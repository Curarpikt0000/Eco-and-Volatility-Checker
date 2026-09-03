#!/usr/bin/env bash
# ensure_tesseract.sh — 幂等确保 tesseract-ocr 可用。
#
# 为什么需要它：tesseract 是 **apt 装的系统二进制**，不是 pip 包。
# devpod 容器重启会把它擦掉（实测 2026-09-03 15:21 重启 → 2026-09-04 已不存在，
# apt 装完时本来就提示 "will not persist over updates/restarts"）。
# 它一旦消失，src/oge_trump.py 的 _ocr_pages() 就拿不到文字，
# 川普 OGE 278-T 逐笔交易会从 632 条**静默退回 0 条**（不报错）。
#
# 用法：
#   bash tools/ensure_tesseract.sh          # 已装则静默退出；没装则 apt 装上
#   bash tools/ensure_tesseract.sh --check  # 只检查不安装，缺失时 exit 1
#
# 长期持久化：把本脚本挂进 ~/.devpod/personal.devpod.yaml 的 tasks
# （容器每次 create/restart 都会执行），或 crontab 的 @reboot。
# 这两处都是 Chao 的共享配置，需他本人同意后再改。
set -uo pipefail

log() { echo "[ensure_tesseract] $*"; }

if command -v tesseract >/dev/null 2>&1; then
  log "ok: $(tesseract --version 2>&1 | head -1)"
  exit 0
fi

if [ "${1:-}" = "--check" ]; then
  log "MISSING: tesseract 不在 PATH（devpod 重启会擦掉它）"
  exit 1
fi

log "missing → apt-get install tesseract-ocr tesseract-ocr-eng"
sudo -n apt-get update -qq >/dev/null 2>&1
sudo -n apt-get install -y tesseract-ocr tesseract-ocr-eng >/dev/null 2>&1

if command -v tesseract >/dev/null 2>&1; then
  log "installed: $(tesseract --version 2>&1 | head -1)"
  exit 0
fi

log "FAILED: 安装后仍不可用，川普 278-T 逐笔将退回 0 条（不是没交易，是读不了）"
exit 1
