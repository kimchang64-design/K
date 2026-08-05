import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(page_title="주식 분석 포털 - 평단선 & 실시간 선물·프로그램 수급", layout="wide")

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

# 상단 탭 구성
main_tab1, main_tab2 = st.tabs(["📈 평단선 차트", "⭐ 업종·테마 분석"])


# ---------------------------------------------------------
# 공통 함수
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_ticker_map():
    try:
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(today_str, market="ALL")
        name_map = {}
        for t in tickers:
            name = stock.get_market_ticker_name(t)
            if name and isinstance(name, str):
                name_map[name.strip()] = t
        return name_map
    except Exception:
        return {}


def resolve_code_or_name(user_input):
    user_input = user_input.strip()
    if user_input.isdigit() and len(user_input) == 6:
        try:
            name = stock.get_market_ticker_name(user_input)
            name_str = str(name).strip() if name else user_input
            return user_input, name_str
        except Exception:
            return user_input, user_input

    name_map = get_stock_ticker_map()
    if user_input in name_map:
        return name_map[user_input], user_input

    for name, code in name_map.items():
        if user_input in name:
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
        },
        "000660": {
            "mcap": 1370000,
            "op_profit": 120500,
            "trade_type": "🏆 중장기",
            "foreign_net": "+89,100주",
            "inst_net": "-12,400주",
            "prog_net": "+310억 (강한유입)",
            "credit_ratio": "0.45%",
        },
        "000990": {
            "mcap": 21500,
            "op_profit": 2100,
            "trade_type": "🌊 스윙",
            "foreign_net": "+12,500주",
            "inst_net": "+3,200주",
            "prog_net": "+45억",
            "credit_ratio": "1.21%",
        },
        "010170": {
            "mcap": 2100,
            "op_profit": -45,
            "trade_type": "⚡ 단타",
            "foreign_net": "+340,000주",
            "inst_net": "+1,200주",
            "prog_net": "+180억 (폭발적)",
            "credit_ratio": "3.85%",
        },
        "017900": {
            "mcap": 1400,
            "op_profit": 18,
            "trade_type": "🌊 스윙",
            "foreign_net": "-4,100주",
            "inst_net": "+5,600주",
            "prog_net": "+12억",
            "credit_ratio": "1.10%",
        },
        "327260": {
            "mcap": 3920,
            "op_profit": 32,
            "trade_type": "⚡ 단타",
            "foreign_net": "+45,000주",
            "inst_net": "+18,900주",
            "prog_net": "+62억",
            "credit_ratio": "2.15%",
        },
        "001440": {
            "mcap": 18500,
            "op_profit": 780,
            "trade_type": "🌊 스윙",
            "foreign_net": "+95,200주",
            "inst_net": "+31,000주",
            "prog_net": "+94억",
            "credit_ratio": "1.05%",
        },
        "024840": {
            "mcap": 850,
            "op_profit": 12,
            "trade_type": "⚡ 단타",
            "foreign_net": "+18,000주",
            "inst_net": "-800주",
            "prog_net": "+8억",
            "credit_ratio": "2.90%",
        },
        "028670": {
            "mcap": 5100,
            "op_profit": 130,
            "trade_type": "🏆 중장기",
            "foreign_net": "+22,100주",
            "inst_net": "+14,500주",
            "prog_net": "+25억",
            "credit_ratio": "0.78%",
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
        },
    )


# ---------------------------------------------------------
# TAB 1: 평단선 차트
# ---------------------------------------------------------
with main_tab1:
    col1, col2 = st.columns([1, 2.5])

    with col1:
        raw_input = st.text_input(
            "종목 입력",
            "삼성전자",
            key="vwap_code_input",
            label_visibility="collapsed",
            placeholder="종목명 또는 코드 입력",
        )
        code, stock_name = resolve_code_or_name(raw_input)
        st.caption(f"📌 **종목:** {stock_name} ({code})")

    with col2:
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

    if selected_timeframe in ["일봉", "주봉", "월봉"]:
        d_col1, d_col2 = st.columns([1, 1])
        with d_col1:
            start_date = st.date_input(
                "시작일", pd.to_datetime("2024-01-01"), key="vwap_start"
            )
        with d_col2:
            end_date = st.date_input(
                "종료일", pd.to_datetime("today"), key="vwap_end"
            )
    else:
        today = datetime.datetime.now()
        start_date = st.date_input("조회일 선택 (분봉)", today, key="vwap_min_date")
        end_date = start_date

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
        df = stock.get_market_ohlcv_by_date(s_date, e_date, code, "m")
        if not df.empty:
            minutes = selected_timeframe.replace("분봉", "") + "T"
            if minutes != "1T":
                df = df.resample(minutes).agg(
                    {
                        "시가": "first",
                        "고가": "max",
                        "저가": "min",
                        "종가": "last",
                        "거래량": "sum",
                    }
                )
            df = df.dropna()

    if df is None or df.empty:
        st.warning("선택한 조건에 해당하는 거래 데이터가 없습니다.")
    else:
        df["TPV"] = df["종가"] * df["거래량"]
        cum_volume = df["거래량"].cumsum()

        df["평단가"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
        df["평단가"] = df["평단가"].ffill()

        last_close = int(df["종가"].iloc[-1])
        last_vwap = int(df["평단가"].iloc[-1])
        disparity = ((last_close - last_vwap) / last_vwap) * 100

        f_info = get_financial_info(code)
        mcap_val = f_info["mcap"]
        op_profit = f_info["op_profit"]
        trade_type = f_info["trade_type"]
        foreign_net = f_info["foreign_net"]
        inst_net = f_info["inst_net"]
        prog_net = f_info["prog_net"]
        credit_ratio = f_info["credit_ratio"]

        target_1st = int(last_vwap * 1.05)
        target_2nd = int(last_vwap * 1.10)
        buy_limit = int(last_vwap * 1.015)
        stop_loss = int(last_vwap * 0.98)
        absolute_stop_loss = int(last_vwap * 0.96)

        if 0 <= disparity <= 5.0:
            status_signal = "🔥 최적타점"
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
        f3.metric("🎯 AI 추천 성향", trade_type)
        f4.metric("⚡ 진단 상태", status_signal)

        s_c1, s_c2, s_c3, s_c4 = st.columns(4)
        s_c1.metric("🌐 외국인 순매수", foreign_net)
        s_c2.metric("🏛️ 기관 순매수", inst_net)
        s_c3.metric("💻 실시간 프로그램", prog_net)
        s_c4.metric("💳 신용잔고율", credit_ratio)

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("현재가", f"{last_close:,}원")
        m2.metric(f"{selected_timeframe} 평단선", f"{last_vwap:,}원", f"{disparity:+.1f}%")
        m3.metric("🎯1차목표(+5%)", f"{target_1st:,}원")
        m4.metric("🚀2차목표(+10%)", f"{target_2nd:,}원")
        m5.metric("🛑1차손절(-2%)", f"{stop_loss:,}원")
        m6.metric("🚨절대손절(-4%)", f"{absolute_stop_loss:,}원")

        with st.expander("📝 텍스트 요약 및 복사 기능 열기"):
            copy_summary = (
                f"■ [{stock_name}({code}) - {selected_timeframe}]\n"
                f"• 시가총액: {mcap_val:,}억원 | 영업이익: {op_profit:,}억원\n"
                f"• 외국인: {foreign_net} | 기관: {inst_net} | 프로그램: {prog_net}\n"
                f"• 현재가: {last_close:,}원 | 평단선: {last_vwap:,}원 ({disparity:+.2f}%)\n"
                f"• 매수범위: {last_vwap:,}원 ~ {buy_limit:,}원\n"
                f"• 🎯 1차목표(+5%): {target_1st:,}원\n"
                f"• 🚀 2차목표(+10%): {target_2nd:,}원\n"
                f"• 🛑 1차손절(-2%): {stop_loss:,}원\n"
                f"• 🚨 절대사수손절(-4%): {absolute_stop_loss:,}원"
            )
            st.code(copy_summary, language="text")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["종가"],
                mode="lines",
                name="종가",
                line=dict(color="#1f77b4", width=1.5),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["평단가"],
                mode="lines",
                name=f"누적 평단선 ({selected_timeframe})",
                line=dict(color="#ff7f0e", width=2.5),
            )
        )

        fig.add_hline(
            y=target_1st,
            line_dash="dot",
            line_color="#1f77b4",
            annotation_text=f"🎯 1차 목표가(+5%): {target_1st:,}원",
            annotation_position="top right",
        )
        fig.add_hline(
            y=target_2nd,
            line_dash="dot",
            line_color="#9467bd",
            annotation_text=f"🚀 2차 목표가(+10%): {target_2nd:,}원",
            annotation_position="top right",
        )
        fig.add_hline(
            y=stop_loss,
            line_dash="dash",
            line_color="#ff7f0e",
            annotation_text=f"🛑 1차 손절가(-2%): {stop_loss:,}원",
            annotation_position="bottom right",
        )
        fig.add_hline(
            y=absolute_stop_loss,
            line_dash="dash",
            line_color="red",
            annotation_text=f"🚨 절대사수 손절가(-4%): {absolute_stop_loss:,}원",
            annotation_position="bottom right",
        )

        fig.update_layout(
            title=f"{stock_name} ({code}) - {selected_timeframe} 평단선 및 매매 가이드 라인",
            margin=dict(l=20, r=20, t=35, b=20),
            hovermode="x unified",
            template="plotly_white",
            height=360,
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------
# TAB 2: 업종·테마 분석 대시보드
# ---------------------------------------------------------
with main_tab2:
    st.title("⭐ 업종·테마 분석 대시보드")
    st.caption("테마별 실시간 시세, 영업이익, 외인·기관 및 실시간 프로그램 수급 종합 분석")

    THEME_DATA = {
        "광케이블/광섬유": {
            "change": "+9.99%",
            "up_down": "상승 13 / 하락 0",
            "stocks": [
                (
                    "대한광통신",
                    "010170",
                    1850,
                    14.50,
                    12500000,
                    231,
                    2100,
                    1810,
                    1580,
                    1450,
                    1780,
                    -45,
                    "⚡ 단타",
                    "+180억",
                ),
                (
                    "광전자",
                    "017900",
                    2450,
                    9.80,
                    4200000,
                    102,
                    1400,
                    2100,
                    2050,
                    1950,
                    2350,
                    18,
                    "🌊 스윙",
                    "+12억",
                ),
                (
                    "RF머트리얼즈",
                    "327260",
                    33750,
                    29.80,
                    3480000,
                    1174,
                    3920,
                    16572,
                    15200,
                    13800,
                    28500,
                    32,
                    "⚡ 단타",
                    "+62억",
                ),
            ],
        },
        "전선": {
            "change": "+8.91%",
            "up_down": "상승 8 / 하락 0",
            "stocks": [
                (
                    "대한전선",
                    "001440",
                    14200,
                    8.50,
                    18200000,
                    2584,
                    18500,
                    13950,
                    12100,
                    11500,
                    13900,
                    780,
                    "🌊 스윙",
                    "+94억",
                ),
                (
                    "KBI메탈",
                    "024840",
                    2150,
                    12.10,
                    8900000,
                    191,
                    850,
                    1850,
                    1780,
                    1650,
                    2020,
                    12,
                    "⚡ 단타",
                    "+8억",
                ),
                (
                    "LS마린솔루션",
                    "028670",
                    19800,
                    6.20,
                    3100000,
                    613,
                    5100,
                    17200,
                    16500,
                    15200,
                    19100,
                    130,
                    "🏆 중장기",
                    "+25억",
                ),
            ],
        },
        "반도체 대표주(생산)": {
            "change": "+6.94%",
            "up_down": "상승 3 / 하락 0",
            "stocks": [
                (
                    "삼성전자",
                    "005930",
                    72500,
                    4.50,
                    28500000,
                    20600,
                    4320000,
                    71000,
                    66200,
                    64000,
                    71200,
                    656700,
                    "🏆 중장기",
                    "+450억",
                ),
                (
                    "SK하이닉스",
                    "000660",
                    188500,
                    8.90,
                    8900000,
                    16700,
                    1370000,
                    165000,
                    158000,
                    149000,
                    181000,
                    120500,
                    "🏆 중장기",
                    "+310억",
                ),
                (
                    "DB하이텍",
                    "000990",
                    48500,
                    7.20,
                    1250000,
                    606,
                    21500,
                    47200,
                    41500,
                    39800,
                    46800,
                    2100,
                    "🌊 스윙",
                    "+45억",
                ),
            ],
        },
    }

    st.subheader("🔥 인기 업종·테마 Top")
    top_keys = list(THEME_DATA.keys())[:3]
    top_cols = st.columns(len(top_keys))

    for i, t_name in enumerate(top_keys):
        t_info = THEME_DATA[t_name]
        top_stocks_str = ", ".join([s[0] for s in t_info["stocks"][:3]])
        with top_cols[i]:
            st.markdown(
                f"""
            <div style="background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="background-color: #ffebee; color: #d32f2f; font-weight: bold; padding: 2px 8px; border-radius: 4px; font-size: 12px;">{i+1}위</span>
                    <span style="color: #d32f2f; font-weight: bold; font-size: 15px;">{t_info['change']}</span>
                </div>
                <div style="font-weight: bold; font-size: 15px; margin-top: 8px; color: #111;">{t_name}</div>
                <div style="font-size: 11px; color: #777; margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{top_stocks_str}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 3.5])

    with col_left:
        search_mode = st.radio(
            "검색 모드", ["테마 검색", "종목 검색"], horizontal=True
        )
        search_input = st.text_input("🔍 검색어 입력...", "")

        selected_theme = None
        matched_themes_from_stock = []

        if search_mode == "테마 검색":
            filtered_themes = [
                t
                for t in THEME_DATA.keys()
                if search_input.strip().lower() in t.lower()
            ]
            if filtered_themes:
                selected_theme = st.radio(
                    "테마 선택",
                    filtered_themes,
                    index=0,
                    label_visibility="collapsed",
                )
            else:
                st.warning("검색된 테마가 없습니다.")
        else:
            query = search_input.strip().lower()
            if query:
                for theme_name, theme_info in THEME_DATA.items():
                    for s in theme_info["stocks"]:
                        if (
                            query in s[0].lower()
                            or query in str(s[1]).zfill(6)
                        ):
                            matched_themes_from_stock.append(
                                (theme_name, s[0])
                            )

    with col_right:
        if search_mode == "테마 검색" and selected_theme:
            themes_to_render = [selected_theme]
        elif search_mode == "종목 검색" and matched_themes_from_stock:
            themes_to_render = list(
                dict.fromkeys([t[0] for t in matched_themes_from_stock])
            )
        else:
            themes_to_render = list(THEME_DATA.keys())[:1]

        for render_theme in themes_to_render:
            st.subheader(f"📌 {render_theme}")
            stocks_list = THEME_DATA[render_theme]["stocks"]

            sort_option = st.radio(
                "정렬 필터",
                ["전체", "거래대금 상위", "상승 TOP", "프로그램 순매수순"],
                horizontal=True,
                key=f"sort_{render_theme}",
            )

            if sort_option == "거래대금 상위":
                stocks_list = sorted(
                    stocks_list, key=lambda x: x[5], reverse=True
                )
            elif sort_option == "상승 TOP":
                stocks_list = sorted(
                    stocks_list, key=lambda x: x[3], reverse=True
                )
            elif sort_option == "프로그램 순매수순":
                stocks_list = sorted(
                    stocks_list,
                    key=lambda x: int(
                        x[13].replace("+", "").replace("억", "").replace(",", "")
                    ),
                    reverse=True,
                )

            table_rows_html = ""
            for idx, item in enumerate(stocks_list, start=1):
                s_name, s_code = item[0], str(item[1]).zfill(6)
                curr_price, change_pct = item[2], item[3]
                trade_amt, op_profit = item[5], item[11]
                trade_type, prog_amt = item[12], item[13]

                d_vwap, w_vwap, m_vwap, m3_vwap = (
                    item[7],
                    item[8],
                    item[9],
                    item[10],
                )
                d_disp = ((curr_price - d_vwap) / d_vwap) * 100
                w_disp = ((curr_price - w_vwap) / w_vwap) * 100
                m_disp = ((curr_price - m_vwap) / m_vwap) * 100
                m3_disp = ((curr_price - m3_vwap) / m3_vwap) * 100

                profit_badge = (
                    f'<span style="color:#0ca678; font-weight:bold;">🟢 흑자 ({op_profit:,}억)</span>'
                    if op_profit > 0
                    else f'<span style="color:#f03e3e; font-weight:bold;">🔴 적자 ({op_profit:,}억)</span>'
                )

                table_rows_html += f"""
                <tr style="border-bottom: 1px solid #f0f0f0; height: 65px; font-size: 12px;">
                    <td style="text-align: center;">{idx}</td>
                    <td style="font-weight: bold;">{s_name} <br><span style="color:#1c7ed6; font-size:10px;">{trade_type}</span></td>
                    <td style="text-align: center;">{s_code}</td>
                    <td style="text-align: center;">{profit_badge}</td>
                    <td style="text-align: center; color: #d32f2f; font-weight: bold;">💻 {prog_amt}</td>
                    <td style="text-align: right; font-weight: bold;">{curr_price:,}원</td>
                    <td style="text-align: right; color: #d32f2f; font-weight: bold;">+{change_pct:.2f}%</td>
                    <td style="text-align: right;">{trade_amt:,}백만</td>
                    <td style="text-align: center; background-color: #fff9db;"><b>{d_vwap:,}원</b><br><span style="color:{'#d32f2f' if d_disp>0 else '#1976d2'};">({d_disp:+.1f}%)</span></td>
                    <td style="text-align: center; background-color: #fff3bf;"><b>{w_vwap:,}원</b><br><span style="color:{'#d32f2f' if w_disp>0 else '#1976d2'};">({w_disp:+.1f}%)</span></td>
                    <td style="text-align: center; background-color: #ffec99;"><b>{m_vwap:,}원</b><br><span style="color:{'#d32f2f' if m_disp>0 else '#1976d2'};">({m_disp:+.1f}%)</span></td>
                    <td style="text-align: center; background-color: #e7f5ff;"><b>{m3_vwap:,}원</b><br><span style="color:{'#d32f2f' if m3_disp>0 else '#1976d2'};">({m3_disp:+.1f}%)</span></td>
                </tr>
                """

            full_table_html = f"""
            <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 20px;">
                <table style="width: 100%; border-collapse: collapse; background-color: #ffffff; min-width: 1050px;">
                    <thead>
                        <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 35px;">
                            <th style="text-align: center;">순위</th>
                            <th style="text-align: left;">종목명</th>
                            <th style="text-align: center;">코드</th>
                            <th style="text-align: center;">실적</th>
                            <th style="text-align: center;">실시간 프로그램</th>
                            <th style="text-align: right;">현재가</th>
                            <th style="text-align: right;">등락률</th>
                            <th style="text-align: right;">거래대금</th>
                            <th style="text-align: center; background-color: #fff9db;">일봉 평단</th>
                            <th style="text-align: center; background-color: #fff3bf;">주봉 평단</th>
                            <th style="text-align: center; background-color: #ffec99;">월봉 평단</th>
                            <th style="text-align: center; background-color: #e7f5ff;">3분봉 평단</th>
                        </tr>
                    </thead>
                    <tbody>{table_rows_html}</tbody>
                </table>
            </div>
            """
            components.html(
                full_table_html, height=len(stocks_list) * 70 + 50, scrolling=True
            )
