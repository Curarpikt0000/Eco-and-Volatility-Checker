# Silver volume ranking, Yahoo limits, option/COT sentinels (2026-10-16)

## Yahoo SI=F volume facts (measured)
- Intraday history limits: 1m ~7-30d, 5m/30m 60d only (30m with range=1y is HTTP 422), 1h up to 730d. For "largest 30-min in a year" you cannot get it; say so, use 1h for the long window.
- Cross-check passed: 1m/5m/30m/1h sums agree exactly for the same window.
- **Yahoo 1d bars for SI=F are unusable for volume** (many days 0 or tens of lots). Rebuild daily volume by summing 1h bars per CME trading day (US-Eastern, day rolls at 18:00 ET), keep days with >=15 hourly bars.
- **Filter by full date, never "MM-DD"**: a 2y series makes "10-14" match 2025 too and produced a fake 19,560-lot hour. Same bug class as year-less date keys.
- Yahoo SI=F vs TradingView SI1! volume differ (contract mix); a user-read figure (e.g. 820 lots) may not match any Yahoo bar. Report the mismatch, don't force it.
- Conversion: 1 COMEX silver lot = 5,000 troy oz = 155.5 t/1000 lots-ish (1 lot = 0.1555 t). Volume in tonnes is notional turnover, not physical movement.
- Annual mine production anchor (Silver Institute World Silver Survey 2026, via miningvisuals.com cites; PDF not opened): 2025 mine 846.6 Moz (~26,300 t, +3% y/y), recycling 197.6 Moz, demand ~1.13 Boz, deficit 40.3 Moz; 2024 mine 819.7 Moz (silverinstitute.org supply-demand page). State which year when quoting.

## Option / COT sentinels (built no_agent crons)
- Root cause of one real row in Notion DB_OPTVOL: tools/snapshot_optvol.py was never scheduled; only the manual 9/21 run existed. Created cron `eco-vol-optvol-snapshot` (30 6 * * 2-6 JST, script eco_vol_optvol_snapshot.sh, silent on success). Log goes to scratch/ (logs/ is NOT gitignored).
- `eco-vol-cot-sentinel` (0 6 * * 6): fires only if weekly change of swap-dealer/managed-money/producer net exceeds 2 sigma of 3y weekly changes (|d|>2sigma occurs 4.5-7.7% of weeks). Do NOT use relative % thresholds: silver MM net is a few thousand lots, >15% weekly moves happen 44.5% of weeks. COT data lags (Tuesday positions, published Friday), cannot answer intraday questions.
- Dry-run pattern: stub notion upsert/read_back, run the real main(); sandbox-copy the sentinel with the fetch stubbed to test five paths (silent real data / fires on injected -20000 lots / same-period dedupe / stale data silent / fetch failure prints error).

## KOL backfill waves
- kol_new_backfill.sh refuses to restart once STATUS is DONE the same day and re-picks the same least-covered people. For wave 2 copy it to /tmp, give each wave its own scratch dir and skip people already tried today.
- Yield for people missing only 1 month is ~1 item/person (5 from 6 people): not worth full waves.

## X posts store merge
- data/x_backfill/web_rows/<handle>/<day>.json -> rows have id/when/who/text/reply/quoted/url; the same post repeats across day files (7,822 rows -> 4,773 unique). Merge into x_posts_store.json with source='web', URL-handle must equal owner, drop replies, never overwrite API rows, back up first, assert count after.
