# Backfilling time-series rows without fabricating history

Distilled 2026-08-23, Eco-and-Volatility-Checker (KOL opinion history), but the rules are
generic to **any** "go find historical records and merge them into an existing per-entity
time series" job.

## ★ The bug I shipped and had to roll back: date-proximity matching

Task: attach newly-written summaries to existing history rows. I keyed the merge on
**(entity, nearest date)** — for each file, take the summary whose date is closest/next.

Result: **1188 inputs produced 2160 written rows**, and a content cross-check showed
**972 rows carried a summary belonging to a DIFFERENT observation** (e.g. a 2025-12-18
opinion stamped with an 2026-04-08 write-up). That is not a merge bug, that is
**manufactured history**. Rolled back wholesale from a pre-run directory copy.

**Why it slipped past casual review:** the log said "wrote 2160 rows" and every row looked
well-formed. Row counts and schema validity cannot detect mis-attribution.
Only comparing the *content* of the joined pair catches it.

**The fix — match on content identity, never on date proximity:**

```python
key = (entity_id, comments_text[:80])   # the observation's own text IS the key
```
When one opinion spans several daily snapshots, its text is byte-identical across them, so a
content key naturally covers the whole span **and cannot bind to a neighbouring observation**.
Guard rail: if the input lacks the text field, **refuse the merge** rather than degrade to a
date guess.

## Window-bounded backfill: hard-validate every date

When you dispatch subagents to "find this person's opinions between A and B", the failure mode
is a subagent finding an undated page and **assigning it a plausible date inside the window**.

Put the rule in the child prompt in these words:
> 拿不准日期的宁可不要 — 把无日期内容随便标个日期就是伪造历史。
> 窗口内确实搜不到 → 返回空数组 + note 写明原因。**宁可 0 条也不凑数。**
> 父端会独立复核每一条的日期，越界一律拒收。

Then **actually do the parent-side re-check** — never trust the child's self-report:

```python
for rec in records:
    d = rec['date']
    if not d:                      reject('no date')
    elif not (w_from <= d <= w_to): reject(f'out of window {w_from}~{w_to}')
    if not rec.get('source'):       flag('no source url')
```
On the 88-person / 284-row run this returned **0 out-of-window, 0 undated, 0 source-less** —
and the children had additionally self-removed an interview that fell one day past the bound
and de-duplicated rows landing on the boundary date. Telling children the parent audits them
measurably improves what they return.

## Merge-script invariants worth hardcoding

1. **Date hard-validation** — outside the window ⇒ reject + report (never silently clamp).
2. **Same-date-same-text dedup** — re-runs must not stack duplicates.
3. **Append-only** — never overwrite an existing row; new evidence adds, it does not replace.
4. **Idempotent** — running twice equals running once.
5. **Back up the whole data dir first** (`cp -r data/... scratch/backups/<name>_<date>`).
   This is what made the 972-row rollback a non-event.

## Honest-coverage reporting

Do not let a coverage target push you into inventing rows. Report the shape truthfully:

- Zero-result entities are fine **when the reason is stated**: deceased (no new opinions can
  exist inside the window), same-name ambiguity that could not be resolved, a window only
  5–6 days wide with no public output in it.
- Distinguish **"strictly ≥365 days"** from **"substantively a year (≥355 days)"** and say
  which you are quoting. On this run: 35 strict vs 52 substantive of 122.
- When many entities cluster just short of the line (here: earliest record 2025-08-24→09-02,
  1–10 days shy), say plainly that **this is where their public record starts** — an archive
  boundary, not a gap you failed to fill. Do not backfill past a source's real beginning.
- Quote the movement, which is the honest headline: **80 entities had their history start
  pushed earlier, average 120 days, max 361 days.**

## Subagent batching for this shape of work

- 6 concurrent children; ~7–10 entities each; 2–4 network calls per entity.
- **Mandate incremental flush: "every 3 entities, overwrite the output file."**
  One child hit the 900s wall on this run — it had already persisted 160/198 rows, so the
  repair was a 38-row top-up instead of a lost batch. This single line is why nothing was lost.
- Deep gaps first: sort the work queue so the biggest windows run early, keeping the tail short.
- Tell children the display layer may show `ANONYMIZED_PERSON_N`; they must **read the real
  name from the input JSON on disk** and search with that.
- Same-name disambiguation is a real cost centre here — children correctly separated analysts
  from an identically-named palaeontologist, novelist, footballer, and painter. Ask for it
  explicitly, and require third-party biographies be judged **not** the subject's own books.

## Related
- `references/kol-roster-and-drilldown-sections.md` — roster SSOT + drill-down rendering
- `references/report-coverage-vs-collection-coverage.md` — the reporting-side sibling lesson
