@st.cache_data(ttl=15)
def get_intraday_data(ticker, timeframe):
    # 1. pykrx를 통해 오늘 실제 현재가 조회 시도
    real_current_price = None
    try:
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        df_real = stock.get_market_ohlcv_by_date(today_str, today_str, ticker)
        if not df_real.empty and "종가" in df_real.columns:
            real_current_price = int(df_real["종가"].iloc[-1])
    except Exception:
        pass

    # 2. 종목별 실제 기준가 매칭 (없을 경우 기본값 적용)
    base_prices = {
        "073240": 7400,   # 금호타이어
        "264850": 7400,   # 이엔셀
        "327260": 7350,   # RF머트리얼즈
        "067290": 2455,   # JW신약
        "252670": 1850,   # 코스나인
        "005930": 72500,  # 삼성전자
        "000660": 1551000,# SK하이닉스
    }
    
    if real_current_price and real_current_price > 100:
        base_price = real_current_price
    else:
        base_price = base_prices.get(ticker, 10000)

    # 3. 장 시작 시간(09:00)부터 현재 시간까지 분봉 타임스탬프 생성
    market_open = pd.Timestamp.today().normalize() + pd.Timedelta(hours=9, minutes=0)
    current_time = datetime.datetime.now()
    if current_time < market_open or current_time.hour >= 15:
        current_time = market_open + pd.Timedelta(hours=6, minutes=30)

    dates = pd.date_range(start=market_open, end=current_time, freq=timeframe)
    if len(dates) < 5:
        dates = pd.date_range(start=market_open, periods=20, freq=timeframe)

    # 4. 종목 코드(숫자)를 활용하되 시간에 따라 주가가 입체적으로 출렁이도록 고유 난수 생성
    ticker_num = int(ticker) if ticker.isdigit() else hash(ticker) % 100000
    np.random.seed(ticker_num + datetime.datetime.now().minute) # 분 단위로 모양이 다이내믹하게 바뀌도록 설정
    
    volatility = base_price * 0.005
    price_changes = np.random.normal(loc=0.02, scale=volatility, size=len(dates))
    closes = base_price + np.cumsum(price_changes)
    
    # 거래량에 따라 세력평단이 확확 움직이도록 변동성 부여
    volumes = np.random.randint(5000, 80000, size=len(dates))
    # 특정 구간에 거래량이 터지도록 조절
    volumes[len(volumes)//3] *= 4
    volumes[(len(volumes)*2)//3] *= 3

    df_intra = pd.DataFrame({"시간": dates, "종가": closes, "거래량": volumes})
    df_intra.set_index("시간", inplace=True)

    # 5. 세력평단 (가중평균 VWAP 계산에 지수 이동 가중치를 섞어 주가 변동에 민감하게 반응하도록 개선)
    df_intra["TPV"] = df_intra["종가"] * df_intra["거래량"]
    df_intra["누적거래대금"] = df_intra["TPV"].cumsum()
    df_intra["누적거래량"] = df_intra["거래량"].cumsum()
    
    # 세력평단선이 주가 흐름에 맞춰 자연스럽고 다이내믹하게 꺾이도록 이동평균 및 VWAP 결합
    vwap_base = df_intra["누적거래대금"] / df_intra["누적거래량"]
    df_intra["세력평단"] = vwap_base.ewm(span=5).mean()

    return df_intra
