# Cron rebuild-vs-push race + finding free monthly data sources

Session-proven pitfalls (Chao 2026-08, adding 图2 India silver imports + 图3 India/China gold premium).

## ★★ Cron dashboard-rebuild OVERWRITES a freshly-added section with its PLACEHOLDER — a build-vs-push TIMING RACE

Every daily cron rebuilds `docs/index.html` from scratch. A section renders its
`<p class="empty">…数据同步中…</p>` placeholder whenever its fetch returns
`status != "ok"` — i.e. the data JSON isn't committed/pulled yet in the cron's
environment.

**The trap:** you add a new section + its data file at (say) 11:11 / 11:22, but the
daily cron already fired its rebuild at 11:00. The cron commits+pushes a PLACEHOLDER
version that clobbers your work on the PUBLIC site. User sees "数据同步中" and thinks the
data was lost.

**It is NOT lost.** The JSON has all the real points; only the published HTML reverted.

### Diagnosis recipe
1. Shape-count the section in the built HTML:
   `python3 -c "h=open('docs/index.html').read(); i=h.find('sec-<id>'); j=h.find('sec-<next>',i); seg=h[i:j]; print('占位:', '数据同步中' in seg, 'polyline:', seg.count('<polyline'), 'rect:', seg.count('<rect'))"`
   → 0 shapes + "数据同步中" = it's the placeholder.
2. Run the fetch alone in the project `.venv` — confirm `status=ok n=<N> latest=<v>`.
   Data is fine → the renderer isn't the problem.
3. Forensics: compare timestamps.
   `git log --format='%h %ci %s' -1 -- data/<newfile>.json` (when data landed)
   vs the offending rebuild commit's `%ci`. If the data-file commit is LATER than the
   cron's rebuild commit → confirmed race, not a bug. You can even inspect the bad
   commit's HTML directly: `git show <cron_commit>:docs/index.html | grep -c '<polyline'`.

### Fix (no code change)
- Manually re-run the build in the project `.venv`:
  `python3 -m src.build_dashboard` (run background+notify; it fetches many sources, minutes).
- Verify shapes present in `docs/index.html` (repeat step 1, expect >0).
- Red-line scan, then commit + push (background + notify).
- Confirm the PUBLIC copy from the raw source (NOT Pages — CDN lags 1-2 min):
  `curl -s https://raw.githubusercontent.com/OWNER/REPO/main/docs/index.html | grep -c '<polyline'`.
- Next day's cron reads the now-committed data and self-heals automatically.

**Rule:** after adding a section, either push data+code BEFORE the next scheduled
rebuild, or manually rebuild+push AFTER — and ALWAYS verify the PUBLISHED HTML.
A green local build ≠ a green public site.

## ★ Test-harness field-name mismatch fakes a "fetch is broken" alarm

A quick `python -c` probe returning `n=11` / `latest=None` may be YOUR probe using the
wrong keys, not a broken fetch. Example: real series lives under `points`
(not `series` / `india`); `len(gp.get('india'))` counted a nested dict's KEYS (11), not
data points (3801). Always confirm the JSON's real keys first:
`json.load(open(f)).keys()` — before concluding the renderer/fetch is broken.

## ★ When the "official" source is annual-only or paywalled, hunt a FREE MONTHLY mirror

Chao pushed back that DGCIS-annual India silver imports "没有什么意义" — annual is useless
for a trend chart, and Metals Focus / S&P Global monthly is paywalled. Escape hatch:

**UN Comtrade preview API (免key, free):**
`https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=699&period=YYYYMM&cmdCode=7106&flowCode=M`
- reporterCode 699 = India; cmdCode 7106 = silver; flowCode M = imports; M = monthly.
- National trade re-mirrored by UNSD → structured MONTHLY series the national portal
  only sells. Preview API limits to 1 period/call → loop month-by-month (~1.5s each).
- **Correct partner filter = `partner2Code == 0` (World total, exactly one row/month).
  Do NOT sum all partner2 rows — that double-counts the World-total row + per-country
  breakdown → ~2× too high.** `netWgt` is in kg → ÷1000 = tonnes.

**ALWAYS calibrate a new source against a known public anchor before trusting it.**
Here 2024 Jan+Feb summed to 2932.1t, matching LBMA's published "2932t" exactly →
口径 confirmed correct. (Bad first attempt summing partner2 gave ~2× → caught by this
check.)

Related: WITS (World Bank) is the same UNSD data with a UI; ChartForest only has
$-total, not the metal tonnage.

**Short-history honest labeling:** when the free monthly source only reaches back N
years (<5), use an honest rolling window (e.g. "12-month rolling mean") and LABEL it as
such on the chart — never a fake "5-year average" without 5 years of data behind it.

## Data-honesty on premium charts (WGC gold premium)

WGC goldhub xlsx `Indian premiums-discounts` sheet = daily India gold domestic
premium/discount in US$/oz (ICE/MCX/RBI/NCDEX, 5-day MA), 2012→present; a bonus
`Chinese premiums-discounts` sheet goes back to 2003. This is the REAL data for a gold
premium chart — richer (daily) than the monthly reference figure. If the user's
reference figure was for SILVER premium (Metals Focus, paywalled), do the GOLD premium
from WGC real data and LABEL the chart honestly as gold ("本图为黄金 premium…白银 premium
数据源为付费商业源，待补") rather than mislabeling or fabricating silver.

## Automation-vs-safety when a source needs the user's login (WGC goldhub)

WGC goldhub xlsx needs an account login to download; there's no free API. Slow-moving
data (premium is a weeks/months trend even if daily-stamped) → daily auto-login has low
marginal value. Offer Chao the tradeoff explicitly (he decides by number), preferring
the SAFER option:
- **A. Full-auto** — store account creds in `.env` (gitignored, never echoed), cron
  logs in daily and downloads. Must first probe the download mechanism (fixed xlsx URL
  vs button+one-time-token → browser automation).
- **B. Semi-auto (recommended)** — user occasionally drops a fresh xlsx into a watched
  directory; cron auto-parses. No password handling → safest, and enough for a slow var.
- **C. Status-quo** — user sends xlsx every few weeks, agent re-runs the parse script.
Do NOT default to auto-storing credentials for a low-frequency source without asking.
