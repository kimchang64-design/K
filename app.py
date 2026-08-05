import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(page_title="주식 분석 포털 - VWAP & 업종테마", layout="wide")

# 여백 최소화 패치 CSS
st.markdown(
    """
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 0rem; padding-left: 2rem; padding-right: 2rem; }
        div[data-testid="stMetricValue"] { font-size: 1.1rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)

# 상단 탭 구성
main_tab1, main_tab2 = st.tabs(["📈 세력 평단가(VWAP) 차트", "⭐ 업종·테마 분석"])


# ---------------------------------------------------------
# 공통 함수 (한글 종목명 자동 변환 지원)
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_ticker_map():
    """KRX 전체 상장 종목의 (종목명: 종목코드) 딕셔너리 생성"""
    try:
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(today_str, market="ALL")
        name_map = {}
        for t in tickers:
            name = stock.get_market_ticker_name(t)
            if name:
                name_map[name.strip()] = t
        return name_map
    except Exception:
        return {}


def resolve_code_or_name(user_input):
    """사용자가 입력한 값이 한글 종목명이면 코드로 변환, 아니면 그대로 반환"""
    user_input = user_input.strip()
    # 이미 6자리 코드인 경우
    if user_input.isdigit() and len(user_input) == 6:
        return user_input, stock.get_market_ticker_name(user_input)

    # 한글 종목명인 경우 맵에서 검색
    name_map = get_stock_ticker_map()
    if user_input in name_map:
        code = name_map[user_input]
        return code, user_input

    # 부분 일치 검색 지원 (예: "삼성" 입력 시 "삼성전자" 매칭)
    for name, code in name_map.items():
        if user_input in name:
            return code, name

    # 기본값으로 입력된 값 반환
    return user_input, stock.get_market_ticker_name(user_input)


def get_financial_info(code):
    sample_financials = {
        "005930": {
            "mcap": 4320000,
            "op_profit": 656700,
            "trade_type": "🏆 중장기",
        },
        "000660": {
            "mcap": 1370000,
            "op_profit": 120500,
            "trade_type": "🏆 중장기",
        },
        "000990": {"mcap": 21500, "op_profit": 2100, "trade_type": "🌊 스윙"},
        "010170": {"mcap": 2100, "op_profit": -45, "trade_type": "⚡ 단타"},
        "017900": {"mcap": 1400, "op_profit": 18, "trade_type": "🌊 스윙"},
        "327260": {"mcap": 3920, "op_profit": 32, "trade_type": "⚡ 단타"},
        "001440": {"mcap": 18500, "op_profit": 780, "trade_type": "🌊 스윙"},
        "024840": {"mcap": 850, "op_profit": 12, "trade_type": "⚡ 단타"},
        "028670": {"mcap": 5100, "op_profit": 130, "trade_type": "🏆 중장기"},
    }
    return sample_financials.get(
        code, {"mcap": 5000, "op_profit": 120, "trade_type": "🌊 스윙"}
    )


# ---------------------------------------------------------
# TAB 1: 세력 평단가(VWAP) 차트 (한글 검색 지원)
# ---------------------------------------------------------
with main_tab1:
    col1, col2 = st.columns([1, 2.5])

    with col1:
        raw_input = st.text_input(
            "종목 입력",
            "삼성전자",
            key="vwap_code_input",
            label_visibility="collapsed",
            placeholder="종목명 또는 코드 입력 (예: 삼성전자)",
        )
        # 한글 입력인지 6자리 코드인지 자동 판별
        code, stock_name = resolve_code_or_name(raw_input)
        if not stock_name:
            stock_name = code
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
        d_col1, d_col2, d_col3 = st.columns([1, 1, 1])
        with d_col1:
            start_date = st.date_input(
                "시작일", pd.to_datetime("2024-01-01"), key="vwap_start"
            )
        with d_col2:
            end_date = st.date_input(
                "종료일", pd.to_datetime("today"), key="vwap_end"
            )
        with d_col3:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            run_btn = st.button(
                "📊 차트 분석 실행", type="primary", key="run_vwap", use_container_width=True
            )
    else:
        d_col1, d_col2 = st.columns([2, 1])
        with d_col1:
            today = datetime.datetime.now()
            start_date = st.date_input("조회일 선택 (분봉)", today, key="vwap_min_date")
            end_date = start_date
        with d_col2:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            run_btn = st.button(
                "📊 차트 분석 실행", type="primary", key="run_vwap", use_container_width=True
            )

    if run_btn:
        s_date = start_date.strftime("%Y%m%d")
        e_date = end_date.strftime("%Y%m%d")

        with st.spinner("데이터 계산 중..."):
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
            st.error(
                "거래 데이터가 없습니다. 종목명/코드를 다시 확인하시거나 휴일 여부를 확인해주세요."
            )
        else:
            df["TPV"] = df["종가"] * df["거래량"]
            cum_volume = df["거래량"].cumsum()

            df["세력평단"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
            df["세력평단"] = df["세력평단"].ffill()

            last_close = int(df["종가"].iloc[-1])
            last_vwap = int(df["세력평단"].iloc[-1])
            disparity = ((last_close - last_vwap) / last_vwap) * 100

            f_info = get_financial_info(code)
            mcap_val = f_info["mcap"]
            op_profit = f_info["op_profit"]
            trade_type = f_info["trade_type"]

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

            # 상단 지표 출력
            m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
            m1.metric("현재가", f"{last_close:,}원")
            m2.metric(f"{selected_timeframe} 세력평단", f"{last_vwap:,}원", f"{disparity:+.1f}%")
            m3.metric("🎯1차목표(+5%)", f"{target_1st:,}원")
            m4.metric("🚀2차목표(+10%)", f"{target_2nd:,}원")
            m5.metric("🛑1차손절(-2%)", f"{stop_loss:,}원")
            m6.metric("🚨절대손절(-4%)", f"{absolute_stop_loss:,}원")
            m7.metric("진단/성향", f"{status_signal} | {trade_type}")

            with st.expander("📝 텍스트 요약 및 복사 기능 열기"):
                copy_summary = (
                    f"■ [{stock_name}({code}) - {selected_timeframe}]\n"
                    f"• 현재가: {last_close:,}원 | 세력평단: {last_vwap:,}원 ({disparity:+.2f}%)\n"
                    f"• 매수범위: {last_vwap:,}원 ~ {buy_limit:,}원\n"
                    f"• 🎯 1차목표(+5%): {target_1st:,}원\n"
                    f"• 🚀 2차목표(+10%): {target_2nd:,}원\n"
                    f"• 🛑 1차손절(-2%): {stop_loss:,}원\n"
                    f"• 🚨 절대사수손절(-4%): {absolute_stop_loss:,}원"
                )
                st.code(copy_summary, language="text")

            # 차트 출력
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
                    y=df["세력평단"],
                    mode="lines",
                    name=f"누적 세력평단 ({selected_timeframe})",
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
                title=f"{stock_name} ({code}) - {selected_timeframe} 세력평단 및 매매 가이드 라인",
                margin=dict(l=20, r=20, t=35, b=20),
                hovermode="x unified",
                template="plotly_white",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------
# TAB 2: 업종 테마 분석
# ---------------------------------------------------------
with main_tab2:
    st.title("⭐ 업종·테마 분석 대시보드")
    st.caption("인기 테마별 종목 전략 가이드")
    st.info(
        "💡 상단 '📈 세력 평단가(VWAP) 차트' 탭에서 한글 종목명('삼성전자', 'SK하이닉스' 등)이나 코드를 입력해 확인하세요."
    )
