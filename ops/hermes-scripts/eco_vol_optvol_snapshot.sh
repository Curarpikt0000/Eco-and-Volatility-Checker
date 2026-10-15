#!/usr/bin/env bash
# eco-vol 每日期权快照 → Notion DB_OPTVOL (no_agent, 零 LLM 成本)
# ★2026-10-14 立(Chao「建」): 9/21 后没有任何 cron 调 tools/snapshot_optvol.py, Notion 255 行里只有 9/21 一行真快照。
# 时间: 日本时间 06:30 周二~周六 = 美东前一日 16:30/17:30 → CBOE 延迟报价已是前一交易日收盘口径。
#   (周一早晨不跑: 对应美东周日, 无新数据。)
# 输出: 成功静默; 失败/读回不符 → 一行 ❌。no_agent cron 只在有输出时发消息。
set -uo pipefail
ROOT=<PROJECT_ROOT>
cd "$ROOT" || { echo "❌ 期权快照: 项目目录不存在"; exit 1; }
LOG=scratch/optvol_snapshot.log; mkdir -p scratch
OUT=$(.venv/bin/python tools/snapshot_optvol.py 2>&1); RC=$?
printf '%s rc=%s\n%s\n---\n' "$(date '+%F %T')" "$RC" "$OUT" >> "$LOG"
if [ $RC -ne 0 ]; then echo "❌ 期权快照失败 rc=$RC: $(echo "$OUT" | tail -1 | cut -c1-160)"; exit 1; fi
echo "$OUT" | grep -q "已写入" || { echo "❌ 期权快照: 未见「已写入」确认: $(echo "$OUT" | tail -1 | cut -c1-160)"; exit 1; }
exit 0
