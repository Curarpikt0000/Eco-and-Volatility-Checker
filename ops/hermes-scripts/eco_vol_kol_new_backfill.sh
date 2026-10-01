#!/usr/bin/env bash
# no_agent cron 入口：工作日 14:00 → 新 KOL 自动一年期回填（逻辑在项目 tools/kol_new_backfill.sh）
# 静默=没有新人要补；有人 → 跑完输出汇总；失败 → ❌ 一行。
exec bash <PROJECT_ROOT>/tools/kol_new_backfill.sh
