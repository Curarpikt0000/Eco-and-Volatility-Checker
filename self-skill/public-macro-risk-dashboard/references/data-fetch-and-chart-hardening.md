# Eco-and-Volatility-Checker — data-fetch, deploy & chart hardening (Chao 2026-08)

Session-distilled fixes for the Eco-and-Volatility-Checker dashboard. All verified live.

## FRED fetching: keyed API first, fredgraph CSV only as fallback
- `fred.stlouisfed.org/graph/fredgraph.csv` intermittently **times out from Python**
  (both `requests` AND `subprocess` curl). Manual `terminal` curl often succeeds, but
  the Python-spawned subprocess/requests read-timeout frequently (env/concurrency).
- **All FRED fetchers use `fetchers.fred.fetch_fred_history(sid, start=...)` (keyed API,
  stable) as channel 1; fredgraph CSV with retries as channel 2.**
- Symptom of ignoring this: a dashboard card shows "数据未就绪" / a long-history chart
  won't render, and re-runs are flaky (works sometimes). That's the CSV endpoint.

## Some BIS series exist ONLY on免key CSV, return EMPTY on keyed API
- Verified: Japan `QJPPAM770A` (BIS credit-to-GDP ratio) → `fetch_fred_history` returns
  EMPTY; only fredgraph CSV has the data. US/CN/EA (`QUSPAM770A`/`QCNPAM770A`/`QXMPAM770A`)
  work on both.
- So the "API-first + CSV-fallback" must be **per-series** (mixed), not either/or.
- ★ When independently verifying a series' availability, **test with `curl` on the CSV
  endpoint** — don't trust the keyed API alone (a subagent once reported "API has data"
  when the API was empty and only CSV had it).

## 线上 "XX 数据未就绪" → check GitHub Pages stale deploy FIRST
- Local fetcher works but the live site shows an empty state = `docs/index.html` is an
  old commit. Fix = rebuild dashboard → `cp dashboard/index.html docs/index.html` →
  commit+push. Rule this out before diving into data-source debugging.

## "本周/过去一周" panels = rolling-window aggregation, never "latest single snapshot"
- Bug seen: `kol_weekly_views` did `src_date = sorted(snaps)[-1]` and rendered only the
  newest day's snapshot → when the newest day was empty/sparse (Sunday cron hadn't run
  full crawl, or only a few entries that day) the whole module went blank.
- Correct pattern (generic for ANY rolling-window panel):
  - window = last Monday → today: `this_monday = today - timedelta(days=today.weekday())`,
    `last_monday = this_monday - timedelta(days=7)`.
  - iterate all snapshots in window, for each entity take its **most-recent-in-window
    record that has substantive content**, dedupe/aggregate.
  - since_date (first-appearance) still回溯 full history; `is_new = since >= this_monday`.

## Custody-acceleration chart — check granularity before promising "daily"
- User asked for "外国官方托管美债每天加速度". Source (Fed H.4.1 / FRED `WMTSECL1`) is
  **weekly** (Wed as-of) → cannot do true daily. Honestly degrade to trailing 7/14/28
  days ≡ **1/2/4 weeks** and label the weekly constraint on the chart.
- Reusable acceleration method (any "加减速/动量拐点" chart):
  - **acceleration = 2nd difference** (change of the change). Zero-axis: above = inflow
    accelerating / outflow decelerating; below = outflow accelerating.
    - 7d(1wk) = `v[i] - 2·v[i-1] + v[i-2]`; 14d uses i-2/i-4; 28d uses i-4/i-8.
  - Weekly small-sample noise is high → **main chart = difference of EMA(3wk) slope**
    (smoothed, zero-axis filled green-up/red-down), with 7/14/28 raw 2nd-diff shown as
    three numeric cells beside it (short window = fastest/most sensitive; long = steadiest/laggiest).
  - Custody口径 = `WMTSECL1` (foreign-official account), NOT `WSHOSHO` (Fed's own SOMA).

## Credit Impulse — 4-country (added Japan) + 2008 long-history reference chart
- fetch adds Japan `QJPPAM770A` → four countries US/CN/EA/JP (`.ci-cols-4`).
- Long-history reference: `points_long` via a `cosd=2006` pull; series回溯 to 1947(US)/
  1985(CN)/1999(EA), Japan full too. `_credit_impulse_long_svg` draws a multi-country
  polyline (coarse granularity, labeled time-span, reference-only). **The 10-year short
  chart stays untouched** (Chao explicit).

## git commit "timeout" in foreground is a display-layer illusion
- Run `git -c commit.gpgsign=false commit ... && git push` via
  `terminal(background=True, notify_on_complete=True)`, then poll for the real exit_code.
  Don't assume failure from a 60s foreground timeout and re-commit.
