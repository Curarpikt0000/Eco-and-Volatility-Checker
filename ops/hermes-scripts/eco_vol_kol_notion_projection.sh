#!/usr/bin/env bash
# Eco KOL store -> Notion projection.
# Runs after the new-KOL backfill job. Quiet when no Notion writes are needed.
set -uo pipefail

export TZ='Asia/Tokyo'
ROOT="<PROJECT_ROOT>"
cd "$ROOT" || { echo "❌ KOL Notion 投影: 项目目录不存在"; exit 1; }

DAY=$(date +%F)
D="scratch/kol_notion_projection_$DAY"
mkdir -p "$D"
RESULT="$D/result.json"
LOG="$D/run.log"

OUT=$(
  timeout 7200 .venv/bin/python - "$RESULT" 2>&1 <<'PY'
import json
import sys

sys.path.insert(0, "src")
import kol_notion_sync as kns  # noqa: E402

out = {"opinions": None, "list_source": None}
out["opinions"] = kns.sync_opinions(dry_run=False)
out["list_source"] = kns.sync_kol_list_source(dry_run=False)
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

errors = (out["opinions"].get("errors") or []) + (out["list_source"].get("errors") or [])
raise SystemExit(2 if errors else 0)
PY
)
RC=$?
{
  echo "=== $(date '+%F %T %Z') rc=$RC ==="
  echo "$OUT"
  [ -f "$RESULT" ] && cat "$RESULT"
  echo
} >> "$LOG"

if [ "$RC" -ne 0 ]; then
  echo "❌ KOL Notion 投影失败(rc=$RC)，见 $D/run.log"
  exit "$RC"
fi

SUMMARY=$(.venv/bin/python - "$RESULT" <<'PY'
import json
import sys

r = json.load(open(sys.argv[1], encoding="utf-8"))
op = r["opinions"] or {}
ls = r["list_source"] or {}
created = int(op.get("created") or 0)
patched = int(op.get("patched") or 0)
src_written = int(ls.get("written") or 0)
errors = len(op.get("errors") or []) + len(ls.get("errors") or [])
if created or patched or src_written or errors:
    print(json.dumps({
        "created": created,
        "patched": patched,
        "list_source_written": src_written,
        "store_rows": op.get("store_rows"),
        "notion_rows_before": op.get("notion_rows"),
        "errors": errors,
    }, ensure_ascii=False))
PY
)

if [ -z "$SUMMARY" ]; then
  exit 0
fi

# sync_opinions records notion_page_id back into sqlite; keep that durable.
git add data/kol_store.sqlite
if ! git diff --cached --quiet; then
  CERR=$(git -c commit.gpgsign=false commit -q -m "kol: sync Notion projection $DAY" 2>&1)
  if [ $? -ne 0 ]; then
    echo "❌ KOL Notion 投影已写入，但 notion_page_id commit 失败: $CERR"
    exit 3
  fi
  PUSH_OUT=$(git push -q origin HEAD 2>&1)
  if [ $? -ne 0 ]; then
    echo "❌ KOL Notion 投影 notion_page_id push 失败: $PUSH_OUT"
    exit 4
  fi
fi

echo "KOL Notion 投影完成: $SUMMARY"
