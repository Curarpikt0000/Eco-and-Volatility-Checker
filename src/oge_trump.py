"""oge_trump.py — 川普 OGE Form 278 财务披露 fetcher。

Chao 需求(2026-08): 政要披露板块补川普真数据。

重大发现(2026-08-12 独立实测, 推翻"川普无逐笔源"旧结论):
  川普作为总统在 OGE 报 **278-T 期间交易报告(Periodic Transaction Report)**,
  这是**逐笔交易级别**(买/卖/日期/金额区间), 且 PDF 直接可下载, 无需 Request。
  同时有 **278 Annual 年度快照**(存量持仓)。

数据源(全 curl 可达, 无需浏览器):
  - OGE XPages REST API: extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest?length=20000
    返回全量 ~16600 条披露文档(JSON, 客户端过滤); 每条 type 字段内嵌 <a href> 直达 PDF。
    ★服务端不按 search 参数过滤 → 必须拿全量再本地按 name 含 'trump' 筛。
  - 文档 PDF: type 字段 href 里的 extapps2.oge.gov/.../\$FILE/xxx.pdf (直接 200)

解析(278-T 逐笔, pdfplumber; OCR 有噪音需容错):
  行格式: # 描述 sale/purchase 日期 Yes 金额区间($lo - $hi)
  ★OCR 坑: purchase→lourchaso/ourchaso; 金额内部有空格($15 001)+bullet分隔(•/·);
    公司名字母混淆(Gonoral MIiis=General Mills)。金额边界 snap 到 OGE 标准档修正。

绝不编: 拿不到标状态; PDF 解析失败标 parse_error 不虚构交易。
"""
import io
import re
import os
import json
import time
import datetime
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (EcoVolChecker research; contact research@example.com)"
HDRS = {"User-Agent": UA, "Accept": "application/json"}
OGE_API = "https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest?draw=1&start=0&length=20000"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_JSON = os.path.join(DATA_DIR, "oge_trump.json")

# OGE 标准金额档(上界), 用于把 OCR 残缺的金额 snap 回标准值
OGE_BANDS = [
    (1, 1000), (1001, 15000), (15001, 50000), (50001, 100000),
    (100001, 250000), (250001, 500000), (500001, 1000000),
    (1000001, 5000000), (5000001, 25000000), (25000001, 50000000),
    (50000001, 100000000),
]


def _fetch(url, timeout=90, as_json=False, retries=3):
    """★2026-09-02: 加指数退避重试。

    原实现是一次性请求、零重试 —— OGE 全量 API 单次响应约 7MB,
    网络抖一下整个 fetch 就失败, 政要卡当天直接标 fetch_error。
    实测该端点本身健康(http=200, 16648 条记录), 故那类失败属瞬时故障,
    不该让一次抖动吃掉当天数据。重试 3 次 (2s/4s 退避) 即可吸收。
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw) if as_json else raw
        except Exception as e:                      # noqa: BLE001 - 网络层各类异常都重试
            last = e
            if attempt < retries - 1:
                time.sleep(2 * (2 ** attempt))      # 2s, 4s
    raise last if last else RuntimeError(f"fetch failed: {url}")


def list_trump_docs():
    """拿 OGE 全量披露, 筛出川普(Trump, Donald J)的所有文档 → list[dict]。"""
    d = _fetch(OGE_API, as_json=True)
    data = d.get("data", [])
    docs = []
    for r in data:
        name = (r.get("name") or "")
        if "trump" not in name.lower():
            continue
        typ = r.get("type") or ""
        m = re.search(r"href='([^']+)'", typ)
        label = re.sub(r"<[^>]+>", "", typ).strip()
        docs.append({
            "name": name,
            "title": r.get("title", ""),
            "doc_type": label,
            "doc_date": (r.get("docDate") or "")[:10],
            "pdf_url": m.group(1) if m else None,
        })
    # 新→旧
    docs.sort(key=lambda x: x["doc_date"], reverse=True)
    return docs


def _snap_band(lo, hi):
    """把 OCR 解析出的金额区间 snap 到最近的 OGE 标准档。"""
    if lo is None:
        return None, None
    # 找 lower 最接近的标准档下界
    best = min(OGE_BANDS, key=lambda b: abs(b[0] - lo))
    return best[0], best[1]


def _parse_amount(s):
    """OCR 金额串 → (lo, hi) 整数。'$15 001 • $50,000' → (15001, 50000)。"""
    nums = re.findall(r"\$\s*[\d][\d ,]*", s)
    vals = []
    for n in nums:
        v = re.sub(r"[ ,$]", "", n)
        if v.isdigit():
            vals.append(int(v))
    if not vals:
        return None, None
    lo = vals[0]
    hi = vals[1] if len(vals) > 1 else None
    return _snap_band(lo, hi)


def _ocr_pages(pdf_bytes, dpi=200):
    """★2026-09-02 新增: 对无文字层的扫描件做 OCR。

    背景: OGE 的 278-T 近期改为纯扫描件上传 —— 34 页里除首页签名外
      文字层全空(pdfplumber/pymupdf 都提取不到), 导致逐笔交易长期为 0,
      而外层只报 fetch_error, 掩盖了"拿得到但读不了"的真相。
    实测: tesseract 5.3 @200dpi, 34 页约 67s, 能正确识别标的名/
      purchase/日期/金额区间(单页 ~30 个金额区间)。
    返回按页拼好的文本行 list; 任一依赖缺失则返回 [] (调用方自行降级)。
    """
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        return []
    lines = []
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        for pg in doc:
            pix = pg.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            t = pytesseract.image_to_string(img, lang="eng") or ""
            lines += [ln.strip() for ln in t.split("\n") if ln.strip()]
    except Exception:
        return lines          # 已 OCR 出的部分照样交出去, 不整批丢弃
    return lines


def parse_278t(pdf_bytes):
    """解析 278-T 逐笔交易 PDF → [{n, asset, direction, dir_cn, txn_date, amount_range}]。"""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        lines = []
        for pg in pdf.pages:
            t = pg.extract_text() or ""
            lines += [l.strip() for l in t.split("\n") if l.strip()]

    # ★无文字层(扫描件) → 走 OCR。判据用"可读字母数字量"而非行数:
    #   扫描件首页往往有电子签名文字, 单看行数会误判为"有文字层"。
    readable = sum(len([c for c in ln if c.isalnum()]) for ln in lines)
    if readable < 400:
        ocr_lines = _ocr_pages(pdf_bytes)
        if ocr_lines:
            lines = ocr_lines

    buy_re = re.compile(r"\b(purchas|urchas|ourchas|lourchas)", re.I)
    sell_re = re.compile(r"\bsale\b", re.I)
    date_re = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
    row_re = re.compile(r"^(\d{1,3})\s+(.+)")

    out = []
    for l in lines:
        m = row_re.match(l)
        if not m:
            continue
        body = m.group(2)
        mb = buy_re.search(body)
        ms = sell_re.search(body)
        is_buy = bool(mb)
        is_sell = bool(ms)
        if not (is_buy or is_sell):
            continue
        cut = mb or ms
        # ★交易日 = 买卖词之后的第一个日期(不是描述里的债券到期日 DUE mm/dd/yy)
        after_dir = body[cut.end():]
        d = date_re.search(after_dir)
        if not d:
            continue
        lo, hi = _parse_amount(after_dir[d.end():])
        if lo is None:
            continue
        asset = body[:cut.start()].strip(" .-")
        # ★OCR 噪声过滤: 扫描件偶有把表格竖线/空白识别成"资产名"的行
        #   (实测 635 条里 3 条, 如 '|' 或空串)。资产名少于 3 个字母数字即丢弃,
        #   宁可漏一条也不让垃圾行进入下游统计。
        if len([c for c in asset if c.isalnum()]) < 3:
            continue
        amt = f"${lo:,} - ${hi:,}" if hi else f"${lo:,}"
        out.append({
            "n": m.group(1),
            "asset": asset,
            "direction": "buy" if is_buy else "sell",
            "dir_cn": "买入" if is_buy else "卖出",
            "txn_date": d.group(1),
            "amount_range": amt,
        })
    return out


def fetch(save=True, max_278t=1):
    """抓川普最新 Annual + 最新 max_278t 份 278-T, 解析逐笔。"""
    result = {
        "as_of": datetime.date.today().isoformat(),
        "name": "Donald J Trump", "title": "总统",
        "annual": None, "transactions": [], "status": "no_data",
        "sources": [],
    }
    try:
        docs = list_trump_docs()
    except Exception as e:
        result["status"] = "fetch_error"
        result["error"] = str(e)
        if save:
            _save(result)
        return result

    result["n_docs"] = len(docs)
    annual = next((d for d in docs if "annual" in d["doc_type"].lower()), None)
    t278 = [d for d in docs if "278 transaction" in d["doc_type"].lower() and d["pdf_url"]]

    if annual:
        result["annual"] = {
            "doc_type": annual["doc_type"], "doc_date": annual["doc_date"],
            "pdf_url": annual["pdf_url"],
        }
        result["sources"].append(annual["pdf_url"])

    all_txns = []
    for doc in t278[:max_278t]:
        try:
            pdf = _fetch(doc["pdf_url"], timeout=120)
            txns = parse_278t(pdf)
            for t in txns:
                t["filing_date"] = doc["doc_date"]
            all_txns += txns
            result["sources"].append(doc["pdf_url"])
        except Exception as e:
            result.setdefault("parse_errors", []).append(
                {"url": doc["pdf_url"], "error": str(e)})

    # 交易日新→旧
    def tkey(t):
        try:
            return datetime.datetime.strptime(t["txn_date"], "%m/%d/%Y")
        except Exception:
            try:
                return datetime.datetime.strptime(t["txn_date"], "%m/%d/%y")
            except Exception:
                return datetime.datetime.min
    all_txns.sort(key=tkey, reverse=True)
    result["transactions"] = all_txns
    result["n_transactions"] = len(all_txns)
    if all_txns:
        result["status"] = "ok"
    elif annual:
        result["status"] = "annual_only"
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
    print(f"川普 OGE: status={r['status']} docs={r.get('n_docs')} txns={r.get('n_transactions')}")
    if r.get("annual"):
        print(f"  Annual: {r['annual']['doc_date']} {r['annual']['pdf_url'][:80]}")
    for t in r.get("transactions", [])[:12]:
        print(f"  {t['txn_date']:10} {t['dir_cn']:4} {t['amount_range']:26} {t['asset'][:40]}")
