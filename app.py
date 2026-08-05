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
# 공통 함수
# ---------------------------------------------------------
def get_stock_name(code):
    try:
        name = stock.get_market_ticker_name(code)
        return name if name else code
    except Exception:
        return code


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
# TAB 1: 세력 평단가(VWAP) 차트 (모든 목표/손절 점선 라인 반영)
# ---------------------------------------------------------
with main_tab1:
    col1, col2 = st.columns([1, 2.5])

    with col1:
        code = st.text_input(
            "종목코드 (6자리)",
            "005930",
            key="vwap_code_input",
            label_visibility="collapsed",
            placeholder="종목코드 입력 (예: 005930)",
        )
        stock_name = get_stock_name(code)
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
        current_name = get_stock_name(code)

        s_date = start_date.strftime("%Y%m%d")
        e_date = end_date.strftime("%Y%m%d")

        with st.spinner("계산 중..."):
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
            st.error("거래 데이터가 없습니다.")
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

            # 💡 주기별 맞춤형 목표가 / 손절가 산출
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

            # 상단 메트릭 표시
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
                    f"■ [{current_name}({code}) - {selected_timeframe}]\n"
                    f"• 현재가: {last_close:,}원 | 세력평단: {last_vwap:,}원 ({disparity:+.2f}%)\n"
                    f"• 매수범위: {last_vwap:,}원 ~ {buy_limit:,}원\n"
                    f"• 🎯 1차목표(+5%): {target_1st:,}원\n"
                    f"• 🚀 2차목표(+10%): {target_2nd:,}원\n"
                    f"• 🛑 1차손절(-2%): {stop_loss:,}원\n"
                    f"• 🚨 절대사수손절(-4%): {absolute_stop_loss:,}원"
                )
                st.code(copy_summary, language="text")

            # 💡 Plotly 차트 구성 (모든 가이드 라인 점선 표시)
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

            # 1차 목표가 점선
            fig.add_hline(
                y=target_1st,
                line_dash="dot",
                line_color="#1f77b4",
                annotation_text=f"🎯 1차 목표가(+5%): {target_1st:,}원",
                annotation_position="top right",
            )
            # 2차 목표가 점선
            fig.add_hline(
                y=target_2nd,
                line_dash="dot",
                line_color="#9467bd",
                annotation_text=f"🚀 2차 목표가(+10%): {target_2nd:,}원",
                annotation_position="top right",
            )
            # 1차 손절가 점선
            fig.add_hline(
                y=stop_loss,
                line_dash="dash",
                line_color="#ff7f0e",
                annotation_text=f"🛑 1차 손절가(-2%): {stop_loss:,}원",
                annotation_position="bottom right",
            )
            # 🚨 절대사수 손절가 점선
            fig.add_hline(
                y=absolute_stop_loss,
                line_dash="dash",
                line_color="red",
                annotation_text=f"🚨 절대사수 손절가(-4%): {absolute_stop_loss:,}원",
                annotation_position="bottom right",
            )

            fig.update_layout(
                title=f"{current_name} ({code}) - {selected_timeframe} 세력평단 및 매매 가이드 라인",
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

    THEME_DATA = {
        "반도체 대표주(생산)": {
            "change": "+6.94%",
            "stocks": [
                (
                    "삼성전자",
                    "005930",
                    72500,
                    4.50,
                    71000,
                    66200,
                    64000,
                    71200,
                    656700,
                ),
                (
                    "SK하이닉스",
                    "000660",
                    188500,
                    8.90,
                    165000,
                    158000,
                    149000,
                    181000,
                    120500,
                ),
            ],
        }
    }
    st.info(
        "💡 상단 '📈 세력 평단가(VWAP) 차트' 탭에서 원하는 종목코드와 주기를 선택하여 상세 가이드 라인을 확인하세요."
    )
