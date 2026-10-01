# Reusable chart TYPES + the whole-dashboard hover-tooltip mechanism

Companion to `add-new-dashboard-section.md`. That file covers wiring a new data source into a
section; THIS file covers (A) chart TYPES beyond the shared `_yield_curves_svg` line helper, and
(B) the one-time interaction upgrade that makes EVERY chart show横纵坐标 on hover. Both realized in
the Eco-and-Volatility-Checker (`~/Projects/Eco-and-Volatility-Checker`, repo Curarpikt0000).

## A. Whole-dashboard hover tooltip — "所有图 hover 显示横纵坐标" (Chao standing request)

Chao's request: hovering any point on any line, or any bar, must show that point's date + value.
This is a GLOBAL interaction layer, not a per-chart edit. The dashboard has ~19 SVG-drawing
functions (`_*_html` / `_*_svg`) emitting `<rect>` (bars), `<polyline>` (lines), `<circle>` (markers).
Solved for all of them with ONE mechanism + a mechanical pass over each draw function.

### The mechanism (add ONCE, near the CSS `</style>` and JS `</script>` of the page template)
The page template in `dashboard.py` is a `.format()` string → **all literal braces must be doubled
`{{ }}`** or `.format` throws KeyError. (An f-string helper does NOT have this constraint; know which
you're editing.)

1. **CSS浮层** before `</style>`: a `#chart-tip` fixed-position div (morandi dark `rgba(58,54,47,.96)`,
   `pointer-events:none`, `z-index:9999`, `opacity` transition), `.tip-d` (date, muted) + `.tip-v`
   (value, bold) child classes, and `circle.tip-hit{{fill:transparent;stroke:none}}` +
   `circle.tip-hit:hover{{fill:rgba(192,138,125,.18)}}`.
2. **JS事件委托** before `</script>`: create/reuse the `#chart-tip` div, then delegate on `document`:
   - `mouseover` → `ev.target.closest('[data-tip]')`; if hit, read `data-tip`, split on `||` into
     `date||value`, render `<div class=tip-d>date</div><div class=tip-v>value</div>`, add `.show`.
   - `mousemove` → reposition (flip left if near right edge, flip below if near top); hide if not over
     a `[data-tip]`.
   - `mouseout` on a `[data-tip]` → hide.
   Delegation means it works for ALL current AND future charts with zero per-chart JS.

### The data-attribute pass (give every data element a `data-tip="日期||值+单位"`)
- **Bars (`<rect>`):** rects are wide → hover directly. In each bar-draw loop append
  `data-tip="{_esc(date)}||{v:.1f} 单位"` to the `<rect>`. Trivial, ~1 line per bar function.
- **Lines (`<polyline>`):** a polyline is ONE element — you CANNOT hover individual points on it.
  Fix: after drawing the polyline, loop the same points and emit a **transparent wide hit circle** per
  point: `<circle class="tip-hit" cx=.. cy=.. r="6" data-tip="序列名 · 日期||值单位"/>`. r=6-7 gives a
  comfortable hover target. These are invisible (transparent fill via the CSS class) but catch the mouse.
- Multi-series charts (`didx`/`qidx`/`yidx` + per-series loop, like `_stress_panel_svg`,
  `_yield_curves_svg`, `_gold_premium_html`, `_credit_impulse_long_svg`): add the hit-circle loop
  inside each series' `if len(pts)>=2:` block, prefixing the series name into the tip.
- Pick the unit from whatever the function already has (`unit`/`val_fmt`/`panel.get("unit_left")`).

### Pitfalls (cost real time this session)
- **f-string cannot contain a backslash in the expression part.** `f'...{X(didx[p[\'date\']])}...'`
  is a SyntaxError. Hoist to plain vars first: `_pd = p["date"]; _cx = X(didx[_pd])` then interpolate
  `{_cx:.1f}`. Bit us on `_credit_impulse_long_svg`.
- **Doubled-brace only in the `.format()` template**, never in the f-string draw helpers. Mixing them
  up gives KeyError at build time.
- **`_esc()` every date/name** that goes into `data-tip` (they can contain `&`, `<`).
- Escape `&` in literal legend text you put in a tip (`S&amp;P500`).

### Verify programmatically (vision backend 400s — do NOT rely on it)
Build, then in the browser console (or on the built HTML) count + fire synthetically:
```
grep -o 'data-tip="' dashboard/index.html | wc -l          # total tips (~14k here: 281 bars + rest line-pts)
grep -o 'class="tip-hit"' dashboard/index.html | wc -l     # line hit circles
```
In `browser_console`, dispatch a synthetic `mouseover` at a `rect[data-tip]` / `circle.tip-hit`
bounding-rect and assert `document.getElementById('chart-tip').classList.contains('show')` + the
rendered `innerHTML` — this proves the delegation works without needing vision. Screenshot with a
tip forced-visible (set `tip.style.left/top` after firing) and send via MEDIA: for Chao's eyeball check.

## B. Dual-axis GROUPED bar chart (two entities, different units, side-by-side per period)

Realized as `_fiscal_budget_html` (日美年度财政花费). Use when comparing TWO series with DIFFERENT
units per category (US $T left axis vs Japan 兆円 right axis), one pair of bars per period.
- Each axis scales independently: `us_max=max(us_vals)*1.15`, `jp_max=max(jp_vals)*1.15`; `YUS`/`YJP`
  map to the same pixel plot area. Left y-labels colored with entity-A color, right with entity-B.
- Per period, group center `GX(i)=ml+(i+.5)*group_w`; entity-A bar at `gx-bw-1`, entity-B at `gx+1`,
  `bw=group_w*0.30`.
- **"已确定 vs 进行中/预测" distinction** (Chao wanted current-FY-in-progress marked differently):
  use an SVG `<pattern>` diagonal hatch fill for the partial/forecast bar + a stroke outline, solid
  fill for confirmed. Define `<defs><pattern id="fb-hatch-us" patternTransform="rotate(45)">…` once.
  The status comes from the fetch (`status:"confirmed"|"partial"`), NOT guessed at render.
- Legend row shows solid-A, solid-B, and a hatch swatch labeled "斜纹=进行中".
- Add `data-tip` to every bar (part A): `data-tip="美国 FY{fy} {已确定|进行中截至X}||${v}T"`.

## C. Fiscal-spending data sources (free, no-key, verified this session)

### US federal outlays (government total spending) — US Treasury MTS,免key
- Dataset: Monthly Treasury Statement, `.../v1/accounting/mts/mts_table_5` (outlays table).
- **`line_code_nbr:eq:5691` = "Total Outlays"** (probe table 5 for a single record_date and grep
  `classification_desc` containing "Total" to find it; table 9's net_outly fields are NULL — wrong table).
- Fields: `current_month_net_outly_amt` (that month), `current_fytd_net_outly_amt` (FISCAL-year-to-date
  cumulative). **US fiscal year starts Oct 1**, so month 09 (Sep) FYTD = full-year actual. Pull each
  FY's Sep row (`record_calendar_month:eq:09`) for confirmed annual totals; pull the latest row for the
  in-progress FY's to-date cumulative (mark `partial`). `/1e12 = $T`.
- If the user wants "每年1/1清零" but the fiscal year isn't Jan-based, say so — US=Oct, Japan=Apr. For
  a two-country comparable chart, "one bar per fiscal year" (Chao's chosen方案A) sidesteps the
  clash; a literal Jan-based cumulative would require self-recomputing monthly (US only, JP has no
  monthly source).

### Japan general-account budget (一般会計当初予算) — no monthly source, use official annual静态表
- Japan has NO free monthly expenditure API like US MTS. It publishes ANNUAL budgets (当初予算 initial /
  補正 supplementary) + year-end 決算. So Japan's line is a **year-per-bar 当初予算 static table**, not a
  monthly cumulative. This is a real constraint — don't promise逐月 for Japan.
- FY2026 (令和8年度) = **122.3兆円** (+7.1兆 YoY), confirmed via 首相官邸「予算の概要」PDF
  (kantei.go.jp/contents/topics/40621_ext_20_1.pdf). Historic 当初予算 are stable authoritative public
  numbers — bake a `JP_GENERAL_BUDGET = {year: 兆円}` dict in external_data.py; update ONE row each Dec
  when the new budget is announced. All rows are `confirmed` (当初予算 = year-start committed盘子).

### General pattern for "annual bar over N years"
- fetch returns `{us:[{fy,value_t,status}], jp:[{fy,value_oku,status}], as_of, source}`; keep last ~11 FYs.
- US auto-updates every daily build (MTS is live-API); JP is the annual static dict. Honest labels:
  US=Total Outlays 财年累计, JP=一般会计当初予算 补正前.
