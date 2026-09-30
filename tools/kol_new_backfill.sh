#!/usr/bin/env bash
# eco-vol 新 KOL 自动一年期回填（Chao 2026-09-30：「每次新增一个 KOL 都需要 backfill 他们的言论」）
#
# 触发：no_agent cron 工作日 14:00 调 ~/.hermes/scripts/eco_vol_kol_new_backfill.sh → 本脚本（setsid 脱离）。
#   11:00 日报步骤 0 已把 Notion 名册同步到 data/kol_registry.json，所以 14:00 能看到当天新增的人。
#
# 判定「要回填的人」（纯机械，不调 LLM）：名册里过去 365 天在 kol_store 覆盖 < MIN_MONTHS 个月的人，
#   且在账本 data/kol_backfill_ledger.json 里尝试次数 < MAX_TRY（公开信息确实少的人不无限重试烧配额）。
# 流程：选人 → 每批 2 人、最多 3 批并行起 hermes 子进程（沿用 gap110 的规格与铁律）→
#       tools/kol_bf_ingest.py --apply 过门禁入库（出处实测、窗口、方向、去重）→ 只提交 data/kol_store.sqlite
#       → 校验 local==remote。看板在下一次日报构建时自动带上。
# 输出：没有要回填的人 → 完全静默；有 → 一段汇总（谁、入库几条、覆盖几个月）；失败 → ❌ 一行。
# 断点：同一天重复触发，已 RUNNING/DONE 直接退出。
set -uo pipefail
ROOT=${KOL_BF_ROOT:-/home/user/Projects/Eco-and-Volatility-Checker}   # 覆盖仅供沙箱自测
cd "$ROOT" || { echo "❌ 新KOL回填: 项目目录不存在"; exit 1; }
if [ "${KOL_BF_DRY:-0}" = "1" ] && [ "$(pwd -P)" = "/home/user/Projects/Eco-and-Volatility-Checker" ]; then
  echo "拒绝: DRY 自测不许对正式目录跑(会往真库写假数据)"; exit 2; fi
DAY=${KOL_BF_DATE:-$(date +%F)}
D="scratch/kol_bf_auto_$DAY"
LEDGER=data/kol_backfill_ledger.json
MIN_MONTHS=${KOL_BF_MIN_MONTHS:-3}
MAX_TRY=2
PER=2; PAR=3
BATCH_TIMEOUT=${KOL_BF_BATCH_TIMEOUT:-3000}   # 单批 50 分钟；cron 脚本上限 60 分钟，留 10 分钟给入库+提交
DRY=${KOL_BF_DRY:-0}          # 1 = 不调 LLM（子进程写假产出），只验证链路
NOPUSH=${KOL_BF_NOPUSH:-0}    # 1 = 不 commit/push（沙箱）
mkdir -p "$D/batches" "$D/out"
exec 9>"$D/.lock"; flock -n 9 || exit 0
if [ -f "$D/STATUS" ] && grep -qE '^(RUNNING|DONE|NONE)' "$D/STATUS"; then exit 0; fi
log(){ echo "$(date '+%F %T') $*" >> "$D/progress.log"; }

# ── 1. 选人 ──
.venv/bin/python - "$D" "$LEDGER" "$MIN_MONTHS" "$MAX_TRY" "$((PER*PAR))" <<'EOF' || { echo "❌ 新KOL回填: 选人失败"; exit 1; }
import json, os, sqlite3, sys, datetime as dt
D, LEDGER, MINM, MAXT, CAP = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
reg = json.load(open("data/kol_registry.json"))["kols"]
led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
today = dt.date.today(); since = (today - dt.timedelta(days=365)).isoformat()
win = [(today.replace(day=1) - dt.timedelta(days=31 * i)).strftime("%Y-%m") for i in range(12)]
win = sorted(set(win))[-12:]
cov = {}
for name, d in sqlite3.connect("data/kol_store.sqlite").execute("select kol_name,date from opinion where date>=?", (since,)):
    cov.setdefault(name, set()).add(d[:7])
todo = []
for k in reg:
    if not k.get("active", True):
        continue
    have = sorted(cov.get(k["display_name"], set()) & set(win))
    if len(have) >= MINM or led.get(k["id"], {}).get("tries", 0) >= MAXT:
        continue
    todo.append({"id": k["id"], "name": k.get("short_name") or k["display_name"].split("（")[0],
                 "display": k["display_name"], "sector": k.get("domain", ""),
                 "search_terms": k.get("search_terms") or [k.get("short_name") or k["display_name"].split("（")[0]],
                 "have_months": have, "missing_months": [m for m in win if m not in have]})
# 新加入名册的人优先；每天最多 CAP 人（一波并行跑完，保证在 cron 脚本 1 小时上限内结束），其余顺延到下一个工作日
todo.sort(key=lambda x: (len(x["have_months"]), x["id"]))
json.dump(todo[:CAP], open(f"{D}/todo.json", "w"), ensure_ascii=False, indent=1)
json.dump(todo[CAP:], open(f"{D}/deferred.json", "w"), ensure_ascii=False, indent=1)
EOF
N=$(.venv/bin/python -c "import json;print(len(json.load(open('$D/todo.json'))))")
if [ "$N" = "0" ]; then echo "NONE $(date '+%F %T')" > "$D/STATUS"; exit 0; fi
echo "RUNNING $(date '+%F %T') $N 人" > "$D/STATUS"
log "待回填 $N 人"

# ── 2. 规格（沿用 gap110 铁律，窗口改为滚动一年）──
WS=$(date -d "$DAY -365 days" +%F)
sed -e "s#scratch/kol_bf_gap110#$D#g" -e "s#2025-09-29 ~ 2026-09-29#$WS ~ $DAY#g" \
    -e "s#（2026-09-29，老名册缺月补齐 110 人）#（自动：名册新增/覆盖不足 $MIN_MONTHS 个月的人）#" \
    scratch/kol_bf_gap110/INSTRUCTIONS.md > "$D/INSTRUCTIONS.md"

run_batch(){  # $1 = 批名
  local B="$1"
  if [ "$DRY" = "1" ]; then
    .venv/bin/python - "$D" "$B" <<'EOF'
import json, sys
D, B = sys.argv[1:]
for x in json.load(open(f"{D}/batches/{B}.json")):
    json.dump([{"date": "2026-09-01", "direction": "中性", "comments": "DRY 假数据", "targets": "",
                "source": "https://example.invalid/x", "detail": "", "detail_status": "partial"}],
              open(f"{D}/out/{x['id']}.json", "w"), ensure_ascii=False)
EOF
    return
  fi
  local PROMPT="你是 KOL 一年期观点回填子agent。工作目录 $ROOT。
先完整阅读规格 $D/INSTRUCTIONS.md（铁律必须遵守），再读名单 $D/batches/$B.json（每项含 id/name/display/sector/search_terms/have_months/missing_months）。**只找 missing_months 里的月份**，每个缺失月份尽量 1-2 条。
display 字段里有机构/头衔，用来排除同名的人。
对名单里每个人按规格检索，**每做完一个人立即用 write_file 落盘** $D/out/<id>.json（裸 JSON 数组），不要攒到最后。
每条的 source 必须是你亲自 web_extract 打开过、页面里确有此人此观点的 URL；日期只认原文发布日。找不到就少写，写 [] 也可以。
全部完成后按规格「完成后回报」每人一行，最后一行写: DONE $B"
  timeout "$BATCH_TIMEOUT" hermes -z "$PROMPT" --provider custom -m claude-opus-5-5 > "$D/log_$B.txt" 2>&1
  echo "EXIT $B $?" >> "$D/log_$B.txt"
}

# ── 3. 分批并行 ──
mapfile -t IDS < <(.venv/bin/python -c "import json;[print(x['id']) for x in json.load(open('$D/todo.json'))]")
pids=(); b=0
for ((s=0; s<${#IDS[@]}; s+=PER)); do
  b=$((b+1)); BN="b$b"
  .venv/bin/python - "$D" "$BN" "${IDS[@]:$s:$PER}" <<'EOF'
import json, sys
D, BN, ids = sys.argv[1], sys.argv[2], set(sys.argv[3:])
json.dump([x for x in json.load(open(f"{D}/todo.json")) if x["id"] in ids], open(f"{D}/batches/{BN}.json", "w"), ensure_ascii=False, indent=1)
EOF
  run_batch "$BN" & pids+=($!)
  sleep 2
  if [ ${#pids[@]} -ge $PAR ]; then wait "${pids[0]}"; pids=("${pids[@]:1}"); fi
done
for p in "${pids[@]}"; do wait "$p"; done
log "子进程全部结束"

# ── 4. 账本 +1（不管有没有产出，防止无限重试）──
.venv/bin/python - "$D" "$LEDGER" <<'EOF'
import json, os, sys, datetime as dt
D, LEDGER = sys.argv[1:]
led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
for x in json.load(open(f"{D}/todo.json")):
    e = led.setdefault(x["id"], {"tries": 0})
    e["tries"] += 1; e["last"] = dt.date.today().isoformat()
    e["out"] = os.path.exists(f"{D}/out/{x['id']}.json")
json.dump(led, open(LEDGER, "w"), ensure_ascii=False, indent=1)
EOF

# ── 5. 门禁入库 ──
FETCH=""; [ "$DRY" = "1" ] && FETCH="--no-fetch"
R=$(.venv/bin/python tools/kol_bf_ingest.py "$D" --apply $FETCH 2>&1 | tail -1)
log "入库: $R"
case "$R" in APPLY*) ;; *) echo "❌ 新KOL回填: 入库脚本失败: $R"; echo "FAIL $(date '+%F %T')" > "$D/STATUS"; exit 1;; esac

# ── 6. 汇总 ──
SUMMARY=$(.venv/bin/python - "$D" <<'EOF'
import json, sys
D = sys.argv[1]
rep = json.load(open(f"{D}/ingest_report.json"))
todo = json.load(open(f"{D}/todo.json"))
lines = []
for x in todo:
    p = rep["people"].get(x["id"])
    if not p or "error" in p:
        lines.append(f"· {x['name']}：0 条（{(p or {}).get('error', '子进程未产出')}）")
    else:
        rj = len(p.get("rejects", []))
        lines.append(f"· {x['name']}：入库 {p['kept']} 条，覆盖 {p['months']} 个月" + (f"，门禁拒收 {rj}" if rj else ""))
T = rep["totals"]
import os
dfr = json.load(open(f"{D}/deferred.json")) if os.path.exists(f"{D}/deferred.json") else []
print(f"新 KOL 一年期回填完成：{len(todo)} 人，新增 {T['inserted']} 条（其中 {T['unverifiable']} 条站点拦截未能自动核验）")
print("\n".join(lines))
if dfr:
    print(f"另有 {len(dfr)} 人排队，下个工作日继续：" + "、".join(x["name"] for x in dfr[:10]))
EOF
)

# ── 7. 提交（只提交 store + 账本）──
if [ "$NOPUSH" != "1" ]; then
  git add data/kol_store.sqlite "$LEDGER"
  if ! git diff --cached --quiet; then
    # ★cron 环境没有交互式签名凭据, /etc/gitconfig 的 commit.gpgsign=true(x509) 会让 commit 直接失败
    #   (2026-09-30 首跑即栽: "gpg failed to sign the data")。与 scripts/daily_commit_push.sh 同做法: 本次提交不签名。
    CERR=$(git -c commit.gpgsign=false commit -q -m "kol: 新 KOL 自动一年期回填 $DAY（$N 人）" 2>&1) \
      || { echo "❌ 新KOL回填: 数据已入库但 commit 失败: $CERR"; echo "FAIL $(date '+%F %T') commit" > "$D/STATUS"; exit 1; }
    PUSH_OUT=$(git push -q origin HEAD 2>&1) || { echo "❌ 新KOL回填: push 失败 $PUSH_OUT"; echo "FAIL $(date '+%F %T') push" > "$D/STATUS"; exit 1; }
    git fetch -q
    [ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] || { echo "❌ 新KOL回填: push 后 local≠remote"; exit 1; }
  fi
fi
echo "DONE $(date '+%F %T')" > "$D/STATUS"
echo "$SUMMARY"
echo "（看板在下次日报构建时自动更新）"
