# Upgrading a static monitoring TABLE into a time-series WARNING panel

Chao's recurring ask: he has (or sends screenshots of) a **static monitoring table** — rows of
current values + status lights (e.g. "表2 美债基差套利监控", "表3 SOFR倒挂监控", "表5 日债基差套利").
He wants it "做成图 … 最能帮我预警 … 然后行动". The correct response is NOT to reproduce the table —
it's to **升级成时序预警面板**. This file is the reusable method. Realized this session building the
基差套利去杠杆预警 (basis-trade deleverage) panel into the Eco dashboard.

## Why time-series beats the static table (say this to Chao, it's the core insight)
A static table only shows the CURRENT snapshot — you can't see a metric **逼近临界的过程**, so you
can't act early. A time-series chart shows the演进 (SOFR creeping toward IORB, carry narrowing, vol
building) so the warning fires BEFORE the blow-up. The whole point of a预警 dashboard is lead time.

## Step 1 — reverse-engineer the analytical framework behind the table
Before any code, work out WHAT RISK the table monitors and WHAT THE TRIGGER CHAIN is. Write it as a
one-line causal chain, because it becomes the panel's narrative + the合成灯 logic.
Example (basis trade): funds buy cash bonds / sell futures, repo-lever 33–99×; they're force-
deleveraged when 融资成本↑(SOFR→IORB封顶) + carry消失(收益率−SOFR收窄/倒挂) + 波动↑(MOVE) →
套利亏损 → 强平 → 抛债 → 收益率跳升 → 踩踏 (the 2020-03 pattern).
That chain → THREE panels (① funding cost ② carry space ③ vol×buffer trigger) + a合成灯 that lights
🔴 when the chain's links align.

## Step 2 — check whether it's already wired (it usually isn't)
`search_files` the repo for the table's Chinese terms (基差套利/SOFR倒挂/去杠杆). A table that was
only ever hand-computed by an agent in a past daily report leaves NO fetcher/data-file/render fn —
confirm that (only a top-level 信号灯 string like `"基差套利风险": "🟡"` exists) so you know you're
building fresh, not duplicating.

## Step 3 — confirm you can get every series REAL before designing
This project already has `FRED_API_KEY` + `_fred_series_hist(sid, start)` (key API + curl CSV double
channel, 3× retry) and `_mof_jgb_yields(col)` for JGB. Probe each needed FRED id with a SMALL batch
(2–3 ids per `.venv/bin/python -c` call — 10 serial curls time out the 60s terminal). Core basis-
trade series, all free & real:
- `SOFR` (overnight funding cost), `IORB` (corridor top / SOFR ceiling), `EFFR`, `RRPONTSYAWARD`
  (ON-RRP award rate = corridor floor)
- `DGS1/2/5/10/30` (UST tenor yields), `WRESBAL` (Fed reserves — **units = 百万$, divide by 1e6 for $T**;
  a wrong /1000 shows "$2.9T" as "2944". ALWAYS pull one sample row and eyeball the magnitude before
  fixing the divisor.)
- JGB via `_mof_jgb_yields`: col6=2Y, col9=5Y, col10=10Y, col14=30Y (col0=Date).
- **No clean free daily JP overnight (TONAR) series exists** → do NOT fabricate a constant. Show JGB
  yields + trend only on the日债 rows, mark carry `n/a` with an ⓘ note ("carry 不做主判定"), keep the
  US carry (clean SOFR corridor) as the reliable judgment. Honest partial > fake completeness.

## Step 4 — reuse the double-axis SVG renderer, don't write a new plotter
`_stress_panel_svg(panel, w, h)` already draws double/single-axis multi-line panels with tip-hit
hover circles, ▲max/▼min/current/median markers, right-side legend. Each of the 3 time-series panels
is just a `panel` dict:
```
{id, title, subtitle, unit_left, unit_right, single_axis(bool),
 series:[{name,color,axis('left'/'right'),dash(bool),width,points:[{date,v}]}], source}
```
Build panels in the fetch fn (`fetch_basis_trade_monitor`), return
`{panels:{funding,carry,trigger}, matrix:[...], lights:{...}, asof, status}`.
- **Carry = yield − SOFR in bp**: intersect DGS<tenor> dates with SOFR dates, `(y−s)*100`, weekly-
  resample (`_weekly_resample`, agg='last') to denoise a 2yr daily series.
- **合成灯 thresholds** (encode Chao's risk logic): funding 🔴 if SOFR−IORB≥0 / 🟡 ≥−5bp / 🟢 else;
  carry 🟢 >30bp / 🟡 0–30 / 🔴 <0 (inverted = arb loses money); vol 🔴 MOVE≥120 / 🟡 ≥100 / 🟢 else.

## Step 5 — add a per-tenor status MATRIX with sparklines (the table's true replacement)
This is what actually replaces the static table: a `.bt-matrix` grid, one row per tenor
(美债 2/5/10/30Y + 日债 10/30Y), columns = 市场 | 期限 | 灯 | Carry(yield−SOFR) | 收益率 | 近30日走势.
The走势 column is a hand-drawn mini `<svg class="bt-spark">` polyline of the last 30 points (write a
tiny `_bt_sparkline(vals)` helper; end-dot colored by direction). Header + 6 rows. This keeps the
familiar "table" affordance Chao's original had, but each cell is now data-driven + trend-aware.

## Step 6 — top合成灯条 (3 lamp cells) for at-a-glance state
Above the 3 charts, a `.bt-lampbar` of 3 `.bt-lamp` cells (icon + label + detail): 融资成本 /
套利Carry / 波动率, reading `lights.funding/carry/vol` + the numeric detail (SOFR−IORB +0bp, 最紧
+53bp, MOVE 71). This is the "已经进入哪一步" summary of the trigger chain.

## Step 7 — wire + verify (same as add-new-dashboard-section.md steps 4–8)
Signature param `basis_trade=None`, `.format` entry, template `<div class="card">{basis_trade}</div>`
(placed after国债市场压力四联图 — same 国债流动性观测 sidebar group), sidebar keyword
"基差套利去杠杆预警" + "SOFR 倒挂", build_dashboard.py fetch try-block + generate() arg.
Verify programmatically (vision 400s): grep the rendered html for `bt-lamp`(=3), `bt-mrow`(=header+6),
`bt-spark`(=6), the 3 panel titles, then JS-simulate `mouseover` on a `.tip-hit` and assert a
`.show` tooltip element appears with the expected `data-tip` text.

## Pitfall — patch-replace that eats a guard clause
Inserting a new fn via patch just BEFORE an existing one can accidentally swallow the next fn's
`if not X: return <placeholder>` guard when the old_string/new_string overlap. After any such insert,
re-read the FOLLOWING function's head and confirm its guard clause survived (a build with `cb=None`
would otherwise crash on `cb.get(...)`). Run `ast.parse` on all three edited files as a cheap check.
