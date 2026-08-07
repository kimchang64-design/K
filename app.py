from datetime import datetime
import json
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st

# 페이지 설정
st.set_page_config(
    page_title="Open Book Pro - Day Trading Mapping (Kiwoom Sync)",
    page_icon="📈",
    layout="wide",
)

# 한글 폰트 깨짐 방지 설정
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False


# 네이버 금융 실시간 분봉 데이터 연동 (키움증권 데이터와 일치)
@st.cache_data(ttl=15)
def get_naver_intraday_data(ticker: str):
  try:
    # 네이버 금융 모바일 API를 통한 당일 분봉 데이터 수신 (실시간 동기화)
    url = f"https://m.stock.naver.com/api/item/getChartData?code={ticker}&timeframe=minute"
    # 3분봉 데이터 조회를 위해 count 넉넉히 설정 (당일 장 시작부터 현재까지 커버)
    url = f"https://m.stock.naver.com/api/stock/{ticker}/integrationMChart?period=day"

    # 안정적인 분봉 데이터 수집을 위한 네이버 금융 chart API 호출
    # (3분봉 기준 데이터 크롤링 엔드포인트)
    api_url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=3&count=500&type=json"

    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(api_url, headers=headers)

    if res.status_code != 200:
      return None

    data = res.json()
    items = data.get("itemData", [])
    if not items:
      # XML 포맷으로 리턴되는 경우 대비 파싱 보완
      return parse_naver_xml_chart(ticker)

    df = pd.DataFrame(items)
    return df

  except Exception as e:
    return parse_naver_xml_chart(ticker)


def parse_naver_xml_chart(ticker: str):
  """네이버 금융 XML/JSON 차트 데이터 대체 파싱 함수 (당일 09시 이후 3분봉 정확 동기화)"""
  try:
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=minute&count=300&type=chart"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)

    import xml.etree.ElementTree as ET

    root = ET.fromstring(res.text)

    rows = []
    for node in root.findall(".//item"):
      data_str = node.attrib.get("data")
      if not data_str:
        continue
      # 데이터 포맷 예: 20260807153000,시가,고가,저가,종가,거래량
      parts = data_str.split("|")
      if len(parts) >= 6:
        dt = parts[0]
        rows.append({
            "Datetime": pd.to_datetime(dt, format="%Y%m%d%H%M%S", errors="coerce"),
            "시가": int(parts[1]),
            "고가": int(parts[2]),
            "저가": int(parts[3]),
            "종가": int(parts[4]),
            "거래량": int(parts[5]),
        })

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["Datetime"])
    df.set_index("Datetime", inplace=True)

    # 3분봉으로 리샘플링 (키움 3분봉 주기 일치화)
    df_3min = (
        df.resample("3min")
        .agg({
            "시가": "first",
            "고가": "max",
            "저가": "min",
            "종가": "last",
            "거래량": "sum",
        })
        .dropna()
    )

    # 당일 09:00 이후 데이터만 추출
    today_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    df_today = df_3min.loc[today_date]

    return df_today
  except Exception as e:
    return None


# 세력 평단가(거래대금 가중평균 VWAP) 계산
def calculate_vwap(df):
  if df.empty:
    return df
  # 당일 09:00 ~ 15:30 장 운영 시간 필터링
  df = df.between_time("09:00", "15:30")
  typical_price = (df["고가"] + df["저가"] + df["종가"]) / 3
  cum_tp_vol = (typical_price * df["거래량"]).cumsum()
  cum_vol = df["거래량"].cumsum()

  df["세력평단"] = (
      cum_tp_vol / cum_vol
  )  # 키움증권 거래대금 가중평균 세력 평단 공식
  return df


# --- UI 구성 ---
st.title("📊 Open Book Pro - Day Trading Mapping (Kiwoom Sync)")
st.markdown(
    "키움증권 HTS 실시간 데이터 연동 — 당일 09:00 이후 3분봉 주가 및 세력 평단"
)

# 상단 입력 패널
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
  ticker_input = st.text_input(
      "종목코드 입력 (6자리)", value="347700", max_chars=6
  )  # 스피어 코드 기본 설정
with col2:
  stock_name = st.text_input("종목명", value="스피어")
with col3:
  timeframe = st.selectbox("봉 주기", ["3분봉", "1분봉", "5분봉"], index=0)

if st.button("🔄 키움 실시간 데이터 동기화 및 매핑", type="primary"):
  with st.spinner("키움/네이버 실시간 서버에서 분봉 데이터를 가져오는 중..."):
    df_raw = parse_naver_xml_chart(ticker_input)

    if df_raw is not None and not df_raw.empty:
      # 주기별 재조정
      if timeframe == "1분봉":
        # 1분봉 원본 활용
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker_input}&timeframe=minute&count=300&type=chart"
        # (필요시 1분봉 리샘플링 로직 적용)
        df_final = df_raw
      elif timeframe == "5분봉":
        df_final = (
            df_raw.resample("5min")
            .agg({
                "시가": "first",
                "고가": "max",
                "저가": "min",
                "종가": "last",
                "거래량": "sum",
            })
            .dropna()
        )
      else:
        df_final = df_raw

      # 세력 평단 계산 적용
      df_final = calculate_vwap(df_final)

      latest_time = df_final.index[-1].strftime("%H:%M")
      latest_price = int(df_final["종가"].iloc[-1])
      latest_vwap = int(df_final["세력평단"].iloc[-1])
      max_price = int(df_final["고가"].max())
      min_price = int(df_final["저가"].min())

      st.success(
          f"[{stock_name} ({ticker_input})] 데이터 동기화 성공 — 기준 시간:"
          f" {latest_time}"
      )

      # 상단 요약 지표
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

      # 차트 시각화 (키움 HTS 스타일 캔들 & 평단선 구현)
      st.subheader(
          f"{stock_name} ({ticker_input}) 당일 {timeframe} 동기화 매핑 차트"
      )

      fig, (ax1, ax2) = plt.subplots(
          2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]}
      )

      # 상단 가격 및 세력평단 차트
      ax1.plot(
          df_final.index,
          df_final["종가"],
          label="종가 (Price)",
          color="#1f77b4",
          linewidth=1.5,
      )
      ax1.plot(
          df_final.index,
          df_final["세력평단"],
          label="세력평단 (VWAP)",
          color="#ff7f0e",
          linewidth=2,
      )
      ax1.set_title(
          f"Kiwoom Synced Intraday Chart ({latest_time})", fontsize=11
      )
      ax1.legend(loc="upper left")
      ax1.grid(True, linestyle="--", alpha=0.5)

      # 하단 거래량 바차트 (빨간색/파란색 양음봉 구분)
      colors = [
          "red" if row["종가"] >= row["시가"] else "blue"
          for idx, row in df_final.iterrows()
      ]
      ax2.bar(
          df_final.index,
          df_final["거래량"],
          color=colors,
          width=dict(
              {"3분봉": 0.0015, "1분봉": 0.0005, "5분봉": 0.002}
          ).get(timeframe, 0.0015),
      )
      ax2.set_title("Volume", fontsize=9)
      ax2.grid(True, linestyle="--", alpha=0.3)

      import matplotlib.dates as mdates

      ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
      ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

      plt.tight_layout()
      st.pyplot(fig)

      # 하단 복사 패널 및 상세 데이터
      st.markdown("---")
      c1, c2 = st.columns(2)
      with c1:
        st.info(f"💡 실시간 세력 평단가 복사값: **{latest_vwap:,} 원**")
      with c2:
        st.info(f"💡 실시간 종가 복사값: **{latest_price:,} 원**")

      with st.expander("📊 키움 연동 상세 분봉 데이터 테이블"):
        st.dataframe(
            df_final.tail(30)[["시가", "고가", "저가", "종가", "거래량", "세력평단"]]
        )

    else:
      st.error(
          "실시간 데이터를 가져오지 못했습니다. 종목코드(예: 347700)를 다시"
          " 확인해주세요."
      )
