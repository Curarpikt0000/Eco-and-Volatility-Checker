#!/usr/bin/env python3
"""AI 债务 CDS 快照入库(硬门禁)。Chao 2026-10-18「做」。

用法:
  python3 tools/ai_cds_ingest.py add --name Oracle --bp 288 --asof 2026-10-14 --src-name Reuters --src-url https://... --basis "S&P Global Market Intelligence" [--note ...]
  python3 tools/ai_cds_ingest.py check        # 只校验现有文件, 不写

★数据口径: 5 年期单名 CDS 利差(bp), 来自新闻转引(Reuters/CNBC 等引 S&P Global Market Intelligence 或 LSEG),
  不是可日更的付费序列; 一天最多一个读数, 没有报道的日子就是空, 绝不插值、不连线、不用昨天冒充今天。
★门禁(任一不满足直接拒收, 不写盘):
  1) name 必须在白名单(防同名/拼错); 2) bp 为数且在 5~3000 之间(排除把 % 当 bp、小数点错位);
  3) asof 为合法日期, 不晚于今天(JST), 不早于 2025-01-01; 4) src-url 必须 https 且域名不是搜索跳转页(news.google.com 等);
  5) src-name 与 basis 非空; 6) 同 (name, asof, src-name) 重复则更新而非追加(幂等);
  7) 同一 (name, asof) 若已有不同来源且数值相差 >15bp, 不拒收但标 conflict=true 并保留两条(留给人判断)。
"""
import sys, json, argparse, os, datetime, urllib.parse
from datetime import timezone, timedelta
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
F = os.path.join(ROOT, "data", "ai_cds_snapshots.json")
NAMES = {"Oracle", "CoreWeave", "SoftBank", "Nvidia", "Amazon", "Alphabet", "Meta", "Microsoft", "Broadcom", "SpaceX", "STMicroelectronics"}
BAD_HOSTS = {"news.google.com", "google.com", "www.google.com", "bing.com", "duckduckgo.com"}


def load():
    if os.path.exists(F):
        return json.load(open(F, encoding="utf-8"))
    return {"note": "5年期单名CDS(bp), 新闻转引(S&P Global Market Intelligence/LSEG 口径), 非日更付费序列; 无报道的日子为空, 不插值", "rows": []}


def gate(name, bp, asof, src_name, src_url, basis):
    errs = []
    if name not in NAMES: errs.append("name 不在白名单: %r" % name)
    try:
        v = float(bp)
        if not (5 <= v <= 3000): errs.append("bp 超出 5~3000: %s(是否把 %% 当成 bp?)" % bp)
    except Exception:
        errs.append("bp 不是数: %r" % bp)
    try:
        d = datetime.date.fromisoformat(asof)
        today = datetime.datetime.now(timezone(timedelta(hours=9))).date()
        if d > today: errs.append("asof 晚于今天(JST): %s" % asof)
        if d < datetime.date(2025, 1, 1): errs.append("asof 早于 2025-01-01: %s" % asof)
    except Exception:
        errs.append("asof 不是 YYYY-MM-DD: %r" % asof)
    u = urllib.parse.urlparse(src_url or "")
    if u.scheme != "https" or not u.netloc: errs.append("src-url 必须是 https 完整链接")
    elif u.netloc in BAD_HOSTS: errs.append("src-url 是搜索/跳转页(%s), 要原文链接" % u.netloc)
    if not (src_name or "").strip(): errs.append("src-name 为空")
    if not (basis or "").strip(): errs.append("basis(数据口径来源)为空")
    return errs


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("add")
    for k in ("name", "bp", "asof", "src-name", "src-url", "basis"): a.add_argument("--" + k, required=True)
    a.add_argument("--note", default="")
    sp.add_parser("check")
    args = ap.parse_args()
    data = load(); rows = data["rows"]
    if args.cmd == "check":
        bad = 0
        for r in rows:
            e = gate(r["name"], r["bp"], r["asof"], r["src_name"], r["src_url"], r["basis"])
            if e: bad += 1; print("✗", r["name"], r["asof"], e)
        print("共 %d 行, 不合格 %d" % (len(rows), bad)); sys.exit(1 if bad else 0)
    errs = gate(args.name, args.bp, args.asof, args.src_name, args.src_url, args.basis)
    if errs:
        print("REJECT:"); [print("  -", e) for e in errs]; sys.exit(2)
    bp = float(args.bp); bp = int(bp) if bp == int(bp) else bp
    new = {"name": args.name, "asof": args.asof, "bp": bp, "src_name": args.src_name.strip(), "src_url": args.src_url.strip(),
           "basis": args.basis.strip(), "note": args.note.strip(), "added": datetime.datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")}
    same = [i for i, r in enumerate(rows) if r["name"] == new["name"] and r["asof"] == new["asof"]]
    upd = [i for i in same if rows[i]["src_name"] == new["src_name"]]
    if upd:
        rows[upd[0]] = new; act = "UPDATE"
    else:
        for i in same:
            if abs(rows[i]["bp"] - bp) > 15: rows[i]["conflict"] = True; new["conflict"] = True
        rows.append(new); act = "ADD" + (" (conflict)" if new.get("conflict") else "")
    rows.sort(key=lambda r: (r["name"], r["asof"], r["src_name"]))
    tmp = F + ".tmp"; json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, F)
    print("%s %s %s %sbp [%s]" % (act, new["name"], new["asof"], bp, new["src_name"]))


if __name__ == "__main__":
    main()
