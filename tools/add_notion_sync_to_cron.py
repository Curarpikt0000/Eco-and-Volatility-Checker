#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 eco-vol-01-daily-scan-report 的 cron prompt 插入「步骤 0：从 Notion 同步 KOL 名册」。

背景(Chao 2026-08-22):
  Notion「KOL List」DB 是 KOL 名册的唯一真源, agent 不得自行增删。
  但每日 cron 原本只**读** data/kol_registry.json, 从不从 Notion 拉取,
  导致 Chao 在 Notion 增删后 GitHub 侧不会自动跟上。
  修法: 不新建 cron, 在现有每日 cron 的抓取步骤之前插一步同步。
"""
import json
import shutil
import sys
from datetime import datetime

PATH = "/home/user/.hermes/cron/jobs.json"
JOB = "eco-vol-01-daily-scan-report"
ANCHOR = "## 步骤 1："

STEP0 = """## 步骤 0：从 Notion 同步 KOL 名册（必须最先做，其余步骤都依赖名册）
★铁律：Notion「KOL List」DB 是名册**唯一真源**，**你绝不可自行增删任何 KOL**。
增删一律由 Chao 在 Notion 侧操作，本步骤只负责单向镜像到 GitHub。
执行：`python3 tools/sync_kol_from_notion.py --apply`
- 脚本会保住本地独有的采集配置(search_terms/youtube_channel_id/source_url)不被覆盖。
- 被移出的人落盘 data/kol_removed_<date>.json 留痕，其 data/kol/backfill/ 历史文件一律保留不删。
- 同步后以名册实际人数为准继续后续步骤，**prompt 里不写死 KOL 数量**。
- 若同步失败(如 Notion API 报错)：**不要中止整个任务**，沿用现有名册继续跑，
  并在最终 Telegram 报告里明确写一行「⚠️ 今日 Notion 名册同步失败，使用上次名册」。
- 若本次同步有增删，在 Telegram 报告里用一行说明「名册变更：+N 人 / -N 人（现 N 人）」。

"""


def main(apply_it):
    data = json.load(open(PATH, encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", data)
    items = list(jobs.values()) if isinstance(jobs, dict) else jobs

    target = None
    for j in items:
        if (j.get("name") or "") == JOB:
            target = j
            break
    if target is None:
        print(f"✗ 找不到 job: {JOB}")
        return 1

    p = target["prompt"]
    if "步骤 0：从 Notion 同步 KOL 名册" in p:
        print("• 已存在步骤 0，无需重复插入（幂等）")
        return 0
    if ANCHOR not in p:
        print(f"✗ 找不到锚点 {ANCHOR!r}，中止（不做模糊插入）")
        return 1

    idx = p.index(ANCHOR)
    newp = p[:idx] + STEP0 + p[idx:]
    print(f"prompt: {len(p)} → {len(newp)} 字符 (+{len(newp) - len(p)})")
    print("--- 插入内容预览 ---")
    print(STEP0[:300] + "...")

    if not apply_it:
        print("\n[预演] 未写盘。加 --apply 生效。")
        return 0

    shutil.copy(PATH, f"{PATH}.bak.{datetime.now():%Y%m%d_%H%M%S}")
    target["prompt"] = newp
    json.dump(data, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n✓ 已写入 " + PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
