# -*- coding: utf-8 -*-
"""
kiwoom_client.py
키움 REST API(openapi.kiwoom.com) 인증 + 분봉 시세 조회 모듈
app.py 에서 import 해서 사용합니다.

사전 준비 (둘 중 아무거나 하나만 해도 됩니다):

[방법 A] 로컬 PC에서 돌릴 때 - .env 파일
1) pip install python-dotenv requests
2) .env 파일에 아래 두 줄 저장
   KIWOOM_APP_KEY=발급받은_App_Key
   KIWOOM_APP_SECRET=발급받은_App_Secret
   KIWOOM_MOCK=True   # 모의투자면 True, 실전이면 False

[방법 B] Streamlit Community Cloud에 배포할 때 - Secrets 설정 (추천)
Streamlit Cloud는 .env 파일을 못 올리고, python-dotenv가 requirements.txt에
없으면 앱이 아예 시작도 못 하고 죽습니다(ModuleNotFoundError). 그래서 Cloud에서는
앱 관리 화면 > Settings > Secrets 에 아래처럼 입력하세요:
   KIWOOM_APP_KEY = "발급받은_App_Key"
   KIWOOM_APP_SECRET = "발급받은_App_Secret"
   KIWOOM_MOCK = "True"
이 파일은 python-dotenv가 없어도, .env가 없어도 죽지 않고 st.secrets에서
자동으로 값을 읽어옵니다.
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, date

# python-dotenv가 requirements.txt에 없으면(특히 Streamlit Cloud) import 자체가
# 실패해서 앱이 통째로 죽습니다. 없어도 죽지 않게 선택적으로만 사용합니다.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_credential(key: str, default=None):
    """
    자격증명을 두 군데서 순서대로 찾는다:
    1) 환경변수 / .env (로컬 개발용)
    2) Streamlit Cloud의 st.secrets (배포용, 추천)
    """
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


APP_KEY = _get_credential("KIWOOM_APP_KEY")
APP_SECRET = _get_credential("KIWOOM_APP_SECRET")
IS_MOCK = str(_get_credential("KIWOOM_MOCK", "True")).lower() == "true"

# 공식 API 가이드(OAuth 인증 > 접근토큰발급) 기준 - 2026년 확인된 정확한 값
BASE_URL = "https://mockapi.kiwoom.com" if IS_MOCK else "https://api.kiwoom.com"

_token_cache = {"access_token": None, "expires_at": 0}


def get_access_token() -> str:
    """
    접근 토큰 발급 (캐싱: 만료 전이면 재사용)
    공식 문서 기준: POST {BASE_URL}/oauth2/token
    실제 응답 형식: {"expires_dt": "20261107083713", "token_type": "Bearer",
                     "token": "...", "return_code": 0, "return_msg": "정상적으로 처리되었습니다"}
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    if not APP_KEY or not APP_SECRET:
        raise RuntimeError(
            "KIWOOM_APP_KEY / KIWOOM_APP_SECRET이 설정되지 않았습니다. "
            "로컬이면 .env 파일, Streamlit Cloud면 Settings > Secrets에 등록해주세요."
        )

    url = f"{BASE_URL}/oauth2/token"
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    payload = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET,
    }
    res = requests.post(url, headers=headers, json=payload, timeout=5)
    res.raise_for_status()
    data = res.json()

    if data.get("return_code") != 0:
        raise RuntimeError(f"토큰 발급 실패: {data.get('return_msg')}")

    _token_cache["access_token"] = data["token"]  # 필드명: token (access_token 아님)

    # expires_dt는 "YYYYMMDDHHMMSS" 형식의 만료 시각(문자열) -> epoch 초로 변환
    expires_dt = data.get("expires_dt")
    if expires_dt:
        exp_time = datetime.strptime(expires_dt, "%Y%m%d%H%M%S")
        _token_cache["expires_at"] = exp_time.timestamp()
    else:
        _token_cache["expires_at"] = now + 43200  # 안전 기본값 12시간

    return _token_cache["access_token"]


def _auth_headers() -> dict:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }


def fetch_minute_chart(stock_code: str, tick_range: int = 3, base_dt: str = None) -> pd.DataFrame:
    """
    당일 분봉 조회 (TR: ka10080 - 주식분봉차트조회요청, 공식 문서 기준 확정 스펙)
    stock_code : 6자리 종목코드 (예: '005930')
    tick_range : 분봉 단위 (1, 3, 5 ...)
    base_dt    : 기준일자 YYYYMMDD, None이면 오늘 날짜 사용
    반환값     : datetime, open, high, low, close, volume 컬럼을 가진 DataFrame
    """
    if base_dt is None:
        base_dt = date.today().strftime("%Y%m%d")

    url = f"{BASE_URL}/api/dostk/chart"
    headers = _auth_headers()
    headers["cont-yn"] = "N"
    headers["next-key"] = ""
    headers["api-id"] = "ka10080"

    payload = {
        "stk_cd": stock_code,
        "tic_scope": str(tick_range),   # "1", "3", "5" 등 분봉 단위
        "upd_stkpc_tp": "1",
        "base_dt": base_dt,
    }

    res = requests.post(url, headers=headers, json=payload, timeout=5)
    res.raise_for_status()
    body = res.json()

    if body.get("return_code") != 0:
        raise RuntimeError(f"분봉 조회 실패: {body.get('return_msg')}")

    rows = body.get("stk_min_pole_chart_qry", [])
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        # 가격 필드는 부호("+"/"-")가 붙어 오므로 절대값 처리
        def _num(v):
            try:
                return abs(int(str(v).replace("+", "").replace("-", "")))
            except (TypeError, ValueError):
                return None

        cntr_tm = r.get("cntr_tm", "")  # YYYYMMDDHHMMSS
        try:
            dt = datetime.strptime(cntr_tm, "%Y%m%d%H%M%S")
        except ValueError:
            continue

        records.append({
            "datetime": dt,
            "open": _num(r.get("open_pric")),
            "high": _num(r.get("high_pric")),
            "low": _num(r.get("low_pric")),
            "close": _num(r.get("cur_prc")),
            "volume": _num(r.get("trde_qty")),
        })

    df = pd.DataFrame(records).sort_values("datetime").reset_index(drop=True)
    return df


if __name__ == "__main__":
    # 연결 테스트
    token = get_access_token()
    print("토큰 발급 성공:", token[:12], "...")
    df = fetch_minute_chart("005930", tick_range=3)
    print(f"분봉 {len(df)}건 수신")
    print(df.tail())
