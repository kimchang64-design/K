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
# TAB 1: 세력 평단가(VWAP) 차트 (한 화면 최적화 버젼)
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

    # 시작일/종료일 및 분석 실행 버튼을 한 줄로 압축
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

            target_1st = int(last_vwap * 1.05)
            target_2nd = int(last_vwap * 1.10)
            buy_limit = int(last_vwap * 1.015)
            stop_loss = int(last_vwap * 0.98)
            absolute_stop_loss = int(last_vwap * 0.96)

            profit_str = (
                f"🟢 흑자({op_profit:,}억)" if op_profit > 0 else f"🔴 적자({op_profit:,}억)"
            )

            if 0 <= disparity <= 5.0:
                status_signal = "🔥 최적타점"
            elif disparity > 20.0:
                status_signal = "⚠️ 진입주의"
            elif last_close < absolute_stop_loss:
                status_signal = "🚨 절대손절이탈"
            else:
                status_signal = "📊 추세유지"

            # 컴팩트 1줄 주요 수치 배치
            m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
            m1.metric("현재가", f"{last_close:,}원")
            m2.metric("세력평단", f"{last_vwap:,}원", f"{disparity:+.1f}%")
            m3.metric("🎯1차목표(+5%)", f"{target_1st:,}원")
            m4.metric("🚀2차목표(+10%)", f"{target_2nd:,}원")
            m5.metric("🛑1차손절(-2%)", f"{stop_loss:,}원")
            m6.metric("🚨절대손절(-4%)", f"{absolute_stop_loss:,}원")
            m7.metric("진단/성향", f"{status_signal} | {trade_type}")

            # 접이식 복사 박스 (공간 절약)
            with st.expander("📝 텍스트 요약 및 복사 기능 열기"):
                copy_summary = (
                    f"■ [{current_name}({code}) - {selected_timeframe}]\n"
                    f"• 현재가: {last_close:,}원 | 세력평단: {last_vwap:,}원 ({disparity:+.2f}%)\n"
                    f"• 매수범위: {last_vwap:,}원 ~ {buy_limit:,}원\n"
                    f"• 1차목표: {target_1st:,}원 | 2차목표: {target_2nd:,}원\n"
                    f"• 1차손절: {stop_loss:,}원 | 🚨절대손절: {absolute_stop_loss:,}원"
                )
                st.code(copy_summary, language="text")

            # 한 화면에 차트가 다 나오도록 높이를 380px로 조율
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
                    name="누적 세력평단",
                    line=dict(color="#ff7f0e", width=2.5),
                )
            )
            fig.add_hline(
                y=absolute_stop_loss,
                line_dash="dash",
                line_color="red",
                annotation_text=f"🚨 절대사수 손절가: {absolute_stop_loss:,}원",
                annotation_position="bottom right",
            )

            fig.update_layout(
                title=f"{current_name} ({code}) - {selected_timeframe} 차트",
                margin=dict(l=20, r=20, t=35, b=20),
                hovermode="x unified",
                template="plotly_white",
                height=380,
            )
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------
# TAB 2: 업종 테마 분석
# ---------------------------------------------------------
with main_tab2:
    st.title("⭐ 업종·테마 분석 대시보드")
    st.caption("25개 인기 테마 시세 및 종목별 전략 가이드")

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
                ),
            ],
        },
    }

    selected_theme = st.selectbox("테마 선택", list(THEME_DATA.keys()))
    if selected_theme:
        stocks_list = THEME_DATA[selected_theme]["stocks"]
        table_rows_html = ""
        for idx, item in enumerate(stocks_list, start=1):
            s_name, s_code, curr_price, change_pct = (
                item[0],
                str(item[1]).zfill(6),
                item[2],
                item[3],
            )
            d_vwap, op_profit = item[7], item[11]
            d_target = int(d_vwap * 1.05)
            d_stop = int(d_vwap * 0.98)
            d_abs_stop = int(d_vwap * 0.96)

            table_rows_html += f"""
            <tr style="border-bottom: 1px solid #eee; height: 50px; font-size: 12px;">
                <td style="text-align: center;">{idx}</td>
                <td style="font-weight: bold;">{s_name} ({s_code})</td>
                <td style="text-align: right;">{curr_price:,}원</td>
                <td style="text-align: right; color: #d32f2f;">+{change_pct:.1f}%</td>
                <td style="text-align: center;"><b>평단: {d_vwap:,}원</b> | 🎯목표: {d_target:,}원 | 🛑1차손절: {d_stop:,}원 | <span style="color:#d6336c; font-weight:bold;">🚨절대손절: {d_abs_stop:,}원</span></td>
            </tr>
            """

        full_table_html = f"""
        <table style="width: 100%; border-collapse: collapse; font-family: sans-serif;">
            <thead>
                <tr style="background-color: #f8f9fa; font-size: 11px; height: 35px;">
                    <th>순위</th><th>종목명</th><th>현재가</th><th>전일대비</th><th>일봉 핵심 전략 가이드라인</th>
                </tr>
            </thead>
            <tbody>{table_rows_html}</tbody>
        </table>
        """
        components.html(full_table_html, height=220, scrolling=True)
