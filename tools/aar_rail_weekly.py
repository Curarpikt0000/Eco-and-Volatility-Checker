"""AAR 美国铁路周度货运量（按 10 类商品 + 联运）抓取解析。

来源: AAR 每周三发布的 Weekly Rail Traffic PDF（wp-content/uploads/YYYY/MM/YYYY-MM-DD-railtraffic.pdf），
列表通过 WordPress 媒体库 API 发现。只取第 1 页「U.S. Rail Traffic」本周数（不含 CPKC/CN/GMXT 在美业务，AAR 口径）。

用法:
  .venv/bin/python tools/aar_rail_weekly.py --since 2021-07-01      # 批量补历史
  .venv/bin/python tools/aar_rail_weekly.py                          # 增量（只抓库里没有的周）
输出: data/aar_rail_weekly.json  {weeks: {week_end: {cat: cars,...}}, meta}
校验: 10 类之和必须 == Total Carloads（容差 0），Total Carloads + Intermodal == Total Traffic，否则该周不入库并记 rejects。
"""
import json, os, re, sys, time, urllib.request, datetime as dt

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "aar_rail_weekly.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"}
CATS = ["Chemicals", "Coal", "Farm Products excl. Grain, and Food", "Forest Products", "Grain",
        "Metallic Ores and Metals", "Motor Vehicles and Parts", "Nonmetallic Minerals",
        "Petroleum and Petroleum Products", "Other"]
MON = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                         "August", "September", "October", "November", "December"])}


def list_pdfs():
    out = {}
    for page in range(1, 40):
        u = f"https://www.aar.org/wp-json/wp/v2/media?search=railtraffic&per_page=100&page={page}&_fields=date,source_url"
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40))
        except Exception as e:
            if getattr(e, "code", None) == 400:
                break
            raise
        if not d:
            break
        for x in d:
            s = x["source_url"]
            if re.search(r"/\d{4}-\d{2}-\d{2}-railtraffic\.pdf$", s, re.I):
                out[s] = x["date"][:10]
        time.sleep(0.8)
    return sorted(out.items(), key=lambda x: x[1])


def _num(s):
    return int(s.replace(",", ""))


def parse(pdf_bytes):
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    t = doc[0].get_text()
    if "U.S. Rail Traffic" not in t:
        raise ValueError("第 1 页不是 U.S. Rail Traffic")
    m = re.search(r"Ended\s+(\w+)\s+(\d{1,2}),\s+(\d{4})", t)
    if not m:
        raise ValueError("找不到周截止日")
    wk = dt.date(int(m.group(3)), MON[m.group(1)], int(m.group(2))).isoformat()
    lines = [l.strip() for l in t.splitlines() if l.strip()]

    def after(label):
        for i, l in enumerate(lines):
            if l == label or (label.startswith("Farm") and l.startswith("Farm Products excl")):
                for j in range(i + 1, min(i + 4, len(lines))):
                    if re.fullmatch(r"[\d,]+", lines[j]):
                        return _num(lines[j])
        raise ValueError(f"找不到 {label}")
    rec = {c: after(c) for c in CATS}
    rec["Total Carloads"] = after("Total Carloads")
    rec["Intermodal"] = after("Total Intermodal Units")
    rec["Total Traffic"] = after("Total Traffic")
    if sum(rec[c] for c in CATS) != rec["Total Carloads"]:
        raise ValueError(f"10 类之和 {sum(rec[c] for c in CATS)} ≠ Total Carloads {rec['Total Carloads']}")
    if rec["Total Carloads"] + rec["Intermodal"] != rec["Total Traffic"]:
        raise ValueError("Carloads + Intermodal ≠ Total Traffic")
    return wk, rec


def _get_pdf(u):
    """★2026-10-30 修: AAR 站对部分 PDF 直链 301 跳转到 /data-center/ 网页(返回 HTML 而非 PDF),
    旧代码把 HTML 当 PDF 解析 → 「第 1 页不是 U.S. Rail Traffic」, 10-21/10-28 两期静默缺失。
    实测: 同一链接加 ?download=1 返回 200+application/pdf。先直链, 拿到的不是 %PDF 就用回退通道。"""
    b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
    if b[:5] == b"%PDF-":
        return b
    b2 = urllib.request.urlopen(urllib.request.Request(u + "?download=1", headers=UA), timeout=60).read()
    if b2[:5] != b"%PDF-":
        raise ValueError("直链与 ?download=1 均未返回 PDF(站点结构可能又变了)")
    return b2


def main():
    since = None
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    try:
        store = json.load(open(OUT))
    except Exception:
        store = {"weeks": {}, "src": {}, "rejects": {}}
    have_src = set(store.get("src", {}).values())
    pdfs = list_pdfs()
    todo = [(u, d) for u, d in pdfs if u not in have_src and (since is None or d >= since)]
    if since is None:
        todo = todo[-8:]          # 增量模式只看最近 8 份
    print(f"媒体库 {len(pdfs)} 份, 待抓 {len(todo)}")
    ok = bad = 0
    for u, d in todo:
        try:
            b = _get_pdf(u)
            wk, rec = parse(b)
            store["weeks"][wk] = rec
            store.setdefault("src", {})[wk] = u
            store.get("rejects", {}).pop(u, None)
            ok += 1
        except Exception as e:
            store.setdefault("rejects", {})[u] = f"{type(e).__name__}: {str(e)[:80]}"
            bad += 1
        time.sleep(1.2)
        if (ok + bad) % 20 == 0:
            json.dump(store, open(OUT, "w"), ensure_ascii=False, indent=0)
            print(f"  进度 {ok + bad}/{len(todo)} ok={ok} bad={bad}", flush=True)
    store["meta"] = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "weeks": len(store["weeks"]),
                     "source": "AAR Weekly Rail Traffic (U.S., excl. CPKC/CN/GMXT U.S. ops)"}
    json.dump(store, open(OUT, "w"), ensure_ascii=False, indent=0)
    print(f"完成 ok={ok} bad={bad} 共 {len(store['weeks'])} 周; 最新 {max(store['weeks']) if store['weeks'] else None}")
    if bad:
        print("拒收:", list(store["rejects"].items())[:5])


if __name__ == "__main__":
    main()
