# Roster governance: an external SSOT the agent MIRRORS but never edits

Companion to `kol-roster-and-drilldown-sections.md` (which covers roster *schema* + drill-down UI).
This file covers **who is allowed to change the roster, and what breaks when it changes.**

Generalises beyond KOLs to any human-curated list an automated pipeline consumes: watchlists,
merchant cohorts, tracked tickers, monitored accounts.

Realised 2026-08-22 on Eco-and-Volatility-Checker after I corrupted the roster by editing it myself.

---

## 1. The rule: external SSOT, one-way mirror, agent never adds or removes

Chao's ruling: **Notion「KOL List」DB is the single source of truth**; `data/kol_registry.json`
is a **mirror**. Additions/removals happen in Notion (by Chao or another agent). This repo only syncs.

- SSOT DB `35947eb5-fd3c-800d-b852-cef31f9de6a5`, inside page「KOL Research Daily Update」
  `31447eb5fd3c8064a531c43b177cdc41` (that page also holds *KOL By Week* / *KOL By Day*).
- Tool `tools/sync_kol_from_notion.py` — bare run = dry-run diff, `--apply` writes.
- Wired as **步骤 0 of the EXISTING daily cron**, before any scraping. Do **not** create a second cron.

### What I did wrong (the reason this file exists)
I added 23 people to the registry on my own initiative, wrote **only the local file — never Notion**,
so the two drifted (124 local vs 115 Notion). Several of those people belonged to a *different
project* entirely. Chao's corrections, in order:

- 「**你不要做我没给你的任务**」
- 「我什么时候让你在这个对话项目里做这个周期、金融占星和易数了？」
- 「现在请你严格遵守铁律，只用 notion 上的 115 人，不要再增加了」

**Adding roster entries unprompted is scope creep, not helpfulness.** The same applies to inventing a
new section/grouping for them — see §4.

### Sync invariants
1. **One direction only.** Never write back to the SSOT from the mirror.
2. **Preserve mirror-only collection config.** `search_terms` / `youtube_channel_id` / `source_url`
   exist only locally — the SSOT has no such columns. Overwriting them silently destroys the
   scraper's ability to find that person. On an existing row, refresh only SSOT-owned fields.
3. **Removals leave a trail and never delete history.** Departures → `data/kol_removed_<date>.json`;
   **keep their `data/kol/backfill/*.json`** so a re-add in the SSOT restores usable history at once.
4. **Sync failure must not abort the day.** Fall back to the existing roster, complete the run, and
   say so in the report (「⚠️ 今日 Notion 名册同步失败，使用上次名册」). Report deltas as one line:
   `名册变更：+N / -N（现 N 人）`.
5. **Show the dry-run diff and get approval before the first `--apply`** when the diff includes
   removals. A removal list is a destructive operation on a curated asset.

---

## 2. ⚠️ Fuzzy name-matching silently DELETES people (institution-suffix trap)

SSOT display names carry suffixes the mirror lacks:
`Nomi Prins（Prinsights Global 创始人 / 前 Goldman Sachs MD）`.

With naive **bidirectional** substring matching, the local row **`Goldman Sachs`** matches that
string first and consumes it. The real `Nomi Prins` then finds no partner, is judged "not in the
SSOT", and lands on the **removal** list. Anyone whose SSOT entry name-drops another roster member's
employer is exposed — and the failure is silent and plausible-looking.

```python
# 1. exact pass over ALL rows first; mark BOTH sides used
# 2. fuzzy ONE-WAY only: local_name ⊂ ssot_name    (SSOT side is the longer, suffixed one)
# 3. among candidates take the SHORTEST local name
# 4. an already-paired local row never participates in fuzzy again
```

**Read the dry-run removal list every time.** A name you know is present in the SSOT appearing under
移出 means the matcher is broken — not that the SSOT changed. I caught this only because Nomi Prins
looked wrong; two other suffixed names (`Amos Hochstein（能源安全高级顾问）`,
`Michael Widmer（美银全球商品研究主管）`) were mis-reported by my first cut as well.

---

## 3. Roster changes must be propagated to EVERY downstream renderer

Removing people from the roster does **not** remove them from the page. Downstream data paths are
independent of the roster *and of each other*:

| Downstream | Reads from | Symptom after a removal |
|---|---|---|
| `_kol_history_payload` | **scans the `data/kol/backfill/` directory** | card is gone, but the person's history is still embedded in the page payload |
| `_kol_views_html` / `_kol_changes_html` | **daily snapshots** (roster as of scrape time) | card still renders and **opens to an empty modal** |

**Rule: any consumer that scans a directory or replays historical snapshots is roster-blind.**

After a roster change, filter at *every* render site against the current roster
(`_roster = set(_kol_meta())`), and **enumerate the consumers first** — I fixed the payload, rebuilt,
and found the cards still there; fixed the cards, rebuilt, and only then was it clean. Two rebuild
cycles (≈6 min each) for one conceptual bug.

Acceptance must assert **both directions in one pass**:
```python
# no clickable card resolves to an empty payload entry
assert not [k for k in drill if not payload.get(k, {}).get('h')]
# and no removed name survives anywhere in the artifact
for name in removed_names:
    assert name not in html
```

---

## 4. Project-boundary check before adding anything to a roster or a new section

I created a 「周期与术数预测」 section containing I-Ching / six-line divination / Qimen Dunjia /
financial-astrology channels. That content class belongs to a **different project**
(`Forecast-Checker`), whose `AGENTS.md` explicitly claims 通灵/占星/末日预言者. I had written that
boundary myself, then violated it.

Chao's ruling: **this project keeps only tradeable financial judgment.** Technical-analysis /
quantitative-cycle practitioners (Elliott Wave, McClellan breadth, ECM, Hurst cycles, generational
long-cycle) stay, in the **general KOL section with no separate grouping**.

Before adding a person or inventing a grouping:
1. `grep` the sibling projects' `AGENTS.md` for the content class — the boundary is usually already
   written down.
2. If it belongs elsewhere, **migrate rather than delete**: export the entries, land them in the
   other project (as a *source* file registered in that project's merge whitelist — never write its
   derived artifact directly), verify they render there, and only then remove them here.
3. Splitting people into a new section also means **removing them from the general renderer** and
   **recomputing the header count after filtering**, or the prose contradicts the card count.
   Conversely, when a section is retired, **delete the filter too** — leaving it in place silently
   hides the people you just decided to keep.

---

## 5. Wiring the sync into the existing daily cron (not a new one)

When asked for "daily sync", check what already runs before claiming anything is missing. I said
"每日同步还没建" when the daily cron had existed all along — it simply **read** the roster file and
never pulled from the SSOT. Chao: 「我记得我们原来不是有一个 cron 每天运行吗？」

Correct framing: *the cron exists; it lacks a sync step.* Insert 步骤 0 ahead of all scraping.

Edit the cron prompt with an **idempotent script**, not by hand:
- back up `~/.hermes/cron/jobs.json` first,
- locate a unique anchor (e.g. `## 步骤 1：`) and **abort if it isn't found** — never fuzzy-insert,
- re-running must detect its own marker and no-op,
- keep the script in `tools/` so the edit is reproducible and reviewable.

Also **sweep the prompt for now-stale instructions** in the same pass. Mine still told the agent how
to handle 另类预言类 KOLs after that whole class had been migrated out — a stale instruction that
could coax a future run into re-adding them. Replace it with the new boundary plus an explicit
"if you see one, flag it, **do not delete it yourself**" (the roster is Notion's, §1).
