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
# Eco 自己的每日 KOL 全量方向快照仓库(独立副本, 进 git, 供周度对比用, 不依赖任何 agent 的 Notion DB)
KOL_DAILY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "kol", "daily")


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


def _days_since_last_monday():
    """今天回溯到『上周一』的天数(含今天区间)。
    上周一 = 本周一 - 7天。用于 KOL 变化的回看窗口。"""
    import datetime as _dt
    today = _dt.date.today()
    this_monday = today - _dt.timedelta(days=today.weekday())  # 本周一
    last_monday = this_monday - _dt.timedelta(days=7)
    return (today - last_monday).days + 1


# ═══════ Eco 自己的 KOL 每日快照仓库(独立副本, 供周度对比, 不依赖任何 agent) ═══════
def save_kol_daily_snapshot(date_str=None):
    """把当日 kol_independent.json 的全量方向(all)落盘为 data/kol/daily/YYYY-MM-DD.json。
    这是 Eco 自己的独立数据仓库副本(进 git), 供周度对比用, 不依赖任何 agent 的 Notion DB。
    幂等: 同日重复调用覆盖当日快照。返回写入路径或 None(无独立数据时跳过)。"""
    import json
    if not os.path.exists(KOL_INDEPENDENT):
        return None
    try:
        ind = json.load(open(KOL_INDEPENDENT))
    except Exception:
        return None
    all_dirs = ind.get("all") or []
    if not all_dirs:
        return None
    ds = date_str or ind.get("date") or datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs(KOL_DAILY_DIR, exist_ok=True)
    snap = {
        "date": ds,
        "count": len(all_dirs),
        "source": "Eco independent daily crawl (web_search 全量 KOL)",
        "kols": [
            {
                "kol": x.get("kol", ""),
                "sector": x.get("sector", ""),
                "direction": x.get("direction", ""),
                "targets": (x.get("targets") or "")[:150],
                "comments": (x.get("comments") or "")[:300],
            }
            for x in all_dirs if x.get("kol")
        ],
    }
    path = os.path.join(KOL_DAILY_DIR, f"{ds}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return path


def load_kol_daily_snapshots():
    """读 data/kol/daily/ 下全部快照。返回 {YYYY-MM-DD: {kol: {direction,sector,targets,comments}}} 按日期。
    无快照返回 {}。"""
    import json
    import glob
    out = {}
    if not os.path.isdir(KOL_DAILY_DIR):
        return out
    for p in glob.glob(os.path.join(KOL_DAILY_DIR, "*.json")):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        ds = d.get("date") or os.path.basename(p)[:10]
        by_kol = {}
        for x in d.get("kols", []):
            if x.get("kol"):
                by_kol[x["kol"]] = x
        if by_kol:
            out[ds] = by_kol
    return out


def kol_weekly_changes():
    """本周 vs 上周 KOL 方向转向, 全部基于 Eco 自己的每日快照(data/kol/daily/), 不碰任何 agent DB。
    比较逻辑: 对每个 KOL, 取『本周最新一天快照的方向』vs『上周最后一天快照的方向』, 不同则记为转向。
    若快照不足(尚未攒够跨周数据), 回退到"最早快照 vs 最新快照"对比, 并标 note。
    返回 [{kol, sector, prev_dir, new_dir, date, comments, targets},...] (供 grouped 分组)。"""
    import datetime as _dt
    snaps = load_kol_daily_snapshots()
    if len(snaps) < 2:
        return []
    dates = sorted(snaps.keys())
    today = _dt.date.today()
    this_monday = today - _dt.timedelta(days=today.weekday())
    last_monday = this_monday - _dt.timedelta(days=7)
    tm, lm = this_monday.strftime("%Y-%m-%d"), last_monday.strftime("%Y-%m-%d")
    # 本周快照 = 日期 >= 本周一; 上周快照 = 上周一 <= 日期 < 本周一
    this_week = [d for d in dates if d >= tm]
    last_week = [d for d in dates if lm <= d < tm]
    if this_week and last_week:
        cur_date, prev_date = this_week[-1], last_week[-1]
    else:
        # 跨周数据不足 → 用最新 vs 最早(诚实回退, 攒够后自动切回周对比)
        cur_date, prev_date = dates[-1], dates[0]
    cur, prev = snaps.get(cur_date, {}), snaps.get(prev_date, {})
    # 无效方向(空/未找到/数据滞后等非真实立场)不参与转向判定
    _invalid_dir = {"", "未找到", "无", "n/a", "未知", "数据滞后", "-", "—"}
    changes = []
    for kol, c in cur.items():
        p = prev.get(kol)
        if not p:
            continue  # 上周无记录 → 不算"转向"(新覆盖的KOL不误报)
        cd = (c.get("direction") or "").strip()
        pd = (p.get("direction") or "").strip()
        if cd in _invalid_dir or pd in _invalid_dir:
            continue  # 任一端无效 → 不是真转向(避免"看空→未找到"伪转向)
        if cd and pd and cd != pd:
            changes.append({
                "kol": kol,
                "sector": c.get("sector", ""),
                "prev_dir": pd,
                "new_dir": cd,
                "date": cur_date,
                "comments": (c.get("comments") or "")[:300],
                "targets": (c.get("targets") or "")[:150],
            })
    return sorted(changes, key=lambda x: x["kol"])


def kol_weekly_views(min_comment_len=10):
    """本周全部有实质观点的 KOL, 按 sector 分组(不只转向, 而是所有有意义的观点)。
    数据源: Eco 自己每日快照(优先本周最新一天; 无快照回退 kol_independent.json 的 all)。
    每个 KOL 取其本周最新一次观点(方向+言论+标的)。绝不编: 无言论/无数据则跳过。
    返回 {"date": 观点日期, "total": KOL数, "modules": [{sector,en,color,views:[{kol,direction,comments,targets,date}]}]}。
    """
    import json
    import datetime as _dt
    # 优先: 过去一周(上周一→今天)滚动窗口聚合(独立数据仓库)
    # ★"本周"= 过去 7 天滚动窗口(上周一 00:00 → 今天), 每个 KOL 取其窗口内
    #   【最近一次有实质观点】的记录 → 只要过去一周任意一天有观点就一直显示,
    #   不会因"最新那天快照恰好空/稀疏/未跑"而整个模块空掉(Chao 2026-08 修正)。
    snaps = load_kol_daily_snapshots()
    rows = []
    src_date = ""
    _invalid = {"", "未找到", "无", "n/a", "未知", "数据滞后", "-", "—"}
    _today = _dt.date.today()
    _this_monday = _today - _dt.timedelta(days=_today.weekday())
    _last_monday = _this_monday - _dt.timedelta(days=7)
    _win_start = _last_monday.strftime("%Y-%m-%d")   # 滚动窗口起点=上周一
    _win_end = _today.strftime("%Y-%m-%d")
    since_map = {}   # kol -> 当前方向连续保持起始日
    if snaps:
        all_dates = sorted(snaps.keys())              # 升序
        # 滚动窗口内的快照日期(上周一 ≤ d ≤ 今天)
        window_dates = [d for d in all_dates if _win_start <= d <= _win_end]
        # 若窗口内一个快照都没有(极端: 长期没跑), 诚实回退到最近有数据的一天
        if not window_dates:
            window_dates = all_dates[-1:]
        src_date = window_dates[-1] if window_dates else (all_dates[-1] if all_dates else "")
        # ── 每个 KOL 取窗口内【最近一次有实质观点】的记录(按日期从新到旧找) ──
        latest_view = {}   # kol -> (date, record)
        for dd in reversed(window_dates):             # 新→旧
            for kol, x in snaps.get(dd, {}).items():
                if kol in latest_view:
                    continue                          # 已有更新的记录
                cmt = (x.get("comments") or "").strip()
                direction = (x.get("direction") or "").strip()
                # 只收有实质言论的(方向可为分歧等, 但 comments 要有内容)
                if cmt:
                    latest_view[kol] = (dd, x)
        # ── 首现日期: 对每个当前观点, 回溯全历史算【当前方向连续保持起始日】 ──
        for kol, (vdate, x) in latest_view.items():
            cur_dir = (x.get("direction") or "").strip()
            since = vdate
            if cur_dir and cur_dir not in _invalid:
                # 从 vdate 往前回溯(全历史, 不限窗口), 方向相同则前推起始日
                earlier = [d for d in all_dates if d < vdate]
                for dd in reversed(earlier):
                    prev_rec = snaps.get(dd, {}).get(kol)
                    if not prev_rec:
                        break  # 断档 → 起始日停在此
                    pdir = (prev_rec.get("direction") or "").strip()
                    if pdir == cur_dir:
                        since = dd
                    else:
                        break  # 方向变了
            since_map[kol] = since
            rows.append({"kol": kol, "sector": x.get("sector", ""),
                         "direction": x.get("direction", ""),
                         "comments": x.get("comments", ""),
                         "targets": x.get("targets", ""), "date": vdate,
                         "since_date": since})
    else:
        # 回退: kol_independent.json 的 all(当日全量, 无历史→首现日=当日)
        if os.path.exists(KOL_INDEPENDENT):
            try:
                d = json.load(open(KOL_INDEPENDENT))
                src_date = d.get("date", "")
                for x in d.get("all", []):
                    if x.get("kol"):
                        rows.append({"kol": x["kol"], "sector": x.get("sector", ""),
                                     "direction": x.get("direction", ""),
                                     "comments": x.get("comments", ""),
                                     "targets": x.get("targets", ""),
                                     "date": x.get("date", src_date),
                                     "since_date": x.get("date", src_date)})
            except Exception:
                pass
    # 本周一(判断"新观点": 当前方向起始日 >= 本周一 = 本周内新转成的)
    _this_monday_str = _this_monday.strftime("%Y-%m-%d")
    # 只保留有实质言论的
    rows = [r for r in rows if (r.get("comments") or "").strip()
            and len((r["comments"]).strip()) >= min_comment_len]
    # 按归一 sector 分组
    groups = {}
    for r in rows:
        sec_raw = (r.get("sector") or "").strip()
        zh, en = _KOL_SECTOR_MAP.get(sec_raw, (sec_raw or "其他", sec_raw or "Other"))
        groups.setdefault(zh, {"sector": zh, "en": en,
                               "color": _KOL_SECTOR_COLOR.get(zh, "#8a8377"),
                               "views": []})
        since = r.get("since_date", r.get("date", src_date))
        groups[zh]["views"].append({
            "kol": r.get("kol", ""),
            "direction": r.get("direction", ""),
            "comments": (r.get("comments") or "")[:400],
            "targets": (r.get("targets") or "")[:150],
            "date": r.get("date", src_date),
            "since_date": since,                    # 当前观点起始日(首现)
            "is_new": bool(since and since >= _this_monday_str),  # 本周内新转成
        })
    # 方向强弱排序: 看多在前(更醒目), 模块内按方向强弱降序
    _rank = {"强烈看多": 2, "看多": 1, "分歧": 0, "中性": 0, "看空": -1, "强烈看空": -2}
    for g in groups.values():
        g["views"].sort(key=lambda v: (-_rank.get(v["direction"], 0), v["kol"]))
    # 模块按观点数降序
    modules = sorted(groups.values(), key=lambda g: len(g["views"]), reverse=True)
    total = sum(len(g["views"]) for g in modules)
    return {"date": src_date, "total": total, "modules": modules}


# sector 中英归一(Notion DB 用英文, independent.json 用中文) → 统一中文模块名 + 英文副标 + 色
_KOL_SECTOR_MAP = {
    "Precious Metals": ("贵金属", "Precious Metals"),
    "贵金属": ("贵金属", "Precious Metals"),
    "贵金属与商品周期": ("贵金属", "Precious Metals & Commodity Cycle"),
    "Macro": ("宏观货币与金融体系", "Macro & Monetary"),
    "宏观货币与金融体系": ("宏观货币与金融体系", "Macro & Monetary"),
    "Equities": ("股权市场", "Equities"),
    "股权市场": ("股权市场", "Equities"),
    "Crypto": ("加密资产", "Crypto"),
    "加密资产": ("加密资产", "Crypto"),
    "Energy & Commodities": ("资源与能源安全", "Energy & Commodities"),
    "Energy": ("资源与能源安全", "Energy & Commodities"),
    "资源与能源安全": ("资源与能源安全", "Energy & Commodities"),
    "Government Debt": ("国债利率与债券市场", "Government Debt & Rates"),
    "国债利率与债券市场": ("国债利率与债券市场", "Government Debt & Rates"),
    "预测": ("预测与周期", "Forecast & Cycle"),
    "科技与未来趋势": ("科技与未来趋势", "Tech & Future"),
    "交易与市场微观结构": ("交易与市场微观结构", "Trading & Microstructure"),
}
_KOL_SECTOR_COLOR = {
    "贵金属": "#bfa06a", "贵金属与商品周期": "#bfa06a",
    "宏观货币与金融体系": "#8ea1ad", "股权市场": "#a693a0",
    "加密资产": "#c9ac6b", "资源与能源安全": "#9aab97",
    "国债利率与债券市场": "#c08a7d", "预测与周期": "#8a8377",
    "科技与未来趋势": "#8ea1ad", "交易与市场微观结构": "#a693a0",
}


def kol_stance_changes_grouped(days=None):
    """本周 KOL 方向转向, 按 sector 模块分组。
    ★数据源: Eco 自己的每日快照(data/kol/daily/, kol_weekly_changes), 完全独立, 不依赖任何 agent 的 Notion DB。
    本周最新快照 vs 上周最后快照对比转向; 跨周数据不足时回退最新vs最早(诚实, 攒够自动切回)。
    返回 {"since": 上周对比基准日, "days": N, "total": 转向总数,
          "modules": [{"sector":中文, "en":英文, "color":色, "changes":[{kol,prev_dir,new_dir,date,comments,targets},...]}]}
    绝不编: 无数据则 modules=[]。"""
    import datetime as _dt
    today = _dt.date.today()

    # ★主源: Eco 自己的每日快照做本周 vs 上周对比(完全独立)
    raw = kol_weekly_changes()
    # 基准日: 用快照里实际对比的 prev 日期(若无则本周一)
    snaps = load_kol_daily_snapshots()
    since = ""
    if snaps:
        dates = sorted(snaps.keys())
        this_monday = today - _dt.timedelta(days=today.weekday())
        last_monday = this_monday - _dt.timedelta(days=7)
        tm, lm = this_monday.strftime("%Y-%m-%d"), last_monday.strftime("%Y-%m-%d")
        last_week = [d for d in dates if lm <= d < tm]
        since = last_week[-1] if last_week else dates[0]
    days = len(snaps)

    # 按归一 sector 分组
    groups = {}
    for ch in raw:
        sec_raw = (ch.get("sector") or "").strip()
        zh, en = _KOL_SECTOR_MAP.get(sec_raw, (sec_raw or "其他", sec_raw or "Other"))
        groups.setdefault(zh, {"sector": zh, "en": en,
                               "color": _KOL_SECTOR_COLOR.get(zh, "#8a8377"),
                               "changes": []})
        groups[zh]["changes"].append({
            "kol": ch.get("kol", ""),
            "prev_dir": ch.get("prev_dir", ""),
            "new_dir": ch.get("new_dir", ""),
            "date": ch.get("date", ""),
            "comments": (ch.get("comments") or "")[:300],
            "targets": (ch.get("targets") or "")[:150],
        })
    # 模块内按日期降序; 模块按转向数降序
    for g in groups.values():
        g["changes"].sort(key=lambda x: x["date"], reverse=True)
    modules = sorted(groups.values(), key=lambda g: len(g["changes"]), reverse=True)
    total = sum(len(g["changes"]) for g in modules)
    return {"since": since, "days": days, "total": total, "modules": modules}


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


# ─────────── 三大央行资产负债表 (JP/CN/US) ───────────
# 数据源: Economic Dashboard 已维护的 B5(PBoC月度)/B6(BoJ旬报)/B7(Fed周度) Notion DB。
# 读最新两行, 每科目算环比。对比口径随频率不同(Fed=WoW真周环比 / BoJ=较上期旬报 / PBoC=较上月MoM)。
CB_BS_DB = {
    "US": "dea7e939bb394d538f3cea3ff0da5a6b",  # B7 Fed 周度
    "JP": "481f6e1960e4444383d66a1e1cafb49b",  # B6 BoJ 旬报
    "CN": "20b0eb37d69744109cca9fba0c61b929",  # B5 PBoC 月度
}

# 每国: (title字段, 单位, 对比口径标签, 资产科目[(显示名,字段)], 负债科目[(显示名,字段)], 总资产字段, 总负债字段)
CB_BS_SPEC = {
    "US": {
        "name": "美联储 Fed", "flag": "🇺🇸", "title": "Week", "unit": "$B", "period": "WoW",
        "assets": [
            ("美国国债 Treasuries", "资产_Treasuries_B"),
            ("短期国债 Bills（RMP 储备管理购买）", "资产_Bills_B", "sub"),
            ("MBS 抵押债", "资产_MBS_B"),
            ("FIMA 海外回购", "资产_FIMA_B"),
            ("SRF 常备回购", "资产_SRF_B"),
        ],
        "liabilities": [
            ("准备金 Reserves", "负债_Reserves_B"),
            ("隔夜逆回购 ON RRP", "负债_ON_RRP_B"),
            ("财政部账户 TGA", "负债_TGA_B"),
            ("流通货币 Currency", "负债_Currency_B"),
        ],
        "total_a": "总资产_B", "total_l": None,
    },
    "JP": {
        "name": "日本央行 BoJ", "flag": "🇯🇵", "title": "Date", "unit": "兆¥", "period": "较上期",
        "assets": [
            ("日本国债 JGB", "资产_国债JGB_兆JPY"),
            ("公司债", "资产_公司债_兆JPY"),
            ("ETF", "资产_ETF_兆JPY"),
            ("J-REIT", "资产_J_REIT_兆JPY"),
        ],
        "liabilities": [
            ("银行券 Banknotes", "负债_银行券_兆JPY"),
            ("经常项目存款", "负债_经常项目存款_兆JPY"),
            ("政府存款", "负债_政府存款_兆JPY"),
        ],
        "total_a": "总资产_兆JPY", "total_l": None,
    },
    "CN": {
        "name": "中国央行 PBoC", "flag": "🇨🇳", "title": "Month", "unit": "亿¥", "period": "MoM",
        "assets": [
            ("外汇占款", "资产_外汇占款_亿"),
            ("对政府债权", "资产_对政府债权_亿"),
            ("对其他存款性公司债权", "资产_对其他存款性公司债权_亿"),
        ],
        "liabilities": [
            ("储备货币", "负债_储备货币_亿"),
            ("货币发行", "负债_货币发行_亿", "sub"),
            ("政府存款", "负债_政府存款_亿"),
        ],
        "total_a": "总资产_亿", "total_l": "总负债_亿",
    },
}


def _title_val(props, field):
    p = props.get(field, {})
    arr = p.get("title") or []
    return "".join(x.get("plain_text", "") for x in arr)


def _bs_line(cur, prev, disp, fld, sub=False):
    """一个科目: 取当前值 + 环比。返回 {name,value,delta,pct,sub} 或 None(值缺)。
    sub=True 表示该项是上一总项的子项(如"货币发行"⊂"储备货币"),渲染层缩进显示"其中·",不与总项同层相加。"""
    v = _num(cur.get(fld, {}))
    if v is None:
        return None
    pv = _num(prev.get(fld, {})) if prev else None
    delta = round(v - pv, 3) if pv is not None else None
    pct = round((v - pv) / pv * 100, 2) if (pv not in (None, 0)) else None
    return {"name": disp, "value": v, "delta": delta, "pct": pct, "sub": sub}


def _usd_convert(cc_data, factor, orig_unit):
    """把一个央行的资负表所有值 × factor 转成 $B。orig_unit 记进 note 保留原口径可溯源。"""
    if not cc_data or factor is None:
        return cc_data
    def conv(line):
        if not line:
            return line
        for k in ("value", "delta"):
            if line.get(k) is not None:
                line[k] = round(line[k] * factor, 1)
        return line
    for sec in ("assets", "liabilities"):
        cc_data[sec] = [conv(x) for x in cc_data.get(sec, [])]
    cc_data["total_assets"] = conv(cc_data.get("total_assets"))
    cc_data["total_liab"] = conv(cc_data.get("total_liab"))
    cc_data["unit"] = "$B"
    cc_data["orig_unit"] = orig_unit
    return cc_data


def fetch_ecb_balance_sheet(to_usd=True, usd_per_eur=None):
    """ECB 欧洲央行资产负债表(完整分项版, 格式与另三国一致)。
    ★数据源: ECB 官方 Data Portal SDMX API 的 ILM 数据集(Eurosystem 周度合并财务报表),
      免费无key, wildcard 一次拉全部 43 分项(单条 series key 查询对维度取值敏感易 400, wildcard 最稳)。
      base: https://data-api.ecb.europa.eu/service/data/ILM/W.U2.C... 单位=百万欧元。
      政策利率 ECBMRRFR(MRO)/ECBDFR(存款便利)/ECBMLFR(边际贷款) 走 FRED。
    to_usd: 全部分项按当天 USD/EUR(DEXUSEU, 1欧元=X美元)折成 $B(乘)。
    返回与 CB_BS_SPEC 一致结构。绝不编: 抓不到的科目跳过。"""
    import requests
    import csv as _csv
    import io as _io

    # ── ILM wildcard 一次拉全部分项 (BS_ITEM.COUNT_AREA.CURRENCY_TRANS → (值,期次)) ──
    got = {}
    period = None
    try:
        r = requests.get("https://data-api.ecb.europa.eu/service/data/ILM/W.U2.C...",
                         params={"lastNObservations": 1, "format": "csvdata"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=35)
        if r.status_code == 200:
            for row in _csv.DictReader(_io.StringIO(r.text)):
                tail = f'{row["BS_ITEM"]}.{row["COUNT_AREA"]}.{row["CURRENCY_TRANS"]}'
                try:
                    got[tail] = float(row["OBS_VALUE"])
                    period = row["TIME_PERIOD"]
                except (ValueError, KeyError):
                    pass
    except Exception:
        pass

    # 科目映射(显示名 → ILM tail key), 已独立验证真实可抓, 单位百万€
    ASSETS = [
        ("黄金及黄金债权 Gold", "A010000.Z5.Z0Z"),
        ("外币资产 FX Assets", "A020000.U4.Z06"),
        ("货币政策证券 Securities(APP+PEPP)", "A070100.U2.EUR"),
        ("对信贷机构贷款 Lending to CIs", "A050000.U2.EUR"),
        ("其他资产 Other Assets", "A110000.Z5.Z01"),
    ]
    LIABS = [
        ("流通银行券 Banknotes", "L010000.Z5.EUR"),
        ("对信贷机构负债 Liab. to CIs", "L020000.U2.EUR"),
        ("存款便利 Deposit Facility", "L020200.U2.EUR", "sub"),
        ("对其他居民负债 Liab. to Others", "L050000.U2.EUR"),
        ("重估账户 Revaluation", "L140000.Z5.Z01"),
        ("资本与储备 Capital&Reserves", "L150000.Z5.Z01"),
        ("其他负债 Other Liab.", "L120000.Z5.Z01"),
    ]
    total_key = "T000000.Z5.Z01"

    # 折美元汇率: 1€ = usd_per_eur 美元
    if usd_per_eur is None:
        try:
            from fetchers.fred import fetch_fred_latest
            usd_per_eur, _ = fetch_fred_latest("DEXUSEU")
        except Exception:
            usd_per_eur = None
    if not usd_per_eur:
        usd_per_eur = 1.16
    # 百万€ → $B: /1000(百万→十亿€) × usd_per_eur; 不折美元则 /1000 得十亿€
    factor = (usd_per_eur / 1000.0) if to_usd else (1.0 / 1000.0)

    def _line(name, tail, sub=False):
        if tail not in got:
            return None
        return {"name": name, "value": round(got[tail] * factor, 1),
                "delta": None, "pct": None, "sub": sub}   # 周环比暂无(只拉最新1期)

    # 政策利率(FRED)
    rates = {}
    for key, sid in (("mro", "ECBMRRFR"), ("dfr", "ECBDFR"), ("mlf", "ECBMLFR")):
        try:
            from fetchers.fred import fetch_fred_latest
            v, _ = fetch_fred_latest(sid)
            if v is not None:
                rates[key] = v
        except Exception:
            pass

    if not got:
        return {"name": "欧洲央行 ECB", "flag": "🇪🇺", "unit": "$B" if to_usd else "十亿€",
                "period": "周度", "date": None, "assets": [], "liabilities": [],
                "total_assets": None, "total_liab": None, "rates": rates, "status": "未找到"}

    assets = [x for x in (_line(n, k) for n, k in ASSETS) if x]
    liabs = [x for x in (_line(s[0], s[1], len(s) > 2 and s[2] == "sub") for s in LIABS) if x]
    ta = _line("总资产", total_key)
    return {
        "name": "欧洲央行 ECB", "flag": "🇪🇺",
        "unit": "$B" if to_usd else "十亿€", "orig_unit": "十亿€",
        "period": "周度", "date": period,       # 如 2026-W32
        "assets": assets, "liabilities": liabs,
        "total_assets": ta, "total_liab": None,
        "rates": rates,
        "usd_per_eur": round(usd_per_eur, 4),
        "source": "ECB Data Portal ILM (Eurosystem 周度财务报表)",
    }


def fetch_cb_balance_sheets(to_usd=True):
    """读 JP/CN/US 三大央行资产负债表最新两期, 每科目算环比。
    to_usd=True: 统一换算成 $B(十亿美元)横向可比(汇率走 FRED DEXJPUS/DEXCHUS)。
    返回 {"US":{...}, "JP":{...}, "CN":{...}}, 每个:
      {name, flag, unit, period, date, assets:[{name,value,delta,pct}], liabilities:[...],
       total_assets:{value,delta,pct}, total_liab:{...}|None}
    取到什么算什么, 缺的科目跳过(绝不编)。"""
    out = {}
    for cc, spec in CB_BS_SPEC.items():
        rows = _latest_row(CB_BS_DB[cc], title_field=spec["title"])
        if not rows:
            out[cc] = {"name": spec["name"], "flag": spec["flag"], "unit": spec["unit"],
                       "period": spec["period"], "date": None, "assets": [], "liabilities": [],
                       "total_assets": None, "total_liab": None, "status": "未找到"}
            continue
        cur = rows[0]
        prev = rows[1] if len(rows) > 1 else {}
        assets = [x for x in (_bs_line(cur, prev, s[0], s[1], len(s) > 2 and s[2] == "sub") for s in spec["assets"]) if x]
        liabs = [x for x in (_bs_line(cur, prev, s[0], s[1], len(s) > 2 and s[2] == "sub") for s in spec["liabilities"]) if x]
        ta = _bs_line(cur, prev, "总资产", spec["total_a"]) if spec.get("total_a") else None
        tl = _bs_line(cur, prev, "总负债", spec["total_l"]) if spec.get("total_l") else None
        out[cc] = {
            "name": spec["name"], "flag": spec["flag"], "unit": spec["unit"],
            "period": spec["period"], "date": _title_val(cur, spec["title"]),
            "assets": assets, "liabilities": liabs,
            "total_assets": ta, "total_liab": tl,
        }
    # ── 统一换算成 $B(十亿美元), 全部用当天最新汇率(Chao 要求横向可比) ──
    usd_per_eur = None
    if to_usd:
        try:
            from fetchers.fred import fetch_fred_latest
            jpy, _ = fetch_fred_latest("DEXJPUS")   # 日元/美元(如 147.5)
            cny, _ = fetch_fred_latest("DEXCHUS")   # 人民币/美元(如 7.15)
            usd_per_eur, _ = fetch_fred_latest("DEXUSEU")  # 1欧元=X美元
            # BoJ: 兆¥(1e12¥) → $B: ×1000/jpy
            if "JP" in out and jpy:
                out["JP"] = _usd_convert(out["JP"], 1000.0 / jpy, "兆¥")
            # PBoC: 亿¥(1e8¥) → $B: ×0.1/cny
            if "CN" in out and cny:
                out["CN"] = _usd_convert(out["CN"], 0.1 / cny, "亿¥")
            # 记录换算汇率(可溯源)
            out["_fx"] = {"USDJPY": jpy, "USDCNY": cny, "USDEUR": usd_per_eur}
        except Exception as e:
            out["_fx_error"] = str(e)

    # ── ECB(欧洲央行): 独立源, 用同一当天 USD/EUR 折算 ──
    try:
        out["ECB"] = fetch_ecb_balance_sheet(to_usd=to_usd, usd_per_eur=usd_per_eur)
    except Exception as e:
        out["_ecb_error"] = str(e)

    # ── 总资产/总负债强制加总: 补"其他"差额项(Chao 要求, 如中国总负债7170≠5798+891.5) ──
    def _add_residual(blk):
        """若有总额且明细未加满, 补一行'其他(差额)'使明细总和=总额。子项(sub)不计入加和。"""
        for sec, tot_key in (("assets", "total_assets"), ("liabilities", "total_liab")):
            tot = blk.get(tot_key)
            lines = blk.get(sec) or []
            if not tot or tot.get("value") is None or not lines:
                continue
            summed = sum(x["value"] for x in lines if x.get("value") is not None and not x.get("sub"))
            resid = round(tot["value"] - summed, 1)
            # 只在差额显著(>总额0.5%且>1)时补, 避免舍入噪音
            if abs(resid) > max(1.0, abs(tot["value"]) * 0.005):
                lines.append({"name": "其他 Other（差额）", "value": resid,
                              "delta": None, "pct": None, "sub": False})
                blk[sec] = lines
    for cc in ("US", "JP", "CN", "ECB"):
        if cc in out and isinstance(out[cc], dict):
            _add_residual(out[cc])
    return out


# ─────────── 外国官方在纽约联储托管的美债 (Fed H.4.1) ───────────
# Chao 需求(2026-08, 附FT图): 外国央行/官方机构在NY Fed托管的可流通美债。
# 反映外国官方对美债的减持/去美元化趋势(FT图红箭头强调2025-26急跌)。
# 数据源: Fed H.4.1 weekly release HTML(每周四更新), "Securities held in custody
#   for foreign official and international accounts" 段的 "Marketable U.S. Treasury securities" 行。
#   ★FRED 的 WMTSECL 等 series 2012 已停更, 活跃真数据只在 Fed H.4.1 release 本身。
# 单位: 百万美元 → 转 $T(万亿)。绝不编: 抓不到标 status。
FED_H41_URL = "https://www.federalreserve.gov/releases/h41/current/h41.htm"


def _custody_history_fred(start="2026-01-01"):
    """从 FRED WMTSECL1(外国官方托管可流通美债, 周度 as-of Wednesday, 2002至今活跃)
    拉历史序列。返回 [(date, value_$T), ...] 升序。空列表=拉取失败。"""
    try:
        from fetchers.fred import fetch_fred_history
    except Exception:
        from src.fetchers.fred import fetch_fred_history
    raw = fetch_fred_history("WMTSECL1", start=start)  # 单位: 百万美元
    return [(d, round(v / 1e6, 4)) for d, v in raw]     # → $T


def _mspd_maturing_within_1yr(record_date, rows):
    """给定某 record_date 的 MSPD table_3 明细行, 加总"距该日1年内到期"的可交易国债 outstanding。
    outstanding_amt 缺失时用 issued_amt+redeemed_amt(redeemed为负)兜底。单位: 百万美元 → 返回 $T。"""
    from datetime import datetime
    try:
        rec = datetime.strptime(record_date, "%Y-%m-%d")
    except Exception:
        return None
    total = 0.0
    for r in rows:
        md = r.get("maturity_date")
        if not md or md == "null":
            continue
        try:
            mdt = datetime.strptime(md, "%Y-%m-%d")
        except Exception:
            continue
        days = (mdt - rec).days
        if 0 <= days <= 366:
            oa = r.get("outstanding_amt")
            if oa in ("null", None, ""):
                try:
                    oa = float(r.get("issued_amt", 0) or 0) + float(r.get("redeemed_amt", 0) or 0)
                except Exception:
                    oa = 0
            else:
                try:
                    oa = float(oa)
                except Exception:
                    oa = 0
            total += oa
    return round(total / 1e6, 4)  # 百万 → 万亿($T)


def fetch_maturing_treasury(cache_path=None):
    """私营部门(含Fed)持有的、1年内到期需展期的【可交易国债】规模, 月末采样。
    ★口径: MSPD table_3(逐券明细) 按 maturity_date 筛"距 record_date ≤366天"的 Marketable 券加总 outstanding。
    ★注意: 该口径为总量(含 Fed SOMA + 私营), 未单独剔除 Fed 持仓(dashboard 明确标注)。
    返回 {history_long[(YYYY-MM,$T)] 2001起, history_recent[(YYYY-MM,$T)] 近两年, value, as_of, status, source}。
    有本地缓存(data/maturing_treasury.json)则增量更新, 只补最新缺失月, 避免每次全量拉。"""
    import os, json, requests
    from datetime import datetime, timedelta
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "maturing_treasury.json")
    BASE = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
            "/v1/debt/mspd/mspd_table_3_market")
    FIELDS = "record_date,maturity_date,outstanding_amt,issued_amt,redeemed_amt,security_type_desc"

    # 1) 读缓存
    cached = {}
    if os.path.exists(cache_path):
        try:
            cj = json.load(open(cache_path))
            cached = {d: v for d, v in cj.get("monthly", [])}
        except Exception:
            cached = {}

    # 2) 按年拉(增量: 已缓存年份的所有月都齐则跳过, 只拉当前年+缺失年)
    def _pull_year(year):
        out = {}
        page = 1
        while True:
            # ★Treasury API: filter 的 : 和 , 是语法字符不可编码; 仅 page[] 方括号需编码; page size 上限 10000。
            url = (f"{BASE}?filter=record_date:gte:{year}-01-01,record_date:lte:{year}-12-31"
                   f"&fields={FIELDS}&page%5Bsize%5D=10000&page%5Bnumber%5D={page}")
            try:
                resp = requests.get(url, timeout=40)
                data = resp.json().get("data", [])
            except Exception:
                break
            if not data:
                break
            # 按 record_date 分组
            by_date = {}
            for r in data:
                by_date.setdefault(r["record_date"], []).append(r)
            for rd, rows in by_date.items():
                out.setdefault(rd, []).extend(rows)
            if len(data) < 10000:
                break
            page += 1
        return out

    now = datetime.utcnow()
    start_year = 2001
    monthly = dict(cached)  # YYYY-MM-DD → $T
    # 需要拉的年份: 未缓存足月的年 + 当前年(总是刷新最新)
    cached_years = {}
    for d in cached:
        cached_years[d[:4]] = cached_years.get(d[:4], 0) + 1
    for year in range(start_year, now.year + 1):
        y = str(year)
        # 已有>=11个月且非当前年 → 跳过(历史不变)
        if cached_years.get(y, 0) >= 11 and year < now.year:
            continue
        yr_rows = _pull_year(year)
        for rd, rows in yr_rows.items():
            val = _mspd_maturing_within_1yr(rd, rows)
            if val is not None:
                monthly[rd] = val

    if not monthly:
        return {"history_long": [], "history_recent": [], "value": None,
                "as_of": None, "status": "MSPD 无数据",
                "source": "US Treasury MSPD table 3 (marketable, maturity≤1yr)"}

    # 3) 排序 + 写缓存
    items = sorted(monthly.items())
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    json.dump({"monthly": items, "updated": now.strftime("%Y-%m-%d"),
               "source": "US Treasury MSPD table 3 (marketable, maturity within 1yr, 含Fed+私营)"},
              open(cache_path, "w"), ensure_ascii=False, indent=1)

    # 4) 长图(全部, YYYY-MM) + 近两年图
    hist_long = [(d[:7], v) for d, v in items]
    cutoff = (now - timedelta(days=760)).strftime("%Y-%m")
    hist_recent = [(m, v) for m, v in hist_long if m >= cutoff]
    last_d, last_v = items[-1]
    return {
        "history_long": hist_long,          # 2001至今月末
        "history_recent": hist_recent,      # 近两年月末
        "value": last_v, "as_of": last_d,
        "status": "ok",
        "source": "US Treasury MSPD table 3 (可交易国债·1年内到期·含Fed+私营)",
    }


def fetch_foreign_custody_ust():
    """抓外国官方托管可流通美债(当前值+周变动+历史序列)。
    ★口径统一走 FRED WMTSECL1(周度, 2002至今活跃, 单一可回溯口径), H.4.1 HTML 仅补总托管。
    返回 {value($T), as_of, wow_delta_bn, wow_pct, total_custody_tn, history[(date,$T)], status, source}。"""
    import re
    import requests
    # === 主口径: FRED WMTSECL1 历史序列 ===
    # 短期图=近12个月; 长期图=近10年(均周度点)
    from datetime import datetime, timedelta
    _start_short = (datetime.utcnow() - timedelta(days=380)).strftime("%Y-%m-%d")   # ~12个月前
    _start_long = (datetime.utcnow() - timedelta(days=3660)).strftime("%Y-%m-%d")   # ~10年前
    hist = _custody_history_fred(start=_start_short)          # 短期(12月)
    hist_long = _custody_history_fred(start=_start_long)       # 长期(10年)
    hist_2008 = _custody_history_fred(start="2007-07-04")      # 2007至今全周期(WMTSECL1序列2002-12建库但2007-07-04才第一个真实非零值, 之前237点为0=统计未开始, 起点取真实数据起点避免贴地假横线)
    fred_val = fred_as_of = fred_wow_bn = fred_wow_pct = None
    if len(hist) >= 2:
        fred_as_of, fred_val = hist[-1]
        prev = hist[-2][1]
        fred_wow_bn = round((fred_val - prev) * 1000, 1)          # $T→$B
        fred_wow_pct = round((fred_val - prev) / prev * 100, 2) if prev else None
    # === 补充: H.4.1 HTML 拿总托管(含机构债/MBS) ===
    total_custody_tn = None
    try:
        r = requests.get(FED_H41_URL,
                         headers={"User-Agent": "EcoVolChecker research (contact ANONYMIZED_EMAIL_ADDRESS_0_2)"},
                         timeout=30)
        if r.status_code == 200:
            txt = re.sub(r"<[^>]+>", " ", r.text)
            txt = re.sub(r"&#xa0;", " ", txt)
            txt = re.sub(r"\s+", " ", txt)
            i = txt.find("held in custody for foreign official")
            if i >= 0:
                seg = txt[i:i + 700]
                mt = re.search(r"international accounts\s+([\d,]+)", seg)
                if mt:
                    total_custody_tn = round(int(mt.group(1).replace(",", "")) / 1e6, 3)
    except Exception:
        pass  # 总托管拿不到不阻塞主口径

    # === 构造返回: FRED 为主口径(历史+当前+周环比), H.4.1 补总托管 ===
    if fred_val is not None:
        return {
            "value": round(fred_val, 3),                    # $T
            "as_of": fred_as_of,
            "wow_delta_bn": fred_wow_bn,                    # 周变动 十亿美元
            "wow_pct": fred_wow_pct,
            "total_custody_tn": total_custody_tn,
            "history": hist,                               # [(date,$T)] 升序, 近12个月周点(短期图)
            "history_long": hist_long,                     # [(date,$T)] 升序, 近10年周点(长期图)
            "history_2008": hist_2008,                     # [(date,$T)] 升序, 2008至今周点(全周期结构图)
            "status": "ok",
            "source": "FRED WMTSECL1 (Fed H.4.1 custody, weekly Wed)",
        }
    return {"value": None, "as_of": None, "history": hist, "history_long": hist_long,
            "history_2008": hist_2008,
            "total_custody_tn": total_custody_tn,
            "status": "FRED WMTSECL1 无数据"}


def fetch_custody_acceleration(weeks=26):
    """外国官方托管美债(Fed H.4.1 WMTSECL1)超短期【加速度】分析。
    ★数据颗粒度=周度(每周三 as-of), 无日度。故 trailing 7/14/28/56 天 ≡ 1/2/4/8 周(诚实标注)。
    加速度 = 二阶差分(变化的变化), 零轴上=流入加速/流出减速, 零轴下=流出加速/流入减速。
      7天(1周)  = v[i] - 2·v[i-1] + v[i-2]
      14天(2周) = v[i] - 2·v[i-2] + v[i-4]
      28天(4周) = v[i] - 2·v[i-4] + v[i-8]
      56天(8周) = v[i] - 2·v[i-8] + v[i-16]
    主平滑指标 = EMA(3周)斜率的差分(压制周度噪声, 拐点更干净)。
    ★fredgraph CSV 端点对 requests 偶发超时 → 优先带 key FRED API(fetch_fred_history)。
    返回 {points:[{date, a7, a14, a28, a56, ema_accel}], asof, unit, source, status, weeks}。
    绝不编: 拉不到→points=[] + status。单位=百万美元($M)。默认 weeks=26(过去约6个月)。
    """
    import datetime as _dt
    # 拉够长的历史(算 EMA + 4周二阶差分需预热, 多取 20 周余量)
    need = weeks + 20
    cosd = (_dt.date.today() - _dt.timedelta(weeks=need + 4)).strftime("%Y-%m-%d")
    pts = []
    # ★通道1: 项目带 key FRED API(fetch_fred_history) —— 现有 custody 板块一直用它, 最稳
    try:
        try:
            from fetchers.fred import fetch_fred_history
        except Exception:
            from src.fetchers.fred import fetch_fred_history
        raw = fetch_fred_history("WMTSECL1", start=cosd)  # 单位: 百万美元
        for d, v in raw:
            try:
                pts.append((str(d).strip(), float(v)))
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    # 通道2: curl 子进程回退(fredgraph CSV, 该端点在本环境偶发超时)
    if len(pts) < 10:
        import subprocess
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=WMTSECL1&cosd={cosd}"
        text = ""
        for _attempt in range(3):
            try:
                r = subprocess.run(["curl", "-s", url, "--max-time", "30",
                                    "-H", "User-Agent: Mozilla/5.0"],
                                   capture_output=True, text=True, timeout=38)
                if r.returncode == 0 and r.stdout and "observation_date" in r.stdout:
                    text = r.stdout
                    break
            except Exception:
                pass
        if text:
            pts = []
            for ln in text.strip().splitlines()[1:]:
                if "," not in ln:
                    continue
                d, v = ln.split(",", 1)
                v = v.strip()
                if v and v != ".":
                    try:
                        pts.append((d.strip(), float(v)))
                    except ValueError:
                        pass
    if len(pts) < 10:
        return {"points": [], "asof": None, "unit": "$M",
                "source": "FRED WMTSECL1 (Fed H.4.1 custody, weekly Wed)",
                "status": "拉取失败(端点超时)", "weeks": weeks}
    dates = [p[0] for p in pts]
    v = [p[1] for p in pts]
    n = len(v)
    # EMA(3周) + 斜率(一阶差) + 斜率差分(加速度)
    span = 3
    alpha = 2.0 / (span + 1)
    ema = [v[0]]
    for i in range(1, n):
        ema.append(alpha * v[i] + (1 - alpha) * ema[-1])
    ema_slope = [None] + [ema[i] - ema[i - 1] for i in range(1, n)]
    out = []
    for i in range(n):
        rec = {"date": dates[i]}
        rec["a7"] = round(v[i] - 2 * v[i - 1] + v[i - 2], 0) if i >= 2 else None
        rec["a14"] = round(v[i] - 2 * v[i - 2] + v[i - 4], 0) if i >= 4 else None
        rec["a28"] = round(v[i] - 2 * v[i - 4] + v[i - 8], 0) if i >= 8 else None
        rec["a56"] = round(v[i] - 2 * v[i - 8] + v[i - 16], 0) if i >= 16 else None
        # EMA 斜率差分(平滑加速度)
        rec["ema_accel"] = (round(ema_slope[i] - ema_slope[i - 1], 0)
                            if i >= 2 and ema_slope[i] is not None
                            and ema_slope[i - 1] is not None else None)
        out.append(rec)
    # 只保留最近 weeks 周(有完整加速度的)
    out = [r for r in out if r["a28"] is not None][-weeks:]
    return {"points": out, "asof": dates[-1], "unit": "$M",
            "source": "FRED WMTSECL1 (Fed H.4.1 custody, 周度 as-of Wed)",
            "status": "ok" if out else "无有效加速度点", "weeks": weeks}


def write_custody_notion(cust=None):
    """把外国官方托管美债写入 Notion DB_CUSTODY(周度, 以 as_of 作 title 幂等 upsert)。
    返回写入的 page id 或 None(数据无效/无DB时跳过)。"""
    import config as c
    import notion_writer as nw
    if cust is None:
        cust = fetch_foreign_custody_ust()
    db = c.NOTION_DB.get("custody")
    if not db or cust.get("value") is None or not cust.get("as_of"):
        return None
    props = {
        "托管美债($T)": nw.prop_num(cust.get("value")),
        "周变动($B)": nw.prop_num(cust.get("wow_delta_bn")),
        "周变动(%)": nw.prop_num(cust.get("wow_pct")),
        "托管总额($T)": nw.prop_num(cust.get("total_custody_tn")),
        "数据源": {"rich_text": [{"type": "text", "text": {"content": cust.get("source", "Fed H.4.1")}}]},
    }
    return nw.upsert(db, cust["as_of"], props, title_field="Date")


# ─────────── 分国别持有美债 (US Treasury TIC — Major Foreign Holders) ───────────
# Chao 需求(2026-08): 在"外国官方托管美债"图下方加 日本/中国 各过去10年持有美债折线。
# ★口径区别: 上面 custody 是 NY Fed 托管账户"外国官方合计"; 这里是 TIC 分国别口径
#   (含官方+私人持有, 月度), 权威源=美国财政部 TIC Major Foreign Holders 历史文件。
# 数据源: ticdata.treasury.gov/Publish/mfhhis01.txt (官方历史 TSV, 2000-03 至今, 免key)。
#   ★注意 Publish/mfh.txt 是旧缓存(停在2023-01), 历史+最新都在 mfhhisNN.txt 系列。
# 单位: 十亿美元($B)。绝不编: 抓不到标 status。
TIC_MFH_HIST_URL = "https://ticdata.treasury.gov/Publish/mfhhis01.txt"
_TIC_MON = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _parse_tic_country(raw, country_key):
    """从 TIC mfhhis 文本解析某国月度序列。country_key: 'Japan' / 'China' / 'EU'。
    文件结构: 每个年份块有一"月份行"(Jan..Dec)+"年份行"(Country + 4位年份),
    随后 Japan / 'China, Mainland' 数据行, 按列对齐。返回 {'YYYY-MM': value_$B} 。
    ★'EU' = 欧元区主要成员国加总(德/法/意/荷/比/卢/爱/西/芬), 逐月求和(TIC 无欧盟合计行;
      注: Belgium 含 Euroclear 托管, 属 TIC 口径固有特性)。"""
    import re
    # 欧元区主要成员(精确行名匹配, 避免误伤脚注文本)
    EU_MEMBERS = {"Germany", "France", "Italy", "Netherlands", "Belgium",
                  "Luxembourg", "Ireland", "Spain", "Finland",
                  "Belgium-Luxembourg"}
    lines = raw.replace("\r", "").split("\n")
    series = {}          # 单国: {月:值}
    eu_series = {}       # EU: {月: 累加值}
    cur_months = cur_years = None
    for l in lines:
        cells = [c.strip() for c in l.split("\t")]
        # 月份行: 至少含 6 个月份缩写
        monpos = {i: _TIC_MON[c] for i, c in enumerate(cells) if c in _TIC_MON}
        if len(monpos) >= 6:
            cur_months, cur_years = monpos, None
            continue
        # 年份行: 第0列 == 'Country', 其余为4位年份
        if cells and cells[0] == "Country":
            cur_years = {i: int(c) for i, c in enumerate(cells) if re.fullmatch(r"\d{4}", c)}
            continue
        name = cells[0].strip('"').strip() if cells else ""
        if country_key == "EU":
            matched = name in EU_MEMBERS
        elif country_key == "Japan":
            matched = (name == "Japan")
        elif country_key == "China":
            matched = name.startswith("China")
        else:
            matched = False
        if matched and cur_months and cur_years:
            for i, mm in cur_months.items():
                yy = cur_years.get(i)
                if not yy or i >= len(cells):
                    continue
                v = cells[i].replace(",", "").strip()
                try:
                    val = float(v)
                except ValueError:
                    continue
                mk = f"{yy:04d}-{mm:02d}"
                if country_key == "EU":
                    eu_series[mk] = eu_series.get(mk, 0.0) + val
                else:
                    series[mk] = val
    return eu_series if country_key == "EU" else series


def fetch_country_ust_holdings(years=10):
    """抓 日本 / 中国 / 欧盟(欧元区加总) 分国别持有美债的月度序列(近 N 年 + 2008起长历史)。
    源: 美国财政部 TIC Major Foreign Holders 历史文件(官方, 月度, $B, 覆盖2000-至今)。
    返回 {"Japan":{...}, "China":{...}, "EU":{...}} 每个:
      {name, flag, series:[(YYYY-MM, $B),...]升序(近N年), series_long:[...](2008起长历史),
       latest:(month,val), first:(month,val), delta_bn, delta_pct, high, low, status, source}。
    ★EU = 欧元区主要成员(德/法/意/荷/比/卢/爱/西/芬)逐月加总(TIC 无欧盟合计行; Belgium 含 Euroclear 托管)。
    绝不编: 解析失败留空 series + status。"""
    import requests
    import datetime
    out = {}
    meta = {"Japan": ("日本", "🇯🇵"), "China": ("中国大陆", "🇨🇳"),
            "EU": ("欧盟(欧元区加总)", "🇪🇺")}
    cutoff = (datetime.date.today().replace(day=1) -
              datetime.timedelta(days=int(years * 365.25) + 45)).strftime("%Y-%m")
    long_cutoff = "2008-01"  # 2008 起长历史
    raw = None
    try:
        r = requests.get(TIC_MFH_HIST_URL,
                         headers={"User-Agent": "Mozilla/5.0 (EcoVolChecker research)"},
                         timeout=40)
        if r.status_code == 200 and "MAJOR FOREIGN HOLDERS" in r.text:
            raw = r.text
    except Exception:
        raw = None
    for key, (zh, flag) in meta.items():
        if not raw:
            out[key] = {"name": zh, "flag": flag, "series": [], "series_long": [],
                        "status": "未找到", "source": "US Treasury TIC MFH"}
            continue
        s = _parse_tic_country(raw, key)
        pts = sorted((m, round(v, 1)) for m, v in s.items() if m >= cutoff)
        pts_long = sorted((m, round(v, 1)) for m, v in s.items() if m >= long_cutoff)
        if len(pts) < 2:
            out[key] = {"name": zh, "flag": flag, "series": pts, "series_long": pts_long,
                        "status": "数据不足", "source": "US Treasury TIC MFH"}
            continue
        first_m, first_v = pts[0]
        last_m, last_v = pts[-1]
        vals = [v for _, v in pts]
        out[key] = {
            "name": zh, "flag": flag, "series": pts, "series_long": pts_long,
            "latest": (last_m, last_v), "first": (first_m, first_v),
            "delta_bn": round(last_v - first_v, 1),
            "delta_pct": round((last_v - first_v) / first_v * 100, 1) if first_v else None,
            "high": round(max(vals), 1), "low": round(min(vals), 1),
            "status": "ok",
            "source": "US Treasury TIC Major Foreign Holders (monthly)",
        }
    return out


# ─────────── 美国国债拍卖 (Treasury Auctions) ───────────
TREASURY_AUCTION_API = ("https://api.fiscaldata.treasury.gov/services/api/"
                        "fiscal_service/v1/accounting/od/auctions_query")
# 关注的关键券种(Note/Bond, 反映市场对中长债需求; Bill 是货币工具口径不同, 不纳入)
AUCTION_KEY_TERMS = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]


def _auc_num(x):
    """把 API 字符串数字转 float, 'null'/空 → None。"""
    if x in (None, "", "null"):
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def fetch_treasury_auctions(history_days=420):
    """抓美国财政部国债拍卖数据(fiscaldata 官方 API, 免费无 key)。
    每个关键券种(2/3/5/7/10/20/30Y Note&Bond): 最新 + 过去3次(共4次) + 下次拍卖日程。
    返回 {terms: {term: {history:[...], next:{...}|None}}, upcoming:[...], as_of, status, source}。
    每次拍卖字段: auction_date, security_type, offering_bn, accepted_bn, bid_to_cover,
    high_yield, indirect_pct(间接投标占比=外国央行代理需求), issue_date。"""
    import requests
    import datetime
    from collections import defaultdict
    start = (datetime.date.today() - datetime.timedelta(days=history_days)).isoformat()
    today = datetime.date.today()
    try:
        r = requests.get(TREASURY_AUCTION_API,
                         params={"sort": "-auction_date", "page[size]": "800",
                                 "filter": f"auction_date:gte:{start}"},
                         timeout=50)
        if r.status_code != 200:
            return {"terms": {}, "upcoming": [], "as_of": None, "status": f"HTTP {r.status_code}"}
        rows = r.json().get("data", [])
    except Exception as e:
        return {"terms": {}, "upcoming": [], "as_of": None, "status": f"错误:{e}"}

    def pack(x):
        offer = _auc_num(x.get("offering_amt"))
        acc = _auc_num(x.get("total_accepted"))
        ind = _auc_num(x.get("indirect_bidder_accepted"))
        # 间接投标占比 = 间接中标 / 总中标(近似外国央行/官方代理需求份额)
        ind_pct = round(ind / acc * 100, 1) if (ind and acc) else None
        return {
            "auction_date": x.get("auction_date"),
            "security_type": x.get("security_type"),
            "security_term": x.get("security_term"),
            "offering_bn": round(offer / 1e9, 1) if offer else None,
            "accepted_bn": round(acc / 1e9, 1) if acc else None,
            "bid_to_cover": _auc_num(x.get("bid_to_cover_ratio")),
            "high_yield": _auc_num(x.get("high_yield")),
            "indirect_pct": ind_pct,
            "issue_date": x.get("issue_date"),
            "reopening": x.get("reopening"),
        }

    done = defaultdict(list)     # term → 已完成(有中标结果)
    future = defaultdict(list)   # term → 未来(auction_date>=today 且未开标)
    for x in rows:
        st, term, ad = x.get("security_type"), x.get("security_term"), x.get("auction_date")
        if st not in ("Note", "Bond") or term not in AUCTION_KEY_TERMS or not ad:
            continue
        d = datetime.date.fromisoformat(ad)
        has_result = x.get("high_yield") not in (None, "null", "")
        if d >= today and not has_result:
            future[term].append(pack(x))
        elif has_result:
            done[term].append(pack(x))

    terms = {}
    latest_date = None
    for term in AUCTION_KEY_TERMS:
        hist = sorted(done[term], key=lambda a: a["auction_date"], reverse=True)[:4]  # 最新+过去3
        nxt = sorted(future[term], key=lambda a: a["auction_date"])
        if not hist and not nxt:
            continue
        if hist:
            ld = hist[0]["auction_date"]
            if latest_date is None or ld > latest_date:
                latest_date = ld
        terms[term] = {"history": hist, "next": nxt[0] if nxt else None}

    # 全局最近一次拍卖日程(所有关键券种混排取最近未来)
    allf = [f for t in future for f in future[t]]
    upcoming = sorted(allf, key=lambda a: a["auction_date"])[:6]
    return {
        "terms": terms,
        "upcoming": upcoming,
        "as_of": latest_date,
        "status": "ok" if terms else "无拍卖数据",
        "source": "US Treasury fiscaldata.treasury.gov auctions_query",
    }


def write_auctions_notion(auc=None):
    """把国债拍卖写入 Notion DB_AUCTIONS(每次拍卖一行, cusip+日期作幂等 key)。
    以 '券种 拍卖日' 作 title。返回写入行数。"""
    import config as c
    import notion_writer as nw
    if auc is None:
        auc = fetch_treasury_auctions()
    db = c.NOTION_DB.get("auctions")
    if not db or auc.get("status") != "ok":
        return 0
    n = 0
    for term, blk in auc["terms"].items():
        for a in blk["history"]:
            title = f"{a['security_type']} {term} {a['auction_date']}"
            props = {
                "券种": {"select": {"name": f"{a['security_type']} {term}"}},
                "拍卖日": {"date": {"start": a["auction_date"]}},
                "发行规模($B)": nw.prop_num(a.get("offering_bn")),
                "中标额($B)": nw.prop_num(a.get("accepted_bn")),
                "中标率(BTC)": nw.prop_num(a.get("bid_to_cover")),
                "最高中标收益率(%)": nw.prop_num(a.get("high_yield")),
                "间接投标占比(%)": nw.prop_num(a.get("indirect_pct")),
            }
            try:
                nw.upsert(db, title, props, title_field="Auction")
                n += 1
            except Exception:
                pass
    return n


# ─────────── 货币供应量 M0/M1/M2 ───────────
MONEY_SUPPLY_OVERRIDE = os.path.join(os.path.dirname(__file__), "..", "data", "money_supply_override.json")
# FRED fredgraph.csv 直连(免 key), 取最后一行=最新
_FRED_MS = {"m1": "M1SL", "m2": "M2SL", "m0": "BOGMBASE"}


def _fred_latest(series_id):
    """curl FRED fredgraph.csv 取最新 (date, value)。失败返回 (None, None)。"""
    import requests
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=20)
        if r.status_code != 200:
            return None, None
        lines = [ln for ln in r.text.strip().splitlines() if "," in ln]
        # 从末尾找最后一个有数值的行(FRED 用 '.' 表示缺失)
        for ln in reversed(lines[1:]):
            d, v = ln.split(",", 1)
            v = v.strip()
            if v and v != ".":
                try:
                    return d.strip()[:7], round(float(v), 1)
                except ValueError:
                    continue
        return None, None
    except Exception:
        return None, None


def fetch_money_supply(to_usd=True):
    """三国货币供应量 M0/M1/M2(+日本 M3)。
    US: FRED 直连(自动最新); JP/CN: 无稳定免费 API→读 money_supply_override.json(weekly cron agent 用官方源更新)。
    to_usd=True(默认): 三国统一折算成 $B(十亿美元)横向可比,汇率走 FRED DEXJPUS/DEXCHUS(与央行资负表同源);
      本币原值保留在 orig_m0/orig_m1/orig_m2/orig_m3 + orig_unit 可溯源。
    返回 {"US":{...}, "JP":{...}, "CN":{...}}, 每国:
      {name, flag, unit, as_of, m0, m0_label, m1, m2, (m3), source, (orig_*), (_fx)}
    绝不编: US 抓不到该项留 None; JP/CN 缺 override 文件则该国留空 status。折不动(缺汇率)则保留本币并标 orig_unit。"""
    import json
    out = {}

    # 美国: FRED 直连. M0 无官方概念→用基础货币 BOGMBASE 代理. 本身就是 $B, 无需折算
    us = {"name": "美国 Fed", "flag": "🇺🇸", "unit": "$B",
          "m0_label": "基础货币 Monetary Base",
          "source": "FRED (M1SL/M2SL/BOGMBASE), 月度"}
    as_ofs = []
    for k, sid in _FRED_MS.items():
        d, v = _fred_latest(sid)
        us[k] = v
        if d:
            as_ofs.append(d)
    us["as_of"] = max(as_ofs) if as_ofs else None
    if us.get("m2") is None and us.get("m1") is None:
        us["status"] = "未找到"
    out["US"] = us

    # 日本 / 中国: 读 override(本币)
    try:
        ov = json.load(open(MONEY_SUPPLY_OVERRIDE))
    except Exception:
        ov = {}
    jp_meta = {"name": "日本 BoJ", "flag": "🇯🇵"}
    cn_meta = {"name": "中国 PBoC", "flag": "🇨🇳"}
    for cc, meta in (("JP", jp_meta), ("CN", cn_meta)):
        blk = ov.get(cc)
        if isinstance(blk, dict) and (blk.get("m2") is not None or blk.get("m1") is not None):
            row = dict(meta)
            row.update({k: blk.get(k) for k in ("unit", "as_of", "m0", "m0_label", "m1", "m2", "m3", "source")})
            out[cc] = row
        else:
            out[cc] = dict(meta, status="未找到")

    # ── 统一折算成 $B(十亿美元)横向可比 ──
    if to_usd:
        try:
            from fetchers.fred import fetch_fred_latest
            jpy, _ = fetch_fred_latest("DEXJPUS")   # 日元/美元(如 147.5)
            cny, _ = fetch_fred_latest("DEXCHUS")   # 人民币/美元(如 7.15)
            # 万亿本币 → $B: (值×1e12 本币) / 汇率 / 1e9 = 值×1000/汇率
            def _to_usd_row(row, rate):
                if not rate or row.get("status") == "未找到":
                    return
                factor = 1000.0 / rate
                orig_unit = row.get("unit")
                for k in ("m0", "m1", "m2", "m3"):
                    if row.get(k) is not None:
                        row[f"orig_{k}"] = row[k]           # 保留本币原值
                        row[k] = round(row[k] * factor, 1)  # 折算 $B
                if orig_unit:
                    row["orig_unit"] = orig_unit
                row["unit"] = "$B"
            if "JP" in out and jpy:
                _to_usd_row(out["JP"], jpy)
            if "CN" in out and cny:
                _to_usd_row(out["CN"], cny)
            out["_fx"] = {"USDJPY": jpy, "USDCNY": cny}
        except Exception as e:
            out["_fx_error"] = str(e)
    return out


def fetch_m2_history(months=126, to_usd=True):
    """三国 M2 月度历史序列(默认126月≈10.5年),用于折线图。
    ★折 $B 用【当天 crawl 的最新美元汇率】统一折算全序列(Chao 2026-08 要求):
      不再用各月历史汇率, 而是抓当日最新 DEXJPUS/DEXCHUS, 整条序列都乘同一汇率。
      → 曲线形状纯粹反映各国本币 M2 增长(剥离汇率波动), 反映真实"放水力度"横向对比。
    源: US=FRED M2SL / JP=BOJ stat-search CSV(第10列亿円,Shift_JIS) / CN=东方财富 datacenter API(亿元)。
    返回 {"US":{unit,points:[{date,value},...],orig_unit,latest,source,fx}, "JP":{...}, "CN":{...}}。
    绝不编: 某国抓不到→该国 points=[] + status。汇率抓不到→退回内置 fallback 并标 fx_note。"""
    import requests
    from datetime import datetime, timedelta
    cosd = (datetime.utcnow() - timedelta(days=int(months * 30.5) + 40)).strftime("%Y-%m-01")

    def _fred_series(sid, start):
        """拉 FRED 月度全序列 [(YYYY-MM, float)],升序。"""
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}", timeout=25)
            if r.status_code != 200:
                return []
            out = []
            for ln in r.text.strip().splitlines()[1:]:
                if "," not in ln:
                    continue
                d, v = ln.split(",", 1)
                v = v.strip()
                if v and v != ".":
                    try:
                        out.append((d.strip()[:7], float(v)))
                    except ValueError:
                        pass
            return out
        except Exception:
            return []

    # ★当天最新汇率(全序列统一折算, 不用各月历史汇率)
    jpy_now = cny_now = None
    try:
        from fetchers.fred import fetch_fred_latest
        jpy_now, _ = fetch_fred_latest("DEXJPUS")   # 日元/美元
        cny_now, _ = fetch_fred_latest("DEXCHUS")   # 人民币/美元
    except Exception:
        pass
    # fallback: 若 fetch_fred_latest 不可用, 从 fredgraph 序列取最后一个有效值
    if not jpy_now:
        _js = _fred_series("DEXJPUS", cosd)
        jpy_now = _js[-1][1] if _js else 157.54
    if not cny_now:
        _cs = _fred_series("DEXCHUS", cosd)
        cny_now = _cs[-1][1] if _cs else 6.7474

    out = {}
    # ── 美国: FRED M2SL, 本身 $B ──
    us_pts = _fred_series("M2SL", cosd)
    out["US"] = {
        "name": "美国 Fed", "flag": "🇺🇸", "unit": "$B",
        "orig_unit": "$B",
        "points": [{"date": d, "value": round(v, 1)} for d, v in us_pts[-months:]],
        "source": "FRED M2SL 月度",
    }

    # ── 日本: BOJ stat-search CSV(Shift_JIS, 第10列 M2存量亿円) ──
    jp_pts = []
    try:
        r = requests.get("https://www.stat-search.boj.or.jp/ssi/mtshtml/csv/md02_m_1_en.csv", timeout=30)
        if r.status_code == 200:
            text = r.content.decode("shift_jis", errors="ignore")
            for ln in text.splitlines():
                cols = ln.split(",")
                if len(cols) < 10:
                    continue
                dt = cols[0].strip()
                if "/" not in dt:
                    continue
                y, m = dt.split("/")[:2]
                if not (y.isdigit() and m.isdigit()):
                    continue
                raw = cols[9].strip()
                try:
                    oku = float(raw)  # 亿円
                except ValueError:
                    continue
                mon = f"{y}-{int(m):02d}"
                trillion_yen = oku / 10000.0  # 亿円→万亿円
                jp_pts.append((mon, trillion_yen))
    except Exception:
        pass
    jp_pts = jp_pts[-months:]
    out["JP"] = {
        "name": "日本 BoJ", "flag": "🇯🇵", "unit": "$B" if to_usd else "万亿円",
        "orig_unit": "万亿円",
        "points": [], "source": "BOJ Time-Series (Money Stock M2 存量, 月度)",
    }
    for mon, tri in jp_pts:
        val = tri
        if to_usd:
            val = round(tri * 1000.0 / jpy_now, 1)  # 万亿円→$B, 全序列用当天最新汇率
        out["JP"]["points"].append({"date": mon, "value": round(val, 1), "orig": round(tri, 1)})

    # ── 中国: 东方财富 datacenter API(亿元) ──
    cn_pts = []
    try:
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?columns=TIME,BASIC_CURRENCY"
               "&pageSize=400&pageNumber=1&sortColumns=REPORT_DATE&sortTypes=1&reportName=RPT_ECONOMY_CURRENCY_SUPPLY")
        r = requests.get(url, headers={"Referer": "https://data.eastmoney.com/", "User-Agent": "Mozilla/5.0"}, timeout=25)
        if r.status_code == 200:
            rows = (r.json().get("result") or {}).get("data") or []
            for row in rows:
                t = str(row.get("TIME", ""))  # "2026年06月份"
                m2 = row.get("BASIC_CURRENCY")
                if m2 is None:
                    continue
                import re as _re
                mt = _re.search(r"(\d{4})\D+(\d{1,2})", t)
                if not mt:
                    continue
                mon = f"{mt.group(1)}-{int(mt.group(2)):02d}"
                wan_yi = float(m2) / 10000.0  # 亿元→万亿元
                cn_pts.append((mon, wan_yi))
    except Exception:
        pass
    cn_pts = cn_pts[-months:]
    out["CN"] = {
        "name": "中国 PBoC", "flag": "🇨🇳", "unit": "$B" if to_usd else "万亿元",
        "orig_unit": "万亿元",
        "points": [], "source": "东方财富 datacenter (PBoC 口径 M2, 月度)",
    }
    for mon, wy in cn_pts:
        val = wy
        if to_usd:
            val = round(wy * 1000.0 / cny_now, 1)  # 万亿元→$B, 全序列用当天最新汇率
        out["CN"]["points"].append({"date": mon, "value": round(val, 1), "orig": round(wy, 1)})

    # 记录本次折算所用的当天汇率(可溯源, 供 dashboard 说明)
    if to_usd:
        out["_fx"] = {"USDJPY": round(jpy_now, 4), "USDCNY": round(cny_now, 4)}

    for cc in ("US", "JP", "CN"):
        blk = out[cc]
        if blk["points"]:
            blk["latest"] = blk["points"][-1]
        else:
            blk["status"] = "未找到"
    return out


def write_money_supply_notion(ms=None):
    """把三国货币供应量写入 Notion DB_MONEY_SUPPLY(每国一行, '国家 as_of' 作 title 幂等)。
    返回写入行数。DB id 缺失或无数据则返回 0。"""
    import config as c
    import notion_writer as nw
    db = c.NOTION_DB.get("money_supply")
    if not db:
        return 0
    ms = ms or fetch_money_supply()
    n = 0
    for cc in ("US", "JP", "CN"):
        d = ms.get(cc) or {}
        if d.get("status") == "未找到" or (d.get("m2") is None and d.get("m1") is None):
            continue
        title = f"{d.get('name', cc)} {d.get('as_of', '')}".strip()
        props = {
            "国家": {"select": {"name": d.get("name", cc)}},
            "口径日期": {"rich_text": [{"text": {"content": str(d.get("as_of", ""))}}]},
            "单位": {"select": {"name": d.get("unit", "")}},
            "M0/基础货币": nw.prop_num(d.get("m0")),
            "M1": nw.prop_num(d.get("m1")),
            "M2": nw.prop_num(d.get("m2")),
            "M3": nw.prop_num(d.get("m3")),
            "来源": {"rich_text": [{"text": {"content": str(d.get("source", ""))[:300]}}]},
        }
        try:
            nw.upsert(db, title, props, title_field="Country")
            n += 1
        except Exception:
            pass
    return n


def fetch_credit_impulse(years=8):
    """三国 Credit Impulse(信贷脉冲)——中期领先指标。

    定义(BIS/学界标准): Credit Impulse = [新增信贷流量的变化] / GDP
      = Δ(信贷流量)/GDP = 信贷存量的二阶差分 / GDP
      衡量的不是债务总量、也不是新增债务, 而是【新增信贷的加速度】。
      领先实体经济约 6-9 个月; 中国信贷脉冲是全球商品/风险资产最强领先指标之一。

    ★口径: 用 BIS 官方 credit-to-GDP ratio (Q*PAM770A, credit to private
      non-financial sector, % of GDP, 季度) 的【二阶差分】近似 Credit Impulse。
      因 GDP 分母变化远慢于信贷, ratio 二阶差分 ≈ Δ信贷流量/GDP(已验证与
      绝对额法方向/拐点完全一致, 数值差<0.2pp)。用 ratio 法的好处:
        ① 三国统一 BIS 口径, 跨国可比(BIS 专门保证国际可比性)
        ② 都到 2025-10, 避免中国季度 GDP 分母序列缺失(FRED 中国 GDP 停在 2023)
        ③ BIS 官方比值, 权威。
    ★频率: BIS 季度数据, 滞后约 1 季(最新到上一季末)。这是全球唯一跨国可比
      的信贷口径, 无周度版本。定位=季度更新的【中期指标】, 领先性足够。
    绝不编: 某国抓不到→该国 points=[] + status="未找到"。

    返回 {"US":{name,flag,points:[{date,ci}],latest,latest_date,signal,source},
          "CN":{...}, "EA":{...}}。signal: strong_pos/pos/neutral/neg/strong_neg。
    """
    import requests
    from datetime import datetime, timedelta
    cosd = (datetime.utcnow() - timedelta(days=int(years * 365) + 400)).strftime("%Y-%m-01")

    def _fred_ratio(sid):
        """拉 BIS credit-to-GDP ratio 季度序列 [(YYYY-MM-DD, float)] 升序。
        优先用项目带 key 的 FRED API 通道(稳); 失败回退免 key fredgraph CSV。"""
        # 通道1: 带 key API (fetchers.fred.fetch_fred_history) —— 更稳
        try:
            from fetchers.fred import fetch_fred_history
            h = fetch_fred_history(sid, start=cosd)
            if h:
                out = []
                for d, v in h:
                    try:
                        out.append((str(d).strip(), float(v)))
                    except (ValueError, TypeError):
                        pass
                if out:
                    return out
        except Exception:
            pass
        # 通道2: 免 key fredgraph CSV 回退
        try:
            r = requests.get(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={cosd}",
                timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return []
            out = []
            for ln in r.text.strip().splitlines()[1:]:
                if "," not in ln:
                    continue
                d, v = ln.split(",", 1)
                v = v.strip()
                if v and v != ".":
                    try:
                        out.append((d.strip(), float(v)))
                    except ValueError:
                        pass
            return out
        except Exception:
            return []

    def _impulse(ratio):
        """ratio 二阶差分 → Credit Impulse(pp of GDP)。"""
        r = [(d, v) for d, v in ratio if v is not None]
        out = []
        for i in range(2, len(r)):
            d = r[i][0]
            ci = (r[i][1] - r[i - 1][1]) - (r[i - 1][1] - r[i - 2][1])
            out.append({"date": d, "ci": round(ci, 2)})
        return out

    def _signal(ci):
        if ci is None:
            return "unknown"
        if ci >= 0.8:
            return "strong_pos"
        if ci >= 0.15:
            return "pos"
        if ci <= -0.8:
            return "strong_neg"
        if ci <= -0.15:
            return "neg"
        return "neutral"

    spec = {
        "US": ("美国", "🇺🇸", "QUSPAM770A"),
        "CN": ("中国", "🇨🇳", "QCNPAM770A"),
        "EA": ("欧元区", "🇪🇺", "QXMPAM770A"),
        "JP": ("日本", "🇯🇵", "QJPPAM770A"),
    }
    # 长历史(2008至今)序列: 用于粗颗粒度参考图。cosd 提前到 2006(留二阶差分预热)
    cosd_long = "2006-01-01"

    def _fred_ratio_long(sid):
        """拉 2006 起的长序列(供 2008 至今参考图)。
        ★优先带 key FRED API(fetch_fred_history, 稳); fredgraph CSV 端点在本环境偶发超时作回退。"""
        # 通道1: 带 key API
        try:
            from fetchers.fred import fetch_fred_history
            h = fetch_fred_history(sid, start=cosd_long)
            if h:
                out = []
                for d, v in h:
                    try:
                        out.append((str(d).strip(), float(v)))
                    except (ValueError, TypeError):
                        pass
                if out:
                    return out
        except Exception:
            pass
        # 通道2: 免 key fredgraph CSV 回退(带 2 次重试)
        for _attempt in range(2):
            try:
                r = requests.get(
                    f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={cosd_long}",
                    timeout=18, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    continue
                out = []
                for ln in r.text.strip().splitlines()[1:]:
                    if "," not in ln:
                        continue
                    d, v = ln.split(",", 1)
                    v = v.strip()
                    if v and v != ".":
                        try:
                            out.append((d.strip(), float(v)))
                        except ValueError:
                            pass
                if out:
                    return out
            except Exception:
                continue
        return []

    out = {}
    for cc, (name, flag, sid) in spec.items():
        ratio = _fred_ratio(sid)
        pts = _impulse(ratio) if len(ratio) >= 3 else []
        # 长历史(2008起)——粗颗粒度参考
        ratio_long = _fred_ratio_long(sid)
        pts_long_all = _impulse(ratio_long) if len(ratio_long) >= 3 else []
        pts_long = [p for p in pts_long_all if p["date"] >= "2008-01-01"]
        if pts:
            latest = pts[-1]["ci"]
            out[cc] = {
                "name": name, "flag": flag, "points": pts,
                "points_long": pts_long,
                "latest": latest, "latest_date": pts[-1]["date"],
                "signal": _signal(latest),
                "source": f"BIS credit-to-GDP ratio (FRED {sid}), 二阶差分",
                "status": "ok",
            }
        else:
            out[cc] = {
                "name": name, "flag": flag, "points": [],
                "points_long": pts_long,
                "latest": None, "latest_date": None, "signal": "unknown",
                "source": f"BIS credit-to-GDP ratio (FRED {sid})",
                "status": "未找到",
            }
    return out


# ─────────── 国债市场压力三联图 (对齐 Morgan Stanley 三图, 过去3年真实公开数据) ───────────
# Chao 需求(2026-08): 参照 MS 报告三图(收益率+波动性/BrokerTec价差/BrokerTec DV01量),
#   用过去3年【真实公开数据】新增三个图, 竖向排列, 数据进 GitHub + Notion。
# ★诚实边界: MS 图2(BrokerTec日内bid-ask)/图3(BrokerTec周度DV01量)是 Morgan Stanley
#   BrokerTec 专有数据, 无免费公开源(已搜索确认只对付费机构客户开放)。故图2/图3 换成
#   主题对齐的免费公开【压力代理】, 并在 dashboard 明确标注"非BrokerTec原指标"。
# 三图逻辑(与 MS 一致): 波动性↑(MOVE) → 市场压力↑(期限溢价/IG OAS) → 风险传导(曲线利差/HY OAS)。
#   图1 收益率+波动性: DGS10/DGS2(FRED) + MOVE指数(yfinance ^MOVE, ICE专有但Yahoo有免费历史)
#   图2 国债市场压力代理: THREEFYTP10(10yr期限溢价,NY Fed ACM) + BAMLC0A0CM(IG企业债OAS)
#   图3 曲线/信用压力代理: T10Y2Y(10Y-2Y曲线利差) + BAMLH0A0HYM2(HY OAS)
# 全部 FRED 带 key API 优先(fredgraph CSV 本环境偶发超时); MOVE 走 yfinance。绝不编: 抓不到标 status。


def _fred_series_hist(sid, start):
    """拉单个 FRED 序列历史, 带 key API 优先, curl CSV 回退。返回 [(date,val),...] 只含有效点。"""
    pts = []
    try:
        try:
            from fetchers.fred import fetch_fred_history
        except Exception:
            from src.fetchers.fred import fetch_fred_history
        raw = fetch_fred_history(sid, start=start)
        for d, v in raw:
            try:
                if v is not None:
                    pts.append((str(d).strip(), float(v)))
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    if len(pts) < 20:
        import subprocess
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
        for _attempt in range(3):
            try:
                r = subprocess.run(["curl", "-s", url, "--max-time", "30",
                                    "-H", "User-Agent: Mozilla/5.0"],
                                   capture_output=True, text=True, timeout=38)
                if r.returncode == 0 and r.stdout and "observation_date" in r.stdout:
                    pts = []
                    for ln in r.stdout.strip().splitlines()[1:]:
                        if "," not in ln:
                            continue
                        d, v = ln.split(",", 1)
                        v = v.strip()
                        if v and v != ".":
                            try:
                                pts.append((d.strip(), float(v)))
                            except ValueError:
                                pass
                    if len(pts) >= 20:
                        break
            except Exception:
                pass
    return pts


def _fetch_move_history(start):
    """MOVE 指数(ICE BofA, 专有)历史 —— 走 yfinance ^MOVE(Yahoo 免费历史)。
    返回 [(date,val),...]。抓不到返回 []（诚实, 不编）。"""
    try:
        import yfinance as yf
    except Exception:
        return []
    try:
        df = yf.download("^MOVE", start=start, interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or len(df) == 0:
            return []
        c = df["Close"]
        # 多列(MultiIndex)时取第一列
        try:
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
        except Exception:
            pass
        c = c.dropna()
        out = []
        for idx, val in c.items():
            try:
                out.append((idx.date().isoformat(), round(float(val), 2)))
            except Exception:
                pass
        return out
    except Exception:
        return []


def _weekly_resample(pts, agg="last"):
    """把日度 [(date,val)] 降采样到周度(周五 as-of), 减少折线噪声。agg: last|mean|max。
    返回 [(week_date, val)]。"""
    import datetime as _dt
    from collections import defaultdict
    buckets = defaultdict(list)
    for d, v in pts:
        try:
            dt = _dt.date.fromisoformat(d[:10])
        except Exception:
            continue
        # 归到该周的周五
        friday = dt + _dt.timedelta(days=(4 - dt.weekday()))
        buckets[friday.isoformat()].append(v)
    out = []
    for wk in sorted(buckets):
        vs = buckets[wk]
        if agg == "mean":
            val = sum(vs) / len(vs)
        elif agg == "max":
            val = max(vs)
        else:
            val = vs[-1]
        out.append((wk, round(val, 4)))
    return out


def fetch_treasury_stress_panels(years=3):
    """国债市场压力三联图(对齐 Morgan Stanley 三图, 过去 N 年真实公开数据, 竖向排列)。
    返回 {panels:[p1,p2,p3], asof, years, status}。每个 panel:
      {id, title, subtitle, note, unit_left, unit_right, series:[{name,color,axis,points:[{date,v}]}], source}
    全部真实公开数据; 图2/图3 是公开压力代理(非 BrokerTec 原指标, note 明确标注)。
    绝不编: 某序列抓不到→该 series.points=[] + 整体 status 反映缺失。周度降采样降噪。"""
    import datetime as _dt
    start = (_dt.date.today() - _dt.timedelta(days=int(365.3 * years) + 10)).isoformat()

    def _mk(pts, weekly=True, agg="last"):
        if not pts:
            return []
        wp = _weekly_resample(pts, agg=agg) if weekly else pts
        return [{"date": d, "v": v} for d, v in wp]

    # ── 图1: 收益率 + 波动性 ──
    dgs10 = _fred_series_hist("DGS10", start)
    dgs2 = _fred_series_hist("DGS2", start)
    move = _fetch_move_history(start)
    panel1 = {
        "id": "yields_vol",
        "title": "① 美债收益率与波动性",
        "subtitle": "US Treasury Yields & MOVE Volatility",
        "note": "MOVE 指数 = ICE BofA 债券市场隐含波动率(国债版 VIX)。收益率与 MOVE 同向飙升 = 利率风险定价剧烈。",
        "unit_left": "MOVE 指数", "unit_right": "收益率 %",
        "series": [
            {"name": "MOVE 指数", "color": "#c17d6a", "axis": "left",
             "dash": True, "points": _mk(move, agg="last")},
            {"name": "10年收益率", "color": "#6b8fb5", "axis": "right",
             "points": _mk(dgs10, agg="last")},
            {"name": "2年收益率", "color": "#7fa085", "axis": "right",
             "points": _mk(dgs2, agg="last")},
        ],
        "source": "FRED DGS10/DGS2 · ICE BofA MOVE (Yahoo Finance ^MOVE)",
    }

    # ── 图2: 国债市场压力代理(对齐 MS 图2 流动性/成本恶化主题) ──
    tp10 = _fred_series_hist("THREEFYTP10", start)   # 10yr 期限溢价(NY Fed ACM), %
    igoas = _fred_series_hist("BAMLC0A0CM", start)    # IG 企业债 OAS, %
    panel2 = {
        "id": "mkt_stress",
        "title": "② 国债市场压力代理",
        "subtitle": "Treasury Market Stress Proxy (公开替代 BrokerTec 日内价差)",
        "note": "⚠ 非 BrokerTec 日内 bid-ask 价差(MS 专有数据无公开源)——改用免费公开压力代理，两条线都是「持有风险资产要求的补偿」，走高=市场压力↑。<br>"
                "<b>① 10年期限溢价(左轴, 橙线)</b>：投资者持有10年期国债、相比不断滚动短债，额外要求的年化补偿(%)。"
                "<b>怎么看</b>：走高=市场担心久期风险/供给过剩/通胀不确定，要求更高补偿；走低甚至转负=避险买盘涌入压低补偿。"
                "<b>怎么用</b>：期限溢价快速抬升往往先于长端收益率飙升，是国债承压的早期信号。<br>"
                "<b>② IG企业债利差 OAS(右轴, 紫线)</b>：<b>IG</b>=Investment Grade(投资级公司债，评级BBB-/Baa3及以上)；<b>OAS</b>=Option-Adjusted Spread(期权调整利差)。即投资级公司债相对同期限国债的信用利差(%，期权调整后)。"
                "<b>怎么看</b>：走阔=市场要求更高信用补偿=融资环境收紧/避险；收窄=信用环境宽松、风险偏好回升。"
                "<b>怎么用</b>：IG OAS 是「机构级」流动性/信用压力的温度计，比股市更早反映融资面紧张。<br>"
                "<b>两线同向走高 = 融资/流动性环境明显收紧</b>（对应 MS 原图「买卖价差扩大、成本上升」的主题）。",
        "unit_left": "期限溢价 %", "unit_right": "IG OAS %",
        "series": [
            {"name": "10年期限溢价", "color": "#b58a6a", "axis": "left",
             "points": _mk(tp10, agg="last")},
            {"name": "IG企业债利差(OAS)", "color": "#8a7fa8", "axis": "right",
             "points": _mk(igoas, agg="last")},
        ],
        "source": "FRED THREEFYTP10 (NY Fed ACM 10yr term premium) · BAMLC0A0CM (ICE BofA IG OAS)",
    }

    # ── 图3: 曲线利差 + 信用压力(对齐 MS 图3 活跃度/风险传导主题) ──
    t10y2y = _fred_series_hist("T10Y2Y", start)       # 10Y-2Y 曲线利差, %
    hyoas = _fred_series_hist("BAMLH0A0HYM2", start)   # HY OAS, %
    panel3 = {
        "id": "curve_credit",
        "title": "③ 收益率曲线与信用压力",
        "subtitle": "Yield Curve & Credit Stress (公开替代 BrokerTec DV01 成交量)",
        "note": "⚠ 非 BrokerTec 周度 DV01 成交量(MS 专有数据无公开源)——改用免费公开风险/曲线代理，反映利率预期与风险传导。<br>"
                "<b>① 10Y-2Y 曲线利差(左轴, 蓝线)</b>：10年期国债收益率 − 2年期国债收益率(%)。"
                "<b>怎么看</b>：<span style=\"color:#2e9e5b\">正值=正常向上倾斜</span>(长债利率高于短债)；"
                "<span style=\"color:#d64545\">负值=倒挂</span>(短债高于长债，历史上是衰退的经典领先信号)；由负转正的「陡峭化」常出现在降息预期升温/衰退临近。"
                "<b>怎么用</b>：看拐点——倒挂后重新转正(bear steepening)往往对应政策转向或risk-off。<br>"
                "<b>② 高收益债利差 HY OAS(右轴, 红线)</b>：<b>HY</b>=High Yield(高收益债/垃圾级，评级BB+/Ba1及以下)；<b>OAS</b>=Option-Adjusted Spread(期权调整利差)。即高收益公司债相对国债的信用利差(%)。"
                "<b>怎么看</b>：这是市场「风险偏好」最灵敏的指标——骤升=避险情绪爆发、风险资产承压；低位平稳=risk-on。"
                "<b>怎么用</b>：HY OAS 突破关键位(如>4.5%)是本系统的硬性卖出触发之一；它领先或同步于股市大跌。<br>"
                "<b>HY OAS 骤升 + 曲线快速变动 = 风险传导、市场剧烈调仓</b>（对应 MS 原图「成交量激增/风险交易」的主题）。",
        "unit_left": "10Y-2Y 利差 %", "unit_right": "HY OAS %",
        "series": [
            {"name": "10Y-2Y 曲线利差", "color": "#6b8fb5", "axis": "left",
             "points": _mk(t10y2y, agg="last")},
            {"name": "高收益债利差(HY OAS)", "color": "#c0757d", "axis": "right",
             "points": _mk(hyoas, agg="last")},
        ],
        "source": "FRED T10Y2Y (10Y-2Y spread) · BAMLH0A0HYM2 (ICE BofA HY OAS)",
    }

    panels = [panel1, panel2, panel3]
    # asof = 所有 series 里最新的日期
    all_last = []
    for p in panels:
        for s in p["series"]:
            if s["points"]:
                all_last.append(s["points"][-1]["date"])
    asof = max(all_last) if all_last else None
    # status: 统计缺失序列
    missing = [f'{p["id"]}/{s["name"]}' for p in panels for s in p["series"] if not s["points"]]
    status = "ok" if not missing else ("部分缺失: " + ", ".join(missing))
    return {"panels": panels, "asof": asof, "years": years, "status": status}


def fetch_ofr_fsi(years=3):
    """OFR 金融压力指数(Financial Stress Index) —— 对齐'国债市场压力'主题的官方权威总览指标。
    数据源: OFR 官方 CSV (financialresearch.gov/financial-stress-index/data/fsi.csv, 免key, 日频2000至今)。
    列: Date, OFR FSI(总), Credit, Equity valuation, Safe assets, Funding, Volatility, +3区域。
    OFR FSI: 0=金融压力处于历史正常水平; 正值=压力高于正常; 负值=低于正常。
    返回 {panel:{...同stress_panel结构...}, asof, years, status, latest:{分量最新值}}。绝不编: 抓不到→status。
    """
    import datetime as _dt
    import subprocess
    start_year = (_dt.date.today() - _dt.timedelta(days=int(365.3 * years) + 10))
    url = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
    text = ""
    # 通道1: urllib
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception:
        text = ""
    # 通道2: curl 回退
    if "OFR FSI" not in text:
        for _attempt in range(3):
            try:
                r = subprocess.run(["curl", "-s", url, "--max-time", "30",
                                    "-H", "User-Agent: Mozilla/5.0"],
                                   capture_output=True, text=True, timeout=38)
                if r.returncode == 0 and "OFR FSI" in (r.stdout or ""):
                    text = r.stdout
                    break
            except Exception:
                pass
    if "OFR FSI" not in text:
        return {"panel": None, "asof": None, "years": years,
                "status": "拉取失败(OFR 端点超时)", "latest": {}}
    lines = text.strip().splitlines()
    header = [h.strip() for h in lines[0].split(",")]
    idx = {h: i for i, h in enumerate(header)}
    # 需要的列(官方 FSI 5 大分量: 信用/股票估值/融资/安全资产/波动性 + 总指数)
    want = {"OFR FSI": "总指数", "Credit": "信用", "Equity valuation": "股票估值",
            "Funding": "融资", "Safe assets": "安全资产", "Volatility": "波动性"}
    series_pts = {k: [] for k in want}
    for ln in lines[1:]:
        cells = ln.split(",")
        if not cells or len(cells) < len(header):
            continue
        d = cells[idx["Date"]].strip()
        try:
            dt = _dt.date.fromisoformat(d)
        except Exception:
            continue
        if dt < start_year:
            continue
        for col in want:
            j = idx.get(col)
            if j is None or j >= len(cells):
                continue
            v = cells[j].strip()
            if v and v not in (".", ""):
                try:
                    series_pts[col].append((d, round(float(v), 3)))
                except ValueError:
                    pass
    # 周度降采样降噪
    colors = {"OFR FSI": "#c0757d", "Credit": "#b58a6a", "Equity valuation": "#c9a86a",
              "Funding": "#8a7fa8", "Safe assets": "#7fa085", "Volatility": "#6b8fb5"}
    series = []
    for col, zh in want.items():
        wp = _weekly_resample(series_pts[col], agg="last") if series_pts[col] else []
        series.append({
            "name": (f"OFR FSI 总指数" if col == "OFR FSI" else zh),
            "color": colors[col],
            "axis": "left",
            "width": (2.4 if col == "OFR FSI" else 1.3),
            "points": [{"date": d, "v": v} for d, v in wp],
        })
    all_last = [s["points"][-1]["date"] for s in series if s["points"]]
    asof = max(all_last) if all_last else None
    latest = {s["name"]: (s["points"][-1]["v"] if s["points"] else None) for s in series}
    panel = {
        "id": "ofr_fsi",
        "title": "④ OFR 金融压力指数",
        "subtitle": "OFR Financial Stress Index (官方权威·全市场压力总览)",
        "note": "OFR FSI = 美国金融研究办公室(财政部下属)编制的官方金融压力指数, 综合 33 个全球金融市场变量。"
                "<b>0 = 压力处于历史正常水平</b>; <span style=\"color:#d64545\">正值 = 压力高于正常</span>(承压); "
                "<span style=\"color:#2e9e5b\">负值 = 低于正常</span>(平静)。粗线为总指数, 细线为官方5大分量(信用/股票估值/融资/安全资产/波动性)——分量线用于定位压力来源(哪个市场在制造压力)。",
        "unit_left": "压力指数(0=正常)", "unit_right": "",
        "series": series,
        "source": "OFR (Office of Financial Research, US Treasury) FSI 官方 CSV",
        "single_axis": True,
    }
    return {"panel": panel, "asof": asof, "years": years,
            "status": "ok" if asof else "无有效数据", "latest": latest}


def write_stress_panels_notion(sp=None):
    """把国债市场压力三联图【最新值】写入 Notion DB_STRESS(以 asof 作 title 幂等 upsert)。
    存最新一期6个指标的当前读数(时序), 完整历史序列存 GitHub data/ 副本。
    返回写入 page id 或 None(无DB/无数据时跳过)。"""
    import config as c
    import notion_writer as nw
    if sp is None:
        sp = fetch_treasury_stress_panels()
    db = c.NOTION_DB.get("stress")
    if not db or not sp.get("asof"):
        return None
    # 从 panels 取每个 series 的最新值
    latest = {}
    for p in sp["panels"]:
        for s in p["series"]:
            latest[s["name"]] = s["points"][-1]["v"] if s["points"] else None
    props = {
        "MOVE指数": nw.prop_num(latest.get("MOVE 指数")),
        "10年收益率": nw.prop_num(latest.get("10年收益率")),
        "2年收益率": nw.prop_num(latest.get("2年收益率")),
        "10年期限溢价": nw.prop_num(latest.get("10年期限溢价")),
        "IG企业债OAS": nw.prop_num(latest.get("IG企业债利差(OAS)")),
        "10Y2Y曲线利差": nw.prop_num(latest.get("10Y-2Y 曲线利差")),
        "HY_OAS": nw.prop_num(latest.get("高收益债利差(HY OAS)")),
        "数据源": {"rich_text": [{"type": "text", "text": {"content":
                  "FRED + ICE BofA MOVE(Yahoo); 图2/图3为公开压力代理(非BrokerTec)"}}]},
    }
    return nw.upsert(db, sp["asof"], props, title_field="Date")


def write_ofr_notion(ofr=None):
    """把 OFR 金融压力指数【最新值】写入 Notion DB_OFR(以 asof 作 title 幂等 upsert)。
    存最新一期总指数+分量当前读数(时序), 完整3年序列存 GitHub data/ 副本。
    返回写入 page id 或 None(无DB/无数据时跳过)。"""
    import config as c
    import notion_writer as nw
    if ofr is None:
        ofr = fetch_ofr_fsi()
    db = c.NOTION_DB.get("ofr")
    if not db or not ofr.get("asof"):
        return None
    latest = ofr.get("latest", {})
    props = {
        "OFR_FSI总指数": nw.prop_num(latest.get("OFR FSI 总指数")),
        "信用": nw.prop_num(latest.get("信用")),
        "股票估值": nw.prop_num(latest.get("股票估值")),
        "融资": nw.prop_num(latest.get("融资")),
        "安全资产": nw.prop_num(latest.get("安全资产")),
        "波动性": nw.prop_num(latest.get("波动性")),
        "数据源": {"rich_text": [{"type": "text", "text": {"content":
                  "OFR (Office of Financial Research, US Treasury) FSI 官方 CSV"}}]},
    }
    return nw.upsert(db, ofr["asof"], props, title_field="Date")


def _fred_series(series_id, start=None):
    """curl FRED fredgraph.csv 取完整历史 [(date, value)] 升序。缺失('.')跳过。失败返回 []。"""
    import requests
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    if start:
        url += f"&cosd={start}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return []
        out = []
        for ln in r.text.strip().splitlines()[1:]:
            if "," not in ln:
                continue
            d, v = ln.split(",", 1)
            v = v.strip()
            if v and v != ".":
                try:
                    out.append((d.strip(), float(v)))
                except ValueError:
                    continue
        return out
    except Exception:
        return []


def _eia_series(series_id, start=None):
    """EIA API v2 petroleum stocks 周频序列。返回 [(date 'YYYY-MM-DD', value 千桶)] 升序。
    需 EIA_API_KEY(在 .env)。失败/无 key 返回 []。绝不编造。"""
    import requests
    key = os.environ.get("EIA_API_KEY")
    if not key:
        # 从 .env 兜底读
        envp = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(envp):
            for line in open(envp):
                if line.startswith("EIA_API_KEY="):
                    key = line.strip().split("=", 1)[1]
                    break
    if not key:
        return []
    url = ("https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
           f"?api_key={key}&frequency=weekly&data[0]=value"
           f"&facets[series][]={series_id}"
           "&sort[0][column]=period&sort[0][direction]=asc&length=5000")
    if start:
        url += f"&start={start}"
    try:
        r = requests.get(url, timeout=40)
        if r.status_code != 200:
            return []
        data = r.json().get("response", {}).get("data", [])
        out = []
        for x in data:
            per = x.get("period")
            val = x.get("value")
            if per and val is not None:
                try:
                    out.append((per, float(val)))
                except (ValueError, TypeError):
                    continue
        out.sort(key=lambda t: t[0])
        return out
    except Exception:
        return []


def _mof_jgb_yields(term_idx):
    """抓日本财务省(MOF)每日 JGB 收益率 CSV(历史 all + 当月), 取指定期限列。
    term_idx: CSV 中列索引(10Y=10, 30Y=14; 列0=Date)。
    返回 {date 'YYYY-MM-DD': yield%} 升序 dict。失败返回 {}。绝不编造。"""
    import csv, io, requests, datetime as _dt
    urls = [
        "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
        "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",
    ]
    out = {}
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            if r.status_code != 200:
                continue
            rows = list(csv.reader(io.StringIO(r.content.decode("utf-8", errors="replace"))))
            for row in rows:
                if not row or len(row) <= term_idx:
                    continue
                d = row[0].strip()
                # 日期形如 2026/8/17
                if "/" not in d:
                    continue
                try:
                    dt = _dt.datetime.strptime(d, "%Y/%m/%d").date()
                except ValueError:
                    continue
                raw = row[term_idx].strip()
                if not raw or raw == "-":
                    continue
                try:
                    out[dt.isoformat()] = float(raw)
                except ValueError:
                    continue
        except Exception:
            continue
    return dict(sorted(out.items()))


def fetch_us_jp_yields(cache_path=None):
    """美日 10Y/30Y 国债收益率同图对比(过去一年, 日频)。绝不编造, 缺项标 status。
      美债: FRED DGS10/DGS30(日频, %)。日债: 日本财务省(MOF) 每日 JGB CSV 10Y/30Y列(日频, %)。
    返回 {status, as_of, series:{us_10y/us_30y/jp_10y/jp_30y: {name,color,dash,points:[(date,%)],latest,as_of}}}。
    """
    import json, datetime as _dt
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "us_jp_yields.json")
    today = _dt.date.today()
    cutoff = (today - _dt.timedelta(days=366)).isoformat()

    # 美债(FRED 日频) — 复用 _fred_series
    us10 = [(d, v) for d, v in _fred_series("DGS10", start=cutoff) if d >= cutoff]
    us30 = [(d, v) for d, v in _fred_series("DGS30", start=cutoff) if d >= cutoff]
    # 日债(MOF 日频)
    jp10_all = _mof_jgb_yields(10)
    jp30_all = _mof_jgb_yields(14)
    jp10 = [(d, v) for d, v in jp10_all.items() if d >= cutoff]
    jp30 = [(d, v) for d, v in jp30_all.items() if d >= cutoff]

    def pack(name, color, dash, pts, src):
        if len(pts) < 2:
            return {"status": "未获取", "name": name}
        return {"status": "ok", "name": name, "color": color, "dash": dash,
                "points": pts, "latest": pts[-1][1], "as_of": pts[-1][0], "source": src}

    series = {
        "us_10y": pack("美国 10Y", "#c0757d", "none", us10, "FRED DGS10 (日频)"),
        "us_30y": pack("美国 30Y", "#8a3f47", "none", us30, "FRED DGS30 (日频)"),
        "jp_10y": pack("日本 10Y", "#6b8fb5", "dash", jp10, "日本财务省 MOF JGB (日频)"),
        "jp_30y": pack("日本 30Y", "#3a5a7d", "dash", jp30, "日本财务省 MOF JGB (日频)"),
    }
    ok_any = any(s.get("status") == "ok" for s in series.values())
    asofs = [s["as_of"] for s in series.values() if s.get("status") == "ok"]
    out = {"status": "ok" if ok_any else "未获取",
           "as_of": max(asofs) if asofs else today.isoformat(),
           "series": series}
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_nikkei225(cache_path=None):
    """日经225指数(过去一年,日频)。FRED NIKKEI225。绝不编造,缺失跳过。
    返回 {status, as_of, latest, hi, lo, points:[(date,收盘)], source}。"""
    import json, datetime as _dt
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "nikkei225.json")
    today = _dt.date.today()
    cutoff = (today - _dt.timedelta(days=366)).isoformat()
    pts = [(d, v) for d, v in _fred_series("NIKKEI225", start=cutoff) if d >= cutoff]
    if len(pts) < 2:
        out = {"status": "未获取"}
    else:
        out = {"status": "ok", "as_of": pts[-1][0], "latest": pts[-1][1],
               "hi": max(v for _, v in pts), "lo": min(v for _, v in pts),
               "points": pts, "source": "FRED NIKKEI225 (日经225指数,日频)"}
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def _jpx_foreign_flow_weekly():
    """抓 JPX 投资部门别周报(东证Prime,金额), 解析海外投资家(Foreigners)每周净买卖(差引き Balance)。
    从 archive 页(00=本年,01=上年)解析 stock_val_1_*.xls 链接→逐个读:
      · 周结束日期从 Excel row3 '(M/D - M/D)' 解析(文件名code是YYMM週号非日期,不能当日期);
      · '海外投資家/Foreigners' 行的 差引き Balance(第6列 idx6)为净额, 字符串带逗号需去除。
    单位:日元→万亿日元(¥T)。返回 [(week_end 'YYYY-MM-DD', 净额¥T)] 升序。失败返回 []。绝不编造。"""
    import re, requests, datetime as _dt, io
    try:
        import pandas as pd
    except Exception:
        return []
    base = "https://www.jpx.co.jp"
    out = []
    links = []
    # archive-00=本年, archive-01=上年 (覆盖过去一年绰绰有余)
    for nn in (0, 1):
        u = base + f"/english/markets/statistics-equities/investor-type/00-00-archives-{nn:02d}.html"
        try:
            h = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
            links += re.findall(r'(/english/markets/statistics-equities/investor-type/[^"]*?stock_val_1_\d{6}\.xls)', h)
        except Exception:
            continue
    cutoff = _dt.date.today() - _dt.timedelta(days=380)
    seen = set()

    def _to_float(x):
        try:
            import pandas as _pd
            if _pd.isna(x):
                return None
        except Exception:
            pass
        if isinstance(x, (int, float)):
            try:
                f = float(x)
                return None if f != f else f  # NaN check
            except Exception:
                return None
        if isinstance(x, str):
            s = x.replace(",", "").replace("△", "-").replace("▲", "-").strip()
            if not s or s == "-":
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return None

    for path in links:
        if path in seen:
            continue
        seen.add(path)
        try:
            raw = requests.get(base + path, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).content
            df = pd.read_excel(io.BytesIO(raw), header=None, sheet_name=0)
        except Exception:
            continue
        # 1) 周结束日期: 扫前6行找 '( M/D - M/D )'
        wk_end = None
        for i in range(min(6, len(df))):
            cell = str(df.iloc[i, 0])
            m = re.search(r'(\d{4})年.*?(\d{1,2})/(\d{1,2})\s*[-–]\s*(\d{1,2})/(\d{1,2})', cell)
            if m:
                yr, _, _, em, ed = m.groups()
                try:
                    wk_end = _dt.date(int(yr), int(em), int(ed))
                except ValueError:
                    wk_end = None
                break
        if wk_end is None or wk_end < cutoff:
            continue
        # 2) 海外投資家 Balance(差引き, 第6列 idx6, 在'売り'行): 单位日元→亿日元(¥100M)
        bal = None
        for i in range(len(df)):
            c0 = str(df.iloc[i, 0])
            if "海外投資家" in c0 or "Foreign" in c0:
                # 差引き净额在'売り'行(本行)第6列; 兜底试下一行
                for j in (i, i + 1):
                    if j < len(df) and df.shape[1] > 6:
                        v = _to_float(df.iloc[j, 6])
                        if v is not None:
                            bal = v; break
                break
        if bal is not None:
            # Excel 单位=千円(1,000 yen): 千円→万亿日元(¥T) = /1e9
            out.append((wk_end.isoformat(), round(bal / 1e9, 3)))  # 千円→万亿日元(¥T)
    out.sort(key=lambda t: t[0])
    return out


def fetch_foreign_flow_japan(cache_path=None):
    """外资净买入日本股票(过去一年,周频)。JPX 投资部门别周报'海外投資家'差引き净额。
    绝不编造,抓不到留空 status。返回 {status,as_of,latest,points:[(week,¥T)],source}。"""
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "foreign_flow_japan.json")
    pts = _jpx_foreign_flow_weekly()
    if len(pts) < 2:
        out = {"status": "未获取"}
    else:
        out = {"status": "ok", "as_of": pts[-1][0], "latest": pts[-1][1],
               "hi": max(v for _, v in pts), "lo": min(v for _, v in pts),
               "points": pts,
               "source": "JPX 投资部门别交易(东证Prime,海外投資家净买卖,周频,万亿日元¥T,原表千円)"}
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def _imf_iip_series(country, entry):
    """IMF SDMX 2.1 拉一国 IIP 资产/负债年度序列(USD)。
    country: USA/JPN/DEU/CHN; entry: A_P(资产)/L_P(负债)。返回 {year:USD} 。失败{}。绝不编造。"""
    import requests
    import xml.etree.ElementTree as ET
    url = f"https://api.imf.org/external/sdmx/2.1/data/IIP/{country}.{entry}.IIP.USD.A?startPeriod=2014"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if r.status_code != 200:
            return {}
        root = ET.fromstring(r.text)
        out = {}
        for el in root.iter():
            if el.tag.split("}")[-1] == "Obs":
                t = el.attrib.get("TIME_PERIOD"); v = el.attrib.get("OBS_VALUE")
                if t and v:
                    try:
                        out[t] = float(v)
                    except ValueError:
                        pass
        return out
    except Exception:
        return {}


def fetch_iip_four_countries(cache_path=None):
    """四国(美/日/德/中)国际投资头寸 IIP(过去约10年,年频): 对外总资产/总负债/净头寸。
    源: IMF SDMX 2.1 (api.imf.org) IIP 数据集, entry A_P(资产)/L_P(负债), INDICATOR=IIP, USD 年频。
    绝不编造, 缺国留 status。返回 {status,as_of,countries:{US/JP/DE/CN:{name,flag,color,
      assets:[(yr,$T)],liab:[(yr,$T)],net:[(yr,$T)],latest_*}}}。"""
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "iip_four.json")
    cmap = {"US": ("USA", "美国", "🇺🇸", "#c0757d"),
            "JP": ("JPN", "日本", "🇯🇵", "#6b8fb5"),
            "DE": ("DEU", "德国", "🇩🇪", "#7fa085"),
            "CN": ("CN_ISO_PLACEHOLDER", "中国", "🇨🇳", "#e0a92e")}
    # 中国 ISO 用 CHN
    cmap["CN"] = ("CHN", "中国", "🇨🇳", "#e0a92e")
    countries = {}
    all_years = []
    for key, (iso, name, flag, color) in cmap.items():
        a = _imf_iip_series(iso, "A_P")
        l = _imf_iip_series(iso, "L_P")
        yrs = sorted(set(a) & set(l))
        yrs = [y for y in yrs if y >= "2015"]
        if len(yrs) < 2:
            countries[key] = {"status": "未获取", "name": name, "flag": flag}
            continue
        assets = [(y, round(a[y] / 1e12, 2)) for y in yrs]
        liab = [(y, round(l[y] / 1e12, 2)) for y in yrs]
        net = [(y, round((a[y] - l[y]) / 1e12, 2)) for y in yrs]
        countries[key] = {
            "status": "ok", "name": name, "flag": flag, "color": color,
            "assets": assets, "liab": liab, "net": net,
            "latest_year": yrs[-1], "latest_assets": assets[-1][1],
            "latest_liab": liab[-1][1], "latest_net": net[-1][1],
        }
        all_years += yrs
    ok = any(c.get("status") == "ok" for c in countries.values())
    out = {"status": "ok" if ok else "未获取",
           "as_of": max(all_years) if all_years else "",
           "source": "IMF International Investment Position (SDMX 2.1, api.imf.org), 年频, USD",
           "countries": countries}
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def _ofr_hfm_series(mnemonic):
    """OFR Hedge Fund Monitor 免key JSON API 季度序列。返回 [(date 'YYYY-MM-DD', float)] 升序。失败返回 []。
    源: https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic=<code> (SEC Form PF 汇总, 无需key)。"""
    import requests
    url = f"https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic={mnemonic}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for row in data:
            if isinstance(row, list) and len(row) >= 2 and row[1] is not None:
                try:
                    out.append((str(row[0]), float(row[1])))
                except (ValueError, TypeError):
                    continue
        return out
    except Exception:
        return []


def fetch_hf_leverage(cache_path=None):
    """对冲基金美债杠杆敞口(季频, 源: OFR Hedge Fund Monitor / SEC Form PF, 免key)。
    绝不编造, 取不到 status='未获取'。数据本质是【季度】更新(Form PF 滞后发布), 非日频。
      图A: 对冲基金美债总名义敞口 / 美国GDP (%)。分子=OFR FPF-ASSETCLASS_USGOV_GNE_SUM, 分母=FRED GDP。
      图B: 对冲基金三类借款规模($万亿): Repo / Prime brokerage / Other secured。
    (对应 BIS AER 2026 Graph 5。零折扣占比图C无公开结构化源, 不做。)
    返回 {status, as_of, source, exposure:{points:[(date,pct)], latest_pct, latest_usd_t},
          borrow:{repo:[(date,$T)], prime:[(date,$T)], other:[(date,$T)], latest_*}}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "hf_leverage.json")
    START = "2015-01-01"
    # 图B 三类借款
    repo = _ofr_hfm_series("FPF-BORROW_REPO_SUM")
    prime = _ofr_hfm_series("FPF-BORROW_PRIMEBROKER_SUM")
    other = _ofr_hfm_series("FPF-BORROW_OTHERSECURED_SUM")
    # 图A 美债敞口 + GDP
    gne = _ofr_hfm_series("FPF-ASSETCLASS_USGOV_GNE_SUM")
    gdp = dict(_fred_series("GDP", START))  # {date: $B annualized}

    def _t(series):
        return [(d, round(v / 1e12, 3)) for d, v in series if d >= START]

    out = {"status": "未获取", "as_of": "",
           "source": "OFR Hedge Fund Monitor (SEC Form PF 汇总, 季频, 免key) + FRED GDP",
           "exposure": {}, "borrow": {}}

    # 借款三类($万亿)
    if repo and prime and other:
        rp, pr, ot = _t(repo), _t(prime), _t(other)
        out["borrow"] = {
            "repo": rp, "prime": pr, "other": ot,
            "latest_repo": rp[-1][1] if rp else None,
            "latest_prime": pr[-1][1] if pr else None,
            "latest_other": ot[-1][1] if ot else None,
            "as_of": rp[-1][0] if rp else "",
        }

    # 美债敞口/GDP (%): GDP 是季度年化十亿美元, 匹配最近季度末
    if gne and gdp:
        exp_pts = []
        latest_usd = None
        for d, v in gne:
            if d < START:
                continue
            # GDP 用同季或最近的可用值 (FRED GDP 日期是季初 YYYY-01/04/07/10-01)
            yr, mo = d[:4], int(d[5:7])
            q_start = f"{yr}-{((mo-1)//3)*3+1:02d}-01"
            g = gdp.get(q_start)
            if g is None:
                # 回退: 取 <= d 的最近 GDP
                cand = [gd for gd in gdp if gd <= d]
                g = gdp[max(cand)] if cand else None
            if g:
                pct = round(v / (g * 1e9) * 100, 2)  # GDP十亿→美元
                exp_pts.append((d, pct))
                latest_usd = round(v / 1e12, 3)
        if exp_pts:
            out["exposure"] = {
                "points": exp_pts, "latest_pct": exp_pts[-1][1],
                "latest_usd_t": latest_usd, "as_of": exp_pts[-1][0],
            }

    if out["borrow"] or out["exposure"]:
        out["status"] = "ok"
        out["as_of"] = out.get("borrow", {}).get("as_of") or out.get("exposure", {}).get("as_of", "")
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_hf_leverage(cache_path=None):
    """对冲基金杠杆监测(OFR Hedge Fund Monitor, SEC Form PF 底层, 季度)。绝不编造。
      图A: 对冲基金美国主权债(美债)总名义敞口 GNE 占 US GDP % (2013Q1起, 季度)
           = FPF-ASSETCLASS_USGOV_GNE_SUM / (FRED GDP 十亿$×1e9) ×100
      图B: 对冲基金三类借款规模($万亿, 季度): Repo / Prime brokerage / Other secured
    源: OFR https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic=<code> (免key)
        GDP: FRED GDP (免key CSV)
    返回 {status, as_of, exposure:{points:[(q,%)], latest_pct, latest_usd_t}, borrow:{repo/prime/other:[(q,$T)], latest_*}}。
    """
    import json, requests
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "hf_leverage.json")

    def _ofr(m):
        try:
            r = requests.get(
                f"https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic={m}",
                timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            d = r.json()
            s = d if isinstance(d, list) else d.get("timeseries", [])
            return [(str(x[0]), float(x[1])) for x in s if x and x[1] is not None]
        except Exception:
            return []

    def _fred_q(series):
        """FRED 季度序列 {date:val}(GDP 十亿$)。用 curl 子进程(该端点对 requests 偶发超时)。"""
        import subprocess
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2013-01-01"
        text = ""
        for _a in range(3):
            try:
                p = subprocess.run(["curl", "-s", "--max-time", "20", url],
                                   capture_output=True, text=True, timeout=25)
                if p.returncode == 0 and p.stdout and "," in p.stdout:
                    text = p.stdout
                    break
            except Exception:
                continue
        out = {}
        for ln in text.splitlines()[1:]:
            p = ln.split(",")
            if len(p) == 2 and p[1] not in ("", "."):
                out[p[0]] = float(p[1])
        return out

    repo = _ofr("FPF-BORROW_REPO_SUM")
    prime = _ofr("FPF-BORROW_PRIMEBROKER_SUM")
    other = _ofr("FPF-BORROW_OTHERSECURED_SUM")
    gne = _ofr("FPF-ASSETCLASS_USGOV_GNE_SUM")
    gdp = _fred_q("GDP")  # 十亿$ 年化, 季度点(月初日期如 2026-01-01)

    def _t(series):  # 转 $万亿
        return [(q, round(v / 1e12, 3)) for q, v in series]

    # 敞口/GDP%: OFR 季末(如 2026-03-31) 对 FRED 季初(2026-01-01)。按年季匹配。
    def _gdp_for_q(qdate):
        yr, mo = qdate[:4], qdate[5:7]
        qmap = {"03": "01", "06": "04", "09": "07", "12": "10"}
        key = f"{yr}-{qmap.get(mo, '01')}-01"
        return gdp.get(key)

    exp_pts = []
    for q, v in gne:
        g = _gdp_for_q(q)
        if g:
            exp_pts.append((q, round(v / (g * 1e9) * 100, 2)))

    ok = bool(repo and gne)
    out = {
        "status": "ok" if ok else "未获取",
        "as_of": (repo[-1][0] if repo else (gne[-1][0] if gne else "")),
        "source": "OFR Hedge Fund Monitor (SEC Form PF, 季度) · FRED GDP",
        "exposure": {
            "points": exp_pts,
            "latest_pct": exp_pts[-1][1] if exp_pts else None,
            "latest_usd_t": round(gne[-1][1] / 1e12, 2) if gne else None,
            "latest_q": gne[-1][0] if gne else "",
        },
        "borrow": {
            "repo": _t(repo), "prime": _t(prime), "other": _t(other),
            "latest_repo": round(repo[-1][1] / 1e12, 2) if repo else None,
            "latest_prime": round(prime[-1][1] / 1e12, 2) if prime else None,
            "latest_other": round(other[-1][1] / 1e12, 2) if other else None,
            "latest_q": repo[-1][0] if repo else "",
        },
    }
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_bis_gold_swaps(cache_path=None):
    """BIS 自营黄金掉期规模(吨)。BIS 机构自己那笔 gold swaps(GATA/Robert Lambourne 追踪)。

    数据由 data/bis_gold_swaps.json 驱动(真值锚点):
      - 年度值(3/31, kind=annual): BIS 年报明确确认的官方数字(2010 至今连续)。
      - 月度值(kind=monthly): GATA 顾问 Lambourne 从 BIS 官方月度 Statement of Account
        (bis.org/banking/balsheet/statofacc{YYMMDD}.pdf)推算, BIS 年报每年验证其准确。
    绝不编造: BIS 从不主动披露 swaps 行, 也不公开精确勾稽算法, 故本函数只消费已核实的
    公开真值(年报 + GATA 推算), 不做无法验证的自行换算。月度更新由 cron agent 读 GATA
    新文章补一个点(只增, 绝不编)。
    返回 {status, as_of, source, unit, note, latest_t, peak_t, peak_date, points:[{date,tonnes,kind,src}]}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "bis_gold_swaps.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "未获取", "as_of": "", "source": "BIS 自营黄金掉期(文件缺失)",
                "unit": "tonnes", "points": []}
    pts = [p for p in (data.get("points") or []) if p.get("date") and p.get("tonnes") is not None]
    pts.sort(key=lambda p: p.get("date", ""))
    if not pts:
        return {"status": "未获取", "as_of": data.get("as_of", ""),
                "source": data.get("source", "BIS 自营黄金掉期"), "unit": "tonnes", "points": []}
    peak = max(pts, key=lambda p: p["tonnes"])
    latest = pts[-1]
    return {
        "status": "ok",
        "as_of": data.get("as_of", latest["date"]),
        "source": data.get("source", "BIS 自营黄金掉期 (BIS own-account gold swaps)"),
        "unit": data.get("unit", "tonnes"),
        "note": data.get("note", ""),
        "latest_t": latest["tonnes"],
        "latest_date": latest["date"],
        "peak_t": peak["tonnes"],
        "peak_date": peak["date"],
        "points": pts,
    }


def fetch_market_breadth(cache_path=None, lookback_days=250, nh_window=20):
    """美股市场广度: RSP(等权标普)/SPY(市值加权标普) 比值, 替代无数据源的 A/D 布尔判断。

    数据源: 东方财富 push2his 原生 API(免 key)。SPY=107.SPY, RSP=107.RSP, 日线复权。
    注: akshare 封装被东财挡, 但原生 push2his API 实测通, 故直接请求(带重试)。

    市场广度含义: RSP/SPY 比值下行 = 少数大权重股领涨、多数股走弱(广度恶化),
    与 NYSE A/D 腾落线「顶背离」同义, 但这是**连续可量化真数据**, 可画折线、可复现判定。

    数值化背离判定(可复现规则, 不靠 AI 主观):
      在最近 nh_window 个交易日内,
      若 S&P(用 SPY 代理)创下近 lookback_days 新高, 但 RSP/SPY 广度比 **未**同步创新高
      (广度比距其近 lookback 高点还差 > 2%), 则判定为 **顶背离(divergence=True)**。
      否则 divergence=False(广度确认)。

    返回 {status, as_of, divergence(bool), evidence{...}, spy_points:[(d,close)],
          ratio_points:[(d, RSP/SPY 归一化)], source}。
    绝不编造: 取不到 status='未获取'。
    """
    import json, requests, datetime as _dt, time as _time
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "market_breadth.json")

    def _load_cache():
        """读上次成功落盘的真数据(抓不到时兜底, 绝不覆盖成空)。"""
        try:
            with open(cache_path, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("status") == "ok" and c.get("spy_points"):
                c["stale"] = True  # 标记为缓存(非当日新抓)
                return c
        except Exception:
            pass
        return None

    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
          "Referer": "https://quote.eastmoney.com/"}
    _sess = requests.Session()
    _sess.headers.update(UA)

    def _kline(secid, beg="20180101"):
        end = _dt.date.today().strftime("%Y%m%d")
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                  "klt": 101, "fqt": 1, "beg": beg, "end": end}
        for attempt in range(6):
            try:
                r = _sess.get(url, params=params, timeout=25)
                d = r.json().get("data")
                if d and d.get("klines"):
                    # klines: "date,open,close,high,low,vol,amount,pct"
                    out = []
                    for ln in d["klines"]:
                        parts = ln.split(",")
                        out.append((parts[0], float(parts[2])))  # (date, close)
                    return out
            except Exception:
                pass
            _time.sleep(1.5 * (attempt + 1))  # 递增退避
        return None

    spy = _kline("107.SPY")
    _time.sleep(1.0)
    rsp = _kline("107.RSP")
    if not spy or not rsp:
        cached = _load_cache()
        if cached:
            return cached  # 东财限流/抖动 → 用上次真数据兜底(绝不覆盖成空)
        return {"status": "未获取", "as_of": "",
                "source": "美股市场广度 RSP/SPY(东方财富, 抓取失败且无缓存)", "divergence": None}

    spy_map = dict(spy)
    rsp_map = dict(rsp)
    common = sorted(set(spy_map) & set(rsp_map))
    if len(common) < nh_window + 5:
        cached = _load_cache()
        if cached:
            return cached
        return {"status": "未获取", "as_of": common[-1] if common else "",
                "source": "美股市场广度 RSP/SPY(数据不足)", "divergence": None}

    # 广度比 = RSP/SPY, 归一化到起点=100 便于观感
    base = rsp_map[common[0]] / spy_map[common[0]]
    ratio_pts = [(d, round((rsp_map[d] / spy_map[d]) / base * 100.0, 3)) for d in common]
    spy_pts = [(d, round(spy_map[d], 2)) for d in common]

    # 数值化背离判定
    recent = common[-nh_window:]
    lb = common[-lookback_days:] if len(common) >= lookback_days else common
    spy_vals_lb = [spy_map[d] for d in lb]
    ratio_vals_lb = [rsp_map[d] / spy_map[d] for d in lb]
    spy_hi = max(spy_vals_lb)
    ratio_hi = max(ratio_vals_lb)
    # 最近 nh_window 内 SPY 是否触及/接近 lookback 新高(>= 99.5% of hi)
    spy_recent_hi = max(spy_map[d] for d in recent)
    ratio_recent_hi = max(rsp_map[d] / spy_map[d] for d in recent)
    spy_made_high = spy_recent_hi >= spy_hi * 0.995
    # 广度比距其 lookback 高点差多少 %
    ratio_gap_pct = round((ratio_hi - ratio_recent_hi) / ratio_hi * 100.0, 2)
    breadth_confirmed = ratio_recent_hi >= ratio_hi * 0.98  # 广度也接近新高=确认
    divergence = bool(spy_made_high and not breadth_confirmed)

    last_d = common[-1]
    evidence = {
        "spy_recent_high": round(spy_recent_hi, 2),
        "spy_lookback_high": round(spy_hi, 2),
        "spy_made_new_high": spy_made_high,
        "ratio_gap_from_high_pct": ratio_gap_pct,
        "breadth_confirmed": breadth_confirmed,
        "lookback_days": len(lb),
        "nh_window": nh_window,
        "rule": "SPY创近lookback新高 且 RSP/SPY广度比距其高点>2% = 顶背离",
    }

    out = {
        "status": "ok",
        "as_of": last_d,
        "divergence": divergence,
        "evidence": evidence,
        "spy_points": spy_pts[-lookback_days:],
        "ratio_points": ratio_pts[-lookback_days:],
        "latest_spy": spy_pts[-1][1],
        "latest_ratio": ratio_pts[-1][1],
        "source": "美股市场广度 RSP(等权)/SPY(市值加权) · 东方财富 push2his API",
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_silver_bank_positions(cache_path=None, weeks=520):
    """白银做市商(bullion banks = commercial)头寸方向 —— CFTC COT commercial 净持仓。

    ★这是「投行/做市商在 COMEX 白银上是接货还是压价」的**一手官方真数据等价物**,
    语义覆盖 Michael Lynch(@DtDS_WSS) 的 "cumulative & monthly issues and stops by bullion
    banks" 图想说的核心(做市商头寸方向), 但用 CFTC 官方 Socrata(免key/可回溯到1986/可每周更新),
    而非被 CME 封禁的 issues/stops 逐日抓取。

    含义: commercial(商业套保, 主体是 bullion banks) 净持仓通常为净空(对冲实物多头)。
      - 净空**扩大** = 做市商加空压价 / 卖压增强(与图里 "Issued" 交货压价同向)
      - 净空**收窄/转多** = 做市商减空 / 被逼平 (与图里 "Stopped" 接货 squeeze 同向)
    绝不编造: 抓不到读上次缓存真值, 绝不覆盖成空。

    返回 {status, as_of, source, unit, latest_net, latest_wow, peak_short_date,
          points:[{date, comm_net, comm_long, comm_short, open_interest}], inventory_note}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data",
                                  "silver_bank_positions.json")

    def _load_cache():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    pts = []
    try:
        from fetchers import cot as _cot
        hist = _cot.fetch_history("silver", weeks=weeks)
        for r in hist:
            if not r.get("as_of"):
                continue
            pts.append({
                "date": r["as_of"],
                "comm_net": r.get("comm_net"),
                "comm_long": r.get("comm_long"),
                "comm_short": r.get("comm_short"),
                "open_interest": r.get("open_interest"),
            })
    except Exception:
        pts = []

    if not pts:
        cached = _load_cache()
        if cached and cached.get("points"):
            cached["status"] = "缓存"
            return cached
        return {"status": "未获取", "as_of": "", "unit": "contracts",
                "source": "CFTC COT 白银 commercial 净持仓(未获取)", "points": []}

    pts.sort(key=lambda p: p.get("date", ""))
    latest = pts[-1]
    prev = pts[-2] if len(pts) > 1 else None
    latest_net = latest.get("comm_net")
    latest_wow = (latest_net - prev["comm_net"]) if (prev and prev.get("comm_net") is not None
                                                      and latest_net is not None) else None
    # 净空最深点(comm_net 最小)
    valid = [p for p in pts if p.get("comm_net") is not None]
    peak_short = min(valid, key=lambda p: p["comm_net"]) if valid else None

    # COMEX 白银库存当前锚点(文字标注, 非每日折线 —— 无稳定免key每日源)
    inv_note = ("COMEX 白银库存约 335M oz(≈10,400 吨), 其中注册(registered)"
                "占比与做市商囤货状态需结合 CME 每日仓单报告(metalcharts.org 快照)。")

    out = {
        "status": "ok",
        "as_of": latest["date"],
        "unit": "contracts",
        "source": "CFTC COT · SILVER - COMMODITY EXCHANGE INC. · commercial 净持仓(官方 Socrata, 免key)",
        "latest_net": latest_net,
        "latest_long": latest.get("comm_long"),
        "latest_short": latest.get("comm_short"),
        "latest_oi": latest.get("open_interest"),
        "latest_wow": latest_wow,
        "peak_short_date": (peak_short or {}).get("date"),
        "peak_short_net": (peak_short or {}).get("comm_net"),
        "inventory_note": inv_note,
        "points": pts,
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_comex_silver_issues_ref(cache_path=None):
    """C: COMEX 白银 issues/stops by bullion banks 静态参考(数据源=Michael Lynch @DtDS_WSS)。

    ★为什么静态不自动更新: 原始底层是 CME COMEX 每日 Issues&Stops by firm 报告, CME 官方
    明确封禁脚本抓取(IP block + Data Terms of Use), 无免key可回溯每日源。ANONYMIZED_PERSON_0_12 本人在
    Substack(econanalytics.substack.com)/X(@DtDS_WSS)周期性更新, 但**事件驱动、不规律、
    无 API、图为嵌入 PNG、不公开原始累加序列**。故本 section 只做诚实的静态参考锚点 + 明确
    标注来源与更新性质, 绝不伪造每日折线。真实可更新的做市商头寸方向见 fetch_silver_bank_positions
    (CFTC 官方一手数据)。

    数据由 data/comex_silver_issues_ref.json 驱动(从公开图手抄的关键锚点, 明确标注非实时)。
    返回 {status, as_of, source, source_url, note, points:[{date, cumulative_koz}], annotations}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data",
                                  "comex_silver_issues_ref.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "未获取", "as_of": "", "unit": "thousands_oz",
                "source": "COMEX 白银累计 issues/stops(文件缺失)", "points": []}
    pts = [p for p in (data.get("points") or []) if p.get("date")]
    pts.sort(key=lambda p: p.get("date", ""))
    return {
        "status": "ok" if pts else "未获取",
        "as_of": data.get("as_of", ""),
        "unit": data.get("unit", "thousands_oz"),
        "source": data.get("source", "Michael Lynch (@DtDS_WSS) · EconAnalytics"),
        "source_url": data.get("source_url", "https://econanalytics.substack.com/"),
        "update_nature": data.get("update_nature",
                                  "事件驱动·不规律更新·CME官方封禁脚本抓取·仅静态参考锚点"),
        "note": data.get("note", ""),
        "annotations": data.get("annotations", []),
        "points": pts,
    }


def fetch_gold_exports(cache_path=None):
    """美国黄金出口(Nonmonetary gold) —— FRED IEAXGG 季度真数据(1999→今, Mil USD)。

    ★对应用户图「各国黄金运回家·2025-26 美国出口货币黄金飙升」。图作者原标 Monetary gold,
    但 FRED 无此序列; 真正对应该暴涨现象的是 **Nonmonetary gold**(非货币黄金 = 民间/商业实物金
    出口, 非央行储备金)。本函数用 FRED 官方真序列 IEAXGG + 真标题, 诚实标注(不照抄不准的
    Monetary)。免 key(fredgraph.csv 直连), 可回溯, 每季更新。

    每季从 FRED 拉最新, 与本地缓存合并(只增新点), 抓不到读缓存真值绝不覆盖成空。
    返回 {status, as_of, source, unit, latest, peak, base_2024_avg, surge_x, points:[{date,value_musd}]}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "gold_exports.json")

    def _load_cache():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    cached = _load_cache()
    # 从 FRED 拉最新(免key fredgraph.csv), 与缓存合并
    fresh = _fred_series("IEAXGG")  # [(date,val)] 升序
    pts = []
    if fresh:
        pts = [{"date": d, "value_musd": round(float(v), 1)} for d, v in fresh]
    elif cached and cached.get("points"):
        out = dict(cached)
        out["status"] = "缓存"
        return out
    if not pts:
        return {"status": "未获取", "as_of": "", "unit": "millions_usd",
                "source": "FRED IEAXGG 美国黄金出口(未获取)", "points": []}

    pts.sort(key=lambda p: p["date"])
    vals = [p["value_musd"] for p in pts]
    peak = max(vals); peak_date = pts[vals.index(peak)]["date"]
    base_2024 = [p["value_musd"] for p in pts if p["date"].startswith("2024")]
    base_avg = round(sum(base_2024) / len(base_2024), 0) if base_2024 else None
    latest = pts[-1]["value_musd"]
    surge_x = round(latest / base_avg, 1) if base_avg else None

    out = {
        "status": "ok",
        "as_of": pts[-1]["date"],
        "series_id": "IEAXGG",
        "unit": "millions_usd",
        "frequency": "quarterly",
        "source": "FRED / U.S. BEA · Exports of Goods: Nonmonetary gold (IEAXGG)",
        "source_url": "https://fred.stlouisfed.org/series/IEAXGG",
        "title_note": (cached or {}).get("title_note",
                       "图作者原标 Monetary gold, FRED 无此序列; 真正对应暴涨的是 Nonmonetary gold"
                       "(非货币黄金=民间/商业实物金出口, 非央行储备金)。本 section 用 FRED 官方真标题诚实标注。"),
        "latest": latest, "latest_date": pts[-1]["date"],
        "peak": peak, "peak_date": peak_date,
        "base_2024_avg": base_avg, "surge_x": surge_x,
        "points": pts,
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


def fetch_us_yield_century(cache_path=None):
    """图5: 美国国债收益率百年周期(4线月度: Fed Funds/3M/10Y/30Y, FRED)。

    数据由 data/us_yield_century.json 驱动(scratch/build_yield_century.py 从 FRED 生成)。
    每季 cron 增量刷新最新月。抓不到读缓存真值绝不覆盖成空。
    诚实: 各线起点为 FRED 收录起点(TB3M 1934/FEDFUNDS 1954/GS10 1953/GS30 1977),
    1920-1933 FRED 无月度序列, 不编造。周期锚点 1940大底/1981大顶/2020大底。
    返回 {status, as_of, source, unit, annotations, cycles, series:{key:{label,color,points}}}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "us_yield_century.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "未获取", "as_of": "", "unit": "%",
                "source": "美国国债收益率百年周期(文件缺失)", "series": {}}
    if not data.get("series"):
        return {"status": "未获取", "as_of": data.get("as_of", ""), "unit": "%",
                "source": data.get("source", ""), "series": {}}
    data["status"] = data.get("status", "ok")
    return data


def fetch_comex_issue_stop_weekly(cache_path=None):
    """图1: COMEX 做市商每周净 issue/stop(金+银, 两口径: 全投行/核心做市商)。

    数据由 Comex-Daily-Report/data/comex_issue_stop_weekly.json 驱动
    (scratch/build_issue_stop_weekly.py 扫 archive 133 PDF + Notion 6/6+ 生成)。
    净值=Σ(大行发货)−Σ(大行接货), 正=净发货(交货/压价), 负=净接货(囤货/看涨)。
    每日 cron 增量: 采集当日 PDF→per-firm 拆分→并入当周。抓不到读缓存绝不覆盖成空。
    返回 {status, as_of, gold:[{week,all_net,core_net,...}], silver:[...], banks_all, banks_core}。
    """
    import json
    if cache_path is None:
        # 数据在姊妹 Comex 项目, Eco dashboard 跨项目读
        cache_path = "/home/user/Projects/Comex-Daily-Report/data/comex_issue_stop_weekly.json"
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "未获取", "as_of": "",
                "source": "COMEX 做市商周净 issue/stop(文件缺失)", "gold": [], "silver": []}
    if not (data.get("gold") or data.get("silver")):
        return {"status": "未获取", "as_of": data.get("archive_range", ""),
                "source": data.get("note", ""), "gold": [], "silver": []}
    data["status"] = data.get("status", "ok")
    # as_of = 最新周
    last_weeks = [r["week"] for r in (data.get("silver") or []) + (data.get("gold") or [])]
    data["as_of"] = max(last_weeks) if last_weeks else data.get("archive_range", "")
    return data


def fetch_fiscal_news(cache_path=None, limit=20):
    """美日财政政策事件时间线(离散事件文本,非时序数字)。
    数据由 data/fiscal_news.json 驱动: 每日 cron agent 模式 web 检索权威源
    (US Treasury/Congress/路透/彭博 · 日本财务省/NHK/日经)动态写入最新美日财政举措
    (债务上限/持续决议CR/政府关门/补正预算/国债发行计划等)。
    绝不编造: 每条事件带真实 source_url。本函数只读文件+按日期倒序+截断到 limit 条。
    返回 {status, as_of, source, events:[{date,country,flag,category,title,summary,source_url,source_name}]}。
    """
    import json
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "fiscal_news.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "未获取", "as_of": "", "source": "美日财政事件(文件缺失)", "events": []}
    events = data.get("events", []) or []
    # 只保留有必需字段的真实条目, 按日期倒序
    clean = [e for e in events if e.get("date") and e.get("title") and e.get("source_url")]
    clean.sort(key=lambda e: e.get("date", ""), reverse=True)
    clean = clean[:limit]
    return {
        "status": "ok" if clean else "未获取",
        "as_of": data.get("as_of", clean[0]["date"] if clean else ""),
        "source": data.get("source", "美日财政政策事件时间线"),
        "note": data.get("note", ""),
        "events": clean,
    }


def fetch_oil_inventory(cache_path=None):
    """美国石油库存运营红线三序列。绝不编造,取不到该项 status='未获取'。
      1) Brent-WTI 价差(过去一年,日频): FRED DCOILBRENTEU - DCOILWTICO(同日对齐,$/桶)
         价差转负(WTI>Brent)=Cushing 交割枢纽库存逼近 tank bottom 的市场信号。
      2) Cushing 原油库存(过去一年,周频): EIA W_EPC0_SAX_YCUOK_MBBL(千桶→百万桶)。运营红线~2000万桶(tank bottom)。
      3) SPR 战略石油储备(过去十年,周频): EIA WCSSTUS1(千桶→百万桶)。运营红线3亿桶(Amos Hochstein 披露)。
    返回 {status, as_of, spread:{...}, cushing:{...}, spr:{...}}。
    """
    import json, datetime as _dt
    if cache_path is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "oil_inventory.json")
    today = _dt.date.today()
    out = {"status": "ok", "as_of": today.isoformat(),
           "spread": {"status": "未获取"}, "cushing": {"status": "未获取"}, "spr": {"status": "未获取"}}

    # 1) Brent-WTI 价差(过去一年,日频)
    start_1y = (today - _dt.timedelta(days=400)).isoformat()
    brent = dict(_fred_series("DCOILBRENTEU", start=start_1y))
    wti = dict(_fred_series("DCOILWTICO", start=start_1y))
    common = sorted(set(brent) & set(wti))
    # 只保留近约 366 天
    cutoff = (today - _dt.timedelta(days=366)).isoformat()
    spread_pts = [(d, round(brent[d] - wti[d], 2)) for d in common if d >= cutoff]
    if len(spread_pts) >= 2:
        last_d, last_v = spread_pts[-1]
        neg_days = sum(1 for _, v in spread_pts if v < 0)
        out["spread"] = {
            "status": "ok", "points": spread_pts, "as_of": last_d,
            "latest": last_v, "hi": max(v for _, v in spread_pts),
            "lo": min(v for _, v in spread_pts), "neg_days": neg_days,
            "source": "FRED (DCOILBRENTEU - DCOILWTICO), 日频",
        }

    # 2) Cushing 库存(过去一年,周频) — EIA 千桶→百万桶
    cush = _eia_series("W_EPC0_SAX_YCUOK_MBBL", start=(today - _dt.timedelta(days=400)).strftime("%Y-%m-%d"))
    cush = [(d, round(v / 1000.0, 2)) for d, v in cush if d >= cutoff]
    if len(cush) >= 2:
        cd, cv = cush[-1]
        out["cushing"] = {
            "status": "ok", "points": cush, "as_of": cd, "latest": cv,
            "hi": max(v for _, v in cush), "lo": min(v for _, v in cush),
            "redline": 20.0,  # 运营红线 2000 万桶(tank bottom)
            "source": "EIA Weekly Petroleum Status (W_EPC0_SAX_YCUOK_MBBL), 周频",
        }

    # 3) SPR(过去十年,周频) — EIA 千桶→百万桶
    spr_start = (today - _dt.timedelta(days=3670)).strftime("%Y-%m-%d")  # ~10年+buffer
    spr = _eia_series("WCSSTUS1", start=spr_start)
    spr = [(d, round(v / 1000.0, 2)) for d, v in spr]
    if len(spr) >= 2:
        sd, sv = spr[-1]
        out["spr"] = {
            "status": "ok", "points": spr, "as_of": sd, "latest": sv,
            "hi": max(v for _, v in spr), "lo": min(v for _, v in spr),
            "redline": 300.0,  # 运营红线 3 亿桶(Amos Hochstein 披露)
            "source": "EIA Weekly Ending Stocks Crude Oil in SPR (WCSSTUS1), 周频",
        }

    if all(out[k].get("status") != "ok" for k in ("spread", "cushing", "spr")):
        out["status"] = "未获取"
    try:
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import json
    print("=== Credit Impulse 三国(信贷脉冲) ===")
    _ci = fetch_credit_impulse()
    for cc, d in _ci.items():
        if d["points"]:
            tail = ", ".join(f"{p['date'][:7]}:{p['ci']:+.2f}" for p in d["points"][-4:])
            print(f"  {d['flag']} {d['name']}: latest {d['latest']:+.2f} ({d['latest_date']}) [{d['signal']}]  近4季: {tail}")
        else:
            print(f"  {d['flag']} {d['name']}: {d['status']}")
    print("\n=== KOL 状态变化(近10天) ===")
    for ch in kol_stance_changes()[:8]:
        print(f"  {ch['date']} {ch['kol']}({ch['sector']}): {ch['prev_dir']} → {ch['new_dir']}")
    print("\n=== 流动性关键点 ===")
    print(json.dumps(fetch_liquidity_points(), ensure_ascii=False, indent=2, default=str)[:1500])
    print("\n=== 外国官方托管美债 (Fed H.4.1) ===")
    print(json.dumps(fetch_foreign_custody_ust(), ensure_ascii=False, indent=2, default=str))
    print("\n=== 美国国债拍卖 ===")
    print(json.dumps(fetch_treasury_auctions(), ensure_ascii=False, indent=2, default=str))
