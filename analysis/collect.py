import sys, time, os
sys.path.insert(0, "/mnt/project-files/krx_etf")
import pandas as pd
from krx_etf_openapi import fetch_etf_day, weekdays, default_key
key = default_key()
names = ["TIGER 2차전지TOP10레버리지","TIGER 반도체TOP10레버리지","KODEX K방산TOP10레버리지","KODEX 200"]
parts=[]
for dd in weekdays("20250925","20261118"):
    df = fetch_etf_day(dd, key)
    if df.empty: continue
    parts.append(df[df["종목코드"].isin(["069500","0100K0","412570","488080"])]); df[df["종목명"].str.contains("방산")].to_csv(f"bang_{dd}.csv",index=False)
    print(dd, len(df), flush=True); time.sleep(0.15)
out = pd.concat(parts).sort_values(["종목명","일자"])
out.to_csv("raw4.csv", index=False, encoding="utf-8-sig")
print(out.groupby("종목명").size())
