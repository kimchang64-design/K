@st.cache_data(ttl=15)
def get_intraday_data(ticker, timeframe):
    real_current_price = None
    try:
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        df_real = stock.get_market_ohlcv_by_date(today_str, today_str, ticker)
        if not df_real.empty and "종가" in df_real.columns:
            real_current_price = int(df_real["종가"].iloc[-1])
    except Exception:
        pass

    base_prices = {
        "009150": 1250000, # 삼성전기
        "073240": 7400,
        "264850": 7400,
        "327260": 7350,
        "067290": 2455,
        "252670": 1850,
        "005930": 72500,
        "000660": 1551000,
    }
    
    if real_current_price and real_current_price > 100:
        base_price = real_current_price
    else:
        base_price = base_prices.get(ticker, 1250000)

    # 핵심: 오늘 장 시작(09:00)부터 '현재 정확한 시각'까지만 데이터 생성 (미래 시간 차단)
    market_open = pd.Timestamp.today().normalize() + pd.Timedelta(hours=9, minutes=0)
    current_time = datetime.datetime.now()
    
    # 만약 장 시작 전이거나 주말/장 마감 후라면 현재 시각을 보정
    market_close = pd.Timestamp.today().normalize() + pd.Timedelta(hours=15, minutes=30)
    if current_time < market_open:
        current_time = market_open + pd.Timedelta(minutes=5)
    elif current_time > market_close:
        current_time = market_close

    dates = pd.date_range(start=market_open, end=current_time, freq=timeframe)
    if len(dates) < 2:
        dates = pd.date_range(start=market_open, periods=10, freq=timeframe)

    ticker_num = int(ticker) if ticker.isdigit() else hash(ticker) % 100000
    np.random.seed(ticker_num + datetime.datetime.now().minute)
    
    volatility = base_price * 0.003
    price_changes = np.random.normal(loc=0.01, scale=volatility, size=len(dates))
    closes = base_price + np.cumsum(price_changes)
    
    volumes = np.random.randint(1000, 20000, size=len(dates))

    df_intra = pd.DataFrame({"시간": dates, "종가": closes, "거래량": volumes})
    df_intra.set_index("시간", inplace=True)

    df_intra["TPV"] = df_intra["종가"] * df_intra["거래량"]
    df_intra["누적거래대금"] = df_intra["TPV"].cumsum()
    df_intra["누적거래량"] = df_intra["거래량"].cumsum()
    
    vwap_base = df_intra["누적거래대금"] / df_intra["누적거래량"]
    df_intra["세력평단"] = vwap_base.ewm(span=5).mean()

    return df_intra
