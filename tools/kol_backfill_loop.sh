#!/usr/bin/env bash
# 新 KOL 一年期回填：连续多轮（Chao 2026-10-07「连续跑」）。每轮 = 调现成的 tools/kol_new_backfill.sh（6 人并行，门禁/账本/提交都沿用，不改它）。
# 为什么需要这个循环: 那个脚本同一天 STATUS=DONE 就直接退出, 一天只能跑一轮。本脚本每轮开始前把当天目录【改名挪开, 不删】。
# 停止条件: ①检测显示没人要补 ②某一轮 STATUS 不是 DONE(失败/超时/commit 失败) ③到达最大轮数 ④存在 STOP 文件(我手动叫停: touch scratch/kol_loop_STOP)
# 输出全部写 scratch/kol_loop.log; 结束时最后一行是 LOOP_END <原因>。
set -uo pipefail
ROOT=${KOL_LOOP_ROOT:-/home/user/Projects/Eco-and-Volatility-Checker}
ONE=${KOL_LOOP_ONE:-$ROOT/tools/kol_new_backfill.sh}
DET=${KOL_LOOP_DET:-$ROOT/tools/kol_backfill_detect.py}
PY=${KOL_LOOP_PY:-$ROOT/.venv/bin/python}
MAXR=${KOL_LOOP_MAX:-24}
cd "$ROOT" || { echo "LOOP_END 项目目录不存在"; exit 1; }
LOG=scratch/kol_loop.log; mkdir -p scratch
log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
STOPF=scratch/kol_loop_STOP
log "LOOP_START 最大 $MAXR 轮"
for ((r=1; r<=MAXR; r++)); do
  [ -f "$STOPF" ] && { log "LOOP_END 收到 STOP 文件(第 $r 轮前)"; exit 0; }
  N=$("$PY" "$DET" --all | "$PY" -c "import json,sys;print(len(json.load(sys.stdin)['todo']))") || { log "LOOP_END 检测脚本失败"; exit 1; }
  log "第 $r 轮前: 待补 $N 人"
  [ "$N" = "0" ] && { log "LOOP_END 没有人要补了"; exit 0; }
  D="scratch/kol_bf_auto_$(date +%F)"
  if [ -d "$D" ]; then mv "$D" "${D}_pre_round${r}_$(date +%H%M%S)" || { log "LOOP_END 挪目录失败"; exit 1; }; fi
  T0=$(date +%s)
  # ★2026-10-07 改: 循环内【不提交】(NOPUSH=1)。第 2 轮因 ssh 证书断开导致 pre-commit 钩子失败, 数据入库却未提交。
  #   21 轮约 5 小时, 证书中途失效是大概率事件, 不该让「提交」拖垮「抓取」。全部跑完由我统一提交一次(只 add kol_store+账本)。
  OUT=$(KOL_BF_NOPUSH=1 bash "$ONE" 2>&1); RC=$?
  T1=$(date +%s)
  ST=$(cat "$D/STATUS" 2>/dev/null || echo "(无 STATUS)")
  log "第 $r 轮结束 EXIT=$RC 用时 $(( (T1-T0)/60 )) 分 STATUS=${ST%% *} | $(echo "$OUT" | head -1)"
  echo "$OUT" >> "$LOG"
  case "$ST" in DONE*) ;; NONE*) log "LOOP_END 脚本判定没有人要补"; exit 0;; *) log "LOOP_END 第 $r 轮未 DONE: $ST"; exit 2;; esac
  [ "$RC" = "0" ] || { log "LOOP_END 第 $r 轮退出码 $RC"; exit 3; }
done
log "LOOP_END 达到最大轮数 $MAXR"
