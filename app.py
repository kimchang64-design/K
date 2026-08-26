# -*- coding: utf-8 -*-
"""
Day Trading Mapping - 당일 분봉 + 세력평단 대시보드
- 3분봉에서 시작연도/종료연도 무시, 당일(09:00~현재) 분봉만 사용
- 세력평단(VWAP 누적 거래량가중평균가) 계산
- 키움 REST API 실계좌 연동(kiwoom_client.py)
- 관심종목(영구 저장) + 최근 검색어(영구 저장) + 한글 종목명 검색
- 수동 새로고침 버튼 + 자동 새로고침(선택)
"""

import json
import os
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, time as dtime

import kiwoom_client  # 같은 폴더의 kiwoom_client.py 사용

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ----------------------------------------------------------------------
# 기본 설정 / 다크테마 스타일
# ----------------------------------------------------------------------
st.set_page_config(page_title="Day trading Mapping", layout="wide")

DARK_BG = "#0b0e14"
CARD_BG = "#161a23"
CARD_BORDER = "#242938"
ORANGE = "#f5a623"
LINE_BLACK = "#1c1c1c"
CANDLE_UP = "#e05252"    # 양봉(상승) - 빨강
CANDLE_DOWN = "#4a90e2"  # 음봉(하락) - 파랑

# 일봉 기준 이동평균선 색상/표시명
MA_PERIODS = [5, 20, 60, 120, 240, 480, 720]
MA_COLORS = {
    5:   "#c48fd1",  # 연한 자주색
    20:  "#e74c3c",  # 빨강
    60:  "#0d2b6e",  # 진한 파랑
    120: "#ffe066",  # 밝은 노랑
    240: "#8fa8d0",  # 옅은 남색
    480: "#c9a27e",  # 옅은 갈색
    720: "#5b1a8c",  # 진한 보라
}

# 3분봉 거래대금 색상 구간 (거래대금은 종가*거래량, 단위: 억원)
VOL_COLOR_BANDS = [
    (10,  "#9aa0a8"),   # 10억 미만 - 회색
    (30,  "#f4c430"),   # 10~30억 - 계란 노른자색
    (50,  "#3366ff"),   # 30~50억 - 파랑
    (100, "#8e44ad"),   # 50~100억 - 보라
    (float("inf"), "#e60000"),  # 100억 이상 - 빨강
]
CUM_VOL_COLOR = "#f5871f"
CUM_VOL_LINE_500 = 500  # 억원 기준선

# 피보나치(당일 고가/저가 기준) 되돌림 비율 및 밴드 색상
FIBO_LEVELS = [0.75, 0.618, 0.5, 0.382]
FIBO_BAND1_COLOR = "rgba(245,166,35,0.35)"  # 0.75~0.618 구간 - 오렌지
FIBO_BAND2_COLOR = "rgba(47,191,173,0.35)"  # 0.5~0.382 구간 - 청록
FIBO_LINE_TOP_COLOR = "#e8a33d"
FIBO_LINE_BOTTOM_COLOR = "#2fbfad"

st.markdown(f"""
<style>
.stApp {{ background-color:{DARK_BG}; color:white; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 1rem; }}
div[data-testid="stVerticalBlock"] {{ gap: 0.35rem; }}
div[data-testid="stHorizontalBlock"] {{ gap: 0.3rem !important; }}
.stButton button {{ padding: 0.25rem 0.6rem !important; }}
div[data-testid="stMetric"] {{
    background-color:{CARD_BG};
    border: 1px solid {CARD_BORDER};
    padding:14px; border-radius:10px;
}}
.header-banner {{
    background: linear-gradient(90deg, #1a1f2e, #12161f);
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 14px;
    font-size: 14px;
    color: #b8c0d0;
}}
label, .stCheckbox label, .stRadio label, [data-testid="stCaptionContainer"] {{
    color: #dfe4ee !important;
}}
[data-testid="stWidgetLabel"] p {{
    color: #dfe4ee !important;
}}
.stMarkdown, .stMarkdown p {{
    color: #eaeef5 !important;
}}
.stButton button p {{
    color: #111111 !important;
}}
.st-key-memo_move_btn_wrap button p {{
    color: #b8860b !important;
}}
.st-key-kiwoom_theme_panel button p,
.st-key-naver_theme_panel button p {{
    color: #2dd4bf !important;
}}
.st-key-kiwoom_theme_panel, .st-key-naver_theme_panel {{
    padding: 4px !important;
}}
.st-key-kiwoom_stock_detail_list button p,
.st-key-naver_stock_detail_list button p {{
    color: #111111 !important;
}}
.copy-metric {{
    background-color: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    padding: 14px; border-radius: 10px;
    cursor: pointer;
}}
.copy-metric:hover {{
    border-color: {ORANGE};
}}
.copy-metric .label {{
    color: #9aa4b8; font-size: 13px; margin-bottom: 4px;
}}
.copy-metric .value {{
    color: #ffffff; font-size: 28px; font-weight: 700;
}}
.copy-metric .delta {{
    font-size: 14px; margin-top: 2px;
}}
</style>
""", unsafe_allow_html=True)

MARKET_OPEN = dtime(9, 0, 0)
MARKET_CLOSE = dtime(15, 30, 0)

WATCHLIST_FILE = "watchlist.json"
RECENT_FILE = "recent_searches.json"
MA_STATE_FILE = "ma_toggle_state.json"
MAX_RECENT = 8
DEFAULT_FOLDER = "기본"
MAX_FOLDERS = 100


# ----------------------------------------------------------------------
# 0. 영구 저장(관심종목 / 최근검색) - 로컬 JSON 파일
# ----------------------------------------------------------------------
def _load_json_list(path: str) -> list:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_json_list(path: str, data: list):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        st.warning(f"저장 실패: {e}")


def _load_watchlist_data():
    """
    폴더 구조 지원. 예전 버전(리스트만 저장된 파일)도 자동 마이그레이션.
    반환: (folders: list[str], items: list[dict])
    """
    folders, items = [DEFAULT_FOLDER], []
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "items" in data:
                folders = data.get("folders") or [DEFAULT_FOLDER]
                items = data.get("items", [])
            elif isinstance(data, list):
                items = data
                for it in items:
                    it.setdefault("folder", DEFAULT_FOLDER)
                folders = [DEFAULT_FOLDER]
        except (json.JSONDecodeError, OSError):
            pass
    if DEFAULT_FOLDER not in folders:
        folders.insert(0, DEFAULT_FOLDER)
    return folders, items


def _save_watchlist_data():
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"folders": st.session_state.folders, "items": st.session_state.watchlist},
                f, ensure_ascii=False, indent=2,
            )
    except OSError as e:
        st.warning(f"저장 실패: {e}")


if "watchlist" not in st.session_state or "folders" not in st.session_state:
    _folders, _items = _load_watchlist_data()
    st.session_state.folders = _folders
    st.session_state.watchlist = _items
if "recent" not in st.session_state:
    st.session_state.recent = _load_json_list(RECENT_FILE)  # [{"code":..., "name":...}]


def _load_ma_toggle_state() -> dict:
    """이평선 on/off 저장값 로드. 파일이 없으면(최초 실행) 5/20/60/120일선만 기본 on."""
    if os.path.exists(MA_STATE_FILE):
        try:
            with open(MA_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {int(k): bool(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return {p: (p in (5, 20, 60, 120)) for p in MA_PERIODS}


def _save_ma_toggle_state(state: dict):
    try:
        with open(MA_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in state.items()}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "ma_toggle_initialized" not in st.session_state:
    _ma_saved = _load_ma_toggle_state()
    for _p in MA_PERIODS:
        st.session_state[f"ma_on_{_p}"] = _ma_saved.get(_p, False)
    st.session_state.ma_toggle_initialized = True


def add_to_recent(code: str, name: str):
    lst = st.session_state.recent
    lst = [x for x in lst if x["code"] != code]
    snapshot = format_snapshot_line(code)
    _, _, _, vwap_price = get_stock_gap_snapshot(code)
    lst.insert(0, {"code": code, "name": name, "snapshot": snapshot, "vwap_price": vwap_price})
    st.session_state.recent = lst[:MAX_RECENT]
    _save_json_list(RECENT_FILE, st.session_state.recent)


def toggle_watchlist(code: str, name: str, folder: str = None):
    """폴더 없이 호출하면 제거만(추가 시 반드시 folder 지정)."""
    lst = st.session_state.watchlist
    if any(x["code"] == code for x in lst):
        lst = [x for x in lst if x["code"] != code]
    else:
        target_folder = folder or DEFAULT_FOLDER
        added_time = datetime.now().strftime("%y%m%d %H:%M")
        snapshot = format_snapshot_line(code)
        lst.append({
            "code": code, "name": name, "folder": target_folder,
            "memo": snapshot or "", "memo_time": added_time if snapshot else "",
            "added_time": added_time,
        })
    st.session_state.watchlist = lst
    _save_watchlist_data()


def add_folder(name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    if name in st.session_state.folders:
        return False
    if len(st.session_state.folders) >= MAX_FOLDERS:
        st.warning(f"폴더는 최대 {MAX_FOLDERS}개까지 만들 수 있습니다.")
        return False
    st.session_state.folders.append(name)
    _save_watchlist_data()
    return True


def rename_folder(old: str, new: str) -> bool:
    new = new.strip()
    if not new or new == old or new in st.session_state.folders:
        return False
    st.session_state.folders = [new if f == old else f for f in st.session_state.folders]
    for it in st.session_state.watchlist:
        if it.get("folder") == old:
            it["folder"] = new
    _save_watchlist_data()
    return True


def delete_folder(name: str):
    if name == DEFAULT_FOLDER:
        return
    st.session_state.folders = [f for f in st.session_state.folders if f != name]
    for it in st.session_state.watchlist:
        if it.get("folder") == name:
            it["folder"] = DEFAULT_FOLDER
    _save_watchlist_data()


def move_item_folder(code: str, new_folder: str):
    for it in st.session_state.watchlist:
        if it["code"] == code:
            it["folder"] = new_folder
    _save_watchlist_data()


def export_watchlist_txt() -> str:
    """관심종목을 폴더별로 묶어 txt 파일로 저장하고 파일명을 반환."""
    fname = f"watchlist_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    lines = []
    for folder in st.session_state.folders:
        items_in = [it for it in st.session_state.watchlist if it.get("folder") == folder]
        if not items_in:
            continue
        lines.append(f"[{folder}]")
        for item in items_in:
            lines.append(f"  {item['name']} ({item['code']})")
            lines.append(f"    추가시각: {item.get('added_time', '-')}")
            if item.get("memo"):
                lines.append(f"    메모: {item['memo']}  (기입: {item.get('memo_time', '-')})")
        lines.append("")
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return fname


def is_in_watchlist(code: str) -> bool:
    return any(x["code"] == code for x in st.session_state.watchlist)


def save_memo(code: str, memo_text: str):
    now_str = datetime.now().strftime("%y%m%d %H:%M")
    for item in st.session_state.watchlist:
        if item["code"] == code:
            item["memo"] = memo_text
            item["memo_time"] = now_str if memo_text else ""
    _save_watchlist_data()


def autosave_on_market_close():
    """장마감(15:30) 이후 하루 1회, 관심종목(폴더/메모 포함)을 날짜별 백업 파일로 저장."""
    now = datetime.now()
    if now.time() >= MARKET_CLOSE:
        today_str = now.strftime("%Y%m%d")
        if st.session_state.get("last_autosave_date") != today_str:
            backup_name = f"watchlist_backup_{today_str}.json"
            _save_json_list(backup_name, st.session_state.watchlist)
            st.session_state.last_autosave_date = today_str


autosave_on_market_close()


def render_watchlist_history(months: int = 3):
    """
    watchlist_backup_YYYYMMDD.json 파일들을 스캔해서
    최근 N개월간 날짜별로 저장된 관심종목 기록을 촘촘하게 표시.
    """
    import glob
    from datetime import timedelta

    files = glob.glob("watchlist_backup_*.json")
    if not files:
        return

    cutoff = datetime.now() - timedelta(days=months * 30)
    dated_files = []
    for f in files:
        try:
            date_part = f.replace("watchlist_backup_", "").replace(".json", "")
            dt = datetime.strptime(date_part, "%Y%m%d")
            if dt >= cutoff:
                dated_files.append((dt, f))
        except ValueError:
            continue

    if not dated_files:
        return

    dated_files.sort(key=lambda x: x[0], reverse=True)

    st.markdown("##### ?? 관심종목 저장 기록 (최근 3개월)")
    for dt, fname in dated_files:
        items = _load_json_list(fname)
        if not items:
            continue
        with st.expander(f"{dt.strftime('%Y-%m-%d')}  ({len(items)}종목)", expanded=False):
            for it in items:
                memo = it.get("memo", "").replace("\n", " / ")
                folder_tag = f"[{it.get('folder', DEFAULT_FOLDER)}] "
                st.markdown(
                    f"<div style='padding:2px 0; font-size:13px; line-height:1.4;'>"
                    f"{folder_tag}<b>{it['name']}</b> ({it['code']}) ? {memo or '기록 없음'}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ----------------------------------------------------------------------
# 0-1. 종목명 <-> 코드 매핑 (한글 검색 지원, pykrx 상장종목 목록 이용)
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner="종목 목록 불러오는 중...")
def load_stock_name_map():
    """
    {"삼성전자": "005930", ...} 형태의 딕셔너리 반환.
    FinanceDataReader로 KRX 상장종목 전체 목록을 한 번만 가져와 캐시.
    (로그인 불필요, pykrx 대체)
    """
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        code_col = "Code" if "Code" in df.columns else "Symbol"
        name_col = "Name"
        name_map = dict(zip(df[name_col], df[code_col]))
        return name_map
    except Exception as e:
        st.warning(f"종목명 매핑 로드 실패(코드로만 검색 가능): {e}")
        return {}


@st.cache_resource(show_spinner=False)
def load_stock_marketcap_map():
    """{"005930": 시가총액(원), ...} 형태의 딕셔너리 반환. FinanceDataReader의 Marcap 컬럼 이용."""
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        code_col = "Code" if "Code" in df.columns else "Symbol"
        if "Marcap" not in df.columns:
            return {}
        return dict(zip(df[code_col], df["Marcap"]))
    except Exception:
        return {}


def format_krw_large(value) -> str:
    """큰 원화 숫자를 조/억 단위로 보기 좋게 변환."""
    if value is None:
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    if value >= 1e12:
        return f"{value / 1e12:,.2f}조원"
    if value >= 1e8:
        return f"{value / 1e8:,.0f}억원"
    return f"{value:,.0f}원"


def resolve_query_to_code(query: str, name_map: dict):
    """입력값이 6자리 숫자면 코드로, 아니면 종목명으로 매핑."""
    query = query.strip()
    if query.isdigit() and len(query) == 6:
        reverse = {v: k for k, v in name_map.items()}
        return query, reverse.get(query, query)
    if query in name_map:
        return name_map[query], query
    matches = [n for n in name_map if query in n]
    if matches:
        best = matches[0]
        return name_map[best], best
    return None, None


# ----------------------------------------------------------------------
# 1. 키움 REST API로 당일 분봉 데이터 수집
# ----------------------------------------------------------------------
@st.cache_data(ttl=15, show_spinner=False)
def fetch_today_minute_data(code: str, interval_min: int = 3) -> pd.DataFrame:
    try:
        df = kiwoom_client.fetch_minute_chart(code, tick_range=interval_min)
    except Exception as e:
        st.warning(f"분봉 데이터 조회 실패: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    latest_date = df["datetime"].dt.date.max()
    df = df[df["datetime"].dt.date == latest_date]
    df = df[df["datetime"].dt.time >= MARKET_OPEN]
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------
# 2. 세력평단(VWAP 누적 거래량가중평균가) 계산
# ----------------------------------------------------------------------
def calc_seryeok_average(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["volume"] = df["volume"].fillna(0)
    df["vol_price"] = df["close"] * df["volume"]
    cum_vol = df["volume"].cumsum()
    cum_vp = df["vol_price"].cumsum()
    with np.errstate(divide="ignore", invalid="ignore"):
        seryeok = cum_vp / cum_vol
    fallback = df["close"].expanding().mean()
    df["seryeok_avg"] = seryeok.where(cum_vol > 0, fallback)
    df["seryeok_avg"] = df["seryeok_avg"].round(0)
    return df


def calc_buy_sell_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    세력 매수 평단 / 세력 매도 평단 (근사치).
    ?? 키움 분봉 API는 체결 건별 매수/매도 구분을 주지 않기 때문에,
    실제 매수·매도 체결량이 아니라 '틱룰(tick rule)' 근사로 계산합니다:
    직전 봉보다 종가가 오른 봉의 거래량은 매수 체결로, 내린(또는 같은) 봉의 거래량은
    매도 체결로 간주해 각각 누적 거래량가중평균가(VWAP)를 구합니다.
    (실시간 체결 데이터를 받아 진짜 매수/매도 체결을 구분하려면 별도의 실시간 체결 API 연동이 필요합니다.)
    """
    if df.empty:
        return df
    df = df.copy()
    df["volume"] = df["volume"].fillna(0)
    prev_close = df["close"].shift(1)
    is_up = df["close"] >= prev_close
    if len(is_up) > 0:
        is_up.iloc[0] = True  # 첫 봉은 매수로 간주(비교 대상 없음)

    buy_vol = df["volume"].where(is_up, 0.0)
    sell_vol = df["volume"].where(~is_up, 0.0)
    cum_buy_vol = buy_vol.cumsum()
    cum_sell_vol = sell_vol.cumsum()
    cum_buy_vp = (df["close"] * buy_vol).cumsum()
    cum_sell_vp = (df["close"] * sell_vol).cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        buy_avg = cum_buy_vp / cum_buy_vol
        sell_avg = cum_sell_vp / cum_sell_vol

    df["buy_avg"] = buy_avg.round(0)
    df["sell_avg"] = sell_avg.round(0)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def cached_theme_list_vwap_gap(code: str):
    """
    테마 목록에서만 쓰는 세력평단比(%) 계산. 60초 캐시로 API 호출 빈도를 낮춤.
    (메인 차트의 15초 캐시와는 별개)
    """
    try:
        df = fetch_today_minute_data(code, interval_min=3)
        if df.empty:
            return None
        df = calc_seryeok_average(df)
        last = df.iloc[-1]
        return (last["close"] - last["seryeok_avg"]) / last["seryeok_avg"] * 100
    except Exception:
        return None


def get_stock_gap_snapshot(code: str):
    """
    종목의 (전일比 등락률%, 세력평단比 괴리율%, 현재가, 세력평단가)을 계산해서 반환.
    실패 시 (None, None, None, None).
    """
    try:
        df = fetch_today_minute_data(code, interval_min=3)
        if df.empty:
            return None, None, None, None
        df = calc_seryeok_average(df)
        last = df.iloc[-1]

        pred_pre = last.get("pred_pre", 0) or 0
        yesterday_close = last["close"] - pred_pre
        day_pct = (pred_pre / yesterday_close * 100) if yesterday_close else None

        vwap_pct = (last["close"] - last["seryeok_avg"]) / last["seryeok_avg"] * 100

        return day_pct, vwap_pct, last["close"], last["seryeok_avg"]
    except Exception:
        return None, None, None, None


def format_snapshot_line(code: str) -> str:
    """
    [YYMMDD HH:MM] 현재가 ...원 세력평단 ...원 전일比 ...% 세력평단比 ...%
    형태의 한 줄 스냅샷 문자열을 만들어 반환. 데이터가 없으면 빈 문자열.
    """
    day_pct, vwap_pct, cur_price, vwap_price = get_stock_gap_snapshot(code)
    if cur_price is None:
        return ""
    now_str = datetime.now().strftime("%y%m%d %H:%M")
    parts = [f"[{now_str}]"]
    parts.append(f"전일比 {day_pct:+.2f}%" if day_pct is not None else "전일比 -")
    parts.append(f"세력평단比 {vwap_pct:+.2f}%" if vwap_pct is not None else "세력평단比 -")
    parts.append(f"현재가 {cur_price:,.0f}원")
    parts.append(f"세력평단 {vwap_price:,.0f}원" if vwap_price is not None else "세력평단 -")
    return " ".join(parts)


# ----------------------------------------------------------------------
# 2-1. 일봉 기준 이동평균선(5/20/60/120/240/480/720일) - 네이버 금융 일별시세
# ----------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_daily_ma_values(code: str) -> dict:
    """
    네이버 금융 일별시세(siseJson)로 최근 750거래일 종가를 받아
    5/20/60/120/240/480/720일 이동평균의 '최신값'을 계산해 반환.
    실패하거나 데이터가 부족한 기간은 None으로 채워서 반환.
    반환: {5: 12345.6, 20: ..., ..., 720: None}
    """
    import requests
    import ast

    result = {p: None for p in MA_PERIODS}
    try:
        url = (
            "https://api.finance.naver.com/siseJson.naver"
            f"?symbol={code}&requestType=1&startTime=19900101&endTime=99991231"
            "&timeframe=day"
        )
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        text = res.text.strip()
        # 응답이 JS 배열 리터럴 형태([['날짜','시가',...], [...], ...])라 ast로 안전하게 파싱
        text = text.replace("\n", "").replace("\t", "")
        rows = ast.literal_eval(text)
        if not rows or len(rows) < 2:
            return result
        header = rows[0]
        close_idx = header.index("종가") if "종가" in header else 4
        closes = []
        for r in rows[1:]:
            try:
                closes.append(float(r[close_idx]))
            except (ValueError, IndexError, TypeError):
                continue
        if not closes:
            return result
        s = pd.Series(closes)
        for p in MA_PERIODS:
            if len(s) >= p:
                result[p] = float(s.tail(p).mean())
        return result
    except Exception:
        return result


# ----------------------------------------------------------------------
# 3. 차트 렌더링
# ----------------------------------------------------------------------
def _vol_color(eok: float) -> str:
    for threshold, color in VOL_COLOR_BANDS:
        if eok < threshold:
            return color
    return VOL_COLOR_BANDS[-1][1]


def render_chart(df: pd.DataFrame, name: str, code: str, interval_min: int,
                  ma_values: dict = None, ma_toggles: dict = None,
                  fibo_on: bool = False, vol_on: bool = False, cumvol_on: bool = False):
    ma_values = ma_values or {}
    ma_toggles = ma_toggles or {}

    chart_date = df["datetime"].dt.date.iloc[-1]
    x_range = [datetime.combine(chart_date, MARKET_OPEN), datetime.combine(chart_date, MARKET_CLOSE)]

    # ---- 서브플롯 구성: 캔들(항상) + 3분봉 거래대금(옵션) + 누적거래대금(옵션) ----
    row_specs = ["price"]
    if vol_on:
        row_specs.append("vol")
    if cumvol_on:
        row_specs.append("cumvol")

    n_rows = len(row_specs)
    if n_rows == 1:
        row_heights = [1.0]
    elif n_rows == 2:
        row_heights = [0.7, 0.3]
    else:
        row_heights = [0.55, 0.225, 0.225]

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=row_heights,
    )
    price_row = 1

    fig.add_trace(go.Candlestick(
        x=df["datetime"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="주가",
        increasing=dict(line=dict(color=CANDLE_UP), fillcolor=CANDLE_UP),
        decreasing=dict(line=dict(color=CANDLE_DOWN), fillcolor=CANDLE_DOWN),
        hovertext=[
            f"시가: {o:,.0f}<br>고가: {h:,.0f}<br>저가: {l:,.0f}<br>종가: {c:,.0f}"
            for o, h, l, c in zip(df["open"], df["high"], df["low"], df["close"])
        ],
        hoverinfo="text+x",
    ), row=price_row, col=1)

    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["seryeok_avg"], mode="lines", name="세력평단",
        line=dict(color="#000000", width=3),
        hovertemplate="세력평단: %{y:,.0f}<extra></extra>",
    ), row=price_row, col=1)

    # 일봉 기준 이동평균선(수평 기준선) + 오른쪽 가격 라벨
    right_labels = []
    for p in MA_PERIODS:
        if ma_toggles.get(p) and ma_values.get(p) is not None:
            val = ma_values[p]
            fig.add_trace(go.Scatter(
                x=x_range, y=[val, val], mode="lines", name=f"{p}일선",
                line=dict(color=MA_COLORS[p], width=1.6, dash="dash"),
                hovertemplate=f"{p}일선: %{{y:,.0f}}<extra></extra>",
            ), row=price_row, col=1)
            right_labels.append((p, val))

    for p, val in right_labels:
        fig.add_annotation(
            xref="paper", x=1.005, xanchor="left",
            yref="y1", y=val, yanchor="middle",
            text=f"{val:,.0f}", showarrow=False,
            font=dict(color=MA_COLORS[p], size=12, family="Arial, sans-serif"),
            align="left",
        )

    # ---- 피보나치(당일 고가/저가 기준) ----
    fibo_prices = {}
    if fibo_on:
        day_high = float(df["high"].max())
        day_low = float(df["low"].min())
        fibo_rng = day_high - day_low
        for lv in FIBO_LEVELS:
            fibo_prices[lv] = day_low + fibo_rng * lv

        # 밴드(채움): 0.75~0.618 오렌지, 0.5~0.382 청록
        fig.add_hrect(y0=fibo_prices[0.618], y1=fibo_prices[0.75],
                      fillcolor=FIBO_BAND1_COLOR, line_width=0, row=price_row, col=1)
        fig.add_hrect(y0=fibo_prices[0.382], y1=fibo_prices[0.5],
                      fillcolor=FIBO_BAND2_COLOR, line_width=0, row=price_row, col=1)

        for lv in FIBO_LEVELS:
            line_color = FIBO_LINE_TOP_COLOR if lv >= 0.618 else FIBO_LINE_BOTTOM_COLOR
            val = fibo_prices[lv]
            fig.add_trace(go.Scatter(
                x=x_range, y=[val, val], mode="lines", name=f"피보 {lv}",
                line=dict(color=line_color, width=1, dash="dot"),
                hovertemplate=f"피보나치 {lv}: %{{y:,.0f}}<extra></extra>",
            ), row=price_row, col=1)
            fig.add_annotation(
                xref="paper", x=1.005, xanchor="left",
                yref="y1", y=val, yanchor="middle",
                text=f"{lv} · {val:,.0f}", showarrow=False,
                font=dict(color=line_color, size=11, family="Arial, sans-serif"),
                align="left",
            )

    # ---- 3분봉 거래대금(색상 구간별) ----
    if vol_on:
        vol_row = row_specs.index("vol") + 1
        trade_won = df["close"] * df["volume"]
        trade_eok = trade_won / 100_000_000
        bar_colors = [_vol_color(v) for v in trade_eok]
        fig.add_trace(go.Bar(
            x=df["datetime"], y=trade_eok, name="3분봉 거래대금",
            marker_color=bar_colors,
            hovertemplate="거래대금: %{y:,.1f}억<extra></extra>",
            showlegend=False,
        ), row=vol_row, col=1)
        fig.update_yaxes(
            title_text="거래대금(억)", side="right", showgrid=True, gridcolor="#e5e5e5",
            tickformat=",.0f", tickfont=dict(color="white"), title_font=dict(color="white"),
            row=vol_row, col=1,
        )

    # ---- 3분봉 누적거래대금 ----
    if cumvol_on:
        cum_row = row_specs.index("cumvol") + 1
        trade_won = df["close"] * df["volume"]
        cum_eok = (trade_won / 100_000_000).cumsum()
        fig.add_trace(go.Bar(
            x=df["datetime"], y=cum_eok, name="누적거래대금",
            marker_color=CUM_VOL_COLOR,
            hovertemplate="누적거래대금: %{y:,.1f}억<extra></extra>",
            showlegend=False,
        ), row=cum_row, col=1)
        fig.add_hline(y=CUM_VOL_LINE_500, line=dict(color="#000000", width=1.5),
                      row=cum_row, col=1)
        fig.update_yaxes(
            title_text="누적거래대금(억)", side="right", showgrid=True, gridcolor="#e5e5e5",
            tickformat=",.0f", tickfont=dict(color="white"), title_font=dict(color="white"),
            row=cum_row, col=1,
        )

    fig.update_layout(
        title=f"{name} ({code}) ({interval_min}분봉) - {chart_date}",
        plot_bgcolor="white", paper_bgcolor=CARD_BG, font=dict(color="white"),
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        margin=dict(l=40, r=70, t=60, b=40), hovermode="x unified",
        height=520 if n_rows == 1 else (620 if n_rows == 2 else 760),
    )
    fig.update_xaxes(showgrid=False, range=x_range, rangeslider=dict(visible=False))
    fig.update_xaxes(tickformat="%H:%M", tickfont=dict(color="white"), row=n_rows, col=1)
    if n_rows > 1:
        fig.update_xaxes(showticklabels=False, row=price_row, col=1)
        vol_row = row_specs.index("vol") + 1 if vol_on else None
        if vol_row is not None and vol_row != n_rows:
            fig.update_xaxes(showticklabels=False, row=vol_row, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", tickformat=",.0f",
                      tickfont=dict(color="white"), row=price_row, col=1)

    st.plotly_chart(
        fig, use_container_width=True,
        config={
            "locale": "ko",
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        },
    )

    # 이평선 가격 복사 버튼 (콤마/원 등 특수문자 없이 숫자만 클립보드에 복사)
    if right_labels:
        st.caption("이평선 가격 복사")
        label_cols = st.columns(len(right_labels))
        for i, (p, val) in enumerate(right_labels):
            with label_cols[i]:
                ma_price_copy_button(p, val, MA_COLORS[p], key=f"{code}_{p}")


# ----------------------------------------------------------------------
# 3-1. 클릭하면 클립보드로 복사되는 숫자 카드
# ----------------------------------------------------------------------
def copy_metric(label: str, value_text: str, copy_text: str, delta_text: str = "", delta_color: str = "#eaeef5", value_color: str = "#ffffff"):
    import streamlit.components.v1 as components
    html = f"""
    <div class="copy-metric" onclick="
        navigator.clipboard.writeText('{copy_text}');
        this.querySelector('.label').innerText='? 복사됨';
        setTimeout(() => {{ this.querySelector('.label').innerText='{label}'; }}, 1200);
    ">
        <div class="label">{label}</div>
        <div class="value" style="color:{value_color};">{value_text}</div>
        <div class="delta" style="color:{delta_color};">{delta_text}</div>
    </div>
    """
    components.html(f"""
    <style>
    .copy-metric {{
        background-color: {CARD_BG}; border: 1px solid {CARD_BORDER};
        padding: 14px; border-radius: 10px; cursor: pointer; font-family: sans-serif;
    }}
    .copy-metric:hover {{ border-color: {ORANGE}; }}
    .copy-metric .label {{ color: #9aa4b8; font-size: 13px; margin-bottom: 4px; }}
    .copy-metric .value {{ font-size: 28px; font-weight: 700; }}
    .copy-metric .delta {{ font-size: 14px; margin-top: 2px; }}
    </style>
    {html}
    """, height=110)


def tiny_copy_button(copy_text: str, key: str):
    """작은 복사 아이콘. 클릭하면 copy_text만 클립보드에 복사."""
    import streamlit.components.v1 as components
    components.html(f"""
    <style>
    .tiny-copy-{key} {{
        display:inline-flex; align-items:center; justify-content:center;
        width: 26px; height: 26px; border-radius: 6px;
        background-color: {CARD_BG}; border: 1px solid {CARD_BORDER};
        cursor: pointer; font-size: 13px; color: #dfe4ee; font-family: sans-serif;
    }}
    .tiny-copy-{key}:hover {{ border-color: {ORANGE}; }}
    </style>
    <div class="tiny-copy-{key}" title="세력평단 가격 복사" onclick="
        navigator.clipboard.writeText('{copy_text}');
        this.innerText='?';
        setTimeout(() => {{ this.innerText='??'; }}, 1000);
    ">??</div>
    """, height=32)


def ma_price_copy_button(period: int, price: float, color: str, key: str):
    """이평선 가격 복사 버튼. 클릭하면 콤마/원 등 특수문자 없이 숫자만 클립보드에 복사."""
    import streamlit.components.v1 as components
    plain_number = f"{price:.0f}"  # 콤마/특수문자 없이 숫자만
    display_text = f"{price:,.0f}"
    components.html(f"""
    <style>
    .ma-copy-{key} {{
        display:flex; align-items:center; justify-content:center; gap:4px;
        padding: 4px 6px; border-radius: 6px;
        background-color: {CARD_BG}; border: 1px solid {CARD_BORDER};
        cursor: pointer; font-size: 12px; font-family: sans-serif;
        color: {color}; font-weight: 600;
    }}
    .ma-copy-{key}:hover {{ border-color: {color}; }}
    </style>
    <div class="ma-copy-{key}" title="{period}일선 가격 복사" onclick="
        navigator.clipboard.writeText('{plain_number}');
        this.querySelector('.txt').innerText='? 복사됨';
        setTimeout(() => {{ this.querySelector('.txt').innerText='{period}일선 {display_text}'; }}, 1000);
    "><span class="txt">{period}일선 {display_text}</span></div>
    """, height=34)


def render_summary_box(lines: list):
    """
    [Day Trading Mapping 요약 분석] 형태의 압축된 요약 카드.
    클릭하면 전체 텍스트가 클립보드로 복사됨. 여백을 최소화한 콤팩트 레이아웃.
    lines[0] = 타이틀, 나머지 = ■ 항목 줄들
    """
    import streamlit.components.v1 as components
    title = lines[0]
    body_lines = lines[1:]
    copy_text = "\n".join(lines)
    body_html = "".join(f"<div class='sum-line'>■ {l}</div>" for l in body_lines)
    components.html(f"""
    <style>
    .summary-box {{
        background-color:{CARD_BG}; border:1px solid {CARD_BORDER};
        border-radius:8px; padding:8px 12px; cursor:pointer;
        font-family:'Malgun Gothic', sans-serif; color:#eaeef5;
        line-height:1.45;
    }}
    .summary-box:hover {{ border-color:{ORANGE}; }}
    .summary-box .sum-title {{ font-size:14px; font-weight:700; margin-bottom:2px; color:#fff; }}
    .summary-box .sum-line {{ font-size:13.5px; }}
    .summary-copied {{ color:{ORANGE}; font-size:11.5px; height:14px; }}
    </style>
    <div class="summary-box" onclick="
        navigator.clipboard.writeText(`{copy_text}`);
        document.getElementById('sumcopied_{abs(hash(copy_text))}').style.visibility='visible';
        setTimeout(() => {{ document.getElementById('sumcopied_{abs(hash(copy_text))}').style.visibility='hidden'; }}, 1200);
    ">
        <div class="sum-title">{title}</div>
        {body_html}
        <div id="sumcopied_{abs(hash(copy_text))}" class="summary-copied" style="visibility:hidden;">? 복사됨</div>
    </div>
    """, height=24 + 19 * len(body_lines) + 20)


# ----------------------------------------------------------------------
# 4. 헤더 배너
# ----------------------------------------------------------------------
st.markdown("## ? Day trading Mapping")

name_map = load_stock_name_map()
marketcap_map = load_stock_marketcap_map()

main_col, side_col = st.columns([2, 1.6])

with main_col:

    # ----------------------------------------------------------------------
    # 5. 검색창 + 최근검색 + 관심종목 + 분봉선택 + 새로고침
    # ----------------------------------------------------------------------
    if "query_input" not in st.session_state:
        st.session_state.query_input = "삼성전자"

    # 칩(최근검색/관심종목) 클릭으로 예약된 이동 요청을 위젯 생성 "전에" 반영
    if "goto_query" in st.session_state:
        st.session_state.query_input = st.session_state.pop("goto_query")

    col_a, col_b, col_c = st.columns([3, 1, 2])
    with col_a:
        query = st.text_input("종목명 또는 6자리 코드 입력", key="query_input")
    with col_b:
        st.write("")
        st.write("")
        search_clicked = st.button("? 조회", use_container_width=True)
    with col_c:
        interval = st.radio("분봉", ["1분봉", "3분봉", "5분봉"], index=1, horizontal=True)
    interval_min = {"1분봉": 1, "3분봉": 3, "5분봉": 5}[interval]

    # 종목 코드 조기 해석 (최근검색에 검색 즉시 반영되도록 칩 렌더링보다 먼저 처리)
    resolved_code, resolved_name_early = (None, None)
    if query:
        resolved_code, resolved_name_early = resolve_query_to_code(query, name_map)
        if resolved_code is not None:
            add_to_recent(resolved_code, resolved_name_early)

    # 최근 검색 칩 (마우스오버하면 검색 당시 스냅샷 표시)
    if st.session_state.recent:
        st.caption("최근 검색")
        recent_cols = st.columns(len(st.session_state.recent) + 1)
        for i, item in enumerate(st.session_state.recent):
            tooltip = item.get("snapshot") or "스냅샷 정보 없음"
            with recent_cols[i]:
                if st.button(f"{item['name']} ({item['code']})", key=f"recent_{item['code']}", help=tooltip):
                    st.session_state.goto_query = item["name"]
                    st.rerun()

    # 관심종목 (폴더별 정리, 폴더 생성/이름변경/삭제/이동 가능)
    if st.session_state.watchlist or len(st.session_state.folders) > 1:
        wl_header_col1, wl_header_col2, wl_header_col3 = st.columns([3, 1, 1])
        with wl_header_col1:
            st.caption("? 관심종목 (폴더별 정리)")
        with wl_header_col2:
            with st.popover("?? 새 폴더"):
                new_folder_name = st.text_input("폴더 이름", key="new_folder_input", label_visibility="collapsed")
                if st.button("만들기", key="new_folder_btn"):
                    if add_folder(new_folder_name):
                        st.rerun()
        with wl_header_col3:
            if st.button("?? TXT 저장", key="export_txt_btn"):
                fname = export_watchlist_txt()
                st.success(f"저장됨: {fname}")

        FOLDERS_PER_ROW = 10
        folders_list = st.session_state.folders
        for row_start in range(0, len(folders_list), FOLDERS_PER_ROW):
            row_folders = folders_list[row_start:row_start + FOLDERS_PER_ROW]
            folder_row_cols = st.columns(len(row_folders))
            for col, folder in zip(folder_row_cols, row_folders):
                with col:
                    items_in = [it for it in st.session_state.watchlist if it.get("folder") == folder]
                    with st.expander(f"?? {folder} ({len(items_in)})", expanded=False):
                        new_name = st.text_input(
                            "이름변경", value=folder, key=f"rename_input_{folder}", label_visibility="collapsed"
                        )
                        if st.button("이름변경", key=f"renamebtn_{folder}", use_container_width=True):
                            if rename_folder(folder, new_name):
                                st.rerun()
                        if folder != DEFAULT_FOLDER:
                            if st.button("폴더삭제", key=f"delbtn_{folder}", use_container_width=True):
                                delete_folder(folder)
                                st.rerun()

                        if not items_in:
                            st.caption("종목 없음")
                        else:
                            for item in items_in:
                                tooltip = item.get("memo", "") or "메모 없음"
                                if item.get("memo_time"):
                                    tooltip += f" ({item['memo_time']})"
                                elif item.get("added_time"):
                                    tooltip += f" / 추가: {item['added_time']}"
                                if st.button(
                                    f"★{item['name']}", key=f"wl_{item['code']}_{folder}",
                                    help=tooltip, use_container_width=True,
                                ):
                                    st.session_state.goto_query = item["name"]
                                    st.rerun()

    # 새로고침 컨트롤 + 관심종목 추가/해제 + 메모·폴더이동 (한 줄, 여백 없이 촘촘하게)
    ctrl_cols = st.columns([1.4, 1.6, 1.3, 1.6, 3])
    with ctrl_cols[0]:
        manual_refresh = st.button("?? 지금 새로고침", use_container_width=True)
    with ctrl_cols[1]:
        auto_refresh = st.checkbox(
            "자동 새로고침 (15초마다)", value=True,
            disabled=not HAS_AUTOREFRESH,
            help=None if HAS_AUTOREFRESH else "pip install streamlit-autorefresh 필요",
        )
    with ctrl_cols[2]:
        if resolved_code is not None:
            if is_in_watchlist(resolved_code):
                if st.button("★ 관심종목 해제", key="star_toggle_top", use_container_width=True):
                    toggle_watchlist(resolved_code, resolved_name_early)
                    st.rerun()
            else:
                if st.button("☆ 관심종목 추가", key="star_toggle_top", use_container_width=True):
                    target_folder = st.session_state.get("last_folder", DEFAULT_FOLDER)
                    if target_folder not in st.session_state.folders:
                        target_folder = DEFAULT_FOLDER
                    toggle_watchlist(resolved_code, resolved_name_early, folder=target_folder)
                    st.session_state.last_folder = target_folder
                    st.rerun()
    with ctrl_cols[3]:
        if st.session_state.watchlist:
            with st.container(key="memo_move_btn_wrap"):
                with st.popover("? 메모 / 폴더이동", use_container_width=True):
                    items = st.session_state.watchlist
                    names = [f"[{it.get('folder', DEFAULT_FOLDER)}] {it['name']} ({it['code']})" for it in items]
                    default_sel = 0
                    if resolved_code is not None:
                        for k, it in enumerate(items):
                            if it["code"] == resolved_code:
                                default_sel = k
                                break
                    sel_idx = st.selectbox(
                        "종목 선택", range(len(items)), index=default_sel,
                        format_func=lambda i: names[i], key="memo_target_idx",
                    )
                    target = items[sel_idx]
                    if target.get("added_time"):
                        st.caption(f"추가시각: {target['added_time']}")

                    new_memo = st.text_input("메모", value=target.get("memo", ""), key=f"memo_input_{target['code']}")
                    if st.button("메모 저장", key="savememo_shared_btn"):
                        snapshot_line = format_snapshot_line(target["code"]) or "스냅샷 정보 없음"
                        combined_memo = (new_memo + "\n" + snapshot_line) if new_memo else snapshot_line
                        save_memo(target["code"], combined_memo)
                        st.rerun()
                    if target.get("memo_time"):
                        st.caption(f"마지막 기입: {target['memo_time']}")

                    st.markdown("---")
                    move_target_folder = st.selectbox(
                        "이동할 폴더", st.session_state.folders,
                        index=st.session_state.folders.index(target.get("folder", DEFAULT_FOLDER))
                        if target.get("folder", DEFAULT_FOLDER) in st.session_state.folders else 0,
                        key="move_folder_select",
                    )
                    if st.button("이 폴더로 이동", key="move_folder_btn"):
                        move_item_folder(target["code"], move_target_folder)
                        st.rerun()

    if manual_refresh:
        fetch_today_minute_data.clear()
        st.rerun()

    if auto_refresh and HAS_AUTOREFRESH:
        st_autorefresh(interval=15_000, key="auto_refresh_timer")

    # ----------------------------------------------------------------------
    # 6. 조회 실행
    # ----------------------------------------------------------------------
    if query:
        code, resolved_name = resolved_code, resolved_name_early

        if code is None:
            st.error(f"'{query}'에 해당하는 종목을 찾을 수 없습니다. 종목명이나 6자리 코드를 정확히 입력해주세요.")
        else:
            with st.spinner("당일 분봉 데이터를 불러오는 중..."):
                df = fetch_today_minute_data(code, interval_min=interval_min)

            if df.empty:
                st.warning("당일 분봉 데이터를 아직 받아오지 못했습니다. 장 시작 전이거나 일시적 오류일 수 있습니다.")
            else:
                df = calc_seryeok_average(df)

                st.markdown(f"### {resolved_name} ({code})")

                # 5/20/60/120일선은 항상 고정 on (버튼 없음), 240/480/720일선만 토글 버튼 유지
                FIXED_MA_ON = [5, 20, 60, 120]
                TOGGLE_MA_PERIODS = [240, 480, 720]

                ma_toggles = {p: True for p in FIXED_MA_ON}
                ma_cols = st.columns(len(TOGGLE_MA_PERIODS))
                for i, p in enumerate(TOGGLE_MA_PERIODS):
                    with ma_cols[i]:
                        ma_toggles[p] = st.checkbox(
                            f"{p}일선", value=False, key=f"ma_on_{p}",
                        )
                        st.markdown(
                            f"<style>.st-key-ma_on_{p} label p "
                            f"{{ color:{MA_COLORS[p]} !important; font-weight:600; }}</style>",
                            unsafe_allow_html=True,
                        )

                with st.spinner("이동평균선 데이터 불러오는 중..."):
                    ma_values = fetch_daily_ma_values(code)
                _save_ma_toggle_state(ma_toggles)

                # 피보나치 / 거래대금 / 누적거래대금은 항상 표시(네트워크 조회 없이 계산만 하므로 버튼 없이 고정)
                fibo_on, vol_on, cumvol_on = True, True, True

                render_chart(df, name=resolved_name, code=code, interval_min=interval_min,
                             ma_values=ma_values, ma_toggles=ma_toggles,
                             fibo_on=fibo_on, vol_on=vol_on, cumvol_on=cumvol_on)

                last = df.iloc[-1]
                pred_pre = last.get("pred_pre", 0) or 0
                yesterday_close = last["close"] - pred_pre
                day_pct = (pred_pre / yesterday_close * 100) if yesterday_close else None
                day_color = "#b22222" if (day_pct or 0) > 0 else "#1f4e96" if (day_pct or 0) < 0 else "#eaeef5"

                c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
                diff = last["close"] - last["seryeok_avg"]
                diff_color = "#e05252" if diff > 0 else "#4a90e2" if diff < 0 else "#eaeef5"
                vwap_pct = diff / last["seryeok_avg"] * 100 if last["seryeok_avg"] else None
                acc_amount = (df["close"] * df["volume"]).sum()
                marcap = marketcap_map.get(code)
                with c1:
                    copy_metric("현재가", f"{last['close']:,.0f} 원", f"{last['close']:,.0f}")
                with c2:
                    copy_metric("세력평단(매수 기준)", f"{last['seryeok_avg']:,.0f} 원", f"{last['seryeok_avg']:.0f}")
                with c3:
                    copy_metric(
                        "전일比",
                        f"{day_pct:+.2f}%" if day_pct is not None else "-",
                        f"{day_pct:+.2f}%" if day_pct is not None else "-",
                        value_color=day_color,
                    )
                with c4:
                    copy_metric(
                        "세력평단比",
                        f"{vwap_pct:+.2f}%" if vwap_pct is not None else "-",
                        f"{vwap_pct:+.2f}%" if vwap_pct is not None else "-",
                        value_color=diff_color,
                    )
                with c5:
                    copy_metric(
                        "평단 대비",
                        f"{diff:+,.0f} 원",
                        f"{diff:+,.0f}",
                        delta_text=f"{vwap_pct:+.2f}%" if vwap_pct is not None else "",
                        delta_color=diff_color,
                    )
                with c6:
                    copy_metric(
                        "3분봉 누적거래대금",
                        format_krw_large(acc_amount),
                        f"{acc_amount:,.0f}",
                    )
                with c7:
                    copy_metric(
                        "시가총액",
                        format_krw_large(marcap) if marcap else "정보 없음",
                        f"{marcap:,.0f}" if marcap else "-",
                    )

                st.caption(
                    "※ 세력평단은 KRX/증권사가 제공하는 공식 지표가 아니라, "
                    "당일 09:00~현재까지 (종가×거래량)의 누적 가중평균(VWAP)으로 자체 계산한 값입니다."
                )

                df = calc_buy_sell_vwap(df)
                bs_last = df.iloc[-1]
                total_volume = df["volume"].sum()
                render_summary_box([
                    "[Day Trading Mapping 요약 분석]",
                    f"종목: {resolved_name} ({code})",
                    f"당일 전체 거래량: {total_volume:,.0f} 주",
                    f"전체 거래량 평단: {last['seryeok_avg']:,.0f} 원",
                    f"세력 매수 평단: {bs_last['buy_avg']:,.0f} 원" if pd.notna(bs_last["buy_avg"]) else "세력 매수 평단: -",
                    f"세력 매도 평단: {bs_last['sell_avg']:,.0f} 원" if pd.notna(bs_last["sell_avg"]) else "세력 매도 평단: -",
                ])
                st.caption(
                    "※ 세력 매수/매도 평단은 실제 체결 매수·매도 구분 데이터가 아니라, "
                    "직전 봉 대비 종가 등락으로 매수/매도를 추정한 근사치(틱룰)입니다."
                )

    render_watchlist_history(months=3)

# ----------------------------------------------------------------------
# 7. 우측 패널 - 업종 테마 분석 (ka90001 순위 + ka90002 구성종목) + 네이버 인기테마
# ----------------------------------------------------------------------
if "vwap_gap_last" not in st.session_state:
    # 종목코드별 마지막 세력평단比(%) 저장소.
    # 체크박스를 꺼도 여기 저장된 값은 지우지 않고 계속 화면에 표시한다.
    # (60초 재계산만 멈추고, 이전에 나온 수치는 그대로 유지)
    st.session_state.vwap_gap_last = {}

with side_col:
    naver_panel_col, kiwoom_panel_col = st.columns(2)

with kiwoom_panel_col:
    with st.container(key="kiwoom_theme_panel"):
        kh_col1, kh_col2, kh_col3 = st.columns([2.1, 2, 1.6], gap="small")
        with kh_col1:
            st.markdown("#### ?? 업종 테마 분석")
        with kh_col2:
            st.checkbox("세력평단比 (60초)", value=False, key="kiwoom_gap_enabled")
        with kh_col3:
            st.checkbox("1000억↓숨김", value=False, key="kiwoom_hide_smallcap",
                        help="시가총액 1000억원 미만 종목을 목록에서 숨깁니다.")

        if "selected_theme" not in st.session_state:
            st.session_state.selected_theme = None

        @st.cache_data(ttl=30, show_spinner=False)
        def cached_theme_groups():
            try:
                groups = kiwoom_client.fetch_theme_groups(date_tp="1", flu_pl_amt_tp="3", stex_tp="1")
            except Exception as e:
                st.warning(f"테마 목록 조회 실패: {e}")
                return []
            # API가 주는 순서를 신뢰하지 않고, 등락률 내림차순으로 재정렬
            def _rt(t):
                try:
                    return float(t.get("flu_rt", 0) or 0)
                except (TypeError, ValueError):
                    return 0.0
            return sorted(groups, key=_rt, reverse=True)

        @st.cache_data(ttl=30, show_spinner=False)
        def cached_theme_stocks(thema_grp_cd: str):
            try:
                return kiwoom_client.fetch_theme_stocks(thema_grp_cd, date_tp="1", stex_tp="1")
            except Exception as e:
                st.warning(f"테마 구성종목 조회 실패: {e}")
                return []

        theme_groups = cached_theme_groups()

        if not theme_groups:
            st.caption("테마 데이터를 불러오지 못했습니다.")
        else:
            for i, theme in enumerate(theme_groups[:30], start=1):
                grp_cd = theme.get("thema_grp_cd", "")
                grp_nm = theme.get("thema_nm", "")
                flu_rt = theme.get("flu_rt", "0")
                try:
                    flu_rt_f = float(flu_rt)
                except (TypeError, ValueError):
                    flu_rt_f = 0.0
                rate_color = "#e05c5c" if flu_rt_f < 0 else "#3ecb7a" if flu_rt_f > 0 else "#9aa4b8"

                row_label = f"{i}위 {grp_nm}  {flu_rt_f:+.2f}%"
                theme_row_key = f"themerow_{grp_cd}"
                st.markdown(
                    f"<style>.st-key-{theme_row_key} button p {{ color:#2ecc71 !important; }}</style>",
                    unsafe_allow_html=True,
                )
                with st.container(key=theme_row_key):
                    if st.button(row_label, key=f"theme_{grp_cd}", use_container_width=True):
                        if st.session_state.selected_theme == grp_cd:
                            st.session_state.selected_theme = None  # 다시 누르면 접기
                        else:
                            st.session_state.selected_theme = grp_cd
                        st.rerun()

                if st.session_state.selected_theme == grp_cd:
                    stocks = cached_theme_stocks(grp_cd)
                    if not stocks:
                        st.caption("구성종목 없음")
                    else:
                        with st.container(key="kiwoom_stock_detail_list"):
                            def _parse_price(v):
                                try:
                                    return abs(int(str(v).replace("+", "").replace("-", "")))
                                except (TypeError, ValueError):
                                    return 0

                            for s in stocks:
                                s_nm = s.get("stk_nm", "")
                                s_cd = s.get("stk_cd", "")
                                s_prc = _parse_price(s.get("cur_prc", "0"))
                                s_rt = s.get("flu_rt", "0")
                                try:
                                    s_rt_f = float(s_rt)
                                except (TypeError, ValueError):
                                    s_rt_f = 0.0
                                s_color = "#e05252" if s_rt_f > 0 else "#4a90e2" if s_rt_f < 0 else "#666666"

                                # 거래대금(근사치: 현재가 × 누적거래량) / 시가총액
                                s_vol = _parse_price(s.get("acc_trde_qty", "0"))
                                s_amount = s_prc * s_vol
                                s_marcap = marketcap_map.get(s_cd)

                                # 시가총액 1000억원 미만 종목 숨기기 (시총 정보가 없는 종목은 숨기지 않음)
                                if st.session_state.get("kiwoom_hide_smallcap", False) and s_marcap and s_marcap < 1e11:
                                    continue

                                # 세력평단 대비 괴리율(%) - 토글 ON일 때만 새로 계산(60초 캐시), 평소엔 API 호출 없음.
                                # 토글을 꺼도 마지막으로 계산됐던 값은 vwap_gap_last에 남아있으므로 계속 표시한다.
                                if st.session_state.get("kiwoom_gap_enabled", False):
                                    gap_pct = cached_theme_list_vwap_gap(s_cd)
                                    if gap_pct is not None:
                                        st.session_state.vwap_gap_last[s_cd] = gap_pct

                                gap_pct_show = st.session_state.vwap_gap_last.get(s_cd)
                                if gap_pct_show is not None:
                                    gap_text = f"{gap_pct_show:+.2f}%"
                                    gap_color = "#f4a6a6" if gap_pct_show > 0 else "#a6c8f4" if gap_pct_show < 0 else "#666666"
                                else:
                                    gap_text = "-"
                                    gap_color = "#666666"

                                # 시총 500억원 미만: 진한 파랑 / 500억~1000억: 파랑 / 3000억~5000억: 빨강
                                # / 5000억~9000억: 핑크 / 9000억 초과: 형광 핑크
                                btn_color = None
                                if s_marcap:
                                    if s_marcap < 5e10:
                                        btn_color = "#1a3fa0"
                                    elif s_marcap < 1e11:
                                        btn_color = "#4a90e2"
                                    elif s_marcap > 9e11:
                                        btn_color = "#ff10f0"
                                    elif s_marcap >= 5e11:
                                        btn_color = "#ff69b4"
                                    elif s_marcap >= 3e11:
                                        btn_color = "#e05252"

                                row_key = f"stkrow_{grp_cd}_{s_cd}"
                                if btn_color:
                                    st.markdown(
                                        f"<style>.st-key-{row_key} button p {{ color:{btn_color} !important; }}</style>",
                                        unsafe_allow_html=True,
                                    )
                                # 거래대금 30억~50억: 밤색 / 50억~100억: 초록 / 100억~500억: 계란노른자 / 500억 이상: 노랑
                                if s_amount >= 5e10:
                                    amt_color = "#ffe600"
                                elif s_amount >= 1e10:
                                    amt_color = "#f5c518"
                                elif s_amount >= 5e9:
                                    amt_color = "#2ecc71"
                                elif s_amount >= 3e9:
                                    amt_color = "#5c3317"
                                else:
                                    amt_color = "#eaeef5"
                                cap_color = btn_color if btn_color else "#eaeef5"
                                with st.container(key=row_key):
                                    row_col1, row_col2 = st.columns([2, 3])
                                    with row_col1:
                                        if st.button(s_nm, key=f"stk_{grp_cd}_{s_cd}", use_container_width=True):
                                            st.session_state.goto_query = s_cd
                                            st.rerun()
                                    with row_col2:
                                        st.markdown(
                                            f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                                            f"{s_prc:,.0f}원 전일比 <span style='color:{s_color};'>{s_rt_f:+.2f}%</span> "
                                            f"세력평단比 <span style='color:{gap_color};'>{gap_text}</span><br>"
                                            f"거래대금<span style='color:{amt_color};'>{format_krw_large(s_amount)}</span> "
                                            f"시총<span style='color:{cap_color};'>{format_krw_large(s_marcap) if s_marcap else '-'}</span>"
                                            f"</div>",
                                            unsafe_allow_html=True,
                                        )


with naver_panel_col:
    with st.container(key="naver_theme_panel"):
        # ----------------------------------------------------------------------
        # 8. 네이버 인기테마 (수동 새로고침 전용, 자동새로고침 걸지 않음 - IP차단 방지)
        # ----------------------------------------------------------------------
        st.markdown("#### ?? 네이버 인기테마 (수동 새로고침 전용)")
        st.caption("비공식 크롤링 데이터입니다. IP 차단 방지를 위해 자동새로고침 없이 버튼을 눌렀을 때만 조회합니다.")

        if "selected_naver_theme" not in st.session_state:
            st.session_state.selected_naver_theme = None
        if "naver_theme_cache" not in st.session_state:
            st.session_state.naver_theme_cache = None
        if "naver_theme_stock_cache" not in st.session_state:
            st.session_state.naver_theme_stock_cache = {}

        def fetch_naver_theme_list():
            """네이버 금융 테마 순위 목록. [{"no":..,"name":..,"change_pct":..}, ...]"""
            import requests
            from bs4 import BeautifulSoup

            headers = {"User-Agent": "Mozilla/5.0"}
            results = []
            for page in (1, 2):
                url = f"https://finance.naver.com/sise/theme.naver?page={page}"
                res = requests.get(url, headers=headers, timeout=6)
                res.encoding = "euc-kr"
                soup = BeautifulSoup(res.text, "html.parser")
                table = soup.select_one("table.type_1")
                if not table:
                    continue
                for row in table.select("tr"):
                    link = row.select_one("td.col_type1 a")
                    if not link:
                        continue
                    name = link.get_text(strip=True)
                    href = link.get("href", "")
                    no_match = None
                    if "no=" in href:
                        no_match = href.split("no=")[-1].split("&")[0]
                    num_tds = row.select("td.number")
                    change_pct = None
                    if num_tds:
                        txt = num_tds[0].get_text(strip=True).replace("%", "").replace("+", "")
                        try:
                            change_pct = float(txt)
                        except ValueError:
                            change_pct = None
                    if no_match:
                        results.append({"no": no_match, "name": name, "change_pct": change_pct})
            return results

        def fetch_naver_theme_stocks(theme_no: str):
            """네이버 테마 구성종목. [{"name":..,"code":..,"price":..,"change_pct":..}, ...]"""
            import requests
            from bs4 import BeautifulSoup

            headers = {"User-Agent": "Mozilla/5.0"}
            url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={theme_no}"
            res = requests.get(url, headers=headers, timeout=6)
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "html.parser")
            table = soup.select_one("table.type_5")
            if not table:
                return []
            stocks = []
            for row in table.select("tr"):
                link = row.select_one("a")
                if not link or "code=" not in link.get("href", ""):
                    continue
                name = link.get_text(strip=True)
                code = link.get("href", "").split("code=")[-1].split("&")[0]
                num_tds = row.select("td.number")
                price, change_pct, volume = None, None, None
                try:
                    if len(num_tds) >= 1:
                        price = int(num_tds[0].get_text(strip=True).replace(",", ""))
                    if len(num_tds) >= 3:
                        change_pct = float(num_tds[2].get_text(strip=True).replace("%", "").replace("+", ""))
                    if len(num_tds) >= 8:
                        volume = int(num_tds[7].get_text(strip=True).replace(",", ""))
                except (ValueError, IndexError):
                    pass
                stocks.append({"name": name, "code": code, "price": price, "change_pct": change_pct, "volume": volume})
            return stocks

        nv_col1, nv_col2, nv_col3 = st.columns([1.8, 2, 1.6], gap="small")
        with nv_col1:
            if st.button("?? 네이버 테마 새로고침", key="naver_theme_refresh"):
                try:
                    st.session_state.naver_theme_cache = fetch_naver_theme_list()
                    st.session_state.naver_theme_stock_cache = {}
                except Exception as e:
                    st.warning(f"네이버 테마 조회 실패: {e}")
        with nv_col2:
            st.checkbox("세력평단比 (60초)", value=False, key="naver_gap_enabled")
        with nv_col3:
            st.checkbox("1000억↓숨김", value=False, key="naver_hide_smallcap",
                        help="시가총액 1000억원 미만 종목을 목록에서 숨깁니다.")

        naver_groups = st.session_state.naver_theme_cache
        if naver_groups is None:
            st.caption("위 버튼을 눌러 조회해주세요.")
        elif not naver_groups:
            st.caption("데이터를 불러오지 못했습니다. 페이지 구조가 변경되었을 수 있어요.")
        else:
            for i, theme in enumerate(naver_groups[:30], start=1):
                no = theme["no"]
                nm = theme["name"]
                pct = theme.get("change_pct")
                pct_f = pct if pct is not None else 0.0
                row_label = f"{i}위 {nm}  {pct_f:+.2f}%" if pct is not None else f"{i}위 {nm}"
                naver_theme_row_key = f"naverthemerow_{no}"
                st.markdown(
                    f"<style>.st-key-{naver_theme_row_key} button p {{ color:#2ecc71 !important; }}</style>",
                    unsafe_allow_html=True,
                )
                with st.container(key=naver_theme_row_key):
                    if st.button(row_label, key=f"navertheme_{no}", use_container_width=True):
                        st.session_state.selected_naver_theme = None if st.session_state.selected_naver_theme == no else no
                        st.rerun()

                if st.session_state.selected_naver_theme == no:
                    if no not in st.session_state.naver_theme_stock_cache:
                        try:
                            st.session_state.naver_theme_stock_cache[no] = fetch_naver_theme_stocks(no)
                        except Exception as e:
                            st.warning(f"구성종목 조회 실패: {e}")
                            st.session_state.naver_theme_stock_cache[no] = []

                    stocks = st.session_state.naver_theme_stock_cache.get(no, [])
                    if not stocks:
                        st.caption("구성종목 없음")
                    else:
                        with st.container(key="naver_stock_detail_list"):
                            for s in stocks:
                                s_pct = s.get("change_pct")
                                s_color = "#e05252" if (s_pct or 0) > 0 else "#4a90e2" if (s_pct or 0) < 0 else "#666666"
                                s_amount = (s.get("price") or 0) * (s.get("volume") or 0)
                                s_marcap = marketcap_map.get(s["code"])

                                # 시가총액 1000억원 미만 종목 숨기기 (시총 정보가 없는 종목은 숨기지 않음)
                                if st.session_state.get("naver_hide_smallcap", False) and s_marcap and s_marcap < 1e11:
                                    continue

                                # 세력평단 대비 괴리율(%) - 토글 ON일 때만 새로 계산(60초 캐시), 평소엔 API 호출 없음.
                                # 토글을 꺼도 마지막으로 계산됐던 값은 vwap_gap_last에 남아있으므로 계속 표시한다.
                                if st.session_state.get("naver_gap_enabled", False):
                                    gap_pct = cached_theme_list_vwap_gap(s["code"])
                                    if gap_pct is not None:
                                        st.session_state.vwap_gap_last[s["code"]] = gap_pct

                                gap_pct_show = st.session_state.vwap_gap_last.get(s["code"])
                                if gap_pct_show is not None:
                                    gap_text = f"{gap_pct_show:+.2f}%"
                                    gap_color = "#f4a6a6" if gap_pct_show > 0 else "#a6c8f4" if gap_pct_show < 0 else "#666666"
                                else:
                                    gap_text = "-"
                                    gap_color = "#666666"

                                # 시총 500억원 미만: 진한 파랑 / 500억~1000억: 파랑 / 3000억~5000억: 빨강
                                # / 5000억~9000억: 핑크 / 9000억 초과: 형광 핑크
                                btn_color = None
                                if s_marcap:
                                    if s_marcap < 5e10:
                                        btn_color = "#1a3fa0"
                                    elif s_marcap < 1e11:
                                        btn_color = "#4a90e2"
                                    elif s_marcap > 9e11:
                                        btn_color = "#ff10f0"
                                    elif s_marcap >= 5e11:
                                        btn_color = "#ff69b4"
                                    elif s_marcap >= 3e11:
                                        btn_color = "#e05252"

                                row_key = f"naverstkrow_{no}_{s['code']}"
                                if btn_color:
                                    st.markdown(
                                        f"<style>.st-key-{row_key} button p {{ color:{btn_color} !important; }}</style>",
                                        unsafe_allow_html=True,
                                    )
                                with st.container(key=row_key):
                                    row_col1, row_col2 = st.columns([2, 3])
                                    with row_col1:
                                        if st.button(s["name"], key=f"naverstk_{no}_{s['code']}", use_container_width=True):
                                            st.session_state.goto_query = s["code"]
                                            st.rerun()
                                    with row_col2:
                                        pct_html = f"<span style='color:{s_color};'>{s_pct:+.2f}%</span>" if s_pct is not None else "-"
                                        amt_text = format_krw_large(s_amount) if s_amount else "-"
                                        cap_text = format_krw_large(s_marcap) if s_marcap else "-"
                                        # 거래대금 30억~50억: 밤색 / 50억~100억: 초록 / 100억~500억: 계란노른자 / 500억 이상: 노랑
                                        if s_amount and s_amount >= 5e10:
                                            amt_color = "#ffe600"
                                        elif s_amount and s_amount >= 1e10:
                                            amt_color = "#f5c518"
                                        elif s_amount and s_amount >= 5e9:
                                            amt_color = "#2ecc71"
                                        elif s_amount and s_amount >= 3e9:
                                            amt_color = "#5c3317"
                                        else:
                                            amt_color = "#eaeef5"
                                        cap_color = btn_color if btn_color else "#eaeef5"
                                        st.markdown(
                                            f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                                            f"{(s['price'] or 0):,.0f}원 전일比 {pct_html} "
                                            f"세력평단比 <span style='color:{gap_color};'>{gap_text}</span><br>"
                                            f"거래대금<span style='color:{amt_color};'>{amt_text}</span> "
                                            f"시총<span style='color:{cap_color};'>{cap_text}</span>"
                                            f"</div>",
                                            unsafe_allow_html=True,
                                        )
