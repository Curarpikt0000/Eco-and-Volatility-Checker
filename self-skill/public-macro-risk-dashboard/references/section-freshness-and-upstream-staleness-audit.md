# Section freshness & upstream-staleness audit (Eco dashboard, 2026-10-06)

SKILL.md is at its size limit; this file is not yet linked from it. Recommend curator consolidation, then add a pointer.

Chao's recurring complaint: "这个图明显没有每日更新". Root pattern: **daily cron says `ok` while a section silently reads a stale upstream**. Trace a section to its *producer* before blaming either side.

## Triage order for "chart X didn't update"
1. Find the fetcher (`grep def fetch_...` in `src/external_data.py`) and read what it reads: live API / local `data/*.json` cache / another project's file / another agent's published site.
2. Query the *source itself* for its newest data date, not the dashboard page text (page-text date scraping picks any date in the section; use only to shortlist suspects).
3. Find who produces the source: grep `~/.hermes/cron/jobs.json` and the sibling project's `cron_wrappers/`. A script with hard-coded `/Users/...` = Mac-produced; the VM has no such cron.
4. Notion rows: all agents share ONE bot token (`Hermes Analysis Issue Report`), so `last_edited_by` cannot tell which machine wrote. Do not claim "Mac is still running" from fresh rows alone.
5. Only then assign blame.

## Findings
- `comex-inventory-charts.pages.dev` (GLD/SLV flows + COMEX/SHFE/SGE inventory) stale since 09-16; producer cron lived on Mac. Fix: vendored 3 scripts into `tools/comex_inv/` (path via `INV_BASE` env), Notion read-only, SPDR xlsx for GLD, SGE weekly PDFs. `fetch_comex_inventory` builds locally first, external site second, cache last. No cron-prompt change needed (step 6 already runs `build_dashboard.py`). Seed `data/comex_inv/sge_history.json` from the old cache so SGE history doesn't shrink.
- A cache-fallback fetcher must expose it (`note`, `stale_days`); the original silently served 4-20 day old data.
- Notion CME rows in `OK (stock)` state carry only SHFE stock, no `[Delivery]`/OI -> weekly issue/stop silently misses days (every Thursday since 08-20, plus 09-28, 10-01). Chart now shows per-week delivery-day count on hover and dashes weeks with <5 days. Don't state "133 days" from PDF count; sum actual `days`.
- 11:00 daily cron reads data Notion writes ~12:30 -> shows one day behind by construction.

## House vs Customer (C/H) for issue/stop
Chao: chart is **House(H) only; C must not enter**. Notion `[Delivery]` tags `Name(C|H)发N/接N` exist only from 2026-08-21; 06-06 to 08-20 rows are untagged. Chao chose A: untagged weeks are **blank (None), not 0, not assumed H**. Archive PDFs (01-06 to 06-05) carry `org` per seat and are usable. Effect: Gold 09-28 week flipped -1970 (C-driven) to +805 House; JPM is almost all C. Verify re-aggregation with an independently written per-week H calc (12/12 matched). PDF and Notion segments share no tagged dates -> continuity across the seam is unproven; say so.

## Pitfalls
- Isolated build must also isolate side effects: `build_dashboard.py` writes production Notion (stress panels) even from a copied dir. Disable Notion-write steps before a "safe" trial, or disclose.
- Don't `grep -r ~/Projects` (timeout); use `search_files` scoped to a project.
- `vision_analyze` level estimates from screenshots are guesses; re-derive from data.
- Headless QA screenshot: Playwright-bundled `chrome --headless=new --no-sandbox --disable-gpu --screenshot=out.png file:///tmp/page.html` (wrap section HTML with extracted CSS; emoji render as boxes there, not a site bug).
- Chao answers by number/letter to a specific earlier question; when a reply doesn't map, check the replied-to/OOB quote before re-asking (I re-asked an already-answered C/H question).
- Never say "still running on Mac"/"fixed" without a physical artifact (log line, mtime, live curl).
