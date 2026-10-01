# Two agents in one repo + one Notion workspace — ownership, collision, recovery

Realized on Eco-and-Volatility-Checker 2026-08-26. A **second agent was actively building in the
same `~/Projects/Eco-and-Volatility-Checker/` and writing the same Notion workspace** while I worked.
This is NOT the cron-collision case (see `shared-repo-cron-collision.md`) — that is a scheduled job
in my own lane. This is a peer agent with its own `src/*.py`, its own cron steps, and its own tables.

## Detecting a live peer agent (do this FIRST on any multi-hour session in this repo)

Signals, in order of how fast they appear:

```bash
git status --short                  # files you didn't create/edit appear as ?? or M
ls -la --time-style=+%H:%M src/     # timestamps INSIDE your session window that aren't yours
```
Then cross-check the cron table and the `.env`:
- a cron job whose `created_at` falls **inside your session** that you did not create
- a new `DB_*` key in `.env` you didn't add
- a daily-cron prompt gaining a step (e.g. "步骤 3.9") referencing a module you never wrote

Hard confirmation used here: a Notion table grew **276 → 895 rows while I was mid-run**, with a date
range that was not mine. Row-count drift during your own idle time = someone else is writing.

> Do not assume "another agent" means another machine or another workspace. Here both agents ran on
> the SAME VM, in the SAME repo, reading the SAME `.env` and therefore the SAME `NOTION_TOKEN` — so
> they hit the same Notion workspace. I initially told Chao "two workspaces collided", which was
> wrong and confused him. Say **"same workspace, two writers"** when that's what it is.

## Chao's ownership rule (2026-08-26, stated as having NO exceptions)

Ownership is decided by **data lineage**, not by convenience:

| Where the data came from | What you must do |
|---|---|
| You scraped it / your LLM produced it | Build **your own DB** + **your own data-source files** |
| You only READ someone else's table | Do NOT rebuild it. Stay read-only. |
| Someone else created/maintains the table | Do not touch it at all |

Corollaries Chao stated explicitly:
- A table that is already a **SSOT owned by him** (e.g. the Notion "KOL List" roster) needs no
  mirror DB — reading it is enough.
- "只要是你去抓到的数据，而不是别人抓到的数据，你就要自己建，没有任何例外."
- Cost is not an accepted reason to skip the split. When told 17 tables → 34 tables doubles API
  writes, he answered build them anyway. **Offer the cost estimate, then comply.**

Practical consequence: run a lineage audit before proposing scope. `grep` every writer:
```bash
for d in DB_A DB_B ...; do echo -n "$d: "; grep -rl "$d" src/*.py | xargs -n1 basename | tr '\n' ' '; echo; done
```
Here that audit overturned my own earlier guess: I had proposed rebuilding only 3 report tables,
but **all 17 `.env` tables were written by my own code** (CFTC/NY Fed/Treasury/FRED/OFR/SEC 13F).
Correct answer was 18, not 3.

## Failure that actually happened: writing 93 rows into the peer's table

I wrote into the peer's `DB_KOL_VIEWS` before noticing it existed. What made it **fully reversible**
was that every write recorded its `notion_page_id` back into my own store:

```python
pg = n.call("/pages", "POST", {...})
ks.set_notion_page(r["uid"], pg["id"])     # ← this is what saved the cleanup
```
Recovery = select rows with a non-empty `notion_page_id`, `PATCH {"archived": true}`, clear the id.
93/93 archived, 0 failures, 0 residual ids.

> **Always persist the remote page/row id you created, on the same transaction as the local record.**
> Without it, "undo my writes but not theirs" is unsolvable in a table you share.

Note the count grew from the 30 I *thought* I'd written to 93 — a killed bulk run had already written
more before the kill landed. Trust the recorded ids, not your memory of how far a job got.

### The hard gate that prevents a repeat
```python
FOREIGN_DBS = {"<peer table id>", "<roster SSOT id>"}

def _assert_not_foreign(db_id: str):
    if (db_id or "").replace("-", "") in {x.replace("-", "") for x in FOREIGN_DBS}:
        raise RuntimeError(f"REFUSED: {db_id} 属于其他 agent, 本模块禁止写入")
```
Compare **dash-stripped** — Notion ids appear both with and without hyphens and a literal compare
silently misses. Call it at the top of every write path, and unit-test that it refuses both forms
and allows your own id.

## Notion API traps hit in this session

**1. `/search` fuzzy-matches and will hand you the WRONG table.**
Using `/search?query="KOL 观点历史库"` returned the *peer's* "KOL 每日观点" table. My idempotency guard
read that as "already exists" and would have blocked creating my own table forever.
Correct existence check — enumerate the parent and compare titles exactly:
```python
ch = n.call(f"/blocks/{PARENT}/children?page_size=100")
hit = [b["id"] for b in ch["results"]
       if b.get("type") == "child_database" and b["child_database"]["title"] == TITLE]
```

**2. A database's `parent` cannot be changed via API.** If you create a DB under the wrong page, only
a human dragging it in the UI can move it. Decide the parent page BEFORE creating.

**3. Losing access mid-session is normal and is a useful signal.** After the peer's table was locked
down, my integration got `404 object_not_found ... Make sure the relevant pages and databases are
shared with your integration`. That is permission-layer isolation working, not a bug — it is stronger
than the code gate. Report it as such.

## Sub-page separation: justify it on ownership, NOT on performance

Chao asked whether many DBs under one page slows reads / paging. **Measured it rather than guessing:**

| operation | median |
|---|---|
| parent page children (26 items) | 0.404s |
| sub-page children (19 items) | 0.341s |
| **empty** table @ sub-page query | 0.728s |
| 44-row table @ parent page query | 0.475s |

An *empty* table was slower than a 44-row one → the variance is network noise, not sibling count.
`/databases/{id}/query` addresses the DB directly, so the number of sibling tables under the parent
is irrelevant. The only real cost is **row count → pagination**: 3,608 rows = 37 pages ≈ 26s.

So: sub-pages are still correct here, but for **ownership legibility, blast-radius, and the ability
to revoke sharing per page** — not speed. Say that honestly instead of accepting the perf premise.
Real speedups are UID-keyed idempotency and a `since=` incremental filter, plus accepting that
writes are dominated by the 3 req/s limit.

## The SSOT store pattern (three lanes → one truth → three projections)

Before: `data/kol/backfill/*.json`, `data/kol/daily/*.json`, and ad-hoc `scratch/<batch>/out/*.json`
were merged **only in memory at render time**. Consequences: a new entity's backfill needed manual
format-wrapping to be visible, Notion was not on the chain at all, and source-coverage was unmeasured.

After: `data/kol_store.sqlite` as the single write target.

```
daily crawl ─┐
backfill    ─┼→ upsert() → kol_store.sqlite ─┬→ dashboard
one-off     ─┘   (sole entry point)          ├→ *_export.json  (git-diffable)
                                             └→ Notion (idempotent, UID-keyed)
```

Design points that mattered:
- `uid = sha1(entity_id | date | direction | text[:120])` → cross-source dedup is free, and it
  doubles as the Notion idempotency key so the three points reconcile 1:1.
- **`origin` rank** (`manual > backfill > daily`) decides who may overwrite whom; a blank value
  never overwrites a real one.
- `ingest_records(list, ...)` accepts a **bare list** — that is what removes the "new entity needs
  format conversion before it shows up" problem permanently.
- Keep a `source_status` column (`ok`/`missing`) so coverage is a query, not a vibe.

### Cut over behind a fallback, and prove equivalence before switching
Point the existing accessor at the store, keep the legacy merge as an exception fallback so the
dashboard can never white-screen, then diff old vs new **per entity**:

```
144 entities: 140 byte-identical, 4 differing
  3 = the newly-merged entities (the intended fix)
  1 = ORDER-ONLY (same set, two records same date, intra-day order differs)
```
Investigate every non-identical entity until it is *explained*. Do not accept "close enough" — the
ORDER-ONLY one looked like a real diff until I printed both sides and saw identical sets.

Final tri-point reconciliation to report: `store 3608 = notion 3608, gap 0, dup_rows 0,
source_ok 1044 = notion_source_filled 1044`, verified by an **independent re-query**, not by the
same function that did the writing.

## Diagnosing a coverage gap: segment by time before blaming the collector

I reported "only 16% of daily snapshots carry a source URL — the crawler isn't saving them."
**That was wrong, and the mean was hiding a step change:**

```
>= 2026-08-22 : 490/495 = 99.0%     ← pipeline is healthy
<  2026-08-22 : 0%      (2,559)     ← pure historical backlog
```

`git log -S'sources' -- src/external_data.py` found the commit that added the field. The fix was
therefore not "improve crawling" (already fine) but **quantify + alert + backfill**:
`source_gap_report()`, `assert_source_quality(min_rate=90)`, `missing_source_candidates()`, and an
`apply_source()` that refuses any value not starting with `http` so backfill can't fabricate.

Also: some `missing` rows are *correct* — an entity who died in 1977, or a name that three searches
confirmed has no market commentary, **should** have no source. Don't chase 100%.

> General rule this cost me twice: **never diagnose from an aggregate. Segment by time first, then
> `git log -S` the field to find when behaviour changed.**

## Reporting discipline for this situation

- When you discover a peer writer mid-run, **stop the bulk job immediately** rather than finishing.
  I killed a 3,292-row run at ~93 rows; finishing would have made cleanup 35× larger.
- Correct your own earlier false claims out loud. I had said "Notion 上根本没有 KOL 数据库" after
  checking only the 17 ids in `.env` — the table existed with 275 rows. Say plainly that you asserted
  an absence you had not verified.
- Do not claim someone else's artifact as your own work, and do not silently adopt it. When a cron
  job and a `src/kol_notion.py` appeared mid-session, the right move was: name them, state they are
  not mine, and refuse to modify them.
- When told "don't touch others' stuff", that includes the **shared daily-cron prompt** if a peer is
  editing it. Put your own guardrails in your own module instead of editing the contested file.
