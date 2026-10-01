#!/usr/bin/env bash
# 通用 Cloudflare Pages 发布器 —— 供所有项目复用。
#
# 用法:
#   publish_cf_pages.sh <project-name> <src-path> [stamp-file]
#     <project-name>  Cloudflare Pages 项目名(小写/连字符), 不存在会自动创建
#     <src-path>      要发布的单个 HTML 文件, 或一个目录
#     [stamp-file]    可选, 内容指纹落盘路径(默认 <src同级>/.cf_last_sha256_<project>)
#
# ★2026-09-19 立。背景: GitHub Pages 因账号级匿名限制全站 404,
#   Chao 要求公网入口不再单点依赖 GitHub。
#
# ★设计铁律(沿用内部发布脚本的教训):
#   成功信息必须在**退出码检查之后**打印, 绝不挂在 `&&` 右边。
#   最终以**匿名 curl 实测 HTTP 200 + 内容指纹比对**为准, 不信 wrangler 的 "Success" 字样。
#
# 退出码:
#   0 成功(或内容未变跳过)  3 源缺失  4 红线命中  5 凭证缺失
#   6 wrangler 缺失  7 部署失败  8 线上实测未通过(404/内容不符)
set -uo pipefail

PROJECT="${1:-}"
SRC="${2:-}"
if [ -z "$PROJECT" ] || [ -z "$SRC" ]; then
  echo "usage: $0 <project-name> <src-file-or-dir> [stamp-file]" >&2
  exit 2
fi

# ── ① 源 ──
if [ ! -e "$SRC" ]; then
  echo "cf[$PROJECT]: SOURCE MISSING $SRC" >&2
  exit 3
fi
if [ -d "$SRC" ]; then
  SRCDIR="$SRC"
  MAIN="$SRC/index.html"
else
  MAIN="$SRC"
  SRCDIR=""
fi
[ -f "$MAIN" ] || { echo "cf[$PROJECT]: no index.html in $SRC" >&2; exit 3; }

DEFAULT_STAMP="$(dirname "$MAIN")/.cf_last_sha256_${PROJECT}"
STAMP="${3:-$DEFAULT_STAMP}"

# ── ② 红线扫描(公网发布, 必须严) ──
SCAN_TARGET="$MAIN"
if grep -qlE 'ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|ntn_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-' "$SCAN_TARGET" 2>/dev/null; then
  echo "cf[$PROJECT]: REDLINE HIT (credential pattern) in $SCAN_TARGET" >&2
  exit 4
fi
# 公网发布额外扫内部标识
# 可选: 设 REDLINE_EXTRA_REGEX='内部域名1|内部域名2' 额外拦截不该上公网的内部标识
if [ -n "${REDLINE_EXTRA_REGEX:-}" ] && grep -qiE "$REDLINE_EXTRA_REGEX" "$SCAN_TARGET" 2>/dev/null; then
  echo "cf[$PROJECT]: REDLINE HIT (internal identifier) in $SCAN_TARGET" >&2
  exit 4
fi

# ── ③ 内容未变则跳过 ──
NEW_SHA=$(sha256sum "$MAIN" | awk '{print $1}')
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$NEW_SHA" ]; then
  echo "cf[$PROJECT]: no change (sha ${NEW_SHA:0:12}), skip"
  exit 0
fi

# ── ④ 凭证 ──
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  set -a; . "$HOME/.hermes/.env" 2>/dev/null; set +a
fi
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "cf[$PROJECT]: CREDENTIALS MISSING (CLOUDFLARE_API_TOKEN / _ACCOUNT_ID)" >&2
  exit 5
fi
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

# ── ⑤ wrangler ──
WRANGLER=""
# ★坑(2026-09-19): wrangler 原装在 /tmp(重启即失), 当天迁到 ~/.hermes/tools/ 但本脚本
#   搜索路径没同步 → 报 "wrangler NOT FOUND" exit 6。持久路径必须排在最前。
for c in "$HOME/.hermes/tools/node_modules/.bin/wrangler" /tmp/node_modules/.bin/wrangler "$HOME/.npm-global/bin/wrangler" "$(command -v wrangler 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && { WRANGLER="$c"; break; }
done
if [ -z "$WRANGLER" ]; then
  echo "cf[$PROJECT]: wrangler NOT FOUND" >&2
  exit 6
fi

# ── ⑥ 项目不存在则建 ──
# ★坑(2026-09-19 实测): 建项目后 Cloudflare 侧有**传播延迟**, 立即 deploy 会报
#   "project not found" 而 rc=1 —— 8/10 站点首轮就栽在这。故建完必须轮询到真能查到为止。
CREATE_RESP=$(curl -s --max-time 60 -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data "{\"name\":\"$PROJECT\",\"production_branch\":\"main\"}" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects" 2>&1)
# 8000002 = 已存在, 属正常; 其余失败则打印真实报错(不吞)
if ! echo "$CREATE_RESP" | grep -q '"success":true'; then
  if ! echo "$CREATE_RESP" | grep -q '8000002'; then
    echo "cf[$PROJECT]: create warning — $(echo "$CREATE_RESP" | head -c 200)" >&2
  fi
fi
# 轮询直到项目可查(最多 ~60s)
# ★坑2(2026-09-19): 单项目端点 GET /pages/projects/<name> 的返回体**不含** "success" 字段,
#   它直接返回 {"result":{...}}。用 grep '"success":true' 作判据会永远失败 ——
#   我据此误判成"传播超时"。正确判据是看 result.id 是否存在。
READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -s --max-time 20 -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$PROJECT" \
      2>/dev/null | grep -q '"subdomain"'; then
    READY=1; break
  fi
  sleep 5
done
if [ $READY -ne 1 ]; then
  echo "cf[$PROJECT]: project not queryable after create (propagation timeout)" >&2
  exit 7
fi

# ── ⑦ 准备发布目录 ──
STAGE="/tmp/cfstage_${PROJECT}"
rm -rf "$STAGE"; mkdir -p "$STAGE"
if [ -n "$SRCDIR" ]; then
  cp -r "$SRCDIR"/. "$STAGE"/ 2>/dev/null
else
  cp "$MAIN" "$STAGE/index.html"
fi

# ── ⑧ 部署(显式判 rc) ──
LOG="/tmp/cfdeploy_${PROJECT}.log"
timeout 900 "$WRANGLER" pages deploy "$STAGE" \
  --project-name="$PROJECT" --branch=main --commit-dirty=true > "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "cf[$PROJECT]: DEPLOY FAILED rc=$RC" >&2
  tail -8 "$LOG" >&2
  exit 7
fi

# ── ⑨ ★线上实测(唯一可信判据): 匿名 curl 取回, 比对 sha256 ──
URL="https://${PROJECT}.pages.dev/"
ONLINE_OK=0
for i in 1 2 3 4 5 6; do
  sleep 5
  CODE=$(curl -s -o /tmp/cfverify.html -w '%{http_code}' -L --max-time 90 "${URL}?cb=$RANDOM$i" 2>/dev/null)
  if [ "$CODE" = "200" ]; then
    GOT=$(sha256sum /tmp/cfverify.html | awk '{print $1}')
    if [ "$GOT" = "$NEW_SHA" ]; then ONLINE_OK=1; break; fi
    LAST="content mismatch (got ${GOT:0:12} want ${NEW_SHA:0:12})"
  else
    LAST="HTTP $CODE"
  fi
done
if [ $ONLINE_OK -ne 1 ]; then
  echo "cf[$PROJECT]: ONLINE VERIFY FAILED — $LAST" >&2
  echo "cf[$PROJECT]: $URL" >&2
  exit 8
fi

# 只有线上实测通过才算成功
echo "$NEW_SHA" > "$STAMP"
printf 'cf[%s]: LIVE %s (sha %s, %s bytes)\n' "$PROJECT" "$URL" "${NEW_SHA:0:12}" "$(wc -c < "$MAIN")"
exit 0
