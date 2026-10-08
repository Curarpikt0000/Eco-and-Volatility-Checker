#!/usr/bin/env python3
"""只检测, 不抓取: 名册里过去 12 个自然月在 kol_store 覆盖不足 MIN_MONTHS 个月的 KOL。
判据与 tools/kol_new_backfill.sh 的选人段逐行一致(覆盖只算真言论, 排除「未找到」占位行; 逐月整数运算)。
默认模式: 有人要补才输出(cron 用); --all 打印完整清单(我手动做回填时用); 绝不写任何文件。"""
import datetime as dt, json, os, sqlite3, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
MINM = int(os.environ.get("KOL_BF_MIN_MONTHS", "12"))
MAXT = 2
reg = json.load(open("data/kol_registry.json", encoding="utf-8"))["kols"]
led = json.load(open("data/kol_backfill_ledger.json", encoding="utf-8")) if os.path.exists("data/kol_backfill_ledger.json") else {}
today = dt.date.today(); since = (today - dt.timedelta(days=365)).isoformat()
win, (y, m) = [], (today.year, today.month)
for _ in range(12):
    win.append(f"{y}-{m:02d}"); y, m = (y, m - 1) if m > 1 else (y - 1, 12)
win = sorted(win)
cov = {}
con = sqlite3.connect("file:data/kol_store.sqlite?mode=ro", uri=True)
for name, d in con.execute("select kol_name,date from opinion where date>=? and coalesce(direction,'')<>'未找到'", (since,)):
    cov.setdefault(name, set()).add(d[:7])
todo, capped = [], []
for k in reg:
    if not k.get("active", True):
        continue
    have = sorted(cov.get(k["display_name"], set()) & set(win))
    if len(have) >= MINM:
        continue
    tries = led.get(k["id"], {}).get("tries", 0)
    row = {"id": k["id"], "name": k.get("short_name") or k["display_name"].split("（")[0], "have": len(have), "tries": tries}
    (capped if tries >= MAXT else todo).append(row)
todo.sort(key=lambda x: (x["have"], x["id"]))
if "--all" in sys.argv:
    print(json.dumps({"window": win, "todo": todo, "tried_out": capped, "active": sum(1 for k in reg if k.get("active", True))}, ensure_ascii=False, indent=1))
elif todo:
    worst = "、".join(f"{x['name']}({x['have']}/12)" for x in todo[:8])
    print(f"新KOL回填待办：名册里 {len(todo)} 人过去 12 个月覆盖不足 {MINM} 个月（另有 {len(capped)} 人已试满 {MAXT} 次）。最缺：{worst}。"
          f"这条只检测不抓取，回话让 Hermes 做即可。")
