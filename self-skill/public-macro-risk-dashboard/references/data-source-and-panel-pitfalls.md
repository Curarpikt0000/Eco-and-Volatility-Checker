# Data-source & panel pitfalls (Eco-and-Volatility-Checker)

Session-specific hard-won detail for adding/repairing dashboard panels. Distilled
from the 2026-08 work adding the "maturing Treasury (再融资墙)" panel, the BIS
report section, and fixing the foreign-custody full-cycle chart start year.

## 1. US Treasury MSPD API (fiscaldata.treasury.gov) — the two 400-error traps

Source: `api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market`
(per-security marketable Treasury detail; monthly `record_date`; each security has
`maturity_date` + `outstanding_amt` in **millions USD**).

**Use case:** to compute "marketable Treasury maturing within 1 year" (再融资墙 /
rollover wall), pull table_3 per-security detail and, for each monthly `record_date`,
sum `outstanding_amt` of securities where `0 <= (maturity_date - record_date).days <= 366`.
`outstanding_amt` is millions → divide by `1e6` for trillions. Result ≈ $14.5T (2026-07),
which correctly includes Bills + within-1yr Notes/Bonds/TIPS. Table_3 is MONTHLY only
(month-end record_dates) — there is NO daily/weekly cut of this exact caliber. If asked
for a daily/weekly bar chart of this metric, the honest answer is monthly is the finest
grain for the precise caliber; going weekly forces a narrower "Bills only" proxy (~$6-7T,
misses within-1yr Notes/Bonds, contradicts the $14.5T figure). Recommend monthly.

**Trap A — filter colons/commas must NOT be URL-encoded.** `requests`' `params=` dict
percent-encodes `:` → `%3A` and `,` → `%2C`, which the Treasury API rejects (400
"Invalid Query Param"). The filter syntax `record_date:gte:2001-01-01,record_date:lte:2001-12-31`
needs LITERAL colons and commas. Build the filter portion of the URL by hand as a plain
string; only the `page[size]` / `page[number]` BRACKETS need encoding (`page%5Bsize%5D`).

**Trap B — page size cap is 10000.** `page[size]=12000` → 400. Cap at 10000 and loop
`page[number]` until a page returns `< 10000` rows. A year of table_3 detail (12 monthly
snapshots × hundreds of securities) exceeds one page, so months straddle page boundaries —
you MUST paginate correctly or monthly sums truncate.

**Known open data-integrity bug (flagged by code review, fix pending):** an inner
`_pull_year` with `except: break` on a requests/JSON failure treats a mid-pagination
network error as end-of-data, caches the partial (understated) year, and the
`>=11 months cached → skip` incremental check then makes the corruption permanent. Correct
pattern: signal pagination failure explicitly (raise / return None) so the caller SKIPS
caching that year and re-fetches next run; only write a year when all pages retrieved
cleanly (add `resp.raise_for_status()`). This is the same class as the project's P1-3
"network failure returns empty silently" hazard, worsened by cache+skip.

## 2. FRED series real-start vs observation_start gap (WMTSECL1 foreign custody)

A FRED series' `observation_start` is NOT necessarily where real data begins. WMTSECL1
(Custody Holdings: Marketable US Treasury Securities) has `observation_start=2002-12-18`
but the first **237 weekly points are all 0.0** — the first genuinely non-zero value is
**2007-07-04 ($1.21T)**. Statistics collection simply hadn't started.

Lesson when the user asks to extend a "full cycle" chart earlier: probe the series' actual
first non-zero value, don't just trust `observation_start`. Setting the chart start to the
series-existence date would draw a fake flat-at-zero line then a jump — misleading, violates
the never-mislead rule. Set the chart start to the **first real non-zero point** and label
it with that year. Verify: pull a wide window, filter `v > 0`, take `[0]`. (This is also why
the original chart was pinned at 2008 — 2007-mid was the true data onset; 2008 was a clean
year boundary.) When a user picks a start year the source can't honestly support, surface
the 2-3 real options (series-start-with-zeros / first-real-value / different-caliber source)
and let them choose rather than silently faking it.

## 3. Adding a new bottom PANEL — the daily-cron inline-generate drift trap

New panels are wired in `src/build_dashboard.py` (fetch → pass to `dashboard.generate()`),
but the **daily cron (`eco-vol-01-daily-scan-report`) has its OWN inline `python -c` that
calls `dashboard.generate(...)` with an explicit kwarg list** — it does NOT import
build_dashboard. Any new `generate()` param you add is silently DROPPED by the cron unless
you also patch the cron's inline call in `~/.hermes/cron/jobs.json`. Symptom: panel shows
when you build manually, but the daily-cron-produced dashboard is missing it. This session
found `maturing_treasury` had been added to build_dashboard but the cron inline call never
passed it — so the panel was absent from every daily build. Whenever you add a panel:
(1) wire build_dashboard.py, (2) grep the cron prompt for the inline `generate(` call and
add the same kwarg (+ its fetch + any standalone-page build), (3) verify by reading the
cron prompt back.

## 4. "Report-scan section + standalone page + button" pattern (BIS Quarterly Review)

Reusable pattern for "scan an external institution's periodic reports, show a summary on the
dashboard with a button to a full standalone page, backfill the past year":

- **Source discovery:** BIS Quarterly Review has deterministic PDF naming
  `https://www.bis.org/publ/qtrpdf/r_qtYYMM.pdf` (YY=year, MM=03/06/09/12). `HEAD`/range-GET
  each candidate for HTTP 200 to confirm existence — 4 quarters = past year. Permanent latest
  entry: `https://www.bis.org/publ/quarterly.htm`. BIS Bulletin list page is JS-rendered
  (curl gets nothing) — leave it to the daily-cron agent's web_extract/browser, same as the
  project's other JS/anti-scrape sources (AAII/CBOE/LEI).
- **Storage:** ONE unified JSON `data/bis/reports.json` (`{updated, reports:[{id,kind,title,
  date,pdf_url,page_url,summary:[...],summary_status}]}`), not per-report files — follows the
  storage-consistency principle. `sync_quarterly()` is idempotent (discovers new, never
  overwrites an existing summary); `upsert_summary()` fills points for a pending report.
- **Summary generation:** `web_extract` on the PDF URL returns LLM-markdown of the doc; a
  40-page PDF is truncated but the review's key-takeaways + boxes are captured. Extract 4-6
  Chinese trader-relevant points, ONLY from actual doc text, never fabricate; can't extract →
  leave `summary_status=pending`, never invent. Backfilling 4 PDFs at once → dispatch 3
  parallel `delegate_task` leaf subagents (toolset `["web"]`) + do the 4th on the main thread.
- **Render:** section shows only the LATEST report's points + a button (reuse the existing
  `.part-title-flex` + `.kol-dash-btn` classes — same as the KOL-dashboard button); button
  links to a standalone page `docs/bis/index.html` (own Morandi-palette generator) listing
  ALL past-year reports as point cards with original-PDF links. Add the section title's
  keyword to the sidebar grouping JS `match:[...]` array so it lands in the right collapsible
  group ("流动性与央行" for BIS).
- **Freshness:** daily cron `sync_quarterly` detects new quarters (most days no-op, seconds);
  a cron prompt step tells the agent to extract+upsert summaries for any `pending` report.
