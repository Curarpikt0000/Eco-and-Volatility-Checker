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
# ★2026-10-30: OGE 把接口升到 v3 (官方搜索页里写的就是 .../API.xsp/v3/rest)。v2 现在只回一个「用来允许访问 REST 服务」的 HTML 占位页,
#   所以 10-03 起每天 JSON 解析报 'Expecting value'。v3 另外把每页上限锁死为 100 条(length=20000 也只回 100), 不能再一次拉全量,
#   改为「search[value]=Trump + 分页」。参数名由实测得出: search[value] 生效; search/q/name 都被忽略(会回全库前 100 条)。
OGE_API = "https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v3/rest"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_JSON = os.path.join(DATA_DIR, "oge_trump.json")

# ★OCR 不可用的原因(由 _ocr_pages 写入, fetch 读出写进结果)。
#   None = 未尝试或一切正常; 非空 = 这次 OCR 走不了, 逐笔 0 条是**环境问题**不是"没交易"。
OCR_UNAVAILABLE_REASON = None

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
    data, start, total = [], 0, None
    while True:
        d = _fetch(f"{OGE_API}?draw=1&start={start}&length=100&search%5Bvalue%5D=Trump", as_json=True)
        page = d.get("data", [])
        if total is None:
            total = d.get("recordsFiltered", 0)
        data += page
        start += 100
        if not page or start >= total:
            break
    # ★对照自检: 搜索参数被服务端忽略时会返回「全库前 100 条」(recordsFiltered≈16794)且几乎没有 Trump → 判失败, 不当成「没有披露」
    if total is None or total > 500 or not any("trump" in (r.get("name") or "").lower() for r in data):
        raise RuntimeError(f"OGE v3 搜索未生效或无 Trump 记录(recordsFiltered={total}, 取回 {len(data)} 行)")
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
    # ★2026-10-31: RapidOCR 常把千分位逗号读成句点('$250.001-$500.000'), 且 S/s 会冒充 $ ('S100.001')。
    #   先规范: 句点夹在数字之间→逗号; 孤立的 S/s 紧跟数字→$。否则 250.001 被读成 250, snap 到 $1-$1,000(实测 144 笔错标)。
    s = re.sub(r"[Ss](?=\d{1,3}[,.]\d{3})", "$", s)
    s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", ",", s)
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
    if hi is None:
        # 单个金额 = OCR 把 '$1,001-$15,000' 读丢了前半, 剩下的是上界。按「上界最接近」选档, 不按下界。
        best = min(OGE_BANDS, key=lambda b: abs(b[1] - lo))
        return best[0], best[1]
    return _snap_band(lo, hi)


def _ocr_pages(pdf_bytes, dpi=200):
    """★2026-09-02 新增: 对无文字层的扫描件做 OCR。

    背景: OGE 的 278-T 近期改为纯扫描件上传 —— 34 页里除首页签名外
      文字层全空(pdfplumber/pymupdf 都提取不到), 导致逐笔交易长期为 0,
      而外层只报 fetch_error, 掩盖了"拿得到但读不了"的真相。
    实测: tesseract 5.3 @200dpi, 34 页约 67s, 能正确识别标的名/
      purchase/日期/金额区间(单页 ~30 个金额区间)。
    返回按页拼好的文本行 list; 任一依赖缺失则返回 [] (调用方自行降级)。

    ★2026-09-04: 原实现是**完全静默**降级 —— OCR 不可用与"这份文件真没交易"
      在外层长得一模一样(都是 0 条), 正是 AGENTS.md 里记的 P1-3 类失败。
      现改为把不可用原因记进模块级 OCR_UNAVAILABLE_REASON, 由 fetch() 写进
      result["ocr_status"], 下游/日报能区分"读不了"和"没有"。
    """
    global OCR_UNAVAILABLE_REASON
    OCR_UNAVAILABLE_REASON = None
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError as e:
        OCR_UNAVAILABLE_REASON = f"python 依赖缺失: {e}"
        return []
    # ★tesseract 是 apt 装的系统二进制, devpod 重启会被擦掉(实测 2026-09-03 15:21
    #   重启后即丢失)。pytesseract 只有真去调用时才报 TesseractNotFoundError,
    #   故这里先探一次版本, 让"环境被重置"这件事在第一时间显形。
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:                           # noqa: BLE001
        OCR_UNAVAILABLE_REASON = (
            "tesseract 二进制不可用(apt 包, devpod 重启不保留; "
            "修复: bash tools/ensure_tesseract.sh): " + str(e)[:120]
        )
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


def _ocr_pages_rapid(pdf_bytes, dpi=200):
    """★2026-10-31: RapidOCR(onnx, 纯 pip)版 OCR, 不依赖 apt 装的 tesseract(devpod 重启会丢, 本机无 sudo)。
    按 y 坐标把文本块聚成行, 行内按 x 排序。依赖缺失返回 [] 并写 OCR_UNAVAILABLE_REASON。"""
    global OCR_UNAVAILABLE_REASON
    try:
        import numpy as np
        import pymupdf
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        OCR_UNAVAILABLE_REASON = f"rapidocr 依赖缺失(pip install rapidocr-onnxruntime): {e}"
        return []
    eng = RapidOCR()
    lines = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    for pg in doc:
        pix = pg.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
        res, _ = eng(img)
        if not res:
            continue
        items = sorted((r[0][0][1], r[0][0][0], r[1]) for r in res)
        cur, last = [], None
        for y, x, t in items:
            if last is not None and abs(y - last) >= 14:
                lines.append(" ".join(tt for _, tt in sorted(cur)))
                cur = []
            cur.append((x, t)); last = y
        if cur:
            lines.append(" ".join(tt for _, tt in sorted(cur)))
    return [l.strip() for l in lines if l.strip()]


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

    buy_re = re.compile(r"\b(purchas|urchas|ourchas|lourchas|purcha[s5][eo]|purchase)", re.I)
    # ★2026-10-31: RapidOCR 常把 sale 读成 salo/sa1e/sa le(实测一份 517 笔里 44 笔卖出因此被漏)。
    #   放宽只限「s-a-(l|1|I)-(e|o|c|0)」形态 + 必须紧跟交易日期(见下 _rows_from_lines 的 date 紧随要求), 防误判描述里的词。
    sell_re = re.compile(r"\bs[a4][l1I][eoc0](?=\s+\d{1,2}[/\\1l]\d)", re.I)
    date_re = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
    row_re = re.compile(r"^(\d{1,3})\s+(.+)")

    out = _rows_from_lines(lines, buy_re, sell_re, date_re, row_re)
    # ★2026-10-31: 文字层是低质 OCR 层时(错字多), 解析会漏约一半。用 RapidOCR 重读, 取笔数更多者。
    try:
        _hint = _max_row_no(pdf_bytes)
    except Exception:  # noqa: BLE001
        _hint = None
    if _hint and len(out) < 0.9 * _hint:
        r_lines = _ocr_pages_rapid(pdf_bytes)
        if r_lines:
            out2 = _rows_from_lines(r_lines, buy_re, sell_re, date_re, row_re)
            if len(out2) > len(out):
                out = out2
    return out


def _merge_wrapped_rows(lines, dir_word):
    """OCR 把长资产名折成两行: 名称在上一行, 下一行以『序号 purchase 日期…』开头。
    把『序号 + 买卖词 + 日期』开头、且没有资产名的行, 与上一行(无序号前缀或以序号开头的名称行)拼回去。"""
    out = []
    for l in lines:
        m = re.match(r"^(\d{1,3})\s+(" + dir_word + r")\s+\d", l, re.I)
        if m and out:
            prev = out.pop()
            # 上一行是被折断的名称部分(其尾部带买卖词/金额的已是完整行, 不合并)
            if not re.search(r"\$", prev):
                out.append(f"{m.group(1)} {prev} {l[len(m.group(1)):].strip()}")
                continue
            out.append(prev)
        out.append(l)
    return out


def _fix_row_numbers(rows):
    """行首序号被 OCR 吞掉首位(106→06): 序号应随行顺序单调递增, 乱序点按『前后邻居之间』补回缺的首位。"""
    seq = [int(r["n"]) for r in rows]
    for i, r in enumerate(rows):
        prev_n = seq[i - 1] if i else 0
        next_n = seq[i + 1] if i + 1 < len(seq) else 10 ** 6
        if not (prev_n < seq[i] < next_n):
            for lead in range(1, 6):
                cand = int(f"{lead}{seq[i]}") if r["n"].startswith("0") or len(r["n"]) < 3 else None
                if cand and prev_n < cand < next_n:
                    r["n"] = str(cand); seq[i] = cand
                    break
    return rows


def _rows_from_lines(lines, buy_re, sell_re, date_re, row_re):
    lines = _merge_wrapped_rows(lines, r"purchase|purchaso|salo|sale|sa1e|ourchase|lourchase")
    out = _rows_from_lines_raw(lines, buy_re, sell_re, date_re, row_re)
    return _fix_row_numbers(out)


def _rows_from_lines_raw(lines, buy_re, sell_re, date_re, row_re):
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
            # ★2026-10-31: 行首有序号+买卖词+日期+金额, 只是资产名被 OCR 整个漏读: 笔数是真的, 保留并标明名称未读出;
            #   纯噪声行(没有序号/日期/金额)在上面早已 continue 掉, 不会走到这里。
            asset = "(名称 OCR 未读出)"
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
            # ★2026-10-30 覆盖率自检: 10-08 那份 278-T 文字层是低质 OCR 层(满是 lourchaso/8110/?026 之类错字),
            #   parse_278t 只读出 165 笔, 而文字层里可认出序号 414 笔、最大序号 517 → 漏读约一半。
            #   以「最大序号」当该份报告的总笔数下限, 算 parse_coverage; 不足 90% 就标 partial, 绝不把半份当全份。
            try:
                _nums = [int(t["n"]) for t in txns if str(t.get("n", "")).isdigit()]
                _total_hint = _max_row_no(pdf)
                _cov = round(len(_nums) / _total_hint, 3) if _total_hint else None
                result.setdefault("parse_coverage", []).append({
                    "pdf": doc["pdf_url"], "doc_date": doc["doc_date"], "parsed": len(txns),
                    "rows_in_pdf_at_least": _total_hint, "coverage": _cov})
                if _cov is not None and _cov < 0.9:
                    result["partial"] = True
            except Exception:  # noqa: BLE001
                pass
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
    # ★把 OCR 环境状态如实带出去: 0 条 + ocr_status 非空 = 读不了(环境),
    #   0 条 + ocr_status 为 None = 这份文件确实没解析出交易。两者绝不混为一谈。
    if OCR_UNAVAILABLE_REASON:
        result["ocr_status"] = OCR_UNAVAILABLE_REASON
    if all_txns:
        result["status"] = "partial" if result.get("partial") else "ok"
    elif annual:
        result["status"] = "annual_only"
    if save:
        _save(result)
    return result


def _max_row_no(pdf_bytes):
    """文字层里「行首序号」的最大值(只统计后面几行出现买卖词的序号)。取不到返回 None。"""
    import pymupdf
    mx = 0
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    for pg in doc:
        ls = [l.strip() for l in pg.get_text().split("\n")]
        for k, l in enumerate(ls):
            if re.fullmatch(r"\d{1,3}", l):
                nxt = " ".join(ls[k + 1:k + 5]).lower()
                if re.search(r"purch|urchas|ourchas|sale|\bsell", nxt):
                    mx = max(mx, int(l))
    return mx or None


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
