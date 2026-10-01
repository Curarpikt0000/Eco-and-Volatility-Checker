# Bulk roster attribution: script probes the I/O, agents judge the semantics

Companion to `kol-roster-and-drilldown-sections.md` (roster fields + drill-down UI). This file
covers the other recurring job on the same registry: **filling in a per-person collection field
(`youtube_channel_id`, `source_url`, feed URL) for 100+ people at once**, where each person has
several plausible candidates and picking the wrong one silently poisons the daily feed.

Realized 2026-08-25 taking `data/kol_registry.json` from **2 → 51** people with a YouTube channel.

---

## 0. Why neither pure-agent nor pure-script works

| Approach | Outcome |
|---|---|
| 6 subagents, each given 20 people, told to search + verify | **6/6 hit the 900s wall, zero output.** Not lazy — 40–55 API calls each, dying before the write |
| One script picking the top search hit | Picks impostors. `kyle_bass` → a bass-guitar tutorial channel |

The work splits cleanly along a seam:

- **Expensive, parallelisable, deterministic I/O** → a script. 120 people × ~6 candidates × 3 tabs
  in **~7 min** at 6 workers.
- **Cheap, serial, judgment-heavy disambiguation** → offline agents reading a local JSON. 6 batches
  of 20 in **~4 min**, no network at all.

**Give the judging agents zero network access.** They read one local file, think, write one local
file. That is what makes them fast and what makes them impossible to time out.

---

## 1. ★★ Use the採集 path the repo already proved — do not hand-roll a second parser

The single most expensive mistake of the session. I needed "latest video title / subscriber count /
which tabs are active" and wrote a `requests` + regex parser against the channel page HTML,
reasoning it was lighter than `yt-dlp` since I only wanted titles.

Result: **1258 of 1258 tabs came back with `latest_title = "Keyboard shortcuts"`.** 100% garbage.
Subscriber counts were off by three orders of magnitude (a ~125K channel read as 19.2M).

Root cause — the data is simply **not in the HTML**:

```python
for pat in (r'"videoRenderer":\{"videoId"', r'"richItemRenderer"', r'"reelItemRenderer"'):
    print(pat, len(re.findall(pat, html)))     # → 0, 0, 0   (filled in by a later XHR)
```

With nothing to match, the regex ran on down the document and hit the accessibility menu.

**This is the worst failure shape available:** no exception, no empty value, a well-formed string in
every record. Six downstream consumers ran happily on it.

The repo already had `src/fetchers/youtube_shorts.py` using `yt-dlp`, including its anti-bot
configuration. Switching to it fixed everything at once:

| Need | hand-rolled regex | `yt-dlp --flat-playlist -J` |
|---|---|---|
| latest title | accessibility menu text ❌ | `entries[].title` ✅ |
| subscribers | mis-anchored, 3 orders off ❌ | `channel_follower_count` — **an int, not `"19.2M"`** ✅ |
| real handle | another regex to write | `uploader_id` ✅ |
| "tab doesn't exist" | indistinguishable from empty | explicit `does not have a videos tab` on stderr ✅ |

Cost: minutes instead of seconds for 120 people. Irrelevant next to shipping fabricated data.

> **Reflex before writing any fetch code:** `grep -rln "<source-name>" src/ --include=*.py`.
> An existing path also carries accumulated anti-bot workarounds you would otherwise re-discover.

## 2. ★ Two probe-integrity checks that would have caught §1 in seconds

### Control group — validate the probe, not just the data
Seed every batch with 1–2 samples whose answer you already know:

```python
CTRL = [{"id": "__CTRL_mkbhd", "cid": "UCBJycsmduvYEL83R_U4JriQ", "handle": "@mkbhd"}]
# @mkbhd resolving to ~21.1M subs + matching handle ⇒ the probe itself is sound.
# Control fails ⇒ every business result is void; do not look at them yet.
```

### Uniformity check — an identical value across all rows is contamination, never luck
```python
from collections import Counter
print(Counter(x["latest_title"] for x in items).most_common(3))
# (…, 1258) as the top entry ⇒ stop, the parser is broken
```
One line, catches the entire class. Run it on any bulk-extracted field before consuming it.

## 3. ★ Judgment rules that produced 43 high-confidence picks and 68 honest nulls

Put these in the batch `INSTRUCTIONS.md`; they are what makes the output trustworthy:

1. **Content title is the strongest signal**, not name similarity. Real case — four channels all
   named some form of "Adrian Day" (an investment analyst):
   `@adriandaytrader` (Spanish-language trading) · `@daydrian` ("Lil Bro Busted His Head!") ·
   `@adriandayphotography` (cameras) · **`@AdrianDayInvest`** → *"Adrian Day on Why Investors
   Should Attend Conferences"* ✅. Only the content separates them.
2. **`null` is a correct answer, and it should be the majority.** 68/120 here. Most people simply
   have no channel. A wrong pick feeds someone else's content into the daily brief every day —
   strictly worse than a blank.
3. **High subscriber count ≠ right person.** Real traps in this batch: `@LateNightSeth` (5.3M),
   `@Athosgamer` (17.3M, Minecraft), `@brino` (7.58M). All genuinely large, all the wrong人.
4. **Institution channel counts when the content lives there** — `andrew_maguire` →
   `@KinesisMoney`, `michael_saylor` → `@strategysoftware`. Note any tab restriction
   (Saylor: take `streams` only — earnings / investor Q&A; `videos` is product marketing).
5. **Any one of the three tabs active ⇒ active.** `/videos` silent while `/shorts` is daily is
   common (this repo previously misreported Armstrong as dormant on exactly that).
6. `- Topic` auto-generated channels are never a valid pick.

## 4. ★ Parent verifies before writing — subagent prose is a claim, not evidence

Re-probe every accepted pick from the parent and require the handle to match:

```
54 probed (52 picks + 2 controls) → 0 failures, 0 handle mismatches, controls green
```

For the borderline tier, **fetch the actual recent titles and read them yourself**. Of 9
medium/low holds, that flipped 3 from the subagent's suggestion:

- `athos_salom` → rejected: content is Portuguese paranormal → belongs to Forecast-Checker per the
  project boundary, not Eco
- `daron_acemoglu` → rejected: MIT centre channel, 2 of 3 recent videos are other speakers
- `thomas_sargent` → rejected: computational-economics screencasts, zero market opinion

**The decision criterion is "can we reliably collect *this person's* opinions here", not "does this
person own the account."** That is what admits `@EinsteinandIves` (third-person titles, 100% Dan
Ives content) and rejects a channel he might nominally be on but never speaks market views on.

Writer script discipline (`scripts/apply_kol_channels.py`):
- accept only `confidence == high` **and** parent-verified, unless overridden
- never overwrite a non-empty existing value — log the conflict for a human
- back up `kol_registry.json` before writing
- park held/rejected rows in `_needs_review.json` / `_rejected.json` with the reason

**Roster 铁律 holds throughout: this fills collection fields only. Person count must not move**
(122 → 122). Assert it as a semantic diff, because a formatting reflow makes `git diff` show all
122 records changed:

```python
assert len(old) == len(new) and set(old) == set(new)
changed = [k for k in old if old[k] != new[k]]     # expect exactly the ones you intended
```

## 5. Pitfall: `subprocess` cannot see venv console scripts

The parent re-verification returned **9/9 empty in 0.23s** — visually identical to "all these
channels are dead", and I nearly wrote that up.

0.23s for 27 network calls is impossible. Real cause: `subprocess.run(["yt-dlp", ...])` raises
`FileNotFoundError` (the console script lives in `.venv/bin`, not the subprocess `PATH`), and
`ThreadPoolExecutor.map` was swallowing it inside a broad `except`.

```python
cmd = [sys.executable, "-m", "yt_dlp", ...]   # module invocation always resolves
```

Already documented in `~/Projects/AI-Blog-Generator/AGENTS.md`; re-derived here at cost.

> **Two durable rules.** (a) Batch results that are *uniformly* empty **and** finish implausibly
> fast indict your invocation, not the data source — same family as the 1258/1258 uniform value in
> §1: *uniform anomalies point inward.* (b) Never let `ThreadPoolExecutor` swallow exceptions
> during a diagnostic; surface `err` per record.

## 6. Independent downstreams agreeing on an anomaly = upstream is broken

All six judging agents volunteered the same caveat — *"every candidate's `active_tabs` is
`latest: null` / title `Keyboard shortcuts`; I could only judge on name and subscriber scale."*
They flagged the degradation instead of quietly producing confident-looking output, which is the
behaviour worth reinforcing in the batch instructions.

**When several isolated consumers independently report the same defect, suspect the shared input
before suspecting any of them.** Verify with a boolean probe on the raw file (see §2) rather than
re-reading their prose.
