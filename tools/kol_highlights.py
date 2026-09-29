#!/usr/bin/env python3
"""KOL 新言论摘录 —— 供日报「KOL 当日精彩言论」段与临时周度汇总使用。

★2026-09-29 立（Chao：「每天日报加入一部分，KOL 当天的所有精彩言论」）。

为什么不能直接读 kol_independent.json：
  全量抓取每天给 153 人都写一条，但多数人当天并没有新发言，子 agent 会把几周前的旧文章
  再总结一遍。直接列出来就是「把旧话当新话」。本脚本只挑**出处日期在窗口内**的观点。

判定（全部机械，不调 LLM）：
  1. 从 kol_store 取 date >= since 的观点，同一人同一句 comments 去重；
  2. 「新」= sources 里最新的出处日期 >= since（只有月份如 2026-09 的算「日期不明」，不收）；
  3. 出处日期晚于今天的(明显写错)丢弃并在 stderr 报数；
  4. detail_status == none 或方向为「未找到」的不收；
  5. 同一人窗口内多条，保留出处最新的 N 条(默认 2)。

用法:
  .venv/bin/python tools/kol_highlights.py                 # 默认 since=上一个交易日
  .venv/bin/python tools/kol_highlights.py --since 2026-09-21 --per-kol 2 --format md
  --format json 供程序用；md 供直接贴进日报。
"""
import argparse
import collections
import datetime as dt
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "kol_store.sqlite")


def prev_weekday(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def load(since, today, per_kol):
    c = sqlite3.connect(DB)
    rows = c.execute(
        "select kol_name, sector, date, direction, comments, targets, detail, detail_status, sources_json "
        "from opinion where date >= ? order by kol_name, date", (since,)).fetchall()
    by = collections.defaultdict(dict)
    future = 0
    for name, sec, d, di, cm, tg, de, st, sj in rows:
        cm = (cm or "").strip()
        if not cm or st == "none" or "未找到" in (di or ""):
            continue
        try:
            srcs = json.loads(sj or "[]")
        except Exception:  # noqa: BLE001
            srcs = []
        ds = [(s.get("date") or "")[:10] for s in srcs]
        full = [x for x in ds if len(x) == 10]
        if not full:
            continue
        sd = max(full)
        if sd > today:
            future += 1
            continue
        if sd < since:
            continue
        src = next((s for s in srcs if (s.get("date") or "")[:10] == sd), srcs[0] if srcs else {})
        by[name][cm] = dict(kol=name.split("（")[0], sector=sec or "其他", src_date=sd, direction=di or "",
                            comments=cm, targets=(tg or "").strip(), detail=de or "", status=st or "",
                            url=src.get("url", ""), title=src.get("title", ""))
    out = []
    for name, m in by.items():
        v = sorted(m.values(), key=lambda o: o["src_date"], reverse=True)[:per_kol]
        out.extend(v)
    if future:
        print(f"[kol_highlights] 丢弃出处日期晚于今天的 {future} 条", file=sys.stderr)
    return out


def to_md(items, since, today):
    secs = collections.defaultdict(list)
    for o in items:
        secs[o["sector"]].append(o)
    n_kol = len({o["kol"] for o in items})
    lines = [f"KOL 新言论（出处日期 {since} ~ {today}）：{n_kol} 人 / {len(items)} 条"]
    for s, v in sorted(secs.items(), key=lambda x: -len(x[1])):
        lines.append(f"\n【{s}】")
        for o in sorted(v, key=lambda o: o["src_date"], reverse=True):
            t = f"｜点位：{o['targets']}" if o["targets"] and "未给出" not in o["targets"] else ""
            thin = "（公开信息有限）" if o["status"] == "thin" else ""
            lines.append(f"- {o['kol']}（{o['src_date'][5:]}，{o['direction'][:12]}）{o['comments']}{t}{thin}"
                         + (f" [出处]({o['url']})" if o["url"] else ""))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    today = dt.date.today()
    ap.add_argument("--since", default=prev_weekday(today).isoformat())
    ap.add_argument("--today", default=today.isoformat())
    ap.add_argument("--per-kol", type=int, default=2)
    ap.add_argument("--format", choices=["md", "json"], default="md")
    a = ap.parse_args()
    items = load(a.since, a.today, a.per_kol)
    if a.format == "json":
        print(json.dumps(items, ensure_ascii=False, indent=1))
    else:
        print(to_md(items, a.since, a.today))


if __name__ == "__main__":
    main()
