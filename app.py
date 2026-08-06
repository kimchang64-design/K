import datetime
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(
    page_title="주식 분석 포털 - 평단선 & 주도주/거래대금/시간외",
    layout="wide",
)

# 여백 최소화 패치 CSS
st.markdown(
    """
    <style>
        .block-container { padding-top: 0.8rem; padding-bottom: 0rem; padding-left: 2rem; padding-right: 2rem; }
        div[data-testid="stMetricValue"] { font-size: 1.05rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)

# 상단 티커 바
ticker_bar_html = """
<div style="display: flex; gap: 10px; margin-bottom: 15px; overflow-x: auto; padding-bottom: 5px;">
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 150px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">🇰🇷 국내 지수</div>
        <div style="font-size: 12px; font-weight: bold; color: #d32f2f;">2,755.20 (+0.85%) <span style="color:#333; font-weight:normal;">(코스피)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 150px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">🇰🇷 코스닥 지수</div>
        <div style="font-size: 12px; font-weight: bold; color: #d32f2f;">872.40 (+1.12%) <span style="color:#333; font-weight:normal;">(코스닥)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 160px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">📈 파생 시장</div>
        <div style="font-size: 12px; font-weight: bold; color: #d32f2f;">362.85 (+0.92%) <span style="color:#333; font-weight:normal;">(선물지수)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 150px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">⚡ 베이시스 상태</div>
        <div style="font-size: 12px; font-weight: bold; color: #1971c2;">+0.65 (콘탱고) <span style="color:#333; font-weight:normal;">(시장 베이시스)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 160px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">🇺🇸 미국 증시</div>
        <div style="font-size: 12px; font-weight: bold; color: #d32f2f;">17,928.30 (+1.45%) <span style="color:#333; font-weight:normal;">(나스닥)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 150px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">💱 외환 시장</div>
        <div style="font-size: 12px; font-weight: bold; color: #1971c2;">1,372.50원 (-3.2원) <span style="color:#333; font-weight:normal;">(원/달러 환율)</span></div>
    </div>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 8px 12px; min-width: 180px; text-align: center;">
        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">📊 프로그램 수급</div>
        <div style="font-size: 11px; font-weight: bold; color: #d32f2f;">+2,150억 (차익+800) <span style="color:#333; font-weight:normal;">(프로그램 순매매)</span></div>
    </div>
</div>
"""
st.markdown(ticker_bar_html, unsafe_allow_html=True)

# 4개의 상단 메인 탭 구성
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(
    ["📈 평단선 차트", "⭐ 업종·테마 분석", "🔥 거래대금 TOP 30", "🌙 시간외 톱 30"]
)


# ---------------------------------------------------------
# 공통 함수
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_ticker_map():
    name_map = {
        "삼성전자": "005930",
        "SK하이닉스": "000660",
        "금호타이어": "073240",
        "대한전선": "001440",
        "대한광통신": "010170",
    }
    try:
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(today_str, market="ALL")
        for t in tickers:
            name = stock.get_market_ticker_name(t)
            if name and isinstance(name, str):
                name_map[name.strip()] = t
    except Exception:
        pass
    return name_map


def resolve_code_or_name(user_input):
    user_input = str(user_input).strip()
    name_map = get_stock_ticker_map()
    code_to_name = {v: k for k, v in name_map.items()}

    if user_input.isdigit() and len(user_input) == 6:
        if user_input in code_to_name:
            return user_input, code_to_name[user_input]
        try:
            name = stock.get_market_ticker_name(user_input)
            name_str = str(name).strip() if name else user_input
            return user_input, name_str
        except Exception:
            return user_input, user_input

    if user_input in name_map:
        return name_map[user_input], user_input

    for name, code in name_map.items():
        if user_input.lower() in name.lower():
            return code, name

    return "073240", "금호타이어"


# ---------------------------------------------------------
# TAB 1: 평단선 차트 (Day trading Mapping 스타일 적용)
# ---------------------------------------------------------
with main_tab1:
    if "search_history" not in st.session_state:
        st.session_state.search_history = ["금호타이어 (073240)", "삼성전자", "SK하이닉스"]
    if "target_stock" not in st.session_state:
        st.session_state.target_stock = "금호타이어"

    col_left, col_right = st.columns([1, 2.5])

    with col_left:
        def on_input_change():
            st.session_state.target_stock = st.session_state.stock_input_field

        def set_recent_stock(val):
            st.session_state.target_stock = val
            st.session_state.stock_input_field = val

        sc1, sc2 = st.columns([4, 1])
        with sc1:
            input_val = st.text_input(
                "종목 입력",
                value=st.session_state.target_stock,
                key="stock_input_field",
                on_change=on_input_change,
                placeholder="종목명 또는 코드",
                label_visibility="collapsed",
            )
        with sc2:
            search_clicked = st.button("조회", use_container_width=True, type="primary")

        if search_clicked and input_val:
            st.session_state.target_stock = input_val

        code, stock_name = resolve_code_or_name(st.session_state.target_stock)

        st.markdown(
            f"""
            <div style="display: flex; align-items: center; justify-content: space-between; background: #111b27; padding: 6px 10px; border: 1px solid #1f2c3a; border-radius: 6px; margin-bottom: 8px;">
                <span style="font-size: 13px; font-weight: bold; color: #fff;">📌 종목: {stock_name} ({code})</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_right:
        # 분봉 선택 버튼 라인 (1분봉, 3분봉, 5분봉)
        bc1, bc2, bc3, bc4 = st.columns([1, 1, 1, 3])
        with bc1:
            if st.button("1분봉", use_container_width=True):
                st.session_state.tf = "1T"
        with bc2:
            if st.button("3분봉", use_container_width=True, type="primary"):
                st.session_state.tf = "3T"
        with bc3:
            if st.button("5분봉", use_container_width=True):
                st.session_state.tf = "5T"

    current_tf = st.session_state.get("tf", "3T")

    # 당일 장중 3분봉 가상/실시간 데이터 생성 (Open Book Pro 스타일 시뮬레이션)
    @st.cache_data(ttl=30)
    def get_intraday_data(ticker, timeframe):
        dates = pd.date_range(
            start=pd.Timestamp.today().normalize() + pd.Timedelta(hours=9, minutes=0),
            end=pd.Timestamp.today().normalize() + pd.Timedelta(hours=15, minutes=30),
            freq=timeframe,
        )
        np.random.seed(int(ticker) if ticker.isdigit() else 42)
        base_price = 7350
        price_changes = np.random.normal(loc=0.1, scale=22, size=len(dates))
        closes = base_price + np.cumsum(price_changes)
        volumes = np.random.randint(2000, 45000, size=len(dates))

        df_intra = pd.DataFrame({"시간": dates, "종가": closes, "거래량": volumes})
        df_intra.set_index("시간", inplace=True)

        # 세력평단 (VWAP 및 가중치 반영 곡선)
        df_intra["TPV"] = df_intra["종가"] * df_intra["거래량"]
        df_intra["누적거래대금"] = df_intra["TPV"].cumsum()
        df_intra["누적거래량"] = df_intra["거래량"].cumsum()
        df_intra["세력평단"] = (df_intra["누적거래대금"] / df_intra["누적거래량"]).ffill() * 0.992

        return df_intra

    df_chart = get_intraday_data(code, current_tf)
    last_close = int(df_chart["종가"].iloc[-1])
    last_vwap = int(df_chart["세력평단"].iloc[-1])
    buy_vwap_val = last_vwap + 185
    sell_vwap_val = last_vwap - 30

    # Plotly 차트 생성 (검은색 종가 실선 + 오렌지색 세력평단 곡선)
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_chart.index.strftime("%H:%M"),
            y=df_chart["종가"],
            mode="lines",
            name="종가",
            line=dict(color="#111111", width=1.6),
            hovertemplate="<b>%{x}</b><br>종가: <b>%{y:,.0f}원</b><extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df_chart.index.strftime("%H:%M"),
            y=df_chart["세력평단"],
            mode="lines",
            name="세력평단",
            line=dict(color="#f59f00", width=2.4),
            hovertemplate="세력평단: <b>%{y:,.0f}원</b><extra></extra>",
        )
    )

    tf_label = "3분봉" if current_tf == "3T" else ("1분봉" if current_tf == "1T" else "5분봉")
    fig.update_layout(
        title=f"KOSPI {stock_name} ({code}) ({tf_label})",
        margin=dict(l=20, r=20, t=35, b=20),
        hovermode="x unified",
        template="plotly_white",
        height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title=""),
    )
    fig.update_xaxes(nticks=10, tickangle=0)

    st.plotly_chart(fig, use_container_width=True)

    # 하단 세력 매수/매도 평단 복사 패널 (첨부 이미지 하단 디자인 완벽 재현)
    bottom_panel_html = f"""
    <div style="display: flex; gap: 15px; background: #111b27; padding: 12px 15px; border-radius: 8px; border: 1px solid #1f2c3a; align-items: center; justify-content: flex-end;">
        <div style="display: flex; align-items: center; gap: 10px; background: #182232; padding: 8px 14px; border-radius: 6px; border: 1px solid #2a3b4c;">
            <span style="color: #f59f00; font-size: 12px; font-weight: bold;">세력 매수 평단</span>
            <span style="color: #ffffff; font-size: 14px; font-weight: bold;">{buy_vwap_val:,} 원</span>
            <button onclick="navigator.clipboard.writeText('{buy_vwap_val}');" style="background: #2a3b4c; color: #fff; border: none; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px;">복사</button>
        </div>
        <div style="display: flex; align-items: center; gap: 10px; background: #182232; padding: 8px 14px; border-radius: 6px; border: 1px solid #2a3b4c;">
            <span style="color: #4dabf7; font-size: 12px; font-weight: bold;">세력 매도 평단</span>
            <span style="color: #ffffff; font-size: 14px; font-weight: bold;">{sell_vwap_val:,} 원</span>
            <button onclick="navigator.clipboard.writeText('{sell_vwap_val}');" style="background: #2a3b4c; color: #fff; border: none; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px;">복사</button>
        </div>
    </div>
    """
    components.html(bottom_panel_html, height=65)

# 나머지 탭(업종·테마, 거래대금 TOP 30, 시간외)은 기존 골격 유지
with main_tab2:
    st.markdown("### ⭐ 업종·테마 분석 대시보드")
    st.caption("선택한 테마 및 주도주 흐름 분석")

with main_tab3:
    st.title("🔥 전체 거래대금 TOP 30 대시보드")

with main_tab4:
    st.title("🌙 시간외 단일가 거래 TOP 30 대시보드")
