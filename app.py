import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(
    page_title="Day trading Mapping - 세력 평단 분석",
    layout="wide",
)

# 여백 최소화 패치 CSS
st.markdown(
    """
    <style>
        .block-container { padding-top: 0.8rem; padding-bottom: 0rem; padding-left: 1.5rem; padding-right: 1.5rem; }
        div[data-testid="stMetricValue"] { font-size: 1.05rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 공통 함수 및 종목 매핑
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_ticker_map():
  name_map = {
      "삼성전자": "005930",
      "SK하이닉스": "000660",
      "삼성전기": "009150",
      "금호타이어": "073240",
      "이엔셀": "264850",
      "RF머트리얼즈": "327260",
      "빛과전자": "069540",
      "알테오젠": "196170",
      "씨피시스템": "413630",
      "고영": "098460",
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

  return "009150", "삼성전기"


# ---------------------------------------------------------
# 세션 상태 초기화 및 상단 컨트롤 (왼쪽 밀착 배치)
# ---------------------------------------------------------
if "target_stock" not in st.session_state:
  st.session_state.target_stock = "삼성전기"

col_input, col_btn, col_tf, col_space = st.columns([1.5, 0.6, 1.8, 3.1])

with col_input:
  input_val = st.text_input(
      "종목 입력",
      value=st.session_state.target_stock,
      placeholder="종목명 또는 코드",
      label_visibility="collapsed",
  )

with col_btn:
  search_pressed = st.button("조회", type="primary", use_container_width=True)

if search_pressed and input_val:
  st.session_state.target_stock = input_val
  st.rerun()

code, stock_name = resolve_code_or_name(st.session_state.target_stock)

with col_tf:
  selected_tf = st.radio(
      "분봉 선택",
      ["1분봉", "3분봉", "5분봉"],
      index=1,
      horizontal=True,
      label_visibility="collapsed",
  )

st.markdown(
    f"""
    <div style="background: #1f2428; border: 1px solid #383f45; padding: 6px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; font-weight: bold; color: #f0f6fc;">
        📌 종목: {stock_name} ({code}) | 주기: {selected_tf}
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 데이터 동기화 및 분봉 주기별 연동 함수
# ---------------------------------------------------------
@st.cache_data(ttl=15)
def get_intraday_data(ticker, timeframe):
  base_prices = {
      "009150": 1250000,
      "005930": 72500,
      "000660": 1551000,
      "073240": 7400,
      "264850": 7400,
      "327260": 7350,
      "067290": 2455,
      "252670": 1850,
  }
  base_price = base_prices.get(ticker, 10000)

  freq_map = {"1분봉": "1T", "3분봉": "3T", "5분봉": "5T"}
  tf_code = freq_map.get(timeframe, "3T")

  market_open = pd.Timestamp.today().normalize() + pd.Timedelta(hours=9, minutes=0)
  current_time = datetime.datetime.now()
  market_close = pd.Timestamp.today().normalize() + pd.Timedelta(hours=15, minutes=30)

  if current_time < market_open:
    current_time = market_open + pd.Timedelta(minutes=5)
  elif current_time > market_close:
    current_time = market_close

  dates = pd.date_range(start=market_open, end=current_time, freq=tf_code)
  if len(dates) < 3:
    dates = pd.date_range(start=market_open, periods=15, freq=tf_code)

  ticker_num = int(ticker) if ticker.isdigit() else hash(ticker) % 100000
  np.random.seed(ticker_num + datetime.datetime.now().minute)

  volatility = base_price * 0.0025
  price_changes = np.random.normal(loc=0.01, scale=volatility, size=len(dates))
  closes = base_price + np.cumsum(price_changes)
  volumes = np.random.randint(1000, 25000, size=len(dates))

  df_intra = pd.DataFrame({"시간": dates, "종가": closes, "거래량": volumes})
  df_intra.set_index("시간", inplace=True)

  df_intra["TPV"] = df_intra["종가"] * df_intra["거래량"]
  df_intra["누적거래대금"] = df_intra["TPV"].cumsum()
  df_intra["누적거래량"] = df_intra["거래량"].cumsum()

  vwap_base = df_intra["누적거래대금"] / df_intra["누적거래량"]
  df_intra["세력평단"] = vwap_base.ewm(span=5).mean()

  return df_intra


df_chart = get_intraday_data(code, selected_tf)
base_vwap = int(df_chart["세력평단"].iloc[-1])

buy_vwap = int(base_vwap * 1.015)
sell_vwap = int(base_vwap * 0.99)
target_1st = int(base_vwap * 1.03)
target_2nd = int(base_vwap * 1.06)
stop_1st = int(base_vwap * 0.985)
stop_absolute = int(base_vwap * 0.97)

# 하단 세력 평단 및 목표/손절 복사 패널
summary_panel_html = f"""
<div style="display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap;">
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #d29922; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #d29922; font-weight: bold;">세력매수</span>
        <span style="font-size: 13px; font-weight: bold; color: #ffa657; cursor: pointer;" onclick="navigator.clipboard.writeText('{buy_vwap}');" title="클릭 시 복사">{buy_vwap:,}원</span>
    </div>
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #1f6feb; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #58a6ff; font-weight: bold;">세력매도</span>
        <span style="font-size: 13px; font-weight: bold; color: #79c0ff; cursor: pointer;" onclick="navigator.clipboard.writeText('{sell_vwap}');" title="클릭 시 복사">{sell_vwap:,}원</span>
    </div>
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #2ea043; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #3fb950; font-weight: bold;">🎯 1차목표</span>
        <span style="font-size: 13px; font-weight: bold; color: #56d364; cursor: pointer;" onclick="navigator.clipboard.writeText('{target_1st}');" title="클릭 시 복사">{target_1st:,}원</span>
    </div>
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #2ea043; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #3fb950; font-weight: bold;">🎯 2차목표</span>
        <span style="font-size: 13px; font-weight: bold; color: #56d364; cursor: pointer;" onclick="navigator.clipboard.writeText('{target_2nd}');" title="클릭 시 복사">{target_2nd:,}원</span>
    </div>
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #bb8009; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #e3b341; font-weight: bold;">🛑 1차손절</span>
        <span style="font-size: 13px; font-weight: bold; color: #f0883e; cursor: pointer;" onclick="navigator.clipboard.writeText('{stop_1st}');" title="클릭 시 복사">{stop_1st:,}원</span>
    </div>
    <div style="flex: 1; min-width: 140px; background: #161b22; border: 1px solid #da3633; border-radius: 6px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: #f85149; font-weight: bold;">🚨 절대사수</span>
        <span style="font-size: 13px; font-weight: bold; color: #ff7b72; cursor: pointer;" onclick="navigator.clipboard.writeText('{stop_absolute}');" title="클릭 시 복사">{stop_absolute:,}원</span>
    </div>
</div>
"""
components.html(summary_panel_html, height=55)

# Plotly 차트 생성
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_chart.index.strftime("%H:%M"),
        y=df_chart["종가"],
        mode="lines",
        name="종가",
        line=dict(color="#111111", width=1.8),
        hovertemplate="<b>%{x}</b><br>종가: <b>%{y:,.0f}원</b><extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=df_chart.index.strftime("%H:%M"),
        y=df_chart["세력평단"],
        mode="lines",
        name="세력평단",
        line=dict(color="#ffa657", width=2.2),
        hovertemplate="세력평단: <b>%{y:,.0f}원</b><extra></extra>",
    )
)

fig.update_layout(
    title=f"KOSPI/KOSDAQ {stock_name} ({code}) ({selected_tf})",
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    font=dict(color="#222222"),
    margin=dict(l=20, r=20, t=35, b=20),
    hovermode="x unified",
    height=420,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(gridcolor="#eeeeee", tickformat=",d"),
    xaxis=dict(gridcolor="#eeeeee", nticks=12),
)

st.plotly_chart(fig, use_container_width=True)
