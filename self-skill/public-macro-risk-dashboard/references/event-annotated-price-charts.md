# Event-annotated price charts ("标出影响这个走势的所有大事件")

Recurring request shape: Chao sends a screenshot of a TradingView-style overlay with hand-drawn
event callouts ("6.5 数据冲击", "美伊签署备忘录") and asks for the same thing, auto-updating.

The chart is the easy half. The **event annotations are the part that invites fabrication** — an
LLM asked "what happened on 2026-03-19" will produce a fluent, plausible, completely invented
answer with an invented URL. Never write event labels from model recall. Use the loop below.

---

## The loop: price first, events second, URLs verified by the parent

**1. Prove the price series before touching events.**
Yahoo `v8/finance/chart/{sym}?range=2y&interval=1d` works for both legs
(gold `GC=F`, DXY `DX-Y.NYB`; ask Chao which contract/index he wants — he cares, e.g. "1 GC=F").

**2. Let the DATA nominate the dates.** Compute daily returns, take σ over a 2-year window (longer
window = stabler σ), flag every day where `|z| >= 1.8` on EITHER leg. ~31 days for a YTD window.
This inverts the dangerous direction: instead of thinking of an event and asserting it moved the
market, the market says "something happened here" and you go find out what. It also guarantees
every annotation sits on a real move — no "big event" marker on a flat day.

**3. Fan out the verification, one date-batch per subagent.** Give each the exact date + that day's
actual % moves + closes, so it can use the numbers as search anchors.

**4. The PARENT re-verifies every URL.** Subagent summaries are self-reports. Run `web_extract` over
every returned URL and check the page title actually corresponds to the claimed event. This session:
36/37 came back live with matching titles; the one that didn't was **downgraded to `medium` with a
visible "出处未能二次核实" note on the chart — not deleted, not silently kept as `high`**.

**5. Render honesty into the section, not just the commit message.**
- badge per event: `已核` (high) / `待核` (medium) / `日历` (official calendar item)
- every event row carries a clickable source link
- anomaly days with no event found are listed explicitly as "未找到明确触发事件" — never padded
- the method paragraph is printed on the page
- events file `mtime > 8 days` → the chart itself prints a staleness warning

**Cadence split:** price updates daily (it rides the normal dashboard build); event re-verification
is weekly (web search is slow and events don't happen daily). Say this on the chart.

---

## Subagent orchestration lessons (these cost a full wasted round)

### Don't impose `output_schema` on a research fan-out
Four subagents came back `status=failed` — **not because they found nothing**. Their transcripts
showed real Reuters/CNBC/Kitco hits. They had wrapped the JSON in a ```json fence, which failed
`output_schema` validation, and the run was marked failed. Data was there; the wrapper killed it.

Fix: drop `output_schema` for research tasks, ask for "pure JSON array, no markdown code block",
and parse defensively in the parent (`re.findall(r'\[\s*\{.*?\}\s*\]', text, re.S)`, take the
longest match). Reserve schemas for tasks with genuinely mechanical output.

**Corollary: read `.../delegation/live/<id>/task-N.log` before concluding a subagent failed.** The
status line lies about the cause; the transcript shows what actually happened.

### "All none" almost always means too-narrow queries, not a too-strict bar
Two agents returned `none` for all 16 dates. Two others, same sources, same period, found
everything. Diff in the transcripts:
- the failures searched only keyword combinations, hit a Wikipedia "Gold" page, and gave up;
- the successes guessed **date-shaped URL paths** and searched non-gold framings.

Re-dispatch changed three things and got **16/16, zero none**:
1. **Widen the topic**, per Chao's own steer — *"跟金融市场流动性相关的大事件…不一定非得跟黄金密切相关"*.
   The March gold crash was driven by an **Iran war → oil → inflation → rate-hike repricing** chain;
   searching "gold" could never surface it. Accept Fed/officials, payrolls/CPI/PCE/GDP, geopolitics,
   tariffs, equity crashes, Treasury events, liquidity events, central-bank action.
2. **Hand them the proven source list** (below) instead of letting them rediscover it.
3. **Set a floor before giving up**: at least 4 distinct query formulations + try date-path URLs.

This matches Chao's standing rule already recorded elsewhere: *言论太少先查上游别降门槛 —— 瓶颈常是
query 太少*. The instinct "my filter is too strict" is usually wrong; the retrieval is too narrow.

### Proven sources for "what moved markets on date X" (pass these to subagents)
```
kitco.com/news/article/YYYY-MM-DD/<slug>   daily metals wrap, best hit rate
kitco.com/opinion/YYYY-MM-DD/<slug>        (slug needs a search first; bare date path won't enumerate)
kitco.com/news/off-the-wire/               Reuters syndication
cnbc.com/YYYY/MM/DD/<slug>.html            date in URL
reuters.com/...-YYYY-MM-DD/                date in URL tail; search "reuters <topic> YYYY-MM-DD"
barchart.com/story/news/ , investinglive.com   daily FX wraps
federalreserve.gov/newsevents/pressreleases/monetaryYYYYMMDDa.htm   FOMC statements, authoritative
```
Note from a subagent worth keeping: CNBC's `stock-market-today-live-updates` URL date is often the
**previous** calendar day (posted the prior evening, updated live) — don't trust the URL date alone.

---

## Calendar events as the reliable floor
FOMC decision dates + outcomes come straight from `federalreserve.gov` press releases and need no
search heuristics. Render them in a distinct colour from the searched anomaly events so the reader
can see which annotations are certain and which are inferred.
