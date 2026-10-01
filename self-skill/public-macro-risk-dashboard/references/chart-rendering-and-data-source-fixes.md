# Chart-rendering & data-source fixes (Eco-and-Volatility-Checker)

Session-tested fixes for the trader-screen SVG dashboard. All in `src/dashboard.py`
(rendering) and `src/external_data.py` (fetch). Rebuild = `.venv/bin/python -m src.build_dashboard`
(execute_code is DISABLED incl. cron — always use `.venv` python via terminal). Verify DOM
programmatically (grep/regex over `docs/index.html`) because vision_analyze backend is flaky (400s);
screenshot + send to Chao for the human visual check.

## 1. yfinance index tickers only return 1 point → Yahoo chart API v8 direct
Symptom: MOVE index line vanished; legend showed 现/高/低/中 all identical (e.g. 74.98).
Root cause: `yfinance.download("^MOVE", ...)` from ~2026-08 returns only the CURRENT day (1 point)
for many index tickers (`^MOVE`, likely others). 1 point can't draw a polyline.
Fix: fetch via Yahoo chart API v8 directly with a browser UA — returns FULL history:
```
url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE?range=5y&interval=1d"
r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=25)
res = r.json()["chart"]["result"][0]
ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
# zip(ts,closes), drop None, date=datetime.date.fromtimestamp(t).isoformat()
```
Encode `^` as `%5E`. Pick range by (today-start).days: >1095→"5y", >730→"3y", else "2y".
Keep yfinance as DEGRADED fallback (only use chart-API result if len>=2). `_fetch_move_history`
in external_data.py is the working reference impl. GENERAL: any yfinance-backed series that
suddenly shows 1 point → switch to chart API v8 direct, same shape. stooq has a JS-verify wall
(returns HTML challenge), not usable via curl.

## 2. Dual-axis SVG chart missing Y-axis scale labels
Symptom (A/D line chart): grid lines drawn but NO numeric Y-axis labels either side.
The chart had a left axis (cumulative A/D) + right axis (participation %) but the render loop
only drew grid `<line>`s, no `<text>` ticks, and margins (ml=20) were too narrow for labels.
Fix: widen `ml`→52, `mr`→176; in the 5-grid loop add both:
  - left tick: `<text x=ml-6 ... text-anchor=end fill=<left-series-color>>{cv:.0f}</text>`
    where `cv = chi - crng*k/4`
  - right tick: `<text x=w-mr+6 ... text-anchor=start fill=<right-series-color>>{pv:.0f}%</text>`
    where `pv = phi - prng*k/4`
Color-code each axis's ticks to ITS series color so双轴 are visually distinct (Chao asked for
"红色纵轴 for MOVE" — left axis专属 MOVE → tick color = MOVE line color #c17d6a). In the shared
`_stress_panel_svg`, derive `_left_color` from the first series with axis=="left" so every panel's
left ticks match its left line automatically.

## 3. Add an average / mean horizontal line to a series
Chao likes a mean reference line on trend charts. Pattern:
```
avg = sum(vals)/len(vals)
y = Y(avg)
parts.append(f'<line x1={ml} y1={y} x2={w-mr} y2={y} stroke=<color> stroke-width=1.2 '
             f'stroke-dasharray="6,3" opacity=0.7/>')
parts.append(f'<text x={ml+4} y={y-4} font-size=9 fill=<color>>均值 {avg:.0f}</text>')
```

## 4. Sidebar scroll-spy: getBoundingClientRect, NOT offsetTop
Symptom: left menu didn't bold/follow the section as you scroll.
Root cause: `titles[i].offsetTop` is relative to the offset PARENT, wrong when there's any
positioned/transform/sticky ancestor. Fix: use `getBoundingClientRect().top` (viewport-relative):
```
var trigger=120, active=0;
for(i...){ if(titles[i].getBoundingClientRect().top - trigger <= 0) active=i; else break; }
if((innerHeight+scrollY) >= scrollHeight-4) active = titles.length-1; // bottom → last item
```
Also: on activate, expand its collapsed group and make the SIDEBAR itself follow — if the active
link is outside the nav's visible area, `nav.scrollTo({top: navScrollTop+(linkTop-navTop)
- navHeight*0.33, behavior:'smooth'})`. Bind to both 'scroll' and 'resize'. Verified双向 via
browser_console (scroll to bottom → nav.scrollTop 0→1000 & link visible; scroll to top → back to 0).

## 5. Page section order MUST match sidebar menu group order
Chao: "每个图的顺序应该和左侧 menu 相符". The sidebar JS regroups sections by keyword into
GROUPS[]; if the HTML template's physical `<!-- --> part-title + card` blocks aren't in the same
group order, the visual page jumps around vs the menu. Detection script (reproduce the JS groupOf
in python, walk part-titles in DOM order, flag any group that reappears after another started):
count "disorder" transitions; target = 0. When moving sections, move the WHOLE block (comment +
part-title + card + svg) — never edit chart内容, only position. Back up dashboard.py to
scratch/backups/ first (Chao铁律: 改前必备份). After reorder verify every `{placeholder}` appears
exactly once (no lost/duplicated block).

## 6. Moving a chart between sidebar groups = edit GROUPS[] keywords only
To move charts (e.g.四个贵金属图) from one menu group to another, move their matching keywords
between the `GROUPS` arrays in the sidebar JS. Use a DISTINCTIVE keyword to avoid collateral hits
(e.g. move "自营黄金掉期" to 能源与大宗 but leave "国际清算银行"/"BIS" in 流动性与央行 so the BIS
quarterly-report section stays put). No HTML move needed if you only want the menu grouping to change
— but if Chao wants physical order matched too (see §5), also move the HTML block.

## 7. Free monthly data sources found this session
- **India silver bullion imports (monthly)**: official DGCIS = annual only; Metals Focus monthly =
  paid. FREE monthly = UN Comtrade preview API (no key, 1 period/call, rate-limited):
  `comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=699&period=YYYYMM&cmdCode=7106&flowCode=M`
  CRITICAL口径: take the row with `partner2Code==0` (that IS the World total; summing all partner2
  rows DOUBLE-COUNTS). netWgt is in kg → /1000 = tonnes. Validated: 2024 Jan+Feb = 636.8+2295.3 =
  2932.1t, matches LBMA's公开 2932t. Comtrade lags 1-2 months (latest month may be missing → honest gap).
- **India/China gold domestic premium (daily)**: WGC goldhub `gold-premiums.xlsx` (login-gated,
  Chao downloads it). Sheets: `Indian premiums-discounts` (2012→, ~3800d, US$/oz, 5-day MA, ICE/MCX/
  RBI/NCDEX source), `Chinese premiums-discounts` (2003→). Parse → data/gold_premium_{india,china}.json
  {status,points:[{date,premium}],latest,min,max,n}. This is真数据 for a GOLD premium chart; the SILVER
  premium in Chao's reference image is Metals Focus (paid) — do NOT fabricate, label chart as黄金.

## 8. Daily-cron-vs-manual-build timing trap
If you push new chart code/data AFTER the 11:00 daily cron already ran, that cron's build produced a
PLACEHOLDER ("数据同步中") and committed it to公网. Symptom: local build shows真数据 but Chao's
screenshot shows placeholder. Not a bug — just re-run build manually and commit; from next day the
cron reads the已push真数据 automatically. Always check `git log --format='%ci' -1 -- <data.json>` vs
the cron time when a "why is it placeholder" question comes in.
