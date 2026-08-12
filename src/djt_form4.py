"""djt_form4.py — 川普 SEC Form 4 内部人交易 fetcher(每日 cron 扫描)。

Chao 需求(2026-08): 政要披露板块加川普 DJT(Trump Media)内部人逐笔交易。

背景: 川普是 Trump Media & Technology Group(NASDAQ: DJT)大股东/关联内部人,
  受 SEC Section 16 约束, 交易须报 **Form 4**(逐笔, 快于 278-T)。
  这是川普持有 DJT 股票的**最快逐笔信号源**(赠与/转让/买卖当日或次日报)。

数据源(SEC EDGAR 官方, 免费, 无需 key, 仅要求 UA):
  - 提交索引: data.sec.gov/submissions/CIK0000947033.json (CIK 947033 = TRUMP DONALD J)
    filings.recent 里 form=='4' 的 accessionNumber
  - 明细 XML: www.sec.gov/Archives/edgar/data/947033/<acc_nodash>/primary_doc.xml
    含 issuer(DJT) / owner / nonDerivativeTransaction(date/code/shares/price/A|D)
    transactionCode: P买 S卖 G赠与 A授予 F扣税 M行权 等

每日 cron: 扫最新 Form 4, 若有新 accession(vs 上次) → 追加交易。
绝不编: 无新交易标 no_new; XML 解析失败标 parse_error。
"""
import os
import re
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (EcoVolChecker research; contact research@example.com)"
CIK = "947033"
CIK_PADDED = "0000947033"
SUBMISSIONS = f"https://data.sec.gov/submissions/CIK{CIK_PADDED}.json"
FILING_DIR = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_JSON = os.path.join(DATA_DIR, "djt_form4.json")

CODE_CN = {
    "P": "买入", "S": "卖出", "G": "赠与", "A": "授予",
    "F": "扣税", "M": "期权行权", "C": "转换", "D": "处置", "J": "其他",
}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_form4(limit=8):
    """列川普最近的 Form 4 filing。"""
    d = json.loads(_get(SUBMISSIONS))
    r = d["filings"]["recent"]
    forms = r["form"]
    out = []
    for i, f in enumerate(forms):
        if f != "4":
            continue
        out.append({
            "accession": r["accessionNumber"][i],
            "filing_date": r["filingDate"][i],
            "acc_nodash": r["accessionNumber"][i].replace("-", ""),
        })
        if len(out) >= limit:
            break
    return out


def parse_form4(acc_nodash):
    """解析一份 Form 4 XML → {issuer, ticker, owner, txns:[...]}。"""
    url = FILING_DIR.format(cik=CIK, acc=acc_nodash)
    raw = _get(url)
    root = ET.fromstring(raw)

    def t(path):
        e = root.find(path)
        return e.text.strip() if e is not None and e.text else None

    issuer = t(".//issuerName")
    ticker = t(".//issuerTradingSymbol")
    owner = t(".//rptOwnerName")

    txns = []
    for tx in root.findall(".//nonDerivativeTransaction") + root.findall(".//derivativeTransaction"):
        sec = tx.findtext(".//securityTitle/value")
        date = tx.findtext(".//transactionDate/value")
        code = tx.findtext(".//transactionCoding/transactionCode")
        shares = tx.findtext(".//transactionAmounts/transactionShares/value")
        price = tx.findtext(".//transactionAmounts/transactionPricePerShare/value")
        ad = tx.findtext(".//transactionAmounts/transactionAcquiredDisposedCode/value")
        try:
            shares_n = float(shares) if shares else None
        except ValueError:
            shares_n = None
        txns.append({
            "security": (sec or "").strip(),
            "txn_date": date,
            "code": code,
            "code_cn": CODE_CN.get(code, code),
            "acquired_disposed": ad,
            "shares": shares_n,
            "price": float(price) if price and price != "0" else None,
        })
    return {"issuer": issuer, "ticker": ticker, "owner": owner, "txns": txns}


def fetch(save=True, max_filings=3):
    """抓最近 max_filings 份 Form 4, 解析全部交易。"""
    result = {
        "as_of": datetime.date.today().isoformat(),
        "name": "Donald J Trump", "title": "总统 (DJT 大股东/内部人)",
        "filings": [], "txns": [], "status": "no_data", "sources": [],
    }
    try:
        f4 = list_form4()
    except Exception as e:
        result["status"] = "fetch_error"
        result["error"] = str(e)
        if save:
            _save(result)
        return result

    result["n_form4_total"] = len(f4)
    for f in f4[:max_filings]:
        try:
            p = parse_form4(f["acc_nodash"])
            for tx in p["txns"]:
                tx["filing_date"] = f["filing_date"]
                tx["accession"] = f["accession"]
                tx["ticker"] = p["ticker"]
                tx["issuer"] = p["issuer"]
            result["txns"] += p["txns"]
            result["filings"].append({
                "accession": f["accession"], "filing_date": f["filing_date"],
                "issuer": p["issuer"], "ticker": p["ticker"], "n_txns": len(p["txns"]),
            })
            result["sources"].append(
                FILING_DIR.format(cik=CIK, acc=f["acc_nodash"]))
        except Exception as e:
            result.setdefault("parse_errors", []).append(
                {"accession": f["accession"], "error": str(e)})

    if result["txns"]:
        result["status"] = "ok"
    if save:
        _save(result)
    return result


def _save(result):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(result, open(OUT_JSON, "w"), ensure_ascii=False, indent=2)


def load():
    if os.path.exists(OUT_JSON):
        return json.load(open(OUT_JSON))
    return None


if __name__ == "__main__":
    r = fetch()
    print(f"DJT Form 4: status={r['status']} total_form4={r.get('n_form4_total')} txns={len(r['txns'])}")
    for tx in r["txns"][:10]:
        sh = f"{tx['shares']:,.0f}股" if tx["shares"] else "-"
        print(f"  {tx['filing_date']} {tx.get('ticker'):5} {tx['code_cn']:5} {tx['acquired_disposed']} {sh:>16} {tx['security'][:30]}")
