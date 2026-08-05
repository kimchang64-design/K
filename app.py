import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pykrx import stock

# 페이지 기본 설정
st.set_page_config(page_title="주식 분석 포털 - VWAP & 업종테마", layout="wide")

# 사이드바/상단 탭 구성
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

    # 대표 샘플 테마 데이터셋 (인기 25개 테마 구성)
    THEME_DATA = {
        "광케이블/광섬유": {
            "change": "+9.99%",
            "up_down": "상승 13 / 하락 0",
            "stocks": [
                ("대한광통신", "010170", 1850, 14.50, 12500000, 231, 2100),
                ("광전자", "017900", 2450, 9.80, 4200000, 102, 1400),
                ("RF머트리얼즈", "327260", 33750, 29.80, 3480000, 1174, 3920),
            ],
        },
        "전선": {
            "change": "+8.91%",
            "up_down": "상승 8 / 하락 0",
            "stocks": [
                ("대한전선", "001440", 14200, 8.50, 18200000, 2584, 18500),
                ("KBI메탈", "024840", 2150, 12.10, 8900000, 191, 850),
                ("LS마린솔루션", "028670", 19800, 6.20, 3100000, 613, 5100),
            ],
        },
        "통신장비": {
            "change": "+7.51%",
            "up_down": "상승 44 / 하락 0",
            "stocks": [
                ("이노인스트루먼트", "215790", 988, 30.00, 8876213, 85, 1923),
                ("CS", "065770", 1990, 29.98, 723915, 13, 975),
                ("오이솔루션", "058610", 25150, 29.84, 115747, 29, 2336),
                ("에이스테크", "088800", 2260, 25.56, 230131, 4, 1518),
                ("케이엠더블유", "032500", 27050, 21.57, 9348459, 243, 7686),
                ("서진시스템", "178320", 35000, 16.86, 302016, 109, 9022),
            ],
        },
        "반도체 대표주(생산)": {
            "change": "+6.94%",
            "up_down": "상승 3 / 하락 0",
            "stocks": [
                ("삼성전자", "005930", 72500, 4.50, 28500000, 20600, 4320000),
                ("SK하이닉스", "000660", 188500, 8.90, 8900000, 16700, 1370000),
                ("DB하이텍", "000990", 48500, 7.20, 1250000, 606, 21500),
            ],
        },
        "5G(5세대 이동통신)": {
            "change": "+6.59%",
            "up_down": "상승 50 / 하락 2",
            "stocks": [
                ("RFHIC", "218410", 18900, 12.50, 2100000, 396, 4800),
                ("쏠리드", "050890", 6100, 7.80, 1850000, 112, 3700),
                ("에프알텍", "083450", 3120, 15.20, 3100000, 96, 820),
            ],
        },
        "온디바이스 AI": {
            "change": "+6.57%",
            "up_down": "상승 18 / 하락 1",
            "stocks": [
                ("제주반도체", "080220", 24500, 18.20, 14500000, 3550, 8400),
                ("리노공업", "058470", 210000, 5.40, 620000, 1302, 31900),
                ("칩스앤미디어", "094360", 28900, 11.20, 2800000, 809, 5800),
            ],
        },
        "CXL(컴퓨터 익스프레스 링크)": {
            "change": "+6.22%",
            "up_down": "상승 12 / 하락 0",
            "stocks": [
                ("네오셈", "253590", 14200, 22.40, 9800000, 1391, 6200),
                ("엑시콘", "092870", 18500, 14.10, 4100000, 758, 3800),
            ],
        },
        "HBM(고대역폭메모리)": {
            "change": "+5.88%",
            "up_down": "상승 22 / 하락 2",
            "stocks": [
                ("한미반도체", "042700", 145000, 11.50, 5200000, 7540, 141000),
                ("피에스케이홀딩스", "031980", 52000, 8.40, 1800000, 936, 11000),
            ],
        },
        "PCB(연성회로기판)": {
            "change": "+5.40%",
            "up_down": "상승 15 / 하락 3",
            "stocks": [
                ("대덕전자", "353200", 24100, 6.20, 1100000, 265, 12000),
                ("심텍", "222800", 31200, 5.10, 950000, 296, 9900),
            ],
        },
        "2차전지(장비)": {
            "change": "+4.95%",
            "up_down": "상승 28 / 하락 4",
            "stocks": [
                ("피엔티", "137400", 54000, 7.80, 1400000, 756, 12200),
                ("하나기술", "299030", 48500, 4.30, 620000, 300, 4800),
            ],
        },
        "로봇(산업용/협동)": {
            "change": "+4.80%",
            "up_down": "상승 31 / 하락 2",
            "stocks": [
                ("두산로보틱스", "454910", 78000, 9.20, 3200000, 2496, 50500),
                ("레인보우로보틱스", "277810", 162000, 6.10, 1100000, 1782, 31100),
            ],
        },
        "바이오시밀러": {
            "change": "+4.12%",
            "up_down": "상승 19 / 하락 5",
            "stocks": [
                ("셀트리온", "068270", 192000, 3.80, 1500000, 2880, 420000),
                ("삼성바이오로직스", "207940", 810000, 2.50, 320000, 2592, 576000),
            ],
        },
        "초전도체": {
            "change": "+3.95%",
            "up_down": "상승 9 / 하락 1",
            "stocks": [
                ("신성델타테크", "065350", 92000, 14.20, 6500000, 5980, 25200),
                ("파워로직스", "047310", 81000, 11.00, 4100000, 3321, 14000),
            ],
        },
        "원자력발전": {
            "change": "+3.80%",
            "up_down": "상승 25 / 하락 3",
            "stocks": [
                ("두산에너빌리티", "034020", 21500, 5.20, 11200000, 2408, 137000),
                ("우진엔텍", "457550", 24800, 13.50, 5800000, 1438, 2300),
            ],
        },
        "방위산업/전쟁": {
            "change": "+3.65%",
            "up_down": "상승 20 / 하락 2",
            "stocks": [
                ("한화에어로스페이스", "012450", 285000, 6.80, 1800000, 5130, 144000),
                ("LIG넥스원", "079550", 210000, 4.50, 720000, 1512, 46200),
            ],
        },
        "전력설비/변압기": {
            "change": "+3.50%",
            "up_down": "상승 16 / 하락 1",
            "stocks": [
                ("HD현대일렉트릭", "267260", 295000, 8.20, 1400000, 4130, 106000),
                ("제룡전기", "033100", 68000, 10.50, 2100000, 1428, 10900),
            ],
        },
        "우주항공산업": {
            "change": "+3.20%",
            "up_down": "상승 14 / 하락 2",
            "stocks": [
                ("컨코아에어로스페이스", "274500", 12500, 7.80, 1900000, 237, 1800),
                ("AP위성", "211270", 16800, 5.40, 820000, 137, 2500),
            ],
        },
        "자율주행": {
            "change": "+3.10%",
            "up_down": "상승 22 / 하락 4",
            "stocks": [
                ("모트렉스", "118990", 13200, 4.20, 1100000, 145, 3200),
                ("현대오토에버", "307950", 154000, 3.80, 410000, 631, 42200),
            ],
        },
        "의료AI": {
            "change": "+2.95%",
            "up_down": "상승 11 / 하락 2",
            "stocks": [
                ("루닛", "328130", 52000, 8.90, 2800000, 1456, 14900),
                ("뷰노", "338220", 31500, 6.40, 1200000, 378, 4100),
            ],
        },
        "폐배터리 재활용": {
            "change": "+2.80%",
            "up_down": "상승 10 / 하락 3",
            "stocks": [
                ("성일하이텍", "365340", 68500, 3.50, 450000, 308, 8200),
                ("새빗켐", "107600", 42000, 4.10, 320000, 134, 2500),
            ],
        },
        "정밀의료/유전자": {
            "change": "+2.60%",
            "up_down": "상승 13 / 하락 4",
            "stocks": [
                ("마크로젠", "038290", 22500, 5.10, 620000, 139, 2300),
            ],
        },
        "스마트팩토리": {
            "change": "+2.45%",
            "up_down": "상승 17 / 하락 3",
            "stocks": [
                ("엠아이큐브솔루션", "373170", 15400, 6.20, 890000, 137, 1800),
            ],
        },
        "화장품/K-뷰티": {
            "change": "+2.30%",
            "up_down": "상승 29 / 하락 6",
            "stocks": [
                ("실리콘투", "257720", 45000, 9.10, 5800000, 2610, 27100),
                ("한국화장품제조", "003350", 62000, 12.40, 2100000, 1302, 2800),
            ],
        },
        "엔터테인먼트/K-POP": {
            "change": "+2.10%",
            "up_down": "상승 12 / 하락 5",
            "stocks": [
                ("JYP Ent.", "035900", 58000, 2.80, 680000, 394, 20600),
                ("하이브", "352820", 182000, 1.90, 420000, 764, 75800),
            ],
        },
        "게임/L2E": {
            "change": "+1.95%",
            "up_down": "상승 18 / 하락 8",
            "stocks": [
                ("크래프톤", "259960", 295000, 3.40, 510000, 1504, 142000),
                ("펄어비스", "263750", 38500, 2.10, 410000, 157, 24800),
            ],
        },
    }

    # 1. 인기 업종·테마 TOP 1위 ~ 5위 카드 영역
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

    # 2. 인기 테마 목록 25개 + 세부 종목 레이아웃
    col_left, col_right = st.columns([1, 2.5])

    with col_left:
        st.subheader("📊 인기 테마 목록 (25개)")
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

            # 정렬 필터 옵션
            sort_option = st.radio(
                "정렬 필터",
                ["전체", "거래대금 상위", "상승 TOP"],
                horizontal=True,
                key="sort_filter_option",
            )

            # DataFrame 변환
            df_theme = pd.DataFrame(
                stocks_list,
                columns=[
                    "종목명",
                    "종목코드",
                    "현재가",
                    "전일대비(%)",
                    "거래량",
                    "거래대금(백만)",
                    "시가총액(억)",
                ],
            )

            if sort_option == "거래대금 상위":
                df_theme = df_theme.sort_values(
                    by="거래대금(백만)", ascending=False
                )
            elif sort_option == "상승 TOP":
                df_theme = df_theme.sort_values(
                    by="전일대비(%)", ascending=False
                )

            # 테이블 표기 형식 가공
            df_display = df_theme.copy()
            df_display.insert(0, "순위", range(1, len(df_display) + 1))

            df_display["현재가"] = df_display["현재가"].apply(
                lambda x: f"{x:,}원"
            )
            df_display["전일대비"] = df_display["전일대비(%)"].apply(
                lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%"
            )
            df_display["거래량"] = df_display["거래량"].apply(
                lambda x: f"{x:,}"
            )
            df_display["거래대금"] = df_display["거래대금(백만)"].apply(
                lambda x: f"{x:,}백만"
            )
            df_display["시가총액"] = df_display["시가총액(억)"].apply(
                lambda x: f"{x:,}억"
            )

            # 표시용 컬럼 정리
            show_cols = [
                "순위",
                "종목명",
                "종목코드",
                "현재가",
                "전일대비",
                "거래량",
                "거래대금",
                "시가총액",
            ]
            st.dataframe(
                df_display[show_cols],
                hide_index=True,
                use_container_width=True,
                height=450,
            )
