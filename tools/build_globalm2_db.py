#!/usr/bin/env python3
"""建 Notion DB: 全球货币供应时序 (DB_GLOBALM2) 并回填全部 367 个月。
★口径: 非官方总量, 是五大经济体自聚合折美元的构造值(字段名与说明均标明)。
★覆盖国数随时段变化 → 单列一个字段, 让人一眼看出该月由几国构成。
"""
import sys, os, time
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")
from build_notion_dbs import find_existing_db, create_db, _num_prop
from notion_writer import upsert, prop_num, prop_select, read_back
import external_data as ed

TITLE = "全球货币供应时序"
PROPS = {
    "Month": {"title": {}},
    "五国合计_万亿USD": _num_prop(),
    "同比_pct": _num_prop(),
    "加速度": _num_prop(),
    "美国M2_万亿USD": _num_prop(),
    "欧元区M3_万亿USD": _num_prop(),
    "中国M2_万亿USD": _num_prop(),
    "日本M2_万亿USD": _num_prop(),
    "英国M4_万亿USD": _num_prop(),
    "覆盖国数": _num_prop(),
    "口径": {"select": {}},
}

def main():
    existing = find_existing_db(TITLE)
    db = existing or create_db(TITLE, PROPS)
    print(("已存在 " if existing else "✅ 已创建 ") + TITLE)
    print(f"DB_GLOBALM2={db}")

    d = ed.fetch_global_money_supply()
    if not str(d.get("status", "")).startswith("ok"):
        print("✗ 抓取失败，不回填"); return 1
    ser = d["series"]
    print(f"待写 {len(ser)} 个月  {ser[0]['m']} ~ {ser[-1]['m']}")

    KM = {"US": "美国M2_万亿USD", "EZ": "欧元区M3_万亿USD", "CN": "中国M2_万亿USD",
          "JP": "日本M2_万亿USD", "GB": "英国M4_万亿USD"}
    ok = fail = 0
    for i, r in enumerate(ser, 1):
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
            upsert(db, r["m"], props, title_field="Month")
            ok += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"  ✗ {r['m']}: {type(e).__name__} {str(e)[:60]}")
        if i % 50 == 0:
            print(f"  进度 {i}/{len(ser)}  ok={ok} fail={fail}")
        time.sleep(0.12)

    print(f"\n完成: ok={ok} fail={fail} / {len(ser)}")
    chk = read_back(db, ser[-1]["m"], "五国合计_万亿USD")
    print(f"读回 {ser[-1]['m']} 合计 = {chk} (应为 {ser[-1]['total']})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
