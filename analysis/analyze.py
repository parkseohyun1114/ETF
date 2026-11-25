import pandas as pd, numpy as np, sys
from scipy import stats
df = pd.read_csv(sys.argv[1], parse_dates=["일자"])
REPORT_END = pd.Timestamp("2026-11-03")
H=[1,5,20]
rows=[]; ev_all=[]
for name,g in df.groupby("종목명"):
    g=g.sort_values("일자").reset_index(drop=True)
    g["d"]=(g["종가"]-g["NAV"])/g["NAV"]*100
    m=g["d"].shift(1).rolling(20).mean(); s=g["d"].shift(1).rolling(20).std(ddof=1)
    g["z"]=(g["d"]-m)/s
    g=g[g["일자"]>=pd.Timestamp("2025-11-04")].reset_index(drop=True)
    # report check: use only report-period rows for windows (as report did: first 20 days not judged)
    rep=g[g["일자"]<=REPORT_END].copy()
    mr=rep["d"].shift(1).rolling(20).mean(); sr=rep["d"].shift(1).rolling(20).std(ddof=1)
    zr=(rep["d"]-mr)/sr
    n_rep=int(((zr>2)&(rep["d"]>0)).sum())
    g["risk"]=(g["z"]>2)&(g["d"]>0)
    for h in H:
        g[f"dd{h}"]=g["d"].shift(-h)-g["d"]
        g[f"gap{h}"]=(g["종가"].shift(-h)/g["종가"]-1)*100-(g["NAV"].shift(-h)/g["NAV"]-1)*100
    print(f"{name}: 보고서방식(2025-11-04~2026-11-03, 첫20일 제외) 위험일={n_rep}, 판정일={zr.notna().sum()} / 전체기간 위험일={int(g['risk'].sum())}, 거래일={len(g)}, 마지막={g['일자'].max().date()}")
    g["etf"]=name; ev_all.append(g)
all_=pd.concat(ev_all)
all_.to_csv("events_full.csv",index=False,encoding="utf-8-sig")
print()
for name,g in all_.groupby("etf"):
    r=g[g.risk]; nr=g[~g.risk & g.z.notna()]
    print(f"== {name}  위험일 {len(r)}일, 위험일 평균 괴리율 {r.d.mean():.2f}% (평소 {nr.d.mean():.2f}%)")
    for h in H:
        x=r[f"gap{h}"].dropna(); y=nr[f"gap{h}"].dropna()
        rev=(r[f"dd{h}"].dropna()<0).mean()*100
        frac=(-r[f"dd{h}"]/r["d"]).dropna().median()*100
        t=stats.ttest_ind(x,y,equal_var=False).pvalue if len(x)>1 else np.nan
        mw=stats.mannwhitneyu(x,y).pvalue if len(x)>1 else np.nan
        print(f"  {h:>2}일후 n={len(x)} 시장-NAV 수익률차 평균 {x.mean():+.2f}%p (중앙 {x.median():+.2f}) vs 평소 {y.mean():+.2f}%p | 괴리율 줄어든 비율 {rev:.0f}% | 회귀정도 중앙값 {frac:.0f}% | p(t)={t:.3f} p(MW)={mw:.3f}")
