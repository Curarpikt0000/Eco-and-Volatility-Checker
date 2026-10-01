# Adding a new section / new data source to the Eco-and-Volatility dashboard

Session-distilled playbook for extending the trader-screen dashboard with a new
chart section and/or a new public data source. Covers the wiring path, reusable
SVG chart primitives, and the hard pitfalls that bite on the second run (cron).

---

## 1. The FIVE wiring points for a new section (miss one and it silently breaks)

Adding a board is NOT just writing a render function. There are 5 places, and the
cron path is separate from the interactive `build_dashboard` path:

1. **`src/external_data.py`** — add `fetch_<thing>()` returning
   `{status, as_of, <series>:{status, points:[(date,val)], ...}}`. Each sub-series
   carries its own `status` so a partial failure degrades gracefully. `status='未获取'`
   when a source is missing — **never fabricate**.
2. **`src/dashboard.py` `generate()` signature** — add a keyword arg
   (e.g. `oil_inventory=None`), default `None`.
3. **`src/dashboard.py` the `.format(...)` dict** — add
   `<key>=_<thing>_html(<arg>)` so the placeholder gets filled.
4. **`src/dashboard.py` the HTML template block** — add the
   `<div class="part-title">…</div><div class="card">{<key>}</div>` where you want
   it to appear (ordering matters; place near thematically-related sections).
5. **`src/build_dashboard.py`** — call `ed.fetch_<thing>()` and pass
   `<thing>=<thing>` into `dash.generate(...)`.

## 2. ★★ The cron inline-`generate()` sync pitfall (the one that vanishes the section)

The daily cron job (`eco-vol-01-daily-scan-report` in `~/.hermes/cron/jobs.json`)
does **NOT** call `build_dashboard.py`. It has its own **hand-written one-liner**
`generate(...)` call embedded in the cron *prompt* string, with its own
`fetch_*()` chain. If you add a section only via steps 1-5 above, it renders in
your manual build but **DISAPPEARS the next morning when cron regenerates**.

Fix, every time you add a section:
- Open `jobs.json`, find the `eco-vol-01-daily-scan-report` job prompt.
- In the fetch chain (`...mt=e.fetch_maturing_treasury();bis.sync_quarterly(5)...`)
  insert `oil=e.fetch_oil_inventory();` (or your fetch).
- In the `generate(...)` call (`...maturing_treasury=mt,bis_latest=bisl))`)
  insert `oil_inventory=oil,`.
- Edit jobs.json with a `.venv` python `json.load`→string-`replace`→`json.dump`
  (back it up first: `cp jobs.json jobs.json.bak-<x>`), then read-back verify both
  substrings are present. `execute_code` is blocked under cron approvals — use
  `.venv/bin/python3` via terminal.

Verification after `build_dashboard`: grep the emitted `docs/index.html` for the
section title AND the source-links/redline strings; confirm the OLD section (if
you replaced one) is GONE (count == 0). Line-diffs look tiny because SVG lives on
long single lines — trust string grep, not `git diff --stat`.

## 3. Reusable SVG chart primitives (in dashboard.py)

- `_bar_chart_svg(points, ...)` — month/period bar chart; last bar auto-highlighted
  + value label on top. Used by re-financing-wall etc.
- `_custody_chart_svg(hist, ...)` — area+line chart with Y grid, date x-labels,
  latest-point marker; trend color = sage-green (rising) / clay-red (falling).
- **Red-line threshold charts (new this session):**
  - `_oil_line_svg(pts, redline=, redline_label=, zero_line=, rising_good=)` — line
    chart with an optional red dashed threshold line and/or a 0 baseline; folds the
    redline/0 into the y-range so it's always visible.
  - `_oil_bar_redline_svg(pts, redline=, redline_label=)` — bar chart where any bar
    **below the redline is filled red** (`#d64545`) to flag breaches; redline drawn
    as a red dashed line with a label.
  - Signal colors: green `#2e9e5b/#2e7d52`, amber `#e0a92e/#a9791a`, red `#d64545`.
    Morandi neutrals for gridlines `#d4cdbe`, muted text `#8a8578`.

## 4. Per-section update-frequency badges (Chao asked for this)

Each `.part-title` carries a colored `.freq-badge` labeling the data source's TRUE
release cadence (not the cron cadence): daily(green)/weekly(blue)/monthly(amber)/
quarterly(purple)/event(gray, e.g. "每次拍卖"). Badge uses `margin-left:auto` to
sit at the right; `.part-title` is `display:flex`. For the two flex titles that
already carry a button (KOL全景/BIS), put the badge between the `</span>` and the
`<a>` with inline `style="margin-left:0"` so it doesn't fight the button.

★ **Sidebar-index textContent contamination fix:** the left module-index auto-builds
link names from `part-title.textContent`. Once badges are inside the title, the
frequency word ("每日更新") gets appended to every sidebar link name. Fix in the
sidebar JS: `var _tc = t.cloneNode(true); var _fb=_tc.querySelector('.freq-badge');
if(_fb)_fb.remove(); var label=(_tc.textContent||'').trim();` — extract the label
from a clone with the badge stripped. groupOf() keyword matching is unaffected.

Map cadence by SOURCE, verified this session:
- daily: FRED daily series,派生 indicator cards, KOL全景 crawl, liquidity, CB balance sheets, OFR/stress panels
- weekly: KOL状态变化 (weekly snapshot diff), Fed H.4.1 custody, EIA weekly stocks
- monthly: FRED monthly (M0/M1/M2, M2 10yr), MSPD refinancing wall, TIC country holdings (~2mo lag)
- quarterly: Credit Impulse, BIS Quarterly Review, 13F
- event: Treasury auctions

## 5. EIA (Energy Information Administration) as a public source

FRED mirrors EIA **oil prices** (`DCOILBRENTEU`, `DCOILWTICO` daily) but does NOT
carry EIA **inventory** series. For Cushing stocks / SPR you must hit the EIA API
directly (free key from https://www.eia.gov/opendata/register.php, store in `.env`
as `EIA_API_KEY`, gitignored).

- Endpoint: `https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key=<key>&frequency=weekly&data[0]=value&facets[series][]=<SERIES>&sort[0][column]=period&sort[0][direction]=asc&length=5000`
- Series verified: SPR = `WCSSTUS1`; Cushing = `W_EPC0_SAX_YCUOK_MBBL`. Values are
  in **thousand barrels** — divide by 1000 for million-barrel display.
- Response path: `.response.data[]` each `{period, value}`.
- ★ **Shell-quoting trap:** `facets[series][]=…` inside a single-quoted curl in
  bash throws "unexpected EOF while looking for matching `'`" because of the
  brackets. Don't fight bash quoting — probe/fetch with a `.venv/bin/python3`
  `urllib`/`requests` script instead. (FRED `series/search` for these inventory
  series returns only the price series — don't conclude the data is unavailable;
  it's just EIA-only.)
- Domain note: SPR operational red line ≈ 300M bbl (per Amos Hochstein); Cushing
  tank-bottom ≈ 20M bbl; Brent-WTI spread going negative = Cushing near tank bottom.

## 6. Adding a KOL — align to Notion SSOT, don't assume local registry is complete

`data/kol_registry.json` (top-level dict with `kols:[]`, `_count`, `_last_updated`)
is a MIRROR; the SSOT is the **Notion KOL List DB** (`35947eb5fd3c800db852cef31f9de6a5`).
These can drift out of sync — a KOL can already exist in Notion but be missing from
the local JSON.

Add-a-KOL discipline (only add the named person; never associate/invent):
1. Idempotent dedupe in the local registry (`id`/`display_name` substring).
2. **Also query the Notion List DB** for the name BEFORE creating a new row. This
   session: local said "not present" but Notion already had the person (编号 115) —
   so the correct action was to ALIGN the local entry to Notion's number + page_id,
   NOT mint a fresh number. SSOT wins.
3. Anchor to an EXISTING `(domain, sector)` class — don't invent a category
   (energy person → `资源与能源安全 / Energy & Commodities`).
4. Notion List DB schema: `编号`(title), `KOL / 机构`(rich_text), `领域`(select,
   fixed option list), `核心背景 / 身份`(rich_text), `主要分析方向 / 监控维度`(rich_text),
   `最新观点`(rich_text), `最新观点日期`(date). `notion_writer._req` returns
   `(status_code, json)` — a tuple, not a dict.
5. Registry `active:true` ⇒ the daily cron (reads all active) auto-picks them up
   next run; no cron edit needed.
6. Backfill file `data/kol/backfill/<id>.json`:
   `{kol, sector, backfill_date, source_method, count, history:[{date, direction,
   comments, targets, source}]}`. Only include attributable, dated, directional
   quotes with a real source URL (web_extract to verify原话); drop anything you
   can't attribute — `count:0` with an honest source_method note is correct when
   nothing is findable. Never fabricate a date/quote/URL.
7. Registry `institution`/`bio`: verify against a first-hand source (Wikipedia /
   the person's own bio page) — don't copy an unverified detail forward (dropped an
   unconfirmed "Tellurian" affiliation, kept the verified "TWG Global managing
   partner" one).
