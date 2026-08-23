#!/usr/bin/env python3
"""给 data/kol/backfill/<id>.json 里的历史观点增量补 detail(深度摘要)。

★2026-08-22 Chao 要求: 「所有人的过去一年的都需要 backfill 如果有需要的话」。
  实测 114 个文件共 369 条历史观点, 全部只有一句 comments、无 detail。

设计要点:
- **幂等 + 可中断续跑**: 已有 detail 的条目跳过, 只处理空的。
- **每日增量**: 默认 --limit 25, 挂在 cron 步骤 3b, 约两周跑完全量, 不拖慢主流程。
- **优先补最近的**: 按 date 降序挑, 近期观点更有参考价值。
- ★**绝不编造**: 本脚本只做「挑选 + 落盘」的确定性部分, 真正的摘要由调用方
  (cron agent / 子 agent)用 web_search + web_extract 产出。脚本自身不生成任何文字。
  --dry-run 列出待补清单供 agent 处理; --apply 从 stdin 读回 agent 产出的 JSON 写盘。

用法:
  # 1) 列出今天要补的条目(agent 据此去检索)
  python3 tools/backfill_kol_detail.py --limit 25 --dry-run
  # 2) agent 检索完后, 把结果 JSON 从 stdin 灌回
  cat filled.json | python3 tools/backfill_kol_detail.py --apply
  # 3) 查看进度
  python3 tools/backfill_kol_detail.py --stat

--apply 输入格式(list): [{"file":"<id>.json","date":"YYYY-MM-DD","detail":"▸...","detail_status":"ok|thin|none","sources":[...]}]
  用 (file, date) 定位条目; 找不到就跳过并报告, 绝不新增伪造条目。
"""
import os
import sys
import json
import glob
import argparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BF_DIR = os.path.join(BASE, "data", "kol", "backfill")


def _load(fp):
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None


def iter_items(only_empty=True):
    """遍历全部历史条目。返回 [(file_basename, kol, idx, record)]。"""
    out = []
    for fp in sorted(glob.glob(os.path.join(BF_DIR, "*.json"))):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        kol = d.get("kol") or os.path.basename(fp)[:-5]
        for idx, r in enumerate(d.get("history") or []):
            if not isinstance(r, dict):
                continue
            if only_empty and (r.get("detail") or "").strip():
                continue
            out.append((os.path.basename(fp), kol, idx, r))
    return out


def cmd_stat():
    total = done = 0
    thin = none_ = 0
    for fp in sorted(glob.glob(os.path.join(BF_DIR, "*.json"))):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        for r in d.get("history") or []:
            if not isinstance(r, dict):
                continue
            total += 1
            if (r.get("detail") or "").strip():
                done += 1
                st = r.get("detail_status")
                if st == "thin":
                    thin += 1
                elif st == "none":
                    none_ += 1
    pct = (done / total * 100) if total else 0
    print(f"历史条目 {total} | 已补 detail {done} ({pct:.1f}%) | 待补 {total - done}")
    print(f"  其中 thin {thin} · none {none_}")
    return 0


def cmd_list(limit):
    """挑选待补条目(按日期降序, 最近的优先)。输出 JSON 供 agent 消费。"""
    items = iter_items(only_empty=True)
    items.sort(key=lambda x: (x[3].get("date") or ""), reverse=True)
    sel = items[:limit]
    payload = [{
        "file": f,
        "kol": kol,
        "date": r.get("date", ""),
        "direction": r.get("direction", ""),
        "comments": r.get("comments", ""),
        "targets": r.get("targets", ""),
        "source": r.get("source", ""),
    } for f, kol, _i, r in sel]
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"\n# 待补总数 {len(items)}, 本次选出 {len(sel)}", file=sys.stderr)
    return 0


def cmd_apply():
    """从 stdin 读 agent 产出的 JSON, 按 (file,date) 回填。"""
    try:
        rows = json.load(sys.stdin)
    except Exception as e:
        print(f"stdin JSON 解析失败: {e}", file=sys.stderr)
        return 1
    if not isinstance(rows, list):
        print("输入必须是 list", file=sys.stderr)
        return 1

    by_file = {}
    for r in rows:
        by_file.setdefault(r.get("file"), []).append(r)

    ok = miss = 0
    for fname, items in by_file.items():
        fp = os.path.join(BF_DIR, fname or "")
        if not fname or not os.path.exists(fp):
            print(f"⚠ 文件不存在, 跳过: {fname}", file=sys.stderr)
            miss += len(items)
            continue
        d = _load(fp)
        if not isinstance(d, dict):
            miss += len(items)
            continue
        hist = d.get("history") or []
        for it in items:
            dt = it.get("date")
            det = (it.get("detail") or "").strip()
            if not det:
                continue
            hit = False
            for r in hist:
                if isinstance(r, dict) and r.get("date") == dt and not (r.get("detail") or "").strip():
                    r["detail"] = det[:1200]
                    r["detail_status"] = it.get("detail_status") or "ok"
                    if it.get("sources"):
                        r["sources"] = it["sources"][:4]
                    ok += 1
                    hit = True
                    break
            if not hit:
                # ★找不到对应条目就跳过, 绝不新增伪造记录
                print(f"⚠ 未匹配 {fname} @ {dt}(或已有 detail), 跳过", file=sys.stderr)
                miss += 1
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"回填成功 {ok} 条, 未匹配/跳过 {miss} 条")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="列出待补条目(默认行为)")
    ap.add_argument("--apply", action="store_true", help="从 stdin 读结果回填")
    ap.add_argument("--stat", action="store_true", help="只看进度")
    a = ap.parse_args()
    if a.stat:
        return cmd_stat()
    if a.apply:
        return cmd_apply()
    return cmd_list(a.limit)


if __name__ == "__main__":
    sys.exit(main())
