import datetime
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
# 세션 상태 초기화
# ---------------------------------------------------------
if "target_stock" not in st.session_state:
  st.session_state.target_stock = "삼성전기"

# 상단 입력 및 조회 레이아웃
col_input, col_btn, col_tf = st.columns([2, 1, 3])

with col_input:
  input_val = st.text_input(
      "종목 입력",
      value=st.session_state.target_stock,
      placeholder="종목명 또는 6자리 코드 입력",
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

# 현재 선택된 종목 표시 뱃지
st.markdown(
    f"""
    <div style="background: #1f2428; border: 1px solid #383f45; padding: 8px 12px; border-radius: 6px; margin-bottom: 10px; font-size: 13px; font-weight: bold; color: #f0f6fc;">
        📌 종목: {stock_name} ({code}) | 주기: {selected_tf}
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# 데이터 계산 및 시각화
# ---------------------------------------------------------
s_date_dummy = "20260101"
e_date_dummy = datetime.datetime.now().strftime("%Y%m%d")
df_temp = stock.get_market_ohlcv_by_date(s_date_dummy, e_date_dummy, code, "d")

if df_temp is not None and not df_temp.empty:
  df_temp["TPV"] = df_temp["종가"] * df_temp["거래량"]
  cum_v_tmp = df_temp["거래량"].cumsum()
  vwap_tmp = df_temp["TPV"].cumsum() / cum_v_tmp.replace(0, pd.NA)
  vwap_tmp = vwap_tmp.ffill()

  last_close = int(df_temp["종가"].iloc[-1])
  base_vwap = int(vwap_tmp.iloc[-1])
  buy_vwap = int(base_vwap * 1.0035)
  sell_vwap = int(base_vwap * 0.9812)
else:
  last_close, base_vwap, buy_vwap, sell_vwap = 1285000, 1270000, 1284433, 1252798

# 하단 세력 평단 패널
summary_panel_html = f"""
<div style="display: flex; gap: 10px; margin-bottom: 10px;">
    <div style="flex: 1; background: #161b22; border: 1px solid #d29922; border-radius: 6px; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #d29922; font-weight: bold;">세력 매수 평단</span>
        <span style="font-size: 15px; font-weight: bold; color: #ffa657; cursor: pointer;" onclick="navigator.clipboard.writeText('{buy_vwap}');" title="클릭 시 복사">{buy_vwap:,} 원</span>
    </div>
    <div style="flex: 1; background: #161b22; border: 1px solid #1f6feb; border-radius: 6px; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #58a6ff; font-weight: bold;">세력 매도 평단</span>
        <span style="font-size: 15px; font-weight: bold; color: #79c0ff; cursor: pointer;" onclick="navigator.clipboard.writeText('{sell_vwap}');" title="클릭 시 복사">{sell_vwap:,} 원</span>
    </div>
</div>
"""
components.html(summary_panel_html, height=55)

# Plotly 차트 생성
fig = go.Figure()
time_points = [
    "09:00",
    "09:39",
    "10:18",
    "10:57",
    "11:36",
    "12:15",
    "12:54",
    "13:33",
    "14:12",
    "14:51",
    "15:30",
]
close_prices = [
    1240000,
    1260000,
    1280000,
    1300000,
    1275000,
    1260000,
    1245000,
    1230000,
    1240000,
    1265000,
    1275000,
]
vwap_prices = [
    1238000,
    1250000,
    1260000,
    1270000,
    1272000,
    1268000,
    1265000,
    1262000,
    1260000,
    1262000,
    1264000,
]

fig.add_trace(
    go.Scatter(
        x=time_points,
        y=close_prices,
        mode="lines",
        name="종가",
        line=dict(color="#f0f6fc", width=1.8),
    )
)
fig.add_trace(
    go.Scatter(
        x=time_points,
        y=vwap_prices,
        mode="lines",
        name="세력평단",
        line=dict(color="#ffa657", width=2.2),
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
    yaxis=dict(gridcolor="#eeeeee"),
    xaxis=dict(gridcolor="#eeeeee"),
)

st.plotly_chart(fig, use_container_width=True)
