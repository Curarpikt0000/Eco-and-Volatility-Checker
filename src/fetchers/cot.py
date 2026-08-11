"""CFTC COT fetcher — 金银 commercial 持仓 (Socrata Legacy futures-only)。

重点：commercial(商业套保) 持仓突增 = 聪明钱信号。
CFTC 周五发布上周二数据。
"""
import requests
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as c


def _query(market_name, limit=60):
    """按 market 精确匹配拉 COT 历史(降序)。返回 raw dict 列表。"""
    # 用 contract_market_name 精确匹配主力(排除 MICRO/其它)
    where = f"market_and_exchange_names='{market_name}'"
    params = {
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": limit,
    }
    try:
        r = requests.get(c.COT_SOURCE, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def _row(raw):
    """把一条 CFTC raw 转成精简 dict。"""
    def gi(k):
        try:
            return int(float(raw.get(c.COT_FIELDS[k], 0)))
        except Exception:
            return 0
    comm_long = gi("comm_long")
    comm_short = gi("comm_short")
    ncl = gi("noncomm_long")
    ncs = gi("noncomm_short")
    return {
        "as_of": (raw.get("report_date_as_yyyy_mm_dd") or "")[:10],
        "open_interest": gi("open_interest"),
        "comm_long": comm_long,
        "comm_short": comm_short,
        "comm_net": comm_long - comm_short,
        "noncomm_long": ncl,
        "noncomm_short": ncs,
        "noncomm_net": ncl - ncs,
    }


def fetch_latest(metal):
    """取金或银最新 COT + 上一周(算环比)。返回 dict 或 None。"""
    market = c.COT_MARKETS[metal]
    raws = _query(market, limit=8)
    if not raws:
        return None
    rows = [_row(x) for x in raws]
    rows = [r for r in rows if r["as_of"]]
    if not rows:
        return None
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    cur["metal"] = metal
    if prev:
        cur["comm_net_wow"] = cur["comm_net"] - prev["comm_net"]
        cur["comm_long_wow"] = cur["comm_long"] - prev["comm_long"]
        cur["comm_short_wow"] = cur["comm_short"] - prev["comm_short"]
    else:
        cur["comm_net_wow"] = None
        cur["comm_long_wow"] = None
        cur["comm_short_wow"] = None
    # commercial 突增标记(long 或 short 任一周环比绝对增量超阈值)
    surge = False
    if prev:
        if abs(cur["comm_long"] - prev["comm_long"]) >= c.COT_COMM_SURGE_THRESHOLD \
           or abs(cur["comm_short"] - prev["comm_short"]) >= c.COT_COMM_SURGE_THRESHOLD:
            surge = True
    cur["comm_surge"] = surge
    return cur


def fetch_history(metal, weeks=60):
    """取金或银最近 N 周 COT 历史(升序，供 backfill)。返回 [dict,...]。"""
    market = c.COT_MARKETS[metal]
    raws = _query(market, limit=weeks + 2)
    rows = [_row(x) for x in raws if (x.get("report_date_as_yyyy_mm_dd") or "")]
    rows.sort(key=lambda r: r["as_of"])
    # 计算逐周环比
    out = []
    for i, r in enumerate(rows):
        r["metal"] = metal
        if i > 0:
            r["comm_net_wow"] = r["comm_net"] - rows[i-1]["comm_net"]
            r["comm_long_wow"] = r["comm_long"] - rows[i-1]["comm_long"]
            r["comm_short_wow"] = r["comm_short"] - rows[i-1]["comm_short"]
            r["comm_surge"] = (abs(r["comm_long"] - rows[i-1]["comm_long"]) >= c.COT_COMM_SURGE_THRESHOLD
                               or abs(r["comm_short"] - rows[i-1]["comm_short"]) >= c.COT_COMM_SURGE_THRESHOLD)
        else:
            r["comm_net_wow"] = r["comm_long_wow"] = r["comm_short_wow"] = None
            r["comm_surge"] = False
        out.append(r)
    return out
