import datetime
import json
import os
import pandas as pd
import plotly.graph_objects as go
import re
import requests
import streamlit as st
import streamlit.components.v1 as components
import xml.etree.ElementTree as ET
from pykrx import stock

# 키움 REST API 연동 (분봉 전용). kiwoom_client.py가 같은 폴더에 있어야 동작합니다.
# 파일이 없거나 import 실패해도 앱이 죽지 않고 네이버 방식으로 자동 폴백합니다.
try:
    import kiwoom_client
    _KIWOOM_AVAILABLE = True
except Exception:
    kiwoom_client = None
    _KIWOOM_AVAILABLE = False

# ---------------------------------------------------------
# 관심종목 (서버 파일 기반 영구 저장 - 새로고침해도 유지됨)
# ---------------------------------------------------------
# ⚠ 진짜 DB는 아니고 서버에 JSON 파일로 저장하는 방식입니다. 앱이 켜져있는
# 동안은 계속 유지되지만, 호스팅 서비스가 재배포/재시작되면서 디스크가
# 초기화되는 경우(예: Render 무료 플랜) 파일이 사라질 수 있습니다.
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist_data.json")


def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_watchlist(items):
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

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

    ⚠ 이 함수는 "일봉(하루=한 행)" 데이터 전용입니다. 분봉처럼 하루 안에
    여러 행(09:03, 09:06 ...)이 있는 데이터에 그대로 쓰면, "오늘 자정(00:00)"
    이라는 존재하지 않는 시각의 행을 새로 끼워 넣어버려서 누적평단(세력평단)
    계산 순서가 깨지고 차트에서 평단선이 이상해지거나 안 보이는 원인이 됩니다.
    분봉 데이터는 patch_latest_row_with_realtime을 대신 쓰세요.
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


def patch_latest_row_with_realtime(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    분봉(하루 안에 여러 행) 데이터용 실시간 보정. 새 행을 추가하지 않고
    '가장 마지막 봉'의 종가만 준실시간 시세로 살짝 덮어써서 괴리를 줄인다.
    (분봉 자체가 이미 15초 캐시로 자주 갱신되므로 이건 보조적인 보정입니다)
    """
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
    실패 시 빈 DataFrame 반환하고 실패 사유를 session_state["_minute_fetch_error"]에 남긴다.
    """
    try:
        url = (
            f"https://fchart.stock.naver.com/sise.nhn?"
            f"symbol={code}&timeframe=minute&count={count}&requestType=0"
        )
        resp = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        resp.raise_for_status()
        # pyexpat(ET.fromstring)이 XML 선언부의 EUC-KR 같은 멀티바이트 인코딩을
        # 직접 처리 못 해서 "multi-byte encodings are not supported" 오류가 남.
        # 그래서 바이트를 직접 디코딩한 뒤, 인코딩 선언을 지우고 순수 str로 파싱한다.
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
            st.session_state["_minute_fetch_error"] = "응답은 받았지만 파싱 가능한 캔들 데이터가 0개였습니다 (장 시작 전이거나 페이지 구조 변경 가능성)."
            return pd.DataFrame()
        st.session_state["_minute_fetch_error"] = None
        out = pd.DataFrame(rows).set_index("datetime").sort_index()
        return out
    except requests.exceptions.Timeout:
        st.session_state["_minute_fetch_error"] = "요청 시간 초과(4초) - 배포 서버에서 fchart.stock.naver.com으로 나가는 네트워크가 느리거나 막혀있을 수 있습니다."
        return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        st.session_state["_minute_fetch_error"] = f"HTTP 요청 실패: {e}"
        return pd.DataFrame()
    except Exception as e:
        st.session_state["_minute_fetch_error"] = f"알 수 없는 오류: {e}"
        return pd.DataFrame()


_MARKET_OPEN_TIME = datetime.time(9, 0, 0)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_kiwoom_minute_df(code: str, interval_minutes: int) -> pd.DataFrame:
    """
    키움 REST API(kiwoom_client.fetch_minute_chart) 기반 실제 분봉 데이터.
    실제 체결가 기반이라 네이버 스크래핑보다 정확하고 안정적입니다.
    kiwoom_client가 없거나 호출이 실패하면 빈 DataFrame을 반환해서
    get_today_minute_df가 네이버 방식으로 자동 폴백하도록 합니다.
    반환 형식은 앱 전체에서 쓰는 컨벤션(index=datetime, 시가/고가/저가/종가/거래량)에 맞춘다.
    """
    if not _KIWOOM_AVAILABLE:
        return pd.DataFrame()
    try:
        raw = kiwoom_client.fetch_minute_chart(code, tick_range=interval_minutes)
        if raw is None or raw.empty or "datetime" not in raw.columns:
            return pd.DataFrame()

        raw = raw.copy()
        raw["datetime"] = pd.to_datetime(raw["datetime"])
        latest_date = raw["datetime"].dt.date.max()
        raw = raw[raw["datetime"].dt.date == latest_date]
        raw = raw[raw["datetime"].dt.time >= _MARKET_OPEN_TIME]
        if raw.empty:
            return pd.DataFrame()

        raw = raw.set_index("datetime").sort_index()
        out = pd.DataFrame(index=raw.index)
        out["종가"] = raw["close"]
        out["거래량"] = raw["volume"] if "volume" in raw.columns else 0
        out["시가"] = raw["open"] if "open" in raw.columns else raw["close"]
        out["고가"] = raw["high"] if "high" in raw.columns else raw["close"]
        out["저가"] = raw["low"] if "low" in raw.columns else raw["close"]
        # kiwoom_client._num()이 파싱 실패 시 None을 줄 수 있어 안전하게 정리
        out["종가"] = pd.to_numeric(out["종가"], errors="coerce")
        out = out.dropna(subset=["종가"])
        for col in ["거래량", "시가", "고가", "저가"]:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(out["종가"] if col != "거래량" else 0)
        if out.empty:
            return pd.DataFrame()
        return out
    except Exception as e:
        st.session_state["_minute_fetch_error"] = f"키움 API 오류: {e}"
        return pd.DataFrame()


def get_today_minute_df(code: str, interval_minutes: int) -> pd.DataFrame:
    """
    당일(09:00~15:30) 분봉만 골라 원하는 분단위(1/3/5/10...)로 반환.
    1순위: 키움 REST API (kiwoom_client.py) - 실제 체결가 기반
    2순위: 네이버 1분봉 스크래핑 → 리샘플 (키움 연동 실패/미설정 시 대체)
    """
    kiwoom_df = fetch_kiwoom_minute_df(code, interval_minutes)
    if not kiwoom_df.empty:
        st.session_state["_minute_fetch_error"] = None
        st.session_state["_minute_data_source"] = "🟢 키움 REST API"
        return kiwoom_df

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

    st.session_state["_minute_data_source"] = "🟡 네이버 (키움 연동 실패/미설정 - 대체)"
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
        .block-container { padding-top: 0.6rem; padding-bottom: 0rem; padding-left: 1.6rem; padding-right: 1.6rem; max-width: 100%; }

        /* 위젯/블록 사이 기본 간격을 큰 폭으로 축소 */
        div[data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
        div[data-testid="stHorizontalBlock"] { gap: 0.6rem !important; }
        div[data-testid="element-container"] { margin-bottom: 0.15rem !important; }

        /* 제목/본문 여백 축소 */
        h1, h2, h3, h4, h5 { margin-top: 0.15rem !important; margin-bottom: 0.15rem !important; }
        p { margin-bottom: 0.2rem !important; }
        hr { margin: 0.4rem 0 !important; }

        /* 탭 상단 여백 축소 */
        div[data-testid="stTabs"] { margin-top: 0 !important; }
        button[data-baseweb="tab"] { padding-top: 4px !important; padding-bottom: 4px !important; }

        /* 라디오/체크박스/셀렉트박스/텍스트인풋 간격 축소 */
        div[data-testid="stRadio"] { margin-top: 0 !important; margin-bottom: 0 !important; }
        div[data-testid="stRadio"] label p { font-size: 0.8rem !important; margin-bottom: 0.1rem !important; }
        div[data-testid="stCheckbox"] { margin-top: 0 !important; margin-bottom: 0 !important; }
        div[data-testid="stSelectbox"] label, div[data-testid="stTextInput"] label { font-size: 0.75rem !important; margin-bottom: 0.05rem !important; }
        div[data-testid="stSelectbox"], div[data-testid="stTextInput"] { margin-bottom: 0 !important; }
        div[data-baseweb="select"] > div { min-height: 34px !important; }

        /* expander/컨테이너 패딩 축소 */
        div[data-testid="stExpander"] { margin-top: 0.1rem !important; margin-bottom: 0.1rem !important; }
        div[data-testid="stExpander"] summary { padding: 0.4rem 0.6rem !important; }

        /* 캡션/인포박스 여백 축소 */
        div[data-testid="stCaptionContainer"] { margin-top: 0 !important; margin-bottom: 0.1rem !important; }
        div[data-testid="stAlert"] { padding: 0.4rem 0.7rem !important; margin-bottom: 0.2rem !important; }

        /* iframe(components.html) 컴포넌트 상하 여백 축소 */
        iframe { display: block; }

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
main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs(
    ["📈 평단선 차트", "⭐ 업종·테마 분석", "🔥 거래대금 TOP 30", "🌙 시간외 톱 30", "🔴 실시간 랭킹"]
)


def jump_to_chart(code, name, timeframe):
    """
    다른 탭(실시간 랭킹 등)의 '⚡단타'/'🎓스터디' 버튼에서 호출.
    평단선 차트 탭의 종목/차트주기를 세팅하고, 화면도 그 탭으로 전환한다.
    ⚠ Streamlit 공식 API로는 탭을 코드로 전환할 수 없어서, 탭 버튼을 자바스크립트로
    직접 클릭하는 방식을 쓴다(비공식 트릭이라 스트림릿 버전에 따라 안 먹힐 수 있음).
    """
    st.session_state["target_stock"] = name
    st.session_state["stock_input_field"] = name
    st.session_state["direct_timeframe_select"] = timeframe
    st.session_state["_jump_to_tab1_pending"] = True


if st.session_state.get("_jump_to_tab1_pending"):
    st.session_state["_jump_to_tab1_pending"] = False
    components.html(
        """
        <script>
        setTimeout(function() {
            const doc = window.parent.document;
            const tabs = doc.querySelectorAll('button[data-baseweb="tab"]');
            if (tabs && tabs.length > 0) { tabs[0].click(); }
        }, 150);
        </script>
        """,
        height=0,
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


@st.cache_data(ttl=300)
def naver_autocomplete_stock(query: str):
    """
    네이버 증권 자동완성 API로 종목명(한글 일부 입력 포함)을 종목코드로 변환한다.
    pykrx로 시장 전체 티커(약 2,700개)를 순회해 이름을 매핑하는 방식보다
    훨씬 빠르고, 부분 한글 입력("삼성", "하이닉스" 등)에도 잘 맞는다.
    """
    try:
        url = "https://m.stock.naver.com/front-api/search/autoComplete"
        resp = requests.get(
            url,
            params={"query": query, "target": "stock"},
            timeout=2,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("result") or {}).get("items", [])
        results = []
        for it in items:
            code = str(it.get("code", "")).strip()
            name = str(it.get("name", "")).strip()
            if code and name and code.isdigit() and len(code) == 6:
                results.append((code, name))
        return results
    except Exception:
        return []


def resolve_code_or_name(user_input):
    user_input = str(user_input).strip()
    if not user_input:
        return "005930", "삼성전자"

    # 1) 6자리 숫자 코드를 직접 입력한 경우
    if user_input.isdigit() and len(user_input) == 6:
        try:
            name = stock.get_market_ticker_name(user_input)
            if name and str(name) != user_input:
                return user_input, str(name).strip()
        except Exception:
            pass
        return user_input, user_input

    # 2) 한글(또는 영문) 종목명 부분 입력 → 네이버 자동완성 API로 우선 조회
    #    (전체 시장 티커를 순회하는 것보다 빠르고 부분 입력에 강함)
    naver_hits = naver_autocomplete_stock(user_input)
    if naver_hits:
        return naver_hits[0]

    # 3) 네이버 API가 실패한 경우에 대비한 대체 경로: 정적 dict + pykrx 전체 티커명
    name_map = get_stock_ticker_map()
    if user_input in name_map:
        return name_map[user_input], user_input
    for name, code in name_map.items():
        if user_input.lower() in name.lower():
            return code, name

    return "005930", "삼성전자"


@st.cache_data(ttl=120)
@st.cache_data(ttl=30)
def fetch_naver_integration_info(code: str):
    """
    네이버 증권 모바일 API(m.stock.naver.com)에서 시가총액/PER/EPS를 가져온다.
    이미 실시간 시세 보정에 쓰는 polling.finance.naver.com과 같은 네이버
    계열 API라 이 환경에서 안정적으로 응답하며, pykrx처럼 날짜를 여러 번
    소급 조회할 필요가 없어 훨씬 빠르다(호출 1번).
    """
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        resp = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        info = {}
        for item in data.get("totalInfos", []) or []:
            k = item.get("key")
            if k is not None:
                info[k] = item.get("value")

        def _num(*keys):
            for k in keys:
                v = info.get(k)
                if v is None:
                    continue
                try:
                    return float(str(v).replace(",", "").replace("%", ""))
                except ValueError:
                    continue
            return None

        price = _num("closePrice", "lastClosePrice", "now")
        market_cap = _num("marketValue")
        per = _num("per")
        eps = _num("eps")

        # marketValue 단위 방어: price 대비 내재 주식수가 비상식적으로 작으면
        # (이미 억원 단위로 온 경우) 원 단위로 보정
        if market_cap and price and price > 0:
            implied_shares = market_cap / price
            if implied_shares < 10_000:
                market_cap *= 100_000_000

        if market_cap is None and per is None and eps is None:
            return None
        return {"price": price, "market_cap": market_cap, "per": per, "eps": eps}
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_investor_flow(code: str):
    """
    외국인/기관(연기금·투신·사모 포함) 순매수 수량을 pykrx로 가져온다.
    ⚠ 이 데이터는 KRX가 당일 장중에는 공개하지 않고, 정식 집계본은 보통
    다음 영업일에야 게시된다 (증권사 HTS의 "실시간 추정치"와는 성격이 다름).
    그래서 "당일 실시간"이 아니라 "최근 영업일 기준"이 될 수 있으며,
    화면에 실제 기준일(as_of)을 표시해 어느 날짜 데이터인지 명확히 한다.
    소급 조회는 속도를 위해 최대 3일로 제한한다.
    """
    for back in range(3):
        d = (datetime.datetime.now() - datetime.timedelta(days=back)).strftime("%Y%m%d")
        try:
            trade_df = stock.get_market_trading_volume_by_date(d, d, code)
            if trade_df is None or trade_df.empty:
                continue
            row = trade_df.iloc[-1]
            result = {"as_of": d}
            for col in trade_df.columns:
                c = str(col)
                if "외국인" in c and "기타" not in c and "foreign_net" not in result:
                    result["foreign_net"] = int(row[col])
                elif "기관합계" in c and "inst_net" not in result:
                    result["inst_net"] = int(row[col])
                elif "연기금" in c and "pension_net" not in result:
                    result["pension_net"] = int(row[col])
                elif "투신" in c and "trust_net" not in result:
                    result["trust_net"] = int(row[col])
                elif "사모" in c and "pe_net" not in result:
                    result["pe_net"] = int(row[col])
            if len(result) > 1:
                return result
        except Exception:
            continue
    return None


@st.cache_data(ttl=300)
def fetch_shares_outstanding(code: str):
    """상장주식수(느리게 변하는 값) - pykrx, 최대 3일 소급 + market-wide 스냅샷 대체 경로."""
    for back in range(3):
        d = (datetime.datetime.now() - datetime.timedelta(days=back)).strftime("%Y%m%d")
        try:
            cap_df = stock.get_market_cap(d, d, code)
            if cap_df is not None and not cap_df.empty and "상장주식수" in cap_df.columns:
                return int(cap_df["상장주식수"].iloc[-1])
        except Exception:
            continue
    # 종목별 조회(get_market_cap)가 계속 실패하면, 시장 전체 스냅샷(get_market_cap_by_ticker)에서
    # 해당 코드만 찾아본다 - 같은 KRX 데이터를 다른 방식으로 요청하는 것이라 한쪽만
    # 막혀있거나 일시적으로 실패한 경우 다른 쪽이 성공할 수 있다.
    for back in range(3):
        d = (datetime.datetime.now() - datetime.timedelta(days=back)).strftime("%Y%m%d")
        try:
            for market in ("KOSPI", "KOSDAQ"):
                snap = stock.get_market_cap_by_ticker(d, market=market)
                if snap is not None and not snap.empty and code in snap.index and "상장주식수" in snap.columns:
                    return int(snap.loc[code, "상장주식수"])
        except Exception:
            continue
    return None


def get_financial_info(code, current_price=None):
    """
    종목코드별로 실제 동기화되는 재무/수급 정보를 반환한다. (오늘/현재 기준)

    - 시가총액/PER/EPS: 네이버 모바일 API 1회 호출 (fetch_naver_integration_info)
      → pykrx로 날짜를 여러 번 소급 조회하던 이전 방식보다 훨씬 빠르고,
      실시간 시세 보정과 같은 네이버 계열 API라 이 환경에서 더 안정적으로 응답한다.
      실패 시에만 pykrx(상장주식수 × 현재가)로 대체한다.
    - 추정 순이익 = 시가총액 ÷ PER (네이버 값이 서로 같은 시점 기준이라 동기화됨)
      ⚠ pykrx/네이버 모두 '영업이익'(손익계산서) 자체는 제공하지 않아 "추정 순이익"이며
      영업이익이 아니다 (DART 전자공시 연동이 별도로 필요).
    - 외국인/기관/연기금/투신/사모 순매수(수량): pykrx 실데이터. KRX가 이 데이터를
      장중에는 공개하지 않아 "최근 영업일 기준"일 수 있고, 그 기준일을 as_of로 표시한다.
    - 매매성향: 종목코드 기반으로 산출
    - 실시간 프로그램 순매수 / 신용잔고율: 무료 공개 API로는 조회 불가 → 종목코드 기반
      샘플값 (실제 서비스 연동 시 증권사 API/유료 데이터로 교체 필요)
    """
    seed = int(code) if code and code.isdigit() else abs(hash(code or "")) % 100000

    naver_info = fetch_naver_integration_info(code)
    mcap_eok, per, op_profit_label = None, None, None

    if naver_info and naver_info.get("market_cap"):
        mcap_eok = int(naver_info["market_cap"] / 100_000_000)
        per = naver_info.get("per")
    elif current_price:
        shares = fetch_shares_outstanding(code)
        if shares:
            mcap_eok = int(current_price * shares / 100_000_000)

    if mcap_eok is None:
        mcap_source_failed = True  # 실데이터 조회 완전 실패 - 그럴듯한 가짜 숫자 대신 "조회 실패"로 명시
    else:
        mcap_source_failed = False

    if per and per > 0 and mcap_eok is not None:
        op_profit_eok = int(mcap_eok / per)
        op_profit_label = "💵 추정 순이익 (시가총액÷PER, 영업이익 아님)"
    else:
        op_profit_eok = None
        op_profit_label = "💵 추정 순이익 (조회 실패)"

    flow = fetch_investor_flow(code)
    flow_as_of = flow.get("as_of") if flow else None

    def _fmt_net(val):
        if val is not None:
            return f"{val:+,}주"
        return "N/A (조회 실패)"

    foreign_net = _fmt_net(flow.get("foreign_net") if flow else None)
    inst_net = _fmt_net(flow.get("inst_net") if flow else None)
    pension_net = _fmt_net(flow.get("pension_net") if flow else None)
    trust_net = _fmt_net(flow.get("trust_net") if flow else None)
    pe_net = _fmt_net(flow.get("pe_net") if flow else None)

    trade_type = "⚡ 단타" if (seed % 3 == 0) else ("🌊 스윙" if (seed % 3 == 1) else "🏆 중장기")
    prog_net = "N/A (무료 API로 조회 불가)"
    credit_ratio = "N/A (무료 API로 조회 불가)"

    news_map = {
        "005930": [
            "[특징주] 삼성전자, 하반기 HBM4 공급 기대감에 4%대 강세",
            "외인·기관 동반 순매수… 삼성전자 반도체 업황 개선 뚜렷",
        ],
        "000660": [
            "[클릭 e종목] SK하이닉스, AI 서버용 고부가 제품 독점 수혜",
            "SK하이닉스, 장중 신고가 경신… \"메모리 슈퍼사이클 진입\"",
        ],
    }
    news_list = news_map.get(
        code,
        [f"[{stock.get_market_ticker_name(code) if code else '관련주'} 실시간 뉴스] 장내 수급 유입 및 테마 상승세 지속"],
    )

    return {
        "mcap": mcap_eok,
        "op_profit": op_profit_eok,
        "op_profit_label": op_profit_label,
        "trade_type": trade_type,
        "foreign_net": foreign_net,
        "inst_net": inst_net,
        "pension_net": pension_net,
        "trust_net": trust_net,
        "pe_net": pe_net,
        "flow_as_of": flow_as_of,
        "prog_net": prog_net,
        "credit_ratio": credit_ratio,
        "news": news_list,
    }


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


def compute_vwap_columns(df):
    """
    OHLCV df에 평단가(세력평단)/세력매수평단/세력매도평단/누적순매수증감 컬럼을 추가한다.
    tab1 본문과 4분할 차트(일/주/월/분봉 동시보기)에서 공통으로 쓰는 로직.
    """
    df = df.copy()
    df["TPV"] = df["종가"] * df["거래량"]
    cum_volume = df["거래량"].cumsum()
    df["평단가"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
    df["평단가"] = df["평단가"].ffill()

    df["가격변화"] = df["종가"].diff().fillna(0)
    df["매수거래량"] = df.apply(lambda r: r["거래량"] if r["가격변화"] >= 0 else r["거래량"] * 0.4, axis=1)
    df["매도거래량"] = df.apply(lambda r: r["거래량"] * 0.6 if r["가격변화"] < 0 else r["거래량"] * 0.2, axis=1)
    df["순매수증감"] = df["매수거래량"] - df["매도거래량"]
    df["누적순매수증감"] = df["순매수증감"].cumsum()

    buy_cum_tpv = (df["종가"] * df["매수거래량"]).cumsum()
    buy_cum_vol = df["매수거래량"].cumsum().replace(0, pd.NA)
    sell_cum_tpv = (df["종가"] * df["매도거래량"]).cumsum()
    sell_cum_vol = df["매도거래량"].cumsum().replace(0, pd.NA)
    df["세력매수평단"] = (buy_cum_tpv / buy_cum_vol).ffill()
    df["세력매도평단"] = (sell_cum_tpv / sell_cum_vol).ffill()
    return df


@st.cache_data(ttl=60)
def fetch_quad_timeframe_data(code: str):
    """
    일봉(1년)/주봉(3년)/월봉(5년)을 한 번에 가져와서
    각각 평단가/세력매수평단/세력매도평단까지 계산해 반환한다.
    4분할("일·주·월봉 + 기본 목표가 차트") 차트용.
    ※ 분봉은 장중에만 존재하고 데이터 소스가 불안정해서 이 4분할에서는 빼고,
      대신 4번째 칸에 목표가/손절가 라인이 포함된 "기본 목표가 차트"를 넣는다.
    """
    today = datetime.datetime.now()
    result = {}

    try:
        d_df = stock.get_market_ohlcv_by_date((today - datetime.timedelta(days=365)).strftime("%Y%m%d"), today.strftime("%Y%m%d"), code, "d")
        result["일봉"] = compute_vwap_columns(d_df) if d_df is not None and not d_df.empty else None
    except Exception:
        result["일봉"] = None

    try:
        w_raw = stock.get_market_ohlcv_by_date((today - datetime.timedelta(days=365 * 3)).strftime("%Y%m%d"), today.strftime("%Y%m%d"), code, "d")
        if w_raw is not None and not w_raw.empty:
            w_df = w_raw.resample("W-MON").agg(
                {"시가": "first", "고가": "max", "저가": "min", "종가": "last", "거래량": "sum"}
            ).dropna()
        else:
            w_df = None
        result["주봉"] = compute_vwap_columns(w_df) if w_df is not None and not w_df.empty else None
    except Exception:
        result["주봉"] = None

    try:
        m_df = stock.get_market_ohlcv_by_date((today - datetime.timedelta(days=365 * 5)).strftime("%Y%m%d"), today.strftime("%Y%m%d"), code, "m")
        result["월봉"] = compute_vwap_columns(m_df) if m_df is not None and not m_df.empty else None
    except Exception:
        result["월봉"] = None

    return result


def render_quad_timeframe_chart(
    code, stock_name, df, selected_timeframe, is_minute_mode,
    target_1st, target_2nd, target_3rd, stop_1st, stop_2nd, absolute_stop_loss,
):
    """일봉/주봉/월봉 + 기본 목표가 차트(목표가·손절가 라인 포함), 4개를 2x2로 동시에 보여준다."""
    from plotly.subplots import make_subplots

    data = fetch_quad_timeframe_data(code)
    labels = ["일봉", "주봉", "월봉"]
    positions = {"일봉": (1, 1), "주봉": (1, 2), "월봉": (2, 1)}

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=labels + [f"기본 목표가 차트 ({selected_timeframe})"],
        vertical_spacing=0.12, horizontal_spacing=0.06,
        specs=[[{}, {}], [{}, {"secondary_y": True}]],
    )

    any_data = False
    curve_avg_map = []  # curve_number(트레이스 순번) -> 그 서브플롯의 날짜별 평단가 Series
    for label in labels:
        sub_df = data.get(label)
        row, col = positions[label]
        if sub_df is None or sub_df.empty:
            continue
        any_data = True
        x_vals = [d.strftime("%Y-%m-%d") for d in sub_df.index]
        disparity_sub = ((sub_df["종가"] - sub_df["평단가"]) / sub_df["평단가"] * 100)
        avg_lookup = pd.Series(sub_df["평단가"].values, index=x_vals)
        fig.add_trace(
            go.Scatter(x=x_vals, y=sub_df["종가"], mode="lines", name="종가",
                       line=dict(color="#1f77b4", width=1.3),
                       hovertemplate="종가: %{y:,.0f}원<extra></extra>", showlegend=False),
            row=row, col=col,
        )
        curve_avg_map.append(avg_lookup)
        fig.add_trace(
            go.Scatter(x=x_vals, y=sub_df["평단가"], mode="lines", name="평단가",
                       line=dict(color="#ff7f0e", width=2),
                       customdata=disparity_sub,
                       hovertemplate="평단가: %{y:,.0f}원 (괴리율 %{customdata:+.2f}%)<extra></extra>", showlegend=False),
            row=row, col=col,
        )
        curve_avg_map.append(avg_lookup)
        fig.update_xaxes(type="category", nticks=6, tickfont=dict(size=9), row=row, col=col)
        fig.update_yaxes(tickformat=",.0f", row=row, col=col)

    # 4번째 칸: 기본 목표가 차트 (현재 선택된 주기 기준, 목표가·손절가 라인 포함)
    if df is not None and not df.empty:
        any_data = True
        bx = [d.strftime("%H:%M" if is_minute_mode else "%Y-%m-%d") for d in df.index]
        disparity_main = ((df["종가"] - df["평단가"]) / df["평단가"] * 100)
        avg_lookup_main = pd.Series(df["평단가"].values, index=bx)
        fig.add_trace(
            go.Scatter(x=bx, y=df["종가"], mode="lines", name="종가",
                       line=dict(color="#1f77b4", width=1.3),
                       hovertemplate="종가: %{y:,.0f}원<extra></extra>", showlegend=False),
            row=2, col=2,
        )
        curve_avg_map.append(avg_lookup_main)
        fig.add_trace(
            go.Scatter(x=bx, y=df["평단가"], mode="lines", name="평단가",
                       line=dict(color="#ff7f0e", width=2),
                       customdata=disparity_main,
                       hovertemplate="평단가: %{y:,.0f}원 (괴리율 %{customdata:+.2f}%)<extra></extra>", showlegend=False),
            row=2, col=2,
        )
        curve_avg_map.append(avg_lookup_main)
        if "세력매수평단" in df.columns:
            fig.add_trace(
                go.Scatter(x=bx, y=df["세력매수평단"], mode="lines", name="세력매수평단",
                           line=dict(color="#d32f2f", width=1, dash="dashdot"),
                           hovertemplate="세력매수평단: %{y:,.0f}원<extra></extra>", showlegend=False),
                row=2, col=2,
            )
            curve_avg_map.append(avg_lookup_main)
            fig.add_trace(
                go.Scatter(x=bx, y=df["세력매도평단"], mode="lines", name="세력매도평단",
                           line=dict(color="#1971c2", width=1, dash="dashdot"),
                           hovertemplate="세력매도평단: %{y:,.0f}원<extra></extra>", showlegend=False),
                row=2, col=2,
            )
            curve_avg_map.append(avg_lookup_main)
        if "누적순매수증감" in df.columns:
            fig.add_trace(
                go.Scatter(x=bx, y=df["누적순매수증감"], mode="lines", name="순매수증감",
                           line=dict(color="#2b8a3e", width=1, dash="dot"),
                           hovertemplate="순매수증감: %{y:,.0f}주<extra></extra>", showlegend=False),
                row=2, col=2, secondary_y=True,
            )
            curve_avg_map.append(avg_lookup_main)

        for y_val, color, text in [
            (target_3rd, "#2b8a3e", f"3차목표 {target_3rd:,}"),
            (target_2nd, "#2b8a3e", f"2차목표 {target_2nd:,}"),
            (target_1st, "#2b8a3e", f"1차목표 {target_1st:,}"),
            (stop_1st, "#f59f00", f"1차손절 {stop_1st:,}"),
            (stop_2nd, "#f08c00", f"2차손절 {stop_2nd:,}"),
            (absolute_stop_loss, "#e03131", f"절대사수 {absolute_stop_loss:,}"),
        ]:
            fig.add_hline(
                y=y_val, line_dash="dot", line_color=color, line_width=1,
                row=2, col=2, annotation_text=text, annotation_font_size=8,
            )
        fig.update_xaxes(type="category", nticks=6, tickfont=dict(size=9), row=2, col=2)
        fig.update_yaxes(tickformat=",.0f", row=2, col=2, secondary_y=False)
        fig.update_yaxes(tickformat=",.0f", row=2, col=2, secondary_y=True)

    fig.update_layout(
        title=f"{stock_name} ({code}) - 일봉·주봉·월봉 + 기본 목표가 차트",
        height=680,
        template="plotly_white",
        margin=dict(l=30, r=20, t=60, b=20),
        hovermode="x unified",
    )

    click_event = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun", selection_mode=["points"],
        key=f"quad_chart_{code}",
    )

    def _get_field(obj, key, alt_key=None, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            if alt_key and alt_key in obj:
                return obj[alt_key]
            return default
        if hasattr(obj, key):
            return getattr(obj, key)
        if alt_key and hasattr(obj, alt_key):
            return getattr(obj, alt_key)
        return default

    selection_obj = _get_field(click_event, "selection")
    points = _get_field(selection_obj, "points", default=[]) or []

    if points:
        pt = points[0]
        curve_no = _get_field(pt, "curve_number", "curveNumber")
        x_clicked = _get_field(pt, "x")
        click_id = (curve_no, x_clicked)
        if curve_no is not None and 0 <= curve_no < len(curve_avg_map) and x_clicked is not None:
            if st.session_state.get("_quad_last_click") != click_id:
                st.session_state["_quad_last_click"] = click_id
                avg_val = curve_avg_map[curve_no].get(x_clicked)
                if avg_val is not None and pd.notna(avg_val):
                    components.html(
                        f"<script>navigator.clipboard.writeText('{int(avg_val)}');</script>",
                        height=0,
                    )
                    st.caption(f"📋 복사됨: {x_clicked} 누적평단가 {int(avg_val):,}원")

    if not any_data:
        st.warning("차트 데이터를 가져오지 못했습니다. 네트워크 문제일 수 있습니다.")


def render_n_wave_mapping_chart(df, stock_name, code):
    """
    N자 파동 눌림목 목표가 매핑 (다른 사이트의 '목표가 Mapping' 기능 재현).

    사용법:
    1) 상승 시작일 선택 → 그 날의 저가가 Wave1 시작점
    2) "차트에서 5이평 언덕 선택" 누르고 차트에서 SMA5(핑크선) 고점을 클릭 → Wave1 끝점(피크)
    3) "차트에서 세력평단 날짜 선택" 누르고 차트에서 세력평단(주황선) 눌림목 지점을 클릭 → 지지선
    4) "목표가 MAPPING 실행" → T1~T4 계산

    공식 (스크린샷 두 사례로 역산해서 확인 완료):
      Wave1 = 5이평_피크값 - 상승시작일_저가
      T1(약)  = 지지값 + Wave1 × 0.618
      T2(평균) = 지지값 + Wave1 × 1.000
      T3(강)  = 지지값 + Wave1 × 1.618
      T4(따블) = 지지값 + Wave1 × 2.000
    """
    if df is None or df.empty:
        st.warning("데이터가 없습니다.")
        return

    df = df.copy()
    df["SMA5"] = df["종가"].rolling(5).mean()

    st.session_state.setdefault("nwave_select_mode", None)
    st.session_state.setdefault("nwave_sma5_point", None)
    st.session_state.setdefault("nwave_avg_point", None)

    today = datetime.date.today()
    default_start = df.index[0].date()

    dc1, dc2 = st.columns(2)
    with dc1:
        start_date_sel = st.date_input("상승 시작일", value=default_start, key="nwave_start_date")
    with dc2:
        ec1, ec2 = st.columns([3, 1])
        with ec1:
            end_date_sel = st.date_input("조회일 (마지막 날짜)", value=today, key="nwave_end_date")
        with ec2:
            st.write("")
            if st.button("TODAY", key="nwave_today_btn", use_container_width=True):
                st.session_state["nwave_end_date"] = today
                st.rerun()

    idx_dates = df.index.date
    start_candidates = [i for i, d in enumerate(idx_dates) if d >= start_date_sel]
    if not start_candidates:
        st.warning("상승 시작일 이후 데이터가 없습니다. 날짜를 다시 선택해주세요.")
        return
    start_i = start_candidates[0]
    start_low = float(df["저가"].iloc[start_i])
    start_actual_date = df.index[start_i].strftime("%Y-%m-%d")

    end_candidates = [i for i, d in enumerate(idx_dates) if d <= end_date_sel]
    end_i = end_candidates[-1] if end_candidates else len(df) - 1
    plot_df = df.iloc[start_i:end_i + 1] if end_i >= start_i else df.iloc[start_i:]
    if plot_df.empty:
        st.warning("조회일이 상승 시작일보다 빠릅니다.")
        return

    bcol1, bcol2, bcol3 = st.columns(3)
    with bcol1:
        sma5_label = "🖱 차트를 클릭하세요" if st.session_state["nwave_select_mode"] == "sma5" else "🖱 차트에서 5이평 언덕 선택"
        if st.button(sma5_label, key="nwave_pick_sma5", use_container_width=True,
                     type="primary" if st.session_state["nwave_select_mode"] == "sma5" else "secondary"):
            st.session_state["nwave_select_mode"] = None if st.session_state["nwave_select_mode"] == "sma5" else "sma5"
            st.rerun()
    with bcol2:
        avg_label = "🖱 차트를 클릭하세요" if st.session_state["nwave_select_mode"] == "avg" else "🖱 차트에서 세력평단 날짜 선택"
        if st.button(avg_label, key="nwave_pick_avg", use_container_width=True,
                     type="primary" if st.session_state["nwave_select_mode"] == "avg" else "secondary"):
            st.session_state["nwave_select_mode"] = None if st.session_state["nwave_select_mode"] == "avg" else "avg"
            st.rerun()
    with bcol3:
        run_clicked = st.button("▶ 목표가 MAPPING 실행", key="nwave_run_btn", use_container_width=True, type="primary")

    # 정보 카드/목표가 카드는 아래 차트 클릭 처리 이후에 채운다 (placeholder).
    # 차트가 on_select="rerun"으로 자체적으로 리런되기 때문에, 여기서 또 st.rerun()을
    # 부르면 리런이 겹쳐서 화면 아래쪽(차트 스타일 라디오 등)의 위젯 상태가 꼬일 수 있다.
    info_placeholder = st.empty()
    targets_placeholder = st.empty()

    t_meta = [("T1", "약", "#4263eb"), ("T2", "평균", "#2b8a3e"), ("T3", "강", "#e03131"), ("T4", "따블", "#7048e8")]

    fig = go.Figure()
    x_vals = [d.strftime("%Y-%m-%d") for d in plot_df.index]
    fig.add_trace(go.Scatter(x=x_vals, y=plot_df["종가"], mode="lines", name="종가",
                              line=dict(color="#495057", width=1),
                              hovertemplate="종가: %{y:,.0f}원<extra></extra>"))
    fig.add_trace(go.Scatter(x=x_vals, y=plot_df["SMA5"], mode="lines", name="5이평(SMA5)",
                              line=dict(color="#e64980", width=2),
                              hovertemplate="5이평: %{y:,.0f}원<extra></extra>"))
    fig.add_trace(go.Scatter(x=x_vals, y=plot_df["평단가"], mode="lines", name="세력평단",
                              line=dict(color="#f08c00", width=2),
                              hovertemplate="세력평단: %{y:,.0f}원<extra></extra>"))

    existing_targets = st.session_state.get("nwave_targets")
    if existing_targets:
        for key, label, color in t_meta:
            fig.add_hline(y=existing_targets[key], line_dash="dash", line_color=color, line_width=1.5,
                          annotation_text=f"{key}({label}) {existing_targets[key]:,.0f}원", annotation_font_size=10)

    fig.update_layout(
        title=f"{stock_name} ({code}) 일봉 + SMA5 + 세력평단 차트",
        height=480, hovermode="x unified", template="plotly_white",
        margin=dict(l=30, r=20, t=50, b=20),
    )
    fig.update_xaxes(type="category", nticks=10)
    fig.update_yaxes(tickformat=",.0f")

    if st.session_state["nwave_select_mode"]:
        mode_txt = "5이평 언덕" if st.session_state["nwave_select_mode"] == "sma5" else "세력평단 지점"
        st.info(f"👆 아래 차트에서 **{mode_txt}**으로 삼을 지점을 클릭하세요.")

    click_event = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun", selection_mode=["points"],
        key=f"nwave_chart_{code}",
    )

    def _get_field(obj, key, alt_key=None, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            if alt_key and alt_key in obj:
                return obj[alt_key]
            return default
        if hasattr(obj, key):
            return getattr(obj, key)
        if alt_key and hasattr(obj, alt_key):
            return getattr(obj, alt_key)
        return default

    selection_obj = _get_field(click_event, "selection")
    points = _get_field(selection_obj, "points", default=[]) or []

    if points and st.session_state["nwave_select_mode"] in ("sma5", "avg"):
        pt = points[0]
        x_clicked = _get_field(pt, "x")
        if x_clicked in x_vals:
            row = plot_df.iloc[x_vals.index(x_clicked)]
            mode = st.session_state["nwave_select_mode"]
            if mode == "sma5" and pd.notna(row["SMA5"]):
                st.session_state["nwave_sma5_point"] = {"date": x_clicked, "value": float(row["SMA5"])}
                st.session_state["nwave_select_mode"] = None
            elif mode == "avg" and pd.notna(row["평단가"]):
                st.session_state["nwave_avg_point"] = {"date": x_clicked, "value": float(row["평단가"])}
                st.session_state["nwave_select_mode"] = None

    # 여기서부터는 차트 클릭 처리까지 끝난 "최신" 상태 - 이제 위쪽 placeholder를 채운다.
    sma5_pt = st.session_state["nwave_sma5_point"]
    avg_pt = st.session_state["nwave_avg_point"]

    with info_placeholder.container():
        info_cols = st.columns(4)
        with info_cols[0]:
            st.metric("상승 시작일 (저가)", f"{start_low:,.0f}원", start_actual_date)
        with info_cols[1]:
            st.metric("5이평 언덕 (SMA5)", f"{sma5_pt['value']:,.0f}원" if sma5_pt else "미선택", sma5_pt["date"] if sma5_pt else None)
        with info_cols[2]:
            st.metric("세력평단 Mapping", f"{avg_pt['value']:,.0f}원" if avg_pt else "미선택", avg_pt["date"] if avg_pt else None)
        with info_cols[3]:
            wave1_preview = (sma5_pt["value"] - start_low) if sma5_pt else None
            st.metric("Wave1 (상승폭)", f"{wave1_preview:,.0f}원" if wave1_preview is not None else "-")

    if run_clicked:
        if sma5_pt and avg_pt:
            wave1 = sma5_pt["value"] - start_low
            support = avg_pt["value"]
            st.session_state["nwave_targets"] = {
                "T1": support + wave1 * 0.618,
                "T2": support + wave1 * 1.0,
                "T3": support + wave1 * 1.618,
                "T4": support + wave1 * 2.0,
            }
        else:
            st.warning("먼저 차트에서 '5이평 언덕'과 '세력평단' 지점을 클릭해서 선택해주세요.")

    targets = st.session_state.get("nwave_targets")
    if targets:
        with targets_placeholder.container():
            t_cols = st.columns(4)
            for col, (key, label, color) in zip(t_cols, t_meta):
                val = targets[key]
                with col:
                    st.markdown(
                        f"""
                        <div onclick="navigator.clipboard.writeText('{int(val)}');"
                             style="border:2px solid {color}; border-radius:8px; padding:10px; text-align:center; cursor:pointer;"
                             title="클릭 시 숫자만 즉시 복사">
                            <div style="font-size:12px; font-weight:bold; color:{color};">{key} ({label})</div>
                            <div style="font-size:16px; font-weight:bold; margin-top:4px;">{val:,.0f}원</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        if run_clicked:
            st.caption("⚠ 방금 계산한 목표가 라인은 차트를 한 번 더 조작하면 다음 렌더에 반영됩니다.")


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
# 업종·테마 분석용 데이터 빌더
# ---------------------------------------------------------
# ⚠ KRX/pykrx는 "이 종목이 어떤 테마에 속하는지"를 알려주는 공식 분류 API를
#   제공하지 않습니다 (테마 분류는 증권사/정보업체가 자체적으로 큐레이션하는
#   비공개 데이터라서요). 그래서 테마-종목 매핑 자체는 예시(샘플) 데이터이고,
#   실제 서비스로 쓰려면 이 매핑 테이블을 직접 관리하거나 유료 테마 DB를
#   연동해야 합니다. 대신 각 종목의 가격/목표가/손절가 계산 로직은 기존
#   앱과 동일한 방식(퍼센트 기반)을 그대로 사용합니다.
def _build_stock_entry(name: str, code: str, price: int, change_pct: float) -> dict:
    seed = int(code) if code.isdigit() else abs(hash(code)) % 100000
    vol_unit = max(1, price // 500)
    volume = int(50_000_000 / max(price, 100) * (0.4 + (seed % 97) / 60))
    amount = price * volume  # 거래대금(원)
    market_cap = price * (3_000_000 + (seed % 50) * 4_000_000)  # 시가총액(원) 근사치
    return {
        "name": name,
        "code": code,
        "price": price,
        "change": change_pct,
        "volume": volume,
        "amount": amount,
        "market_cap": market_cap,
        "op_status": "🟢 흑자" if seed % 5 != 0 else "🔴 적자",
        "trade_type": "⚡ 단타" if change_pct >= 5 else "🌊 스윙",
        "d_vwap": int(price * (0.975 if change_pct >= 0 else 1.01)),
        "target1": int(price * 1.05),
        "target2": int(price * 1.10),
        "target3": int(price * 1.15),
        "stop1": int(price * 0.98),
        "stop2": int(price * 0.97),
        "stop_abs": int(price * 0.96),
    }


THEME_SEED = [
    ("귀금속(금/은)", [("엘컴텍", "037950", 3170, 13.62), ("아이티센글로벌", "124500", 26200, 11.73), ("고려아연", "010130", 1161000, 6.03), ("영풍", "000670", 37350, 0.27)]),
    ("지역화폐", [("쿠콘", "294570", 41200, 5.40), ("유라클", "088320", 8120, 3.85), ("한국전자금융", "063570", 5290, 2.10)]),
    ("마리화나(대마)", [("파이온엑스", "121850", 3480, 4.20), ("비엘팜텍", "020150", 1560, 3.10), ("HLB바이오스텝", "278650", 12300, -1.50)]),
    ("mRNA(메신저 리보핵산)", [("큐라티스", "348080", 6200, 2.84), ("한미약품", "128940", 312000, 1.20), ("나이벡", "138610", 22400, -0.80)]),
    ("드론(Drone)", [("제이씨현시스템", "033320", 4870, 2.31), ("피씨디렉트", "051380", 2140, 1.90)]),
    ("광케이블/광섬유", [("대한광통신", "010170", 1850, 4.50)]),
    ("전선", [("대한전선", "001440", 14200, 8.50)]),
    ("2차전지", [("에코프로", "086520", 118000, 3.40), ("포스코퓨처엠", "003670", 245000, 2.10), ("엘앤에프", "066970", 98000, -1.20)]),
    ("반도체", [("SK하이닉스", "000660", 188500, 8.90), ("한미반도체", "042700", 132000, 5.60), ("DB하이텍", "000990", 47500, -0.90)]),
    ("로봇", [("휴림로봇", "090710", 7500, 6.10), ("레인보우로보틱스", "277810", 495000, 2.27), ("두산로보틱스", "454910", 68900, 1.40)]),
    ("AI(인공지능)", [("솔트룩스", "304100", 15600, 4.90), ("코난테크놀로지", "402030", 12800, 3.20)]),
    ("우주항공", [("한화에어로스페이스", "012450", 315000, 2.80), ("한국항공우주", "047810", 68200, 1.10)]),
    ("원자력발전", [("두산에너빌리티", "034020", 77400, 0.52), ("한전기술", "052690", 89400, -1.40)]),
    ("수소차", [("에스퓨얼셀", "288620", 24100, 3.60), ("일진하이솔루스", "271940", 18700, 2.00)]),
    ("자율주행", [("현대모비스", "012330", 245000, 1.80), ("모바일어플라이언스", "087260", 5220, 2.90)]),
    ("게임", [("크래프톤", "259960", 289000, 1.20), ("펄어비스", "263750", 41800, -0.60)]),
    ("K-뷰티", [("클리오", "237880", 38900, 4.10), ("아모레퍼시픽", "090430", 142000, 1.50)]),
    ("K-푸드", [("삼양식품", "003230", 612000, 2.20), ("CJ제일제당", "097950", 298000, 0.80)]),
    ("조선", [("HD한국조선해양", "009540", 242000, -1.63), ("삼성중공업", "010140", 12800, 1.90)]),
    ("건설", [("대우건설", "047040", 17030, 4.93), ("GS건설", "006360", 32850, 5.46)]),
    ("태양광", [("한화솔루션", "009830", 30500, 1.16), ("OCI홀딩스", "010060", 98700, -2.10)]),
    ("바이오시밀러", [("삼성바이오로직스", "207940", 985000, 1.00), ("셀트리온", "068270", 189000, -0.50)]),
    ("K-방산", [("한화시스템", "272210", 32850, -1.63), ("LIG넥스원", "079550", 218000, 2.30)]),
    ("여행/레저", [("하나투어", "039130", 68900, 3.10), ("모두투어", "080160", 12400, 2.40)]),
    ("면세점/화장품유통", [("호텔신라", "008770", 62800, -0.80), ("신세계", "004170", 152000, 0.40)]),
]

THEME_DATA = {}
for _t_name, _stocks in THEME_SEED:
    _entries = [_build_stock_entry(n, c, p, ch) for (n, c, p, ch) in _stocks]
    _avg_change = sum(e["change"] for e in _entries) / len(_entries)
    THEME_DATA[_t_name] = {
        "change": f"{_avg_change:+.2f}%",
        "change_val": _avg_change,
        "leader": _entries[0]["name"],
        "up_count": sum(1 for e in _entries if e["change"] > 0),
        "down_count": sum(1 for e in _entries if e["change"] < 0),
        "stocks": _entries,
    }
# 상승률(평균 등락) 기준 내림차순 정렬 → 인기 테마 순위
THEME_DATA = dict(sorted(THEME_DATA.items(), key=lambda kv: kv[1]["change_val"], reverse=True))


@st.cache_data(ttl=30)
def fetch_naver_live_ranking() -> pd.DataFrame:
    """
    네이버 금융 '거래량 상위' 페이지에서 거래량+거래대금+등락률을 함께 가져온다.
    ⚠ pykrx의 get_market_ohlcv_by_ticker는 KRX 정식 종가(EOD) 기준이라
    장중에는 "당일" 데이터가 아예 없어서 실시간 랭킹에 못 씁니다.
    이 페이지는 네이버가 장중에도 실시간으로 갱신하는 페이지라 장중에도 값이 보입니다.
    (비공식 HTML 파싱 - 페이지 구조가 바뀌면 깨질 수 있음, 실패 시 빈 DataFrame)
    """
    try:
        url = "https://finance.naver.com/sise/sise_quant.naver"
        resp = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
        resp.encoding = "euc-kr"
        html = resp.text

        code_name_pairs = re.findall(r'/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>', html)
        code_map = {}
        for code, name in code_name_pairs:
            name = name.strip()
            if name and name not in code_map:
                code_map[name] = code

        import io as _io
        tables = pd.read_html(_io.StringIO(html))
        target = None
        for t in tables:
            cols = [str(c) for c in t.columns]
            if any("종목명" in c for c in cols) and any("거래량" in c for c in cols):
                target = t.copy()
                break
        if target is None:
            return pd.DataFrame()

        target.columns = [str(c) for c in target.columns]
        target = target.dropna(subset=["종목명"])
        target = target[target["종목명"].astype(str).str.strip() != ""]

        def _to_num(series):
            return pd.to_numeric(
                series.astype(str).str.replace(",", "").str.replace("%", ""), errors="coerce"
            )

        out = pd.DataFrame()
        out["종목명"] = target["종목명"].astype(str).str.strip()
        out["코드"] = out["종목명"].map(code_map)
        out["현재가"] = _to_num(target.get("현재가", pd.Series(dtype=float)))
        out["등락률"] = _to_num(target.get("등락률", pd.Series(dtype=float)))
        out["거래량"] = _to_num(target.get("거래량", pd.Series(dtype=float)))
        amt_col = next((c for c in target.columns if "거래대금" in c), None)
        out["거래대금"] = _to_num(target[amt_col]) * 1_000_000 if amt_col else None  # 표시 단위: 백만원

        out = out.dropna(subset=["코드", "현재가", "거래량"])
        return out
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def fetch_naver_popular_search() -> list:
    """
    네이버 금융 '인기 검색 종목' 페이지 기반 검색 상위 TOP10.
    ⚠ 공식 API가 아니라 페이지 HTML을 파싱하는 방식이라, 네이버 쪽 페이지
    구조가 바뀌면 깨질 수 있습니다. 실패 시 빈 리스트를 반환하고 화면에서
    안내 문구로 대체합니다.
    """
    try:
        url = "https://finance.naver.com/sise/lastsearch2.naver"
        resp = requests.get(
            url, timeout=3, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.encoding = "euc-kr"
        html = resp.text
        rows = re.findall(
            r'<td class="no">(\d+)</td>\s*<td class="tit">\s*<a href="/item/main\.naver\?code=(\d+)"[^>]*>([^<]+)</a>',
            html,
        )
        prices = re.findall(r'class="td_r"[^>]*>([\d,]+)</td>', html)
        out = []
        for i, (rank, code, name) in enumerate(rows[:10]):
            price = prices[i] if i < len(prices) else "-"
            out.append({"rank": int(rank), "name": name.strip(), "code": code, "price": price})
        return out
    except Exception:
        return []



# ---------------------------------------------------------
with main_tab1:
    if "search_history" not in st.session_state:
        st.session_state.search_history = ["삼성전자", "SK하이닉스"]
    if "target_stock" not in st.session_state:
        st.session_state.target_stock = "삼성전자"

    def on_input_change():
        st.session_state.target_stock = st.session_state.stock_input_field

    def set_recent_stock(val):
        st.session_state.target_stock = val
        st.session_state.stock_input_field = val

    sc1, sc2, sc3, sc4 = st.columns([2.2, 0.7, 2.6, 1])

    with sc3:
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

    with sc1:
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; height:38px; background:#f8f9fa; padding:0 10px; border:1px solid #e9ecef; border-radius:6px; font-size:13px; font-weight:bold;">
                📌 종목: {stock_name} ({code})
            </div>
            """,
            unsafe_allow_html=True,
        )
    with sc4:
        st.markdown(
            f"""
            <button onclick="navigator.clipboard.writeText('{code}');"
                    style="width:100%; height:38px; background:#1a73e8; color:white; border:none; border-radius:6px; cursor:pointer; font-size:11px; font-weight:bold;">
                📋 코드 복사 ({code})
            </button>
            """,
            unsafe_allow_html=True,
        )

    watchlist = load_watchlist()
    wl_map = {w["code"]: w for w in watchlist}
    is_in_wl = code in wl_map

    def _toggle_watchlist():
        wl = load_watchlist()
        if code in [w["code"] for w in wl]:
            wl = [w for w in wl if w["code"] != code]
        else:
            wl.insert(0, {"code": code, "name": stock_name, "memo": ""})
        save_watchlist(wl)

    def _update_memo():
        wl = load_watchlist()
        for w in wl:
            if w["code"] == code:
                w["memo"] = st.session_state.get("wl_memo_input", "")
        save_watchlist(wl)

    def _select_watchlist(c, n):
        st.session_state.target_stock = n
        st.session_state.stock_input_field = n

    wl_col1, wl_col2 = st.columns([1, 4])
    with wl_col1:
        st.button(
            "★ 관심종목 해제" if is_in_wl else "☆ 관심종목 추가",
            key="wl_toggle_btn", on_click=_toggle_watchlist, use_container_width=True,
        )
    with wl_col2:
        if is_in_wl:
            st.text_input(
                "메모", value=wl_map[code].get("memo", ""), key="wl_memo_input",
                on_change=_update_memo, placeholder="이 종목 메모 (자동 저장)",
                label_visibility="collapsed",
            )
        else:
            st.caption("⭐ 관심종목은 서버 파일에 저장되어 새로고침해도 유지됩니다. 추가하면 메모도 남길 수 있어요.")

    if watchlist:
        wl_list = watchlist[:10]
        wl_cols = st.columns(len(wl_list))
        for idx, w in enumerate(wl_list):
            with wl_cols[idx]:
                label = f"⭐ {w['name']}" + (" 📝" if w.get("memo") else "")
                st.button(
                    label, key=f"wl_btn_{idx}",
                    on_click=_select_watchlist, args=(w["code"], w["name"]),
                    use_container_width=True, help=w.get("memo") or None,
                )

    if st.session_state.search_history:
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

    # 차트 주기(일봉/주봉/월봉/분봉)는 실제 라디오 위젯을 현재가~절대사수 카드 바로
    # 아래에서 그리고(요청사항), 여기서는 값만 세션에서 읽어와 데이터를 먼저 가져온다.
    timeframe_options = [
        "일봉", "주봉", "월봉",
        "1분봉", "3분봉", "5분봉", "10분봉", "15분봉", "30분봉",
        "45분봉", "60분봉", "90분봉", "120분봉", "240분봉", "300분봉", "999분봉",
    ]
    selected_timeframe = st.session_state.get("direct_timeframe_select", "일봉")

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

    # (HTS 수급·평단 분석 박스는 페이지 맨 아래로 이동됨 - "시가총액·수급·진단 정보" 아래에 표시)

    is_minute_mode = selected_timeframe.endswith("분봉")
    today = datetime.date.today()
    year_options = list(range(today.year - 4, today.year + 1))  # 항상 올해를 포함하도록 동적 생성
    year_start_default = datetime.date(today.year, 1, 1)  # 시작연도 기본값 = 올해 1월 1일

    if st.session_state.get("_reset_to_today_pending"):
        st.session_state["ey"] = today.year
        st.session_state["em"] = today.month
        st.session_state["ed"] = today.day
        st.session_state["_reset_to_today_pending"] = False

    if st.session_state.get("_swap_dates_pending"):
        sy0 = st.session_state.get("sy") or year_start_default.year
        sm0 = st.session_state.get("sm") or year_start_default.month
        sd0 = st.session_state.get("sd") or year_start_default.day
        st.session_state["ey"] = sy0
        st.session_state["em"] = sm0
        st.session_state["ed"] = sd0
        st.session_state["_swap_dates_pending"] = False

    # 실제 위젯은 현재가~절대사수 카드 옆(오른쪽)에서 그리고, 여기서는 값만 읽어서
    # 데이터부터 먼저 가져온다 (요청: 조회기간 UI를 카드 오른쪽으로 이동).
    if is_minute_mode:
        s_year, s_mon, s_day = today.year, today.month, today.day
        e_year, e_mon, e_day = today.year, today.month, today.day
    else:
        s_year = st.session_state.get("sy") or year_start_default.year
        s_mon = st.session_state.get("sm") or year_start_default.month
        s_day = st.session_state.get("sd") or year_start_default.day
        e_year = st.session_state.get("ey") or today.year
        e_mon = st.session_state.get("em") or today.month
        e_day = st.session_state.get("ed") or today.day

    try:
        start_date = datetime.date(s_year, s_mon, s_day)
    except (ValueError, TypeError):
        start_date = datetime.date(s_year, s_mon, 1)

    try:
        end_date = datetime.date(e_year, e_mon, e_day)
    except (ValueError, TypeError):
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
            err_detail = st.session_state.get("_minute_fetch_error")
            warn_msg = "당일 분봉 데이터를 아직 받아오지 못했습니다. 장 시작(09:00) 이전이거나 네트워크 문제일 수 있습니다."
            if err_detail:
                warn_msg += f"\n\n**실패 사유:** {err_detail}"
            st.warning(warn_msg)
            if st.button("🔄 분봉 다시 시도", key="minute_retry_btn"):
                fetch_kiwoom_minute_df.clear()
                fetch_naver_minute_ohlcv.clear()
                st.rerun()
        else:
            st.caption(f"📡 분봉 데이터 출처: {st.session_state.get('_minute_data_source', '알 수 없음')}")

    # 실시간(준실시간) 시세 보정 - 키움 체결가와의 괴리 축소
    # (체크박스 위젯 자체는 페이지 맨 아래로 이동 - 여기서는 값만 세션에서 읽어서 적용)
    use_realtime_patch = st.session_state.get("rt_patch_toggle", False)
    rt_info = None
    if use_realtime_patch and df is not None and not df.empty:
        rt_info = fetch_realtime_price(code)
        if is_minute_mode:
            df = patch_latest_row_with_realtime(df, code)
        else:
            df = patch_today_with_realtime(df, code)

    def _render_realtime_patch_toggle():
        rt_col1, rt_col2 = st.columns([1, 5])
        with rt_col1:
            st.checkbox("⚡ 실시간 시세 보정", value=False, key="rt_patch_toggle")
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

    def _render_date_range_picker(auto_copy_value=None, disparity_value=None):
        """
        조회기간(시작/종료 연·월·일) 선택 위젯 + 스왑/오늘로 버튼 + 차트 주기 라디오.
        데이터가 없어서 경고만 뜨는 상태에서도 항상 보여야 사용자가 날짜를
        직접 고쳐서 빠져나올 수 있으므로, df 유무와 무관하게 호출 가능한
        독립 함수로 뺐다.
        """
        def _mark_daterange_changed():
            st.session_state["_daterange_changed"] = True

        def _on_sy_change():
            st.session_state["_daterange_changed"] = True
            if st.session_state.get("_year_sync_on", True):
                st.session_state["ey"] = st.session_state["sy"]

        def _on_ey_change():
            st.session_state["_daterange_changed"] = True
            if st.session_state.get("_year_sync_on", True):
                st.session_state["sy"] = st.session_state["ey"]

        st.session_state.setdefault("_year_sync_on", True)

        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            if st.button("➡ 종료=시작", key="swap_dates_btn", use_container_width=True):
                st.session_state["_swap_dates_pending"] = True
                st.rerun()
        with bcol2:
            sync_label = "🔗 연도동기화 ON" if st.session_state["_year_sync_on"] else "⛓️‍💥 연도동기화 OFF"
            if st.button(sync_label, key="year_sync_toggle_btn", use_container_width=True):
                st.session_state["_year_sync_on"] = not st.session_state["_year_sync_on"]
                st.rerun()
        with bcol3:
            if st.button("📌 오늘로", key="reset_to_today_btn", use_container_width=True):
                st.session_state["_reset_to_today_pending"] = True
                st.session_state["_daterange_changed"] = True
                st.rerun()

        dcol1, dcol2, dcol3 = st.columns(3)
        with dcol1:
            st.selectbox("시작연도", year_options,
                         index=year_options.index(min(max(s_year, year_options[0]), year_options[-1])),
                         key="sy", label_visibility="collapsed", on_change=_on_sy_change)
        with dcol2:
            st.selectbox("시작월", list(range(1, 13)), index=s_mon - 1, key="sm",
                         label_visibility="collapsed", on_change=_mark_daterange_changed)
        with dcol3:
            st.selectbox("시작일", list(range(1, 32)), index=s_day - 1, key="sd",
                         label_visibility="collapsed", on_change=_mark_daterange_changed)

        ecol1, ecol2, ecol3 = st.columns(3)
        with ecol1:
            st.selectbox("종료연도", year_options,
                         index=year_options.index(min(max(e_year, year_options[0]), year_options[-1])),
                         key="ey", label_visibility="collapsed", on_change=_on_ey_change)
        with ecol2:
            st.selectbox("종료월", list(range(1, 13)), index=e_mon - 1, key="em",
                         label_visibility="collapsed", on_change=_mark_daterange_changed)
        with ecol3:
            st.selectbox("종료일", list(range(1, 32)), index=e_day - 1, key="ed",
                         label_visibility="collapsed", on_change=_mark_daterange_changed)

        if is_minute_mode:
            st.caption("⏱️ 분봉 모드는 당일(09:00~15:30) 고정이라 위 조회기간은 무시됩니다.")

        # 조회기간을 수동으로 바꾸면 종료일 기준 일봉 평단가(숫자만)를 자동으로 클립보드에 복사
        # (다른 사이트에 바로 붙여넣기 가능하도록 순수 숫자만 복사하고, 괴리율은 화면에 참고용으로 같이 표시)
        if st.session_state.get("_daterange_changed"):
            st.session_state["_daterange_changed"] = False
            if auto_copy_value is not None:
                components.html(
                    f"<script>navigator.clipboard.writeText('{int(auto_copy_value)}');</script>",
                    height=0,
                )
                st.session_state["_last_copied_avg"] = {
                    "value": int(auto_copy_value),
                    "disparity": disparity_value,
                }

        last_copied = st.session_state.get("_last_copied_avg")
        if last_copied is not None:
            v = last_copied["value"]
            d = last_copied["disparity"]
            label = f"📋 복사됨: 평단가 {v:,}원" + (f" (괴리율 {d:+.2f}%)" if d is not None else "")
            components.html(
                f"""
                <div onclick="navigator.clipboard.writeText('{v}');
                              this.querySelector('.copied-flash').style.opacity=1;
                              setTimeout(()=>{{this.querySelector('.copied-flash').style.opacity=0;}}, 900);"
                     style="display:inline-flex; align-items:center; gap:6px; font-size:12px; color:#555;
                            cursor:pointer; padding:2px 6px; border-radius:4px;"
                     title="클릭하면 평단가 숫자를 다시 복사합니다"
                     onmouseover="this.style.background='#f1f3f5';"
                     onmouseout="this.style.background='transparent';">
                    <span>{label}</span>
                    <span class="copied-flash" style="opacity:0; transition:opacity .2s; color:#2b8a3e; font-weight:bold;">✓ 복사됨</span>
                </div>
                """,
                height=26,
            )

    if df is None or df.empty:
        _dp_col1, _dp_col2 = st.columns([5.3, 1.55])
        with _dp_col1:
            st.warning("선택한 조건에 해당하는 거래 데이터가 없습니다. 오른쪽에서 조회기간을 다시 맞춰보세요 (시작일이 종료일보다 늦으면 이렇게 됩니다).")
        with _dp_col2:
            _render_date_range_picker(auto_copy_value=None)
        st.radio(
            "차트 주기",
            timeframe_options,
            horizontal=True,
            key="direct_timeframe_select",
            label_visibility="collapsed",
        )
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        _render_realtime_patch_toggle()
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

        f_info = get_financial_info(code, current_price=last_close)
        mcap_val = f_info["mcap"]
        op_profit = f_info["op_profit"]
        op_profit_label = f_info["op_profit_label"]
        trade_type = f_info["trade_type"]
        foreign_net = f_info["foreign_net"]
        inst_net = f_info["inst_net"]
        pension_net = f_info["pension_net"]
        trust_net = f_info["trust_net"]
        pe_net = f_info["pe_net"]
        flow_as_of = f_info.get("flow_as_of")
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

        # (시가총액/추정순이익/매매성향/진단상태/수급 카드는 페이지 맨 아래로 이동됨)

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
        </div>
        """
        # (카드+조회기간 위젯은 차트 스타일 글자 바로 위로 이동 - 아래쪽에서 렌더링)

        st.radio(
            "차트 주기",
            timeframe_options,
            horizontal=True,
            key="direct_timeframe_select",
            label_visibility="collapsed",
        )



        chart_mode = st.session_state.get("chart_display_mode", "🔲 일·주·월·분봉 동시보기")

        if chart_mode == "🌊 N파동 목표가 Mapping":
            render_n_wave_mapping_chart(df, stock_name, code)
        elif chart_mode == "🔲 일·주·월·분봉 동시보기":
            render_quad_timeframe_chart(
                code, stock_name, df, selected_timeframe, is_minute_mode,
                target_1st, target_2nd, target_3rd, stop_1st, stop_2nd, absolute_stop_loss,
            )
        elif chart_mode == "🧭 Study Mapping 스타일 (클릭 기준점 리셋)":
            render_study_mapping_chart(df, stock_name, code, selected_timeframe)
        else:
            fig = go.Figure()

            hover_x = [d.strftime("%H:%M" if is_minute_mode else "%Y-%m-%d") for d in df.index]

            row_disparity = ((df["종가"] - df["평단가"]) / df["평단가"] * 100)
            hover_close = [
                f"종가: {int(c):,}원 ({d:+.2f}%)" if pd.notna(d) else f"종가: {int(c):,}원"
                for c, d in zip(df["종가"], row_disparity)
            ]
            hover_vwap = [
                f"누적 평단가: {int(v):,}원 (괴리율 {d:+.2f}%)" if pd.notna(v) and pd.notna(d) else "누적 평단가: -"
                for v, d in zip(df["평단가"], row_disparity)
            ]
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
                yaxis=dict(title="가격 (원)", tickformat=",.0f"),
                yaxis2=dict(title="누적 순매수 증감 (주)", overlaying="y", side="right", showgrid=False, tickformat=",.0f")
            )

            fig.update_xaxes(
                type="category",
                tickangle=0,
                nticks=10,
            )

            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

        row_l, row_r = st.columns([5.3, 1.55])
        with row_l:
            components.html(metrics_click_copy_html, height=150)
        with row_r:
            _render_date_range_picker(auto_copy_value=last_vwap, disparity_value=disparity)

        st.radio(
            "차트 스타일",
            ["📊 기본 목표가 차트", "🧭 Study Mapping 스타일 (클릭 기준점 리셋)", "🔲 일·주·월·분봉 동시보기", "🌊 N파동 목표가 Mapping"],
            index=2,
            horizontal=True,
            key="chart_display_mode",
        )

        with st.expander("📝 텍스트 요약 및 전체 복사 기능", expanded=True):
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


        st.markdown("<hr style='margin:16px 0 10px 0;'>", unsafe_allow_html=True)
        st.markdown("### 📊 시가총액 · 수급 · 진단 정보")

        f1, f2, f3, f4 = st.columns(4)
        f1.metric("🏢 시가총액", f"{mcap_val:,} 억원" if mcap_val is not None else "N/A (조회 실패)")
        f2.metric(
            op_profit_label,
            f"{op_profit:,} 억원" if op_profit is not None else "N/A",
            ("🟢 흑자" if op_profit > 0 else "🔴 적자") if op_profit is not None else None,
        )
        f3.metric("🎯 매매 성향", trade_type)
        f4.metric("⚡ 진단 상태", status_signal)

        s_c1, s_c2, s_c3, s_c4 = st.columns(4)
        s_c1.metric("🌐 외국인 순매수", foreign_net)
        s_c2.metric("🏛️ 기관 순매수", inst_net)
        s_c3.metric("💻 실시간 프로그램", prog_net)
        s_c4.metric("💳 신용잔고율", credit_ratio)

        flow_note_col, flow_btn_col = st.columns([5, 1])
        with flow_note_col:
            if flow_as_of:
                as_of_fmt = f"{flow_as_of[:4]}-{flow_as_of[4:6]}-{flow_as_of[6:]}"
                today_str = datetime.datetime.now().strftime("%Y%m%d")
                if flow_as_of == today_str:
                    st.caption(f"👇 기관합계 세부 내역 · 수급 기준일: {as_of_fmt} (당일)")
                else:
                    st.caption(f"👇 기관합계 세부 내역 · 수급 기준일: {as_of_fmt} (KRX가 당일 장중엔 투자자별 수급을 공개하지 않아 최근 영업일 기준입니다)")
            else:
                st.caption("👇 기관합계 세부 내역 · ⚠ 수급 데이터 조회 실패 (아래 값은 N/A로 표시됩니다)")
        with flow_btn_col:
            if st.button("🔄 새로고침", key="flow_refresh_btn"):
                fetch_investor_flow.clear()
                fetch_naver_integration_info.clear()
                fetch_shares_outstanding.clear()
                st.rerun()

        p_c1, p_c2, p_c3 = st.columns(3)
        p_c1.metric("🏦 연기금 순매수", pension_net)
        p_c2.metric("📈 투신 순매수", trust_net)
        p_c3.metric("🕵️ 사모 순매수", pe_net)

        hts_top_panel_html = f"""
        <div style="background: #ffffff; border: 1px solid #1a73e8; border-radius: 8px; padding: 12px 15px; margin-top: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
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

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        _render_realtime_patch_toggle()


# ---------------------------------------------------------
# TAB 2: 업종·테마 분석 대시보드
# ---------------------------------------------------------
with main_tab2:
    st.markdown("### ⭐ 업종·테마 분석 대시보드")
    st.caption("다단계 목표가 및 다단계 손절선 포함 분석 · 테마-종목 매핑은 예시 데이터입니다")

    theme_names_all = list(THEME_DATA.keys())
    top5_keys = theme_names_all[:5]
    top_cols = st.columns(len(top5_keys))

    for i, t_name in enumerate(top5_keys):
        t_info = THEME_DATA[t_name]
        rank_num = i + 1
        chg_color = "#d32f2f" if t_info["change_val"] >= 0 else "#1971c2"
        card_html = (
            '<div style="background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); min-height: 118px;">'
            '<div style="display: flex; justify-content: space-between; align-items: center;">'
            f'<span style="color: {chg_color}; font-weight: bold; font-size: 13px;">{rank_num}위</span>'
            f'<span style="color: {chg_color}; font-weight: bold; font-size: 13px;">{t_info["change"]}</span>'
            "</div>"
            f'<div style="font-weight: bold; font-size: 14px; margin-top: 6px; color: #111;">{t_name}</div>'
            f'<div style="font-size: 11px; color: #666; margin-top: 4px;">{t_info["leader"]} 외</div>'
            f'<div style="font-size: 10px; margin-top: 6px;">'
            f'<span style="color:#d32f2f; font-weight:bold;">상승 {t_info["up_count"]}</span>'
            f'<span style="color:#999;"> / </span>'
            f'<span style="color:#1971c2; font-weight:bold;">하락 {t_info["down_count"]}</span>'
            "</div>"
            "</div>"
        )
        with top_cols[i]:
            st.markdown(card_html, unsafe_allow_html=True)

    st.markdown("", unsafe_allow_html=True)
    col_left, col_right = st.columns([1, 3.2])

    with col_left:
        panel_mode = st.radio(
            "패널 모드", ["🌡️ 인기 테마 목록", "🔎 종목 검색"], horizontal=True,
            key="theme_panel_mode", label_visibility="collapsed",
        )

        if panel_mode == "🔎 종목 검색":
            search_input = st.text_input(
                "검색어 입력...", "", key="t_search", placeholder="종목명 또는 코드 입력..."
            )
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
            selected_theme = None
        else:
            st.markdown(
                f"<span style='font-size:12px; color:#555;'>🌡️ 인기 테마 목록 <b>{len(theme_names_all)}개</b></span>",
                unsafe_allow_html=True,
            )
            radio_labels = []
            for i, t_name in enumerate(theme_names_all, start=1):
                t_info = THEME_DATA[t_name]
                radio_labels.append(
                    f"{i}. {t_name}  {t_info['change']}  (▲{t_info['up_count']}/▼{t_info['down_count']})"
                )
            with st.container(height=460):
                sel_label = st.radio(
                    "테마 선택",
                    radio_labels,
                    index=0,
                    label_visibility="collapsed",
                    key="t_radio_v2",
                )
            sel_idx = radio_labels.index(sel_label)
            selected_theme = theme_names_all[sel_idx]
            matched_stocks = None

    def _render_stock_table(rows, height=260):
        table_rows_html = ""
        for idx, item in enumerate(rows, start=1):
            chg_color = "#d32f2f" if item["change"] >= 0 else "#1971c2"
            chg_sign = "+" if item["change"] >= 0 else ""
            theme_tag = f" ({item['theme']})" if "theme" in item else ""
            table_rows_html += f"""
            <tr style="border-bottom: 1px solid #f0f0f0; height: 62px; font-size: 11px;">
                <td style="text-align: center; font-weight: bold;">{idx}</td>
                <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['trade_type']}{theme_tag}</span></td>
                <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
                <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
                <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
                <td style="text-align: right; color: {chg_color}; font-weight: bold;">{chg_sign}{item['change']:.2f}%</td>
                <td style="text-align: right;">{item['volume']:,}</td>
                <td style="text-align: right;">{item['amount']//1000000:,}백만</td>
                <td style="text-align: right;">{item['market_cap']//100000000:,}억</td>
                <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원</td>
                <td style="text-align: right; color: #2b8a3e;">{item['target1']:,}원</td>
                <td style="text-align: right; color: #2b8a3e;">{item['target2']:,}원</td>
                <td style="text-align: right; color: #2b8a3e;">{item['target3']:,}원</td>
                <td style="text-align: right; color: #f59f00;">{item['stop1']:,}원</td>
                <td style="text-align: right; color: #f08c00;">{item['stop2']:,}원</td>
                <td style="text-align: right; font-weight: bold; color: #e03131;">{item['stop_abs']:,}원</td>
            </tr>
            """
        table_html = f"""
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
                        <th style="text-align: right;">거래량</th>
                        <th style="text-align: right;">거래대금</th>
                        <th style="text-align: right;">시가총액</th>
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
        components.html(table_html, height=height, scrolling=True)

    with col_right:
        if panel_mode == "🔎 종목 검색":
            st.markdown("### 📌 종목 검색 결과 분석", unsafe_allow_html=True)
            if matched_stocks:
                _render_stock_table(matched_stocks, height=260)
            else:
                st.info("검색된 종목이 없습니다.")
        else:
            t_info = THEME_DATA[selected_theme]
            head_col1, head_col2 = st.columns([3, 2])
            with head_col1:
                st.markdown(f"### 📌 {selected_theme}", unsafe_allow_html=True)
            with head_col2:
                st.markdown(
                    f"<div style='text-align:right; font-size:13px; padding-top:8px;'>"
                    f"<span style='color:#d32f2f; font-weight:bold;'>▲상승 {t_info['up_count']}</span>&nbsp;&nbsp;"
                    f"<span style='color:#1971c2; font-weight:bold;'>▼하락 {t_info['down_count']}</span>&nbsp;&nbsp;"
                    f"<span style='color:#666;'>구성종목 {len(t_info['stocks'])}개</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            sort_mode = st.radio(
                "정렬", ["전체", "거래대금 상위", "상승 TOP"],
                horizontal=True, key="theme_sort_mode", label_visibility="collapsed",
            )
            stocks_list = list(t_info["stocks"])
            if sort_mode == "거래대금 상위":
                stocks_list = sorted(stocks_list, key=lambda s: s["amount"], reverse=True)
            elif sort_mode == "상승 TOP":
                stocks_list = sorted(stocks_list, key=lambda s: s["change"], reverse=True)

            _render_stock_table(stocks_list, height=260)


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

# ---------------------------------------------------------
# TAB 5: 실시간 랭킹 (거래량 상위 / 거래대금 상위 / 검색 상위)
# ---------------------------------------------------------
with main_tab5:
    top_head1, top_head2 = st.columns([4, 1])
    with top_head1:
        st.markdown("### 🔴 실시간 랭킹")
        st.caption(
            f"네이버 증권 실시간 페이지 기반 · 갱신: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            "(장중에도 갱신되는 페이지를 사용합니다 - 예전에 쓰던 pykrx는 장마감 데이터라 장중엔 항상 비어있었습니다)"
        )
    with top_head2:
        if st.button("🔄 새로고침", key="rt_rank_refresh"):
            fetch_naver_live_ranking.clear()
            fetch_naver_popular_search.clear()
            st.rerun()

    market_df = fetch_naver_live_ranking()

    def _render_rank_rows(rows, value_fmt):
        """네이티브 스트림릿 위젯으로 랭킹 행을 그린다 (⚡단타/🎓스터디 버튼 클릭 가능하게)."""
        for i, r in enumerate(rows, start=1):
            chg = r.get("등락률", 0.0) or 0.0
            chg_color = "#d32f2f" if chg >= 0 else "#1971c2"
            chg_sign = "+" if chg >= 0 else ""
            row_c1, row_c2, row_c3, row_c4 = st.columns([3, 2, 1, 1])
            with row_c1:
                st.markdown(
                    f"<div style='font-size:12px; padding-top:6px;'>"
                    f"<span style='color:#868e96; font-weight:bold;'>{i}</span> "
                    f"<span style='font-weight:bold;'>{r['name']}</span></div>",
                    unsafe_allow_html=True,
                )
            with row_c2:
                st.markdown(
                    f"<div style='text-align:right; font-size:12px; padding-top:6px;'>"
                    f"<b>{value_fmt(r)}</b> "
                    f"<span style='color:{chg_color};'>{chg_sign}{chg:.2f}%</span></div>",
                    unsafe_allow_html=True,
                )
            with row_c3:
                st.button(
                    "⚡단타", key=f"jump_day_{r.get('_key', i)}_{value_fmt(r)}",
                    on_click=jump_to_chart, args=(r.get("code"), r["name"], "3분봉"),
                    use_container_width=True,
                )
            with row_c4:
                st.button(
                    "🎓스터디", key=f"jump_study_{r.get('_key', i)}_{value_fmt(r)}",
                    on_click=jump_to_chart, args=(r.get("code"), r["name"], "일봉"),
                    use_container_width=True,
                )

    rank_col1, rank_col2, rank_col3 = st.columns(3)

    with rank_col1:
        st.markdown("#### 📊 거래량 상위 TOP10")
        if market_df.empty:
            st.warning("데이터를 불러오지 못했습니다. 🔄 새로고침을 눌러 다시 시도해보세요.")
        else:
            top_vol = market_df.sort_values("거래량", ascending=False).head(10)
            rows = [
                {"name": row["종목명"], "code": row["코드"], "거래량": row["거래량"], "등락률": row["등락률"], "_key": f"vol{idx}"}
                for idx, (_, row) in enumerate(top_vol.iterrows())
            ]
            _render_rank_rows(rows, lambda r: f"{int(r['거래량']):,}주")

    with rank_col2:
        st.markdown("#### 💰 거래대금 상위 TOP10")
        if market_df.empty or market_df["거래대금"].isna().all():
            st.warning("데이터를 불러오지 못했습니다. 🔄 새로고침을 눌러 다시 시도해보세요.")
        else:
            top_amt = market_df.dropna(subset=["거래대금"]).sort_values("거래대금", ascending=False).head(10)
            rows = [
                {"name": row["종목명"], "code": row["코드"], "거래대금": row["거래대금"], "등락률": row["등락률"], "_key": f"amt{idx}"}
                for idx, (_, row) in enumerate(top_amt.iterrows())
            ]
            _render_rank_rows(rows, lambda r: f"{int(r['거래대금']//1_000_000):,}백만")

    with rank_col3:
        st.markdown("#### 🔍 검색 상위 TOP10")
        st.caption("⚠ 비공식 스크래핑 기반이라 실패할 수 있습니다")
        search_rows = fetch_naver_popular_search()
        if not search_rows:
            st.info("검색 순위를 지금은 불러올 수 없습니다. 🔄 새로고침을 눌러보세요.")
        else:
            rows = [
                {"name": r["name"], "code": r["code"], "가격": r.get("price", "-"), "등락률": 0.0, "_key": f"srch{idx}"}
                for idx, r in enumerate(search_rows)
            ]
            _render_rank_rows(rows, lambda r: f"{r['가격']}원")
