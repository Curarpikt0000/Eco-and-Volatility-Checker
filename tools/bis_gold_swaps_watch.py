#!/usr/bin/env python3
"""BIS 月度 Statement of Account 到货检查 (Chao 2026-10-30: 每张图每天有人看管)。

背景: 看板「BIS 自营黄金掉期」的吨数, BIS 从不直接披露, 靠 GATA 顾问从月度 Statement of Account 反推,
  本项目无法独立从官方 PDF 还原吨数(PDF 里只有百万 SDR 的「黄金及黄金贷款」「黄金存款」总额, 缺 SDR/盎司换算; 实测
  6 月 PDF 差额 23320 百万SDR 对不出已知的 144 吨)。故数据点仍靠人工/GATA 追加。
本脚本只做「看管」不做「编数」: 读 BIS 官方列表页, 找最新一期月份, 与 data/bis_gold_swaps.json 里
  最新月度点比对; BIS 已发布更新的月份而文件里没有 → 输出一行告警(no_agent cron 有输出才推送)。
  对照组: 同一页面必须能解析出 ≥6 个月份, 否则判为「页面结构变了/抓取失败」而不是「无新数据」。
退出码恒为 0(告警走 stdout)。
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "data", "bis_gold_swaps.json")
URL = "https://www.bis.org/publications?series%5B0%5D=Statement%20of%20account"
MON = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                       "august", "september", "october", "november", "december"])}


def latest_bis():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    ms = re.findall(r"statement-account-(\d{1,2})-([a-z]+)-(\d{4})", html)
    ds = sorted({dt.date(int(y), MON[m], int(d)) for d, m, y in ms if m in MON})
    return ds


def main():
    try:
        ds = latest_bis()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ eco-vol BIS 黄金掉期看管: 无法读取 BIS 列表页({type(e).__name__}), 今日未检查")
        return 0
    if len(ds) < 6:
        print(f"⚠️ eco-vol BIS 黄金掉期看管: BIS 页面只解析出 {len(ds)} 个月份(<6), 疑似页面结构变了, 今日未检查")
        return 0
    have = max(p["date"] for p in json.load(open(F, encoding="utf-8"))["points"] if p.get("kind") == "monthly")
    new = [d for d in ds if d.isoformat() > have]
    if new:
        print(f"⚠️ eco-vol BIS 黄金掉期: BIS 已发布 {', '.join(d.isoformat() for d in new)} 的 Statement of Account, "
              f"本项目最新月度点是 {have}, 需补点(吨数靠 GATA 反推, 无法自动还原)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
