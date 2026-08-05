import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pykrx import stock

st.title("📈 세력 평단가(VWAP) 차트")

# 1. 설정 옵션 선택
col1, col2 = st.columns(2)
with col1:
    code = st.text_input("종목코드 (6자리)", "005930")
with col2:
    # requested 주기 전체 옵션 (0분봉은 최소 단위인 1분봉으로 대체 적용)
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
    )

# 2. 날짜 선택
if timeframe in ["일봉", "주봉", "월봉"]:
    start_date = st.date_input("시작일", pd.to_datetime("2024-01-01"))
    end_date = st.date_input("종료일", pd.to_datetime("today"))
else:
    today = datetime.datetime.now()
    start_date = st.date_input("조회일 선택 (분봉)", today)
    end_date = start_date

if st.button("차트 그리기"):
    s_date = start_date.strftime("%Y%m%d")
    e_date = end_date.strftime("%Y%m%d")

    with st.spinner("데이터를 불러오는 중입니다..."):
        if timeframe == "일봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "d")
        elif timeframe == "주봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "w")
        elif timeframe == "월봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
        else:
            # 1분봉 데이터 수집
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")

            if not df.empty:
                # 선택한 주기 분 단위 파싱 (예: "90분봉" -> "90T")
                minutes = timeframe.replace("분봉", "") + "T"

                if minutes == "1T":
                    # 1분봉은 리샘플링 없이 그대로 활용
                    pass
                else:
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
        # 세력 평단(VWAP) 계산: 누적(종가 * 거래량) / 누적 거래량
        df["TPV"] = df["종가"] * df["거래량"]
        cum_volume = df["거래량"].cumsum()

        # 거래량이 0인 구간 예외 처리
        df["세력평단"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
        df["세력평단"] = df["세력평단"].ffill()

        # 차트 그리기
        fig = go.Figure()

        # 주가 선 (분홍색)
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["종가"],
                mode="lines",
                name="주가",
                line=dict(color="lightpink", width=1.5),
            )
        )

        # 세력 평단선 (노란색)
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["세력평단"],
                mode="lines",
                name="누적 세력평단",
                line=dict(color="gold", width=3),
            )
        )

        fig.update_layout(
            title=f"{code} - {timeframe} 세력평단 차트",
            xaxis_title="시간/날짜",
            yaxis_title="가격(원)",
            hovermode="x unified",
            template="plotly_white",
        )

        st.plotly_chart(fig, use_container_width=True)
