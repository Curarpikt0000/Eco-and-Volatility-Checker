#!/usr/bin/env python3
"""Chao 2026-09-25 指令: KOL List #138-#142「KOL / 机构」改为「人名（机构备注）」。
新名直接取另一 agent「KOL By Day」已在用的同人选项(两表一致), 不自造。
流程: 备份旧值 → PATCH → 读回逐字比对。--apply 才写。
"""
import json, sys, urllib.request
from datetime import datetime
B = "/home/user/Projects/Eco-and-Volatility-Checker"
APPLY = "--apply" in sys.argv
tok = [l.split("=", 1)[1].strip().strip('"').strip("'") for l in open(f"{B}/.env", encoding="utf-8") if l.startswith("NOTION_TOKEN=")][0]
H = {"Authorization": f"Bearer {tok}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
def api(url, body=None, method="GET"):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=H, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

ROWS = {  # 编号: (page_id, 人名关键词, 多选项时的偏好子串)
    "138": ("3df47eb5-fd3c-81bd-9de8-e7bde1660145", "McAlvany", "主讲"),
    "139": ("3e047eb5-fd3c-812b-851c-ddafbe0f9c28", "Rupal Bhansali", None),
    "140": ("3e047eb5-fd3c-81e1-b20a-f7230bcd3942", "Gerald Celente", None),
    "141": ("3e047eb5-fd3c-8128-bd98-e428ce849a48", "Egon von Greyerz", None),
    "142": ("3e047eb5-fd3c-8147-bed6-e85c39bb2f56", "Bill Holter", None),
}
PAGE = "31447eb5fd3c8064a531c43b177cdc41"
kids = api(f"https://api.notion.com/v1/blocks/{PAGE}/children?page_size=100")["results"]
byday = [k["id"] for k in kids if k["type"] == "child_database" and k["child_database"]["title"] == "KOL By Day"][0]
opts = [o["name"] for o in api(f"https://api.notion.com/v1/databases/{byday}")["properties"]["Name of KOL"]["select"]["options"]]

plan = []
for num, (pid, key, pref) in ROWS.items():
    cands = sorted(set(o for o in opts if o.startswith(key) or (key == "McAlvany" and o.startswith("David McAlvany"))))
    if pref:
        cands = [c for c in cands if pref in c] or cands
    if len(cands) != 1:
        raise SystemExit(f"#{num} {key}: 候选 {len(cands)} 个, 停止 {cands}")
    page = api(f"https://api.notion.com/v1/pages/{pid}")
    assert page["parent"].get("database_id", "").replace("-", "") == "35947eb5fd3c800db852cef31f9de6a5"
    num_real = "".join(x["plain_text"] for x in page["properties"]["编号"]["title"])
    assert num_real == num, (num, num_real)
    old = "".join(x["plain_text"] for x in page["properties"]["KOL / 机构"]["rich_text"])
    plan.append((num, pid, old, cands[0]))

for num, pid, old, new in plan:
    print(f"#{num} {pid}\n   旧: {old[:70]}\n   新: {new}")
if not APPLY:
    print("\n[预演] 加 --apply 写入"); sys.exit(0)

bak = f"{B}/data/notion_kol_rename_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
json.dump([{"num": n, "page_id": p, "old": o, "new": w} for n, p, o, w in plan], open(bak, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n备份旧值: {bak}")
ok = 0
for num, pid, old, new in plan:
    api(f"https://api.notion.com/v1/pages/{pid}", {"properties": {"KOL / 机构": {"rich_text": [{"type": "text", "text": {"content": new}}]}}}, "PATCH")
    back = "".join(x["plain_text"] for x in api(f"https://api.notion.com/v1/pages/{pid}")["properties"]["KOL / 机构"]["rich_text"])
    good = back == new
    ok += good
    print(f"  #{num} 读回{'一致 ✅' if good else '不一致 ❌ ' + back[:60]}")
print(f"读回 {ok}/{len(plan)}")
