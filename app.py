import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(page_title="주식 분석 포털 - VWAP & 업종테마", layout="wide")

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
    """
    종목별 재무/시총/매매성향 룩업 예시 데이터
    """
    sample_financials = {
        "005930": {"mcap": 4320000, "op_profit": 656700, "trade_type": "🏆 중장기"},
        "000660": {"mcap": 1370000, "op_profit": 120500, "trade_type": "🏆 중장기"},
        "000990": {"mcap": 21500, "op_profit": 2100, "trade_type": "🌊 스윙"},
        "010170": {"mcap": 2100, "op_profit": -45, "trade_type": "⚡ 단타"},
        "017900": {"mcap": 1400, "op_profit": 18, "trade_type": "🌊 스윙"},
        "327260": {"mcap": 3920, "op_profit": 32, "trade_type": "⚡ 단타"},
        "001440": {"mcap": 18500, "op_profit": 780, "trade_type": "🌊 스윙"},
        "024840": {"mcap": 850, "op_profit": 12, "trade_type": "⚡ 단타"},
        "028670": {"mcap": 5100, "op_profit": 130, "trade_type": "🏆 중장기"},
    }
    if code in sample_financials:
        return sample_financials[code]
    else:
        return {"mcap": 5000, "op_profit": 120, "trade_type": "🌊 스윙"}


# ---------------------------------------------------------
# TAB 1: 세력 평단가(VWAP) 차트 (절대 손절가 추가)
# ---------------------------------------------------------
with main_tab1:
    st.title("📈 세력 평단가(VWAP) 분석 대시보드")

    if "recent_codes" not in st.session_state:
        st.session_state.recent_codes = []

    col1, col2 = st.columns([1, 2.5])

    with col1:
        code = st.text_input("종목코드 (6자리)", "005930", key="vwap_code_input")
        stock_name = get_stock_name(code)
        if stock_name != code:
            st.caption(f"📌 **종목명:** {stock_name} ({code})")

    with col2:
        timeframe_options = [
            "일봉", "주봉", "월봉",
            "1분봉", "3분봉", "5분봉", "10분봉", "15분봉",
            "30분봉", "45분봉", "60분봉", "90분봉", "120분봉",
            "240분봉", "300분봉", "999분봉"
        ]
        selected_timeframe = st.radio(
            "차트 주기 선택 (원클릭 다이렉트 선택)",
            timeframe_options,
            index=0,
            horizontal=True,
            key="direct_timeframe_select"
        )

    if st.session_state.recent_codes:
        st.write("🔍 **최근 검색 종목:**")
        cols = st.columns(min(len(st.session_state.recent_codes), 5))
        for idx, recent_item in enumerate(st.session_state.recent_codes[:5]):
            r_code = recent_item["code"]
            r_name = recent_item["name"]
            if cols[idx].button(
                f"📌 {r_name} ({r_code})", key=f"recent_{r_code}"
            ):
                code = r_code

    if selected_timeframe in ["일봉", "주봉", "월봉"]:
        c1, c2 = st.columns(2)
        with c1:
            start_date = st.date_input(
                "시작일", pd.to_datetime("2024-01-01"), key="vwap_start"
            )
        with c2:
            end_date = st.date_input(
                "종료일", pd.to_datetime("today"), key="vwap_end"
            )
    else:
        today = datetime.datetime.now()
        start_date = st.date_input("조회일 선택 (분봉)", today, key="vwap_min_date")
        end_date = start_date

    if st.button("차트 및 수치 분석 실행", type="primary", key="run_vwap"):
        current_name = get_stock_name(code)

        new_entry = {"code": code, "name": current_name}
        st.session_state.recent_codes = [
            item
            for item in st.session_state.recent_codes
            if item["code"] != code
        ]
        st.session_state.recent_codes.insert(0, new_entry)

        s_date = start_date.strftime("%Y%m%d")
        e_date = end_date.strftime("%Y%m%d")

        with st.spinner("데이터를 계산 중입니다..."):
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
                "선택한 날짜에 거래 데이터가 없습니다. 주말/휴일이거나 장 개장 전인지 확인해주세요."
            )
        else:
            df["TPV"] = df["종가"] * df["거래량"]
            cum_volume = df["거래량"].cumsum()

            df["세력평단"] = df["TPV"].cumsum() / cum_volume.replace(0, pd.NA)
            df["세력평단"] = df["세력평단"].ffill()

            last_close = int(df["종가"].iloc[-1])
            last_vwap = int(df["세력평단"].iloc[-1])
            disparity = ((last_close - last_vwap) / last_vwap) * 100

            # 💡 재무 및 성향 데이터
            f_info = get_financial_info(code)
            mcap_val = f_info["mcap"]
            op_profit = f_info["op_profit"]
            trade_type = f_info["trade_type"]

            # 💡 가격 지표 계산 (목표가, 매수가, 1차 손절가, 🚨 절대 손절가)
            target_1st = int(last_vwap * 1.05)   # +5%
            target_2nd = int(last_vwap * 1.10)   # +10%
            buy_limit = int(last_vwap * 1.015)   # ~ +1.5%
            stop_loss = int(last_vwap * 0.98)    # -2% (1차 손절)
            absolute_stop_loss = int(last_vwap * 0.96) # -4% (🚨 절대 이탈 금지 손절가)

            profit_str = f"🟢 흑자 ({op_profit:,}억원)" if op_profit > 0 else f"🔴 적자 ({op_profit:,}억원)"

            # 💡 진단 신호
            if 0 <= disparity <= 5.0:
                status_signal = "🔥 손절짧은 눌림목 최적타점"
            elif disparity > 20.0:
                status_signal = "⚠️ 괴리율 과다 (진입주의)"
            elif last_close < absolute_stop_loss:
                status_signal = "🚨 절대손절가 이탈 (위험)"
            else:
                status_signal = "📊 추세 추종 진행 중"

            copy_summary = (
                f"■ {s_date}~{e_date} [{current_name}({code}) - {selected_timeframe}]\n"
                f"• 시가총액: {mcap_val:,}억원 | 영업이익: {profit_str}\n"
                f"• AI 추천 매매성향: {trade_type} | 진단: {status_signal}\n"
                f"• 현재가/종가: {last_close:,}원\n"
                f"• 누적 세력평단: {last_vwap:,}원 (괴리율 {disparity:+.2f}%)\n"
                f"• 🎯 매수추천범위: {last_vwap:,}원 ~ {buy_limit:,}원\n"
                f"• 🎯 1차 목표가(+5%): {target_1st:,}원\n"
                f"• 🚀 2차 목표가(+10%): {target_2nd:,}원\n"
                f"• 🛑 1차 권장손절가(-2%): {stop_loss:,}원\n"
                f"• 🚨 [절대사수] 손절가(-4%): {absolute_stop_loss:,}원 (이탈 시 즉시 탈출)"
            )

            st.subheader(f"📊 {current_name} ({code}) - 종합 종목 분석 요약")

            # 1단 지표 카드
            f_col1, f_col2, f_col3, f_col4 = st.columns(4)
            f_col1.metric("🏢 시가총액", f"{mcap_val:,} 억원")
            f_col2.metric("💵 영업이익", f"{op_profit:,} 억원", "🟢 흑자" if op_profit > 0 else "🔴 적자")
            f_col3.metric("🎯 AI 추천 성향", trade_type)
            f_col4.metric("⚡ 진단 상태", status_signal)

            st.markdown("<br>", unsafe_allow_html=True)

            # 2단 지표 카드: 절대 손절가 추가 (총 6개 메트릭)
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            mc1.metric("현재가 / 종가", f"{last_close:,} 원")
            mc2.metric("누적 세력평단", f"{last_vwap:,} 원", f"{disparity:+.2f}%")
            mc3.metric("🎯 1차 목표가 (+5%)", f"{target_1st:,} 원")
            mc4.metric("🚀 2차 목표가 (+10%)", f"{target_2nd:,} 원")
            mc5.metric("🛑 1차 손절가 (-2%)", f"{stop_loss:,} 원")
            mc6.metric("🚨 절대사수 손절가 (-4%)", f"{absolute_stop_loss:,} 원", "이탈시 전량탈출", delta_color="inverse")

            copy_html = f"""
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #dee2e6; font-family: sans-serif;">
                <div style="display: flex; gap: 10px; margin-bottom: 12px;">
                    <button onclick="navigator.clipboard.writeText('{last_vwap}');" 
                            style="padding: 8px 16px; background-color: #ff4b4b; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        📋 세력평단 수치만 복사 ({last_vwap})
                    </button>
                    <button onclick="navigator.clipboard.writeText(document.getElementById('fullSummary').innerText);" 
                            style="padding: 8px 16px; background-color: #4bac30; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        📝 종합 매매전략 요약 복사
                    </button>
                </div>
                <pre id="fullSummary" style="margin: 0; font-family: monospace; font-size: 13px; color: #333; line-height: 1.5;">{copy_summary}</pre>
            </div>
            """
            components.html(copy_html, height=250)

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
                    line=dict(color="#ff7f0e", width=3),
                )
            )
            # 🚨 차트 상에 절대 손절가 가로 라인 표시
            fig.add_hline(
                y=absolute_stop_loss,
                line_dash="dash",
                line_color="red",
                annotation_text=f"🚨 절대사수 손절가: {absolute_stop_loss:,}원",
                annotation_position="bottom right"
            )

            fig.update_layout(
                title=f"{current_name} ({code}) - {selected_timeframe} 세력평단 차트",
                xaxis_title="시간/날짜",
                yaxis_title="가격(원)",
                hovermode="x unified",
                template="plotly_white",
                height=500,
            )
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------
# TAB 2: 업종 테마 분석 (절대 손절가 열 추가)
# ---------------------------------------------------------
with main_tab2:
    st.title("⭐ 업종·테마 분석 대시보드")
    st.caption("25개 인기 테마 시세, 실적, 세력평단 및 [목표가 / 매수단가 / 1차손절가 / 🚨절대손절가] 종합 분석")

    THEME_DATA = {
        "광케이블/광섬유": {
            "change": "+9.99%", "up_down": "상승 13 / 하락 0",
            "stocks": [
                ("대한광통신", "010170", 1850, 14.50, 12500000, 231, 2100, 1810, 1580, 1450, 1780, -45, "⚡ 단타"),
                ("광전자", "017900", 2450, 9.80, 4200000, 102, 1400, 2100, 2050, 1950, 2350, 18, "🌊 스윙"),
                ("RF머트리얼즈", "327260", 33750, 29.80, 3480000, 1174, 3920, 16572, 15200, 13800, 28500, 32, "⚡ 단타"),
            ],
        },
        "전선": {
            "change": "+8.91%", "up_down": "상승 8 / 하락 0",
            "stocks": [
                ("대한전선", "001440", 14200, 8.50, 18200000, 2584, 18500, 13950, 12100, 11500, 13900, 780, "🌊 스윙"),
                ("KBI메탈", "024840", 2150, 12.10, 8900000, 191, 850, 1850, 1780, 1650, 2020, 12, "⚡ 단타"),
                ("LS마린솔루션", "028670", 19800, 6.20, 3100000, 613, 5100, 17200, 16500, 15200, 19100, 130, "🏆 중장기"),
            ],
        },
        "통신장비": {
            "change": "+7.51%", "up_down": "상승 44 / 하락 0",
            "stocks": [
                ("이노인스트루먼트", "215790", 988, 30.00, 8876213, 85, 1923, 760, 720, 680, 910, -12, "⚡ 단타"),
                ("CS", "065770", 1990, 29.98, 723915, 13, 975, 1530, 1480, 1390, 1820, 5, "⚡ 단타"),
                ("오이솔루션", "058610", 25150, 29.84, 115747, 29, 2336, 19800, 18900, 17500, 23400, -88, "⚡ 단타"),
                ("에이스테크", "088800", 2260, 25.56, 230131, 4, 1518, 1810, 1720, 1600, 2100, -210, "⚡ 단타"),
                ("케이엠더블유", "032500", 27050, 21.57, 9348459, 243, 7686, 22100, 21000, 19800, 25800, -150, "🌊 스윙"),
                ("서진시스템", "178320", 35000, 16.86, 302016, 109, 9022, 34200, 28200, 26500, 33500, 490, "🏆 중장기"),
            ],
        },
        "반도체 대표주(생산)": {
            "change": "+6.94%", "up_down": "상승 3 / 하락 0",
            "stocks": [
                ("삼성전자", "005930", 72500, 4.50, 28500000, 20600, 4320000, 71000, 66200, 64000, 71200, 656700, "🏆 중장기"),
                ("SK하이닉스", "000660", 188500, 8.90, 8900000, 16700, 1370000, 165000, 158000, 149000, 181000, 120500, "🏆 중장기"),
                ("DB하이텍", "000990", 48500, 7.20, 1250000, 606, 21500, 47200, 41500, 39800, 46800, 2100, "🌊 스윙"),
            ],
        },
    }

    st.subheader("🔥 인기 업종·테마 Top")

    top_5_keys = list(THEME_DATA.keys())[:4]
    top_cols = st.columns(4)

    for i, t_name in enumerate(top_5_keys):
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
                <div style="font-size: 11px; color: #777; margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    {top_stocks_str}
                </div>
                <div style="font-size: 11px; color: #888; margin-top: 4px;">
                    {t_info['up_down']}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 3.2])

    with col_left:
        search_mode = st.radio(
            "검색 모드",
            ["테마 검색", "종목 검색"],
            horizontal=True,
            key="search_mode_select",
        )

        search_input = st.text_input(
            "🔍 검색어 입력...", "", key="search_general_input"
        )

        selected_theme = None
        matched_themes_from_stock = []

        if search_mode == "테마 검색":
            st.subheader(f"📊 인기 테마 목록 ({len(THEME_DATA)}개)")
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
                    key="theme_radio_select",
                )
            else:
                st.warning("검색된 테마가 없습니다.")
        else:
            st.subheader("🔎 검색된 종목 소속 테마")
            query = search_input.strip().lower()
            if query:
                for theme_name, theme_info in THEME_DATA.items():
                    for s in theme_info["stocks"]:
                        s_name = s[0]
                        s_code = str(s[1]).zfill(6)
                        if query in s_name.lower() or query in s_code:
                            matched_themes_from_stock.append((theme_name, s_name))

                if matched_themes_from_stock:
                    st.success(
                        f"총 **{len(matched_themes_from_stock)}개** 테마에 포함되어 있습니다."
                    )
                    for t_name, matched_sname in matched_themes_from_stock:
                        st.caption(f"• **{matched_sname}** ➔ [{t_name}]")
                else:
                    st.info("검색어와 일치하는 종목을 찾지 못했습니다.")
            else:
                st.info("종목명 또는 종목코드를 입력하세요.")

    with col_right:
        if search_mode == "테마 검색" and selected_theme:
            themes_to_render = [selected_theme]
        elif search_mode == "종목 검색" and matched_themes_from_stock:
            themes_to_render = list(
                dict.fromkeys([t[0] for t in matched_themes_from_stock])
            )
        else:
            themes_to_render = []

        if themes_to_render:
            for render_theme in themes_to_render:
                st.subheader(f"📌 {render_theme}")
                stocks_list = THEME_DATA[render_theme]["stocks"]

                table_rows_html = ""
                for idx, item in enumerate(stocks_list, start=1):
                    s_name = item[0]
                    s_code = str(item[1]).zfill(6)
                    curr_price = item[2]
                    change_pct = item[3]
                    trade_amt = item[5]

                    d_vwap = item[7]
                    w_vwap = item[8]
                    m_vwap = item[9]
                    m3_vwap = item[10]
                    op_profit = item[11]
                    trade_type = item[12]

                    d_disp = ((curr_price - d_vwap) / d_vwap) * 100

                    d_target = int(d_vwap * 1.05)
                    d_buy_max = int(d_vwap * 1.015)
                    d_stop = int(d_vwap * 0.98)
                    d_abs_stop = int(d_vwap * 0.96) # 🚨 절대 손절가

                    change_str = f"+{change_pct:.2f}%" if change_pct > 0 else f"{change_pct:.2f}%"

                    if op_profit > 0:
                        profit_badge = f'<span style="background-color:#e6fcf5; color:#0ca678; padding:2px 5px; border-radius:4px; font-weight:bold; font-size:10px;">🟢 흑자 ({op_profit:,}억)</span>'
                    else:
                        profit_badge = f'<span style="background-color:#fff5f5; color:#f03e3e; padding:2px 5px; border-radius:4px; font-weight:bold; font-size:10px;">🔴 적자 ({op_profit:,}억)</span>'

                    table_rows_html += f"""
                    <tr style="border-bottom: 1px solid #f0f0f0; height: 75px; font-size: 12px;">
                        <td style="text-align: center; color: #666; width: 30px;">{idx}</td>
                        <td style="font-weight: bold; color: #111; padding-left: 5px; width: 100px;">{s_name}</td>
                        <td style="text-align: center; width: 75px;">{s_code}</td>
                        <td style="text-align: center; width: 95px;">{profit_badge}</td>
                        <td style="text-align: right; padding-right: 5px; font-weight: bold; width: 65px;">{curr_price:,}원</td>
                        <td style="text-align: right; padding-right: 5px; color: #d32f2f; font-weight: bold; width: 60px;">{change_str}</td>
                        
                        <td style="text-align: center; background-color: #fff9db;">
                            <div style="font-size: 11px; font-weight: bold; color: #111;">📋 평단: {d_vwap:,}원 ({d_disp:+.1f}%)</div>
                            <div style="font-size: 9px; color: #1c7ed6; margin-top:2px;">🎯 목표: {d_target:,}원</div>
                            <div style="font-size: 9px; color: #2b8a3e;">🛒 매수: ~{d_buy_max:,}원</div>
                            <div style="font-size: 9px; color: #c92a2a;">🛑 1차 손절: {d_stop:,}원</div>
                            <div style="font-size: 9px; color: #d6336c; font-weight: bold; background-color: #ffe3e3; border-radius: 3px; margin-top:2px; padding: 1px;">🚨 절대사수 손절: {d_abs_stop:,}원</div>
                        </td>
                    </tr>
                    """

                full_table_html = f"""
                <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px; font-family: sans-serif; margin-bottom: 25px;">
                    <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                        <thead>
                            <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; color: #555; font-size: 11px; height: 38px;">
                                <th style="text-align: center; width: 30px;">순위</th>
                                <th style="text-align: left; padding-left: 5px; width: 100px;">종목명</th>
                                <th style="text-align: center; width: 75px;">종목코드</th>
                                <th style="text-align: center; width: 95px;">실적(영업이익)</th>
                                <th style="text-align: right; padding-right: 5px; width: 65px;">현재가</th>
                                <th style="text-align: right; padding-right: 5px; width: 60px;">전일대비</th>
                                <th style="text-align: center; background-color: #fff9db; color: #d9480f;">일봉 상세 전략 및 🚨 절대사수 손절가</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows_html}
                        </tbody>
                    </table>
                </div>
                """

                calc_height = max(180, len(stocks_list) * 85 + 60)
                components.html(
                    full_table_html, height=calc_height, scrolling=True
                )
