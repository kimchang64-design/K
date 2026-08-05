import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(page_title="세력 평단가 차트", layout="wide")

st.title("📈 세력 평단가(VWAP) 분석 대시보드")

# 최근 검색 종목 저장소 초기화 (세션 상태)
if "recent_codes" not in st.session_state:
    st.session_state.recent_codes = []

# 1. 상단 입력 및 설정 옵션
col1, col2 = st.columns([1, 1])
with col1:
    code = st.text_input("종목코드 (6자리)", "005930")
with col2:
    timeframe = st.selectbox(
        "차트 주기 선택",
        [
            "1분봉",
            "3분봉",
            "5분봉",
            "10분봉",
            "15분봉",
            "30분봉",
            "45분봉",
            "60분봉",
            "90분봉",
            "120분봉",
            "240분봉",
            "300분봉",
            "일봉",
            "주봉",
            "월봉",
        ],
        index=12,  # 기본값: 일봉
    )

# 최근 검색 종목 표시
if st.session_state.recent_codes:
    st.write("🔍 **최근 검색 종목:**")
    cols = st.columns(len(st.session_state.recent_codes) + 1)
    for idx, recent_code in enumerate(st.session_state.recent_codes):
        if cols[idx].button(f"📌 {recent_code}", key=f"recent_{recent_code}"):
            code = recent_code

# 2. 날짜 선택
if timeframe in ["일봉", "주봉", "월봉"]:
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("시작일", pd.to_datetime("2024-01-01"))
    with c2:
        end_date = st.date_input("종료일", pd.to_datetime("today"))
else:
    today = datetime.datetime.now()
    start_date = st.date_input("조회일 선택 (분봉)", today)
    end_date = start_date

# 차트 그리기 버튼
if st.button("차트 및 수치 분석 실행", type="primary"):
    # 최근 검색 기록 업데이트 (최대 5개 유지)
    if code not in st.session_state.recent_codes:
        st.session_state.recent_codes.insert(0, code)
        st.session_state.recent_codes = st.session_state.recent_codes[:5]

    s_date = start_date.strftime("%Y%m%d")
    e_date = end_date.strftime("%Y%m%d")

    with st.spinner("데이터를 계산 중입니다..."):
        if timeframe == "일봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "d")
        elif timeframe == "주봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "d")
            if not df.empty:
                df = df.resample("W-MON").agg(
                    {
                        "시가": "first",
                        "고가": "max",
                        "저가": "min",
                        "종가": "last",
                        "거래량": "sum",
                    }
                )
                df = df.dropna()
        elif timeframe == "월봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
        else:
            # 분봉 처리
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
            if not df.empty:
                minutes = timeframe.replace("분봉", "") + "T"
                if minutes != "1T":
                    df = df.resample(minutes).agg(
                        {
                            "시가": "first",
                            "고가": "max",
                            "저가": "min",
                            "종가": "last",
                            "거래량": "sum",
                        }
                    )
                df = df.dropna()

    if df is None or df.empty:
        st.error(
            "선택한 날짜에 거래 데이터가 없습니다. 주말/휴일이거나 장 개장 전인지 확인해주세요."
        )
    else:
        # 세력 평단(VWAP) 및 괴리율 계산
        df["TPV"] = df["종가"] * df["거래량"]
        cum_volume = df["거래량"].cumsum()

        df["세력평단"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
        df["세력평단"] = df["세력평단"].ffill()

        # 최근(마지막) 수치 데이터 추출
        last_close = int(df["종가"].iloc[-1])
        last_vwap = int(df["세력평단"].iloc[-1])
        disparity = ((last_close - last_vwap) / last_vwap) * 100

        # 복사용 텍스트 양식 생성
        copy_text = f"[{code}] 종가: {last_close:,}원 | 세력평단: {last_vwap:,}원 | 괴리율: {disparity:+.2f}%"

        st.subheader(f"📊 {code} 분석 결과 요약")

        # 수치 요약 카드 (3개 컬럼)
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("현재가 / 종가", f"{last_close:,} 원")
        mc2.metric("누적 세력평단", f"{last_vwap:,} 원")
        mc3.metric("괴리율", f"{disparity:+.2f} %")

        # 복사 코드 박스
        st.code(copy_text, language="text")

        # 차트 시각화
        fig = go.Figure()

        # 주가 선 (검은색/분홍색 계열)
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["종가"],
                mode="lines",
                name="종가",
                line=dict(color="#1f77b4", width=1.5),
            )
        )

        # 세력 평단선 (주황색/노란색 계열)
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["세력평단"],
                mode="lines",
                name="누적 세력평단",
                line=dict(color="#ff7f0e", width=3),
            )
        )

        fig.update_layout(
            title=f"{code} - {timeframe} 세력평단 차트",
            xaxis_title="시간/날짜",
            yaxis_title="가격(원)",
            hovermode="x unified",
            template="plotly_white",
            height=500,
        )

        st.plotly_chart(fig, use_container_width=True)
