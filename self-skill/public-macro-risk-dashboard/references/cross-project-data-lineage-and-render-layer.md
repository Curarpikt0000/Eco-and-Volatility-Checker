# Cross-project data lineage: when the chart lives in a different repo from the scraper

Session 2026-08-25. Chao asked why an indicator he'd approved still wasn't on the dashboard, and
separately challenged: 「你确认一下我们的项目是叫 Economy Dashboard 还是 Eco and Volatility
Checker？你不会修改错地方了吧？」 Both are symptoms of the same structural fact — this pipeline is
**two repos deep**, and it is easy for both agent and user to lose track of which layer a change
landed in.

---

## 1. The two-repo split (verify with evidence, not memory)

| | Economic-Dashboard (ED) | Eco-and-Volatility-Checker (Eco) |
|---|---|---|
| Role | **producer** — scrapers → Notion 13 DBs | **consumer** — reads Notion → HTML dashboard |
| PBoC scrapers | ✅ `src/scrapers/pboc_*` | ❌ none |
| Writes B2/B5/B7 | ✅ | ❌ |
| Renders sections | ❌ | ✅ `src/dashboard.py` |

Discriminating evidence (run these rather than asserting from memory):

```bash
ls  <repo>/src/scrapers/pboc_omo_scraper.py          # exists in ED only
grep -rl '<B2 db id>' <repo>/src                      # ED: config.py (owner)
                                                      # Eco: external_data.py (registry only)
```

**★ A DB id appearing in a repo does not mean that repo reads it.** Eco's `ECON_DB` dict lists
`"pboc": "<B2 id>"`, but grepping `pboc` across the whole file returns **exactly that one line** —
registered, never called. Saying "B2 isn't in the downstream's scope" is imprecise; the accurate
statement is "it's registered but never read, so new B2 columns can't break it." Check call sites,
not just constant tables, before claiming impact or non-impact.

## 2. A source-layer fix is invisible until the render layer ships

Fixing the scraper + backfilling Notion produces **zero** visible change. The user's mental model
is the dashboard, so "I fixed the PBoC data" reads to them as "it's on the dashboard now."

State the layer explicitly every time:
> Data layer done (scraper + Notion B2, 541 rows). **Dashboard section not written yet — you
> won't see anything on the page.**

Verify the render claim against the live page, not the repo:

```bash
grep -c 'china_liquidity\|中国流动性\|OMO' src/dashboard.py     # source
curl -s https://<user>.github.io/<repo>/ | grep -c 'OMO\|DR007'  # live
```

**★ A live-page grep can hit KOL prose, not your section.** Here the live grep returned `1` — from
a KOL commentary paragraph containing the words 中国流动性, not from any new section. Always print
the surrounding context (`grep -o '.\{80\}KEYWORD.\{80\}'`) before concluding the section shipped.

## 3. Don't let Q&A masquerade as progress

I said "now starting implementation", then answered three rounds of substantive questions
(swap accounting, PBoC/BoJ balance-sheet口径, X credentials) writing **zero** implementation code.
The user reasonably asked why the section still wasn't there. Either:
- answer the questions and say plainly *"this is Q&A; implementation hasn't started"*, or
- say *"parking these, implementing first"*.

Never let an earlier "starting now" imply background progress that isn't happening. When resuming,
re-verify current state with `git status` before reporting — here it surfaced a `youtube_shorts.py`
written by a **parallel session's subagent**, which would otherwise have been misattributed to
this line of work.

## 4. Where a China-liquidity section belongs, and why four charts not one

Target slot: after `_liquidity_html()` (US liquidity points), before `_cb_balance_html()` — i.e.
inside the "流动性与央行" band Chao named.

Use **separate charts, shared palette/time-axis**, not one combined chart: OMO daily injections are
千亿-scale, DR007 is a ~1.4% rate, MLF balance ~5万亿, PSL balance ~1.8万亿 — three orders of
magnitude apart, so a single axis renders the small series invisible.

Highest-value design detail: overlay the **7-day reverse-repo policy rate** on the DR007 line. The
gap between them *is* the funding-tightness read (above = tight, below = loose), which a bare
DR007 line cannot convey. Encode judgement rules in code rather than leaving them to per-run AI:

- DR007 persistently above the 7-day policy rate → funding tight
- Large OMO injections but DR007 not falling → **transmission blocked (alert)**
- MLF shrinking / net drain → medium-term tightening, leads the short end
