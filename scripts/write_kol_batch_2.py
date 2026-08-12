#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 KOL 第2批分片。web_search 后端本轮几乎全部返回空结果，
遵守项目铁律「绝不编数字，取不到标未找到」，无近期明确观点者一律标 '未找到'。"""
import json
import os

OUT = "/home/user/Projects/Eco-and-Volatility-Checker/data/kol_batch_2.json"

NF = "未找到"
NF_C = "本轮 web_search 未返回该 KOL 近期明确的市场方向观点，按铁律标未找到，绝不编造。"

kols = [
    {"kol": "James Grant", "sector": "Government Debt", "direction": NF,
     "comments": "多次搜索(含 Grant's Interest Rate Observer/2026 债市)后端均返回空，未获近期明确观点。", "targets": ""},
    {"kol": "Lacy Hunt", "sector": "Government Debt", "direction": NF,
     "comments": "搜索 Hoisington/2026 衰退与利率展望后端返回空，未获近期明确观点。", "targets": ""},
    {"kol": "Abhigya Anand", "sector": "Alternative", "direction": NF,
     "comments": "另类预言类 KOL；搜索其 2026 预言/经济股市均返回空，无可用市场方向。", "targets": ""},
    {"kol": "Plai Navaracha", "sector": "Alternative", "direction": "中性",
     "comments": "泰国占卜师(Mor Plai)预言 11 月至次年 4 月泰国政经将有起色，属另类预言而非明确金融方向，弱信号偏中性。",
     "targets": "泰国经济/政局(定性)"},
    {"kol": "Athos Salomé", "sector": "Alternative", "direction": NF,
     "comments": "巴西灵媒预言类 KOL；搜索 2026 预言返回空，无市场方向。", "targets": ""},
    {"kol": "David Icke", "sector": "Alternative", "direction": NF,
     "comments": "阴谋论/另类 KOL；搜索 2026 经济/金融崩溃预言返回空，无明确市场方向。", "targets": ""},
    {"kol": "Amanda Grace(Alternative", "sector": "Alternative", "direction": NF,
     "comments": NF_C, "targets": ""},
    {"kol": "Brandon Biggs", "sector": "Alternative", "direction": NF,
     "comments": "预言类 KOL；搜索 2026 经济崩溃/美元预言返回空，无明确市场方向。", "targets": ""},
    {"kol": "FEMA", "sector": "Alternative", "direction": NF,
     "comments": "机构非市场观点主体；未获近期明确市场方向观点。", "targets": ""},
    {"kol": "Ray Kurzweil", "sector": "Equities", "direction": NF,
     "comments": "搜索 2026 AI/奇点/科技预测返回空，未获近期明确股市方向观点。", "targets": ""},
    {"kol": "Michael Saylor(Crypto", "sector": "Equities", "direction": NF,
     "comments": NF_C, "targets": ""},
    {"kol": "Ivan Zhao", "sector": "Equities", "direction": NF,
     "comments": NF_C, "targets": ""},
    {"kol": "Raoul Pal", "sector": "Crypto", "direction": NF,
     "comments": "搜索 Real Vision/比特币/宏观 2026 后端返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Cathie Wood", "sector": "Equities", "direction": NF,
     "comments": "搜索 ARK/特斯拉/比特币 2026 预测后端返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Dan Ives", "sector": "Equities", "direction": NF,
     "comments": "搜索 Wedbush 科技股 2026 展望后端返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Anu Anand", "sector": "Energy & Commodities", "direction": NF,
     "comments": "搜索大宗商品 2026 观点返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Rory Johnston", "sector": "Energy & Commodities", "direction": NF,
     "comments": "搜索 Commodity Context/油价 2026 返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Doomberg", "sector": "Energy & Commodities", "direction": NF,
     "comments": "搜索能源/大宗商品 2026 展望后端返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Eric Nuttall", "sector": "Energy & Commodities", "direction": NF,
     "comments": "搜索原油/能源股 2026 看多观点后端返回空，未获近期明确方向。", "targets": ""},
    {"kol": "Chris Vermeulen", "sector": "Precious Metals", "direction": NF,
     "comments": "搜索黄金/贵金属 2026 预测后端返回空，未获近期明确方向。", "targets": ""},
]

assert len(kols) == 20, f"应为20个，实际{len(kols)}"

payload = {"batch": 2, "kols": kols}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

# 统计
total = len(kols)
nf = sum(1 for k in kols if k["direction"] == NF)
covered = total - nf
dist = {}
for k in kols:
    dist[k["direction"]] = dist.get(k["direction"], 0) + 1
print(f"写入: {OUT}")
print(f"总数: {total}  有方向覆盖: {covered}  未找到: {nf}")
print("方向分布:", json.dumps(dist, ensure_ascii=False))
