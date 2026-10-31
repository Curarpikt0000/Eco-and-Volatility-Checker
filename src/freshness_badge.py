#!/usr/bin/env python3
"""给看板每个「频率标签」追加『源头最新日 · 滞后 N 天』(Chao 2026-10-30: 页面日期不可靠, 要读源头)。

数据来源: data/freshness_sentinel.json (哨兵每日跑, 读各 fetcher 的真实末点, 不是页面里的日期)。
做法: 对已渲染的 HTML 做后处理 —— 在 <div class="part-title" ...>...<span class="freq-badge ...">文本</span> 里,
  按板块标题关键词匹配到哨兵里的数据源, 在徽章文本后追加 ' · 源头 MM-DD(滞后N天)'。
  - 只匹配「标题关键词 → 哨兵 name」映射表里明确对应的; 没映射到的板块保持原样(不硬配、不编)。
  - 滞后超容忍 → 徽章加 freq-stale 类(红色), 一眼可见。
  - 幂等: 已追加过的先剥掉再加。
用法: from src.freshness_badge import annotate; html = annotate(html)
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = os.path.join(ROOT, "data", "freshness_sentinel.json")

# 板块标题关键词 → 哨兵 name。顺序即优先级(靠前的先匹配)。只放有明确数据源对应的。
MAP = [
    ("中国央行流动性", "china_liquidity"),
    ("A 股资金面", None),                    # 多源混合, 不单配
    ("央行货币互换", "cb_liquidity_swaps"),
    ("Credit Impulse", "credit_impulse"),
    ("政府债务 / GDP", "debt_to_gdp"),
    ("美国公司债", "corporate_credit"),
    ("CIPS", "cips"),
    ("AI 产业链", "ai_fcf"),
    ("国债市场收益率·波动性·压力", "treasury_stress_panels"),
    ("基差套利去杠杆", "basis_trade_monitor"),
    ("国债拍卖", "treasury_auctions"),
    ("外国官方托管美债", "foreign_custody_ust"),
    ("美日 10年/30年国债收益率", "us_jp_yields"),
    ("日经225 vs 外资", "nikkei225"),
    ("美国国债收益率百年周期", "us_yield_century"),
    ("对冲基金美债杠杆", "hf_leverage"),
    ("美日财政政策事件", "fiscal_news"),
    ("日美年度财政花费", "fiscal_budget"),
    ("美国黄金出口", "gold_exports"),
    ("黄金 Domestic Premium", "gold_premium"),
    ("印度 &amp; 中国黄金", "gold_premium"),
    ("印度白银月度进口", "silver_imports_data"),
    ("BIS 自营黄金掉期", "bis_gold_swaps"),
    ("COMEX &amp; 上海贵金属库存", "comex_inventory"),
    ("COMEX 做市商每周净", "comex_issue_stop_weekly"),
    ("COMEX 交割前十名", "comex_issue_stop_firms"),
    ("白银做市商头寸", "silver_bank_positions"),
    ("NYSE A/D 腾落线", "ad_line_real"),
    ("美国石油库存", "oil_inventory"),
    ("三国货币供应量", "money_supply"),
    ("三国 M2 十年走势", "m2_history"),
    ("四国国际投资头寸", "iip_four_countries"),
    ("持有美债", "country_ust_holdings"),
]
# 手工/静态板块 → data/manual_checks.json 的键(2026-10-31, Chao 批准 Opus 建议『页面标最后检查日』)
# 值是 (登记键, 子键或None)。子键用于一个板块里多国分别登记(三国货币供应量=CN 核对过/JP 未核对)。
MANUAL = [
    ("三国货币供应量", ("money_supply", None)),
    ("美日财政政策事件", ("fiscal_news", None)),
    ("BIS 自营黄金掉期", ("bis_gold_swaps", None)),
    ("日美年度财政花费", ("japan_budget", None)),
    ("COMEX 白银 投行累计", ("comex_silver_static", None)),
]
MANUAL_FILE = os.path.join(ROOT, "data", "manual_checks.json")
_TAG = re.compile(r"<[^>]+>")


def _manual():
    try:
        return json.load(open(MANUAL_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _manual_text(reg, key):
    """返回徽章后缀文本。有登记 → '人工核对 MM-DD'; 分国登记 → 'CN MM-DD / JP 未登记'; 全 null → '人工核对日 未登记'。"""
    e = reg.get(key) or {}
    det = e.get("detail")
    if det:
        parts = [f"{c} {(v.get('checked') or '')[5:] or '未登记'}" for c, v in det.items()]
        return "人工核对 " + " / ".join(parts)
    c = e.get("checked")
    return f"人工核对 {c[5:]}" if c else "人工核对日 未登记"



def _load():
    try:
        d = json.load(open(SENTINEL, encoding="utf-8"))
        return {r["name"]: r for r in d.get("results", [])}
    except Exception:
        return {}


def annotate(html: str) -> str:
    rec = _load()
    reg = _manual()
    if not rec and not reg:
        return html     # 哨兵和登记表都没有 → 不加任何东西(不编)
    pat = re.compile(r'(<div class="part-title"[^>]*>)(.*?)(</div>)', re.S)

    def fix(m):
        head, inner, tail = m.group(1), m.group(2), m.group(3)
        if "freq-badge" not in inner:
            return m.group(0)
        title = _TAG.sub("", inner)
        # ★徽章可能带 style 属性(如白银静态参考 <span class="freq-badge" style="...">): 捕获 class 之后、> 之前的全部属性
        bm = re.search(r'<span class="freq-badge([^"]*)"([^>]*)>([^<]*)</span>', inner)
        if not bm:
            return m.group(0)
        cls, extra_attr, txt = bm.group(1), bm.group(2), re.sub(r"\s*·\s*(源头|人工核对).*$", "", bm.group(3))
        name = next((n for k, n in MAP if k in title or k in inner), None)
        r = rec.get(name) if name else None
        parts = []
        stale = False
        if r and r.get("as_of"):
            lag, tol = r.get("lag_days"), r.get("tol_days")
            mmdd = r["as_of"][5:] if len(r["as_of"]) >= 10 else r["as_of"]
            stale = (lag is not None and tol is not None and lag > tol)
            parts.append(f"源头 {mmdd}（滞后{lag}天）")
        mk = next((v for k, v in MANUAL if k in title or k in inner), None)
        if mk:
            parts.append(_manual_text(reg, mk[0]))
        if not parts:
            return m.group(0)
        cls = cls.replace(" freq-stale", "") + (" freq-stale" if stale else "")
        new = f'<span class="freq-badge{cls}"{extra_attr}>{txt} · ' + " · ".join(parts) + "</span>"
        return head + inner.replace(bm.group(0), new) + tail

    return pat.sub(fix, html)
