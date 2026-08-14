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


# sector 中英归一(Notion DB 用英文, independent.json 用中文) → 统一中文模块名 + 英文副标 + 色
_KOL_SECTOR_MAP = {
    "Precious Metals": ("贵金属", "Precious Metals"),
    "贵金属": ("贵金属", "Precious Metals"),
    "贵金属与商品周期": ("贵金属与商品周期", "Precious Metals & Commodity Cycle"),
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
    """从『上周一至今』识别 KOL 方向转向, 按 sector 模块分组。
    优先用 cron 独立抓的 kol_independent.json 的 changes(当日精准), 但那只有当日;
    历史转向靠另一 agent 的 Notion by_day DB(逐日时序)回看 → kol_stance_changes(days)。
    返回 {"since": 上周一日期, "days": N, "total": 转向总数,
          "modules": [{"sector":中文, "en":英文, "color":色, "changes":[{kol,prev_dir,new_dir,date,comments,targets,sub_sector},...]}]}
    绝不编: 无数据则 modules=[]。"""
    if days is None:
        days = _days_since_last_monday()
    import datetime as _dt
    today = _dt.date.today()
    since = (today - _dt.timedelta(days=days - 1)).strftime("%Y-%m-%d")

    # 主源: Notion by_day 逐日时序(支持跨天回看)
    raw = kol_stance_changes(days=days)  # [{kol,sector,prev_dir,new_dir,date,comments,targets}]
    # 补充: independent.json 的当日 changes(可能有 Notion DB 尚未同步的)
    try:
        ind_changes, _ = load_independent_kol()
        seen = {c["kol"] for c in raw}
        for c in ind_changes:
            if c.get("kol") and c["kol"] not in seen:
                raw.append(c)
                seen.add(c["kol"])
    except Exception:
        pass

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
            ("MBS 抵押债", "资产_MBS_B"),
            ("短期国债 Bills", "资产_Bills_B"),
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
    # ── 统一换算成 $B(十亿美元) ──
    if to_usd:
        try:
            from fetchers.fred import fetch_fred_latest
            jpy, _ = fetch_fred_latest("DEXJPUS")   # 日元/美元(如 147.5)
            cny, _ = fetch_fred_latest("DEXCHUS")   # 人民币/美元(如 7.15)
            # BoJ: 兆¥(1e12¥) → $B: ×1000/jpy
            if "JP" in out and jpy:
                out["JP"] = _usd_convert(out["JP"], 1000.0 / jpy, "兆¥")
            # PBoC: 亿¥(1e8¥) → $B: ×0.1/cny
            if "CN" in out and cny:
                out["CN"] = _usd_convert(out["CN"], 0.1 / cny, "亿¥")
            # 记录换算汇率(可溯源)
            out["_fx"] = {"USDJPY": jpy, "USDCNY": cny}
        except Exception as e:
            out["_fx_error"] = str(e)
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
            "status": "ok",
            "source": "FRED WMTSECL1 (Fed H.4.1 custody, weekly Wed)",
        }
    return {"value": None, "as_of": None, "history": hist, "history_long": hist_long,
            "total_custody_tn": total_custody_tn,
            "status": "FRED WMTSECL1 无数据"}


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
    """从 TIC mfhhis 文本解析某国月度序列。country_key: 'Japan' 或 'China'。
    文件结构: 每个年份块有一"月份行"(Jan..Dec)+"年份行"(Country + 4位年份),
    随后 Japan / 'China, Mainland' 数据行, 按列对齐。返回 {'YYYY-MM': value_$B} 。"""
    import re
    lines = raw.replace("\r", "").split("\n")
    series = {}
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
        matched = (country_key == "Japan" and name == "Japan") or \
                  (country_key == "China" and name.startswith("China"))
        if matched and cur_months and cur_years:
            for i, mm in cur_months.items():
                yy = cur_years.get(i)
                if not yy or i >= len(cells):
                    continue
                v = cells[i].replace(",", "").strip()
                try:
                    series[f"{yy:04d}-{mm:02d}"] = float(v)
                except ValueError:
                    continue
    return series


def fetch_country_ust_holdings(years=10):
    """抓 日本 / 中国 分国别持有美债的月度序列(近 N 年)。
    源: 美国财政部 TIC Major Foreign Holders 历史文件(官方, 月度, $B)。
    返回 {"Japan":{...}, "China":{...}} 每个:
      {name, flag, series:[(YYYY-MM, $B),...]升序, latest:(month,val), first:(month,val),
       delta_bn, delta_pct, high, low, status, source} ; 拿不到 status='未找到'。
    绝不编: 解析失败留空 series + status。"""
    import requests
    import datetime
    out = {}
    meta = {"Japan": ("日本", "🇯🇵"), "China": ("中国大陆", "🇨🇳")}
    cutoff = (datetime.date.today().replace(day=1) -
              datetime.timedelta(days=int(years * 365.25) + 45)).strftime("%Y-%m")
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
            out[key] = {"name": zh, "flag": flag, "series": [], "status": "未找到",
                        "source": "US Treasury TIC MFH"}
            continue
        s = _parse_tic_country(raw, key)
        pts = sorted((m, v) for m, v in s.items() if m >= cutoff)
        if len(pts) < 2:
            out[key] = {"name": zh, "flag": flag, "series": pts, "status": "数据不足",
                        "source": "US Treasury TIC MFH"}
            continue
        first_m, first_v = pts[0]
        last_m, last_v = pts[-1]
        vals = [v for _, v in pts]
        out[key] = {
            "name": zh, "flag": flag, "series": pts,
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
    """三国 M2 月度历史序列(默认126月≈10.5年),用于折线图。折 $B 用当月汇率(反映真实美元口径)。
    源: US=FRED M2SL / JP=BOJ stat-search CSV(第10列亿円,Shift_JIS) / CN=东方财富 datacenter API(亿元)。
    返回 {"US":{unit,points:[{date,value},...],orig_unit,latest,source}, "JP":{...}, "CN":{...}}。
    绝不编: 某国抓不到→该国 points=[] + status。折美元用 FRED 月度 DEXJPUS/DEXCHUS 历史序列(按月对齐,缺则用最近汇率)。"""
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

    # 历史汇率(月度, YYYY-MM -> rate), 用于按月折美元
    jpy_hist = dict(_fred_series("DEXJPUS", cosd))
    cny_hist = dict(_fred_series("DEXCHUS", cosd))

    def _rate_for(month, hist, fallback):
        """取该月汇率, 缺则用最近可得(往前找), 再缺用 fallback。"""
        if month in hist:
            return hist[month]
        keys = sorted(k for k in hist if k <= month)
        if keys:
            return hist[keys[-1]]
        return fallback

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
            rate = _rate_for(mon, jpy_hist, 157.54)
            val = round(tri * 1000.0 / rate, 1)  # 万亿円→$B
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
            rate = _rate_for(mon, cny_hist, 6.7474)
            val = round(wy * 1000.0 / rate, 1)  # 万亿元→$B
        out["CN"]["points"].append({"date": mon, "value": round(val, 1), "orig": round(wy, 1)})

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


if __name__ == "__main__":
    import json
    print("=== KOL 状态变化(近10天) ===")
    for ch in kol_stance_changes()[:8]:
        print(f"  {ch['date']} {ch['kol']}({ch['sector']}): {ch['prev_dir']} → {ch['new_dir']}")
    print("\n=== 流动性关键点 ===")
    print(json.dumps(fetch_liquidity_points(), ensure_ascii=False, indent=2, default=str)[:1500])
    print("\n=== 外国官方托管美债 (Fed H.4.1) ===")
    print(json.dumps(fetch_foreign_custody_ust(), ensure_ascii=False, indent=2, default=str))
    print("\n=== 美国国债拍卖 ===")
    print(json.dumps(fetch_treasury_auctions(), ensure_ascii=False, indent=2, default=str))
