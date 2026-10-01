# Treasury MSPD API + dashboard-enhancement patterns

Session-distilled reference for the Eco-and-Volatility-Checker pipeline. Two parts:
(A) a reusable public data-source (Treasury MSPD) with hard API quirks, and
(B) the dashboard UI/legibility patterns Chao asked for and how they were built.

---

## A. US Treasury MSPD (Monthly Statement of the Public Debt) — the "maturing-within-1yr Treasury" data source

**What it gives you (free, official, no key):** per-security marketable-debt detail with
`maturity_date` + `outstanding_amt`, so you can compute *any* maturity-bucket aggregate
(e.g. "possibly-rolled-over debt maturing within 1 year") by summing over securities.

**Endpoint (逐券明细表 = the useful one):**
```
https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market
```
- `mspd_table_1` = maturity-agnostic held-public vs intragov totals (NOT bucketed by maturity).
- `mspd_table_3_market` = per-CUSIP rows: `record_date, security_type_desc, security_class1_desc,
  maturity_date, outstanding_amt, issued_amt, redeemed_amt`. Earliest `record_date` = **2001-01-31**
  (so "since 2000" becomes "since 2001", state it honestly).
- `outstanding_amt` is often `"null"` (~half the rows). Fallback: `issued_amt + redeemed_amt`
  (redeemed is negative). Amounts are in **millions USD** → divide by 1e6 for $T.
- Compute "within 1 year": for each row, `0 <= (maturity_date - record_date).days <= 366`, sum the amount.
  Sanity check: 2026-07-31 ≈ **$14.52T** (174 securities: Bills + Notes/Bonds/TIPS maturing ≤1yr).

### THE TWO NON-OBVIOUS API QUIRKS (cost 4 failed attempts — do NOT rediscover)
1. **`filter=` colons and commas MUST NOT be URL-encoded.** They are the Treasury filter
   *syntax*. If you use `requests.get(BASE, params={...})`, requests encodes `:` → `%3A`
   and `,` → `%2C` and the API returns **400 "Invalid Query Param"**. FIX: build the URL string
   manually with literal `:` and `,` in the filter; only the `page[...]` brackets get encoded.
2. **`page[size]` max = 10000.** `12000` → **400 "Invalid Query Param"** (misleading — nothing
   about the filter is wrong). Cap at 10000 and loop `page[number]` until a page returns < 10000 rows.

Correct URL shape:
```
{BASE}?filter=record_date:gte:{y}-01-01,record_date:lte:{y}-12-31
      &fields=record_date,maturity_date,outstanding_amt,issued_amt,redeemed_amt,security_type_desc
      &page%5Bsize%5D=10000&page%5Bnumber%5D={page}
```
Debug ladder when you get 400: add params ONE at a time (single-filter → dual-filter →
+page[size] → +page[number]) and shrink `fields` — that isolates the offending param fast.

### Fetcher design that worked (in `external_data.py`)
- Pull **by year**, group rows by `record_date`, compute the ≤1yr sum per month-end.
- **Local cache** `data/maturing_treasury.json` keyed by date; on re-run, skip years already
  full (≥11 months) and only re-pull the current year. First full 2001→now pull ≈ 23s.
- Return `history_long` (all months, YYYY-MM) + `history_recent` (last ~2yr) + `value`/`as_of`.
- **Caveat to label on the chart:** MSPD is *total* (Fed SOMA + private). It does NOT isolate
  "private-sector held". If Chao wants pure-private, subtract Fed SOMA short-end holdings
  (extra source, larger error) — otherwise state "含 Fed + 私营, 未剔除 Fed SOMA".

Wiring: `build_dashboard.py` fetches it; `generate(..., maturing_treasury=...)`; a
`_maturing_treasury_html()` renders **two charts (near-2yr + 2001-to-now全周期)** reusing the
existing `_custody_chart_svg` / `_custody_span_line` helpers (they accept `[(date,$T)]`).

---

## B. Dashboard legibility patterns Chao requested (all reusable across his dashboards)

1. **Data-source codes → clickable hyperlinks.** Chao dislikes bare指标代码 (`BAMLH0A0HYM2`,
   `DGS10`). Build one `_linkify_sources(text)` helper (esc first, then regex-swap known codes to
   `<a class="src-lnk" ...>`), apply it at EVERY `数据源：` render site. FRED series → 
   `https://fred.stlouisfed.org/series/<ID>` (whitelist the IDs to avoid mangling plain caps like
   `US`/`OAS`); OFR → financialresearch.gov; TIC → home.treasury.gov; ^MOVE → Yahoo;
   MSPD → fiscaldata.treasury.gov. One helper, whole dashboard.

2. **Always spell out abbreviations in the card "如何看" / footnote.** Chao repeatedly asks
   "X 是什么字母的缩写". Pre-expand in the HOW_TO_READ text: `A/D=Advance/Decline`,
   `HY=High Yield`, `IG=Investment Grade`, `OAS=Option-Adjusted Spread`, `VIX=Volatility Index`,
   `CAPE=Cyclically Adjusted PE`, `LEI=Leading Economic Index`, `SOFR=Secured Overnight
   Financing Rate`, `IORB=Interest on Reserve Balances`. Do this proactively for every acronym.

3. **Dual-axis line charts: label max/min/current/median on EACH line.** Chao objected that a
   dual-axis chart with no zero line leaves you unable to read the point value. Solution (not a
   shared zero line — that misleads across two axes): mark ▲max / ▼min / hollow "当前 X.XX" point +
   a dashed median line per series, and a `现X 高X 低X 中X` summary in the legend. Watch viewBox
   width — 3-digit values overflow; widen `w`/`mr` and shorten labels; verify programmatically that
   no `<text>` x+width exceeds viewBox.

4. **Sidenav module index → thematic collapsible groups.** A flat "1..6 + a pile of ＋" index is
   what Chao rejected. Pure-JS: scan `.part-title`, map each to a theme group by keyword
   (核心风险扫描 / KOL观点 / 流动性与央行 / 国债流动性观测 / 机构与政要持仓), render collapsible
   `.sn-group` sections. Zero change to the板块 titles → future板块 auto-join their group.

5. **KOL cards: show industry standing at the bottom.** The registry `institution`/`bio` field
   already holds it (97/98 filled) — DON'T re-research 100+ people. In `_kol_views_html`, load
   `kol_registry.json`, map `display_name → institution`, render `🏛 <standing>` at each card's
   foot. Add a title-right button linking the sibling KOL dashboard
   (`https://curarpikt0000.github.io/kol-dashboard/`).

---

## C. KOL "state change / 转向"口径 (avoid the recurring misread)
- "转向" is **weekly**: this-week's latest snapshot direction vs last-week's last snapshot
  direction, only counted when they differ (`kol_weekly_changes()`). It is NOT "today".
- Registry is `data/kol_registry.json` with top-level `{_count, kols:[...]}`; active list can be
  smaller than total (some `active=false`). Add a KOL by appending one entry (ASCII name to dodge
  the redactor), bump `_count`, read back to verify pollution=0. Cron reads "all active" → new KOL
  auto-included next run, no cron edit.
- **1-year言论 backfill** is agent-mode (web_search ddgs + LLM extract), 5 people/run every 30m via
  cron; queue file `data/kol/backfill_queue.json` marks done. "Covered" = ≥3 dated comments spanning
  ≥6 months; Fed-advisor/academic/deceased/non-market figures legitimately return few/none — write a
  thin file, note "无可追踪公开市场言论", mark done, don't loop on them.
