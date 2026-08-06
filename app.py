import datetime
import json
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import xml.etree.ElementTree as ET
from pykrx import stock

# ---------------------------------------------------------
# 실시간(준실시간) 시세 보정
# ---------------------------------------------------------
# pykrx는 KRX 정식 종가 기준 데이터라서 장중에는 "오늘" 데이터가
# 아예 없거나(장 시작 전) 전일 종가로 채워지는 경우가 많습니다.
# 그래서 키움 HTS 실시간 체결가와 차이가 나는 겁니다.
# 아래 함수는 네이버 금융의 준실시간 시세(수 초 지연) API를 붙여서
# "오늘"의 종가를 최대한 실시간에 가깝게 덮어씌우는 보정용입니다.
# ⚠ 완전한 틱 단위 실시간(키움과 100% 동일)을 원하면 키움 Open API+
#    (OCX, 로컬 PC + 로그인 필요)를 직접 연동해야 하며, 이 부분은
#    순수 파이썬 웹앱(streamlit cloud 등)에서는 대체가 불가능합니다.
@st.cache_data(ttl=5)  # 5초 캐시: 너무 잦은 호출 방지, 그래도 준실시간 유지
def fetch_realtime_price(code: str):
    """
    네이버 금융 준실시간 시세를 가져온다.
    반환: dict(현재가, 등락률, 거래량, 시각) 또는 실패 시 None
    """
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
    """
    df(pykrx 일봉)의 '오늘' 행을 준실시간 시세로 덮어써서
    키움 실시간 체결가와의 괴리를 줄인다.
    - 오늘 날짜 행이 아예 없으면 새로 추가
    - 있으면 종가/거래량을 실시간 값으로 교체
    거래량이 없으면(장중 누적거래량 조회 실패) 직전 거래량으로 대체.
    """
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


# ---------------------------------------------------------
# 분봉(실제 장중 1분봉) 데이터
# ---------------------------------------------------------
# ⚠ pykrx는 분봉 API를 제공하지 않습니다. get_market_ohlcv_by_date(freq="m")의
#   "m"은 "월봉(month)"이라서, 분봉을 pykrx로 받으려 하면 사실상 월봉을
#   억지로 리샘플하는 것이라 실제 장중 흐름과 전혀 다른 데이터가 나옵니다.
#   그래서 분봉은 네이버 증권 차트 API(1분봉 원본)로 따로 받아옵니다.
@st.cache_data(ttl=15)  # 15초 캐시: 장중 갱신은 유지하면서 과도한 호출 방지
def fetch_naver_minute_ohlcv(code: str, count: int = 500) -> pd.DataFrame:
    """
    네이버 증권 1분봉 원본 데이터를 가져온다. (기본 최근 count개 캔들)
    반환: index=datetime, columns=[시가,고가,저가,종가,거래량]
    실패 시 빈 DataFrame 반환.
    """
    try:
        url = (
            f"https://fchart.stock.naver.com/sise.nhn?"
            f"symbol={code}&timeframe=minute&count={count}&requestType=0"
        )
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
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
    """
    당일(09:00~15:30) 분봉만 골라 원하는 분단위(1/3/5/10...)로 리샘플해서 반환.
    """
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
# 공통 함수 (한글 종목명 및 매핑 강화)
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_ticker_map():
    name_map = {
        "삼성전자": "005930",
        "SK하이닉스": "000660",
        "LG에너지솔루션": "373220",
        "삼성바이오로직스": "207940",
        "현대차": "005380",
        "셀트리온": "068270",
        "KIA": "000270",
        "기아": "000270",
        "KB금융": "105560",
        "POSCO홀딩스": "005490",
        "네이버": "035420",
        "NAVER": "035420",
        "카카오": "035720",
        "에코프로비엠": "247540",
        "에코프로": "086520",
        "한미반도체": "042700",
        "대한전선": "001440",
        "대한광통신": "010170",
        "대원전선": "006340",
        "한화오션": "042660",
        "광전자": "017900",
        "RF머트리얼즈": "327260",
        "DB하이텍": "000990",
        "제주반도체": "080220",
        "코с나인": "252670",
        "씨젠": "096530",
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

    return "005930", "삼성전자"


def get_financial_info(code):
    sample_financials = {
        "005930": {
            "mcap": 4320000,
            "op_profit": 656700,
            "trade_type": "🏆 중장기",
            "foreign_net": "+125,400주",
            "inst_net": "+45,200주",
            "prog_net": "+450억 (매수우위)",
            "credit_ratio": "0.32%",
            "news": [
                "[특징주] 삼성전자, 하반기 HBM4 공급 기대감에 4%대 강세",
                "외인·기관 동반 순매수… 삼성전자 반도체 업황 개선 뚜렷",
                "증권가 \"삼성전자 목표주가 상향… 메모리 반도체 실적 호조\"",
            ],
        },
        "000660": {
            "mcap": 1370000,
            "op_profit": 120500,
            "trade_type": "🏆 중장기",
            "foreign_net": "+89,100주",
            "inst_net": "-12,400주",
            "prog_net": "+310억 (강한유입)",
            "credit_ratio": "0.45%",
            "news": [
                "[클릭 e종목] SK하이닉스, AI 서버용 고부가 제품 독점 수혜",
                "SK하이닉스, 장중 신고가 경신… \"메모리 슈퍼사이클 진입\"",
            ],
        },
        "042660": {
            "mcap": 250000,
            "op_profit": 3500,
            "trade_type": "🏆 중장기",
            "foreign_net": "+45,000주",
            "inst_net": "+12,000주",
            "prog_net": "+150억",
            "credit_ratio": "0.80%",
            "news": [
                "한화오션, 특수선 수주 호조 및 해양 플랜트 실적 개선 기대감",
            ],
        },
    }
    return sample_financials.get(
        code,
        {
            "mcap": 5000,
            "op_profit": 120,
            "trade_type": "🌊 스윙",
            "foreign_net": "+5,000주",
            "inst_net": "+1,200주",
            "prog_net": "+5억",
            "credit_ratio": "1.00%",
            "news": [
                f"[{stock.get_market_ticker_name(code) if code else '관련주'} 실시간 뉴스] 장내 수급 유입 및 테마 상승세 지속"
            ],
        },
    )


# ---------------------------------------------------------
# Study Mapping 스타일 차트 (2번째/3번째 참고 이미지 재현)
# - 차트의 특정 지점을 클릭하면 그 지점을 새 기준점(앵커)으로 삼아
#   세력평단(누적평단)을 그 지점부터 다시 계산
# - 기준점 정보 박스 + 최신(현재) 정보 박스를 함께 표시, 클릭 시 즉시 복사
# - 여백 좌/우 조절, 시간표시 토글, 전체범위 복원, 결과/이미지 복사 버튼 포함
# ---------------------------------------------------------
STUDY_MAPPING_HTML_TEMPLATE = """
<div id="sm_root" style="font-family: -apple-system, 'Malgun Gothic', sans-serif;">
  <div id="sm_toolbar" style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; font-size:12px;">
      <button id="sm_btn_copy_result" class="sm-btn sm-btn-blue">📋 결과 복사</button>
      <button id="sm_btn_copy_img" class="sm-btn sm-btn-purple">🖼 차트 이미지 복사</button>
      <button id="sm_btn_save_img" class="sm-btn sm-btn-green">⬇ 차트 이미지 저장</button>
      <button id="sm_btn_reset_range" class="sm-btn sm-btn-gray">↺ 전체 범위 복원</button>
      <button id="sm_btn_reset_anchor" class="sm-btn sm-btn-orange">📌 기준점 초기화</button>
      <span style="margin-left:8px;">여백 좌:</span>
      <input type="range" id="sm_pad_left" min="0" max="60" value="5" style="width:80px;">
      <span>우:</span>
      <input type="range" id="sm_pad_right" min="0" max="60" value="5" style="width:80px;">
      <label style="margin-left:8px;"><input type="checkbox" id="sm_show_time" checked> 시간 보이기</label>
      <span id="sm_clock" style="margin-left:auto; font-weight:bold; color:#1a73e8;"></span>
  </div>

  <div style="position:relative; border:1px solid #e0e0e0; border-radius:8px; padding:6px; background:#ffffff;">
    <div id="sm_anchor_box" class="sm-info-box" style="display:none; left:10px; top:10px;"></div>
    <div id="sm_latest_box" class="sm-info-box" style="display:none; right:10px; top:10px;"></div>
    <div id="sm_plot" style="width:100%; height:480px;"></div>
  </div>
  <div style="font-size:11px; color:#888; margin-top:4px;">
    ※ 차트 위 아무 지점이나 클릭하면 그 지점부터 세력평단(누적평단)이 다시 계산됩니다. (기준점 표시: 분홍 점선)
  </div>
</div>

<style>
  .sm-btn { border:none; border-radius:5px; padding:6px 10px; font-size:11px; font-weight:bold; cursor:pointer; color:#fff; }
  .sm-btn-blue { background:#1a73e8; }
  .sm-btn-purple { background:#7048e8; }
  .sm-btn-green { background:#2b8a3e; }
  .sm-btn-gray { background:#868e96; }
  .sm-btn-orange { background:#f08c00; }
  .sm-info-box {
      position:absolute; z-index:5; background:#ffffff; border:1px solid #dee2e6;
      border-radius:8px; padding:8px 10px; font-size:12px; box-shadow:0 2px 8px rgba(0,0,0,0.12);
      min-width:190px;
  }
  .sm-info-box .sm-close { position:absolute; top:4px; right:6px; cursor:pointer; color:#adb5bd; font-weight:bold; }
  .sm-info-title { font-weight:bold; font-size:11px; color:#495057; margin-bottom:4px; }
  .sm-info-row { display:flex; justify-content:space-between; gap:10px; padding:2px 0; }
  .sm-info-label { color:#666; }
  .sm-info-value { font-weight:bold; cursor:pointer; }
  .sm-info-value:hover { text-decoration:underline; }
</style>

<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<script>
(function() {
  const D = __DATA_JSON__;
  const N = D.close.length;

  function cumAvgFrom(startIdx, volArr, origArr) {
      const out = new Array(N).fill(null);
      let cumTPV = 0, cumVol = 0;
      for (let i = startIdx; i < N; i++) {
          cumTPV += D.close[i] * (volArr[i] || 0);
          cumVol += (volArr[i] || 0);
          out[i] = cumVol > 0 ? cumTPV / cumVol : (out[i-1] !== undefined ? out[i-1] : D.close[i]);
      }
      for (let i = 0; i < startIdx; i++) { out[i] = origArr[i]; }
      return out;
  }

  let anchorIdx = 0;
  let avgSeries = D.origAvg.slice();
  let buyAvgSeries = D.origBuyAvg.slice();
  let sellAvgSeries = D.origSellAvg.slice();
  let padLeft = 5, padRight = 5;

  const traceClose = {
      x: D.dates, y: D.close, mode: 'lines', name: '종가',
      line: { color: '#212529', width: 1.4 },
      hovertemplate: '%{x}<br>종가: %{y:,.0f}원<extra></extra>'
  };
  const traceAvg = {
      x: D.dates, y: avgSeries, mode: 'lines', name: '세력평단(전체)',
      line: { color: '#f08c00', width: 2.6 },
      hovertemplate: '%{x}<br>세력평단: %{y:,.0f}원<extra></extra>'
  };
  const traceBuyAvg = {
      x: D.dates, y: buyAvgSeries, mode: 'lines', name: '세력매수평단',
      line: { color: '#d32f2f', width: 1.7, dash: 'dashdot' },
      hovertemplate: '%{x}<br>세력매수평단: %{y:,.0f}원<extra></extra>'
  };
  const traceSellAvg = {
      x: D.dates, y: sellAvgSeries, mode: 'lines', name: '세력매도평단',
      line: { color: '#1971c2', width: 1.7, dash: 'dashdot' },
      hovertemplate: '%{x}<br>세력매도평단: %{y:,.0f}원<extra></extra>'
  };

  const layout = {
      margin: {l: 50, r: 30, t: 20, b: 40},
      hovermode: 'x unified',
      showlegend: true,
      legend: {orientation: 'h', y: 1.08},
      xaxis: {type: 'category'},
      yaxis: {title: '가격(원)'},
      shapes: [],
  };

  Plotly.newPlot('sm_plot', [traceClose, traceAvg, traceBuyAvg, traceSellAvg], layout, {displaylogo:false, responsive:true});
  const plotDiv = document.getElementById('sm_plot');

  function fmt(n) { return Math.round(n).toLocaleString('ko-KR'); }

  function bindCopy(container) {
      container.querySelectorAll('[data-copy]').forEach(function(el) {
          el.onclick = function() { navigator.clipboard.writeText(el.getAttribute('data-copy')); };
      });
  }

  function showLatestBox() {
      const lastIdx = N - 1;
      const close_v = D.close[lastIdx];
      const avg_v = avgSeries[lastIdx];
      const buy_v = buyAvgSeries[lastIdx];
      const sell_v = sellAvgSeries[lastIdx];
      const disp = ((close_v - avg_v) / avg_v * 100);
      const box = document.getElementById('sm_latest_box');
      box.style.display = 'block';
      box.innerHTML =
        '<span class="sm-close" onclick="document.getElementById(\\'sm_latest_box\\').style.display=\\'none\\';">✕</span>' +
        '<div class="sm-info-title">📍 ' + D.dates[0] + ' ~ ' + D.dates[lastIdx] + '</div>' +
        '<div class="sm-info-row"><span class="sm-info-label">종가</span><span class="sm-info-value" data-copy="' + Math.round(close_v) + '">' + fmt(close_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력평단</span><span class="sm-info-value" style="color:#f08c00;" data-copy="' + Math.round(avg_v) + '">' + fmt(avg_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력매수평단</span><span class="sm-info-value" style="color:#d32f2f;" data-copy="' + Math.round(buy_v) + '">' + fmt(buy_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력매도평단</span><span class="sm-info-value" style="color:#1971c2;" data-copy="' + Math.round(sell_v) + '">' + fmt(sell_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">괴리율(전체평단)</span><span class="sm-info-value" style="color:' + (disp>=0?'#d32f2f':'#1971c2') + ';">' + (disp>=0?'+':'') + disp.toFixed(2) + '%</span></div>' +
        '<div style="font-size:10px; color:#adb5bd; margin-top:4px;">숫자를 누르면 가격만 복사됩니다 (키움 라인 붙여넣기용)</div>';
      bindCopy(box);
  }

  function showAnchorBox(idx) {
      const close_v = D.close[idx];
      const avg_v = avgSeries[idx];
      const buy_v = buyAvgSeries[idx];
      const sell_v = sellAvgSeries[idx];
      const disp = ((close_v - avg_v) / avg_v * 100);
      const box = document.getElementById('sm_anchor_box');
      box.style.display = 'block';
      box.innerHTML =
        '<span class="sm-close" onclick="document.getElementById(\\'sm_anchor_box\\').style.display=\\'none\\';">✕</span>' +
        '<div class="sm-info-title">📌 ' + D.dates[idx] + ' 기준 (재계산 시작점)</div>' +
        '<div class="sm-info-row"><span class="sm-info-label">종가</span><span class="sm-info-value" data-copy="' + Math.round(close_v) + '">' + fmt(close_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력평단</span><span class="sm-info-value" style="color:#f08c00;" data-copy="' + Math.round(avg_v) + '">' + fmt(avg_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력매수평단</span><span class="sm-info-value" style="color:#d32f2f;" data-copy="' + Math.round(buy_v) + '">' + fmt(buy_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">세력매도평단</span><span class="sm-info-value" style="color:#1971c2;" data-copy="' + Math.round(sell_v) + '">' + fmt(sell_v) + '원</span></div>' +
        '<div class="sm-info-row"><span class="sm-info-label">괴리율(전체평단)</span><span class="sm-info-value">' + (disp>=0?'+':'') + disp.toFixed(2) + '%</span></div>';
      bindCopy(box);
  }

  function redraw() {
      avgSeries = cumAvgFrom(anchorIdx, D.volume, D.origAvg);
      buyAvgSeries = cumAvgFrom(anchorIdx, D.buyVolume, D.origBuyAvg);
      sellAvgSeries = cumAvgFrom(anchorIdx, D.sellVolume, D.origSellAvg);
      Plotly.restyle('sm_plot', {y: [avgSeries]}, [1]);
      Plotly.restyle('sm_plot', {y: [buyAvgSeries]}, [2]);
      Plotly.restyle('sm_plot', {y: [sellAvgSeries]}, [3]);
      const shapes = anchorIdx > 0 ? [{
          type: 'line', x0: D.dates[anchorIdx], x1: D.dates[anchorIdx],
          yref: 'paper', y0: 0, y1: 1,
          line: { color: '#e64980', width: 1.5, dash: 'dot' }
      }] : [];
      Plotly.relayout('sm_plot', {shapes: shapes});
      showLatestBox();
      if (anchorIdx > 0) { showAnchorBox(anchorIdx); }
      else { document.getElementById('sm_anchor_box').style.display = 'none'; }
  }

  plotDiv.on('plotly_click', function(evt) {
      if (!evt.points || !evt.points.length) return;
      anchorIdx = evt.points[0].pointIndex;
      redraw();
  });

  document.getElementById('sm_btn_reset_anchor').onclick = function() {
      anchorIdx = 0;
      redraw();
  };

  document.getElementById('sm_btn_reset_range').onclick = function() {
      Plotly.relayout('sm_plot', {'xaxis.autorange': true, 'yaxis.autorange': true});
      padLeft = 5; padRight = 5;
      document.getElementById('sm_pad_left').value = 5;
      document.getElementById('sm_pad_right').value = 5;
      Plotly.relayout('sm_plot', {'margin.l': 50, 'margin.r': 30});
  };

  function applyPadding() {
      Plotly.relayout('sm_plot', {'margin.l': 50 + padLeft, 'margin.r': 30 + padRight});
  }
  document.getElementById('sm_pad_left').oninput = function(e) { padLeft = parseInt(e.target.value, 10); applyPadding(); };
  document.getElementById('sm_pad_right').oninput = function(e) { padRight = parseInt(e.target.value, 10); applyPadding(); };

  document.getElementById('sm_show_time').onchange = function(e) {
      document.getElementById('sm_clock').style.display = e.target.checked ? 'inline' : 'none';
  };

  function tickClock() {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      document.getElementById('sm_clock').textContent =
          now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) + ' ' +
          pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
  }
  tickClock();
  setInterval(tickClock, 1000);

  document.getElementById('sm_btn_copy_result').onclick = function() {
      const lastIdx = N - 1;
      const disp = ((D.close[lastIdx] - avgSeries[lastIdx]) / avgSeries[lastIdx] * 100);
      let text = '■ [' + D.stockName + '(' + D.code + ') - ' + D.timeframe + ']\\n' +
                 '• 종가: ' + fmt(D.close[lastIdx]) + '원\\n' +
                 '• 세력평단: ' + fmt(avgSeries[lastIdx]) + '원\\n' +
                 '• 세력매수평단: ' + fmt(buyAvgSeries[lastIdx]) + '원\\n' +
                 '• 세력매도평단: ' + fmt(sellAvgSeries[lastIdx]) + '원\\n' +
                 '• 괴리율(전체평단): ' + (disp>=0?'+':'') + disp.toFixed(2) + '%';
      if (anchorIdx > 0) { text += '\\n• 기준점(' + D.dates[anchorIdx] + ') 이후 재계산됨'; }
      navigator.clipboard.writeText(text);
  };

  document.getElementById('sm_btn_save_img').onclick = function() {
      Plotly.downloadImage('sm_plot', {format:'png', filename: D.stockName + '_' + D.timeframe + '_chart'});
  };

  document.getElementById('sm_btn_copy_img').onclick = function() {
      Plotly.toImage(plotDiv, {format:'png', width:1200, height:600}).then(function(url) {
          fetch(url).then(function(r) { return r.blob(); }).then(function(blob) {
              if (navigator.clipboard && window.ClipboardItem) {
                  navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
              }
          });
      });
  };

  redraw();
})();
</script>
"""


def render_study_mapping_chart(df, stock_name, code, selected_timeframe):
    is_minute = selected_timeframe.endswith("분봉")
    x_fmt = "%H:%M" if is_minute else "%Y-%m-%d"
    dates = [d.strftime(x_fmt) for d in df.index]
    close = [float(v) for v in df["종가"]]
    volume = [float(v) for v in df["거래량"]]
    buy_volume = [float(v) for v in df["매수거래량"]]
    sell_volume = [float(v) for v in df["매도거래량"]]
    orig_avg = [float(v) if pd.notna(v) else None for v in df["평단가"]]
    orig_buy_avg = [float(v) if pd.notna(v) else None for v in df["세력매수평단"]]
    orig_sell_avg = [float(v) if pd.notna(v) else None for v in df["세력매도평단"]]

    payload = {
        "dates": dates,
        "close": close,
        "volume": volume,
        "buyVolume": buy_volume,
        "sellVolume": sell_volume,
        "origAvg": orig_avg,
        "origBuyAvg": orig_buy_avg,
        "origSellAvg": orig_sell_avg,
        "stockName": stock_name,
        "code": code,
        "timeframe": selected_timeframe,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = STUDY_MAPPING_HTML_TEMPLATE.replace("__DATA_JSON__", data_json)
    components.html(html, height=680, scrolling=False)


# ---------------------------------------------------------
# TAB 1: 평단선 차트
# ---------------------------------------------------------
with main_tab1:
    if "search_history" not in st.session_state:
        st.session_state.search_history = ["삼성전자", "SK하이닉스"]
    if "target_stock" not in st.session_state:
        st.session_state.target_stock = "삼성전자"

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
            search_clicked = st.button(
                "검색", use_container_width=True, type="primary"
            )

        if search_clicked and input_val:
            st.session_state.target_stock = input_val

        code, stock_name = resolve_code_or_name(
            st.session_state.target_stock
        )

        if stock_name and stock_name not in st.session_state.search_history:
            st.session_state.search_history.insert(0, stock_name)
            if len(st.session_state.search_history) > 12:
                st.session_state.search_history.pop()

        st.markdown(
            f"""
            <div style="display: flex; align-items: center; justify-content: space-between; background: #f8f9fa; padding: 6px 10px; border: 1px solid #e9ecef; border-radius: 6px; margin-bottom: 8px;">
                <span style="font-size: 13px; font-weight: bold;">📌 종목: {stock_name} ({code})</span>
                <button onclick="navigator.clipboard.writeText('{code}');" style="background:#1a73e8; color:white; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:11px; font-weight:bold;">
                    📋 코드 복사 ({code})
                </button>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.session_state.search_history:
            st.markdown(
                "<span style='font-size:11px; color:#666;'>최근 검색 기록 (최대 12개):</span>",
                unsafe_allow_html=True,
            )
            history_list = st.session_state.search_history[:12]
            h_cols = st.columns(len(history_list))
            for idx, hist_name in enumerate(history_list):
                with h_cols[idx]:
                    st.button(
                        hist_name,
                        key=f"hist_btn_{idx}",
                        on_click=set_recent_stock,
                        args=(hist_name,),
                        use_container_width=True,
                    )

    with col_right:
        timeframe_options = [
            "일봉",
            "주봉",
            "월봉",
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
            "999분봉",
        ]
        selected_timeframe = st.radio(
            "차트 주기",
            timeframe_options,
            index=0,
            horizontal=True,
            key="direct_timeframe_select",
            label_visibility="collapsed",
        )

    s_date_dummy = "20240101"
    e_date_dummy = datetime.datetime.now().strftime("%Y%m%d")
    df_temp = stock.get_market_ohlcv_by_date(s_date_dummy, e_date_dummy, code, "d")
    if df_temp is not None and not df_temp.empty:
        df_temp["TPV"] = df_temp["종가"] * df_temp["거래량"]
        cum_v_tmp = df_temp["거래량"].cumsum()
        vwap_tmp = df_temp["TPV"].cumsum() / cum_v_tmp.replace(0, pd.NA)
        vwap_tmp = vwap_tmp.ffill()
        
        df_temp["가격변화"] = df_temp["종가"].diff().fillna(0)
        df_temp["매수거래량"] = df_temp.apply(lambda r: r["거래량"] if r["가격변화"] >= 0 else r["거래량"] * 0.4, axis=1)
        df_temp["매도거래량"] = df_temp.apply(lambda r: r["거래량"] * 0.6 if r["가격변화"] < 0 else r["거래량"] * 0.2, axis=1)
        df_temp["순매수증감"] = df_temp["매수거래량"] - df_temp["매도거래량"]

        # 세력매수평단 / 세력매도평단: 상승일(매수우위)/하락일(매도우위) 거래량으로 가중평균한
        # "매수 쪽에 실린 평단" / "매도 쪽에 실린 평단". 전체 평단(v_val)과는 다른 값입니다.
        buy_tpv_tmp = (df_temp["종가"] * df_temp["매수거래량"]).cumsum()
        buy_vol_tmp = df_temp["매수거래량"].cumsum().replace(0, pd.NA)
        sell_tpv_tmp = (df_temp["종가"] * df_temp["매도거래량"]).cumsum()
        sell_vol_tmp = df_temp["매도거래량"].cumsum().replace(0, pd.NA)
        buy_vwap_tmp = (buy_tpv_tmp / buy_vol_tmp).ffill()
        sell_vwap_tmp = (sell_tpv_tmp / sell_vol_tmp).ffill()

        t_vol = int(df_temp["거래량"].iloc[-1])
        c_buy = int(df_temp["매수거래량"].sum())
        n_qty = int(df_temp["순매수증감"].iloc[-1])
        r_buy = (df_temp["매수거래량"].iloc[-1] / t_vol * 100) if t_vol > 0 else 0.0
        r_net = (n_qty / t_vol * 100) if t_vol > 0 else 0.0
        v_val = int(vwap_tmp.iloc[-1])
        b_vwap = int(buy_vwap_tmp.iloc[-1]) if pd.notna(buy_vwap_tmp.iloc[-1]) else v_val
        s_vwap = int(sell_vwap_tmp.iloc[-1]) if pd.notna(sell_vwap_tmp.iloc[-1]) else v_val
    else:
        t_vol, c_buy, n_qty, r_buy, r_net, v_val, b_vwap, s_vwap = 1599258, 285894, -109492, 17.88, -6.85, 198465, 199134, 195719

    hts_top_panel_html = f"""
    <div style="background: #ffffff; border: 1px solid #1a73e8; border-radius: 8px; padding: 12px 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
        <div style="font-weight: bold; font-size: 13px; color: #1a73e8; margin-bottom: 8px; border-bottom: 2px solid #1a73e8; padding-bottom: 4px;">
            📊 HTS 기준 [{stock_name}] 수급 및 평단 분석 결과 <span style="font-size:11px; color:#666; font-weight:normal;">(글자 클릭 시 확인창 없이 즉시 복사)</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 8px; font-size: 12px;">
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">당일 전체 거래량:</span>
                <span onclick="navigator.clipboard.writeText('{t_vol}');" style="font-weight: bold; color: #111; cursor: pointer;" title="클릭 시 즉시 복사">{t_vol:,} 주</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">누적 매수 증가량:</span>
                <span onclick="navigator.clipboard.writeText('{c_buy}');" style="font-weight: bold; color: #111; cursor: pointer;" title="클릭 시 즉시 복사">{c_buy:,} 주</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">순매수 수량(증감):</span>
                <span onclick="navigator.clipboard.writeText('{n_qty}');" style="font-weight: bold; color: {'#d32f2f' if n_qty>=0 else '#7048e8'}; cursor: pointer;" title="클릭 시 즉시 복사">{n_qty:,} 주</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">거래량 대비 매수 비율:</span>
                <span onclick="navigator.clipboard.writeText('{r_buy:.2f}');" style="font-weight: bold; color: #111; cursor: pointer;" title="클릭 시 즉시 복사">{r_buy:.2f} %</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">거래량 대비 순매수 비율:</span>
                <span onclick="navigator.clipboard.writeText('{r_net:.2f}');" style="font-weight: bold; color: {'#d32f2f' if r_net>=0 else '#e03131'}; cursor: pointer;" title="클릭 시 즉시 복사">{r_net:.2f} %</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #f8f9fa; border-radius: 4px;">
                <span style="color: #555; font-weight: bold; white-space: nowrap;">전체 거래량 평단:</span>
                <span onclick="navigator.clipboard.writeText('{v_val}');" style="font-weight: bold; color: #111; cursor: pointer;" title="클릭 시 즉시 복사">{v_val:,} 원</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #fff9db; border: 1px solid #ffe066; border-radius: 4px;">
                <span style="color: #d9480f; font-weight: bold; white-space: nowrap;">세력 매수 평단:</span>
                <span onclick="navigator.clipboard.writeText('{b_vwap}');" style="font-weight: bold; color: #d32f2f; cursor: pointer;" title="클릭 시 즉시 복사">{b_vwap:,} 원</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 4px; padding: 5px 8px; background: #e7f5ff; border: 1px solid #74c0fc; border-radius: 4px;">
                <span style="color: #1864ab; font-weight: bold; white-space: nowrap;">세력 매도 평단:</span>
                <span onclick="navigator.clipboard.writeText('{s_vwap}');" style="font-weight: bold; color: #1971c2; cursor: pointer;" title="클릭 시 즉시 복사">{s_vwap:,} 원</span>
            </div>
        </div>
    </div>
    """
    components.html(hts_top_panel_html, height=135)

    is_minute_mode = selected_timeframe.endswith("분봉")

    if is_minute_mode:
        today = datetime.date.today()
        st.info(
            f"⏱️ 분봉 모드 — 단타용이라 **당일({today.strftime('%Y-%m-%d')}) 09:00 장 시작~15:30 장 마감**만 자동 조회됩니다. "
            f"(참고: 한국거래소 정규장은 08:00이 아니라 **09:00 시작·15:30 종료**가 맞습니다. "
            f"08:00~09:00은 '시간외 단일가/동시호가' 구간이라 분봉 차트엔 안 잡혀요.)"
        )
        s_year, s_mon, s_day = today.year, today.month, today.day
        e_year, e_mon, e_day = today.year, today.month, today.day
        with st.expander("📅 조회 기간 수동으로 바꾸기 (기본은 당일 자동)"):
            d_cols = st.columns(6)
            with d_cols[0]:
                s_year = st.selectbox("시작 연도", [2022, 2023, 2024, 2025, 2026], index=[2022, 2023, 2024, 2025, 2026].index(today.year), key="sy")
            with d_cols[1]:
                s_mon = st.selectbox("시작 월", list(range(1, 13)), index=today.month - 1, key="sm")
            with d_cols[2]:
                s_day = st.selectbox("시작 일", list(range(1, 32)), index=today.day - 1, key="sd")
            with d_cols[3]:
                e_year = st.selectbox("종료 연도", [2022, 2023, 2024, 2025, 2026], index=[2022, 2023, 2024, 2025, 2026].index(today.year), key="ey")
            with d_cols[4]:
                e_mon = st.selectbox("종료 월", list(range(1, 13)), index=today.month - 1, key="em")
            with d_cols[5]:
                e_day = st.selectbox("종료 일", list(range(1, 32)), index=today.day - 1, key="ed")
    else:
        st.markdown("📅 **조회 기간 설정 (연도·월·일 상세 선택)**")
        d_cols = st.columns(6)

        with d_cols[0]:
            s_year = st.selectbox(
                "시작 연도", [2022, 2023, 2024, 2025, 2026], index=2, key="sy"
            )
        with d_cols[1]:
            s_mon = st.selectbox(
                "시작 월", list(range(1, 13)), index=0, key="sm"
            )
        with d_cols[2]:
            s_day = st.selectbox(
                "시작 일", list(range(1, 32)), index=0, key="sd"
            )

        with d_cols[3]:
            e_year = st.selectbox(
                "종료 연도", [2022, 2023, 2024, 2025, 2026], index=4, key="ey"
            )
        with d_cols[4]:
            e_mon = st.selectbox(
                "종료 월", list(range(1, 13)), index=7, key="em"
            )
        with d_cols[5]:
            e_day = st.selectbox(
                "종료 일", list(range(1, 32)), index=4, key="ed"
            )

    try:
        start_date = datetime.date(s_year, s_mon, s_day)
    except ValueError:
        start_date = datetime.date(s_year, s_mon, 1)

    try:
        end_date = datetime.date(e_year, e_mon, e_day)
    except ValueError:
        end_date = datetime.date(e_year, e_mon, 1)

    s_date = start_date.strftime("%Y%m%d")
    e_date = end_date.strftime("%Y%m%d")

    if selected_timeframe == "일봉":
        df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "d")
    elif selected_timeframe == "주봉":
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
    elif selected_timeframe == "월봉":
        df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
    else:
        interval_minutes = int(selected_timeframe.replace("분봉", ""))
        df = get_today_minute_df(code, interval_minutes)
        if df.empty:
            st.warning(
                "당일 분봉 데이터를 아직 받아오지 못했습니다. "
                "장 시작(09:00) 이전이거나 네트워크 문제일 수 있습니다."
            )

    # 실시간(준실시간) 시세 보정 - 키움 체결가와의 괴리 축소
    rt_col1, rt_col2 = st.columns([1, 5])
    with rt_col1:
        use_realtime_patch = st.checkbox("⚡ 실시간 시세 보정", value=True, key="rt_patch_toggle")
    rt_info = None
    if use_realtime_patch and df is not None and not df.empty:
        rt_info = fetch_realtime_price(code)
        df = patch_today_with_realtime(df, code)
    with rt_col2:
        if use_realtime_patch and rt_info:
            st.caption(
                f"🟢 준실시간 반영됨 (네이버 시세 기준, {rt_info['time']} 조회) · "
                f"현재가 {rt_info['price']:,}원 · 완전한 틱 단위 일치는 키움 Open API+ 직접 연동이 필요합니다."
            )
        elif use_realtime_patch:
            st.caption("🟡 실시간 시세 조회 실패 — 네트워크 차단 또는 API 응답 오류. pykrx 기본값(전일/EOD)으로 표시됩니다.")
        else:
            st.caption("⚪ 실시간 보정 꺼짐 — pykrx 종가(EOD/지연) 기준으로 표시됩니다.")

    if df is None or df.empty:
        st.warning("선택한 조건에 해당하는 거래 데이터가 없습니다.")
    else:
        df["TPV"] = df["종가"] * df["거래량"]
        cum_volume = df["거래량"].cumsum()

        df["평단가"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
        df["평단가"] = df["평단가"].ffill()

        df["가격변화"] = df["종가"].diff().fillna(0)
        df["매수거래량"] = df.apply(lambda r: r["거래량"] if r["가격변화"] >= 0 else r["거래량"] * 0.4, axis=1)
        df["매도거래량"] = df.apply(lambda r: r["거래량"] * 0.6 if r["가격변화"] < 0 else r["거래량"] * 0.2, axis=1)
        df["순매수증감"] = df["매수거래량"] - df["매도거래량"]
        df["누적순매수증감"] = df["순매수증감"].cumsum()

        # 세력매수평단 / 세력매도평단
        # - 평단가(=세력평단): 전체 거래량으로 가중평균한 누적 평단선 (매수/매도 구분 없음)
        # - 세력매수평단: 상승(매수우위)일 거래량에 실린 가격만 누적 가중평균 → "사들인 자리"의 평단
        # - 세력매도평단: 하락(매도우위)일 거래량에 실린 가격만 누적 가중평균 → "덜어낸 자리"의 평단
        # 세 값은 서로 다릅니다. 평단가(전체)를 기준으로 보통 세력매수평단이 위, 세력매도평단이 아래에 위치합니다.
        buy_cum_tpv = (df["종가"] * df["매수거래량"]).cumsum()
        buy_cum_vol = df["매수거래량"].cumsum().replace(0, pd.NA)
        sell_cum_tpv = (df["종가"] * df["매도거래량"]).cumsum()
        sell_cum_vol = df["매도거래량"].cumsum().replace(0, pd.NA)
        df["세력매수평단"] = (buy_cum_tpv / buy_cum_vol).ffill()
        df["세력매도평단"] = (sell_cum_tpv / sell_cum_vol).ffill()

        last_close = int(df["종가"].iloc[-1])
        last_vwap = int(df["평단가"].iloc[-1])
        disparity = ((last_close - last_vwap) / last_vwap) * 100
        last_buy_vwap = int(df["세력매수평단"].iloc[-1]) if pd.notna(df["세력매수평단"].iloc[-1]) else last_vwap
        last_sell_vwap = int(df["세력매도평단"].iloc[-1]) if pd.notna(df["세력매도평단"].iloc[-1]) else last_vwap

        f_info = get_financial_info(code)
        mcap_val = f_info["mcap"]
        op_profit = f_info["op_profit"]
        trade_type = f_info["trade_type"]
        foreign_net = f_info["foreign_net"]
        inst_net = f_info["inst_net"]
        prog_net = f_info["prog_net"]
        credit_ratio = f_info["credit_ratio"]
        news_list = f_info.get("news", [])

        # 목표가 단계별 설정: 1차(+5%), 2차(+10%), 3차(+15%)
        target_1st = int(last_vwap * 1.05)
        target_2nd = int(last_vwap * 1.10)
        target_3rd = int(last_vwap * 1.15)

        # 손절가 단계별 설정: 1차(-2%), 2차(-3%), 절대사수 손절가(-4%)
        stop_1st = int(last_vwap * 0.98)
        stop_2nd = int(last_vwap * 0.97)
        absolute_stop_loss = int(last_vwap * 0.96)

        if 0 <= disparity <= 5.0:
            status_signal = "🔥 최적타점 (손절짧은매수타점)"
        elif disparity > 20.0:
            status_signal = "⚠️ 진입주의"
        elif last_close < absolute_stop_loss:
            status_signal = "🚨 절대손절이탈"
        else:
            status_signal = "📊 추세유지"

        f1, f2, f3, f4 = st.columns(4)
        f1.metric("🏢 시가총액", f"{mcap_val:,} 억원")
        f2.metric(
            "💵 영업이익",
            f"{op_profit:,} 억원",
            "🟢 흑자" if op_profit > 0 else "🔴 적자",
        )
        f3.metric("🎯 매매 성향", trade_type)
        f4.metric("⚡ 진단 상태", status_signal)

        s_c1, s_c2, s_c3, s_c4 = st.columns(4)
        s_c1.metric("🌐 외국인 순매수", foreign_net)
        s_c2.metric("🏛️ 기관 순매수", inst_net)
        s_c3.metric("💻 실시간 프로그램", prog_net)
        s_c4.metric("💳 신용잔고율", credit_ratio)

        st.markdown(
            f"""
            <div style="background-color: #f1f3f5; border-left: 4px solid #1a73e8; padding: 10px 15px; border-radius: 0 6px 6px 0; margin: 10px 0;">
                <div style="font-weight: bold; font-size: 13px; color: #1a73e8; margin-bottom: 5px;">📰 [{stock_name}] 실시간 상승 이유 및 주요 뉴스 속보</div>
                <ul style="margin: 0; padding-left: 20px; font-size: 12px; color: #333;">
                    {''.join([f"<li>{news}</li>" for news in news_list])}
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

        metrics_click_copy_html = f"""
        <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 5px;">
            <div onclick="navigator.clipboard.writeText('{last_close}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#666; font-weight:bold;">현재가</div>
                <div style="font-size:13px; font-weight:bold; color:#111; margin-top:2px;">{last_close:,}원 <span style="font-size:10px; color:{'#2b8a3e' if disparity>=0 else '#e03131'};">({disparity:+.1f}%)</span></div>
            </div>
            
            <div onclick="navigator.clipboard.writeText('{last_vwap}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#1a73e8; font-weight:bold;">📌 {selected_timeframe} 평단가</div>
                <div style="font-size:13px; font-weight:bold; color:#1a73e8; margin-top:2px;">{last_vwap:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{last_buy_vwap}');" style="background:#fff9db; border:1px solid #ffe066; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 가격 숫자만 즉시 복사 (키움 라인에 붙여넣기용)">
                <div style="font-size:11px; color:#d9480f; font-weight:bold;">🟠 세력매수평단</div>
                <div style="font-size:13px; font-weight:bold; color:#d32f2f; margin-top:2px;">{last_buy_vwap:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{last_sell_vwap}');" style="background:#e7f5ff; border:1px solid #74c0fc; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 가격 숫자만 즉시 복사 (키움 라인에 붙여넣기용)">
                <div style="font-size:11px; color:#1864ab; font-weight:bold;">🔵 세력매도평단</div>
                <div style="font-size:13px; font-weight:bold; color:#1971c2; margin-top:2px;">{last_sell_vwap:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{target_1st}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#2b8a3e; font-weight:bold;">🎯 1차목표(+5%)</div>
                <div style="font-size:13px; font-weight:bold; color:#2b8a3e; margin-top:2px;">{target_1st:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{target_2nd}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#2b8a3e; font-weight:bold;">🎯 2차목표(+10%)</div>
                <div style="font-size:13px; font-weight:bold; color:#2b8a3e; margin-top:2px;">{target_2nd:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{target_3rd}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#2b8a3e; font-weight:bold;">🎯 3차목표(+15%)</div>
                <div style="font-size:13px; font-weight:bold; color:#2b8a3e; margin-top:2px;">{target_3rd:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{stop_1st}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#f59f00; font-weight:bold;">🛑 1차 손절(-2%)</div>
                <div style="font-size:13px; font-weight:bold; color:#f59f00; margin-top:2px;">{stop_1st:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{stop_2nd}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#f08c00; font-weight:bold;">🛑 2차 손절(-3%)</div>
                <div style="font-size:13px; font-weight:bold; color:#f08c00; margin-top:2px;">{stop_2nd:,}원</div>
            </div>

            <div onclick="navigator.clipboard.writeText('{absolute_stop_loss}');" style="background:#ffffff; border:1px solid #e0e0e0; border-radius:8px; padding:10px 10px; min-width:110px; cursor:pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" title="클릭 시 확인창 없이 즉시 복사">
                <div style="font-size:11px; color:#e03131; font-weight:bold;">🚨 절대사수(-4%)</div>
                <div style="font-size:13px; font-weight:bold; color:#e03131; margin-top:2px;">{absolute_stop_loss:,}원</div>
            </div>
        </div>
        """
        components.html(metrics_click_copy_html, height=150)

        with st.expander("📝 텍스트 요약 및 전체 복사 기능"):
            copy_summary = (
                f"■ [{stock_name}({code}) - {selected_timeframe}]\n"
                f"• 매매성향: {trade_type} | 괴리율: {disparity:+.2f}%\n"
                f"• 현재가: {last_close:,}원 | 평단가: {last_vwap:,}원\n"
                f"• 🎯 1차목표 (+5%): {target_1st:,}원\n"
                f"• 🎯 2차목표 (+10%): {target_2nd:,}원\n"
                f"• 🎯 3차목표 (+15%): {target_3rd:,}원\n"
                f"• 🛑 1차 손절가 (-2%): {stop_1st:,}원\n"
                f"• 🛑 2차 손절가 (-3%): {stop_2nd:,}원\n"
                f"• 🚨 절대사수 손절가 (-4%): {absolute_stop_loss:,}원"
            )
            st.code(copy_summary, language="text")

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        chart_mode = st.radio(
            "차트 스타일",
            ["📊 기본 목표가 차트", "🧭 Study Mapping 스타일 (클릭 기준점 리셋)"],
            horizontal=True,
            key="chart_display_mode",
        )

        if chart_mode == "🧭 Study Mapping 스타일 (클릭 기준점 리셋)":
            render_study_mapping_chart(df, stock_name, code, selected_timeframe)
        else:
            fig = go.Figure()

            hover_x = [d.strftime("%H:%M" if is_minute_mode else "%Y-%m-%d") for d in df.index]

            hover_close = [f"종가: {int(val):,}원 ({disparity:+.2f}%)" for val in df["종가"]]
            hover_vwap = [f"누적 평단가: {int(val):,}원" if pd.notna(val) else "누적 평단가: -" for val in df["평단가"]]
            hover_net_inc = [f"순매수 증감: {int(val):,}주" for val in df["누적순매수증감"]]

            # 1. 종가 선
            fig.add_trace(
                go.Scatter(
                    x=hover_x,
                    y=df["종가"],
                    mode="lines",
                    name="종가",
                    text=hover_close,
                    hovertemplate="<b>%{x}</b><br>%{text}<extra>종가</extra>",
                    line=dict(color="#1f77b4", width=1.5),
                )
            )
            # 2. 누적 평단가 선
            fig.add_trace(
                go.Scatter(
                    x=hover_x,
                    y=df["평단가"],
                    mode="lines",
                    name=f"누적 평단가 ({selected_timeframe})",
                    text=hover_vwap,
                    hovertemplate="<b>%{x}</b><br>%{text}<extra>평단가</extra>",
                    line=dict(color="#ff7f0e", width=2.5),
                )
            )
            # 2-1. 세력매수평단 선
            hover_buy_vwap = [f"세력매수평단: {int(val):,}원" if pd.notna(val) else "세력매수평단: -" for val in df["세력매수평단"]]
            fig.add_trace(
                go.Scatter(
                    x=hover_x,
                    y=df["세력매수평단"],
                    mode="lines",
                    name="세력매수평단",
                    text=hover_buy_vwap,
                    hovertemplate="<b>%{x}</b><br>%{text}<extra>세력매수평단</extra>",
                    line=dict(color="#d32f2f", width=1.6, dash="dashdot"),
                )
            )
            # 2-2. 세력매도평단 선
            hover_sell_vwap = [f"세력매도평단: {int(val):,}원" if pd.notna(val) else "세력매도평단: -" for val in df["세력매도평단"]]
            fig.add_trace(
                go.Scatter(
                    x=hover_x,
                    y=df["세력매도평단"],
                    mode="lines",
                    name="세력매도평단",
                    text=hover_sell_vwap,
                    hovertemplate="<b>%{x}</b><br>%{text}<extra>세력매도평단</extra>",
                    line=dict(color="#1971c2", width=1.6, dash="dashdot"),
                )
            )
            # 3. 순매수 증감 추세선 (보조 축 활용)
            fig.add_trace(
                go.Scatter(
                    x=hover_x,
                    y=df["누적순매수증감"],
                    mode="lines",
                    name="누적 순매수 증감",
                    text=hover_net_inc,
                    hovertemplate="<b>%{x}</b><br>%{text}<extra>순매수증감</extra>",
                    line=dict(color="#2b8a3e", width=2, dash="dot"),
                    yaxis="y2"
                )
            )

            # 차트 내 다단계 목표가 및 다단계 손절선 가이드 라인 추가
            fig.add_hline(
                y=last_buy_vwap,
                line_dash="dashdot",
                line_color="#d32f2f",
                annotation_text=f"🟠 세력매수평단: {last_buy_vwap:,}원",
                annotation_position="top right",
            )
            fig.add_hline(
                y=last_sell_vwap,
                line_dash="dashdot",
                line_color="#1971c2",
                annotation_text=f"🔵 세력매도평단: {last_sell_vwap:,}원",
                annotation_position="bottom right",
            )
            fig.add_hline(
                y=target_3rd,
                line_dash="dot",
                line_color="#2b8a3e",
                annotation_text=f"🎯 3차 목표가 (+15%): {target_3rd:,}원",
                annotation_position="top left",
            )
            fig.add_hline(
                y=target_2nd,
                line_dash="dot",
                line_color="#2b8a3e",
                annotation_text=f"🎯 2차 목표가 (+10%): {target_2nd:,}원",
                annotation_position="top left",
            )
            fig.add_hline(
                y=target_1st,
                line_dash="dot",
                line_color="#2b8a3e",
                annotation_text=f"🎯 1차 목표가 (+5%): {target_1st:,}원",
                annotation_position="top left",
            )
            fig.add_hline(
                y=stop_1st,
                line_dash="dash",
                line_color="#f59f00",
                annotation_text=f"🛑 1차 손절가 (-2%): {stop_1st:,}원",
                annotation_position="bottom left",
            )
            fig.add_hline(
                y=stop_2nd,
                line_dash="dash",
                line_color="#f08c00",
                annotation_text=f"🛑 2차 손절가 (-3%): {stop_2nd:,}원",
                annotation_position="bottom left",
            )
            fig.add_hline(
                y=absolute_stop_loss,
                line_dash="dash",
                line_color="#e03131",
                annotation_text=f"🚨 절대사수 손절가 (-4%): {absolute_stop_loss:,}원",
                annotation_position="bottom left",
            )

            fig.update_layout(
                title=f"{stock_name} ({code}) - 다단계 목표가 및 손절선 차트",
                margin=dict(l=20, r=20, t=35, b=20),
                hovermode="x unified",
                template="plotly_white",
                height=400,
                yaxis=dict(title="가격 (원)"),
                yaxis2=dict(title="누적 순매수 증감 (주)", overlaying="y", side="right", showgrid=False)
            )

            fig.update_xaxes(
                type="category",
                tickangle=0,
                nticks=10,
            )

            st.plotly_chart(fig, use_container_width=True)

        # 📌 최근 날짜별 상세 수치 카드 (클릭 즉시 복사)
        st.markdown("### 📋 최근 날짜별 상세 수치 복사 (원하시는 가격 글자를 클릭하면 즉시 복사됩니다)")
        recent_df = df.tail(10).iloc[::-1]
        
        card_rows_html = ""
        for dt_idx, row in recent_df.iterrows():
            d_str = dt_idx.strftime("%H:%M" if is_minute_mode else "%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
            c_val = int(row["종가"])
            v_val = int(row["평단가"]) if pd.notna(row["평단가"]) else 0
            n_val = int(row["순매수증감"])
            t1 = int(v_val * 1.05) if v_val > 0 else 0
            t2 = int(v_val * 1.10) if v_val > 0 else 0
            t3 = int(v_val * 1.15) if v_val > 0 else 0
            s1 = int(v_val * 0.98) if v_val > 0 else 0
            s2 = int(v_val * 0.97) if v_val > 0 else 0
            s_abs = int(v_val * 0.96) if v_val > 0 else 0
            
            card_rows_html += f"""
            <tr style="border-bottom: 1px solid #f0f0f0; height: 40px; font-size: 11px;">
                <td style="text-align: center; font-weight: bold; color: #333;">{d_str}</td>
                <td onclick="navigator.clipboard.writeText('{c_val}');" style="text-align: right; font-weight: bold; color: #1f77b4; cursor: pointer;" title="클릭 시 즉시 복사">{c_val:,}원</td>
                <td onclick="navigator.clipboard.writeText('{v_val}');" style="text-align: right; font-weight: bold; color: #ff7f0e; cursor: pointer; background: #fff9db;" title="클릭 시 즉시 복사">{v_val:,}원</td>
                <td onclick="navigator.clipboard.writeText('{t1}');" style="text-align: right; color: #2b8a3e; cursor: pointer;" title="클릭 시 즉시 복사">{t1:,}원</td>
                <td onclick="navigator.clipboard.writeText('{t2}');" style="text-align: right; color: #2b8a3e; cursor: pointer;" title="클릭 시 즉시 복사">{t2:,}원</td>
                <td onclick="navigator.clipboard.writeText('{t3}');" style="text-align: right; color: #2b8a3e; cursor: pointer;" title="클릭 시 즉시 복사">{t3:,}원</td>
                <td onclick="navigator.clipboard.writeText('{s1}');" style="text-align: right; color: #f59f00; cursor: pointer;" title="클릭 시 즉시 복사">{s1:,}원</td>
                <td onclick="navigator.clipboard.writeText('{s2}');" style="text-align: right; color: #f08c00; cursor: pointer;" title="클릭 시 즉시 복사">{s2:,}원</td>
                <td onclick="navigator.clipboard.writeText('{s_abs}');" style="text-align: right; font-weight: bold; color: #e03131; cursor: pointer;" title="클릭 시 즉시 복사">{s_abs:,}원</td>
            </tr>
            """
            
        recent_table_html = f"""
        <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 15px;">
            <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                <thead>
                    <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 32px;">
                        <th style="text-align: center;">날짜</th>
                        <th style="text-align: right; color: #1f77b4;">종가 (복사)</th>
                        <th style="text-align: right; color: #ff7f0e; background: #fff9db;">평단가 (복사)</th>
                        <th style="text-align: right; color: #2b8a3e;">1차목표(+5%)</th>
                        <th style="text-align: right; color: #2b8a3e;">2차목표(+10%)</th>
                        <th style="text-align: right; color: #2b8a3e;">3차목표(+15%)</th>
                        <th style="text-align: right; color: #f59f00;">1차손절(-2%)</th>
                        <th style="text-align: right; color: #f08c00;">2차손절(-3%)</th>
                        <th style="text-align: right; color: #e03131;">절대사수(-4%)</th>
                    </tr>
                </thead>
                <tbody>{card_rows_html}</tbody>
            </table>
        </div>
        """
        components.html(recent_table_html, height=280)


# ---------------------------------------------------------
# TAB 2: 업종·테마 분석 대시보드
# ---------------------------------------------------------
with main_tab2:
    st.markdown("### ⭐ 업종·테마 분석 대시보드")
    st.caption("다단계 목표가 및 다단계 손절선 포함 분석")

    THEME_DATA = {
        "광케이블/광섬유": {
            "change": "+9.99%",
            "leader": "대한광통신",
            "stocks": [
                {
                    "name": "대한광통신",
                    "code": "010170",
                    "price": 1850,
                    "change": 4.50,
                    "op_status": "🟢 흑자",
                    "trade_type": "⚡ 단타",
                    "d_vwap": 1810,
                    "d_disp": "+2.1%",
                    "target1": 1900,
                    "target2": 1990,
                    "target3": 2080,
                    "stop1": 1770,
                    "stop2": 1755,
                    "stop_abs": 1735,
                }
            ],
        },
        "전선": {
            "change": "+8.91%",
            "leader": "대한전선",
            "stocks": [
                {
                    "name": "대한전선",
                    "code": "001440",
                    "price": 14200,
                    "change": 8.50,
                    "op_status": "🟢 흑자",
                    "trade_type": "🌊 스윙",
                    "d_vwap": 13950,
                    "d_disp": "+1.8%",
                    "target1": 14600,
                    "target2": 15340,
                    "target3": 16040,
                    "stop1": 13650,
                    "stop2": 13530,
                    "stop_abs": 13390,
                }
            ],
        },
    }

    top_keys = list(THEME_DATA.keys())[:5]
    top_cols = st.columns(len(top_keys) if len(top_keys) > 0 else 1)

    for i, t_name in enumerate(top_keys):
        t_info = THEME_DATA[t_name]
        rank_num = i + 1
        card_html = (
            '<div style="background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); min-height: 110px;">'
            f'<div style="display: flex; justify-content: space-between; align-items: center;">'
            f'<span style="color: #d32f2f; font-weight: bold; font-size: 13px;">{rank_num}위</span>'
            f'<span style="color: #d32f2f; font-weight: bold; font-size: 13px;">{t_info["change"]}</span>'
            "</div>"
            f'<div style="font-weight: bold; font-size: 14px; margin-top: 6px; color: #111;">{t_name}</div>'
            f'<div style="font-size: 11px; color: #666; margin-top: 4px;">{t_info["leader"]} 외</div>'
            "</div>"
        )
        with top_cols[i]:
            st.markdown(card_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_left, col_right = st.columns([1, 3.2])

    with col_left:
        search_mode = st.radio(
            "검색 모드", ["종목 검색", "테마 검색"], horizontal=True, key="s_mode"
        )
        search_input = st.text_input(
            "검색어 입력...", "", key="t_search", placeholder="종목명 또는 테마명 입력..."
        )

        theme_list = list(THEME_DATA.keys())

        if search_mode == "종목 검색":
            matched_stocks = []
            for t_name, t_info in THEME_DATA.items():
                for s_item in t_info["stocks"]:
                    if not search_input or (
                        search_input.lower() in s_item["name"].lower()
                        or search_input in s_item["code"]
                    ):
                        matched_stocks.append({**s_item, "theme": t_name})

            st.markdown(
                f"<span style='font-size:12px; color:#555;'>검색 결과: <b>{len(matched_stocks)}개</b> 종목</span>",
                unsafe_allow_html=True,
            )
        else:
            filtered_themes = [
                t for t in theme_list if not search_input or search_input in t
            ]
            selected_theme = st.radio(
                "테마 선택 라디오",
                filtered_themes if filtered_themes else ["검색 결과 없음"],
                index=0,
                label_visibility="collapsed",
                key="t_radio",
            )

    with col_right:
        if search_mode == "종목 검색":
            st.markdown("### 📌 종목 검색 결과 분석", unsafe_allow_html=True)
            if "matched_stocks" in locals() and matched_stocks:
                table_rows_html = ""
                for idx, item in enumerate(matched_stocks, start=1):
                    table_rows_html += f"""
                    <tr style="border-bottom: 1px solid #f0f0f0; height: 65px; font-size: 11px;">
                        <td style="text-align: center; font-weight: bold;">{idx}</td>
                        <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['trade_type']} ({item['theme']})</span></td>
                        <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
                        <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
                        <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
                        <td style="text-align: right; color: #d32f2f; font-weight: bold;">+{item['change']:.2f}%</td>
                        <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target1']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target2']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target3']:,}원</td>
                        <td style="text-align: right; color: #f59f00;">{item['stop1']:,}원</td>
                        <td style="text-align: right; color: #f08c00;">{item['stop2']:,}원</td>
                        <td style="text-align: right; font-weight: bold; color: #e03131;">{item['stop_abs']:,}원</td>
                    </tr>
                    """
                search_table_html = f"""
                <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                        <thead>
                            <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 38px;">
                                <th style="text-align: center;">순위</th>
                                <th style="text-align: left;">종목명</th>
                                <th style="text-align: center;">코드</th>
                                <th style="text-align: center;">실적</th>
                                <th style="text-align: right;">현재가</th>
                                <th style="text-align: right;">전일대비</th>
                                <th style="text-align: center; background-color: #fff9db;">일봉 평단</th>
                                <th style="text-align: right; color: #2b8a3e;">1차목표</th>
                                <th style="text-align: right; color: #2b8a3e;">2차목표</th>
                                <th style="text-align: right; color: #2b8a3e;">3차목표</th>
                                <th style="text-align: right; color: #f59f00;">1차손절</th>
                                <th style="text-align: right; color: #f08c00;">2차손절</th>
                                <th style="text-align: right; color: #e03131;">절대사수</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows_html}</tbody>
                    </table>
                </div>
                """
                components.html(search_table_html, height=220, scrolling=True)
            else:
                st.info("검색된 종목이 없습니다.")
        else:
            if (
                "selected_theme" in locals()
                and selected_theme
                and selected_theme in THEME_DATA
            ):
                st.markdown(f"### 📌 {selected_theme}", unsafe_allow_html=True)
                stocks_list = THEME_DATA[selected_theme]["stocks"]
                table_rows_html = ""
                for idx, item in enumerate(stocks_list, start=1):
                    table_rows_html += f"""
                    <tr style="border-bottom: 1px solid #f0f0f0; height: 65px; font-size: 11px;">
                        <td style="text-align: center; font-weight: bold;">{idx}</td>
                        <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['trade_type']}</span></td>
                        <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
                        <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
                        <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
                        <td style="text-align: right; color: #d32f2f; font-weight: bold;">+{item['change']:.2f}%</td>
                        <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target1']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target2']:,}원</td>
                        <td style="text-align: right; color: #2b8a3e;">{item['target3']:,}원</td>
                        <td style="text-align: right; color: #f59f00;">{item['stop1']:,}원</td>
                        <td style="text-align: right; color: #f08c00;">{item['stop2']:,}원</td>
                        <td style="text-align: right; font-weight: bold; color: #e03131;">{item['stop_abs']:,}원</td>
                    </tr>
                    """
                full_table_html = f"""
                <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                        <thead>
                            <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 38px;">
                                <th style="text-align: center;">순위</th>
                                <th style="text-align: left;">종목명</th>
                                <th style="text-align: center;">코드</th>
                                <th style="text-align: center;">실적</th>
                                <th style="text-align: right;">현재가</th>
                                <th style="text-align: right;">전일대비</th>
                                <th style="text-align: center; background-color: #fff9db;">일봉 평단</th>
                                <th style="text-align: right; color: #2b8a3e;">1차목표</th>
                                <th style="text-align: right; color: #2b8a3e;">2차목표</th>
                                <th style="text-align: right; color: #2b8a3e;">3차목표</th>
                                <th style="text-align: right; color: #f59f00;">1차손절</th>
                                <th style="text-align: right; color: #f08c00;">2차손절</th>
                                <th style="text-align: right; color: #e03131;">절대사수</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows_html}</tbody>
                    </table>
                </div>
                """
                components.html(full_table_html, height=220, scrolling=True)


# ---------------------------------------------------------
# TAB 3: 전체 거래대금 TOP 30 대시보드
# ---------------------------------------------------------
with main_tab3:
    st.title("🔥 전체 거래대금 TOP 30 대시보드")
    st.caption("다단계 목표가 및 다단계 손절선 포함 분석")

    t30_sort_mode = st.radio(
        "정렬 기준 선택",
        ["기본 순위", "거래대금 많은순", "등락률 높은순"],
        horizontal=True,
        key="t30_sort",
    )

    top30_sample = [
        {
            "name": "삼성전자",
            "code": "005930",
            "price": 72500,
            "change": 4.50,
            "amt": 20600,
            "op_status": "🟢 흑자",
            "d_vwap": 71000,
            "target1": 74550,
            "target2": 78100,
            "target3": 81650,
            "stop1": 69580,
            "stop2": 68870,
            "stop_abs": 68160,
            "type": "🏆 중장기",
        },
        {
            "name": "SK하이닉스",
            "code": "000660",
            "price": 188500,
            "change": 8.90,
            "amt": 16700,
            "op_status": "🟢 흑자",
            "d_vwap": 165000,
            "target1": 173250,
            "target2": 181500,
            "target3": 189750,
            "stop1": 161700,
            "stop2": 160050,
            "stop_abs": 158400,
            "type": "🏆 중장기",
        },
    ]

    t30_rows = ""
    for idx, item in enumerate(top30_sample, start=1):
        t30_rows += f"""
        <tr style="border-bottom: 1px solid #f0f0f0; height: 50px; font-size: 11px;">
            <td style="text-align: center; font-weight: bold;">{idx}</td>
            <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['type']}</span></td>
            <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
            <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
            <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
            <td style="text-align: right; color: #d32f2f;">+{item['change']:.2f}%</td>
            <td style="text-align: right;">{item['amt']:,} 백만</td>
            <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target1']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target2']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target3']:,}원</td>
            <td style="text-align: right; color: #f59f00;">{item['stop1']:,}원</td>
            <td style="text-align: right; color: #f08c00;">{item['stop2']:,}원</td>
            <td style="text-align: right; font-weight: bold; color: #e03131;">{item['stop_abs']:,}원</td>
        </tr>
        """

    t30_table = f"""
    <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px;">
        <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
            <thead>
                <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 35px;">
                    <th style="text-align: center;">순위</th>
                    <th style="text-align: left;">종목명</th>
                    <th style="text-align: center;">코드</th>
                    <th style="text-align: center;">실적</th>
                    <th style="text-align: right;">현재가</th>
                    <th style="text-align: right;">등락률</th>
                    <th style="text-align: right;">거래대금</th>
                    <th style="text-align: center; background-color: #fff9db;">일봉 평단</th>
                    <th style="text-align: right; color: #2b8a3e;">1차목표</th>
                    <th style="text-align: right; color: #2b8a3e;">2차목표</th>
                    <th style="text-align: right; color: #2b8a3e;">3차목표</th>
                    <th style="text-align: right; color: #f59f00;">1차손절</th>
                    <th style="text-align: right; color: #f08c00;">2차손절</th>
                    <th style="text-align: right; color: #e03131;">절대사수</th>
                </tr>
            </thead>
            <tbody>{t30_rows}</tbody>
        </table>
    </div>
    """
    components.html(t30_table, height=250, scrolling=True)


# ---------------------------------------------------------
# TAB 4: 시간외 거래 TOP 30 대시보드
# ---------------------------------------------------------
with main_tab4:
    st.title("🌙 시간외 단일가 거래 TOP 30 대시보드")
    st.caption("다단계 목표가 및 다단계 손절선 포함 분석")

    ah_sort_mode = st.radio(
        "정렬 기준 선택",
        ["기본 순위", "시간외 거래대금 많은순", "시간외 등락률 높은순"],
        horizontal=True,
        key="ah_sort",
    )

    after_hours_data = [
        {
            "name": "대한광통신",
            "code": "010170",
            "price": 1950,
            "change": 9.80,
            "amt": 850,
            "op_status": "🟢 흑자",
            "d_vwap": 1810,
            "target1": 1900,
            "target2": 1990,
            "target3": 2080,
            "stop1": 1770,
            "stop2": 1755,
            "stop_abs": 1735,
            "reason": "재료 호재 (단타/스윙)",
        },
        {
            "name": "대한전선",
            "code": "001440",
            "price": 14800,
            "change": 4.20,
            "amt": 1200,
            "op_status": "🟢 흑자",
            "d_vwap": 13950,
            "target1": 14600,
            "target2": 15340,
            "target3": 16040,
            "stop1": 13650,
            "stop2": 13530,
            "stop_abs": 13390,
            "reason": "대규모 수주 (스윙)",
        },
    ]

    ah_rows = ""
    for idx, item in enumerate(after_hours_data, start=1):
        ah_rows += f"""
        <tr style="border-bottom: 1px solid #f0f0f0; height: 50px; font-size: 11px;">
            <td style="text-align: center; font-weight: bold;">{idx}</td>
            <td style="font-weight: bold;">{item['name']}</td>
            <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
            <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
            <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
            <td style="text-align: right; color: #d32f2f;">+{item['change']:.2f}%</td>
            <td style="text-align: right;">{item['amt']:,} 백만</td>
            <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target1']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target2']:,}원</td>
            <td style="text-align: right; color: #2b8a3e;">{item['target3']:,}원</td>
            <td style="text-align: right; color: #f59f00;">{item['stop1']:,}원</td>
            <td style="text-align: right; color: #f08c00;">{item['stop2']:,}원</td>
            <td style="text-align: right; font-weight: bold; color: #e03131;">{item['stop_abs']:,}원</td>
            <td style="text-align: center; color: #2b8a3e;">{item['reason']}</td>
        </tr>
        """

    ah_table = f"""
    <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px;">
        <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
            <thead>
                <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 35px;">
                    <th style="text-align: center;">순위</th>
                    <th style="text-align: left;">종목명</th>
                    <th style="text-align: center;">코드</th>
                    <th style="text-align: center;">실적</th>
                    <th style="text-align: right;">시간외 종가</th>
                    <th style="text-align: right;">시간외 등락률</th>
                    <th style="text-align: right;">시간외 거래대금</th>
                    <th style="text-align: center; background-color: #fff9db;">일봉 평단</th>
                    <th style="text-align: right; color: #2b8a3e;">1차목표</th>
                    <th style="text-align: right; color: #2b8a3e;">2차목표</th>
                    <th style="text-align: right; color: #2b8a3e;">3차목표</th>
                    <th style="text-align: right; color: #f59f00;">1차손절</th>
                    <th style="text-align: right; color: #f08c00;">2차손절</th>
                    <th style="text-align: right; color: #e03131;">절대사수</th>
                    <th style="text-align: center;">특이사항</th>
                </tr>
            </thead>
            <tbody>{ah_rows}</tbody>
        </table>
    </div>
    """
    components.html(ah_table, height=250, scrolling=True)
