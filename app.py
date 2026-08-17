import datetime
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import requests
import streamlit as st
import streamlit.components.v1 as components
import xml.etree.ElementTree as ET
from pykrx import stock

# ---------------------------------------------------------
# 실시간(준실시간) 시세 보정
# ---------------------------------------------------------
@st.cache_data(ttl=5)
def fetch_realtime_price(code: str):
    try:
        url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        item = data["datas"][0]
        return {
            "price": int(item["closePrice"].replace(",", "")),
            "change_rate": float(item["fluctuationsRatio"]),
            "volume": int(item["accumulatedTradingVolume"].replace(",", "")),
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return None


def patch_today_with_realtime(df: pd.DataFrame, code: str) -> pd.DataFrame:
    rt = fetch_realtime_price(code)
    if rt is None or df is None or df.empty:
        return df

    today = pd.Timestamp(datetime.datetime.now().date())
    df = df.copy()

    if today in df.index:
        df.loc[today, "종가"] = rt["price"]
        if rt["volume"] > 0:
            df.loc[today, "거래량"] = rt["volume"]
    else:
        last_row = df.iloc[-1].copy()
        last_row["종가"] = rt["price"]
        last_row["시가"] = last_row.get("시가", rt["price"])
        last_row["고가"] = max(last_row.get("고가", rt["price"]), rt["price"])
        last_row["저가"] = min(last_row.get("저가", rt["price"]), rt["price"])
        if rt["volume"] > 0:
            last_row["거래량"] = rt["volume"]
        df.loc[today] = last_row

    return df


def patch_latest_row_with_realtime(df: pd.DataFrame, code: str) -> pd.DataFrame:
    rt = fetch_realtime_price(code)
    if rt is None or df is None or df.empty:
        return df
    df = df.copy()
    last_idx = df.index[-1]
    df.loc[last_idx, "종가"] = rt["price"]
    df.loc[last_idx, "고가"] = max(df.loc[last_idx, "고가"], rt["price"])
    df.loc[last_idx, "저가"] = min(df.loc[last_idx, "저가"], rt["price"])
    return df


# ---------------------------------------------------------
# 분봉 / 일봉 / 주봉 / 월봉 데이터 수집 함수
# ---------------------------------------------------------
@st.cache_data(ttl=15)
def fetch_naver_minute_ohlcv(code: str, count: int = 500) -> pd.DataFrame:
    try:
        url = (
            f"https://fchart.stock.naver.com/sise.nhn?"
            f"symbol={code}&timeframe=minute&count={count}&requestType=0"
        )
        resp = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        resp.raise_for_status()
        raw_text = resp.content.decode("euc-kr", errors="replace")
        raw_text = re.sub(r'encoding="[^"]*"', "", raw_text, count=1)
        root = ET.fromstring(raw_text)
        rows = []
        for item in root.iter("item"):
            data_str = item.attrib.get("data", "")
            parts = data_str.split("|")
            if len(parts) < 6:
                continue
            dt_str, o, h, l, c, v = parts[:6]
            try:
                dt = datetime.datetime.strptime(dt_str, "%Y%m%d%H%M")
                rows.append(
                    {
                        "datetime": dt,
                        "시가": float(o),
                        "고가": float(h),
                        "저가": float(l),
                        "종가": float(c),
                        "거래량": float(v),
                    }
                )
            except (ValueError, TypeError):
                continue
        if not rows:
            return pd.DataFrame()
        out = pd.DataFrame(rows).set_index("datetime").sort_index()
        return out
    except Exception:
        return pd.DataFrame()


def get_today_minute_df(code: str, interval_minutes: int) -> pd.DataFrame:
    raw = fetch_naver_minute_ohlcv(code, count=500)
    if raw.empty:
        return raw

    today = datetime.datetime.now().date()
    raw = raw[raw.index.date == today]
    if raw.empty:
        return raw

    if interval_minutes > 1:
        raw = raw.resample(f"{interval_minutes}T").agg(
            {"시가": "first", "고가": "max", "저가": "min", "종가": "last", "거래량": "sum"}
        )
        raw = raw.dropna()

    return raw


@st.cache_data(ttl=60)
def fetch_pykrx_ohlcv(code: str, timeframe_type: str) -> pd.DataFrame:
    """
    timeframe_type: 'day', 'week', 'month'
    pykrx를 이용해 일/주/월봉 데이터를 가져온 뒤 세력평단 계산용 더미 컬럼을 추가한다.
    """
    now = datetime.datetime.now()
    start_date = (now - datetime.timedelta(days=730)).strftime("%Y%m%d")
    end_date = now.strftime("%Y%m%d")
    
    freq_map = {"day": "d", "week": "w", "month": "m"}
    freq = freq_map.get(timeframe_type, "d")
    
    try:
        df = stock.get_market_ohlcv_by_date(start_date, end_date, code, freq=freq)
        if df is None or df.empty:
            return pd.DataFrame()
        
        # 컬럼명 통일 (시가, 고가, 저가, 종가, 거래량)
        rename_cols = {}
        for col in df.columns:
            if "시가" in col: rename_cols[col] = "시가"
            elif "고가" in col: rename_cols[col] = "고가"
            elif "저가" in col: rename_cols[col] = "저가"
            elif "종가" in col: rename_cols[col] = "종가"
            elif "거래량" in col: rename_cols[col] = "거래량"
        df = df.rename(columns=rename_cols)
        
        # 세력평단 계산용 임시 컬럼 부여 (전체 종가*거래량 기반 추정치 예시)
        df["매수거래량"] = df["거래량"] * 0.6
        df["매도거래량"] = df["거래량"] * 0.4
        
        # 평단가 산출 로직
        cum_tpv = (df["종가"] * df["거래량"]).cumsum()
        cum_vol = df["거래량"].cumsum()
        df["평단가"] = cum_tpv / cum_vol.replace(0, 1)
        
        cum_b_tpv = (df["종가"] * df["매수거래량"]).cumsum()
        cum_b_vol = df["매수거래량"].cumsum()
        df["세력매수평단"] = cum_b_tpv / cum_b_vol.replace(0, 1)
        
        cum_s_tpv = (df["종가"] * df["매도거래량"]).cumsum()
        cum_s_vol = df["매도거래량"].cumsum()
        df["세력매도평단"] = cum_s_tpv / cum_s_vol.replace(0, 1)
        
        return df
    except Exception:
        return pd.DataFrame()


# 페이지 기본 설정
st.set_page_config(
    page_title="주식 분석 포털 - 멀티 차트 뷰",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container { padding-top: 0.6rem; padding-bottom: 0rem; padding-left: 1.6rem; padding-right: 1.6rem; max-width: 100%; }
        div[data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
        div[data-testid="stHorizontalBlock"] { gap: 0.6rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)

# 간단한 상단 검색바 예시
col_s1, col_s2 = st.columns([3, 7])
with col_s1:
    stock_input = st.text_input("종목명 또는 코드 입력", value="삼성전자")
with col_s2:
    st.markdown("### 📊 일봉·주봉·월봉·분봉 동시 멀티 뷰")

code, stock_name = "005930", "삼성전자"
if stock_input:
    # 간단 매핑 또는 자동완성 연동 함수 활용 가능
    if stock_input.isdigit() and len(stock_input) == 6:
        code = stock_input
        try:
            stock_name = stock.get_market_ticker_name(code)
        except:
            stock_name = code
    else:
        # 이름 기반 조회 샘플
        from pykrx import stock as krx_stock
        try:
            tickers = krx_stock.get_market_ticker_list(datetime.datetime.now().strftime("%Y%m%d"), market="ALL")
            for t in tickers:
                name = krx_stock.get_market_ticker_name(t)
                if stock_input in name:
                    code, stock_name = t, name
                    break
        except:
            pass

# ---------------------------------------------------------
# 멀티 차트 HTML 템플릿 (일봉, 주봉, 월봉, 분봉 4분할 화면)
# ---------------------------------------------------------
MULTI_STUDY_HTML_TEMPLATE = """
<div id="sm_root" style="font-family: -apple-system, 'Malgun Gothic', sans-serif;">
  <div id="sm_toolbar" style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; font-size:12px; background:#f8f9fa; padding:8px; border-radius:6px;">
      <b>분봉 주기 선택:</b>
      <button class="sm-min-btn" data-val="1">1분</button>
      <button class="sm-min-btn" data-val="3">3분</button>
      <button class="sm-min-btn" data-val="5">5분</button>
      <button class="sm-min-btn" data-val="15">15분</button>
      <button class="sm-min-btn" data-val="999">999분</button>
      <span id="sm_clock" style="margin-left:auto; font-weight:bold; color:#1a73e8;"></span>
  </div>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
    <div style="border:1px solid #e0e0e0; border-radius:8px; padding:6px; background:#ffffff;">
      <div style="font-weight:bold; font-size:12px; margin-bottom:4px; color:#333;">📈 일봉 차트</div>
      <div id="plot_day" style="width:100%; height:320px;"></div>
    </div>
    <div style="border:1px solid #e0e0e0; border-radius:8px; padding:6px; background:#ffffff;">
      <div style="font-weight:bold; font-size:12px; margin-bottom:4px; color:#333;">📈 주봉 차트</div>
      <div id="plot_week" style="width:100%; height:320px;"></div>
    </div>
    <div style="border:1px solid #e0e0e0; border-radius:8px; padding:6px; background:#ffffff;">
      <div style="font-weight:bold; font-size:12px; margin-bottom:4px; color:#333;">📈 월봉 차트</div>
      <div id="plot_month" style="width:100%; height:320px;"></div>
    </div>
    <div style="border:1px solid #e0e0e0; border-radius:8px; padding:6px; background:#ffffff;">
      <div style="font-weight:bold; font-size:12px; margin-bottom:4px; color:#333;">📈 분봉 차트 (<span id="lbl_min_title">1</span>분)</div>
      <div id="plot_min" style="width:100%; height:320px;"></div>
    </div>
  </div>
</div>

<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<script>
(function() {
  const DATA = __ALL_DATA_JSON__;

  function renderChart(divId, dSet) {
      if (!dSet || !dSet.close || dSet.close.length === 0) {
          document.getElementById(divId).innerHTML = "<div style='text-align:center;padding:50px;color:#aaa;'>데이터 없음</div>";
          return;
      }
      const traceClose = { x: dSet.dates, y: dSet.close, mode: 'lines', name: '종가', line: { color: '#212529', width: 1.2 } };
      const traceAvg = { x: dSet.dates, y: dSet.origAvg, mode: 'lines', name: '세력평단', line: { color: '#f08c00', width: 2 } };
      
      const layout = {
          margin: {l: 40, r: 20, t: 10, b: 30},
          hovermode: 'x unified',
          showlegend: false,
          xaxis: {type: 'category'},
          yaxis: {title: ''}
      };
      Plotly.newPlot(divId, [traceClose, traceAvg], layout, {displaylogo:false, responsive:true});
  }

  // 초기 렌더링 (일, 주, 월)
  renderChart('plot_day', DATA.day);
  renderChart('plot_week', DATA.week);
  renderChart('plot_month', DATA.month);
  renderChart('plot_min', DATA.min_1); // 기본 1분봉

  // 분봉 버튼 클릭 이벤트 처리
  document.querySelectorAll('.sm-min-btn').forEach(btn => {
      btn.onclick = function() {
          const val = this.getAttribute('data-val');
          document.getElementById('lbl_min_title').textContent = val;
          
          let targetMinData = DATA.min_1;
          if (val === '3') targetMinData = DATA.min_3;
          else if (val === '5') targetMinData = DATA.min_5;
          else if (val === '15') targetMinData = DATA.min_15;
          else if (val === '999') targetMinData = DATA.min_999;
          
          renderChart('plot_min', targetMinData);
      };
  });

  // 시계 표시
  function tickClock() {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      document.getElementById('sm_clock').textContent =
          now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) + ' ' +
          pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
  }
  tickClock();
  setInterval(tickClock, 1000);
})();
</script>
"""

# 데이터 프레임 준비 (일, 주, 월)
df_day = fetch_pykrx_ohlcv(code, "day")
df_week = fetch_pykrx_ohlcv(code, "week")
df_month = fetch_pykrx_ohlcv(code, "month")

# 분봉 데이터 (1분, 3분, 5분, 15분, 999분 시뮬레이션/리샘플)
df_min_1 = get_today_minute_df(code, 1)
df_min_3 = get_today_minute_df(code, 3)
df_min_5 = get_today_minute_df(code, 5)
df_min_15 = get_today_minute_df(code, 15)
df_min_999 = get_today_minute_df(code, 60) # 999분 버튼 대응용 예시

def df_to_dict(df, is_minute=False):
    if df is None or df.empty:
        return {"dates": [], "close": [], "origAvg": []}
    x_fmt = "%H:%M" if is_minute else "%Y-%m-%d"
    return {
        "dates": [d.strftime(x_fmt) for d in df.index],
        "close": [float(v) for v in df["종가"]],
        "origAvg": [float(v) if "평단가" in df.columns and pd.notna(v) else float(v) for v in df["종가"]]
    }

all_data_payload = {
    "day": df_to_dict(df_day),
    "week": df_to_dict(df_week),
    "month": df_to_dict(df_month),
    "min_1": df_to_dict(df_min_1, True),
    "min_3": df_to_dict(df_min_3, True),
    "min_5": df_to_dict(df_min_5, True),
    "min_15": df_to_dict(df_min_15, True),
    "min_999": df_to_dict(df_min_999, True),
}

final_html = MULTI_STUDY_HTML_TEMPLATE.replace("__ALL_DATA_JSON__", json.dumps(all_data_payload, ensure_ascii=False))
components.html(final_html, height=750, scrolling=False)
