"""KRX 공식 Open API(ETF 일별매매정보) 호출.

data.krx.co.kr 비로그인 요청은 'LOGOUT' 응답으로 막혀서(pykrx 포함)
공식 Open API(openapi.krx.co.kr)의 ETF 일별매매정보를 사용한다.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd"
COLS = {"BAS_DD": "일자", "ISU_CD": "종목코드", "ISU_NM": "종목명", "TDD_CLSPRC": "종가",
        "NAV": "NAV", "ACC_TRDVOL": "거래량", "INVSTASST_NETASST_TOTAMT": "순자산총액"}
KEEP = list(COLS.values())


class KRXError(RuntimeError):
    pass


def get_key() -> str | None:
    """인증키 찾는 순서: Streamlit secrets → 환경변수 KRX_API_KEY → .krx_api_key 파일.
    키는 저장소에 올리지 않는다(.gitignore)."""
    try:
        import streamlit as st
        if "KRX_API_KEY" in st.secrets:
            return str(st.secrets["KRX_API_KEY"]).strip()
    except Exception:
        pass
    if os.environ.get("KRX_API_KEY"):
        return os.environ["KRX_API_KEY"].strip()
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".krx_api_key")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read().strip()
    return None


def _get(bas_dd: str, key: str) -> list[dict]:
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL, params={"basDd": bas_dd}, headers={"AUTH_KEY": key}, timeout=20)
        except requests.RequestException as e:
            if attempt == 2:
                raise KRXError(f"KRX 연결 실패: {e}") from e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (401, 403):
            raise KRXError(f"KRX 인증 실패(HTTP {r.status_code}). 인증키·이용 신청 승인 여부를 확인하세요.")
        if r.status_code != 200:
            raise KRXError(f"KRX HTTP {r.status_code}: {r.text[:200]!r}")
        return r.json().get("OutBlock_1") or []
    return []


def fetch_day_raw(bas_dd: str, key: str) -> pd.DataFrame:
    """KRX 응답 원본 그대로(문자열). 검증 화면에서 공시값과 대조할 때 쓴다."""
    return pd.DataFrame(_get(bas_dd, key))


def fetch_day(bas_dd: str, key: str) -> pd.DataFrame:
    """basDd(YYYYMMDD) 하루치 ETF 전종목(약 1,190개).
    휴장일에는 KRX가 빈 행(종가·NAV 결측)을 주므로 그런 행은 여기서 버린다."""
    df = pd.DataFrame(_get(bas_dd, key)).rename(columns=COLS)
    if df.empty:
        return pd.DataFrame(columns=KEEP)
    df = df[KEEP].copy()
    for c in ["종가", "NAV", "거래량", "순자산총액"]:
        df[c] = num(df[c])
    df["일자"] = pd.to_datetime(df["일자"].astype(str), format="%Y%m%d")
    return df.dropna(subset=["종가", "NAV"])


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip().replace({"-": None, "": None}),
                         errors="coerce")


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def kst_today() -> date:
    return (datetime.utcnow() + timedelta(hours=9)).date()
