#!/usr/bin/env python3
"""把子 agent 产出的「快照历史条目 detail」回填进 data/kol/daily/*.json。

★2026-08-23 Chao 选 A: 全量补齐 2376 条快照历史条目的深度摘要。

背景 / 为什么不是写进 backfill:
  dashboard 的历史观点有两个来源(见 external_data.kol_full_history):
    路1 data/kol/daily/*.json   —— 每日快照, 连续同内容会被合并成 (first_date, last_date) 区间
    路2 data/kol/backfill/*.json —— 逐 KOL 历史回填(已于本日 100% 补完 detail)
  本次要补的 2376 条全部来自路1。子 agent 拿到的 date 是**区间的 last_date**,
  而快照文件是按天存的 —— 所以必须把 detail 写回「该区间覆盖的每一天」的快照,
  否则区间合并后取不到(合并时用的是最后一天的 detail)。

幂等: 已有 detail 的条目不覆盖。可重复运行。

用法:
  python3 tools/apply_snapshot_detail.py --input /tmp/sn_all.json        # 回填
  python3 tools/apply_snapshot_detail.py --stat                          # 看进度
"""
import os
import sys
import json
import glob
import argparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(BASE, "data", "kol", "daily")


def _load(fp):
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None


def cmd_stat():
    tot = done = 0
    for fp in sorted(glob.glob(os.path.join(DAILY, "*.json"))):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        for r in d.get("kols") or []:
            if not (r.get("comments") or "").strip():
                continue
            tot += 1
            if (r.get("detail") or "").strip():
                done += 1
    pct = done / tot * 100 if tot else 0
    print(f"快照条目(含 comments) {tot} | 已有 detail {done} ({pct:.1f}%) | 待补 {tot - done}")
    return 0


def cmd_apply(path):
    rows = json.load(open(path, encoding="utf-8"))
    print(f"输入 {len(rows)} 条")

    # ★★2026-08-23 关键修正(第一版有严重 bug, 已回滚重写):
    #   第一版按「(kol, 日期就近) 回溯区间」贴 detail —— 实测把 972 条**不同观点**
    #   错配上了别的日期的摘要(如 12-18 的观点被贴上 2026-04-08 的摘要)。这是伪造。
    #   正解: **只按 (kol, comments 全文) 精确匹配**。同一条观点横跨多天快照时,
    #   各天的 comments 字符串本来就完全相同 —— 用内容当键天然覆盖整个区间,
    #   且绝不可能贴错到另一条观点上。日期只作为辅助校验, 不参与匹配决策。
    idx = {}
    for r in rows:
        k = r.get("kol")
        det = (r.get("detail") or "").strip()
        cmt = (r.get("comments") or "").strip()
        if k and det and cmt:
            idx[(k, cmt)] = {"d": det, "s": r.get("detail_status") or "ok"}
    print(f"有效条目(按 kol+comments 去重) {len(idx)}")
    if not idx:
        print("⚠ 输入缺少 comments 字段, 无法安全匹配 —— 拒绝回填(不按日期猜)", file=sys.stderr)
        return 1

    written = skipped = unmatched = 0
    for fp in sorted(glob.glob(os.path.join(DAILY, "*.json"))):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        changed = False
        for r in d.get("kols") or []:
            kol = r.get("kol")
            cmt = (r.get("comments") or "").strip()
            if not kol or not cmt:
                continue
            if (r.get("detail") or "").strip():
                skipped += 1
                continue                       # 幂等: 不覆盖已有
            hit = idx.get((kol, cmt))          # ★只认内容精确一致
            if hit:
                r["detail"] = hit["d"][:1200]
                r["detail_status"] = hit["s"]
                written += 1
                changed = True
            else:
                unmatched += 1
        if changed:
            json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"回填 {written} 条 | 跳过(已有) {skipped} | 未匹配(保持空白, 不猜) {unmatched}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--stat", action="store_true")
    a = ap.parse_args()
    if a.stat:
        return cmd_stat()
    if not a.input:
        print("需要 --input <json> 或 --stat", file=sys.stderr)
        return 1
    return cmd_apply(a.input)


if __name__ == "__main__":
    sys.exit(main())
