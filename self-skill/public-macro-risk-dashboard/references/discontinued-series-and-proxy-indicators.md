# When an official series stops publishing: triage, proxies, and the traps

Realized adding 中国央行流动性 (OMO / DR007 / MLF / SFISF) plus its 两融 + 宽基ETF份额 proxies.
Companion to `add-new-dashboard-section.md`. Read before telling a user "this data isn't available"
or before buying a paid data source.

---

## A. Triage: "stopped publishing" is three different things

Getting this wrong produces a confidently WRONG caption on a public page.

| Case | Symptom | Correct wording |
|---|---|---|
| **Moved** | Main page stale; data now in annual report / trade association / quarterly PDF | "no longer in <old place>", ingest the new one, downgrade the frequency badge |
| **Merged into a bigger quota** | Series stops mid-life, no announcement of termination | "no standalone disclosure" — **NOT** "the tool is unused" |
| **Policy termination** | API returns structurally valid **zeros** | Truly gone. Stop retrying, go find a proxy |

Worked examples:
- **SFISF** — PBoC page had only 2 operation notices, last 2025-01. First read: "the facility is
  idle." **Wrong.** 2025-05-07 PBoC merged SFISF (500bn) with the buyback-relending tool (300bn)
  into one 800bn quota and stopped publishing SFISF separately. The gap means *no standalone
  notice*, not *no operations*. Cross-check that confirmed it: the securities-association annual
  figure (cumulative 105.0bn) matched our scraped 50+55 exactly.
- **A-share northbound daily net buy** — EastMoney endpoint returns `0.00` for every row. Not a
  scrape failure: exchanges stopped daily disclosure 2024-08-19 (quarterly now).

**Zeros that are structurally well-formed are a disclosure-policy signal, not a bug.** Confirm with
one search before debugging the scraper.

## B. Will a paid source help? Decide from the CAUSE, not hope

- Stopped for a **structural/regulatory** reason (merged quota, mandated termination) → Wind / CEIC
  / Bloomberg resell the *same public releases*. **Paying buys nothing.** Say so plainly.
- Blocked for a **technical** reason (anti-bot, login wall, no bulk endpoint) → paid access is a
  real fix.

Users ask "should I open an account?" — this distinction is the whole answer, and it needs to be
stated with its reason attached.

## C. Choosing a proxy: serve the QUESTION, not the metric name

Ask what the user actually wants to know. Usually the *signal*, not that specific series — and then
a daily proxy beats the quarterly official number.

| Original (low freq) | Real question | Daily proxy |
|---|---|---|
| SFISF (event-driven) | Is the market being supported? | Margin balance (leverage) · broad-index ETF **shares** |
| Northbound (terminated) | Are foreigners in or out? | PBoC "overseas holdings of domestic equities" (monthly, official) |

Non-negotiables when shipping a proxy:
1. **Its own chart / own table row.** Never merged into the original metric's series.
2. Caption states **"proxy indicator — not <X> itself"**.
3. Explain *why* it tracks the signal, so a reader can judge the inference themselves.

## D. ETF flows: track SHARES, never AUM or price

**AUM = NAV × shares**, so it moves with the index. Index +10% with zero creations still shows
"+10% AUM" — reading that as inflow is simply wrong. **Only share count proves money moved.**

Source (verified 2026-08): `akshare.fund_etf_scale_sse(date="YYYYMMDD")` — Shanghai Exchange
official daily ETF table, ~800 funds, includes 基金份额. First-party, not a vendor derivation.

Two collector traps:
- **Non-trading days raise `KeyError`** (empty frame → akshare's column rename fails). That is
  "no session that day", not an outage. Catch and skip; do not retry or abort the backfill.
  Sanity check: a 14-day probe returning 13 hits + 1 skip is correct, not a 93% success rate.
- **No range endpoint** — one request per date. Loop with a delay; checkpoint to disk every N days
  so a long backfill survives interruption.

## E. A partially-backfilled series renders as a fake crash

**The most dangerous defect in this file.** Not an exception — a plausible, confident, wrong chart.

Mid-backfill the series was "both ends, hollow middle" (2025-08 start + 2026-08 tail, 11 months
missing). Connecting adjacent points drew a **−71.97% cliff**. Real intraday moves at the time were
±2%. Publishing that hands the reader a decisive, false conclusion.

Guard before rendering — check the **date interval**, not just values:

```python
# scan back from the tail; cut at the first gap, keep only the recent contiguous run
for i in range(len(s) - 1, 0, -1):
    if (date(s[i]) - date(s[i-1])).days > 20:      # daily series: >20d = gap, not a move
        s = s[i:]
        break
```
Report `gap_trimmed` upward and surface it in the caption, so a shortened chart is visible rather
than silent. Post-fix the worst single step went −71.97% → 5.13%.

## F. A REAL crash needs the opposite treatment: verify, then annotate

Same panel also held a genuine −73% decline. **Magnitude cannot distinguish real from artifact** —
only re-sourcing can.

Method: take 4+ key dates off the series and match them against public reporting.
```
2025-12-31  888.30bn shares  ✓   2026-01-21  719.78bn  ✓
2026-01-27  575.33bn         ✓   2026-08-10  248.61bn  ✓
```
All four matched → real (Central Huijin redemptions; Q1 report confirmed ~50bn shares from that
fund alone).

**Once confirmed real, the chart MUST say so** — a callout stating it is a real event plus the
cross-check dates. Otherwise every future reader (you included) reopens the same "did we scrape
this wrong?" investigation. An unexplained cliff is a permanent tax on the dashboard.

## G. Write availability limits into the ARTIFACT, not just the chat

"MLF only covers 20 months because PBoC created that section in 2025-01" and "SFISF folded into the
800bn quota" belong in the figure caption. Reported only in chat, the next session re-walks every
dead end. Caption it once; save the re-derivation forever.

## H. Don't ship a derivation that fails back-testing

Tried inferring SFISF from the PBoC balance-sheet line 对其他金融性公司债权. Back-tested against
the two known operation dates:

| Month | SFISF actual | Line item MoM |
|---|---|---|
| 2024-10 | 50.0bn (1st op) | +17.1bn ✗ |
| 2025-01 | 55.0bn (2nd op) | +1.26bn ✗ |
| 2025-03 | none | −370bn ✗ |

The line commingles relending, PSL and others; the signal is drowned. **Dropped it.**

Any derived indicator must be back-tested against known ground-truth events before shipping. Without
that step this would have become a professional-looking noise series on a public dashboard — worse
than having no indicator, because people would act on it.
