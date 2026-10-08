#!/usr/bin/env bash
# no_agent cron 入口：工作日 14:00 → 只【检测】名册里谁的一年期言论覆盖不足，不抓取、不入库、不烧配额。
# Chao 2026-10-07 定: 回填由 Hermes 在对话里手动做(「B 然后你来全量做」)，cron 只负责「别忘了」。
# 输出: 没有人要补 → 完全静默；有 → 一段汇报(几人、谁最缺)。选人逻辑与 tools/kol_new_backfill.sh 完全相同(同一判据)。
# 原回填入口见 tools/kol_new_backfill.sh(未改动, 我手动调用它)。
cd <PROJECT_ROOT> || { echo "❌ 新KOL检测: 项目目录不存在"; exit 1; }
exec .venv/bin/python tools/kol_backfill_detect.py
