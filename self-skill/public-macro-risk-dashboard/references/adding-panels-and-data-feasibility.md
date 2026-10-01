# Adding a new panel + data-source feasibility gate

Session-distilled operating detail for extending the Eco-and-Volatility-Checker
dashboard (repo Curarpikt0000/Eco-and-Volatility-Checker). Load when adding a
NEW indicator/panel, changing a chart's date range, converting chart type, or
when a user asks for a new metric whose data source you haven't verified.

---

## 1. Data-source feasibility gate — DO THIS BEFORE PROMISING OR BUILDING

Chao's project rule: **only free/public sources, no keyed commercial APIs, and
never fabricate a proxy to stand in for a series you can't actually get.**
Before you say "I'll build it" or design a fetcher, PROVE the data is free and
accessible. Run real probes, not guesses.

Checklist when a new indicator is requested:
1. Is there a free FRED series? (`/fred/series?series_id=...` → check it exists
   AND check `frequency` AND pull a window to confirm real values.)
2. Is it a Treasury/SEC/CFTC/BIS/OFR official free endpoint?
3. If it's a market/credit derivative (CDS, single-name spreads, options
   surfaces): assume **structurally paywalled** until proven otherwise. Probe
   the actual endpoint with the actual key before believing a pricing table.

**Hard finding (single-name corporate CDS, e.g. Oracle 5Y):** there is NO free
daily source. All 8 probed routes failed —
- FRED: only rating/index OAS (BAMLC0A0CM / AAA / BBB), no single names.
- FINRA TRACE free Query API: only Market Breadth/Sentiment aggregates; per-bond
  trades require WRDS (paid) or FINRA paid licensing.
- FMP: no CDS / single-name bond-spread endpoint at all.
- BondbloX/BondEvalue: paid exchange app.
- **Finnhub free tier: `/bond/profile`, `/bond/price`, `/bond/tick`,
  `/bond/yield-curve` all return `403 "You don't have access to this resource"`
  even though the pricing table shows a "Free" checkmark. The pricing-table
  checkmark is MISLEADING — bond endpoints are paid-tier only. `/quote`,
  `/stock/metric`, `/stock/profile2` work on free; `/stock/candle` is 403 too.**
- GitHub/Kaggle datasets, X/blog/YouTube: only screenshots of Bloomberg/JPMorgan
  charts, no downloadable raw series.
- Bloomberg / Markit / S&P: paid (this is what Apollo etc. use).

Correct behavior when data is paywalled: **say so honestly, do NOT build a
proxy chart that impersonates the real series.** A stock-price/implied-vol proxy
labeled as "CDS" violates Chao's "数字必可溯源 / 绝不臆测" red-line and is worse
than no chart. Offer the only real path (user exports CSV from their Bloomberg
terminal into `data/`, you build a cron that reads it) and stop.

Verification standard Chao expects: real news anchors to sanity-check any credit
number you DO get (e.g. Oracle 5Y CDS peaked ~190–212bp Apr 2026, IG index ~53bp).

**Confirmed-working FREE sources added since (probe once, reuse forever):**
- **EIA API v2** (US energy: oil/gas stocks). Needs a FREE key — register at
  eia.gov/opendata/register.php, arrives by email in ~1 min. Store as `EIA_API_KEY`
  in `.env` (gitignored). This is a KEYED-BUT-FREE source and is allowed (not a paid
  commercial API). Weekly petroleum stocks route:
  `https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key=<K>&frequency=weekly&data[0]=value&facets[series][]=<SERIES>&sort[0][column]=period&sort[0][direction]=asc&length=5000`
  - Cushing crude stocks: `W_EPC0_SAX_YCUOK_MBBL` (thousand bbl; ÷1000 → million bbl). Tank-bottom red line ≈ 20M bbl.
  - SPR: `WCSSTUS1` (thousand bbl, 1982-present). Operating red line = 300M bbl (Amos Hochstein).
  - ★ FRED does NOT carry these EIA crude-INVENTORY series — its search returns only oil
    PRICES (DCOILBRENTEU / DCOILWTICO). Don't guess FRED IDs like WCESTUS1; they don't exist
    on FRED. Prices → FRED; inventories → EIA.
  - ★ Shell-quoting trap: the `facets[series][]` brackets + single quotes break bash
    (`unexpected EOF matching '`). Build/test EIA URLs from `.venv/bin/python3 -c`, not curl.
  - Helpers in external_data.py: `_eia_series(series_id, start)` (reads key from env or .env,
    returns [(period,value)] asc) and `_fred_series(id, start)` (full-history fredgraph CSV,
    skips '.' rows) — reuse both for any new EIA/FRED series.

**US equity price/breadth (RSP-SPY etc.) — East Money native API (probed 2026-08):**
- akshare (installed 1.18.81) wrapper is BLOCKED by East Money (`Connection aborted /
  RemoteDisconnected`), but the raw East Money `push2his` API works via plain `requests`.
  Bypass akshare and call it directly:
  `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=<MKT.CODE>&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=YYYYMMDD&end=YYYYMMDD`
  - `secid` market prefix: `107`=Arca/AMEX (SPY=`107.SPY`, RSP=equal-weight S&P=`107.RSP`),
    `106`=NYSE, `105`=NASDAQ. `klt=101`=daily.
  - `klines` rows are `"date,open,close,high,low,vol,amount,pct"` → parse close = index 2.
  - Symbol search: `https://searchapi.eastmoney.com/api/suggest/get?input=<KW>&type=14`.
  - ★ East Money RATE-LIMITS sustained/high-freq requests (curl AND requests return empty,
    cools off in tens of minutes). A low-freq daily cron generally gets through, but you MUST
    add a **cache-fallback**: on fetch failure read the last successfully-saved
    `data/market_breadth.json` and return it (never overwrite real values with empty) — same
    "抓不到保留旧真值" rule as the notion upsert skip_none guard.
- **NYSE A/D advance-decline line has NO free programmatic source.** Stooq = full-site JS PoW
  wall (curl blocked); Yahoo A/D symbols (`^ADLINE`/`^NYAD`/`^ADD`) all 404 and Yahoo history
  download needs a Gold subscription; FRED has no daily NYSE advancing/declining-issues series;
  Finnhub breadth is paid tier. → Use **RSP/SPY (equal-weight ÷ cap-weight) ratio as a market-
  breadth proxy**: ratio falling = a few mega-caps leading while most stocks lag = same meaning
  as an A/D top-divergence, but continuous, quantifiable, chartable, and reproducibly judged
  (SPY makes new lookback high while RSP/SPY does NOT = divergence=True). This REPLACES the old
  boolean `ad_line` (source="search", unit="布尔", warn/trigger=None) which showed "顶背离/达成"
  with NO chart and NO stored evidence — Chao rightly challenged "无数字无图怎么判断达到阈值".
  A source="search" boolean with only `{value:true}` and no evidence is a red-line violation.
- **moomoo OpenD gateway:** `futu-api` Python SDK installs cleanly via pip (`.venv` has 10.9),
  but the OpenD gateway binary's official download page generates its `.tar.gz` link entirely
  via JS + a market-selection popup — a headless browser CANNOT extract the real direct link
  (heavy anti-automation). → Ask the user to download it locally and send the file, or paste the
  real link. OpenD emitting quotes ALSO requires the user's moomoo login + US market-data
  entitlement + possibly an SMS code; the agent cannot log in on their behalf.

## 2. FRED "series exists but starts at zero" trap

`observation_start` in the series metadata is NOT the first real data point. A
series can be created years before it carries real values and back-fill the gap
with `0.0`.

**Worked case — WMTSECL1 (foreign official custody of marketable UST):**
metadata `observation_start = 2002-12-18`, but the first 237 weekly points
(2002-12 → 2007-06, ~19% of the series) are literally `0.0`. First real non-zero
value is **2007-07-04 ($1.21T)**.

Consequence: setting a "full cycle" chart to start at the nominal series start
draws a long flat line pinned to zero, then a jump — which visually LIES
("foreign officials held ~nothing 2002-2007" when really "no data collected
yet"). This is exactly why the original chart was pinned at 2008.

Fix: **set the chart start to the first real non-zero value**, and label it with
that year. Probe head values before choosing a start:
```python
vals = [(o["date"], o["value"]) for o in obs if o["value"] not in (".", "")]
first_nonzero = next(x for x in vals if float(x[1]) > 0)
```
When the user asks for "2000 to now" but the free source only starts at 2007,
tell them the real floor and default to the honest earliest-real-data start —
don't relabel 2007 data as "2000".

## 3. The daily-cron inline-generate() trap (CRITICAL for any new panel)

This dashboard is generated in TWO places that DRIFT:
- `src/build_dashboard.py` — the clean orchestration path you edit and test.
- the **daily cron** (`eco-vol-01-daily-scan-report`) has its OWN inline
  `python -c "...dashboard.generate(...)"` one-liner in its prompt (step 6),
  with the fetch calls and the full `generate(...)` kwargs hand-written.

If you add a new panel and only wire `build_dashboard.py`, the cron-generated
dashboard **silently omits the new panel every day** (your manual build looks
right; production loses it). This session found the cron inline-generate was
ALSO missing `maturing_treasury=` — a pre-existing silent omission.

Whenever you add/rename a `generate()` param, you MUST patch it into BOTH:
1. `src/dashboard.py` signature + render dict + template block.
2. `src/build_dashboard.py` fetch block + `generate(...)` call.
3. the cron job prompt's inline `import ...`, the fetch statements, AND the
   `generate(...)` kwargs (edit `~/.hermes/cron/jobs.json` via a venv-python
   script — execute_code is disabled in cron mode; patch string-replace with
   `assert old in prompt` guards, then read back and grep the new kwargs).

## 4. New-panel add recipe (full stack), modeled on the BIS section

For a new panel like "BIS reports" (Quarterly Review summaries + button + own page):
1. **Fetcher module** `src/<name>.py` with a single JSON store
   `data/<name>/reports.json` (unify — do NOT scatter one-file-per-item; see
   handover.md storage-consistency rule). Functions: `sync_*` (idempotent
   discover, never overwrite existing summaries), `upsert_summary`,
   `latest_*` (for the dashboard section), `all_*` (for the standalone page),
   `build_standalone_page` (writes `docs/<name>/index.html`).
2. **Dashboard section render fn** in `dashboard.py` returning the summary +
   a button reusing the existing `.part-title-flex` + `.kol-dash-btn` classes
   (Chao's established button pattern → links to the standalone page).
3. **Standalone page** at `docs/<name>/index.html`, Morandi palette, "← 返回"
   button, published at `https://curarpikt0000.github.io/<repo>/<name>/`.
4. **Wire** generate() signature + render dict + build_dashboard fetch + the
   cron inline (see §3).
5. **Sidebar grouping**: add the panel's title keyword to the right group's
   `match` array in the collapsible-sidebar JS (`GROUPS`).
6. Backfill past-year content with **parallel subagents** (one PDF each,
   toolset `web`, extract via `web_extract` on the PDF URL, return JSON points),
   then main-thread `upsert_summary` each. Only real doc content — mark pending
   / "待更新" when a source can't be read, never invent points.

## 5. Reusable bar-chart SVG

When Chao asks to convert a line chart to bars: MSPD (and most official monthly
reports) are month-end only — there is no daily/weekly granularity, so "past
year" = ~13 monthly bars is the honest max resolution; state that. The
`_bar_chart_svg(points, ...)` helper (last bar highlighted darker + value label,
y-axis floored just below min to exaggerate differences, x-labels thinned to
~6, Morandi green) is the pattern; keep the full-cycle line as a reference chart
below the bars rather than deleting the long-trend view.

**Threshold / operating-red-line charts (added for the oil-inventory section):**
two reusable SVG helpers in dashboard.py for any "value vs an operating-limit" series —
- `_oil_line_svg(pts, redline=, redline_label=, zero_line=, rising_good=)` — line with an
  optional RED DASHED threshold line (`#d64545`) and/or a 0 baseline; latest point dot+label;
  trend auto-colored via `rising_good`.
- `_oil_bar_redline_svg(pts, redline=, redline_label=)` — weekly bars where any bar BELOW the
  redline is dyed red (`#d64545`).
Despite the `_oil_` prefix these are generic threshold-chart primitives — reuse them for any
future "breached an operating limit" panel, not just oil.

## 6. Chao working-style reminders reconfirmed this session
- "把 X 改成柱状图" / "改成 2000 至今" = a specific, already-agreed edit; just do
  it, don't re-litigate — but DO surface an honest data floor if the ask exceeds
  what the source supports (offer the nearest real option + default to it).
- Extremely terse approvals ("A", "可以") = authorization to proceed multi-step.
- When the user says "撤回刚才的话 / 你自己 run 就可以" they are removing a
  blocker task from THEM, not asking you to keep pushing — accept the stop.
- Screenshot deliverables via `MEDIA:<path>` when vision backends 400 — verify
  the chart programmatically (DOM `<rect>` count, titles) and let Chao eyeball.
