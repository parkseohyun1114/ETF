"""괴리율 경보기의 분석 엔진.

정의 (기말 프로젝트 보고서와 동일)
  괴리율 d(%) = (종가 - NAV) / NAV * 100
  Z = (오늘 d - 직전 20거래일 d 평균) / 직전 20거래일 d 표준편차   ← 오늘 값은 기준에 넣지 않음
  위험일 = Z > 2 이고 d > 0  (평소보다 유난히 비싸게 거래된 날)
  위험일 이후 1·5·20거래일 동안 괴리율이 얼마나 되돌아오는지(회귀)를 본다.
"""
from __future__ import annotations

import os
from datetime import timedelta

import numpy as np
import pandas as pd

from krx_api import fetch_day, weekdays, kst_today, KRXError

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "etf_daily.parquet")
WINDOW = 20
Z_TH = 2.0
H = [1, 5, 20]


# ---------------------------------------------------------------- 데이터
def load_cache() -> pd.DataFrame:
    if os.path.exists(DATA):
        return pd.read_parquet(DATA)
    return pd.DataFrame(columns=["일자", "종목코드", "종목명", "종가", "NAV", "거래량", "순자산총액"])


def update_cache(df: pd.DataFrame, key: str | None, max_days: int = 40, progress=None):
    """캐시 마지막 날 다음 날부터 최근 거래일까지 KRX에서 새로 받아 붙인다.
    반환: (데이터, 새로 받은 거래일 목록, 오류 메시지 또는 None)"""
    if not key:
        import krx_api
        why = krx_api.KEY_PROBLEM or "KRX 인증키가 없어요."
        return df, [], f"{why} 저장된 데이터로 실행합니다."
    today = kst_today()
    last = df["일자"].max().date() if len(df) else today - timedelta(days=400)
    days = list(weekdays(last + timedelta(days=1), today))[-max_days:]
    new, got = [], []
    try:
        for i, d in enumerate(days):
            if progress:
                progress(i, len(days), d)
            x = fetch_day(d.strftime("%Y%m%d"), key)
            if len(x):           # 휴장일·아직 미집계(당일 장중)면 비어 있음
                new.append(x)
                got.append(d)
    except Exception as e:   # 네트워크·인증 등 어떤 오류든 앱은 저장 데이터로 계속 돈다
        return _append(df, new), got, f"KRX 호출 실패({type(e).__name__}: {str(e)[:120]}) 저장된 데이터로 실행합니다."
    df = _append(df, new)
    if new:
        try:
            df.to_parquet(DATA, index=False)
        except OSError:
            pass
    return df, got, None


def _append(df, new):
    if not new:
        return df
    out = pd.concat([df] + new, ignore_index=True)
    return out.drop_duplicates(["일자", "종목코드"], keep="last").sort_values(["종목코드", "일자"]).reset_index(drop=True)


# ---------------------------------------------------------------- 지표
def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """종목별로 괴리율, 20일 기준선, Z, 위험일, 1·5·20일 뒤 변화를 붙인다."""
    df = df.dropna(subset=["종가", "NAV"])
    df = df[df["NAV"] > 0].sort_values(["종목코드", "일자"]).reset_index(drop=True)
    df["괴리율"] = (df["종가"] - df["NAV"]) / df["NAV"] * 100
    g = df.groupby("종목코드", sort=False)["괴리율"]
    prev = g.shift(1)
    roll = prev.groupby(df["종목코드"], sort=False).rolling(WINDOW, min_periods=WINDOW)
    df["기준평균"] = roll.mean().reset_index(level=0, drop=True)
    df["기준표준편차"] = roll.std(ddof=1).reset_index(level=0, drop=True)
    sd = df["기준표준편차"].where(df["기준표준편차"] > 1e-6)
    df["Z"] = (df["괴리율"] - df["기준평균"]) / sd
    # 가격제한폭 근처 극단일: 하루 등락이 제한폭(일반 ±30%, 2배 레버리지·인버스2X는 ±60%)의 80% 이상
    df["일수익률"] = df.groupby("종목코드", sort=False)["종가"].pct_change() * 100
    mult = np.where(df["종목명"].str.contains("레버리지|2X", regex=True), 2, 1)
    df["제한폭"] = 30.0 * mult
    df["극단일"] = df["일수익률"].abs() >= 0.8 * df["제한폭"]
    # NAV 주도형: 가격은 거의 그대로인데 NAV가 떨어져서 괴리가 생긴 날.
    # 분배금(배당) 반영·해외 시차 등으로 생길 수 있어, 가격이 튄 경보와 따로 보여준다.
    nav_r = df.groupby("종목코드", sort=False)["NAV"].pct_change() * 100
    d_chg = df["괴리율"] - g.shift(1)
    df["NAV주도"] = (nav_r < -0.2) & (-nav_r >= 0.6 * d_chg)
    # 거래가 없던 날(거래정지 등)은 가격이 멈춰 있어 괴리율이 비정상이므로 판정 제외
    tradable = df["거래량"].fillna(0) > 0
    df["위험일"] = (df["Z"] > Z_TH) & (df["괴리율"] > 0) & tradable
    for h in H:
        fut_d = g.shift(-h)
        fut_p = df.groupby("종목코드", sort=False)["종가"].shift(-h)
        fut_n = df.groupby("종목코드", sort=False)["NAV"].shift(-h)
        df[f"괴리변화{h}"] = fut_d - df["괴리율"]                                   # %p, 음수면 줄어듦
        df[f"수익률차{h}"] = ((fut_p / df["종가"] - 1) - (fut_n / df["NAV"] - 1)) * 100  # 시장가 수익률 - NAV 수익률
    return df


def is_halted(latest_row) -> bool:
    return (latest_row["거래량"] or 0) == 0


# ---------------------------------------------------------------- 화면 1: 오늘의 경보
def scan(sig: pd.DataFrame, day=None) -> pd.DataFrame:
    day = sig["일자"].max() if day is None else day
    today = sig[sig["일자"] == day]
    alarms = today[today["위험일"]].copy()
    # 각 종목의 과거(최근 1년) 위험일 성적: 5일 뒤 괴리율이 줄어든 비율
    hist = sig[(sig["일자"] < day) & (sig["일자"] >= day - pd.Timedelta(days=365)) & sig["위험일"]]
    rec = hist.dropna(subset=["괴리변화5"]).groupby("종목코드").agg(
        과거위험일=("위험일", "size"), 과거5일회복률=("괴리변화5", lambda s: (s < 0).mean() * 100))
    alarms = alarms.join(rec, on="종목코드")
    alarms["과거위험일"] = alarms["과거위험일"].fillna(0).astype(int)
    return alarms.sort_values("Z", ascending=False)


def scan_discount(sig: pd.DataFrame, day=None, min_gap=0.5) -> pd.DataFrame:
    """할인일: 평소보다 유난히 싸게 거래된 ETF (Z < -2 이고 괴리율 < -min_gap)."""
    day = sig["일자"].max() if day is None else day
    t = sig[(sig["일자"] == day) & (sig["거래량"].fillna(0) > 0)]
    return t[(t["Z"] < -Z_TH) & (t["괴리율"] <= -min_gap)].sort_values("Z")


def pooled_stats(sig: pd.DataFrame, end, days=365) -> dict:
    """전체 ETF를 합쳐서 본 위험일 이후 회귀 통계 (경보 화면의 '근거' 문장용)."""
    w = sig[(sig["일자"] <= end) & (sig["일자"] > end - pd.Timedelta(days=days))]
    r = w[w["위험일"]]
    out = {"위험일수": int(len(r)), "종목수": int(r["종목코드"].nunique())}
    for h in H:
        x = r[f"괴리변화{h}"].dropna()
        out[f"회복{h}"] = float((x < 0).mean() * 100) if len(x) else np.nan
        out[f"n{h}"] = int(len(x))
    return out


# ---------------------------------------------------------------- 화면 2: 종목 분석
def ticker_view(sig: pd.DataFrame, code: str, start, end) -> pd.DataFrame:
    t = sig[sig["종목코드"] == code]
    return t[(t["일자"] >= pd.Timestamp(start)) & (t["일자"] <= pd.Timestamp(end))].reset_index(drop=True)


def event_study(t: pd.DataFrame) -> pd.DataFrame:
    """위험일 vs 평소(Z 계산 가능한 나머지 날) 비교표."""
    from scipy import stats
    r = t[t["위험일"]]
    base = t[~t["위험일"] & t["Z"].notna()]
    rows = []
    for h in H:
        x = r[f"수익률차{h}"].dropna()
        y = base[f"수익률차{h}"].dropna()
        dd = r[f"괴리변화{h}"].dropna()
        frac = (-r[f"괴리변화{h}"] / r["괴리율"]).dropna()
        p = stats.ttest_ind(x, y, equal_var=False).pvalue if len(x) > 1 and len(y) > 1 else np.nan
        rows.append({
            "기간": f"{h}거래일 뒤",
            "표본(위험일)": len(x),
            "괴리율 줄어든 비율(%)": (dd < 0).mean() * 100 if len(dd) else np.nan,
            "괴리 해소 정도 중앙값(%)": frac.median() * 100 if len(frac) else np.nan,
            "위험일 뒤 시장-NAV 수익률차(%p)": x.mean() if len(x) else np.nan,
            "평소 시장-NAV 수익률차(%p)": y.mean() if len(y) else np.nan,
            "p값(Welch t)": p,
        })
    return pd.DataFrame(rows)


def recovery_path(t: pd.DataFrame, k_max: int = 20) -> pd.DataFrame:
    """위험일을 0일로 놓고 그 뒤 k일 괴리율의 평균 경로."""
    t = t.reset_index(drop=True)
    idx = t.index[t["위험일"]]
    rows = []
    for k in range(0, k_max + 1):
        v = [t.at[i + k, "괴리율"] for i in idx if i + k < len(t)]
        rows.append({"경과일": k, "평균 괴리율": np.mean(v) if v else np.nan, "표본": len(v)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 화면 3: 검증
SNAPSHOT = os.path.join(os.path.dirname(DATA), "check_snapshot.parquet")
REPORT = {"412570": 10, "488080": 8, "0100K0": 9}   # 결과보고서의 위험일 수 (2025-11-04~2026-11-03)


def check_krx_fields(raw: pd.DataFrame) -> pd.DataFrame:
    """KRX가 직접 공시한 값과 앱이 원자료로 다시 계산한 값을 대조한다.
    (ETF 일별매매정보 API에는 '괴리율' 필드가 없어서, 같은 응답 안의 공시 필드로
     파싱·계산 경로가 맞는지 확인하고, 괴리율 공식에 쓰는 종가·NAV의 정합성을 본다.)"""
    from krx_api import num
    p, chg, rt = num(raw["TDD_CLSPRC"]), num(raw["CMPPREVDD_PRC"]), num(raw["FLUC_RT"])
    mcap, shrs = num(raw["MKTCAP"]), num(raw["LIST_SHRS"])
    hi, lo = num(raw["TDD_HGPRC"]), num(raw["TDD_LWPRC"])
    ok = p.notna() & (p > 0) & (num(raw["ACC_TRDVOL"]) > 0)   # 거래 없는 종목은 고가·저가가 0
    checks = [
        ("등락률 = 대비 ÷ 전일종가", "KRX 공시 등락률(FLUC_RT)",
         ((chg / (p - chg) * 100).round(2) - rt).abs() <= 0.011),
        ("시가총액 = 종가 × 상장좌수", "KRX 공시 시가총액(MKTCAP)",
         ((p * shrs - mcap).abs() / mcap) <= 1e-6),
        ("저가 ≤ 종가 ≤ 고가", "KRX 공시 고가·저가",
         (lo <= p) & (p <= hi)),
    ]
    rows = []
    for name, ref, m in checks:
        m = m[ok]
        rows.append({"검증 항목(앱 계산)": name, "대조 기준": ref, "대상 ETF": int(m.notna().sum()),
                     "일치": int(m.sum()), "일치율(%)": round(m.mean() * 100, 2)})
    return pd.DataFrame(rows)


def check_report(df_raw: pd.DataFrame) -> pd.DataFrame:
    """보고서 방식(기간 안 데이터만으로 Z 계산, 첫 20일 판정 제외)으로 위험일 수 재현."""
    rows = []
    for code, exp in REPORT.items():
        x = df_raw[(df_raw["종목코드"] == code) & (df_raw["일자"] >= "2025-11-04") & (df_raw["일자"] <= "2026-11-03")]
        s = add_signals(x)
        n = int(s["위험일"].sum())
        rows.append({"종목코드": code, "종목명": s["종목명"].iloc[-1], "거래일": len(s),
                     "보고서 위험일": exp, "앱 재계산": n, "결과": "✅ 일치" if n == exp else "❌ 불일치"})
    return pd.DataFrame(rows)
