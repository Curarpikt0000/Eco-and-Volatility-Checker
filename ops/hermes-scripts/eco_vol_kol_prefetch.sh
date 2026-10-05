#!/usr/bin/env bash
# eco-vol KOL 全量深度抓取 —— 后台 6 批并行 + 跑完自动合并。
#
# ★2026-09-28 立（Chao 同意「cron 改为全量」）。
#   背景: 11:00 日报 cron 是单个 agent turn，里面没法可靠地并行子 agent，逐个深度抓 153 人必超时，
#   于是日报长期只「沿用旧快照 + 定向刷新一两人」，9/17 以后大部分人 11 天没刷新。
#   9/28 手动实测: 起 6 个独立 hermes 进程(每批约 26 人)，约 40 分钟 153/153 全部落盘。
#
# 设计:
#   - 本脚本由 no_agent cron 在 09:00(工作日) 触发，只负责「拉起」然后立刻返回，
#     不占 cron 的 1 小时脚本超时；真正的活在 setsid 脱离出来的 runner 里跑。
#   - runner 等 6 批全部结束 → 跑 tools/kol_merge_deep.py → 把结果写进 STATUS 文件。
#   - 11:00 日报 cron 步骤 3 读 STATUS 文件判断: DONE 就直接用; RUNNING 最多等 20 分钟; 其余沿用旧数据并在日报里写明。
#   - 同日重复触发: 已 RUNNING/DONE 则直接退出，不重复烧配额。
#
# 输出: 正常静默(no_agent cron 只在有输出时发消息)；只有拉起失败才打印。
set -uo pipefail

ROOT=<PROJECT_ROOT>
D=${KOL_PREFETCH_DATE:-$(date +%F)}   # 覆盖仅供自测
BASE="$ROOT/scratch/kol_deep_$D"
STATUS="$BASE/STATUS"
TEMPLATE="$ROOT/scratch/kol_deep_run_batch.sh"   # 子 agent prompt 模板(单批 runner)
NBATCH=6
BATCH_TIMEOUT=3000   # 单批硬上限 50 分钟

mkdir -p "$BASE/batches" "$BASE/out"

if [ -f "$STATUS" ] && grep -qE '^(RUNNING|DONE)' "$STATUS"; then
  exit 0
fi

# ── 0. 先从 Notion 同步名册(2026-10-02 立) ──
# 背景: 10/02 抓取 09:00 按 192 人切批，而日报步骤 0 在 11:00 才把名册同步到 198 人，
#   6 位新增 KOL 当天既没抓取也没出现在看板。名册必须在切批【之前】同步。
# 同步失败不中止抓取: 沿用现有名册继续，并打印一行告警(no_agent cron 有输出才发消息)。
# 自测模式(KOL_PREFETCH_DRY=1)不联网同步，避免测试改动真实名册。
SYNC_WARN=""
if [ "${KOL_PREFETCH_DRY:-0}" != "1" ]; then
  SYNC_OUT=$(cd "$ROOT" && timeout 300 "$ROOT/.venv/bin/python" tools/sync_kol_from_notion.py --apply 2>&1)
  SYNC_RC=$?
  if [ "$SYNC_RC" -ne 0 ] || ! echo "$SYNC_OUT" | grep -q "已写入"; then
    SYNC_WARN="⚠️ eco-vol KOL 抓取: 抓取前 Notion 名册同步失败(rc=$SYNC_RC)，今日沿用上次名册，新增人要等明天。"
    echo "$SYNC_WARN"
  fi
fi

# ── 1. 按名册切批 ──
if ! "$ROOT/.venv/bin/python" - "$BASE" "$NBATCH" <<'EOF'
import json, sys
base, n = sys.argv[1], int(sys.argv[2])
reg = json.load(open("<PROJECT_ROOT>/data/kol_registry.json"))
k = [{"id": x["id"], "name": x["display_name"], "sector": x.get("domain", ""),
      "search_terms": x.get("search_terms") or []} for x in reg["kols"] if x.get("active")]
if not k:
    sys.exit("名册 active 为 0")
sz = -(-len(k) // n)
for i in range(n):
    json.dump(k[i*sz:(i+1)*sz], open(f"{base}/batches/b{i+1}.json", "w"), ensure_ascii=False)
EOF
then
  echo "❌ eco-vol KOL 全量抓取: 切批失败(名册读不到?)，今日日报将沿用旧 KOL 数据"
  exit 1
fi

# 单批 runner(模型与交互 session 一致；模板里的旧模型名替换掉)
# 2026-10-01: opus-5-5 -> sonnet-5. 6 并行批 x 50-145 轮在 opus 上 3h 烧掉 $500 Playground 月额度。
KOL_MODEL="${KOL_MODEL:-claude-sonnet-5}"
sed -e "s/claude-opus-4-8/$KOL_MODEL/" "$TEMPLATE" > "$BASE/run_batch.sh"
# 自测模式: 不调 LLM，批进程只 sleep，用来验证拉起/等待/合并/STATUS 这条链路
if [ "${KOL_PREFETCH_DRY:-0}" = "1" ]; then printf '#!/bin/bash\nsleep 8\n' > "$BASE/run_batch.sh"; fi
echo "RUNNING $(date '+%F %T')" > "$STATUS"

# ── 2. 脱离 cron 进程拉起 runner ──
setsid bash -c "
  cd '$ROOT'
  for i in \$(seq 1 $NBATCH); do
    timeout $BATCH_TIMEOUT bash '$BASE/run_batch.sh' b\$i '$D' > '$BASE/log_b'\$i'.txt' 2>&1 &
    sleep 3
  done
  wait
  if '$ROOT/.venv/bin/python' '$ROOT/tools/kol_merge_deep.py' '$D' > '$BASE/merge.log' 2>&1; then
    echo \"DONE \$(date '+%F %T') \$(grep -o 'MERGE-OK.*' '$BASE/merge.log' | head -1)\" > '$STATUS'
  else
    echo \"FAILED \$(date '+%F %T') \$(tail -1 '$BASE/merge.log')\" > '$STATUS'
  fi
" > "$BASE/runner.log" 2>&1 < /dev/null &
disown || true

sleep 5
if ! pgrep -f "kol_deep_$D/run_batch.sh" > /dev/null; then
  echo "❌ eco-vol KOL 全量抓取: 批进程没起来，见 $BASE/runner.log"
  echo "FAILED $(date '+%F %T') 批进程未启动" > "$STATUS"
  exit 1
fi
exit 0
