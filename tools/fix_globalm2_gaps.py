#!/usr/bin/env python3
"""对账并补齐 DB_GLOBALM2 缺失月份。
★日志停在 350/367 无"完成"行, DB 实际 363 行 —— 进程在尾部被中断。
★不猜, 用 set-diff 精确算出缺哪几个月(memory 教训: 长名单必用 set-diff 不用眼睛)。
"""
import sys, os, re, time
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")
from notion_writer import _req, upsert, prop_num, prop_select, read_back
import external_data as ed

DB = "3e247eb5-fd3c-8158-b5ba-f3d1990b3cfb"

# 1. 拉 DB 里已有的全部 Month
have, cur = set(), None
while True:
    p = {"page_size": 100}
    if cur:
        p["start_cursor"] = cur
    s, b = _req("POST", f"/databases/{DB}/query", p)
    if s != 200:
        print("查询失败", s); raise SystemExit(1)
    for r in b.get("results", []):
        t = r["properties"]["Month"]["title"]
        if t:
            have.add(t[0]["plain_text"])
    if not b.get("has_more"):
        break
    cur = b.get("next_cursor")
print(f"DB 现有 {len(have)} 个月")

# 2. 应有的
d = ed.fetch_global_money_supply()
ser = d["series"]
want = {r["m"] for r in ser}
print(f"应有 {len(want)} 个月")

missing = sorted(want - have)
extra = sorted(have - want)
print(f"\n★缺失 {len(missing)}: {missing}")
print(f"★多余 {len(extra)}: {extra}")

if not missing:
    print("\n无需补写")
    raise SystemExit(0)

# 3. 补写
KM = {"US": "美国M2_万亿USD", "EZ": "欧元区M3_万亿USD", "CN": "中国M2_万亿USD",
      "JP": "日本M2_万亿USD", "GB": "英国M4_万亿USD"}
by = {r["m"]: r for r in ser}
ok = fail = 0
for m in missing:
    r = by[m]
    props = {
        "五国合计_万亿USD": prop_num(r["total"]),
        "同比_pct": prop_num(r.get("yoy")),
        "加速度": prop_num(r.get("accel")),
        "覆盖国数": prop_num(r["n_cty"]),
        "口径": prop_select("五国聚合折USD(非官方总量)"),
    }
    for cc, fld in KM.items():
        props[fld] = prop_num(r["parts"].get(cc))
    try:
        upsert(DB, m, props, title_field="Month")
        ok += 1
        print(f"  ✅ {m}  合计={r['total']}")
    except Exception as e:
        fail += 1
        print(f"  ✗ {m}: {type(e).__name__} {str(e)[:70]}")
    time.sleep(0.15)

print(f"\n补写 ok={ok} fail={fail}")
print(f"读回 2026-07 合计 = "
      f"{read_back(DB, '2026-07', '五国合计_万亿USD', title_field='Month')}")
