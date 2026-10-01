# Data-source staleness triage: archive-vs-current tables, and red-badge false alarms

How to react when a dashboard panel looks stale. Two opposite root causes hide
behind the same symptom, and the fixes are the reverse of each other.

The trigger that surfaced all of this (2026-08, Eco-and-Volatility-Checker):
Chao asked one question — *"the header says 每月更新·滞后约2月 but the chart says
滞后 233 天 — so which day IS this data?"* **A page that contradicts itself is a
bug reporting itself.** Never wave it away as "that source is just slow."

## Rule 0 — every red badge must be resolved to a verdict

For each stale badge, go look up the official latest release and land on exactly
one of two verdicts. Leaving red badges permanently displayed is its own defect:
the boy-who-cried-wolf effect means real staleness stops being noticed.

| Symptom | Check official latest | Verdict | Fix |
|---|---|---|---|
| Panel 233 days stale | Official already published a newer period | **Wrong source** | Change the data source |
| Panel 324 days stale | Official's newest IS that old | **Wrong threshold** (false alarm) | Change the SLA threshold, leave data alone |

A single `web_search` settles it — in this case Reuters/WolfStreet had already
reported the newer figure, instantly disproving "the agency hasn't published."

## Trap A — "historical archive" file vs "current release" file

**Case:** US Treasury TIC foreign holdings of USTs were fetched from
`ticdata.treasury.gov/Publish/mfhhis01.txt`. That file is updated yearly, returns
HTTP 200, and parses into 100+ clean data points — **everything looks healthy.**
But it is the *historical archive* table: its content stops at the **prior
calendar year end**. The current-year monthly data lives in a different file,
`slt_table5` (a rolling ~13-month window).

Result: the page showed Japan $1,186B / China $684B (Dec-2025) while the official
Jun-2026 figures ($1,116.7B / $633.4B) had been published weeks earlier.
**6 months stale AND numerically wrong.**

Generalizable lesson:
- Government/institutional data sites routinely split **archive** and **current**
  into two similarly-named files (`*hist*` vs `*_table5`, `*_hist` vs `*_current`).
  Wiring only the archive = permanently half-a-year behind.
- **HTTP 200 + successful parse + hundreds of rows does NOT mean fresh.** The only
  freshness test that counts is *"what is the newest period IN the payload, and
  does it match the agency's newest published period?"*
- Correct fix: fetch BOTH and merge, with **the current table taking precedence**
  (it also carries official revisions to recent months).

### Trap A corollary — new panels are the highest-risk panels

`git log -S` showed this bug existed **from the panel's very first commit** and
survived a week unnoticed. A brand-new panel has no historical baseline on screen,
so a wrong value looks exactly like a right one. **Cross-check any newly wired
data source against the agency's latest published figure on day one** — that is
the single cheapest defect-catch in the whole pipeline.

## Trap B — SLA threshold set from the frequency NAME, not measured latency

**Case:** Credit-impulse panels (BIS credit-to-GDP via FRED `QUSPAM770A` /
`QCNPAM770A`) flagged red at 324 days. Checking FRED directly: the newest
observation genuinely IS `2025-10-01`. BIS compiles + FRED republishes with a real
**9-10 month lag**. Applying a generic `quarterly = 135 days` tolerance guarantees
a permanent false red.

Fix: give slow series their own threshold (`bis_quarterly = 330`) and correct the
on-page prose too — it claimed "滞后约 1 季" when reality is ~3 quarters.
**Wrong explanatory copy is itself misinformation, independent of the number.**

## Trap C — a limitation that cannot be fixed must be EXPLAINED, not red-flagged

The EU series is a 9-country eurozone sum. The current table (`slt_table5`) only
lists the **top-20 holders**, so Germany/Italy/Netherlands/Spain/Finland fall into
"All Other" — the 9-country aggregate is **structurally unreconstructable** from
the current release. It can only come from the year-end archive.

Correct handling (all three parts matter):
1. **Keep the real older value.** Do NOT assemble a partial sum from whichever
   countries happen to be listed — that silently changes the series definition and
   makes the line jump. Falling back to the archive value is the honest choice.
2. **Attach a machine-readable reason** (e.g. a `lag_reason` field on the series)
   and render it next to the chart in plain language.
3. **Change the badge wording when the cause is known.** A generic red
   "please check whether the agency published something newer" implies the
   scraper is broken. With a known cause it should read "(reason below)" and point
   at the explanation.

## Freshness checklist to run before publishing

- [ ] For each source: newest period in payload == agency's newest published period?
- [ ] Any stale badge resolved to **wrong-source** or **wrong-threshold**? None left ambiguous.
- [ ] SLA thresholds derived from *measured* publication lag, not the word
      "monthly"/"quarterly".
- [ ] On-page frequency/lag prose matches measured reality.
- [ ] Known-limitation panels show the reason, not a generic alarm.
- [ ] Newly added panels cross-checked against the official figure this release.

## Honest-reporting note (Chao explicitly pushed back)

When reporting a fix, do not say "the live site is broken" without separating:
- **a half-finished feature I shipped** (new drill-down whose payload never got
  wired), versus
- **a pre-existing defect I found and fixed** (the TIC wrong-source value, present
  since the panel was created).

Chao's reaction — *"what do you mean broken? it was fine before you touched it"* —
is the cost of that sloppiness. Use `git log -S '<symbol>'` / `git show <rev>:<path>`
to establish exactly when each defect entered, and state authorship plainly.
