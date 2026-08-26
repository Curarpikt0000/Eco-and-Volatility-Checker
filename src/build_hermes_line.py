"""build_hermes_line.py — 建立「Hermes 独立线」的 Notion 表体系。

★2026-08-26 Chao 拍板的血缘规则(无例外):
    只要数据是【我抓的 / 我的 LLM 产出的】 → 必须有我自己的 DB + 我自己的数据源文件
    只是【只读别人的表】               → 不建, 保持只读
    别人创建/维护的表                  → 完全不碰

血缘核查结论(grep src/ 全部写入方逐一确认):
    .env 里 17 张 DB 全部由本项目代码抓取写入(CFTC/NY Fed/Treasury/FRED/OFR/SEC 13F...),
    无一张是别人抓的 → 17 张全部需要在独立线重建, 外加我自己的月报, 共 18 张。

    例外(不重建):
      - Notion「KOL List」  = Chao 创建的名册 SSOT, 我只读 → 不建
      - DB_KOL_VIEWS        = 另一 agent 的表(我的 integration 已无权访问) → 不碰
      - 月报表(他人今日新建) = 他们的 → 不碰, 我建自己的

用法:
    python -m src.build_hermes_line --plan     # 只打印计划, 不写
    python -m src.build_hermes_line --create   # 建子页 + 18 张表, 写回 .env(HDB_*)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import kol_notion_sync as kns  # noqa: E402

PARENT_PAGE = "3b947eb5-fd3c-80ea-9b06-d41704af3b05"
SUBPAGE_TITLE = "Eco · Hermes 独立线"
ENV_PATH = os.path.join(ROOT, ".env")
HERMES_DATA = os.path.join(ROOT, "data", "hermes_line")

T = "title"
RT = "rich_text"
NUM = "number"
DATE = "date"
SEL = "select"
URL = "url"


def _p(kind: str, **kw):
    return {kind: kw or {}}


# 18 张表定义: env_key → (标题, 属性表, 说明)
TABLES = {
    "HDB_INDICATORS": ("Hermes · 每日指标", {
        "日期": _p(T), "综合信号": _p(SEL), "触发数": _p(NUM),
        "VIX": _p(NUM), "HY利差": _p(NUM), "10Y": _p(NUM), "30Y": _p(NUM),
        "美元指数": _p(NUM), "黄金": _p(NUM), "白银": _p(NUM),
        "恐慌贪婪": _p(NUM), "备注": _p(RT), "数据源": _p(RT),
    }, "17项指标时序+信号灯"),
    "HDB_COT": ("Hermes · 金银 COT", {
        "日期": _p(T), "品种": _p(SEL), "商业净持仓": _p(NUM),
        "大户净持仓": _p(NUM), "散户净持仓": _p(NUM),
        "未平仓合约": _p(NUM), "周变化": _p(NUM), "数据源": _p(RT),
    }, "CFTC 持仓周报"),
    "HDB_CUSTODY": ("Hermes · 外国官方托管美债", {
        "日期": _p(T), "托管余额_十亿": _p(NUM), "周变化_十亿": _p(NUM),
        "四周变化_十亿": _p(NUM), "数据源": _p(RT),
    }, "NY Fed 托管数据"),
    "HDB_AUCTIONS": ("Hermes · 国债拍卖", {
        "记录": _p(T), "拍卖日": _p(DATE), "期限": _p(SEL),
        "中标利率": _p(NUM), "投标倍数": _p(NUM), "间接认购比": _p(NUM),
        "尾部": _p(NUM), "规模_十亿": _p(NUM), "数据源": _p(RT),
    }, "Treasury 拍卖结果"),
    "HDB_MONEY_SUPPLY": ("Hermes · 货币供应量 M0/M1/M2", {
        "记录": _p(T), "月份": _p(DATE), "国家": _p(SEL),
        "M0": _p(NUM), "M1": _p(NUM), "M2": _p(NUM),
        "同比": _p(NUM), "数据源": _p(RT),
    }, "三国货币供应"),
    "HDB_STRESS": ("Hermes · 国债市场压力", {
        "日期": _p(T), "MOVE": _p(NUM), "SOFR利差": _p(NUM),
        "掉期利差": _p(NUM), "流动性指数": _p(NUM), "数据源": _p(RT),
    }, "国债压力四联图"),
    "HDB_OFR": ("Hermes · OFR金融压力指数", {
        "日期": _p(T), "OFR_FSI": _p(NUM), "信用": _p(NUM),
        "股票估值": _p(NUM), "资金": _p(NUM), "安全资产": _p(NUM),
        "波动": _p(NUM), "数据源": _p(RT),
    }, "OFR 官方压力指数"),
    "HDB_YIELDS": ("Hermes · 美日国债收益率", {
        "日期": _p(T), "US10Y": _p(NUM), "US30Y": _p(NUM),
        "JP10Y": _p(NUM), "JP30Y": _p(NUM), "利差": _p(NUM), "数据源": _p(RT),
    }, "美日收益率日频"),
    "HDB_NIKKEI": ("Hermes · 日经225", {
        "日期": _p(T), "收盘": _p(NUM), "涨跌幅": _p(NUM),
        "成交额": _p(NUM), "数据源": _p(RT),
    }, "日经指数日频"),
    "HDB_FOREIGN_FLOW": ("Hermes · 外资净买入日股", {
        "记录": _p(T), "周": _p(DATE), "净买入_万亿日元": _p(NUM),
        "累计": _p(NUM), "数据源": _p(RT),
    }, "外资流动周频"),
    "HDB_IIP": ("Hermes · 四国IIP国际投资头寸", {
        "记录": _p(T), "期间": _p(DATE), "国家": _p(SEL),
        "净头寸_万亿": _p(NUM), "资产": _p(NUM), "负债": _p(NUM), "数据源": _p(RT),
    }, "IIP 年频"),
    "HDB_HF_LEVERAGE": ("Hermes · 对冲基金美债杠杆", {
        "记录": _p(T), "季度": _p(DATE), "杠杆倍数": _p(NUM),
        "回购敞口_十亿": _p(NUM), "数据源": _p(RT),
    }, "OFR 季度杠杆"),
    "HDB_BIS_GOLD_SWAPS": ("Hermes · BIS自营黄金掉期", {
        "记录": _p(T), "月份": _p(DATE), "掉期_吨": _p(NUM),
        "环比": _p(NUM), "数据源": _p(RT),
    }, "BIS 黄金掉期"),
    "HDB_FISCAL_NEWS": ("Hermes · 美日财政政策事件", {
        "标题": _p(T), "日期": _p(DATE), "国家": _p(SEL),
        "类别": _p(SEL), "摘要": _p(RT), "来源链接": _p(URL), "数据源": _p(RT),
    }, "财政事件检索"),
    "HDB_HOLDINGS": ("Hermes · 机构持仓 13F", {
        "记录": _p(T), "季度": _p(DATE), "机构": _p(RT),
        "标的": _p(RT), "持股数": _p(NUM), "市值_百万": _p(NUM),
        "环比变化": _p(NUM), "数据源": _p(RT),
    }, "SEC 13F 季度"),
    "HDB_REPORT": ("Hermes · 每日报告", {
        "日期": _p(T), "综合信号": _p(SEL), "触发数": _p(NUM),
        "摘要": _p(RT), "KOL转向": _p(RT), "流动性要点": _p(RT),
        "GitHub副本": _p(URL),
    }, "我的 LLM 日报"),
    "HDB_WEEKLY": ("Hermes · 周报", {
        "周": _p(T), "起止": _p(DATE), "综合研判": _p(RT),
        "指标变化": _p(RT), "KOL周内转向": _p(RT), "下周关注": _p(RT),
        "GitHub副本": _p(URL),
    }, "我的 LLM 周报"),
    "HDB_MONTHLY": ("Hermes · 月报", {
        "月份": _p(T), "期间": _p(DATE), "结构性变化": _p(RT),
        "指标月度汇总": _p(RT), "KOL月度转向": _p(RT),
        "央行资负表": _p(RT), "下月关注": _p(RT), "GitHub副本": _p(URL),
    }, "我的 LLM 月报(独立于他人月报表)"),
}

DESC = ("Hermes 独立线专用。数据源=本项目自抓 → data/hermes_line/。"
        "★与另一 agent 的同名表完全独立, 互不写入。禁止手工增删行。")


def ensure_subpage(n: kns.Notion, create: bool = False) -> str | None:
    ch = n.call(f"/blocks/{PARENT_PAGE}/children?page_size=100")
    for b in ch.get("results", []):
        if b.get("type") == "child_page" and \
                b["child_page"]["title"] == SUBPAGE_TITLE:
            return b["id"]
    if not create:
        return None
    pg = n.call("/pages", "POST", {
        "parent": {"type": "page_id", "page_id": PARENT_PAGE},
        "properties": {"title": [{"type": "text",
                                  "text": {"content": SUBPAGE_TITLE}}]},
        "children": [{"object": "block", "type": "paragraph", "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": DESC}}]}}],
    })
    return pg["id"]


def existing_tables(n: kns.Notion, page_id: str) -> dict:
    out = {}
    cur = None
    while True:
        url = f"/blocks/{page_id}/children?page_size=100"
        if cur:
            url += f"&start_cursor={cur}"
        ch = n.call(url)
        for b in ch.get("results", []):
            if b.get("type") == "child_database":
                out[b["child_database"]["title"]] = b["id"]
        if not ch.get("has_more"):
            return out
        cur = ch["next_cursor"]


def create_tables(create: bool = False) -> dict:
    n = kns.Notion()
    page = ensure_subpage(n, create=create)
    res = {"subpage": page, "created": {}, "existed": {}, "errors": []}
    if not page:
        res["errors"].append("子页不存在(用 --create 建)")
        return res
    have = existing_tables(n, page)
    for env_key, (title, props, note) in TABLES.items():
        if title in have:
            res["existed"][env_key] = have[title]
            continue
        if not create:
            res["created"][env_key] = "(待建) " + title
            continue
        try:
            d = n.call("/databases", "POST", {
                "parent": {"type": "page_id", "page_id": page},
                "title": [{"type": "text", "text": {"content": title}}],
                "description": [{"type": "text",
                                 "text": {"content": f"{note}。{DESC}"}}],
                "properties": props,
            })
            res["created"][env_key] = d["id"]
        except Exception as ex:
            res["errors"].append(f"{env_key}: {ex}")
    return res


def write_env(mapping: dict):
    """把 HDB_* 追加进 .env(并存, 绝不覆盖既有 DB_*)。"""
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    have = {ln.split("=", 1)[0] for ln in lines if "=" in ln}
    add = [f"{k}={v}" for k, v in sorted(mapping.items())
           if k not in have and not str(v).startswith("(")]
    if not add:
        return 0
    with open(ENV_PATH, "a", encoding="utf-8") as f:
        f.write("\n# ── Hermes 独立线 (2026-08-26) ──\n")
        f.write("\n".join(add) + "\n")
    return len(add)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    os.makedirs(HERMES_DATA, exist_ok=True)
    r = create_tables(create=a.create)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if a.create:
        m = dict(r["created"])
        m.update(r["existed"])
        print("写入 .env 条数:", write_env(m))
