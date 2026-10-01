#!/usr/bin/env bash
# eco-vol 未提交告警 —— 方案甲(兜底闸)
#
# ★为什么外部还要再查一遍(Chao 2026-09-14 选「丙」= 乙+甲):
#   乙(步骤8 脚本硬校验)能让**跑到那一步**的失败暴露出来。
#   但 9/14 的真实事故是 agent 在**执行到那一步之前就断了** —— 连脚本都没被调起来,
#   自然也没有非零退出码可看, cron 还记 last_status=ok。
#   这种「连报错机会都没有」的情况只能靠外部检查兜底。
#
# 判据只认**产物**, 不看任何 cron 状态标签:
#   工作日 cron 跑过(当天有数据文件被写) 但 git 里没有当天的 daily commit → 告警。
#
# no_agent 脚本: **有输出才发消息, 静默即正常**(不刷屏, Chao 讨厌流水账)。
set -uo pipefail

REPO="<PROJECT_ROOT>"
cd "$REPO" 2>/dev/null || { echo "⚠️ eco-vol 告警: 进不去 $REPO"; exit 0; }

TODAY=$(date '+%Y-%m-%d')
DOW=$(date '+%u')          # 1=周一 ... 7=周日

# 周末不跑日报(cron 排程 0 11 * * 1-5), 周六有 weekly 另算 —— 都不在本闸范围
[ "$DOW" -ge 6 ] && exit 0

# 11:00 的 job, 给足余量, 12:30 之前不判
NOW_MIN=$((10#$(date '+%H') * 60 + 10#$(date '+%M')))
[ "$NOW_MIN" -lt 750 ] && exit 0

# ── 判据1: 今天 cron 到底跑没跑(产物 mtime) ──
RAN=$(find data docs -newermt "$TODAY 09:00" -type f 2>/dev/null | wc -l)
if [ "$RAN" -lt 5 ]; then
    echo "⚠️ **eco-vol 日报 cron 今天没跑**（$TODAY）"
    echo ""
    echo "判据：data/ 与 docs/ 下今天 09:00 之后被写的文件只有 $RAN 个（正常应 40+）。"
    echo "请检查 cron job \`eco-vol-01-daily-scan-report\`（排程 0 11 * * 1-5）。"
    exit 0
fi

# ── 判据2: 跑了, 那有没有当天的 daily commit ──
HAS_COMMIT=$(git log --oneline --since="$TODAY 00:00" --until="$TODAY 23:59" 2>/dev/null \
             | grep -icE "daily $TODAY|daily ${TODAY}" || true)

if [ "$HAS_COMMIT" -gt 0 ]; then
    # 有 commit, 再确认是否 push 出去了
    git fetch -q origin 2>/dev/null
    AHEAD=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
    if [ "$AHEAD" -gt 0 ]; then
        echo "⚠️ **eco-vol 今天已 commit 但没 push**（$TODAY）"
        echo ""
        echo "本地领先远端 $AHEAD 个 commit："
        git log origin/main..HEAD --oneline 2>/dev/null | sed 's/^/  · /'
        echo ""
        echo "成果还在本机，没进 GitHub。"
    fi
    exit 0
fi

# ── 跑了但没 commit = 就是 9/14 那个病 ──
UNCOMMITTED=$(git status --porcelain -uall 2>/dev/null | wc -l)
echo "⚠️ **eco-vol 今天跑了但没提交**（$TODAY）"
echo ""
echo "· cron 确实跑了：今天 09:00 后有 $RAN 个数据/产物文件被写入"
echo "· 但 git 里没有 \`daily $TODAY\` 的 commit"
echo "· 当前未提交文件：$UNCOMMITTED 个"
echo ""
echo "这与 2026-09-09、09-14 两次静默失败同型：抓数与 dashboard 全部正常，"
echo "agent 在执行步骤 8 提交时中断，而 cron 仍记 last_status=ok。"
echo ""
echo "补提交命令（会自动做红线扫描与 local==remote 硬校验）："
echo "\`\`\`"
echo "bash $REPO/scripts/daily_commit_push.sh $TODAY 480"
echo "\`\`\`"
exit 0
