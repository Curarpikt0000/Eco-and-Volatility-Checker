"""politician_disclosure.py — 政要股票交易披露 fetcher。

Chao 需求(2026-08): 政要(佩洛西/Crenshaw 等)持仓披露单独板块。
政界人物不报 13F(那是机构投资经理的), 但美国国会议员受 STOCK Act 约束必须报
Periodic Transaction Report(PTR)。众议院官方数据在 disclosures-clerk.house.gov 公开。

数据源(subagent 2026-08-12 全实测通过, 无需 OCR):
  - 年度索引 ZIP: .../public_disc/financial-pdfs/{year}FD.ZIP (含 tab 分隔 {year}FD.txt)
    索引 9 列: Prefix/Last/First/Suffix/FilingType/StateDst/Year/FilingDate/DocID
    FilingType='P' = PTR(要的); DocID 通常以 2 开头
  - PTR 明细 PDF: .../public_disc/ptr-pdfs/{Year}/{DocID}.pdf (数字版 PDF, pdfplumber 可解析)
    ★路径坑: PTR 走 ptr-pdfs/, 其它类型走 financial-pdfs/{year}/; 用错→404
    ★PTR 无配套 XML(只有 PDF)

覆盖真相(诚实):
  - Pelosi(众议院 CA11) / Crenshaw(众议院 TX02): ✅ 完全可程序化
  - Tuberville(参议员): ⚠️ 参议院走 efdsearch.senate.gov(需会话 cookie, 另建), 本模块未覆盖
  - Trump: ❌ 非国会成员无 PTR 义务, 无免费逐笔交易结构化源 → 保留占位卡片标注

绝不编: 拿不到的议员/交易标状态, 不虚构。
"""
import io
import csv
import re
import os
import json
import zipfile
import datetime
import urllib.request
import urllib.error

UA = "EcoVolChecker research (contact ANONYMIZED_EMAIL_ADDRESS_0_2)"
HDRS = {"User-Agent": UA}
ZIP_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP"
PTR_PDF = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{docid}.pdf"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_JSON = os.path.join(DATA_DIR, "politician_disclosure.json")

# 追踪的众议院议员(Last + StateDst 精确匹配, 比 First 稳)
HOUSE_TARGETS = [
    {"name": "Nancy Pelosi", "last": "Pelosi", "state_dst": "CA11",
     "title": "众议院议员 (加州 · 前议长)"},
    {"name": "Dan Crenshaw", "last": "Crenshaw", "state_dst": "TX02",
     "title": "众议院议员 (德州)"},
]

# 无免费逐笔交易源的政要 → 占位卡片(诚实标注)
NO_FREE_SOURCE = [
    {"name": "Donald Trump", "title": "总统",
     "note": "非国会成员, 无 STOCK Act PTR 义务; 仅 OGE Form 278e 年度披露(非交易级), 无免费逐笔交易结构化源"},
    {"name": "Tommy Tuberville", "title": "参议员 (阿拉巴马)",
     "note": "参议员披露在 efdsearch.senate.gov(需会话 cookie), 本模块未覆盖; 待后续接入"},
]


def _fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_index(year):
    """下载某年 FD.ZIP, 解析 tab 分隔索引 → list[dict]。"""
    raw = _fetch(ZIP_URL.format(year=year))
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(f"{year}FD.txt") as f:
            text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text, delimiter="\t"))


def find_ptrs(year, last, state_dst=""):
    """在某年索引里找指定议员的 PTR filing。"""
    out = []
    for row in load_index(year):
        if row.get("FilingType") != "P":
            continue
        if row.get("Last", "").strip().lower() != last.lower():
            continue
        if state_dst and row.get("StateDst", "").strip().upper() != state_dst.upper():
            continue
        out.append({
            "name": f"{row['First']} {row['Last']}".strip(),
            "state_dst": row.get("StateDst", ""),
            "filing_date": row.get("FilingDate", ""),
            "year": row.get("Year", ""),
            "doc_id": row.get("DocID", ""),
            "pdf_url": PTR_PDF.format(year=row["Year"], docid=row["DocID"]),
        })
    return out


def parse_ptr_pdf(pdf_bytes):
    """解析 PTR PDF → [{ticker, direction, txn_date, amount_range, dir_cn}]。"""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    txt = txt.replace("\x00", "")
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    re_l1 = re.compile(
        r"(?P<dir>S \(partial\)|P \(partial\)|E \(partial\)|[PSE])\s+"
        r"(?P<txn>\d{2}/\d{2}/\d{4})\s+\d{2}/\d{2}/\d{4}\s+"
        r"(?P<lo>\$[\d,]+)\s*-\s*(?P<hi>\$[\d,]+)?\s*$")
    re_tk = re.compile(r"\(([A-Z][A-Z\.]{0,5})\)(?=\s*(?:\[[A-Z]{2}\]|$|\s))")
    dir_map = {"P": "买入", "S": "卖出", "E": "行权",
               "S (partial)": "部分卖出", "P (partial)": "部分买入", "E (partial)": "部分行权"}
    out = []
    for i, l in enumerate(lines):
        m = re_l1.search(l)
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        tks = re_tk.findall(l + " " + nxt)
        hi = m["hi"]
        if not hi:
            amts = re.findall(r"\$[\d,]+", nxt)
            hi = amts[-1] if amts else None
        d = m["dir"].strip()
        out.append({
            "ticker": tks[0] if tks else None,
            "direction": d,
            "dir_cn": dir_map.get(d, d),
            "txn_date": m["txn"],
            "amount_range": f"{m['lo']} - {hi}" if hi else m["lo"],
        })
    return out


def fetch_politician(target, years=None):
    """抓一个议员最近的 PTR + 解析明细。years 默认当年和去年。"""
    if years is None:
        y = datetime.date.today().year
        years = [y, y - 1]
    all_ptrs = []
    for yr in years:
        try:
            all_ptrs += find_ptrs(yr, target["last"], target.get("state_dst", ""))
        except urllib.error.HTTPError as e:
            print(f"  [{target['name']} {yr}] 索引 HTTP {e.code}")
        except Exception as e:
            print(f"  [{target['name']} {yr}] 索引失败: {e}")
    # 按 filing_date 新→旧, 取最近 3 份
    def dkey(p):
        try:
            return datetime.datetime.strptime(p["filing_date"], "%m/%d/%Y")
        except Exception:
            return datetime.datetime.min
    all_ptrs.sort(key=dkey, reverse=True)
    recent = all_ptrs[:3]
    trades = []
    for p in recent:
        try:
            pdf = _fetch(p["pdf_url"])
            tr = parse_ptr_pdf(pdf)
            for t in tr:
                t["filing_date"] = p["filing_date"]
                t["doc_id"] = p["doc_id"]
            trades += tr
        except Exception as e:
            print(f"  [{target['name']}] PTR {p['doc_id']} 解析失败: {e}")
    # 按交易日新→旧
    def tkey(t):
        try:
            return datetime.datetime.strptime(t["txn_date"], "%m/%d/%Y")
        except Exception:
            return datetime.datetime.min
    trades.sort(key=tkey, reverse=True)
    return {
        "name": target["name"], "title": target["title"],
        "n_filings": len(all_ptrs), "n_recent_parsed": len(recent),
        "trades": trades[:15],  # 最近 15 笔
        "status": "ok" if trades else ("no_trades" if all_ptrs else "no_filings"),
    }


def fetch_all(save=True):
    """抓所有追踪政要。"""
    result = {"as_of": datetime.date.today().isoformat(), "politicians": []}
    for t in HOUSE_TARGETS:
        print(f"[政要] 抓 {t['name']}...", flush=True)
        result["politicians"].append(fetch_politician(t))
    # 无源政要占位
    for t in NO_FREE_SOURCE:
        result["politicians"].append({
            "name": t["name"], "title": t["title"], "status": "no_free_source",
            "note": t["note"], "trades": [],
        })
    if save:
        os.makedirs(DATA_DIR, exist_ok=True)
        json.dump(result, open(OUT_JSON, "w"), ensure_ascii=False, indent=2)
        print(f"[政要] 保存 {OUT_JSON}")
    return result


def load_disclosure():
    if os.path.exists(OUT_JSON):
        return json.load(open(OUT_JSON))
    return {"as_of": None, "politicians": []}


if __name__ == "__main__":
    r = fetch_all()
    for p in r["politicians"]:
        print(f"\n=== {p['name']} ({p['title']}) status={p['status']} ===")
        for t in p.get("trades", [])[:8]:
            print(f"  {t['txn_date']} {t['dir_cn']:6} {t.get('ticker') or '(无代码)':8} {t['amount_range']}")
        if p.get("note"):
            print(f"  注: {p['note']}")
