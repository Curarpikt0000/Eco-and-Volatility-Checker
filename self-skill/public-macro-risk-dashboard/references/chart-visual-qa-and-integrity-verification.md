# Verifying a NEW dashboard section: visual QA + data-integrity proof

Companion to `add-new-dashboard-section.md` step 7. Programmatic checks (point counts, "no `empty`
string", future-date scan) prove the section BUILT — they do **not** prove it's readable or honest.
Two extra loops close that gap. Both were realized building the 债务/GDP + 分评级公司债 sections.

---

## A. Visual QA loop with `browser_vision` (do this before every rebuild)

Supersedes the old "vision backend is flaky → verify programmatically" note. Vision works and it
caught **4 real rendering defects that every programmatic check passed clean**. Programmatic checks
confirmed 6 SVGs / 1,640 tooltips / 0 future dates while the chart was in fact partly unreadable.

### Loop
1. Render ONLY the new section(s) standalone — don't wait 8 min for a full rebuild:
   ```
   cd src && ../.venv/bin/python -c "
   import external_data as ed, dashboard as db
   h1=db._<name>_html(ed.fetch_<name>())
   open('/tmp/newsec.html','w').write('<meta charset=utf-8><body style=\"background:#faf8f4\">'+h1)"
   ```
   (`background` must match the dashboard's paper tone or contrast judgements are wrong.)
2. `browser_navigate` to `file:///tmp/newsec.html`.
3. `browser_vision` with a **specific, enumerated** question — never "does this look OK". Ask about
   overlap, legibility, whether encoded distinctions are actually visible, legend/clipping. One
   question per suspected failure mode; vision answers point-by-point.
4. Fix → re-render → re-ask the same question. Two rounds was enough here.

### Defects this catches that code checks never will
- **An element is emitted but invisible.** Forecast rects existed in the a11y tree yet rendered at
  `opacity 0.16` → effectively blank. Element-count assertions pass; the human sees nothing.
- **Missing scale.** Bars with no x-axis ticks/gridlines — unquantifiable.
- **Label collision.** Series end-labels overprinting into a smear (fix: greedy vertical de-overlap,
  sort by y, push down to `minsep≈11px`, shift the whole stack up if it overflows, draw a faint
  leader line back to the true point when a label moved >1.5px). Apply to EVERY multi-line chart in
  the section, not just the one vision flagged.
- **Text-on-pattern.** Value labels sitting on hatch/fill. Halo (`stroke=<bg>` + `paint-order="stroke"`)
  fixes crossing gridlines but NOT a busy pattern behind text — for that, move the label outside the
  full drawn extent (`bar end + forecast width`), and widen the right margin to match.

### ⚠️ Vision output is a HYPOTHESIS, not a fact — cross-check before acting

**Measured hit rate (2026-08, AI FCF + credit charts): 1 true defect out of 4 specific claims.**
In a SINGLE vision response about the same chart:
- ❌ "X 轴间隔不规则" → source showed strictly every-2-months. False.
- ❌ "NEE appears in the bars" → NEE was explicitly excluded; 18 tickers parsed, no NEE. **Hallucinated
  an entity that does not exist in the data.**
- ❌ "ORCL has no visible value label" → all 18 value labels present in the SVG.
- ✅ "top y-tick collides with the unit caption" → **real**: tick `120` at `y=33.5` vs caption at
  `y=26`, both right-anchored at `x=55`. 7.5px apart. Genuine defect.

So: never accept AND never dismiss wholesale. Adjudicate **every** claim against the DOM/source
individually. The cheap adjudication pattern — parse the actual coordinates and compute the collision
rather than re-reading the screenshot:
```python
seg = html[html.index('aifcf-svg'):html.index('</svg>', html.index('aifcf-svg'))]
for m in re.finditer(r'<text x="55" y="([\d.]+)"[^>]*>([^<]+)</text>', seg):
    print(m.group(1), repr(m.group(2)))        # y-coords + text ⇒ collisions are arithmetic
```
Same for label overlap — assert it, don't eyeball it:
```python
collisions = [(p[2], q[2]) for i, p in enumerate(lab) for q in lab[i+1:]
              if abs(p[0]-q[0]) < 30 and abs(p[1]-q[1]) < 10]
assert not collisions
```
A hallucinated ticker is the tell that vision is pattern-completing from the chart's *genre* rather
than reading it. When you see one impossible claim, distrust that whole response — but still check
each item, because the true defect was in the same paragraph as the invented one.

### Legend/color wiring: verify group keys against the DATA layer, never hardcode
Hardcoding group-name → color as a literal dict silently breaks when the names drift from the data
layer. Here the render dict used invented names (`"芯片/半导体"`, `"算力与数据中心"`) while
`AI_UNIVERSE` actually said `"芯片/加速器"`, `"算力/数据中心"` — so **13 of 18 companies fell to the
grey fallback color and the legend showed only 1 entry**. Every programmatic count passed; the chart
just quietly lost its encoding.

Derive the palette from the data instead:
```python
def _ai_colors(names):
    seen = list(dict.fromkeys(names))       # preserve first-appearance order
    return {n: _PALETTE[i % len(_PALETTE)] for i, n in enumerate(seen)}
```
And add a mismatch assertion to the standalone QA step — this is the check that would have caught it
in seconds:
```python
print('unmatched:', [g for g, _ in AI_UNIVERSE if g not in COLOR_KEYS])   # must be []
```
Generalises: **any lookup keyed on a human-written string duplicated from another module needs an
"unmatched keys" assertion**, because the failure mode is a silent fallback, not an exception.

### Beware over-strict verification regexes reporting false failures
Checking the legend fix with `<rect x="\d+" y="350"` returned 1 match and looked like the bug was
unfixed — but real coordinates were `x="172.0"` (floats). The looser
`<rect[^>]*fill="(#[0-9a-f]{6})" opacity` showed all 5 colors correctly applied. **When a verification
regex reports failure, confirm the regex matches the actual serialisation before concluding the code
is broken** — same lesson as the `font-size="9"` attribute-anchored miss above.

### Earlier worked example of the same adjudication discipline
Vision claimed 巴西/德国 rendered a "rising" hatch inconsistent with the legend. Re-querying the
fetcher proved 巴西 93.3→106.5 and 德国 62.9→73.7 **are** rising forecasts — the hatch was correct
and "fixing" it would have introduced a bug. **Always re-derive the disputed values from the source
dict before changing code.** Cheap check:
```
for c in d['countries']: print(c['name'], c['latest'], c['forecast'][-1][1])
```
Equally: do **not** dismiss a flagged item just because the literal claim was wrong. That same
misread exposed a genuine defect — a row showed `▼5.1pp` (5-year HISTORICAL change) next to a rising
forecast hatch, two opposite arrows with no explanation. **When one chart encodes both a historical
delta and a forecast direction, they will sometimes contradict; say so explicitly** in a tooltip and
in the caption, or readers conclude the chart is broken.

### Derive caption examples from live data — never hardcode
The clarifying example ("例：X近5年▼8.7pp去杠杆，但IMF预测2031回升至142.1%") must be COMPUTED by
scanning for the first country matching `chg_5y < 0 and forecast[-1] > latest`. A hardcoded country
name + numbers goes stale at the next WEO and becomes a false statement on a public page.

### Axis ticks: snap the STEP, not the top — and verify from the DOM, not the screenshot
Vision flagged unreadable ticks (`0 / 5.8 / 11.6 / 17.5 / 23.3`). Two iterations were needed:

1. **Rounding the axis maximum is not enough.** Ticks are drawn at `top * k / divs`, so a "nice"
   top of 25 with 4 divisions still yields 6.25 / 12.5 / 18.75.
2. **Snapping the step too coarsely wastes the canvas.** Forcing the step to 1/2/2.5/5×10ⁿ pushed a
   max of 21.7 up to a top of 40 — 45% of the chart height empty.

Working version — enumerate candidate steps and take the smallest that still covers the data:
```python
def _nice_top(v, divs=4):
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v / divs))
    for e in (exp, exp + 1):
        for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
            if m * 10 ** e * divs >= v:
                return m * 10 ** e * divs
    return 10 ** (exp + 1) * divs
```
Pass `divs` matching the actual tick loop — a chart drawing `range(4)` has **3** intervals, so
`divs=3`, or the ticks come out uneven again on that one chart only.

Unit-test it with an explicit quality bar rather than eyeballing: every case must satisfy
`top >= v` **and** utilisation `v/top > 65%` **and** round tick values. Final spread was 85–99%
utilisation across 21.7→24, 1.15→1.2, 205→240, 0.0087→0.01.

**Verify the fix by parsing tick text out of the built HTML — a screenshot re-read can be wrong.**
Vision correctly said "not fixed" after round 1; the authoritative confirmation was:
```python
labs = [html.unescape(x) for x in re.findall(r'>([0-9][0-9.,]*)</text>', frag)]
```
Note the tick `<text>` elements carried no `font-size="9"` attribute — an attribute-anchored regex
returned `[]` and looked like "no ticks exist". Match on element shape, not on styling attributes.

### Compare against a pre-change baseline to prove no regression
Copy `docs/index.html` to `/tmp/index_before.html` *before* rebuilding, then diff structural counts:
```python
for k in ['data-tip', '<svg', '<polyline', 'stale-badge', 'part-title', '未就绪']:
    print(k, old.count(k), new.count(k), new.count(k) - old.count(k))
```
Expected deltas should be fully explainable by the new section (+2 svg, +1 polyline, +1 part-title).
An unexplained delta elsewhere = collateral damage. Caution: pick the metric the project actually
uses — `<title>` moved 1→36 here and looked alarming, but the dashboard's real tooltip mechanism is
`data-tip` (18,766→18,767, i.e. flat). Check several counters before concluding regression.

### Minimum-visibility + third-state markers

`width = max(x(v2)-x(v1), 2.0)` so a tiny delta still renders. And if "no marker" and "marker too
small to see" look identical, the reader can't distinguish them — give the opposite case its own
glyph (declining forecast → dashed vertical tick in a contrasting dark color, white halo underneath
so it reads on a filled bar) and add it to the legend as a third item.

---

## B. Simulated-outage test — proves the 铁律 (抓不到不覆盖真值) mechanically

The project bans fabricated/placeholder values overwriting real data. Assert it, don't assume it.
Monkeypatch the network away and inspect what the fetch + render actually produce:

```
cd src && ../.venv/bin/python -c "
import requests, external_data as ed, dashboard as db, re
orig = requests.get
requests.get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('simulated outage'))
try:
    d = ed.fetch_<name>()
finally:
    requests.get = orig
h = db._<name>_html(d)
print('status =', d['status'], '| note =', d.get('note'))
print('fabricated number leaked?', bool(re.search(r'\d+\.\d+%', h)))
print('HTML >>>', repr(h))"
```
PASS = `status` is a not-found/cache marker, **zero** numeric values in the HTML, and the stub reads
like `<p class="empty">…数据未就绪。（<reason>）</p>`. Run it for every new fetcher before rebuild.

Note: placeholder rating/series shells may still be present in the dict with `status="未找到"` —
that's fine **iff** every render path filters on `status == "ok"`. The outage test is what proves
the filter is actually wired.

### Put the exception TYPE in the note, or bugs masquerade as outages
A `NameError` (module imported at function scope elsewhere, so `requests` was undefined here) was
swallowed by the fetcher's broad `except Exception` and surfaced as `status="未找到"` — visually
identical to "the source is down". It cost a debugging round. Two rules:
- Every fetcher's except block must record the type: `out["note"] = f"<src> 异常: {type(e).__name__}"`.
  Then `note=IMF API 异常: NameError` immediately reads as *my bug*, not *their outage*.
- A brand-new fetcher returning "not found" on its FIRST run is far more likely a code bug than a
  dead endpoint. Before reporting the source as unavailable, re-hit the same URL raw in the same
  process and print `status_code` + record count.
- Don't assume a module is imported at file scope in a large `external_data.py`; several fetchers
  import `requests` locally. Import inside your function.

---

## C. Level indicators need a percentile, not just a period-over-period delta

A "近1月Δ" alone can't tell you whether a level is extreme. Computing each series' percentile within
its own available window turned a modest-looking table into the session's actual finding: CCC OAS at
the **97.6th percentile** of its 3-year range while BB sat at the **10.6th** and BBB at 25.6 —
i.e. distress isolated to the weakest issuers rather than broad credit stress, which the 1-month
column alone understated.

```
s = [v for _, v in r["oas_series"]]
pct = 100.0 * sum(1 for v in s if v <= cur) / len(s)   # guard len(s) >= 30
```
- Label the window honestly: `（区间起自 {series[0][0]}，{n} 个交易日）` — the START DATE, computed
  from the `(date, value)` tuples. Pulling `s[0]` off a values-only list prints a *price* where a
  date belongs (shipped "区间起自 0.51" once; caught on read-back). Always eyeball a rendered
  numeric/date string, not just "the panel appeared".
- Pick the window-describing series from one that actually has data
  (`next((f(r) for r in rs if f(r)), None)`), never `rs[0]` — the first row may be empty.
- When probing a fetcher's output, print `list(r.keys())` first. Guessing `r['oas']` when the field
  is `r['oas_series']` yields an empty result that looks like "no data" rather than a typo.

---

## D. Ordering that avoids wasted 8-minute rebuilds
Standalone-render QA (A) and the outage test (B) are seconds each; the full rebuild is ~8 min. Run
A and B to convergence FIRST. If a fix lands while a rebuild is in flight, that build is stale —
let it exit, then start the definitive one rather than reasoning about which changes it contains.
