# Packed sub-agent batches for roster backfill (2026-08 run)

Companion to `kol-history-backfill.md`, which covers the one-KOL-per-child shape.
This file covers the **packed** variant (N people per child) and the failure that
forced it, plus verification details learned the hard way.

Read both: that file has the data reality, record format, and the resume cron.

## When the coverage gap appears

23 cycle/esoteric forecasters were appended to `data/kol_registry.json` **without**
running backfill. Their drill-down panels rendered "no archived opinions" — the
feature was fine, the data was absent. Roster showed 133 active vs 99 backfill
files.

**Adding people to the roster is only half the job.** Re-run the coverage diff
immediately after any roster addition:

```python
import json, glob, os, re
reg = json.load(open('data/kol_registry.json'))
kols = reg if isinstance(reg, list) else reg.get('kols', reg)
names = [k.get('display_name') or k.get('name') for k in kols if k.get('active', True)]
slug = lambda n: re.sub(r'[^a-z0-9]+', '_', n.lower()).strip('_')
have = {os.path.basename(p)[:-5] for p in glob.glob('data/kol/backfill/*.json')}
missing = [n for n in names if slug(n) not in have]
print(len(names), 'active |', len(have), 'backfilled |', len(missing), 'missing')
```

## Why the first dispatch lost nearly everything

34 people across 3 children. **All three returned `status: timeout` at 600s**
with 25 / 34 / 27 API calls completed and almost nothing on disk.

They had NOT hung. Live transcripts (`~/.hermes/cache/delegation/live/<id>/task-N.log`)
showed genuine, high-quality work — real `web_extract` calls pulling real article
text. They had simply gathered everything into context intending to write all
files at the end. The timeout erased all of it.

One child had opportunistically written 4 files before dying. Those 4 were
flawless: **19/19 source URLs verified HTTP 200, zero fabrication**, dates spread
across the target window. The research quality was never the problem — only the
**landing discipline** was.

## Rules that fixed it

Put every one of these in the shared spec file the children read:

1. **"Finish one person -> `write_file` immediately -> then start the next."**
   State plainly: *you have a 600s hard timeout; only files on disk survive;
   anything still in your context when you time out is lost.* Children do not
   infer this — they default to batch-at-the-end.
2. **Max 2 `web_search` per person. Do NOT use `web_extract`.** Crawls run 5-15s
   each and are exactly what exhausts the budget. Search snippets normally carry
   date + claim, which is enough to write the record. Rank it explicitly:
   **coverage of everyone beats depth on the first few.**
3. **Order-and-degrade:** process in the listed order; if time runs short,
   writing `count: 0` for the tail is CORRECT — never lose already-gathered
   people to chase unfinished ones.
4. **Progress print every ~3 people** so the parent can watch the live transcript.
5. **8 people per child**, not 11+. Halve it if each person needs a page crawl.

Parent-side: count landed files by mtime rather than reading summaries —
`find data/kol/backfill -name '*.json' -newermt '<dispatch time>'`. A
`status: timeout` batch is routinely a partial success worth keeping; re-dispatch
only the people with no file, never the whole batch.

## Detail traps from this run

**`direction` needs the `另类预言` value.** Enum:
`强烈看多 / 看多 / 中性 / 分歧 / 看空 / 强烈看空 / 另类预言`. Pure timing or prophecy
calls ("date X is the turning point", biblical / astrological / I-Ching channels)
get `另类预言` — do not force a tradeable bull/bear label onto them. Uncertain →
`中性`.

**CJK display names cannot be slugged.** Latin slugging collapses them to empty.
Name those files from the roster's **`id`** field (`id: wuchangye` →
`wuchangye.json`). State it explicitly or children invent a transliteration.

**Merged history elements are dicts; the date field is `first_date`.**
`kol_full_history()` merges backfill + daily snapshots and collapses consecutive
identical opinions into date ranges. Indexing `it[0]` raises `KeyError: 0`.

**Never hand-truncate a URL when verifying.** Probe every returned URL, reading
full strings out of the JSON:

```bash
while read u; do
  echo "$(curl -sL -o /dev/null --max-time 20 \
      -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120' \
      -w '%{http_code}' "$u")  $u"
done < /tmp/urls.txt
```
Shortening a URL for readability produces a bogus 404 and a false fabrication
accusation — hit here when `the-economy-into-2028` got clipped to `...-2026`.
403 = WAF blocking curl (domain is real); 404 on a control-validated probe =
fabricated.

**`count: 0` is a correct answer.** Small CJK esoteric-finance channels genuinely
have few indexable dated posts. An empty drill-down reading "not yet collected"
is honest; padded filler is a P0 integrity breach. Tell Chao up front which
entries are expected to come back empty and why, so a sparse result is not read
as a bug.

## Post-rebuild dashboard assertion

```python
drill = set(re.findall(r'class="[^"]*kol-drill[^"]*"[^>]*data-kol="([^"]+)"', html))
empty = [k for k in drill if k not in DATA or not DATA[k].get('h')]
```
`empty` must be 0 — every clickable card needs content behind it; people with no
history must not render clickable at all.

One person legitimately appearing in BOTH "weekly opinions" and "stance changes"
is by design, not duplication. Real duplication = one person in both a
specialised sector section and the general section. Fix by filtering that sector
out of the general renderer **and recomputing its displayed total**, so the
headline count matches the cards actually rendered.

## Browser console reads can be false-negative

Probing the rendered page via a JS console expression returned
`drillCount: 0, cycItems: 0` and nearly triggered a bogus "HTML is malformed"
diagnosis. The tell: `document.documentElement.outerHTML.length` came back **39**
with an empty `document.title` — the expression had evaluated against
`about:blank`, not the loaded page. Offline parsing of the built HTML showed 184
`kol-drill` occurrences and perfectly well-formed attributes.

**Verify DOM claims by parsing the artifact on disk before concluding the
generator is broken.**
