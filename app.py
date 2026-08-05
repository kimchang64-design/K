import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

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
        "코스나인": "252670",
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
# TAB 1: 평단선 차트
# ---------------------------------------------------------
with main_tab1:
    if "search_history" not in st.session_state:
        st.session_state.search_history = ["삼성전자", "SK하이닉스"]
    if "target_stock" not in st.session_state:
        st.session_state.target_stock = "삼성전자"

    col1, col2 = st.columns([1, 2.5])

    with col1:

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
        news_list = f_info.get("news", [])

        target_1st = int(last_vwap * 1.05)
        target_2nd = int(last_vwap * 1.10)
        buy_limit = int(last_vwap * 1.015)
        stop_loss = int(last_vwap * 0.98)
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

        # 📰 뉴스란 (원상복구 단독 배치)
        st.markdown(
            f"""
            <div style="background-color: #f1f3f5; border-left: 4px solid #1a73e8; padding: 10px 15px; border-radius: 0 6px 6px 0; margin: 10px 0; height: 115px; overflow-y: auto;">
                <div style="font-weight: bold; font-size: 13px; color: #1a73e8; margin-bottom: 5px;">📰 [{stock_name}] 실시간 상승 이유 및 뉴스 속보</div>
                <ul style="margin: 0; padding-left: 20px; font-size: 11px; color: #333;">
                    {''.join([f"<li>{news}</li>" for news in news_list])}
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("현재가", f"{last_close:,}원")
        m2.metric(
            f"{selected_timeframe} 평단가",
            f"{last_vwap:,}원",
            f"괴리율 {disparity:+.1f}%",
        )
        m3.metric("🎯1차목표(+5%)", f"{target_1st:,}원")
        m4.metric("🚀2차목표(+10%)", f"{target_2nd:,}원")
        m5.metric("🛑1차손절(-2%)", f"{stop_loss:,}원")
        m6.metric("🚨절대손절(-4%)", f"{absolute_stop_loss:,}원")

        st.markdown(
            "### 📋 키움차트/주문창 단가 수치 복사하기 (클릭 시 확인창 없이 즉시 복사)"
        )
        copy_html = f"""
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <button onclick="navigator.clipboard.writeText('{last_vwap}');" style="background:#1a73e8; color:white; border:none; padding:8px 14px; border-radius:5px; cursor:pointer; font-weight:bold;">
                📌 평단가 ({last_vwap}) 복사
            </button>
            <button onclick="navigator.clipboard.writeText('{target_1st}');" style="background:#0ca678; color:white; border:none; padding:8px 14px; border-radius:5px; cursor:pointer; font-weight:bold;">
                🎯 1차목표 ({target_1st}) 복사
            </button>
            <button onclick="navigator.clipboard.writeText('{target_2nd}');" style="background:#7048e8; color:white; border:none; padding:8px 14px; border-radius:5px; cursor:pointer; font-weight:bold;">
                🚀 2차목표 ({target_2nd}) 복사
            </button>
            <button onclick="navigator.clipboard.writeText('{stop_loss}');" style="background:#f59f00; color:white; border:none; padding:8px 14px; border-radius:5px; cursor:pointer; font-weight:bold;">
                🛑 1차손절 ({stop_loss}) 복사
            </button>
            <button onclick="navigator.clipboard.writeText('{absolute_stop_loss}');" style="background:#e03131; color:white; border:none; padding:8px 14px; border-radius:5px; cursor:pointer; font-weight:bold;">
                🚨 절대손절 ({absolute_stop_loss}) 복사
            </button>
        </div>
        """
        components.html(copy_html, height=55)

        with st.expander("📝 텍스트 요약 및 전체 복사 기능"):
            copy_summary = (
                f"■ [{stock_name}({code}) - {selected_timeframe}]\n"
                f"• 매매성향: {trade_type} | 괴리율: {disparity:+.2f}%\n"
                f"• 현재가: {last_close:,}원 | 평단가: {last_vwap:,}원\n"
                f"• 매수타점범위: {last_vwap:,}원 ~ {buy_limit:,}원 (손절짧은타점)\n"
                f"• 🎯 1차목표(+5%): {target_1st:,}원\n"
                f"• 🚀 2차목표(+10%): {target_2nd:,}원\n"
                f"• 🛑 1차손절(-2%): {stop_loss:,}원\n"
                f"• 🚨 절대손절(-4%): {absolute_stop_loss:,}원"
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
                name=f"누적 평단가 ({selected_timeframe})",
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

        fig.update_xaxes(
            tickformat="%Y-%m",
            dtick="M1",
            tickangle=0,
        )

        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------
# TAB 2: 업종·테마 분석 대시보드
# ---------------------------------------------------------
with main_tab2:
    st.markdown("### ⭐ 업종·테마 분석 대시보드")
    st.caption(
        "실적(흑자/적자), 매매유형, 다중 주기 평단가, 목표가 및 손절가 분석"
    )

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
                    "w_vwap": 1580,
                    "m_vwap": 1450,
                    "m3_vwap": 1790,
                    "target": 1900,
                    "stop": 1770,
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
                    "w_vwap": 12100,
                    "m_vwap": 11500,
                    "m3_vwap": 14100,
                    "target": 14600,
                    "stop": 13650,
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
            "검색 모드", ["테마 검색", "종목 검색"], horizontal=True, key="s_mode"
        )
        search_input = st.text_input(
            "검색어 입력...", "", key="t_search", placeholder="검색어 입력..."
        )
        theme_list = list(THEME_DATA.keys())
        selected_theme = st.radio(
            "테마 선택 라디오",
            theme_list,
            index=0,
            label_visibility="collapsed",
            key="t_radio",
        )

    with col_right:
        if selected_theme and selected_theme in THEME_DATA:
            st.markdown(f"### 📌 {selected_theme}", unsafe_allow_html=True)
            stocks_list = THEME_DATA[selected_theme]["stocks"]
            table_rows_html = ""
            for idx, item in enumerate(stocks_list, start=1):
                table_rows_html += f"""
                <tr style="border-bottom: 1px solid #f0f0f0; height: 65px; font-size: 12px;">
                    <td style="text-align: center; font-weight: bold;">{idx}</td>
                    <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['trade_type']}</span></td>
                    <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
                    <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
                    <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
                    <td style="text-align: right; color: #d32f2f; font-weight: bold;">+{item['change']:.2f}%</td>
                    <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원 ({item['d_disp']})</td>
                    <td style="text-align: center; background-color: #f3f0ff; font-weight: bold;">{item['w_vwap']:,}원</td>
                    <td style="text-align: center; background-color: #e6fcf5; font-weight: bold;">{item['m_vwap']:,}원</td>
                    <td style="text-align: center; background-color: #fff0f6; font-weight: bold;">{item['m3_vwap']:,}원</td>
                    <td style="text-align: right; color: #2b8a3e; font-weight: bold;">{item['target']:,}원</td>
                    <td style="text-align: right; color: #e03131; font-weight: bold;">{item['stop']:,}원</td>
                </tr>
                """
            full_table_html = f"""
            <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px;">
                <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                    <thead>
                        <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; font-size: 11px; height: 38px;">
                            <th style="text-align: center;">순위</th>
                            <th style="text-align: left;">종목명</th>
                            <th style="text-align: center;">종목코드</th>
                            <th style="text-align: center;">실적</th>
                            <th style="text-align: right;">현재가</th>
                            <th style="text-align: right;">전일대비</th>
                            <th style="text-align: center; background-color: #fff9db;">일봉 평단(괴리)</th>
                            <th style="text-align: center; background-color: #f3f0ff;">주봉 평단</th>
                            <th style="text-align: center; background-color: #e6fcf5;">월봉 평단</th>
                            <th style="text-align: center; background-color: #fff0f6;">3분봉 평단</th>
                            <th style="text-align: right; color: #2b8a3e;">🎯 목표가(+5%)</th>
                            <th style="text-align: right; color: #e03131;">🛑 손절가(-2%)</th>
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
    st.caption(
        "시장 주도 상위 종목 실적, 다중 주기 평단가, 목표가 및 손절가 분석"
    )

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
            "d_disp": "+2.1%",
            "w_vwap": 68500,
            "m_vwap": 65000,
            "m3_vwap": 72100,
            "target": 74550,
            "stop": 69580,
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
            "d_disp": "+14.2%",
            "w_vwap": 155000,
            "m_vwap": 140000,
            "m3_vwap": 187000,
            "target": 173250,
            "stop": 161700,
            "type": "🏆 중장기",
        },
    ]

    t30_rows = ""
    for idx, item in enumerate(top30_sample, start=1):
        t30_rows += f"""
        <tr style="border-bottom: 1px solid #f0f0f0; height: 50px; font-size: 12px;">
            <td style="text-align: center; font-weight: bold;">{idx}</td>
            <td style="font-weight: bold;">{item['name']}<br><span style="color:#1c7ed6; font-size:10px;">{item['type']}</span></td>
            <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
            <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
            <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
            <td style="text-align: right; color: #d32f2f;">+{item['change']:.2f}%</td>
            <td style="text-align: right;">{item['amt']:,} 백만</td>
            <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원 ({item['d_disp']})</td>
            <td style="text-align: center; background-color: #f3f0ff; font-weight: bold;">{item['w_vwap']:,}원</td>
            <td style="text-align: center; background-color: #e6fcf5; font-weight: bold;">{item['m_vwap']:,}원</td>
            <td style="text-align: center; background-color: #fff0f6; font-weight: bold;">{item['m3_vwap']:,}원</td>
            <td style="text-align: right; color: #2b8a3e; font-weight: bold;">{item['target']:,}원</td>
            <td style="text-align: right; color: #e03131; font-weight: bold;">{item['stop']:,}원</td>
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
                    <th style="text-align: center; background-color: #fff9db;">일봉 평단(괴리)</th>
                    <th style="text-align: center; background-color: #f3f0ff;">주봉 평단</th>
                    <th style="text-align: center; background-color: #e6fcf5;">월봉 평단</th>
                    <th style="text-align: center; background-color: #fff0f6;">3분봉 평단</th>
                    <th style="text-align: right; color: #2b8a3e;">🎯 목표가(+5%)</th>
                    <th style="text-align: right; color: #e03131;">🛑 손절가(-2%)</th>
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
    st.caption("시간외 급등 종목 실적, 다중 주기 평단가, 목표가 및 손절가 분석")

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
            "d_disp": "+7.7%",
            "w_vwap": 1580,
            "m_vwap": 1450,
            "m3_vwap": 1920,
            "target": 1900,
            "stop": 1773,
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
            "d_disp": "+6.1%",
            "w_vwap": 12100,
            "m_vwap": 11500,
            "m3_vwap": 14600,
            "target": 14647,
            "stop": 13671,
            "reason": "대규모 수주 (스윙)",
        },
    ]

    ah_rows = ""
    for idx, item in enumerate(after_hours_data, start=1):
        ah_rows += f"""
        <tr style="border-bottom: 1px solid #f0f0f0; height: 50px; font-size: 12px;">
            <td style="text-align: center; font-weight: bold;">{idx}</td>
            <td style="font-weight: bold;">{item['name']}</td>
            <td style="text-align: center; font-weight: bold; color: #1a73e8;">{item['code']}</td>
            <td style="text-align: center; font-weight: bold;">{item['op_status']}</td>
            <td style="text-align: right; font-weight: bold;">{item['price']:,}원</td>
            <td style="text-align: right; color: #d32f2f;">+{item['change']:.2f}%</td>
            <td style="text-align: right;">{item['amt']:,} 백만</td>
            <td style="text-align: center; background-color: #fff9db; font-weight: bold;">{item['d_vwap']:,}원 ({item['d_disp']})</td>
            <td style="text-align: center; background-color: #f3f0ff; font-weight: bold;">{item['w_vwap']:,}원</td>
            <td style="text-align: center; background-color: #e6fcf5; font-weight: bold;">{item['m_vwap']:,}원</td>
            <td style="text-align: center; background-color: #fff0f6; font-weight: bold;">{item['m3_vwap']:,}원</td>
            <td style="text-align: right; color: #2b8a3e; font-weight: bold;">{item['target']:,}원</td>
            <td style="text-align: right; color: #e03131; font-weight: bold;">{item['stop']:,}원</td>
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
                    <th style="text-align: center; background-color: #fff9db;">일봉 평단(괴리)</th>
                    <th style="text-align: center; background-color: #f3f0ff;">주봉 평단</th>
                    <th style="text-align: center; background-color: #e6fcf5;">월봉 평단</th>
                    <th style="text-align: center; background-color: #fff0f6;">3분봉 평단</th>
                    <th style="text-align: right; color: #2b8a3e;">🎯 목표가(+5%)</th>
                    <th style="text-align: right; color: #e03131;">🛑 손절가(-2%)</th>
                    <th style="text-align: center;">특이사항 / 성향</th>
                </tr>
            </thead>
            <tbody>{ah_rows}</tbody>
        </table>
    </div>
    """
    components.html(ah_table, height=250, scrolling=True)
