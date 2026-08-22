#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 eco-vol-01 cron prompt 里已过时的「另类预言类」描述。

背景(Chao 2026-08-22):
  玄学/术数/占星/通灵/末日预言类已全部迁往 Forecast-Checker 项目,
  Eco 名册里不再有这类人。但 cron 步骤 3 仍在指导 agent 如何处理他们,
  属过时指令 —— 会让 agent 困惑, 甚至可能诱导它去"找回"这类人。
"""
import json
import shutil
import sys
from datetime import datetime

PATH = "/home/user/.hermes/cron/jobs.json"
JOB = "eco-vol-01-daily-scan-report"

OLD = ('  - ★另类预言类(domain=预测 或 sector=Alternative,如 Craig Hamilton-Parker/'
       'Abhigya Anand/David Icke 等通灵/占星/末日预言者): 用该 KOL 的 search_terms 字段搜'
       '(如 "world predictions"),抓其最新世界/市场预言摘要。**不按可交易方向严格归类**,'
       'direction 填"另类预言"或据其预言倾向(崩盘预警→看空/复苏预言→看多)填,comments 记预言要点。'
       '作民间预期/情绪传播度信号,不与其他 KOL 混为同一判断标准。')

NEW = ('  - ★注意: 玄学/术数/占星/通灵/末日预言类**已于 2026-08-22 全部迁往 Forecast-Checker 项目**, '
       '本项目名册中不应再有这类人。若在名册里见到, 说明 Notion 侧被误加 —— '
       '照常抓取即可, 但在最终 Telegram 报告里提醒 Chao 核对归属, **不要自行删除**(名册只由 Notion 决定)。\n'
       '  - 技术分析/量化周期派(艾略特波浪/市场宽度 McClellan/ECM 经济信心模型/Hurst 周期/世代长周期)'
       '按普通分析师处理, 归常规 KOL 板块, 不单独分组。')


def main(apply_it):
    data = json.load(open(PATH, encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", data)
    items = list(jobs.values()) if isinstance(jobs, dict) else jobs

    target = next((j for j in items if (j.get("name") or "") == JOB), None)
    if target is None:
        print(f"✗ 找不到 job: {JOB}")
        return 1

    p = target["prompt"]
    if "已于 2026-08-22 全部迁往 Forecast-Checker" in p:
        print("• 已更新过，跳过（幂等）")
        return 0
    if OLD not in p:
        print("✗ 找不到待替换原文（可能已被其他改动动过），中止，不做模糊替换")
        return 1

    newp = p.replace(OLD, NEW)
    print(f"prompt: {len(p)} → {len(newp)} 字符")
    if not apply_it:
        print("[预演] 未写盘。加 --apply 生效。")
        return 0

    shutil.copy(PATH, f"{PATH}.bak.{datetime.now():%Y%m%d_%H%M%S}")
    target["prompt"] = newp
    json.dump(data, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("✓ 已写入 " + PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
