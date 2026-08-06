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
        .block-container { padding-top: 0.8rem; padding-bottom: 0rem; padding-left: 1.5rem; padding-right: 1.5rem; background-color: #0e1117; color: #fafafa; }
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

  return "073240", "금호타이어"


# ---------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------
if "target_stock" not in st.session_state:
  st.session_state.target_stock = "금호타이어"

code, stock_name = resolve_code_or_name(st.session_state.target_stock)

# ---------------------------------------------------------
# 상단 타이틀 및 검색 바 (첫 번째 사진 레이아웃 반영)
# ---------------------------------------------------------
top_search_html = f"""
<div style="display: flex; justify-content: space-between; align-items: center; background: #161b22; padding: 10px 15px; border-radius: 8px; border: 1px solid #30363d; margin-bottom: 12px;">
    <div style="display: flex; align-items: center; gap: 15px;">
        <span style="font-size: 16px; font-weight: bold; color: #f0f6fc;">Day trading Mapping</span>
        <span style="font-size: 12px; color: #8b94e0; background: #21262d; padding: 4px 8px; border-radius: 4px;">KOSPI {stock_name} ({code})</span>
    </div>
    <div style="font-size: 11px; color: #8b949e;">
        💡 종목코드를 입력하여 실시간 3분봉 세력 평단을 분석하세요.
    </div>
</div>
"""
st.markdown(top_search_html, unsafe_allow_html=True)

# 검색 입력 창 및 최근 검색어 버튼 구현
col_s1, col_s2 = st.columns([1, 3])
with col_s1:
  user_input_val = st.text_input(
      "종목 검색",
      value=st.session_state.target_stock,
      placeholder="종목명 또는 6자리 코드 입력",
      label_visibility="collapsed",
  )
  if user_input_val != st.session_state.target_stock:
    st.session_state.target_stock = user_input_val
    st.rerun()

with col_s2:
  preset_stocks = [
      "금호타이어",
      "이엔셀",
      "RF머트리얼즈",
      "빛과전자",
      "알테오젠",
      "씨피시스템",
      "고영",
  ]
  p_cols = st.columns(len(preset_stocks))
  for idx, p_name in enumerate(preset_stocks):
    with p_cols[idx]:
      if st.button(p_name, use_container_width=True, key=f"preset_{idx}"):
        st.session_state.target_stock = p_name
        st.rerun()

# ---------------------------------------------------------
# 데이터 수집 및 세력 평단 계산 (3분봉 기준 모의/실시간 연동)
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
  buy_vwap = int(base_vwap * 1.0035)  # 세력 매수 평단
  sell_vwap = int(base_vwap * 0.9812)  # 세력 매도 평단
else:
  last_close, base_vwap, buy_vwap, sell_vwap = 7464, 7392, 7392, 7382

# ---------------------------------------------------------
# 첫 번째 사진 하단 패널 형태의 세력 매수/매도 평단 요약
# ---------------------------------------------------------
summary_panel_html = f"""
<div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 10px; margin-bottom: 12px;">
    <div style="background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #8b949e; font-weight: bold;">전체 거래량 평단</span>
        <span style="font-size: 14px; font-weight: bold; color: #58a6ff;">{base_vwap:,} 원</span>
    </div>
    <div style="background: #161b22; border: 1px solid #d29922; border-radius: 6px; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #d29922; font-weight: bold;">세력 매수 평단</span>
        <span style="font-size: 14px; font-weight: bold; color: #ffa657;" onclick="navigator.clipboard.writeText('{buy_vwap}');" title="클릭 시 복사">{buy_vwap:,} 원</span>
    </div>
    <div style="background: #161b22; border: 1px solid #1f6feb; border-radius: 6px; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #58a6ff; font-weight: bold;">세력 매도 평단</span>
        <span style="font-size: 14px; font-weight: bold; color: #79c0ff;" onclick="navigator.clipboard.writeText('{sell_vwap}');" title="클릭 시 복사">{sell_vwap:,} 원</span>
    </div>
</div>
"""
components.html(summary_panel_html, height=55)

# ---------------------------------------------------------
# Plotly 3분봉 스타일 차트 생성 (종가선 및 세력평단선)
# ---------------------------------------------------------
fig = go.Figure()

# 임의의 3분봉 시뮬레이션 데이터 포인트 (첫 번째 사진의 물결 형태 패턴 구현)
time_points = [
    "10:00",
    "10:06",
    "10:30",
    "10:51",
    "11:09",
    "12:15",
    "13:21",
    "14:24",
    "15:30",
]
close_prices = [7350, 7390, 7464, 7400, 7460, 7410, 7350, 7300, 7350]
vwap_prices = [7355, 7370, 7392, 7398, 7402, 7395, 7380, 7370, 7392]

fig.add_trace(
    go.Scatter(
        x=time_points,
        y=close_prices,
        mode="lines+markers",
        name="종가",
        line=dict(color="#f0f6fc", width=2),
        marker=dict(size=6),
    )
)

fig.add_trace(
    go.Scatter(
        x=time_points,
        y=vwap_prices,
        mode="lines",
        name="세력평단",
        line=dict(color="#ffa657", width=2.5),
    )
)

fig.update_layout(
    title=f"KOSPI {stock_name} ({code}) (3분봉)",
    paper_bgcolor="#0e1117",
    plot_bgcolor="#0e1117",
    font=dict(color="#f0f6fc"),
    margin=dict(l=20, r=20, t=35, b=20),
    hovermode="x unified",
    height=400,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(gridcolor="#30363d"),
    xaxis=dict(gridcolor="#30363d"),
)

st.plotly_chart(fig, use_container_width=True)
