"""전략 실험: 기존 위험일 엔진(core.add_signals) 위에서 돌리는 세 가지 분석.

1) 매수 타이밍: 위험일에 바로 사지 않고 기다리면 프리미엄(괴리율)을 얼마나 덜 내나
2) 할인일 역발상: Z < -2 할인일에 사서 괴리가 회복되면 파는 평균회귀 전략
3) 민감도: Z 기준 × 기준선 창 길이를 바꿔도 결론이 유지되는가

성과는 모두 'NAV 대비'로 잰다. 시장 전체가 오르내린 효과(NAV 수익률)를 빼고,
괴리 때문에 생긴 이득·손해만 보기 위해서다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import core

COST = 0.10   # 왕복 거래비용 가정(%p): 수수료 약 0.03% + 호가 차이 0.07%. 보수적으로 잡은 가정값.
MAX_WAIT = 5  # 기다리는 최대 거래일
MAX_HOLD = 10 # 할인일 전략 최대 보유 거래일


def _by_code(sig):
    for code, t in sig.groupby("종목코드", sort=False):
        yield code, t.reset_index(drop=True)


def timing_backtest(sig: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """위험일마다 세 가지 매수 방법의 '낸 프리미엄(매수 시점 괴리율)'을 비교한다.
    바로 매수 = 위험일 종가 / 1일 대기 = 다음 거래일 종가 / 정상화 대기 = Z < 1 이 되는 첫날(최대 5일).
    절약(%p) = 위험일 괴리율 − 실제 매수일 괴리율. 양수면 프리미엄을 그만큼 덜 냈다는 뜻."""
    rows = []
    for code, t in _by_code(sig):
        idx = t.index[t["위험일"]]
        for i in idx:
            day = t.at[i, "일자"]
            if (start is not None and day < pd.Timestamp(start)) or (end is not None and day > pd.Timestamp(end)):
                continue
            if i + 1 >= len(t):
                continue
            d0 = t.at[i, "괴리율"]
            j = i + 1
            while j < len(t) - 1 and j - i < MAX_WAIT and not (t.at[j, "Z"] < 1):
                j += 1
            rows.append({"종목코드": code, "종목명": t.at[i, "종목명"], "일자": day, "위험일 괴리율": d0,
                         "1일 대기 괴리율": t.at[i + 1, "괴리율"], "정상화 대기 괴리율": t.at[j, "괴리율"],
                         "대기일": j - i})
    df = pd.DataFrame(rows)
    if len(df):
        df["1일 대기 절약"] = df["위험일 괴리율"] - df["1일 대기 괴리율"]
        df["정상화 대기 절약"] = df["위험일 괴리율"] - df["정상화 대기 괴리율"]
    return df


def summarize_timing(bt: pd.DataFrame) -> dict:
    if bt.empty:
        return {"n": 0}
    return {"n": len(bt),
            "절약1": bt["1일 대기 절약"].mean(), "유리1": (bt["1일 대기 절약"] > 0).mean() * 100,
            "절약N": bt["정상화 대기 절약"].mean(), "유리N": (bt["정상화 대기 절약"] > 0).mean() * 100,
            "대기일": bt["대기일"].mean()}


def discount_strategy(sig: pd.DataFrame, start=None, end=None, min_gap=0.0, lag: int = 0) -> pd.DataFrame:
    """할인일(Z < -2, 괴리율 < -min_gap)에 종가 매수 → 괴리율이 20일 평균 이상으로 돌아오면 매도(최대 10일).
    겹치는 매매는 하지 않는다(보유 중이면 새 신호 무시).
    lag=0: 할인일 종가에 매수(장중 실시간 iNAV로 괴리를 보고 마감 전에 산다는 가정)
    lag=1: 다음 거래일 종가에 매수(장 마감 뒤 확정 NAV를 보고 다음 날 산다는 보수적 가정)
    초과수익(%p) = 시장가 수익률 − NAV 수익률 = 괴리 회복으로 번 몫. 순초과수익 = 초과수익 − 거래비용."""
    rows = []
    for code, t in _by_code(sig):
        sig_mask = (t["Z"] < -core.Z_TH) & (t["괴리율"] < -min_gap) & (t["거래량"].fillna(0) > 0)
        i, n = 0, len(t)
        while i < n - 1:
            day = t.at[i, "일자"]
            in_rng = (start is None or day >= pd.Timestamp(start)) and (end is None or day <= pd.Timestamp(end))
            if not (sig_mask.iat[i] and in_rng):
                i += 1
                continue
            b = i + lag
            if b >= n - 1:
                break
            j = b + 1
            while j < n - 1 and j - b < MAX_HOLD and not (t.at[j, "괴리율"] >= t.at[i, "기준평균"]):
                j += 1
            p0, p1, n0, n1 = t.at[b, "종가"], t.at[j, "종가"], t.at[b, "NAV"], t.at[j, "NAV"]
            ret = (p1 / p0 - 1) * 100
            nav = (n1 / n0 - 1) * 100
            rows.append({"종목코드": code, "종목명": t.at[i, "종목명"], "매수일": day, "매도일": t.at[j, "일자"],
                         "보유일": j - b, "매수 괴리율": t.at[b, "괴리율"], "매도 괴리율": t.at[j, "괴리율"],
                         "가격 수익률": ret, "NAV 수익률": nav, "초과수익": ret - nav,
                         "순초과수익": ret - nav - COST, "회복": t.at[j, "괴리율"] >= t.at[i, "기준평균"]})
            i = j + 1
    return pd.DataFrame(rows)


def summarize_discount(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0}
    return {"n": len(tr), "회복률": tr["회복"].mean() * 100, "보유일": tr["보유일"].mean(),
            "초과": tr["초과수익"].mean(), "순초과": tr["순초과수익"].mean(),
            "승률": (tr["순초과수익"] > 0).mean() * 100, "가격": tr["가격 수익률"].mean()}


def sensitivity(df_raw: pd.DataFrame, codes, start, end,
                zs=(1.5, 2.0, 2.5), windows=(10, 20, 60)) -> pd.DataFrame:
    """Z 기준 × 창 길이 격자에서 종목별 위험일 수와 위험일 뒤 괴리 축소 비율."""
    base = df_raw[df_raw["종목코드"].isin(codes)]
    rows = []
    for w in windows:
        for z in zs:
            s = core.add_signals(base, window=w, z_th=z)
            s = s[(s["일자"] >= pd.Timestamp(start)) & (s["일자"] <= pd.Timestamp(end))]
            for code in codes:
                t = s[s["종목코드"] == code]
                r = t[t["위험일"]]
                row = {"창": w, "Z": z, "종목코드": code, "종목명": t["종목명"].iloc[-1] if len(t) else code,
                       "판정일": int(t["Z"].notna().sum()), "위험일": len(r)}
                for h in core.H:
                    x = r[f"괴리변화{h}"].dropna()
                    row[f"축소{h}"] = (x < 0).mean() * 100 if len(x) else np.nan
                row["5일 수익률차"] = r["수익률차5"].mean() if len(r) else np.nan
                rows.append(row)
    return pd.DataFrame(rows)
