# Adding chart panels + free data sources to the Eco-and-Volatility dashboard

Session-specific playbook for extending the trader-screen dashboard with new chart
panels, replicating paywalled research charts with public proxies, and the
code-level pitfalls of `src/dashboard.py` (a giant `.format()` HTML string) and
`src/external_data.py` fetchers. Distilled from the 2026-08 build (Morgan Stanley
treasury-stress four-panel figure, OFR FSI, left index sidebar, TIC EU aggregation,
custody 2008 chart).

## The wiring pattern (every new panel follows this)

`fetch_X()` in `external_data.py`  →  `build_dashboard.py` calls it + passes the
result into `dash.generate(...)`  →  `generate()` signature gains a kwarg  →
`generate()`'s `.format(...)` call maps it to `_X_html(...)`  →  a template slot
`<div class="card">{X}</div>` in the body  →  optional CSS block.

Checklist to add ONE panel end-to-end (miss any and it silently renders empty):
1. `external_data.py`: write `fetch_X(years=N)` returning `{..., "status": "ok"|"未找到"}`.
   Follow the house pattern: **带 key FRED API (`fetchers.fred.fetch_fred_history`)
   优先, curl `fredgraph.csv` 回退** (the CSV endpoint times out intermittently in
   this VM's Python subprocess; the keyed API is stable). Weekly-resample daily
   series to reduce noise (`_weekly_resample`, Friday as-of).
2. `dashboard.py`: write `_X_html(x)` (+ an SVG helper if it's a chart) + a CSS block.
3. `dashboard.py`: add `X=None` to `generate()` signature AND `X=_X_html(X)` to the
   `.format(...)` call AND a `{X}` template slot in the body HTML.
4. `build_dashboard.py`: `X = ed.fetch_X() or {}`, pass `X=X` into `dash.generate`,
   and (if persisted) `json.dump` to `data/<sub>/X.json` + call `ed.write_X_notion(X)`.
5. `config.py`: add `"X": ENV.get("DB_X","")` to `NOTION_DB` if it writes Notion.
6. Notion DB: write a **small incremental** build script (see below) — never re-run
   the monolithic `build_notion_dbs.py`, it overwrites `.env` keeping only 3 DBs.
7. Regenerate with `python -m src.build_dashboard`; verify with a `python3 -c`
   grep of the produced `dashboard/index.html` for the new title / CSS class /
   `<polyline>` count before committing.

## Replicating a proprietary / paywalled research chart (MS BrokerTec case)

When the user hands a chart from Morgan Stanley / Goldman / etc. and says "recreate
with our data over N years":
- **Ask FIRST whether the underlying data is publicly available.** MS BrokerTec
  intraday bid-ask spread and weekly DV01 volume are **proprietary, paywalled, no
  free source** (confirmed by search — BrokerTec cash-Treasury micro data is
  institutional-only). Do NOT fabricate. Do NOT silently substitute.
- Offer the honest options via `clarify`: (a) recreate only the panels whose data
  is public; (b) substitute **theme-aligned public proxies** for the paywalled
  panels, each **explicitly labelled** "⚠ 非 BrokerTec 原指标 / public proxy"; (c)
  user supplies the paid data.
- Chao chose (b). The proxy mapping used (all FRED, 3y, weekly-resampled):
  - Panel ① Yields+Volatility (EXACT match to MS): `DGS10` + `DGS2` + **real MOVE
    index** (see below).
  - Panel ② "market stress proxy" (replaces BrokerTec bid-ask): `THREEFYTP10`
    (10y term premium, NY Fed ACM) + `BAMLC0A0CM` (IG corp OAS).
  - Panel ③ "curve & credit stress" (replaces BrokerTec DV01 volume): `T10Y2Y`
    (curve slope) + `BAMLH0A0HYM2` (HY OAS).
  - Panel ④ (Chao added) OFR Financial Stress Index (see below).
- The `note` field of each panel is HTML and rendered UNescaped in the dashboard —
  use it for **per-metric explanation** (什么/怎么看/怎么用) when the user asks to
  annotate; put ⚠ proxy disclaimers there.

## Free data sources discovered this build

- **MOVE index (ICE BofA bond-vol, the "bond VIX")**: FRED has NO free MOVE series.
  Get real daily history via **`yfinance` ticker `^MOVE`** (installed in `.venv`).
  Gotcha: `df["Close"]` may be a MultiIndex DataFrame — take `.iloc[:,0]` if it has
  `.columns`, then `.dropna()`. First Yahoo chart-API attempt returned only 1 point;
  `yfinance.download(start=...)` returns the full multi-year series. Fall back to
  `[]` (never fabricate) if unavailable.
- **OFR Financial Stress Index**: official free CSV, daily, back to 2000:
  `https://www.financialresearch.gov/financial-stress-index/data/fsi.csv`
  Columns: `Date, OFR FSI, Credit, Equity valuation, Safe assets, Funding,
  Volatility, +3 regional`. Reading: 0 = historically-normal stress; >0 = elevated;
  <0 = calm. urllib first, curl fallback (both with a browser UA).
- **TIC "EU" holdings of US Treasuries**: TIC Major-Foreign-Holders has **no EU
  aggregate row** — sum eurozone member rows month-by-month. Member row names in
  `mfhhis01.txt`: `Germany, France, Italy, Netherlands, Belgium, Luxembourg,
  Ireland, Spain, Finland` (+ early `Belgium-Luxembourg` combined row). Match rows
  by EXACT name against a member set (avoid substring hits on footnote text).
  **Belgium includes Euroclear third-party custody** — the EU aggregate is inflated
  and trend-heavy; label this caveat in the panel note. The file covers **2000–2025**
  so it serves both the near-10y window AND a 2008-onward long-history chart from
  one fetch (emit both `series` = near-N-years and `series_long` = 2008+).
- **Foreign official custody of USTs 2008-history**: FRED `WMTSECL1` (weekly, Wed
  as-of) reaches back to 2008-01 (~972 weekly points). Emit `history`,
  `history_long`, `history_2008` in one fetch by calling the history helper with
  three different `start=` values.

## Left-sidebar section index for a long dashboard

Chao asked for a left index bar because the page got too long. Zero-touch pattern
(don't hand-add ids to every section):
- HTML shell after `<body>`: a `<nav class="sidenav" id="sidenav">` with an empty
  `<div id="sidenav-links">` + a `<button id="sn-toggle">☰</button>`.
- JS at the end of the script block: scan `document.querySelectorAll('.part-title')`,
  assign each `id="sec-N"`, build a link (short label = text before `·`/`（`/`(`,
  truncated), `scrollIntoView({behavior:'smooth'})` on click, and a scroll-spy that
  toggles `.sn-active` on the current section. Future panels are auto-indexed.
- CSS: `.sidenav` fixed 230px sticky; `@media (min-width:1101px){ body{padding-left:230px} }`
  to shift the container; `@media (max-width:1100px)` hides it behind the ☰ toggle.
- `.part-title { scroll-margin-top: 16px; }` so anchor jumps aren't hidden under a
  fixed header.

## CRITICAL: dashboard.py is one giant str.format() — brace & backslash traps

`generate()` builds the whole page from a `"""...""".format(**kwargs)` string, so:
- **Every literal `{` / `}` in CSS AND in `<script>` JS must be DOUBLED** (`{{` `}}`).
  A single unescaped brace → `KeyError`/`IndexError` at format time or a mangled
  page. This bit twice this session (the sidebar JS + new CSS blocks). After editing,
  ALWAYS run `python -m src.build_dashboard` — a clean run proves the braces balance.
- **Python 3.11 f-strings can't contain a backslash inside the expression part.**
  `f'...{" x=\"5\"" if cond else ""}...'` → SyntaxError. Fix: compute the string in
  a plain variable first (`leg_dash = ' stroke-dasharray="5,3"' if ... else ""`),
  then interpolate the variable. (SVG helper functions in dashboard.py are plain
  f-strings, NOT the giant format string — different rule from the point above.)
- The panel `note`/`how` fields are inserted UNescaped, so HTML (`<b>`, `<br>`,
  `<span style=...>`) works there for rich per-metric annotations.

## Incremental Notion DB creation (never re-run the monolith)

The repo's `build_notion_dbs.py` rewrites `.env` keeping ONLY the original 3 DB ids
— running it destroys `DB_HOLDINGS/CUSTODY/...`. To add new DBs (e.g. `DB_STRESS`,
`DB_OFR`): write a small `build_<x>_dbs.py` that imports the shared `create_db`
(idempotent by title), creates only the new DBs, and **APPENDS** the new keys to
`.env` (never rewrites the file). Then `write_X_notion()` + read-back verify.

## Verification & commit discipline (unchanged house rules, reaffirmed)

- Verify EVERY new series actually returned data BEFORE building the panel:
  `python3 -c "... print(len(pts), first, last)"`. Never assume a FRED id exists —
  several (`OFRFSI*`, `TEDRATE`) return 0 points from FRED and need a different source.
- git commit in this VM's foreground times out (60s tool-layer illusion) →
  run commit+push as a **background** process with `notify_on_complete`.
- Redline scan before push; the grep pattern `secret` false-positives on
  "Under**secret**ary" / "Assistant **Secret**ary" job titles — check the actual
  match, use a real-token pattern (`ntn_[A-Za-z0-9]{20}`, `sk-...`) to decide.
- Vision backend (browser_vision / vision_analyze) was failing this session; fall
  back to programmatic DOM checks via `browser_console` (count `.part-title`,
  `polyline`, panel `getBoundingClientRect().top` to prove vertical stacking) +
  ship the screenshot path to the user for their own eyes.
