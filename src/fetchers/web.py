"""Web fetchers — 反爬源 + HTML 解析。每个函数独立 try/except，取不到返回 None。

纪律：解析失败宁可返回 None(status='未找到')，绝不编数字。
所有正则经 subagent 实测核实(2026-08-11)，对应各源真实页面结构。
"""
import re
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fetchers.util import http_get, jina_get

JINA = "https://r.jina.ai/"


def _num(s):
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s).replace(",", ""))
    return float(m.group()) if m else None


def _parse_date(s):
    import datetime
    if not s:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(s.strip().replace(",", ""), fmt.replace(",", "")).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


# ─────────── CNN Fear & Greed (内部 JSON API) ───────────
def fetch_fear_greed():
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json", "Origin": "https://www.cnn.com",
           "Referer": "https://www.cnn.com/markets/fear-and-greed"}
    st, body = http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                        headers=hdr, timeout=25, as_json=True)
    if st == 200 and isinstance(body, dict):
        fg = body.get("fear_and_greed", {})
        v = fg.get("score")
        ts = fg.get("timestamp", "")[:10]
        if v is not None:
            return {"value": round(float(v), 1), "as_of": ts, "status": "ok",
                    "extra": {"rating": fg.get("rating")}}
    return {"value": None, "as_of": None, "status": "未找到"}


def fetch_fear_greed_history(start="2025-01-01"):
    import datetime
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json", "Referer": "https://www.cnn.com/markets/fear-and-greed"}
    st, body = http_get(f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}",
                        headers=hdr, timeout=30, as_json=True)
    out = []
    if st == 200 and isinstance(body, dict):
        for pt in body.get("fear_and_greed_historical", {}).get("data", []):
            try:
                d = datetime.datetime.utcfromtimestamp(pt["x"] / 1000).strftime("%Y-%m-%d")
                out.append((d, round(float(pt["y"]), 1)))
            except Exception:
                continue
    return out


# ─────────── multpl Shiller CAPE ───────────
def fetch_cape():
    for body in (http_get("https://www.multpl.com/shiller-pe", timeout=25)[1],
                 jina_get("https://www.multpl.com/shiller-pe")):
        if body:
            m = re.search(r"Current Shiller PE Ratio is\s*([\d.]+)", body)
            if m:
                return {"value": float(m.group(1)), "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── currentmarketvaluation Buffett Indicator ───────────
def fetch_buffett():
    body = http_get("https://www.currentmarketvaluation.com/models/buffett-indicator.php", timeout=25)[1]
    if body:
        m = re.search(r"we calculate the Buffett Indicator as\s+(\d{2,3})%", body)
        if m:
            dt = re.search(r"As of\s+([A-Za-z]+ \d{1,2},? \d{4})\s+we calculate", body)
            return {"value": float(m.group(1)), "as_of": _parse_date(dt.group(1)) if dt else None,
                    "status": "ok"}
        m = re.search(r"current ratio of\s+(\d{2,3})%", body)
        if m:
            return {"value": float(m.group(1)), "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── NAAIM Exposure — 已于 2026-08-01 转付费停更 ───────────
def fetch_naaim():
    body = jina_get("https://www.naaim.org/programs/naaim-exposure-index/")
    if body and "transitioned to a subscription" in body:
        return {"value": None, "as_of": None, "status": "数据源已转付费停更(2026-08-01)"}
    if body:
        m = re.search(r"NAAIM (?:Exposure Index|Number)[^\d\-]{0,30}(-?\d{1,3}\.?\d*)", body)
        if m:
            return {"value": float(m.group(1)), "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── AAII Sentiment (Bull-Bear spread) — 官方 xls ───────────
def fetch_aaii_sentiment():
    # 公开页无当周数，用官方 sentiment.xls
    try:
        import io
        st, _ = http_get("https://www.aaii.com/files/surveys/sentiment.xls", timeout=30)
        import requests
        from fetchers.util import HEADERS
        r = requests.get("https://www.aaii.com/files/surveys/sentiment.xls",
                         headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            import openpyxl  # 可能是老 xls，退回 xlrd
            # 老 .xls 用 pandas + xlrd
            import pandas as pd
            df = pd.read_excel(io.BytesIO(r.content), skiprows=3)
            df = df.dropna(subset=[df.columns[0]])
            last = df.iloc[-1]
            bull = float(last.iloc[1]) * (100 if last.iloc[1] < 1.5 else 1)
            bear = float(last.iloc[3]) * (100 if last.iloc[3] < 1.5 else 1)
            d = last.iloc[0]
            ds = str(d)[:10] if not hasattr(d, "strftime") else d.strftime("%Y-%m-%d")
            return {"value": round(bull - bear, 1), "as_of": ds, "status": "ok",
                    "extra": {"bull": round(bull, 1), "bear": round(bear, 1)}}
    except Exception:
        pass
    # 降级 YCharts
    t = jina_get("https://ycharts.com/indicators/us_investor_sentiment_bearish")
    if t:
        mb = re.search(r"Last Value\s*\|\s*([0-9]+\.[0-9]+)%", t)
        if mb:
            return {"value": None, "as_of": None, "status": "部分(仅bearish)",
                    "extra": {"bear": float(mb.group(1))}}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── AAII Asset Allocation (stocks %) ───────────
def fetch_aaii_allocation():
    t = jina_get("https://www.aaii.com/assetallocationsurvey")
    if t:
        m = re.search(r"Stocks Total\s*([0-9]+\.[0-9]+)%", t)
        if m:
            dt = re.search(r"Asset Allocation Results for\s+([A-Za-z]+\s+[0-9]{4})", t)
            return {"value": float(m.group(1)), "as_of": _parse_date(dt.group(1)) if dt else None,
                    "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── CBOE Equity Put/Call ───────────
def fetch_put_call():
    t = jina_get("https://www.cboe.com/us/options/market_statistics/daily/")
    if t:
        m = re.search(r"EQUITY PUT/CALL RATIO\s*\|\s*([0-9]+\.[0-9]+)", t, re.I)
        if m:
            return {"value": float(m.group(1)), "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── FINRA Margin Debt (月度) ───────────
def fetch_margin_debt():
    """FINRA 月度保证金负债(十亿$)。真实表格: 'Jun-26 | 1,502,072 | ...'(百万$)。
    Jina 失败 → 回退本地 margin_debt_history.json 最新值。"""
    t = jina_get("https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics")
    if t:
        m = re.search(r"([A-Z][a-z]{2}-\d{2})\s*\|\s*([\d,]{7,})", t)
        if m:
            month, valm = m.group(1), _num(m.group(2))
            if valm and valm > 100000:
                return {"value": round(valm / 1000, 1), "as_of": _finra_month(month),
                        "status": "ok"}
    # 回退历史文件
    import os, json
    hp = os.path.join(os.path.dirname(__file__), "..", "..", "data", "margin_debt_history.json")
    if os.path.exists(hp):
        try:
            h = json.load(open(hp)).get("margin_debt", [])
            if h:
                d, v = h[-1]
                return {"value": v, "as_of": d, "status": "ok"}
        except Exception:
            pass
    return {"value": None, "as_of": None, "status": "未找到"}


def fetch_margin_debt_history():
    """从 FINRA 官方 xlsx 拉全部月度历史(供 backfill)。返回 [(YYYY-MM-DD, 十亿$),...] 升序。"""
    import io, datetime
    try:
        import requests
        from fetchers.util import HEADERS
        r = requests.get("https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
                         headers=HEADERS, timeout=40)
        if r.status_code != 200 or len(r.content) < 1000:
            return []
        import pandas as pd
        df = pd.read_excel(io.BytesIO(r.content))
        out = []
        for _, row in df.iterrows():
            # 第1列月份, 找 Debit 列
            cells = list(row.values)
            month = str(cells[0])
            # debit 通常第2列
            for c in cells[1:]:
                try:
                    v = float(str(c).replace(",", ""))
                    if v > 100000:  # 百万级
                        d = _parse_finra_any(month)
                        if d:
                            out.append((d, round(v / 1000, 1)))
                        break
                except Exception:
                    continue
        out.sort()
        return out
    except Exception:
        return []


def _finra_month(s):
    """'Jun-26' -> '2026-06-30'(月末)。"""
    import datetime, calendar
    try:
        dt = datetime.datetime.strptime(s, "%b-%y")
        last = calendar.monthrange(dt.year, dt.month)[1]
        return f"{dt.year}-{dt.month:02d}-{last:02d}"
    except Exception:
        return None


def _parse_finra_any(s):
    import datetime, calendar
    s = str(s).strip()
    for fmt in ("%b-%y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b-%Y", "%B %Y"):
        try:
            dt = datetime.datetime.strptime(s.split(" ")[0] if fmt.startswith("%Y") else s, fmt)
            last = calendar.monthrange(dt.year, dt.month)[1]
            return f"{dt.year}-{dt.month:02d}-{last:02d}"
        except Exception:
            continue
    return None


# ─────────── Renaissance IPO count ───────────
def fetch_ipo():
    body = http_get("https://www.renaissancecapital.com/IPO-Center/Stats", timeout=25)[1]
    if body:
        m = re.search(r"There have been\s*(?:<strong>)?\s*(\d+)\s*(?:</strong>)?\s*IPOs (?:priced this year|in \d{4})", body)
        if m:
            proceeds = re.search(r"Total proceeds raised were\s*(?:<strong>)?\$([\d.]+)\s*bil", body)
            extra = {"proceeds_bil": float(proceeds.group(1))} if proceeds else {}
            return {"value": float(m.group(1)), "as_of": None, "status": "ok", "extra": extra}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── GuruFocus Insider Buy/Sell ───────────
def fetch_insider():
    t = jina_get("https://www.gurufocus.com/economic_indicators/4359/insider-buysell-ratio")
    if t:
        m = re.search(r"Insider Buy/Sell Ratio[^0-9]*is currently\s*([\d.]+)", t)
        if m:
            v = float(m.group(1).rstrip("."))
            if 0 < v < 20:
                return {"value": v, "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── Conference Board LEI (月度) ───────────
def fetch_lei():
    t = jina_get("https://www.conference-board.org/topics/us-leading-indicators/")
    if t:
        # 6-month change: "LEI is down by only X% over the first half"
        m6 = re.search(r"LEI is down by only ([\d.]+)% over the first half", t)
        mlei = re.search(r"\(LEI\) for the US (?:declined|increased|fell|rose) by [\d.]+% in ([A-Za-z]+ \d{4}) to (\d{2,3}\.\d)", t)
        val6 = -float(m6.group(1)) if m6 else None
        if val6 is not None:
            extra = {}
            if mlei:
                extra = {"lei_index": float(mlei.group(2)), "month": mlei.group(1)}
            return {"value": val6, "as_of": _parse_date(mlei.group(1).replace(" ", " 1, ")) if mlei else None,
                    "status": "ok", "extra": extra}
    return {"value": None, "as_of": None, "status": "未找到"}


WEB_FETCHERS = {
    "fear_greed": fetch_fear_greed,
    "cape": fetch_cape,
    "buffett": fetch_buffett,
    "naaim": fetch_naaim,
    "aaii_bull_bear": fetch_aaii_sentiment,
    "aaii_alloc": fetch_aaii_allocation,
    "put_call": fetch_put_call,
    "margin_debt": fetch_margin_debt,
    "ipo_count": fetch_ipo,
    "insider": fetch_insider,
    "lei": fetch_lei,
}
