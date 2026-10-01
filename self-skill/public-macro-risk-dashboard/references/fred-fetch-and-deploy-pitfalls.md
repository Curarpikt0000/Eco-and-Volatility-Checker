# FRED fetch resilience, deploy freshness, and verification pitfalls

Distilled from the Eco-and-Volatility-Checker session (2026-08) where Chao added
Credit-Impulse-Japan, a 2008 long-history chart, and the custody-UST acceleration
chart. These are recurring operating traps for this pipeline (and any FRED-backed
macro dashboard).

## 1. FRED data-fetch: use the带key API primary, fredgraph CSV only as fallback
- The免key CSV endpoint `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SID>&cosd=<date>`
  is **unstable from inside the VM's Python** — BOTH `requests` and a `subprocess`
  `curl` to it time out intermittently (ReadTimeout), even though a *manual*
  terminal `curl` of the same URL succeeds. Do NOT make the CSV endpoint the
  primary channel and do NOT conclude "the data is gone" from a CSV timeout.
- The stable channel is the project's **带key FRED API**:
  `from fetchers.fred import fetch_fred_history; fetch_fred_history(SID, start=cosd)`.
  Every fetcher that pulls FRED should try `fetch_fred_history` FIRST, then fall
  back to the CSV endpoint (with 2–4 retries) only if the API returns empty.
- Pattern already applied to: `fetch_credit_impulse._fred_ratio`,
  `_fred_ratio_long`, and `fetch_custody_acceleration`.

## 2. Series-availability quirk: some BIS series exist ONLY on the CSV endpoint
- Japan BIS credit-to-GDP ratio `QJPPAM770A` returns **EMPTY from the带key API**
  but returns real quarterly data from the免key CSV endpoint. (US/CN/EU
  QUSPAM770A/QCNPAM770A/QXMPAM770A work on both.)
- Consequence: the API-primary + CSV-fallback pattern is REQUIRED, not just nice —
  it's the only way Japan resolves. When adding a new country/series, verify BOTH
  channels; don't assume API coverage.
- BIS credit-to-GDP ratio history depth (for long-history charts): US→1947,
  CN→1985, EU→1999, JP full; 2008–2010 all present, so a "2008 至今" reference
  line is safe for all four.

## 3. Independently verify delegate sub-agent data claims (iron rule bit here)
- A sub-agent reported "QJPPAM770A returns real data via the API" — it had used
  the CSV endpoint via curl. When the main agent verified with the project's own
  `fetch_fred_history` (API), it got EMPTY. The sub-agent wasn't lying; it used a
  DIFFERENT channel. Always re-run the claim through the EXACT code path the
  pipeline will use before integrating. (See global rule §2.10 / MEMORY iron rule
  on independent verification.)

## 4. Live-site "数据未就绪 / data未就绪" ≠ data-source failure
- When the GitHub Pages dashboard shows a card's empty-state ("… 数据未就绪") but
  the LOCAL fetcher returns data fine, the cause is almost always a **stale
  GitHub Pages deploy** — `docs/index.html` is from an older commit.
- Fix: rebuild locally → `cp dashboard/index.html docs/index.html` → commit → push.
  Verify the fetcher independently first so you don't chase a phantom data bug.

## 5. git commit/push "timeout" is a DISPLAY artifact in this VM — run in background
- `git commit` / `git push` frequently reports "Command timed out after 60s" in
  the foreground tool even though there is no index.lock, no pre-commit hook, and
  the operation actually SUCCEEDS moments later. The 60s cap is the tool layer,
  not git.
- Correct pattern for every commit+push here: run it as a **background** terminal
  command with `notify_on_complete=true`, then poll — the commit lands (verify via
  `git log -1 --oneline`). Use `git -c commit.gpgsign=false commit -m "…"` (repo
  discipline: no gpg sign; avoid parentheses in commit messages per redactor rule).
- Do NOT retry commit repeatedly in the foreground assuming failure — you'll get
  duplicate-commit confusion. Background + poll once.

## 6. build_dashboard hardcoded window params — grep before assuming the fetcher wins
- When a chart's on-screen window didn't match the fetcher default (e.g. custody
  acceleration showed 13 weeks after the fetcher default moved to 26), the cause
  was a HARDCODED `weeks=13` in `build_dashboard.py`'s call, overriding the
  fetcher's new default. After changing a fetcher default, grep the call site in
  `build_dashboard.py` and update the explicit arg too.

## 7. Chart-type preference: multi-window ACCELERATION → multi-LINE with zero-axis, not bars
- Chao found a single EMA-smoothed bar chart "hard to understand" and asked for
  **separate lines per look-back window** (7/14/28/56-day ≡ 1/2/4/8-week) on ONE
  zero-axis chart so he can read the CROSSOVERS (short line crossing mid/long =
  short-term momentum turning first / leading signal; lines diverging = trend
  strengthening; converging/crossing = momentum switch).
- General preference for "acceleration / momentum-of-momentum" visuals: prefer
  multiple trailing-window lines on a shared zero-axis over a single smoothed bar
  series. Keep a small "latest readout" cell per window above the chart.

## 8. Rolling-window semantics for "本周 / this week" aggregates
- "本周" for a KOL/opinion aggregate must mean a **rolling past-7-day window
  (last Monday → today)**, taking each entity's most-recent substantive record in
  that window — NOT "records dated >= this Monday". The latter empties the whole
  module on a Monday (or whenever the latest daily snapshot is sparse/empty).
  `kol_weekly_views` was rebuilt to the rolling-window form for exactly this bug.

## 9. Weekly-vs-daily honesty for "超短期 / every-day" requests
- Fed H.4.1 custody UST (`WMTSECL1`) is **weekly** (as-of Wednesday), NOT daily.
  A user asking for "每天的加速度" can't get true daily granularity — label the
  chart honestly as "trailing 7/14/28/56 天 ≡ 1/2/4/8 周" and say so. Don't fake
  daily points. Acceleration = 2nd difference: a_k[i] = v[i] − 2·v[i-k] + v[i-2k].
