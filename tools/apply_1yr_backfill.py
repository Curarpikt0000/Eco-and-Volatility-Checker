#!/usr/bin/env python3
"""把「过去一年缺失窗口」的回补观点写进 data/kol/backfill/<id>.json。

★2026-08-23 Chao: 「所有人过去一年的都需要 backfill」。核查发现 88/122 人历史不足一年
  （每日快照 2025-09 才开始攒），本脚本把子 agent 检索到的缺口期观点合并进 backfill。

★★安全设计（吸取本日教训：上一次回填因匹配键选错，972 条被贴到别的观点上）：
  1. **日期硬校验**：每条记录的 date 必须落在该人的 window_from ~ window_to 内，
     越界一律拒收并报告 —— 越界意味着子 agent 把无日期内容随便标了个日期 = 伪造历史。
  2. **同日同文去重**：同一 (id, date, comments前80字) 只保留一条，重复不叠加。
  3. **不覆盖已有**：既有 history 条目一律保留，只做增量追加。
  4. **幂等**：可重复运行；再跑一次不会产生重复条目。

用法:
  python3 tools/apply_1yr_backfill.py --input scratch/kol_bf_1yr/out --gap scratch/kol_gap_1yr.json
  python3 tools/apply_1yr_backfill.py --stat        # 看当前一年覆盖率
"""
import os
import sys
import json
import glob
import argparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BF_DIR = os.path.join(BASE, "data", "kol", "backfill")
REG = os.path.join(BASE, "data", "kol_registry.json")


def _load(fp):
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None


def _id2file():
    """名册 id -> backfill 文件路径（文件名通常就是 id，但以 kol 名回退匹配）。"""
    reg = _load(REG) or {}
    out = {}
    for k in reg.get("kols", []):
        if not k.get("active"):
            continue
        kid = k.get("id")
        fp = os.path.join(BF_DIR, f"{kid}.json")
        out[kid] = (fp, k.get("display_name") or "")
    return out


def cmd_stat(y1="2025-08-23"):
    import datetime  # noqa
    m = _id2file()
    full = short = none_ = 0
    for kid, (fp, nm) in m.items():
        d = _load(fp)
        hist = (d or {}).get("history") or []
        ds = sorted(h.get("date", "") for h in hist if h.get("date"))
        if not ds:
            none_ += 1
        elif ds[0] <= y1:
            full += 1
        else:
            short += 1
    tot = len(m)
    print(f"在册 {tot} 人 | ✅满一年 {full} | ⚠️不足一年 {short} | ❌无历史 {none_}")
    print(f"覆盖率 {full/tot*100:.1f}%")
    return 0


def cmd_apply(indir, gapfile):
    gap = {g["id"]: g for g in (_load(gapfile) or [])}
    m = _id2file()

    rows = []
    for fp in sorted(glob.glob(os.path.join(indir, "*.json"))):
        x = _load(fp)
        if isinstance(x, list):
            rows += x
    print(f"读入 {len(rows)} 个人的回补结果")

    added = rejected = dup = skipped = 0
    reject_detail = []
    for r in rows:
        kid = r.get("id")
        recs = r.get("records") or []
        if not kid or kid not in m:
            skipped += len(recs)
            continue
        fp, nm = m[kid]
        g = gap.get(kid) or {}
        w_from = g.get("window_from") or "2025-08-23"
        w_to = g.get("window_to") or "2026-08-22"

        d = _load(fp)
        if not isinstance(d, dict):
            # 该人此前完全无 backfill 文件 → 新建骨架
            d = {"kol": nm, "sector": "", "backfill_date": "2026-08-23",
                 "source_method": "1yr gap backfill (web_search + web_extract)",
                 "count": 0, "history": []}
        hist = d.setdefault("history", [])
        seen = {(h.get("date", ""), (h.get("comments") or "")[:80]) for h in hist}

        for rec in recs:
            dt = (rec.get("date") or "").strip()
            cmt = (rec.get("comments") or "").strip()
            if not dt or not cmt:
                rejected += 1
                reject_detail.append((kid, dt, "缺date或comments"))
                continue
            # ★日期硬校验：必须落在缺口窗口内
            if not (w_from <= dt <= w_to):
                rejected += 1
                reject_detail.append((kid, dt, f"越界(窗口 {w_from}~{w_to})"))
                continue
            key = (dt, cmt[:80])
            if key in seen:
                dup += 1
                continue
            seen.add(key)
            hist.append({
                "date": dt,
                "direction": (rec.get("direction") or "").strip(),
                "comments": cmt,
                "targets": (rec.get("targets") or "").strip(),
                "source": (rec.get("source") or "").strip(),
                "detail": (rec.get("detail") or "").strip()[:1200],
                "detail_status": rec.get("detail_status") or "ok",
                "_bf": "1yr-gap-20260823",
            })
            added += 1

        hist.sort(key=lambda h: h.get("date", ""), reverse=True)
        d["count"] = len(hist)
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"新增 {added} 条 | 重复跳过 {dup} | ★日期越界拒收 {rejected} | 名册外跳过 {skipped}")
    if reject_detail:
        print("拒收明细(前 12 条):")
        for x in reject_detail[:12]:
            print("   ", x)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--gap", default=os.path.join(BASE, "scratch", "kol_gap_1yr.json"))
    ap.add_argument("--stat", action="store_true")
    a = ap.parse_args()
    if a.stat:
        return cmd_stat()
    if not a.input:
        print("需要 --input <目录> 或 --stat", file=sys.stderr)
        return 1
    return cmd_apply(a.input, a.gap)


if __name__ == "__main__":
    sys.exit(main())
