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


# ─────────── multpl Shiller CAPE (2026-08 改: pandas 直连,不用 Jina) ───────────
def fetch_cape():
    """Shiller CAPE。multpl.com 表格普通 UA 即 200(不需 Jina)。
    pandas.read_html 取表0第0行=最新, 带日期。失败回退旧正则/Jina。"""
    try:
        import pandas as pd
        from fetchers.util import HEADERS
        tables = pd.read_html("https://www.multpl.com/shiller-pe/table/by-month",
                              storage_options=HEADERS)
        if tables:
            df = tables[0]
            # 列 [Date, Value]; 第0行最新
            row = df.iloc[0]
            raw = str(row.iloc[1])
            v = float(re.sub(r"[^\d.]", "", raw))
            ds = _parse_date(str(row.iloc[0]))
            if 5 < v < 100:  # sanity: CAPE 合理区间
                return {"value": round(v, 2), "as_of": ds, "status": "ok"}
    except Exception:
        pass
    # 回退: 旧正则(http_get/jina)
    for body in (http_get("https://www.multpl.com/shiller-pe", timeout=25)[1],
                 jina_get("https://www.multpl.com/shiller-pe")):
        if body:
            m = re.search(r"Current Shiller PE Ratio is\s*([\d.]+)", body)
            if m:
                return {"value": float(m.group(1)), "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── Buffett Indicator (2026-08 改: FRED 纯 API 双系列算比率) ───────────
def fetch_buffett():
    """巴菲特指标=美股总市值/GDP。用 FRED Z.1 官方口径(季度,零反爬):
    NCBEILQ027S(公司股权市值,百万$) / (GDP,十亿$ ×1000) ×100。失败回退旧网页抓。"""
    try:
        from fetchers.fred import fetch_fred_latest
        mv, mv_d = fetch_fred_latest("NCBEILQ027S")   # 百万$
        gdp, _ = fetch_fred_latest("GDP")              # 十亿$
        if mv and gdp:
            ratio = mv / (gdp * 1000) * 100
            if 50 < ratio < 400:  # sanity
                return {"value": round(ratio, 1), "as_of": mv_d, "status": "ok",
                        "extra": {"source": "FRED Z.1"}}
    except Exception:
        pass
    # 回退: 旧网页抓
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


# ─────────── NAAIM Exposure — 2026-08-01 起非会员转付费(免费页延迟3个月,无实时值) ───────────
def fetch_naaim():
    """NAAIM 主动经理股票敞口。2026-08-01 起非会员转订阅制:免费页数据延迟3个月,
    对当前情绪无用。替代已在 config: BofA FMS 现金水平(月度,信号最像)。此处保持标注不编。"""
    body = jina_get("https://www.naaim.org/programs/naaim-exposure-index/")
    if body and "subscription" in body.lower():
        return {"value": None, "as_of": None, "status": "非会员延迟3月(2026-08转付费),用BofA FMS现金替代"}
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
            # 老 .xls 用 pandas + xlrd
            import pandas as pd
            df = pd.read_excel(io.BytesIO(r.content), skiprows=3)
            df = df.dropna(subset=[df.columns[0]])
            last = df.iloc[-1]
            bull = float(last.iloc[1]) * (100 if last.iloc[1] < 1.5 else 1)
            bear = float(last.iloc[3]) * (100 if last.iloc[3] < 1.5 else 1)
            d = last.iloc[0]
            ds = str(d)[:10] if not hasattr(d, "strftime") else d.strftime("%Y-%m-%d")
            # sanity: 日期须像 ISO 且 bull/bear 在合理区间且不相等异常
            _iso_ok = bool(re.match(r"\d{4}-\d{2}-\d{2}", ds))
            _val_ok = (0 < bull < 90) and (0 < bear < 90) and abs(bull - bear) < 90
            if _iso_ok and _val_ok and not (bull == bear):
                return {"value": round(bull - bear, 1), "as_of": ds, "status": "ok",
                        "extra": {"bull": round(bull, 1), "bear": round(bear, 1)}}
            # 解析异常(表头漂移/占位) → 视为失败, 让上层回退 overrides
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


# ─────────── AAII Asset Allocation (2026-08 改: read_html 直连,不用 Jina) ───────────
def fetch_aaii_allocation():
    """AAII 家庭股票总配置%。aaii.com 公开页普通 UA 即 200(不需 Jina/登录)。
    pandas.read_html 找 10x4 表, iloc[3,2]=Stocks Total%。失败回退 Jina 正则。"""
    try:
        import pandas as pd
        from fetchers.util import HEADERS
        tables = pd.read_html("https://www.aaii.com/assetallocationsurvey", storage_options=HEADERS)
        for df in tables:
            if df.shape[0] >= 4 and df.shape[1] >= 3:
                # 找含 "Stocks Total" 的行
                for i in range(len(df)):
                    label = str(df.iloc[i, 0])
                    if "Stocks Total" in label or "Stock Total" in label:
                        raw = str(df.iloc[i, df.shape[1] - 2] if df.shape[1] > 2 else df.iloc[i, 1])
                        v = _num(raw)
                        if v and 20 < v < 100:
                            return {"value": round(v, 2), "as_of": None, "status": "ok"}
    except Exception:
        pass
    # 回退 Jina 正则
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
    import io
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


# ─────────── Renaissance IPO count (2026-08 改: stockanalysis 直连) ───────────
def fetch_ipo():
    """当年 YTD IPO 宗数。stockanalysis.com/ipos/<year> 普通 UA 直连(替 Renaissance 反爬)。
    read_html 表0行数=YTD IPO 数。失败回退旧 Renaissance 抓。"""
    try:
        import pandas as pd, datetime
        from fetchers.util import HEADERS
        year = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).year
        tables = pd.read_html(f"https://stockanalysis.com/ipos/{year}/", storage_options=HEADERS)
        if tables:
            n = len(tables[0])
            if n > 0:
                return {"value": float(n), "as_of": f"{year}-YTD", "status": "ok",
                        "extra": {"source": "stockanalysis", "year": year}}
    except Exception:
        pass
    # 回退旧 Renaissance
    body = http_get("https://www.renaissancecapital.com/IPO-Center/Stats", timeout=25)[1]
    if body:
        m = re.search(r"There have been\s*(?:<strong>)?\s*(\d+)\s*(?:</strong>)?\s*IPOs (?:priced this year|in \d{4})", body)
        if m:
            proceeds = re.search(r"Total proceeds raised were\s*(?:<strong>)?\$([\d.]+)\s*bil", body)
            extra = {"proceeds_bil": float(proceeds.group(1))} if proceeds else {}
            return {"value": float(m.group(1)), "as_of": None, "status": "ok", "extra": extra}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── Insider Buy/Sell (2026-08 改: openinsider,替被403的gurufocus) ───────────
def fetch_insider():
    """内部人买卖比($)。openinsider.com 普通 UA 直连(gurufocus 已被 Cloudflare 403)。
    买入榜$总额 / 卖出榜$总额。注:近期榜前100笔口径,做趋势方向。失败回退旧 gurufocus。"""
    try:
        import pandas as pd
        from fetchers.util import HEADERS

        def _sum_value(url):
            tables = pd.read_html(url, storage_options=HEADERS)
            for df in tables:
                cols = [str(c) for c in df.columns]
                if any("Value" in c for c in cols) and any("Ticker" in c for c in cols):
                    vcol = [c for c in df.columns if "Value" in str(c)][0]
                    tot = 0.0
                    for x in df[vcol]:
                        n = _num(str(x))
                        if n:
                            tot += abs(n)
                    return tot
            return None

        buys = _sum_value("http://openinsider.com/insider-purchases")
        sells = _sum_value("http://openinsider.com/insider-sales")
        if buys and sells and sells > 0:
            ratio = buys / sells
            if 0 < ratio < 50:
                return {"value": round(ratio, 3), "as_of": None, "status": "ok",
                        "extra": {"source": "openinsider", "note": "近期榜前100笔口径,趋势用"}}
    except Exception:
        pass
    # 回退旧 gurufocus
    t = jina_get("https://www.gurufocus.com/economic_indicators/4359/insider-buysell-ratio")
    if t:
        m = re.search(r"Insider Buy/Sell Ratio[^0-9]*is currently\s*([\d.]+)", t)
        if m:
            v = float(m.group(1).rstrip("."))
            if 0 < v < 20:
                return {"value": v, "as_of": None, "status": "ok"}
    return {"value": None, "as_of": None, "status": "未找到"}


# ─────────── Conference Board LEI (2026-08 改: FRED OECD CLI 替代付费源) ───────────
def fetch_lei():
    """领先经济指数。Conference Board LEI 已付费闭源 → 替代 FRED OECD 美国综合领先指标
    USALOLITOAASTSAM(月度,基准100)。value=6个月变化(最新-6期前)。失败回退旧网页抓。"""
    try:
        from fetchers.fred import fetch_fred_history
        hist = fetch_fred_history("USALOLITOAASTSAM", start="2024-01-01")
        if hist and len(hist) >= 7:
            latest_d, latest_v = hist[-1]
            _, prev_v = hist[-7]  # 6 个月前
            chg6 = round(latest_v - prev_v, 2)
            return {"value": chg6, "as_of": latest_d, "status": "ok",
                    "extra": {"cli_index": round(latest_v, 2), "source": "FRED OECD CLI",
                              "note": "OECD综合领先指标6月变化(替Conference Board付费LEI)"}}
    except Exception:
        pass
    # 回退旧 Conference Board 网页抓
    t = jina_get("https://www.conference-board.org/topics/us-leading-indicators/")
    if t:
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
