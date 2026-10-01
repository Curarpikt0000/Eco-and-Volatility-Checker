# Detecting a scraper that fails SILENTLY (honest-None == invisible outage)

Cross-project method, proven 2026-08-25 on the sibling `economic-dashboard-daily-pipeline`
(worked example there: `references/pboc-omo-silent-scraper-gap.md`). It applies directly here
because this pipeline shares the same design: **every fetcher returns `None` rather than
fabricate** (AAII / CBOE / GuruFocus / LEI / BofA / COT web sources).

## The problem this design creates

"Couldn't fetch today" and "this source has been dead for two months" produce the **identical
observable**: field null, job `rc=0`, `last_status: ok`, no error in the log.
Data honesty and silent failure are the same behaviour at the cron layer.

Real case: a Notion field was null for **two months** (an upstream wording change broke the
regex) while every cron ran green. Nobody noticed until the user asked a question about it.

## Detection method (use when auditing "do we actually have X?")

1. **Read the SINK, not the code.** "The scraper exists, is imported, and has a dedicated
   column" was all true while zero data flowed. Reading source would have given the wrong
   answer. Query the actual DB.
2. **Companion-field comparison.** Pull a field known to be healthy from the *same table, same
   write, same cron* alongside the suspect field. One populated + one all-null instantly rules
   out scheduling, auth, API writes, and weekend skips, and localises the fault to a single
   fetcher.
3. **Scan the FULL table (paginated) and report the LAST GOOD DATE.** A recent-15-row window
   said "never worked"; the full 543-row scan showed 15 good rows ending on an exact date — a
   *regression*, not an unimplemented feature. The boundary date usually coincides with the
   upstream change that caused it, so it is the single highest-value clue. Never characterise a
   gap from a small recent window.
4. **`EXIT=0` is not evidence of semantic completeness.** Assert on per-field non-null counts.

## Prevention: a field-freshness audit is MANDATORY for honest-None pipelines

If not-fetching never raises, something independent must notice "never fetched".

Shape that works (implemented as `src/field_freshness_audit.py` in the sibling repo):
- per key field, non-null rate over the last N rows
- `rate == 0` → 🔴 probable fetcher death; `0 < rate < floor` → 🟡 unstable
- always print the **last good date**
- `--quiet`: silent when all green (no_agent-cron friendly), `exit 1` on anomaly
- known-sparse fields (a series that legitimately only starts mid-history) get their own floor,
  otherwise chronic false alarms train everyone to ignore it

**Prove the monitor actually fires.** Widen its window until it hits a known-sparse field and
confirm you get the 🟡 and the non-zero exit. A monitor that has never gone red is not known to
work — it is just an untested script.

## Related pitfall already in this skill

This is the *read* counterpart to the empty-value-overwrite bug in SKILL.md's pitfalls (a failed
fetch PATCHing `None` over a real Notion value). Same root: a source failing quietly. One
corrupts stored history, the other hides a permanent gap. Both are only visible from the sink.
