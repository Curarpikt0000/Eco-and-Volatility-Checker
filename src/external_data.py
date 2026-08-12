"""external_data.py — 联动读取 KOL 和 Economic Dashboard 的数据。

- KOL by_day DB：取最近 N 天 KOL 言论，识别「状态变化」(主导方向 vs 该 KOL 上次)
- Economic Dashboard DB：取 Fed/中日流动性关键点(reserves/RRP/TGA/DR007/USDJPY 等)

只读，不写。供每日 report + dashboard 底部板块用。
时区 JST。所有数字来自真实 Notion，绝不编造。
"""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(__file__))
from notion_writer import _req

# ─────────── KOL ───────────
KOL_BY_DAY_DB = "32347eb5fd3c8087b9c0f409f95f664e"
KOL_REGISTRY = os.path.join(os.path.dirname(__file__), "..", "data", "kol_registry.json")
KOL_INDEPENDENT = os.path.join(os.path.dirname(__file__), "..", "data", "kol_independent.json")


def load_registry():
    """读 KOL 名册(full list)。返回 [{id,display_name,domain,sector,institution},...]。"""
    import json
    try:
        d = json.load(open(KOL_REGISTRY))
        return d.get("kols", [])
    except Exception:
        return []


def load_independent_kol():
    """读 Eco 自己独立抓的 KOL 数据(cron agent 每日 web_search 写入)。
    格式: {"date":"YYYY-MM-DD", "changes":[{kol,sector,prev_dir,new_dir,date,comments,targets},...],
           "all":[{kol,sector,direction,date,comments,targets},...]}
    返回 (changes_list, meta) 或 ([], {})。"""
    import json
    if os.path.exists(KOL_INDEPENDENT):
        try:
            d = json.load(open(KOL_INDEPENDENT))
            return d.get("changes", []), d
        except Exception:
            pass
    return [], {}


def _rt(prop):
    """rich_text / title → 纯文本。"""
    arr = prop.get("rich_text") or prop.get("title") or []
    return "".join(x.get("plain_text", x.get("text", {}).get("content", "")) for x in arr)


def _sel(prop):
    s = prop.get("select")
    return s.get("name") if s else ""


def fetch_kol_recent(days=10, limit=200):
    """取最近 N 天 KOL by_day 记录。返回 [dict,...] 按日期降序。"""
    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    cursor = None
    while True:
        payload = {
            "filter": {"property": "Date", "date": {"on_or_after": since}},
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor
        st, b = _req("POST", f"/databases/{KOL_BY_DAY_DB}/query", payload)
        if st != 200:
            break
        for r in b.get("results", []):
            p = r["properties"]
            out.append({
                "date": (p.get("Date", {}).get("date") or {}).get("start", "")[:10],
                "kol": _sel(p.get("Name of KOL", {})),
                "type": _sel(p.get("KOL or IB View", {})),
                "direction": _sel(p.get("主导方向", {})),
                "sector": _sel(p.get("Sector", {})),
                "detail_sector": _sel(p.get("Detail Sector", {})),
                "suggestion": _rt(p.get("Suggestion", {})),
                "comments": _rt(p.get("Comments", {})),
                "dir_detail": _rt(p.get("方向明细", {})),
                "targets": _rt(p.get("多空标的", {})),
            })
        if b.get("has_more"):
            cursor = b["next_cursor"]
        else:
            break
        if len(out) >= limit:
            break
    return out


def kol_stance_changes(days=10):
    """识别最近 N 天内 KOL 的「状态变化」：某 KOL 最新主导方向 != 其之前一条。
    返回 [{kol, sector, prev_dir, new_dir, date, comments, targets},...]。
    """
    recs = fetch_kol_recent(days=days)
    # 按 KOL 分组，按日期升序
    by_kol = {}
    for r in recs:
        if not r["kol"] or not r["direction"]:
            continue
        by_kol.setdefault(r["kol"], []).append(r)
    changes = []
    for kol, rs in by_kol.items():
        rs.sort(key=lambda x: x["date"])
        for i in range(1, len(rs)):
            if rs[i]["direction"] != rs[i - 1]["direction"]:
                changes.append({
                    "kol": kol,
                    "sector": rs[i]["sector"],
                    "prev_dir": rs[i - 1]["direction"],
                    "new_dir": rs[i]["direction"],
                    "date": rs[i]["date"],
                    "comments": rs[i]["comments"][:300],
                    "targets": rs[i]["targets"][:150],
                })
    # 只保留最近的变化(去重同 KOL 取最新)
    latest = {}
    for ch in sorted(changes, key=lambda x: x["date"]):
        latest[ch["kol"]] = ch
    return sorted(latest.values(), key=lambda x: x["date"], reverse=True)


def kol_today(date_str=None):
    """取指定日期(默认最新有数据日)的 KOL 言论。返回 [dict,...]。"""
    recs = fetch_kol_recent(days=7)
    if not recs:
        return []
    if date_str is None:
        date_str = max(r["date"] for r in recs if r["date"])
    return [r for r in recs if r["date"] == date_str]


# ─────────── Economic Dashboard 流动性 ───────────
ECON_DB = {
    "fed_liquidity": "4df3fc720f0c4cdc902cb18c009e4802",   # A5: reserves/RRP/TGA
    "risk_report": "750f9b463e234537bc7c07213da4d8fb",     # A6: 每日风控报告
    "ust_yields": "76f9359788ef481faeba19e5b74d5dc4",      # A1: 收益率
    "pboc": "b54e379b6aea4062a15c891697af1230",            # B2: 中国流动性
    "boj": "286e24acda1242f9a7dfca9aa1c89a2e",             # B3: 日本流动性
}


def _num(prop):
    return prop.get("number")


def _latest_row(db_id, title_field="Date"):
    """取某 DB 最新一行(按 title 降序)。返回 properties dict 或 None。"""
    st, b = _req("POST", f"/databases/{db_id}/query",
                 {"sorts": [{"property": title_field, "direction": "descending"}], "page_size": 2})
    if st == 200 and b.get("results"):
        return [r["properties"] for r in b["results"]]
    return None


def fetch_liquidity_points():
    """取 Economic Dashboard 流动性关键点。返回 dict(取到什么算什么，缺就 None)。"""
    out = {}
    # Fed 流动性 (A5)
    rows = _latest_row(ECON_DB["fed_liquidity"])
    if rows:
        cur = rows[0]
        prev = rows[1] if len(rows) > 1 else {}
        for label, fld in [("reserves_T", "Reserves_T"), ("on_rrp_B", "ON_RRP_B"), ("tga_B", "TGA_B")]:
            v = _num(cur.get(fld, {}))
            pv = _num(prev.get(fld, {})) if prev else None
            if v is not None:
                out[label] = {"value": v, "prev": pv,
                              "delta": (round(v - pv, 2) if pv is not None else None)}
    # 每日风控报告 (A6) — 取风控灯/结论文本
    rr = _latest_row(ECON_DB["risk_report"])
    if rr:
        cur = rr[0]
        for name, p in cur.items():
            if p.get("type") == "rich_text" and _rt(p):
                out.setdefault("risk_notes", {})[name] = _rt(p)[:400]
            elif p.get("type") == "select" and p.get("select"):
                out.setdefault("risk_lights", {})[name] = p["select"]["name"]
    # 收益率 (A1)
    yr = _latest_row(ECON_DB["ust_yields"])
    if yr:
        cur = yr[0]
        prev = yr[1] if len(yr) > 1 else {}
        for fld in ["10Y", "2Y", "30Y"]:
            v = _num(cur.get(fld, {}))
            pv = _num(prev.get(fld, {})) if prev else None
            if v is not None:
                out.setdefault("yields", {})[fld] = {"value": v, "delta": (round(v - pv, 3) if pv is not None else None)}
    return out


if __name__ == "__main__":
    import json
    print("=== KOL 状态变化(近10天) ===")
    for ch in kol_stance_changes()[:8]:
        print(f"  {ch['date']} {ch['kol']}({ch['sector']}): {ch['prev_dir']} → {ch['new_dir']}")
    print("\n=== 流动性关键点 ===")
    print(json.dumps(fetch_liquidity_points(), ensure_ascii=False, indent=2, default=str)[:1500])
