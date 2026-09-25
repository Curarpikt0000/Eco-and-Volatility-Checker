#!/usr/bin/env python3
"""回填产出入库前的硬门禁 + 入库。
门禁(每条): 日期在窗口内 / 必填字段 / direction 三选一 / source 是 http(s) URL / comments 长度 / 非简介。
可选 --verify-urls: 逐条 HEAD/GET 校验 URL 可访问(非 4xx/5xx)。
入库: apply 到 data/kol/backfill/<id>.json (增量追加, 同日同文去重) → kol_store.ingest_backfill_dir
用法:
  python3 tools/apply_full_backfill.py --check            # 只门禁报告
  python3 tools/apply_full_backfill.py --check --verify-urls
  python3 tools/apply_full_backfill.py --apply             # 门禁 + 写 backfill + 进 store
"""
import os, sys, json, glob, argparse, re, datetime as dt
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
OUT = os.path.join(BASE, "scratch", "kol_bf_full", "out")
GAP = os.path.join(BASE, "scratch", "kol_gap_full_20260925.json")
BF = os.path.join(BASE, "data", "kol", "backfill")
TAG = "full-1yr-20260925"
BIO = re.compile(r"(简介|履历|出生于|毕业于|现任.*(CEO|主席|董事)|是一位|biography|about us)", re.I)

def gate(rec, w_from, w_to):
    d = (rec.get("date") or "").strip()
    c = (rec.get("comments") or "").strip()
    s = (rec.get("source") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d): return "日期格式"
    try: dt.date.fromisoformat(d)
    except ValueError: return "日期非法"
    if not (w_from <= d <= w_to): return f"越界({d})"
    if (rec.get("direction") or "").strip() not in ("看涨", "看跌", "中性"): return "direction"
    if not re.match(r"https?://[^\s]+\.[a-z]{2,}", s, re.I): return "source 非 URL"
    if len(c) < 20: return "comments 太短"
    if BIO.search(c) and not re.search(r"(看|预测|认为|警告|判断|预计|建议)", c): return "疑似简介"
    return None

def verify_url(u):
    import requests
    try:
        r = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, stream=True)
        return r.status_code
    except Exception as e:
        return type(e).__name__

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true"); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify-urls", action="store_true")
    a = ap.parse_args()
    gap = {g["id"]: g for g in json.load(open(GAP, encoding="utf-8"))}
    files = sorted(glob.glob(os.path.join(OUT, "*.json")))
    tot = ok = 0; rej = {}; per = {}; bad_url = []
    good_by_id = {}
    for fp in files:
        kid = os.path.basename(fp)[:-5]
        if kid not in gap: rej.setdefault("id 不在清单", []).append(kid); continue
        g = gap[kid]
        try: recs = json.load(open(fp, encoding="utf-8"))
        except Exception as e: rej.setdefault(f"JSON 解析失败 {type(e).__name__}", []).append(kid); continue
        if not isinstance(recs, list): rej.setdefault("非 list", []).append(kid); continue
        good = []
        for r in recs:
            tot += 1
            why = gate(r, g["window_from"], g["window_to"])
            if why: rej.setdefault(why.split("(")[0], []).append(f"{kid}:{r.get('date')}"); continue
            if a.verify_urls:
                st = verify_url(r["source"])
                if not (isinstance(st, int) and st < 400 or st in (401, 403, 429)):
                    bad_url.append(f"{kid} {r['date']} {st} {r['source'][:90]}"); continue
            good.append(r); ok += 1
        good_by_id[kid] = good
        months = sorted({r["date"][:7] for r in good})
        per[kid] = (len(recs), len(good), len(months), len(set(months) & set(g["missing_months"])))
    print(f"文件 {len(files)}/{len(gap)} | 记录 {tot} | 通过门禁 {ok} | 拒收 {tot - ok}")
    for k, v in sorted(rej.items(), key=lambda x: -len(x[1])):
        print(f"  拒收[{k}] {len(v)}: {v[:6]}")
    if bad_url:
        print(f"  URL 打不开 {len(bad_url)}:"); [print("    ", x) for x in bad_url[:15]]
    empty = [k for k, v in per.items() if v[1] == 0]
    print(f"通过 0 条的人 {len(empty)}: {empty[:20]}")
    if not a.apply: return 0
    # ---- 写 backfill 文件(增量, 去重)
    reg = {k["id"]: k for k in json.load(open(os.path.join(BASE, "data", "kol_registry.json"), encoding="utf-8"))["kols"]}
    added = dup = 0
    for kid, good in good_by_id.items():
        if not good: continue
        fp = os.path.join(BF, f"{kid}.json")
        d = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else \
            {"kol": reg[kid]["display_name"], "sector": reg[kid].get("sector", ""),
             "backfill_date": "2026-09-25", "source_method": f"{TAG} (web_search + web_extract)",
             "count": 0, "history": []}
        hist = d.setdefault("history", [])
        seen = {(h.get("date", ""), (h.get("comments") or "")[:80]) for h in hist}
        for r in good:
            key = (r["date"], r["comments"].strip()[:80])
            if key in seen: dup += 1; continue
            seen.add(key)
            hist.append({"date": r["date"], "direction": r["direction"].strip(), "comments": r["comments"].strip(),
                         "targets": (r.get("targets") or "").strip(), "source": r["source"].strip(),
                         "detail": (r.get("detail") or "").strip()[:1200],
                         "detail_status": r.get("detail_status") or "ok", "_bf": TAG})
            added += 1
        hist.sort(key=lambda h: h.get("date", ""), reverse=True)
        d["count"] = len(hist)
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"backfill 写入: 新增 {added} | 重复跳过 {dup}")
    import kol_store as ks
    res = ks.ingest_backfill_dir()
    print("store 入库:", res)
    try:
        ks.export_json() if hasattr(ks, "export_json") else None
    except Exception as e:
        print("export 失败", type(e).__name__, e)
    return 0

if __name__ == "__main__":
    sys.exit(main())
