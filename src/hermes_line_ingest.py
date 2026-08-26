"""hermes_line_ingest.py — 把本地自抓数据灌进「Hermes 独立线」18 张 Notion 表。

★血缘规则(Chao 2026-08-26): 只写 HDB_* (我自己的表), 绝不碰 DB_* / 他人的表。
★铁律: 数据一律来自本地真实落盘文件, 拿不到就写 0 行并如实报告, 绝不编造。

数据源 → 目标表:
    data/snapshots/*.json  .results   → HDB_INDICATORS   (102 天)
    data/snapshots/*.json  .cot       → HDB_COT          (金/银)
    reports/*.md                      → HDB_REPORT
    reports/weekly/*.md               → HDB_WEEKLY
    reports/monthly/*.md              → HDB_MONTHLY (暂无)
    data/holdings_13f.json            → HDB_HOLDINGS
    data/us_jp_yields.json            → HDB_YIELDS  (仅当前快照, 无历史序列)

未接入的表会如实返回 rows=0 + reason, 不留假数据。

用法:
    python -m src.hermes_line_ingest --plan          # 只统计, 不写
    python -m src.hermes_line_ingest --sample 3      # 每表样板 3 行
    python -m src.hermes_line_ingest --write         # 全量
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import kol_notion_sync as kns  # noqa: E402

HERMES_DATA = os.path.join(ROOT, "data", "hermes_line")
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
REPORT_DIR = os.path.join(ROOT, "reports")

# 只允许写这些表(全部 HDB_ 前缀)。硬闸门。
ALLOWED_PREFIX = "HDB_"


def _guard(env_key: str):
    if not env_key.startswith(ALLOWED_PREFIX):
        raise RuntimeError(f"REFUSED: {env_key} 非 HDB_* 表, 本模块禁止写入")


def rt(s, limit=2000):
    s = str(s or "")[:limit]
    return [{"type": "text", "text": {"content": s}}] if s else []


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _title(s):
    return {"title": rt(s)}


# ── 抽取器: 每个返回 [(uid, properties), ...] ─────────────────────

def ex_indicators():
    """每日指标。

    ★结构实测(2026-08-26): overall/hit 【不在】 data/snapshots/ 里,
      它们只存在于 data/daily/*.json。早先从 snapshot 取会全空。
      故: 指标值取 snapshots(102天全覆盖), 信号灯从 daily 按日期补(仅12天有)。
    """
    daily = {}
    for p in glob.glob(os.path.join(ROOT, "data", "daily", "*.json")):
        try:
            dd = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ds = (dd.get("date") or os.path.basename(p)[:-5]).strip()
        daily[ds] = dd

    rows = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ds = (d.get("date") or os.path.basename(p)[:-5]).strip()
        res = d.get("results") or {}
        if not ds or not res:
            continue
        g = lambda k: num((res.get(k) or {}).get("value"))
        dl = daily.get(ds) or {}
        props = {
            "日期": _title(ds),
            "触发数": {"number": num(dl.get("hit"))},
            "VIX": {"number": g("vix")},
            "HY利差": {"number": g("hy_oas")},
            "恐慌贪婪": {"number": g("fear_greed")},
            "数据源": {"rich_text": rt(f"data/snapshots/{os.path.basename(p)}"
                                    + (" + data/daily/" if dl else ""))},
        }
        ov = (dl.get("overall") or "").strip()
        if ov:
            props["综合信号"] = {"select": {"name": ov[:100]}}
        notes = [f"{k}={(v or {}).get('value')}" for k, v in res.items()
                 if isinstance(v, dict) and v.get("value") is not None]
        props["备注"] = {"rich_text": rt("; ".join(notes))}
        rows.append((f"ind|{ds}", props))
    return rows


def ex_cot():
    rows = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        cot = d.get("cot") or {}
        for metal, c in cot.items():
            if not isinstance(c, dict) or c.get("comm_net") is None:
                continue
            as_of = (c.get("as_of") or "").strip()
            if not as_of:
                continue
            rows.append((f"cot|{metal}|{as_of}", {
                "日期": _title(as_of),
                "品种": {"select": {"name": metal[:100]}},
                "商业净持仓": {"number": num(c.get("comm_net"))},
                "大户净持仓": {"number": num(c.get("noncomm_net"))},
                "未平仓合约": {"number": num(c.get("open_interest"))},
                "周变化": {"number": num(c.get("comm_net_wow"))},
                "数据源": {"rich_text": rt("CFTC COT via data/snapshots/")},
            }))
    # 同 (品种,日期) 去重, 保留最后一次
    ded = {}
    for uid, pr in rows:
        ded[uid] = pr
    return list(ded.items())


def _md_head(path, n=1800):
    try:
        return open(path, encoding="utf-8").read()[:n]
    except Exception:
        return ""


def ex_report():
    rows = []
    for p in sorted(glob.glob(os.path.join(REPORT_DIR, "*.md"))):
        ds = os.path.basename(p)[:-3]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            continue
        rows.append((f"rep|{ds}", {
            "日期": _title(ds),
            "摘要": {"rich_text": rt(_md_head(p))},
            "GitHub副本": {"url": f"reports/{os.path.basename(p)}"[:200]
                          if False else None},
        }))
    for _, pr in rows:
        pr.pop("GitHub副本", None)
    return rows


def ex_weekly():
    rows = []
    for p in sorted(glob.glob(os.path.join(REPORT_DIR, "weekly", "*.md"))):
        wk = os.path.basename(p)[:-3]
        rows.append((f"wk|{wk}", {
            "周": _title(wk),
            "综合研判": {"rich_text": rt(_md_head(p))},
        }))
    return rows


def ex_monthly():
    rows = []
    for p in sorted(glob.glob(os.path.join(REPORT_DIR, "monthly", "*.md"))):
        mo = os.path.basename(p)[:-3]
        rows.append((f"mo|{mo}", {
            "月份": _title(mo),
            "结构性变化": {"rich_text": rt(_md_head(p))},
        }))
    return rows


def ex_holdings():
    """13F 持仓。

    ★字段结构实测(2026-08-26): institutions[] 下【没有】holdings 键,
      实际持仓分散在 top_holdings / new_buys / exits 三个列表里,
      每项含 issuer/ticker/shares/prev_shares/value/action/pct。
      早先按 .holdings 取会静默得到 0 行 —— 已修正为遍历这三个列表。
    合并 holdings_13f.json(最新季) 与 holdings_13f_2025.json(历史季)。
    ★窗口(Chao 2026-08-26 选 B): 只取近 3 年季度。全量十年 15557 行,
      在 Notion 里几乎不会被翻, 真要长历史直接查本地 JSON 更快。
    """
    from datetime import date
    cutoff = f"{date.today().year - 3}-01-01"
    rows = []
    for fname in ("holdings_13f.json", "holdings_13f_2025.json"):
        p = os.path.join(ROOT, "data", fname)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for inst in d.get("institutions", []):
            if not isinstance(inst, dict):
                continue
            name = (inst.get("fund") or inst.get("kol") or "").strip()
            if not name:
                continue
            q = (inst.get("report_date") or d.get("date") or "").strip()
            if q and q < cutoff:          # 窗口 B: 只留近 3 年
                continue
            for bucket in ("top_holdings", "new_buys", "exits"):
                for h in (inst.get(bucket) or []):
                    if not isinstance(h, dict):
                        continue
                    tk = (h.get("ticker") or h.get("issuer") or "").strip()
                    if not tk:
                        continue
                    v = num(h.get("value"))
                    pr = {
                        "记录": _title(f"{q}｜{name}｜{tk}"),
                        "机构": {"rich_text": rt(name)},
                        "标的": {"rich_text": rt(
                            f"{tk} · {h.get('issuer','')} [{h.get('action','')}]")},
                        "持股数": {"number": num(h.get("shares"))},
                        "市值_百万": {"number": round(v / 1e6, 2) if v else None},
                        "环比变化": {"number": num(h.get("pct"))},
                        "数据源": {"rich_text": rt(f"SEC 13F via data/{fname}")},
                    }
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", q or ""):
                        pr["季度"] = {"date": {"start": q}}
                    # ★去重键含 action+shares: top_holdings 与 new_buys 会装
                    #   同一笔持仓(实测 195 例), 只按 ticker 去重会把同一笔算两遍。
                    #   而 exits(0股/清仓) 是不同事件, 必须保留为独立行。
                    sh = h.get("shares")
                    act = (h.get("action") or "").strip()
                    rows.append((f"h13f|{q}|{name}|{tk}|{act}|{sh}", pr, bucket))
    ded: dict = {}
    for uid, pr, bucket in rows:
        if uid in ded:
            ded[uid][1].add(bucket)        # 同一笔, 只记桶来源
        else:
            ded[uid] = (pr, {bucket})
    out = []
    for uid, (pr, buckets) in ded.items():
        src = pr["数据源"]["rich_text"]
        tag = "/".join(sorted(buckets))
        pr["数据源"] = {"rich_text": rt(
            (src[0]["text"]["content"] if src else "") + f" [{tag}]")}
        out.append((uid, pr))
    return out


def ex_yields():
    """美日国债收益率日频时序。

    ★结构实测(2026-08-26): series.<k> 是 dict, 真实数据在 .points = [[date, value], ...],
      【不是】 .value。早先按 .value 取 → 全 None 且只产 1 行,
      我据此误报过「本地无历史序列」。实际有一整年日频数据。
    """
    p = os.path.join(ROOT, "data", "us_jp_yields.json")
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    se = d.get("series") or {}
    col = {"us_10y": "US10Y", "us_30y": "US30Y",
           "jp_10y": "JP10Y", "jp_30y": "JP30Y"}
    by_date: dict = {}
    for key, label in col.items():
        s = se.get(key)
        if not isinstance(s, dict):
            continue
        for pt in (s.get("points") or []):
            if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
                continue
            ds, v = str(pt[0]).strip()[:10], num(pt[1])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or v is None:
                continue
            by_date.setdefault(ds, {})[label] = v
    rows = []
    for ds in sorted(by_date):
        vals = by_date[ds]
        pr = {"日期": _title(ds),
              "数据源": {"rich_text": rt("data/us_jp_yields.json .points")}}
        for label in col.values():
            pr[label] = {"number": vals.get(label)}
        u10, j10 = vals.get("US10Y"), vals.get("JP10Y")
        pr["利差"] = {"number": round(u10 - j10, 4)
                     if (u10 is not None and j10 is not None) else None}
        rows.append((f"y|{ds}", pr))
    return rows


def ex_custody():
    """外国官方托管美债 —— fetch_foreign_custody_ust().history_long = [[date, tn], ...]"""
    try:
        import external_data as ed
        d = ed.fetch_foreign_custody_ust() or {}
    except Exception:
        return []
    pts = d.get("history_long") or d.get("history") or []
    rows, prev = [], None
    for p in pts:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2):
            continue
        ds, tn = str(p[0])[:10], num(p[1])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or tn is None:
            continue
        bn = tn * 1000.0                      # 万亿 → 十亿
        rows.append((f"cu|{ds}", {
            "日期": _title(ds),
            "托管余额_十亿": {"number": round(bn, 2)},
            "周变化_十亿": {"number": round(bn - prev, 2) if prev else None},
            "数据源": {"rich_text": rt("NY Fed via fetch_foreign_custody_ust")},
        }))
        prev = bn
    return rows


def ex_money_supply():
    """三国货币供应 —— fetch_money_supply() → {US:{m0,m1,m2,as_of}, JP:..., CN:...}"""
    try:
        import external_data as ed
        d = ed.fetch_money_supply() or {}
    except Exception:
        return []
    rows = []
    for cc in ("US", "JP", "CN"):
        c = d.get(cc)
        if not isinstance(c, dict):
            continue
        mo = (c.get("as_of") or "").strip()
        if not mo:
            continue
        start = f"{mo}-01" if re.fullmatch(r"\d{4}-\d{2}", mo) else mo
        pr = {
            "记录": _title(f"{mo}｜{cc}"),
            "国家": {"select": {"name": cc}},
            "M0": {"number": num(c.get("m0"))},
            "M1": {"number": num(c.get("m1"))},
            "M2": {"number": num(c.get("m2"))},
            "数据源": {"rich_text": rt(str(c.get("source") or "")[:180])},
        }
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            pr["月份"] = {"date": {"start": start}}
        rows.append((f"ms|{mo}|{cc}", pr))
    return rows


def ex_ofr():
    """OFR 金融压力指数 —— 只有 latest 截面(无历史序列), 故仅 1 行。"""
    try:
        import external_data as ed
        d = ed.fetch_ofr_fsi() or {}
    except Exception:
        return []
    if (d.get("status") or "") != "ok":
        return []
    ds = (d.get("asof") or "").strip()[:10]
    lt = d.get("latest") or {}
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or not lt:
        return []
    return [(f"ofr|{ds}", {
        "日期": _title(ds),
        "OFR_FSI": {"number": num(lt.get("OFR FSI 总指数"))},
        "信用": {"number": num(lt.get("信用"))},
        "股票估值": {"number": num(lt.get("股票估值"))},
        "资金": {"number": num(lt.get("融资"))},
        "安全资产": {"number": num(lt.get("安全资产"))},
        "波动": {"number": num(lt.get("波动性"))},
        "数据源": {"rich_text": rt("OFR via fetch_ofr_fsi")},
    })]


def ex_nikkei():
    """日经225 —— points = [[date, close], ...]"""
    try:
        import external_data as ed
        d = ed.fetch_nikkei225() or {}
    except Exception:
        return []
    rows, prev = [], None
    for p in (d.get("points") or []):
        if not (isinstance(p, (list, tuple)) and len(p) >= 2):
            continue
        ds, v = str(p[0])[:10], num(p[1])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or v is None:
            continue
        rows.append((f"nk|{ds}", {
            "日期": _title(ds),
            "收盘": {"number": v},
            "涨跌幅": {"number": round((v - prev) / prev * 100, 3) if prev else None},
            "数据源": {"rich_text": rt(str(d.get("source") or "")[:180])},
        }))
        prev = v
    return rows


def ex_iip():
    """四国 IIP —— countries.<CC>.{assets,liab,net} = [[year, val], ...]"""
    try:
        import external_data as ed
        d = ed.fetch_iip_four_countries() or {}
    except Exception:
        return []
    rows = []
    for cc, c in (d.get("countries") or {}).items():
        if not isinstance(c, dict):
            continue
        m = {}
        for fld in ("assets", "liab", "net"):
            for p in (c.get(fld) or []):
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    m.setdefault(str(p[0]), {})[fld] = num(p[1])
        for yr, v in sorted(m.items()):
            if not re.fullmatch(r"\d{4}", yr):
                continue
            rows.append((f"iip|{yr}|{cc}", {
                "记录": _title(f"{yr}｜{cc}"),
                "期间": {"date": {"start": f"{yr}-12-31"}},
                "国家": {"select": {"name": cc}},
                "净头寸_万亿": {"number": v.get("net")},
                "资产": {"number": v.get("assets")},
                "负债": {"number": v.get("liab")},
                "数据源": {"rich_text": rt(str(d.get("source") or "")[:180])},
            }))
    return rows


def ex_hf_leverage():
    """对冲基金美债杠杆 —— exposure.points / borrow.repo = [(date, val), ...]"""
    try:
        import external_data as ed
        d = ed.fetch_hf_leverage() or {}
    except Exception:
        return []
    exp = (d.get("exposure") or {}).get("points") or []
    rep = (d.get("borrow") or {}).get("repo") or []
    m = {}
    for ds, v in [(str(a)[:10], num(b)) for a, b in exp
                  if isinstance(a, str) or True]:
        m.setdefault(ds, {})["lev"] = v
    for ds, v in [(str(a)[:10], num(b)) for a, b in rep]:
        m.setdefault(ds, {})["repo"] = v
    rows = []
    for ds in sorted(m):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            continue
        rows.append((f"hf|{ds}", {
            "记录": _title(ds),
            "季度": {"date": {"start": ds}},
            "杠杆倍数": {"number": m[ds].get("lev")},
            "回购敞口_十亿": {"number": m[ds].get("repo")},
            "数据源": {"rich_text": rt(str(d.get("source") or "OFR")[:180])},
        }))
    return rows


def ex_bis_swaps():
    """BIS 自营黄金掉期 —— points = [{date, tonnes, kind, src}, ...]"""
    try:
        import external_data as ed
        d = ed.fetch_bis_gold_swaps() or {}
    except Exception:
        return []
    rows, prev = [], None
    for p in (d.get("points") or []):
        if not isinstance(p, dict):
            continue
        ds, t = str(p.get("date") or "")[:10], num(p.get("tonnes"))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or t is None:
            continue
        rows.append((f"bis|{ds}", {
            "记录": _title(f"{ds}｜{p.get('kind','')}"),
            "月份": {"date": {"start": ds}},
            "掉期_吨": {"number": t},
            "环比": {"number": round(t - prev, 2) if prev is not None else None},
            "数据源": {"rich_text": rt(str(p.get("src") or "")[:180])},
        }))
        prev = t
    return rows


def ex_fiscal_news():
    """美日财政事件 —— events = [{date,country,category,title,summary,source_url}]"""
    try:
        import external_data as ed
        d = ed.fetch_fiscal_news() or {}
    except Exception:
        return []
    rows = []
    for ev in (d.get("events") or []):
        if not isinstance(ev, dict):
            continue
        ds = str(ev.get("date") or "")[:10]
        ti = (ev.get("title") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or not ti:
            continue
        pr = {
            "标题": _title(f"{ds}｜{ti}"),
            "日期": {"date": {"start": ds}},
            "摘要": {"rich_text": rt(ev.get("summary"))},
            "数据源": {"rich_text": rt(str(ev.get("source_name") or "")[:180])},
        }
        if ev.get("country"):
            pr["国家"] = {"select": {"name": str(ev["country"])[:100]}}
        if ev.get("category"):
            pr["类别"] = {"select": {"name": str(ev["category"])[:100]}}
        u = (ev.get("source_url") or "").strip()
        if u.startswith("http"):
            pr["来源链接"] = {"url": u}
        rows.append((f"fn|{ds}|{ti[:40]}", pr))
    return rows


def ex_foreign_flow():
    """外资净买入日股(周频)。

    ★★2026-08-26 血的教训: 【绝不调用 ed.fetch_foreign_flow_japan()】。
      该 fetcher 抓取失败时会把 data/foreign_flow_japan.json 覆盖成
      {"status":"未获取"} —— 我探测时就这么干过一次, 53 周真实数据被抹掉,
      靠 git checkout 才救回。这正是本项目 AGENTS.md 记的「空值覆盖真值」陷阱。
      本抽取器【只读缓存文件】, 不触发任何网络抓取。
    """
    p = os.path.join(ROOT, "data", "foreign_flow_japan.json")
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    if (d.get("status") or "") != "ok":
        return []
    rows, cum = [], 0.0
    for pt in (d.get("points") or []):
        if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
            continue
        ds, v = str(pt[0])[:10], num(pt[1])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) or v is None:
            continue
        cum += v
        rows.append((f"ff|{ds}", {
            "记录": _title(ds),
            "周": {"date": {"start": ds}},
            "净买入_万亿日元": {"number": v},
            "累计": {"number": round(cum, 3)},
            "数据源": {"rich_text": rt(str(d.get("source") or "")[:180])},
        }))
    return rows


EXTRACTORS = {
    "HDB_INDICATORS": (ex_indicators, "日期"),
    "HDB_COT": (ex_cot, "日期"),
    "HDB_REPORT": (ex_report, "日期"),
    "HDB_WEEKLY": (ex_weekly, "周"),
    "HDB_MONTHLY": (ex_monthly, "月份"),
    "HDB_HOLDINGS": (ex_holdings, "记录"),
    "HDB_YIELDS": (ex_yields, "日期"),
    "HDB_CUSTODY": (ex_custody, "日期"),
    "HDB_MONEY_SUPPLY": (ex_money_supply, "记录"),
    "HDB_OFR": (ex_ofr, "日期"),
    "HDB_NIKKEI": (ex_nikkei, "日期"),
    "HDB_IIP": (ex_iip, "记录"),
    "HDB_HF_LEVERAGE": (ex_hf_leverage, "记录"),
    "HDB_BIS_GOLD_SWAPS": (ex_bis_swaps, "记录"),
    "HDB_FISCAL_NEWS": (ex_fiscal_news, "标题"),
    "HDB_FOREIGN_FLOW": (ex_foreign_flow, "记录"),
}

# ★幂等键补充字段(Chao 2026-08-26 实测暴露, 两次):
#   ① COT 同一日期有 gold/silver 两行, 只用 title(日期) 去重会把第二行
#      静默跳过 —— 实测丢了 2026-06-09 silver。
#   ② HOLDINGS 同季同标的可有「清旧仓 + 建新仓」两个真实事件
#      (如 Berkshire 2026-06-30 BAC: 新建 483,394,015 股 / 清仓 0 股),
#      只用 title 去重会在下次增量跑时静默漏掉其中一条。
#   凡 title 不唯一的表, 必须在此声明附加字段, 组合成真正的唯一键。
DEDUP_EXTRA = {
    "HDB_COT": ["品种"],
    "HDB_HOLDINGS": ["标的", "持股数"],
}


def _field_text(v: dict) -> str:
    """把任意 Notion 属性值(本地构造 或 API 返回)压成可比字符串。"""
    if not v:
        return ""
    if "select" in v:
        return str((v.get("select") or {}).get("name", ""))
    if "number" in v:
        n = v.get("number")
        return "" if n is None else repr(float(n))
    if "rich_text" in v:
        parts = []
        for x in v.get("rich_text") or []:
            parts.append(x.get("plain_text")
                         or (x.get("text") or {}).get("content", ""))
        return "".join(parts)
    if "date" in v:
        return str((v.get("date") or {}).get("start", ""))
    return ""


def _row_key(props: dict, title_field: str, table: str) -> str:
    """本地行的唯一键 = title + 附加字段。"""
    parts = [_local_title(props, title_field)]
    for f in DEDUP_EXTRA.get(table, []):
        parts.append(_field_text(props.get(f)))
    return "|".join(parts)


def _notion_key(props: dict, title_field: str, table: str) -> str:
    """Notion 已有行的唯一键, 必须与 _row_key 同构。"""
    parts = [kns.plain(props.get(title_field))]
    for f in DEDUP_EXTRA.get(table, []):
        parts.append(_field_text(props.get(f)))
    return "|".join(parts)

NOT_WIRED = {
    "HDB_AUCTIONS": "本地/fetcher 均无落盘序列, 需另接 Treasury 拍卖结果源",
    "HDB_STRESS": "无历史序列 fetcher, 需另接",
}


def _local_title(props: dict, title_field: str) -> str:
    """从【本地构造的】payload 里取标题文本。

    ★不可用 kns.plain(): 那个函数解析的是 Notion【返回】的结构(带 plain_text),
      本地构造的是 {"type":"text","text":{"content":...}} —— 无 plain_text 键,
      直接传进去会 KeyError。两种结构必须分开处理。
    """
    try:
        return "".join(x["text"]["content"]
                       for x in props[title_field]["title"])
    except Exception:
        return ""


def snapshot_local(rows_by_table: dict):
    """把抽取结果落到 data/hermes_line/ —— 我自己的数据源, 不共用。"""
    os.makedirs(HERMES_DATA, exist_ok=True)
    for k, rows in rows_by_table.items():
        with open(os.path.join(HERMES_DATA, f"{k}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"table": k, "count": len(rows),
                       "rows": [{"uid": u, "props": p} for u, p in rows]},
                      f, ensure_ascii=False, indent=1)


def run(mode="plan", sample=0):
    n = kns.Notion()
    e = kns._env()
    out = {"tables": {}, "not_wired": NOT_WIRED, "errors": []}
    all_rows = {}
    for key, (fn, title_field) in EXTRACTORS.items():
        try:
            rows = fn()
        except Exception as ex:
            out["errors"].append(f"{key} 抽取失败: {ex}")
            continue
        all_rows[key] = rows
        out["tables"][key] = {"extracted": len(rows), "written": 0}
        if mode == "plan":
            continue
        _guard(key)
        dbid = e.get(key)
        if not dbid:
            out["errors"].append(f"{key} .env 缺 id")
            continue
        # 读已有 title 做幂等
        have = set()
        try:
            for r in n.query_all(dbid):
                have.add(_notion_key(r["properties"], title_field, key))
        except Exception as ex:
            out["errors"].append(f"{key} 读表失败: {ex}")
            continue
        todo = [(u, p) for u, p in rows
                if _row_key(p, title_field, key) not in have]
        if sample:
            todo = todo[:sample]
        for uid, props in todo:
            try:
                n.call("/pages", "POST",
                       {"parent": {"database_id": dbid}, "properties": props})
                out["tables"][key]["written"] += 1
                time.sleep(0.34)
            except Exception as ex:
                out["errors"].append(f"{key} {uid}: {str(ex)[:120]}")
                if len(out["errors"]) > 25:
                    out["aborted"] = True
                    return out
    snapshot_local(all_rows)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args()
    mode = "write" if (a.write or a.sample) else "plan"
    print(json.dumps(run(mode, a.sample), ensure_ascii=False, indent=1))
