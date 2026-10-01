# KOL registry management, new indicator cards, backfill & git ops

Session-distilled operating detail for the Eco-and-Volatility-Checker KOL subsystem
and for adding new indicator cards. Complements the main SKILL.md.

## 1. Adding a KOL to the registry (the safe workflow)

Registry SSOT: `data/kol_registry.json` (key `kols`, each entry has
`id / display_name / notion_select_name / domain / sector / detail_sector /
kol_or_ib / institution / search_terms / x_handle / active / added_date / focus`).
Registry rule: **只增不减** (only-add). SSOT mirror = Notion KOL List DB.

Steps (do NOT hand-edit the big JSON — use a small idempotent python snippet):
1. `active` filter matters: only `active==true` entries are crawled. Institutions /
   fund founders that are non-crawl targets are `active:false` (e.g. Goldman Sachs,
   fund-head names) — the crawl count ≠ total registry count.
2. Idempotency: skip if the person already exists (`any('lastname' in
   k['display_name'].lower() ...)`).
3. Classify by ANCHORING TO EXISTING enum values, don't invent new ones. Read the
   current `domain`/`sector` distribution first. Known enums include
   sector: `Precious Metals / Macro / Equities / Government Debt / Alternative / Crypto`;
   domain includes `贵金属 / 贵金属与商品周期 / 宏观货币与金融体系 / 预测 / ...`.
4. Fill `search_terms` correctly for the person's TYPE — see §2.
5. Write, then **read back** (`json.load` again) to verify count, the new name is
   present, `active==true`, and prior entries still there (only-add proof).
6. Red-line scan `data/kol_registry.json` for keys (it's public KOL info, always clean),
   commit `--no-gpg-sign` / `-c commit.gpgsign=false`, push.

### The "身份描述 + 名字" trap (Chao corrected this, 2026-08)
When the user gives a NAME plus a role description, add EXACTLY the named person.
Do NOT let the role description make you联想-substitute a different well-known person.
Real mistake this session: user said "Sprott CIO ... Maria Smirnova" across turns;
I wrongly added John Hathaway (a Sprott PM but not the CIO) AND invented David
Rosenberg. Both had to be reverted. Lesson: the name is authoritative; the role is
just context. If name and role seem to point at different people, ASK — do not pick.
Reverting is a real delete (breaks only-add), so it needs explicit user OK.

### 另类预言 / Alternative KOLs (psychics, astrologers, doom-predictors)
These EXIST as a legitimate category in the registry (`domain=预测` / `sector=Alternative`:
Abhigya Anand, David Icke, Craig Hamilton-Parker, etc.). They are tracked as an
ALTERNATIVE / SENTIMENT signal, NOT as tradeable-direction analysts.
- `search_terms` = "<name> world predictions" (NOT "<name> latest market view").
- Do not force a strict bull/bear direction; map doom/collapse-prediction → 看空,
  recovery-prediction → 看多, and note it's alternative in comments.
- When user says "add X" and X is a psychic, CONFIRM intent once (they may want the
  doom-prophecy propagation as an alt-sentiment signal — a valid use) before classing.

## 2. Daily crawl cron must NOT hardcode the KOL count (pitfall Chao hit)
The daily-scan cron prompt (`eco-vol-01-daily-scan-report`) originally said
"读名册...88个KOL ... 对全部 88 个 KOL" in 4 places. Adding new KOLs then silently
dropped them (agent crawled only 88). FIX: change every hardcoded number to a DYNAMIC
phrasing — "读名册取 active==true 的全部 KOL(数量以名册为准)". Then adding a KOL is
registry-edit + push only, ZERO cron change. Also add per-type crawl instructions
(analysts use "latest market view", Alternative use their search_terms).
The cron store is `~/.hermes/cron/jobs.json` (unicode-escaped) — edit the prompt field
via python (load → replace exact substring → dump ensure_ascii=False), assert the OLD
string matched before writing, then read back and grep for leftover numbers.

## 3. Adding a NEW indicator card (worked example: Credit Impulse)
Pattern for any new card: fetcher in `src/external_data.py` → html/svg + CSS in
`src/dashboard.py` → wire a param through `generate()` + template + `build_dashboard.py`
→ rebuild → browser/console verify → commit → (usually) NO new cron because
`build_dashboard` runs inside the existing daily cron and auto-picks up the new fetcher.

Credit Impulse specifics (a reusable mid-term leading indicator):
- Definition = Δ(new credit flow)/GDP = 2nd difference of credit stock / GDP =
  the ACCELERATION of new lending (not debt total, not new debt). Leads real economy
  ~6-9 months; China's is a top global commodity/risk-asset leading indicator.
- DATA REALITY: web_search cannot fetch true "as-of past date" views; but BIS credit
  series exist on FRED. Use BIS **credit-to-GDP ratio** (`QUSPAM770A/QCNPAM770A/
  QXMPAM770A`, quarterly, %GDP) and take its **2nd difference** as CI. This ≈ the
  absolute-flow method (`CRDQ*APABIS`/GDP) — verified identical direction/turning
  points, <0.2pp diff — but keeps 3 countries on one BIS-comparable basis, both to
  2025-10, and avoids the missing China quarterly GDP (FRED China GDP stops 2023).
- Frequency honesty: BIS is quarterly, lags ~1 quarter. Label the card "季度更新·数据
  滞后约1季 (as of …)". Do NOT imply weekly/monthly when the source is quarterly.
- FRED fetch: prefer the keyed API path (`fetchers.fred.fetch_fred_history`) — the
  keyless `fredgraph.csv` endpoint intermittently times out. Provide both (keyed first,
  keyless fallback).
- SVG for signed values needs an explicit ZERO axis + latest-point signal-color hollow
  circle (green #2e9e5b / yellow #e0a92e / red #d64545), matching Chao's morandi+signal
  palette.

## 4. git commit foreground timeout = DISPLAY ARTIFACT, run it in the background
Repeatedly this session `git commit` (and commit+push) returned the tool's 60s
timeout even though the commit was TINY and there was no lock / no hook / no hung git
process (git log returned instantly). The commit had NOT applied (HEAD unchanged,
files still staged). Retrying foreground kept timing out. FIX that worked every time:
run the commit (and push) with `terminal(background=true, notify_on_complete=true)`,
then `process(action=poll)` — the background run completes and shows the real
`[main <sha>]` + push refspec. Treat foreground git-commit timeout as a display-layer
artifact on this VM, not a real failure; go background. (Related but distinct from the
redactor/SSH agent issues — this is plain local
commit, no auth involved.)

## 5. KOL historical-comment backfill method (past-year comments)
Goal: give every active KOL ~1 year of dated opinion `comments`.
- Storage: one file per KOL `data/kol/daily/` snapshots use key `kols` (NOT `all` —
  a real gotcha: I first queried the wrong field and saw "all snapshots empty").
  Backfill output: `data/kol/backfill/<id>.json` =
  `{kol,sector,backfill_date,source_method,count,history:[{date,direction,comments,
  targets,source}]}`.
- HARD REALITY (tell the user up front): web_search returns CURRENT retrievable
  content, it cannot time-travel. "Complete past-year comments" is NOT achievable from
  search; what IS achievable is: per-KOL search "past 12 months views", LLM extracts
  ONLY entries whose date can be confirmed from a real source. Not found → skip / mark
  "未找到". Never fabricate a date or a view.
- Execution: parallel `delegate_task` (toolset `["web"]`), max 3 children per call
  here. Each child returns a JSON array + a coverage report. SAMPLE FIRST (3-5 KOLs),
  get user sign-off, then full (Chao's "样板验收才全量" rule).
- Yield when search healthy: well-covered analysts (Colombo, Gromen, Hemke) → 7-12
  dated entries each; niche people or those whose content only lives on aggregator
  sites where authorship can't be confirmed → 0 (honest empty, NOT fabricated).
- **web_search-health GATE**: if search returns empty (386-byte empty `data.web:[]`)
  for even a generic query, the backend is DOWN (documented failure mode). Do NOT hard-
  run backfill through an outage — you'll get mass "未找到" that is a tool artifact,
  not real absence. PAUSE and either wait or set a watchdog cron (every 2h) that health-
  checks search and auto-resumes the remaining KOLs, committing as it goes. Commit each
  batch immediately so nothing is lost mid-run.
