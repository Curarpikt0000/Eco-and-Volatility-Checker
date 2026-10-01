# Backfill correctness & daily-report coverage parity

Two silent-failure classes hit in one session (2026-08-23, Eco-and-Volatility-Checker).
Both look like success in the logs. Both need an **independent check by the parent**, not
the worker's self-report.

---

## 1. Backfill mis-attribution — the matching key is the whole ballgame

### What happened
Task: attach richer `detail` summaries to ~2,400 historical KOL opinion entries stored across
per-day snapshot files. First implementation matched by **`(person, nearest date)`** and walked
a range forward.

Log said: `1188 inputs → 2160 rows filled`. Looks like a bonus. It was **972 rows of fabricated
history** — a 2025-12-18 opinion got the summary written for a 2026-04-08 opinion, because
"nearest later date" is a *different opinion*, not the same one spanning days.

### Why the log couldn't catch it
`filled > input` reads as "range coverage worked". Nothing errors. The only way to see it is to
**re-derive the join independently and compare content**, not counts.

### The fix — match on CONTENT, never on date proximity
```python
# WRONG: date-proximity walk invents associations
# key = (person, nearest_date_forward)

# RIGHT: the opinion text itself is the identity
key = (person_id, comments_text[:80])
```
Same opinion repeated across N daily snapshots has an **identical `comments` string** — so a
content key covers the multi-day span naturally *and* cannot cross-attach to a different opinion.

Guards to bake into the apply script:
1. **Refuse to run if the input lacks the content field.** Don't fall back to guessing by date.
2. **Leave unmatched rows blank.** A gap is honest; a wrong fill is fabrication.
3. Idempotent + append-only (never overwrite an existing value).

### Verification that actually works
```python
# independent re-derivation, run by the PARENT after apply
for row in filled_rows:
    src = source_index[(row.person, row.comments[:80])]
    assert row.detail == src.detail          # content agreement, not count agreement
```
Report `mismatched` explicitly. `0` is the only acceptable number.

---

## 2. Date-window hard validation for gap backfills

When subagents research a **missing time window** per entity (`window_from ~ window_to`), the
failure mode is: they find undated content and **stamp a plausible date on it** to satisfy the
"3–8 records" ask. That is manufactured history.

### Prompt-side
- State the window per entity in the input row.
- "Records whose date you cannot verify: **drop them**. Returning `records: []` with a `note`
  is a correct answer. Never date-stamp undated content."
- Tell them the parent re-checks every date and rejects out-of-range — this measurably changes
  behaviour (observed: workers proactively discarded out-of-window items and de-duped against
  the boundary date on their own).

### Apply-side (non-negotiable)
```python
if not (w_from <= rec_date <= w_to):
    rejected += 1                 # out-of-window == undated content given a fake date
    continue                      # never coerce, never clamp
```
Also reject missing date, missing source. Print a rejection breakdown.

### Parent re-verifies, independent of worker claims
Workers reported "date out-of-range: 0". The parent recomputed from the batch window files and
confirmed independently: `out-of-range 0 / no-date 0 / no-source 0`. Do this every time — the
worker's self-report is the thing under test.

---

## 3. Report coverage drifts away from the dashboard silently

### The gap
Dashboard had **45 sections**. The cron's report step named only a 6-part skeleton plus 5 extras.
**30+ sections were being fetched, written, rendered — and never mentioned in the daily report.**
Nobody noticed for months because the report itself looked complete and well-formed.

Separately: the report text said "three central banks" while the fetcher had been returning a
**fourth (ECB) all along**. The data was present in the dashboard the whole time.

### Diagnostic (run periodically, cheap)
```python
# A. sections that exist
secs = re.findall(r'<div class="part-title"[^>]*>(.*?)</div>', html, re.S)

# B. fetchers that exist vs. fetchers the cron prompt actually calls
avail = {n for n in dir(external_data) if n.startswith('fetch_')}
used  = set(re.findall(r'\b(fetch_[a-z0-9_]+)\s*\(', cron_prompt))
print(sorted(avail - used))     # candidates for "collected but unreported"
```
Then read the report step and ask: **does every rendered section map to a named module?**

### ★ The inference trap — burned on this
"Section X isn't in the report" ⇒ **"we're not collecting X"** is WRONG.
I reported ECB as a missing data source. It wasn't; only the report *copy* omitted it.
**Always check the fetcher's live return value before declaring a data gap.**
Cheapest possible probe:
```python
d = fetch_cb_balance_sheets()
print(list(d.keys()))           # -> ['US','JP','CN','_fx','ECB']  … it was there
```

### Report structure Chao asked for (see USER memory)
Fixed module skeleton, coverage over brevity:
- Changed → detail; unchanged → one line. Never drop a module.
- Low-frequency sections with no update still get a placeholder line
  `(quarterly — no update this run)`, so the skeleton stays complete and he can confirm at a
  glance that everything was looked at.
- Final module = **data health**: sources that failed / weren't ready + parser reconciliation
  results. Emit `all sources normal` even on clean days — a silently-dead source is the thing
  this catches.

---

## 4. Editing a long cron prompt without breaking it

The report step lives in a multi-thousand-character prompt that also contains the
`dashboard.generate(...)` call with ~47 kwargs. Prompt edits have repeatedly clipped kwargs and
silently dropped whole sections.

- Back up first: `cp jobs.json jobs.json.bak-<date>-<what>`.
- Splice by locating **step boundaries** (`## step 9` → `## step 1b`), assert both offsets found.
- **Re-verify the kwarg count after every prompt edit.** Extract the call body by *paren
  matching*, not a loose regex — the prompt's prose also contains the literal string
  `dashboard.generate`, and a greedy/loose pattern grabs the wrong span and yields confidently
  wrong counts (seen: "2 args", then "0 args", before matching properly to get 47).

```python
i = prompt.index('dashboard.generate(')
depth = 0
for k, ch in enumerate(prompt[i:]):
    depth += (ch == '(') - (ch == ')')
    if depth == 0:
        body = prompt[i:i+k+1]; break
assert len(re.findall(r'(\w+)\s*=', body)) == 47
```

- Protected files (`AGENTS.md`): an approval timeout is a **refusal**. Don't reroute through
  terminal/execute_code. Record the change in the project's `docs/context-log.md` instead and
  tell the user AGENTS.md still needs their authorization.
