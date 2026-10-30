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
_TAG = re.compile(r"<[^>]+>")


def _load():
    try:
        d = json.load(open(SENTINEL, encoding="utf-8"))
        return {r["name"]: r for r in d.get("results", [])}
    except Exception:
        return {}


def annotate(html: str) -> str:
    rec = _load()
    if not rec:
        return html     # 哨兵没跑过 → 不加任何东西(不编)
    pat = re.compile(r'(<div class="part-title"[^>]*>)(.*?)(</div>)', re.S)

    def fix(m):
        head, inner, tail = m.group(1), m.group(2), m.group(3)
        if "freq-badge" not in inner:
            return m.group(0)
        title = _TAG.sub("", inner)
        name = next((n for k, n in MAP if k in title or k in inner), None)
        r = rec.get(name) if name else None
        if not r or not r.get("as_of"):
            return m.group(0)
        bm = re.search(r'<span class="freq-badge([^"]*)">([^<]*)</span>', inner)
        if not bm:
            return m.group(0)
        cls, txt = bm.group(1), re.sub(r"\s*·\s*源头 .*$", "", bm.group(2))
        lag, tol = r.get("lag_days"), r.get("tol_days")
        mmdd = r["as_of"][5:] if len(r["as_of"]) >= 10 else r["as_of"]
        stale = (lag is not None and tol is not None and lag > tol)
        cls = cls.replace(" freq-stale", "") + (" freq-stale" if stale else "")
        new = f'<span class="freq-badge{cls}">{txt} · 源头 {mmdd}（滞后{lag}天）</span>'
        return head + inner.replace(bm.group(0), new) + tail

    return pat.sub(fix, html)
