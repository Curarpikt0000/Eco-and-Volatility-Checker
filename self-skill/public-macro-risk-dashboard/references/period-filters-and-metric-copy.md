# Client-side period filters & rewriting metric explanations (2026-08-31)

Two recurring Chao requests on the Eco dashboard, both about **legibility rather
than new data**:

1. "给这个模块加一个 本日/本周/本月 的 filter，点一个键就能切换"
2. "改一下你这个 metrics 的说明，让它更清晰一点"

---

## 1. Adding a 本日/本周/本月 filter to an aggregation block

**Architecture: compute all three server-side, embed all three, switch with CSS.**
No fetch on click, no loading state, instant response. The data is small (KB) and
already in memory at build time.

### Data layer — one window helper, `period` kwarg everywhere

Centralise the window arithmetic so the two blocks can never drift apart:

```python
def _kol_period_window(period="week"):
    """→ (win_start, win_end, new_base) as YYYY-MM-DD.
       day   = today            week = last Monday→today (UNCHANGED legacy 口径)
       month = 1st of month→today"""
    today = _dt.date.today()
    this_monday = today - _dt.timedelta(days=today.weekday())
    if period == "day":     start = new_base = today
    elif period == "month": start = new_base = today.replace(day=1)
    else:                   start, new_base = this_monday - _dt.timedelta(days=7), this_monday
    return (start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"),
            new_base.strftime("%Y-%m-%d"))
```

- **`period="week"` MUST be the default and MUST reproduce the pre-change output
  byte-for-byte.** Assert it explicitly — this is what lets you add the feature
  without touching cron or any other caller:

```python
a, b = fn(), fn(period="week")
assert a["total"] == b["total"] and len(a["modules"]) == len(b["modules"])
```

- The `new_base` third value drives the "🆕 new this period" badge, so the badge
  re-scopes with the filter instead of always meaning "this week".

### Render layer — tabs + panes, and keep back-compat

```python
def _kol_multi_period_html(data_by_period, kind, active="week"):
    render = _kol_views_html if kind == "views" else _kol_changes_html
    # ★ back-compat: old callers pass a single dict, not {day,week,month}
    if not isinstance(data_by_period, dict) or not (
            {"day","week","month"} & set(data_by_period.keys())):
        return render(data_by_period, period="week")
    ...  # emit .kp-tabs + three .kp-pane divs, non-active with style="display:none"
```

- Give each block its own `group` id (`kol-views` / `kol-changes`) so the two
  filters operate independently — verify that切一个不影响另一个.
- Thread `period` into the render fn **only for wording** (title, empty-state text,
  the 🆕 badge). Data selection already happened upstream.
- Every empty-state string must re-scope too: `f'{_pl}暂无…'`, never a hardcoded
  「本周」on a pane the user reached by clicking 本月.

### Front-end — one delegated handler, prepended to the existing click listener

The page already had a `document.addEventListener('click', …)` doing drill-downs.
Add the filter branch at the TOP of that same handler with an early `return`,
rather than registering a second listener:

```js
var kp = ev.target.closest ? ev.target.closest('.kp-btn') : null;
if (kp) {
  var grp = kp.getAttribute('data-kp-group'), sel = kp.getAttribute('data-kp');
  /* toggle .on across btns[data-kp-group=grp]; set display on panes[data-kp-group=grp] */
  return;
}
```

Template note: this file's HTML/JS is inside a `.format()` string — **all literal
braces must be doubled** (`{{ }}`), including in the CSS block.

### Verifying without a browser

`browser_exec` was unavailable this session (harness `AttributeError`). Do **not**
skip the interaction test — a static grep only proves the markup was emitted, not
that clicking works.

Working substitute: parse the **built artifact** for the real button/pane
attributes, feed them to a minimal DOM stub, and run the **byte-identical handler
code** under `node`:

```js
const btnRaw  = [...HTML.matchAll(/<button type="button" class="(kp-btn(?: on)?)" data-kp-group="([^"]+)" data-kp="([^"]+)"/g)];
const paneRaw = [...HTML.matchAll(/<div class="kp-pane" data-kp-group="([^"]+)" data-kp-pane="([^"]+)"( style="display:none")?>/g)];
// stub: classList add/remove/contains, getAttribute, closest('.kp-btn'), style.display
// then call the copied handler and assert exactly-one-active / exactly-one-visible
```

Assert: initial state = week only · each of day/month/week activates exactly one
button + one pane · **切换 group A 不影响 group B**. 9 assertions, ~2s, no browser.
Keep the script in `scratch/` (gitignored) for re-runs.

### Interpreting the resulting numbers before reporting

A "month" window can legitimately show **fewer** turns than "week":

| period | window | views | turns |
|---|---|---|---|
| day | today | 127 | 13 |
| week | last Mon→today | 130 | 75 |
| month | 1st→today | 144 | **2** |

Turn-detection is an **endpoint diff** (`latest in window` vs `last snapshot before
window`). Over a month, a KOL who flipped and flipped back reads as unchanged. That
is correct for the chosen 口径 — explain it rather than "fixing" it, and offer the
alternative (per-day cumulative transitions) as a separate option if the user wants
a count of *events* instead of *net change*.

---

## 2. Rewriting metric explanations — the four-part structure

Chao's complaint about the original notes: they opened with the derivation formula,
then immediately spent the most-visible real estate on **internal technical debt**
("真 swap spread 无免费源, FRED DSWP2/10 已停更 2016, OFR 付费…"), while never
explaining what the abbreviation even stood for.

Structure that fixed it — apply to every indicator:

```
【是什么】 plain-language definition + what the abbreviation expands to + data source
【怎么看】 which direction is bad, and the transmission chain (why it predicts anything)
【怎么用】 the actual thresholds, what to pair it with, and how NOT to read it
【注意】   口径 caveats / proxy-substitution debt  ← demoted to LAST
```

Content rules learned from the pass over 20 indicators (avg 30–50 chars → 250–320):

- **Expand every abbreviation on first use.** "CP" meant nothing to the reader:
  *CP = Commercial Paper 商业票据，银行发的短期无担保借条，不押抵押品，纯靠信用*.
- **Flag direction-inverted metrics explicitly.** `put_call`, `bofa_fms_cash`,
  `insider`, `lei` are all **越低越危险**, opposite to the majority. VIX's danger
  for a *top*-detector is also the low end, not the high end. These get a ★ marker.
- **Name the most-likely misreading.** `yield_curve`: inversion means "recession on
  the way (maybe 1-2yr)", but **un-inversion (bull steepening) is the near-term
  signal** — the opposite of the intuitive read.
- **Give historical anchors** so a number has a scale: CAPE 1929≈33 / 2000≈44 /
  2009≈13; HY OAS 2008 >20%; SOFR-IORB 2019-09 repo crisis.
- **State what the metric CANNOT do.** CAPE can sit high for years — using it to
  time exits guarantees missing the move. A/D divergence leads by weeks-to-months.
- **Distinguish near-duplicate cards.** `aaii_bull_bear` = what retail *says*
  (survey); `aaii_alloc` = what retail *did* (allocation). Say so on both.
- **Carry the honesty boundary into the copy itself**: sources with no free feed
  (`bofa_bull_bear`, `ad_line` — web_search cross-checked) must state that they go
  blank rather than reuse a stale value.

### Threshold-consistency self-check (do NOT skip)

The main risk of a bulk copy rewrite is prose that contradicts the live thresholds.
Assert programmatically that every number written in the text exists in that
indicator's actual `warn`/`trigger`:

```python
for m in config.INDICATORS:
    for label, v in (("warn", m.get("warn")), ("trigger", m.get("trigger"))):
        if v is None: continue
        s = "%g" % v
        assert s in m["note"], f'{m["key"]}: note missing {label}={s}'
```

17/17 passed. Also diff every **non-`note`** field against a pre-edit backup to
prove the rewrite touched copy only:

```python
F = ["key","name_zh","name_en","group","source","unit","direction","warn","trigger","status_labels"]
diff = [(a["key"], f) for a, b in zip(old.INDICATORS, new.INDICATORS) for f in F if a.get(f) != b.get(f)]
assert not diff          # → "无 —— 只改了 note"
```

`git diff --stat` should show exactly N changed lines, all containing `"note"`.

### Gotcha: `dashboard.generate()` returns a PATH, not HTML

Verifying the rewrite, I captured the return value as a string and got **74 bytes**,
concluding the render had failed. It hadn't — the function writes the file and
returns its path. Assert against `dashboard/index.html` on disk (≈2 MB, and both
`dashboard/` and `docs/` copies), never against the return value.
