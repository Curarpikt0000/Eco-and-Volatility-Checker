# KOL historical-comments backfill (past-N-months opinion history)

When Chao asks to "backfill all KOLs' past-year comments into the DB" for the
Eco-and-Volatility-Checker KOL subsystem. Distilled from the 2026-08 full backfill.

## Data reality (state this honestly up front, don't over-promise)
- web_search **cannot time-travel** — it returns *currently indexable* content,
  not "what X said on 2025-09-15". So "complete past-12-month comments" is NOT
  achievable for every KOL. What IS achievable: search each KOL's interviews /
  articles / podcast appearances and extract every opinion that carries a
  **source-confirmed date**. Well-covered KOLs (Sprott Money / Kitco / KWN /
  FXStreet / Substack regulars) yield 5–21 dated items each; niche analysts whose
  own site is down and whose content only lives on shared aggregator pages (where
  authorship can't be confirmed) yield 0 — mark `status:"未找到"`, never fabricate.
- Existing snapshots (`data/kol/daily/*.json`) use field **`kols`** (NOT `all`);
  each row already carries `comments`. Prior by_day-DB import is sparse (a few
  KOLs/day); Eco's own daily crawl is dense (full roster). Backfill fills the gap
  BEFORE those snapshots begin.

## Workflow (sample-before-full, per Chao's batch rule)
1. Compute the target set: active KOLs (`active==true`) that have NO
   `data/kol/backfill/<id>.json` yet (diff registry against the backfill dir).
2. **Sample 3 representative KOLs first** (one well-known, one niche/new, one
   another-type e.g. alt/predictions), show Chao the yield, get sign-off, THEN full.
3. Fan out with `delegate_task` in batches (max_concurrent_children = 3), one KOL
   per child, toolset `["web"]`. Each child returns a JSON array of
   `{date:"YYYY-MM-DD"(real source date), direction, comments(中文 50-150), targets, source}`.
   Iron rule in every child prompt: **only source-confirmed dates, never fabricate;
   found nothing → return `[]`.** Alt/prediction KOLs (通灵/占星/末日) use their
   `search_terms` and map to a leaning (崩盘预警→看空), not a strict tradable dir.
4. **Independently re-verify** child output before trusting (subagent summaries are
   self-reports). Land each KOL as `data/kol/backfill/<id>.json`:
   `{kol, sector, backfill_date, source_method, count, history:[...]}`.
5. Commit + push after each batch (public repo Curarpikt0000/Eco-and-Volatility-Checker)
   so nothing is lost mid-run. Red-line scan first (public KOL opinions are safe).

## Two operational pitfalls that bit this run
- **`git commit` "timed out" is a DISPLAY artifact, not a failure.** In this env a
  foreground `git commit` on many new files hits the tool's ~60s wall and reports
  timeout, but the commit actually completed (verify: `git log -1 --oneline`
  advanced). FIX: run commit+push **`background=true, notify_on_complete=true`**
  with `git -c commit.gpgsign=false commit …` — reliable, no false timeout. This
  is the right pattern for any multi-file commit here.
- **web_search backend outage mid-run** → many KOLs come back 0/残缺. Do NOT harden
  that into the data (it's a tool outage, not "no opinions"). Diagnose + swap the
  backend (see `hermes-plugin-development` → "FIRST: is this actually a plugin job")
  — the 2026-08 root cause was SearXNG upstream engines all rate-limited/CAPTCHA'd;
  `hermes config set web.search_backend ddgs` restored it and yields jumped
  (Jim Curry 0→12, Larry Lepard 2→11). Re-run the故障期 KOLs after the fix.

## Resume-on-recovery watchdog (so it finishes unattended)
A 2h cron (`eco-vol-kol-backfill-resume`, agent mode, toolsets terminal/file/web):
health-check web_search with a must-hit query; if empty → silent exit; else diff
registry vs backfill dir, run the next ~4 undone KOLs, commit+push, report REMAIN.
Loops until REMAIN=0. Matches Chao's "reuse cron / automate, don't sit and wait".
