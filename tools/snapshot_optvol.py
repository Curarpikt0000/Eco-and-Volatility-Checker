#!/usr/bin/env python3
"""每日把 CBOE 期权快照写入 Notion DB_OPTVOL（幂等 upsert，一天一行）。
★偏斜与期限结构无历史源 → 只能每日累积，这个脚本就是「积累器」。
★同日重跑不会造重复行（upsert 按 Date 标题匹配）。
★拿不到的字段留 None，skip_none=True 不会覆盖已有真值。
"""
import sys, os, datetime
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")
from notion_writer import upsert, prop_num, prop_select, read_back
import external_data as ed

DB = None
for ln in open(".env"):
    if ln.startswith("DB_OPTVOL="):
        DB = ln.split("=", 1)[1].strip()
if not DB:
    print("✗ DB_OPTVOL 未配置"); raise SystemExit(1)


def pick(lst, tenor, key):
    for x in lst:
        if x.get("t") == tenor:
            return x.get(key)
    return None


def main():
    d = ed.fetch_pm_option_vol()
    print(f"fetch status={d['status']} errors={d['errors']}")
    if not str(d.get("status", "")).startswith("ok"):
        print("✗ 抓取失败，不写入（避免用空值覆盖）"); return 1

    date = d["date"]
    props = {}
    for tk in ("GLD", "SLV"):
        v = d["tickers"].get(tk)
        if not v:
            print(f"  ! {tk} 无数据，该组字段留空")
            continue
        for tenor in ("1M", "3M", "12M"):
            sk = pick(v["skew"], tenor, "skew")
            props[f"{tk}_25D偏斜_{tenor}"] = prop_num(sk)
        for tenor in ("1M", "3M", "6M", "12M", "24M"):
            atm = pick(v["term"], tenor, "atm")
            props[f"{tk}_ATM_IV_{tenor}"] = prop_num(atm)
        if v.get("shape"):
            props[f"{tk}_期限结构形态"] = prop_select(v["shape"])
    props["数据来源"] = prop_select("CBOE每日快照")

    if not props:
        print("✗ 无可写字段"); return 1

    upsert(DB, date, props, title_field="Date")
    # ★写后读回验证（项目纪律）
    chk = read_back(DB, date, "GLD_ATM_IV_1M")
    print(f"✅ 已写入 {date}，读回 GLD_ATM_IV_1M = {chk}")
    for tk in ("GLD", "SLV"):
        v = d["tickers"].get(tk)
        if v:
            print(f"   {tk} 形态={v['shape']} "
                  f"ATM1M={pick(v['term'],'1M','atm')} "
                  f"偏斜12M={pick(v['skew'],'12M','skew')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
