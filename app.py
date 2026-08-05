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


# ---------------------------------------------------------
# TAB 1: 세력 평단가(VWAP) 차트
# ---------------------------------------------------------
with main_tab1:
    st.title("📈 세력 평단가(VWAP) 분석 대시보드")

    if "recent_codes" not in st.session_state:
        st.session_state.recent_codes = []

    col1, col2, col3 = st.columns([1.2, 1, 1])

    with col1:
        code = st.text_input("종목코드 (6자리)", "005930", key="vwap_code_input")
        stock_name = get_stock_name(code)
        if stock_name != code:
            st.caption(f"📌 **종목명:** {stock_name} ({code})")

    with col2:
        time_type = st.radio(
            "차트 주기 구분", ["일/주/월봉", "분봉"], horizontal=True, key="time_type"
        )

    with col3:
        if time_type == "일/주/월봉":
            day_type = st.selectbox(
                "봉 단위 선택", ["일봉", "주봉", "월봉"], index=0, key="day_type"
            )
            selected_timeframe = day_type
        else:
            min_type = st.selectbox(
                "분봉 단위 선택",
                [
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
                ],
                index=0,
                key="min_type",
            )
            selected_timeframe = min_type

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

    if time_type == "일/주/월봉":
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

            copy_summary = f"■ {s_date}~{e_date} [{current_name}({code})]\n• 종가: {last_close:,}원\n• 세력평단: {last_vwap:,}원\n• 괴리율: {disparity:+.2f}%"

            st.subheader(f"📊 {current_name} ({code}) 분석 결과 요약")

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("현재가 / 종가", f"{last_close:,} 원")
            mc2.metric("누적 세력평단", f"{last_vwap:,} 원")
            mc3.metric("괴리율", f"{disparity:+.2f} %")

            copy_html = f"""
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #dee2e6; font-family: sans-serif;">
                <div style="display: flex; gap: 10px; margin-bottom: 12px;">
                    <button onclick="navigator.clipboard.writeText('{last_vwap}');" 
                            style="padding: 8px 16px; background-color: #ff4b4b; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        📋 세력평단 수치만 복사 ({last_vwap})
                    </button>
                    <button onclick="navigator.clipboard.writeText(document.getElementById('fullSummary').innerText);" 
                            style="padding: 8px 16px; background-color: #4bac30; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        📝 전체 결과 요약 복사
                    </button>
                </div>
                <pre id="fullSummary" style="margin: 0; font-family: monospace; font-size: 13px; color: #333; line-height: 1.5;">{copy_summary}</pre>
            </div>
            """
            components.html(copy_html, height=160)

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
# TAB 2: 업종 테마 분석
# ---------------------------------------------------------
with main_tab2:
    st.title("⭐ 업종·테마 분석 대시보드")
    st.caption("주도 업종/테마 순위 및 테마별 세부 구성 종목의 시세를 분석합니다.")

    # 각 종목 구조: (종목명, 코드, 현재가, 전일대비%, 거래량, 거래대금, 시총, 일봉평단, 주봉평단, 월봉평단, 3분봉평단)
    THEME_DATA = {
        "광케이블/광섬유": {
            "change": "+9.99%",
            "up_down": "상승 13 / 하락 0",
            "stocks": [
                ("대한광통신", "010170", 1850, 14.50, 12500000, 231, 2100, 1620, 1580, 1450, 1780),
                ("광전자", "017900", 2450, 9.80, 4200000, 102, 1400, 2100, 2050, 1950, 2350),
                ("RF머트리얼즈", "327260", 33750, 29.80, 3480000, 1174, 3920, 16572, 15200, 13800, 28500),
            ],
        },
        "전선": {
            "change": "+8.91%",
            "up_down": "상승 8 / 하락 0",
            "stocks": [
                ("대한전선", "001440", 14200, 8.50, 18200000, 2584, 18500, 12800, 12100, 11500, 13900),
                ("KBI메탈", "024840", 2150, 12.10, 8900000, 191, 850, 1850, 1780, 1650, 2020),
                ("LS마린솔루션", "028670", 19800, 6.20, 3100000, 613, 5100, 17200, 16500, 15200, 19100),
            ],
        },
        "통신장비": {
            "change": "+7.51%",
            "up_down": "상승 44 / 하락 0",
            "stocks": [
                ("이노인스트루먼트", "215790", 988, 30.00, 8876213, 85, 1923, 760, 720, 680, 910),
                ("CS", "065770", 1990, 29.98, 723915, 13, 975, 1530, 1480, 1390, 1820),
                ("오이솔루션", "058610", 25150, 29.84, 115747, 29, 2336, 19800, 18900, 17500, 23400),
                ("에이스테크", "088800", 2260, 25.56, 230131, 4, 1518, 1810, 1720, 1600, 2100),
                ("케이엠더블유", "032500", 27050, 21.57, 9348459, 243, 7686, 22100, 21000, 19800, 25800),
                ("서진시스템", "178320", 35000, 16.86, 302016, 109, 9022, 29800, 28200, 26500, 33500),
            ],
        },
        "반도체 대표주(생산)": {
            "change": "+6.94%",
            "up_down": "상승 3 / 하락 0",
            "stocks": [
                ("삼성전자", "005930", 72500, 4.50, 28500000, 20600, 4320000, 68500, 66200, 64000, 71200),
                ("SK하이닉스", "000660", 188500, 8.90, 8900000, 16700, 1370000, 165000, 158000, 149000, 181000),
                ("DB하이텍", "000990", 48500, 7.20, 1250000, 606, 21500, 43200, 41500, 39800, 46800),
            ],
        },
        "5G(5세대 이동통신)": {
            "change": "+6.59%",
            "up_down": "상승 50 / 하락 2",
            "stocks": [
                ("RFHIC", "218410", 18900, 12.50, 2100000, 396, 4800, 16200, 15500, 14200, 17900),
                ("쏠리드", "050890", 6100, 7.80, 1850000, 112, 3700, 5400, 5100, 4800, 5900),
                ("에프알텍", "083450", 3120, 15.20, 3100000, 96, 820, 2600, 2450, 2300, 2980),
            ],
        },
        "온디바이스 AI": {
            "change": "+6.57%",
            "up_down": "상승 18 / 하락 1",
            "stocks": [
                ("제주반도체", "080220", 24500, 18.20, 14500000, 3550, 8400, 19500, 18200, 16900, 22800),
                ("리노공업", "058470", 210000, 5.40, 620000, 1302, 31900, 192000, 185000, 178000, 205000),
                ("칩스앤미디어", "094360", 28900, 11.20, 2800000, 809, 5800, 24100, 23000, 21800, 27300),
            ],
        },
    }

    # 1. 인기 업종·테마 TOP 1위 ~ 5위
    st.subheader("🔥 인기 업종·테마 Top (1위 ~ 5위)")

    top_5_keys = list(THEME_DATA.keys())[:5]
    top_cols = st.columns(5)

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

    # 2. 테마 세부 종목 레이아웃
    col_left, col_right = st.columns([1, 3.2])

    with col_left:
        st.subheader("📊 인기 테마 목록")
        search_theme = st.text_input(
            "🔍 테마 검색...", "", key="search_theme_input"
        )

        filtered_themes = [
            t for t in THEME_DATA.keys() if search_theme.lower() in t.lower()
        ]

        selected_theme = st.radio(
            "테마 선택",
            filtered_themes,
            index=0 if filtered_themes else None,
            label_visibility="collapsed",
            key="theme_radio_select",
        )

    with col_right:
        if selected_theme:
            t_data = THEME_DATA[selected_theme]
            stocks_list = t_data["stocks"]

            st.subheader(f"📌 {selected_theme}")

            # 정렬 필터
            sort_option = st.radio(
                "정렬 필터",
                ["전체", "거래대금 상위", "상승 TOP"],
                horizontal=True,
                key="sort_filter_option",
            )

            if sort_option == "거래대금 상위":
                stocks_list = sorted(stocks_list, key=lambda x: x[5], reverse=True)
            elif sort_option == "상승 TOP":
                stocks_list = sorted(stocks_list, key=lambda x: x[3], reverse=True)

            table_rows_html = ""
            for idx, item in enumerate(stocks_list, start=1):
                s_name = item[0]
                s_code = str(item[1]).zfill(6)
                curr_price = item[2]
                
                # 4대 주기 세력평단 수치
                d_vwap = item[7]   # 일봉
                w_vwap = item[8]   # 주봉
                m_vwap = item[9]   # 월봉
                m3_vwap = item[10] # 3분봉

                # 괴리율 계산: ((현재가 - 세력평단) / 세력평단) * 100
                d_disp = ((curr_price - d_vwap) / d_vwap) * 100
                w_disp = ((curr_price - w_vwap) / w_vwap) * 100
                m_disp = ((curr_price - m_vwap) / m_vwap) * 100
                m3_disp = ((curr_price - m3_vwap) / m3_vwap) * 100

                table_rows_html += f"""
                <tr style="border-bottom: 1px solid #f0f0f0; height: 48px; font-size: 12px;">
                    <td style="text-align: center; color: #666; width: 35px;">{idx}</td>
                    <td style="font-weight: bold; color: #111; padding-left: 5px; width: 100px;">{s_name}</td>
                    <td style="text-align: center; width: 75px;">
                        <button onclick="navigator.clipboard.writeText('{s_code}');" 
                                style="padding: 2px 4px; background-color: #f1f3f5; color: #333; border: 1px solid #ced4da; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px;">
                            📋 {s_code}
                        </button>
                    </td>
                    <td style="text-align: right; padding-right: 5px; font-weight: bold; width: 75px;">{curr_price:,}원</td>
                    
                    <!-- 일봉 -->
                    <td style="text-align: center; background-color: #fff9db;">
                        <button onclick="navigator.clipboard.writeText('{d_vwap}');" 
                                style="padding: 2px 4px; background-color: #ffe066; color: #000; border: 1px solid #fcc419; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px; font-weight: bold;">
                            📋 {d_vwap:,}
                        </button>
                        <div style="font-size: 10px; color: {'#d32f2f' if d_disp > 0 else '#1976d2'}; font-weight: bold;">{d_disp:+.1f}%</div>
                    </td>
                    
                    <!-- 주봉 -->
                    <td style="text-align: center; background-color: #fff3bf;">
                        <button onclick="navigator.clipboard.writeText('{w_vwap}');" 
                                style="padding: 2px 4px; background-color: #ffd43b; color: #000; border: 1px solid #fab005; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px; font-weight: bold;">
                            📋 {w_vwap:,}
                        </button>
                        <div style="font-size: 10px; color: {'#d32f2f' if w_disp > 0 else '#1976d2'}; font-weight: bold;">{w_disp:+.1f}%</div>
                    </td>

                    <!-- 월봉 -->
                    <td style="text-align: center; background-color: #ffec99;">
                        <button onclick="navigator.clipboard.writeText('{m_vwap}');" 
                                style="padding: 2px 4px; background-color: #fcc419; color: #000; border: 1px solid #f59f00; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px; font-weight: bold;">
                            📋 {m_vwap:,}
                        </button>
                        <div style="font-size: 10px; color: {'#d32f2f' if m_disp > 0 else '#1976d2'}; font-weight: bold;">{m_disp:+.1f}%</div>
                    </td>

                    <!-- 3분봉 -->
                    <td style="text-align: center; background-color: #e7f5ff;">
                        <button onclick="navigator.clipboard.writeText('{m3_vwap}');" 
                                style="padding: 2px 4px; background-color: #a5d8ff; color: #000; border: 1px solid #74c0fc; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px; font-weight: bold;">
                            📋 {m3_vwap:,}
                        </button>
                        <div style="font-size: 10px; color: {'#d32f2f' if m3_disp > 0 else '#1976d2'}; font-weight: bold;">{m3_disp:+.1f}%</div>
                    </td>
                </tr>
                """

            full_table_html = f"""
            <div style="overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <table style="width: 100%; border-collapse: collapse; background-color: #ffffff;">
                    <thead>
                        <tr style="background-color: #fafafa; border-bottom: 2px solid #e0e0e0; color: #555; font-size: 11px; height: 38px;">
                            <th style="text-align: center; width: 35px;">순위</th>
                            <th style="text-align: left; padding-left: 5px; width: 100px;">종목명</th>
                            <th style="text-align: center; width: 75px;">종목코드</th>
                            <th style="text-align: right; padding-right: 5px; width: 75px;">현재가</th>
                            <th style="text-align: center; background-color: #fff9db; color: #d9480f;">일봉 평단 (괴리율)</th>
                            <th style="text-align: center; background-color: #fff3bf; color: #d9480f;">주봉 평단 (괴리율)</th>
                            <th style="text-align: center; background-color: #ffec99; color: #d9480f;">월봉 평단 (괴리율)</th>
                            <th style="text-align: center; background-color: #e7f5ff; color: #1864ab;">3분봉 평단 (괴리율)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>
            """

            calc_height = max(200, len(stocks_list) * 55 + 60)
            components.html(full_table_html, height=calc_height, scrolling=True)
