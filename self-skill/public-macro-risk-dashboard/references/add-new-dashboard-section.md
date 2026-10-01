# Adding a new "data source → dashboard section" (repeatable checklist)

This is the canonical procedure for the recurring request "帮我把这张图/这个指标也建进 dashboard".
Done 3× in one session (silver COT positioning, COMEX silver issues static ref, US gold exports)
with identical wiring. Follow in order; each step has a known anchor file.

## Batch of charts at once ("这5个图，你能拿到数据就做哪个")
Chao often sends SEVERAL reference-image charts in one turn and says build the ones you can get
data for. Do NOT block the whole batch waiting on the hardest source. Triage FIRST, then execute:
- For each chart: run step-0 source vetting → classify ✅buildable-now / ⚠️needs-user-input / ❌blocked.
- Immediately BUILD every ✅ (data first-party & in hand), commit them, THEN report a per-chart
  verdict table and ask Chao only the specific unblocking questions for the ⚠️/❌ ones (bundle them
  into ONE clarify, don't drip-ask). Don't idle waiting for a reply — if Chao goes quiet, ship the
  buildable ones and leave the blocked ones as pending todos.
- Known verdicts for precious-metals / India charts (probed this session, skip re-probing):
  - US Treasury yield century cycle → ✅ FRED FEDFUNDS(1954)/TB3MS(1934)/GS10(1953)/GS30(1977) monthly.
    1920–1933 has no FRED monthly → draw from each line's true start, honest note, don't fabricate.
  - COMEX market-maker weekly net issue/stop → ✅ via sibling Comex repo (see per-firm section below).
  - India silver IMPORTS monthly → ✅ SOLVED via **UN Comtrade free monthly API** (supersedes the old
    "DGCIS/S&P paywalled → skip" verdict). DGCIS portal is annual-only + paywalled for monthly, S&P
    Global is paywalled — but UN Comtrade (UNSD, a DIFFERENT non-national free source) has India HS7106
    monthly. See "Free monthly trade data via UN Comtrade" below. Validated 2932t anchor vs LBMA.
  - India domestic premium/discount → gold: WGC goldhub has it (2012+ daily) — xlsx is behind a WGC
    login, so it's a **user-supplied-xlsx** section (Chao downloads once, we parse; see below). The
    xlsx also carries CHINA premium (2003+) as a bonus 2nd line. Silver premium is Metals Focus
    (paywalled, no free equivalent) → build GOLD premium from WGC, label honestly, leave silver pending.

### Escalation ladder when the free official path looks closed
Chao's standing follow-up after "免费源堵死" is **"再扩展一下范围，看看有没有个人网站上的非官方源"**.
Pre-empt it — run the ladder in one pass and report the whole thing, rather than closing at rung 1:
1. Official first-party API → 2. Official **PDF/XLSX attachment** (see
`references/china-official-stats-pdf-sources.md` — the norm for Chinese regulators) → 3. Legacy/previous-generation
URL path of the same site → 4. Wayback → 5. Non-official aggregators & academic/personal sites
(Damodaran, chinadata.live, university data pages) → 6. Declare closed.
**Any rung-5 hit must be cross-validated against a known official number before it ships**, and must be
labelled 第三方 in the UI. A third-party series that matches official on every overlapping period is
usable; one you can't overlap-test is not.

### PITFALL: don't delegate an open-ended source hunt — it hits the 600s subagent cap
Two `delegate_task` subagents sent to "find data source X" both **timed out at 600s** (34 and 12 API
calls, zero output returned) — an open-ended probe loop has no natural stopping point, so the whole
budget burns and you get NOTHING back, having lost 10 minutes. Either do source-hunting inline (you can
checkpoint and keep partial findings), or delegate only a **narrowly scoped, few-call** question
("fetch THIS url, parse THIS table, report the numbers"). Never delegate "search the web until you find
a source for X".

### Long probe sessions: report progress before the user has to ask
Chao gets anxious on long silences ("还在跑么"). Source-vetting sweeps run 10+ minutes across many
probe scripts. Checkpoint to him mid-sweep with what's confirmed vs still open, and when a mid-turn
request arrives (he often adds a NEW chart request while you're probing), acknowledge it, finish the
in-flight correctness fix, then pivot — don't silently queue it.

## 0. Vet the data source BEFORE writing any code (most important step)
Users often send a **screenshot of someone else's chart**. Do NOT assume the chart's label or
source is usable. Classify the source first and tell Chao the honest verdict + give options:

- **First-party, free, no-key, backfillable** (FRED / CFTC Socrata / US Treasury fiscaldata /
  BEA via FRED / TIC / BOJ / EIA / IMF SDMX): ✅ ideal — build a real auto-updating section.
- **Blocked by scraping ban** (e.g. **CME/COMEX**: `cmegroup.com/delivery_reports/*.pdf` returns
  a JSON "IP address is blocked … Data Terms of Use" body, ~600 bytes, NOT a PDF): ❌ hard wall,
  compliance-sensitive. Do not keep hammering it. Offer: (A) static reference chart w/ explicit
  "非实时·来源X·CME封禁无法自动更新" labeling, or (B) a **semantic-equivalent first-party source**.
- **Third-party mirror / niche GitHub tracker**: check `api.github.com/repos/<x>/commits` for
  staleness before relying on it (nyxgeek/comex_silver_tracker was 6mo stale → unusable as daily).
- **A named analyst's chart (Substack/X)**: check their archive for update cadence. If event-driven,
  irregular, no API, PNG-embedded, no raw series → only viable as **static reference anchors**
  hand-transcribed from the public image, clearly labeled non-real-time.

### Honest labeling when the chart's TITLE is wrong
Chao's rule: 论断锚具名数据+可追溯出处; 绝不臆测. If a user's chart is mislabeled, use the TRUE
series + TRUE title, do NOT copy the mislabel. Example this session: user image said "Monetary
gold" but FRED has no such export series; the real surge is **IEAXGG = Nonmonetary gold**
(private/commercial physical bullion, not central-bank reserve gold). Built with IEAXGG + honest
"数据诚实说明" paragraph explaining the discrepancy. Central-bank reserve gold does not get exported
like this — the semantic check catches the mislabel.

### Free monthly trade data via UN Comtrade (when "official portal is paywalled/annual-only")
When a country's OWN trade portal (DGCIS, national customs) is paywalled or annual-only, the same
import/export flow is almost always available FREE and MONTHLY from **UN Comtrade (UNSD)** — a
different, non-national, free source. This turned India silver imports from ❌paywalled into a ✅
buildable auto-updating monthly section this session.
- Endpoint (免key preview, no signup): `https://comtradeapi.un.org/public/v1/preview/C/M/HS`
  params: `reporterCode=<M49>` (India=699), `period=YYYYMM`, `flowCode=M` (M=import, X=export),
  `cmdCode=<HS>` (silver bullion = HS **7106**; gold = 7108), `partnerCode=0` (World).
  Preview limits **ONE period per call** → loop months with a ~1.5s sleep; wrap in retry(3).
- **口径 anchor-validation trick (MANDATORY — caught a 2× double-count this session):** the preview
  response returns MULTIPLE rows per period, split by `partner2Code`. Naively `sum(netWgt)` over ALL
  rows DOUBLE-COUNTS (World total + per-partner breakdown both present) → gave 3580t vs the true 1837t.
  **Fix: filter to the single `partner2Code == 0` row** (World total, no secondary breakdown) — exactly
  one row per period. Then `netWgt` is in **kg → /1000 = tonnes**. VALIDATE against a known public
  anchor before trusting: LBMA publicly stated India's first two months of 2024 = 2932t; the
  `partner2Code==0` sum gave 636.8 + 2295.3 = **2932.1t — exact match**, proving the口径. Always
  cross-check a computed series against ONE independently-published number before shipping it.
- Data lag: Comtrade publishes ~1–2 months behind; latest month is often absent → the fetch must
  SKIP-not-zero missing months (绝不补0), and the section is a `每月` (monthly) freq badge.
- History depth via free preview is limited (India went back to 2024 only). If <5yr, do NOT fake a
  "5-year average" line — use a **12-month rolling mean** and label it as such honestly.
- Auto-increment: fetch script is idempotent (reads existing JSON, only appends missing months) and
  is invoked from build_dashboard.py's try-block via `subprocess.run(["python3", <script>])` so the
  daily cron picks up new months with no cron-prompt edit.

### User-supplied paywalled xlsx (WGC goldhub etc.) — parse-script + manual-refresh pattern
Some ideal series are FREE but behind a one-time account login (WGC goldhub gold premium: free but
login-gated xlsx, no API). Pattern: Chao downloads the xlsx once and sends it; we build a parse
script that lands a clean JSON, and the section is "手动刷新" (Chao re-downloads periodically).
- Parse with `openpyxl` (`.venv` has it): `load_workbook(path, data_only=True)`; iterate sheets —
  a single WGC download often carries MULTIPLE useful series (Indian + Chinese premium tabs). Handle
  BOTH `datetime` cells and `'YYYY-MM-DD'` string cells for the date column; skip header/disclaimer rows.
- Landed JSON keeps `points`, `unit`, `source`, `as_of`, min/max, n. Confirm sane extremes vs the
  chart you're mirroring (India premium range −120 ~ +172 US$/oz, 3801 daily pts 2012→) before wiring.
- The fetch fn in external_data.py just READS the landed JSON (no live pull) — status='未获取' if the
  file is missing so it degrades gracefully. Offer Chao an optional daily-cron "WGC data is N days old"
  staleness reminder rather than pretending it auto-updates.
- When the reference chart Chao sent is a DIFFERENT metal than what's freely available (his ref was
  SILVER premium = Metals Focus paywalled; only GOLD premium is free via WGC), build the free one and
  LABEL the discrepancy in the section (数据诚实说明: "本图为黄金 premium…白银 premium 源 Metals Focus
  付费, 待补"). Never silently substitute one metal for another without the honest note.

### Reusing a SIBLING project's existing acquisition + parser (don't rebuild the wheel)
Before building a fetcher from scratch, search Chao's OTHER repos — he often already has a hardened
pipeline for the same raw data. Example this session: the CME-blocked issues/stops PDF is ALREADY
solved in `~/Projects/Comex-Daily-AI-Report/`: `scripts/cme_delivery_parser.parse_delivery_pdf`
(x-coordinate parser, returns per-seat `{firm, org, name, issued, stopped}` — validated across 133
historical PDFs), a ScraperAPI→Jina→Wayback 3-layer fallback, an `archive/issuestop-history-backup/
data/<YYYY-MM-DD>/MetalsIssuesAndStopsReport.pdf` corpus (Jan–Jun, ~133 days), AND a Notion\n"Daily auto tracking" DB holding `[Delivery]` Activity-Note rows for dates past the archive.

**Daily-increment source discovery (the key win this session — "未来也要每天更新"):** when a chart's
data "stops at date X", do NOT assume the archive corpus is the live source. Trace where the sibling's
DAILY cron actually lands new data. The Comex daily cron (`07:45/07:50` core/slow) downloads the CME
delivery PDF and **uploads it as a Notion file-attachment + writes a per-firm `[Delivery]` Activity-Note
row** into the `Daily auto tracking` DB every day. That DB — not the archive — is the auto-updating feed.

**Notion DB-id 16-hex truncation trap (cost a 404):** context-summary / handoff notes often carry a
TRUNCATED 16-char Notion id (e.g. `2e047eb5fd3c80d8`). A real Notion id is 32 hex. Querying the short
form → `HTTP 404 Not Found`. Fix: `POST /v1/search {"filter":{"property":"object","value":"database"}}`
to list every DB the integration can see, match by title, and copy the FULL dashed id
(`2e047eb5-fd3c-80d8-9d56-e2c1ad066138`). Also use `/v1/search` to find which DB actually has the
`files` attachment column (schema: `GET /v1/databases/<id>` → look for `type:"files"`) — the analysis-
text DB and the raw-PDF DB are often DIFFERENT DBs.

**Per-firm 发/接 regex beats `(TOT N)`:** the Activity-Note `[Delivery]` segment is
`[Delivery] Gold: HSBC发66, BNP发21 / Deutsche接33, Wells接17 (TOT 90)`. Regex `\(TOT (\d+)\)` only
gives the AGGREGATE — useless for the bank-lens. Instead regex EVERY `([A-Za-z][A-Za-z0-9]*)(发|接)(\d+)`
(发=issued, 接=stopped), map the SHORT name → canonical bank (Jp→JPM, Wells→Wells Fargo, Bmo→BMO,
Sg→SG, Standard→Std Chartered, Rbc→RBC, Morgan→Morgan Stanley …), drop non-banks (StoneX/ADM/Cme/
Advantage/Marex/Dorman/Wedbush/Interactive/RJ/PTG/Plus500/Citadel/Phillip). Scan the whole DB once to
enumerate the real short-name set before finalizing the map. This yields the SAME per-firm granularity
as the PDF, so the two channels merge seamlessly.

**Dual-channel merge (archive打底 + Notion增量):** the two feeds OVERLAP and each has GAPS — the Notion
DB had a Jan→May hole (1/9 jumps to 4/10) because it wasn't running early; the archive is complete
Jan–Jun but stops. Merge per business_date with **archive-priority**: collect archive per-day per-firm,
then Notion ONLY for `date > archive_max_date`, union, then ISO-week aggregate. Result covered 31 weeks
(vs 21 archive-only) up to the latest delivery week AND auto-extends every day. Search pattern:
`search_files` the sibling repo for the metric name + read its `skill/references/*data-acquisition*.md`
before coding.

### Per-firm aggregation → dual-lens (all-banks vs core-makers)
When the source has per-firm granularity (CME issues/stops does), Chao's "挑大行" request means map
firm CODES → bank names and offer TWO lenses he can toggle: **全投行** (all ~17 investment-bank
seats, excluding pure futures brokers ADM/StoneX/Advantage/Marex/RJ OBrien/CME/PTG) and **核心做市商**
(~10 traditional LBMA gold/silver makers: JPM 661/HSBC 323/BNP 555/Scotia 435/Citi 880/Goldman 072/
BofA 624/Morgan Stanley 657/Std Chartered 332/Deutsche 099). Aggregate by **ISO week** (`week_monday`);
net = Σ(bank issued) − Σ(bank stopped), 正=净发货(交货/压价) 负=净接货(囤货/看涨). First probe the
corpus to RANK firms by (issued+stopped) volume before finalizing the name list — confirm the map
against real data, don't guess codes. Only金+银 per Chao's scope.

### Semantic-equivalent substitution (when the exact source is blocked)
Ask "what does this chart actually signal?" then find a first-party proxy for THAT signal.
Example: Michael Lynch's "bullion bank cumulative issues/stops" (CME-blocked) → the signal is
"are market-makers accepting delivery (stop=bullish) or issuing (压价)". First-party equivalent =
**CFTC COT commercial net position** for that metal (commercial 主体就是 bullion banks; net-short
widening = 加空压价 = Issued; net-short narrowing = 减空/被逼平 = Stopped). CFTC Socrata is
免key, backfillable to 1986, weekly. Build the proxy as the primary auto-updating section AND
optionally the blocked original as a labeled static reference below it, cross-referencing each other.

### Cross-market funding-cost equivalents (US SOFR ≈ JP TONAR ≈ EU €STR) + BoJ-daily-XLSX stitch
When building a US-vs-Japan (or any cross-market) comparison, the SAME concept has a DIFFERENT-named
first-party series per market — find the true equivalent before drawing a same-frame comparison, and
never leave one side "real" and the other "近似". Equivalences proven this session (basis-trade
deleverage panel):
- **Overnight funding cost**: US = **SOFR** (FRED, daily); Japan = **TONAR** (BoJ 無担保コールO/N物,
  the operating-target o/n rate; = the SOFR analog); EU = €STR.
- **Policy corridor**: US = **IORB** (ceiling) / **ON RRP award rate `RRPONTSYAWARD`** (floor). SOFR
  touching/crossing IORB = funding-blood-vessel squeeze (2019-09, 2020-03 preceded deleverage).
- **carry (per tenor)** = that tenor's yield − overnight funding: US = `DGS{2,5,10,30}` − SOFR (bp);
  JP = MOF JGB{2,5,10,30} − TONAR (bp). carry narrowing / turning negative = basis-trade profit gone
  = forced-deleverage trigger; short end (2Y/1M) inverts first.
- **BoJ TONAR has NO free full-history CSV** — but BoJ publishes ONE XLSX per business day at
  `boj.or.jp/en/statistics/market/short/mutan/d_release/md/{YYYY}/md{YYYYMMDD}.xlsx` (sheet `コール`,
  the `Average` row = TONAR%). The FIX for "no free daily series": scrape the yearly index page
  (`.../md/{year}/index.htm`, regex `md(\d{8})\.xlsx`), take the last ~N business-day files, `curl`
  each + `openpyxl.load_workbook(BytesIO(bytes), data_only=True)`, read the `Average` value + the
  report-date from the sheet title (`for August 18` → parse month+day). ~90 files ≈ 4 months of daily
  data — plenty for current judgement + 30-day sparklines. Loop with per-file timeout; skip failures.
  If NONE come back, degrade the JP carry to n/a honestly — NEVER substitute the policy-rate constant
  for the true o/n rate (Chao rule: 绝不用近似冒充). FRED's `IRSTCI01JPM156N` is monthly+lagged — not a
  substitute for daily TONAR. MacroMicro/Convex have it but the BoJ-XLSX stitch is the free daily path.
- The MOF JGB CSV (`_mof_jgb_yields(col)`) has ALL tenors: **2Y=col6, 5Y=col9, 10Y=col10, 30Y=col14**
  (col0=date). Use these for the JP carry lines, not just 10/30.

### Static monitoring TABLE → time-series warning PANEL (the design upgrade)
When Chao sends a screenshot of a STATIC monitoring TABLE ("表格 N: XX监控 当前值+状态灯") and asks to
build it into the dashboard, the right move is NOT to reproduce the table — it's to **升级成时序预警图**:
a static table is only a snapshot and can't show the approach-to-threshold that lets you act EARLY.
Turn "current value + status light" into "time-series lines + threshold red-line + a per-item status
MATRIX (current light + carry/value + a 30-day mini-sparkline)". Multi-panel联合展示 with an explicit
TRIGGER-CHAIN narrative (①→②→③ 共振 = high risk) and a "怎么看/怎么用" note per panel. Worked case:
user's basis-trade tables 2/3/5/6 → a 3-panel + matrix deleverage-warning section (① funding-cost
stress SOFR-vs-corridor+TONAR / ② carry space per tenor US-vs-JP / ③ trigger = MOVE vol × Fed reserves)
+ a synthetic lamp bar (funding/jp-funding/carry/vol lights). The lights are DERIVED from the real
series (SOFR−IORB gap, min carry bp, MOVE level, JP min carry bp), never hand-set.

### Reuse the existing multi-line / dual-axis panel renderer — construct a panel DICT, don't write new SVG
Before hand-writing SVG for a new multi-line or dual-axis chart, reuse `_stress_panel_svg(panel)` —
it already does dual left/right axes, per-point transparent `.tip-hit` hover circles, hi/lo/current/
median markers, and a right-side legend. New charts = just build the `panel` dict it eats:
`{id, title, subtitle, unit_left, unit_right, single_axis?, series:[{name,color,axis:"left"/"right",
dash?, width?, points:[{date,v}]}], source}`. `single_axis:True` for one-scale panels (all lines share
the left axis, e.g. a bp-carry panel). Set `dash:True` on the JP (低-freq / secondary-market) lines to
visually separate US-solid vs JP-dashed.周度降采样 (`_weekly_resample`) long series before feeding.
This cut a 3-chart section to constructing 3 dicts + one small matrix/sparkline helper.

### PITFALL: `patch` on a big multi-line f-string HTML/py function can silently delete a guard-clause or docstring quote
Editing dense f-string render functions or long fetchers with the `patch` tool, the old_string can span
past what you intended and drop an adjacent `if not X: return '<p class="empty">…</p>'` guard, or the
OPENING `"""` of a docstring — both happened this session (caught only by the auto-lint `SyntaxError:
invalid decimal literal` and a read-back). After ANY patch to such a function: (a) trust the auto-lint
error if it fires — fix immediately; (b) read back the 5 lines around the edit to confirm the guard
clause / docstring quotes survived; (c) run `python3 -c "import ast; ast.parse(open(f).read())"` on
BOTH dashboard.py and external_data.py before building. Never assume a "success" patch left the
surrounding structure intact.

## 1. fetch function → `src/external_data.py`
Insert before `def fetch_fiscal_news`. Copy the shape of `fetch_bis_gold_swaps` (seed-JSON reader)
for static refs, or `fetch_silver_bank_positions` / `fetch_gold_exports` (live fetch + cache
fallback) for auto-updating. MANDATORY cache-fallback contract (Chao 铁律 抓不到不覆盖成空):
```
cached = _load_cache()
fresh = <fetch>            # e.g. _fred_series("IEAXGG") or cot.fetch_history("silver", weeks=520)
if not fresh and cached and cached.get("points"):
    out = dict(cached); out["status"] = "缓存"; return out
if not <data>: return {"status":"未获取", ...}
# ... compute, then write cache, return {"status":"ok", ...}
```
- Reuse existing fetchers: `from fetchers import cot` gives `cot.fetch_history(metal, weeks=N)`
  (full COT commercial history). `_fred_series("<ID>")` = free fredgraph.csv puller, no api key.
- Return dict keys the render fn will read: status, as_of, source, source_url, unit, points, +
  computed extremes (latest/peak/base/surge_x).

## 2. seed / cache data → `data/<name>.json`
For static refs, hand-write the JSON with `points`, `annotations` (color-coded), `source`,
`source_url`, `update_nature`, and a `note`/`title_note` documenting why it's static or relabeled.
For live sources, the fetch fn writes this file itself on first successful run — probe it once via
`.venv/bin/python -c "..."` to confirm it lands before wiring the UI.

## 3. render function → `src/dashboard.py`
Insert after the sibling section's render fn (e.g. after `_bis_gold_swaps_html`). Copy that shape.
- Line charts: call `_yield_curves_svg({key: {status,name,color,dash,points:[(date,val)],latest}}, yunit=...)`.
  One key per line. `dash:"6,4"` for the dashed "hand-transcribed/estimated" look.
- Guard: `if not X or X.get("status") in (None,"未获取") or not X.get("points"): return '<p class="empty">…抓取中…</p>'`
  (graceful degradation — a blocked/limited source must NOT break the whole build).
- Include a `<div class="cust-how">` "如何看" block + a "数据诚实说明" block naming the source and any caveats.
- Morandi palette; signal colors 绿#2e9e5b/黄#e0a92e/红#d64545; freq badge (freq-d/w, or a custom ⚪静态参考).

### X-axis label overlap on long-span charts (Chao flagged "横坐标都互相覆盖了，看不清")
`_yield_curves_svg` is the SHARED chart helper (7+ sections use it). Its old X-axis logic labeled
"every odd month" — fine for a 1yr daily chart (~6 labels) but catastrophic for 10yr weekly (522pts)
or 27yr quarterly (109pts) data → 60+ labels overprinting into an unreadable smear. Fix once in the
helper, all charts benefit:
- Target ~8 evenly-spaced labels: `step = max(1, round(n / 8))`, iterate `range(0, n, step)` + force
  the last index so the newest point is labeled.
- Compute span: `long_span = (date.fromisoformat(all_dates[-1][:10]) - date.fromisoformat(all_dates[0][:10])).days > 3*365`.
  Long-span → show YEAR only (`d[:4]`); short-span → year-month (`d[:7]`).
- Dedup consecutive identical labels (`if lbl == _prev_lbl: continue`) — otherwise the forced-last
  index duplicates the trailing year (e.g. 2026/2026).
When you touch any shared rendering helper, re-verify EVERY consumer, not just the new section
(programmatic count: `re.findall(r'<text x="[\d.]+" y="27[0-2]', svg)` → expect ≤~10 per chart, no dups).

### Multi-frequency series on one chart — build the axis from the HIGH-freq series (Chao flagged "最新一周没数据")
When two series of DIFFERENT update cadence share a chart (daily index + weekly fund-flow, daily price
+ monthly holdings), building the time axis from the LOW-freq series silently TRUNCATES the high-freq
series' latest span → the chart looks like "no data for the last N days" when the data is actually
complete. This was a real bug: 日经225 (daily, to latest close) × 外资 foreign-flow (weekly, lags 1–2wk)
used the weekly axis → the newest ~10 days of Nikkei got chopped, and Chao spotted it instantly.
**Rule: the time axis = the HIGH-freq series' full date range; project the LOW-freq series onto it**
(each weekly bar lands at its own date, the right edge naturally goes blank where the lagging series
hasn't reported). Add a red dashed "数据截至 XX" line + last-point value label so the low-freq lag is
shown honestly, not hidden. The low-freq lag is a REAL publication delay — annotate it, never fabricate-fill.

### Data-freshness audit — "能拿到最新数据的图都要显示到最新" (Chao standing requirement)
Chao wants every chart to display through its source's true latest date. Audit method: for each fetcher,
compare ① data's actual latest date vs ② the date the chart draws to. Three verdicts:
- **data newer than drawn** = alignment/range bug → fix the render to draw to latest.
- **source itself lags** (monthly 30–60d, quarterly 100+d = SEC/central-bank/Comtrade real release
  cadence) = NOT a bug → just carry a "最新（YYYY-MM-DD）" label so it's visibly honest.
- **code capped the pull** (hardcoded end date / stale generator not re-run) → remove the cap / re-run.
To decide "already at source latest?", CHECK the source's official newest period (e.g. FRED series page),
never assume it should have更新. Most Eco lag-charts (gold exports IEAXGG quarterly, HF-leverage Form-PF
quarterly, BIS annual, India-silver Comtrade monthly, century-yield GS10 monthly) are at source-latest —
their lag is release cadence, not a defect, and they already print a 最新() label. Keep a reusable
`scratch/freshness_audit.py` that walks the fetchers and prints data-latest vs drawn-latest per chart.

## 4. wire generate() → `src/dashboard.py`
- Add param to `def generate(... , <name>=None):` signature.
- Add `<name>=_<name>_html(<name>),` to the `.format(...)` dict.
- Add the section HTML template block `<div class="part-title" id="sec-<name>">…</div><div class="card">{<name>}</div>`
  next to the topically-adjacent section.

## 5. sidebar grouping → `src/dashboard.py` GROUPS
Add a keyword that appears in the new section's part-title to the right group's `match: [...]` list.
Existing groups: 核心风险扫描 / KOL观点 / 流动性与央行(黄金/央行/BIS主题) / 国债流动性观测 /
能源与大宗(石油+贵金属) / 财政政策 / 日本市场 / 机构与政要持仓. Match string must be a substring
of the actual rendered title (the sidebar JS matches on title text).

## 6. wire build_dashboard.py
- Add a `try/except` fetch block (copy an adjacent one) that calls `ed.fetch_<name>()` and prints a
  one-line status log.
- Add `<name>=<name>,` to the `dashboard.generate(...)` call.
- NOTE: cron needs NO change — the daily cron prompt calls build_dashboard as a module, so any fetch
  wired into build_dashboard.py is picked up automatically. (Same for market_breadth/BIS.)

## 7. verify (programmatic + VISUAL — both required)
See `references/chart-visual-qa-and-integrity-verification.md` for the full loop. Programmatic
checks prove the section BUILT; they do NOT prove it's legible or honest. Minimum bar before rebuild:
(a) standalone-render the new section to `/tmp/newsec.html` and run a `browser_vision` pass with
enumerated questions (catches invisible-but-emitted elements, label collision, missing axis —
all of which pass every programmatic assertion); (b) run the simulated-outage test to prove the
fetcher degrades to `<p class="empty">…未就绪</p>` with zero fabricated numbers.
```
.venv/bin/python -m src.build_dashboard      # background + notify; ~4min full run; watch the status log line
# then, on dashboard/index.html AND docs/index.html:
python3 -c "import re; h=open('dashboard/index.html',encoding='utf-8').read(); \
 seg=h[h.find('sec-<name>'):h.find('<next-sec-id>', h.find('sec-<name>'))]; \
 print('pts:', sum(len(p.split()) for p in re.findall(r'points=\"([^\"]+)\"', seg))); \
 print('key values present:', '<expected number>' in seg, 'no empty:', 'empty' not in seg)"
```
Confirm both `dashboard/index.html` and `docs/index.html` contain `sec-<name>` (docs/ is the public
Pages source and build writes both). Screenshot via browser + MEDIA: to Chao if vision analysis 400s.

## 8. commit + push (background + notify) (grep for internal domains / plaintext keys — public repo, must be clean).
`git add <specific files incl. dashboard/index.html + docs/index.html + data/*.json>`,
`git commit --no-gpg-sign -m "..."` (English msg, NO parens in message — redactor chokes on `()`),
`git push origin main` (origin = personal public Curarpikt0000). Foreground commit often times out →
run commit+push in ONE background command with notify_on_complete.

### Cross-repo pipeline: promote the builder out of scratch/, commit the JSON in the SIBLING repo
When the data pipeline lives in / reads from a SIBLING project (e.g. the COMEX issue/stop aggregator
reads `~/Projects/Comex-Daily-AI-Report/archive/` and writes `Comex-Daily-Report/data/*.json` that the
Eco dashboard then reads cross-project), two commits are needed and one gotcha bites:
- `scratch/` is GLOBALLY gitignored (Chao 铁律). A pipeline script written there will NOT commit.
  `cp scratch/<name>.py <sibling-repo>/src/<name>.py` before committing so it actually enters git.
- Commit the generated JSON in the SIBLING repo's `data/` (data归属跟着采集脚本走), and commit the
  fetch/render/wiring in the dashboard repo separately. Two repos, two `git push` (both personal public).
- The dashboard fetch fn reads the sibling JSON by ABSOLUTE path (`/home/user/Projects/<sibling>/data/...`);
  keep the cache-fallback contract so a missing sibling file degrades gracefully, never errors the build.

## GitHub Pages deploy lag (Chao asks "是不是还没更新")
After push, `curl -sI https://curarpikt0000.github.io/.../` → check `last-modified`. Pages rebuilds
1–5 min after push. If `last-modified` predates your commit and `curl <url> | grep <section-title>`
returns 0, it's just deploy lag, not a bug — code is correct, git is synced. Tell Chao to wait +
Ctrl+Shift+R hard-refresh. Re-`curl` after ~60s to confirm the rebuild landed.
`sleep 60 && curl` in one command hits the terminal timeout — run them as separate calls.

## Every chart MUST have a periodic-update mechanism (Chao standing requirement)
Chao asked to "确保我们的每一个图都有周期性的更新机制". Audit method — classify each `ed.fetch_*`
in build_dashboard.py by data-source type; the update mechanism differs:
- **Live-API fetches** (FRED / CFTC Socrata / US Treasury fiscaldata / EIA / IMF SDMX / MOF / JPX /
  OFR / 东财 push2his): auto-refresh EVERY daily run, because the 11:00 cron calls build_dashboard
  as a module and re-invokes all fetches. NO extra wiring needed — this is the majority.
- **Seed-JSON / override / no-API sections** (fiscal_news, bis_gold_swaps GATA monthly, COMEX silver
  Lynch static ref, money_supply JP/CN override): the JSON does NOT self-update. Each needs an
  explicit update step IN the daily cron agent prompt (web_search/web_extract → append/update the
  JSON, 只增不改历史, 抓不到只更新"最后检查"日期, 绝不编造).
- Verify coverage by grepping the daily job prompt for each non-API section's keyword — every one
  must be mentioned. When adding a new non-API section, ALSO add its check to the daily cron prompt.
- Editing the daily cron prompt safely: it's a giant escaped single-line JSON string. Do NOT hand-edit
  the `\uXXXX` escapes. Write a small idempotent `.venv/bin/python` script that: backs up jobs.json,
  loads it, finds the job by `job_id`, checks for a MARKER string (skip if present), appends the new
  step text to `prompt`, writes back with `json.dump(..., ensure_ascii=False, indent=2)`. Run it via
  terminal (execute_code is blocked for cron safety). Re-run once to confirm idempotent SKIP.
- **Redactor-poisoned literal in jobs.json (verify, don't blindly rewrite):** the daily-cron prompt on
  disk can already contain an `ANONYMIZED_PERSON_..` literal baked into a marker string (this session:
  `[ANONYMIZED_..-SILVER-CHECK]` where the true marker was `[LYNCH-SILVER-CHECK]`). It got there from an
  earlier display-layer write-through. When your idempotent editor runs, grep the loaded prompt for
  `ANONYMIZED` and restore the true token from a known-good source (memory / the code the step invokes).
  Confirm it's pre-existing (check the .bak you just made) — a python `json.load` reads DISK truth, so if
  the .bak already has it, it's historical, not your doing; fix it anyway so the marker matches.

## Consuming another agent's / another profile's data feed
When Chao says "another agent already produces X daily, just read the latest" (e.g. A/D line data
in `Economic-Dashboard/data/ad_line/` via cron job `334572d3e1a7`), VERIFY the path/repo actually
resolves from THIS session before wiring a reader:
- Check local path, then `api.github.com/repos/<owner>/<repo>/contents/<path>` for the public copy.
- A cron `job_id` Chao names may belong to a DIFFERENT Hermes profile (only the current profile's
  jobs show in `cronjob action=list`). If the job isn't in the list and the data dir doesn't exist
  locally and the repo 404s anonymously (private or different owner), that feed lives in another
  profile — you cannot read it from here. Do NOT hardcode an unresolvable path or fabricate a reader.
  Report the honest blocker and ask Chao for the absolute path or correct owner/repo before proceeding.
- Never `git pull` / touch another project's working tree to "help" — UNLESS this session IS the
  designated read-only consumer AND the tree is a stale clone with no local-unique commits (see below).

### Success path: this session as the read-only consumer of a sibling repo's daily cron output
When the feed DOES resolve (repo exists, path present), wire a robust daily-syncing reader. Realized
this session for A/D 腾落线: `Curarpikt0000/Economic-Dashboard` `data/ad_line/ad_line_sp500_history.json`
(SP500 501-ticker advance/decline, cron `334572d3e1a7`). A prior "404" can be transient — re-try
`git fetch` before concluding the repo is private/unreachable.
- **Stale-clone reset is safe iff no local-unique commits.** The local `~/Projects/Economic-Dashboard`
  was stuck with an `UU docs/context-log.md` merge conflict blocking `git pull`. Before `git reset --hard`,
  PROVE it's safe: `git log --oneline origin/main..HEAD` MUST be empty (no commits you'd lose) — a pure
  behind-origin read-only clone. Then `git reset --hard origin/main` clears the conflict + fast-forwards.
  This is the ONE case where touching another project's tree is OK: you own nothing in it, it's a
  consumer mirror, and you verified zero local-unique work. Do NOT reset if `origin/main..HEAD` is non-empty.
- **Bake the sync INTO build_dashboard.py so it self-updates daily** (no cron-prompt edit needed):
  in the fetch's try-block, `subprocess.run(["git","-C",<sibling_repo>,"fetch","origin","main","--quiet"])`
  then `reset --hard origin/main --quiet` (both `check=False`, wrapped so a sync failure falls back to the
  existing local file, never errors the build), THEN read the JSON. Because the 11:00 cron re-invokes
  build_dashboard, the sibling's latest daily data is pulled every run automatically.
- **Reuse the existing render/signal plumbing by matching field names.** The A/D fetch returned the
  market_breadth-compatible shape (`spy_points`=cumulative A/D line, `ratio_points`=advance_pct) so the
  existing double-line-normalized SVG + `run.py` ad_line signal injection worked with minimal new code.
  When replacing a proxy with the real thing, make the real fetch PRIMARY and demote the proxy to a
  fallback (`if real.status==ok use it; else try proxy; else keep old value`) — never delete the proxy,
  it's the degrade path. Keep both sections visible (real A/D as the main chart, RSP/SPY proxy below as
  supplementary) rather than ripping the old one out.

## Vetting an analyst's chart cadence (for "每天看看他有没有更新" requests)
When Chao wants daily monitoring of a named analyst's chart (e.g. Michael Lynch @DtDS_WSS):
- Their chart is usually a PNG embed on Substack/X with NO API and NO raw series. The cron agent can
  only read NUMBERS THAT APPEAR IN ARTICLE BODY TEXT/captions — it CANNOT read values off the PNG.
- So the honest "auto-update" is best-effort: web_extract their `/archive`, compare newest article
  date vs the seed JSON's `as_of`; if a new article has explicit body numbers → append an anchor;
  if new article but numbers only in the image → update only a "最后检查 YYYY-MM-DD: 有新文章无正文数字"
  note; if no new article → no change. Tell Chao this limitation upfront; never fabricate from a PNG.
