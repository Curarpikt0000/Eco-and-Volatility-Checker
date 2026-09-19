#!/usr/bin/env bash
# 把 docs/index.html 发布到 Uber 内网 vibe(灾备入口)。
#
# ★2026-09-18 立。背景: 公网 GitHub Pages 当天 404(账号级限制, 非仓库违规),
#   Chao 要求内外双入口, 公网打不开时还能走内网。
#
# ★设计铁律(来自 chao-vibe skill 的两天静默故障教训):
#   成功信息必须在**退出码检查之后**打印, 绝不挂在 `&&` 右边 ——
#   否则上游命令失败时 echo 仍可能执行, 日志说"published"而实际没发。
#   每个变更阶段都显式判 rc, 并打印可核对的真凭据(version 号)。
#
# 退出码:
#   0 成功(或内容未变跳过)  3 源文件缺失  4 红线命中
#   5 SSH_AUTH_SOCK 不可用  6 上传失败    7 返回体未含 deployed
set -uo pipefail

REPO="${REPO:-/home/user/Projects/Eco-and-Volatility-Checker}"
SRC="${SRC:-$REPO/docs/index.html}"
SLUG="${SLUG:-eco-volatility-checker}"
TITLE="${TITLE:-Eco Volatility Checker · 每日宏观风险扫描}"
STAMP="$REPO/data/.vibe_last_sha256"
PAYLOAD="/tmp/vibe_${SLUG}_payload.json"
RESULT="/tmp/vibe_${SLUG}_result.json"

# ── ① 源文件 ──
if [ ! -f "$SRC" ]; then
  echo "vibe: SOURCE MISSING $SRC" >&2
  exit 3
fi
SIZE=$(wc -c < "$SRC")

# ── ② 红线扫描(内网也扫: 密钥绝不外流; 内部标识此处允许但仍记录) ──
if grep -qE 'ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|ntn_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' "$SRC"; then
  echo "vibe: REDLINE HIT (credential pattern in $SRC)" >&2
  exit 4
fi

# ── ③ 内容未变则跳过(省一次上传, 但不算失败) ──
NEW_SHA=$(sha256sum "$SRC" | awk '{print $1}')
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$NEW_SHA" ]; then
  echo "vibe: no change (sha ${NEW_SHA:0:12}), skip upload"
  exit 0
fi

# ── ④ SSH_AUTH_SOCK(cron 环境无继承, 必须在脚本内自设; 用 symlink 不用 realpath) ──
if [ -z "${SSH_AUTH_SOCK:-}" ] || [ ! -S "${SSH_AUTH_SOCK:-}" ]; then
  CAND=$(readlink -f /var/lib/devpod/ssh/active_ssh_auth_sock 2>/dev/null)
  if [ -n "$CAND" ] && [ -S "$CAND" ]; then
    export SSH_AUTH_SOCK="$CAND"
  else
    echo "vibe: SSH_AUTH_SOCK unavailable — aifx MCP will fail" >&2
    exit 5
  fi
fi

# ── ⑤ 构造 payload ──
python3 - "$SRC" "$SLUG" "$TITLE" "$PAYLOAD" <<'PY'
import json, sys
src, slug, title, out = sys.argv[1:5]
html = open(src, encoding='utf-8').read()
json.dump({"slug": slug, "title": title, "files": {"index.html": html}},
          open(out, 'w', encoding='utf-8'), ensure_ascii=False)
PY
if [ $? -ne 0 ] || [ ! -s "$PAYLOAD" ]; then
  echo "vibe: PAYLOAD BUILD FAILED" >&2
  exit 6
fi

# ── ⑥ 上传(显式判 rc, 不用 && 串) ──
timeout 900 aifx mcp call vibe-mcp upload_vibe_dist --args-file "$PAYLOAD" > "$RESULT" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "vibe: UPLOAD FAILED rc=$RC" >&2
  head -c 400 "$RESULT" >&2
  exit 6
fi

# ── ⑦ 校验返回体真的 deployed, 并取出 version 作凭据 ──
VER=$(python3 - "$RESULT" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    sys.exit(1)
if d.get("status") != "deployed":
    sys.exit(1)
print(d.get("version", "?"))
PY
)
if [ -z "$VER" ]; then
  echo "vibe: RESPONSE NOT deployed" >&2
  head -c 400 "$RESULT" >&2
  exit 7
fi

# 只有走到这里才算成功 —— 打印真凭据(version), 不是一句空话
echo "$NEW_SHA" > "$STAMP"
printf 'vibe: deployed v%s (%s bytes, sha %s)\n' "$VER" "$SIZE" "${NEW_SHA:0:12}"
printf 'vibe: https://vibe-mcp.uberinternal.com/api/vibe/blob/%s/index.html\n' "$SLUG"
exit 0
