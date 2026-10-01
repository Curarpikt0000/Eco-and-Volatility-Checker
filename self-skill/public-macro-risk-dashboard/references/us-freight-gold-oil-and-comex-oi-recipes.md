# US freight / gold-oil ratio / COMEX OI — verified recipes (2026-10-01)

All numbers below were verified on the live build; use as a starting point, re-verify before quoting.

## Gold/oil ratio (1971+)
- Gold: London monthly average (datasets/gold-prices CSV; same source as stock/gold chart — overlap months matched exactly). Oil: FRED `WTISPLC` (monthly avg, WTI spot).
- Current month: COMEX GC=F daily closes + FRED `DCOILWTICO` daily, averaged the same way as history. "Today" ratio uses latest day that has BOTH prices.
- Stats at 2026-09-29: ratio 43.5 (96th pct of 669 months); mean 18.7, median 16.2, ex-2020 mean 18.4, since-1986 mean 20.4. Record high 101.7 (Apr 2020), low 6.6 (Jun 2008).
- A slide saying "mean 20, gold $5000 → oil $250" is just 5000/20; at constant gold the mean-revert oil price is ~$224, or gold ~$1,800 at constant oil. State both legs.

## US freight (rail weekly + road monthly)
- **Rail, weekly, by commodity**: AAR publishes `https://www.aar.org/wp-content/uploads/YYYY/MM/YYYY-MM-DD-railtraffic.pdf` every Wednesday. The aar.org HTML pages 429/Cloudflare; the **WordPress media API** (`/wp-json/wp/v2/media?search=railtraffic&per_page=100&page=N`) lists all PDFs. Page 1 of the PDF = U.S. weekly: 10 commodity groups + carloads + intermodal + total. Parse with pymupdf; **validate every file** (Σ10 groups == total carloads; carloads+intermodal == total traffic) and reject on mismatch. 273 weeks (2021-07→2026-09) parsed with 0 rejects. One week (2024-04-06) has no file on the site — leave a gap, say so on the chart, YoY for that week blank.
- YoY must compare to the week **364 days earlier (±3d)**, not same calendar date, or the figure drifts (+5.2% vs correct +4.8%).
- **Road has no free weekly national volume.** Use FRED monthly: ATA truck tonnage (`TRUCKD11`, SA, ~2-month lag) + Cass Freight Index shipments (`FRGSHPUSM649NCIS`, NSA) and expenditures (`FRGEXPUSM649NCIS`). Cost side: PPI long-distance TL `PCU484121484121`; weekly diesel `GASDESW` (EIA via FRED). Rebase to one month =100 for multi-line comparison and label them indices, not tonnage.
- **FreightWaves SONAR** (OTRI/STRI rejection rate, NTI spot, VCRPM1 contract rate) is paid; the public Market Monitor page (`gosonar.com/freightwaves-sonar-market-monitor`) shows only today's value with no data date, and sometimes Cloudflare-blocks ("Attention Required"). Pattern used: fetch once per weekday, parse regex, store `data/sonar_snapshots.json` keyed by scrape day (JST), keep old rows if blocked, state on the chart that history accrues from first-scrape date. Never back-fill.
- Fuller/FreightWaves free research: monthly "State of Freight" (video + gated white paper). Their frequently-cited indicators: contract-load rejection rate (most trusted, inflation-immune; 5–10% balanced, 12–15%+ → contract rates rise), outbound tender volume, NTI/VCRPM1 spread, import containers, diesel.

## Chart front-end gotchas (inline SVG in the dashboard template)
- Template is a Python f-string: every JS/CSS brace must be doubled `{{ }}`. Offline render test = extract section HTML + script, un-double braces, load in headless Chromium (playwright is in system python `/usr/bin/python3`, NOT the project venv), assert `path` counts after clicking filter buttons and check `pageerror` is empty.
- Y axis: compute a "nice" step (1/2/2.5/5/10 × 10^k) and floor/ceil to it so YoY charts show a 0% gridline; pad-based ranges produced ugly tick values.
- X year labels: draw at the first point whose month == '01' (not 'year changed'), or the first year label silently vanishes on monthly series.
- Event-delegated hover (`data-tip="title||body<br>…"` on transparent `rect`s) works for dynamically rendered SVG — no extra listener needed.
- Vision-model feedback on an element-only screenshot often reports "clipped legend"; that's missing page CSS in the test harness, not a real defect — check against the full-page shot first.

## COMEX delivery + open interest (user asked: late-month OI spike in Oct GC/SI?)
- Delivery detail (daily, per-firm, gold/silver/platinum): `~/Projects/Comex-Daily-Report/data/comex_issue_stop_firms.json`; units: gold 100 oz/lot, silver 5,000 oz/lot, platinum 50 oz/lot. Daily issued == stopped (checked).
- OI by contract month: Notion OI Daily Bulletin DB (from CME Section 62 bulletin), `top3` months per product only — a minor month (e.g. SIV26) won't appear, so say "can't tell" rather than infer. CME site itself 403s from this VM.
- Finding (to 2026-10-01 report): GCV26 OI fell 55k→12.3k lots into delivery, GCZ26 rose by the same amount = roll, no late spike. Spot-check the report-date vs trade-date offset (report date = prior trading day) and duplicated consecutive days (9/28 vs 9/29 near-identical) before concluding.
- Seasonality caveat to state: Sep isn't a main gold delivery month (Oct is), Sep is a main silver month; platinum main month is Jul — and the Jul platinum figure (38 lots) looked suspiciously low (data-source seam at 2026-06-05 between PDF archive and Notion daily).
