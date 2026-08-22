#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「周期与术数预测」23 人按 Chao 2026-08-22 决定拆分。

背景(我的越界, 记录在案):
  2026-08-20 我在 Eco 项目自行新建 sector "Cycles & Esoteric Forecasting" 并塞入 23 人。
  Chao 未下达此指令; 且 Forecast-Checker 项目的 AGENTS.md 明确规定
  「通灵/占星/末日预言者」归 Forecast-Checker 收录。属于把 B 项目范围塞进 A 项目。

Chao 决定(2026-08-22):
  - 撤走 15 位【玄学/术数/占星/宗教预言】→ 迁往 Forecast-Checker
  - 保留 8 位【技术分析/周期理论】→ 归回 Eco 常规 KOL 板块, 取消独立 section

划分依据(不按地域, 按方法论):
  留 = 主流金融技术分析流派(艾略特波浪 / 市场宽度 / 人口与世代长周期 / 学术周期机构)
  撤 = 占星 / 卦象 / 八字 / 奇门遁甲 / 圣经末世预言
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data", "kol_registry.json")
OUT = os.path.join(ROOT, "scratch", "cycle_split_esoteric.json")

# 撤走: 玄学 / 占星 / 术数 / 宗教预言 → Forecast-Checker
ESOTERIC = [
    "Raymond A. Merriman",            # 金融占星 geocosmic 地象周期
    "Bo Polny",                       # 圣经周期 / Seven Seals 末世择时
    "Andrew Pancholi",                # Gann 周期(Gann 体系含占星/几何玄学)
    "吳昌燁 · 太一研究院",             # 奇门遁甲
    "六爻佔卦之狼眼看世界",            # 周易六爻
    "小夏易經視角",                    # 易经卦象
    "秋潤金融玄學 / 秋润易道",         # 八字+六爻+文王卦
    "易經交易攻守道",                  # 易经思维
    "丙午易说天下",                    # 八字命理
    "天遁财局",                        # 奇门遁甲
    "JingHongNews 景宏资讯",           # 奇门遁甲
]
# 保留: 主流技术分析 / 量化周期 / 人口与世代统计 → Eco 常规 KOL 板块
KEEP = [
    "Martin Armstrong",                              # ECM 8.6年周期 / Socrates
    "Robert Prechter / Elliott Wave International",  # 艾略特波浪
    "Charles Nenner",                                # 周期算法(前高盛)
    "Harry S. Dent Jr.",                             # 人口周期 / 消费支出波
    "Neil Howe",                                     # Strauss-Howe 第四转折
    "Eric Hadik",                                    # 40年周期 Cycle Progression
    "Foundation for the Study of Cycles",            # 1941 学术机构
    "Tom McClellan",                                 # McClellan Oscillator 市场宽度
    "Glenn Neely",                                   # NEoWave
    "Avi Gilburt",                                   # 艾略特波浪
    "Peter Goodburn / WaveTrack International",      # 艾略特波浪
    "David Hickson / Sentient Trader",               # Hurst 嵌套周期
]


def main(esoteric_names):
    reg = json.load(open(REG, encoding="utf-8"))
    is_list = isinstance(reg, list)
    kols = reg if is_list else reg.get("kols", reg)

    idx = {k.get("display_name"): k for k in kols}
    missing = [n for n in esoteric_names if n not in idx]
    if missing:
        print("✗ 名册中找不到以下人名, 中止(不做模糊匹配):")
        for n in missing:
            print("   -", n)
        return 1

    moved = [idx[n] for n in esoteric_names]
    remain = [k for k in kols if k.get("display_name") not in set(esoteric_names)]

    # 导出被撤走的人(供 Forecast-Checker 接收)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"exported_from": "Eco-and-Volatility-Checker/data/kol_registry.json",
               "export_date": "2026-08-22",
               "reason": "Chao 决定: 玄学/术数/占星/宗教预言类归 Forecast-Checker",
               "count": len(moved), "kols": moved},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 保留者: 清掉专用 sector, 归回常规板块
    kept_cycle = 0
    for k in remain:
        if k.get("sector") == "Cycles & Esoteric Forecasting":
            k["sector"] = "Technical & Cycle Analysis"
            k["domain"] = "技术分析与周期"
            k["_reclass_note"] = "2026-08-22 Chao: 取消独立 section, 归回常规 KOL 板块"
            kept_cycle += 1

    if is_list:
        json.dump(remain, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        reg["kols"] = remain
        json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"✓ 撤走 {len(moved)} 人 → {OUT}")
    print(f"✓ 保留并改 sector 的 {kept_cycle} 人 → Technical & Cycle Analysis")
    print(f"✓ 名册 {len(kols)} → {len(remain)} 人")
    return 0


if __name__ == "__main__":
    sys.exit(main(ESOTERIC))
