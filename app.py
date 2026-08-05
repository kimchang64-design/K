import streamlit as st
import pykrx.stock as stock
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta

st.title("📈 세력 평단가(VWAP) 차트 (일봉 / 3분봉)")

# 1. 설정 옵션 선택
col1, col2 = st.columns(2)
with col1:
    code = st.text_input("종목코드 (6자리)", "005930")
with col2:
    chart_type = st.radio("차트 주기 선택", ["일봉", "3분봉"], horizontal=True)

# 2. 날짜 선택
if chart_type == "일봉":
    start_date = st.date_input("시작일 (바닥)", pd.to_datetime("2024-01-01"))
    end_date = st.date_input("종료일", pd.to_datetime("today"))
else:
    today = datetime.today()
    start_date = st.date_input("조회일 선택 (3분봉)", today)
    end_date = start_date

if st.button("차트 그리기"):
    s_date = start_date.strftime("%Y%m%d")
    e_date = end_date.strftime("%Y%m%d")
    
    with st.spinner("데이터를 불러오는 중입니다..."):
        if chart_type == "일봉":
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code)
        else:
            df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
            if not df.empty:
                df = df.resample('3T').agg({
                    '시가': 'first',
                    '고가': 'max',
                    '저가': 'min',
                    '종가': 'last',
                    '거래량': 'sum'
                }).dropna()

    if df.empty:
        st.error("데이터가 없습니다. 날짜나 종목코드를 확인해주세요.")
    else:
        # 세력 평단(VWAP) 계산: 누적(종가 * 거래량) / 누적 거래량
        df['TPV'] = df['종가'] * df['거래량']
        df['세력평단'] = df['TPV'].cumsum() / df['거래량'].cumsum()

        # 차트 그리기
        fig = go.Figure()
        
        # 주가 선 (분홍색)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['종가'], 
            mode='lines', name='주가', 
            line=dict(color='lightpink', width=1.5)
        ))
        
        # 세력 평단선 (노란색)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['세력평단'], 
            mode='lines', name='누적 세력평단', 
            line=dict(color='gold', width=3)
        ))

        fig.update_layout(
            title=f"{code} - {chart_type} 세력평단 차트",
            xaxis_title="시간/날짜",
            yaxis_title="가격(원)",
            hovermode="x unified",
            template="plotly_white"
        )

        st.plotly_chart(fig, use_container_width=True)