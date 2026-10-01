# Batch field-enrichment: two-stage probes, control groups, and silent parser pollution

Session 2026-08-25, Eco-and-Volatility-Checker. Task: fill in `youtube_channel_id` for a
122-person KOL roster where only **2 people** had one — so the Shorts collector (already fixed
and working) only ever ran for 2 of them.

Companion to `kol-roster-and-drilldown-sections.md` (roster *fields* and rendering). This file is
the **method for populating a field across a whole roster** when the value must be discovered
per-person and a wrong value is worse than a blank.

Outcome: 2 → 45 people, 52/52 picks verified, 0 wrong-handle, 68 honest nulls.

---

## 1. ★★ Two-stage split: expensive I/O to a script, semantic judgement to agents

First attempt: 6 subagents, each given 20 people, told to search *and* decide. **All 6 hit the
900s wall with zero output written.** They were not idling — 40–55 API calls each — the work is
just arithmetically impossible: 20 people × ~5 candidates × ~4 HTTP calls, serially, per agent.
Everything died before the write.

The split that worked:

| stage | who | why |
|---|---|---|
| **① discovery / probing** | plain Python script, `ThreadPoolExecutor(6–8)` | HTTP is parallelisable and needs zero reasoning |
| **② judging which candidate is really this person** | offline subagents, **network tools forbidden** | pure semantics over a local JSON, no I/O to time out |
| **③ verification** | parent, direct probes | never trust a child's identifier (§4) |

Numbers: **120 people / 676 candidates / 0 failures / ~430s** for stage ①. Stage ② then took
~250s for all 6 agents because they only read one local file each.

Stage ① writes **one file per person** (`scratch/kol_enrich/probe/<id>.json`), so an interrupted
run resumes for free and nothing is lost to a timeout.

For stage ②, state the ban explicitly in the task context — *"OFFLINE JUDGEMENT — DO NOT USE THE
NETWORK (no web_search/curl/yt-dlp)"* — otherwise agents "helpfully" start verifying online and
you are back to the 900s wall.

> Generalises to any *"go find attribute X for all N entities"* task: if an agent must both
> fetch and decide, it will time out at N far smaller than you expect.

---

## 2. ★★★ The self-rolled HTML parser that returned 100% garbage — silently

For the probe I wrote my own `requests` + regex scraper of the YouTube channel page to get
"latest video title / subscriber count / which tabs are active", instead of using
`src/fetchers/youtube_shorts.py` — **the yt-dlp path this very repo had already debugged**
(cookies + `player_client=web_safari` + deno on PATH).

Result: **1258 of 1258 tab records** carried `latest_title = "Keyboard shortcuts"`, and
subscriber counts were off by three orders of magnitude (`@strategysoftware` → "19.2M").

Root cause: the channel page HTML **contains no video entries at all** —
`videoRenderer` / `richItemRenderer` / `reelItemRenderer` all match **0 times** (the grid is
filled by a later XHR). My regex therefore walked past the empty `ytInitialData` and matched the
accessibility menu at the bottom of the page.

```python
# The 20-second check that would have prevented the whole detour
for pat in (r'"videoRenderer":\{"videoId"', r'"richItemRenderer"', r'"reelItemRenderer"'):
    print(pat, len(re.findall(pat, html)))     # all 0 → the data is NOT in this HTML
```

This is the **worst failure shape**: no exception, no empty return, every field a plausible
non-empty string. Downstream ran perfectly on 100% garbage.

The fix was to use the library that returns structured data instead of parsing HTML:

```python
yt-dlp --flat-playlist --playlist-end 3 -J \
       --extractor-args youtube:player_client=web_safari,default \
       --cookies <cookies.txt>  https://www.youtube.com/channel/<UC…>/videos
# → channel_follower_count (INT, not the string "19.2M"), entries[].title, uploader_id
#   and, usefully, an explicit stderr "does not have a videos tab" instead of ambiguous emptiness
```

Cost: slower (minutes not seconds for 120 people). Irrelevant — wrong data costs far more.

**Rule: before writing a fetcher for a source, grep the repo for one.**
```bash
grep -rln "youtube\|yt-dlp" src/ --include=*.py     # 30 seconds
```
An existing path also carries its accumulated anti-bot workarounds; a fresh one re-earns every
one of those bruises.

---

## 3. ★ Two cheap detectors for silent pollution

**(a) Distribution check** — any field whose values are suspiciously uniform is a red flag:
```python
from collections import Counter
print(Counter(x["latest_title"] for x in items).most_common(3))
# ("Keyboard shortcuts", 1258) ← stop everything, the parser is wrong
```
Run this on the probe output *before* handing it to stage ②, not after.

**(b) Control group** — seed the batch with 1–2 entities whose answer you already know:
```python
CTRL = [{"id": "__CTRL_mkbhd",   "cid": "UCBJycsmduvYEL83R_U4JriQ", "handle": "@mkbhd"},
        {"id": "__CTRL_kinesis", "cid": "UCXJEH6DxUixkTYhH4XxI7kQ", "handle": "@KinesisMoney"}]
```
If the controls don't come back right, **every business row is untrustworthy** — don't even read
them. Post-fix the controls returned `@mkbhd / 21,100,000` and `@KinesisMoney / 64,800`, which is
what made the 52 real results reportable.

---

## 4. ★ Verify subagent-supplied identifiers at the parent, always

Children return IDs that *look* right. Before anything touches the roster, the parent re-probes
every pick and compares the handle it actually resolves to:

```
54 probes (52 picks + 2 controls) → 0 failures, 0 handle mismatches
```

Only then run the apply script. This is the same "child summaries are self-reports" discipline as
elsewhere, made concrete: the artifact to verify is the **identifier**, and the check is a live
lookup, not a re-read of the child's JSON.

---

## 5. Judging rules that produced the right answer (including 68 nulls)

The task file given to the judging agents encoded these; they matter more than the model:

- **`null` is a correct, expected answer.** 68/120 were null. Most people in a macro/finance
  roster simply have no personal channel. Picking a plausible-looking impostor puts someone
  else's content into the daily brief every day — strictly worse than a blank.
- **Subscriber count is not identity.** Real traps in this batch: `@LateNightSeth` (5.3M, a US
  talk show), `@Athosgamer` (17.3M, a gamer), `@daydrian` (4.6M, comedy) — all genuinely large,
  all the wrong person.
- **Video titles are the strongest signal.** Four same-name candidates for one analyst separated
  instantly by content: a Spanish-language trading channel, `"Lil Bro Busted His Head!"`, a
  photography channel, and `"<Name> on Why Investors Should Attend Conferences"` ← the real one.
  This is exactly the field the broken parser had destroyed, which is why v1 judging was worthless.
- **Institution channels count.** When the person publishes under their firm, the firm's channel
  is the right answer (Kinesis Money, First Majestic, DoubleLine, ARK…). Record it with a note.
- **`- Topic` auto-channels are never the answer** (YouTube-generated, no uploads).
- **All three tabs.** `/videos` empty ≠ dormant — many publish only Shorts. Only all of
  `/videos` + `/shorts` + `/streams` empty means no collection value.

Apply only `confidence: high` **and** parent-verified; park medium/low in
`_needs_review.json` for a human. Here: 43 applied, 9 parked.

---

## 6. ★ When several independent downstreams report the same anomaly, believe them

All **6** judging agents independently wrote, unprompted, some version of *"every candidate's
`active_tabs` is `latest: null` / title `"Keyboard shortcuts"` — the activity rule was unusable,
I judged on name and subscriber scale only."*

They did not paper over it, and that report is what exposed my parser bug. Two takeaways:

- **Treat convergent downstream complaints as an upstream signal.** Investigate the producer
  before questioning the consumers.
- An agent that says *"this input is unusable, here's what I could still do"* is behaving
  correctly. Preserve that by making "the data looks broken" an explicitly allowed output in the
  task description.

---

## 7. Roster-mutation discipline (the SSOT rule, mechanically enforced)

The roster's SSOT is Notion; this agent may **fill fields, never add or remove people**. The apply
script enforces it rather than relying on care:

- refuses to create or delete records; only writes empty `youtube_channel_id` / `youtube_handle`
- if a field already holds a *different* value → **do not overwrite**, log to review
- timestamped `.bak` before writing (and add `*.bak` to `.gitignore` — these are local
  provenance, not repo content)
- reads back and prints the coverage count afterwards (`122 people, 45 with channel id`)

**Verify the diff semantically, not by line count.** Git showed all 122 records changed, which
looks like exactly the kind of accident this rule exists to prevent. A key-by-key comparison
against `git show HEAD:` proved the truth: `122 → 122 people, 0 added, 0 removed`, only 44
records with real field changes — the rest was JSON re-indentation.

```python
old = json.loads(subprocess.run(["git","show","HEAD:data/kol_registry.json"],
                                capture_output=True, text=True).stdout)
# compare by id → report added / removed / changed-fields counts before committing
```
Never report contamination from a line-diff alone; diff the parsed objects.
