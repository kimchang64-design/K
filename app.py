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
import re
import html
import requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date, time as dtime, timedelta

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

# N파동 목표가 T1~T6 가로점선 + 오른쪽 가격표시 색상(파스텔 초록, 잘 보이도록 통일)
NWAVE_TARGET_COLOR = "#77dd77"
NWAVE_TARGET_LINE_WIDTH = 2.5
# 분봉차트 "N봉 언덕 시각" 세로점선 색상(파스텔 초록)
NWAVE_HILL_LINE_COLOR = "#77dd77"
# 분봉차트 "세력평단가 시각" 세로점선 색상(밤색)
NWAVE_AVG_LINE_COLOR = "#5c3317"

# 일봉 기준 이동평균선 색상/표시명
MA_PERIODS = [5, 20, 60, 120, 240, 480, 720]

# 신호 스트립(일봉/분봉) 통합 호버 텍스트에 마커 모양을 글자로도 보여주기 위한 매핑
SIGNAL_MARKER_GLYPH = {
    "star": "★", "circle": "●", "triangle-up": "▲", "triangle-down": "▼",
    "arrow-up": "➤", "square": "■", "diamond": "◆", "x": "✕",
}
MA_COLORS = {
    5:   "#c48fd1",  # 연한 자주색
    20:  "#e74c3c",  # 빨강
    60:  "#8fa8d0",  # 옅은 남색 (기존 240일선 색)
    120: "#ffe066",  # 밝은 노랑
    240: "#0d2b6e",  # 진한 파랑 (기존 60일선 색)
    480: "#c9a27e",  # 옅은 갈색
    720: "#5b1a8c",  # 진한 보라
}

# 3분봉 거래대금 색상 구간 (거래대금은 종가*거래량, 단위: 억원)
VOL_COLOR_BANDS = [
    (10,   "#9aa0a8"),   # 10억 미만 - 회색
    (30,   "#f4c430"),   # 10~30억 - 계란 노른자색
    (50,   "#3366ff"),   # 30~50억 - 파랑
    (100,  "#8e44ad"),   # 50~100억 - 보라
    (500,  "#2ecc71"),   # 100~500억 - 초록
    (1000, "#e0ff4f"),   # 500~1000억 - 파스텔 형광색
    (float("inf"), "#7ec8ff"),  # 1000억 이상 - 하늘색
]
# 일봉 거래대금 색상 구간(같은 팔레트, 하루 전체 거래대금 규모에 맞게 임계값만 10배 확대)
VOL_COLOR_BANDS_DAILY = [
    (100,   "#9aa0a8"),   # 100억 미만 - 회색
    (300,   "#f4c430"),   # 100~300억 - 계란 노른자색
    (500,   "#3366ff"),   # 300~500억 - 파랑
    (1000,  "#8e44ad"),   # 500~1000억 - 보라
    (5000,  "#2ecc71"),   # 1000~5000억 - 초록
    (10000, "#e0ff4f"),   # 5000~10000억 - 파스텔 형광색
    (float("inf"), "#7ec8ff"),  # 1조 이상 - 하늘색
]
CUM_VOL_COLOR = "#f5871f"
CUM_VOL_LINE_500 = 500  # 억원 기준선

# 일봉 세력평단가 차트 전용 이동평균선 색상 (실선으로 계속 이어지는 진짜 이동평균선)
DAILY_MA_COLORS = {
    5:   "#1a7a3c",  # 진한 초록
    20:  "#e74c3c",  # 빨강
    60:  "#a64dff",  # 보라
    120: "#ffff00",  # 노랑
    240: "#3b4f8a",  # 중간 남색
    480: "#c9a27e",  # 연한 갈색
    720: "#5b1a8c",  # 진한 보라
}

# 3분봉 차트 전용 이동평균선(봉 개수 기준: 5/20/60/120봉) 색상
MIN_MA_PERIODS = [5, 20, 60, 120]
MIN_MA_COLORS = {
    5:   "#2ecc71",  # 밝은 초록
    20:  "#e74c3c",  # 빨강
    60:  "#a64dff",  # 보라
    120: "#ffe066",  # 노랑
}

# 20/60/120/240일선(일봉차트 실선 + 분봉차트 수평 기준선 공통)을 다른 선들보다 1단계 더 굵게 그리기 위한 가산치
_EMPHASIS_MA_PERIODS = {20, 60, 120, 240}
_MA_WIDTH_STEP = 0.6

# 분봉차트 전용 봉개수 이평선(MIN_MA_PERIODS) 중 20봉/60봉선만 1단계 더 굵게
_EMPHASIS_MIN_MA_PERIODS = {20, 60}

# 분봉차트에 표시할 중요 시간대 세로 회색 점선 (장중 특정 시각을 눈에 띄게 표시)
MIN_CHART_TIME_MARKS = [dtime(10, 20), dtime(12, 10), dtime(13, 50)]


def _theme_count_color(n: int) -> str:
    """테마 종목수 표시 색상: 3개이하 계란노른자 / 4~5 파랑 / 6~10 빨강 / 11~15 밝은초록 / 16~20 파스텔형광 / 21↑ 파스텔하늘색"""
    if n <= 3:
        return "#f4c430"
    elif n <= 5:
        return "#3366ff"
    elif n <= 10:
        return "#e60000"
    elif n <= 15:
        return "#2ecc71"
    elif n <= 20:
        return "#e0ff4f"
    else:
        return "#7ec8ff"

# 피보나치(당일 고가/저가 기준) 되돌림 비율 및 밴드 색상
FIBO_LEVELS = [0.75, 0.618, 0.5, 0.382]
FIBO_BAND1_COLOR = "rgba(245,166,35,0.35)"  # 0.75~0.618 구간 - 오렌지
FIBO_BAND2_COLOR = "rgba(47,191,173,0.35)"  # 0.5~0.382 구간 - 청록
FIBO_LINE_TOP_COLOR = "#e8a33d"
FIBO_LINE_BOTTOM_COLOR = "#2fbfad"

st.markdown(f"""
<style>
.stApp {{ background-color:{DARK_BG}; color:white; }}
header[data-testid="stHeader"] {{ display: none; }}
.block-container {{ padding-top: 0.25rem; padding-bottom: 1rem; padding-left: 0.6rem; padding-right: 0.6rem; max-width: 100% !important; }}
div[data-testid="stVerticalBlock"] {{ gap: 0.35rem; }}
div[data-testid="stHorizontalBlock"] {{ gap: 0.3rem !important; }}
.stButton button {{ padding: 0.25rem 0.6rem !important; }}
/* 년/월/일 날짜 드롭다운: 숫자만 겨우 들어갈 만큼 가로폭 최소화 */
div[class*="_wrap"] div[data-baseweb="select"] {{
    min-width: 58px !important;
}}
div[class*="_wrap"] div[data-baseweb="select"] > div {{
    padding-left: 6px !important;
    padding-right: 4px !important;
    min-height: 32px !important;
}}
div[class*="_wrap"] div[data-testid="stHorizontalBlock"] {{
    gap: 0.25rem !important;
}}
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
.stPopover button p,
[data-testid="stPopover"] button p {{
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
.st-key-kiwoom_theme_panel .stButton button,
.st-key-naver_theme_panel .stButton button {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
[class*="st-key-kiwoom_stock_detail_list_"] button p,
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
WL_UPDATE_FILE = "watchlist_update.json"
RECENT_FILE = "recent_searches.json"
MA_STATE_FILE = "ma_toggle_state.json"
CANDLE_FILL_STATE_FILE = "candle_fill_state.json"
AMT_HIDE_STATE_FILE = "amt_hide_state.json"
DAILY_CACHE_MODE_STATE_FILE = "daily_cache_mode_state.json"
MIN_CHART_TEMPLATE_STATE_FILE = "min_chart_template_state.json"
KIWOOM_THEME_POLL_STATE_FILE = "kiwoom_theme_poll_state.json"
SURGE_HIDDEN_STATE_FILE = "surge_rank_hidden_state.json"
THEME_HIDDEN_STATE_FILE = "theme_rank_hidden_state.json"
DAILY_VIEW_MONTHS_STATE_FILE = "daily_view_months_state.json"
DAILY_VIEW_MONTHS_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 24]  # '일날짜크기' 버튼 선택지
DAILY_VIEW_MONTHS_DEFAULT = 6  # '일날짜크기' 기본값(처음 실행 시, 저장된 값이 없을 때)
AMT_HIDE_PRESETS = [30, 50, 100, 200, 300, 400, 500, 1000]  # 억원 단위 빠른 필터 버튼

# 테마 목록에서 거래대금 기준 숨김 선택지 (원 단위 임계값, None=숨김 없음)
AMT_HIDE_OPTIONS = {
    "안함": None,
    "10억 미만 숨기기": 1e9,
    "30억 미만 숨기기": 3e9,
    "50억 미만 숨기기": 5e9,
    "100억 미만 숨기기": 1e10,
    "200억 미만 숨기기": 2e10,
    "300억 미만 숨기기": 3e10,
    "400억 미만 숨기기": 4e10,
    "500억 미만 숨기기": 5e10,
    "1000억 미만 숨기기": 1e11,
    "2000억 미만 숨기기": 2e11,
    "3000억 미만 숨기기": 3e11,
    "5000억 미만 숨기기": 5e11,
    "10000억 미만 숨기기": 1e12,
}
MAX_RECENT = 25
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


def _load_wl_update_data():
    """'업' 버튼으로 조회한 (경과일수/저장일 종가 대비 괴리율) 데이터 + 폴더별 정렬상태를
    영구 저장 파일에서 불러온다. 반환: (gap_data: {code: {"days":int, "gap":float}}, sort_order: {folder: "+"/"-"})"""
    if os.path.exists(WL_UPDATE_FILE):
        try:
            with open(WL_UPDATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("gap_data", {}) or {}, data.get("sort_order", {}) or {}
        except (json.JSONDecodeError, OSError):
            return {}, {}
    return {}, {}


def _save_wl_update_data():
    try:
        with open(WL_UPDATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "gap_data": st.session_state.wl_update_gap,
                    "sort_order": st.session_state.wl_update_sort,
                },
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
CHECKED_STOCKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checked_stocks_state.json")


def _load_checked_stocks() -> dict:
    """사이트를 새로고침/재시작해도 v체크된 종목이 유지되도록 디스크에서 복원 ({code: name})."""
    if os.path.exists(CHECKED_STOCKS_FILE):
        try:
            with open(CHECKED_STOCKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return {}


def _save_checked_stocks_if_changed():
    """v체크 종목이 바뀌었을 때만 디스크에 저장 (바뀐 게 없으면 아무것도 안 함)."""
    cur = dict(st.session_state.get("checked_stocks", {}))
    if cur == st.session_state.get("_checked_stocks_saved"):
        return
    try:
        with open(CHECKED_STOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
        st.session_state["_checked_stocks_saved"] = cur
    except OSError:
        pass


if "checked_stocks" not in st.session_state:
    st.session_state.checked_stocks = _load_checked_stocks()  # {code: name} - 테마 목록에서 체크한 종목(관심종목 일괄저장용)
    st.session_state["_checked_stocks_saved"] = dict(st.session_state.checked_stocks)
if "wl_update_gap" not in st.session_state or "wl_update_sort" not in st.session_state:
    _wl_upd_gap, _wl_upd_sort = _load_wl_update_data()
    st.session_state.wl_update_gap = _wl_upd_gap    # {code: {"days":int, "gap":float}} - '업' 버튼 눌러야 채워짐
    st.session_state.wl_update_sort = _wl_upd_sort  # {folder: "+"/"-"} - '업+'/'업-' 정렬 상태 (새로고침해도 유지)


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


def _load_candle_fill_state() -> dict:
    """캔들 영역채우기 on/off 저장값 로드. 파일 없으면(최초 실행) 기본 off."""
    if os.path.exists(CANDLE_FILL_STATE_FILE):
        try:
            with open(CANDLE_FILL_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: bool(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return {"min_fill_on": False, "daily_fill_on": False, "daily_signal_on": True, "daily_volume_on": True,
            "watch_marker_on": False, "daily_news_on": False}


def _save_candle_fill_state(state: dict):
    try:
        with open(CANDLE_FILL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _load_amt_hide_state() -> dict:
    """네이버/업종테마 공통 거래대금(대금) 숨김 설정 저장값 로드.
    '천억↓'(시가총액 소형주 숨김)은 새로고침할 때마다 항상 기본 체크(True) 상태로 시작하도록
    저장된 값을 쓰지 않고 매번 True로 고정한다."""
    if os.path.exists(AMT_HIDE_STATE_FILE):
        try:
            with open(AMT_HIDE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"choice": data.get("choice", "안함"), "smallcap": True}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return {"choice": "안함", "smallcap": True}


def _save_amt_hide_state(choice: str, smallcap: bool):
    try:
        with open(AMT_HIDE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"choice": choice, "smallcap": smallcap}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "amt_hide_initialized" not in st.session_state:
    _amt_saved = _load_amt_hide_state()
    st.session_state["shared_amt_hide_choice"] = _amt_saved["choice"]
    st.session_state["shared_hide_smallcap"] = _amt_saved["smallcap"]
    st.session_state.amt_hide_initialized = True
    st.session_state["_amt_hide_radio_ver"] = 0


def _load_daily_cache_mode() -> str:
    """일봉 데이터(fetch_daily_ohlcv) 캐시 주기 저장값 로드. 기본 '1h'."""
    if os.path.exists(DAILY_CACHE_MODE_STATE_FILE):
        try:
            with open(DAILY_CACHE_MODE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _m = data.get("mode", "1h")
            if _m in ("1h", "5h", "12h"):
                return _m
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return "1h"


def _save_daily_cache_mode(mode: str):
    try:
        with open(DAILY_CACHE_MODE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": mode}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "daily_cache_mode" not in st.session_state:
    st.session_state["daily_cache_mode"] = _load_daily_cache_mode()


def _load_min_chart_template() -> str:
    """분봉차트 '분차트틀'(기본/신호1) 선택값 로드. 기본값 '기본'. 새로고침/재시작해도 유지."""
    if os.path.exists(MIN_CHART_TEMPLATE_STATE_FILE):
        try:
            with open(MIN_CHART_TEMPLATE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _t = data.get("template", "기본")
            if _t in ("기본", "신호1"):
                return _t
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return "기본"


def _save_min_chart_template(template: str):
    try:
        with open(MIN_CHART_TEMPLATE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"template": template}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "min_chart_template" not in st.session_state:
    st.session_state["min_chart_template"] = _load_min_chart_template()


MINUTE_INTERVAL_OPTIONS = ["1", "3", "5", "10", "15", "30", "45", "60", "120", "240", "390"]
MINUTE_INTERVAL_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minute_interval_state.json")


def _load_minute_interval() -> str:
    """분봉 선택(1/3/5/10... 분) 저장값 로드. 기본값 '3'. 새로고침/재시작해도 유지."""
    if os.path.exists(MINUTE_INTERVAL_STATE_FILE):
        try:
            with open(MINUTE_INTERVAL_STATE_FILE, "r", encoding="utf-8") as f:
                v = str(json.load(f).get("interval", "3"))
            if v in MINUTE_INTERVAL_OPTIONS:
                return v
        except (json.JSONDecodeError, OSError, ValueError, AttributeError):
            pass
    return "3"


def _save_minute_interval(v: str):
    try:
        with open(MINUTE_INTERVAL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"interval": v}, f, ensure_ascii=False)
    except OSError:
        pass


if "minute_interval_radio" not in st.session_state:
    st.session_state["minute_interval_radio"] = _load_minute_interval()
    st.session_state["_minute_interval_saved"] = st.session_state["minute_interval_radio"]


# 10분봉 이상 '조회기간(개월)' 선택(1~12개월) 저장값 - 새로고침/재시작/종목 변경/분봉 종류 변경에도 유지
MINUTE_RANGE_MONTHS_OPTIONS = list(range(1, 13))
MINUTE_RANGE_MONTHS_DEFAULT = 5
MINUTE_RANGE_MONTHS_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minute_range_months_state.json")


def _load_minute_range_months() -> int:
    if os.path.exists(MINUTE_RANGE_MONTHS_STATE_FILE):
        try:
            with open(MINUTE_RANGE_MONTHS_STATE_FILE, "r", encoding="utf-8") as f:
                m = int(json.load(f).get("months", MINUTE_RANGE_MONTHS_DEFAULT))
            if m in MINUTE_RANGE_MONTHS_OPTIONS:
                return m
        except (json.JSONDecodeError, OSError, ValueError, TypeError, AttributeError):
            pass
    return MINUTE_RANGE_MONTHS_DEFAULT


def _save_minute_range_months(months: int):
    try:
        with open(MINUTE_RANGE_MONTHS_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"months": int(months)}, f, ensure_ascii=False)
    except OSError:
        pass


def _on_minute_range_months_change():
    _save_minute_range_months(st.session_state.get("minute_range_months", MINUTE_RANGE_MONTHS_DEFAULT))


# 1/3/5분봉처럼 이 위젯이 화면에 없는 동안 Streamlit이 위젯 상태를 지워버려도, 매 실행마다
# 저장된 값으로 복구해서 개월수가 유지되게 한다.
if "minute_range_months" not in st.session_state:
    st.session_state["minute_range_months"] = _load_minute_range_months()


# 1/3/5분봉 '(분일)' 선택(1~30일) 저장값 - 1이면 기존처럼 당일만, N이면 최근 N거래일치 캔들을 이어서 보여준다.
MINUTE_RANGE_DAYS_OPTIONS = list(range(1, 31))
MINUTE_RANGE_DAYS_DEFAULT = 1
MINUTE_RANGE_DAYS_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minute_range_days_state.json")


def _load_minute_range_days() -> int:
    if os.path.exists(MINUTE_RANGE_DAYS_STATE_FILE):
        try:
            with open(MINUTE_RANGE_DAYS_STATE_FILE, "r", encoding="utf-8") as f:
                d = int(json.load(f).get("days", MINUTE_RANGE_DAYS_DEFAULT))
            if d in MINUTE_RANGE_DAYS_OPTIONS:
                return d
        except (json.JSONDecodeError, OSError, ValueError, TypeError, AttributeError):
            pass
    return MINUTE_RANGE_DAYS_DEFAULT


def _save_minute_range_days(days: int):
    try:
        with open(MINUTE_RANGE_DAYS_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"days": int(days)}, f, ensure_ascii=False)
    except OSError:
        pass


def _on_minute_range_days_change():
    _save_minute_range_days(st.session_state.get("minute_range_days", MINUTE_RANGE_DAYS_DEFAULT))


if "minute_range_days" not in st.session_state:
    st.session_state["minute_range_days"] = _load_minute_range_days()


# '일먼'(일봉 먼저) 스위치 저장값: 켜면 종목을 고를 때 일봉 → 분봉 순서로 처리, 끄면(기본) 분봉 → 일봉. 주봉/월봉은 항상 마지막.
DAILY_FIRST_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_first_state.json")


def _load_daily_first() -> bool:
    try:
        with open(DAILY_FIRST_STATE_FILE, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("daily_first", False))
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return False


def _on_daily_first_change():
    try:
        with open(DAILY_FIRST_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"daily_first": bool(st.session_state.get("daily_first", False))}, f)
    except OSError:
        pass


if "daily_first" not in st.session_state:
    st.session_state["daily_first"] = _load_daily_first()


def _load_daily_view_months():
    """'일날짜크기' 버튼으로 고른 일봉차트 초기 표시 개월수 저장값 로드.
    저장된 값이 없으면 기본값 6개월. 새로고침/재시작해도 마지막으로 고른 개월수가
    유지되도록 로컬 파일에 저장해둔다."""
    if os.path.exists(DAILY_VIEW_MONTHS_STATE_FILE):
        try:
            with open(DAILY_VIEW_MONTHS_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _m = data.get("months")
            if _m is None or _m in DAILY_VIEW_MONTHS_OPTIONS:
                return _m
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return DAILY_VIEW_MONTHS_DEFAULT


def _save_daily_view_months(months):
    try:
        with open(DAILY_VIEW_MONTHS_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"months": months}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "daily_view_months" not in st.session_state:
    st.session_state["daily_view_months"] = _load_daily_view_months()


def _load_kiwoom_theme_poll_mode() -> str:
    """업종테마 목록/구성종목 자동조회 주기 저장값 로드. 기본 '30s'."""
    if os.path.exists(KIWOOM_THEME_POLL_STATE_FILE):
        try:
            with open(KIWOOM_THEME_POLL_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _m = data.get("mode", "30s")
            if _m in ("off", "30s", "23h"):
                return _m
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return "30s"


def _save_kiwoom_theme_poll_mode(mode: str):
    try:
        with open(KIWOOM_THEME_POLL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": mode}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "kiwoom_theme_poll_mode" not in st.session_state:
    # 새로고침/재시작할 때마다 항상 '로컬'(키움 미조회, 저장된 스냅샷만 사용)로 시작해서
    # 실수로 자동 폴링(30초/23시간)이 켜진 채로 남아있는 일이 없도록 한다.
    st.session_state["kiwoom_theme_poll_mode"] = "local"

THEME_RANK_SUN_FILTER_PREF_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "theme_rank_sun_filter_pref.txt"
)


def _load_theme_rank_sun_filter_pref() -> bool:
    """'순' 버튼(필터 통과 0종목인 테마 숨기기) 저장값 로드. 기본값 ON."""
    if os.path.exists(THEME_RANK_SUN_FILTER_PREF_FILE):
        try:
            with open(THEME_RANK_SUN_FILTER_PREF_FILE, "r", encoding="utf-8") as f:
                return f.read().strip() != "0"
        except Exception:
            return True
    return True


def _save_theme_rank_sun_filter_pref(enabled: bool):
    try:
        with open(THEME_RANK_SUN_FILTER_PREF_FILE, "w", encoding="utf-8") as f:
            f.write("1" if enabled else "0")
    except OSError:
        pass


if "theme_rank_sun_filter_on" not in st.session_state:
    # 새로고침/재시작하면 예전에 껐더라도 항상 ON(빨간 표시)으로 시작한다.
    st.session_state["theme_rank_sun_filter_on"] = True


def _load_surge_hidden_state() -> dict:
    """급등순위 '숨' 버튼으로 숨긴 종목(코드→숨긴 시점 스냅샷) 로드. 새로고침/PC 재부팅해도
    유지되도록 로컬 파일에 저장해둔다 - '복원'/'복' 버튼을 누르기 전까지는 계속 숨겨진 채로 남는다."""
    if os.path.exists(SURGE_HIDDEN_STATE_FILE):
        try:
            with open(SURGE_HIDDEN_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_surge_hidden_state(state: dict):
    try:
        with open(SURGE_HIDDEN_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "surge_rank_hidden" not in st.session_state:
    st.session_state.surge_rank_hidden = _load_surge_hidden_state()


def _load_theme_hidden_state() -> dict:
    """업종테마 순위에서 '숨' 버튼으로 숨긴 테마(코드→숨긴 시점 스냅샷) 로드. 급등순위와 동일하게
    새로고침/PC 재부팅해도 '복원'/'복' 버튼을 누르기 전까지 계속 숨겨진 채로 남는다."""
    if os.path.exists(THEME_HIDDEN_STATE_FILE):
        try:
            with open(THEME_HIDDEN_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_theme_hidden_state(state: dict):
    try:
        with open(THEME_HIDDEN_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if "theme_rank_hidden" not in st.session_state:
    st.session_state.theme_rank_hidden = _load_theme_hidden_state()


def add_to_recent(code: str, name: str):
    lst = st.session_state.recent
    lst = [x for x in lst if x["code"] != code]
    snapshot = format_snapshot_line(code)
    _, _, _, vwap_price = get_stock_gap_snapshot(code)
    lst.insert(0, {"code": code, "name": name, "snapshot": snapshot, "vwap_price": vwap_price})
    st.session_state.recent = lst[:MAX_RECENT]
    _save_json_list(RECENT_FILE, st.session_state.recent)


def get_first_watchlist_added_date(code: str):
    """이 종목이 관심종목(어느 폴더든)으로 저장된 적이 있으면, 그 중 가장 이른 저장일(date)을 반환.
    한 번도 저장된 적 없으면 None. added_time 형식: '%y%m%d %H:%M'."""
    candidates = []
    for it in st.session_state.get("watchlist", []):
        if it.get("code") != code:
            continue
        at = it.get("added_time")
        if not at:
            continue
        try:
            dt = datetime.strptime(at.strip(), "%y%m%d %H:%M")
            candidates.append(dt.date())
        except (ValueError, TypeError):
            continue
    return min(candidates) if candidates else None


def toggle_watchlist(code: str, name: str, folder: str = None, snapshot_override=None):
    """폴더 없이 호출하면 제거만(추가 시 반드시 folder 지정).
    snapshot_override를 주면 그 값(일봉 차트 선택 기간 기준)으로 메모 스냅샷을 저장."""
    lst = st.session_state.watchlist
    if any(x["code"] == code for x in lst):
        lst = [x for x in lst if x["code"] != code]
    else:
        target_folder = folder or DEFAULT_FOLDER
        added_time = datetime.now().strftime("%y%m%d %H:%M")
        snapshot = format_snapshot_line(code, override=snapshot_override)
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


def _rename_folder_on_enter(old_name: str):
    """폴더 이름 입력창에서 엔터(또는 포커스 아웃)만 눌러도 자동으로 이름이 바뀌도록 하는 콜백."""
    _new_val = st.session_state.get(f"rename_input_{old_name}", "")
    if rename_folder(old_name, _new_val):
        if old_name in st.session_state.wl_update_sort:
            st.session_state.wl_update_sort[_new_val.strip()] = st.session_state.wl_update_sort.pop(old_name)
            _save_wl_update_data()


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


def add_items_to_folder(items: list, folder: str):
    """체크된 종목들을 한꺼번에 지정 폴더에 저장(이미 있으면 그 폴더로 이동)."""
    lst = st.session_state.watchlist
    existing_codes = {x["code"] for x in lst}
    added_time = datetime.now().strftime("%y%m%d %H:%M")
    for it in items:
        code, name = it["code"], it["name"]
        if code in existing_codes:
            for x in lst:
                if x["code"] == code:
                    x["folder"] = folder
        else:
            snapshot = format_snapshot_line(code)
            lst.append({
                "code": code, "name": name, "folder": folder,
                "memo": snapshot or "", "memo_time": added_time if snapshot else "",
                "added_time": added_time,
            })
    st.session_state.watchlist = lst
    _save_watchlist_data()


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


@st.cache_data(ttl=20, show_spinner=False)
def _load_watchlist_history_files(months: int):
    """watchlist_backup_*.json 파일 목록+내용을 스캔해서 (date, fname, items) 리스트로 반환.
    파일이 많아질수록(수개월 누적) 매 재실행마다 전부 읽으면 느려지므로 20초 캐시."""
    import glob
    from datetime import timedelta

    files = glob.glob("watchlist_backup_*.json")
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
    dated_files.sort(key=lambda x: x[0], reverse=True)

    result = []
    for dt, fname in dated_files:
        items = _load_json_list(fname)
        if items:
            result.append((dt, fname, items))
    return result


def render_watchlist_history(months: int = 3):
    """
    watchlist_backup_YYYYMMDD.json 파일들을 스캔해서
    최근 N개월간 날짜별로 저장된 관심종목 기록을 촘촘하게 표시.
    """
    dated_files = _load_watchlist_history_files(months)
    if not dated_files:
        return

    st.markdown("##### 📅 관심종목 저장 기록 (최근 3개월)")
    for dt, fname, items in dated_files:
        with st.expander(f"{dt.strftime('%Y-%m-%d')}  ({len(items)}종목)", expanded=False):
            for it in items:
                memo = it.get("memo", "").replace("\n", " / ")
                folder_tag = f"[{it.get('folder', DEFAULT_FOLDER)}] "
                st.markdown(
                    f"<div style='padding:2px 0; font-size:13px; line-height:1.4;'>"
                    f"{folder_tag}<b>{it['name']}</b> ({it['code']}) — {memo or '기록 없음'}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ----------------------------------------------------------------------
# 0-1. 종목명 <-> 코드 매핑 (한글 검색 지원, pykrx 상장종목 목록 이용)
# ----------------------------------------------------------------------
def _load_krx_listing_with_fallback(max_back_days: int = 10) -> pd.DataFrame:
    """KRX 상장종목 전체 목록을 가져온다.
    1차: FinanceDataReader.StockListing("KRX") 정상 경로.
    2차: FinanceDataReader 내부적으로 참조하는 GitHub 캐시
        (raw.githubusercontent.com/.../data/listing/krx/{날짜}.csv) 가
        '오늘' 날짜분이 아직 안 올라와 404가 나는 경우가 흔하므로,
        하루씩 거슬러 올라가며 가장 최근에 올라와 있는 날짜의 CSV를 직접 시도한다.
    (최근 며칠치가 다 없으면 예외를 던져서 캐시하지 않고 다음 호출에서 재시도하게 한다.)
    """
    import FinanceDataReader as fdr
    try:
        return fdr.StockListing("KRX")
    except Exception:
        pass  # 아래 fallback으로 진행

    from datetime import timedelta
    base_url = (
        "https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
        "refs/heads/master/data/listing/krx/{}.csv"
    )
    last_err = None
    d = date.today()
    for _ in range(max_back_days):
        d = d - timedelta(days=1)
        url = base_url.format(d.strftime("%Y-%m-%d"))
        try:
            df = pd.read_csv(
                url, index_col=0,
                dtype={"Code": str, "Dept": str, "ChangeCode": str, "MarketId": str},
            )
            return df.reset_index(drop=True)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"최근 {max_back_days}일 내 KRX 종목 목록 캐시를 찾을 수 없습니다: {last_err}")


@st.cache_resource(show_spinner="종목 목록 불러오는 중...")
def load_stock_name_map():
    """
    {"삼성전자": "005930", ...} 형태의 딕셔너리 반환.
    FinanceDataReader로 KRX 상장종목 전체 목록을 한 번만 가져와 캐시.
    (로그인 불필요, pykrx 대체)
    실패 시 예외를 던져서(캐시하지 않고) 다음 호출에서 다시 시도하게 한다.
    """
    df = _load_krx_listing_with_fallback()
    code_col = "Code" if "Code" in df.columns else "Symbol"
    name_col = "Name"
    name_map = dict(zip(df[name_col], df[code_col]))
    if not name_map:
        raise RuntimeError("종목 목록이 비어 있습니다.")
    return name_map


@st.cache_resource(show_spinner=False)
def load_stock_marketcap_map():
    """{"005930": 시가총액(원), ...} 형태의 딕셔너리 반환. FinanceDataReader의 Marcap 컬럼 이용.
    실패 시 예외를 던져서(캐시하지 않고) 다음 호출에서 다시 시도하게 한다."""
    df = _load_krx_listing_with_fallback()
    code_col = "Code" if "Code" in df.columns else "Symbol"
    if "Marcap" not in df.columns:
        raise RuntimeError("Marcap 컬럼이 없습니다.")
    result = dict(zip(df[code_col], df["Marcap"]))
    if not result:
        raise RuntimeError("시가총액 목록이 비어 있습니다.")
    return result


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


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_prior_minute_history(code: str, interval_min: int, keep_bars: int = 450, months: int = 1) -> pd.DataFrame:
    """1/3/5분봉(당일만 표시)에서 300봉 볼린저·60봉선·완생5분 같은 긴 기간 지표를 계산하기 위한
    '오늘 이전' 분봉(최근 keep_bars개). 화면에는 그리지 않고 지표 계산에만 쓴다. 1시간 캐시.
    조회에 실패하거나 결과가 비어 있으면 경고 없이 빈 DataFrame을 돌려준다."""
    try:
        h = kiwoom_client.fetch_minute_chart_history(code, tick_range=interval_min, months=months)
        if h is None or h.empty or "datetime" not in h.columns:
            return pd.DataFrame()
        h = h[h["datetime"].dt.date < date.today()]
        h = h[h["datetime"].dt.time >= MARKET_OPEN]
        return h.sort_values("datetime").tail(keep_bars).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def fetch_minute_data_days(code: str, interval_min: int, days: int, use_local: bool = True) -> pd.DataFrame:
    """1/3/5분봉 '(분일)' 선택용: 최근 days거래일치 분봉(오늘 포함)을 이어서 돌려준다.
    확정된 날짜는 10분봉 이상과 같은 로컬 캐시를 쓰고, 오늘치만 매번 새로 받아온다."""
    months = max(1, -(-int(days) // 18))
    df_all = fetch_minute_data_range_local_first(code, interval_min=interval_min, months=months, use_local=use_local)
    if df_all is None or df_all.empty:
        return pd.DataFrame()
    keep_dates = sorted(df_all["datetime"].dt.date.unique())[-int(days):]
    return df_all[df_all["datetime"].dt.date.isin(keep_dates)].reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_minute_warm_history(code: str, interval_min: int, total_months: int,
                              before_dt, keep_bars: int = 450) -> pd.DataFrame:
    """10분봉 이상: 화면에 보이는 구간(before_dt 이전)의 지표 계산용 봉. total_months(보이는 개월수 + 여유분)만큼
    조회해서 before_dt 이전 봉만 최근 keep_bars개 돌려준다. 키움이 그 기간을 못 주면(빈 결과·오류) 개월수를
    줄여 한 번 더 시도하고, 그래도 안 되면 경고 없이 빈 DataFrame을 돌려준다."""
    tries = []
    for m in (int(total_months), 12):
        if m >= 2 and m not in tries:
            tries.append(m)
    for m in tries:
        try:
            h = kiwoom_client.fetch_minute_chart_history(code, tick_range=interval_min, months=m)
            if h is None or h.empty or "datetime" not in h.columns:
                continue
            h = h[h["datetime"].dt.time >= MARKET_OPEN]
            h = h[h["datetime"] < pd.Timestamp(before_dt)]
            if h.empty:
                continue
            return h.sort_values("datetime").tail(keep_bars).reset_index(drop=True)
        except Exception:
            continue
    return pd.DataFrame()


def calc_warm_extra_months(interval_min: int, target_bars: int = 360, cap: int = 9) -> int:
    """10분봉 이상: 화면에 보이는 개월수 앞쪽에 지표 계산용으로 더 받아올 개월수(약 target_bars봉 분량).
    (240분봉처럼 봉이 적게 쌓이는 분봉에서도 300봉 볼린저 '빨간선'이 보이게 하기 위함)"""
    bars_per_day = max(1, -(-390 // int(interval_min)))
    return int(min(cap, max(1, -(-target_bars // (21 * bars_per_day)))))


# 10분봉 이상(10/15/30/45/60/120/240분봉)은 당일치만 보여주지 않고, 일봉처럼 몇 개월치를
# 이어서 보여준다. 과거로 여러 번 나눠 호출해야 해서 시간이 좀 걸리므로 30분 캐시.
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_minute_data_range(code: str, interval_min: int = 10, months: int = 9) -> pd.DataFrame:
    try:
        df = kiwoom_client.fetch_minute_chart_history(code, tick_range=interval_min, months=months)
    except Exception as e:
        st.warning(f"분봉 데이터 조회 실패: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df = df[df["datetime"].dt.time >= MARKET_OPEN]
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------
# 1-1. 10분봉 이상 로컬(내 PC) 캐시 - 키움에 매번 다시 조회하지 않도록 확정된(오늘 이전) 분봉을
# 로컬 JSON 파일로 저장해둔다. 오늘치 분봉은 장중에 계속 바뀌므로 캐시하지 않고 항상 새로
# 가져오지만, 그건 어차피 "당일 조회" 1건짜리라 가볍다. "로컬" 체크박스로 켜고 끌 수 있고,
# "로컬 비우기" 버튼으로 저장된 파일을 전부 지울 수 있다.
# ----------------------------------------------------------------------
MINUTE_CACHE_DIR = "minute_cache"


def _minute_cache_path(code: str, interval_min: int) -> str:
    os.makedirs(MINUTE_CACHE_DIR, exist_ok=True)
    return os.path.join(MINUTE_CACHE_DIR, f"{code}_{interval_min}.json")


def _load_minute_cache(code: str, interval_min: int) -> pd.DataFrame:
    path = _minute_cache_path(code, interval_min)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df
    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError):
        return pd.DataFrame()


def _minute_meta_path(code: str, interval_min: int) -> str:
    return os.path.join(MINUTE_CACHE_DIR, f"{code}_{interval_min}.meta.json")


def _load_minute_meta(code: str, interval_min: int) -> dict:
    try:
        with open(_minute_meta_path(code, interval_min), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_minute_meta(code: str, interval_min: int, meta: dict):
    try:
        os.makedirs(MINUTE_CACHE_DIR, exist_ok=True)
        with open(_minute_meta_path(code, interval_min), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError:
        pass


def _save_minute_cache(code: str, interval_min: int, df: pd.DataFrame):
    if df.empty:
        return
    path = _minute_cache_path(code, interval_min)
    try:
        out = df.copy()
        out["datetime"] = out["datetime"].astype(str)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out.to_dict(orient="records"), f, ensure_ascii=False)
    except OSError as e:
        st.warning(f"로컬 분봉 캐시 저장 실패: {e}")


def clear_minute_local_cache() -> int:
    """'로컬 비우기' 버튼: 10분봉 이상 로컬 분봉 캐시 파일을 모두 삭제한다. 삭제한 파일 수를 반환."""
    if not os.path.isdir(MINUTE_CACHE_DIR):
        return 0
    n = 0
    for fn in os.listdir(MINUTE_CACHE_DIR):
        try:
            os.remove(os.path.join(MINUTE_CACHE_DIR, fn))
            n += 1
        except OSError:
            pass
    return n


def fetch_minute_data_range_local_first(code: str, interval_min: int, months: int,
                                         use_local: bool = True) -> pd.DataFrame:
    """10분봉 이상 데이터를 가져오되, 로컬 캐시를 우선 사용한다.
    - '확정된'(오늘보다 이전 날짜) 분봉은 한 번 키움에서 받아오면 절대 바뀌지 않으므로,
      로컬 캐시가 이미 목표 개월 수만큼 커버하고 있으면 키움 API를 다시 호출하지 않는다.
    - 오늘치 분봉은 장중에 계속 바뀌므로 캐시에 넣지 않고, 가벼운 '당일 조회' 1건으로 매번
      새로 받아와서 합친다.
    - use_local=False면 캐시를 아예 쓰지 않고(읽지도 저장하지도 않고) 기존처럼 키움에서 그대로
      받아온다."""
    today = date.today()
    cutoff = today - timedelta(days=int(months * 30.5))

    confirmed = pd.DataFrame()
    if use_local:
        cached = _load_minute_cache(code, interval_min)
        if not cached.empty:
            confirmed = cached[cached["datetime"].dt.date < today]

    need_backfill = confirmed.empty or confirmed["datetime"].dt.date.min() > cutoff
    # 같은 개월수의 '과거 쪽 채우기'는 하루에 한 번만 시도한다. (상장한 지 얼마 안 된 종목이나 키움이 그 기간을 못 주는
    # 경우, 캐시가 영영 목표 개월수에 못 미쳐서 화면을 다시 그릴 때마다 키움을 반복 호출하던 것을 막는다.
    # 실패해도 그날은 재시도하지 않으며, '로컬 비우기'를 누르면 기록도 지워져서 다시 시도한다.)
    meta = _load_minute_meta(code, interval_min) if use_local else {}
    bf_key = f"{today.isoformat()}:{months}"
    if need_backfill and use_local and meta.get("backfill") == bf_key:
        need_backfill = False

    # 오래된/구멍 난 캐시 자동 보충: 캐시는 '오래된 쪽'만 채웠고 최근 며칠은 다시 받지 않아서, 며칠 전에 만든 캐시를
    # 계속 쓰면 그 이후 날짜가 영영 빠졌다. 최근 거래일이 빠졌거나(최근 공백), 중간 평일이 12% 넘게 빠진
    # 캐시(손상)면 하루에 한 번만 키움에서 다시 받아서 합친다(실패해도 그날은 다시 시도하지 않음 - '로컬 비우기'로 초기화).
    need_heal = False
    heal_months = months
    if use_local and not confirmed.empty and not need_backfill:
        _d = confirmed["datetime"].dt.date
        first_c, last_c = _d.min(), _d.max()
        prev_wd = today - timedelta(days=1)
        while prev_wd.weekday() >= 5:
            prev_wd -= timedelta(days=1)
        recent_gap = last_c < prev_wd
        have_days = set(_d.unique())
        wd_all = [x.date() for x in pd.bdate_range(first_c, last_c)]
        damaged = len(wd_all) >= 20 and (sum(1 for x in wd_all if x not in have_days) / len(wd_all)) > 0.12
        if recent_gap or damaged:
            if meta.get("healed") != today.isoformat():
                need_heal = True
                heal_months = months if damaged else max(1, int(-(-(today - last_c).days // 30.5)) + 1)

    if need_backfill or need_heal:
        fetched = fetch_minute_data_range(code, interval_min=interval_min,
                                          months=(months if need_backfill else heal_months))
        if not fetched.empty:
            new_conf = fetched[fetched["datetime"].dt.date < today]
            if not confirmed.empty:  # 기존 캐시와 합쳐서(겹치면 새로 받은 값 우선) 더 오래된 날짜도 잃지 않게 한다
                new_conf = pd.concat([confirmed, new_conf], ignore_index=True)
                new_conf = new_conf.drop_duplicates(subset="datetime", keep="last").sort_values("datetime")
            confirmed = new_conf.reset_index(drop=True)
            if use_local:
                _save_minute_cache(code, interval_min, confirmed)
        if use_local:
            if need_backfill:
                meta["backfill"] = bf_key
            if need_heal:
                meta["healed"] = today.isoformat()
            _save_minute_meta(code, interval_min, meta)

    today_df = fetch_today_minute_data(code, interval_min=interval_min)

    if confirmed.empty and today_df.empty:
        return pd.DataFrame()
    merged = pd.concat([confirmed, today_df], ignore_index=True) if not today_df.empty else confirmed
    merged = merged.drop_duplicates(subset="datetime").sort_values("datetime")
    merged = merged[merged["datetime"].dt.date >= cutoff].reset_index(drop=True)
    return merged


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
    ⚠️ 키움 분봉 API는 체결 건별 매수/매도 구분을 주지 않기 때문에,
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


def get_daily_range_snapshot(code: str):
    """일봉세력평단가 차트에서 사용자가 선택해둔 시작일~종료일 기준으로
    (전일比%, 세력평단比%, 현재가, 세력평단가)를 계산. 선택된 날짜 정보가 없으면 None."""
    try:
        sy = st.session_state.get(f"daily_start_{code}_y")
        sm = st.session_state.get(f"daily_start_{code}_m")
        sd = st.session_state.get(f"daily_start_{code}_d")
        ey = st.session_state.get(f"daily_end_{code}_y")
        em = st.session_state.get(f"daily_end_{code}_m")
        ed = st.session_state.get(f"daily_end_{code}_d")
        if None in (sy, sm, sd, ey, em, ed):
            return None
        start_d = date(sy, sm, sd)
        end_d = date(ey, em, ed)
    except (TypeError, ValueError):
        return None

    full_df = fetch_daily_ohlcv(code)
    if full_df.empty:
        return None
    mask = (full_df["date"].dt.date >= start_d) & (full_df["date"].dt.date <= end_d)
    sub = full_df.loc[mask]
    if sub.empty:
        return None
    sub = sub.copy()
    sub["cum_vwap"] = (sub["close"] * sub["volume"]).cumsum() / sub["volume"].cumsum()
    last_close = float(sub["close"].iloc[-1])
    last_vwap = float(sub["cum_vwap"].iloc[-1])
    vwap_pct = (last_close - last_vwap) / last_vwap * 100 if last_vwap else None

    last_idx = sub.index[-1]
    pos = full_df.index.get_loc(last_idx)
    day_pct = None
    if pos > 0:
        prev_close = float(full_df["close"].iloc[pos - 1])
        if prev_close:
            day_pct = (last_close - prev_close) / prev_close * 100

    return day_pct, vwap_pct, last_close, last_vwap


def format_snapshot_line(code: str, override=None) -> str:
    """
    [YYMMDD HH:MM] 현재가 ...원 세력평단 ...원 전일比 ...% 세력평단比 ...%
    형태의 한 줄 스냅샷 문자열을 만들어 반환. 데이터가 없으면 빈 문자열.
    override=(day_pct, vwap_pct, cur_price, vwap_price)를 주면 그 값을 그대로 사용
    (일봉세력평단가 차트에서 선택한 시작일~종료일 기준 값을 저장할 때 사용).
    """
    if override is not None:
        day_pct, vwap_pct, cur_price, vwap_price = override
    else:
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
# 2-1. 일봉 데이터(OHLCV) - 네이버 금융 일별시세
# ----------------------------------------------------------------------
def _fetch_daily_ohlcv_raw(code: str, start_ymd: str = "19900101") -> pd.DataFrame:
    """
    네이버 금융 일별시세(siseJson)로 일봉 OHLCV 전체를 받아 DataFrame으로 반환.
    컬럼: date(문자열 YYYYMMDD), open, high, low, close, volume. 날짜 오름차순.
    실패 시 빈 DataFrame 반환.
    """
    import requests
    import ast

    try:
        url = (
            "https://api.finance.naver.com/siseJson.naver"
            f"?symbol={code}&requestType=1&startTime={start_ymd}&endTime=99991231"
            "&timeframe=day"
        )
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        text = res.text.strip().replace("\n", "").replace("\t", "")
        rows = ast.literal_eval(text)
        if not rows or len(rows) < 2:
            return pd.DataFrame()
        header = rows[0]
        idx = {name: header.index(name) for name in ("날짜", "시가", "고가", "저가", "종가", "거래량") if name in header}
        records = []
        for r in rows[1:]:
            try:
                records.append({
                    "date": str(r[idx["날짜"]]),
                    "open": float(r[idx["시가"]]),
                    "high": float(r[idx["고가"]]),
                    "low": float(r[idx["저가"]]),
                    "close": float(r[idx["종가"]]),
                    "volume": float(r[idx["거래량"]]),
                })
            except (ValueError, IndexError, KeyError, TypeError):
                continue
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_daily_ohlcv_1h(code: str) -> pd.DataFrame:
    return _fetch_daily_ohlcv_raw(code)


@st.cache_data(ttl=18000, show_spinner=False)
def _fetch_daily_ohlcv_5h(code: str) -> pd.DataFrame:
    return _fetch_daily_ohlcv_raw(code)


@st.cache_data(ttl=43200, show_spinner=False)
def _fetch_daily_ohlcv_12h(code: str) -> pd.DataFrame:
    return _fetch_daily_ohlcv_raw(code)


# ----------------------------------------------------------------------
# 2-1-1. 일봉 로컬(내 PC) 캐시 - 분봉의 "로컬"/"로컬 비우기"와 같은 개념이지만 별도 토글/버튼
# ("일봉 로컬"/"일봉 로컬비우기")으로 관리한다. 일봉은 네이버 요청 1번으로 전체 기간이 오므로
# "여러 번 나눠 호출"할 필요는 없지만, 오늘치까지 이미 로컬에 있으면 그 요청 자체를 아예
# 건너뛰어서 메모리 캐시가 날아간 뒤(앱 재시작 등)에도 다시 네트워크를 타지 않게 해준다.
# ----------------------------------------------------------------------
DAILY_CACHE_DIR = "daily_cache"


def _daily_cache_path(code: str) -> str:
    os.makedirs(DAILY_CACHE_DIR, exist_ok=True)
    return os.path.join(DAILY_CACHE_DIR, f"{code}.json")


def _load_daily_local_cache(code: str) -> pd.DataFrame:
    path = _daily_cache_path(code)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError):
        return pd.DataFrame()


def _save_daily_local_cache(code: str, df: pd.DataFrame):
    if df.empty:
        return
    path = _daily_cache_path(code)
    try:
        out = df.copy()
        out["date"] = out["date"].astype(str)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out.to_dict(orient="records"), f, ensure_ascii=False)
    except OSError as e:
        st.warning(f"일봉 로컬 캐시 저장 실패: {e}")


def clear_daily_local_cache() -> int:
    """'일봉 로컬비우기' 버튼: 일봉 로컬 캐시 파일을 모두 삭제한다. 삭제한 파일 수를 반환."""
    if not os.path.isdir(DAILY_CACHE_DIR):
        return 0
    n = 0
    for fn in os.listdir(DAILY_CACHE_DIR):
        try:
            os.remove(os.path.join(DAILY_CACHE_DIR, fn))
            n += 1
        except OSError:
            pass
    return n


def fetch_daily_ohlcv(code: str) -> pd.DataFrame:
    """일봉 데이터를 사용자가 고른 캐시 주기(1시간/5시간/12시간)에 맞춰 반환.
    '일봉 로컬' 토글이 켜져 있으면, 오늘치까지 이미 로컬(디스크)에 저장돼 있는 경우
    네이버 요청(과 메모리 캐시 조회)을 아예 건너뛰고 로컬 파일을 그대로 반환한다."""
    if st.session_state.get("daily_local_cache_on", True):
        cached = _load_daily_local_cache(code)
        if not cached.empty and (cached["date"].dt.date == date.today()).any():
            return cached

        mode = st.session_state.get("daily_cache_mode", "1h")
        if mode == "5h":
            fresh = _fetch_daily_ohlcv_5h(code)
        elif mode == "12h":
            fresh = _fetch_daily_ohlcv_12h(code)
        else:
            fresh = _fetch_daily_ohlcv_1h(code)

        if not fresh.empty:
            _save_daily_local_cache(code, fresh)
            return fresh
        return cached  # 네트워크 실패 시라도 로컬에 있던 예전 데이터라도 반환

    mode = st.session_state.get("daily_cache_mode", "1h")
    if mode == "5h":
        return _fetch_daily_ohlcv_5h(code)
    if mode == "12h":
        return _fetch_daily_ohlcv_12h(code)
    return _fetch_daily_ohlcv_1h(code)


def fetch_daily_ohlcv_with_today(code: str) -> pd.DataFrame:
    """일봉 차트용: 네이버 일봉(또는 로컬/메모리 캐시)에 '오늘' 봉이 없거나 장중이라 값이
    낡았을 수 있어서, 오늘 분봉(키움, 15초 캐시)으로 오늘 일봉(시가/고가/저가/종가/거래량)을
    만들어 덮어쓰거나 추가한다. 장 마감(15:40) 이후 네이버가 이미 오늘 봉을 갖고 있으면
    네이버 값을 그대로 쓴다. 분봉 조회 실패/휴장 등으로 오늘 분봉이 없으면 원본 그대로 반환."""
    daily = fetch_daily_ohlcv(code)
    try:
        today = date.today()
        if today.weekday() >= 5:
            return daily
        has_today = (not daily.empty) and bool((daily["date"].dt.date == today).any())
        if has_today and datetime.now().time() >= dtime(15, 40):
            return daily
        m = fetch_today_minute_data(code, interval_min=3)
        if m.empty or m["datetime"].dt.date.max() != today:
            return daily
        bar = pd.DataFrame([{
            "date": pd.Timestamp(today),
            "open": float(m["open"].iloc[0]),
            "high": float(m["high"].max()),
            "low": float(m["low"].min()),
            "close": float(m["close"].iloc[-1]),
            "volume": float(m["volume"].sum()),
        }])
        base = daily[daily["date"].dt.date != today] if not daily.empty else daily
        out = pd.concat([base, bar], ignore_index=True)
        return out.sort_values("date").reset_index(drop=True)
    except Exception:
        return daily


def fetch_daily_ma_values(code: str) -> dict:
    """일봉 종가 기준 5/20/60/120/240/480/720일 이동평균 '최신값'. 데이터 부족 시 None."""
    result = {p: None for p in MA_PERIODS}
    df = fetch_daily_ohlcv(code)
    if df.empty:
        return result
    closes = df["close"]
    for p in MA_PERIODS:
        if len(closes) >= p:
            result[p] = float(closes.tail(p).mean())
    return result


# ----------------------------------------------------------------------
# 2-2. 업종테마 목록/구성종목 (모듈 레벨 캐시 함수 - 매 rerun마다 재정의하면
#      st.cache_data 캐시가 제대로 안 먹어서 느려지므로 반드시 여기(모듈 최상단)에 고정)
# ----------------------------------------------------------------------
def _theme_groups_raw():
    try:
        groups = kiwoom_client.fetch_theme_groups(date_tp="1", flu_pl_amt_tp="3", stex_tp="1")
    except Exception as e:
        st.warning(f"테마 목록 조회 실패: {e}")
        return []

    def _rt(t):
        try:
            return float(t.get("flu_rt", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return sorted(groups, key=_rt, reverse=True)


@st.cache_data(ttl=30, show_spinner=False)
def _theme_groups_30s():
    return _theme_groups_raw()


@st.cache_data(ttl=82800, show_spinner=False)  # 23시간
def _theme_groups_23h():
    return _theme_groups_raw()


def cached_theme_groups():
    _mode = st.session_state.get("kiwoom_theme_poll_mode", "30s")
    if _mode == "local":
        return _get_active_theme_snapshot().get("groups", [])
    if _mode == "off":
        return st.session_state.get("kiwoom_theme_groups_last", [])
    if _mode == "23h":
        _result = _theme_groups_23h()
    else:
        _result = _theme_groups_30s()
    st.session_state["kiwoom_theme_groups_last"] = _result
    return _result


def _theme_stocks_raw(thema_grp_cd: str):
    try:
        return kiwoom_client.fetch_theme_stocks(thema_grp_cd, date_tp="1", stex_tp="1")
    except Exception as e:
        st.warning(f"테마 구성종목 조회 실패: {e}")
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _theme_stocks_30s(thema_grp_cd: str):
    return _theme_stocks_raw(thema_grp_cd)


@st.cache_data(ttl=82800, show_spinner=False)  # 23시간
def _theme_stocks_23h(thema_grp_cd: str):
    return _theme_stocks_raw(thema_grp_cd)


THEME_SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme_snapshot_cache")

# '저장'/'로드' 기능으로 PC에 통째로 백업/복원할 때 쓰는 폴더 (요/테요 공용 베이스 경로)
EXPORT_BASE_DIR = r"C:\Users\LG\Downloads\내프로젝트폴더"
EXPORT_SURGE_DIR = os.path.join(EXPORT_BASE_DIR, "요")
EXPORT_THEME_DIR = os.path.join(EXPORT_BASE_DIR, "테요")


def _pick_monthly_export_filename(export_dir: str) -> str:
    """이번 저장의 파일명은 항상 '오늘 날짜'(YYYYMMDD)로 만든다.
    단, 같은 달에 이미 저장해둔 파일이 있으면(파일명이 다른 날짜라도) 그 파일은 지우고
    오늘 날짜 이름으로 새로 만든다 — 즉 한 달에 파일이 하나만 남고, 그 파일명은 항상
    '이번 달 마지막으로 저장한 날짜'가 된다. 달이 바뀌면 지난 달 파일은 그대로 두고
    새 파일을 만든다."""
    today = date.today()
    today_str = today.strftime("%Y%m%d")
    this_month_prefix = today.strftime("%Y%m")
    if os.path.isdir(export_dir):
        for fn in os.listdir(export_dir):
            if fn.endswith(".json") and len(fn) == 13 and fn[:6] == this_month_prefix and fn[:-5] != today_str:
                os.remove(os.path.join(export_dir, fn))
    return today_str


def _export_bundle_to_pc(export_dir: str, saved_dates: list, load_fn) -> tuple:
    """로컬 캐시에 있는 날짜별 데이터를 전부 모아 PC 폴더에 파일 하나로 백업.
    반환값: (파일명(확장자 제외), 백업된 날짜 수)"""
    os.makedirs(export_dir, exist_ok=True)
    bundle = {d: load_fn(d) for d in saved_dates}
    fname = _pick_monthly_export_filename(export_dir)
    with open(os.path.join(export_dir, f"{fname}.json"), "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    return fname, len(bundle)


def _list_pc_export_files(export_dir: str) -> list:
    """PC 폴더에 저장된 백업 파일 목록(최신순). 오프라인에서도 디스크만 읽으므로 항상 동작한다."""
    if not os.path.isdir(export_dir):
        return []
    return sorted((fn[:-5] for fn in os.listdir(export_dir) if fn.endswith(".json")), reverse=True)


def _import_bundle_from_pc(export_dir: str, fname: str, save_fn, cache_key_prefix: str) -> int:
    """PC 백업 파일 하나를 읽어서, 안에 들어있는 날짜별 데이터를 전부 로컬 캐시(디스크)로 복원한다.
    반환값: 복원된 날짜 수."""
    path = os.path.join(export_dir, f"{fname}.json")
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        bundle = json.load(f)
    for d, data in bundle.items():
        save_fn(d, data)
        st.session_state.pop(f"{cache_key_prefix}{d}", None)  # 세션 캐시 무효화, 다음 조회 때 새로 읽게
    return len(bundle)


# ---- '오달저' (월이 바뀌면 지난달 데이터를 자동으로 PC에 백업) ----
AUTO_MONTH_EXPORT_PREF_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "auto_month_export_pref.txt"
)


def _load_auto_month_export_pref() -> bool:
    """기본값 ON. 새로고침/재시작해도 유지되도록 파일에 저장해둔 값을 읽는다."""
    if os.path.exists(AUTO_MONTH_EXPORT_PREF_FILE):
        try:
            with open(AUTO_MONTH_EXPORT_PREF_FILE, "r", encoding="utf-8") as f:
                return f.read().strip() != "0"
        except Exception:
            return True
    return True


def _save_auto_month_export_pref(enabled: bool):
    with open(AUTO_MONTH_EXPORT_PREF_FILE, "w", encoding="utf-8") as f:
        f.write("1" if enabled else "0")


if "auto_month_export_enabled" not in st.session_state:
    st.session_state["auto_month_export_enabled"] = _load_auto_month_export_pref()


def _run_month_rollover_autoexport(export_dir: str, saved_dates_fn, load_fn, tracker_name: str):
    """'오달저' ON일 때: 마지막으로 확인했던 달과 지금 달을 비교해서 달이 바뀌었으면,
    방금 끝난 지난달에 로컬에 저장돼 있던 날짜별 데이터를 모아 PC에 자동 백업한다.
    ('저장' 버튼을 깜빡 눌러도 월말에 자동으로 보존되게 하기 위한 안전장치.)"""
    os.makedirs(export_dir, exist_ok=True)
    tracker_path = os.path.join(export_dir, f".{tracker_name}_last_month")
    today = date.today()
    this_month = today.strftime("%Y-%m")

    last_month_recorded = None
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                last_month_recorded = f.read().strip() or None
        except Exception:
            last_month_recorded = None

    if last_month_recorded and last_month_recorded != this_month:
        _prev_year, _prev_month = last_month_recorded.split("-")
        _prev_prefix = f"{_prev_year}{_prev_month}"
        _prev_dates = [d for d in saved_dates_fn() if d.startswith(_prev_prefix)]
        if _prev_dates:
            bundle = {d: load_fn(d) for d in _prev_dates}
            _fname = f"{_prev_prefix}01"  # 그 달 1일자로 파일명 표기 (예: 20260901)
            with open(os.path.join(export_dir, f"{_fname}.json"), "w", encoding="utf-8") as f:
                json.dump(bundle, f, ensure_ascii=False)

    if last_month_recorded != this_month:
        with open(tracker_path, "w", encoding="utf-8") as f:
            f.write(this_month)


def _theme_snapshot_file(date_str: str) -> str:
    return os.path.join(THEME_SNAPSHOT_DIR, f"{date_str}.json")


def _theme_snapshot_saved_dates() -> list:
    """'테업'으로 저장해둔 날짜 목록(최신순). 디스크만 읽고 키움 호출 없음."""
    if not os.path.isdir(THEME_SNAPSHOT_DIR):
        return []
    return sorted((fn[:-5] for fn in os.listdir(THEME_SNAPSHOT_DIR) if fn.endswith(".json")), reverse=True)


def _load_theme_snapshot(date_str: str) -> dict:
    path = _theme_snapshot_file(date_str)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_theme_snapshot(date_str: str, data: dict):
    os.makedirs(THEME_SNAPSHOT_DIR, exist_ok=True)
    with open(_theme_snapshot_file(date_str), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _delete_theme_snapshot(date_str: str):
    path = _theme_snapshot_file(date_str)
    if os.path.exists(path):
        os.remove(path)


def _get_active_theme_snapshot() -> dict:
    """'로컬' 모드에서 쓸 현재 활성 스냅샷. '테요'에서 고른 과거 날짜가 있으면 그것,
    없으면 '테업'으로 오늘 받아둔 최신 스냅샷(세션 메모리). 세션이 새로 시작돼서 메모리가
    비어있으면, 오늘 날짜로 디스크에 저장된 파일이 있는지 확인해서 있으면 그걸 대신 읽는다
    (그래야 새로고침/재시작해도 '실시간'이 매번 빈 화면이 되지 않는다). 키움 호출은 없다."""
    active_date = st.session_state.get("theme_snapshot_active_date")
    if active_date:
        _key = f"theme_snapshot_data_{active_date}"
        if _key not in st.session_state:
            st.session_state[_key] = _load_theme_snapshot(active_date)
        return st.session_state[_key]
    _live = st.session_state.get("theme_snapshot_data_live")
    if _live:
        return _live
    _today_str = date.today().isoformat()
    _today_data = _load_theme_snapshot(_today_str)
    if not _today_data:
        _dates = _theme_snapshot_saved_dates()
        if _dates:
            _today_data = _load_theme_snapshot(_dates[0])  # 오늘 저장분이 없으면 가장 최근 저장분
    if _today_data:
        st.session_state["theme_snapshot_data_live"] = _today_data
    return _today_data or {}


def fetch_kiwoom_theme_snapshot_raw(delay_sec: float = 0.3) -> dict:
    """[테업 버튼 전용] 업종테마 전체(최대 30개)와 각 구성종목을 한 번에 크롤링해서 로컬
    저장용 스냅샷을 만든다. 테마 목록 조회 1회 + 구성종목 조회 최대 30회가 한꺼번에 나가므로,
    이 함수는 '테업' 버튼 클릭 위치에서만 호출해야 한다 (그래야 '로컬' 모드에서는 이 스냅샷만
    재사용하고 평소에 키움을 두드리지 않는다는 규칙이 지켜진다)."""
    import time as _time
    groups = _theme_groups_raw()[:30]
    stocks_map = {}
    for i, g in enumerate(groups):
        grp_cd = g.get("thema_grp_cd", "")
        if not grp_cd:
            continue
        stocks_map[grp_cd] = _theme_stocks_raw(grp_cd)
        if i < len(groups) - 1:
            _time.sleep(delay_sec)  # 요청 사이 간격 (테업 버튼은 0.3초, 자동 저장은 더 길게)
    return {"groups": groups, "stocks": stocks_map}


def cached_theme_stocks(thema_grp_cd: str):
    _mode = st.session_state.get("kiwoom_theme_poll_mode", "30s")
    if _mode == "local":
        return _get_active_theme_snapshot().get("stocks", {}).get(thema_grp_cd, [])
    if _mode == "off":
        return st.session_state.setdefault("kiwoom_theme_stocks_last", {}).get(thema_grp_cd, [])
    if _mode == "23h":
        _result = _theme_stocks_23h(thema_grp_cd)
    else:
        _result = _theme_stocks_30s(thema_grp_cd)
    st.session_state.setdefault("kiwoom_theme_stocks_last", {})[thema_grp_cd] = _result
    return _result


def fetch_naver_theme_list():
    """네이버 금융 테마 순위 목록. [{"no":..,"name":..,"change_pct":..}, ...]"""
    import requests
    import time as _time
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/sise/",
    }
    results = []
    last_error = None
    for page in (1, 2):
        if page > 1:
            _time.sleep(1.2)  # 페이지 전환 사이 딜레이 (봇 차단 회피)
        url = f"https://finance.naver.com/sise/theme.naver?page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=8)
        except Exception as e:
            last_error = f"page={page}: 네이버 접속 실패: {e}"
            continue
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.select_one("table.type_1")
        if not table:
            last_error = f"page={page}: 표를 찾지 못함 ({_naver_fetch_fail_reason(res.status_code, res.text)})"
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
    if not results and last_error:
        raise RuntimeError(last_error)
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


def _kiwoom_amount_calc(s):
    def _pnum(v):
        try:
            return abs(int(str(v).replace("+", "").replace("-", "")))
        except (TypeError, ValueError):
            return 0
    return _pnum(s.get("cur_prc", "0")) * _pnum(s.get("acc_trde_qty", "0"))


def _naver_amount_calc(s):
    return (s.get("price") or 0) * (s.get("volume") or 0)


def _pick_stock_table(soup):
    """네이버 금융 시세표는 페이지마다 table 클래스가 다를 수 있어(type_1/type_2/type_5 등)
    실제로 종목 링크(code=...)가 들어있는 표를 찾아서 반환한다. 없으면 None."""
    for sel in ("table.type_2", "table.type_5", "table.type_1", "table"):
        for cand in soup.select(sel):
            if cand.select_one("a[href*='code=']"):
                return cand
    return None


def _looks_like_blocked_page(html_text: str) -> bool:
    """네이버가 접속을 일시적으로 제한(차단/캡차/과다요청 등)했을 때 자주 등장하는 문구가
    있는지 간단히 점검한다. 확정적인 판별은 아니고 사용자에게 원인 힌트를 주기 위한 용도."""
    _markers = [
        "captcha", "비정상적인 접근", "일시적으로 이용", "이용이 제한", "정상적인 경로",
        "접속이 원활하지 않습니다", "너무 많은 요청", "자동입력 방지", "차단된 사용자",
        "일시적으로 차단", "요청이 많아",
    ]
    _low = (html_text or "")[:3000].lower()
    return any(m.lower() in _low for m in _markers)


def _naver_fetch_fail_reason(res_status: int, html_text: str) -> str:
    """표를 못 찾았을 때, 네이버가 일시적으로 막은 것처럼 보이는지 구조변경으로 보이는지
    문구로 간단히 구분해서 알려준다 (완전히 정확한 판별은 아님)."""
    if _looks_like_blocked_page(html_text):
        return "네이버가 접속을 일시적으로 제한한 것으로 보임 (몇 분 후 다시 시도해보세요)"
    if res_status != 200:
        return f"HTTP {res_status}"
    return f"HTTP {res_status}, 페이지 구조가 바뀌었을 수 있음"


def _throttled_naver_fetch(state_key: str, fetch_fn, min_interval_sec: float = 20.0):
    """짧은 시간 안에 같은 데이터를 반복 요청해서 네이버 차단을 유발하지 않도록, 최근
    min_interval_sec 이내에 이미 받아온 데이터가 있으면 재사용하고 새로 요청하지 않는다.
    (흰네업/일주 같은 자동 스캔 버튼을 연달아 눌러도 매번 네이버를 새로 두드리지 않게 하기 위함.
    사용자가 직접 누르는 '새로고침' 버튼은 이 함수를 거치지 않고 항상 즉시 새로 받아온다.)"""
    import time as _time
    _now = _time.time()
    _ts_key = f"{state_key}_fetched_at"
    _last_ts = st.session_state.get(_ts_key)
    _cached = st.session_state.get(state_key)
    if _cached and _last_ts and (_now - _last_ts) < min_interval_sec:
        return _cached
    data = fetch_fn()
    st.session_state[state_key] = data
    st.session_state[_ts_key] = _now
    return data


SURGE_RANK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "surge_rank_cache")

# 급등순위 밴드 3단계: 기본(왼쪽 패널 단독) / ▶1회 / ▶2회 (양쪽 패널에 나눠 표시)
SURGE_RANK_BANDS = {0: (0.0, 30.0), 1: (0.0, 30.0)}


def _fmt_pct_band(v: float) -> str:
    """9.99 같은 소수는 그대로, 30.0/10.0 같은 정수는 소수점 없이 표시."""
    return f"{v:.0f}" if float(v).is_integer() else f"{v:g}"


def _surge_rank_file(date_str: str) -> str:
    return os.path.join(SURGE_RANK_DIR, f"{date_str}.json")


def _surge_rank_saved_dates() -> list:
    """'업'으로 저장해둔 날짜 목록(최신순). 디스크만 읽고 키움 호출 없음."""
    if not os.path.isdir(SURGE_RANK_DIR):
        return []
    return sorted((fn[:-5] for fn in os.listdir(SURGE_RANK_DIR) if fn.endswith(".json")), reverse=True)


def _load_surge_rank_date(date_str: str) -> list:
    """특정 날짜에 저장된 급등순위 원본을 로컬 디스크에서 읽는다. 키움 호출 없음."""
    path = _surge_rank_file(date_str)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_surge_rank_date(date_str: str, data: list):
    os.makedirs(SURGE_RANK_DIR, exist_ok=True)
    with open(_surge_rank_file(date_str), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _delete_surge_rank_date(date_str: str):
    path = _surge_rank_file(date_str)
    if os.path.exists(path):
        os.remove(path)


def fetch_kiwoom_surge_rank_raw() -> list:
    """[업 버튼 전용] 키움 등락률상위(ka10027)를 실제로 호출해서 0%~+30% 구간 종목을 가져온다.
    이 함수는 '업' 버튼 클릭 위치에서만 호출되어야 한다 — 그래야 '업을 누르기 전에는 키움에
    전혀 부담을 주지 않는다'는 규칙이 지켜진다.
    [{"code":.., "name":.., "price":.., "change_pct":.., "volume":..}, ...]"""
    raw = kiwoom_client.fetch_updown_rank()

    def _num(v):
        try:
            return abs(int(str(v).replace("+", "").replace("-", "")))
        except (TypeError, ValueError):
            return None

    def _pct(v):
        try:
            return float(str(v).replace("+", ""))
        except (TypeError, ValueError):
            return None

    results = []
    for r in raw:
        _code_raw = str(r.get("stk_cd", "")).strip()
        _code_match = re.search(r"(\d{6})", _code_raw)
        code = _code_match.group(1) if _code_match else ""
        if not code:
            continue
        pct = _pct(r.get("flu_rt"))
        if pct is None or not (0.0 <= pct <= 30.0):
            continue
        # 거래량 필드명이 문서마다 달라(acc_trde_qty가 확인 안 됨), 후보 중 처음 값이 있는 걸 사용
        volume = None
        for _vk in ("acc_trde_qty", "trde_qty", "now_trde_qty", "trde_qty_cnd"):
            if r.get(_vk) not in (None, ""):
                volume = _num(r.get(_vk))
                if volume is not None:
                    break
        results.append({
            "code": code, "name": r.get("stk_nm", ""),
            "price": _num(r.get("cur_prc")), "change_pct": pct,
            "volume": volume,
        })
    results.sort(key=lambda s: s["change_pct"], reverse=True)
    return results


def _get_active_surge_rank_data() -> list:
    """현재 화면에 보여줄 급등순위 원본(0%~30%) 데이터를 반환. 키움 호출은 절대 하지 않고
    '요'에서 선택된 과거 날짜(있으면) 또는 오늘 '업'으로 받아둔 최신 데이터(세션 메모리)를
    사용한다. 세션이 새로 시작돼서 메모리가 비어있으면, 오늘 날짜로 디스크에 저장된 파일이
    있는지 확인해서 있으면 그걸 대신 읽는다 (그래야 새로고침/재시작해도 '실시간'이 매번
    빈 화면이 되지 않는다)."""
    active_date = st.session_state.get("surge_rank_active_date")
    if active_date:
        _key = f"surge_rank_data_{active_date}"
        if _key not in st.session_state:
            st.session_state[_key] = _load_surge_rank_date(active_date)
        return st.session_state[_key]
    _live = st.session_state.get("surge_rank_data_live")
    if _live:
        return _live
    _today_str = date.today().isoformat()
    _today_data = _load_surge_rank_date(_today_str)
    if not _today_data:
        # 오늘 저장분이 아직 없으면(주말/장 시작 전 등) 가장 최근에 저장된 날짜를 그대로 보여준다
        _dates = _surge_rank_saved_dates()
        if _dates:
            _today_data = _load_surge_rank_date(_dates[0])
    if _today_data:
        st.session_state["surge_rank_data_live"] = _today_data
    return _today_data or []


def _surge_rank_band(pct_low: float, pct_high: float) -> list:
    data = _get_active_surge_rank_data()
    band = [s for s in data if s.get("change_pct") is not None and pct_low <= s["change_pct"] < pct_high + 0.0001]
    band.sort(key=lambda s: s["change_pct"], reverse=True)
    return band


def _bulk_hide_checked_surge_stocks(temp: bool) -> int:
    """급등순위 헤더의 일괄 '숨'/'X' 버튼: 현재 v(선택) 체크된 종목들 중, 급등순위 데이터에
    실제로 존재하는 종목만 골라 한 번에 숨긴다. temp=False면 개별 '숨' 버튼과 동일하게
    숨긴 시점 스냅샷을 로컬 파일에 저장해 영구히 숨기고(체크 해제도 함께), temp=True면
    개별 'X' 버튼과 동일하게 이번 세션에서만 한 번 숨긴다(체크는 유지)."""
    _by_code = {s.get("code"): s for s in _get_active_surge_rank_data() if s.get("code")}
    _checked_codes = [c for c in list(st.session_state.checked_stocks.keys()) if c in _by_code]
    if not _checked_codes:
        return 0
    for code in _checked_codes:
        s = _by_code[code]
        if temp:
            st.session_state.setdefault("surge_rank_temp_hidden", set()).add(code)
        else:
            price = s.get("price")
            st.session_state.surge_rank_hidden[code] = {
                "name": s.get("name", ""), "price": price, "pct": s.get("change_pct") or 0.0,
                "amount": (price or 0) * (s.get("volume") or 0), "marketcap": marketcap_map.get(code),
            }
            st.session_state.checked_stocks.pop(code, None)
    if not temp:
        _save_surge_hidden_state(st.session_state.surge_rank_hidden)
    return len(_checked_codes)


def _render_surge_rank_rows(stocks: list, key_prefix: str):
    """급등순위 종목 리스트 렌더링 (관심종목 체크·전체선택·필터는 다른 리스트들과 동일하게
    checked_stocks/_visible_stocks_generic을 그대로 재사용해서 완전히 동일하게 연동된다).
    종목별 버튼 2개로 숨길 수 있다:
    - '숨': 숨긴 시점의 가격/등락률/대금/시총 스냅샷을 로컬 파일에 저장하고, PC 재부팅·
      새로고침·'업' 버튼과 무관하게 '업종테마' 자리의 숨김목록 패널에서 '복원'/'복' 버튼으로
      복구하기 전까지 계속 숨겨진 채로 남는다.
    - 'X': 이번 세션에서만 한 번 숨기는 단발성 버튼 - 새로고침하면 원래대로 다시 보인다."""
    _hidden = st.session_state.surge_rank_hidden
    _temp_hidden = st.session_state.setdefault("surge_rank_temp_hidden", set())
    if _hidden or _temp_hidden:
        stocks = [s for s in stocks if s.get("code") not in _hidden and s.get("code") not in _temp_hidden]

    if not stocks:
        st.caption("데이터가 없습니다. '업' 버튼으로 먼저 받아오거나 '요'에서 과거 날짜를 골라주세요.")
        return

    amount_fn = lambda s: (s.get("price") or 0) * (s.get("volume") or 0)
    visible = _visible_stocks_generic(stocks, amount_fn, "code")
    _visible_codes = {s.get("code") for s in visible}
    _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)

    if len(visible) < len(stocks):
        _sample = stocks[0]
        st.caption(
            f"밴드 내 {len(stocks)}종목 중 {len(visible)}종목만 대금/천억↓ 필터 통과 "
            f"(예시 1종목 - 가격:{_sample.get('price')}, 거래량:{_sample.get('volume')}, "
            f"등락률:{_sample.get('change_pct')})"
        )

    # ---- 전체선택: 체크박스를 실제로 클릭했을 때(on_change)만 현재 보이는 종목들을 일괄
    # 체크/해제한다. 매 rerun마다 "현재 다 체크됐는지"를 비교해서 자동으로 다시 맞추지 않기
    # 때문에, '요'/'대금' 등으로 새 종목이 화면에 나타나도 그 종목까지 자동으로 체크되지 않는다
    # (개별 체크하거나 전체선택을 다시 눌러야 체크된다). ----
    _selall_key = f"{key_prefix}_selall_v{_chk_ver}"

    def _sync_selall(_visible=visible, _key_prefix=key_prefix, _ver=_chk_ver, _sel_key=_selall_key):
        _on = st.session_state.get(_sel_key, False)
        for s in _visible:
            code = s.get("code")
            if _on:
                st.session_state.checked_stocks[code] = s.get("name", "")
                st.session_state[f"{_key_prefix}_chk_{code}_v{_ver}"] = True
            else:
                st.session_state.checked_stocks.pop(code, None)
                st.session_state[f"{_key_prefix}_chk_{code}_v{_ver}"] = False

    if _selall_key not in st.session_state:
        st.session_state[_selall_key] = bool(visible) and all(
            s.get("code") in st.session_state.checked_stocks for s in visible
        )
    st.checkbox(
        "전체선택", key=_selall_key, on_change=_sync_selall,
        help="현재 대금/천억↓/필터를 통과해 보이는 종목 전체를 관심종목 체크",
    )

    # '숨'/'X' 버튼 모양·색 CSS: 종목 줄마다 <style> 요소를 2개씩 넣던 것을 여기서 한 번에 넣는다
    # (줄 컨테이너 키의 접두사로 구분: _x_wrap_=버튼 모양, _xhide_=숨 색, _xtemp_=X 색. 화면 모양은 그대로).
    st.markdown(
        "<style>"
        f'[class*="st-key-{key_prefix}_x_wrap_"] button {{ padding:0 !important; margin:0 !important; '
        f'width:20px !important; min-width:20px !important; max-width:20px !important; '
        f'min-height:16px !important; height:16px !important; line-height:16px !important; '
        f'font-size:9px !important; border:none !important; background:transparent !important; }}'
        f'[class*="st-key-{key_prefix}_xhide_"] button {{ color:#e05252 !important; }}'
        f'[class*="st-key-{key_prefix}_xtemp_"] button {{ color:#9aa4b8 !important; }}'
        "</style>",
        unsafe_allow_html=True,
    )

    for s in stocks:
        code = s.get("code", "")
        if not code or code not in _visible_codes:
            continue
        name = s.get("name", "")
        price = s.get("price")
        pct = s.get("change_pct")
        pct_f = pct if pct is not None else 0.0
        s_marcap = marketcap_map.get(code)
        _amt = (price or 0) * (s.get("volume") or 0)

        row_col1, row_col_chk, row_col2, row_col_x = st.columns(
            [1.65, 0.3, 1.15, 0.18], gap="small"
        )
        with row_col1:
            if st.button(f"{name}", key=f"{key_prefix}_btn_{code}", use_container_width=True):
                st.session_state.goto_query = code
                st.session_state["local_snapshot_view_date"] = st.session_state.get("surge_rank_active_date")
                st.rerun()
        with row_col_chk:
            _chk = st.checkbox(
                "선택", value=(code in st.session_state.checked_stocks),
                key=f"{key_prefix}_chk_{code}_v{_chk_ver}", label_visibility="collapsed",
            )
            if _chk:
                st.session_state.checked_stocks[code] = name
            else:
                st.session_state.checked_stocks.pop(code, None)
        with row_col2:
            amt_text = format_krw_large(_amt).replace("원", "") if _amt else "-"
            cap_text = format_krw_large(s_marcap).replace("원", "") if s_marcap else "-"
            st.markdown(
                f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                f"{(price or 0):,.0f} <span style='color:#e05252'>{pct_f:+.2f}%</span><br>"
                f"대금{amt_text} 시{cap_text}</div>",
                unsafe_allow_html=True,
            )
        with row_col_x:
            _srx_key = f"{key_prefix}_x_wrap_{code}"
            with st.container(key=_srx_key):
                with st.container(key=f"{key_prefix}_xhide_{code}"):
                    if st.button("숨", key=f"{key_prefix}_x_{code}",
                                 help="급등순위 표시에서 이 종목 계속 숨기기 (복원/복 누르기 전까지 "
                                      "새로고침·재부팅·'업'과 무관하게 계속 숨김)"):
                        _hidden[code] = {
                            "name": name, "price": price, "pct": pct_f,
                            "amount": _amt, "marketcap": s_marcap,
                        }
                        _save_surge_hidden_state(_hidden)
                        _was_checked = code in st.session_state.checked_stocks
                        st.session_state.checked_stocks.pop(code, None)
                        # 이 패널만 다시 그려도 되는 경우: ▶ 안 누른 기본 상태(급등순위가 이 패널에만 보임)이고,
                        # 관심 체크된 종목이 아니었을 때. ▶ 상태는 좌/우 절반 나눔과 숨김목록이 다른 패널에도 있고,
                        # 체크 해제는 헤더의 관심(N) 숫자에 반영돼야 해서 전체 재실행을 유지한다.
                        if _was_checked or st.session_state.get("top30_toggle_mode", 0) != 0:
                            st.rerun()
                        st.rerun(scope="fragment")
                with st.container(key=f"{key_prefix}_xtemp_{code}"):
                    if st.button("X", key=f"{key_prefix}_tx_{code}",
                                 help="지금만 한 번 숨기기 (새로고침하면 다시 보임)"):
                        _temp_hidden.add(code)
                        if st.session_state.get("top30_toggle_mode", 0) != 0:
                            st.rerun()  # ▶ 상태: 다른 패널과 좌/우 나눔이 연결돼 전체 재실행
                        st.rerun(scope="fragment")  # 기본 상태: 이 패널만 다시 그린다


def _render_surge_rank_hidden_panel():
    """'업종테마' 자리에 대신 표시: 키움 급등순위에서 '숨' 버튼으로 숨긴 종목들을 숨긴
    시점의 가격/등락률/대금/시총 스냅샷 그대로 보여준다. 종목명 옆 'v'(선택) 체크박스는
    checked_stocks를 그대로 공유하는 관심종목 체크이자, 맨 위 '복원' 버튼을 눌렀을 때 일괄
    복구할 종목을 고르는 체크이기도 하다. 종목별 '복' 버튼으로도 개별 복구할 수 있다.
    복구된 종목은 surge_rank_hidden(로컬 파일까지 함께 갱신)에서 빠지므로, 과거 날짜('요')든
    앞으로 '업'을 눌러 받아오는 데이터든 다시 급등순위에 보인다."""
    st.markdown("<div style='font-size:11px; font-weight:700;'>🙈 급등순위 숨김목록</div>",
                unsafe_allow_html=True)
    hidden = st.session_state.surge_rank_hidden
    if not hidden:
        st.caption("급등순위에서 '숨' 버튼으로 숨긴 종목이 없습니다.")
        return

    if st.button(
        "복원", key="surge_hidden_restore_checked_btn", use_container_width=True,
        help="아래 숨김목록 중 v(선택)가 체크된 종목들을 급등순위에 다시 보이게 복구합니다",
    ):
        _restored = [c for c in hidden if c in st.session_state.checked_stocks]
        for c in _restored:
            hidden.pop(c, None)
        if _restored:
            _save_surge_hidden_state(hidden)
            st.rerun()

    _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
    for code, snap in list(hidden.items()):
        name = snap.get("name", "")
        price = snap.get("price")
        pct_f = snap.get("pct") or 0.0
        amt = snap.get("amount")
        marcap = snap.get("marketcap")

        row_col1, row_col_chk, row_col2, row_col_r = st.columns(
            [1.65, 0.3, 1.15, 0.18], gap="small"
        )
        with row_col1:
            if st.button(name, key=f"surge_hidden_btn_{code}", use_container_width=True):
                st.session_state.goto_query = code
                st.rerun()
        with row_col_chk:
            _chk = st.checkbox(
                "선택", value=(code in st.session_state.checked_stocks),
                key=f"surge_hidden_chk_{code}_v{_chk_ver}", label_visibility="collapsed",
            )
            if _chk:
                st.session_state.checked_stocks[code] = name
            else:
                st.session_state.checked_stocks.pop(code, None)
        with row_col2:
            amt_text = format_krw_large(amt).replace("원", "") if amt else "-"
            cap_text = format_krw_large(marcap).replace("원", "") if marcap else "-"
            st.markdown(
                f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                f"{(price or 0):,.0f} <span style='color:#e05252'>{pct_f:+.2f}%</span><br>"
                f"대금{amt_text} 시{cap_text}</div>",
                unsafe_allow_html=True,
            )
        with row_col_r:
            _srr_key = f"surge_hidden_restore_wrap_{code}"
            st.markdown(
                f"<style>.st-key-{_srr_key} button {{ padding:0 !important; margin:0 !important; "
                f"width:20px !important; min-width:20px !important; max-width:20px !important; "
                f"min-height:18px !important; height:18px !important; line-height:18px !important; "
                f"font-size:10px !important; color:#3ecb7a !important; "
                f"border:none !important; background:transparent !important; }}</style>",
                unsafe_allow_html=True,
            )
            with st.container(key=_srr_key):
                if st.button("복", key=f"surge_hidden_restore_{code}", help="이 종목 급등순위에 다시 보이게 복구"):
                    hidden.pop(code, None)
                    _save_surge_hidden_state(hidden)
                    st.rerun()


def _render_theme_rank_hidden_section():
    """업종테마 순위에서 '숨' 버튼으로 숨긴 테마들을 숨긴 시점의 등락률 스냅샷 그대로 보여준다.
    급등순위 숨김목록과 같은 방식(복원/복 버튼)으로 복구하지만, 테마 코드는 종목이 아니므로
    관심종목 체크(checked_stocks)는 건드리지 않고 별도의 복원선택 상태를 쓴다."""
    hidden = st.session_state.theme_rank_hidden
    if not hidden:
        return
    st.markdown("<div style='font-size:11px; font-weight:700; margin-top:6px;'>🙈 업종테마 숨김목록</div>",
                unsafe_allow_html=True)
    _restore_sel = st.session_state.setdefault("theme_hidden_restore_selected", set())

    if st.button(
        "복원", key="theme_hidden_restore_checked_btn", use_container_width=True,
        help="아래 숨김목록 중 v(선택)가 체크된 테마들을 업종테마 순위에 다시 보이게 복구합니다",
    ):
        _restored = [c for c in hidden if c in _restore_sel]
        for c in _restored:
            hidden.pop(c, None)
            _restore_sel.discard(c)
        if _restored:
            _save_theme_hidden_state(hidden)
            st.rerun()

    _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
    for grp_cd, snap in list(hidden.items()):
        name = snap.get("name", "")
        pct_f = snap.get("pct") or 0.0
        rate_color = "#e05c5c" if pct_f < 0 else "#3ecb7a" if pct_f > 0 else "#9aa4b8"

        row_col1, row_col_chk, row_col_r = st.columns([2.6, 0.3, 0.18], gap="small")
        with row_col1:
            st.markdown(
                f"<div style='padding:4px 0; font-size:12px;'>{name} "
                f"<span style='color:{rate_color}'>{pct_f:+.2f}%</span></div>",
                unsafe_allow_html=True,
            )
        with row_col_chk:
            _chk = st.checkbox(
                "선택", value=(grp_cd in _restore_sel),
                key=f"theme_hidden_chk_{grp_cd}_v{_chk_ver}", label_visibility="collapsed",
            )
            if _chk:
                _restore_sel.add(grp_cd)
            else:
                _restore_sel.discard(grp_cd)
        with row_col_r:
            _thr_key = f"theme_hidden_restore_wrap_{grp_cd}"
            st.markdown(
                f"<style>.st-key-{_thr_key} button {{ padding:0 !important; margin:0 !important; "
                f"width:20px !important; min-width:20px !important; max-width:20px !important; "
                f"min-height:18px !important; height:18px !important; line-height:18px !important; "
                f"font-size:10px !important; color:#3ecb7a !important; "
                f"border:none !important; background:transparent !important; }}</style>",
                unsafe_allow_html=True,
            )
            with st.container(key=_thr_key):
                if st.button("복", key=f"theme_hidden_restore_{grp_cd}", help="이 테마 업종테마 순위에 다시 보이게 복구"):
                    hidden.pop(grp_cd, None)
                    _restore_sel.discard(grp_cd)
                    _save_theme_hidden_state(hidden)
                    st.rerun()


def _render_kiwoom_surge_rank_panel():
    """▶ 기본(0) 상태: 네이버인기테마 자리를 대체하는 키움 급등순위 30%~0% 목록 (단독, 분할 없음).
    키움 호출은 절대 없음 — '업'으로 저장해둔 로컬 데이터만 읽는다."""
    _low, _high = SURGE_RANK_BANDS[0]
    _all_data = _get_active_surge_rank_data()
    _band = _surge_rank_band(_low, _high)

    _hdr_col1, _hdr_col2 = st.columns([3.5, 1], gap="small")
    with _hdr_col1:
        st.markdown(
            f"<div style='font-size:11px; font-weight:700;'>🚀 키움 급등순위 {_fmt_pct_band(_high)}%~{_fmt_pct_band(_low)}%</div>",
            unsafe_allow_html=True,
        )
    with _hdr_col2:
        _amount_fn = lambda s: (s.get("price") or 0) * (s.get("volume") or 0)
        _n = len(_visible_stocks_generic(_band, _amount_fn, "code"))
        st.markdown(
            f"<div style='text-align:right; font-size:22px; line-height:1; "
            f"color:{_theme_count_color(_n)}; font-weight:800;'>{_n}</div>",
            unsafe_allow_html=True,
        )
    st.caption(f"전체 저장 {len(_all_data)}종목 중 {_fmt_pct_band(_high)}%~{_fmt_pct_band(_low)}% 구간 {len(_band)}종목 "
               f"(대금/천억↓/신호필터 통과 {_n}종목)")
    _render_surge_rank_rows(_band, key_prefix="surge_band0")


def _render_kiwoom_surge_split_panel(top30_mode: int, side: str):
    """▶ 1회/2회 상태: 해당 밴드를 좌/우 패널에 절반씩 나눠서 표시.
    side='left'는 상위 절반(더 높은 등락률), 'right'는 나머지 절반."""
    _low, _high = SURGE_RANK_BANDS[top30_mode]
    band = _surge_rank_band(_low, _high)
    half = (len(band) + 1) // 2
    chunk = band[:half] if side == "left" else band[half:]

    _hdr_col1, _hdr_col2 = st.columns([3.5, 1], gap="small")
    with _hdr_col1:
        st.markdown(
            f"<div style='font-size:11px; font-weight:700;'>🚀 급등 {_fmt_pct_band(_high)}%~{_fmt_pct_band(_low)}% "
            f"({'상위' if side == 'left' else '나머지'})</div>",
            unsafe_allow_html=True,
        )
    with _hdr_col2:
        _amount_fn = lambda s: (s.get("price") or 0) * (s.get("volume") or 0)
        _n = len(_visible_stocks_generic(chunk, _amount_fn, "code"))
        st.markdown(
            f"<div style='text-align:right; font-size:22px; line-height:1; "
            f"color:{_theme_count_color(_n)}; font-weight:800;'>{_n}</div>",
            unsafe_allow_html=True,
        )
    if side == "left":
        st.caption(f"이 구간 전체 {len(band)}종목 중 상위 {len(chunk)}종목 (대금/천억↓/신호필터 통과 {_n}종목)")
    else:
        st.caption(f"대금/천억↓/신호필터 통과 {_n}종목")
    _render_surge_rank_rows(chunk, key_prefix=f"surge_band{top30_mode}_{side}")


def fetch_naver_search_top30():
    """네이버 금융 '인기검색종목(검색상위)' 30종목.
    [{"rank":.., "name":.., "code":.., "price":.., "change_pct":.., "volume":..}, ...]"""
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/sise/",
    }
    url = "https://finance.naver.com/sise/lastsearch2.naver"
    try:
        res = requests.get(url, headers=headers, timeout=8)
    except Exception as e:
        raise RuntimeError(f"네이버 접속 실패: {e}") from e
    res.encoding = "euc-kr"
    soup = BeautifulSoup(res.text, "html.parser")
    table = _pick_stock_table(soup)
    if table is None:
        raise RuntimeError(f"검색상위 표를 찾지 못함 ({_naver_fetch_fail_reason(res.status_code, res.text)})")
    results = []
    for row in table.select("tr"):
        link = row.select_one("a")
        if not link or "code=" not in link.get("href", ""):
            continue
        name = link.get_text(strip=True)
        code = link.get("href", "").split("code=")[-1].split("&")[0]
        rank_td = row.select_one("td.no")
        try:
            rank = int(rank_td.get_text(strip=True)) if rank_td else len(results) + 1
        except ValueError:
            rank = len(results) + 1
        num_tds = row.select("td.number")
        price, change_pct, volume = None, None, None
        try:
            # 순서: [0]검색비율%, [1]현재가, [2]전일비, [3]등락률%, [4]거래량, ...
            if len(num_tds) >= 2:
                price = int(num_tds[1].get_text(strip=True).replace(",", ""))
            if len(num_tds) >= 4:
                change_pct = float(num_tds[3].get_text(strip=True).replace("%", "").replace("+", ""))
            if len(num_tds) >= 5:
                volume = int(num_tds[4].get_text(strip=True).replace(",", ""))
        except (ValueError, IndexError):
            pass
        results.append({"rank": rank, "name": name, "code": code, "price": price,
                         "change_pct": change_pct, "volume": volume})
    if not results:
        raise RuntimeError("검색상위 표는 찾았지만 종목 행을 읽지 못함 (열 구조가 바뀌었을 수 있음)")
    return results


def _fetch_sise_quant_combined(nxt: bool = False):
    """코스피+코스닥 '거래상위'(sise_quant.naver) 페이지를 양쪽 다 받아 합친 원본 목록.
    nxt=True면 넥스트레이드(NXT) 시세 페이지를 대신 조회한다 (2025.3 네이버페이 증권 NXT 연동 반영,
    파라미터는 네이버 쪽 변경 시 조정이 필요할 수 있음).
    [{"name":.., "code":.., "price":.., "change_pct":.., "volume":.., "amount":..}, ...] (중복 code 제거)
    양쪽 시장 모두 실패하면(=표를 못 찾거나 접속 실패) 원인을 알 수 있도록 예외를 발생시킨다."""
    import requests
    import time as _time
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/sise/",
    }
    all_stocks = []
    last_error = None
    for sosok in (0, 1):
        if sosok > 0:
            _time.sleep(1.2)  # 코스피→코스닥 전환 사이 딜레이 (봇 차단 회피)
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        if nxt:
            url += "&nxt=1"
        try:
            res = requests.get(url, headers=headers, timeout=8)
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "html.parser")
            table = _pick_stock_table(soup)
            if table is None:
                last_error = f"sosok={sosok}: 표를 찾지 못함 ({_naver_fetch_fail_reason(res.status_code, res.text)})"
                continue
            for row in table.select("tr"):
                link = row.select_one("a")
                if not link or "code=" not in link.get("href", ""):
                    continue
                name = link.get_text(strip=True)
                code = link.get("href", "").split("code=")[-1].split("&")[0]
                num_tds = row.select("td.number")
                price, change_pct, volume, amount = None, None, None, None
                try:
                    # 순서: [0]현재가, [1]전일비, [2]등락률%, [3]매수호가, [4]매도호가,
                    #       [5]거래량, [6]거래대금(백만원), [7]전일거래량
                    if len(num_tds) >= 1:
                        price = int(num_tds[0].get_text(strip=True).replace(",", ""))
                    if len(num_tds) >= 3:
                        change_pct = float(num_tds[2].get_text(strip=True).replace("%", "").replace("+", ""))
                    if len(num_tds) >= 6:
                        volume = int(num_tds[5].get_text(strip=True).replace(",", ""))
                    if len(num_tds) >= 7:
                        amount = int(num_tds[6].get_text(strip=True).replace(",", "")) * 1_000_000
                except (ValueError, IndexError):
                    pass
                if amount is None:
                    amount = (price or 0) * (volume or 0)
                all_stocks.append({"name": name, "code": code, "price": price,
                                    "change_pct": change_pct, "volume": volume, "amount": amount})
        except Exception as e:
            last_error = f"sosok={sosok}: {e}"
            continue

    dedup = {}
    for s in all_stocks:
        if s["code"] and s["code"] not in dedup:
            dedup[s["code"]] = s
    result = list(dedup.values())
    if not result:
        raise RuntimeError(last_error or "거래상위 페이지에서 종목 데이터를 찾지 못함")
    return result


def fetch_trading_value_top30():
    """코스피+코스닥 통합 '거래대금 상위' 30종목 (거래상위 페이지를 거래대금 기준으로 재정렬).
    [{"rank":.., "name":.., "code":.., "price":.., "change_pct":.., "volume":.., "amount":..}, ...]"""
    ranked = sorted(_fetch_sise_quant_combined(), key=lambda x: x["amount"] or 0, reverse=True)[:30]
    for i, s in enumerate(ranked, start=1):
        s["rank"] = i
    return ranked


def fetch_volume_rank_top30():
    """코스피+코스닥 통합 '거래량순위 상위' 30종목 (거래상위 페이지를 거래량 기준으로 재정렬).
    [{"rank":.., "name":.., "code":.., "price":.., "change_pct":.., "volume":.., "amount":..}, ...]"""
    ranked = sorted(_fetch_sise_quant_combined(), key=lambda x: x["volume"] or 0, reverse=True)[:30]
    for i, s in enumerate(ranked, start=1):
        s["rank"] = i
    return ranked


def fetch_nxt_trading_top30():
    """넥스트레이드(NXT) '거래상위' 30종목, 거래대금 기준 (코스피+코스닥 NXT 시세 통합).
    ※ 네이버페이 증권이 2025.3부터 NXT 시세를 제공하기 시작했으나, NXT 전용 조회 파라미터는
    공식 문서가 없어 추정치(nxt=1)로 구현했다. 실제로 값이 비거나 KRX와 동일하게 나오면
    _fetch_sise_quant_combined()의 nxt 파라미터/URL을 조정해야 한다."""
    ranked = sorted(_fetch_sise_quant_combined(nxt=True), key=lambda x: x["amount"] or 0, reverse=True)[:30]
    for i, s in enumerate(ranked, start=1):
        s["rank"] = i
    return ranked


# ▶ 토글 버튼 상태(0/1/2)와 각 상태에서 왼쪽(네이버 자리)/오른쪽(업종테마 자리)에 표시할 리스트 매핑.
# 0=기본(네이버인기테마/업종테마), 1=(네이버검색상위30/거래대금상위30), 2=(거래량순위상위30/NXT거래상위30)
_TOP30_LIST_META = {
    "search": {"label": "🔍 네이버검색상위 30종목", "fetch": fetch_naver_search_top30, "amount_fn": _naver_amount_calc},
    "amount": {"label": "💰 거래대금 상위 30종목", "fetch": fetch_trading_value_top30,
               "amount_fn": lambda s: s.get("amount") or 0},
    "volume": {"label": "📈 거래량순위 상위 30종목", "fetch": fetch_volume_rank_top30,
               "amount_fn": lambda s: s.get("amount") or 0},
    "nxt": {"label": "🆕 NXT 거래상위 30종목", "fetch": fetch_nxt_trading_top30,
            "amount_fn": lambda s: s.get("amount") or 0},
}
_TOP30_MODE_PAIRS = {1: ("search", "amount"), 2: ("volume", "nxt")}


def compute_gangnamyeon_signal(full_df: pd.DataFrame) -> pd.Series:
    """강남연 신호: 아래 3개 키움 신호가 같은 날 동시에 뜨는 시점.
    신호1: avg(거래대금,1) >= 15000 and C(1)*1.15 <= H and L*1.15 <= H and O*1.09 <= C  (=compute_kiwoom_signal4_bigmove)
    신호2: Disparity(25) >= 106  (=compute_kiwoom_signal1_disparity)
    신호3: MA10=EAvg(C,10); MA20=EAvg(C,20); MA10>MA20 and V>Avg(V,10)*2 and C>O and C>C(1)  (=compute_kiwoom_signal2_ma_volume)
    """
    s1 = compute_kiwoom_signal4_bigmove(full_df)
    s2 = compute_kiwoom_signal1_disparity(full_df)
    s3 = compute_kiwoom_signal2_ma_volume(full_df)
    return (s1 & s2 & s3).fillna(False)


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangnamyeon_signal_today(code: str) -> bool:
    """강남연 신호(신호1+신호2+신호3 동시발생)가 최신(당일) 봉에서 떴는지 여부. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 65:
            return False
        sig = compute_gangnamyeon_signal(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


def compute_gwayeon_signal(full_df: pd.DataFrame) -> pd.Series:
    """과연 신호: 아래 2개 키움 신호가 같은 날 동시에 뜨는 시점.
    신호1: Disparity(25) >= 106  (=compute_kiwoom_signal1_disparity)
    신호2: MA10=EAvg(C,10); MA20=EAvg(C,20); MA10>MA20 and V>Avg(V,10)*2 and C>O and C>C(1)  (=compute_kiwoom_signal2_ma_volume)
    """
    s1 = compute_kiwoom_signal1_disparity(full_df)
    s2 = compute_kiwoom_signal2_ma_volume(full_df)
    return (s1 & s2).fillna(False)


@st.cache_data(ttl=300, show_spinner=False)
def cached_gwayeon_signal_today(code: str) -> bool:
    """과연 신호(신호1+신호2 동시발생)가 최신(당일) 봉에서 떴는지 여부. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 65:
            return False
        sig = compute_gwayeon_signal(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


def _signal_hit_in_window(full_df: pd.DataFrame, compute_fn, start_days_back: int = 7,
                           end_days_back: int = 1) -> bool:
    """'일주' 계열 신호 판정 공용 함수: compute_fn이 만든 신호가 (최신봉 날짜 - start_days_back)일부터
    (최신봉 날짜 - end_days_back)일까지 범위 안의 어느 봉에서든 한 번이라도 떴으면 True.
    end_days_back=1 이면 당일은 제외하고 어제까지, start_days_back=7이면 1주일 전부터 포함."""
    if full_df.empty:
        return False
    sig = compute_fn(full_df)
    if sig.empty:
        return False
    dates = full_df["date"]
    last_date = dates.iloc[-1]
    window_start = last_date - pd.Timedelta(days=start_days_back)
    window_end = last_date - pd.Timedelta(days=end_days_back)
    mask = (dates >= window_start) & (dates <= window_end)
    return bool(sig[mask].any())


def _signal_count_in_window(full_df: pd.DataFrame, compute_fn, start_days_back: int = 90,
                             end_days_back: int = 1, min_count: int = 2, exact: bool = False) -> bool:
    """필터 전용 공용 함수: compute_fn이 만든 신호가 (최신봉 날짜 - start_days_back)일부터
    (최신봉 날짜 - end_days_back)일까지 범위 안에서 몇 번 떴는지로 판정.
    end_days_back=1이면 당일 제외 어제까지, end_days_back=0이면 당일 포함, start_days_back=90이면
    90일 전부터 포함. exact=False면 min_count번 '이상', exact=True면 정확히 min_count번일 때만 True.
    (해당 종목의 전체 데이터가 start_days_back일보다 짧아도 있는 데이터 범위 안에서 그대로 판정한다.)"""
    if full_df.empty:
        return False
    sig = compute_fn(full_df)
    if sig.empty:
        return False
    dates = full_df["date"]
    last_date = dates.iloc[-1]
    window_start = last_date - pd.Timedelta(days=start_days_back)
    window_end = last_date - pd.Timedelta(days=end_days_back)
    mask = (dates >= window_start) & (dates <= window_end)
    cnt = int(sig[mask].sum())
    return cnt == min_count if exact else cnt >= min_count


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangnamyeon_signal_week(code: str) -> bool:
    """강남연 신호가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 65:
            return False
        return _signal_hit_in_window(full_df, compute_gangnamyeon_signal)
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_white_signal_week(code: str) -> bool:
    """흰신호(신호3)가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 55:
            return False
        return _signal_hit_in_window(full_df, compute_kiwoom_signal3_bbands_envelope)
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_vertical_blue_signal_week(code: str) -> bool:
    """수직파랑 신호가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 145:
            return False
        return _signal_hit_in_window(full_df, compute_vertical_blue_signal)
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_gwayeon_signal_week(code: str) -> bool:
    """과연 신호가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 65:
            return False
        return _signal_hit_in_window(full_df, compute_gwayeon_signal)
    except Exception:
        return False


def compute_vertical_blue_signal(full_df: pd.DataFrame) -> pd.Series:
    """수직파랑 신호(스캔 전용 - 일봉 세력평단가 차트에는 아직 표시하지 않음):
    CL = valuewhen(1, (highest(h(1), 120) < highest(h, 120)), ((highest(high, 20) + lowest(low, 20)) / 2));
    TargetLine = highest(H, 20) - (((highest(H, 20) - CL) / 5) * 10);
    CrossUp(C, TargetLine)

    - highest(h(1),120) < highest(h,120): 오늘 고가가 최근 120일 신고가를 새로 갱신한 시점(신고가 돌파일)
    - CL: 신고가 돌파가 일어난 가장 최근 시점의 (20일 고가+20일 저가)/2 값을, 다음 돌파가 나올 때까지 그대로 유지(forward-fill)
    - TargetLine = 2*CL - highest(H,20) (20일 고가를 CL 기준으로 대칭 반사시킨 값)
    - 종가가 TargetLine을 상향 돌파하는 시점이 신호
    """
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]

    roll_high20 = high.rolling(20).max()
    roll_low20 = low.rolling(20).min()
    roll_high120 = high.rolling(120).max()
    roll_high120_prev = roll_high120.shift(1)  # highest(h(1), 120)

    breakout_cond = roll_high120_prev < roll_high120  # highest(h(1),120) < highest(h,120)
    expr = (roll_high20 + roll_low20) / 2

    # valuewhen(1, cond, expr): 조건이 True였던 가장 최근 시점의 expr 값을 다음 True가 나올 때까지 유지
    CL = expr.where(breakout_cond).ffill()

    target_line = roll_high20 - (((roll_high20 - CL) / 5) * 10)

    return _crossup(close, target_line).fillna(False)


@st.cache_data(ttl=300, show_spinner=False)
def cached_vertical_blue_signal_today(code: str) -> bool:
    """수직파랑 신호가 최신(당일) 봉에서 떴는지 여부. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 145:
            return False
        sig = compute_vertical_blue_signal(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_yeokbaejeongcho_signal_today(code: str) -> bool:
    """역배정초 신호(compute_yellow_arrow_signal)가 최신(당일) 봉에서 떴는지 여부. 5분 캐시.
    BBU300(300봉 볼린저밴드) 계산 때문에 다른 신호보다 훨씬 긴 데이터가 필요하다."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 320:
            return False
        sig = compute_yellow_arrow_signal(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_yeokbaejeongcho_signal_week(code: str) -> bool:
    """역배정초 신호가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 320:
            return False
        return _signal_hit_in_window(full_df, compute_yellow_arrow_signal)
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_kkotyeolmae_signal_today(code: str) -> bool:
    """꽃열매 신호(compute_kkotsaem_signal)가 최신(당일) 봉에서 떴는지 여부. 5분 캐시.
    PriceOsc(5,112,26)의 장기(112) EMA와 40봉 shift 때문에 넉넉한 데이터가 필요하다."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 200:
            return False
        sig = compute_kkotsaem_signal(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_kkotyeolmae_signal_week(code: str) -> bool:
    """꽃열매 신호가 1주일 전부터 어제까지(당일 제외) 사이에 한 번이라도 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 200:
            return False
        return _signal_hit_in_window(full_df, compute_kkotsaem_signal)
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangse2_signal(code: str) -> bool:
    """하루전90강세둘 필터: avg(거래대금,1)>=15000 and C(1)*1.15<=H and L*1.15<=H and O*1.09<=C
    (=compute_kiwoom_signal4_bigmove) 신호가 하루 전부터 90일 사이에 2번 이상 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 95:
            return False
        return _signal_count_in_window(
            full_df, compute_kiwoom_signal4_bigmove, start_days_back=90, end_days_back=1, min_count=2
        )
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangse_today90_2plus_signal(code: str) -> bool:
    """당일90강세둘이상 필터: 같은 신호(compute_kiwoom_signal4_bigmove)가 당일부터 90일 사이에
    2번 이상 떴는지. 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 5:
            return False
        return _signal_count_in_window(
            full_df, compute_kiwoom_signal4_bigmove, start_days_back=90, end_days_back=0, min_count=2
        )
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangse_today7m_2exact_signal(code: str) -> bool:
    """당일7개월강세둘만 필터: 같은 신호가 당일부터 7개월(210일) 사이에 정확히 2번만 떴는지.
    (해당 종목 데이터가 7개월보다 짧아도 있는 만큼만으로 그대로 판정 - 최소 6개월치는 있어야 함) 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 120:  # 최소 약 6개월치 거래일
            return False
        return _signal_count_in_window(
            full_df, compute_kiwoom_signal4_bigmove, start_days_back=210, end_days_back=0,
            min_count=2, exact=True,
        )
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_gangse_today7m_3plus_signal(code: str) -> bool:
    """당일7개월강세셋이상 필터: 같은 신호가 당일부터 7개월(210일) 사이에 3번 이상 떴는지.
    (해당 종목 데이터가 7개월보다 짧아도 있는 만큼만으로 그대로 판정 - 최소 6개월치는 있어야 함) 5분 캐시."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 120:  # 최소 약 6개월치 거래일
            return False
        return _signal_count_in_window(
            full_df, compute_kiwoom_signal4_bigmove, start_days_back=210, end_days_back=0, min_count=3
        )
    except Exception:
        return False


def _run_signal_auto_scan(signal_check_fn, label: str, delay_sec: float = 2.5, status_box=None):
    """공용 신호 자동 스캔: 네이버 테마를 새로고침한 뒤, 네이버인기테마(1~30위) → 업종테마(1~30위)
    순서로 구성종목을 훑어서 당일 signal_check_fn(code)가 True인 종목을 자동으로 관심종목 체크해준다.
    label은 진행 상태 문구와 결과 요약에 표시되는 버튼 이름(예: '흰', '강남연')이다.
    status_box는 진행 상황을 실시간으로 표시할 st.empty() 자리(placeholder). 팝오버 버튼을 누르면
    팝오버 자체는 닫히므로, 팝오버 밖(버튼 줄 아래)에 미리 만들어둔 placeholder를 넘겨받아야
    스캔 도중 몇 번째 테마를 확인 중인지가 화면에 실시간으로 보인다. 안 넘기면 새로 하나 만든다.
    네이버·키움 서버 부담을 줄이기 위해 테마 하나씩 처리하고 사이사이 딜레이를 둔다.
    '대금'/'천억↓' 필터가 켜져 있으면 그 기준을 먼저 통과한 종목만 신호를 검사한다
    (필터링된 종목 수만큼 API 호출이 줄어 더 빨라진다)."""
    import time as _time

    st.session_state.setdefault("kiwoom_seen_themes", set())
    st.session_state.setdefault("selected_naver_theme", None)
    st.session_state.setdefault("naver_theme_stock_cache", {})

    amt_threshold = AMT_HIDE_OPTIONS.get(st.session_state.get("shared_amt_hide_choice", "안함"))
    hide_smallcap = st.session_state.get("shared_hide_smallcap", False)

    if status_box is None:
        status_box = st.empty()

    _top30_mode = st.session_state.get("top30_toggle_mode", 0)

    # 1) 좌측: 급등순위 전체(0%~30%) - 화면에 보이는 ▶ 밴드와 무관하게 항상 전체를 스캔한다.
    #    (▶는 화면 표시 방식일 뿐이라, 흰네업/일주/필터는 항상 전체 데이터를 대상으로 해야
    #    지금 화면에 3~8종목만 보이는 좁은 밴드에 있어도 신호를 놓치지 않는다)
    #    로컬 캐시 전용 - 키움을 절대 다시 조회하지 않는다.
    #    ('업'을 눌러 저장해둔 데이터 또는 '요'에서 선택한 과거 날짜 데이터만 사용)
    status_box.caption(f"{label}: 급등순위 전체(0%~30%) 확인 중 (로컬 데이터)...")
    _band = _get_active_surge_rank_data()

    naver_found = 0
    kiwoom_found = 0
    matched_codes = set()

    for idx, s in enumerate(_band, start=1):
        code = s.get("code")
        if not code:
            continue
        status_box.caption(f"{label}: 급등순위 {idx}/{len(_band)} 확인 중 ({s.get('name', '')})")
        s_marcap = marketcap_map.get(code)
        if hide_smallcap and s_marcap and s_marcap < 1e11:
            continue
        if amt_threshold is not None and (s.get("price") or 0) * (s.get("volume") or 0) < amt_threshold:
            continue
        if signal_check_fn(code):
            st.session_state.checked_stocks[code] = s.get("name", "")
            naver_found += 1
            matched_codes.add(code)

    # 2) 우측: 업종테마 1위 ~ 30위 (키움 API, 기존 그대로 - 이쪽은 계속 실시간 조회)
    for idx, theme in enumerate(kiwoom_groups, start=1):
        grp_cd = theme.get("thema_grp_cd", "")
        grp_nm = re.sub(r"\([^)]*\)", "", theme.get("thema_nm", "")).strip()
        status_box.caption(f"{label}: NXT거래상위 {idx}/{len(kiwoom_groups)}위 확인 중 ({grp_nm})")
        st.session_state.kiwoom_seen_themes.add(grp_cd)
        stocks = cached_theme_stocks(grp_cd)
        for s in stocks:
            code = s.get("stk_cd")
            if not code:
                continue
            s_marcap = marketcap_map.get(code)
            if hide_smallcap and s_marcap and s_marcap < 1e11:
                continue
            if amt_threshold is not None and _kiwoom_amount_calc(s) < amt_threshold:
                continue
            if signal_check_fn(code):
                st.session_state.checked_stocks[code] = s.get("stk_nm", "")
                kiwoom_found += 1
                matched_codes.add(code)
        if idx < len(kiwoom_groups):
            _time.sleep(delay_sec)

    status_box.empty()
    st.session_state["white_auto_scan_summary"] = {
        "label": label,
        "a_label": "급등순위(0%~30%)",
        "b_label": "업종테마",
        "naver_found": naver_found,
        "kiwoom_found": kiwoom_found,
        "unique_found": len(matched_codes),
        "ts": datetime.now().strftime("%H:%M:%S"),
    }


def _run_white_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '흰' 버튼: 당일 흰신호(신호3, 일봉 세력평단가 차트)가 뜬 종목을 자동으로 찾아
    관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "흰"
    _run_signal_auto_scan(cached_white_signal_today, "흰", delay_sec=delay_sec, status_box=status_box)


def _run_gangnamyeon_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '강남연' 버튼: 강남연 신호(신호1+신호2+신호3 동시발생)가 당일 뜬 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "강남연"
    _run_signal_auto_scan(cached_gangnamyeon_signal_today, "강남연", delay_sec=delay_sec, status_box=status_box)


def _run_gwayeon_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '과연' 버튼: 과연 신호(신호1+신호2 동시발생)가 당일 뜬 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "과연"
    _run_signal_auto_scan(cached_gwayeon_signal_today, "과연", delay_sec=delay_sec, status_box=status_box)


def _run_gangnamyeon_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '강남연' 버튼: 강남연 신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·강남연"
    _run_signal_auto_scan(cached_gangnamyeon_signal_week, "일주·강남연", delay_sec=delay_sec, status_box=status_box)


def _run_white_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '흰' 버튼: 흰신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·흰"
    _run_signal_auto_scan(cached_white_signal_week, "일주·흰", delay_sec=delay_sec, status_box=status_box)


def _run_vertical_blue_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '수직파랑' 버튼: 수직파랑 신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·수직파랑"
    _run_signal_auto_scan(cached_vertical_blue_signal_week, "일주·수직파랑", delay_sec=delay_sec, status_box=status_box)


def _run_gwayeon_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '과연' 버튼: 과연 신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·과연"
    _run_signal_auto_scan(cached_gwayeon_signal_week, "일주·과연", delay_sec=delay_sec, status_box=status_box)


def _run_vertical_blue_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '수직파랑' 버튼: 수직파랑 신호(120일 신고가 돌파 기준 CL·TargetLine을
    종가가 상향 돌파)가 당일 뜬 종목을 자동으로 찾아 관심종목에 체크한다.
    (네이버인기테마 1~30위 → 업종테마 1~30위 순서, 일봉 세력평단가 차트에는 별도 표시 없이 스캔 전용)"""
    st.session_state["active_list_filter"] = "수직파랑"
    _run_signal_auto_scan(cached_vertical_blue_signal_today, "수직파랑", delay_sec=delay_sec, status_box=status_box)


def _run_yeokbaejeongcho_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '역배정초' 버튼: 역배정초 신호(BBU300 우상향 + 이평20 눌림목 반등 +
    볼밴/60일선 상향돌파 + 거래대금 필터)가 당일 뜬 종목을 자동으로 찾아 관심종목에 체크한다.
    (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "역배정초"
    _run_signal_auto_scan(cached_yeokbaejeongcho_signal_today, "역배정초", delay_sec=delay_sec, status_box=status_box)


def _run_yeokbaejeongcho_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '역배정초' 버튼: 역배정초 신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·역배정초"
    _run_signal_auto_scan(cached_yeokbaejeongcho_signal_week, "일주·역배정초", delay_sec=delay_sec, status_box=status_box)


def _run_kkotyeolmae_signal_auto_scan(delay_sec: float = 2.5, status_box=None):
    """흰네업 팝오버 안 '꽃열매' 버튼: 꽃열매 신호(키움 조건검색 '꽃열매' 그대로 이식,
    PriceOsc 이중 조건 + 40봉 신고가 + 거래대금 필터 + 양봉)가 당일 뜬 종목을 자동으로 찾아
    관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "꽃열매"
    _run_signal_auto_scan(cached_kkotyeolmae_signal_today, "꽃열매", delay_sec=delay_sec, status_box=status_box)


def _run_kkotyeolmae_signal_week_auto_scan(delay_sec: float = 2.5, status_box=None):
    """일주 팝오버 안 '꽃열매' 버튼: 꽃열매 신호가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을
    자동으로 찾아 관심종목에 체크한다. (네이버인기테마 1~30위 → 업종테마 1~30위 순서)"""
    st.session_state["active_list_filter"] = "일주·꽃열매"
    _run_signal_auto_scan(cached_kkotyeolmae_signal_week, "일주·꽃열매", delay_sec=delay_sec, status_box=status_box)


def _visible_stocks_generic(stocks, amount_fn, code_key):
    """대금/천억↓/흰 필터를 통과하는 종목만 남긴다 (테마 목록 우측 숫자와 동일한 기준)."""
    amt_threshold = AMT_HIDE_OPTIONS.get(st.session_state.get("shared_amt_hide_choice", "안함"))
    hide_smallcap = st.session_state.get("shared_hide_smallcap", False)
    out = []
    for s in stocks:
        code = s.get(code_key)
        if not code:
            continue
        s_marcap = marketcap_map.get(code)
        if hide_smallcap and s_marcap and s_marcap < 1e11:
            continue
        if amt_threshold is not None and amount_fn(s) < amt_threshold:
            continue
        if not _passes_white_filter(code):
            continue
        out.append(s)
    return out


def _run_check_all_visible_themes():
    """체관: 이미 종목 목록을 불러와서(=우측에 숫자가 표시되는) 보이는 종목이 1개 이상인
    테마들을 전부 찾아서, 각 테마의 '전체선택' + 종목별 '선택' 체크박스를 한 번에 ON으로 켜고
    그 종목들을 관심종목 체크에 반영한다. (네이버·업종테마 공통, 아직 안 펼쳐본 테마는 대상 아님)"""
    _ver = st.session_state.get("stock_chk_reset_ver", 0)

    # 현재 화면에 떠 있는 급등순위 밴드(로컬 캐시 전용)도 동일하게 체관 대상에 포함
    _top30_mode = st.session_state.get("top30_toggle_mode", 0)
    _band_low, _band_high = SURGE_RANK_BANDS.get(_top30_mode, SURGE_RANK_BANDS[0])
    _band = _surge_rank_band(_band_low, _band_high)
    _band_amount_fn = lambda s: (s.get("price") or 0) * (s.get("volume") or 0)
    _vis_band = _visible_stocks_generic(_band, _band_amount_fn, "code")
    if _vis_band:
        for s in _vis_band:
            st.session_state.checked_stocks[s.get("code")] = s.get("name", "")
        if _top30_mode == 0:
            for s in _vis_band:
                st.session_state[f"surge_band0_chk_{s['code']}_v{_ver}"] = True
            st.session_state[f"surge_band0_selall_v{_ver}"] = True
        else:
            _half = (len(_band) + 1) // 2
            _left_codes = {s.get("code") for s in _band[:_half]}
            for s in _vis_band:
                _side = "left" if s.get("code") in _left_codes else "right"
                st.session_state[f"surge_band{_top30_mode}_{_side}_chk_{s['code']}_v{_ver}"] = True
            st.session_state[f"surge_band{_top30_mode}_left_selall_v{_ver}"] = True
            st.session_state[f"surge_band{_top30_mode}_right_selall_v{_ver}"] = True

    # 업종테마: 이미 펼쳐봐서 종목 목록이 있는 테마들
    for grp_cd in list(st.session_state.get("kiwoom_seen_themes", set())):
        stocks = cached_theme_stocks(grp_cd)
        vis = _visible_stocks_generic(stocks, _kiwoom_amount_calc, "stk_cd")
        if vis:
            for s in vis:
                s_cd = s.get("stk_cd")
                st.session_state.checked_stocks[s_cd] = s.get("stk_nm", "")
                st.session_state[f"chk_{grp_cd}_{s_cd}_v{_ver}"] = True
            st.session_state[f"selall_{grp_cd}_v{_ver}"] = True

    # 네이버테마: 이미 구성종목을 받아온 테마들
    for no, stocks in list(st.session_state.get("naver_theme_stock_cache", {}).items()):
        vis = _visible_stocks_generic(stocks or [], _naver_amount_calc, "code")
        if vis:
            for s in vis:
                s_code = s.get("code")
                st.session_state.checked_stocks[s_code] = s.get("name", "")
                st.session_state[f"navchk_{no}_{s_code}_v{_ver}"] = True
            st.session_state[f"selall_naver_{no}_v{_ver}"] = True


def _render_top30_list_panel(list_kind: str):
    """▶ 토글 ON 시 표시되는 flat 30종목 리스트 (list_kind: search/amount/volume/nxt, _TOP30_LIST_META 참고).
    관심종목 체크·전체선택·차트이동은 네이버인기테마/업종테마 목록과 동일하게 checked_stocks에
    직접 반영되므로, 관심(폴더저장)/흰네업/일주/체관/체취 버튼과 대금/천억↓/필터(흰·강남연 등 신호필터)가
    _visible_stocks_generic()을 그대로 재사용해서 다른 목록들과 완전히 동일하게 연동된다."""
    _meta = _TOP30_LIST_META[list_kind]
    label = _meta["label"]
    cache_key = f"top30_{list_kind}_cache"
    amount_fn = _meta["amount_fn"]

    hdr_col, refresh_col = st.columns([2.2, 1], gap="small")
    with hdr_col:
        st.markdown(f"<div style='font-size:11px; font-weight:700;'>{label}</div>", unsafe_allow_html=True)
    with refresh_col:
        if st.button("🔄 새로고침", key=f"top30_refresh_{list_kind}", use_container_width=True):
            st.session_state[cache_key] = None
            st.rerun()

    stocks = st.session_state.get(cache_key)
    if stocks is None:
        try:
            stocks = _meta["fetch"]()
        except Exception as e:
            st.warning(f"{label} 조회 실패: {e}")
            stocks = []
        st.session_state[cache_key] = stocks

    if not stocks:
        st.caption("데이터를 불러오지 못했습니다. 위 새로고침을 눌러주세요.")
        return

    _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
    visible = _visible_stocks_generic(stocks[:30], amount_fn, "code")
    _visible_codes = {s.get("code") for s in visible}

    _selall_key = f"top30_selall_{list_kind}_v{_chk_ver}"
    _all_checked = bool(visible) and all(s.get("code") in st.session_state.checked_stocks for s in visible)
    _selall = st.checkbox("전체선택", value=_all_checked, key=_selall_key,
                          help="현재 대금/천억↓/필터를 통과해 보이는 종목 전체를 관심종목 체크")
    if _selall != _all_checked:
        for s in visible:
            code = s.get("code")
            if _selall:
                st.session_state.checked_stocks[code] = s.get("name", "")
                st.session_state[f"top30chk_{list_kind}_{code}_v{_chk_ver}"] = True
            else:
                st.session_state.checked_stocks.pop(code, None)
                st.session_state[f"top30chk_{list_kind}_{code}_v{_chk_ver}"] = False
        st.rerun()

    for s in stocks[:30]:
        code = s.get("code", "")
        if not code or code not in _visible_codes:
            continue
        rank = s.get("rank", "")
        name = s.get("name", "")
        price = s.get("price")
        pct = s.get("change_pct")
        pct_f = pct if pct is not None else 0.0
        s_color = "#e05252" if (pct or 0) > 0 else "#4a90e2" if (pct or 0) < 0 else "#666666"
        s_marcap = marketcap_map.get(code)

        row_col1, row_col_chk, row_col2 = st.columns([1.7, 0.3, 1.2], gap="small")
        with row_col1:
            if st.button(f"{rank}위 {name}", key=f"top30btn_{list_kind}_{code}", use_container_width=True):
                st.session_state.goto_query = code
                st.rerun()
        with row_col_chk:
            _chk = st.checkbox(
                "선택", value=(code in st.session_state.checked_stocks),
                key=f"top30chk_{list_kind}_{code}_v{_chk_ver}", label_visibility="collapsed",
            )
            if _chk:
                st.session_state.checked_stocks[code] = name
            else:
                st.session_state.checked_stocks.pop(code, None)
        with row_col2:
            pct_html = f"<span style='color:{s_color};'>{pct_f:+.2f}%</span>" if pct is not None else "-"
            cap_text = format_krw_large(s_marcap).replace("원", "") if s_marcap else "-"
            st.markdown(
                f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                f"{(price or 0):,.0f} {pct_html}<br>시{cap_text}</div>",
                unsafe_allow_html=True,
            )


# ----------------------------------------------------------------------
# 3. 차트 렌더링
# ----------------------------------------------------------------------
def _vol_color(eok: float, bands=VOL_COLOR_BANDS) -> str:
    for threshold, color in bands:
        if eok < threshold:
            return color
    return bands[-1][1]


# ---------------------------------------------------------
# N파동 목표가 Mapping (Wave1 = 5이평 언덕 - 상승 시작일 저가)
# ---------------------------------------------------------
N_WAVE_T_META = [
    ("T1", "약", 0.618, "#4263eb"),
    ("T2", "평균", 1.0, "#2b8a3e"),
    ("T3", "강", 1.618, "#e03131"),
    ("T4", "따블", 2.0, "#7048e8"),
    ("T5", "따블+@", 2.618, "#d6336c"),
    ("T6", "따따블", 4.236, "#e8590c"),
]


def _nearest_row_idx(frame: pd.DataFrame, target_date):
    """target_date 이전(또는 그날)의 가장 가까운 거래일 행의 인덱스를 찾는다.
    없으면 target_date 이후 첫 거래일로 대체."""
    dates = frame["date"].dt.date
    cands = frame.index[dates <= target_date]
    if len(cands) == 0:
        cands = frame.index[dates >= target_date]
        if len(cands) == 0:
            return None
        return cands[0]
    return cands[-1]


def compute_watchlist_gap(code: str, current_price: float):
    """관심종목으로 저장된 적 있는 종목이면, 최초 저장일의 종가 대비 현재가 괴리율을 계산.
    저장된 적 없거나 계산 불가하면 None."""
    added_date = get_first_watchlist_added_date(code)
    if added_date is None or not current_price:
        return None
    full_df = fetch_daily_ohlcv(code)
    if full_df.empty:
        return None
    idx = _nearest_row_idx(full_df, added_date)
    if idx is None:
        return None
    base_price = float(full_df.loc[idx, "close"])
    if not base_price:
        return None
    return {
        "added_date": added_date,
        "actual_date": full_df.loc[idx, "date"].strftime("%Y-%m-%d"),
        "base_price": base_price,
        "gap": (current_price - base_price) / base_price * 100,
    }


def compute_nwave_mapping(code: str, start_date, end_date, sma5_date, avg_date):
    """N파동 목표가 Mapping 계산.
    - 상승 시작일(=시작일) 저가 → Wave1 시작점
    - 5이평 언덕 날짜의 SMA5 값 → Wave1 끝점(피크)
    - 세력평단가 날짜의 (선택기간) 누적 세력평단 값 → 지지값
    - Wave1 = 5이평 피크값 - 상승시작일 저가
    - T1~T6 = 지지값 + Wave1 × (0.618/1.0/1.618/2.0/2.618/4.236)
    """
    full_df = fetch_daily_ohlcv(code)
    if full_df.empty:
        return None
    full_df = full_df.copy()
    if "ma5" not in full_df.columns:
        full_df["ma5"] = full_df["close"].rolling(5).mean()

    mask = (full_df["date"].dt.date >= start_date) & (full_df["date"].dt.date <= end_date)
    sub = full_df.loc[mask].copy()
    if sub.empty:
        return None
    sub["cum_vwap"] = (sub["close"] * sub["volume"]).cumsum() / sub["volume"].cumsum()

    start_low = float(sub["low"].iloc[0])
    start_actual_date = sub["date"].iloc[0].strftime("%Y-%m-%d")

    sma5_idx = _nearest_row_idx(full_df, sma5_date)
    sma5_val, sma5_actual_date = None, None
    if sma5_idx is not None and pd.notna(full_df.loc[sma5_idx, "ma5"]):
        sma5_val = float(full_df.loc[sma5_idx, "ma5"])
        sma5_actual_date = full_df.loc[sma5_idx, "date"].strftime("%Y-%m-%d")

    avg_idx = _nearest_row_idx(sub, avg_date)
    avg_val, avg_actual_date = None, None
    if avg_idx is not None and pd.notna(sub.loc[avg_idx, "cum_vwap"]):
        avg_val = float(sub.loc[avg_idx, "cum_vwap"])
        avg_actual_date = sub.loc[avg_idx, "date"].strftime("%Y-%m-%d")

    info = {
        "start_low": start_low, "start_date": start_actual_date,
        "sma5_val": sma5_val, "sma5_date": sma5_actual_date,
        "avg_val": avg_val, "avg_date": avg_actual_date,
        "wave1": None, "targets": None,
        "current_price": float(sub["close"].iloc[-1]),
    }
    if sma5_val is not None and avg_val is not None:
        wave1 = sma5_val - start_low
        info["wave1"] = wave1
        info["targets"] = {key: avg_val + wave1 * mult for key, _, mult, _ in N_WAVE_T_META}
    return info


def _nearest_row_idx_time(frame: pd.DataFrame, target_time):
    """target_time 이전(또는 그 시각)의 가장 가까운 분봉 행의 인덱스를 찾는다.
    없으면 target_time 이후 첫 분봉으로 대체. (_nearest_row_idx의 분봉/시각 버전)"""
    times = frame["datetime"].dt.time
    cands = frame.index[times <= target_time]
    if len(cands) == 0:
        cands = frame.index[times >= target_time]
        if len(cands) == 0:
            return None
        return cands[0]
    return cands[-1]


def find_min_ma_hill_time(df: pd.DataFrame, ma_period: int, start_time, end_time):
    """분봉 데이터의 (시작시각~종료시각) 구간에서 N봉 이동평균선이 가장 높은(고점=언덕) 시각을 자동으로 찾는다.
    종목을 바꿀 때마다 5(20/60/120)봉 언덕 시각을 손으로 일일이 맞추지 않아도 되도록,
    '목표' 버튼을 누르는 순간 자동으로 계산해서 채워주기 위한 보조 함수."""
    if df is None or df.empty:
        return None
    mask = (df["datetime"].dt.time >= start_time) & (df["datetime"].dt.time <= end_time)
    sub = df.loc[mask].reset_index(drop=True)
    if sub.empty:
        return None
    ma_series = sub["close"].rolling(ma_period, min_periods=1).mean()
    if ma_series.dropna().empty:
        return None
    peak_pos = int(ma_series.idxmax())
    return sub["datetime"].iloc[peak_pos].time()


def compute_nwave_mapping_minute(df: pd.DataFrame, start_time, end_time, sma_time, avg_time, ma_period: int = 5):
    """N파동 목표가 Mapping 계산 (당일 분봉 버전).
    - 상승 시작분(=시작분) 저가 → Wave1 시작점
    - 선택한 언덕 시각의 ma_period봉 이동평균값(기본 5봉) → Wave1 끝점(피크)
    - 세력평단가 시각의 (선택 시작분~종료분) 누적 세력평단 값 → 지지값
    - Wave1 = 언덕 피크값 - 상승시작분 저가
    - T1~T6 = 지지값 + Wave1 × (0.618/1.0/1.618/2.0/2.618/4.236)
    (일봉 버전 compute_nwave_mapping과 동일한 로직을 '일' 대신 '분'/'시각' 기준으로 계산.
    ma_period로 5/20/60/120봉 중 어떤 이동평균선을 언덕으로 쓸지 고를 수 있다.)
    """
    if df.empty:
        return None
    df = df.copy()
    ma_col = f"ma{ma_period}"
    if ma_col not in df.columns:
        df[ma_col] = df["close"].rolling(ma_period).mean()

    mask = (df["datetime"].dt.time >= start_time) & (df["datetime"].dt.time <= end_time)
    sub = df.loc[mask].copy()
    if sub.empty:
        return None
    sub["cum_vwap"] = (sub["close"] * sub["volume"]).cumsum() / sub["volume"].cumsum()

    start_low = float(sub["low"].iloc[0])
    start_actual_time = sub["datetime"].iloc[0].strftime("%H:%M")

    sma_idx = _nearest_row_idx_time(df, sma_time)
    sma5_val, sma5_actual_time = None, None
    if sma_idx is not None and pd.notna(df.loc[sma_idx, ma_col]):
        sma5_val = float(df.loc[sma_idx, ma_col])
        sma5_actual_time = df.loc[sma_idx, "datetime"].strftime("%H:%M")

    avg_idx = _nearest_row_idx_time(sub, avg_time)
    avg_val, avg_actual_time = None, None
    if avg_idx is not None and pd.notna(sub.loc[avg_idx, "cum_vwap"]):
        avg_val = float(sub.loc[avg_idx, "cum_vwap"])
        avg_actual_time = sub.loc[avg_idx, "datetime"].strftime("%H:%M")

    info = {
        "start_low": start_low, "start_date": start_actual_time,
        "sma5_val": sma5_val, "sma5_date": sma5_actual_time,
        "avg_val": avg_val, "avg_date": avg_actual_time,
        "wave1": None, "targets": None,
        "current_price": float(sub["close"].iloc[-1]),
    }
    if sma5_val is not None and avg_val is not None:
        wave1 = sma5_val - start_low
        info["wave1"] = wave1
        info["targets"] = {key: avg_val + wave1 * mult for key, _, mult, _ in N_WAVE_T_META}
    return info


def render_nwave_info_boxes(info: dict, start_label: str = "상승 시작일 (저가)",
                             ma_label: str = "5이평 언덕 (SMA5)", avg_label: str = "세력평단 Mapping"):
    """N파동 목표가 Mapping 결과 박스: 상승시작일/5이평언덕/세력평단/Wave1 4칸 + T1~T6 6칸.
    (분봉판은 start_label/ma_label을 '상승 시작분'/'N봉 언덕' 등으로 바꿔서 재사용)"""
    if not info:
        return

    def _fmt(v):
        return f"{v:,.0f}원" if v is not None else "날짜에 데이터 없음"

    metric_defs = [
        (start_label, f"{info['start_low']:,.0f}원", info.get("start_date")),
        (ma_label, _fmt(info.get("sma5_val")), info.get("sma5_date")),
        (avg_label, _fmt(info.get("avg_val")), info.get("avg_date")),
        ("Wave1 (상승폭)", f"{info['wave1']:,.0f}원" if info.get("wave1") is not None else "-", None),
    ]
    m_cols = st.columns(4)
    for col, (label, value, date_str) in zip(m_cols, metric_defs):
        with col:
            date_html = (
                f'<div style="font-size:11px; color:#51cf66; margin-top:2px;">▲ {date_str}</div>'
                if date_str else ""
            )
            st.markdown(
                f"""
                <div style="padding:2px 6px 6px 2px;">
                    <div style="font-size:12px; color:#9aa4b2;">{label}</div>
                    <div style="font-size:17px; font-weight:700; color:#eaeef5; margin-top:2px;">{value}</div>
                    {date_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

    if info.get("targets"):
        import streamlit.components.v1 as components
        _cur_price = info.get("current_price")
        t_cols = st.columns(6)
        for col, (key, label, _, color) in zip(t_cols, N_WAVE_T_META):
            val = info["targets"][key]
            if _cur_price:
                _gap = (val - _cur_price) / _cur_price * 100
                _gap_text = f"{_gap:+.2f}%"
            else:
                _gap_text = ""
            price_text = f"{val:,.0f}원"
            plain_number = f"{int(round(val))}"
            with col:
                components.html(f"""
                <style>
                .twave-box {{
                    border:1.5px solid {color}; border-radius:8px; padding:8px 4px;
                    text-align:center; background-color:{CARD_BG}; font-family:sans-serif;
                }}
                .twave-label {{ font-size:11px; font-weight:bold; color:{color}; }}
                .twave-gap {{ font-size:11px; font-weight:bold; color:{color}; margin-top:2px; }}
                .twave-price {{
                    font-size:13px; font-weight:bold; color:#eaeef5; margin-top:4px; cursor:pointer;
                }}
                .twave-price:hover {{ text-decoration: underline; }}
                </style>
                <div class="twave-box">
                    <div class="twave-label">{key} ({label})</div>
                    <div class="twave-gap">{_gap_text}</div>
                    <div class="twave-price" title="클릭 시 숫자만 복사" onclick="
                        navigator.clipboard.writeText('{plain_number}');
                        this.innerText='✅ 복사됨';
                        setTimeout(() => {{ this.innerText='{price_text}'; }}, 900);
                    ">{price_text}</div>
                </div>
                """, height=80)
    else:
        st.caption("5이평 언덕 / 세력평단가 날짜에 해당하는 데이터가 없습니다. 날짜를 다시 선택해주세요.")


# ---------------------------------------------------------
# 키움 수식 기반 매수 신호(노란 화살표)
# ---------------------------------------------------------
def compute_yellow_arrow_signal(full_df: pd.DataFrame) -> pd.Series:
    """키움 조건식(BBU300 우상향 + 이평20 눌림목 반등 + 볼밴/60일선 상향돌파 + 거래대금 필터)을
    그대로 판다스로 옮긴 신호. full_df는 date 오름차순 정렬된 전체 일봉 데이터여야 한다.
    반환값: full_df와 같은 인덱스를 갖는 bool Series (True인 날 = 신호 발생일)

    ※ 원 수식의 '거래대금' 필드는 키움 HTS 내부 단위를 그대로 알 수 없어
      close×volume(원화 거래대금)을 '억원' 단위로 환산해 근사했습니다.
      (거래대금/100 >= 50 → 5일 평균 거래대금 50억원 이상, 으로 해석)
    """
    close = full_df["close"]
    high = full_df["high"]
    volume = full_df["volume"]

    # BBU300 = 볼린저밴드 상단(300, 2)
    bb_mid300 = close.rolling(300).mean()
    bb_std300 = close.rolling(300).std(ddof=0)
    bbu300 = bb_mid300 + 2 * bb_std300
    A1 = (bbu300 > bbu300.shift(1)) & (bbu300.shift(1) > bbu300.shift(2))

    이평 = close.rolling(20).mean()
    이평60 = close.rolling(60).mean()

    A2 = (이평.shift(10) < 이평.shift(11)) & (이평.shift(11) < 이평.shift(12))
    A3 = (이평.shift(2) > 이평.shift(1)) & (이평 > 이평.shift(1))
    A4 = (이평.shift(3) > 이평.shift(2)) & (이평.shift(1) > 이평.shift(2))
    A5 = (이평.shift(4) > 이평.shift(3)) & (이평.shift(2) > 이평.shift(3))
    A6 = (이평.shift(5) > 이평.shift(4)) & (이평.shift(3) > 이평.shift(4))
    A7 = (이평.shift(6) > 이평.shift(5)) & (이평.shift(4) > 이평.shift(5))

    # BBandsup(20,2) 상단 돌파(crossup) 체크
    bb_mid20 = close.rolling(20).mean()
    bb_std20 = close.rolling(20).std(ddof=0)
    bbu20 = bb_mid20 + 2 * bb_std20
    체크 = (high > bbu20) & (high.shift(1) <= bbu20.shift(1))
    A8 = 체크.rolling(5).sum() >= 1

    A9 = 이평 < 이평60
    A10 = close > 이평

    체크1 = (high > 이평60) & (high.shift(1) <= 이평60.shift(1))
    A11 = 체크1.rolling(5).sum() >= 1

    trading_value_100m = (close * volume) / 100_000_000  # 억원 단위 근사 거래대금
    A12 = trading_value_100m.rolling(5).mean() >= 50

    signal = (
        A1 & A2 & (A3 | A4 | A5 | A6 | A7) & A8 & A9 & A10 & A11 & A12
    )
    return signal.fillna(False)


def _ema(series: pd.Series, period: int) -> pd.Series:
    """키움 EMA(지수이동평균)와 동일한 계산(adjust=False)."""
    return series.ewm(span=period, adjust=False).mean()


def _price_osc_and_signal(close: pd.Series, short: int, long: int, signal_period: int):
    """키움 Price Oscillator(단기,장기,시그널): PPO = (단기EMA-장기EMA)/장기EMA*100,
    Signal선 = PPO의 signal_period EMA. (ppo, signal) 튜플 반환."""
    ema_short = _ema(close, short)
    ema_long = _ema(close, long)
    ppo = (ema_short - ema_long) / ema_long * 100
    sig = _ema(ppo, signal_period)
    return ppo, sig


def compute_kkotsaem_signal(full_df: pd.DataFrame) -> pd.Series:
    """꽃샘 신호 (키움 조건검색 '꽃열매(꽃이지고 열매가 매수 신고가)' 그대로 이식):
    A: [일]0봉전 PriceOsc(5,112,26) Signal선 이상
    B: [일]40봉전 PriceOsc(5,112,26) Signal선 이하
    C: [일]0봉전 PriceOsc(20,60,26) Signal선 이상
    D: 신고가 - 0봉전 고가가 40봉중 신고가
    E: 1봉전부터 40봉이내 거래대금(백만원) 3,000 이상이 1회 이상 발생
    F: 0봉전 시가가 1봉전 종가 대비 1% 이상 상승
    G: 당일 거래대금(백만원) 300,000 ~ 999,999,990 (=3,000억원 이상)
    H: 0봉전 시가 < 0봉전 종가 (양봉)
    신호 = A and B and C and D and E and (F or G) and H
    """
    close = full_df["close"]
    open_ = full_df["open"]
    high = full_df["high"]
    volume = full_df["volume"]

    ppo_a, sig_a = _price_osc_and_signal(close, 5, 112, 26)
    A = ppo_a >= sig_a

    B = ppo_a.shift(40) <= sig_a.shift(40)

    ppo_c, sig_c = _price_osc_and_signal(close, 20, 60, 26)
    C = ppo_c >= sig_c

    D = high >= high.rolling(40).max()

    trading_value_100m_won = close * volume  # 원 단위
    tv_million = trading_value_100m_won / 1_000_000  # 백만원 단위 (키움 '거래대금' 표시 단위)
    E = (tv_million >= 3000).shift(1).rolling(40).sum() >= 1

    F = ((open_ - close.shift(1)) / close.shift(1) * 100) >= 1

    G = (tv_million >= 300000) & (tv_million <= 999999990)

    H = open_ < close

    signal = A & B & C & D & E & (F | G) & H
    return signal.fillna(False)


def _crossup(x: pd.Series, y: pd.Series) -> pd.Series:
    """키움 CrossUp(X,Y): 이전 봉엔 X<=Y 였다가 이번 봉에 X>Y 로 올라선 시점."""
    return (x > y) & (x.shift(1) <= y.shift(1))


def _crossdown(x: pd.Series, y: pd.Series) -> pd.Series:
    """키움 CrossDown(X,Y): 이전 봉엔 X>=Y 였다가 이번 봉에 X<Y 로 내려선 시점."""
    return (x < y) & (x.shift(1) >= y.shift(1))


def _valuewhen(cond: pd.Series, value: pd.Series) -> pd.Series:
    """키움 VALUEWHEN(1,cond,value): cond가 True인 시점의 value를 그 이후로 계속 유지(ffill)."""
    return value.where(cond.fillna(False)).ffill()


def _barssince(cond: pd.Series) -> pd.Series:
    """키움 BarsSince(cond): 마지막으로 cond가 True였던 시점부터 지난 봉 수(0=지금 True)."""
    idx = pd.Series(np.arange(len(cond)), index=cond.index)
    last_true_idx = idx.where(cond.fillna(False)).ffill()
    return idx - last_true_idx


def _highestsince(cond: pd.Series, value: pd.Series) -> pd.Series:
    """키움 HighestSince(1,cond,value): cond가 마지막으로 True였던 시점(그 시점 포함)부터
    지금까지 value의 최고값을 계속 갱신하며 유지."""
    cond = cond.fillna(False)
    group = cond.cumsum()
    return value.groupby(group).cummax()


def _trix(close: pd.Series, n: int) -> pd.Series:
    """TRIX(n): 종가를 n기간으로 3번 지수이동평균(EMA)한 값의 전봉 대비 변화율(%)."""
    ema1 = _ema(close, n)
    ema2 = _ema(ema1, n)
    ema3 = _ema(ema2, n)
    return (ema3 - ema3.shift(1)) / ema3.shift(1) * 100


def compute_ma20_60_crossup_signal(full_df: pd.DataFrame) -> pd.Series:
    """이화살표신호(초록 #00ff00, 세모/화살표):
    A = avg(C, 20); B = avg(C, 60); CrossUp(A, B)
    """
    close = full_df["close"]
    A = close.rolling(20).mean()
    B = close.rolling(60).mean()
    return _crossup(A, B).fillna(False)


def compute_isusik_star_signal(full_df: pd.DataFrame) -> pd.Series:
    """이수식 신호(노랑 #ffff00, 별표 ＊):
    x1 = CrossUp(C, avg(C,120))
    x2 = V >= avg(V,20)*1
    x3 = V >= 500000
    x4 = (C/C(1)-1)*100 >= 1
    x5 = (C/O-1)*100 >= 1
    signal = x1 and x2 and x3 and x4 and x5
    """
    close = full_df["close"]
    open_ = full_df["open"]
    volume = full_df["volume"]

    ma120 = close.rolling(120).mean()
    x1 = _crossup(close, ma120)

    vol_ma20 = volume.rolling(20).mean()
    x2 = volume >= (vol_ma20 * 1)

    x3 = volume >= 500000

    x4 = (close / close.shift(1) - 1) * 100 >= 1

    x5 = (close / open_ - 1) * 100 >= 1

    signal = x1 & x2 & x3 & x4 & x5
    return signal.fillna(False)


def compute_isusik_circle_signal(full_df: pd.DataFrame) -> pd.Series:
    """이신호(연노랑 #feff7a, 동그라미 ●):
    a = avg(C, 120); b = avg(C, 1); CrossUp(b, a)
    (avg(C,1)은 종가 그 자체이므로 종가가 120일 이평선을 상향 돌파하는 시점)
    """
    close = full_df["close"]
    a = close.rolling(120).mean()
    b = close.rolling(1).mean()
    return _crossup(b, a).fillna(False)


def compute_signal_seryeok_deolpa(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '세력선덜파'(보라, 삼각형):
    COND=(V>MA(V,20)*1.5) AND (C>O);
    평단=SUM(IF(COND,C*V,0),240)/SUM(IF(COND,V,0),240);
    CROSSUP(C,평단)"""
    close = full_df["close"]
    open_ = full_df["open"]
    volume = full_df["volume"]
    vol_ma20 = volume.rolling(20).mean()
    cond = (volume > vol_ma20 * 1.5) & (close > open_)
    cv_cond = (close * volume).where(cond, 0.0)
    v_cond = volume.where(cond, 0.0)
    a = cv_cond.rolling(240).sum()
    b = v_cond.rolling(240).sum()
    pyeongdan = a / b.replace(0, np.nan)
    return _crossup(close, pyeongdan).fillna(False)


def compute_signal_sanghyang_deolpa(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '상향덜파'(검정, 삼각형):
    A=(H+L+C)/3; B=SUM(A*V,120); M1=SUM(V,120); D=B/M1; E=eavg(eavg(D,8),5);
    CrossUp(C,E)"""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]
    volume = full_df["volume"]
    A = (high + low + close) / 3
    B = (A * volume).rolling(120).sum()
    M1 = volume.rolling(120).sum()
    D = B / M1.replace(0, np.nan)
    E = _ema(_ema(D, 8), 5)
    return _crossup(close, E).fillna(False)


def compute_signal_maesu_hubo(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '매수후보'(올리브, 삼각형):
    TP=(H+L+C)/3; VW=SUM(TP*V,120)/SUM(V,120); LINE=eavg(eavg(VW,8),5);
    CrossUp(C,LINE) AND V>avg(V,20)"""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]
    volume = full_df["volume"]
    TP = (high + low + close) / 3
    VW = (TP * volume).rolling(120).sum() / volume.rolling(120).sum().replace(0, np.nan)
    LINE = _ema(_ema(VW, 8), 5)
    vol_ma20 = volume.rolling(20).mean()
    signal = _crossup(close, LINE) & (volume > vol_ma20)
    return signal.fillna(False)


def compute_signal_sinho_up41(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '신호업41'(갈색, 화살표) — 원본 '신호 검색 설정' 창(지표변수 탭) 기준값:
    일자1=2, 일자2=448, 일자3=256, 일자4=26, 방법=12.
    M1=MA(C,2,12); M2=MA(C,448,12); M3=MA(C,256,12); M4=MA(C,26,12);
    조건=M1>M2&&M2>M3&&C>M1&& (뒤가 끊김) / m=macd(12,26); (조건식에 미사용)
    ※ 'MA(가격,기간,방법=12)'의 방법(12) 값이 정확히 어떤 이동평균 방식을 뜻하는지는
    알 수 없고, 조건식 마지막의 '&&'가 다음 항 없이 끊겨 있으며 macd도 조건에 쓰이지
    않아, 방법 값과 macd는 무시하고 M1/M2/M3를 단순이동평균으로, 조건은
    'M1>M2 and M2>M3 and C>M1' 로 해석해 구현했습니다(M4도 조건에 쓰이지 않아 미사용).
    실제 원본 화면(스크린샷)에서 상승 구간 동안 봉마다 연속으로 신호가 찍히는 것과
    일치하는 방식(크로스업 1회성이 아니라 조건이 참인 매 봉마다 표시)입니다."""
    close = full_df["close"]
    M1 = close.rolling(2).mean()
    M2 = close.rolling(448).mean()
    M3 = close.rolling(256).mean()
    signal = (M1 > M2) & (M2 > M3) & (close > M1)
    return signal.fillna(False)


def compute_signal_maedo(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '매도'(하늘색, 역삼각형):
    rsi(5) > eavg(rsi(5),10) + 2*stdev(rsi(5),10)"""
    close = full_df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 5, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 5, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi5 = 100 - 100 / (1 + rs)
    band = _ema(rsi5, 10) + 2 * rsi5.rolling(10).std(ddof=0)
    return (rsi5 > band).fillna(False)


def compute_signal_sabun(full_df: pd.DataFrame) -> pd.Series:
    """신호 스트립 '사번'(금색, 화살표).
    원 수식 첫 줄 'shift((highest(high,9)+lowest(low,9)+highest(high,26)+lowest(low,26))/4,26-1),'
    은 어떤 변수에도 대입되지 않고 콤마로 끊긴 채 이어지는 미완성 구문이라(신호업41의 미사용
    macd처럼) 실제 조건 계산에서 제외하고, 아래 4가지 조건을 AND로 묶어 구현했습니다:
    1) 5봉 박스권 상단 돌파선(TOP) 상향돌파: LT=LOWEST(L,5); HT=HIGHEST(H,5);
       NewH=VALUEWHEN(1,H>HT(1),H); BOX1=HIGHEST(H,3)<HIGHEST(H,4);
       TOP=VALUEWHEN(1,BarsSince(H>HT(1))==3 AND BOX1,NewH); CrossUp(C,TOP)
    2) eavg(C,20)<=eavg(C,5)
    3) 볼린저밴드(152,1) 폭 조건: A=((BBandsUp-BBandsDown)/BBandsC)*1000; B=(C-BBandsDown)/(BBandsUp-BBandsDown);
       D=A*1111; B>=1 and (1<=A<10000) and 최근 30봉 중 A(n)<D 인 시점이 한 번이라도 있음
    4) E=(당일고가-당일저가)*100 > 2
    (dayHigh()/dayLow()는 일봉 기준이라 그날의 고가/저가로 계산했습니다.)"""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]

    LT = low.rolling(5).min()
    HT = high.rolling(5).max()
    brk = high > HT.shift(1)
    NewH = _valuewhen(brk, high)
    BOX1 = high.rolling(3).max() < high.rolling(4).max()
    cond_top = (_barssince(brk) == 3) & BOX1
    TOP = _valuewhen(cond_top, NewH)
    part1 = _crossup(close, TOP)

    part2 = _ema(close, 20) <= _ema(close, 5)

    sma152 = close.rolling(152).mean()
    std152 = close.rolling(152).std(ddof=0)
    bb_up = sma152 + std152
    bb_down = sma152 - std152
    bb_c = sma152
    A = ((bb_up - bb_down) / bb_c.replace(0, np.nan)) * 1000
    B = (close - bb_down) / (bb_up - bb_down).replace(0, np.nan)
    D = A * 1111
    cond_hist = pd.Series(False, index=close.index)
    for k in range(1, 31):
        cond_hist = cond_hist | (A.shift(k) < D)
    part3 = (B >= 1) & (A >= 1) & (A < 10000) & cond_hist

    part4 = (high - low) * 100 > 2

    signal = part1 & part2 & part3 & part4
    return signal.fillna(False)


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> pd.Series:
    """CCI(N): (TP-SMA(TP,N)) / (0.015 * 평균편차(TP,N)), TP=(H+L+C)/3."""
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(n).mean()
    mad = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))


def compute_kiwoom_signal1_disparity(full_df: pd.DataFrame) -> pd.Series:
    """신호1(남색): Disparity(25) >= 106
    Disparity(N) = 종가 / N일 단순이동평균 * 100 (이격도)."""
    close = full_df["close"]
    disparity25 = close / close.rolling(25).mean() * 100
    return (disparity25 >= 106).fillna(False)


def compute_kiwoom_signal2_ma_volume(full_df: pd.DataFrame) -> pd.Series:
    """신호2(연두색):
    MA10=EAvg(C,10), MA20=EAvg(C,20) (지수이동평균)
    MA10 > MA20 and V > Avg(V,10)*2 and C > O and C > C(1)"""
    close = full_df["close"]
    open_ = full_df["open"]
    volume = full_df["volume"]

    ma10 = close.ewm(span=10, adjust=False).mean()
    ma20 = close.ewm(span=20, adjust=False).mean()
    avg_v10 = volume.rolling(10).mean()

    signal = (
        (ma10 > ma20)
        & (volume > avg_v10 * 2)
        & (close > open_)
        & (close > close.shift(1))
    )
    return signal.fillna(False)


def compute_kiwoom_signal3_bbands_envelope(full_df: pd.DataFrame) -> pd.Series:
    """신호3(흰색): 볼린저밴드 상단(17,2 / 40,2) + 이격도(20) + 엔벨로프(20,6 / 50,3) 조합 신호.
    A=BBandsUp(17,2); B=BBandsUp(40,2); D=Disparity(20);
    E=EnvelopeUp(20,6); P=EnvelopeUp(50,3)."""
    close = full_df["close"]
    open_ = full_df["open"]
    high = full_df["high"]
    volume = full_df["volume"]

    def _sma(s, n):
        return s.rolling(n).mean()

    def _std(s, n):
        return s.rolling(n).std(ddof=0)

    A = _sma(close, 17) + 2 * _std(close, 17)
    B = _sma(close, 40) + 2 * _std(close, 40)
    D = close / _sma(close, 20) * 100
    E = _sma(close, 20) * 1.06
    P = _sma(close, 50) * 1.03
    ma_h5 = _sma(high, 5)
    ma_v5 = _sma(volume, 5)

    sub1 = (close > ma_h5) & _crossup(A, E)
    sub2 = (close > ma_h5) & (B > E) & (A.shift(1) < B.shift(1)) & _crossup(A, B)
    sub3 = (A > B) & (B > E) & _crossup(close, A)
    sub4 = _crossup(close, A) & _crossup(close, E)
    sub5 = _crossup(close, A) & _crossup(close, B) & _crossup(close, E)
    sub_any = sub1 | sub2 | sub3 | sub4 | sub5

    branch1 = (
        (open_ < close) & (close > P.shift(19)) & (D < 150) & (D > D.shift(1)) & sub_any
    )
    branch2 = (
        (open_ < close) & (close < P.shift(19)) & (D > D.shift(1))
        & (volume > ma_v5 * 2) & sub_any
    )

    signal = branch1 | branch2
    return signal.fillna(False)


def compute_kiwoom_signal4_bigmove(full_df: pd.DataFrame) -> pd.Series:
    """신호4(자주색):
    avg(거래대금,1) >= 15000 and C(1)*1.15 <= H and L*1.15 <= H and O*1.09 <= C
    ※ '거래대금' 필드는 키움 HTS 내부 단위를 알 수 없어 종가×거래량을 백만원 단위로
      환산해 근사했습니다(15000 => 약 150억원)."""
    close = full_df["close"]
    open_ = full_df["open"]
    high = full_df["high"]
    low = full_df["low"]
    volume = full_df["volume"]

    trading_value_mn = (close * volume) / 1_000_000  # 백만원 단위 근사 거래대금

    signal = (
        (trading_value_mn >= 15000)
        & (close.shift(1) * 1.15 <= high)
        & (low * 1.15 <= high)
        & (open_ * 1.09 <= close)
    )
    return signal.fillna(False)


@st.cache_data(ttl=300, show_spinner=False)
def cached_white_signal_today(code: str) -> bool:
    """일봉 세력평단가 차트의 '신호3(흰색)'이 최신(당일) 봉에서 떴는지 여부.
    업종테마/네이버테마 목록에서 '흰' 필터가 켜졌을 때만 종목별로 호출된다.
    5분 캐시로 같은 종목을 반복 계산/재조회하지 않도록 한다."""
    try:
        full_df = fetch_daily_ohlcv(code)
        if full_df.empty or len(full_df) < 55:
            return False
        sig = compute_kiwoom_signal3_bbands_envelope(full_df)
        if sig.empty:
            return False
        return bool(sig.iloc[-1])
    except Exception:
        return False


_LIST_FILTER_FUNCS = {
    "흰": cached_white_signal_today,
    "강남연": cached_gangnamyeon_signal_today,
    "수직파랑": cached_vertical_blue_signal_today,
    "과연": cached_gwayeon_signal_today,
    "역배정초": cached_yeokbaejeongcho_signal_today,
    "꽃열매": cached_kkotyeolmae_signal_today,
    "일주·흰": cached_white_signal_week,
    "일주·강남연": cached_gangnamyeon_signal_week,
    "일주·수직파랑": cached_vertical_blue_signal_week,
    "일주·과연": cached_gwayeon_signal_week,
    "일주·역배정초": cached_yeokbaejeongcho_signal_week,
    "일주·꽃열매": cached_kkotyeolmae_signal_week,
    "하루전90강세둘": cached_gangse2_signal,
    "당일90강세둘이상": cached_gangse_today90_2plus_signal,
    "당일7개월강세둘만": cached_gangse_today7m_2exact_signal,
    "당일7개월강세셋이상": cached_gangse_today7m_3plus_signal,
}


def _passes_white_filter(code: str) -> bool:
    """목록 필터(옛 '흰' 토글, 이제는 여러 신호 중 하나를 고를 수 있는 팝오버)가 꺼져 있으면
    항상 통과. 켜져 있으면 선택된 신호가 해당 조건(당일 또는 일주일 이내)에 뜬 종목만 통과.
    흰네업/일주 스캔 버튼을 누르면 그 신호 이름으로 자동 활성화되어, 테마 옆 숫자도
    스캔으로 실제 찾은 종목 수만큼만 줄어들어 표시된다."""
    if not _passes_multi_signal_filter(code):
        return False
    active = st.session_state.get("active_list_filter")
    if not active:
        return True
    fn = _LIST_FILTER_FUNCS.get(active)
    if fn is None:
        return True
    return fn(code)


def _percent_axis_ticks(low: float, high: float, ref: float):
    """가격 범위(low~high)를 기준가(ref) 대비 등락률(%) 눈금으로 변환.
    반환값은 (실제 가격 tick 위치 리스트, '+5%' 형식의 라벨 리스트) — 플롯 축은 여전히
    실제 가격을 쓰되, 눈금 라벨만 키움 '비율차트'처럼 %로 보여준다."""
    if not ref or ref <= 0 or high <= low:
        return None, None

    pct_low = (low / ref - 1) * 100
    pct_high = (high / ref - 1) * 100
    span = pct_high - pct_low
    if span <= 0:
        return None, None

    nice_steps = [1, 2, 2.5, 5, 10, 15, 20, 25, 50, 100, 200, 250, 500]
    target = span / 7  # 대략 7~8개 눈금이 나오도록
    step = nice_steps[-1]
    for cand in nice_steps:
        if cand >= target:
            step = cand
            break

    start = np.floor(pct_low / step) * step
    end = np.ceil(pct_high / step) * step
    pct_ticks = np.arange(start, end + step / 2, step)

    tickvals = [ref * (1 + p / 100) for p in pct_ticks]
    ticktext = [f"{p:+.0f}%" for p in pct_ticks]
    return tickvals, ticktext


def _wma(series: pd.Series, n: int) -> pd.Series:
    """키움 가중이동평균(선형가중, WMA): 최근 봉일수록 가중치가 크게(1..n) 부여된 이동평균."""
    if n < 1:
        return series * np.nan
    weights = np.arange(1, n + 1, dtype=float)
    w_sum = weights.sum()
    return series.rolling(n).apply(lambda x: np.dot(x, weights) / w_sum, raw=True)


def compute_kiwoom_line_cyan_hh(full_df: pd.DataFrame, ma_period: int = 41, hh_window: int = 40) -> pd.Series:
    """하늘색선:
    이평=MA(C,가중,41기간); HH=Highest(이평,41-1); LL=Lowest(이평,41-1);
    ValueWhen(1,HH>HH(1),HH)
    → 이평(41기간 가중이동평균)의 40봉 최고값(HH)이 직전봉보다 갱신될 때만 값을 업데이트하고,
      갱신이 없으면 마지막으로 갱신됐던 값을 그대로 유지(계단식 우상향 라인).
    ※ 원 수식의 '이평=ma(C,지수,가중)'에는 기간(정수) 인자가 빠져 있어, 바로 아래 Highest/Lowest에
      쓰인 창 크기(41-1=40)와 맞춰 41기간 가중이동평균으로 가정해 구현했습니다.
    """
    close = full_df["close"]
    ma = _wma(close, ma_period)
    hh = ma.rolling(hh_window).max()
    cond = hh > hh.shift(1)
    line = hh.where(cond)
    return line.ffill()


def compute_kiwoom_line_orange_ssch0(full_df: pd.DataFrame, n: int = 52, hh_window: int = 80) -> pd.Series:
    """주황색선 (Hull Moving Average 방식):
    A=WMA(2*WMA(종가,52/2,가중) - WMA(종가,52,가중), Sqrt(52), 가중);
    sscH0=Highest(A,80)
    → A는 정확히 Hull Moving Average(52) 공식이며, sscH0은 A의 80봉 롤링 최고값(계단식으로
      오르내림, ValueWhen 없이 단순 최고값)."""
    close = full_df["close"]
    half = max(int(n / 2), 1)
    sqrt_n = max(int(round(np.sqrt(n))), 1)

    wma_half = _wma(close, half)
    wma_full = _wma(close, n)
    raw_hma = 2 * wma_half - wma_full
    hma = _wma(raw_hma, sqrt_n)

    return hma.rolling(hh_window).max()


def _tema(series: pd.Series, n: int) -> pd.Series:
    """TEMA(삼중지수이동평균) = 3*EMA1 - 3*EMA2 + EMA3."""
    e1 = series.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    """CCI(N) = (전형가 - 전형가 N일 SMA) / (0.015 * N일 평균절대편차)."""
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(n).mean()
    mean_dev = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma_tp) / (0.015 * mean_dev)


def _parabolic_sar(high: pd.Series, low: pd.Series, close: pd.Series,
                    af_start: float = 0.02, af_max: float = 0.2, af_step: float = 0.02) -> pd.Series:
    """Wilder's Parabolic SAR(가·감속값 af_start, 최대 af_max, 증분 af_step)."""
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    n = len(c)
    sar = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=close.index)

    uptrend = c[1] >= c[0]
    trend = 1 if uptrend else -1
    if uptrend:
        sar[1] = l[0]
        ep = h[1]
    else:
        sar[1] = h[0]
        ep = l[1]
    af = af_start

    for i in range(2, n):
        prev_sar = sar[i - 1]
        if trend == 1:
            new_sar = prev_sar + af * (ep - prev_sar)
            new_sar = min(new_sar, l[i - 1], l[i - 2])
            if l[i] < new_sar:
                trend = -1
                sar[i] = ep
                ep = l[i]
                af = af_start
            else:
                sar[i] = new_sar
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_step, af_max)
        else:
            new_sar = prev_sar + af * (ep - prev_sar)
            new_sar = max(new_sar, h[i - 1], h[i - 2])
            if h[i] > new_sar:
                trend = 1
                sar[i] = ep
                ep = h[i]
                af = af_start
            else:
                sar[i] = new_sar
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_step, af_max)

    return pd.Series(sar, index=close.index)


def compute_kiwoom_line_composite_signal(full_df: pd.DataFrame) -> pd.Series:
    """굵은 벽돌색선(#CC3300): 7개 보조지표의 방향(±1)을 합산한 합성 오실레이터가
    -5선을 상향 돌파한 시점의 종가를 유지하는 계단식 라인.
    B1=MACD(12,26)>Signal(9); B2=C>SMA(20); B3=12일 등락률>0; B4=EMA3(스토캐스틱%K(5))>50;
    B5=CCI(20)>0; B6=C>SAR(0.02,0.2); B7=차이킨오실레이터(3,10 EMA of A/D)>0
    A=ΣB; s=EMA9(A); ValueWhen(1, CrossUp(s,-5), C)"""
    close = full_df["close"]
    high = full_df["high"]
    low = full_df["low"]
    volume = full_df["volume"]
    idx = close.index

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    B1 = pd.Series(np.where(macd > macd_signal, 1, -1), index=idx)

    sma20 = close.rolling(20).mean()
    B2 = pd.Series(np.where(close > sma20, 1, -1), index=idx)

    roc12 = (close - close.shift(12)) / close.shift(12) * 100
    B3 = pd.Series(np.where(roc12 > 0, 1, -1), index=idx)

    ll5 = low.rolling(5).min()
    hh5 = high.rolling(5).max()
    fast_k = (close - ll5) / (hh5 - ll5) * 100
    fast_k = fast_k.replace([np.inf, -np.inf], np.nan)
    b4_raw = fast_k.ewm(span=3, adjust=False).mean()
    B4 = pd.Series(np.where(b4_raw > 50, 1, -1), index=idx)

    cci20 = _cci(high, low, close, 20)
    B5 = pd.Series(np.where(cci20 > 0, 1, -1), index=idx)

    sar = _parabolic_sar(high, low, close, 0.02, 0.2, 0.02)
    B6 = pd.Series(np.where(close > sar, 1, -1), index=idx)

    hl_range = (high - low).replace(0, np.nan)
    mfv = ((close - low) - (high - close)) / hl_range * volume
    mfv = mfv.fillna(0.0)
    adl = mfv.cumsum()
    chaikin_osc = adl.ewm(span=3, adjust=False).mean() - adl.ewm(span=10, adjust=False).mean()
    B7 = pd.Series(np.where(chaikin_osc > 0, 1, -1), index=idx)

    A = B1 + B2 + B3 + B4 + B5 + B6 + B7
    s = A.astype(float).ewm(span=9, adjust=False).mean()

    cond = (s > -5) & (s.shift(1) <= -5)
    val = close.where(cond)
    return val.ffill()


def compute_kiwoom_line_tema_center(full_df: pd.DataFrame, n: int = 20) -> pd.Series:
    """벽돌색 보조선: 중심선=TEMA(종가,20). (상단선=TEMA(종가,5)-중심선=이격값은 최종 출력값이
    아니므로 계산에서 제외하고, 수식이 반환하는 '중심선'만 라인으로 표시합니다.)"""
    return _tema(full_df["close"], n)


def _trix(series: pd.Series, n: int = 12) -> pd.Series:
    """TRIX(N): 3중 지수이동평균의 전일 대비 변화율(%)."""
    e1 = series.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return (e3 - e3.shift(1)) / e3.shift(1) * 100


def _highest_since(cond: pd.Series, value: pd.Series) -> pd.Series:
    """키움 HighestSince(1,cond,value): cond가 True였던 가장 최근 시점부터 지금까지의 value 최고값.
    cond가 True인 봉마다 구간이 새로 시작되어 그 봉의 값부터 다시 누적 최고값을 쌓는다."""
    grp = cond.cumsum()
    return value.groupby(grp).cummax()


def compute_kiwoom_line_purple_highestsince(full_df: pd.DataFrame, n: int = 12) -> pd.Series:
    """보라색선: HighestSince(1, CrossUp(TRIX(12),0), High)
    → TRIX(12)가 0선을 상향 돌파한 시점부터 현재까지의 고가(H) 중 최고값을 유지하다가,
      다시 상향 돌파가 나오면 그 시점의 고가부터 새로 리셋되어 계단식으로 누적된다."""
    close = full_df["close"]
    high = full_df["high"]
    trix12 = _trix(close, n)
    cond = (trix12 > 0) & (trix12.shift(1) <= 0)
    return _highest_since(cond, high)


def compute_line_trix_highestsince_close(full_df: pd.DataFrame, n: int = 27) -> pd.Series:
    """검정굵은선(#000000)+핑크선(#FF00FF) 겹선: HighestSince(1, CrossUp(Trix(27),0), avg(C,1))
    → TRIX(27)가 0선을 상향 돌파한 시점부터 현재까지의 종가(C) 중 최고값을 유지하다가,
      다시 상향 돌파가 나오면 그 시점의 종가부터 새로 리셋되어 계단식으로 누적된다."""
    close = full_df["close"]
    trix = _trix(close, n)
    cond = (trix > 0) & (trix.shift(1) <= 0)
    return _highest_since(cond, close)


def compute_line_trix45_highestsince_avgc105(full_df: pd.DataFrame, n: int = 45, avg_n: int = 105) -> pd.Series:
    """핑크굵은선(#FF00FF)+검정선(#000000) 겹선: HighestSince(1, CrossUp(Trix(45),0), avg(C,105))
    → TRIX(45)가 0선을 상향 돌파한 시점부터 현재까지의 종가 105봉 단순이동평균(avg(C,105)) 중
      최고값을 유지하다가, 다시 상향 돌파가 나오면 그 시점의 avg(C,105) 값부터 새로 리셋되어
      계단식으로 누적된다."""
    close = full_df["close"]
    avg_c105 = close.rolling(avg_n).mean()
    trix = _trix(close, n)
    cond = (trix > 0) & (trix.shift(1) <= 0)
    return _highest_since(cond, avg_c105)


def compute_line_valuewhen_crossup_daeseon(full_df: pd.DataFrame) -> pd.Series:
    """핑크선(#FE53FE): a=avg(C,5); b=avg(C,20); d=avg(C,60);
    대선=ValueWhen(1, a>b && b>d && a>d, C);
    시세=ValueWhen(1, 대선(2)<대선(1) && 대선(1)>대선, 대선(1));
    결과=ValueWhen(1, CrossUp(a,시세), a)
    → 5/20/60일선이 정배열(a>b>d)일 때의 종가로 '대선'을 계단식 갱신하고, '대선'이 직전 봉보다
      상승하다가 꺾이는(고점을 찍는) 시점의 '대선(1)'값을 '시세'로 계단식 유지한 뒤,
      단기이평(a)이 그 '시세'를 상향 돌파하는 시점의 a값으로 최종 라인을 계단식 갱신한다."""
    close = full_df["close"]
    a = close.rolling(5).mean()
    b = close.rolling(20).mean()
    d = close.rolling(60).mean()

    cond1 = (a > b) & (b > d) & (a > d)
    daeseon = close.where(cond1).ffill()

    cond2 = (daeseon.shift(2) < daeseon.shift(1)) & (daeseon.shift(1) > daeseon)
    siese = daeseon.shift(1).where(cond2).ffill()

    cond3 = _crossup(a, siese)
    return a.where(cond3).ffill()


def _value_when(cond: pd.Series, value: pd.Series, n: int = 1) -> pd.Series:
    """키움 ValueWhen(N,cond,value): cond가 True였던 시점들 중 가장 최근으로부터 N번째(N=1이면
    가장 최근) 시점의 value 값을 그 다음 True 시점이 나올 때까지 계단식으로 유지한다."""
    true_vals = value.where(cond)
    occurrences = true_vals.dropna()
    shifted = occurrences.shift(n - 1)
    return shifted.reindex(value.index).ffill()


def compute_line_cl_highest60_lowest60(full_df: pd.DataFrame) -> pd.Series:
    """굵은선: CL=ValueWhen(1, Highest(H(1),60)<Highest(H,60), (Highest(H,400)+Lowest(L,60))/2);
    결과=Highest(H,60)-(((Highest(H,60)-CL)/5)*10)
    → 60봉 신고가 갱신 시점의 (400봉 최고가+60봉 최저가)/2 값을 CL로 유지하다가, 다음 신고가
      갱신 때 CL을 새 값으로 교체하는 계단식 지지선."""
    high = full_df["high"]
    low = full_df["low"]
    hh60 = high.rolling(60).max()
    hh400 = high.rolling(400).max()
    ll60 = low.rolling(60).min()

    cond = hh60 > hh60.shift(1)
    mid = (hh400 + ll60) / 2
    cl = mid.where(cond).ffill()

    return hh60 - ((hh60 - cl) / 5) * 10


def compute_line_valuewhen6_localbottom_open(full_df: pd.DataFrame) -> pd.Series:
    """A=C>C(1) && C>C(2) && C>C(3) && C>C(4);
    B=C(1)<C(2) && C(1)<C(3) && C(1)<C(4) && C(1)<C(5);
    K=O>=C(1);
    결과=ValueWhen(6, A&&B&&K, 종가)
    → 현재 종가가 직전 4개 종가보다 모두 높고, 직전(1봉전) 종가가 그 앞 4개 종가보다 모두 낮으며
      (직전 봉이 국소 저점), 오늘 시가가 전일 종가 이상인 조건을 만족한 시점들 중 6번째로
      최근인 시점의 종가를 계단식으로 유지한다."""
    close = full_df["close"]
    open_ = full_df["open"]

    condA = (close > close.shift(1)) & (close > close.shift(2)) & (close > close.shift(3)) & (close > close.shift(4))
    condB = (close.shift(1) < close.shift(2)) & (close.shift(1) < close.shift(3)) & \
            (close.shift(1) < close.shift(4)) & (close.shift(1) < close.shift(5))
    condK = open_ >= close.shift(1)
    cond = condA & condB & condK

    return _value_when(cond, close, n=6)


def compute_line_cci_crossdown_highest_low120(full_df: pd.DataFrame) -> pd.Series:
    """파란선(#3333FF): HighestSince(1, CrossDown(CCI(9),0), Highest(L,120))
    → CCI(9)가 0선을 하향 돌파한 시점부터 현재까지의 (120봉 최고 저가) 중 최고값을 유지하다가,
      다시 하향 돌파가 나오면 그 시점부터 새로 리셋되어 계단식으로 누적된다."""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]
    cci9 = _cci(high, low, close, 9)
    cond = _crossdown(cci9, pd.Series(0.0, index=cci9.index))
    value = low.rolling(120).max()
    return _highest_since(cond, value)


def compute_line_cl120_symmetric_support(full_df: pd.DataFrame, window: int = 120, mult: float = 10) -> pd.Series:
    """진한파랑선(맨뒤): CL=ValueWhen(1, Highest(H(1),120)<Highest(H,120), (Highest(H,120)+Lowest(L,120))/2);
    결과=Highest(H,120)-(((Highest(H,120)-CL)/5)*10)
    → 120봉 신고가 갱신 시점의 (120봉 최고+120봉 최저)/2 값을 CL로 유지하다가, 다음 신고가
      갱신 때 CL을 새 값으로 교체하는 계단식 지지선."""
    high = full_df["high"]
    low = full_df["low"]
    hh = high.rolling(window).max()
    ll = low.rolling(window).min()

    cond = hh > hh.shift(1)
    mid = (hh + ll) / 2
    cl = mid.where(cond).ffill()

    return hh - ((hh - cl) / 5) * mult


def compute_line_cl_asymmetric_support(full_df: pd.DataFrame, hh_window: int = 60,
                                        hh_ref_window: int = 400, ll_window: int = 60,
                                        mult: float = 10) -> pd.Series:
    """연노랑선(맨뒤): CL=ValueWhen(1,(Highest(H(1),60)<Highest(H,60)),
    ((Highest(H,400)+Lowest(L,60))/2)); 결과=Highest(H,60)-(((Highest(H,60)-CL)/5)*10)
    → CL120 지지선과 같은 구조이나, CL 중간값을 구할 때 고점은 400봉, 저점은 60봉으로
      서로 다른 기간(비대칭)을 사용한다."""
    high = full_df["high"]
    low = full_df["low"]
    hh60 = high.rolling(hh_window).max()
    hh400 = high.rolling(hh_ref_window).max()
    ll60 = low.rolling(ll_window).min()

    cond = hh60 > hh60.shift(1)
    mid = (hh400 + ll60) / 2
    cl = mid.where(cond).ffill()

    return hh60 - ((hh60 - cl) / 5) * mult


def compute_line_valuewhen_ma220_rising(full_df: pd.DataFrame, n: int = 220) -> pd.Series:
    """자주색+흰색 겹선: ValueWhen(1, avg(C,220)>avg(C,220,1), avg(C,220))
    → 220일 이동평균이 직전 봉보다 상승 중일 때의 220일 이동평균값을 계단식으로 유지한다."""
    close = full_df["close"]
    ma220 = close.rolling(n).mean()
    cond = ma220 > ma220.shift(1)
    return ma220.where(cond).ffill()


def compute_line_valuewhen_ma_falling(full_df: pd.DataFrame, n: int = 155) -> pd.Series:
    """연두형광+파랑 겹선: ValueWhen(1, avg(C,155)<avg(C,155,1), avg(C,155))
    → 155일 이동평균이 직전 봉보다 하락 중일 때의 155일 이동평균값을 계단식으로 유지한다."""
    close = full_df["close"]
    ma_n = close.rolling(n).mean()
    cond = ma_n < ma_n.shift(1)
    return ma_n.where(cond).ffill()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    """ATR(N): True Range의 N봉 단순이동평균. TR=max(H-L, |H-C(1)|, |L-C(1)|)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def compute_line_dn8_upt(full_df: pd.DataFrame, atr_n: int = 60, hh_window: int = 200) -> pd.Series:
    """연두색선: B=(H+L)/2; dn8=B-ATR(60)+1; upT=ValueWhen(1, Highest(dn8(1),200)<dn8, dn8)
    → dn8 값이 직전까지의 200봉 최고 dn8보다 더 높은 신고점을 찍을 때마다 그 시점의 dn8 값으로
      계단식 갱신되는 상승 지지선."""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]

    b = (high + low) / 2
    dn8 = b - _atr(high, low, close, atr_n) + 1

    hh200_prev = dn8.rolling(hh_window).max().shift(1)
    cond = hh200_prev < dn8

    return dn8.where(cond).ffill()


def compute_line_targetline_cl_mixed(full_df: pd.DataFrame, cond_window: int = 120,
                                      base_window: int = 20, mult: float = 4) -> pd.Series:
    """하늘색굵은선+흰겹선: CL=ValueWhen(1, Highest(H(1),120)<Highest(H,120), (Highest(H,20)+Lowest(L,20))/2);
    TargetLine=Highest(H,20)-(((Highest(H,20)-CL)/5)*4)
    → 120봉 신고가 갱신 시점마다 그 시점의 (20봉 최고+20봉 최저)/2 값을 CL로 계단식 유지하고,
      이를 기준으로 20봉 최고가에서 일정 비율만큼 내려온 목표선을 그린다."""
    high = full_df["high"]
    low = full_df["low"]

    hh_cond = high.rolling(cond_window).max()
    cond = hh_cond > hh_cond.shift(1)

    hh_base = high.rolling(base_window).max()
    ll_base = low.rolling(base_window).min()
    mid = (hh_base + ll_base) / 2
    cl = mid.where(cond).ffill()

    return hh_base - ((hh_base - cl) / 5) * mult


def _bars_since(cond: pd.Series) -> pd.Series:
    """키움 BarsSince(cond): cond가 마지막으로 True였던 시점으로부터 지난 봉 수(True인 봉은 0)."""
    idx = pd.Series(np.arange(len(cond)), index=cond.index, dtype=float)
    true_idx = idx.where(cond.fillna(False))
    last_true_idx = true_idx.ffill()
    return idx - last_true_idx


def compute_line_ac_breakout_cc(full_df: pd.DataFrame) -> pd.Series:
    """핑크+노랑 겹선:
    AC=ValueWhen(1, Highest(V(1),125)<V and Highest(C(1),60)<C, C);
    AV=ValueWhen(1, Highest(V(1),125)<V and Highest(C(1),60)<C, V);
    BB=BarsSince(그 조건);
    CC=Highest(Max(C(1),O(1)),20);
    DD=V<AV*0.5;
    EE=C>=CC*0.95 and C<=CC*1.05;
    결과=ValueWhen(1, BB<20 and DD and EE, CC)
    → 거래량 125봉 신고가 + 종가 60봉 신고가를 동시에 갱신한 시점(대량거래 돌파)의 종가/거래량을
      AC/AV로 계단식 저장해 두었다가, 그 이후 20봉 이내에 거래량이 AV의 절반 밑으로 줄고
      현재가가 (직전 종가/시가 중 큰 값 기준) 20봉 고점(CC) 근처(±5%)에 머무를 때 CC값으로
      계단식 갱신된다(거래 소강 후 재접근 구간 표시)."""
    close = full_df["close"]
    open_ = full_df["open"]
    high_ = full_df["high"]
    volume = full_df["volume"]

    cond_ac = (volume.rolling(125).max().shift(1) < volume) & \
              (close.rolling(60).max().shift(1) < close)

    ac = close.where(cond_ac).ffill()
    av = volume.where(cond_ac).ffill()
    bb = _bars_since(cond_ac)

    base = pd.concat([close.shift(1), open_.shift(1)], axis=1).max(axis=1)
    cc = base.rolling(20).max()

    dd = volume < av * 0.5
    ee = (close >= cc * 0.95) & (close <= cc * 1.05)

    final_cond = (bb < 20) & dd & ee
    return cc.where(final_cond).ffill()


def compute_seryeok_line_hull_highest(full_df: pd.DataFrame, n: int, hh_window: int) -> pd.Series:
    """세력라인(HMA 기반): A=WMA(2*WMA(종가,n/2,가중) - WMA(종가,n,가중), Sqrt(n), 가중);
    sscH0=Highest(A,hh_window). Hull Moving Average(n)의 hh_window봉 롤링 최고값."""
    close = full_df["close"]
    half = max(int(n / 2), 1)
    sqrt_n = max(int(round(np.sqrt(n))), 1)
    wma_half = _wma(close, half)
    wma_full = _wma(close, n)
    raw_hma = 2 * wma_half - wma_full
    hma = _wma(raw_hma, sqrt_n)
    return hma.rolling(hh_window).max()


def compute_line_hilo_mid_shifted(full_df: pd.DataFrame, window: int = 40, shift: int = 159) -> pd.Series:
    """연두노랑선: a=Highest(H,40,159); b=Lowest(L,40,159); m=(a+b)/2.
    ※ Highest/Lowest의 세 번째 인자(159)가 정확히 어떤 의미(과거로 밀어서 표시하는 시프트인지,
    다른 옵션인지)인지 원본 편집기 문법으로는 확인이 안 돼서, '40봉 최고/최저를 구한 뒤
    그 결과를 159봉만큼 과거로 밀어서(shift) 표시'하는 것으로 해석해 구현했습니다.
    다르게 해석해야 한다면 알려주세요."""
    high = full_df["high"]
    low = full_df["low"]
    a = high.rolling(window).max().shift(shift)
    b = low.rolling(window).min().shift(shift)
    return (a + b) / 2


def compute_line_hilo_mid78(full_df: pd.DataFrame) -> pd.Series:
    """검정+파랑 겹선(이평선보다 뒤): (Highest(H,78)+Lowest(L,78))/2"""
    high = full_df["high"]
    low = full_df["low"]
    return (high.rolling(78).max() + low.rolling(78).min()) / 2


def compute_line_trix20_crossup_highestsince_ma20(full_df: pd.DataFrame) -> pd.Series:
    """갈색선(이평선보다 뒤): HighestSince(1, CrossUp(Trix(20),0), avg(C,20))
    → Trix(20)가 0선을 상향 돌파한 마지막 시점부터 지금까지, 20일 이평선(avg(C,20))의
      최고값을 계속 갱신하며 유지."""
    close = full_df["close"]
    trix20 = _trix(close, 20)
    cond = _crossup(trix20, pd.Series(0.0, index=close.index))
    ma20 = close.rolling(20).mean()
    return _highestsince(cond, ma20)


def compute_line_atr400_band_crossflip_open(full_df: pd.DataFrame) -> pd.Series:
    """청록선(다른선들보다 뒤): A=Highest(Lowest(L,400)+ATR(400),87);
    B=Lowest(Highest(H,400)-ATR(400),87); D=(A+B)/2;
    d1=CrossUp(C,D); d2=CrossDown(C,D); E=ValueWhen(1,d1 or d2,O)
    → 종가가 D선을 상/하향 돌파할 때마다 그 시점의 시가로 계단식 갱신되는 라인."""
    high = full_df["high"]
    low = full_df["low"]
    close = full_df["close"]
    open_ = full_df["open"]
    atr400 = _atr(high, low, close, 400)
    A = (low.rolling(400).min() + atr400).rolling(87).max()
    B = (high.rolling(400).max() - atr400).rolling(87).min()
    D = (A + B) / 2
    d1 = _crossup(close, D)
    d2 = _crossdown(close, D)
    cond = d1 | d2
    return _valuewhen(cond, open_)


def compute_line_wavg_open_band(full_df: pd.DataFrame) -> pd.Series:
    """(이평선보다 뒤): avg(wavg(O,240),240) + 2*stdev(wavg(O,240),240)
    → 시가의 240일 가중이동평균(WMA)을 구한 뒤, 그 값의 240일 단순이동평균에
      표준편차*2를 더한 밴드 상단선."""
    open_ = full_df["open"]
    wavg240 = _wma(open_, 240)
    sma_of_wavg = wavg240.rolling(240).mean()
    std_of_wavg = wavg240.rolling(240).std(ddof=0)
    return sma_of_wavg + 2 * std_of_wavg


def compute_line_ma40_typical_stdev_shifted(full_df: pd.DataFrame, n: int = 40, shift: int = 25) -> pd.Series:
    """점선: shift(MA(종가,40,단순) + 2*stdev((C+H+L)/3,40), 25)
    → 종가 40일 단순이동평균에 (고저종 평균가의 40일 표준편차)*2를 더한 값을,
      25봉만큼 과거로 밀어서(shift) 표시."""
    close = full_df["close"]
    high = full_df["high"]
    low = full_df["low"]
    sma_n = close.rolling(n).mean()
    typical = (close + high + low) / 3
    std_n = typical.rolling(n).std(ddof=0)
    return (sma_n + 2 * std_n).shift(shift)


def _tema(series: pd.Series, n: int) -> pd.Series:
    """TEMA(N) = 3*EMA1 - 3*EMA2 + EMA3 (EMA를 3번 겹쳐 지연을 줄인 이동평균)."""
    e1 = _ema(series, n)
    e2 = _ema(e1, n)
    e3 = _ema(e2, n)
    return 3 * e1 - 3 * e2 + e3


def compute_min_line_trix12_highestsince_high(df: pd.DataFrame) -> pd.Series:
    """분차트틀 '신호1' 전용: HighestSince(1, CrossUp(Trix(12),0), High)
    → Trix(12)가 0선을 상향 돌파한 마지막 시점부터 지금까지 고가(High)의 최고값을 유지."""
    close = df["close"]
    trix12 = _trix(close, 12)
    cond = _crossup(trix12, pd.Series(0.0, index=close.index))
    return _highestsince(cond, df["high"])


def compute_min_line_hilo_mid60(df: pd.DataFrame) -> pd.Series:
    """분차트틀 '신호1' 전용: a=Highest(H,60,가중); b=Lowest(L,60,가중); m=(a+b)/2
    ※ 'highest/lowest(...,가중)'의 '가중'이 정확히 어떤 계산을 뜻하는지 알 수 없어(최고/최저
    자체엔 보통 '가중' 방식이 따로 없음), 가중 표시는 무시하고 일반 60봉 최고/최저로 구현했습니다."""
    high = df["high"]
    low = df["low"]
    a = high.rolling(60).max()
    b = low.rolling(60).min()
    return (a + b) / 2


def compute_min_line_trix20_highestsince_ma9(df: pd.DataFrame) -> pd.Series:
    """분차트틀 '신호1' 전용: HighestSince(1, CrossUp(Trix(20),0), avg(C,9))
    → Trix(20)가 0선을 상향 돌파한 마지막 시점부터 지금까지 9봉 이평선의 최고값을 유지."""
    close = df["close"]
    trix20 = _trix(close, 20)
    cond = _crossup(trix20, pd.Series(0.0, index=close.index))
    ma9 = close.rolling(9).mean()
    return _highestsince(cond, ma9)


def compute_min_signal_2060_crossdown(df: pd.DataFrame) -> pd.Series:
    """분차트틀 '신호1' 신호 스트립 '2060'(초록, 역삼각형): A=avg(C,60); B=avg(C,20); CrossDown(A,B)
    → 60봉 이평이 20봉 이평을 하향 돌파(데드크로스)하는 시점."""
    close = df["close"]
    a = close.rolling(60).mean()
    b = close.rolling(20).mean()
    return _crossdown(a, b).fillna(False)


def compute_line_tema200_swing_hold(df: pd.DataFrame) -> pd.Series:
    """분차트틀 '신호1' 전용 라인:
    LT=Lowest(L,5); HT=Highest(H,5);
    NewH=ValueWhen(1,H>HT(1),H); NewL=ValueWhen(1,L<LT(1),L); T=TEMA(C,200);
    Z=(NewL==Low(1) && NewL<Low) or (NewH==High(1) && NewH>High);
    SL=ValueWhen(1,Z,T); ValueWhen(1,SL!=SL(1),TEMA(C,200))
    → 스윙 고/저점이 확정되는 시점(Z)의 TEMA200 값을 SL로 잡고, SL이 바뀔 때마다 그 시점의
      TEMA200 값을 계단식으로 유지하는 라인."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    LT = low.rolling(5).min()
    HT = high.rolling(5).max()
    NewH = _valuewhen(high > HT.shift(1), high)
    NewL = _valuewhen(low < LT.shift(1), low)
    T = _tema(close, 200)
    Z = ((NewL == low.shift(1)) & (NewL < low)) | ((NewH == high.shift(1)) & (NewH > high))
    SL = _valuewhen(Z, T)
    changed = SL.notna() & (SL != SL.shift(1))
    return _valuewhen(changed, T)


# ----------------------------------------------------------------------
# 일봉차트 아래 '신호 스트립' 신호 정의 (차트와 흰네업 신호 동시발생 필터가 같은 정의를 공유한다)
# (이름, 계산함수, 마커모양, 색) - 순서가 곧 차트 아래 세로 레인(1~12) 순서
# ----------------------------------------------------------------------
DAILY_SIGNAL_SPECS = [
    ("120약", compute_isusik_star_signal, "star", "#ffff00"),
    ("120-1", compute_isusik_circle_signal, "circle", "#ffff00"),
    ("세력선덜파", compute_signal_seryeok_deolpa, "triangle-up", "#9933ff"),
    ("상향덜파", compute_signal_sanghyang_deolpa, "triangle-up", "#000000"),
    ("신호업41", compute_signal_sinho_up41, "arrow-up", "#993300"),
    ("매도", compute_signal_maedo, "triangle-down", "#99ccff"),
    ("사번", compute_signal_sabun, "arrow-up", "#cc9900"),
    ("이격도과얄", compute_kiwoom_signal1_disparity, "circle", "#0A29AE"),
    ("매수후보", compute_signal_maesu_hubo, "triangle-up", "#FF0000"),
    ("1020외인초기유입", compute_kiwoom_signal2_ma_volume, "circle", "#99CC00"),
    ("나호흰색", compute_kiwoom_signal3_bbands_envelope, "circle", "#FFFFFF"),
    ("2060", compute_min_signal_2060_crossdown, "triangle-down", "#00FF00"),
]


# 흰네업 신호 동시발생 필터 '전용' 신호: 일봉차트 신호 스트립(레인)에는 넣지 않는다(일봉차트에는 이미 핑크 세로선으로 표시 중).
# '강세' = avg(거래대금,1)>=15000 and C(1)*1.15<=H and L*1.15<=H and O*1.09<=C (compute_kiwoom_signal4_bigmove)
DAILY_FILTER_ONLY_SIGNAL_SPECS = [
    ("강세", compute_kiwoom_signal4_bigmove, "diamond", "#FF80FF"),
]
# 흰네업 팝오버(체크박스)·필터 계산에 쓰는 전체 목록 = 차트 신호 + 필터 전용 신호
DAILY_FILTER_SIGNAL_SPECS = DAILY_SIGNAL_SPECS + DAILY_FILTER_ONLY_SIGNAL_SPECS


def _daily_ohlcv_local_first(code: str, need_end_iso: str) -> pd.DataFrame:
    """신호 동시발생 검색 전용 일봉 로더(로컬 우선).
    내 PC에 저장된 일봉 파일(daily_cache)이 검색 종료일까지 이미 포함하고 있으면 네이버 요청을
    아예 하지 않고 그 파일만 쓴다 (과거 날짜 검색은 사실상 전부 여기서 끝난다).
    로컬 파일이 없거나 종료일을 못 덮는 경우(예: 오늘 날짜 검색)에만 기존 fetch_daily_ohlcv로
    넘어가서 네이버에서 받고 로컬에 저장한다 → 다음 검색부터는 다시 안 받는다.
    (키움은 이 경로에서 전혀 호출하지 않는다.)"""
    try:
        need_end = pd.Timestamp(need_end_iso)
        while need_end.weekday() >= 5:  # 토/일을 종료일로 골랐으면 직전 금요일까지만 있으면 충분
            need_end -= pd.Timedelta(days=1)
        local = _load_daily_local_cache(code)
        if not local.empty and local["date"].max() >= need_end:
            return local
    except Exception:
        pass
    return fetch_daily_ohlcv(code)


@st.cache_data(ttl=300, show_spinner=False)
def cached_daily_multi_signal_dates(code: str, names: tuple, need_end_iso: str) -> tuple:
    """선택한 일봉 신호들이 '같은 날' 모두 동시에 뜬 날짜들(YYYY-MM-DD 문자열 튜플)을 반환.
    need_end_iso(검색 종료일)는 로컬 일봉 파일이 그 날짜까지 덮는지 판단하는 용도다."""
    try:
        full_df = _daily_ohlcv_local_first(code, need_end_iso)
        if full_df is None or full_df.empty:
            return ()
        fn_map = {n: fn for n, fn, _sym, _col in DAILY_FILTER_SIGNAL_SPECS}
        combined = None
        for n in names:
            fn = fn_map.get(n)
            if fn is None:
                return ()
            m = fn(full_df).reindex(full_df.index).fillna(False).astype(bool)
            combined = m if combined is None else (combined & m)
        if combined is None or not combined.any():
            return ()
        return tuple(full_df.loc[combined, "date"].dt.strftime("%Y-%m-%d"))
    except Exception:
        return ()


def _passes_multi_signal_filter(code: str) -> bool:
    """흰네업 팝오버에서 '적용'한 신호 동시발생 필터. 꺼져 있으면 항상 통과. 켜져 있으면 선택한
    날짜(또는 시작~종료 기간) 안의 어느 하루에라도 체크한 신호들이 같은 날 모두 떴던 종목만 통과."""
    cfg = st.session_state.get("multi_signal_filter")
    if not cfg:
        return True
    s, e = cfg["start"], cfg["end"]
    dates = cached_daily_multi_signal_dates(code, tuple(cfg["signals"]), e)
    return any(s <= d <= e for d in dates)


# ----------------------------------------------------------------------
# 휴장일(토/일/공휴일) 판별 - 0~-30 날짜 버튼의 안내 메시지에 사용
# 2026년은 아래 표(공공데이터포털 특일 정보 기준 + 증시 휴장일)를 쓰고, 다른 연도는 'holidays'
# 패키지(pip install holidays)가 설치돼 있으면 그걸로 조회한다. 없으면 토/일만 안내한다.
# ----------------------------------------------------------------------
_KR_HOLIDAY_TABLE = {
    "2026-01-01": "신정", "2026-02-16": "설날 연휴", "2026-02-17": "설날", "2026-02-18": "설날 연휴",
    "2026-03-01": "삼일절", "2026-03-02": "대체공휴일(삼일절)", "2026-05-01": "노동절",
    "2026-05-05": "어린이날", "2026-05-24": "부처님오신날", "2026-05-25": "대체공휴일(부처님오신날)",
    "2026-06-03": "전국동시지방선거", "2026-06-06": "현충일", "2026-07-17": "제헌절",
    "2026-08-15": "광복절", "2026-08-17": "대체공휴일(광복절)",
    "2026-09-24": "추석 연휴", "2026-09-25": "추석", "2026-09-26": "추석 연휴",
    "2026-10-03": "개천절", "2026-10-05": "대체공휴일(개천절)", "2026-10-09": "한글날",
    "2026-12-25": "기독탄신일", "2026-12-31": "연말 휴장일",
}
_KR_HOLIDAY_TABLE_YEARS = {2026}


@st.cache_data(show_spinner=False)
def _kr_holidays_from_package(year: int) -> dict:
    try:
        import holidays as _hol
    except Exception:
        return {}
    try:
        try:
            h = _hol.country_holidays("KR", years=year, language="ko")
        except Exception:
            h = _hol.country_holidays("KR", years=year)
        return {k.isoformat(): str(v) for k, v in h.items()}
    except Exception:
        return {}


def _kr_holiday_name(d: date) -> str:
    """공휴일(또는 증시 휴장일) 이름. 아니면 빈 문자열."""
    if d.year in _KR_HOLIDAY_TABLE_YEARS:
        return _KR_HOLIDAY_TABLE.get(d.isoformat(), "")
    return _kr_holidays_from_package(d.year).get(d.isoformat(), "")


def _day_off_note(d: date) -> str:
    """토요일/일요일/공휴일이면 그 안내 문구(예: '토요일 · 공휴일(추석 연휴)'), 평일이면 빈 문자열."""
    parts = []
    wd = d.weekday()
    if wd == 5:
        parts.append("토요일")
    elif wd == 6:
        parts.append("일요일")
    h = _kr_holiday_name(d)
    if h:
        parts.append(h if h.endswith("휴장일") else f"공휴일({h})")
    return " · ".join(parts)


def _multi_sig_pick_day_cb(n: int):
    """0~-30 날짜 버튼(on_click): 오늘로부터 n일 전 하루를 '특정날짜만'으로 지정하고 바로 적용한다.
    (신호가 하나도 체크 안 돼 있으면 경고만 띄우고 팝오버는 그대로 열려 있다.)"""
    target = date.today() - timedelta(days=n)
    st.session_state["multi_sig_start_date"] = target
    st.session_state["multi_sig_end_date"] = target
    st.session_state["multi_sig_single_only"] = True
    _multi_sig_apply_cb()
    if not st.session_state.get("multi_sig_warn"):
        note = _day_off_note(target)
        if note:
            st.session_state["multi_sig_toast"] = (
                f"{target.strftime('%Y.%m.%d')}({'월화수목금토일'[target.weekday()]})은 {note}입니다. "
                f"장이 열리지 않아 신호가 없을 수 있어요."
            )


def _sync_rank_theme_to_date(iso: str) -> str:
    """흰네업 '적용'(특정 하루) 시 '요'(급등순위)와 '테요'(업종테마) 날짜도 같은 날짜로 맞춘다.
    - 오늘 날짜면 둘 다 실시간으로, 과거 날짜면 그 날짜 저장이 있는 쪽만 그 날짜로 바꾼다.
    - 저장이 없는 쪽은 그대로 두고, 안내 문구(없으면 빈 문자열)를 돌려준다."""
    if iso == date.today().isoformat():
        st.session_state["surge_rank_active_date"] = None
        st.session_state["theme_snapshot_active_date"] = None
        return ""
    missing = []
    if iso in set(_surge_rank_saved_dates()):
        st.session_state["surge_rank_active_date"] = iso
        st.session_state["surge_pick_pick_y"] = int(iso[:4])   # 요 팝오버의 연/월 선택도 같이 맞춤
        st.session_state["surge_pick_pick_m"] = int(iso[5:7])
        st.session_state["surge_pick_msg"] = ""
    else:
        missing.append("요")
    if not _sync_theme_date_from_surge(iso):
        missing.append("테요")
    if missing:
        return f"{iso} 저장이 없어 {'·'.join(missing)} 날짜는 그대로 두었습니다."
    return ""


def _multi_sig_apply_cb():
    """흰네업 팝오버 '적용' 버튼(on_click): 체크한 신호 + 날짜/기간을 필터로 저장하고 팝오버를 닫는다."""
    names = [n for n, _fn, _sym, _col in DAILY_FILTER_SIGNAL_SPECS if st.session_state.get(f"multi_sig_chk_{n}")]
    if not names:
        st.session_state["multi_sig_warn"] = "신호를 1개 이상 체크해주세요."
        return
    s = st.session_state.get("multi_sig_start_date")
    if st.session_state.get("multi_sig_single_only", False):
        e = s  # '특정날짜만' ON: 종료날짜는 무시하고 시작날짜 하루만 본다
    else:
        e = st.session_state.get("multi_sig_end_date")
    if s is None or e is None:
        st.session_state["multi_sig_warn"] = "날짜를 선택해주세요."
        return
    if s > e:
        st.session_state["multi_sig_warn"] = "시작날짜가 종료날짜보다 늦습니다."
        return
    st.session_state["multi_signal_filter"] = {"signals": names, "start": s.isoformat(), "end": e.isoformat()}
    if s == e:
        # 특정 하루를 검색할 때는 그날의 급등순위/업종테마 목록(요/테요)과 맞춰서 검색한다
        _sync_note = _sync_rank_theme_to_date(s.isoformat())
        if _sync_note:
            st.session_state["multi_sig_toast"] = _sync_note
    st.session_state["active_list_filter"] = None  # 기존 필터와 섞여 헷갈리지 않게 끈다
    st.session_state["multi_sig_warn"] = ""
    st.session_state["whitenv_popover_ver"] = st.session_state.get("whitenv_popover_ver", 0) + 1
    st.session_state["whitenv_full_rerun"] = True  # 목록에 필터를 반영하려면 앱 전체를 다시 그려야 한다


def _multi_sig_reset_cb():
    """흰네업 팝오버 '리셋' 버튼(on_click): 신호 동시발생 필터를 끄고 체크박스도 모두 해제."""
    st.session_state.pop("multi_signal_filter", None)
    st.session_state["multi_sig_warn"] = ""
    for n, _fn, _sym, _col in DAILY_FILTER_SIGNAL_SPECS:
        st.session_state[f"multi_sig_chk_{n}"] = False
    st.session_state["active_list_filter"] = None
    st.session_state["whitenv_popover_ver"] = st.session_state.get("whitenv_popover_ver", 0) + 1
    st.session_state["whitenv_full_rerun"] = True


def _fetch_daily_incremental(code: str, local: pd.DataFrame):
    """로컬 일봉에 '새 날짜만' 이어붙이기. 마지막 로컬 날짜 7일 전부터만 네이버에서 받아(짧은 응답),
    겹치는 날짜의 종가가 로컬과 같은지 확인한 뒤 이어붙인다. 로컬이 없거나, 겹치는 날짜가 없거나,
    종가가 다르면(액면분할·배당 등으로 과거 가격이 수정된 경우) 안전하게 전체를 다시 받는다.
    반환: (DataFrame, 방식) - 방식은 'inc'(이어붙임) / 'full'(전체 재다운로드) / 'fail'(실패)."""
    if local.empty:
        df = _fetch_daily_ohlcv_raw(code)
        return df, ("full" if not df.empty else "fail")
    last = local["date"].max()
    start = (last - pd.Timedelta(days=7)).strftime("%Y%m%d")
    tail = _fetch_daily_ohlcv_raw(code, start)
    if tail.empty:
        return pd.DataFrame(), "fail"
    # 마지막 로컬 봉은 장중 미완성일 수 있으니 비교에서 제외하고, 그 이전 겹치는 날짜로 검증
    ov = local[local["date"] < last].merge(tail, on="date", suffixes=("_l", "_n"))
    consistent = (not ov.empty) and bool(((ov["close_l"] - ov["close_n"]).abs() < 0.5).all())
    if not consistent:
        df = _fetch_daily_ohlcv_raw(code)
        return df, ("full" if not df.empty else "fail")
    cols = list(tail.columns)
    keep = local[local["date"] < tail["date"].min()][cols]
    merged = (pd.concat([keep, tail], ignore_index=True)
              .sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True))
    return merged, "inc"


def _latest_expected_daily_bar_date() -> pd.Timestamp:
    """지금 시점에 일봉 파일이 최소한 여기까지는 있어야 '최신'이라고 볼 수 있는 날짜.
    평일 장 마감(15:40) 전이면 직전 평일, 마감 후면 오늘. 주말이면 직전 금요일.
    (공휴일은 모르므로 그런 날은 한 번 더 받을 수 있다 - 해롭지 않음)"""
    now = datetime.now()
    d = pd.Timestamp(now.date())
    if now.hour * 60 + now.minute < 15 * 60 + 40:
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def _run_daily_prefetch(delay_sec: float = 0.3, status_box=None):
    """[흰네업 팝오버 '일봉 받아두기'] 지금 로컬에 저장돼 있는 키움급등순위 + 업종테마 스냅샷에 있는
    종목들의 일봉을 네이버에서 미리 받아 로컬(daily_cache)에 저장해 둔다. 키움은 호출하지 않는다
    (스냅샷/급등순위는 이미 디스크에 있는 데이터만 읽음). 이미 최신 일봉이 로컬에 있는 종목은
    건너뛰므로, 한 번 받아두면 신호 동시발생 검색은 이후 네트워크 없이 로컬 파일만으로 돈다."""
    import time as _time
    if status_box is None:
        status_box = st.empty()

    codes, names = [], {}
    for s in _get_active_surge_rank_data():
        c = s.get("code")
        if c and c not in names:
            codes.append(c); names[c] = s.get("name", "")
    for _grp_cd, _stocks in (_get_active_theme_snapshot().get("stocks", {}) or {}).items():
        for s in _stocks or []:
            c = s.get("stk_cd")
            if c and c not in names:
                codes.append(c); names[c] = s.get("stk_nm", "")

    target = _latest_expected_daily_bar_date()
    downloaded = appended = skipped = failed = 0
    for i, c in enumerate(codes, start=1):
        status_box.caption(f"일봉 받아두기: {i}/{len(codes)} 확인 중 ({names.get(c, '')})")
        local = _load_daily_local_cache(c)
        if not local.empty and local["date"].max() >= target:
            skipped += 1
            continue
        fresh, _mode = _fetch_daily_incremental(c, local)
        if fresh.empty:
            failed += 1
        else:
            _save_daily_local_cache(c, fresh)
            if _mode == "inc":
                appended += 1
            else:
                downloaded += 1
        _time.sleep(delay_sec)
    status_box.empty()
    st.session_state["daily_prefetch_summary"] = {
        "total": len(codes), "downloaded": downloaded, "appended": appended, "skipped": skipped, "failed": failed,
        "ts": datetime.now().strftime("%H:%M:%S"),
    }


@st.fragment
def _render_whitenv_popover():
    """흰네업 팝오버. @st.fragment라서 이 안의 체크박스/날짜/특정날짜만 클릭은 앱 전체를 다시 그리지
    않고 이 팝오버만 다시 그려서 거의 즉시 반응한다. 목록(키움급등순위/업종테마)에 필터를 실제로
    반영해야 하는 '적용'/'리셋'/날짜 버튼은 아래 whitenv_full_rerun 플래그로 전체를 한 번 다시 그린다."""
    if st.session_state.pop("whitenv_full_rerun", False):
        st.rerun()  # scope="app"(기본값): 앱 전체 재실행
    _whitenv_pop_ver = st.session_state.get("whitenv_popover_ver", 0)
    with st.popover(
        "흰네업", key=f"whitenv_popover_v{_whitenv_pop_ver}", use_container_width=True,
        help="일봉차트 아래 신호들을 v 체크하고 날짜(또는 기간)를 고른 뒤 '적용'을 누르면, "
             "그 날짜에 체크한 신호가 같은 날 동시에 뜬 종목만 키움급등순위·업종테마에 표시합니다.",
    ):
        _today_d = date.today()
        _only_on = st.session_state.get("multi_sig_single_only", False)
        st.session_state.setdefault("multi_sig_start_date", _today_d - timedelta(days=2))
        st.session_state.setdefault("multi_sig_end_date", _today_d)
        _sd_col, _ed_col = st.columns(2, gap="small")
        with _sd_col:
            st.date_input("시작날짜", key="multi_sig_start_date", max_value=_today_d, format="YYYY.MM.DD")
        with _ed_col:
            st.date_input("종료날짜", key="multi_sig_end_date", max_value=_today_d, format="YYYY.MM.DD",
                          disabled=_only_on)
        st.checkbox(
            "특정날짜만", key="multi_sig_single_only",
            help="켜면 종료날짜는 무시하고, 시작날짜 그 하루에만 체크한 신호가 동시에 뜬 종목을 찾습니다. "
                 "끄면 시작날짜 ~ 종료날짜 기간 안에서 찾습니다.",
        )
        # ---- 0 ~ -30 날짜 버튼: 누르면 그 날짜(오늘로부터 n일 전) 하루만 바로 찾는다 ----
        _sel_off = (_today_d - st.session_state["multi_sig_start_date"]).days if _only_on else None
        _day_css = [
            ".st-key-multi_sig_single_only label p { color:#31333f !important; font-weight:700 !important; }",
            ".st-key-multi_sig_days { display:flex !important; flex-flow:row wrap !important; gap:4px !important; }",
            ".st-key-multi_sig_days > div { width:calc((100% - 28px)/8) !important; flex:0 0 auto !important; min-width:0 !important; }",
            ".st-key-multi_sig_days button { padding:0.05rem 0 !important; min-height:26px !important; line-height:1 !important; }",
            ".st-key-multi_sig_days button p { font-size:11px !important; }",
        ]
        _day_tips = {}
        for _n in range(31):
            _d = _today_d - timedelta(days=_n)
            _note = _day_off_note(_d)
            _lbl = f"{_d.strftime('%Y.%m.%d')}({'월화수목금토일'[_d.weekday()]})"
            _day_tips[_n] = f"{_lbl} {_note}입니다 - 장이 쉬는 날이에요" if _note else _lbl
            if _note and _n != _sel_off:  # 선택된(빨간 배경) 버튼은 글자색을 건드리지 않는다
                _is_blue = _d.weekday() == 5 and not _kr_holiday_name(_d)
                _day_css.append(
                    f".st-key-multi_sig_day_{_n} button p {{ color:{'#1e6fe0' if _is_blue else '#e53935'} !important; "
                    f"font-weight:800 !important; }}")
        st.markdown("<style>" + "".join(_day_css) + "</style>", unsafe_allow_html=True)
        with st.container(key="multi_sig_days"):
            for _n in range(31):
                st.button("0" if _n == 0 else f"-{_n}", key=f"multi_sig_day_{_n}", use_container_width=True,
                          type="primary" if _n == _sel_off else "secondary",
                          on_click=_multi_sig_pick_day_cb, args=(_n,), help=_day_tips[_n])
        if _only_on:
            _sel_note = _day_off_note(st.session_state["multi_sig_start_date"])
            if _sel_note:
                st.caption(f"⚠ 선택한 날짜는 {_sel_note}입니다 (장이 쉬는 날)")
        st.divider()
        st.caption("신호 선택 (여러 개 체크하면 같은 날 모두 뜬 종목만)")
        # 팝오버 배경이 흰색이라, 각 신호 이름을 차트의 신호 색으로 표시한다(흰색 신호만 검정).
        _pop_sel = '[data-testid="stPopoverBody"]:has(.st-key-multi_sig_apply_btn)'
        _css = [
            f'{_pop_sel} [data-testid="stDateInput"] label, {_pop_sel} [data-testid="stDateInput"] label p, '
            f'{_pop_sel} [data-testid="stCaptionContainer"], {_pop_sel} [data-testid="stCaptionContainer"] p '
            f'{{ color:#31333f !important; }}'
        ]
        for _i, (_sig_nm, _fn, _sym, _col) in enumerate(DAILY_FILTER_SIGNAL_SPECS):
            _txt_col = "#000000" if _col.lower() == "#ffffff" else _col
            _css.append(f'.st-key-multi_sig_row_{_i} label p {{ color:{_txt_col} !important; font-weight:800 !important; }}')
        st.markdown("<style>" + "".join(_css) + "</style>", unsafe_allow_html=True)
        for _i, (_sig_nm, _fn, _sym, _col) in enumerate(DAILY_FILTER_SIGNAL_SPECS):
            with st.container(key=f"multi_sig_row_{_i}"):
                st.checkbox(_sig_nm, key=f"multi_sig_chk_{_sig_nm}")
        _warn_msg = st.session_state.get("multi_sig_warn")
        if _warn_msg:
            st.warning(_warn_msg)
        _apply_col, _reset_col = st.columns(2, gap="small")
        with _apply_col:
            st.button("적용", key="multi_sig_apply_btn", use_container_width=True,
                      type="primary", on_click=_multi_sig_apply_cb)
        with _reset_col:
            st.button(
                "리셋", key="whitenv_filter_reset_btn", use_container_width=True,
                on_click=_multi_sig_reset_cb,
                help="신호 체크와 화면 필터(표시 제한)를 모두 끄고 원래대로 돌립니다. "
                     "이미 관심종목에 체크된 종목은 그대로 남습니다.",
            )
        st.divider()
        if st.button(
            "일봉 받아두기", key="daily_prefetch_btn", use_container_width=True,
            help="지금 저장돼 있는 키움급등순위·업종테마 종목들의 일봉을 미리 내 PC에 저장해 둡니다. "
                 "(키움은 호출하지 않고 네이버에서만 받으며, 이미 최신인 종목은 건너뛰고 새 날짜만 이어붙입니다.) "
                 "한 번 받아두면 신호 동시발생 검색이 네트워크 없이 로컬로만 동작합니다.",
        ):
            st.session_state["whitenv_popover_ver"] = st.session_state.get("whitenv_popover_ver", 0) + 1
            st.session_state["daily_prefetch_pending"] = True
            st.rerun()  # 오래 걸리는 작업은 앱 전체 흐름(진행 표시줄)에서 실행


# ----------------------------------------------------------------------
# '요'/'테요' 팝오버 공용 날짜 선택 UI
#  방법1) 연도 + 월(1~12월) 버튼 + 일(1~31) 버튼 격자  - 저장된 날짜는 초록색으로 표시
#  방법2) 연/월/일 숫자 드롭다운 + '이 날짜 보기' 버튼
# (예전의 '저장된 날짜가 전부 세로로 길게 나열되던 목록'을 대체한다)
# ----------------------------------------------------------------------
def _sync_theme_date_from_surge(iso: str) -> bool:
    """'요'에서 날짜를 고르면 '테요'도 같은 날짜로 맞춘다(과거 같은 날짜를 두 번 고르는 번거로움 제거).
    그 날짜에 테요(업종테마) 저장이 있을 때만 맞추고, 없으면 테요는 그대로 두고 False를 돌려준다."""
    if iso in set(_theme_snapshot_saved_dates()):
        st.session_state["theme_snapshot_active_date"] = iso
        # 테요 팝오버의 연/월 선택도 같이 맞춰서 열었을 때 그 날짜가 바로 보이게 한다
        st.session_state["theme_pick_pick_y"] = int(iso[:4])
        st.session_state["theme_pick_pick_m"] = int(iso[5:7])
        st.session_state["theme_pick_msg"] = ""
        return True
    return False


def _picker_pick_cb(prefix: str, iso: str, active_key: str, is_saved: bool):
    """날짜 버튼(on_click): 저장된 날짜면 그 날짜를 보고, 아니면 안내만 띄운다.
    '요'(surge_pick)에서 고르면 '테요'도 같은 날짜로 함께 맞춘다."""
    if is_saved:
        st.session_state[active_key] = iso
        st.session_state[f"{prefix}_msg"] = ""
        st.session_state[f"{prefix}_full_rerun"] = True  # 양쪽 목록을 새 날짜로 다시 그리려면 전체 재실행이 필요
        if prefix == "surge_pick" and not _sync_theme_date_from_surge(iso):
            st.session_state[f"{prefix}_msg"] = f"테요에는 {iso} 저장이 없어 테요는 그대로 두었습니다."
    else:
        st.session_state[f"{prefix}_msg"] = f"{iso} 은(는) 저장된 데이터가 없습니다 (초록색 날짜만 볼 수 있어요)."


def _picker_set_month_cb(prefix: str, m: int):
    st.session_state[f"{prefix}_pick_m"] = m


def _render_saved_date_picker(prefix: str, saved_dates: list, active_key: str, delete_fn, cache_prefix: str,
                              file_fn=None):
    import calendar
    if st.session_state.pop(f"{prefix}_full_rerun", False):
        st.rerun()

    saved_set = set(saved_dates)
    today = date.today()
    active = st.session_state.get(active_key)
    try:
        base = date.fromisoformat(active) if active else (date.fromisoformat(saved_dates[0]) if saved_dates else today)
    except ValueError:
        base = today
    years = sorted({today.year, base.year} | {int(d[:4]) for d in saved_dates if str(d)[:4].isdigit()})
    ykey, mkey = f"{prefix}_pick_y", f"{prefix}_pick_m"
    if st.session_state.get(ykey) not in years:
        st.session_state[ykey] = base.year if base.year in years else years[-1]
    st.session_state.setdefault(mkey, base.month)

    if not saved_dates:
        st.caption("저장된 과거 날짜가 없습니다. 먼저 받아오기 버튼으로 저장하세요.")

    # ---- 방법 1: 연도 / 월 버튼 / 일 버튼 ----
    st.caption("① 버튼으로 고르기 (초록 = 장중 저장 / 파랑 = 장마감 후 15:30~ 저장)")
    y_col, _sp = st.columns([1, 2], gap="small")
    with y_col:
        sel_year = st.selectbox("연도", years, key=ykey, label_visibility="collapsed")
    sel_month = int(st.session_state[mkey])
    months_with_data = {int(d[5:7]) for d in saved_dates if d[:4] == str(sel_year)}

    css = [
        f".st-key-{prefix}_months, .st-key-{prefix}_days {{ display:flex !important; flex-flow:row wrap !important; gap:4px !important; }}",
        f".st-key-{prefix}_months > div {{ width:calc((100% - 20px)/6) !important; flex:0 0 auto !important; min-width:0 !important; }}",
        f".st-key-{prefix}_days > div {{ width:calc((100% - 28px)/8) !important; flex:0 0 auto !important; min-width:0 !important; }}",
        f".st-key-{prefix}_months button, .st-key-{prefix}_days button {{ padding:0.05rem 0 !important; min-height:26px !important; line-height:1 !important; }}",
        f".st-key-{prefix}_months button p, .st-key-{prefix}_days button p {{ font-size:11px !important; }}",
    ]
    for m in range(1, 13):
        if m == sel_month:
            continue
        col = "#1b7f3b" if m in months_with_data else "#9aa0a8"
        css.append(f"div.st-key-{prefix}_mon_{m} button p {{ color:{col} !important; font-weight:{800 if m in months_with_data else 400} !important; }}")
    ndays = calendar.monthrange(sel_year, sel_month)[1]

    # 저장된 날짜가 '언제 저장됐는지'는 저장 파일의 마지막 수정 시각으로 안다(그날 15:30 이후에 저장됐으면 장마감 후 저장).
    # 이 달에 보이는 날짜만 확인하므로 파일 조회는 최대 31번이다. 다른 날짜에 수정된 파일(예: 백업 복원)은 구분하지 않고 초록.
    saved_hm = {}      # iso -> 'HH:MM'
    post_close = set()  # 장마감 후(15:30~) 저장된 날짜
    if file_fn is not None:
        for d in range(1, ndays + 1):
            iso = f"{sel_year:04d}-{sel_month:02d}-{d:02d}"
            if iso not in saved_set:
                continue
            try:
                ts = datetime.fromtimestamp(os.path.getmtime(file_fn(iso)))
            except OSError:
                continue
            if ts.date().isoformat() != iso:
                continue
            saved_hm[iso] = ts.strftime("%H:%M")
            if (ts.hour, ts.minute) >= (15, 30):
                post_close.add(iso)

    for d in range(1, ndays + 1):
        iso = f"{sel_year:04d}-{sel_month:02d}-{d:02d}"
        if iso == active:
            continue
        if iso in post_close:   # 장마감 후 저장: 파랑
            css.append(f"div.st-key-{prefix}_day_{d} button {{ background:#e3eefc !important; border-color:#3b82f6 !important; }}"
                       f"div.st-key-{prefix}_day_{d} button p {{ color:#1d4ed8 !important; font-weight:800 !important; }}")
        elif iso in saved_set:  # 장중 저장: 초록
            css.append(f"div.st-key-{prefix}_day_{d} button {{ background:#e3f6e8 !important; border-color:#2ecc71 !important; }}"
                       f"div.st-key-{prefix}_day_{d} button p {{ color:#1b7f3b !important; font-weight:800 !important; }}")
        else:
            css.append(f"div.st-key-{prefix}_day_{d} button p {{ color:#9aa0a8 !important; }}")
    st.markdown("<style>" + "".join(css) + "</style>", unsafe_allow_html=True)

    with st.container(key=f"{prefix}_months"):
        for m in range(1, 13):
            st.button(f"{m}월", key=f"{prefix}_mon_{m}", use_container_width=True,
                      type="primary" if m == sel_month else "secondary",
                      on_click=_picker_set_month_cb, args=(prefix, m))
    st.caption(f"{sel_year}년 {sel_month}월")
    with st.container(key=f"{prefix}_days"):
        for d in range(1, ndays + 1):
            iso = f"{sel_year:04d}-{sel_month:02d}-{d:02d}"
            st.button(str(d), key=f"{prefix}_day_{d}", use_container_width=True,
                      type="primary" if iso == active else "secondary",
                      disabled=(date(sel_year, sel_month, d) > today),
                      on_click=_picker_pick_cb, args=(prefix, iso, active_key, iso in saved_set),
                      help=((f"{iso} (저장됨 {saved_hm[iso]}" + (" · 장마감 후)" if iso in post_close else " · 장중)"))
                            if iso in saved_hm else (f"{iso} (저장됨)" if iso in saved_set else f"{iso} (저장 없음)")))
    _msg = st.session_state.get(f"{prefix}_msg")
    if _msg:
        st.caption(f"⚠ {_msg}")

    # ---- 방법 2: 연/월/일 숫자 드롭다운 ----
    st.caption("② 연/월/일 직접 고르기")
    ymd = date_ymd_input("날짜", base, f"{prefix}_ymd", show_label=False)
    iso2 = ymd.isoformat()
    st.button("이 날짜 보기", key=f"{prefix}_ymd_go", use_container_width=True,
              on_click=_picker_pick_cb, args=(prefix, iso2, active_key, iso2 in saved_set),
              help="저장된 날짜만 볼 수 있습니다")

    # ---- 삭제: 지금 보고 있는 날짜의 저장 데이터를 지운다(예전 ✕ 버튼 대체) ----
    if active:
        if st.button(f"🗑 {active} 저장 데이터 삭제", key=f"{prefix}_del_active", use_container_width=True):
            delete_fn(active)
            st.session_state.pop(f"{cache_prefix}{active}", None)
            st.session_state[active_key] = None
            st.rerun()


# ----------------------------------------------------------------------
# 매일 15:31 자동 '업'(키움 급등순위 저장) + 15:40 '테업'(업종테마 저장) + 15:50 '일봉 받아두기'(네이버 일봉 저장)
# - 앱(브라우저 탭)이 열려 있을 때 동작.
# 15:31 이후 처음 열었을 때도 그날 아직 안 했으면 한 번 실행한다(평일·비공휴일만).
# ----------------------------------------------------------------------
AUTO_UP_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_up_state.json")
# 자동 저장은 15:31부터 '업 → 테업 → 일봉 받아두기' 순서로 하나씩 이어서 한다:
# 앞 작업이 끝나고 AUTO_TASK_MIN_GAP_SEC(15초)가 지나면 다음 작업을 시작한다(확인 주기는 5초라 15~20초 뒤).
AUTO_UP_TIME = (15, 31)           # 자동 '업'(급등순위) 시작 시각 = 연쇄의 시작
AUTO_THEME_UP_TIME = AUTO_UP_TIME  # '테업'(업종테마): 업이 끝난 뒤 15초 후 자동으로 이어짐(시작 시각은 업과 같음)
AUTO_THEME_DELAY_SEC = 2.0        # 자동 테업의 키움 요청 사이 간격(초): 30개 테마면 약 1분
AUTO_DAILY_PREFETCH_TIME = AUTO_UP_TIME  # '일봉 받아두기': 테업이 끝난 뒤 15초 후 자동으로 이어짐(마지막)
AUTO_DAILY_PREFETCH_DELAY_SEC = 0.5  # 자동 일봉 받아두기의 네이버 요청 사이 간격(초). 수동 버튼(0.3초)보다 천천히
AUTO_TASK_MIN_GAP_SEC = 15        # 자동 작업(업/테업/일봉 받아두기) 사이 간격(초): 앞 작업이 끝난 뒤 이만큼 지나면 다음 작업
AUTO_SCHEDULER_TICK_SEC = 5       # 자동 저장 시각/순서를 확인하는 주기(초). 15:31 전에는 바로 끝나서 부담이 없다


# 업(급등순위) / 테업(업종테마) / 일봉 받아두기 각각 따로 기록
_AUTO_UP_KEYS = {"surge": "last_date", "theme": "theme_last_date", "daily": "daily_last_date"}


def _auto_up_read_state() -> dict:
    if os.path.exists(AUTO_UP_STATE_FILE):
        try:
            with open(AUTO_UP_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return {}


def _auto_up_last_done(kind: str = "surge") -> str:
    return str(_auto_up_read_state().get(_AUTO_UP_KEYS[kind], ""))


def _auto_up_mark_done(iso: str, kind: str = "surge", src: str = "auto", n=None):
    """오늘 해당 작업을 마쳤다고 기록. 완료 시각(HH:MM)·실행 주체(auto=자동 / manual=수동)·개수도 같이 남겨서
    화면의 '자동 저장 상태' 한 줄에 보여준다."""
    data = _auto_up_read_state()
    key = _AUTO_UP_KEYS[kind]
    data[key] = iso
    data[f"{key}_time"] = datetime.now().strftime("%H:%M")
    data[f"{key}_src"] = src
    if n is not None:
        data[f"{key}_n"] = int(n)
    try:
        with open(AUTO_UP_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def _auto_up_status_html() -> str:
    """'🌐 네이버인기테마' 제목 줄 끝에 붙일 작은 글씨: 오늘 업/테업/일봉 받아두기가 끝났는지 한눈에 보여준다.
    - 오늘 완료: 초록 '업✓15:31' (수동으로 눌러서 끝났으면 '(수동)' 표시)
    - 오늘 아직: 회색 '업 10/20' (마지막으로 끝낸 날짜) / 기록이 없으면 '업 -'
    기록 파일(작은 JSON) 한 번 읽는 것이 전부라 속도에 영향이 없다."""
    state = _auto_up_read_state()
    today = date.today().isoformat()
    parts = []
    for kind, label in (("surge", "업"), ("theme", "테업"), ("daily", "일봉")):
        key = _AUTO_UP_KEYS[kind]
        d = str(state.get(key, ""))
        if d == today:
            t = str(state.get(f"{key}_time", ""))
            manual = "(수동)" if state.get(f"{key}_src") == "manual" else ""
            parts.append(f"<span style='color:#2ecc71'>{label}✓{t}{manual}</span>")
        elif len(d) >= 10:
            parts.append(f"<span style='color:#9aa4b8'>{label} {d[5:7]}/{d[8:10]}</span>")
        else:
            parts.append(f"<span style='color:#9aa4b8'>{label} -</span>")
    return ("<span style='font-size:10px; font-weight:600; margin-left:8px; white-space:nowrap;' "
            "title='장 마감 후 자동 저장 상태: 초록 ✓=오늘 완료, 회색 날짜=마지막으로 끝낸 날'>⏰ "
            + " ".join(parts) + "</span>")


def _do_surge_up_and_save() -> int:
    """'업' 버튼과 똑같은 동작: 키움 급등순위를 받아 오늘 날짜로 로컬에 저장하고 화면 데이터로 설정."""
    data = fetch_kiwoom_surge_rank_raw()
    today_str = date.today().isoformat()
    _save_surge_rank_date(today_str, data)
    st.session_state[f"surge_rank_data_{today_str}"] = data
    st.session_state["surge_rank_data_live"] = data
    st.session_state["surge_rank_active_date"] = None
    return len(data)


def _do_theme_snapshot_and_save() -> int:
    """'테업' 버튼과 똑같은 동작: 업종테마(최대 30개)+구성종목을 받아 오늘 날짜로 로컬에 저장."""
    snap = fetch_kiwoom_theme_snapshot_raw(delay_sec=AUTO_THEME_DELAY_SEC)
    today_str = date.today().isoformat()
    _save_theme_snapshot(today_str, snap)
    st.session_state[f"theme_snapshot_data_{today_str}"] = snap
    st.session_state["theme_snapshot_data_live"] = snap
    st.session_state["theme_snapshot_active_date"] = None
    return len(snap.get("groups", []))


def _do_daily_prefetch_auto() -> int:
    """'일봉 받아두기' 버튼과 똑같은 동작(저장된 급등순위·업종테마 종목의 일봉을 네이버에서 받아 로컬에 저장).
    처리한 종목 수를 돌려주고, 확인한 종목이 있는데 전부 실패했으면(예: 네이버 장애) 예외를 내서 재시도되게 한다."""
    _run_daily_prefetch(delay_sec=AUTO_DAILY_PREFETCH_DELAY_SEC)
    summ = st.session_state.get("daily_prefetch_summary") or {}
    total = int(summ.get("total", 0))
    if total > 0 and int(summ.get("failed", 0)) >= total:
        raise RuntimeError("모든 종목의 일봉을 받지 못했습니다(네이버 응답 없음)")
    return total


@st.fragment(run_every=AUTO_SCHEDULER_TICK_SEC)
def _auto_up_scheduler():
    """5초마다 가볍게 시간만 확인한다(15:31 전에는 바로 끝남).
    15:31 이후 오늘 아직 안 한 작업을 아래 순서로 '하나씩 이어서' 한다:
    ① '업'(급등순위) → 끝나고 15초 뒤 ② '테업'(업종테마) → 끝나고 15초 뒤 ③ '일봉 받아두기'(저장된 종목 일봉을 네이버에서 받음)
    한 번에 하나만 실행하므로 서로 겹치지 않는다. 앞 작업이 끝나야(성공하거나 3번 실패해야) 다음으로 넘어간다.
    각각 실패해도 하루 최대 3번만 시도한다. 15:31 이후에 앱을 늦게 열어도 같은 순서로 이어서 따라잡는다."""
    import time as _time
    now = datetime.now()
    if (now.hour, now.minute) < AUTO_UP_TIME:  # 15:31 전: 휴일 조회·파일 읽기 없이 바로 종료(10초마다 불러도 부담 없음)
        return
    today = now.date()
    if today.weekday() >= 5 or _day_off_note(today):
        return
    iso = today.isoformat()
    tasks = [
        ("surge", "업", _do_surge_up_and_save, "종목", AUTO_UP_TIME),
        ("theme", "테업", _do_theme_snapshot_and_save, "개 테마", AUTO_THEME_UP_TIME),
        ("daily", "일봉 받아두기", _do_daily_prefetch_auto, "종목 확인", AUTO_DAILY_PREFETCH_TIME),
    ]
    for kind, label, fn, unit, start_hm in tasks:
        if (now.hour, now.minute) < start_hm:
            continue
        if _auto_up_last_done(kind) == iso:
            continue
        tries = st.session_state.setdefault(f"_auto_up_tries_{kind}", {})
        if tries.get(iso, 0) >= 3:  # 실패해도 하루 최대 3번만 시도(키움 부담 방지)
            continue
        if _time.time() - st.session_state.get("_auto_up_last_run_ts", 0.0) < AUTO_TASK_MIN_GAP_SEC:
            continue  # 방금 다른 자동 작업을 했으면 간격을 두고 다음 확인 때 실행
        tries[iso] = tries.get(iso, 0) + 1
        st.session_state["_auto_up_last_run_ts"] = _time.time()
        cnt, err = None, None
        try:
            _src_txt = "네이버에서 천천히 받는 중" if kind == "daily" else "키움에 천천히 요청하는 중"
            with st.spinner(f"자동 {label} 실행 중... ({_src_txt})"):
                cnt = fn()
            _auto_up_mark_done(iso, kind, "auto", cnt)
        except Exception as e:
            err = str(e)
        st.session_state["_auto_up_last_run_ts"] = _time.time()  # 끝난 시각부터 간격 계산
        if cnt is not None:
            st.session_state["multi_sig_toast"] = f"⏰ 자동 {label} 완료: {cnt}{unit} 저장"
            st.rerun()
        st.toast(f"자동 {label} 실패({tries[iso]}/3): {err}", icon="⚠️")
        break  # 한 번에 하나만


POPOVER_NARROW_WIDTH_PX = 340  # 흰네업/요/테요 팝오버 가로폭(px). 더 줄이거나 늘리려면 이 숫자만 바꾸면 된다.


def _cloud_cross_time_in_session(t0, t1, frac: float, open_t, close_t):
    """rangebreaks(장 마감~다음날 장 시작 건너뛰기)가 있는 분봉차트용: 두 봉 사이 교차 지점의
    x 시각을 '화면에 실제로 보이는(장중) 시간' 기준으로 보간한다. 단순 시간 보간을 하면 교차
    지점이 숨겨진 시간대(장 마감 후~장 시작 전)에 떨어져서 plotly가 그 점을 지워버리고,
    그러면 색칠 도형이 깨진다."""
    t0 = pd.Timestamp(t0)
    t1 = pd.Timestamp(t1)
    if t0.date() == t1.date():
        return t0 + (t1 - t0) * frac
    close0 = pd.Timestamp(datetime.combine(t0.date(), close_t))
    open1 = pd.Timestamp(datetime.combine(t1.date(), open_t))
    rem0 = max((close0 - t0).total_seconds(), 0.0)
    part1 = max((t1 - open1).total_seconds(), 0.0)
    total = rem0 + part1
    if total <= 0:
        return t0
    d = frac * total
    if d < rem0:
        return t0 + pd.Timedelta(seconds=d)
    return open1 + pd.Timedelta(seconds=d - rem0)


def build_ma_cloud_segments(dates: pd.Series, ma_a: pd.Series, ma_b: pd.Series, session=None):
    """두 이평선(a=단기, b=장기) 사이 구름대 채우기용 데이터 생성.
    두 선이 교차하는 지점은 보간해서 점을 추가하고, b>=a 구간(장기선이 위)과
    a>=b 구간(단기선이 위)을 각각 NaN으로 끊어서 반환한다.
    반환: (x, lower_b, upper_b, lower_a, upper_a)  ※ *_b: b가 위, *_a: a가 위 구간"""
    d = pd.DataFrame({"x": pd.to_datetime(dates).values, "a": ma_a.values, "b": ma_b.values}).dropna()
    xs, av, bv = [], [], []
    rows = d.values.tolist()
    for i, (x, a, b) in enumerate(rows):
        if i > 0:
            px, pa, pb = rows[i - 1]
            pd_ = pa - pb
            cd_ = a - b
            if pd_ * cd_ < 0:
                t = pd_ / (pd_ - cd_)
                if session is not None:
                    cx = _cloud_cross_time_in_session(px, x, t, session[0], session[1])
                else:
                    cx = pd.Timestamp(px) + (pd.Timestamp(x) - pd.Timestamp(px)) * t
                cx = pd.Timestamp(cx).floor("s")  # 나노초 단위 제거(plotly 경고 방지)
                cy = pa + (a - pa) * t
                xs.append(cx); av.append(cy); bv.append(cy)
        xs.append(pd.Timestamp(x)); av.append(a); bv.append(b)
    xs = pd.Series(xs)
    av = np.array(av, dtype=float)
    bv = np.array(bv, dtype=float)
    b_up = bv >= av
    a_up = av >= bv
    nan = np.nan
    lower_b = np.where(b_up, av, nan)
    upper_b = np.where(b_up, bv, nan)
    lower_a = np.where(a_up, bv, nan)
    upper_a = np.where(a_up, av, nan)
    return xs, lower_b, upper_b, lower_a, upper_a


def build_ma_cloud_polygons(xs, lower, upper):
    """구름대를 '구간별 닫힌 도형'으로 만든다. lower/upper에서 NaN이 아닌 연속 구간마다
    (위 경계 왼→오른쪽 + 아래 경계 오른→왼쪽)로 도형을 만들고, 구간 사이는 None으로 끊는다.
    plotly fill='toself' 는 끊긴 구간을 각각 따로 칠하므로, fill='tonexty'가 끊긴 구간을 서로
    이어 붙여서 엉뚱한 곳이 칠해지는 문제가 없다."""
    xs = list(xs)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    ok = ~(np.isnan(lower) | np.isnan(upper))
    px, py = [], []
    n = len(xs)
    i = 0
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        seg_x = xs[i:j + 1]
        px += seg_x + seg_x[::-1] + [None]
        py += list(upper[i:j + 1]) + list(lower[i:j + 1])[::-1] + [None]
        i = j + 1
    return px, py


def compute_line_bbands_up(full_df: pd.DataFrame, n: int = 300, mult: float = 2) -> pd.Series:
    """빨간선: BBandsUp(300,2) = avg(C,300) + 2*stdev(C,300)"""
    close = full_df["close"]
    return close.rolling(n).mean() + mult * close.rolling(n).std(ddof=0)


def _ema(series: pd.Series, n: int) -> pd.Series:
    """EMA(N): 키움 eavg(데이터,N) - N기간 지수이동평균."""
    return series.ewm(span=n, adjust=False).mean()


def _hma(series: pd.Series, n: int) -> pd.Series:
    """Hull Moving Average(N): WMA(2*WMA(data,n/2,가중) - WMA(data,n,가중), Sqrt(n), 가중)."""
    half = max(int(n / 2), 1)
    sqrt_n = max(int(round(np.sqrt(n))), 1)
    wma_half = _wma(series, half)
    wma_full = _wma(series, n)
    raw_hma = 2 * wma_half - wma_full
    return _wma(raw_hma, sqrt_n)


def compute_line_hma_low120_crossdown_ema50(full_df: pd.DataFrame) -> pd.Series:
    """검정굵은선+파랑겹선: A=WMA(2*WMA(저가,60,가중)-WMA(저가,120,가중),Sqrt(120),가중);
    B=EMA(C,50); 결과=ValueWhen(1, CrossDown(A,B), A)
    → 저가 기준 HMA(120)이 종가 EMA(50)를 하향 돌파하는 시점의 HMA(120) 값으로 계단식 갱신된다."""
    low = full_df["low"]
    close = full_df["close"]
    a = _hma(low, 120)
    b = _ema(close, 50)
    cond = _crossdown(a, b)
    return a.where(cond).ffill()


def compute_seryeok_line_trix_step(full_df: pd.DataFrame, n: int = 20) -> pd.Series:
    """세력라인(Trix 계단선): sscH1=HighestSince(1, CrossUp(Trix(20),0), avg(C,1))
    → TRIX(20)이 0선을 상향 돌파한 시점부터 현재까지의 종가 중 최고값을 계단식으로 유지."""
    close = full_df["close"]
    trix20 = _trix(close, n)
    cond = (trix20 > 0) & (trix20.shift(1) <= 0)
    return _highest_since(cond, close)


def compute_kiwoom_line_cyan2_support(full_df: pd.DataFrame, window: int = 100) -> pd.Series:
    """하늘색선2(#00ccff): 100봉 신고가 갱신 시점의 (100봉 최고+최저)/2 값을 gb로 유지하다가,
    다음 신고가 갱신 때 gb를 새 값으로 교체하는 계단식 지지선.
    gb = ValueWhen(1, Highest(H(1),100)<Highest(H,100), (Highest(High,100)+Lowest(Low,100))/2)
    최종 = Highest(H,100) - ((Highest(H,100)-gb)/5)*8"""
    high = full_df["high"]
    low = full_df["low"]
    hh100 = high.rolling(window).max()
    ll100 = low.rolling(window).min()

    cond = hh100 > hh100.shift(1)
    mid = (hh100 + ll100) / 2
    gb = mid.where(cond).ffill()

    return hh100 - ((hh100 - gb) / 5) * 8


def _highest_range(series: pd.Series, n1: int, n2: int) -> pd.Series:
    """키움 Highest(자료, N1, N2): N1봉 전부터 N2봉 전까지 범위(폭 N2-N1+1)의 최고값."""
    window = n2 - n1 + 1
    return series.rolling(window).max().shift(n1)


def _lowest_range(series: pd.Series, n1: int, n2: int) -> pd.Series:
    """키움 Lowest(자료, N1, N2): N1봉 전부터 N2봉 전까지 범위(폭 N2-N1+1)의 최저값."""
    window = n2 - n1 + 1
    return series.rolling(window).min().shift(n1)


def compute_kiwoom_line_cyan3_channel_mid(full_df: pd.DataFrame, n1: int = 25, n2: int = 80) -> pd.Series:
    """하늘색선3(#00ffff): a=Highest(H,25,80); b=Lowest(L,25,80); m=(a+b)/2
    → 25~80봉 전 구간(폭 56봉)의 최고/최저 중간값. 최근 24봉은 창에서 제외되어 지연(lag)된
      채널 중심선이 되며, 창이 넓고 뒤로 밀려 있어 넓은 평평한 구간(계단식 plateau)이 나타난다."""
    high = full_df["high"]
    low = full_df["low"]
    a = _highest_range(high, n1, n2)
    b = _lowest_range(low, n1, n2)
    return (a + b) / 2


def compute_line_hilo120_mid(full_df: pd.DataFrame, window: int = 120) -> pd.Series:
    """핑크선(#FF00FF): a=Highest(H,120,가중); b=Lowest(L,120,가중); m=(a+b)/2
    → 120봉 구간의 최고가/최저가 중간값. (최고/최저에는 가중 방식이 결과에 영향을 주지 않으므로
      단순 롤링 최고/최저로 계산)"""
    high = full_df["high"]
    low = full_df["low"]
    a = high.rolling(window).max()
    b = low.rolling(window).min()
    return (a + b) / 2


def compute_line_hilo60_mid(full_df: pd.DataFrame, window: int = 60) -> pd.Series:
    """연핑크선(#FF99CC): a=Highest(H,60,가중); b=Lowest(L,60,가중); m=(a+b)/2
    → 60봉 구간의 최고가/최저가 중간값. (최고/최저에는 가중 방식이 결과에 영향을 주지 않으므로
      단순 롤링 최고/최저로 계산)"""
    high = full_df["high"]
    low = full_df["low"]
    a = high.rolling(window).max()
    b = low.rolling(window).min()
    return (a + b) / 2


def compute_line_disparity120_valuewhen(full_df: pd.DataFrame, n: int = 120, level: float = 101) -> pd.Series:
    """벽돌색선(#CC3300): A=Disparity(120); D=ValueWhen(1, CrossUp(A,101) OR CrossDown(A,101), (H+L)/2)
    → 이격도(120)가 101을 상향/하향 돌파할 때마다 그 시점의 (고가+저가)/2 값으로 계단식 갱신."""
    close = full_df["close"]
    high = full_df["high"]
    low = full_df["low"]
    disparity = close / close.rolling(n).mean() * 100
    cond = _crossup(disparity, pd.Series(level, index=disparity.index)) | \
           _crossdown(disparity, pd.Series(level, index=disparity.index))
    mid_hl = (high + low) / 2
    return mid_hl.where(cond).ffill()


def compute_kiwoom_line_white_bigvol_vwap(full_df: pd.DataFrame, ma_period: int = 20,
                                           mult: float = 1.5, window: int = 240) -> pd.Series:
    """흰색선(가장 굵음): 거래량이 20일평균×1.5배를 넘는 '대량거래일'만 골라, 그 날들의
    종가×거래량 합을 거래량 합으로 나눈 240봉 롤링 평균단가(대량거래일 기준 VWAP).
    A=SUM(IF(V>MA(V,20)*1.5, C*V, 0), 240); B=SUM(IF(V>MA(V,20)*1.5, V, 0), 240); A/B"""
    close = full_df["close"]
    volume = full_df["volume"]

    ma_v20 = volume.rolling(ma_period).mean()
    cond = volume > ma_v20 * mult

    cv = (close * volume).where(cond, 0.0)
    v_only = volume.where(cond, 0.0)

    A = cv.rolling(window).sum()
    B = v_only.rolling(window).sum()

    return A / B.replace(0, np.nan)


# ----------------------------------------------------------------------
# 종목별 실시간 뉴스 속보 (1줄 표시용)
# - 1차: 네이버증권(stock.naver.com)의 공개 JSON API (/api/domestic/detail/news).
#   네이버 웹/모바일 화면이 실제로 사용하는 비공식 API로, 페이지 구조가 바뀌어도
#   잘 깨지지 않고 HTML 파싱보다 안정적이다. (공식 지원 API는 아님)
# - 2차(1차 실패 시 폴백): 기존 finance.naver.com HTML 표 파싱 방식.
# - 폴링 주기 3분 + 차단(403/429) 감지 시 자동 백오프(일시정지)로 서버 부담을 줄인다.
# ----------------------------------------------------------------------
NAVER_STOCK_NEWS_API_URL = "https://stock.naver.com/api/domestic/detail/news"
NAVER_ITEM_NEWS_URL = "https://finance.naver.com/item/news_news.naver"  # 폴백용

NEWS_POLL_INTERVAL_MS = 180_000   # 뉴스 전용 자동새로고침 주기 (3분)
NEWS_CACHE_TTL_SEC = 180          # 위 주기와 맞춰 3분간은 같은 결과 재사용
NEWS_BACKOFF_FAIL_THRESHOLD = 2   # 이 횟수 이상 연속으로 차단성 응답을 받으면 백오프 진입
NEWS_BACKOFF_SECONDS = 60         # 백오프 진입 시 쉬는 시간(초). 이 동안은 요청 자체를 보내지 않음

# 뉴스 시각이 얼마나 최근인지에 따른 강조 색상 (초 단위 임계값, 색상) 순서대로 검사.
NEWS_RECENCY_COLOR_BUCKETS = (
    (3 * 60, "#ff3b3b"),              # 3분 이내: 밝은 빨간색
    (30 * 60, "#c77dff"),             # 30분 이내: 밝은 보라색
    (60 * 60, "#4aa8ff"),             # 1시간 이내: 밝은 파란색
    (12 * 60 * 60, "#f5c518"),        # 12시간 이내: 계란노른자색
    (24 * 60 * 60, "#fff176"),        # 24시간 이내: 연한 노랑색
    (14 * 24 * 60 * 60, "#33cc66"),   # 2주 이내: 초록색
    (30 * 24 * 60 * 60, "#a8e6a8"),   # 1달 이내: 연한 초록색
)
NEWS_RECENCY_DEFAULT_COLOR = "#ffffff"  # 그 이상 지난 뉴스는 기본 흰색


def _news_recency_color(dt_val) -> str:
    if dt_val is None:
        return NEWS_RECENCY_DEFAULT_COLOR
    age_sec = (datetime.now() - dt_val).total_seconds()
    if age_sec < 0:
        age_sec = 0
    for threshold_sec, color in NEWS_RECENCY_COLOR_BUCKETS:
        if age_sec <= threshold_sec:
            return color
    return NEWS_RECENCY_DEFAULT_COLOR


def _news_time_display(dt_val, raw_time: str) -> str:
    """'2026 0901 8 7' 형태(연도 / 월일 / 시 / 분, 시·분은 앞자리 0 생략)로 표시할 문자열 생성."""
    if dt_val is None:
        return raw_time
    return f"{dt_val.year} {dt_val.month:02d}{dt_val.day:02d} {dt_val.hour} {dt_val.minute}"


def build_news_line_html(news_data: dict) -> str:
    """뉴스 데이터(dict)를 색상이 입혀진 HTML 조각으로 변환 (제목 · 언론사 · 시각).
    제목과 시각 모두 뉴스가 얼마나 최근인지에 따른 같은 강조색을 사용한다.
    """
    title = html.escape(news_data.get("title") or "")
    press = html.escape(news_data.get("press") or "")
    dt_val = news_data.get("dt")
    time_display = html.escape(_news_time_display(dt_val, news_data.get("raw_time") or ""))
    recency_color = _news_recency_color(dt_val)

    segments = [f'<span style="color:{recency_color}; font-weight:700;">{title}</span>']
    if press:
        segments.append(f'<span style="color:#ffffff;">· {press}</span>')
    if time_display:
        segments.append(f'<span style="color:{recency_color}; font-weight:700;">· {time_display}</span>')
    return " ".join(segments)

# JSON 응답의 각 뉴스 항목에서 제목/언론사/시각 필드를 찾을 때 시도해볼 후보 키 이름들.
# 비공식 API라 필드명이 문서화되어 있지 않으므로 여러 후보를 순서대로 시도한다.
_NEWS_TITLE_KEYS = ("title", "articleTitle", "subject", "newsTitle")
_NEWS_PRESS_KEYS = ("office", "officeName", "press", "source", "media", "provider")
_NEWS_TIME_KEYS = ("datetime", "date", "regDt", "inputTime", "publishedAt", "wdate", "time", "articleDate")
_NEWS_LIST_KEYS = ("items", "list", "newsList", "articles", "result", "contents")


def _parse_news_datetime(date_val):
    """다양한 형태의 뉴스 시각 값을 datetime 객체로 파싱. 실패하면 None.
    문자열('YYYY-MM-DD HH:MM:SS', 'YYYYMMDDHHMM' 등)과 epoch(초/밀리초) 숫자를 모두 시도한다.
    """
    if date_val is None or date_val == "":
        return None

    if isinstance(date_val, (int, float)):
        ts = date_val / 1000 if date_val > 1e12 else date_val
        try:
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError, OverflowError):
            return None

    text = str(date_val).strip()
    if text.isdigit():
        if len(text) == 14:  # YYYYMMDDHHMMSS
            try:
                return datetime.strptime(text, "%Y%m%d%H%M%S")
            except ValueError:
                pass
        if len(text) == 12:  # YYYYMMDDHHMM (네이버증권 뉴스 API에서 관찰된 형식)
            try:
                return datetime.strptime(text, "%Y%m%d%H%M")
            except ValueError:
                pass
        if len(text) == 8:  # YYYYMMDD
            try:
                return datetime.strptime(text, "%Y%m%d")
            except ValueError:
                pass
        try:
            return _parse_news_datetime(int(text))
        except Exception:
            return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    now = datetime.now()
    try:
        if "." in text:
            return datetime.strptime(f"{now.year}.{text}", "%Y.%m.%d %H:%M")
        if ":" in text:
            return datetime.strptime(f"{now.strftime('%Y.%m.%d')} {text}", "%Y.%m.%d %H:%M")
    except ValueError:
        pass
    return None


def _pick_field(item: dict, candidates: tuple[str, ...]):
    for key in candidates:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _extract_news_items(payload) -> list:
    """API 응답(list 또는 여러 wrapper dict 형태)에서 뉴스 항목 리스트를 뽑아낸다.
    실제 관찰된 구조: 최상위가 '클러스터(언론사/유형별 묶음)' 리스트이고,
    각 클러스터가 {"itemTotal": N, "items": [실제 기사...]} 형태로 기사를 한 겹 더 감싸고 있다.
    이 경우 모든 클러스터의 items를 펼쳐서 실제 기사 리스트로 만든다.
    """
    top_level = []
    if isinstance(payload, list):
        top_level = payload
    elif isinstance(payload, dict):
        for key in _NEWS_LIST_KEYS:
            val = payload.get(key)
            if isinstance(val, list):
                top_level = val
                break
        if not top_level:
            for val in payload.values():
                if isinstance(val, list):
                    top_level = val
                    break

    if not top_level:
        return []

    first = top_level[0]
    # 클러스터 묶음(각 원소가 title 없이 items 하위 리스트만 가짐)이면 한 겹 펼친다.
    if isinstance(first, dict) and "title" not in first and any(k in first for k in _NEWS_LIST_KEYS):
        flattened = []
        for cluster in top_level:
            if not isinstance(cluster, dict):
                continue
            for key in _NEWS_LIST_KEYS:
                sub = cluster.get(key)
                if isinstance(sub, list):
                    flattened.extend(sub)
                    break
        if flattened:
            return flattened

    return top_level


def _build_news_data(title: str, press, time_val) -> dict:
    """제목/언론사/시각 원본 값을 받아 화면 표시에 필요한 구조로 정리."""
    title = re.sub(r"<.*?>", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    press_txt = str(press).strip() if press else ""
    dt_val = _parse_news_datetime(time_val)
    return {"title": title, "press": press_txt, "dt": dt_val, "raw_time": str(time_val) if time_val else ""}


@st.cache_data(ttl=NEWS_CACHE_TTL_SEC, show_spinner=False)
def _fetch_stock_news_raw(code: str):
    """종목 뉴스 실제 조회. 1차 stock.naver.com JSON API, 실패 시 finance.naver.com HTML 폴백.
    반환: (news_data_dict_or_None, blocked: bool, debug_info: str)
    news_data_dict는 {"title", "press", "dt"(datetime|None), "raw_time"} 형태.
    blocked=True 는 403/429 등 '차단성' 응답을 받았다는 뜻 (백오프 트리거용).
    debug_info 는 실패 원인을 화면에서 바로 확인하기 위한 진단 문자열.
    """
    debug_parts = []

    # 1차: stock.naver.com 공식 웹앱이 쓰는 JSON API
    try:
        resp = requests.get(
            NAVER_STOCK_NEWS_API_URL,
            params={"itemCode": code, "page": 1, "pageSize": 5},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://stock.naver.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
            timeout=5,
        )
        debug_parts.append(f"1차(JSON) status={resp.status_code}")
        if resp.status_code in (403, 429):
            return None, True, " / ".join(debug_parts)
        if resp.ok:
            try:
                payload = resp.json()
            except Exception as e:
                debug_parts.append(f"json파싱실패:{type(e).__name__}:{str(resp.text)[:120]}")
                payload = None
            if payload is not None:
                items = _extract_news_items(payload)
                debug_parts.append(f"items수={len(items)}")
                if not items and isinstance(payload, dict):
                    debug_parts.append(f"응답최상위키={list(payload.keys())[:10]}")
                if items:
                    first = items[0]
                    if isinstance(first, dict):
                        debug_parts.append(f"첫항목키={list(first.keys())[:12]}")
                        title = _pick_field(first, _NEWS_TITLE_KEYS)
                        press = _pick_field(first, _NEWS_PRESS_KEYS)
                        time_val = _pick_field(first, _NEWS_TIME_KEYS)
                        if title:
                            return _build_news_data(str(title), press, time_val), False, " / ".join(debug_parts)
                        debug_parts.append("제목필드못찾음")
        else:
            debug_parts.append(f"본문일부={str(resp.text)[:120]}")
    except Exception as e:
        debug_parts.append(f"1차 예외:{type(e).__name__}:{str(e)[:120]}")

    # 2차 폴백: 기존 finance.naver.com HTML 표 파싱
    try:
        resp = requests.get(
            NAVER_ITEM_NEWS_URL,
            params={"code": code, "page": 1},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=5,
        )
        debug_parts.append(f"2차(HTML) status={resp.status_code}")
        if resp.status_code in (403, 429):
            return None, True, " / ".join(debug_parts)
        resp.raise_for_status()
        resp.encoding = "euc-kr"
        html = resp.text
    except Exception as e:
        debug_parts.append(f"2차 예외:{type(e).__name__}:{str(e)[:120]}")
        return None, False, " / ".join(debug_parts)

    title_m = re.search(r'class="title"[^>]*>\s*<a[^>]*>(.*?)</a>', html, re.S)
    if not title_m:
        debug_parts.append("2차: title 패턴 매칭 실패")
        return None, False, " / ".join(debug_parts)
    press_m = re.search(r'class="info">(.*?)</td>', html, re.S)
    date_m = re.search(r'class="date">(.*?)</td>', html, re.S)

    title = re.sub(r"<.*?>", "", title_m.group(1)).strip()
    if not title:
        return None, False, " / ".join(debug_parts)
    press = re.sub(r"<.*?>", "", press_m.group(1)).strip() if press_m else ""
    date_txt = re.sub(r"<.*?>", "", date_m.group(1)).strip() if date_m else ""
    return _build_news_data(title, press, date_txt), False, " / ".join(debug_parts)


def _news_backoff_key(code: str) -> str:
    return f"news_backoff_until_{code}"


def _news_fail_key(code: str) -> str:
    return f"news_backoff_fails_{code}"


def get_news_backoff_remaining(code: str) -> int:
    """현재 백오프(일시정지) 중이면 남은 초를 반환, 아니면 0."""
    until_ts = st.session_state.get(_news_backoff_key(code))
    if not until_ts:
        return 0
    remain = int(until_ts - datetime.now().timestamp())
    return remain if remain > 0 else 0


def fetch_latest_stock_news_data(code: str) -> dict | None:
    """3분 캐시 + 차단 감지 시 자동 백오프(일시정지)가 적용된 뉴스 조회 래퍼.
    백오프 중에는 실제 HTTP 요청을 아예 보내지 않는다 (서버 부담 최소화).
    반환값은 {"title", "press", "dt"(datetime|None), "raw_time"} 딕셔너리.
    실패 원인 진단 문자열은 st.session_state[f"news_debug_{code}"]에 저장된다.
    """
    if get_news_backoff_remaining(code) > 0:
        return None

    news_data, blocked, debug_info = _fetch_stock_news_raw(code)
    st.session_state[f"news_debug_{code}"] = debug_info

    fail_key = _news_fail_key(code)
    if blocked:
        fails = st.session_state.get(fail_key, 0) + 1
        st.session_state[fail_key] = fails
        if fails >= NEWS_BACKOFF_FAIL_THRESHOLD:
            st.session_state[_news_backoff_key(code)] = datetime.now().timestamp() + NEWS_BACKOFF_SECONDS
            st.session_state[fail_key] = 0
        return None

    st.session_state[fail_key] = 0
    return news_data


# ----------------------------------------------------------------------
# 세력선1~4: 종목을 고를 때마다 시작일이 자동으로 세팅되는 4개의 추가 세력평단선
#  - 세력선1: 19개월 이내, 종가가 60일선 아래에 있는 구간의 최저점 → 시작일 (파스텔형광, 굵기5)
#             (세력선2/3/4에 가려져도 될 만큼, 항상 이들보다 먼저/맨 아래에 그린다)
#  - 세력선2: 12개월 이내, 5일선 언덕(로컬 고점)들 중 캔들 최고점 → 시작일 (파스텔형광, 굵기3)
#  - 세력선3: 50봉(영업일) 이내(가장 최근 18봉 제외), 5일선 언덕(로컬 고점) 중 캔들 최고봉,
#             단 세력선4 시작일보다 늦어야 함(데드크로스 조건은 없음)
#             → 시작일 (형광색, 굵기3 / 캔들 위 얇은 버전은 굵기2)
#  - 세력선4: 5개월 이내, 20일선이 60일선 아래로 역배열(종가도 60일선 아래) 확정된 구간의
#             최저점 → 시작일 (형광색, 굵기4 / 캔들 위 얇은 버전은 굵기2)
#  4개 모두 종료일은 오늘 날짜.
#
#  위 4개 선과 별도로, 같은 시작일/종료일/색상 기준의 "캔들 위에 보이는" 얇은 버전도
#  양봉/음봉 캔들 위에 겹쳐 그린다(아래 render_daily_seryeok_chart 참고; 굵기는 세력선별
#  top_width, 지정 없으면 SERYEOK_AUTO_LINE_TOP_WIDTH). 굵은 선이 캔들에 가려지더라도
#  이 얇은 선으로 계속 위치를 확인할 수 있게 하기 위함이다.
# ----------------------------------------------------------------------
SERYEOK_AUTO_LINE_STYLES = {
    1: dict(color="#e0ff4f", width=5, months=19, label="세력선1"),                    # 파스텔형광 굵기5
    2: dict(color="#e0ff4f", width=3, months=12, label="세력선2"),                    # 파스텔형광 굵기3
    3: dict(color="#00e5ff", width=3, days=50,   label="세력선3", top_width=2),       # 형광색 굵기3(캔들위 굵기2)
    4: dict(color="#00e5ff", width=4, months=5,  label="세력선4", top_width=2),       # 형광색 굵기4(캔들위 굵기2)
}

# 위 4개 세력선을 캔들 위에 겹쳐 그릴 때 공통으로 쓰는 굵기(요청: 모두 굵기1)
SERYEOK_AUTO_LINE_TOP_WIDTH = 1


def _months_ago_date(base: date, months: int) -> date:
    """base 날짜에서 'months' 개월 전 날짜(해당 월에 없는 일자는 말일로 보정)."""
    import calendar
    total = base.month - 1 - months
    y = base.year + total // 12
    m = total % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    d = min(base.day, last_day)
    return date(y, m, d)


def _local_max_mask(s: pd.Series, window: int = 3) -> pd.Series:
    """'5일선 언덕' 판정용: 좌우 window일을 포함한 구간에서 자기 자신이 최고값인 지점(로컬 고점)."""
    roll_max = s.rolling(window * 2 + 1, center=True, min_periods=1).max()
    return (s == roll_max) & s.notna()


def _seryeok_window_df(full_df: pd.DataFrame, months: int, end_date: date) -> pd.DataFrame:
    """오늘(end_date) 기준 최근 N개월 구간의 일봉만 추려낸다."""
    start_bound = _months_ago_date(end_date, months)
    m = (full_df["date"].dt.date >= start_bound) & (full_df["date"].dt.date <= end_date)
    return full_df.loc[m]


def _seryeok_window_df_bars(full_df: pd.DataFrame, n_bars: int, end_date: date) -> pd.DataFrame:
    """오늘(end_date) 기준 최근 n_bars개 봉(영업일)만 추려낸다(달력일이 아닌 실제 캔들 개수 기준)."""
    win_all = full_df.loc[full_df["date"].dt.date <= end_date]
    return win_all.tail(n_bars)


def _seryeok_style_fallback_date(end_date: date, style: dict) -> date:
    """세력선 시작일 계산에 실패했을 때 쓰는 대체 날짜("N개월 전" 또는 "N봉(=N일) 전")."""
    if "days" in style:
        return end_date - timedelta(days=style["days"])
    return _months_ago_date(end_date, style["months"])


def _find_seryeok1_start(full_df: pd.DataFrame, end_date: date):
    """19개월 이내, 캔들(종가)이 60일선 아래에 있는 구간의 최저가 시점."""
    win = _seryeok_window_df(full_df, 19, end_date)
    win = win.dropna(subset=["close", "low", "ma60"])
    win = win[win["close"] < win["ma60"]]
    if win.empty:
        return None
    idx = win["low"].idxmin()
    return full_df.loc[idx, "date"].date()


def _find_seryeok2_start(full_df: pd.DataFrame, end_date: date):
    """12개월 이내, 5일선 언덕(로컬 고점)들 중 캔들 최고가가 가장 높은 봉의 시점."""
    win = _seryeok_window_df(full_df, 12, end_date)
    win = win.dropna(subset=["ma5", "high"])
    if win.empty:
        return None
    peaks = win[_local_max_mask(win["ma5"], window=3)]
    if peaks.empty:
        peaks = win
    idx = peaks["high"].idxmax()
    return full_df.loc[idx, "date"].date()


def _find_seryeok3_start(full_df: pd.DataFrame, end_date: date, min_start_date: date | None = None):
    """50봉(영업일) 이내(단, 가장 최근 18봉은 제외한 구간)에서 5일선 언덕(로컬 고점) 중
    캔들 최고가가 가장 높은 봉의 시점. 단, 세력선4번 시작일(min_start_date)보다 늦은(더 최근인)
    봉만 후보로 삼는다 — 후보가 하나도 없으면 이 제약 없이 다시 찾는다."""
    win_all = _seryeok_window_df_bars(full_df, 50, end_date)
    if len(win_all) <= 18:
        return None
    win = win_all.iloc[:-18]  # 가장 최근 18봉(18일 최고봉 구간) 제외
    win = win.dropna(subset=["ma5", "high"])
    if win.empty:
        return None
    peaks = win[_local_max_mask(win["ma5"], window=3)]
    if peaks.empty:
        peaks = win
    if min_start_date is not None:
        later_peaks = peaks[peaks["date"].dt.date > min_start_date]
        if not later_peaks.empty:
            peaks = later_peaks
    idx = peaks["high"].idxmax()
    return full_df.loc[idx, "date"].date()


def _find_seryeok4_start(full_df: pd.DataFrame, end_date: date):
    """5개월 이내, 20일선이 60일선 아래로 역배열되고(종가도 60일선 아래) 확정된 구간의 최저가 시점."""
    win = _seryeok_window_df(full_df, 5, end_date)
    win = win.dropna(subset=["ma20", "ma60", "close", "low"])
    win = win[(win["ma20"] < win["ma60"]) & (win["close"] < win["ma60"])]
    if win.empty:
        return None
    idx = win["low"].idxmin()
    return full_df.loc[idx, "date"].date()


_SERYEOK_AUTO_FINDERS = {
    1: _find_seryeok1_start,
    2: _find_seryeok2_start,
    3: _find_seryeok3_start,
    4: _find_seryeok4_start,
}


def compute_seryeok_auto_dates(code: str, end_date=None) -> dict:
    """세력선1~4의 (시작일, 종료일) 딕셔너리를 계산해서 반환.
    {1: {"start": date, "end": date}, 2: {...}, 3: {...}, 4: {...}}
    데이터가 부족해 조건을 못 찾으면 해당 세력선의 "N개월 전" 날짜로 대체한다."""
    end_date = end_date or date.today()
    full_df = fetch_daily_ohlcv(code)
    result = {}
    if full_df.empty:
        for n, style in SERYEOK_AUTO_LINE_STYLES.items():
            fallback = _seryeok_style_fallback_date(end_date, style)
            result[n] = {"start": fallback, "end": end_date}
        return result

    full_df = full_df.copy()
    for p in (5, 20, 60):
        full_df[f"ma{p}"] = full_df["close"].rolling(p).mean()

    for n, style in SERYEOK_AUTO_LINE_STYLES.items():
        if n == 3:
            continue  # 세력선4 시작일을 먼저 구한 뒤 아래에서 계산
        finder = _SERYEOK_AUTO_FINDERS[n]
        start = finder(full_df, end_date)
        if start is None:
            start = _seryeok_style_fallback_date(end_date, style)
        result[n] = {"start": start, "end": end_date}

    # 세력선3은 "세력선4 시작일보다 늦어야 함" 조건이 있어 세력선4 계산 후에 처리
    _style3 = SERYEOK_AUTO_LINE_STYLES[3]
    _line4_start = result.get(4, {}).get("start")
    _start3 = _find_seryeok3_start(full_df, end_date, min_start_date=_line4_start)
    if _start3 is None:
        _start3 = _seryeok_style_fallback_date(end_date, _style3)
    result[3] = {"start": _start3, "end": end_date}
    return result


def _find_daily_sma5_hill_date(full_df: pd.DataFrame, after_date: date, end_date: date):
    """after_date보다 늦은(더 최근인) 날짜들 중에서, 5일선 언덕(로컬 고점) 중 캔들 최고가가
    가장 높은 봉의 날짜를 찾는다. ('목표' 버튼으로 시작일이 자동 세팅될 때, 5이평 언덕 날짜를
    시작일보다 늦은 날짜 중에서 자동으로 골라주기 위한 보조 함수)"""
    win = full_df[(full_df["date"].dt.date > after_date) & (full_df["date"].dt.date <= end_date)]
    win = win.dropna(subset=["ma5", "high"])
    if win.empty:
        return None
    peaks = win[_local_max_mask(win["ma5"], window=3)]
    if peaks.empty:
        peaks = win
    idx = peaks["high"].idxmax()
    return full_df.loc[idx, "date"].date()


def _find_daily_lowest_price_date(full_df: pd.DataFrame, after_date: date, end_date: date):
    """after_date(=5이평 언덕 날짜)보다 늦은 날짜들 중에서, 저가가 가장 낮은 봉의 날짜를 찾는다.
    ('목표' 버튼으로 세력평단가 날짜를 자동 세팅하기 위한 보조 함수)"""
    win = full_df[(full_df["date"].dt.date > after_date) & (full_df["date"].dt.date <= end_date)]
    win = win.dropna(subset=["low"])
    if win.empty:
        return None
    idx = win["low"].idxmin()
    return full_df.loc[idx, "date"].date()


def compute_seryeok_line_range(full_df: pd.DataFrame, start_date, end_date) -> pd.Series:
    """full_df 전체 인덱스 기준으로 [start_date, end_date] 구간만 누적 세력평단(VWAP) 값을 채우고
    그 외 구간은 NaN인 Series를 반환. (다른 '맨뒤' 오버레이 선들과 동일한 방식으로,
    실제 표시 구간(sub)과 무관하게 자체 시작일부터 값을 누적할 수 있게 한다)"""
    result = pd.Series(index=full_df.index, dtype=float)
    if start_date is None or end_date is None or start_date > end_date:
        return result
    mask = (full_df["date"].dt.date >= start_date) & (full_df["date"].dt.date <= end_date)
    seg = full_df.loc[mask]
    if seg.empty or seg["volume"].sum() == 0:
        return result
    cum = (seg["close"] * seg["volume"]).cumsum() / seg["volume"].cumsum()
    result.loc[seg.index] = cum.values
    return result


def _signal_wansaeng_core(full_df: pd.DataFrame, high_n: int, low_n: int, need_open_gap: bool) -> pd.Series:
    """완생/미생 공통 수식:
    max(avg(C,5),avg(C,20),avg(C,60)) < min(avg(C,5),avg(C,20),avg(C,60))*(1+3/100)
    && C > highest(H(1),5) && avg(V,5) >= 5000 && V > V(1)*1.5
    && C > (highest(high,high_n)+lowest(low,low_n))/2 && C > avg(C,60)
    && CrossUp(C, BBandsUp(20,2))  [&& O*1.025 <= H  (need_open_gap일 때)]"""
    o = full_df["open"]
    h = full_df["high"]
    l = full_df["low"]
    c = full_df["close"]
    v = full_df["volume"].astype(float)
    m5 = c.rolling(5).mean()
    m20 = c.rolling(20).mean()
    m60 = c.rolling(60).mean()
    mx = pd.concat([m5, m20, m60], axis=1).max(axis=1)
    mn = pd.concat([m5, m20, m60], axis=1).min(axis=1)
    cond = mx < mn * (1 + 3 / 100)
    cond &= c > h.shift(1).rolling(5).max()
    cond &= v.rolling(5).mean() >= 5000
    cond &= v > v.shift(1) * 1.5
    cond &= c > (h.rolling(high_n).max() + l.rolling(low_n).min()) / 2
    cond &= c > m60
    bb_up20 = c.rolling(20).mean() + 2 * c.rolling(20).std(ddof=0)
    cond &= (c > bb_up20) & (c.shift(1) <= bb_up20.shift(1))
    if need_open_gap:
        cond &= o * 1.025 <= h
    return cond.fillna(False)


def compute_signal_wansaeng5(full_df: pd.DataFrame) -> pd.Series:
    """분봉 신호 '완생'(및 분봉 세로선): 위 공통 수식 + highest(high,1.5)(소수점 버린 1봉) + lowest(low,78)
    + O*1.025 <= H. (예전 이름 '완생5분'과 같은 수식)"""
    return _signal_wansaeng_core(full_df, high_n=1, low_n=78, need_open_gap=True)


def compute_signal_misaeng(full_df: pd.DataFrame) -> pd.Series:
    """분봉 신호 '미생': 완생과 같지만 C > (highest(high,78)+lowest(low,78))/2 이고 O*1.025 <= H 조건은 없다."""
    return _signal_wansaeng_core(full_df, high_n=78, low_n=78, need_open_gap=False)


def compute_signal_chuse_banbal(full_df: pd.DataFrame) -> pd.Series:
    """분봉 신호 '추세반등':
    DayOpen() < PredayClose()*1.10 AND PredayClose() < C
    AND avg(C(1),5) < avg(C(4),5) AND avg(C(1),5) < avg(C,5)
    AND C > BBandsUp(300,2) AND C > avg(C,226) AND C > avg(C,60)
    AND avg(C,60) > avg(C(5),60) AND C > (highest(high,52)+lowest(low,52))/2
    DayOpen = 그 날 첫 봉의 시가, PredayClose = 전 거래일 마지막 봉의 종가(데이터에 이전 날이 없으면 신호 없음)."""
    h = full_df["high"]
    l = full_df["low"]
    c = full_df["close"]
    day = full_df["datetime"].dt.date
    day_open = full_df["open"].groupby(day).transform("first")
    last_close_by_day = c.groupby(day).last()
    prev_close_by_day = last_close_by_day.shift(1)
    preday_close = day.map(prev_close_by_day).astype(float)
    ma5 = c.rolling(5).mean()
    ma60 = c.rolling(60).mean()
    bb_up300 = c.rolling(300).mean() + 2 * c.rolling(300).std(ddof=0)
    cond = day_open < preday_close * 1.10
    cond &= preday_close < c
    cond &= ma5.shift(1) < ma5.shift(4)
    cond &= ma5.shift(1) < ma5
    cond &= c > bb_up300
    cond &= c > c.rolling(226).mean()
    cond &= c > ma60
    cond &= ma60 > ma60.shift(5)
    cond &= c > (h.rolling(52).max() + l.rolling(52).min()) / 2
    return cond.fillna(False)


def compute_min_vertical_line(df: pd.DataFrame, target_win: int, break_win: int,
                              cl_high_win: int = 20, cl_low_win: int = 20) -> pd.Series:
    """분봉 수직선(초록/주황) 공통 수식:
    CL = valuewhen(1, highest(h(1),break_win) < highest(h,break_win), (highest(high,cl_high_win)+lowest(low,cl_low_win))/2)
    결과 = highest(H,target_win) - (((highest(H,target_win) - CL) / 5) * 10)"""
    high = df["high"]
    low = df["low"]
    hh_target = high.rolling(target_win).max()
    hh_break = high.rolling(break_win).max()
    cond = hh_break.shift(1) < hh_break
    expr = (high.rolling(cl_high_win).max() + low.rolling(cl_low_win).min()) / 2
    cl = expr.where(cond).ffill()
    return hh_target - (((hh_target - cl) / 5) * 10)


def compute_min_line_trix10_highestsince_ema10(df: pd.DataFrame) -> pd.Series:
    """수직갈색: 저항 = HighestSince(1, CrossUp(Trix(10),0), avg(종가,10,지수))"""
    close = df["close"]
    trix10 = _trix(close, 10)
    cond = _crossup(trix10, pd.Series(0.0, index=close.index)).fillna(False)
    ema10 = close.ewm(span=10, adjust=False).mean()
    res = _highestsince(cond, ema10)
    return res.where(cond.cumsum() > 0)  # 첫 상향돌파 전에는 선 없음


def compute_min_line_ma100_50_cross_value(df: pd.DataFrame) -> pd.Series:
    """수직연초록: Mm=ma(c,100); Mn=ma(c,50); valuewhen(1, crossup(Mm,Mn) or crossdown(Mm,Mn), Mm)"""
    close = df["close"]
    mm = close.rolling(100).mean()
    mn = close.rolling(50).mean()
    cond = (_crossup(mm, mn) | _crossdown(mm, mn)).fillna(False)
    return _valuewhen(cond, mm)


def compute_min_line_volume_vwap(df: pd.DataFrame, mult: float = 1.0) -> pd.Series:
    """중간파랑/스윙하늘선: COND = V > MA(V,20)*2; A = SUM(IF(COND,C*V,0),120);
    B = SUM(IF(COND,V,0),120); 세력평단 = A/B (mult를 곱해서 반환: 1.0 또는 1.20)"""
    vol = df["volume"].astype(float)
    close = df["close"]
    cond = vol > vol.rolling(20).mean() * 2
    a = (close * vol).where(cond, 0.0).rolling(120).sum()
    b = vol.where(cond, 0.0).rolling(120).sum()
    return (a / b.where(b > 0)) * mult


def compute_min_line_rolling_vwap(df: pd.DataFrame, n: int = 130, mult: float = 1.0) -> pd.Series:
    """흰검정점선390분용 계열: A = SUM(C*V, n); B = SUM(V, n); 평단 = A / B  (mult 곱해서 반환)"""
    vol = df["volume"].astype(float)
    a = (df["close"] * vol).rolling(n).sum()
    b = vol.rolling(n).sum()
    return (a / b.where(b > 0)) * mult


def compute_seryeok4_minute_line(df: pd.DataFrame, code: str, interval_min: int = 10):
    """분봉(10분봉 이상) 차트용 '세력선4' 자동 세력평단선.
    일봉차트의 세력선4와 같은 기법(5개월 이내, 20일선<60일선 역배열 + 종가<60일선 구간의 최저점)으로
    시작일을 종목 선택 시마다 자동 계산하고, 그 시작일부터 현재까지 분봉 기준으로 누적
    세력평단(VWAP = 누적(종가*거래량)/누적거래량)을 구해 Series(df 인덱스 기준, 그 전은 NaN)로 반환.
    시작일을 못 구하면 None."""
    if df is None or df.empty:
        return None
    result = pd.Series(index=df.index, dtype=float)
    if interval_min < 10:
        # 1/3/5분봉(당일치만): 몇 개월 전 기준이 의미 없으므로, 10:30 이후 당일 최저점(저가가 가장 낮은 봉)이
        # 생기면 그 봉부터 현재까지 누적 세력평단선을 그린다. 장중에 더 낮은 저점이 새로 생기면
        # 시작 지점도 그 새 최저점으로 자동 이동한다.
        _day = df["datetime"].dt.date.iloc[-1]
        # 10:30 이후 봉들 중에서만 최저점을 찾는다(10:30 전에는 선이 나오지 않음)
        _today_df = df.loc[(df["datetime"].dt.date == _day) &
                           (df["datetime"].dt.time >= dtime(10, 30))]
        _low_valid = _today_df["low"].dropna()
        if _low_valid.empty:
            return result
        seg = df.loc[_low_valid.idxmin():].loc[lambda d: d["datetime"].dt.date == _day]
    else:
        try:
            _dates = compute_seryeok_auto_dates(code)
            _start = _dates.get(4, {}).get("start")
        except Exception:
            return None
        if _start is None:
            return None
        _mask = df["datetime"].dt.date >= _start
        seg = df.loc[_mask]
    if seg.empty:
        return result
    _vol = seg["volume"].fillna(0)
    _cum_vol = _vol.cumsum()
    with np.errstate(divide="ignore", invalid="ignore"):
        _vwap = (seg["close"] * _vol).cumsum() / _cum_vol
    result.loc[seg.index] = _vwap.where(_cum_vol > 0).values
    return result


def _add_white_dotted_vwap_pair(fig, full_df, sub, price_row: int, name: str, n: int, mult: float, width: int):
    """분봉 차트의 '흰검정점선390분용' 계열을 일봉에도 똑같이 그린다:
    SUM(C*V, n)/SUM(V, n) (n=130봉 거래량가중 평단)에 mult를 곱한 선을 '흰 점선(굵기 width)' 아래에
    '회색(#808080) 실선(굵기 width+2)' 밑받침을 깔아서 그린다(분봉과 같은 색·굵기)."""
    _vals = compute_min_line_rolling_vwap(full_df, n, mult)
    _m = full_df["date"].isin(sub["date"])
    _x = full_df.loc[_m, "date"]
    _y = _vals.loc[_m]
    if not _y.notna().any():
        return
    fig.add_trace(go.Scatter(
        x=_x, y=_y, mode="lines", name=name + "(밑받침)",
        line=dict(color="#808080", width=width + 2),
        connectgaps=True, hoverinfo="skip", showlegend=False,
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=_x, y=_y, mode="lines", name=name,
        line=dict(color="#FFFFFF", width=width, dash="dot"),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)


def render_daily_seryeok_chart(code: str, name: str, start_date, end_date, show_legend: bool = False,
                                fill_candles: bool = False, nwave_info: dict | None = None,
                                show_signal: bool = False, show_volume: bool = False,
                                show_kiwoom3: bool = False,
                                watch_added_date=None,
                                local_snapshot_date=None,
                                seryeok_auto_dates: dict | None = None,
                                chart_display_start_date=None,
                                nwave_marker_dates: dict | None = None,
                                view_months: int | None = None,
                                show_vwap_sigma: bool = False):
    """일봉 세력평단가 차트: 캔들 + 5~720일 이동평균선 + (선택기간) 누적 세력평단선
    (+선택 시 N파동 목표가 점선 / 매수 신호 / 거래대금 보조지표 / 관심종목 저장일 초록 점선
     / '요'·'테요' 로컬 스냅샷 조회일 흰 점선 / 세력선1~4 자동 시작일 세력평단선).

    nwave_marker_dates: '목표' 패널의 시작일/5이평 언덕 날짜/세력평단가 날짜를 차트에 흰색
    세로 점선으로 표시하기 위한 {"start": date, "sma5": date, "avg": date} 딕셔너리.

    chart_display_start_date: 화면에 실제로 그려줄 캔들 구간의 시작일. None이면 기존처럼
    start_date를 그대로 표시 시작일로 쓴다. 값이 주어지면(예: '목표' 버튼으로 시작일이 자동으로
    최근 날짜로 당겨졌을 때) 세력평단(VWAP) 누적 계산은 그대로 start_date~end_date 구간만
    쓰되, 캔들/이평선 등 화면 표시 자체는 이 값부터 넓게 보여줘서 차트가 확대(줌인)되지 않게 한다."""
    full_df = fetch_daily_ohlcv_with_today(code)
    if full_df.empty:
        st.warning("일봉 데이터를 받아오지 못했습니다.")
        return

    for p in MA_PERIODS:
        full_df[f"ma{p}"] = full_df["close"].rolling(p).mean()

    # 화면 표시 구간(display)과 세력평단 누적 계산 구간(start_date~end_date)을 분리한다.
    _display_start = chart_display_start_date if chart_display_start_date is not None else start_date
    if _display_start > start_date:
        _display_start = start_date
    mask = (full_df["date"].dt.date >= _display_start) & (full_df["date"].dt.date <= end_date)
    sub = full_df.loc[mask].copy()
    if sub.empty:
        st.warning("선택한 기간에 해당하는 일봉 데이터가 없습니다.")
        return

    sub["cum_vwap"] = compute_seryeok_line_range(full_df, start_date, end_date).loc[sub.index]
    _vwap_valid_for_ma = sub["cum_vwap"].dropna()
    _last_vwap_for_ma = float(_vwap_valid_for_ma.iloc[-1]) if not _vwap_valid_for_ma.empty \
        else float(sub["close"].iloc[-1])

    # 호버용: 날짜 옆에 표시할 세력평단比(연한빨강/연한파랑) + 전일比(빨강/파랑)
    sub["_seryeok_gap"] = (sub["close"] - sub["cum_vwap"]) / sub["cum_vwap"] * 100
    sub["_prev_close"] = sub["close"].shift(1)
    sub["_day_gap"] = sub["close"].pct_change() * 100
    _hover_gap_lines = []
    for _sg, _dg in zip(sub["_seryeok_gap"], sub["_day_gap"]):
        if pd.notna(_sg):
            _sg_color = "#f4a6a6" if _sg >= 0 else "#a6c8f4"
            _line = f'<span style="color:{_sg_color}">세{_sg:+.0f}%</span>'
        else:
            _line = '<span style="color:#888888">세-</span>'
        if pd.notna(_dg):
            _dg_color = "#e05252" if _dg >= 0 else "#4a90e2"
            _line += f'  <span style="color:{_dg_color}">전{_dg:+.0f}%</span>'
        _hover_gap_lines.append(_line)

    # ---- 서브플롯 구성: 캔들(항상) + 거래대금(옵션, 분봉 거래대금 박스의 약 1/4 높이) ----
    # 캔들을 보조축(secondary_y)에 그려서 이평선/다른 라인선(모두 주축 scatter)보다 항상 위에 보이도록 함
    # (plotly는 캔들스틱을 scatter보다 항상 아래 레이어에 그리는 내부 규칙이 있어, 트레이스 순서만으로는
    # 캔들을 위로 올릴 수 없다 — 대신 나중에 그려지는 서브플롯(보조축)에 캔들을 배치해 우회한다)
    price_row = 1
    signal_row = 2
    # 기본 높이(655): 위쪽 날짜 라벨(종료일/세력선1~4 종료/안내문구), 차트 상단 종목명 제목,
    # 차트 내부 title(플롯 자체의 "종목명 (코드) 일봉 세력평단가 차트" 글자)까지 모두 제거해서
    # 절약된 세로 여백만큼 차트 자체 높이를 늘려서(520 → 655) 캔들이 더 커 보이도록 함
    # (가격/거래대금 비율은 그대로 유지)
    _daily_chart_base_height = 655
    # ---- 신호 스트립: on/off 버튼 없이 항상 표시. 캔들 차트 바로 아래, 거래대금 바로 위에
    # 배치되는 얇은 띠(거래대금 박스보다도 작게)로, 신호 8종을 각자 고정된 세로 레인에 모아 찍는다. ----
    _signal_height_px = 34
    if show_volume:
        vol_row = 3
        _price_height = _daily_chart_base_height - (0 if show_legend else 30)
        _vol_height_px = 60  # 분봉차트 거래대금 박스(약 171px)의 대략 1/3~1/4 크기 (너무 작으면 렌더링이 불안정해 약간 여유를 둠)
        _total_height = _price_height + _signal_height_px + _vol_height_px
        row_heights = [_price_height / _total_height, _signal_height_px / _total_height,
                       _vol_height_px / _total_height]
        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            vertical_spacing=0.006, row_heights=row_heights,
            specs=[[{"secondary_y": True}], [{}], [{}]],
        )
    else:
        _price_height = _daily_chart_base_height - (0 if show_legend else 30)
        _total_height = _price_height + _signal_height_px
        row_heights = [_price_height / _total_height, _signal_height_px / _total_height]
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.006, row_heights=row_heights,
            specs=[[{"secondary_y": True}], [{}]],
        )

    def _pct_span(cur, base):
        if base is None or pd.isna(base) or not base:
            return "-"
        _p = (cur - base) / base * 100
        _c = "#e05252" if _p >= 0 else "#4a90e2"
        return f'<span style="color:{_c}">{_p:+.0f}%</span>'

    fig.add_trace(go.Candlestick(
        x=sub["date"], open=sub["open"], high=sub["high"], low=sub["low"], close=sub["close"],
        name="일봉",
        increasing=dict(line=dict(color=CANDLE_UP), fillcolor=(CANDLE_UP if fill_candles else "rgba(0,0,0,0)")),
        decreasing=dict(line=dict(color=CANDLE_DOWN), fillcolor=(CANDLE_DOWN if fill_candles else "rgba(0,0,0,0)")),
        hovertext=[
            f"{gl}<br>시가: {o:,.0f}<br>"
            f"고가: {_pct_span(h, pc)}<br>"
            f"저가: {_pct_span(l, pc)}<br>"
            f"종가: {_pct_span(c, pc)}"
            for gl, o, h, l, c, pc in zip(
                _hover_gap_lines, sub["open"], sub["high"], sub["low"], sub["close"], sub["_prev_close"]
            )
        ],
        hoverinfo="text+x",
    ), row=price_row, col=1, secondary_y=True)

    _newlines_mask = full_df["date"].isin(sub["date"])

    # ---- 20일선/60일선 구름대(색 채우기, 맨뒤): 종가 단순이동평균 20 vs 60 사이를 채움
    # 60일선이 위(하락 구간)=파랑 #99CCFF / 20일선이 위(상승 구간)=연하늘 #CCFFFF ----
    _cloud_ma20 = full_df["close"].rolling(20).mean()
    _cloud_ma60 = full_df["close"].rolling(60).mean()
    _cx, _lb_b, _ub_b, _lb_a, _ub_a = build_ma_cloud_segments(
        full_df.loc[_newlines_mask, "date"], _cloud_ma20.loc[_newlines_mask], _cloud_ma60.loc[_newlines_mask])
    for _lo, _up, _fc, _nm in (
        (_lb_b, _ub_b, "#99CCFF", "20/60 구름대(60일선 위)"),
        (_lb_a, _ub_a, "#CCFFFF", "20/60 구름대(20일선 위)"),
    ):
        # 구간별 닫힌 도형(fill='toself')으로 칠해서, 끊긴 구간이 서로 이어져 엉뚱한 곳이 칠해지는
        # tonexty 문제를 피한다.
        _px, _py = build_ma_cloud_polygons(_cx, _lo, _up)
        if not _px:
            continue
        fig.add_trace(go.Scatter(
            x=_px, y=_py, mode="lines", line=dict(width=0, color=_fc),
            fill="toself", fillcolor=_fc, name=_nm,
            showlegend=False, hoverinfo="skip", connectgaps=False,
        ), row=price_row, col=1)

    # ---- 신규 라인 3(맨뒤, 올리브): A=WMA(2*WMA(종가,200,가중)-WMA(종가,400,가중),Sqrt(400),가중);
    # sscH0=Highest(A,182) ----
    _newline3_full = compute_seryeok_line_hull_highest(full_df, 400, 182)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_newlines_mask, "date"], y=_newline3_full.loc[_newlines_mask],
        mode="lines", name="HMA400 고점선(182, 맨뒤)",
        line=dict(color="#8CBA00", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 흰검정점선390분용1 (분봉 차트와 같은 선, 맨뒤): 130봉 거래량가중 평단 x1.03, 흰 점선 굵기2 ----
    _add_white_dotted_vwap_pair(fig, full_df, sub, price_row, "흰검정점선390분용1", 130, 1.03, 2)

    # ---- 초록선(맨뒤): A=C>C(1)&&C>C(2)&&C>C(3)&&C>C(4); B=C(1)<C(2)&&C(1)<C(3)&&C(1)<C(4)&&C(1)<C(5);
    # K=O>=C(1); 결과=ValueWhen(6, A&&B&&K, 종가)
    # (다른 라인선들에 가려지도록 다른 오버레이 라인들보다 먼저/맨 아래에 그린다) ----
    _localbottom_line_full = compute_line_valuewhen6_localbottom_open(full_df)
    _lb_mask = full_df["date"].isin(sub["date"])
    fig.add_trace(go.Scatter(
        x=full_df.loc[_lb_mask, "date"], y=_localbottom_line_full.loc[_lb_mask],
        mode="lines", name="국소저점 시가돌파선",
        line=dict(color="#00CC00", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 자주색선(맨뒤): A=WMA(2*WMA(종가,60,가중)-WMA(종가,120,가중),Sqrt(120),가중); sscH0=Highest(A,110)
    # (다른 라인선들에 가려지도록 다른 오버레이 라인들보다 먼저/맨 아래에 그린다) ----
    _hma120_highest110_full = compute_seryeok_line_hull_highest(full_df, 120, 110)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_lb_mask, "date"], y=_hma120_highest110_full.loc[_lb_mask],
        mode="lines", name="HMA120 고점선(110)",
        line=dict(color="#800080", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 진한파랑선(맨뒤): CL=ValueWhen(1, Highest(H(1),120)<Highest(H,120), (Highest(H,120)+Lowest(L,120))/2);
    # 결과=Highest(H,120)-(((Highest(H,120)-CL)/5)*10)
    # (다른 라인선들에 가려지도록 다른 오버레이 라인들보다 먼저/맨 아래에 그린다) ----
    _cl120_symmetric_full = compute_line_cl120_symmetric_support(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_lb_mask, "date"], y=_cl120_symmetric_full.loc[_lb_mask],
        mode="lines", name="CL120 지지선",
        line=dict(color="#4169E1", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 하늘색선(맨뒤): HighestSince(1, CrossDown(CCI(9),0), Highest(L,120))
    # (다른 라인선들에 가려지도록 다른 오버레이 라인들보다 먼저/맨 아래에 그린다) ----
    _cci_line_back_full = compute_line_cci_crossdown_highest_low120(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_lb_mask, "date"], y=_cci_line_back_full.loc[_lb_mask],
        mode="lines", name="CCI9 하향돌파 고점선(맨뒤)",
        line=dict(color="#00AEDB", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 연두색선(맨뒤): B=(H+L)/2; dn8=B-ATR(60)+1; upT=ValueWhen(1, Highest(dn8(1),200)<dn8, dn8)
    # (다른 라인선들에 가려지도록 다른 오버레이 라인들보다 먼저/맨 아래에 그린다) ----
    _dn8_upt_full = compute_line_dn8_upt(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_lb_mask, "date"], y=_dn8_upt_full.loc[_lb_mask],
        mode="lines", name="dn8 upT선(맨뒤)",
        line=dict(color="#00FF99", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # 5/20/60/120/240일 이평선은 다른 추가 라인선(세력라인/키움3신호 등)에 가려지지 않도록
    # 해당 라인들을 모두 그린 뒤 맨 마지막(최상단)에 추가한다. (아래쪽 코드 참고)

    _seryeok_hover = []
    for _sg in sub["_seryeok_gap"]:
        if pd.notna(_sg):
            _sg_color2 = "#f4a6a6" if _sg >= 0 else "#a6c8f4"
            _seryeok_hover.append(f'세력평단: <span style="color:{_sg_color2}">{_sg:+.0f}%</span>')
        else:
            _seryeok_hover.append('세력평단: <span style="color:#888888">-</span>')

    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["cum_vwap"], mode="lines", name="세력평단",
        line=dict(color="#000000", width=5),
        hovertext=_seryeok_hover,
        hoverinfo="text",
    ), row=price_row, col=1)

    if show_vwap_sigma:
        _vwap_s = sub["cum_vwap"]
        _close_s = sub["close"]
        _valid_mask = _vwap_s.notna() & (_vwap_s > 0) & _close_s.notna()
        if _valid_mask.sum() >= 2:
            _dev_pct = ((_close_s[_valid_mask] - _vwap_s[_valid_mask]) / _vwap_s[_valid_mask]) * 100.0
            _sigma_pct = float(_dev_pct.std(ddof=1))
            if pd.notna(_sigma_pct) and _sigma_pct > 0:
                _sigma_levels = [
                    (3, "+3σ", "dot", 1.2, "rgba(255, 120, 120, 0.75)"),
                    (2, "+2σ", "dot", 1.2, "rgba(255, 165, 90, 0.75)"),
                    (1, "+1σ", "dot", 1.2, "rgba(255, 220, 110, 0.80)"),
                    (-1, "-1σ", "dot", 1.2, "rgba(130, 215, 255, 0.80)"),
                    (-2, "-2σ", "dot", 1.2, "rgba(95, 165, 255, 0.75)"),
                    (-3, "-3σ", "dot", 1.2, "rgba(145, 120, 255, 0.75)"),
                ]
                for _mult, _lbl, _dash, _w, _col in _sigma_levels:
                    _band_y = _vwap_s * (1.0 + (_mult * _sigma_pct) / 100.0)
                    _band_hover = [
                        f"VWAP {_lbl} ({_mult * _sigma_pct:+.2f}%): {yv:,.0f}" if pd.notna(yv) else ""
                        for yv in _band_y
                    ]
                    fig.add_trace(go.Scatter(
                        x=sub["date"],
                        y=_band_y,
                        mode="lines",
                        name=f"세력평단 {_lbl}",
                        line=dict(color=_col, width=_w, dash=_dash),
                        hovertext=_band_hover,
                        hoverinfo="text",
                        connectgaps=False,
                    ), row=price_row, col=1)

    # ---- 세력선1~4: 종목 선택 시 자동으로 계산된 시작일(19개월/12개월/50봉/5개월 이내 조건) ~
    # 오늘까지의 누적 세력평단(VWAP) 선. 표시구간(sub)과 무관하게 full_df 기준으로 계산한 뒤
    # 표시구간만 자른다. 세력선1이 세력선2/3/4에 가려져도 되도록 항상 먼저(맨 아래) 그린다. ----
    if seryeok_auto_dates:
        for _n, _style in SERYEOK_AUTO_LINE_STYLES.items():
            _rng = seryeok_auto_dates.get(_n)
            if not _rng:
                continue
            _line_series = compute_seryeok_line_range(full_df, _rng.get("start"), _rng.get("end"))
            fig.add_trace(go.Scatter(
                x=full_df.loc[_lb_mask, "date"], y=_line_series.loc[_lb_mask],
                mode="lines", name=_style["label"],
                line=dict(color=_style["color"], width=_style["width"]),
                connectgaps=True,
                hovertext=[f'{_style["label"]}: {v:,.0f}' if pd.notna(v) else "" for v in _line_series.loc[_lb_mask]],
                hoverinfo="text",
            ), row=price_row, col=1)

    # ---- 세력선1~4 (캔들 위에 보이는 얇은 버전): 위와 같은 시작일/색상을 그대로 쓰되
    # 굵기1로, 캔들과 같은 보조축(secondary_y)에 겹쳐 그려서 양봉/음봉 캔들보다 항상
    # 위에 보이게 한다(굵은 아래쪽 세력선이 캔들 몸통에 가려지더라도 이 얇은 선으로
    # 위치를 계속 확인할 수 있다). 범례 중복을 피하기 위해 legend는 표시하지 않는다. ----
    if seryeok_auto_dates:
        for _n, _style in SERYEOK_AUTO_LINE_STYLES.items():
            _rng = seryeok_auto_dates.get(_n)
            if not _rng:
                continue
            _line_series_top = compute_seryeok_line_range(full_df, _rng.get("start"), _rng.get("end"))
            fig.add_trace(go.Scatter(
                x=full_df.loc[_lb_mask, "date"], y=_line_series_top.loc[_lb_mask],
                mode="lines", name=f'{_style["label"]}(캔들위)',
                line=dict(color=_style["color"], width=_style.get("top_width", SERYEOK_AUTO_LINE_TOP_WIDTH)),
                connectgaps=True, hoverinfo="skip", showlegend=False,
            ), row=price_row, col=1, secondary_y=True)

    # ---- 연핑크선: a=Highest(H,60); b=Lowest(L,60); m=(a+b)/2 ----
    _hilo60_mid_full = compute_line_hilo60_mid(full_df)
    _hilo60_mask = full_df["date"].isin(sub["date"])
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo60_mask, "date"], y=_hilo60_mid_full.loc[_hilo60_mask],
        mode="lines", name="60봉 고저중간선",
        line=dict(color="#FF99CC", width=4),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 핑크선: a=Highest(H,120,가중); b=Lowest(L,120,가중); m=(a+b)/2 ----
    _hilo120_mid_full = compute_line_hilo120_mid(full_df)
    _hilo120_mask = full_df["date"].isin(sub["date"])
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_hilo120_mid_full.loc[_hilo120_mask],
        mode="lines", name="120봉 고저중간선",
        line=dict(color="#FF00FF", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 흰검정점선390분용 (분봉 차트와 같은 선): 130봉 거래량가중 평단, 흰 점선 굵기4 + 회색 밑받침 ----
    _add_white_dotted_vwap_pair(fig, full_df, sub, price_row, "흰검정점선390분용", 130, 1.0, 4)

    # ---- 벽돌색선: A=Disparity(120); D=ValueWhen(1, CrossUp(A,101) OR CrossDown(A,101), (H+L)/2) ----
    _disp120_line_full = compute_line_disparity120_valuewhen(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_disp120_line_full.loc[_hilo120_mask],
        mode="lines", name="이격도120 돌파선",
        line=dict(color="#CC3300", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 검정굵은선+핑크겹선: HighestSince(1, CrossUp(Trix(27),0), avg(C,1)) 동일 수식 2겹
    # (검정 굵기7을 먼저 그린 뒤 그 위에 핑크 굵기2를 겹쳐 그려 테두리 효과) ----
    _trix27_line_full = compute_line_trix_highestsince_close(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_trix27_line_full.loc[_hilo120_mask],
        mode="lines", name="Trix27 고점누적선(검정)",
        line=dict(color="#000000", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_trix27_line_full.loc[_hilo120_mask],
        mode="lines", name="Trix27 고점누적선(핑크)",
        line=dict(color="#FF00FF", width=2),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 핑크굵은선+검정겹선: HighestSince(1, CrossUp(Trix(45),0), avg(C,105)) 동일 수식 2겹
    # (핑크 굵기7을 먼저 그린 뒤 그 위에 검정 굵기3을 겹쳐 그려 테두리 효과) ----
    _trix45_line_full = compute_line_trix45_highestsince_avgc105(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_trix45_line_full.loc[_hilo120_mask],
        mode="lines", name="Trix45 고점누적선(핑크)",
        line=dict(color="#FF00FF", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_trix45_line_full.loc[_hilo120_mask],
        mode="lines", name="Trix45 고점누적선(검정)",
        line=dict(color="#000000", width=3),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 핑크선: a=avg(C,5); b=avg(C,20); d=avg(C,60); 대선=ValueWhen(...); 시세=ValueWhen(...);
    # 결과=ValueWhen(1, CrossUp(a,시세), a) ----
    _daeseon_line_full = compute_line_valuewhen_crossup_daeseon(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_daeseon_line_full.loc[_hilo120_mask],
        mode="lines", name="대선 시세돌파선",
        line=dict(color="#FE53FE", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 흰색선: A=SUM(IF(V>MA(V,20)*1.5, C*V, 0), 240); B=SUM(IF(V>MA(V,20)*1.5, V, 0), 240); A/B
    # (대량거래일 기준 240봉 VWAP, 기존 키움3신호 토글용 함수를 재사용) ----
    _white_bigvol_vwap_full = compute_kiwoom_line_white_bigvol_vwap(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_white_bigvol_vwap_full.loc[_hilo120_mask],
        mode="lines", name="대량거래VWAP(흰)",
        line=dict(color="#ffffff", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 흰굵은선+하늘색겹선: gb=ValueWhen(1, Highest(H(1),100)<Highest(H,100), (Highest(H,100)+Lowest(L,100))/2);
    # 결과=Highest(H,100)-((Highest(H,100)-gb)/5)*8  동일 수식 2겹
    # (흰 굵기7을 먼저 그린 뒤 그 위에 하늘색 굵기3을 겹쳐 그려 테두리 효과) ----
    _cyan2_support_full = compute_kiwoom_line_cyan2_support(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_cyan2_support_full.loc[_hilo120_mask],
        mode="lines", name="gb지지선(흰)",
        line=dict(color="#ffffff", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_cyan2_support_full.loc[_hilo120_mask],
        mode="lines", name="gb지지선(하늘)",
        line=dict(color="#00ccff", width=3),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 검정굵은선+파랑겹선: A=WMA(2*WMA(저가,60,가중)-WMA(저가,120,가중),Sqrt(120),가중);
    # B=EMA(C,50); 결과=ValueWhen(1, CrossDown(A,B), A)  동일 수식 2겹
    # (검정 굵기7을 먼저 그린 뒤 그 위에 파랑 굵기1을 겹쳐 그려 테두리 효과) ----
    _hma_low120_crossdown_full = compute_line_hma_low120_crossdown_ema50(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_hma_low120_crossdown_full.loc[_hilo120_mask],
        mode="lines", name="HMA저가120 하향돌파선(검정)",
        line=dict(color="#000000", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_hma_low120_crossdown_full.loc[_hilo120_mask],
        mode="lines", name="HMA저가120 하향돌파선(파랑)",
        line=dict(color="#0000FF", width=1),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 파란선: HighestSince(1, CrossDown(CCI(9),0), Highest(L,120)) ----
    _cci_line_full = compute_line_cci_crossdown_highest_low120(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_cci_line_full.loc[_hilo120_mask],
        mode="lines", name="CCI9 하향돌파 고점선",
        line=dict(color="#3333FF", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 자주색굵은선+흰색겹선: ValueWhen(1, avg(C,220)>avg(C,220,1), avg(C,220)) 동일 수식 2겹
    # (자주색 굵기7을 먼저 그린 뒤 그 위에 흰색 굵기2를 겹쳐 그려 테두리 효과) ----
    _ma220_rising_full = compute_line_valuewhen_ma220_rising(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_ma220_rising_full.loc[_hilo120_mask],
        mode="lines", name="MA220 상승유지선(자주)",
        line=dict(color="#800080", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_ma220_rising_full.loc[_hilo120_mask],
        mode="lines", name="MA220 상승유지선(흰)",
        line=dict(color="#ffffff", width=2),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 하늘색굵은선+흰겹선: CL=ValueWhen(1, Highest(H(1),120)<Highest(H,120), (Highest(H,20)+Lowest(L,20))/2);
    # TargetLine=Highest(H,20)-(((Highest(H,20)-CL)/5)*4)  동일 수식 2겹
    # (하늘색 굵기5를 먼저 그린 뒤 그 위에 흰색 굵기2를 겹쳐 그려 테두리 효과) ----
    _targetline_full = compute_line_targetline_cl_mixed(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_targetline_full.loc[_hilo120_mask],
        mode="lines", name="TargetLine(하늘)",
        line=dict(color="#00CCFF", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_targetline_full.loc[_hilo120_mask],
        mode="lines", name="TargetLine(흰)",
        line=dict(color="#ffffff", width=2),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 핑크굵은선+노랑겹선: AC/AV/BB/CC/DD/EE 조합 (거래량·종가 동시 신고가 돌파 후
    # 거래 소강+가격 재접근 구간 표시) 동일 수식 2겹
    # (핑크 굵기7을 먼저 그린 뒤 그 위에 노랑 굵기5를 겹쳐 그려 테두리 효과) ----
    _ac_breakout_full = compute_line_ac_breakout_cc(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_ac_breakout_full.loc[_hilo120_mask],
        mode="lines", name="AC돌파 재접근선(핑크)",
        line=dict(color="#FE53FE", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_ac_breakout_full.loc[_hilo120_mask],
        mode="lines", name="AC돌파 재접근선(노랑)",
        line=dict(color="#FFFF00", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 키움 3신호 (Disparity / MA+거래량 / BBands+Envelope 조합) ----
    if show_kiwoom3:
        # ---- 주황색선 / 하늘색선 (계단식 저항·돌파 라인) ----
        _orange_line_full = compute_kiwoom_line_orange_ssch0(full_df)
        _cyan_line_full = compute_kiwoom_line_cyan_hh(full_df)
        _line_mask = full_df["date"].isin(sub["date"])
        _line_dates = full_df.loc[_line_mask, "date"]

        fig.add_trace(go.Scatter(
            x=_line_dates, y=_orange_line_full.loc[_line_mask],
            mode="lines", name="sscH0(주황)",
            line=dict(color="#f5871f", width=2.5),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_cyan_line_full.loc[_line_mask],
            mode="lines", name="HH선(연하늘)",
            line=dict(color="#ccffff", width=2.5),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 벽돌색선 2개 (7지표 합성 ValueWhen선 / TEMA20 중심선) ----
        _composite_line_full = compute_kiwoom_line_composite_signal(full_df)
        _tema_center_full = compute_kiwoom_line_tema_center(full_df)

        fig.add_trace(go.Scatter(
            x=_line_dates, y=_composite_line_full.loc[_line_mask],
            mode="lines", name="합성신호선",
            line=dict(color="#cc3300", width=4),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_tema_center_full.loc[_line_mask],
            mode="lines", name="TEMA20 중심선",
            line=dict(color="#cc3300", width=1.5, dash="dot"),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 보라색선 (TRIX(12) 0선 상향돌파 이후 고가 누적 최고값) ----
        _purple_line_full = compute_kiwoom_line_purple_highestsince(full_df)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_purple_line_full.loc[_line_mask],
            mode="lines", name="TRIX 고점누적선",
            line=dict(color="#9933ff", width=3),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 하늘색선2 (100봉 신고가 기준 gb 지지선) ----
        _cyan2_line_full = compute_kiwoom_line_cyan2_support(full_df)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_cyan2_line_full.loc[_line_mask],
            mode="lines", name="gb지지선",
            line=dict(color="#00ccff", width=3),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 하늘색선3 (25~80봉전 구간 최고/최저 중간값, 지연 채널중심선) ----
        _cyan3_line_full = compute_kiwoom_line_cyan3_channel_mid(full_df)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_cyan3_line_full.loc[_line_mask],
            mode="lines", name="채널중심선",
            line=dict(color="#00ffff", width=3),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 흰색선 (대량거래일 기준 240봉 VWAP, 가장 굵은 선) ----
        _white_line_full = compute_kiwoom_line_white_bigvol_vwap(full_df)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_white_line_full.loc[_line_mask],
            mode="lines", name="대량거래VWAP",
            line=dict(color="#ffffff", width=5),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        # ---- 핑크 세로선 (강세패턴: 신호4와 동일 조건, 키움 '강세약세' 스타일 수직선) ----
        _pink_mask_full = compute_kiwoom_signal4_bigmove(full_df)
        _pink_dates = full_df.loc[_pink_mask_full & _line_mask, "date"]
        for _pd in _pink_dates:
            fig.add_vline(
                x=pd.Timestamp(_pd), line_color="#ff66cc", line_width=1.3, opacity=0.9,
                row=price_row, col=1,
            )

        # ---- 세력라인 4개 (HMA 기반 Highest 3개 + Trix(20) 계단선) ----
        _seryeok_line_specs = [
            (compute_seryeok_line_hull_highest(full_df, 77, 44), "세력라인1(77/44)", "#99CC00", 5),
            (compute_seryeok_line_trix_step(full_df, 20), "세력라인4(Trix계단)", "#CC99FF", 2),
        ]
        for _sl_series, _sl_name, _sl_color, _sl_width in _seryeok_line_specs:
            fig.add_trace(go.Scatter(
                x=_line_dates, y=_sl_series.loc[_line_mask],
                mode="lines", name=_sl_name,
                line=dict(color=_sl_color, width=_sl_width),
                connectgaps=True, hoverinfo="skip",
            ), row=price_row, col=1)

        # 세력라인2(110/35)/세력라인3(60/30)는 가장 잘 보이도록 이 블록의 다른 모든 라인선보다
        # 위에 그려야 하므로, 여기서는 계산만 해두고 실제 add_trace는 5/20/60/120/240일 이평선
        # 바로 앞(맨 마지막 직전)에서 수행한다. (아래쪽 코드 참고)
        _seryeok_line2_series = compute_seryeok_line_hull_highest(full_df, 110, 35)
        _seryeok_line3_series = compute_seryeok_line_hull_highest(full_df, 60, 30)

        # ---- 신호1/2/3 마커: 이 블록의 모든 라인선보다 위에 그려지도록 맨 마지막에 추가 ----
        _k3_specs = [
            ("kiwoom_sig1", compute_kiwoom_signal1_disparity, "신호1(이격도)", "#1a237e", "below", 0.97),  # 남색, 캔들 아래
            ("kiwoom_sig2", compute_kiwoom_signal2_ma_volume, "신호2(이평+거래량)", "#8bc34a", "above", 1.03),  # 연두색, 캔들 위
            ("kiwoom_sig3", compute_kiwoom_signal3_bbands_envelope, "신호3(볼밴+엔벨로프)", "#ffffff", "above", 1.06),  # 흰색, 캔들 위
        ]
        for _key, _fn, _label, _color, _pos, _y_ratio in _k3_specs:
            _k3_mask_full = _fn(full_df)
            _k3_full = full_df.loc[_k3_mask_full]
            _k3_in_range = _k3_full[_k3_full["date"].isin(sub["date"])]
            if not _k3_in_range.empty:
                if _pos == "above":
                    _k3_y = _k3_in_range["high"] * _y_ratio
                    _k3_symbol = "triangle-down"
                else:
                    _k3_y = _k3_in_range["low"] * _y_ratio
                    _k3_symbol = "triangle-up"
                fig.add_trace(go.Scatter(
                    x=_k3_in_range["date"], y=_k3_y,
                    mode="markers", name=_label,
                    marker=dict(symbol=_k3_symbol, size=10, color=_color,
                                line=dict(width=1, color="#333333")),
                    hovertext=[f"{_label} ({d.strftime('%Y-%m-%d')})" for d in _k3_in_range["date"]],
                    hoverinfo="text",
                ), row=price_row, col=1)

    # ---- 세력라인2(110/35)/세력라인3(60/30): 다른 모든 라인선보다 위, 5/20/60/120/240일선보다는
    # 아래에 보이도록 이 시점에 추가한다. (요청에 따라 굵기 변경: 110/35=2, 60/30=4, 둘 다 연보라) ----
    if show_kiwoom3:
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_seryeok_line2_series.loc[_line_mask],
            mode="lines", name="세력라인2(110/35)",
            line=dict(color="#CC99FF", width=2),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        fig.add_trace(go.Scatter(
            x=_line_dates, y=_seryeok_line3_series.loc[_line_mask],
            mode="lines", name="세력라인3(60/30)",
            line=dict(color="#CC99FF", width=4),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

    # ---- 주황선(맨앞): A=WMA(2*WMA(종가,26,가중)-WMA(종가,52,가중),Sqrt(52),가중); sscH0=Highest(A,80) ----
    _hma52_highest80_full = compute_seryeok_line_hull_highest(full_df, 52, 80)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_hma52_highest80_full.loc[_hilo120_mask],
        mode="lines", name="HMA52 고점선(80)",
        line=dict(color="#FF6600", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 연두형광선: ValueWhen(1, avg(C,155)<avg(C,155,1), avg(C,155))
    # (155일 이평선이 직전 봉보다 하락 중일 때의 값으로 계단식 유지) (파랑 겹선 제거, 단일 라인) ----
    _ma155_falling_full = compute_line_valuewhen_ma_falling(full_df, n=155)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_ma155_falling_full.loc[_hilo120_mask],
        mode="lines", name="MA155 하락유지선(연두)",
        line=dict(color="#6FFF25", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 신규 라인 4(다른 라인들보다 앞/이동평균선보다 뒤, 연두노랑): a=Highest(H,40,159);
    # b=Lowest(L,40,159); m=(a+b)/2 ----
    _newline4_full = compute_line_hilo_mid_shifted(full_df, window=40, shift=159)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline4_full.loc[_hilo120_mask],
        mode="lines", name="40봉 고저중간선(159, 이평선 바로 뒤)",
        line=dict(color="#CCFF33", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 검정선(굵기5, 이평선보다 뒤): (Highest(H,78)+Lowest(L,78))/2
    # + 그 위에 같은 수식의 파랑 겹선(굵기2) ----
    _newline5_full = compute_line_hilo_mid78(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline5_full.loc[_hilo120_mask],
        mode="lines", name="78봉 고저중간선(검정)",
        line=dict(color="#000000", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline5_full.loc[_hilo120_mask],
        mode="lines", name="78봉 고저중간선(파랑)",
        line=dict(color="#0000FF", width=2),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 갈색선(굵기5, 이평선보다 뒤): HighestSince(1, CrossUp(Trix(20),0), avg(C,20)) ----
    _newline6_full = compute_line_trix20_crossup_highestsince_ma20(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline6_full.loc[_hilo120_mask],
        mode="lines", name="Trix20 상향돌파 고점유지선",
        line=dict(color="#996600", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 청록선(굵기7, 다른 선들보다 뒤): A=Highest(Lowest(L,400)+ATR(400),87);
    # B=Lowest(Highest(H,400)-ATR(400),87); D=(A+B)/2; E=ValueWhen(1,CrossUp(C,D) or CrossDown(C,D),O) ----
    _newline7_full = compute_line_atr400_band_crossflip_open(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline7_full.loc[_hilo120_mask],
        mode="lines", name="ATR400밴드 교차유지선",
        line=dict(color="#33CCCC", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- (굵기6, 이평선보다 뒤): avg(wavg(O,240),240) + 2*stdev(wavg(O,240),240) ----
    _newline9_full = compute_line_wavg_open_band(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline9_full.loc[_hilo120_mask],
        mode="lines", name="시가 WMA240 밴드상단선",
        line=dict(color="#00CED1", width=6),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 점선(굵기5): shift(MA(종가,40,단순)+2*stdev((C+H+L)/3,40), 25) ----
    _newline10_full = compute_line_ma40_typical_stdev_shifted(full_df, n=40, shift=25)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline10_full.loc[_hilo120_mask],
        mode="lines", name="MA40+2σ 밴드선(25봉 시프트)",
        line=dict(color="#00FF99", width=5, dash="dot"),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 빨간선(굵기5): BBandsUp(300,2) = avg(C,300)+2*stdev(C,300) ----
    _newline11_full = compute_line_bbands_up(full_df, n=300, mult=2)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_newline11_full.loc[_hilo120_mask],
        mode="lines", name="볼린저밴드 상단(300,2)",
        line=dict(color="#FF0000", width=5),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 5/20/60/120/240일 이평선: 다른 추가 라인선(세력라인/키움3신호 등)보다 항상 위에
    # 보이도록, 그 라인들을 모두 그린 뒤 이 시점에 최상단으로 추가한다. ----
    for p in MA_PERIODS:
        _ma_line_width = 2.4 if p == 60 else 1.4
        if p in _EMPHASIS_MA_PERIODS:
            _ma_line_width += _MA_WIDTH_STEP
        fig.add_trace(go.Scatter(
            x=sub["date"], y=sub[f"ma{p}"], mode="lines", name=f"{p}일선",
            line=dict(color=DAILY_MA_COLORS[p], width=_ma_line_width),
            hoverinfo="skip",
            connectgaps=True,
        ), row=price_row, col=1)
        _ma_last_series = sub[f"ma{p}"].dropna()
        if not _ma_last_series.empty and _last_vwap_for_ma:
            _ma_last_val = float(_ma_last_series.iloc[-1])
            _ma_gap_d = (_ma_last_val - _last_vwap_for_ma) / _last_vwap_for_ma * 100
            _ma_gap_d_color = "#f4a6a6" if _ma_gap_d >= 0 else "#a6c8f4"
            fig.add_annotation(
                xref="paper", x=1.005, xanchor="left",
                yref="y", y=_ma_last_val, yanchor="middle",
                text=f"{p}선({_ma_gap_d:+.2f}%)", showarrow=False,
                font=dict(color=_ma_gap_d_color, size=11, family="Arial, sans-serif"),
                align="left",
                row=price_row, col=1,
            )

    # ---- CL지지선: CL=ValueWhen(1, Highest(H(1),60)<Highest(H,60), (Highest(H,400)+Lowest(L,60))/2);
    # 결과=Highest(H,60)-(((Highest(H,60)-CL)/5)*10)
    # (다른 모든 라인선/이평선보다도 위에 보이도록 이평선 루프 뒤에 맨 마지막으로 배치) ----
    _cl_highest60_full = compute_line_cl_highest60_lowest60(full_df)
    fig.add_trace(go.Scatter(
        x=full_df.loc[_hilo120_mask, "date"], y=_cl_highest60_full.loc[_hilo120_mask],
        mode="lines", name="CL지지선(연노랑, 맨위)",
        line=dict(color="#FFFF99", width=7),
        connectgaps=True, hoverinfo="skip",
    ), row=price_row, col=1)

    # ---- 신호(연보라 세모): 모든 라인선보다 위에 그려지도록 라인 트레이스들 뒤에 배치 ----
    if show_signal:
        _sig_mask_full = compute_yellow_arrow_signal(full_df)
        _sig_full = full_df.loc[_sig_mask_full]
        _sig_in_range = _sig_full[_sig_full["date"].isin(sub["date"])]
        if not _sig_in_range.empty:
            fig.add_trace(go.Scatter(
                x=_sig_in_range["date"], y=_sig_in_range["high"] * 1.03,
                mode="markers", name="신호",
                marker=dict(symbol="triangle-down", size=11, color="#c9a0ff",
                            line=dict(width=1, color="#7d4fb5")),
                hovertext=[f"신호 발생 ({d.strftime('%Y-%m-%d')})" for d in _sig_in_range["date"]],
                hoverinfo="text",
            ), row=price_row, col=1)

        # ---- 이화살표신호(초록 #00ff00, 세모): A=avg(C,20); B=avg(C,60); CrossUp(A,B) ----
        _ma_crossup_mask_full = compute_ma20_60_crossup_signal(full_df)
        _ma_crossup_full = full_df.loc[_ma_crossup_mask_full]
        _ma_crossup_in_range = _ma_crossup_full[_ma_crossup_full["date"].isin(sub["date"])]
        if not _ma_crossup_in_range.empty:
            fig.add_trace(go.Scatter(
                x=_ma_crossup_in_range["date"], y=_ma_crossup_in_range["low"] * 0.95,
                mode="markers", name="이화살표신호",
                marker=dict(symbol="triangle-up", size=11, color="#00ff00",
                            line=dict(width=1, color="#008800")),
                hovertext=[f"이화살표신호 ({d.strftime('%Y-%m-%d')})" for d in _ma_crossup_in_range["date"]],
                hoverinfo="text",
            ), row=price_row, col=1)

        # ---- 이수식 신호(노랑 #ffff00, 별표 ＊) ----
        _star_mask_full = compute_isusik_star_signal(full_df)
        _star_full = full_df.loc[_star_mask_full]
        _star_in_range = _star_full[_star_full["date"].isin(sub["date"])]
        if not _star_in_range.empty:
            fig.add_trace(go.Scatter(
                x=_star_in_range["date"], y=_star_in_range["low"] * 0.93,
                mode="markers", name="이수식신호",
                marker=dict(symbol="star", size=13, color="#ffff00",
                            line=dict(width=1, color="#b3b300")),
                hovertext=[f"이수식신호 ({d.strftime('%Y-%m-%d')})" for d in _star_in_range["date"]],
                hoverinfo="text",
            ), row=price_row, col=1)

        # ---- 이신호(연노랑 #feff7a, 동그라미 ●): a=avg(C,120); b=avg(C,1); CrossUp(b,a) ----
        _circle_mask_full = compute_isusik_circle_signal(full_df)
        _circle_full = full_df.loc[_circle_mask_full]
        _circle_in_range = _circle_full[_circle_full["date"].isin(sub["date"])]
        if not _circle_in_range.empty:
            fig.add_trace(go.Scatter(
                x=_circle_in_range["date"], y=_circle_in_range["low"] * 0.91,
                mode="markers", name="이신호",
                marker=dict(symbol="circle", size=10, color="#feff7a",
                            line=dict(width=1, color="#b3b300")),
                hovertext=[f"이신호 ({d.strftime('%Y-%m-%d')})" for d in _circle_in_range["date"]],
                hoverinfo="text",
            ), row=price_row, col=1)

    # ---- 신호 스트립(on/off 버튼 없이 항상 표시): 캔들 차트 바로 아래, 거래대금 바로 위에
    # 신호 8종을 각자 고정된 세로 레인(1~8)에 모아 찍는다. 같은 날 여러 신호가 겹치면
    # 세로로 쌓여 보인다. ----
    _signal_defs = [(_n, _fn(full_df), _sym, _col) for (_n, _fn, _sym, _col) in DAILY_SIGNAL_SPECS]
    for _lane, (_sig_name, _sig_mask_full, _sig_symbol, _sig_color) in enumerate(_signal_defs, start=1):
        # x축을 표시구간 전체 날짜로 채우고, 신호가 뜬 날만 y값을 넣고 나머지는 NaN으로 비워서 표시.
        # (마커는 순전히 시각 표시용이며, 아래 '통합 호버용' 트레이스가 날짜별 정확한 툴팁을 담당)
        _sig_on_sub = _sig_mask_full.reindex(sub.index).fillna(False)
        if not _sig_on_sub.any():
            continue
        _y = pd.Series(np.where(_sig_on_sub, _lane, np.nan), index=sub.index)
        fig.add_trace(go.Scatter(
            x=sub["date"], y=_y,
            mode="markers", name=_sig_name,
            marker=dict(symbol=_sig_symbol, size=9, color=_sig_color,
                        line=dict(width=1, color="#333333")),
            hoverinfo="skip",
            connectgaps=False,
            showlegend=show_legend,
        ), row=signal_row, col=1)

    # ---- 통합 호버용 트레이스: hovermode="x unified"가 신호가 없는 날짜에도 '가장 가까운 신호
    # 날짜'로 당겨붙여 서로 다른 신호의 날짜가 뒤섞여 보이는 문제를 막기 위해, 표시구간의 모든
    # 날짜에 점을 둔 트레이스 1개를 따로 만들고, 그 날 실제로 뜬 신호 이름들만 묶어 보여준다
    # (항상 정확히 그 날짜의 점이 잡히므로 날짜가 섞일 수 없다). ----
    _sig_text_by_date = pd.Series([""] * len(sub), index=sub.index)
    for _sig_name, _sig_mask_full, _sig_symbol, _sig_color in _signal_defs:
        _sig_on_sub = _sig_mask_full.reindex(sub.index).fillna(False)
        _sig_text_by_date = _sig_text_by_date.where(
            ~_sig_on_sub,
            _sig_text_by_date + f"{SIGNAL_MARKER_GLYPH.get(_sig_symbol, '•')} {_sig_name}<br>")
    fig.add_trace(go.Scatter(
        x=sub["date"], y=[(len(_signal_defs) + 1) / 2] * len(sub),
        mode="markers", marker=dict(size=0, opacity=0), name="",
        text=_sig_text_by_date,
        hovertemplate="%{text}<extra></extra>",
        showlegend=False,
    ), row=signal_row, col=1)
    fig.update_yaxes(
        visible=False, showgrid=False, zeroline=False,
        range=[0.5, len(_signal_defs) + 0.5],  # 레인 상하 여백을 최소화해 빡빡하게 배치
        row=signal_row, col=1,
    )
    fig.update_xaxes(showgrid=False, row=signal_row, col=1)

    # ---- 거래대금 보조지표 (일봉: 종가×거래량, 억원 단위) ----
    if show_volume:
        trade_won_d = sub["close"] * sub["volume"]
        trade_eok_d = trade_won_d / 100_000_000
        bar_colors_d = [_vol_color(v, VOL_COLOR_BANDS_DAILY) for v in trade_eok_d]
        fig.add_trace(go.Bar(
            x=sub["date"], y=trade_eok_d, name="거래대금",
            marker_color=bar_colors_d,
            hovertemplate="거래대금: %{y:,.1f}억<extra></extra>",
            showlegend=False,
        ), row=vol_row, col=1)
        fig.update_yaxes(
            title_text="거래대금(억)", side="right", showgrid=True, gridcolor="#e5e5e5",
            tickformat=",.0f", tickfont=dict(color="white", size=9), title_font=dict(color="white", size=10),
            row=vol_row, col=1,
        )

    last_vwap = _last_vwap_for_ma
    last_close = float(sub["close"].iloc[-1])
    gap_pct = (last_close - last_vwap) / last_vwap * 100 if last_vwap else 0.0
    close_color = CANDLE_UP if gap_pct >= 0 else CANDLE_DOWN

    fig.add_annotation(
        xref="paper", x=1.005, xanchor="left",
        yref="y", y=last_vwap, yanchor="bottom",
        text=f"세 {last_vwap:,.0f}", showarrow=False,
        font=dict(color="#000000", size=12, family="Arial, sans-serif"),
        align="left",
        row=price_row, col=1,
    )
    fig.add_annotation(
        xref="paper", x=1.005, xanchor="left",
        yref="y", y=last_close, yanchor="top",
        text=f"현 {last_close:,.0f} ({gap_pct:+.2f}%)", showarrow=False,
        font=dict(color=close_color, size=12, family="Arial, sans-serif"),
        align="left",
        row=price_row, col=1,
    )

    fig.update_layout(
        plot_bgcolor="#dddddd", paper_bgcolor=CARD_BG, font=dict(color="white"),
        showlegend=show_legend,
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center", font=dict(color="#111111", size=11),
                    bgcolor="rgba(255,255,255,0.96)", bordercolor="#9aa0a8", borderwidth=1),
        margin=dict(l=40, r=35, t=(35 if show_legend else 15), b=40), hovermode="x unified",
        height=_total_height,
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(color="white"), rangeslider=dict(visible=False),
                      hoverformat="%-m, %d. %Y")
    # 서브플롯(거래대금) 추가 후 x축 자동범위가 과거 전체 데이터로 확장되는 것을 막기 위해
    # 실제 표시 구간(sub)의 최소~최대 날짜로 명시적으로 고정한다.
    # '일날짜크기' 버튼으로 개월수를 골랐으면, 데이터 자체(sub/이평선/세력평단 계산)는 그대로
    # 두고 화면에 처음 보여줄 x축 범위만 최근 N개월로 좁힌다(왼쪽으로 드래그/줌아웃하면
    # 그 이전 데이터도 그대로 남아있어 다시 볼 수 있다).
    _xaxis_min = sub["date"].min()
    _xaxis_max = sub["date"].max()
    if view_months:
        _view_min = _xaxis_max - pd.DateOffset(months=view_months)
        if _view_min > _xaxis_min:
            _xaxis_min = _view_min
    # 오른쪽 끝에 다음 영업일 1칸 여유를 줘서 마지막(오늘) 캔들이 잘려 보이지 않게 함 (키움처럼)
    # (금요일이면 +1일이 토요일이라 건너뛰어져 여유가 사라지므로 '영업일' 기준으로 더한다)
    fig.update_xaxes(type="date", range=[_xaxis_min, _xaxis_max + pd.offsets.BDay(1)])
    # 키움처럼 캔들이 촘촘하게 이어지도록 주말(토·일)과, 평일인데 데이터가 없는 날(공휴일 등)의
    # 빈 칸을 가로축에서 건너뛴다.
    _all_bdays = pd.bdate_range(sub["date"].min().normalize(), sub["date"].max().normalize())
    _missing_bdays = _all_bdays.difference(pd.DatetimeIndex(sub["date"]).normalize())
    _rb = [dict(bounds=["sat", "mon"])]
    if len(_missing_bdays):
        _rb.append(dict(values=[d.strftime("%Y-%m-%d") for d in _missing_bdays]))
    fig.update_xaxes(rangebreaks=_rb)
    fig.update_xaxes(tickformat="%m", row=(vol_row if show_volume else signal_row), col=1)
    fig.update_xaxes(showticklabels=False, row=price_row, col=1)
    if show_volume:
        fig.update_xaxes(showticklabels=False, row=signal_row, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", tickformat=",.0f",
                      tickfont=dict(color="white"), row=price_row, col=1)

    # ---- 키움 '비율차트'처럼 Y축을 기준가(표시구간 첫 종가) 대비 등락률(%)로 표시 ----
    _pct_ref = float(sub["close"].iloc[0])
    _pct_low = float(min(sub["low"].min(), sub["close"].min()))
    _pct_high = float(max(sub["high"].max(), sub["close"].max()))
    _pct_tickvals, _pct_ticktext = _percent_axis_ticks(_pct_low, _pct_high, _pct_ref)
    if _pct_tickvals:
        fig.update_yaxes(
            tickmode="array", tickvals=_pct_tickvals, ticktext=_pct_ticktext,
            row=price_row, col=1,
        )

    # 캔들을 보조축(secondary_y)으로 옮기면서 주축의 자동범위가 캔들 고저가 아닌 다른 라인선들만
    # 기준으로 계산될 수 있어, 실제 캔들 고저(+여유폭)를 주축 범위로 명시 고정한다.
    # (보조축은 아래에서 matches="y"로 이 범위를 그대로 따라간다)
    _price_range_pad = (_pct_high - _pct_low) * 0.03 if _pct_high > _pct_low else max(_pct_high, 1.0) * 0.03
    fig.update_yaxes(
        range=[_pct_low - _price_range_pad, _pct_high + _price_range_pad],
        row=price_row, col=1,
    )

    if nwave_info and nwave_info.get("targets"):
        _chart_cur_price = nwave_info.get("current_price") or last_close
        for key, label, _, _color in N_WAVE_T_META:
            val = nwave_info["targets"][key]
            _t_gap = (val - _chart_cur_price) / _chart_cur_price * 100 if _chart_cur_price else 0.0
            fig.add_hline(
                y=val, line_dash="dash", line_color=NWAVE_TARGET_COLOR, line_width=NWAVE_TARGET_LINE_WIDTH,
                annotation_text=f"{key}({label}) {_t_gap:+.2f}%", annotation_font_size=10,
                annotation_font_color=NWAVE_TARGET_COLOR, annotation_position="right",
                row=price_row, col=1,
            )

    # ---- 관심종목 최초 저장일: 초록 점선 + "관심"/날짜/괴리율 3줄 라벨 (표시 구간 안에 있을 때만) ----
    if watch_added_date is not None:
        _sub_min_date = sub["date"].min().date()
        _sub_max_date = sub["date"].max().date()
        if _sub_min_date <= watch_added_date <= _sub_max_date:
            fig.add_vline(
                x=pd.Timestamp(watch_added_date), line_dash="dot", line_color="#2ecc71",
                line_width=1.3, opacity=0.9,
                row=price_row, col=1,
            )
            _watch_idx = _nearest_row_idx(full_df, watch_added_date)
            _watch_base_price = (
                float(full_df.loc[_watch_idx, "close"]) if _watch_idx is not None else None
            )
            _watch_gap_pct = None
            if _watch_base_price:
                _cur_price_for_watch = float(sub["close"].iloc[-1])
                _watch_gap_pct = (_cur_price_for_watch - _watch_base_price) / _watch_base_price * 100
            _wg_line_color = "#ff4fa3" if (_watch_gap_pct or 0) >= 0 else "#00e5ff"
            _wg_line_text = f"{_watch_gap_pct:+.2f}%" if _watch_gap_pct is not None else "-"

            # 한 줄에 "관심 / 날짜(초록,큰글씨) / 괴리율(핑크·형광파랑,큰글씨)"를 가로로 여백없이 붙여서 표시
            _wg_rich_text = (
                f'<span style="color:#9aa4b8; font-size:13px;">관심 </span>'
                f'<span style="color:#2ecc71; font-size:28px;">{watch_added_date.strftime("%m/%d")} </span>'
                f'<span style="color:{_wg_line_color}; font-size:28px;">{_wg_line_text}</span>'
            )
            fig.add_annotation(
                x=pd.Timestamp(watch_added_date), xref="x", y=0.95, yref="y domain",
                text=_wg_rich_text, showarrow=False, align="center",
                font=dict(family="sans-serif"),
                row=price_row, col=1,
            )

    # ---- '요'/'테요' 로컬 스냅샷 조회일: 종목을 그 팝오버에서 골라 과거 날짜 데이터로 이동해왔을 때,
    # 그 조회 기준 날짜를 흰색 점선으로 표시 (표시 구간 안에 있을 때만) ----
    if local_snapshot_date is not None:
        _sub_min_date2 = sub["date"].min().date()
        _sub_max_date2 = sub["date"].max().date()
        if _sub_min_date2 <= local_snapshot_date <= _sub_max_date2:
            fig.add_vline(
                x=pd.Timestamp(local_snapshot_date), line_dash="dot", line_color="#ffffff",
                line_width=1.3, opacity=0.9,
                row=price_row, col=1,
            )
            fig.add_annotation(
                x=pd.Timestamp(local_snapshot_date), xref="x", y=0.88, yref="y domain",
                text=(
                    f'<span style="color:#9aa4b8; font-size:13px;">로컬 </span>'
                    f'<span style="color:#ffffff; font-size:22px;">{local_snapshot_date.strftime("%m/%d")}</span>'
                ),
                showarrow=False, align="center",
                font=dict(family="sans-serif"),
                row=price_row, col=1,
            )

    # ---- '목표' 패널의 시작일 / 5이평 언덕 날짜 / 세력평단가 날짜: 흰색 세로 점선 + 작은 라벨로
    # 표시 (표시 구간 안에 있을 때만). 시작일은 '목표' 자동 세팅으로 최근 날짜로 당겨져 있어도
    # 차트 자체는 넓게 표시되므로, 이 점선으로 실제 시작일 위치를 눈으로 바로 확인할 수 있다. ----
    if nwave_marker_dates:
        _nw_sub_min = sub["date"].min().date()
        _nw_sub_max = sub["date"].max().date()
        _nw_marker_specs = (
            ("start", "시작"), ("sma5", "5이평"), ("avg", "세력평단"),
        )
        for _nw_key, _nw_label in _nw_marker_specs:
            _nw_date = nwave_marker_dates.get(_nw_key)
            if _nw_date is None or not (_nw_sub_min <= _nw_date <= _nw_sub_max):
                continue
            fig.add_vline(
                x=pd.Timestamp(_nw_date), line_dash="dot", line_color="#ffffff",
                line_width=1.3, opacity=0.9,
                row=price_row, col=1,
            )
            fig.add_annotation(
                x=pd.Timestamp(_nw_date), xref="x", y=1.0, yref="y domain", yanchor="bottom",
                text=(
                    f'<span style="color:#ffffff; font-size:11px;">{_nw_label} '
                    f'{_nw_date.strftime("%m/%d")}</span>'
                ),
                showarrow=False, align="center", textangle=-90,
                font=dict(family="sans-serif"),
                row=price_row, col=1,
            )

    # 캔들을 그린 보조축(secondary_y)을 주축과 정확히 같은 범위로 맞추고, 눈금/격자는 숨겨서
    # 실제로는 안 보이지만 캔들만 다른 모든 선(주축 scatter)보다 위에 그려지도록 한다.
    fig.update_yaxes(
        matches="y", showticklabels=False, showgrid=False, zeroline=False,
        secondary_y=True, row=price_row, col=1,
    )

    st.plotly_chart(
        fig, use_container_width=True,
        config={"locale": "ko", "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
    )

def _compute_signal1_lines(df: pd.DataFrame):
    """'신호1' 분차트틀 전용 추가 라인 계산.
    COND = V > MA(V,20)*2  (거래량이 20봉 평균거래량의 2배를 초과하는 구간)
    평단(80봉):     A=SUM(IF(COND,C*V,0),80);  B=SUM(IF(COND,V,0),80);  평단=A/B
    세력평단(120봉): A=SUM(IF(COND,C*V,0),120); B=SUM(IF(COND,V,0),120); 세력평단=A/B
    반환: (평단 시리즈, 세력평단 시리즈)"""
    vol = df["volume"]
    close = df["close"]
    vol_ma20 = vol.rolling(20).mean()
    cond = vol > (vol_ma20 * 2)
    cv_cond = (close * vol).where(cond, 0.0)
    v_cond = vol.where(cond, 0.0)

    a80 = cv_cond.rolling(80).sum()
    b80 = v_cond.rolling(80).sum()
    pyeongdan = a80 / b80.replace(0, np.nan)

    a120 = cv_cond.rolling(120).sum()
    b120 = v_cond.rolling(120).sum()
    seryeok_pyeongdan = a120 / b120.replace(0, np.nan)

    return pyeongdan, seryeok_pyeongdan


def build_period_ohlcv(code: str, period: str) -> pd.DataFrame:
    """주봉/월봉 데이터: 일봉(네이버 + 오늘 분봉 보정)을 주(금요일 마감)/월 단위로 묶어서 만든다.
    열: datetime(그 기간의 마지막 거래일), open, high, low, close, volume. 진행 중인 이번 주/이번 달 봉도 포함."""
    daily = fetch_daily_ohlcv_with_today(code)
    if daily is None or daily.empty:
        return pd.DataFrame()
    g = daily.set_index("date").sort_index()
    rules = ["W-FRI"] if period == "주봉" else ["ME", "M"]
    agg = None
    last_day = None
    for rule in rules:
        try:
            agg = g.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last", "volume": "sum"})
            last_day = g.index.to_series().resample(rule).max()
            break
        except (ValueError, TypeError):
            continue
    if agg is None:
        return pd.DataFrame()
    agg = agg.dropna(subset=["open", "close"])
    out = agg.copy()
    out["datetime"] = last_day.reindex(out.index).values
    out = out.dropna(subset=["datetime"]).reset_index(drop=True)
    return out[["datetime", "open", "high", "low", "close", "volume"]]


def compute_period_seryeok_lines(full: pd.DataFrame):
    """주봉/월봉 세력평단 점선 계산.
    - 정배열 = 20봉선 > 60봉선, 역배열 = 20봉선 < 60봉선. '역배열초' = 정배열에서 역배열로 바뀌는 첫 봉.
    - 고점세력평단: 가장 최근 '역배열초' 직전의 정배열 구간에서 고가가 가장 높은 봉(역배열되기 전 최고점)부터
      현재까지의 거래량가중 평균(누적(종가×거래량)/누적거래량).
    - 하단세력평단: 그 고점 이후 저가가 가장 낮은 봉(최저점)부터 현재까지의 같은 방식 평균.
    반환: dict(cross_dn=역배열초 bool Series, high_line, low_line=Series 또는 None, high_idx, low_idx)"""
    c = full["close"].astype(float)
    v = full["volume"].fillna(0).astype(float)
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    valid = ma20.notna() & ma60.notna()
    up = (ma20 > ma60) & valid
    dn = (ma20 < ma60) & valid
    cross_dn = dn & up.shift(1, fill_value=False)
    res = {"cross_dn": cross_dn, "high_line": None, "low_line": None, "high_idx": None, "low_idx": None}
    ks = np.flatnonzero(cross_dn.values)
    if len(ks) == 0:
        return res
    k = int(ks[-1])
    p0 = k - 1
    while p0 - 1 >= 0 and bool(up.iloc[p0 - 1]):
        p0 -= 1
    seg = full["high"].iloc[p0:k]
    if seg.empty:
        return res
    peak = int(np.nanargmax(seg.values)) + p0

    def vwap_from(a: int) -> pd.Series:
        cv = (c * v).iloc[a:].cumsum()
        vv = v.iloc[a:].cumsum()
        out = pd.Series(np.nan, index=full.index)
        out.iloc[a:] = (cv / vv.where(vv > 0)).values
        return out

    res["high_line"] = vwap_from(peak)
    res["high_idx"] = peak
    after = full["low"].iloc[peak + 1:]
    if len(after) > 0:
        low_i = int(np.nanargmin(after.values)) + peak + 1
        res["low_line"] = vwap_from(low_i)
        res["low_idx"] = low_i
    return res


def render_period_chart(code: str, name: str, period: str, fill_candles: bool = False):
    """분봉 자리에 보여주는 주봉/월봉 차트: 캔들 + 5/20/60/120봉선 + 20/60 구름대 + 거래량.
    이동평균은 전체 기간으로 계산하고, 화면에는 주봉 최근 3년 / 월봉 최근 10년만 보여준다."""
    full = build_period_ohlcv(code, period)
    if full.empty:
        st.warning(f"{period} 데이터를 불러오지 못했습니다.")
        return
    view_n = 156 if period == "주봉" else 120
    n_full = len(full)
    start_i = max(0, n_full - view_n)
    df = full.iloc[start_i:].reset_index(drop=True)

    # 세로 공간: 캔들 영역은 약 232px 그대로 두고 거래량 칸만 30px → 15px(1/2)로 줄인다.
    # (줄어든 만큼 캔들 차트를 넓히지 않으므로 전체 높이도 320 → 305px로 같이 줄어든다.)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.938, 0.0606])

    # 20/60 구름대(구간별 도형으로 칠함: 정배열=연하늘, 역배열=파랑)
    try:
        ma20 = full["close"].rolling(20).mean().iloc[start_i:].reset_index(drop=True)
        ma60 = full["close"].rolling(60).mean().iloc[start_i:].reset_index(drop=True)
        cx, lb_b, ub_b, lb_a, ub_a = build_ma_cloud_segments(df["datetime"], ma20, ma60)
        for lo, up, fc in ((lb_b, ub_b, "#99CCFF"), (lb_a, ub_a, "#CCFFFF")):
            px, py = build_ma_cloud_polygons(cx, lo, up)
            if px:
                fig.add_trace(go.Scatter(
                    x=px, y=py, mode="lines", line=dict(width=0, color=fc), fill="toself", fillcolor=fc,
                    showlegend=False, hoverinfo="skip", connectgaps=False, meta="period_cloud",
                ), row=1, col=1)
    except Exception:
        pass

    for p in MIN_MA_PERIODS:
        ma = full["close"].rolling(p).mean().iloc[start_i:].reset_index(drop=True)
        if not ma.notna().any():
            continue
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=ma, mode="lines", name=f"{p}봉선",
            line=dict(color=MIN_MA_COLORS[p], width=(2 if p in (20, 60) else 1.2)),
            hovertemplate=f"{p}봉선: %{{y:,.0f}}<extra></extra>",
        ), row=1, col=1)

    # ---- 고점세력평단(검정 점선 굵기5) / 하단세력평단(검정 점선 굵기4) / 역배열초 신호 ----
    try:
        _sl = compute_period_seryeok_lines(full)
        for _key, _idx_key, _nm, _w, _pos in (
            ("high_line", "high_idx", "고점세력평단", 5, "top center"),
            ("low_line", "low_idx", "하단세력평단", 4, "bottom center"),
        ):
            _ser = _sl.get(_key)
            if _ser is None:
                continue
            _ser_v = _ser.iloc[start_i:].reset_index(drop=True)
            if not _ser_v.notna().any():
                continue
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=_ser_v, mode="lines", name=_nm,
                line=dict(color="#000000", width=_w, dash="dot"), connectgaps=False,
                hovertemplate=f"{_nm}: %{{y:,.0f}}<extra></extra>",
            ), row=1, col=1)
            _ai = _sl.get(_idx_key)
            if _ai is not None and _ai >= start_i:  # 시작점이 화면 안에 있을 때만 시작 표시(점+이름)
                _row = full.iloc[_ai]
                _ay = float(_row["high"]) if _key == "high_line" else float(_row["low"])
                fig.add_trace(go.Scatter(
                    x=[_row["datetime"]], y=[_ay], mode="markers+text", name=f"{_nm} 시작",
                    marker=dict(size=7, color="#000000"), text=[_nm], textposition=_pos,
                    textfont=dict(color="#000000", size=10), showlegend=False,
                    hovertemplate=f"{_nm} 시작<extra></extra>",
                ), row=1, col=1)
        _cd = _sl["cross_dn"].iloc[start_i:].reset_index(drop=True)
        if _cd.any():
            _m = _cd.values.astype(bool)
            fig.add_trace(go.Scatter(
                x=df["datetime"].values[_m], y=df["high"].values[_m] * 1.02, mode="markers+text", name="역배열초",
                marker=dict(symbol="triangle-down", size=11, color="#1f4fd8", line=dict(width=1, color="#0b2a8a")),
                text=["역배열초"] * int(_m.sum()), textposition="top center",
                textfont=dict(color="#1f4fd8", size=10), showlegend=False,
                hovertemplate="역배열초<extra></extra>",
            ), row=1, col=1)
    except Exception:
        pass

    fig.add_trace(go.Candlestick(
        x=df["datetime"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="주가",
        increasing=dict(line=dict(color=CANDLE_UP), fillcolor=(CANDLE_UP if fill_candles else "rgba(0,0,0,0)")),
        decreasing=dict(line=dict(color=CANDLE_DOWN), fillcolor=(CANDLE_DOWN if fill_candles else "rgba(0,0,0,0)")),
        hovertext=[
            f"({t.strftime('%Y-%m-%d')}) {period}<br>시가: {o:,.0f}<br>고가: {h:,.0f}<br>저가: {l:,.0f}<br>종가: {c:,.0f}"
            for t, o, h, l, c in zip(df["datetime"], df["open"], df["high"], df["low"], df["close"])
        ],
        hoverinfo="text",
    ), row=1, col=1)

    vol_colors = [CANDLE_UP if c >= o else CANDLE_DOWN for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(
        x=df["datetime"], y=df["volume"], marker_color=vol_colors, name=f"{period} 거래량",
        showlegend=False, hovertemplate="거래량: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    last_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else last_close
    chg = (last_close / prev_close - 1) * 100 if prev_close else 0.0
    fig.add_annotation(
        x=1.0, xref="paper", y=last_close, yref="y", xanchor="left", showarrow=False,
        text=f"현 {last_close:,.0f} ({chg:+.2f}%)", font=dict(color="white", size=11),
    )
    _t0 = df["datetime"].iloc[0].strftime("%Y-%m-%d")
    _t1 = df["datetime"].iloc[-1].strftime("%Y-%m-%d")
    # 제목(종목명/기간)은 위쪽 흰색 큰 종목명과 중복이라 삭제해서 세로 여백을 아낀다.
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor=CARD_BG, font=dict(color="white"),
        showlegend=False, margin=dict(l=40, r=70, t=0, b=40), hovermode="x unified", height=295,
    )
    # 구름대(20/60 색채움)를 캔들·다른 선보다 맨 뒤로: plotly는 캔들(box)을 선(scatter)보다 항상 아래 레이어에
    # 그리므로, 구름대만 기본 가격축에 남기고 나머지(캔들·이동평균선·세력평단선·신호)는 투명 겹침 y축으로 올린다.
    # (겹침 y축은 가격축과 범위가 같게 matches로 묶음)
    for _tr in fig.data:
        if _tr.meta != "period_cloud" and _tr.yaxis in (None, "y") and _tr.type in ("scatter", "candlestick"):
            _tr.yaxis = "y3"
    fig.update_layout(yaxis3=dict(
        overlaying="y", matches="y", autorange=True, anchor="x", visible=False, showgrid=False,
        zeroline=False, showticklabels=False,
    ))
    # 가격 글자(y축)와 날짜 글자(x축)는 흰색
    fig.update_xaxes(showgrid=False, rangeslider=dict(visible=False), tickformat="%Y-%m",
                     tickfont=dict(color="white"))
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", tickformat=",.0f",
                     tickfont=dict(color="white"), row=1, col=1)
    # 거래대금 칸이 얇아서 눈금 글자가 겹치지 않게 눈금을 2개로 줄이고 글자도 작게
    fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", tickformat=",.0f", nticks=2,
                     tickfont=dict(size=9, color="white"), row=2, col=1)
    st.plotly_chart(fig, use_container_width=True,
                    config={"locale": "ko", "modeBarButtonsToRemove": ["select2d", "lasso2d"]})


_MIN_LEGEND_MEMORY_JS = """<script>
(function(){
  var P = window.parent;
  // ---- 분봉 차트 아래 정보줄: 세력매수/세력평단 값을 클릭하면 숫자만 클립보드에 복사 ----
  if (P.__minCopyTimer) { P.clearInterval(P.__minCopyTimer); P.__minCopyTimer = null; }
  function copyText(t){
    try { P.navigator.clipboard.writeText(t); }
    catch(e) {
      try { var ta = P.document.createElement("textarea"); ta.value = t; P.document.body.appendChild(ta);
            ta.select(); P.document.execCommand("copy"); P.document.body.removeChild(ta); } catch(e2) {}
    }
  }
  function hookCopy(gd){
    if (gd.__minCopyHook) return;
    gd.__minCopyHook = true;
    gd.on("plotly_clickannotation", function(ev){
      try {
        var a = ev.annotation || {};
        var nm = String(a.name || "");
        if (nm.indexOf("copy:") !== 0) return;
        copyText(nm.slice(5));
        var idx = ev.index, old = a.text;
        P.Plotly.relayout(gd, "annotations[" + idx + "].text", "<b>✅ 복사됨</b>");
        setTimeout(function(){ try { P.Plotly.relayout(gd, "annotations[" + idx + "].text", old); } catch(e) {} }, 900);
      } catch(e) {}
    });
  }
  P.__minCopyTimer = P.setInterval(function(){
    try {
      P.document.querySelectorAll(".js-plotly-plot").forEach(function(gd){
        if (gd.layout && gd.layout.meta === "min_chart") hookCopy(gd);
      });
    } catch(e) {}
  }, 600);
  var KEY = "minchart_hidden_lines_v1";
  var ENABLED = __ENABLED__;
  var WAS = P.__minLegendEnabled;
  P.__minLegendEnabled = ENABLED;
  if (P.__minLegendTimer) { P.clearInterval(P.__minLegendTimer); P.__minLegendTimer = null; }
  function isMin(gd){ try { return !!(gd.layout && gd.layout.meta === "min_chart"); } catch(e) { return false; } }
  if (!ENABLED) {
    // '기본' 틀에서 다른 틀로 바뀐 순간 한 번만: 기본 틀에서 꺼뒀던 선을 다시 모두 보이게 되돌린다.
    if (WAS === true) {
      try {
        P.document.querySelectorAll(".js-plotly-plot").forEach(function(gd){
          if (!gd.data || !isMin(gd)) return;
          var idx = [];
          gd.data.forEach(function(tr, i){ if (tr.visible === "legendonly") idx.push(i); });
          if (idx.length) P.Plotly.restyle(gd, {visible: true}, idx);
        });
      } catch(e) {}
    }
    return;
  }
  function load(){ try { return JSON.parse(P.localStorage.getItem(KEY) || "[]"); } catch(e) { return []; } }
  function save(a){ try { P.localStorage.setItem(KEY, JSON.stringify(a)); } catch(e) {} }
  function onRestyle(gd, ev){
    try {
      if (!P.__minLegendEnabled) return;
      var upd = ev[0], idx = ev[1];
      if (!upd || upd.visible === undefined) return;
      var set = new Set(load());
      var all = (idx && idx.length) ? idx : gd.data.map(function(_, i){ return i; });
      all.forEach(function(i){
        var tr = gd.data[i]; if (!tr || !tr.name) return;
        if (tr.visible === "legendonly") set.add(tr.name); else set.delete(tr.name);
      });
      save(Array.from(set));
    } catch(e) {}
  }
  function tick(){
    try {
      P.document.querySelectorAll(".js-plotly-plot").forEach(function(gd){
        if (!gd.data || !isMin(gd)) return;
        if (!gd.__minHook) { gd.__minHook = true; gd.on("plotly_restyle", function(ev){ onRestyle(gd, ev); }); }
        var hidden = new Set(load()), idx = [];
        gd.data.forEach(function(tr, i){ if (tr.name && hidden.has(tr.name) && tr.visible !== "legendonly") idx.push(i); });
        if (idx.length) P.Plotly.restyle(gd, {visible: "legendonly"}, idx);
      });
    } catch(e) {}
  }
  P.__minLegendTimer = P.setInterval(tick, 600);
  tick();
})();
</script>"""


def render_min_legend_memory(enabled: bool):
    """분봉차트 '기본' 틀 전용: 범례(범)에서 끈 선을 브라우저(localStorage)에 기억해서, '범'을 껐다 켜도,
    종목/분봉 종류를 바꿔도, 새로고침해도 계속 꺼진 상태로 유지한다. 범례에서 다시 켜면 기억도 지워진다.
    다른 틀(신호1 등)에서는 동작하지 않고, 기본 틀에서 다른 틀로 바꾸면 모든 선이 다시 보인다."""
    import streamlit.components.v1 as components
    components.html(_MIN_LEGEND_MEMORY_JS.replace("__ENABLED__", "true" if enabled else "false"), height=0)


def render_chart(df: pd.DataFrame, name: str, code: str, interval_min: int,
                  ma_values: dict = None, ma_toggles: dict = None,
                  fibo_on: bool = False, vol_on: bool = False, cumvol_on: bool = False,
                  show_legend: bool = False, fill_candles: bool = False,
                  nwave_info: dict | None = None,
                  nwave_sma5_time=None, nwave_avg_time=None,
                  min_chart_template: str = "기본",
                  seryeok4_line=None,
                  warm_df: pd.DataFrame | None = None,
                  info_line: dict | None = None):
    ma_values = ma_values or {}
    ma_toggles = ma_toggles or {}

    first_date = df["datetime"].dt.date.min()
    chart_date = df["datetime"].dt.date.iloc[-1]
    is_multi_day = first_date != chart_date
    if is_multi_day:
        # 10분봉 이상: 여러 날짜를 이어서 보여주므로, 실제 데이터 범위 전체를 x축 범위로 쓴다.
        x_range = [df["datetime"].min(), df["datetime"].max()]
    else:
        x_range = [datetime.combine(chart_date, MARKET_OPEN), datetime.combine(chart_date, MARKET_CLOSE)]

    # ---- 지표 계산용 '이전 데이터(워밍업)': 화면에는 df(보이는 구간)만 그리지만, 300봉 볼린저/60봉선
    # 같이 긴 기간이 필요한 선·신호는 warm_df(보이는 구간 이전 봉들)까지 이어 붙여서 계산한 뒤
    # 보이는 구간만 잘라서 쓴다. (_full: 이전+보이는 구간 전체 / _wv: 계산 결과를 보이는 구간만 잘라줌) ----
    _n_warm = 0
    _full = df
    if warm_df is not None and len(warm_df) > 0:
        _wcols = ["datetime", "open", "high", "low", "close", "volume"]
        _w = warm_df[_wcols]
        _w = _w[_w["datetime"] < df["datetime"].min()]
        if len(_w) > 0:
            _full = pd.concat([_w, df[_wcols]], ignore_index=True)
            _n_warm = len(_w)

    def _wv(_s):
        """_full 기준으로 계산한 Series를 보이는 구간(df)과 같은 길이로 잘라서 돌려준다."""
        if _n_warm == 0:
            return _s
        return _s.iloc[_n_warm:].reset_index(drop=True)

    # ---- 서브플롯 구성: 캔들(항상) + 신호 스트립(분차트틀 기본/신호1 모두, 항상 표시)
    # + 3분봉 거래대금(옵션) + 누적거래대금(옵션) ----
    row_specs = ["price", "signal"]  # 신호 스트립은 기본/신호1 틀 모두 표시
    if vol_on:
        row_specs.append("vol")
    if cumvol_on:
        row_specs.append("cumvol")

    n_rows = len(row_specs)
    # 캔들/세력평단선을 올려두는 투명 겹침 y축 이름(가격축 위에 겹쳐 그려져서 다른 선들보다 항상 위에 보임)
    _top_axis = f"y{n_rows + 1}"      # 세력평단선 전용 겹침 y축(다른 선들보다 위)
    _candle_axis = f"y{n_rows + 2}"   # 캔들 전용 겹침 y축(세력평단선을 포함한 모든 선보다 위)
    # 차트 아래 T1~T6 정보 박스를 없앤 높이(px)만큼 전체 높이를 늘려서, 늘어난 만큼 캔들 차트만 커지게 한다.
    _EXTRA_CANDLE_PX = 110
    _base_fig_h = (520 if n_rows == 1 else (620 if n_rows == 2 else 760)) - (0 if show_legend else 30)
    _plot_h = max(_base_fig_h - ((60 if show_legend else 30) + 40), 1)
    _extra_scale = _plot_h / (_plot_h + _EXTRA_CANDLE_PX)
    if n_rows == 1:
        row_heights = [1.0]
    else:
        _sig_h = 0.10 if "signal" in row_specs else 0.0
        _rest_specs = [s for s in row_specs if s != "signal"]
        _rest_total = 1.0 - _sig_h
        # 거래대금/누적거래대금 세로 길이를 각각 기존의 1/2로 줄이고, 줄어든 만큼은 캔들(가격)
        # 차트 쪽에 더해서 전체 높이는 그대로 두되 캔들 차트가 그만큼 세로로 더 커지게 한다.
        if len(_rest_specs) == 1:
            _rest_heights = [_rest_total]
        elif len(_rest_specs) == 2:
            _rest_heights = [_rest_total * 0.85, _rest_total * 0.15]            # 기존 0.7 / 0.3
        else:
            # 캔들 0.775 유지 / 누적거래대금은 다시 1/2(0.1125→0.05625), 줄어든 만큼 거래대금에 더함
            _rest_heights = [_rest_total * 0.775, _rest_total * 0.16875, _rest_total * 0.05625]
        row_heights = []
        _ri = 0
        for _s in row_specs:
            if _s == "signal":
                row_heights.append(_sig_h)
            else:
                row_heights.append(_rest_heights[_ri])
                _ri += 1
        # 캔들 외 행(신호/거래대금/누적거래대금)은 기존 픽셀 높이 유지, 늘어난 높이는 모두 캔들 행으로
        row_heights = [h * _extra_scale if i != 0 else h for i, h in enumerate(row_heights)]
        row_heights[0] = 1.0 - sum(row_heights[1:])

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=row_heights,
    )
    price_row = 1
    signal_row = row_specs.index("signal") + 1 if "signal" in row_specs else None

    # ---- 분차트틀 '신호1' 선택 시 추가 라인(다른 선/캔들보다 맨 뒤: 캔들 트레이스보다 먼저 추가) ----
    if True:  # 기본/신호1 틀 공통(두 틀이 똑같이 나오도록 틀 구분 없이 항상 추가)
        _sig1_trix12_high = compute_min_line_trix12_highestsince_high(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_trix12_high, mode="lines", name="Trix12 상향돌파 고가유지선",
            line=dict(color="#9933FF", width=5),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        _sig1_hilo60 = compute_min_line_hilo_mid60(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_hilo60, mode="lines", name="60봉 고저중간선",
            line=dict(color="#E2A900", width=7),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        _sig1_trix20_ma9 = compute_min_line_trix20_highestsince_ma9(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_trix20_ma9, mode="lines", name="Trix20 상향돌파 MA9유지선",
            line=dict(color="#EDB100", width=7),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

        _sig1_swing = compute_line_tema200_swing_hold(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_swing, mode="lines", name="TEMA200 스윙유지선(초록)",
            line=dict(color="#33CC33", width=7),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_swing, mode="lines", name="TEMA200 스윙유지선(노랑 점선)",
            line=dict(color="#FFFF00", width=2, dash="dot"),
            connectgaps=True, hoverinfo="skip", showlegend=False,
        ), row=price_row, col=1)
        _sig1_wavg_band = compute_line_wavg_open_band(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_wavg_band, mode="lines", name="시가 WMA240 밴드상단선",
            line=dict(color="#00FFCC", width=7),
            connectgaps=True, hoverinfo="skip",
        ), row=price_row, col=1)

    fig.add_trace(go.Candlestick(
        x=df["datetime"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="주가",
        increasing=dict(line=dict(color=CANDLE_UP), fillcolor=(CANDLE_UP if fill_candles else "rgba(0,0,0,0)")),
        decreasing=dict(line=dict(color=CANDLE_DOWN), fillcolor=(CANDLE_DOWN if fill_candles else "rgba(0,0,0,0)")),
        hovertext=[
            f"({t.strftime('%Y-%m-%d')}) {t.strftime('%H:%M')}<br>"
            f"시가: {o:,.0f}<br>고가: {h:,.0f}<br>저가: {l:,.0f}<br>종가: {c:,.0f}"
            for t, o, h, l, c in zip(df["datetime"], df["open"], df["high"], df["low"], df["close"])
        ],
        hoverinfo="text",
    ), row=price_row, col=1)
    # 캔들은 plotly가 선(scatter)보다 항상 아래 레이어에 그리므로, 캔들만 투명 겹침(overlay) y축에
    # 올려서(y축 범위는 원래 가격축과 matches로 동일) 다른 선들보다 가장 위에 보이게 한다.
    fig.data[-1].update(yaxis=_candle_axis)


    # ---- 중요 시간대 표시: 10:20 / 12:10 / 13:50 세로 회색 점선 (당일 단일 차트에서만; 여러
    # 날짜를 이어서 보여주는 10분봉 이상 차트에서는 날짜마다 그리면 너무 어수선해서 생략) ----
    if not is_multi_day:
        for _tm in MIN_CHART_TIME_MARKS:
            fig.add_vline(
                x=datetime.combine(chart_date, _tm), line_dash="dot", line_color="#9aa0a8",
                line_width=1.2, opacity=0.8,
                row=price_row, col=1,
            )

    # ---- 20봉선/60봉선 구름대(색 채우기, 맨뒤): 일봉차트와 같은 색 규칙 ----
    # 20봉선이 위(정배열)=연하늘 #CCFFFF / 60봉선이 위(역배열)=파랑 #99CCFF
    try:
        _mc_ma20 = _wv(_full["close"].rolling(20).mean())
        _mc_ma60 = _wv(_full["close"].rolling(60).mean())
        _mc_x, _mc_lb_b, _mc_ub_b, _mc_lb_a, _mc_ub_a = build_ma_cloud_segments(
            df["datetime"].reset_index(drop=True), _mc_ma20.reset_index(drop=True), _mc_ma60.reset_index(drop=True),
            session=((MARKET_OPEN, MARKET_CLOSE) if is_multi_day else None))
        for _lo, _up, _fc, _nm in (
            (_mc_lb_b, _mc_ub_b, "#99CCFF", "20/60봉 구름대(60봉선 위=역배열)"),
            (_mc_lb_a, _mc_ub_a, "#CCFFFF", "20/60봉 구름대(20봉선 위=정배열)"),
        ):
            _px, _py = build_ma_cloud_polygons(_mc_x, _lo, _up)
            if not _px:
                continue
            fig.add_trace(go.Scatter(
                x=_px, y=_py, mode="lines", line=dict(width=0, color=_fc),
                fill="toself", fillcolor=_fc, name=_nm,
                showlegend=False, hoverinfo="skip", connectgaps=False, meta="ma_cloud",
            ), row=price_row, col=1)
    except Exception:
        pass

    # ---- 3분봉 이동평균선(봉 개수 기준: 5/20/60/120봉) ----
    for p in MIN_MA_PERIODS:
        ma_series = _wv(_full["close"].rolling(p).mean())
        _min_ma_width = 1.3 + (_MA_WIDTH_STEP if p in _EMPHASIS_MIN_MA_PERIODS else 0)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=ma_series, mode="lines", name=f"{p}봉선",
            line=dict(color=MIN_MA_COLORS[p], width=_min_ma_width),
            hovertemplate=f"{p}봉선: %{{y:,.0f}}<extra></extra>",
            connectgaps=True,
        ), row=price_row, col=1)

    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["seryeok_avg"], mode="lines", name="세력평단",
        line=dict(color="#000000", width=3),
        hovertemplate="세력평단: %{y:,.0f}<extra></extra>",
    ), row=price_row, col=1)
    fig.data[-1].update(yaxis=_top_axis)  # 세력평단선: 다른 선들보다 위(캔들 바로 아래)

    # ---- 분차트틀 '신호1' 선택 시: 기본(위 5/20/60/120봉선 + 세력평단)에 추가로
    # 평단(핑크 굵기5, 80봉) / 세력평단(신호1)(초록 굵기7, 120봉) / 그 위에 검정 굵기1 테두리선 ----
    if True:  # 기본/신호1 틀 공통
        _sig1_pyeongdan, _sig1_seryeok = _compute_signal1_lines(df)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_pyeongdan, mode="lines", name="평단",
            line=dict(color="#ff00ff", width=5),
            hovertemplate="평단: %{y:,.0f}<extra></extra>",
            connectgaps=True,
        ), row=price_row, col=1)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_seryeok, mode="lines", name="세력평단(신호1)",
            line=dict(color="#008e2f", width=7),
            hovertemplate="세력평단(신호1): %{y:,.0f}<extra></extra>",
            connectgaps=True,
        ), row=price_row, col=1)
        fig.data[-1].update(yaxis=_top_axis)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_sig1_seryeok, mode="lines", name="세력평단(신호1) 테두리",
            line=dict(color="#000000", width=1),
            hovertemplate="세력평단(신호1): %{y:,.0f}<extra></extra>",
            connectgaps=True, showlegend=False,
        ), row=price_row, col=1)
        fig.data[-1].update(yaxis=_top_axis)

    # ---- 분봉 추가선들 (색상은 키움 색상표 RGB 기준) ----
    # 맨뒤 그룹(meta=back_line): 밝은플래쉬 / 맨위 그룹(meta=top_line): 빨간선, 수직주황선
    _min_extra_lines = [
        # (이름, 계산함수, 색, 굵기, 그룹)
        ("밝은플래쉬", lambda d: compute_line_wavg_open_band(d), "#00FFCC", 7, "back_line"),
        # 흰색 점선: 차트 바탕이 흰색이라 중간회색(#808080) 실선 밑받침을 깔아 보이게 함
        ("흰검정점선390분용1", lambda d: compute_min_line_rolling_vwap(d, 130, 1.03), "#FFFFFF", 2, "back_line", "wd"),
        ("흰검정점선390분용", lambda d: compute_min_line_rolling_vwap(d, 130, 1.0), "#FFFFFF", 4, None, "wd"),
        ("굵은중간파랑", lambda d: compute_min_line_volume_vwap(d, 1.20), "#3366FF", 7, None),
        ("중간파랑", lambda d: compute_min_line_rolling_vwap(d, 120, 1.0), "#3366FF", 5, None),  # SUM(C*V,120)/SUM(V,120)
        ("스윙하늘선", lambda d: compute_line_hilo_mid_shifted(d, 25, 80), "#00FFFF", 4, None),
        ("수직초록선", lambda d: compute_min_vertical_line(d, 20, 20, 20, 20), "#008000", 6, None),
        ("수직갈색", lambda d: compute_min_line_trix10_highestsince_ema10(d), "#993300", 4, None),
        ("수직연초록", lambda d: compute_min_line_ma100_50_cross_value(d), "#339966", 5, None),
        ("자주선", lambda d: compute_seryeok_line_hull_highest(d, 120, 110), "#800080", 6, None),
        # --- 일봉 차트에 있는 선을 분봉에도 같은 이름·색·굵기·모양으로 ---
        # shift(MA(종가,40)+2*stdev((C+H+L)/3,40), 25): 초록 점선 굵기5
        ("MA40+2σ 밴드선(25봉 시프트)", lambda d: compute_line_ma40_typical_stdev_shifted(d, n=40, shift=25),
         "#00FF99", 5, None, "dot"),
        # ValueWhen(1, avg(C,220)>avg(C,220,1), avg(C,220)): 같은 수식 2겹 - 자주 굵기7을 먼저 그리고 그 위에 흰색 굵기2
        ("MA220 상승유지선(자주)", lambda d: compute_line_valuewhen_ma220_rising(d), "#800080", 7, None),
        ("MA220 상승유지선(흰)", lambda d: compute_line_valuewhen_ma220_rising(d), "#ffffff", 2, None, "nohover"),
        ("빨간선", lambda d: compute_line_bbands_up(d, 300, 2), "#FF0000", 5, "top_line"),
        ("수직주황선", lambda d: compute_min_vertical_line(d, 30, 35, 20, 20), "#FF6600", 5, "top_line"),
    ]
    for _item in _min_extra_lines:
        _nm, _fn, _col, _w, _grp = _item[:5]
        _style = _item[5] if len(_item) > 5 else None
        try:
            _ys = _fn(_full)
            if _ys is not None:
                _ys = _wv(pd.Series(_ys))
        except Exception:
            continue
        if _ys is None or not pd.Series(_ys).notna().any():
            continue
        if _style == "wd":
            # 흰 점선 아래에 중간회색 실선(굵기+2)을 먼저 깔아서 흰 바탕에서도 보이게 한다
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=_ys, mode="lines", name=_nm + "(밑받침)",
                line=dict(color="#808080", width=_w + 2),  # 중간회색 밑받침(검정 세력평단선과 안 겹치게)
                showlegend=False, hoverinfo="skip", connectgaps=True, meta=_grp,
            ), row=price_row, col=1)
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=_ys, mode="lines", name=_nm,
                line=dict(color=_col, width=_w, dash="dot"),
                hovertemplate=_nm + ": %{y:,.0f}<extra></extra>",
                connectgaps=True, meta=_grp,
            ), row=price_row, col=1)
            continue
        _line_kw = dict(color=_col, width=_w)
        if _style == "dot":
            _line_kw["dash"] = "dot"
        _hover_kw = (dict(hoverinfo="skip") if _style == "nohover"   # 같은 값 겹선: 호버에 두 번 안 나오게
                     else dict(hovertemplate=_nm + ": %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=_ys, mode="lines", name=_nm,
            line=_line_kw, connectgaps=True, meta=_grp, **_hover_kw,
        ), row=price_row, col=1)

    # ---- 분봉 메인차트 신호 마커: 완생 / 미생 / 추세반등(모든 분봉), 매수후보(390분봉일 때만 메인차트에도 표시) ----
    # 같은 봉에 여러 신호가 겹쳐도 보이도록 신호마다 캔들 저가 아래 다른 높이(1%씩 간격)에 찍는다.
    _lows = df["low"].astype(float).values
    _wansaeng_mask = _wv(compute_signal_wansaeng5(_full))
    _main_signals = [
        # (이름, 마스크, 모양, 크기, 색)
        ("완생", _wansaeng_mask, "star", 13, "#FB035F"),
        ("미생", _wv(compute_signal_misaeng(_full)), "diamond", 12, "#FF00FF"),
        ("추세반등", _wv(compute_signal_chuse_banbal(_full)), "triangle-up", 12, "#FF9900"),
    ]
    if interval_min == 390:
        _main_signals.append(("매수후보", _wv(compute_signal_maesu_hubo(_full)), "triangle-up", 12, "#FF0000"))
    for _k, (_sn, _smask, _ssym, _ssize, _scol) in enumerate(_main_signals):
        _sm = np.asarray(_smask.fillna(False).values, dtype=bool)
        if not _sm.any():
            continue
        fig.add_trace(go.Scatter(
            x=df["datetime"].values[_sm], y=_lows[_sm] * (1 - 0.008 - 0.009 * _k), mode="markers+text", name=_sn,
            marker=dict(symbol=_ssym, size=_ssize, color=_scol, line=dict(width=1, color="#333333")),
            text=[_sn] * int(_sm.sum()), textposition="bottom center",
            textfont=dict(color=_scol, size=11),
            hovertemplate=_sn + "<extra></extra>", showlegend=False, meta="top_line",
        ), row=price_row, col=1)

    # ---- 분봉 세로선(키움 '강세약세' 스타일): 완생 수식이 참인 봉마다 분홍 세로선을 차트 전체 높이로 ----
    _vm = np.asarray(_wansaeng_mask.fillna(False).values, dtype=bool)
    for _vt in df["datetime"].values[_vm]:
        fig.add_shape(
            type="line", xref="x", yref="paper", x0=_vt, x1=_vt, y0=0, y1=1,
            line=dict(color="#FF80FF", width=1.5), layer="below",
        )

    # ---- 세력선4: 검정 점선 굵기4. 10분봉 이상은 일봉 세력선4와 같은 기법의 자동 시작일부터,
    # 1/3/5분봉(당일)은 당일 최저점이 생긴 봉부터 누적 세력평단선을 그린다. ----
    if seryeok4_line is not None and seryeok4_line.notna().any():
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=seryeok4_line, mode="lines", name="세력선4",
            line=dict(color="#000000", width=4, dash="dot"),
            connectgaps=True,
            hovertemplate="세력선4: %{y:,.0f}<extra></extra>",
        ), row=price_row, col=1)

    last_close = float(df["close"].iloc[-1])

    # 일봉 기준 이동평균선(수평 기준선) + 오른쪽 가격(현재가 대비 괴리율) 라벨
    right_labels = []
    for p in MA_PERIODS:
        if ma_toggles.get(p) and ma_values.get(p) is not None:
            val = ma_values[p]
            _ma_ref_width = 1.6 + (_MA_WIDTH_STEP if p in _EMPHASIS_MA_PERIODS else 0)
            fig.add_trace(go.Scatter(
                x=x_range, y=[val, val], mode="lines", name=f"{p}일선",
                line=dict(color=MA_COLORS[p], width=_ma_ref_width, dash="dash"),
                hovertemplate=f"{p}일선: %{{y:,.0f}}<extra></extra>",
            ), row=price_row, col=1)
            right_labels.append((p, val))

    for p, val in right_labels:
        _ma_gap = (val - last_close) / last_close * 100 if last_close else 0.0
        _ma_gap_color = CANDLE_UP if _ma_gap >= 0 else CANDLE_DOWN
        fig.add_annotation(
            xref="paper", x=1.005, xanchor="left",
            yref="y1", y=val, yanchor="middle",
            text=f"({_ma_gap:+.2f}%){val:,.0f}", showarrow=False,
            font=dict(color=_ma_gap_color, size=12, family="Arial, sans-serif"),
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
        # layer="below": 밴드를 모든 선/캔들 '아래'(맨 뒤)에 깔아서, 밴드가 선 위를 덮어 색이 반투명하게
        # 변질되던 문제를 없앤다.
        fig.add_hrect(y0=fibo_prices[0.618], y1=fibo_prices[0.75],
                      fillcolor=FIBO_BAND1_COLOR, line_width=0, layer="below", row=price_row, col=1)
        fig.add_hrect(y0=fibo_prices[0.382], y1=fibo_prices[0.5],
                      fillcolor=FIBO_BAND2_COLOR, line_width=0, layer="below", row=price_row, col=1)

        for lv in FIBO_LEVELS:
            line_color = FIBO_LINE_TOP_COLOR if lv >= 0.618 else FIBO_LINE_BOTTOM_COLOR
            val = fibo_prices[lv]
            fig.add_trace(go.Scatter(
                x=x_range, y=[val, val], mode="lines", name=f"피보 {lv}",
                line=dict(color=line_color, width=1, dash="dot"),
                hovertemplate=f"피보나치 {lv}: %{{y:,.0f}}<extra></extra>",
                meta="fibo_back",
            ), row=price_row, col=1)
            # 피보나치 수치는 오른쪽에 표시하지 않음(요청에 따라 숨김) - 밴드/점선만 표시

    # ---- N파동 목표가 Mapping T1~T6 가로 점선 (일봉 세력평단가 차트와 동일한 방식) ----
    if nwave_info and nwave_info.get("targets"):
        _chart_cur_price = nwave_info.get("current_price") or last_close
        for key, label, _, _color in N_WAVE_T_META:
            val = nwave_info["targets"][key]
            _t_gap = (val - _chart_cur_price) / _chart_cur_price * 100 if _chart_cur_price else 0.0
            fig.add_hline(
                y=val, line_dash="dash", line_color=NWAVE_TARGET_COLOR, line_width=NWAVE_TARGET_LINE_WIDTH,
                annotation_text=f"{key}({label}) {_t_gap:+.2f}%", annotation_font_size=10,
                annotation_font_color=NWAVE_TARGET_COLOR, annotation_position="right",
                row=price_row, col=1,
            )

    # ---- "목표" 버튼을 눌렀을 때: N봉 언덕 시각(파스텔 초록) / 세력평단가 시각(밤색) 세로 점선 ----
    # (종목 바꿀 때마다 시각을 손으로 다시 맞추기 번거로우니, 자동으로 세팅된 시각을
    #  차트에서 바로 눈으로 확인할 수 있도록 세로 점선으로 표시)
    # ※ 이 시각은 "당일 특정 시:분"이라 여러 날짜를 이어서 보여주는 10분봉 이상 차트에서는
    #   의미가 없으므로(어느 날짜인지 모호함) 당일 단일 차트에서만 표시한다.
    if not is_multi_day:
        if nwave_sma5_time is not None:
            fig.add_vline(
                x=datetime.combine(chart_date, nwave_sma5_time),
                line_dash="dot", line_color=NWAVE_HILL_LINE_COLOR, line_width=1.8,
                row=price_row, col=1,
            )
        if nwave_avg_time is not None:
            fig.add_vline(
                x=datetime.combine(chart_date, nwave_avg_time),
                line_dash="dot", line_color=NWAVE_AVG_LINE_COLOR, line_width=1.8,
                row=price_row, col=1,
            )

    # ---- 오른쪽 라벨: 세력평단(현재가 대비 괴리율) / 현재가 ----
    # (시작분/종료분 선택으로 seryeok_avg에 NaN 구간이 있을 수 있어, 마지막 유효값을 사용)
    _vwap_valid_last = df["seryeok_avg"].dropna()
    last_vwap_now = float(_vwap_valid_last.iloc[-1]) if not _vwap_valid_last.empty else last_close
    gap_pct_now = (last_close - last_vwap_now) / last_vwap_now * 100 if last_vwap_now else 0.0
    _vwap_gap_now = (last_vwap_now - last_close) / last_close * 100 if last_close else 0.0
    _vwap_gap_color = CANDLE_UP if _vwap_gap_now >= 0 else CANDLE_DOWN
    fig.add_annotation(
        xref="paper", x=1.005, xanchor="left", yref="y1", y=last_vwap_now, yanchor="bottom",
        text=f"({_vwap_gap_now:+.2f}%){last_vwap_now:,.0f}", showarrow=False,
        font=dict(color=_vwap_gap_color, size=12, family="Arial, sans-serif"), align="left",
    )
    fig.add_annotation(
        xref="paper", x=1.005, xanchor="left", yref="y1", y=last_close, yanchor="top",
        text=f"({gap_pct_now:+.2f}%) {last_close:,.0f}", showarrow=False,
        font=dict(color="#ffffff", size=12, family="Arial, sans-serif"), align="left",
    )

    # ---- 분차트 신호 스트립(기본/신호1 틀 공통, on/off 버튼 없이 항상 표시): 캔들 차트 바로 아래,
    # 거래대금 바로 위에 신호 5종을 각자 고정된 세로 레인에 모아 찍는다. ----
    if signal_row is not None:
        _min_signal_defs = [
            ("이격도과얄", _wv(compute_kiwoom_signal1_disparity(_full)), "circle", "#0A29AE"),
            ("매수후보", _wv(compute_signal_maesu_hubo(_full)), "triangle-up", "#FF0000"),
            ("1020외인초기유입", _wv(compute_kiwoom_signal2_ma_volume(_full)), "circle", "#99CC00"),
            ("나호흰색", _wv(compute_kiwoom_signal3_bbands_envelope(_full)), "circle", "#FFFFFF"),
            ("2060", _wv(compute_min_signal_2060_crossdown(_full)), "triangle-down", "#00FF00"),
        ]
        for _lane, (_sig_name, _sig_mask, _sig_symbol, _sig_color) in enumerate(_min_signal_defs, start=1):
            # 마커는 순전히 시각 표시용(hoverinfo="skip"). 날짜별 정확한 툴팁은 아래 '통합 호버용'
            # 트레이스가 전담한다.
            _sig_mask = _sig_mask.fillna(False)
            if not _sig_mask.any():
                continue
            _y = np.where(_sig_mask, _lane, np.nan)
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=_y,
                mode="markers", name=_sig_name,
                marker=dict(symbol=_sig_symbol, size=9, color=_sig_color,
                            line=dict(width=1, color="#333333")),
                hoverinfo="skip",
                connectgaps=False,
                showlegend=show_legend,
            ), row=signal_row, col=1)

        # ---- 통합 호버용 트레이스: hovermode="x unified"가 신호 없는 시점에도 '가장 가까운 신호
        # 시점'으로 당겨붙어 서로 다른 신호의 시간이 뒤섞여 보이는 문제를 막기 위해, 전체 시간대에
        # 점을 둔 트레이스 1개를 따로 만들고, 그 시점에 실제로 뜬 신호 이름들만 묶어 보여준다. ----
        _min_sig_text = pd.Series([""] * len(df), index=df.index)
        for _sig_name, _sig_mask, _sig_symbol, _sig_color in _min_signal_defs:
            _sig_mask = _sig_mask.fillna(False)
            _min_sig_text = _min_sig_text.where(
                ~_sig_mask,
                _min_sig_text + f"{SIGNAL_MARKER_GLYPH.get(_sig_symbol, '•')} {_sig_name}<br>")
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=[(len(_min_signal_defs) + 1) / 2] * len(df),
            mode="markers", marker=dict(size=0, opacity=0), name="",
            text=_min_sig_text,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        ), row=signal_row, col=1)
        fig.update_yaxes(
            visible=False, showgrid=False, zeroline=False,
            range=[0.3, len(_min_signal_defs) + 0.7],
            row=signal_row, col=1,
        )
        fig.update_xaxes(showgrid=False, showticklabels=False, row=signal_row, col=1)

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

    _title_period = f"{first_date} ~ {chart_date}" if is_multi_day else f"{chart_date}"
    fig.update_layout(
        # 제목(종목명/분봉/기간)은 위쪽 흰색 큰 종목명과 중복이라 삭제(세로 여백 절약).
        # meta는 범례 on/off 기억 스크립트가 '분봉 차트'를 알아보는 표식(제목 대신 사용).
        meta="min_chart",
        plot_bgcolor="white", paper_bgcolor=CARD_BG, font=dict(color="white"),
        showlegend=show_legend,
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center",
                    # 범례가 어두운 배경과 흰 차트 위에 걸쳐 나와서 흰 글자가 안 보이던 문제:
                    # 흰색 반투명 박스 + 진한 글자색으로 어디서든 읽히게 한다.
                    bgcolor="rgba(255,255,255,0.96)", bordercolor="#9aa0a8", borderwidth=1,
                    font=dict(color="#111111", size=11)),
        margin=dict(l=40, r=70, t=(60 if show_legend else 10), b=52), hovermode="x unified",
        height=_base_fig_h + _EXTRA_CANDLE_PX,
    )
    fig.update_xaxes(showgrid=False, range=x_range, rangeslider=dict(visible=False),
                      hoverformat="%Y-%m-%d %H:%M")
    if is_multi_day:
        # 여러 날짜를 이어서 보여줄 때는 주말/장 마감~다음날 장 시작 사이 빈 시간대를
        # 건너뛰어서(rangebreaks) 캔들이 끊기지 않고 촘촘하게 이어지도록 한다.
        _close_hr = MARKET_CLOSE.hour + MARKET_CLOSE.minute / 60
        _open_hr = MARKET_OPEN.hour + MARKET_OPEN.minute / 60
        fig.update_xaxes(rangebreaks=[
            dict(bounds=["sat", "mon"]),
            dict(bounds=[_close_hr, _open_hr], pattern="hour"),
        ])
        fig.update_xaxes(tickformat="%m/%d %H:%M", tickfont=dict(color="white"), row=n_rows, col=1)
    else:
        fig.update_xaxes(tickformat="%H:%M", tickfont=dict(color="white"), row=n_rows, col=1)
    if n_rows > 1:
        fig.update_xaxes(showticklabels=False, row=price_row, col=1)
        vol_row = row_specs.index("vol") + 1 if vol_on else None
        if vol_row is not None and vol_row != n_rows:
            fig.update_xaxes(showticklabels=False, row=vol_row, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", tickformat=",.0f",
                      tickfont=dict(color="white"), row=price_row, col=1)

    # 캔들이 다른 모든 오버레이 선들보다 항상 맨 위에 보이도록, 캔들 트레이스를 맨 마지막으로 이동
    _candle_traces = [tr for tr in fig.data if tr.type == "candlestick"]
    # ---- 차트 맨 아래 검정 여백(x축 날짜 글자 아래)에 '현제가 / 세력매수 / 세력평단 / 괴 / 전' 한 줄 표시.
    # 세로 공간을 늘리지 않으려고 아래쪽 여백 안에 주석으로 그린다. 세력매수·세력평단 값은 클릭하면
    # 콤마 없는 숫자만 클립보드에 복사된다(복사 처리는 render_min_legend_memory 스크립트가 담당). ----
    if info_line:
        def _tw(txt, size):
            """글자 폭(px) 대략 계산: 한글 1.0, 숫자/% 0.58, 콤마·점·콜론·공백 0.3~0.35, +/- 0.5."""
            w = 0.0
            for ch in txt:
                if "가" <= ch <= "힣":
                    w += 1.0
                elif ch.isdigit() or ch == "%":
                    w += 0.58
                elif ch in ",.:":
                    w += 0.32
                elif ch == " ":
                    w += 0.35
                else:
                    w += 0.5
            return w * size

        _BR, _BB = "#ff5a5a", "#4db8ff"  # 밝은 빨강 / 밝은 파랑(양수/음수)

        def _sgn_style(v):
            if v is None:
                return "#eaeef5", "#2a2f3a"
            return (_BR, "#3b0f14") if v >= 0 else (_BB, "#0f2540")

        _items = [
            ("price", f"현제가:{info_line['price']:,.0f}", 23, "#ffffff", None, None),
            ("buy", f"세력매수:{info_line['buy']:,.0f}", 16, "#ffffff", None, f"copy:{info_line['buy']:.0f}"),
            ("vwap", f"세력평단:{info_line['vwap']:,.0f}", 16, "#ffffff", None, f"copy:{info_line['vwap']:.0f}"),
        ]
        _gv, _dv = info_line.get("gap"), info_line.get("day")
        _gc, _gbg = _sgn_style(_gv)
        _dc, _dbg = _sgn_style(_dv)
        _items.append(("gap", f"괴 {_gv:+.2f}%" if _gv is not None else "괴 -", 16, _gc, _gbg, None))
        _items.append(("day", f"전 {_dv:+.2f}%" if _dv is not None else "전 -", 16, _dc, _dbg, None))
        _xpx = -34.0  # 플롯 왼쪽 끝 기준 픽셀 위치(왼쪽 여백 안쪽부터 시작)
        for _k, _txt, _sz, _col, _bg, _copy in _items:
            _kw = dict(
                xref="paper", yref="paper", x=0.0, y=0.0, xanchor="left", yanchor="top",
                xshift=_xpx, yshift=-21, showarrow=False, align="left",
                text=f"<b>{_txt}</b>", font=dict(color=_col, size=_sz),
            )
            if _bg:
                _kw.update(bgcolor=_bg, borderpad=2)
            if _copy:
                _kw.update(captureevents=True, name=_copy, hovertext="클릭하면 가격이 복사됩니다")
            fig.add_annotation(**_kw)
            _xpx += _tw(_txt, _sz) + (14 if _bg is None else 16) + (4 if _bg else 0)
    # 겹침 y축 2개: (n+1)=세력평단선, (n+2)=캔들. 그리는 순서: 일반 선(가격축) < 세력평단선 < 캔들
    for _ov in (n_rows + 1, n_rows + 2):
        fig.update_layout({f"yaxis{_ov}": dict(
            overlaying="y", matches="y", autorange=True, anchor="x", visible=False, showgrid=False,
            zeroline=False, showticklabels=False,
        )})
    _non_candle = [tr for tr in fig.data if tr.type != "candlestick"]
    _fibo_traces = [tr for tr in _non_candle if tr.meta == "fibo_back"]
    _cloud_traces = [tr for tr in _non_candle if tr.meta == "ma_cloud"]
    _back_traces = [tr for tr in _non_candle if tr.meta == "back_line"]
    _top_traces = [tr for tr in _non_candle if tr.meta == "top_line"]
    _other_traces = [tr for tr in _non_candle if tr.meta not in ("fibo_back", "ma_cloud", "back_line", "top_line")]
    # 순서(뒤→앞): 피보나치 점선(밴드는 layer=below) → 구름대 색채움 → 밝은플래쉬 → 일반 선들 → 빨간선/수직주황선 → 캔들
    fig.data = tuple(_fibo_traces + _cloud_traces + _back_traces + _other_traces + _top_traces + _candle_traces)

    st.plotly_chart(
        fig, use_container_width=True,
        config={
            "locale": "ko",
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        },
    )


# ----------------------------------------------------------------------
# 3-1. 클릭하면 클립보드로 복사되는 숫자 카드
# ----------------------------------------------------------------------
def copy_metric(label: str, value_text: str, copy_text: str, delta_text: str = "", delta_color: str = "#eaeef5", value_color: str = "#ffffff"):
    import streamlit.components.v1 as components
    html = f"""
    <div class="copy-metric" onclick="
        navigator.clipboard.writeText('{copy_text}');
        this.querySelector('.label').innerText='✅ 복사됨';
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
        this.innerText='✅';
        setTimeout(() => {{ this.innerText='📋'; }}, 1000);
    ">📋</div>
    """, height=32)


def date_ymd_input(label: str, default_date, key_prefix: str, show_label: bool = True):
    """년/월/일 드롭다운(전부 숫자)으로 날짜를 입력받는다. 박스 가로폭은 숫자만 겨우 들어갈 만큼 최소화.
    show_label=False면 위쪽 캡션 글자를 표시하지 않고 그만큼 세로 공간을 절약한다."""
    if show_label:
        st.caption(label)
    with st.container(key=f"{key_prefix}_wrap"):
        y_col, m_col, d_col = st.columns([1, 0.75, 0.75])
        year_options = list(range(2015, date.today().year + 1))
        with y_col:
            year = st.selectbox(
                "년", year_options,
                index=year_options.index(default_date.year) if default_date.year in year_options else len(year_options) - 1,
                key=f"{key_prefix}_y", label_visibility="collapsed",
            )
        with m_col:
            month = st.selectbox("월", list(range(1, 13)), index=default_date.month - 1,
                                  key=f"{key_prefix}_m", label_visibility="collapsed")
        with d_col:
            day_options = list(range(1, 32))
            day = st.selectbox("일", day_options, index=min(default_date.day, 31) - 1,
                                key=f"{key_prefix}_d", label_visibility="collapsed")
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 1)  # 해당 월에 없는 날짜(31일 등) 선택 시 1일로 보정


def minute_hm_input(label: str, times: list, default_time, key_prefix: str):
    """당일 분봉 시간(HH:MM) 목록 중에서 드롭다운으로 시작분/종료분을 선택.
    (일봉 세력평단가 차트의 시작일/종료일 선택 UI와 동일한 패턴, 분봉용)"""
    st.caption(label)
    if not times:
        return default_time
    labels = [t.strftime("%H:%M") for t in times]
    default_label = default_time.strftime("%H:%M") if default_time in times else labels[-1]
    default_idx = labels.index(default_label)
    sel_label = st.selectbox(label, labels, index=default_idx,
                              key=key_prefix, label_visibility="collapsed")
    return times[labels.index(sel_label)]


def seryeok_copy_text(price: float, key: str, font_weight: str = "700"):
    """'세력 12,345' 형태의 텍스트를 클릭하면 콤마 등 특수문자 없이 숫자만 클립보드에 복사."""
    import streamlit.components.v1 as components
    plain_number = f"{price:.0f}"
    display_text = f"{price:,.0f}"
    components.html(f"""
    <style>
    .seryeok-copy-{key} {{
        font-size:13px; font-weight:{font_weight}; color:#eaeef5;
        cursor:pointer; font-family: sans-serif; padding-top:6px;
    }}
    .seryeok-copy-{key}:hover {{ text-decoration: underline; }}
    </style>
    <div class="seryeok-copy-{key}" title="세력평단 가격 복사" onclick="
        navigator.clipboard.writeText('{plain_number}');
        this.innerText='✅ 복사됨';
        setTimeout(() => {{ this.innerText='세력 {display_text}'; }}, 1000);
    ">세력 {display_text}</div>
    """, height=28)


def code_copy_button(code: str, name: str, key: str):
    """종목명 + 코드가 함께 표시되는 버튼(목취 버튼과 세로 높이가 비슷하도록 컴팩트하게 구성).
    종목명이 버튼 폭보다 길면 잘려서 표시되고, 클릭하면 종목코드를 클립보드에 복사한다."""
    import streamlit.components.v1 as components
    label_text = code if code else "코드명"
    display_name = name if name else ""
    components.html(f"""
    <style>
    .code-copy-{key} {{
        display:flex; flex-direction:column; align-items:center; justify-content:center;
        padding:2px 12px; border:1px solid rgba(250,250,250,0.25);
        border-radius:8px; cursor:pointer; color:#111111; background:#ffffff;
        font-family: sans-serif; white-space:nowrap; overflow:hidden;
        line-height:1.2; height:34px; box-sizing:border-box;
    }}
    .code-copy-{key}:hover {{ border-color:#999; }}
    .code-copy-{key} .cc-name {{
        font-size:11px; font-weight:700; max-width:100%; overflow:hidden; text-overflow:ellipsis;
    }}
    .code-copy-{key} .cc-code {{ font-size:13px; font-weight:700; }}
    .code-copy-{key} .cc-copied {{ display:none; font-size:13px; font-weight:700; }}
    .code-copy-{key}.copied .cc-name, .code-copy-{key}.copied .cc-code {{ display:none; }}
    .code-copy-{key}.copied .cc-copied {{ display:block; }}
    </style>
    <div class="code-copy-{key}" title="클릭 시 종목코드 복사" onclick="
        navigator.clipboard.writeText('{code}');
        this.classList.add('copied');
        var elx = this;
        setTimeout(function() {{ elx.classList.remove('copied'); }}, 1000);
    ">
        <div class="cc-name">{display_name}</div>
        <div class="cc-code">{label_text}</div>
        <div class="cc-copied">✅ 복사됨</div>
    </div>
    """, height=38)


def render_summary_box(lines: list):
    """
    [Day Trading Mapping 요약 분석] 형태의 압축된 요약 카드.
    클릭하면 전체 텍스트가 클립보드로 복사됨. 타이틀과 항목들을 같은 줄에 가로로 배치.
    lines[0] = 타이틀, 나머지 = ■ 항목들(가로로 나열)
    """
    import streamlit.components.v1 as components
    title = lines[0]
    body_lines = lines[1:]
    copy_text = "\n".join(lines)
    body_html = "".join(f"<span class='sum-item'>■ {l}</span>" for l in body_lines)
    components.html(f"""
    <style>
    .summary-box {{
        background-color:{CARD_BG}; border:1px solid {CARD_BORDER};
        border-radius:8px; padding:8px 12px; cursor:pointer;
        font-family:'Malgun Gothic', sans-serif; color:#eaeef5;
        line-height:1.45;
        display:flex; align-items:center; flex-wrap:wrap; column-gap:14px; row-gap:2px;
    }}
    .summary-box:hover {{ border-color:{ORANGE}; }}
    .summary-box .sum-title {{ font-size:14px; font-weight:700; color:#fff; white-space:nowrap; }}
    .summary-box .sum-item {{ font-size:13.5px; white-space:nowrap; }}
    .summary-copied {{ color:{ORANGE}; font-size:11.5px; height:14px; width:100%; }}
    </style>
    <div class="summary-box" onclick="
        navigator.clipboard.writeText(`{copy_text}`);
        document.getElementById('sumcopied_{abs(hash(copy_text))}').style.visibility='visible';
        setTimeout(() => {{ document.getElementById('sumcopied_{abs(hash(copy_text))}').style.visibility='hidden'; }}, 1200);
    ">
        <span class="sum-title">{title}</span>
        {body_html}
        <div id="sumcopied_{abs(hash(copy_text))}" class="summary-copied" style="visibility:hidden;">✅ 복사됨</div>
    </div>
    """, height=70)


# ----------------------------------------------------------------------
# 4. 헤더 배너 (제목 텍스트는 여백 절약을 위해 생략)
# ----------------------------------------------------------------------
try:
    name_map = load_stock_name_map()
except Exception as e:
    st.warning(f"종목명 목록 로드 실패(코드로만 검색 가능, 자동 재시도): {e}")
    name_map = {}

try:
    marketcap_map = load_stock_marketcap_map()
except Exception as e:
    st.warning(f"시가총액 목록 로드 실패(자동 재시도): {e}")
    marketcap_map = {}


def _cleanup_stale_nwave_min_state():
    """분봉 '목표' 자동세팅(종목별 N봉 언덕/세력평단가 시각)은 당일 분봉 데이터 기준이라
    거래일이 바뀌면 더 이상 의미가 없다. 서버(앱)를 며칠씩 재시작 없이 켜둬도 종목별
    임시값이 세션 메모리에 계속 쌓이지 않도록, 날짜가 바뀐 첫 실행에서 한 번만 정리한다.
    (※ 이 값들은 애초에 파일로 저장되지 않고 세션 메모리에만 있어 PC 용량과는 무관하지만,
      혹시 모를 누적을 막기 위한 안전장치)"""
    today_str = date.today().isoformat()
    if st.session_state.get("_nwave_min_state_date") == today_str:
        return
    stale_prefixes = ("nwave_min_sma5_", "nwave_min_avg_", "nwave_min_ma_period_",
                       "min_start_", "min_end_")
    for k in list(st.session_state.keys()):
        if k.startswith(stale_prefixes):
            del st.session_state[k]
    st.session_state.pop("nwave_min_auto_applied_code", None)
    st.session_state["_nwave_min_state_date"] = today_str


_cleanup_stale_nwave_min_state()

main_col, side_col = st.columns([3, 0.9], gap="small")

with main_col:

    # ----------------------------------------------------------------------
    # 5. 검색창 + 최근검색 + 관심종목 + 분봉선택 + 새로고침
    # ----------------------------------------------------------------------
    if "query_input" not in st.session_state:
        st.session_state.query_input = "삼성전자"

    # 칩(최근검색/관심종목) 클릭으로 예약된 이동 요청을 위젯 생성 "전에" 반영
    if "goto_query" in st.session_state:
        st.session_state.query_input = st.session_state.pop("goto_query")

    # 한 줄: 검색창 | 조회 | 분봉 선택  (라벨/설명 글자를 없애서 세로 공간을 아낌)
    with st.container(key="top_search_row"):
        col_a, col_b, col_c = st.columns([2.5, 1, 1.9], vertical_alignment="center")
        with col_a:
            query = st.text_input(
                "종목명 또는 6자리 코드 입력", key="query_input",
                label_visibility="collapsed", placeholder="종목명 또는 6자리 코드 입력",
            )
        with col_b:
            search_clicked = st.button("⚡ 조회", use_container_width=True)
        with col_c:
            interval = st.radio(
                "분봉", MINUTE_INTERVAL_OPTIONS, horizontal=True, key="minute_interval_radio",
                label_visibility="collapsed",
            )
            if interval != st.session_state.get("_minute_interval_saved"):
                _save_minute_interval(interval)
                st.session_state["_minute_interval_saved"] = interval
    st.markdown(
        "<style>"
        ".st-key-top_search_row div[data-testid='stHorizontalBlock'] { align-items: center !important; }"
        ".st-key-top_search_row div[data-testid='stTextInput'], "
        ".st-key-top_search_row div[data-testid='stRadio'], "
        ".st-key-top_search_row div[data-testid='stButton'] { margin: 0 !important; }"
        "</style>",
        unsafe_allow_html=True,
    )
    interval_min = int(interval)

    # 10분봉 이상: 몇 개월치를 이어서 볼지 선택 (개월 수가 적을수록 키움 API 호출 횟수가
    # 줄어서 부담이 줄어든다). 1/3/5분봉은 당일치만 보므로 이 선택이 필요 없다.
    # ※ 실제 선택 UI(조회 기간(개월)/로컬/로컬비우기)는 화면 아래쪽 "일봉 로컬비우기"/
    # "일날짜크기"와 같은 줄로 옮겨서 표시한다. 여기서는 그 줄이 그려지기 전에 이미
    # 골라둔 값을 세션에서 먼저 읽어와 분봉 데이터 조회에 바로 사용한다.
    if interval_min >= 10:
        minute_range_months = st.session_state.get("minute_range_months", 5)
        use_local_minute_cache = st.session_state.get("minute_local_cache_on", True)
    else:
        minute_range_months = None
        use_local_minute_cache = st.session_state.get("minute_local_cache_on", True)


    # 종목 코드 조기 해석 (최근검색에 검색 즉시 반영되도록 칩 렌더링보다 먼저 처리)
    resolved_code, resolved_name_early = (None, None)
    if query:
        resolved_code, resolved_name_early = resolve_query_to_code(query, name_map)
        if resolved_code is not None:
            add_to_recent(resolved_code, resolved_name_early)

    # 최근 검색 칩 (마우스오버하면 검색 당시 스냅샷 표시)
    # 최대 MAX_RECENT(25)개까지 한 줄에 가로로 딱 붙여서 표시 - 이름이 길면 말줄임표(...)로
    # 잘려 보이더라도(버튼에 hover하면 코드/스냅샷 툴팁으로 확인 가능) 한 줄 안에 최대한 많이
    # 들어가도록 각 버튼 폭을 좁게 고정한다.
    if st.session_state.recent:
        with st.container(key="recent_search_row"):
            recent_cols = st.columns(len(st.session_state.recent))
            for i, item in enumerate(st.session_state.recent):
                tooltip = f"{item['name']} ({item['code']})\n{item.get('snapshot') or '스냅샷 정보 없음'}"
                with recent_cols[i]:
                    if st.button(f"{item['name']} ({item['code']})", key=f"recent_{item['code']}", help=tooltip):
                        st.session_state.goto_query = item["name"]
                        st.rerun()
        st.markdown(
            "<style>"
            ".st-key-recent_search_row div[data-testid='stHorizontalBlock'] {"
            "  flex-wrap: nowrap !important; gap: 3px !important; }"
            ".st-key-recent_search_row div[data-testid='column'] {"
            "  width: auto !important; min-width: 0 !important; flex: 1 1 0 !important; }"
            ".st-key-recent_search_row button {"
            "  white-space: nowrap !important; overflow: hidden !important; "
            "  text-overflow: ellipsis !important; padding: 2px 6px !important; "
            "  width: 100% !important; min-width: 0 !important; }"
            "</style>",
            unsafe_allow_html=True,
        )

    # 관심종목 (폴더별 정리, 폴더 생성/이름변경/삭제/이동 가능)
    # ※ "새 폴더"/"TXT 저장" 버튼은 화면 아래쪽 "메모 / 폴더이동" 버튼과 같은 줄로 옮겨서 표시한다.
    if st.session_state.watchlist or len(st.session_state.folders) > 1:
        FOLDERS_PER_ROW = 10
        folders_list = st.session_state.folders
        for row_start in range(0, len(folders_list), FOLDERS_PER_ROW):
            row_folders = folders_list[row_start:row_start + FOLDERS_PER_ROW]
            folder_row_cols = st.columns(len(row_folders))
            for col, folder in zip(folder_row_cols, row_folders):
                with col:
                    items_in = [it for it in st.session_state.watchlist if it.get("folder") == folder]
                    _folder_open_key = f"folder_open_{folder}"
                    if _folder_open_key not in st.session_state:
                        st.session_state[_folder_open_key] = False
                    if st.button(f"📁 {folder} ({len(items_in)})", key=f"folder_toggle_{folder}",
                                 use_container_width=True):
                        st.session_state[_folder_open_key] = not st.session_state[_folder_open_key]
                        st.rerun()

                    if st.session_state[_folder_open_key]:
                        st.text_input(
                            "이름변경", value=folder, key=f"rename_input_{folder}", label_visibility="collapsed",
                            on_change=_rename_folder_on_enter, args=(folder,),
                            help="이름을 바꾸고 엔터(또는 다른 곳 클릭)만 해도 자동으로 저장됩니다.",
                        )

                        _is_default_folder = (folder == DEFAULT_FOLDER)
                        _fbtn_labels = ["업", "업+", "업-"] + ([] if _is_default_folder else ["삭"]) + \
                            ["고침", "세+", "세-", "전+", "전-"]
                        _fbtn_widths = [0.6, 0.6, 0.6] + ([] if _is_default_folder else [1]) + [1, 1, 1, 1, 1]
                        st.markdown(
                            "<style>"
                            f".st-key-folder_btn_row_{folder} .stButton button {{"
                            "  padding: 0.05rem 0.15rem !important; min-height: 22px !important;"
                            "  font-size: 11px !important; line-height: 1 !important;"
                            "}"
                            "</style>",
                            unsafe_allow_html=True,
                        )
                        with st.container(key=f"folder_btn_row_{folder}"):
                            _fbtn_cols = st.columns(_fbtn_widths, gap="small")
                            _fbtn_idx = 0
                            with _fbtn_cols[_fbtn_idx]:
                                if st.button("업", key=f"updatebtn_{folder}", use_container_width=True,
                                             help="이 폴더 종목들을 저장일 종가 대비 현재가 괴리율(%)과 "
                                                  "저장 후 경과일수로 지금 조회해서 종목명 위에 표시합니다. "
                                                  "누르기 전까지는 조회하지 않습니다(네이버·키움 API 부담 방지)."):
                                    for _uit in items_in:
                                        try:
                                            _ucode = _uit["code"]
                                            _ucur_price = None
                                            _udf = fetch_today_minute_data(_ucode, interval_min=3)
                                            if not _udf.empty:
                                                _ucur_price = float(_udf.iloc[-1]["close"])
                                            if not _ucur_price:
                                                _uddf = fetch_daily_ohlcv(_ucode)
                                                if not _uddf.empty:
                                                    _ucur_price = float(_uddf.iloc[-1]["close"])
                                            _ugap_info = compute_watchlist_gap(_ucode, _ucur_price) if _ucur_price else None
                                            if _ugap_info is not None:
                                                _uadded = get_first_watchlist_added_date(_ucode)
                                                _udays = (date.today() - _uadded).days if _uadded else None
                                                if _udays is not None:
                                                    st.session_state.wl_update_gap[_ucode] = {
                                                        "days": _udays, "gap": _ugap_info["gap"],
                                                    }
                                        except Exception:
                                            pass
                                    _save_wl_update_data()
                                    st.rerun()
                            _fbtn_idx += 1
                            with _fbtn_cols[_fbtn_idx]:
                                if st.button("업+", key=f"updatesortplus_{folder}", use_container_width=True,
                                             help="'업'으로 조회된 괴리율이 높은 순(내림차순)으로 정렬합니다. "
                                                  "새로고침해도 정렬 상태가 유지됩니다."):
                                    st.session_state.wl_update_sort[folder] = "+"
                                    _save_wl_update_data()
                                    st.rerun()
                            _fbtn_idx += 1
                            with _fbtn_cols[_fbtn_idx]:
                                if st.button("업-", key=f"updatesortminus_{folder}", use_container_width=True,
                                             help="'업'으로 조회된 괴리율이 낮은 순(오름차순)으로 정렬합니다. "
                                                  "새로고침해도 정렬 상태가 유지됩니다."):
                                    st.session_state.wl_update_sort[folder] = "-"
                                    _save_wl_update_data()
                                    st.rerun()
                            _fbtn_idx += 1
                            if not _is_default_folder:
                                with _fbtn_cols[_fbtn_idx]:
                                    if st.button("삭", key=f"delbtn_{folder}", use_container_width=True,
                                                 help="폴더삭제"):
                                        delete_folder(folder)
                                        st.rerun()
                                _fbtn_idx += 1
                            with _fbtn_cols[_fbtn_idx]:
                                if st.button("고침", key=f"refreshbtn_{folder}", use_container_width=True,
                                             help="이 폴더의 세력평단比/전일比를 지금 조회해서 갱신합니다. "
                                                  "누르기 전까지는 조회하지 않습니다(네이버·키움 API 부담 방지)."):
                                    _new_cache = {}
                                    for _rit in items_in:
                                        _rg_text, _rg_color, _rg_val = "-", "#888888", None
                                        _rd_text, _rd_color, _rd_val = "-", "#888888", None
                                        try:
                                            _rdf = fetch_today_minute_data(_rit["code"], interval_min=3)
                                            if not _rdf.empty:
                                                _rdf = calc_seryeok_average(_rdf)
                                                _rlast = _rdf.iloc[-1]
                                                _rclose = float(_rlast["close"])
                                                _rvwap = float(_rlast["seryeok_avg"])
                                                if _rvwap:
                                                    _rgap = (_rclose - _rvwap) / _rvwap * 100
                                                    _rg_text = f"세{_rgap:+.0f}%"
                                                    _rg_color = "#f4a6a6" if _rgap > 0 else "#a6c8f4" if _rgap < 0 else "#888888"
                                                    _rg_val = _rgap
                                                _rpred_pre = _rlast.get("pred_pre", 0) or 0
                                                _ryclose = _rclose - _rpred_pre
                                                if _ryclose:
                                                    _rday = _rpred_pre / _ryclose * 100
                                                    _rd_text = f"전{_rday:+.0f}%"
                                                    _rd_color = "#e05252" if _rday > 0 else "#4a90e2" if _rday < 0 else "#888888"
                                                    _rd_val = _rday
                                        except Exception:
                                            pass
                                        _new_cache[_rit["code"]] = (_rg_text, _rg_color, _rd_text, _rd_color, _rg_val, _rd_val)
                                    st.session_state.setdefault("wl_gap_cache", {})[folder] = _new_cache
                                    st.rerun()
                            _fbtn_idx += 1
                            for _sort_label in ["세+", "세-", "전+", "전-"]:
                                with _fbtn_cols[_fbtn_idx]:
                                    if st.button(_sort_label, key=f"sortbtn_{_sort_label}_{folder}",
                                                 use_container_width=True,
                                                 help="'고침'으로 조회된 수치를 기준으로 정렬합니다 "
                                                      "(먼저 '고침'을 눌러야 값이 있습니다)."):
                                        st.session_state[f"wl_sort_{folder}"] = _sort_label
                                        st.rerun()
                                _fbtn_idx += 1

                        if not items_in:
                            st.caption("종목 없음")
                        else:
                            _folder_cache = st.session_state.get("wl_gap_cache", {}).get(folder, {})

                            _sort_mode = st.session_state.get(f"wl_sort_{folder}")
                            if _sort_mode and _folder_cache:
                                _val_idx = 4 if _sort_mode.startswith("세") else 5
                                _with_val = [(it, _folder_cache.get(it["code"], (None,) * 6)[_val_idx]) for it in items_in]
                                _have_val = [t for t in _with_val if t[1] is not None]
                                _no_val = [t for t in _with_val if t[1] is None]
                                _have_val.sort(key=lambda t: t[1], reverse=_sort_mode.endswith("+"))
                                items_in = [t[0] for t in _have_val] + [t[0] for t in _no_val]

                            # '업+'/'업-' 정렬 (영구 저장된 상태 - 새로고침해도 유지, 이 정렬이 최종 우선)
                            _usort_mode = st.session_state.wl_update_sort.get(folder)
                            if _usort_mode:
                                _uwith_val = [
                                    (it, st.session_state.wl_update_gap.get(it["code"], {}).get("gap"))
                                    for it in items_in
                                ]
                                _uhave_val = [t for t in _uwith_val if t[1] is not None]
                                _uno_val = [t for t in _uwith_val if t[1] is None]
                                _uhave_val.sort(key=lambda t: t[1], reverse=(_usort_mode == "+"))
                                items_in = [t[0] for t in _uhave_val] + [t[0] for t in _uno_val]

                            for item in items_in:
                                tooltip = item.get("memo", "") or "메모 없음"
                                if item.get("memo_time"):
                                    tooltip += f" ({item['memo_time']})"
                                elif item.get("added_time"):
                                    tooltip += f" / 추가: {item['added_time']}"

                                # 폴더의 '고침' 버튼을 눌렀을 때 캐시된 값만 사용 (자동 조회 없음 - 네이버·키움 API 부담 방지)
                                if item["code"] in _folder_cache:
                                    _wl_gap_text, _wl_gap_color, _wl_day_text, _wl_day_color, _wl_gap_val, _wl_day_val = _folder_cache[item["code"]]
                                else:
                                    _wl_gap_text, _wl_gap_color = "-", "#888888"
                                    _wl_day_text, _wl_day_color = "-", "#888888"

                                # '업' 버튼으로 조회된 경과일수 + 저장일 종가 대비 괴리율 (예: "120 +32%")
                                _uinfo = st.session_state.wl_update_gap.get(item["code"])

                                item_col1, item_col2, item_col3, item_col4 = st.columns([3.2, 1, 1, 0.7], gap="small")
                                with item_col1:
                                    _wl_name_key = f"wl_item_wrap_{item['code']}_{folder}"
                                    if _uinfo is not None:
                                        _uday_val = _uinfo.get("days")
                                        _ugap_val = _uinfo.get("gap")
                                        _ugap_color = "#e05252" if (_ugap_val or 0) > 0 else "#4a90e2" if (_ugap_val or 0) < 0 else "#888888"
                                        st.markdown(
                                            f"<div style='text-align:center; padding:0; margin:0; "
                                            f"font-size:11px; font-weight:700; line-height:1.2; color:#dfe4ee;'>"
                                            f"{_uday_val}<span style='color:{_ugap_color};'>{_ugap_val:+.0f}%</span></div>",
                                            unsafe_allow_html=True,
                                        )
                                    st.markdown(
                                        "<style>"
                                        f".st-key-{_wl_name_key} button {{ padding:0.1rem 0.3rem !important; }}"
                                        f".st-key-{_wl_name_key} button p {{"
                                        "  font-size:16px !important; font-weight:800 !important;"
                                        "  white-space:nowrap !important; overflow:hidden !important;"
                                        "  text-overflow:ellipsis !important; display:block !important;"
                                        "}"
                                        "</style>",
                                        unsafe_allow_html=True,
                                    )
                                    with st.container(key=_wl_name_key):
                                        if st.button(
                                            item["name"], key=f"wl_{item['code']}_{folder}",
                                            help=tooltip, use_container_width=True,
                                        ):
                                            st.session_state.goto_query = item["name"]
                                            st.rerun()
                                with item_col2:
                                    st.markdown(
                                        f"<div style='padding-top:8px; font-size:11.5px; font-weight:700; "
                                        f"color:{_wl_gap_color};'>{_wl_gap_text}</div>",
                                        unsafe_allow_html=True,
                                    )
                                with item_col3:
                                    st.markdown(
                                        f"<div style='padding-top:8px; font-size:11.5px; font-weight:700; "
                                        f"color:{_wl_day_color};'>{_wl_day_text}</div>",
                                        unsafe_allow_html=True,
                                    )
                                with item_col4:
                                    _wlx_key = f"wlx_wrap_{item['code']}_{folder}"
                                    st.markdown(
                                        f"<style>.st-key-{_wlx_key} button {{ padding:0 !important; "
                                        f"min-height:20px !important; height:20px !important; "
                                        f"font-size:11px !important; color:#e05252 !important; "
                                        f"border:none !important; background:transparent !important; }}</style>",
                                        unsafe_allow_html=True,
                                    )
                                    with st.container(key=_wlx_key):
                                        if st.button("X", key=f"wlx_{item['code']}_{folder}"):
                                            toggle_watchlist(item["code"], item["name"])  # folder 없이 호출 = 제거
                                            st.rerun()

    # 종목명 + 새로고침 컨트롤 + 관심종목 추가/해제 + 메모·폴더이동 + 새 폴더 + TXT 저장 + 240/480/720일선 (한 줄, 여백 없이 촘촘하게)
    _cc = st.columns([1.8, 0.35, 0.4, 0.75, 0.75, 0.75, 0.45, 1.5, 1.3, 1.6, 0.9, 1.1, 0.6, 0.6, 0.6], gap="small")
    # 앞쪽(제목 | 새로 | 자동 | 분차트틀 | (분일) | (개월))은 아래에서 _cc[0..5]로 직접 그린다.
    ctrl_cols = [_cc[0], None, None, _cc[8], _cc[9], _cc[10], _cc[11], _cc[12], _cc[13], _cc[14]]
    # 분봉 / 주봉 / 월봉 보기 전환 버튼 (왼쪽 차트 자리를 분봉 ↔ 주봉 ↔ 월봉으로 바꿔서 보여준다)
    # '일먼'(일봉 먼저) 스위치: 켜면 종목 선택 시 일봉을 먼저 처리하고 분봉을 나중에 처리한다(끄면 분봉 먼저).
    # 화면 자리는 그대로(왼쪽 분봉 / 오른쪽 일봉)이고 '그리는 순서'만 바뀐다. 주봉/월봉은 어느 쪽이든 항상 맨 마지막.
    with _cc[6]:
        st.checkbox(
            "일먼", key="daily_first", on_change=_on_daily_first_change,
            help="체크하면 종목을 고를 때 일봉을 먼저 보여주고 분봉을 나중에 처리합니다(기본: 분봉 먼저). 주봉/월봉은 항상 마지막입니다.",
        )
    with _cc[7]:
        _view_mode_now = st.session_state.get("min_view_mode", "분봉")
        with st.container(key="view_mode_btn_wrap"):
            _vm_cols = st.columns(3, gap="small")
            for _vm_col, _vm_label in zip(_vm_cols, ("분봉", "주봉", "월봉")):
                with _vm_col:
                    if st.button(_vm_label, key=f"min_view_mode_btn_{_vm_label}",
                                 type=("primary" if _view_mode_now == _vm_label else "secondary"),
                                 use_container_width=True):
                        if st.session_state.get("min_view_mode", "분봉") != _vm_label:
                            st.session_state["min_view_mode"] = _vm_label
                            st.rerun()
        st.markdown(
            "<style>"
            ".st-key-view_mode_btn_wrap button { padding:0.25rem 0.2rem !important; "
            "min-height:2.4rem !important; height:2.4rem !important; white-space:nowrap !important; }"
            ".st-key-view_mode_btn_wrap button p { white-space:nowrap !important; margin:0 !important; font-weight:700; }"
            "</style>",
            unsafe_allow_html=True,
        )
    with ctrl_cols[0]:
        if resolved_code is not None:
            import streamlit.components.v1 as components
            components.html(f"""
            <style>
            .min-title-{resolved_code} {{
                font-size:22px; font-weight:700; white-space:nowrap;
                padding-top:4px; color:#ffffff; font-family:sans-serif;
            }}
            .min-title-{resolved_code} .name-copy {{ cursor:pointer; }}
            .min-title-{resolved_code} .name-copy:hover {{ text-decoration: underline; }}
            </style>
            <div class="min-title-{resolved_code}">
                <span class="name-copy" title="클릭 시 종목코드 복사" onclick="
                    navigator.clipboard.writeText('{resolved_code}');
                    this.innerText='✅ 복사됨';
                    setTimeout(() => {{ this.innerText='{resolved_name_early}'; }}, 900);
                ">{resolved_name_early}</span> ({resolved_code})
            </div>
            """, height=40)
    with _cc[1]:
        with st.container(key="min_refresh_btn_wrap"):
            manual_refresh = st.button("새로")
        st.markdown(
            "<style>"
            ".st-key-min_refresh_btn_wrap { display:flex !important; align-items:center !important; "
            "height:100% !important; }"
            ".st-key-min_refresh_btn_wrap button { white-space:nowrap !important; width:auto !important; "
            "min-width:0 !important; padding:0.25rem 0.6rem !important; "
            "min-height:2.4rem !important; height:2.4rem !important; }"
            ".st-key-min_refresh_btn_wrap button p { white-space:nowrap !important; margin:0 !important; }"
            "</style>",
            unsafe_allow_html=True,
        )
    with _cc[2]:
        auto_refresh = st.checkbox(
            "자동", value=False,
            disabled=not HAS_AUTOREFRESH,
            help=("체크하면 15초마다 자동 새로고침합니다." if HAS_AUTOREFRESH
                  else "pip install streamlit-autorefresh 필요"),
        )
    with _cc[3]:
        with st.container(key="hdr_tmpl_wrap"):
            with st.popover("분차트틀", use_container_width=True):
                _tmpl_options = ["기본", "신호1"]
                _cur_tmpl = st.session_state.get("min_chart_template", "기본")
                _tmpl_idx = _tmpl_options.index(_cur_tmpl) if _cur_tmpl in _tmpl_options else 0
                _sel_tmpl = st.radio(
                    "분봉 차트 틀 선택", _tmpl_options, index=_tmpl_idx,
                    key="min_chart_template_radio",
                    help="기본: 5/20/60/120봉선 + 세력평단 (현재 세팅). "
                         "신호1: 기본 세팅에 평단(핑크)/세력평단(초록+검정 테두리) 라인 추가.",
                )
                if _sel_tmpl != st.session_state.get("min_chart_template", "기본"):
                    st.session_state["min_chart_template"] = _sel_tmpl
                    _save_min_chart_template(_sel_tmpl)
                    st.rerun()
    # (분일): 1/3/5분봉일 때만 활성. 1일 = 기존처럼 당일만, N일 = 최근 N거래일치 캔들
    with _cc[4]:
        _days_cur = st.session_state.get("minute_range_days", MINUTE_RANGE_DAYS_DEFAULT)
        _days_idx = MINUTE_RANGE_DAYS_OPTIONS.index(_days_cur) if _days_cur in MINUTE_RANGE_DAYS_OPTIONS else 0
        with st.container(key="hdr_days_wrap"):
            with st.popover(f"(분일):{_days_cur}", use_container_width=True,
                            disabled=interval_min not in (1, 3, 5),
                            help="1/3/5분봉에서 최근 며칠치 캔들을 이어서 볼지 선택합니다(1일=당일만)."):
                st.selectbox(
                    "조회 기간(일)", MINUTE_RANGE_DAYS_OPTIONS, index=_days_idx,
                    key="minute_range_days", label_visibility="collapsed",
                    format_func=lambda _d: f"{_d}일",
                    on_change=_on_minute_range_days_change,
                )
    # (개월): 10분봉 이상일 때만 활성 (기존에 화면 아래쪽에 있던 '조회기간(개월)'을 이곳으로 이동)
    with _cc[5]:
        _mrm_options = MINUTE_RANGE_MONTHS_OPTIONS
        _mrm_cur = st.session_state.get("minute_range_months", MINUTE_RANGE_MONTHS_DEFAULT)
        _mrm_index = _mrm_options.index(_mrm_cur) if _mrm_cur in _mrm_options else 4
        with st.container(key="hdr_months_wrap"):
            with st.popover(f"(개월):{_mrm_cur}", use_container_width=True,
                            disabled=interval_min < 10,
                            help="10분봉 이상 차트를 몇 개월치 이어서 볼지 선택합니다. "
                                 "개월 수가 적을수록 키움 API 호출 횟수가 줄어 부담이 줄어듭니다."):
                st.selectbox(
                    "조회 기간(개월)", _mrm_options, index=_mrm_index,
                    key="minute_range_months", label_visibility="collapsed",
                    format_func=lambda _m: f"{_m}개월",
                    on_change=_on_minute_range_months_change,
                )
    st.markdown(
        "<style>"
        ".st-key-hdr_tmpl_wrap button, .st-key-hdr_days_wrap button, .st-key-hdr_months_wrap button "
        "{ padding:0.25rem 0.3rem !important; min-height:2.4rem !important; height:2.4rem !important; "
        "white-space:nowrap !important; }"
        ".st-key-hdr_tmpl_wrap button p, .st-key-hdr_days_wrap button p, .st-key-hdr_months_wrap button p "
        "{ white-space:nowrap !important; margin:0 !important; font-weight:700 !important; }"
        # 헤더 줄 위/아래 검정 여백 줄이기(세로 공간 절약)
        "div[data-testid='stHorizontalBlock']:has(.st-key-view_mode_btn_wrap) "
        "{ margin-top:-0.45rem !important; margin-bottom:-0.35rem !important; }"
        "</style>",
        unsafe_allow_html=True,
    )
    with ctrl_cols[3]:
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
                    _snap_override = get_daily_range_snapshot(resolved_code)
                    toggle_watchlist(resolved_code, resolved_name_early, folder=target_folder,
                                      snapshot_override=_snap_override)
                    st.session_state.last_folder = target_folder
                    st.rerun()
    with ctrl_cols[4]:
        if st.session_state.watchlist:
            with st.container(key="memo_move_btn_wrap"):
                with st.popover("✎ 메모 / 폴더이동", use_container_width=True):
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
    if st.session_state.watchlist or len(st.session_state.folders) > 1:
        with ctrl_cols[5]:
            with st.popover("📁 새 폴더", use_container_width=True):
                new_folder_name = st.text_input("폴더 이름", key="new_folder_input", label_visibility="collapsed")
                if st.button("만들기", key="new_folder_btn"):
                    if add_folder(new_folder_name):
                        st.rerun()
                st.markdown(
                    "<style>"
                    ".st-key-new_folder_btn button p { color:#111111 !important; }"
                    ".st-key-folder_reorder_wrap button p { color:#111111 !important; }"
                    "</style>",
                    unsafe_allow_html=True,
                )
                st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)
                st.caption("📌 폴더 순서 변경 (⏮ 맨앞 / ◀▶ 한칸 / ⏭ 맨뒤)")
                with st.container(key="folder_reorder_wrap"):
                    for _ridx, _rfolder in enumerate(st.session_state.folders):
                        _rc1, _rc2, _rc3, _rc4, _rc5 = st.columns([0.13, 0.13, 0.13, 0.13, 0.48])
                        with _rc1:
                            if st.button("⏮", key=f"folder_move_first_{_rfolder}",
                                         disabled=(_ridx == 0), use_container_width=True,
                                         help="맨 왼쪽으로 이동"):
                                st.session_state.folders.pop(_ridx)
                                st.session_state.folders.insert(0, _rfolder)
                                _save_watchlist_data()
                                st.rerun()
                        with _rc2:
                            if st.button("◀", key=f"folder_move_left_{_rfolder}",
                                         disabled=(_ridx == 0), use_container_width=True):
                                st.session_state.folders[_ridx], st.session_state.folders[_ridx - 1] = (
                                    st.session_state.folders[_ridx - 1], st.session_state.folders[_ridx]
                                )
                                _save_watchlist_data()
                                st.rerun()
                        with _rc3:
                            if st.button("▶", key=f"folder_move_right_{_rfolder}",
                                         disabled=(_ridx == len(st.session_state.folders) - 1),
                                         use_container_width=True):
                                st.session_state.folders[_ridx], st.session_state.folders[_ridx + 1] = (
                                    st.session_state.folders[_ridx + 1], st.session_state.folders[_ridx]
                                )
                                _save_watchlist_data()
                                st.rerun()
                        with _rc4:
                            if st.button("⏭", key=f"folder_move_last_{_rfolder}",
                                         disabled=(_ridx == len(st.session_state.folders) - 1),
                                         use_container_width=True, help="맨 오른쪽으로 이동"):
                                st.session_state.folders.pop(_ridx)
                                st.session_state.folders.append(_rfolder)
                                _save_watchlist_data()
                                st.rerun()
                        with _rc5:
                            st.markdown(
                                f"<div style='padding-top:6px; font-size:12px; color:#111111; font-weight:600;'>"
                                f"{_rfolder}</div>",
                                unsafe_allow_html=True,
                            )
        with ctrl_cols[6]:
            if st.button("💾 TXT 저장", key="export_txt_btn", use_container_width=True):
                fname = export_watchlist_txt()
                st.success(f"저장됨: {fname}")

    for _ma_p, _ma_col in zip((240, 480, 720), (ctrl_cols[7], ctrl_cols[8], ctrl_cols[9])):
        with _ma_col:
            st.checkbox(f"{_ma_p}일선", value=False, key=f"ma_on_{_ma_p}")
            st.markdown(
                f"<style>.st-key-ma_on_{_ma_p} label p "
                f"{{ color:{MA_COLORS[_ma_p]} !important; font-weight:600; }}</style>",
                unsafe_allow_html=True,
            )

    if manual_refresh:
        fetch_today_minute_data.clear()
        fetch_minute_data_range.clear()
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
            # 1/3/5분봉: 당일치만. 10분봉부터는 일봉처럼 여러 달치를 이어서 보여준다.
            _warm_df = None  # 지표 계산용(화면에는 안 그림) 이전 분봉
            _range_days = int(st.session_state.get("minute_range_days", 1) or 1)
            if interval_min < 10 and _range_days <= 1:
                with st.spinner("당일 분봉 데이터를 불러오는 중..."):
                    df = fetch_today_minute_data(code, interval_min=interval_min)
                    if not df.empty:
                        _warm_df = fetch_prior_minute_history(code, interval_min)
            elif interval_min < 10:
                # (분일) N일: 1/3/5분봉도 최근 N거래일치 캔들을 이어서 보여준다.
                with st.spinner(f"{interval_min}분봉 데이터(최근 {_range_days}일치)를 불러오는 중..."):
                    df = fetch_minute_data_days(code, interval_min, _range_days, use_local_minute_cache)
                    if not df.empty:
                        _warm_df = fetch_prior_minute_history(
                            code, interval_min, keep_bars=450 + len(df),
                            months=max(1, -(-_range_days // 18)) + 1,
                        )
            else:
                _range_months = minute_range_months or 5
                _spinner_msg = (
                    f"{interval_min}분봉 데이터(최근 {_range_months}개월치, 로컬 캐시 사용)를 불러오는 중..."
                    if use_local_minute_cache else
                    f"{interval_min}분봉 데이터(최근 {_range_months}개월치)를 불러오는 중... "
                    f"기간이 길어 시간이 다소 걸릴 수 있습니다."
                )
                with st.spinner(_spinner_msg):
                    df = fetch_minute_data_range_local_first(
                        code, interval_min=interval_min, months=_range_months,
                        use_local=use_local_minute_cache,
                    )
                # 300봉 볼린저(빨간선) 등 긴 기간 지표용 '보이는 구간 이전' 봉: 보이는 봉이 600개 미만일 때만
                # 별도로 조회하고, 조회에 실패해도 경고 없이 넘어간다(차트 자체는 그대로 표시).
                if not df.empty and len(df) < 600:
                    _warm_df = fetch_minute_warm_history(
                        code, interval_min,
                        _range_months + calc_warm_extra_months(interval_min),
                        df["datetime"].min(),
                    )

            if df.empty:
                st.warning("당일 분봉 데이터를 아직 받아오지 못했습니다. 장 시작 전이거나 일시적 오류일 수 있습니다.")
            else:
                df = calc_seryeok_average(df)

                # 5/20/60/120일선은 항상 고정 on (버튼 없음), 240/480/720일선만 토글 버튼 유지
                FIXED_MA_ON = [5, 20, 60, 120]
                TOGGLE_MA_PERIODS = [240, 480, 720]
                ma_toggles = {p: True for p in FIXED_MA_ON}

                # "목표" 패널(분봉 N봉 언덕 기준선 선택) 열림 여부를 먼저 확인해서,
                # 종목명 + 240/480/720일선 체크박스 + (패널이 열려있을 때만) 5/20/60/120봉
                # 언덕 기준선 버튼을 같은 줄에 함께 배치한다.
                # ※ 목표/목실 상태는 종목별이 아니라 "전역(sticky)"으로 관리한다.
                #   목표(또는 목표+목실)를 켜둔 채로 다른 종목을 선택해도, 목취(또는 목표 재클릭으로
                #   닫기)를 하지 않는 한 계속 켜진 상태가 유지되고, 새로 고른 종목 기준으로
                #   시각(N봉 언덕/세력평단가)이 자동으로 다시 세팅된다.
                NWAVE_MIN_PANEL_KEY = "nwave_min_panel_on"
                NWAVE_MIN_SHOW_KEY = "nwave_min_show_on"
                NWAVE_MIN_AUTO_CODE_KEY = "nwave_min_auto_applied_code"
                nwave_min_panel_open = st.session_state.get(NWAVE_MIN_PANEL_KEY, False)
                _ma_period_labels = {5: "5봉", 20: "20봉", 60: "60봉", 120: "120봉"}
                _ma_period_options = list(_ma_period_labels.keys())
                _ma_period_saved_key = f"nwave_min_ma_period_saved_{code}"
                _ma_period_default = st.session_state.get(_ma_period_saved_key, 5)

                if nwave_min_panel_open:
                    radio_col = st.columns([1.7])[0]

                for p in TOGGLE_MA_PERIODS:
                    ma_toggles[p] = st.session_state.get(f"ma_on_{p}", False)

                if nwave_min_panel_open:
                    with radio_col:
                        nwave_ma_period = st.radio(
                            "목표가 언덕 기준선",
                            _ma_period_options,
                            index=_ma_period_options.index(_ma_period_default)
                            if _ma_period_default in _ma_period_options else 0,
                            format_func=lambda p: _ma_period_labels[p],
                            horizontal=True, key=f"nwave_min_ma_period_{code}",
                            label_visibility="collapsed",
                        )
                    st.session_state[_ma_period_saved_key] = nwave_ma_period
                else:
                    nwave_ma_period = _ma_period_default

                with st.spinner("이동평균선 데이터 불러오는 중..."):
                    ma_values = fetch_daily_ma_values(code)
                _save_ma_toggle_state(ma_toggles)

                # 피보나치 / 거래대금 / 누적거래대금은 항상 표시(네트워크 조회 없이 계산만 하므로 버튼 없이 고정)
                fibo_on, vol_on, cumvol_on = True, True, True

                # 전일比(범례 줄에 같이 표시하기 위해 미리 계산)
                _pred_pre = df.iloc[-1].get("pred_pre", 0) or 0
                _yesterday_close = df.iloc[-1]["close"] - _pred_pre
                _day_pct = (_pred_pre / _yesterday_close * 100) if _yesterday_close else None
                _day_color = "#e05252" if (_day_pct or 0) > 0 else "#4a90e2" if (_day_pct or 0) < 0 else "#eaeef5"

                candle_fill_state = _load_candle_fill_state()

                chart_col_a, chart_col_b = st.columns([16, 29], gap="small")
                # 분봉/일봉 처리 순서: 기본은 분봉 → 일봉, '일먼' 스위치를 켜면 일봉 → 분봉 (주봉/월봉은 아래에서 항상 마지막)
                for _blk in (("day", "min") if st.session_state.get("daily_first", False) else ("min", "day")):
                    if _blk == "min":
                        with chart_col_a:
                            # 왼쪽 열 순서: 분봉 차트 → 주봉/월봉 → 컨트롤. 주봉/월봉은 분봉 → 일봉 다음, 맨 마지막에 그린다.
                            _view_mode_now = st.session_state.get("min_view_mode", "분봉")
                            # 분봉 차트는 컨트롤(시작분/종료분, 범/채/목표/목실/목취) '위'에 보이게 하려고, 자리를 먼저
                            # 만들어 두고 컨트롤(값을 읽어야 함)을 거친 뒤에 이 슬롯에 그린다.
                            _min_chart_slot = st.container()
                            # 주봉/월봉 칸은 분봉 차트 바로 아래, 컨트롤(시작분/종료분, 범/채/목표...) 위에 둔다.
                            # (실제 그리기는 분봉 → 일봉 다음, 맨 마지막에 한다.)
                            _period_slot = st.container() if _view_mode_now in ("주봉", "월봉") else None
                            # ---- 3분봉 세력평단선 시작분/종료분 선택 (+ 목표가 Mapping 패널) ----
                            # (일봉 세력평단가 차트의 시작일/종료일, 목표/목실/목취 버튼과 동일한 개념을
                            #  '일' 대신 '분'/'시각' 기준으로 옮긴 것.)
                            _min_times_all = df["datetime"].dt.time.tolist()

                            _sma5_min_saved_key = f"nwave_min_sma5_saved_{code}"
                            _avg_min_saved_key = f"nwave_min_avg_saved_{code}"
                            _sma5_min_default = st.session_state.get(_sma5_min_saved_key, _min_times_all[-1])
                            _avg_min_default = st.session_state.get(_avg_min_saved_key, _min_times_all[-1])

                            # 목표 패널이 켜진 채로(sticky) 다른 종목을 선택한 경우: 이 종목에 대해서는
                            # 아직 자동 세팅을 한 적이 없으므로, 새 종목 기준으로 N봉 언덕 시각 /
                            # 세력평단가 시각을 자동으로 다시 계산해서 세팅한다. (목실 결과도 그대로 이어짐)
                            if nwave_min_panel_open and st.session_state.get(NWAVE_MIN_AUTO_CODE_KEY) != code:
                                _auto_hill_time_switch = find_min_ma_hill_time(
                                    df, nwave_ma_period, _min_times_all[0], _min_times_all[-1],
                                )
                                if _auto_hill_time_switch is not None:
                                    st.session_state[_sma5_min_saved_key] = _auto_hill_time_switch
                                    _sma5_min_default = _auto_hill_time_switch
                                st.session_state[_avg_min_saved_key] = _min_times_all[-1]
                                _avg_min_default = _min_times_all[-1]
                                st.session_state[NWAVE_MIN_AUTO_CODE_KEY] = code

                            if nwave_min_panel_open:
                                min_row1_c1, min_row1_c2 = st.columns([0.55, 0.45])
                                with min_row1_c1:
                                    min_start_time = minute_hm_input(
                                        "시작분", _min_times_all, _min_times_all[0],
                                        key_prefix=f"min_start_{code}",
                                    )
                                with min_row1_c2:
                                    nwave_sma5_time = minute_hm_input(
                                        f"{nwave_ma_period}봉 언덕 시각", _min_times_all, _sma5_min_default,
                                        key_prefix=f"nwave_min_sma5_{code}",
                                    )
                                _min_row2_left, min_row2_c2 = st.columns([0.55, 0.45])  # 왼쪽은 비움(종료분 삭제)
                                with min_row2_c2:
                                    nwave_avg_time = minute_hm_input(
                                        "세력평단가 시각", _min_times_all, _avg_min_default,
                                        key_prefix=f"nwave_min_avg_{code}",
                                    )
                                st.session_state[_sma5_min_saved_key] = nwave_sma5_time
                                st.session_state[_avg_min_saved_key] = nwave_avg_time
                            else:
                                min_start_col, _min_end_blank = st.columns([0.5, 0.5])  # 오른쪽은 비움(종료분 삭제)
                                with min_start_col:
                                    min_start_time = minute_hm_input(
                                        "시작분", _min_times_all, _min_times_all[0],
                                        key_prefix=f"min_start_{code}",
                                    )
                                # 패널이 숨겨져 있어도 "기억용" 값으로 이전 선택을 그대로 유지
                                nwave_sma5_time = _sma5_min_default
                                nwave_avg_time = _avg_min_default
                                nwave_ma_period = _ma_period_default

                            # 종료분은 선택하지 않고 항상 가장 늦은 시각(최신 봉)으로 고정한다 -> 세력평단선이 끝까지 이어진다.
                            # (여러 날이 이어진 차트에서는 하루 중 가장 늦은 시각이라, 날짜별로 끝이 잘리지도 않는다.)
                            min_end_time = max(_min_times_all)

                            chart_df = df.copy()
                            if min_start_time > min_end_time:
                                st.warning("시작분이 종료분보다 늦습니다.")
                                chart_df["seryeok_avg"] = float("nan")
                            else:
                                _min_mask = (df["datetime"].dt.time >= min_start_time) & \
                                            (df["datetime"].dt.time <= min_end_time)
                                chart_df["seryeok_avg"] = float("nan")
                                _sub_for_vwap = calc_seryeok_average(df.loc[_min_mask].reset_index(drop=True))
                                chart_df.loc[_min_mask, "seryeok_avg"] = _sub_for_vwap["seryeok_avg"].values

                            _last_close_a = float(df["close"].iloc[-1])
                            _vwap_valid_a = chart_df["seryeok_avg"].dropna()
                            _last_vwap_a = float(_vwap_valid_a.iloc[-1]) if not _vwap_valid_a.empty else _last_close_a
                            _gap_pct_a = (_last_close_a - _last_vwap_a) / _last_vwap_a * 100 if _last_vwap_a else 0.0
                            _gap_color_a = CANDLE_UP if _gap_pct_a >= 0 else CANDLE_DOWN

                            # (세력/괴/전 표시는 분봉 차트 아래 정보줄로 옮겼으므로 이 줄에서는 삭제)
                            legend_row_a1, legend_row_a2, legend_row_apanel, legend_row_arun, legend_row_acancel, \
                                _legend_row_spacer = \
                                st.columns([0.55, 0.55, 0.55, 0.55, 0.55, 2.25])
                            with legend_row_a1:
                                show_legend_a = st.checkbox("범", value=False, key=f"legend_min_{code}")
                            with legend_row_a2:
                                fill_a = st.checkbox("채", value=candle_fill_state.get("min_fill_on", False),
                                                     key=f"fill_min_{code}")
                            with legend_row_apanel:
                                if st.button("목표", key="nwave_min_panel_btn",
                                             help="N봉(5/20/60/120) 언덕 / 세력평단가 시각 선택창 펼치기·접기 "
                                                  "(다른 종목을 선택해도 켜둔 상태가 유지됩니다)"):
                                    _panel_will_open = not nwave_min_panel_open
                                    st.session_state[NWAVE_MIN_PANEL_KEY] = _panel_will_open
                                    if _panel_will_open:
                                        # 종목을 바꿀 때마다 매번 손으로 시각을 맞추지 않도록,
                                        # "목표" 버튼으로 패널을 펼 때 N봉 언덕 시각 / 세력평단가 시각을 자동 세팅한다.
                                        _auto_hill_time = find_min_ma_hill_time(
                                            df, nwave_ma_period, min_start_time, min_end_time,
                                        )
                                        if _auto_hill_time is not None:
                                            st.session_state[_sma5_min_saved_key] = _auto_hill_time
                                        st.session_state[_avg_min_saved_key] = _min_times_all[-1]
                                        st.session_state[NWAVE_MIN_AUTO_CODE_KEY] = code
                                    st.rerun()
                            with legend_row_arun:
                                if st.button("목실", key="nwave_min_run_btn", type="primary",
                                             help="N파동 목표가 MAPPING 실행 (T1~T6 값 표시) "
                                                  "(다른 종목을 선택해도 켜둔 상태가 유지됩니다)"):
                                    st.session_state[NWAVE_MIN_SHOW_KEY] = True
                            with legend_row_acancel:
                                if st.button("목취", key="nwave_min_cancel_btn",
                                             help="목실 취소 + 목표 패널 접기 (T1~T6 값 초기화, 원상복귀)"):
                                    st.session_state[NWAVE_MIN_SHOW_KEY] = False
                                    st.session_state[NWAVE_MIN_PANEL_KEY] = False
                                    st.rerun()
                            if fill_a != candle_fill_state.get("min_fill_on", False):
                                candle_fill_state["min_fill_on"] = fill_a
                                _save_candle_fill_state(candle_fill_state)

                            # "목표" 패널이 열려 있고 "목실"을 눌렀을 때만 N파동 목표가 Mapping 계산
                            # (render_chart에 넘겨서 T1~T6 가로 점선을 차트 위에 함께 그리기 위해 미리 계산)
                            _nwave_info_min = None
                            if nwave_min_panel_open and st.session_state.get(NWAVE_MIN_SHOW_KEY) \
                                    and min_start_time <= min_end_time:
                                _nwave_info_min = compute_nwave_mapping_minute(
                                    df, min_start_time, min_end_time, nwave_sma5_time, nwave_avg_time,
                                    ma_period=nwave_ma_period,
                                )

                            # 세력선4(검정 점선 굵기4) 자동 계산 - 종목을 바꿀 때마다 새로 계산됨
                            # (10분봉 이상: 일봉 기법의 자동 시작일 / 1·3·5분봉: 당일 최저점 봉부터)
                            _seryeok4_min_line = compute_seryeok4_minute_line(df, code, interval_min)

                            with _min_chart_slot:
                                render_chart(chart_df, name=resolved_name, code=code, interval_min=interval_min,
                                             seryeok4_line=_seryeok4_min_line, warm_df=_warm_df,
                                         info_line=dict(price=_last_close_a, vwap=_last_vwap_a,
                                                        buy=float(df["seryeok_avg"].iloc[-1]),
                                                        gap=_gap_pct_a, day=_day_pct),
                                             ma_values=ma_values, ma_toggles=ma_toggles,
                                             fibo_on=fibo_on, vol_on=vol_on, cumvol_on=cumvol_on,
                                             show_legend=show_legend_a, fill_candles=fill_a,
                                             nwave_info=_nwave_info_min,
                                             nwave_sma5_time=(nwave_sma5_time if nwave_min_panel_open else None),
                                             nwave_avg_time=(nwave_avg_time if nwave_min_panel_open else None),
                                             min_chart_template=st.session_state.get("min_chart_template", "기본"))
                                render_min_legend_memory(st.session_state.get("min_chart_template", "기본") == "기본")  # 기억 기능은 '기본' 틀만

                            # "목표" 패널이 열려 있고 "목실"을 눌렀을 때만 T1~T6 결과 박스도 표시
                            if nwave_min_panel_open and st.session_state.get(NWAVE_MIN_SHOW_KEY):
                                if min_start_time > min_end_time:
                                    pass  # 위에서 이미 경고 표시함
                                elif _nwave_info_min is not None:
                                    pass  # 차트 아래 T1~T6 정보 박스는 없앰(그 높이만큼 캔들 차트를 키움). 점선/라벨은 차트에 그대로 표시
                                else:
                                    st.caption(f"{nwave_ma_period}봉 언덕 / 세력평단가 시각에 해당하는 데이터가 없습니다. 시각을 다시 선택해주세요.")

                    else:
                        with chart_col_b:
                            # 위젯 생성 전에 "오늘로" 요청을 먼저 반영(위젯 생성 후에는 값을 못 바꾸므로)
                            if st.session_state.get(f"reset_end_today_{code}"):
                                _today0 = date.today()
                                st.session_state[f"daily_end_{code}_y"] = _today0.year
                                st.session_state[f"daily_end_{code}_m"] = _today0.month
                                st.session_state[f"daily_end_{code}_d"] = _today0.day
                                st.session_state[f"reset_end_today_{code}"] = False

                            # "목표" 버튼을 눌러야만 시작일 자동 세팅 + 5이평 언덕/세력평단가 날짜 선택
                            # UI가 펼쳐진다. 평소(패널 닫힘)에는 시작일/종료일만 보여서 기존처럼 빠르게
                            # 조회 가능. ※ 목표/목실 상태는 종목별이 아니라 "전역(sticky)"으로 관리한다.
                            #   목표(또는 목표+목실)를 켜둔 채로 다른 종목을 선택해도, 목취(또는 목표
                            #   재클릭으로 닫기)를 하지 않는 한 계속 켜진 상태가 유지되고, 새로 고른
                            #   종목 기준으로 시작일(세력선4 시작일과 동일) / 5이평 언덕 날짜 / 세력평단가
                            #   날짜가 자동으로 다시 세팅된다. (분봉판 '목표' 패널과 동일한 sticky 패턴)
                            NWAVE_DAILY_PANEL_KEY = "nwave_daily_panel_on"
                            NWAVE_DAILY_SHOW_KEY = "nwave_daily_show_on"
                            NWAVE_DAILY_AUTO_CODE_KEY = "nwave_daily_auto_applied_code"
                            NWAVE_DAILY_FORCE_APPLY_KEY = "nwave_daily_force_apply"
                            nwave_panel_open = st.session_state.get(NWAVE_DAILY_PANEL_KEY, False)

                            # ⚠ Streamlit은 "이번 실행에서 렌더링되지 않은 위젯"의 session_state 값을
                            # 실행이 끝날 때 자동으로 지워버린다. 그래서 패널을 접었다 열면
                            # date_ymd_input의 위젯 키(_y/_m/_d)에 의존한 값은 초기화돼버린다.
                            # 이를 막기 위해 위젯 키와는 별도로 "기억용" 값을 직접 관리한다.
                            _sma5_saved_key = f"nwave_sma5_saved_{code}"
                            _avg_saved_key = f"nwave_avg_saved_{code}"
                            _sma5_default = st.session_state.get(_sma5_saved_key, date.today())
                            _avg_default = st.session_state.get(_avg_saved_key, date.today())
                            # 차트를 넓게(확대 없이) 보여주기 위한 "표시 전용" 시작일 저장 키.
                            # (시작일이 '목표' 자동 세팅으로 최근 날짜로 당겨져도, 차트 자체는 이 키에
                            #  저장된 원래(넓은) 시작일부터 그대로 보여준다)
                            _display_start_key = f"nwave_daily_display_start_{code}"

                            def _apply_nwave_daily_auto(target_code: str):
                                """'목표' 자동 세팅: 시작일을 세력선4 시작일과 동일하게 맞추고, 5이평
                                언덕 날짜(시작일보다 늦은 날짜 중 5일선 언덕 최고점) / 세력평단가 날짜
                                (5이평 언덕 날짜보다 늦은 날짜 중 전저점 쌍바닥을 만든 날짜)를 자동 계산해서
                                채운다. 차트 표시 자체는 확대되지 않도록, 자동 세팅 직전의 시작일을
                                '넓은 표시용 시작일'로 별도 저장해둔다."""
                                _prev_y = st.session_state.get(f"daily_start_{target_code}_y")
                                _prev_m = st.session_state.get(f"daily_start_{target_code}_m")
                                _prev_d = st.session_state.get(f"daily_start_{target_code}_d")
                                try:
                                    _prev_start = date(_prev_y, _prev_m, _prev_d) \
                                        if _prev_y and _prev_m and _prev_d else date(date.today().year, 1, 1)
                                except ValueError:
                                    _prev_start = date(date.today().year, 1, 1)
                                st.session_state[_display_start_key] = _prev_start

                                _auto_dates = compute_seryeok_auto_dates(target_code)
                                _new_start = _auto_dates.get(4, {}).get("start")
                                if _new_start is None:
                                    return
                                st.session_state[f"daily_start_{target_code}_y"] = _new_start.year
                                st.session_state[f"daily_start_{target_code}_m"] = _new_start.month
                                st.session_state[f"daily_start_{target_code}_d"] = _new_start.day

                                _full_df_for_auto = fetch_daily_ohlcv(target_code)
                                if not _full_df_for_auto.empty:
                                    _full_df_for_auto = _full_df_for_auto.copy()
                                    if "ma5" not in _full_df_for_auto.columns:
                                        _full_df_for_auto["ma5"] = _full_df_for_auto["close"].rolling(5).mean()
                                    _today0 = date.today()

                                    # 5이평 언덕 날짜: 시작일보다는 늦은 날짜여야 하고, "지금(재계산 전)
                                    # 세팅되어 있던 5이평 언덕 날짜"보다는 이전 날짜들 중에서 최고점을 찾는다.
                                    # (다시 계산할수록 더 이전 시점의 언덕을 찾아 들어가는 방식)
                                    _prev_hill_date = st.session_state.get(f"nwave_sma5_saved_{target_code}")
                                    _hill_date = None
                                    if isinstance(_prev_hill_date, date) and _prev_hill_date > _new_start:
                                        _hill_upper_bound = _prev_hill_date - timedelta(days=1)
                                        if _hill_upper_bound > _new_start:
                                            _hill_date = _find_daily_sma5_hill_date(
                                                _full_df_for_auto, _new_start, _hill_upper_bound,
                                            )
                                    if _hill_date is None:
                                        # "지금 세팅값"이 없거나(최초 실행) 그 값이 시작일에 너무 가까워
                                        # 검색 구간을 못 만들면, 기존처럼 시작일~오늘 전체에서 찾는다.
                                        _hill_date = _find_daily_sma5_hill_date(_full_df_for_auto, _new_start, _today0)
                                    if _hill_date is None:
                                        _hill_date = _today0

                                    # 세력평단가 날짜: 5이평 언덕 날짜보다 늦은 날짜 중 저가가 가장 낮은 날짜.
                                    _bottom_date = _find_daily_lowest_price_date(_full_df_for_auto, _hill_date, _today0)
                                    if _bottom_date is None:
                                        _bottom_date = _today0
                                    st.session_state[f"nwave_sma5_saved_{target_code}"] = _hill_date
                                    st.session_state[f"nwave_avg_saved_{target_code}"] = _bottom_date

                            # 목표 패널이 켜진 채로(sticky) 다른 종목을 선택한 경우, 또는 방금 "목표"
                            # 버튼을 눌러 자동 재계산을 강제 요청한 경우: 시작일/5이평 언덕 날짜/세력평단가
                            # 날짜를 새로 계산해서 세팅한다.
                            # ⚠ 이 처리는 반드시 아래의 "시작일" date_ymd_input 위젯이 렌더링되기 전에
                            # 실행해야 한다(위젯이 이미 렌더링된 뒤에 같은 위젯 키의 session_state를 직접
                            # 바꾸면 StreamlitAPIException이 발생한다). 그래서 버튼 클릭 핸들러에서는
                            # 직접 계산하지 않고 "강제 재계산 요청" 플래그만 세운 뒤 rerun하고, 실제 계산은
                            # 항상 여기(위젯 렌더링 이전)에서 수행한다.
                            _force_apply = st.session_state.pop(NWAVE_DAILY_FORCE_APPLY_KEY, False)
                            if nwave_panel_open and (_force_apply or st.session_state.get(NWAVE_DAILY_AUTO_CODE_KEY) != code):
                                _apply_nwave_daily_auto(code)
                                st.session_state[NWAVE_DAILY_AUTO_CODE_KEY] = code
                                _sma5_default = st.session_state.get(_sma5_saved_key, date.today())
                                _avg_default = st.session_state.get(_avg_saved_key, date.today())

                            if nwave_panel_open:
                                # 시작일 위, 종료일 아래로 세로 배치 + 그 오른쪽에 N파동 목표가 Mapping용
                                # 5이평 언덕 날짜 / 세력평단가 날짜 선택 (박스 폭은 그만큼 줄여서 한 줄에 배치)
                                nwave_row1_c1, nwave_row1_c2 = st.columns([0.55, 0.45])
                                with nwave_row1_c1:
                                    daily_start = date_ymd_input("시작일", date(date.today().year, 1, 1),
                                                                  key_prefix=f"daily_start_{code}")
                                with nwave_row1_c2:
                                    nwave_sma5_date = date_ymd_input("5이평 언덕 날짜", _sma5_default,
                                                                      key_prefix=f"nwave_sma5_{code}")

                                nwave_row2_c1, nwave_row2_c2 = st.columns([0.55, 0.45])
                                with nwave_row2_c1:
                                    daily_end = date_ymd_input("종료일", date.today(), key_prefix=f"daily_end_{code}",
                                                                show_label=False)
                                with nwave_row2_c2:
                                    nwave_avg_date = date_ymd_input("세력평단가 날짜", _avg_default,
                                                                     key_prefix=f"nwave_avg_{code}")

                                # 위젯이 렌더링된 이번 실행에서 선택값을 "기억용" 키로도 즉시 백업.
                                # (패널을 닫는 다음 실행부터는 위젯 키가 사라지므로, 이 백업이 유일한 저장소가 된다)
                                st.session_state[_sma5_saved_key] = nwave_sma5_date
                                st.session_state[_avg_saved_key] = nwave_avg_date
                            else:
                                daily_start = date_ymd_input("시작일", date(date.today().year, 1, 1),
                                                              key_prefix=f"daily_start_{code}")
                                daily_end = date_ymd_input("종료일", date.today(), key_prefix=f"daily_end_{code}",
                                                            show_label=False)
                                # 패널이 숨겨져 있어도, "기억용" 키에 저장해둔 이전 선택값을 그대로 사용한다.
                                nwave_sma5_date = _sma5_default
                                nwave_avg_date = _avg_default

                            # ---- 세력선1~4: 종목을 고를 때마다 조건에 맞는 시작일이 자동으로 세팅되는
                            # 4개의 추가 세력평단선. 시작일/종료일 박스는 세로 폭을 좁혀 한 줄에 4세트를 배치.
                            # (위젯 key에 종목코드가 포함돼 있어, 종목을 바꾸면 자동계산된 기본값이 새로 적용되고
                            #  같은 종목으로 돌아오면 마지막으로 조정했던 값이 그대로 유지된다) ----
                            _seryeok_auto = compute_seryeok_auto_dates(code)
                            _sr_cols = st.columns(4)
                            seryeok_auto_dates = {}
                            for _sr_n in range(1, 5):
                                with _sr_cols[_sr_n - 1]:
                                    _sr_def = _seryeok_auto.get(_sr_n, {"start": date.today(), "end": date.today()})
                                    _sr_start = date_ymd_input(f"세력선{_sr_n} 시작", _sr_def["start"],
                                                                key_prefix=f"seryeok{_sr_n}_start_{code}")
                                    _sr_end = date_ymd_input(f"세력선{_sr_n} 종료", _sr_def["end"],
                                                              key_prefix=f"seryeok{_sr_n}_end_{code}",
                                                              show_label=False)
                                    seryeok_auto_dates[_sr_n] = {"start": _sr_start, "end": _sr_end}

                            _daily_df_snap = fetch_daily_ohlcv(code)
                            _last_vwap_b = _gap_pct_b = None
                            if not _daily_df_snap.empty and daily_start <= daily_end:
                                _mask_snap = (_daily_df_snap["date"].dt.date >= daily_start) & (_daily_df_snap["date"].dt.date <= daily_end)
                                _sub_snap = _daily_df_snap.loc[_mask_snap]
                                if not _sub_snap.empty:
                                    _cum_vwap_snap = (_sub_snap["close"] * _sub_snap["volume"]).cumsum() / _sub_snap["volume"].cumsum()
                                    _last_vwap_b = float(_cum_vwap_snap.iloc[-1])
                                    _last_close_b = float(_sub_snap["close"].iloc[-1])
                                    _gap_pct_b = (_last_close_b - _last_vwap_b) / _last_vwap_b * 100 if _last_vwap_b else 0.0
                            _gap_color_b = CANDLE_UP if (_gap_pct_b or 0) >= 0 else CANDLE_DOWN

                            st.markdown(
                                "<style>"
                                ".st-key-daily_btn_row_wrap div[data-testid='stHorizontalBlock'] {"
                                "  gap: 0.05rem !important;"
                                "}"
                                ".st-key-daily_btn_row_wrap [data-testid='stCheckbox'],"
                                ".st-key-daily_btn_row_wrap [data-testid='stCheckbox'] * {"
                                "  white-space: nowrap !important;"
                                "}"
                                ".st-key-daily_btn_row_wrap [data-testid='stCheckbox'] label {"
                                "  width: max-content !important;"
                                "}"
                                "</style>",
                                unsafe_allow_html=True,
                            )
                            with st.container(key="daily_btn_row_wrap"):
                                legend_row_b1, legend_row_bnewsref, legend_row_blegend, legend_row_b2, legend_row_bwatch, \
                                    legend_row_bvol, legend_row_bsig, legend_row_bk3, legend_row_b3, legend_row_bpanel, \
                                    legend_row_brun, legend_row_bcancel, legend_row_b4, legend_row_b5, legend_row_b6 = \
                                    st.columns([0.5, 0.5, 0.5, 0.5, 0.55, 0.55, 0.55, 0.55, 0.6, 0.55, 0.55, 0.55, 0.7, 0.75, 0.45])
                                with legend_row_b1:
                                    show_news_b = st.checkbox(
                                        # 새로고침(=새 세션) 시 이전 저장값과 무관하게 항상 체크 해제 상태로 시작
                                        "뉴", value=False,
                                        key=f"news_daily_{code}",
                                        help="현재 종목 실시간 뉴스 속보 1줄을 차트 바로 아래에 표시 (켤 때만 조회, 3분마다 자동 갱신)",
                                    )
                                with legend_row_bnewsref:
                                    manual_news_refresh_clicked = st.button(
                                        "새", key=f"news_refresh_btn_{code}",
                                        help="지금 즉시 뉴스 새로고침 (3분 대기 없이 강제 조회). "
                                             "단, 차단 의심으로 일시중지 중이면 그 시간은 그대로 유지됩니다.",
                                    )
                                with legend_row_blegend:
                                    # 범례(선 이름 목록) 보기: 분봉의 '범'과 같은 기능. 끈 상태(기본)에서는 차트가 예전과 완전히 같다.
                                    show_legend_b = st.checkbox(
                                        "범", value=False, key=f"legend_daily_{code}",
                                        help="차트에 어떤 선이 있는지 선 이름(범례)을 표시합니다",
                                    )
                                with legend_row_b2:
                                    fill_b = st.checkbox("채", value=candle_fill_state.get("daily_fill_on", False),
                                                         key=f"fill_daily_{code}", help="캔들 채움")
                                with legend_row_bwatch:
                                    show_watch_marker = st.checkbox(
                                        "관심", value=candle_fill_state.get("watch_marker_on", False),
                                        key=f"watch_marker_{code}",
                                        help="관심종목 최초 저장일 점선 + 저장일 대비 괴리율 표시",
                                    )
                                with legend_row_bvol:
                                    show_volume_b = st.checkbox("대금", value=candle_fill_state.get("daily_volume_on", True),
                                                                 key=f"volume_daily_{code}",
                                                                 help="일봉 차트 바로 아래에 거래대금 보조지표 표시")
                                with legend_row_bsig:
                                    show_signal_b = st.checkbox("신호", value=candle_fill_state.get("daily_signal_on", True),
                                                                 key=f"signal_daily_{code}",
                                                                 help="키움 조건식 기반 매수 신호(연보라 세모)를 차트에 표시")
                                with legend_row_bk3:
                                    show_kiwoom3_b = st.checkbox(
                                        "3신호", value=candle_fill_state.get("daily_kiwoom3_on", False),
                                        key=f"kiwoom3_daily_{code}",
                                        help="키움 3가지 신호(세모) + 저항선/합성선 7개(선) + 핑크 세로선을 차트에 표시\n"
                                             "신호1(남색): Disparity(25)>=106\n"
                                             "신호2(연두색): MA10>MA20 + 거래량 급증 + 양봉\n"
                                             "신호3(흰색): 볼린저밴드+이격도+엔벨로프 조합\n"
                                             "연하늘선: 41기간 가중이평의 40봉 최고값이 갱신될 때만 올라가는 계단선\n"
                                             "주황색선: Hull이동평균(52)의 80봉 최고값(sscH0)\n"
                                             "벽돌색 굵은선: MACD/이평/CCI/SAR 등 7지표 합성오실레이터 -5 상향돌파 시 종가 유지선\n"
                                             "벽돌색 점선: TEMA(20) 중심선\n"
                                             "보라색선: TRIX(12) 0선 상향돌파 이후 고가 누적 최고값\n"
                                             "하늘색선2: 100봉 신고가 갱신 시점 기준 gb 지지선\n"
                                             "하늘색선3: 25~80봉전 구간 최고/최저 중간값(지연 채널중심선)\n"
                                             "핑크 세로선: 대량거래대금+급등 조건 발생일에 수직선 표시\n"
                                             "흰색 굵은선: 대량거래일(거래량>20일평균×1.5) 기준 240봉 VWAP",
                                    )
                                with legend_row_b3:
                                    if st.button("오늘", key=f"today_btn_{code}"):
                                        st.session_state[f"reset_end_today_{code}"] = True
                                        st.rerun()
                                with legend_row_bpanel:
                                    if st.button("목표", key="nwave_daily_panel_btn",
                                                 help="시작일을 세력선4 시작일과 동일하게 자동 세팅 + "
                                                      "5이평 언덕 / 세력평단가 날짜 자동 세팅 · 선택창 펼치기/접기 "
                                                      "(다른 종목을 선택해도 켜둔 상태가 유지됩니다)"):
                                        _panel_will_open = not nwave_panel_open
                                        st.session_state[NWAVE_DAILY_PANEL_KEY] = _panel_will_open
                                        if _panel_will_open:
                                            # 위젯이 이미 렌더링된 이번 실행에서는 위젯 키를 직접 바꿀 수
                                            # 없으므로, 다음 실행(rerun) 맨 앞에서 자동 계산을 하도록
                                            # "강제 재계산" 플래그만 세워둔다.
                                            st.session_state[NWAVE_DAILY_FORCE_APPLY_KEY] = True
                                        else:
                                            st.session_state.pop(_display_start_key, None)
                                        st.rerun()
                                with legend_row_brun:
                                    if st.button("목실", key="nwave_daily_run_btn", type="primary",
                                                 help="N파동 목표가 MAPPING 실행 (T1~T6 점선 표시) "
                                                      "(다른 종목을 선택해도 켜둔 상태가 유지됩니다)"):
                                        st.session_state[NWAVE_DAILY_SHOW_KEY] = True
                                with legend_row_bcancel:
                                    if st.button("목취", key="nwave_daily_cancel_btn",
                                                 help="목실 취소 + 목표 패널 접기 (T1~T6 값 초기화, 원상복귀)"):
                                        st.session_state[NWAVE_DAILY_SHOW_KEY] = False
                                        st.session_state[NWAVE_DAILY_PANEL_KEY] = False
                                        st.session_state.pop(_display_start_key, None)
                                        st.rerun()
                                with legend_row_b4:
                                    if _last_vwap_b is not None:
                                        seryeok_copy_text(_last_vwap_b, key=f"seryeok_daily_{code}")
                                    else:
                                        st.markdown("<div style='padding-top:6px; font-size:13px;'>세력 -</div>",
                                                    unsafe_allow_html=True)
                                with legend_row_b5:
                                    code_copy_button(code, resolved_name, key=f"codebtn_{code}")
                                with legend_row_b6:
                                    _gap_line = (
                                        f"<div style='padding-top:2px; font-size:13px; font-weight:700; color:{_gap_color_b}; "
                                        f"text-align:right; white-space:nowrap;'>괴 {_gap_pct_b:+.2f}%</div>"
                                        if _gap_pct_b is not None else
                                        "<div style='padding-top:2px; font-size:13px; text-align:right; white-space:nowrap;'>괴 -</div>"
                                    )
                                    _day_line = (
                                        f"<div style='font-size:13px; font-weight:700; color:{_day_color}; "
                                        f"text-align:right; white-space:nowrap;'>전 {_day_pct:+.2f}%</div>"
                                        if _day_pct is not None else
                                        "<div style='font-size:13px; text-align:right; white-space:nowrap;'>전 -</div>"
                                    )
                                    st.markdown(_gap_line + _day_line, unsafe_allow_html=True)
                            show_vwap_sigma_b = st.checkbox(
                                "세력평단 ±3σ 점선 표시",
                                value=st.session_state.get("daily_vwap_sigma_on", False),
                                key=f"daily_vwap_sigma_cb_{code}",
                            )
                            st.session_state["daily_vwap_sigma_on"] = show_vwap_sigma_b
                            if fill_b != candle_fill_state.get("daily_fill_on", False):
                                candle_fill_state["daily_fill_on"] = fill_b
                                _save_candle_fill_state(candle_fill_state)
                            if show_signal_b != candle_fill_state.get("daily_signal_on", True):
                                candle_fill_state["daily_signal_on"] = show_signal_b
                                _save_candle_fill_state(candle_fill_state)
                            if show_kiwoom3_b != candle_fill_state.get("daily_kiwoom3_on", False):
                                candle_fill_state["daily_kiwoom3_on"] = show_kiwoom3_b
                                _save_candle_fill_state(candle_fill_state)
                            if show_volume_b != candle_fill_state.get("daily_volume_on", True):
                                candle_fill_state["daily_volume_on"] = show_volume_b
                                _save_candle_fill_state(candle_fill_state)
                            if show_watch_marker != candle_fill_state.get("watch_marker_on", False):
                                candle_fill_state["watch_marker_on"] = show_watch_marker
                                _save_candle_fill_state(candle_fill_state)
                            if show_news_b != candle_fill_state.get("daily_news_on", False):
                                candle_fill_state["daily_news_on"] = show_news_b
                                _save_candle_fill_state(candle_fill_state)

                            if daily_start > daily_end:
                                st.warning("시작일이 종료일보다 늦습니다.")
                            else:
                                # 패널(목표 버튼)이 닫혀 있으면 목표가 계산·표시 자체를 하지 않는다.
                                # -> 다른 종목 조회 시 첨부1번 사진처럼 이 영역이 아예 안 보이고,
                                #    불필요한 재계산도 돌지 않는다.
                                _nwave_info = None
                                if nwave_panel_open and st.session_state.get(NWAVE_DAILY_SHOW_KEY):
                                    _nwave_info = compute_nwave_mapping(
                                        code, daily_start, daily_end, nwave_sma5_date, nwave_avg_date,
                                    )
                                # '목표' 패널이 열려 있는 동안에는(자동 세팅된 최근 시작일 때문에)
                                # 차트가 확대되지 않도록, 자동 세팅 직전의 "넓은" 시작일을 표시 전용으로 사용.
                                _chart_display_start = st.session_state.get(_display_start_key) if nwave_panel_open else None
                                # '목표'의 시작일/5이평 언덕 날짜/세력평단가 날짜를 차트에 흰 점선으로 표시
                                # (패널이 열려 있을 때만 — 닫혀 있으면 값이 의미가 없으므로 표시하지 않는다)
                                _nwave_marker_dates = (
                                    {"start": daily_start, "sma5": nwave_sma5_date, "avg": nwave_avg_date}
                                    if nwave_panel_open else None
                                )
                                _watch_added_date = get_first_watchlist_added_date(code) if show_watch_marker else None
                                _local_snapshot_str = st.session_state.get("local_snapshot_view_date")
                                _local_snapshot_date = None
                                if _local_snapshot_str:
                                    try:
                                        _local_snapshot_date = date.fromisoformat(_local_snapshot_str)
                                    except ValueError:
                                        _local_snapshot_date = None
                                with st.spinner("일봉 데이터 불러오는 중..."):
                                    render_daily_seryeok_chart(code, resolved_name, daily_start, daily_end,
                                                                show_legend=show_legend_b, fill_candles=fill_b,
                                                                nwave_info=_nwave_info, show_signal=show_signal_b,
                                                                show_volume=show_volume_b,
                                                                show_kiwoom3=show_kiwoom3_b,
                                                                watch_added_date=_watch_added_date,
                                                                local_snapshot_date=_local_snapshot_date,
                                                                seryeok_auto_dates=seryeok_auto_dates,
                                                                chart_display_start_date=_chart_display_start,
                                                                nwave_marker_dates=_nwave_marker_dates,
                                                                view_months=st.session_state.get("daily_view_months"),
                                                                show_vwap_sigma=show_vwap_sigma_b)

                                # "뉴" 버튼을 켰을 때만 차트 바로 아래에 실시간 뉴스속보 1줄 표시.
                                # 꺼두면 아예 렌더링/조회 자체를 하지 않아 다른 종목 전환이 더 빠르다.
                                if show_news_b:
                                    if HAS_AUTOREFRESH:
                                        st_autorefresh(interval=NEWS_POLL_INTERVAL_MS, key=f"news_autorefresh_{code}")
                                    _backoff_remain = get_news_backoff_remaining(code)
                                    # "새" 버튼을 누르면 3분 캐시를 무시하고 즉시 재조회.
                                    # 단, 차단 의심으로 백오프(일시중지) 중이면 그 보호는 그대로 유지한다.
                                    if manual_news_refresh_clicked and _backoff_remain == 0:
                                        _fetch_stock_news_raw.clear()
                                    if _backoff_remain > 0:
                                        # 최근 네이버 응답이 차단성(403/429)이라 잠시 요청을 쉬는 중.
                                        # 이 구간에는 실제 HTTP 요청을 아예 보내지 않는다.
                                        st.markdown(
                                            f'<div style="margin-top:-4px; margin-bottom:6px; padding:5px 10px; '
                                            f'background:{CARD_BG}; border:1px solid {CARD_BORDER}; border-radius:5px; '
                                            f'font-size:12px; color:#e0975a;">'
                                            f'⏸ 뉴스 조회 일시중지 (차단 의심, {_backoff_remain}초 후 재시도)</div>',
                                            unsafe_allow_html=True,
                                        )
                                    else:
                                        _news_data = fetch_latest_stock_news_data(code)
                                        if _news_data:
                                            _news_html = build_news_line_html(_news_data)
                                            st.markdown(
                                                f'<div style="margin-top:-4px; margin-bottom:6px; padding:5px 10px; '
                                                f'background:{CARD_BG}; border:1px solid {CARD_BORDER}; border-radius:5px; '
                                                f'font-size:13px; font-weight:600; width:100%; box-sizing:border-box; '
                                                f'white-space:normal; word-break:keep-all; overflow-wrap:break-word; '
                                                f'line-height:1.4;">'
                                                f'📰 {_news_html}</div>',
                                                unsafe_allow_html=True,
                                            )
                                        else:
                                            _debug_info = st.session_state.get(f"news_debug_{code}", "")
                                            st.markdown(
                                                '<div style="margin-top:-4px; margin-bottom:2px; padding:5px 10px; '
                                                'font-size:12px; color:#ffffff;">📰 최근 뉴스 없음 / 조회 실패</div>',
                                                unsafe_allow_html=True,
                                            )
                                            if _debug_info:
                                                st.markdown(
                                                    f'<div style="margin-top:0; margin-bottom:6px; padding:2px 10px; '
                                                    f'font-size:11px; color:#888;">🔧 진단: {_debug_info}</div>',
                                                    unsafe_allow_html=True,
                                                )
                                if _watch_added_date is not None:
                                    _in_range = daily_start <= _watch_added_date <= daily_end
                                    st.markdown(
                                        f'<div style="font-size:13px; color:#8fd9a8;">'
                                        f'🔖 관심종목 최초 저장일: {_watch_added_date} '
                                        + ("" if _in_range else "(현재 조회 기간 밖이라 차트에 점선으로 표시되지 않음)")
                                        + "</div>",
                                        unsafe_allow_html=True,
                                    )
                                if nwave_panel_open and _nwave_info is not None:
                                    render_nwave_info_boxes(_nwave_info)

                # ---- 주봉/월봉은 맨 마지막(분봉 → 일봉 → 주봉/월봉 순서)에 그려서 일봉이 먼저 바뀌게 한다.
                # 화면 위치는 왼쪽 열 맨 위 슬롯(_period_slot)이라 분봉 차트 위에 보인다. ----
                if _period_slot is not None:
                    with _period_slot:
                        with st.spinner(f"{_view_mode_now} 데이터를 만드는 중..."):
                            render_period_chart(code, resolved_name, _view_mode_now,
                                                fill_candles=candle_fill_state.get("min_fill_on", False))

                # ---- 일봉 로컬(내 PC) 캐시: 분봉과 별도 토글/비우기 버튼. 일봉은 애초에 네이버
                # 금융에서 한 번의 가벼운 요청으로 전체 기간을 받아오는 구조라 분봉처럼 "여러 번
                # 나눠 호출"할 일이 없지만, 오늘치까지 이미 로컬에 저장돼 있으면 그 요청조차
                # 아예 건너뛰도록 해서 앱을 껐다 켜도(메모리 캐시가 날아가도) 다시 네트워크를
                # 타지 않게 해준다. (10분봉 이상을 보고 있을 때는 분봉 쪽 "조회 기간(개월)/로컬/
                # 로컬비우기"도 같은 줄에 함께 배치한다.) ----
                if interval_min >= 10:
                    (_minute_local_col, _minute_clear_col,
                     _daily_local_col1, _daily_local_col2, _daily_local_col3) = st.columns(
                        [0.6, 1, 1, 1.3, 1]
                    )
                else:
                    _daily_local_col1, _daily_local_col2, _daily_local_col3, _ = st.columns([1, 1, 1, 3])

                if interval_min >= 10:
                    with _minute_local_col:
                        st.write("")
                        st.checkbox(
                            "로컬", value=st.session_state.get("minute_local_cache_on", True),
                            key="minute_local_cache_on",
                            help="켜두면, 확정된(오늘 이전) 분봉은 한 번 받아온 뒤 이 PC에 저장해두고 "
                                 "다음부터는 그걸 그대로 씁니다(키움에 재조회하지 않음). 오늘치 분봉만 "
                                 "매번 가볍게 새로 받아옵니다. 끄면 매번 키움에서 전부 새로 받아옵니다.",
                        )
                    with _minute_clear_col:
                        st.write("")
                        if st.button("로컬 비우기", key="minute_local_cache_clear_btn",
                                     help="저장해둔 10분봉 이상 로컬 캐시 파일을 전부 삭제합니다."):
                            _n_cleared = clear_minute_local_cache()
                            fetch_minute_data_range.clear()
                            st.success(f"로컬 분봉 캐시 {_n_cleared}개 파일을 비웠습니다.")

                with _daily_local_col1:
                    if interval_min >= 10:
                        st.write("")
                    use_daily_local_cache = st.checkbox(
                        "일봉 로컬", value=st.session_state.get("daily_local_cache_on", True),
                        key="daily_local_cache_on",
                        help="켜두면 오늘치까지 이미 로컬(이 PC)에 저장된 일봉 데이터는 "
                             "네이버에 다시 요청하지 않고 그대로 씁니다. 앱을 껐다 켜도 "
                             "유지됩니다. (일봉은 원래 요청 1번으로 전체 기간을 받아오는 구조라 "
                             "분봉만큼 부담이 크진 않지만, 그 요청 자체도 아예 건너뛰고 싶을 때 켜세요)",
                    )
                with _daily_local_col2:
                    if interval_min >= 10:
                        st.write("")
                    if st.button("일봉 로컬비우기", key="daily_local_cache_clear_btn",
                                 help="저장해둔 일봉 로컬 캐시 파일을 전부 삭제합니다."):
                        _n_daily_cleared = clear_daily_local_cache()
                        st.success(f"일봉 로컬 캐시 {_n_daily_cleared}개 파일을 비웠습니다.")
                with _daily_local_col3:
                    if interval_min >= 10:
                        st.write("")
                    with st.popover("일날짜크기", use_container_width=True,
                                     help="일봉 차트에 처음 보여줄 화면 기간(개월수)을 고릅니다. "
                                          "전체 데이터는 그대로 유지되고 화면에 처음 보이는 범위만 "
                                          "좁아지며, 차트에서 드래그/줌아웃하면 이전 데이터도 그대로 "
                                          "다시 볼 수 있습니다. 새로고침해도 고른 개월수가 유지됩니다."):
                        _dvm_cur = st.session_state.get("daily_view_months")
                        _dvm_labels = ["전체"] + [f"{m}개월" for m in DAILY_VIEW_MONTHS_OPTIONS]
                        _dvm_index = (
                            0 if _dvm_cur not in DAILY_VIEW_MONTHS_OPTIONS
                            else DAILY_VIEW_MONTHS_OPTIONS.index(_dvm_cur) + 1
                        )
                        _dvm_choice = st.radio(
                            "일봉 화면 표시 개월수", _dvm_labels, index=_dvm_index,
                            key="daily_view_months_radio", label_visibility="collapsed",
                        )
                        _dvm_new = None if _dvm_choice == "전체" else int(_dvm_choice[:-2])
                        if _dvm_new != st.session_state.get("daily_view_months"):
                            st.session_state["daily_view_months"] = _dvm_new
                            _save_daily_view_months(_dvm_new)
                            st.rerun()

                last = df.iloc[-1]

                # 현재가/세력평단(매수 기준)/세력평단比/평단 대비 카드는 삭제(분봉 차트 아래 정보줄로 대체).
                # 나머지 카드는 원래 폭(1/7) 그대로 왼쪽으로 붙인다.
                c5, c6, c7, _c_spacer = st.columns([1, 1, 1, 4])
                diff = last["close"] - last["seryeok_avg"]
                diff_color = "#e05252" if diff > 0 else "#4a90e2" if diff < 0 else "#eaeef5"
                vwap_pct = diff / last["seryeok_avg"] * 100 if last["seryeok_avg"] else None
                acc_amount = (df["close"] * df["volume"]).sum()
                marcap = marketcap_map.get(code)
                with c5:
                    copy_metric(
                        "3분봉 누적거래대금",
                        format_krw_large(acc_amount),
                        f"{acc_amount:,.0f}",
                    )
                with c6:
                    _c7a, _c7b, _c7c = st.columns([4, 0.9, 0.9], gap="small")
                    with _c7a:
                        copy_metric(
                            "시가총액",
                            format_krw_large(marcap) if marcap else "정보 없음",
                            f"{marcap:,.0f}" if marcap else "-",
                        )
                    st.markdown(
                        "<style>"
                        ".st-key-daily_cache_wrap .stButton button {"
                        "  padding: 0.02rem 0.05rem !important; min-height: 18px !important;"
                        "  font-size: 9px !important; line-height: 1 !important;"
                        "}"
                        "</style>",
                        unsafe_allow_html=True,
                    )
                    _daily_mode = st.session_state.get("daily_cache_mode", "1h")
                    _daily_btns = [("1h", "1시간후", _c7b), ("12h", "12시간후", _c7c)]
                    with st.container(key="daily_cache_wrap"):
                        for _dval, _dlabel, _dcol in _daily_btns:
                            with _dcol:
                                _d_on = (_daily_mode == _dval)
                                if st.button(_dlabel, key=f"daily_cache_btn_{_dval}", use_container_width=True,
                                             type="primary" if _d_on else "secondary",
                                             help="일봉 데이터 캐시 주기"):
                                    st.session_state["daily_cache_mode"] = _dval
                                    _save_daily_cache_mode(_dval)
                                    st.rerun()
                with c7:
                    _watch_gap_info = compute_watchlist_gap(code, last["close"]) if show_watch_marker else None
                    if _watch_gap_info is not None:
                        _wg = _watch_gap_info["gap"]
                        _wg_color = "#ff4fa3" if _wg >= 0 else "#00e5ff"
                        copy_metric(
                            "관심종목 괴리율",
                            f"{_wg:+.2f}%",
                            f"{_wg:+.2f}%",
                            delta_text=f"저장일 {_watch_gap_info['actual_date']}",
                            value_color=_wg_color,
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
    interest_col, whitenv_col, week_col, shared_white_col, check_all_col, clear_chk_col, shared_col2 = st.columns(
        [0.8, 0.85, 0.65, 0.6, 0.7, 0.7, 1], gap="small"
    )
    with interest_col:
        st.markdown(
            "<style>.st-key-interest_wrap button { background-color:#f4c430 !important; color:#111 !important; }</style>",
            unsafe_allow_html=True,
        )
        with st.container(key="interest_wrap"):
            _n_checked = len(st.session_state.checked_stocks)
            with st.popover(f"관심({_n_checked})" if _n_checked else "관심"):
                _checked_items = [{"code": c, "name": n} for c, n in st.session_state.checked_stocks.items()]
                if _checked_items:
                    st.caption(f"{len(_checked_items)}종목 선택됨 - 저장할 폴더를 고르세요")
                    _items_to_add = _checked_items
                elif resolved_code is not None:
                    # 네이버인기테마/업종테마에 체크한 종목이 하나도 없어도,
                    # 지금 조회 중인(분봉/일봉 차트로 보고 있는) 종목을 저장할 수 있게 한다.
                    st.caption(f"체크된 종목 없음 → 현재 종목 '{resolved_name_early}' 저장 - 저장할 폴더를 고르세요")
                    _items_to_add = [{"code": resolved_code, "name": resolved_name_early}]
                else:
                    st.caption("체크된 종목도 없고, 조회 중인 종목도 없습니다.")
                    _items_to_add = []

                if _items_to_add:
                    _today_folder_name = datetime.now().strftime("%Y.%m.%d")
                    _show_virtual_today = _today_folder_name not in st.session_state.folders
                    for _fidx, _folder in enumerate(st.session_state.folders):
                        if st.button(f"📁 {_folder}", key=f"save_checked_to_{_folder}", use_container_width=True):
                            add_items_to_folder(_items_to_add, _folder)
                            st.session_state.checked_stocks = {}
                            st.rerun()
                        if _fidx == 0 and _show_virtual_today:
                            if st.button(f"🗓️ {_today_folder_name} (신규)", key="save_checked_to_today_virtual",
                                         use_container_width=True):
                                add_folder(_today_folder_name)
                                add_items_to_folder(_items_to_add, _today_folder_name)
                                st.session_state.checked_stocks = {}
                                st.rerun()

                    st.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)
                    if st.button("📂 새폴더 만들기", key="new_folder_make_btn", use_container_width=True):
                        st.session_state["show_new_folder_form"] = True
                    if st.session_state.get("show_new_folder_form"):
                        with st.form(key="new_folder_form", clear_on_submit=True):
                            _new_folder_name = st.text_input(
                                "새 폴더 이름", key="new_folder_name_val", label_visibility="collapsed",
                                placeholder="폴더 이름 입력 후 Enter",
                            )
                            _new_folder_submitted = st.form_submit_button("만들기", use_container_width=True)
                            if _new_folder_submitted and _new_folder_name.strip():
                                _new_name = _new_folder_name.strip()
                                _created = add_folder(_new_name)
                                if _created or _new_name in st.session_state.folders:
                                    add_items_to_folder(_items_to_add, _new_name)
                                    st.session_state.checked_stocks = {}
                                    st.session_state["show_new_folder_form"] = False
                                    st.rerun()
                        if st.button("취소", key="new_folder_cancel_btn", use_container_width=True):
                            st.session_state["show_new_folder_form"] = False
                            st.rerun()
    with whitenv_col:
        _whitenv_pop_ver = st.session_state.get("whitenv_popover_ver", 0)
        # (예전 스캔 버튼 변수: 아래 pending 처리 코드가 참조하므로 False로 둔다)
        _gangnamyeon_clicked = _white_scan_clicked = _vblue_clicked = False
        _gwayeon_clicked = _yeokbaejeongcho_clicked = _kkotyeolmae_clicked = False
        _daily_prefetch_clicked = False
        _whitenv_reset_clicked = False
        _render_whitenv_popover()  # 흰네업 팝오버(프래그먼트): 안의 클릭은 앱 전체를 다시 그리지 않는다
    with week_col:
        _week_pop_ver = st.session_state.get("week_popover_ver", 0)
        with st.popover(
            "일주", key=f"week_popover_v{_week_pop_ver}", use_container_width=True,
            help="흰네업과 똑같은 신호 버튼들이지만, 당일이 아니라 1주일 전부터 어제까지 사이에 "
                 "그 신호가 한 번이라도 뜬 적 있는 종목을 찾습니다.\n"
                 "네이버인기테마(1~30위) → 업종테마(1~30위) 순서로 테마를 하나씩 처리하고 "
                 "사이사이 딜레이를 둬서 네이버·키움 부담을 줄이는 방식이라 시간이 다소 걸릴 수 있습니다.",
        ):
            _week_reset_clicked = st.button(
                "리셋", key="week_filter_reset_btn", use_container_width=True,
                help="위 신호 버튼으로 켜진 화면 필터(표시 제한)만 끄고 원래대로 돌립니다. "
                     "이미 관심종목에 체크된 종목은 그대로 남습니다.",
            )
            st.divider()
            _week_gangnamyeon_clicked = st.button(
                "강남연", key="week_gangnamyeon_signal_auto_scan_btn", use_container_width=True,
                help="신호1(대량거래대금 급등) + 신호2(이격도25≥106) + 신호3(단기이평 골든크로스+거래량폭증) "
                     "3개 신호가 1주일 전부터 어제까지 사이에 동시에 뜬 적 있는 종목을 찾습니다.",
            )
            _week_white_clicked = st.button(
                "흰", key="week_white_signal_auto_scan_btn", use_container_width=True,
                help="일봉 세력평단가 차트의 흰신호(신호3)가 1주일 전부터 어제까지 사이에 뜬 적 있는 "
                     "종목을 찾습니다.",
            )
            _week_vblue_clicked = st.button(
                "수직파랑", key="week_vertical_blue_signal_auto_scan_btn", use_container_width=True,
                help="이수식 신호(120일 신고가 돌파 기준 TargetLine 상향 돌파)가 1주일 전부터 어제까지 "
                     "사이에 뜬 적 있는 종목을 찾습니다.",
            )
            _week_gwayeon_clicked = st.button(
                "과연", key="week_gwayeon_signal_auto_scan_btn", use_container_width=True,
                help="신호1(이격도25≥106) + 신호2(단기이평 골든크로스+거래량폭증) 2개 신호가 1주일 전부터 "
                     "어제까지 사이에 동시에 뜬 적 있는 종목을 찾습니다.",
            )
            _week_yeokbaejeongcho_clicked = st.button(
                "역배정초", key="week_yeokbaejeongcho_signal_auto_scan_btn", use_container_width=True,
                help="역배정초 신호(BBU300 우상향 + 이평20 눌림목 반등 + 볼밴/60일선 상향돌파 + "
                     "거래대금 필터)가 1주일 전부터 어제까지 사이에 뜬 적 있는 종목을 찾습니다.",
            )
            _week_kkotyeolmae_clicked = st.button(
                "꽃열매", key="week_kkotyeolmae_signal_auto_scan_btn", use_container_width=True,
                help="꽃열매 신호(PriceOsc 이중 조건 + 40봉 신고가 + 거래대금 필터 + 양봉)가 "
                     "1주일 전부터 어제까지 사이에 뜬 적 있는 종목을 찾습니다.",
            )
    with shared_white_col:
        _active_filter = st.session_state.get("active_list_filter")
        _filter_pop_ver = st.session_state.get("filter_popover_ver", 0)
        _filter_wrap_key = "list_filter_toggle_wrap"
        if _active_filter:
            st.markdown(
                f"<style>.st-key-{_filter_wrap_key} button {{ background-color:#ffffff !important; "
                f"border-color:#ffffff !important; }}"
                f".st-key-{_filter_wrap_key} button p {{ color:#111 !important; font-weight:800; }}</style>",
                unsafe_allow_html=True,
            )
        with st.container(key=_filter_wrap_key):
            with st.popover(
                _active_filter if _active_filter else "필터",
                key=f"list_filter_popover_v{_filter_pop_ver}", use_container_width=True,
                help="켜두면 테마를 펼칠 때 선택한 신호가 뜬 종목만 표시되고, 옆 숫자도 그 개수로 "
                     "줄어듭니다. 위 4개는 당일 기준, 구분선 아래 '일주·' 4개는 1주일 전부터 어제까지 "
                     "기준입니다. 종목마다 일봉 데이터를 확인해야 해서 켜두면 네이버·키움 조회 부담이 "
                     "늘어나니, 확인 후에는 같은 버튼을 한 번 더 눌러 꺼주세요. "
                     "(검색상위30·거래대금상위30·거래량순위30·NXT거래상위30 공통)",
            ):
                _filter_reset_clicked = st.button(
                    "리셋", key="list_filter_reset_btn", use_container_width=True,
                    help="위에서 어떤 걸 켰든 상관없이 필터를 끄고 원래대로 돌립니다.",
                )
                st.divider()
                _filter_white_clicked = st.button(
                    "흰", key="list_filter_white_btn", use_container_width=True,
                    help="당일 흰신호(신호3, 일봉 세력평단가 차트)가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_gangnam_clicked = st.button(
                    "강남연", key="list_filter_gangnamyeon_btn", use_container_width=True,
                    help="당일 강남연 신호(신호1+신호2+신호3 동시발생)가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_vblue_clicked = st.button(
                    "수직파랑", key="list_filter_vblue_btn", use_container_width=True,
                    help="당일 수직파랑 신호가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_gwayeon_clicked = st.button(
                    "과연", key="list_filter_gwayeon_btn", use_container_width=True,
                    help="당일 과연 신호(신호1+신호2 동시발생)가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_yeokbaejeongcho_clicked = st.button(
                    "역배정초", key="list_filter_yeokbaejeongcho_btn", use_container_width=True,
                    help="당일 역배정초 신호가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_kkotyeolmae_clicked = st.button(
                    "꽃열매", key="list_filter_kkotyeolmae_btn", use_container_width=True,
                    help="당일 꽃열매 신호가 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                st.markdown("---")
                _filter_week_gangnam_clicked = st.button(
                    "일주·강남연", key="list_filter_week_gangnamyeon_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 강남연 신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_week_white_clicked = st.button(
                    "일주·흰", key="list_filter_week_white_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 흰신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_week_vblue_clicked = st.button(
                    "일주·수직파랑", key="list_filter_week_vblue_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 수직파랑 신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_week_gwayeon_clicked = st.button(
                    "일주·과연", key="list_filter_week_gwayeon_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 과연 신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_week_yeokbaejeongcho_clicked = st.button(
                    "일주·역배정초", key="list_filter_week_yeokbaejeongcho_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 역배정초 신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_week_kkotyeolmae_clicked = st.button(
                    "일주·꽃열매", key="list_filter_week_kkotyeolmae_btn", use_container_width=True,
                    help="1주일 전부터 어제까지 사이 꽃열매 신호가 뜬 적 있는 종목만 표시. 다시 누르면 꺼집니다.",
                )
                st.markdown("---")
                _filter_gangse2_clicked = st.button(
                    "하루전90강세둘", key="list_filter_gangse2_btn", use_container_width=True,
                    help="avg(거래대금,1)≥15000 and C(1)×1.15≤H and L×1.15≤H and O×1.09≤C 신호가 "
                         "하루 전부터 90일 사이에 2번 이상 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_gangse_today90_2plus_clicked = st.button(
                    "당일90강세둘이상", key="list_filter_gangse_today90_2plus_btn", use_container_width=True,
                    help="같은 신호가 당일부터 90일 사이에 2번 이상 뜬 종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_gangse_today7m_2exact_clicked = st.button(
                    "당일7개월강세둘만", key="list_filter_gangse_today7m_2exact_btn", use_container_width=True,
                    help="같은 신호가 당일부터 7개월(데이터 부족 시 최소 6개월) 사이에 정확히 2번만 뜬 "
                         "종목만 표시. 다시 누르면 꺼집니다.",
                )
                _filter_gangse_today7m_3plus_clicked = st.button(
                    "당일7개월강세셋이상", key="list_filter_gangse_today7m_3plus_btn", use_container_width=True,
                    help="같은 신호가 당일부터 7개월(데이터 부족 시 최소 6개월) 사이에 3번 이상 뜬 "
                         "종목만 표시. 다시 누르면 꺼집니다.",
                )
        if _filter_white_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "흰" else "흰"
            st.rerun()
        if _filter_gangnam_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "강남연" else "강남연"
            st.rerun()
        if _filter_vblue_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "수직파랑" else "수직파랑"
            st.rerun()
        if _filter_gwayeon_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "과연" else "과연"
            st.rerun()
        if _filter_yeokbaejeongcho_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "역배정초" else "역배정초"
            st.rerun()
        if _filter_kkotyeolmae_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "꽃열매" else "꽃열매"
            st.rerun()
        if _filter_week_gangnam_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "일주·강남연" else "일주·강남연"
            st.rerun()
        if _filter_week_white_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "일주·흰" else "일주·흰"
            st.rerun()
        if _filter_week_vblue_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "일주·수직파랑" else "일주·수직파랑"
            st.rerun()
        if _filter_week_gwayeon_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "일주·과연" else "일주·과연"
            st.rerun()
        if _filter_week_yeokbaejeongcho_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = (
                None if _active_filter == "일주·역배정초" else "일주·역배정초"
            )
            st.rerun()
        if _filter_week_kkotyeolmae_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = (
                None if _active_filter == "일주·꽃열매" else "일주·꽃열매"
            )
            st.rerun()
        if _filter_gangse2_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None if _active_filter == "하루전90강세둘" else "하루전90강세둘"
            st.rerun()
        if _filter_gangse_today90_2plus_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = (
                None if _active_filter == "당일90강세둘이상" else "당일90강세둘이상"
            )
            st.rerun()
        if _filter_gangse_today7m_2exact_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = (
                None if _active_filter == "당일7개월강세둘만" else "당일7개월강세둘만"
            )
            st.rerun()
        if _filter_gangse_today7m_3plus_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = (
                None if _active_filter == "당일7개월강세셋이상" else "당일7개월강세셋이상"
            )
            st.rerun()
        if _filter_reset_clicked:
            st.session_state["filter_popover_ver"] = _filter_pop_ver + 1
            st.session_state["active_list_filter"] = None
            st.session_state.pop("multi_signal_filter", None)
            st.rerun()
    with check_all_col:
        if st.button(
            "체관", key="check_all_visible_btn", use_container_width=True,
            help="이미 펼쳐봐서 우측에 숫자가 표시된 테마들 중, 보이는 종목이 1개 이상인 "
                 "테마의 '전체선택'을 한 번에 켜서 그 종목들을 관심종목에 체크합니다. "
                 "(아직 한 번도 안 펼쳐본 테마는 대상에서 빠집니다)",
        ):
            _run_check_all_visible_themes()
            st.rerun()
    with clear_chk_col:
        if st.button(
            "체취", key="clear_all_checks_btn", use_container_width=True,
            help="관심종목 저장용으로 체크해둔 종목들과, 테마별 '전체선택' + 종목별 '선택' "
                 "체크 상태를 전부 해제합니다.",
        ):
            st.session_state.checked_stocks = {}
            st.session_state["stock_chk_reset_ver"] = st.session_state.get("stock_chk_reset_ver", 0) + 1
            st.rerun()
    with shared_col2:
        st.checkbox("천억↓", value=True, key="shared_hide_smallcap",
                    help="시가총액 1000억원 미만 종목을 목록에서 숨깁니다. (네이버·업종테마 공통)")

    _scan_status_box = st.empty()

    # 팝오버(흰네업) 안에서 신호 버튼을 누르면: 1) 팝오버 키 버전을 올려서 팝오버가 바로 닫히게 하고
    # 2) 어떤 신호를 스캔할지 pending 상태로 저장한 뒤 즉시 rerun한다.
    # 실제 스캔(+진행 상황 표시)은 팝오버가 이미 닫힌 다음 rerun에서 진행한다.
    if _gangnamyeon_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "강남연"
        st.rerun()
    if _white_scan_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "흰"
        st.rerun()
    if _vblue_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "수직파랑"
        st.rerun()
    if _gwayeon_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "과연"
        st.rerun()
    if _yeokbaejeongcho_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "역배정초"
        st.rerun()
    if _kkotyeolmae_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["whitenv_pending_scan"] = "꽃열매"
        st.rerun()
    if _week_gangnamyeon_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "강남연"
        st.rerun()
    if _week_white_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "흰"
        st.rerun()
    if _week_vblue_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "수직파랑"
        st.rerun()
    if _week_gwayeon_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "과연"
        st.rerun()
    if _week_yeokbaejeongcho_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "역배정초"
        st.rerun()
    if _week_kkotyeolmae_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["week_pending_scan"] = "꽃열매"
        st.rerun()
    if _whitenv_reset_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["active_list_filter"] = None
        st.rerun()
    if _week_reset_clicked:
        st.session_state["week_popover_ver"] = _week_pop_ver + 1
        st.session_state["active_list_filter"] = None
        st.rerun()

    if _daily_prefetch_clicked:
        st.session_state["whitenv_popover_ver"] = _whitenv_pop_ver + 1
        st.session_state["daily_prefetch_pending"] = True
        st.rerun()

    _pending_scan = st.session_state.get("whitenv_pending_scan")
    if _pending_scan == "강남연":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("강남연 진행 중... (네이버→업종 순서로 당일 강남연 신호 종목을 찾는 중)"):
            _run_gangnamyeon_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _pending_scan == "흰":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("흰 진행 중... (네이버→업종 순서로 당일 흰신호 종목을 찾는 중)"):
            _run_white_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _pending_scan == "수직파랑":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("수직파랑 진행 중... (네이버→업종 순서로 당일 수직파랑 신호 종목을 찾는 중)"):
            _run_vertical_blue_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _pending_scan == "과연":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("과연 진행 중... (네이버→업종 순서로 당일 과연 신호 종목을 찾는 중)"):
            _run_gwayeon_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _pending_scan == "역배정초":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("역배정초 진행 중... (네이버→업종 순서로 당일 역배정초 신호 종목을 찾는 중)"):
            _run_yeokbaejeongcho_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _pending_scan == "꽃열매":
        st.session_state["whitenv_pending_scan"] = None
        with st.spinner("꽃열매 진행 중... (네이버→업종 순서로 당일 꽃열매 신호 종목을 찾는 중)"):
            _run_kkotyeolmae_signal_auto_scan(status_box=_scan_status_box)
        st.rerun()

    if st.session_state.get("daily_prefetch_pending"):
        st.session_state["daily_prefetch_pending"] = False
        with st.spinner("일봉 받아두기 진행 중... (저장된 급등순위·업종테마 종목의 일봉을 로컬에 저장하는 중)"):
            _run_daily_prefetch(status_box=_scan_status_box)
        st.rerun()

    _week_pending_scan = st.session_state.get("week_pending_scan")
    if _week_pending_scan == "강남연":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·강남연 진행 중... (네이버→업종 순서로 1주일 내 강남연 신호 종목을 찾는 중)"):
            _run_gangnamyeon_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _week_pending_scan == "흰":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·흰 진행 중... (네이버→업종 순서로 1주일 내 흰신호 종목을 찾는 중)"):
            _run_white_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _week_pending_scan == "수직파랑":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·수직파랑 진행 중... (네이버→업종 순서로 1주일 내 수직파랑 신호 종목을 찾는 중)"):
            _run_vertical_blue_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _week_pending_scan == "과연":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·과연 진행 중... (네이버→업종 순서로 1주일 내 과연 신호 종목을 찾는 중)"):
            _run_gwayeon_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _week_pending_scan == "역배정초":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·역배정초 진행 중... (네이버→업종 순서로 1주일 내 역배정초 신호 종목을 찾는 중)"):
            _run_yeokbaejeongcho_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()
    elif _week_pending_scan == "꽃열매":
        st.session_state["week_pending_scan"] = None
        with st.spinner("일주·꽃열매 진행 중... (네이버→업종 순서로 1주일 내 꽃열매 신호 종목을 찾는 중)"):
            _run_kkotyeolmae_signal_week_auto_scan(status_box=_scan_status_box)
        st.rerun()

    _scan_summary = st.session_state.get("white_auto_scan_summary")
    if _scan_summary:
        _scan_label = _scan_summary.get("label", "흰")
        # label이 이미 "일주·강남연"처럼 접두어를 포함하고 있으면 그대로 쓰고,
        # 흰네업 계열("강남연"/"흰"/"수직파랑"/"과연")이면 "흰네업 · " 접두어를 붙인다.
        _scan_caption_head = _scan_label if _scan_label.startswith("일주") else f"흰네업 · {_scan_label}"
        _a_label = _scan_summary.get("a_label", "네이버")
        _b_label = _scan_summary.get("b_label", "업종")
        _scan_status_box.caption(
            f"{_scan_caption_head} 결과({_scan_summary['ts']}): "
            f"{_a_label} {_scan_summary['naver_found']}건 · "
            f"{_b_label} {_scan_summary['kiwoom_found']}건 발견 → "
            f"중복 제외 실제 {_scan_summary['unique_found']}종목 관심 체크됨"
        )

    _save_checked_stocks_if_changed()
    _mt = st.session_state.pop("multi_sig_toast", None)
    if _mt:
        st.toast(_mt, icon="📅")
    _multi_cfg = st.session_state.get("multi_signal_filter")
    if _multi_cfg:
        _fmt_d = lambda iso: iso.replace("-", ".")
        _rng_txt = _fmt_d(_multi_cfg["start"]) if _multi_cfg["start"] == _multi_cfg["end"] \
            else f"{_fmt_d(_multi_cfg['start'])} ~ {_fmt_d(_multi_cfg['end'])}"
        _off_txt = ""
        if _multi_cfg["start"] == _multi_cfg["end"]:
            _n_txt = _day_off_note(date.fromisoformat(_multi_cfg["start"]))
            if _n_txt:
                _off_txt = f" ⚠ {_n_txt}"
        st.caption(f"🔎 신호 동시발생 필터 적용 중: {' + '.join(_multi_cfg['signals'])} · {_rng_txt}{_off_txt} "
                   f"(흰네업 → 리셋으로 해제)")

    _pf = st.session_state.get("daily_prefetch_summary")
    if _pf:
        st.caption(
            f"일봉 받아두기 결과({_pf['ts']}): 총 {_pf['total']}종목 중 전체 새로 받음 {_pf['downloaded']} · "
            f"새 날짜만 이어붙임 {_pf.get('appended', 0)} · 이미 최신이라 건너뜀 {_pf['skipped']} · 실패 {_pf['failed']}"
        )

    st.markdown(
        "<style>"
        ".st-key-amt_preset_row button {"
        "  padding: 0.05rem 0.25rem !important; min-height: 20px !important;"
        "  font-size: 10.5px !important; line-height: 1 !important;"
        "}"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="amt_preset_row"):
        # ("없음" = 안함, 그 뒤로 30억~1000억 미만 숨기기) - 대금 팝오버의 라디오 선택과 완전히 동일한 상태를 공유
        _amt_quick_choices = [("없음", "안함")] + [(f"{_p}↓", f"{_p}억 미만 숨기기") for _p in AMT_HIDE_PRESETS]
        preset_cols = st.columns(len(_amt_quick_choices) + 1, gap="small")
        _current_choice = st.session_state.get("shared_amt_hide_choice", "안함")

        with preset_cols[0]:
            with st.popover("대금", help="거래대금 숨김 기준 (네이버·업종테마 공통)", use_container_width=True):
                _amt_options_list = list(AMT_HIDE_OPTIONS.keys())
                _amt_cur_idx = _amt_options_list.index(_current_choice) if _current_choice in _amt_options_list else 0
                _amt_radio_ver = st.session_state.get("_amt_hide_radio_ver", 0)
                _amt_radio_val = st.radio(
                    "숨길 기준 선택", options=_amt_options_list, index=_amt_cur_idx,
                    key=f"amt_hide_radio_v{_amt_radio_ver}",
                )
                if _amt_radio_val != _current_choice:
                    st.session_state["shared_amt_hide_choice"] = _amt_radio_val

        for _i, (_label, _choice_key) in enumerate(_amt_quick_choices):
            with preset_cols[_i + 1]:
                _is_active = (_current_choice == _choice_key)
                _wrap_key = f"amt_preset_wrap_{_i}"
                if _is_active:
                    st.markdown(
                        f"<style>.st-key-{_wrap_key} button p {{ color:#ff3b3b !important; font-weight:800; }}</style>",
                        unsafe_allow_html=True,
                    )
                with st.container(key=_wrap_key):
                    if st.button(_label, key=f"amt_preset_{_i}"):
                        st.session_state["shared_amt_hide_choice"] = "안함" if _is_active else _choice_key
                        st.session_state["_amt_hide_radio_ver"] = st.session_state.get("_amt_hide_radio_ver", 0) + 1
                        st.rerun()

    _save_amt_hide_state(st.session_state.get("shared_amt_hide_choice", "안함"),
                          st.session_state.get("shared_hide_smallcap", False))

    # '오달저' ON이면 달이 바뀌었는지 확인해서 지난달 데이터를 자동으로 PC에 백업 (가벼운 체크,
    # 달이 안 바뀌었으면 아무 일도 안 함)
    if st.session_state.get("auto_month_export_enabled", True):
        _run_month_rollover_autoexport(
            EXPORT_SURGE_DIR, _surge_rank_saved_dates, _load_surge_rank_date, "surge"
        )
        _run_month_rollover_autoexport(
            EXPORT_THEME_DIR, _theme_snapshot_saved_dates, _load_theme_snapshot, "theme"
        )

    naver_panel_col, kiwoom_panel_col = st.columns(2, gap="small")

# 업종테마 종목 이름 색(시총 구간): 500억↓ 진한 파랑 / 500~1000억 파랑 / 9000억↑ 형광 핑크 / 5000~9000억 핑크 / 3000~5000억 빨강
_STKROW_COLORS = ["#1a3fa0", "#4a90e2", "#ff10f0", "#ff69b4", "#e05252"]


@st.fragment
def _render_kiwoom_theme_panel():
    with st.container(key="kiwoom_theme_panel"):
        kh_col1, kh_col2, kh_col_sun, kh_col_top30, kh_col3, kh_col4, kh_col5, kh_col6 = st.columns(
            [1.3, 0.7, 0.3, 0.3, 0.7, 0.8, 0.8, 0.7], gap="small"
        )
        with kh_col1:
            st.markdown("<div style='font-size:11px; font-weight:700;'>📊 업종테마</div>", unsafe_allow_html=True)

        _top30_mode_peek = st.session_state.get("top30_toggle_mode", 0)
        if _top30_mode_peek == 0:
            with kh_col2:
                st.checkbox("60초", value=False, key="kiwoom_gap_enabled", help="세력평단比 60초 자동계산")

        st.markdown(
            "<style>"
            ".st-key-theme_poll_row .stButton button {"
            "  padding: 0.02rem 0.05rem !important; min-height: 22px !important;"
            "  font-size: 10px !important; line-height: 1 !important;"
            "}"
            ".st-key-search_top30_toggle_wrap button {"
            "  padding: 0.02rem 0.05rem !important; min-height: 22px !important;"
            "  font-size: 10px !important; line-height: 1 !important;"
            "}"
            ".st-key-theme_local_row .stButton button {"
            "  padding: 0.02rem 0.05rem !important; min-height: 22px !important;"
            "  font-size: 10px !important; line-height: 1 !important;"
            "}"
            ".st-key-theme_sun_filter_wrap button {"
            "  padding: 0.02rem 0.05rem !important; min-height: 22px !important;"
            "  font-size: 10px !important; line-height: 1 !important;"
            "}"
            "</style>",
            unsafe_allow_html=True,
        )
        with kh_col_sun:
            _sun_on = st.session_state.get("theme_rank_sun_filter_on", True)
            with st.container(key="theme_sun_filter_wrap"):
                if st.button(
                    "순", key="theme_sun_filter_btn", use_container_width=True,
                    type="primary" if _sun_on else "secondary",
                    help="ON(기본, 새로고침하면 다시 ON으로 시작): 업종테마 순위에서 대금/천억↓/신호필터를 통과한 "
                         "종목이 0개인 테마는 목록에서 아예 숨기고, 1개 이상인 테마만 이름+세부종목을 "
                         "보여줍니다. OFF: 0개인 테마도 전부 다 표시합니다.",
                ):
                    st.session_state["theme_rank_sun_filter_on"] = not _sun_on
                    _save_theme_rank_sun_filter_pref(not _sun_on)
                    st.rerun(scope="fragment")  # 패널 안 목록만 다시 그린다(앱 전체 재실행 불필요)
        with kh_col_top30:
            _top30_mode = st.session_state.get("top30_toggle_mode", 0)
            with st.container(key="search_top30_toggle_wrap"):
                if st.button(
                    "▶", key="search_top30_toggle_btn", use_container_width=True,
                    type="primary" if _top30_mode != 0 else "secondary",
                    help="누를 때마다 [기본: 키움 급등순위 30%~0% / 업종테마] → [급등 30%~0% 분할 / 급등순위숨김목록] "
                         "→ 다시 기본으로 전환됩니다. "
                         "여기 나오는 급등순위는 모두 '업' 버튼으로 저장해둔 로컬 데이터일 뿐, 키움을 다시 조회하지 않습니다. "
                         "관심종목 체크, 전체선택/체관·체취, 흰네업·일주 신호찾기, 대금/천억↓ 필터가 그대로 연동됩니다.",
                ):
                    st.session_state["top30_toggle_mode"] = (_top30_mode + 1) % 2
                    # 전체 재실행 유지: 이 값을 급등순위 패널(네이버 이름의 패널)도 읽어서 좌/우 절반 나눔이 바뀌므로
                    # 두 패널이 함께 다시 그려져야 한다(패널만 다시 그리면 한쪽이 옛 화면으로 남는다).
                    st.rerun()

        # ▶ 토글 상태(둘 다)와 무관하게 항상 같은 자리에 보이도록 유지 (테업/테요 및 poll모드 버튼)
        _poll_mode = st.session_state.get("kiwoom_theme_poll_mode", "30s")
        _poll_btns = [("off", "OFF", kh_col3), ("30s", "펼30초", kh_col4),
                      ("23h", "펼23시", kh_col5), ("local", "로컬", kh_col6)]
        with st.container(key="theme_poll_row"):
            for _mval, _mlabel, _mcol in _poll_btns:
                with _mcol:
                    _is_on = (_poll_mode == _mval)
                    _help = (
                        "'테업' 버튼으로 저장해둔 로컬 스냅샷만 사용 - 키움 조회 없음"
                        if _mval == "local" else
                        "업종테마 목록/구성종목 자동조회 주기 (네이버·키움 부담 조절)"
                    )
                    if st.button(_mlabel, key=f"theme_poll_btn_{_mval}", use_container_width=True,
                                 type="primary" if _is_on else "secondary", help=_help):
                        st.session_state["kiwoom_theme_poll_mode"] = _mval
                        _save_kiwoom_theme_poll_mode(_mval)
                        st.rerun()

        te_col1, te_col2 = st.columns([0.5, 0.5], gap="small")
        with te_col1:
            with st.container(key="theme_local_row"):
                if st.button(
                    "테업", key="theme_snapshot_force_crawl_btn", use_container_width=True,
                    help="업종테마 전체(최대 30개)와 구성종목을 지금 이 순간에만 강제로 새로 받아와서 "
                         "오늘 날짜로 로컬에 저장합니다. 저장 후 poll 모드를 '로컬'로 바꾸면, "
                         "다시 '테업'을 누르기 전까지 흰네업/일주/필터/대금/천억↓ 무엇을 눌러도 "
                         "키움에 요청하지 않고 이 저장된 데이터만 사용합니다.",
                ):
                    try:
                        _snap = fetch_kiwoom_theme_snapshot_raw()
                        _today_str = date.today().isoformat()
                        _save_theme_snapshot(_today_str, _snap)
                        st.session_state[f"theme_snapshot_data_{_today_str}"] = _snap
                        st.session_state["theme_snapshot_data_live"] = _snap
                        st.session_state["theme_snapshot_active_date"] = None
                        if (datetime.now().hour, datetime.now().minute) >= (15, 31):
                            _auto_up_mark_done(_today_str, "theme", "manual")  # 장 마감 후 수동 테업이면 자동 테업은 건너뜀
                        st.success(f"업종테마 {len(_snap.get('groups', []))}개 스냅샷 갱신 완료")
                    except Exception as e:
                        st.warning(f"업종테마 스냅샷 조회 실패: {e}")
        with te_col2:
            with st.popover("테요", use_container_width=True,
                             help="과거에 '테업'을 눌러 저장해둔 날짜별 업종테마 스냅샷을 다시 봅니다 "
                                  "(키움 호출 없음, 로컬 캐시만 사용, poll 모드가 '로컬'일 때 적용됨)"):
                st.caption("날짜를 선택하면 그날 저장된 업종테마를 봅니다 (키움 재조회 없음)")

                _t_auto_exp_on = st.session_state.get("auto_month_export_enabled", True)
                _t_new_auto_exp_on = st.checkbox(
                    "오달저", value=_t_auto_exp_on, key="auto_month_export_toggle_theme",
                    help="ON(기본, 새로고침해도 유지): 매달 1일이 되는 순간 지난달 날짜별 데이터를 "
                         "자동으로 PC 폴더에 백업합니다. '저장' 버튼을 깜빡 안 눌러도 월말 데이터가 보존됩니다. "
                         "요/테요 둘 다에 적용되는 공통 설정입니다.",
                )
                if _t_new_auto_exp_on != _t_auto_exp_on:
                    st.session_state["auto_month_export_enabled"] = _t_new_auto_exp_on
                    _save_auto_month_export_pref(_t_new_auto_exp_on)

                _tsv_col, _tld_col = st.columns([1, 1], gap="small")
                with _tsv_col:
                    if st.button("저장", key="theme_export_save_btn", use_container_width=True,
                                 help=r"로컬에 저장된 모든 날짜의 업종테마 스냅샷을 PC 폴더로 백업합니다 "
                                      r"(C:\Users\LG\Downloads\내프로젝트폴더\테요). "
                                      r"파일명은 항상 오늘 날짜이고, 같은 달 안에서는 이전 파일을 지우고 새 날짜로 "
                                      r"교체되며, 달이 바뀌면 이전 파일은 남기고 새 파일을 만듭니다."):
                        try:
                            _tfname, _tn = _export_bundle_to_pc(
                                EXPORT_THEME_DIR, _theme_snapshot_saved_dates(), _load_theme_snapshot
                            )
                            st.success(f"{_tfname}.json 으로 {_tn}개 날짜 저장 완료")
                        except Exception as e:
                            st.warning(f"PC 저장 실패: {e}")
                with _tld_col:
                    if st.button("로드", key="theme_import_toggle_btn", use_container_width=True,
                                 help="PC 폴더에 저장해둔 백업 파일 목록을 펼쳐서 골라 불러옵니다 (로컬 캐시로 복원, 키움 호출 없음)"):
                        st.session_state["theme_show_pc_list"] = not st.session_state.get("theme_show_pc_list", False)
                if st.session_state.get("theme_show_pc_list", False):
                    st.caption("PC 백업 파일 목록 (클릭하면 로컬로 복원)")
                    _t_pc_files = _list_pc_export_files(EXPORT_THEME_DIR)
                    if not _t_pc_files:
                        st.caption("PC에 저장된 백업이 없습니다.")
                    for _tpf in _t_pc_files:
                        if st.button(_tpf, key=f"theme_import_btn_{_tpf}", use_container_width=True):
                            try:
                                _tn = _import_bundle_from_pc(
                                    EXPORT_THEME_DIR, _tpf, _save_theme_snapshot, "theme_snapshot_data_"
                                )
                                st.success(f"{_tn}개 날짜 복원 완료")
                                st.rerun()
                            except Exception as e:
                                st.warning(f"불러오기 실패: {e}")

                _live_active = st.session_state.get("theme_snapshot_active_date") is None
                if st.button("🔴 실시간(오늘/최신)", key="theme_snapshot_date_live", use_container_width=True,
                             type="primary" if _live_active else "secondary"):
                    st.session_state["theme_snapshot_active_date"] = None
                    st.rerun(scope="fragment")  # 테요(업종테마) 패널만 다시 그린다
                _render_saved_date_picker(
                    "theme_pick", _theme_snapshot_saved_dates(), "theme_snapshot_active_date",
                    _delete_theme_snapshot, "theme_snapshot_data_", file_fn=_theme_snapshot_file,
                )

        _top30_mode = st.session_state.get("top30_toggle_mode", 0)
        if _top30_mode != 0:
            # ▶ 한 번 누른 상태: 급등순위에서 '숨' 버튼으로 숨긴 종목을 복구하는 패널
            # (급등순위숨김목록)을 표시한다. (첫화면은 아래의 업종테마 테마순위)
            _render_surge_rank_hidden_panel()
            _render_theme_rank_hidden_section()
            return

        # 첫화면(▶ 안 누른 기본 상태): 업종테마 테마순위를 표시한다.
        # (급등순위숨김목록과 자리를 맞바꿈 - 다시 되돌리고 싶으면 위 조건을 `== 0`으로 바꾸면 된다.)
        if "selected_theme" not in st.session_state:
            st.session_state.selected_theme = None

        theme_groups = cached_theme_groups()
        _t_hidden = st.session_state.theme_rank_hidden
        _t_temp_hidden = st.session_state.setdefault("theme_rank_temp_hidden", set())
        if _t_hidden or _t_temp_hidden:
            theme_groups = [
                t for t in theme_groups
                if t.get("thema_grp_cd") not in _t_hidden and t.get("thema_grp_cd") not in _t_temp_hidden
            ]

        if "kiwoom_seen_themes" not in st.session_state:
            st.session_state.kiwoom_seen_themes = set()

        def _kiwoom_amount(s):
            def _pnum(v):
                try:
                    return abs(int(str(v).replace("+", "").replace("-", "")))
                except (TypeError, ValueError):
                    return 0
            return _pnum(s.get("cur_prc", "0")) * _pnum(s.get("acc_trde_qty", "0"))

        def _kiwoom_visible_stocks(stocks):
            threshold = AMT_HIDE_OPTIONS.get(st.session_state.get("shared_amt_hide_choice", "안함"))
            hide_smallcap = st.session_state.get("shared_hide_smallcap", False)
            out = []
            for s in stocks:
                s_marcap = marketcap_map.get(s.get("stk_cd", ""))
                if hide_smallcap and s_marcap and s_marcap < 1e11:
                    continue
                if threshold is not None and _kiwoom_amount(s) < threshold:
                    continue
                if not _passes_white_filter(s.get("stk_cd", "")):
                    continue
                out.append(s)
            return out

        if not theme_groups:
            st.caption("테마 데이터를 불러오지 못했습니다.")
        else:
            _seen_theme_stock_codes = set()  # 상위 순위 테마에 이미 나온 종목은 하위 순위에서 중복 표시 안 함
            # 테마 '숨'/'X' 버튼 모양·색, 종목 이름 시총 색상용 CSS를 테마마다/종목마다 <style> 요소로 따로 넣던 것을
            # 여기서 한 번에 넣는다(화면 요소 수가 크게 줄어 패널 다시 그리기가 가벼워짐. 화면 모양은 그대로).
            _css_parts = []
            for _g in theme_groups[:30]:
                _k = f"theme_x_wrap_{_g.get('thema_grp_cd', '')}"
                _css_parts.append(
                    f".st-key-{_k} button {{ padding:0 !important; margin:0 !important; "
                    f"width:20px !important; min-width:20px !important; max-width:20px !important; "
                    f"min-height:16px !important; height:16px !important; line-height:16px !important; "
                    f"font-size:9px !important; border:none !important; background:transparent !important; }}"
                    f".st-key-{_k}_hide button {{ color:#e05252 !important; }}"
                    f".st-key-{_k}_temp button {{ color:#9aa4b8 !important; }}"
                )
            # 종목 줄 컨테이너 키에 색 번호(stkrow_c1_~c5_)를 넣어 두고, 색상 규칙은 이 한 곳에서 번호별로 정의
            for _ci, _cc in enumerate(_STKROW_COLORS, start=1):
                _css_parts.append(f'[class*="st-key-stkrow_c{_ci}_"] button p {{ color:{_cc} !important; }}')
            st.markdown("<style>" + "".join(_css_parts) + "</style>", unsafe_allow_html=True)
            for i, theme in enumerate(theme_groups[:30], start=1):
                grp_cd = theme.get("thema_grp_cd", "")
                grp_nm = re.sub(r"\([^)]*\)", "", theme.get("thema_nm", "")).strip()
                flu_rt = theme.get("flu_rt", "0")
                try:
                    flu_rt_f = float(flu_rt)
                except (TypeError, ValueError):
                    flu_rt_f = 0.0
                rate_color = "#e05c5c" if flu_rt_f < 0 else "#3ecb7a" if flu_rt_f > 0 else "#9aa4b8"

                row_label = f"{i}위 {grp_nm}  {flu_rt_f:+.2f}%"

                # 필터 통과 종목 수를 먼저 계산해서, '순' ON이면 0종목인 테마는 아예 안 그린다.
                # (cached_theme_stocks가 자체적으로 30초/23시간 주기 캐싱을 하므로 매번 불러도
                # 키움 부담이 크게 늘지 않음). 이미 더 높은 순위(더 작은 위) 테마에서 나온 종목은
                # 이 테마(더 낮은 순위)에서는 중복이라 빼고 보여준다 - 항상 처음부터 펼쳐서
                # 보여주므로, 여러 테마에 같은 종목이 반복돼서 보이면 헷갈리기 때문.
                _theme_stocks_raw = cached_theme_stocks(grp_cd)
                _theme_stocks_for_count = [
                    s for s in _theme_stocks_raw if s.get("stk_cd") not in _seen_theme_stock_codes
                ]
                _seen_theme_stock_codes.update(
                    s.get("stk_cd") for s in _theme_stocks_raw if s.get("stk_cd")
                )
                st.session_state.kiwoom_seen_themes.add(grp_cd)
                # 필터(시총/거래대금/흰신호 등) 통과 종목 목록을 테마마다 '한 번만' 계산해서
                # 상단 숫자, 전체선택 체크박스 상태, 종목 줄 그리기에 모두 재사용한다(예전에는 같은 계산을 3번 반복).
                _vis_stocks = _kiwoom_visible_stocks(_theme_stocks_for_count)
                visible_count = len(_vis_stocks)

                if st.session_state.get("theme_rank_sun_filter_on", True) and visible_count == 0:
                    continue

                trow_col1, trow_col_chk, trow_col2, trow_col_x = st.columns(
                    [3.9, 0.3, 0.9, 0.2], gap="small"
                )

                with trow_col1:
                    st.markdown(
                        f"<div style='padding:6px 4px; font-size:14px; font-weight:600; color:#2ecc71;'>"
                        f"{row_label}</div>",
                        unsafe_allow_html=True,
                    )
                with trow_col_chk:
                    if grp_cd in st.session_state.kiwoom_seen_themes:
                        _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
                        _all_checked = bool(_vis_stocks) and all(
                            s.get("stk_cd") in st.session_state.checked_stocks for s in _vis_stocks
                        )
                        _selall = st.checkbox("전체선택", value=_all_checked, key=f"selall_{grp_cd}_v{_chk_ver}",
                                              label_visibility="collapsed")
                        if _selall != _all_checked:
                            if _selall:
                                for s in _vis_stocks:
                                    s_cd = s.get("stk_cd")
                                    st.session_state.checked_stocks[s_cd] = s.get("stk_nm", "")
                                    st.session_state[f"chk_{grp_cd}_{s_cd}_v{_chk_ver}"] = True
                            else:
                                for s in _vis_stocks:
                                    s_cd = s.get("stk_cd")
                                    st.session_state.checked_stocks.pop(s_cd, None)
                                    st.session_state[f"chk_{grp_cd}_{s_cd}_v{_chk_ver}"] = False
                            st.rerun()
                with trow_col2:
                    st.markdown(
                        f"<div style='text-align:right; padding-top:2px; font-size:29px; "
                        f"line-height:1; color:{_theme_count_color(visible_count)}; font-weight:800;'>"
                        f"{visible_count}</div>",
                        unsafe_allow_html=True,

                    )
                with trow_col_x:
                    _trx_key = f"theme_x_wrap_{grp_cd}"  # 버튼 모양/색 CSS는 테마 루프 앞에서 한 번에 넣음
                    with st.container(key=_trx_key):
                        with st.container(key=f"{_trx_key}_hide"):
                            if st.button("숨", key=f"theme_x_{grp_cd}",
                                         help="업종테마 순위에서 이 테마 계속 숨기기 (복원/복 누르기 전까지 "
                                              "새로고침·재부팅·'테업'과 무관하게 계속 숨김)"):
                                _t_hidden[grp_cd] = {"name": grp_nm, "pct": flu_rt_f}
                                _save_theme_hidden_state(_t_hidden)
                                st.rerun(scope="fragment")  # 패널 안 목록만 다시 그린다
                        with st.container(key=f"{_trx_key}_temp"):
                            if st.button("X", key=f"theme_tx_{grp_cd}",
                                         help="지금만 한 번 숨기기 (새로고침하면 다시 보임)"):
                                _t_temp_hidden.add(grp_cd)
                                st.rerun(scope="fragment")  # 패널 안 목록만 다시 그린다

                # 클릭 없이 처음부터 모든 테마의 구성종목을 펼쳐서 보여준다 (중복 종목은 위에서 이미 제외됨).
                stocks = _theme_stocks_for_count
                if not stocks:
                    st.caption("구성종목 없음")
                else:
                    with st.container(key=f"kiwoom_stock_detail_list_{grp_cd}"):
                        def _parse_price(v):
                            try:
                                return abs(int(str(v).replace("+", "").replace("-", "")))
                            except (TypeError, ValueError):
                                return 0

                        for s in _vis_stocks:  # 필터를 이미 통과한 종목만(위에서 한 번 계산한 목록)
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
                            # (시총 1000억 미만 / 거래대금 기준 / 흰신호 필터는 _kiwoom_visible_stocks에서 이미 적용됨)

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

                            # 컨테이너 키에 시총 색 번호(0=색 없음, 1~5)를 넣는다 → 색은 위에서 한 번에 넣은 CSS가 적용
                            _ci = (_STKROW_COLORS.index(btn_color) + 1) if btn_color in _STKROW_COLORS else 0
                            row_key = f"stkrow_c{_ci}_{grp_cd}_{s_cd}"
                            # 거래대금 색상: 10억↓회색/10~30억 계란노른자/30~50억 파랑/50~100억 보라/100억↑빨강
                            amt_color = _vol_color(s_amount / 1e8)
                            cap_color = btn_color if btn_color else "#eaeef5"
                            with st.container(key=row_key):
                                row_col1, row_col_chk, row_col2 = st.columns([1.7, 0.3, 3], gap="small")
                                with row_col1:
                                    if st.button(s_nm, key=f"stk_{grp_cd}_{s_cd}", use_container_width=True):
                                        st.session_state.goto_query = s_cd
                                        st.session_state["local_snapshot_view_date"] = (
                                            st.session_state.get("theme_snapshot_active_date")
                                            if st.session_state.get("kiwoom_theme_poll_mode") == "local"
                                            else None
                                        )
                                        st.rerun()  # 차트(패널 바깥)에 반영해야 하므로 전체 재실행 유지
                                with row_col_chk:
                                    _chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
                                    _chk = st.checkbox(
                                        "선택", value=(s_cd in st.session_state.checked_stocks),
                                        key=f"chk_{grp_cd}_{s_cd}_v{_chk_ver}", label_visibility="collapsed",
                                    )
                                    if _chk:
                                        st.session_state.checked_stocks[s_cd] = s_nm
                                    else:
                                        st.session_state.checked_stocks.pop(s_cd, None)
                                with row_col2:
                                    st.markdown(
                                        f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                                        f"{s_prc:,.0f} 전 <span style='color:{s_color};'>{s_rt_f:+.2f}%</span> "
                                        f"세 <span style='color:{gap_color};'>{gap_text}</span><br>"
                                        f"대<span style='color:{amt_color};'>{format_krw_large(s_amount).replace('원','')}</span> "
                                        f"시<span style='color:{cap_color};'>{(format_krw_large(s_marcap).replace('원','') if s_marcap else '-')}</span>"
                                        f"</div>",
                                        unsafe_allow_html=True,
                                    )



with kiwoom_panel_col:
    _render_kiwoom_theme_panel()

@st.fragment
def _render_naver_theme_panel():
    with st.container(key="naver_theme_panel"):
        # ----------------------------------------------------------------------
        # 8. 네이버 인기테마 (수동 새로고침 전용, 자동새로고침 걸지 않음 - IP차단 방지)
        # ----------------------------------------------------------------------
        st.markdown("<div style='font-size:11px; font-weight:700;'>🌐 네이버인기테마" + _auto_up_status_html() + "</div>",
                    unsafe_allow_html=True)

        if "selected_naver_theme" not in st.session_state:
            st.session_state.selected_naver_theme = None
        if "naver_theme_cache" not in st.session_state:
            st.session_state.naver_theme_cache = None
        if "naver_theme_stock_cache" not in st.session_state:
            st.session_state.naver_theme_stock_cache = {}

        nv_col2, nv_col3, nv_col4, nv_col5, nv_col6 = st.columns(
            [0.75, 0.45, 0.32, 0.24, 0.24], gap="small"
        )
        with nv_col2:
            st.checkbox("60초", value=False, key="naver_gap_enabled", help="세력평단比 60초 자동계산")
        with nv_col3:
            _surge_up_clicked = st.button(
                "업", key="surge_rank_force_crawl_btn",
                help="키움 급등순위(등락률상위)를 지금 이 순간에만 강제로 새로 받아옵니다. "
                     "받아온 데이터는 오늘 날짜로 로컬에 저장되고, 이 버튼을 다시 누르기 전까지는 "
                     "흰네업/일주/필터/새로고침 무엇을 눌러도 키움에 절대 다시 요청하지 않고 "
                     "이 저장된 데이터만 계속 사용합니다.",
            )
        with nv_col4:
            with st.popover("요", use_container_width=True,
                             help="과거에 '업'을 눌러 저장해둔 날짜별 급등순위를 다시 봅니다 (키움 호출 없음, 로컬 캐시만 사용)"):
                st.caption("날짜를 선택하면 그날 저장된 급등순위를 봅니다 (키움 재조회 없음)")

                _auto_exp_on = st.session_state.get("auto_month_export_enabled", True)
                _new_auto_exp_on = st.checkbox(
                    "오달저", value=_auto_exp_on, key="auto_month_export_toggle_surge",
                    help="ON(기본, 새로고침해도 유지): 매달 1일이 되는 순간 지난달 날짜별 데이터를 "
                         "자동으로 PC 폴더에 백업합니다. '저장' 버튼을 깜빡 안 눌러도 월말 데이터가 보존됩니다. "
                         "요/테요 둘 다에 적용되는 공통 설정입니다.",
                )
                if _new_auto_exp_on != _auto_exp_on:
                    st.session_state["auto_month_export_enabled"] = _new_auto_exp_on
                    _save_auto_month_export_pref(_new_auto_exp_on)

                _sv_col, _ld_col = st.columns([1, 1], gap="small")
                with _sv_col:
                    if st.button("저장", key="surge_export_save_btn", use_container_width=True,
                                 help=r"로컬에 저장된 모든 날짜의 급등순위를 PC 폴더로 백업합니다 "
                                      r"(C:\Users\LG\Downloads\내프로젝트폴더\요). "
                                      r"파일명은 항상 오늘 날짜이고, 같은 달 안에서는 이전 파일을 지우고 새 날짜로 "
                                      r"교체되며, 달이 바뀌면 이전 파일은 남기고 새 파일을 만듭니다."):
                        try:
                            _fname, _n = _export_bundle_to_pc(
                                EXPORT_SURGE_DIR, _surge_rank_saved_dates(), _load_surge_rank_date
                            )
                            st.success(f"{_fname}.json 으로 {_n}개 날짜 저장 완료")
                        except Exception as e:
                            st.warning(f"PC 저장 실패: {e}")
                with _ld_col:
                    if st.button("로드", key="surge_import_toggle_btn", use_container_width=True,
                                 help="PC 폴더에 저장해둔 백업 파일 목록을 펼쳐서 골라 불러옵니다 (로컬 캐시로 복원, 키움 호출 없음)"):
                        st.session_state["surge_show_pc_list"] = not st.session_state.get("surge_show_pc_list", False)
                if st.session_state.get("surge_show_pc_list", False):
                    st.caption("PC 백업 파일 목록 (클릭하면 로컬로 복원)")
                    _pc_files = _list_pc_export_files(EXPORT_SURGE_DIR)
                    if not _pc_files:
                        st.caption("PC에 저장된 백업이 없습니다.")
                    for _pf in _pc_files:
                        if st.button(_pf, key=f"surge_import_btn_{_pf}", use_container_width=True):
                            try:
                                _n = _import_bundle_from_pc(
                                    EXPORT_SURGE_DIR, _pf, _save_surge_rank_date, "surge_rank_data_"
                                )
                                st.success(f"{_n}개 날짜 복원 완료")
                                st.rerun()
                            except Exception as e:
                                st.warning(f"불러오기 실패: {e}")

                _live_active = st.session_state.get("surge_rank_active_date") is None
                if st.button("🔴 실시간(오늘/최신)", key="surge_rank_date_live", use_container_width=True,
                             type="primary" if _live_active else "secondary"):
                    st.session_state["surge_rank_active_date"] = None
                    st.session_state["theme_snapshot_active_date"] = None  # 테요도 함께 실시간으로
                    st.rerun()
                _render_saved_date_picker(
                    "surge_pick", _surge_rank_saved_dates(), "surge_rank_active_date",
                    _delete_surge_rank_date, "surge_rank_data_", file_fn=_surge_rank_file,
                )

        with nv_col5:
            if st.button("숨", key="surge_bulk_hide_btn", use_container_width=True,
                         help="v(선택) 체크된 종목들을 한 번에 급등순위에서 계속 숨깁니다 "
                              "(복원/복 누르기 전까지 새로고침·재부팅·'업'과 무관하게 계속 숨김)"):
                _n = _bulk_hide_checked_surge_stocks(temp=False)
                if _n:
                    st.rerun()
        with nv_col6:
            if st.button("X", key="surge_bulk_temp_hide_btn", use_container_width=True,
                         help="v(선택) 체크된 종목들을 한 번에 지금만 숨깁니다 (새로고침하면 다시 보임)"):
                _n = _bulk_hide_checked_surge_stocks(temp=True)
                if _n:
                    st.rerun()

        # '업' 클릭 처리는 좁은 컬럼 밖(전체 폭)에서 해야 에러 메시지가 세로로 쪼개지지 않는다.
        if _surge_up_clicked:
            try:
                _surge_data = fetch_kiwoom_surge_rank_raw()
                _today_str = date.today().isoformat()
                _save_surge_rank_date(_today_str, _surge_data)
                st.session_state[f"surge_rank_data_{_today_str}"] = _surge_data
                st.session_state["surge_rank_data_live"] = _surge_data
                st.session_state["surge_rank_active_date"] = None
                if (datetime.now().hour, datetime.now().minute) >= (15, 31):
                    _auto_up_mark_done(_today_str, "surge", "manual")  # 장 마감 후 수동으로 업을 눌렀으면 자동 업은 건너뜀
                st.success(f"급등순위 {len(_surge_data)}종목 갱신 완료")
            except Exception as e:
                st.warning(f"급등순위 조회 실패: {e}")

        _top30_mode = st.session_state.get("top30_toggle_mode", 0)
        if _top30_mode == 1:
            _render_kiwoom_surge_split_panel(_top30_mode, side="left")
            return

        # 네이버 차단 이슈로 기본 화면은 당분간 키움 급등순위(30%~0%)로 대체.
        # (예전 네이버인기테마 렌더링 코드는 아래 그대로 남겨두었고, 필요해지면 이 return만 지우면 복귀 가능)
        _render_kiwoom_surge_rank_panel()
        return

        naver_groups = st.session_state.naver_theme_cache

        def _naver_amount(s):
            return (s.get("price") or 0) * (s.get("volume") or 0)

        def _naver_visible_count(stocks):
            threshold = AMT_HIDE_OPTIONS.get(st.session_state.get("shared_amt_hide_choice", "안함"))
            hide_smallcap = st.session_state.get("shared_hide_smallcap", False)
            cnt = 0
            for s in stocks:
                s_marcap = marketcap_map.get(s.get("code"))
                if hide_smallcap and s_marcap and s_marcap < 1e11:
                    continue
                if threshold is not None and _naver_amount(s) < threshold:
                    continue
                if not _passes_white_filter(s.get("code", "")):
                    continue
                cnt += 1
            return cnt

        def _naver_visible_stocks(stocks):
            threshold = AMT_HIDE_OPTIONS.get(st.session_state.get("shared_amt_hide_choice", "안함"))
            hide_smallcap = st.session_state.get("shared_hide_smallcap", False)
            out = []
            for s in stocks:
                s_marcap = marketcap_map.get(s.get("code"))
                if hide_smallcap and s_marcap and s_marcap < 1e11:
                    continue
                if threshold is not None and _naver_amount(s) < threshold:
                    continue
                if not _passes_white_filter(s.get("code", "")):
                    continue
                out.append(s)
            return out

        if naver_groups is None:
            st.caption("위 버튼을 눌러 조회해주세요.")
        elif not naver_groups:
            st.caption("데이터를 불러오지 못했습니다. 페이지 구조가 변경되었을 수 있어요.")
        else:
            for i, theme in enumerate(naver_groups[:30], start=1):
                no = theme["no"]
                nm = re.sub(r"\([^)]*\)", "", theme["name"]).strip()
                pct = theme.get("change_pct")
                pct_f = pct if pct is not None else 0.0
                row_label = f"{i}위 {nm}  {pct_f:+.2f}%" if pct is not None else f"{i}위 {nm}"
                naver_theme_row_key = f"naverthemerow_{no}"
                st.markdown(
                    f"<style>.st-key-{naver_theme_row_key} button p {{ color:#2ecc71 !important; }}</style>",
                    unsafe_allow_html=True,
                )
                cached_stocks_for_row = st.session_state.naver_theme_stock_cache.get(no)

                ntrow_col1, ntrow_col_chk, ntrow_col2 = st.columns([4.1, 0.3, 0.9], gap="small")
                with ntrow_col1:
                    with st.container(key=naver_theme_row_key):
                        if st.button(row_label, key=f"navertheme_{no}", use_container_width=True):
                            st.session_state.selected_naver_theme = None if st.session_state.selected_naver_theme == no else no
                            st.rerun(scope="fragment")  # 패널 안(펼치기/접기)만 다시 그린다
                with ntrow_col_chk:
                    if cached_stocks_for_row is not None:
                        _nv_chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
                        _nv_vis_stocks = _naver_visible_stocks(cached_stocks_for_row)
                        _nv_all_checked = bool(_nv_vis_stocks) and all(
                            s.get("code") in st.session_state.checked_stocks for s in _nv_vis_stocks
                        )
                        _nv_selall = st.checkbox("전체선택", value=_nv_all_checked,
                                                 key=f"selall_naver_{no}_v{_nv_chk_ver}",
                                                 label_visibility="collapsed")
                        if _nv_selall != _nv_all_checked:
                            if _nv_selall:
                                for s in _nv_vis_stocks:
                                    s_code = s.get("code")
                                    st.session_state.checked_stocks[s_code] = s.get("name", "")
                                    st.session_state[f"navchk_{no}_{s_code}_v{_nv_chk_ver}"] = True
                            else:
                                for s in _nv_vis_stocks:
                                    s_code = s.get("code")
                                    st.session_state.checked_stocks.pop(s_code, None)
                                    st.session_state[f"navchk_{no}_{s_code}_v{_nv_chk_ver}"] = False
                            st.rerun()
                with ntrow_col2:
                    if cached_stocks_for_row is not None:
                        _nv_count = _naver_visible_count(cached_stocks_for_row)
                        st.markdown(
                            f"<div style='text-align:right; padding-top:2px; font-size:29px; "
                            f"line-height:1; color:{_theme_count_color(_nv_count)}; font-weight:800;'>"
                            f"{_nv_count}</div>",
                            unsafe_allow_html=True,
                        )

                if st.session_state.selected_naver_theme == no:
                    if no not in st.session_state.naver_theme_stock_cache:
                        try:
                            st.session_state.naver_theme_stock_cache[no] = fetch_naver_theme_stocks(no)
                        except Exception as e:
                            st.warning(f"구성종목 조회 실패: {e}")
                            st.session_state.naver_theme_stock_cache[no] = []
                        st.rerun(scope="fragment")  # 새로 받아온 종목수를 위쪽 목록 줄에도 바로 반영(같은 패널 안이라 패널만 다시 그림)

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
                                if st.session_state.get("shared_hide_smallcap", False) and s_marcap and s_marcap < 1e11:
                                    continue

                                # 거래대금 기준 숨기기(선택한 임계값 미만이면 숨김)
                                _amt_threshold = AMT_HIDE_OPTIONS.get(
                                    st.session_state.get("shared_amt_hide_choice", "안함"))
                                if _amt_threshold is not None and (s_amount or 0) < _amt_threshold:
                                    continue

                                # 흰신호(당일) 필터 - '흰' 토글이 켜져 있을 때만 종목별 일봉 데이터를 확인
                                if not _passes_white_filter(s["code"]):
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
                                    row_col1, row_col_chk, row_col2 = st.columns([1.7, 0.3, 3], gap="small")
                                    with row_col1:
                                        if st.button(s["name"], key=f"naverstk_{no}_{s['code']}", use_container_width=True):
                                            st.session_state.goto_query = s["code"]
                                            st.rerun()  # 차트(패널 바깥)에 반영해야 하므로 전체 재실행 유지
                                    with row_col_chk:
                                        _nv_chk_ver = st.session_state.get("stock_chk_reset_ver", 0)
                                        _nchk = st.checkbox(
                                            "선택", value=(s["code"] in st.session_state.checked_stocks),
                                            key=f"navchk_{no}_{s['code']}_v{_nv_chk_ver}", label_visibility="collapsed",
                                        )
                                        if _nchk:
                                            st.session_state.checked_stocks[s["code"]] = s["name"]
                                        else:
                                            st.session_state.checked_stocks.pop(s["code"], None)
                                    with row_col2:
                                        pct_html = f"<span style='color:{s_color};'>{s_pct:+.2f}%</span>" if s_pct is not None else "-"
                                        amt_text = format_krw_large(s_amount).replace("원", "") if s_amount else "-"
                                        cap_text = format_krw_large(s_marcap).replace("원", "") if s_marcap else "-"
                                        # 거래대금 색상: 10억↓회색/10~30억 계란노른자/30~50억 파랑/50~100억 보라/100억↑빨강
                                        amt_color = _vol_color((s_amount or 0) / 1e8)
                                        cap_color = btn_color if btn_color else "#eaeef5"
                                        st.markdown(
                                            f"<div style='padding:2px 0; text-align:right; font-size:11.5px; line-height:1.3;'>"
                                            f"{(s['price'] or 0):,.0f} 전 {pct_html} "
                                            f"세 <span style='color:{gap_color};'>{gap_text}</span><br>"
                                            f"대<span style='color:{amt_color};'>{amt_text}</span> "
                                            f"시<span style='color:{cap_color};'>{cap_text}</span>"
                                            f"</div>",
                                            unsafe_allow_html=True,
                                        )

with naver_panel_col:
    _render_naver_theme_panel()

_save_checked_stocks_if_changed()
# 흰네업 / 요 / 테요 팝오버만 가로폭을 좁힌다 (각 팝오버 안에만 있는 버튼으로 구분 - 다른 팝오버는 그대로)
_pw = POPOVER_NARROW_WIDTH_PX
_pop_sels = ",".join(
    f'[data-testid="stPopoverBody"]:has(.st-key-{k})'
    for k in ("multi_sig_apply_btn", "surge_export_save_btn", "theme_export_save_btn")
)
st.markdown(
    f"<style>{_pop_sels} {{ width:min({_pw}px, 92vw) !important; min-width:0 !important; "
    f"max-width:92vw !important; box-sizing:border-box !important; }}</style>",
    unsafe_allow_html=True,
)
_auto_up_scheduler()  # 매일 15:31 자동 '업'+'테업' (1분마다 시간만 확인)
