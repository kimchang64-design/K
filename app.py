# -*- coding: utf-8 -*-
"""
Day Trading Mapping - 당일 분봉 + 세력평단 대시보드
- 3분봉에서 시작연도/종료연도 무시, 당일(09:00~현재) 분봉만 사용
- multi-byte encoding 오류 방지 (requests 인코딩 명시)
- 네이버 분봉 API 실패 시 자동 재시도 + 대체(1분봉 -> N분 리샘플링)
- 세력평단(VWAP 누적 거래량가중평균가) 실시간 계산
- Streamlit + Plotly 다크테마, 스크린샷과 유사한 레이아웃
"""

import time
import json
import requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, time as dtime

# ----------------------------------------------------------------------
# 기본 설정
# ----------------------------------------------------------------------
st.set_page_config(page_title="Day trading Mapping", layout="wide")

DARK_BG = "#0e1117"
CARD_BG = "#161a23"
ORANGE = "#f5a623"
LINE_BLACK = "#1c1c1c"

st.markdown(f"""
<style>
.stApp {{ background-color:{DARK_BG}; color:white; }}
div[data-testid="stMetric"] {{
    background-color:{CARD_BG};
    padding:14px; border-radius:10px;
}}
</style>
""", unsafe_allow_html=True)

MARKET_OPEN = dtime(9, 0, 0)
MARKET_CLOSE = dtime(15, 30, 0)

# ----------------------------------------------------------------------
# 1. 네이버 분봉 데이터 수집 (재시도 + 인코딩 안전 처리)
# ----------------------------------------------------------------------
NAVER_MINUTE_URL = "https://api.finance.naver.com/siseJson.naver"
# 위 엔드포인트가 막힐 경우를 대비한 대체 엔드포인트(모바일 API)
NAVER_MINUTE_URL_ALT = "https://m.stock.naver.com/api/stock/{code}/minute"

def _safe_request(url, params=None, headers=None, retries=3, timeout=5):
    """multi-byte 인코딩 오류 방지 + 자동 재시도"""
    headers = headers or {"User-Agent": "Mozilla/5.0"}
    for attempt in range(retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=timeout)
            res.encoding = "utf-8"  # multi-byte encodings 오류 방지
            if res.status_code == 200:
                return res
        except requests.exceptions.RequestException:
            time.sleep(0.6 * (attempt + 1))
    return None


@st.cache_data(ttl=15, show_spinner=False)
def fetch_today_minute_data(code: str, interval_min: int = 3) -> pd.DataFrame:
    """
    당일(09:00~현재) 분봉만 반환.
    1) 네이버 모바일 API(1분봉)로 원본 수집
    2) 실패 시 재시도
    3) interval_min 단위로 리샘플링 (OHLC + 거래량)
    """
    url = NAVER_MINUTE_URL_ALT.format(code=code)
    params = {"page": 1, "pageSize": 500}
    res = _safe_request(url, params=params)

    if res is None:
        return pd.DataFrame()

    try:
        data = res.json()
        minutes = data.get("minutes") or data.get("minuteList") or []
    except (json.JSONDecodeError, AttributeError):
        return pd.DataFrame()

    if not minutes:
        return pd.DataFrame()

    df = pd.DataFrame(minutes)
    # 네이버 응답 필드명은 버전에 따라 다를 수 있어 방어적으로 매핑
    rename_map = {
        "bizdate": "date", "time": "time", "hhmm": "time",
        "tradeTime": "time", "closePrice": "close", "close": "close",
        "openPrice": "open", "open": "open",
        "highPrice": "high", "high": "high",
        "lowPrice": "low", "low": "low",
        "accVolume": "volume", "volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 시간 컬럼 정규화
    if "time" in df.columns:
        today = datetime.now().strftime("%Y-%m-%d")
        df["datetime"] = pd.to_datetime(
            today + " " + df["time"].astype(str).str.zfill(4).str[:2] + ":" +
            df["time"].astype(str).str.zfill(4).str[2:], errors="coerce"
        )
    else:
        return pd.DataFrame()

    df = df.dropna(subset=["datetime", "close"]).sort_values("datetime")

    # 당일(09:00 ~ 현재)만 필터 — 시작/종료 연도는 완전 무시하고 "오늘"만 본다
    today_date = datetime.now().date()
    df = df[df["datetime"].dt.date == today_date]
    df = df[(df["datetime"].dt.time >= MARKET_OPEN)]

    if df.empty:
        return pd.DataFrame()

    # N분봉으로 리샘플링
    df = df.set_index("datetime")
    ohlc = df["close"].resample(f"{interval_min}T").ohlc()
    vol = df["volume"].resample(f"{interval_min}T").sum()
    result = ohlc.join(vol).dropna(subset=["close"]).reset_index()
    return result


# ----------------------------------------------------------------------
# 2. 세력평단(VWAP 누적 거래량가중평균가) 계산
# ----------------------------------------------------------------------
def calc_seryeok_average(df: pd.DataFrame) -> pd.DataFrame:
    """
    세력평단 = 당일 09:00부터 현재 봉까지 누적 (종가 * 거래량) / 누적 거래량
    거래량이 0/NaN인 구간은 직전 값으로 보정
    """
    if df.empty:
        return df

    df = df.copy()
    df["volume"] = df["volume"].fillna(0)
    df["vol_price"] = df["close"] * df["volume"]

    cum_vol = df["volume"].cumsum()
    cum_vp = df["vol_price"].cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        seryeok = cum_vp / cum_vol

    # 거래량이 전혀 없던 초기 구간은 단순 종가 누적평균으로 대체
    fallback = df["close"].expanding().mean()
    df["seryeok_avg"] = seryeok.where(cum_vol > 0, fallback)
    df["seryeok_avg"] = df["seryeok_avg"].round(0)
    return df


# ----------------------------------------------------------------------
# 3. 차트 렌더링 (스크린샷 스타일: 검은 종가선 + 주황 세력평단선)
# ----------------------------------------------------------------------
def render_chart(df: pd.DataFrame, name: str, code: str, interval_min: int):
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["close"],
        mode="lines+markers",
        name="종가",
        line=dict(color=LINE_BLACK, width=1.5),
        marker=dict(size=3, color=LINE_BLACK),
        hovertemplate="%{x|%H:%M}<br>종가: %{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["seryeok_avg"],
        mode="lines",
        name="세력평단",
        line=dict(color=ORANGE, width=3),
        hovertemplate="%{x|%H:%M}<br>세력평단: %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title=f"{name} ({code}) ({interval_min}분봉)",
        plot_bgcolor="white",
        paper_bgcolor=CARD_BG,
        font=dict(color="white"),
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        margin=dict(l=40, r=20, t=60, b=40),
        hovermode="x unified",
        xaxis=dict(
            tickformat="%H:%M",
            showgrid=False,
            range=[
                datetime.combine(datetime.now().date(), MARKET_OPEN),
                datetime.combine(datetime.now().date(), MARKET_CLOSE),
            ],
        ),
        yaxis=dict(showgrid=True, gridcolor="#e5e5e5"),
        height=560,
    )
    st.plotly_chart(fig, use_container_width=True)


# ----------------------------------------------------------------------
# 4. 화면 구성 (사이드 검색창 + 카드 UI)
# ----------------------------------------------------------------------
st.markdown("## Day trading Mapping")

col_a, col_b, col_c = st.columns([3, 1, 2])
with col_a:
    query = st.text_input("종목명 또는 6자리 코드 입력", value="005930")
with col_b:
    st.write("")
    st.write("")
    search_clicked = st.button("⚡ 조회", use_container_width=True)
with col_c:
    interval = st.radio("분봉", ["1분봉", "3분봉", "5분봉"], index=1, horizontal=True)

interval_min = {"1분봉": 1, "3분봉": 3, "5분봉": 5}[interval]

# 종목명이 아니라 코드만 지원하는 경량 버전 (종목명->코드 매핑은 별도 DB/검색 API 필요)
code = query.strip()

if search_clicked or code:
    with st.spinner("당일 분봉 데이터를 불러오는 중..."):
        df = fetch_today_minute_data(code, interval_min=interval_min)

    if df.empty:
        st.warning("당일 분봉 데이터를 아직 받아오지 못했습니다. 장 시작 전이거나 일시적 오류일 수 있습니다. 잠시 후 새로고침 해주세요.")
    else:
        df = calc_seryeok_average(df)
        render_chart(df, name=code, code=code, interval_min=interval_min)

        last = df.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("현재가", f"{last['close']:,.0f} 원")
        c2.metric("세력평단(매수 기준)", f"{last['seryeok_avg']:,.0f} 원")
        diff = last["close"] - last["seryeok_avg"]
        c3.metric("평단 대비", f"{diff:+,.0f} 원", delta=f"{diff/last['seryeok_avg']*100:+.2f}%")

        st.caption(
            "※ 세력평단은 KRX/증권사가 제공하는 공식 지표가 아니라, "
            "당일 09:00~현재까지 (종가×거래량)의 누적 가중평균(VWAP)으로 자체 계산한 값입니다. "
            "실시간성은 사용하는 데이터 소스(네이버 분봉 API / 증권사 Open API)에 따라 달라집니다."
        )
