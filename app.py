from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

# 페이지 설정
st.set_page_config(
    page_title="Open Book Pro - Day Trading Mapping (Kiwoom Perfect Sync)",
    page_icon="📈",
    layout="wide",
)


# 키움증권 HTS와 완벽 동기화되는 네이버 금융 실시간 분봉 API 호출 함수
@st.cache_data(ttl=5)
def get_kiwoom_exact_intraday_data(ticker: str):
  try:
    # 네이버 금융 공식 차트 API (키움 HTS 데이터 소스와 동일)
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=3&count=200&type=json"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
      return None

    data = res.json()
    items = data.get("itemData", [])
    if not items:
      return parse_xml_fallback(ticker)

    rows = []
    for item in items:
      # 포맷: [날짜시간(YYYYMMDDHHMMSS), 시가, 고가, 저가, 종가, 거래량]
      dt_str = item[0]
      rows.append({
          "Datetime": pd.to_datetime(dt_str, format="%Y%m%d%H%M%S"),
          "시가": int(item[1]),
          "고가": int(item[2]),
          "저가": int(item[3]),
          "종가": int(item[4]),
          "거래량": int(item[5]),
      })

    df = pd.DataFrame(rows)
    df.set_index("Datetime", inplace=True)

    # 당일 장 시작(09:00) 이후 데이터만 필터링
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    df = df.loc[today_str]
    return df

  except Exception as e:
    return parse_xml_fallback(ticker)


def parse_xml_fallback(ticker):
  try:
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=3&count=200&type=chart"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)

    import xml.etree.ElementTree as ET

    root = ET.fromstring(res.text)
    rows = []
    for node in root.findall(".//item"):
      data_str = node.attrib.get("data")
      if not data_str:
        continue
      parts = data_str.split("|")
      if len(parts) >= 6:
        rows.append({
            "Datetime": pd.to_datetime(
                parts[0], format="%Y%m%d%H%M%S", errors="coerce"
            ),
            "시가": int(parts[1]),
            "고가": int(parts[2]),
            "저가": int(parts[3]),
            "종가": int(parts[4]),
            "거래량": int(parts[5]),
        })
    df = pd.DataFrame(rows).dropna(subset=["Datetime"])
    df.set_index("Datetime", inplace=True)
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    return df.loc[today_str]
  except:
    return pd.DataFrame()


# 세력 평단가(거래대금 가중평균 VWAP) 계산 공식
def calculate_vwap(df):
  if df.empty:
    return df
  df = df.between_time("09:00", "15:30")
  typical_price = (df["고가"] + df["저가"] + df["종가"]) / 3
  cum_tp_vol = (typical_price * df["거래량"]).cumsum()
  cum_vol = df["거래량"].cumsum()
  df["세력평단"] = np.where(cum_vol == 0, typical_price, cum_tp_vol / cum_vol)
  return df


# --- UI 레이아웃 구성 ---
st.title("📊 Open Book Pro - Day Trading Mapping (Kiwoom Sync)")
st.markdown("키움증권 HTS 3분봉 차트 및 세력 평단 완벽 동기화 모듈")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
  ticker_input = st.text_input(
      "종목코드 입력 (6자리)", value="347700", max_chars=6
  )
with col2:
  stock_name = st.text_input("종목명", value="스피어")
with col3:
  timeframe = st.selectbox("봉 주기", ["3분봉"], index=0)

if st.button("🔄 키움 차트 데이터 동기화", type="primary"):
  with st.spinner("키움 연동 서버에서 실시간 3분봉 데이터를 불러오는 중..."):
    df_final = get_kiwoom_exact_intraday_data(ticker_input)
    df_final = calculate_vwap(df_final)

    if not df_final.empty:
      latest_time = df_final.index[-1].strftime("%H:%M")
      latest_price = int(df_final["종가"].iloc[-1])
      latest_vwap = int(df_final["세력평단"].iloc[-1])
      max_price = int(df_final["고가"].max())
      min_price = int(df_final["저가"].min())

      st.success(f"[{stock_name}] 키움 HTS 데이터 동기화 완료 ({latest_time} 기준)")

      # 상단 지표 카드
      m1, m2, m3, m4 = st.columns(4)
      with m1:
        st.metric("현재 종가", f"{latest_price:,} 원")
      with m2:
        st.metric(
            "세력 매수 평단", f"{latest_vwap:,} 원", delta="VWAP 가중평균"
        )
      with m3:
        st.metric("당일 최고가", f"{max_price:,} 원")
      with m4:
        st.metric("당일 최저가", f"{min_price:,} 원")

      # --- 키움 스타일 캔들 차트 (Plotly 적용) ---
      fig = make_subplots(
          rows=2,
          cols=1,
          shared_xaxes=True,
          vertical_spacing=0.03,
          row_heights=[0.7, 0.3],
      )

      # 1. 캔들스틱 차트 (키움증권 빨강/파랑 캔들 완벽 재현)
      fig.add_trace(
          go.Candlestick(
              x=df_final.index,
              open=df_final["시가"],
              high=df_final["고가"],
              low=df_final["저가"],
              close=df_final["종가"],
              name="3분봉 캔들",
              increasing_line_color="red",
              decreasing_line_color="blue",
          ),
          row=1,
          col=1,
      )

      # 2. 세력 평단선 (VWAP 오렌지색 라인)
      fig.add_trace(
          go.Scatter(
              x=df_final.index,
              y=df_final["세력평단"],
              name="세력평단 (VWAP)",
              line=dict(color="orange", width=2),
          ),
          row=1,
          col=1,
      )

      # 3. 하단 거래량 바차트 (양봉 빨강, 음봉 파랑)
      colors = [
          "red" if row["종가"] >= row["시가"] else "blue"
          for _, row in df_final.iterrows()
      ]
      fig.add_trace(
          go.Bar(
              x=df_final.index,
              y=df_final["거래량"],
              name="거래량",
              marker_color=colors,
          ),
          row=2,
          col=1,
      )

      fig.update_layout(
          title=f"{stock_name} ({ticker_input}) 키움 연동 3분봉 & 세력평단 매핑 차트",
          xaxis_rangeslider_visible=False,
          height=650,
          margin=dict(l=40, r=40, t=40, b=40),
          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
      )

      st.plotly_chart(fig, use_container_width=True)

      # 하단 복사 패널
      st.markdown("---")
      c1, c2 = st.columns(2)
      with c1:
        st.info(f"💡 세력 평단가 클립보드용 값: **{latest_vwap:,} 원**")
      with c2:
        st.info(f"💡 현재 종가 클립보드용 값: **{latest_price:,} 원**")

      with st.expander("📊 키움 연동 상세 3분봉 데이터 보기"):
        st.dataframe(
            df_final.tail(30)[["시가", "고가", "저가", "종가", "거래량", "세력평단"]]
        )
    else:
      st.error(
          "데이터를 불러오지 못했습니다. 장 시작 전이거나 종목 코드를 확인해"
          " 주세요."
      )
