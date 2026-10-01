# Build recipe — public-macro-risk-dashboard (Eco-and-Volatility-Checker)

Session-specific implementation detail. Repo `~/Projects/Eco-and-Volatility-Checker`.

## File layout (src/)
- `config.py` — SSOT: `INDICATORS` list (each: key/name_zh/name_en/group[short|mid|long]/source[fred|web|derived|search]/fred_id|url/unit/direction[high_bad|low_bad]/warn/trigger/note), `SELL_TRIGGERS` (7), `NOTION_DB` map (indicators/cot/report/weekly), `COT_MARKETS`, `COT_COMM_SURGE_THRESHOLD`.
- `fetchers/` — `fred.py` (fetch_fred_latest w/ 3-retry, fetch_fred_history), `cot.py` (CFTC Socrata, fetch_latest/fetch_history + comm_net WoW + surge flag), `web.py` (anti-scrape parsers + margin_debt history-file fallback), `util.py` (http_get with browser headers, jina_get w/ retries+X-Return-Format, with_timeout hard-timeout wrapper).
- `notion_writer.py` — `_req`, `upsert` (query-by-title → PATCH-or-create), `read_back`, prop_* helpers.
- `signals.py` — `light(ind,value)` → 🟢🟡🔴⚪, `group_stats`, `eval_sell_triggers` (returns checks + hit count), `overall_signal`.
- `run.py` — daily main: fetch_all (fred/web/cot + margin_gdp derived) → snapshot json → write 3 DBs → history_getter_factory.
- `dashboard.py` — HTML gen (see below). `external_data.py` — sibling-DB readers. `report_writer.py` — Notion page body + GitHub copies + weekly. `backfill.py` — weekly history; daily-backfill was a scratch one-off.

## Threshold string (red/yellow/green legend on each card)
```python
def threshold_text(ind):
    warn, trig, d = ind.get("warn"), ind.get("trigger"), ind.get("direction")
    if warn is None or trig is None: return "无数值阈值（定性判断）"
    us = "%" if ind.get("unit") == "%" else ""
    if d == "high_bad":  # value 越高越危险
        return f"🟢<{warn}{us} · 🟡{warn}–{trig}{us} · 🔴≥{trig}{us}"
    return f"🟢>{warn}{us} · 🟡{trig}–{warn}{us} · 🔴≤{trig}{us}"   # low_bad
```

## 2-week sparkline SVG (bold + area fill, morandi trend colour)
```python
def sparkline_svg(points, direction="high_bad", w=140, h=36):
    vals = [v for _, v in points]
    if len(vals) < 2: return '<span class="spark-na">数据不足</span>'
    lo, hi = min(vals), max(vals); rng = (hi-lo) or 1; pad=3; n=len(vals)
    pts = [f"{pad+i*(w-2*pad)/(n-1):.1f},{h-pad-(v-lo)/rng*(h-2*pad):.1f}" for i,v in enumerate(vals)]
    rising = vals[-1] > vals[0]
    bad = rising if direction=="high_bad" else not rising
    color = "#c08a7d" if bad else "#9aab97"   # 陶土红 worse / 鼠尾草绿 better
    fill  = "rgba(192,138,125,0.10)" if bad else "rgba(154,171,151,0.12)"
    dx,dy = pts[-1].split(","); area = f"{pad},{h-pad} "+" ".join(pts)+f" {w-pad},{h-pad}"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="{fill}"/>'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
            f'<circle cx="{dx}" cy="{dy}" r="2.8" fill="{color}"/></svg>')
```
`load_history(snap_dir, key, days=14)` reads the daily snapshots; daily-backfill近30天 from FRED daily so this isn't empty on day one.

## Morandi palette (CSS :root)
```
--bg:#e8e4dd --card:#f2efe9 --card2:#e3ddd3 --border:#cdc6ba --text:#4a463f --muted:#8a8377
--sage:#9aab97/--sage-bg:#dfe6dc  --clay:#c08a7d/--clay-bg:#ecd9d3  --mustard:#c9ac6b/--mustard-bg:#ece2c8
--dust-blue:#8ea1ad/--dust-blue-bg:#dbe2e6 --mauve:#a693a0
```
Card = `border-left:4px solid <light-colour>`, value = monospace 24px, 📌 daily-note on `--dust-blue-bg`, "如何看" on `--card2`. Trader-screen = info density in this palette, NOT a dark theme.

## generate() signature (all the injectables)
```python
dashboard.generate(snap, checks, hit, gstats, overall,
    ai_reads=<{key:2-3句解读}>, ai_conclusions=<{short,mid,long}>,
    daily_notes=<{key:一句话短评}>, kol_changes=<[{kol,sector,prev_dir,new_dir,date,comments,targets}]>,
    liquidity=<external_data.fetch_liquidity_points()>)
```
Writes `dashboard/index.html`, `dashboard/scan-<date>.html`, AND `docs/index.html` (Pages). `_rule_conclusions()` is the规则兜底 when the agent didn't supply AI conclusions.

## external_data.py — sibling-DB readers (READ-ONLY, same Notion token)
- KOL by_day DB `32347eb5fd3c8087b9c0f409f95f664e` fields: Date/Name of KOL/主导方向/Sector/Comments/方向明细/多空标的. `kol_stance_changes(days)` groups by KOL, flags 主导方向 != previous. **This is the FALLBACK.**
- `load_registry()` reads `data/kol_registry.json` (80 KOL, copied from Economy-KOL-to-Notion GitHub). `load_independent_kol()` reads Eco's OWN `data/kol_independent.json` — **preferred**; the cron agent writes it by web_searching ~20-25 core KOL itself.
- Economic-Dashboard liquidity DBs: A5 Fed liquidity `4df3fc720f0c4cdc902cb18c009e4802` (Reserves_T/ON_RRP_B/TGA_B), A1 yields `76f9359788ef481faeba19e5b74d5dc4` (10Y/2Y/30Y), A6 risk report `750f9b463e234537bc7c07213da4d8fb` (风控灯 selects + AI短评/操作建议/关键变动 rich_text). `fetch_liquidity_points()` returns the latest row + day-over-day delta + risk lights + key-change text.

## Notion page-body blocks (report_writer.py)
Helpers: `_h2/_h3/_p/_bullet/_callout(text,emoji)/_divider`. Text capped 1990 chars (Notion 2000 limit). `_clear_page_blocks(pid)` DELETEs existing children first. `write_daily_page_content(date, payload)` builds the 6-part skeleton + sector_analysis (split on `\n\n` into paragraphs) + KOL + liquidity, then PATCHes children in ≤90-block batches. `write_github_copy(date, md, json)` → reports/<date>.md + latest.md + data/daily/<date>.json. `write_weekly(week_label, payload)` → weekly DB row + reports/weekly/<week>.md.

## Anti-scrape source parse anchors (verified 2026-08, use via web_extract through r.jina.ai/)
- AAII allocation `aaii.com/assetallocationsurvey` → `Stocks Total XX.XX%`; sentiment公开页无当周数 → 用官方 `files/surveys/sentiment.xls` or web_search.
- CBOE `cboe.com/us/options/market_statistics/daily/` → `EQUITY PUT/CALL RATIO 0.XX` (CDN json/csv return 403).
- GuruFocus insider `/economic_indicators/4359/insider-buysell-ratio` → `is currently 0.XX` (Cloudflare-blocked direct).
- Conference Board LEI `/topics/us-leading-indicators/` (trailing slash, bot-JS) → `LEI is down by only X% over the first half` (6-mo) + `(LEI) for the US ... in <Month Year> to <level>`.
- FINRA margin `.../margin-statistics` → table row `Mon-YY | 1,502,072` (百万 ÷1000 = 十亿$); xlsx direct = 403, so scrape the ~13-month table via web_extract and keep `data/margin_debt_history.json`.
- Buffett `currentmarketvaluation.com/models/buffett-indicator.php` (direct requests OK) → `we calculate the Buffett Indicator as XX%`.
- CAPE `multpl.com/shiller-pe` (direct OK) → `Current Shiller PE Ratio is XX.XX`.
- Renaissance IPO `renaissancecapital.com/IPO-Center/Stats` (direct OK) → `There have been NN IPOs`.
- FRED (VIXCLS, BAMLH0A0HYM2, T10Y2Y, DGS10/2, DFII10, DTWEXBGS) + CNN F&G `production.dataviz.cnn.io/index/fearandgreed/graphdata` (needs Win UA + Referer to beat 418) — all reliable, script-fetched.
- NAAIM = paywalled since 2026-08-01, label停更, don't fabricate.

## Enable GitHub Pages
```
gh repo create Curarpikt0000/Eco-and-Volatility-Checker --public
git push -u origin main
gh api -X POST repos/Curarpikt0000/Eco-and-Volatility-Checker/pages -f 'source[branch]=main' -f 'source[path]=/docs'
# live URL: https://curarpikt0000.github.io/Eco-and-Volatility-Checker/   (no-auth curl 200 = live)
```
