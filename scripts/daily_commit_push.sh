#!/usr/bin/env bash
# eco-vol 日报 cron 步骤 8: 提交 + push + **硬校验**
#
# ★为什么要这个脚本(2026-09-14 Chao「今天任务跑了么，你们看看 cron 是不是出问题了」):
#   9/14 cron 11:00 正常跑完全部抓取与 dashboard 重建(52 个数据文件), 但 agent 在
#   执行步骤 8 的 commit 时**输出中断** —— 日志末尾停在一个残缺的 <invoke name="terminal">
#   上, 无闭合无执行结果, 而 cron 仍记 last_status=ok。近一周此类静默失败 2 次(9/9、9/14)。
#   根因: 「提交」这一步只是 prompt 里的一行命令, agent 中途断掉就没人知道。
#   对策: 做成脚本 + 校验 HEAD 真的前进了、local==remote, 否则非零退出让 cron 记 error。
#
# ★纪律(与本项目 AGENTS.md 一致):
#   - 多 agent 共写此 repo: **只 add 本次 cron 产出的文件**, 绝不 git add -A / -u。
#     判据是 mtime 落在本次运行窗口内, 别的 agent(如 data/hermes_line/HDB_*.json)
#     的文件不能被卷进来。
#   - 抓不到/没东西提交 → 如实退出, 绝不造空 commit。
#
# 用法: bash scripts/daily_commit_push.sh <YYYY-MM-DD> [窗口分钟数, 默认 90]
set -uo pipefail

REPO="/home/user/Projects/Eco-and-Volatility-Checker"
DATE_STR="${1:-$(date '+%Y-%m-%d')}"
WINDOW_MIN="${2:-90}"

cd "$REPO" || { echo "❌ 进不去 $REPO"; exit 2; }

echo "=== 步骤8 提交+push  日期=$DATE_STR  窗口=${WINDOW_MIN}分钟 ==="

# ── 0. 安全闸: .env 必须被忽略 ──
if ! git check-ignore -q .env; then
    echo "❌ .env 未被 .gitignore 忽略 —— 中止, 绝不冒险 push 密钥"
    exit 3
fi
echo "  ✅ .env 已忽略"

BEFORE=$(git rev-parse HEAD)

# ── 1. 挑出本次运行产出的文件(mtime 在窗口内) ──
# ★不能用 -uno: 那会排除**未跟踪**文件, 导致某天新增的数据文件永远提交不上
#   (2026-09-14 自测在临时 repo 里抓到 —— 真 repo 因文件都已跟踪而没暴露)。
#   用 -uall 列出未跟踪文件的**每个具体路径**(默认 -unormal 只给到目录名 "data/",
#   目录名喂给 date -r / git add 会连累别的 agent 的文件)。
CUT=$(date -d "$WINDOW_MIN minutes ago" '+%s')
MINE=$(git status --porcelain -uall | awk '{print $2}' | while read -r f; do
    [ -e "$f" ] || continue
    t=$(date -r "$f" '+%s' 2>/dev/null) || continue
    [ "$t" -ge "$CUT" ] && echo "$f"
done)

if [ -z "$MINE" ]; then
    echo "  ℹ️ 窗口内无改动文件 —— 无需提交(不造空 commit)"
    # 仍要检查有没有历史遗留的未 push commit
    AHEAD=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
    if [ "$AHEAD" -gt 0 ]; then
        echo "  ⚠️ 但本地领先远端 $AHEAD 个 commit, 尝试 push"
        git push origin main || { echo "❌ push 失败"; exit 5; }
    fi
    exit 0
fi

N=$(echo "$MINE" | wc -l)
echo "  本次产出 $N 个文件:"
echo "$MINE" | sed 's/^/    /'

# ── 2. 排除别的 agent 的已知产物(双保险, mtime 之外再按路径挡一层) ──
SKIPPED=$(echo "$MINE" | grep -E 'data/hermes_line/HDB_' || true)
if [ -n "$SKIPPED" ]; then
    echo "  ⚠️ 以下属别的 agent, 已排除:"
    echo "$SKIPPED" | sed 's/^/    /'
    MINE=$(echo "$MINE" | grep -vE 'data/hermes_line/HDB_' || true)
fi
[ -z "$MINE" ] && { echo "  ℹ️ 排除后无自有文件可提交"; exit 0; }

# ── 3. 红线扫描 ──
HITS=$(echo "$MINE" | grep -E '\.(json|md|html|py)$' | \
       xargs grep -lE 'ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|ntn_[A-Za-z0-9]{20,}|-----BEGIN' 2>/dev/null || true)
if [ -n "$HITS" ]; then
    echo "❌ 红线命中, 中止 push:"
    echo "$HITS" | sed 's/^/    /'
    exit 4
fi
echo "  ✅ 红线扫描 0 命中"

# ── 4. add + commit ──
echo "$MINE" | xargs git add -- || { echo "❌ git add 失败"; exit 5; }
STAGED=$(git diff --cached --name-only | wc -l)
if [ "$STAGED" -eq 0 ]; then
    echo "  ℹ️ 暂存区为空 —— 无需提交"
    exit 0
fi
echo "  已暂存 $STAGED 个文件"

git -c commit.gpgsign=false \
    -c user.name="Curarpikt0000" \
    -c user.email="curarpikt0000@users.noreply.github.com" \
    commit -q -m "daily $DATE_STR" || { echo "❌ commit 失败"; exit 5; }

AFTER=$(git rev-parse HEAD)

# ── 5. ★硬校验一: HEAD 必须真的前进了 ──
if [ "$BEFORE" = "$AFTER" ]; then
    echo "❌ 硬校验失败: commit 后 HEAD 未变($BEFORE) —— 提交没有真正发生"
    exit 6
fi
echo "  ✅ HEAD 前进: ${BEFORE:0:7} → ${AFTER:0:7}"

# ── 6. push ──
git push origin main || { echo "❌ push 失败 —— 本地已 commit 但远端未更新"; exit 7; }

# ── 7. ★硬校验二: local 必须 == remote ──
git fetch -q origin 2>/dev/null
L=$(git rev-parse HEAD)
R=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
if [ "$L" != "$R" ]; then
    echo "❌ 硬校验失败: local(${L:0:7}) != remote(${R:0:7}) —— push 没有真正生效"
    exit 8
fi

echo "  ✅ 硬校验通过: local == remote == ${L:0:7}"
echo "=== 步骤8 完成: daily $DATE_STR 已提交并 push($STAGED 个文件) ==="
exit 0
