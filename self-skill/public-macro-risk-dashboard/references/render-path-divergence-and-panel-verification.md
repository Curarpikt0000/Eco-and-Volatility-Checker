# Empty panels, divergent render paths, and how to actually verify a rendered panel

Session-proven on Eco-and-Volatility-Checker (2026-09). Three separate traps that all
produce the same user-visible symptom: **"这个板块怎么是空的 / 数据只到 X 日"**.

---

## 1. THE BIG ONE: two render paths that drift apart

### Symptom
User reports a dashboard panel renders `数据未就绪` / `tf-none` empty state, or shows
stale data — but the fetcher works perfectly when you run it by hand.

### Root cause (this project's actual architecture)
There are **TWO independent ways the dashboard gets built**, and they maintain
separate, hand-written fetcher lists:

| Path | Where the fetcher list lives |
|---|---|
| `src/build_dashboard.py` | normal Python, `ed.fetch_*()` calls |
| **the daily cron** | a ~17,000-char **inline mega-command inside the cron job's prompt**, calling 40+ `e.fetch_*()` in one `python -c "..."` |

The cron does NOT call `build_dashboard.py`. When someone adds a panel they typically
update only one path. The missing fetcher is never called → `dashboard.generate()`
receives `None` for that kwarg → the renderer falls into its empty-state branch:

```python
if not cl or cl.get("status") != "ok":
    return '<p class="empty">中国流动性数据未就绪…'
```

**The data layer is completely healthy.** Running the fetcher manually returns
`status=ok` with hundreds of points. This is why "just rerun the fetcher" proves
nothing and misleads you.

### Diagnosis — mechanical set-diff, never eyeball the mega-command
Do NOT try to read a 17k-char one-liner. Extract and diff programmatically
(`scratch/_diff_cron_vs_builder.py` pattern):

```python
import json, re, inspect, sys
sys.path.insert(0, 'src')

jobs = json.load(open('/home/user/.hermes/cron/jobs.json'))
jobs = jobs if isinstance(jobs, list) else jobs.get('jobs', jobs)
jobs = list(jobs.values()) if isinstance(jobs, dict) else jobs
prompt = next(j for j in jobs if j['name'] == '<job name>')['prompt']

cron_fetchers = set(re.findall(r'\be\.(fetch_[a-z0-9_]+)\(', prompt))
bd_src        = open('src/build_dashboard.py').read()
bd_fetchers   = set(re.findall(r'\bed\.(fetch_[a-z0-9_]+)\(', bd_src))

print('only cron   :', sorted(cron_fetchers - bd_fetchers))   # builder would LOSE these
print('only builder:', sorted(bd_fetchers - cron_fetchers))   # ← the empty-panel root cause

# and the kwargs actually passed to generate()
import dashboard
params = list(inspect.signature(dashboard.generate).parameters)
def kwargs_after(src, marker, span=8000):
    if marker not in src: return set(), False
    return set(re.findall(r'[\s(,]([a-z_][a-z0-9_]*)\s*=', src.split(marker)[-1][:span])), True
```

**Gotcha that produced a wrong answer mid-session:** `build_dashboard.py` calls
`dash.generate(` (aliased import), the cron calls `dashboard.generate(`. A regex
hardcoding one alias reports "builder fails to pass 54 of 54 params", which is
absurd on its face — the builder demonstrably renders every panel. **If a diff says
one side is missing ~everything, your extractor is broken, not the code.** Try both
aliases (`grep -n 'generate' src/build_dashboard.py` to find the real call site).

### Real numbers from this session (useful as a sanity baseline)
- cron: 38 fetchers · builder: **40** · `only cron` = **0** · `only builder` =
  `fetch_china_liquidity`, `fetch_cb_liquidity_swaps` ← exactly the two blank panels
- `generate()` has **54** params; cron omits 7, builder omits 3
- The builder's 3 omissions are `ai_reads` / `ai_conclusions` / `daily_notes`, all
  read from an **already-persisted** `data/ai_analysis_<date>.json`
  (keys `reads` / `notes` / `conclusions`) — **plain file read, no LLM, no network**

### Consequence for the fix
A one-off `build_dashboard.py` rerun repopulates the panel, but **the next cron run
blanks it again**. Always tell the user this explicitly — a "fixed" panel that
reverts overnight destroys trust. Say: *"已填上，但明天 11:00 cron 一跑会再变空，因为
根因在 cron 侧还没修。"*

### Beware stale in-prompt warnings
The cron prompt carried `★不能改用 build_dashboard.py: 它不读 ai_analysis，会丢 AI 短评`.
That warning had gone **stale** — the gap was 3 kwargs sourced from a file already on
disk. A prohibition written into a prompt is a claim with a timestamp, not a law;
re-verify it before accepting it as a blocker.

### Prevention (the durable fix)
Single source of truth: cron invokes `python src/build_dashboard.py`. Plus a
**hard gate** — compare `inspect.signature(generate)` params against kwargs actually
passed and raise LOUD on any omission, so the third recurrence is impossible.
See `add-new-dashboard-section.md` for the add-a-panel checklist that must touch
both paths until the consolidation lands.

---

## 2. Verifying a panel: how a verification script produced a FALSE PASS

This nearly shipped a bogus "✅ clean" verdict.

**What went wrong.** The script located the panel with `h.find('国债拍卖')` and scanned
the following 20 KB. But the first textual occurrence of a panel title in these
dashboards is inside a **CSS comment** (`/* 国债拍卖 timeline */ .auc-wrap { … }`), so
it scanned a stylesheet, found zero yields, and reported *"抽到 0 个收益率 → 无低于 3%
→ ✅ 干净"*. **Zero data points must never satisfy a data-integrity assertion.**

**Correct anchoring — target rendered class instances, not the title string:**

```python
cands = [m.start() for m in re.finditer(r'class="auc-', h)]   # 244 real instances
if not cands:
    raise SystemExit('no rendered instances — panel did not render at all')
seg = h[cands[0]: cands[-1] + 3000]
```

**Rules that follow:**
- Assert a **non-zero sample count** before evaluating any "is it clean" predicate.
  `found == 0` is an inconclusive/FAIL result, never a pass.
- Distinguish *CSS definition* from *rendered instance*: `.cbs-b { … }` in a
  `<style>` block vs `class="cbs-b"` in the body. Grep for `class="<prefix>` .
- Empty-state fingerprints in this codebase: `class="empty"`, `tf-none`,
  `数据未就绪`, `未获取`, `数据同步中`. Grep the panel segment for all of them.
- Positive evidence beats absence of negatives: assert the panel contains N bars /
  rows / dated points and that values fall in a plausible band.

## 3. `rc=0` and an empty grep are NOT verification

A background rebuild returned `rc=0` while its `grep -E '国债拍卖|auction'` filter
matched nothing — the log simply doesn't print that label. Neither the exit code nor
the silent grep says anything about panel content. **Always read the rendered
artifact.** (Related known trap: in a pipeline the exit code can come from `tee`, not
the python process.)

Cheap freshness cross-check before deep-diving: compare file size and mtime across
builds. `6.6 MB → 7.1 MB` after adding two panels is corroborating evidence; a
`docs/index.html` that is smaller and older than the last cron run means **you are
inspecting a stale file**, which mimics a data bug perfectly. This wasted a diagnostic
round this session.

---

## 4. "Data stopped at date X" is usually a real-world calendar, not a bug

Before treating a stale-looking date as breakage, check whether the SOURCE simply
hasn't published. Two confirmed non-bugs in this project:

- **Treasury auctions "stuck" at 08-25** — that IS the most recent 2-Year auction.
  Each of the 7 tenors has its own irregular calendar (latest spread across
  08-11…08-27) and the `upcoming` banner correctly showed the next one (09-08 3-Year).
- **ETF weekly net flow "only to 08-24"** — 08-24 is the **Monday anchor** of a weekly
  bucket covering 08-24…08-28, not a cutoff. Re-aggregating the daily series
  reproduced the weekly bars exactly.

Recommended remedy for the second class: label weekly buckets as a **range**
(`08-24 ~ 08-28`) so an anchor date is never misread as staleness.

---

## 5. Filtering by "type"/"term" is not enough — TIPS pollutes nominal yield curves

Found while cross-checking a user screenshot, not from any error.

**Symptom:** two rows inside the nominal Treasury auction panel with roughly half the
expected size and yield:

| Tenor | Date | Size | Yield | neighbouring nominal |
|---|---|---|---|---|
| 10-Year | 2026-07-23 | 21.0 B | **2.438 %** | 42.0 B / 4.683 % |
| 30-Year | 2026-02-19 | 9.0 B | **2.473 %** | 25.0 B / 5.216 % |

**Cause:** these are **TIPS**. TIPS report a *real* (inflation-adjusted) yield and are
issued in much smaller size, so mixing them into a nominal series makes demand look
like it collapsed. `security_type` is still `Note`/`Bond` and `security_term` is still
`10-Year`, so the existing filter could not exclude them.

**Fix — use the official discriminator, don't infer from magnitudes:**
```python
if str(x.get("inflation_index_security") or "").strip().lower() in ("yes", "y", "true"):
    continue
```
Corroborating fields present only on TIPS rows: `cpi_base_reference_period`,
`index_ratio_on_issue_date`, `adj_price`, `adj_accrued_int_per1000`.

**Method worth repeating:** rather than guessing from the numbers, pull the SAME row
from the upstream API with *all* fields and diff it against a known-good row —
`inflation_index_security: Yes` vs `No` fell straight out. Chao's standing rule is that
an anomaly claim needs an authoritative field, not a plausible story.

**Generalize:** any "latest N auctions/prints per bucket" view should exclude
instrument variants that share type+term labels but differ in quoting convention
(TIPS, FRNs, reopenings, micro contracts). Post-fix assertion: every nominal yield in
the rendered panel sits in a sane band (observed 3.965–5.216 %); anything under ~3 %
is a red flag.

---

## 6. Darkening the palette without breaking legibility

Chao asked for "底色再暗一点，太凉了" — that is *warmer AND darker*, not just darker.
The Morandi palette lives in `src/dashboard.py` `:root`.

Applied: `--bg #e8e4dd → #ddd6ca` (relative luminance −13 %),
`--card #f2efe9 → #eae4d9` (−10 %), with `--border`/`--text`/`--muted` deepened in step.

**Always verify WCAG contrast after a palette change** — compute relative luminance
and contrast ratios (body text ≥ 4.5, secondary ≥ 3.0) rather than judging by eye.
Here all four pairs *improved*, and it surfaced a pre-existing violation: secondary
text on background was **2.96 (failing)** and became 3.15. Reusable checker:
`scratch/_chk_contrast.py`.
