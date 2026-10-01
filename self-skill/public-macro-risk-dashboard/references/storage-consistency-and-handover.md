# Storage consistency + dashboard handover (Eco-and-Volatility-Checker)

Distilled 2026-08-18 from Chao's review of the daily-scan pipeline's data storage.
Two durable lessons for ANY daily-scan / KOL-tracking dashboard, plus the
handover.md structure Chao asked for.

## 1. Roster-driven vs queue-driven coverage (the KOL "does cron cover ALL lists?" trap)

A daily-scan pipeline usually grows TWO KOL data paths with DIFFERENT coverage guarantees:

- **Daily direction scan** — reads the roster (`kol_registry.json`) filtered `active==true`,
  count NOT hardcoded, so new KOLs auto-include. ✅ Full-coverage, idempotent every run.
- **1-year history backfill** — queue-driven from `backfill_queue.json`, marks each person
  `done` once. ⚠️ **NOT idempotent**: if the roster later gains a KOL, or an existing KOL
  gets a new `search_term`, the one-shot queue does NOT re-scan them. So "cron covers all
  lists every run" is FALSE for the backfill path.

**Rule**: any "cover everything" cron must be **roster-driven, not queue-driven**. Make
backfill diff the roster's active KOLs against the backfill store's keys each run, and
re-queue anyone whose `backfill_date` is stale (e.g. >90 days). That converts a one-shot
queue into a self-healing "eventually covers + refreshes every active KOL" guarantee — which
is what the user actually wants when they ask "can the cron cover all of one KOL's lists?".

## 2. Scattered-per-file JSON is tech debt; consolidate by ROLE not blindly

A long-running pipeline accumulates scattered JSON. When the user asks "can we unify into
one file?", the answer is layered — decide per role, don't merge everything:

- **Roster / SSOT** (`kol_registry.json`) — keep as the single source of truth. add-only.
- **Per-entity history** (`kol/backfill/<id>.json`, one file per person) — 🔴 MERGE into one
  `kol_backfill.json` as `{id: {history, backfill_date, ...}}`. Per-file scatter gives no
  benefit and creates "which file holds whom" ambiguity + non-atomic writes.
- **Time-series snapshots** (`kol/daily/YYYY-MM-DD.json`, one per day) — KEEP per-day. This
  is a legitimate append-only log (weekly diff needs history accumulation). Merging would
  grow unbounded and lose cheap incremental append. Just DOCUMENT it as an append-log, not
  "scattered state".
- **Dead files** (`kol_batch_1/2/3.json` with zero code references) — 🔴 DELETE. Verify zero
  references first (grep src/), then remove.
- **Root-level dated dumps** (`ai_analysis_YYYY-MM-DD.json` at repo root) — move under a
  subdir (`data/ai_analysis/`) or make a single append log.

**Migration discipline** (Chao's铁律): add-only + verify-after-write + no data loss. Pilot
the merge on a COPY first, verify every entity's history survives, switch the reader, THEN
delete the old dir. Never delete before the new store is proven readable.

**Diagnosis first**: before proposing a fix, `find data -name "*.json" | wc -l` and grep
each candidate for code references to separate live files from dead remnants. In this project
the count was 311 KOL JSONs across 4 locations — the scale itself was the signal.

## 3. handover.md structure (whole-dashboard inventory Chao asked for)

When Chao asks to "organize everything about the online dashboard into a handover.md on my
GitHub", produce ONE class-level doc covering these sections (this exact shape was accepted):

0. **TL;DR storage-consistency answer** — put the direct answers to the user's pointed
   questions FIRST (the coverage table, the unify-or-not table), before the reference material.
1. System overview — purpose, stack, key files.
2. Core indicators table — `key | group | source | sell-trigger? | condition` for every metric.
   Explain the source TYPES (fred/web/search/derived) once.
3. Bottom panels table — `panel | fetch function | source | update freq` for every non-card panel.
4. Notion tables/columns — one row per DB: `key | purpose | row title | key columns`.
5. Update frequency — the ACTIVE crons only (grep enabled==true), + per-panel data freshness.
6. KOL extraction method — roster SSOT, the numbered daily-scan steps, special-KOL classes,
   the search-backend note, the backfill path.
7. Storage-consistency issues — the §1/§2 diagnosis + a proposed target layout + migration discipline.
8. Known open issues / tech debt — a severity-tagged table.
9. Discipline (non-negotiable) — never-fabricate, add-only roster, static thresholds,
   write-then-read-back, red-line scan, strip internal URLs before public push.

**Verify before publishing**: read back the key COUNTS in the doc against the real files
(`find | wc -l`) so numbers are accurate; red-line scan for internal URLs; the one legitimate
hit is the doc's OWN discipline line telling future agents to strip internal URLs.
Commit `--no-gpg-sign`, `git pull --rebase` first (backfill cron may be mid-write), push
background (foreground git times out), and verify the push landed (`old..new main -> main`).
