# Money-supply M0/M1/M2 data sources (US / JP / CN) — verified 2026-08

Feeds the `_money_supply_html` bottom-block. `fetch_money_supply()` returns
`{US/JP/CN: {name,flag,unit,as_of,m0,m0_label,m1,m2,(m3),source, [status]}}`.
Absolute rule: **never编数字** — a country with no fresh fetch keeps its last override value and the weekly cron notes "待官方发布".

## Which source per country (and why FRED is NOT usable for JP/CN)

- **US = FRED direct,免key, auto-latest.** `curl "https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>"`, take the last non-`.` line = latest `(date,value)`. Series:
  - M1 = `M1SL`, M2 = `M2SL` (both monthly SA, $Billions).
  - "M0" — the US has NO official M0; use **`BOGMBASE` (Monetary Base)** as the代理, labelled 基础货币 Monetary Base. (`CURRCIR` currency-in-circulation exists but updates ~8 months slower — don't use as the main M0.)
  - `_fred_latest(series_id)` helper: GET the csv, iterate lines from the END, first value that isn't empty/`.` wins. `as_of` = max date across the three.
- **JP = BOJ official (FRED's Japan series are DEAD).** FRED's `MANMM101JPM189S`/`MYAGM1JPM189S`/`MABMM301JPM189S` etc. come from OECD and **stopped 2013–2023** — do NOT use them. Use BOJ:
  - Money Stock (M1/M2/M3/L): `https://www.boj.or.jp/en/statistics/money/ms/index.htm`; monthly PDF `.../ms/ms<YYMM>.pdf` (e.g. `ms2607.pdf` = 2026-07), released 次月第2工作日.
  - Monetary Base (≈M0): `https://www.boj.or.jp/en/statistics/boj/other/mb/index.htm`; `.../mb/base<YYMM>.pdf`, released 次月第3工作日.
- **CN = PBoC official (FRED's China series are DEAD).** FRED `MYAGM2CNM189N` stops 2019-08, `MANMM101CNM189N` 2023-11, no China M0 series — do NOT use. China is one of the few countries that officially publishes M0/M1/M2 all three:
  - PBoC 货币政策执行报告 (quarterly, full M0/M1/M2 text) + 金融统计数据报告 (monthly, 次月10-15日): `http://www.pbc.gov.cn`.
  - East Money `https://data.eastmoney.com/cjsj/hbgyl.html` and Trading Economics `zh.tradingeconomics.com/china/money-supply-m2` transcribe PBoC (free web, cross-check only).

Because JP/CN have no stable free API, `fetch_money_supply()` reads them from **`data/money_supply_override.json`** (a small hand/agent-maintained file, IN git — public data). The weekly cron's agent step uses `web_extract` on the BOJ/PBoC/TE pages to refresh the override when `as_of` is stale, then re-runs the fetch. US always overrides the override with live FRED at fetch time.

## ★★BOJ Money Stock 速报 PDF — the column-order trap (a subagent got this WRONG; verify)

The BOJ Money Stock 速報 PDF has a **TWO-ROW stitched header**. When you `pdfplumber` extract text, a data row like the 2026/7 line looks like:

```
7  1,297.0  1,293.6  1,641.2  1,637.2  1,090.5  109.9  980.6  528.9  21.9  2,338.4  2,330.6
```

The real column order (decoding the two header rows together) is:
`月 | M2 | M2季调 | M3 | M3季调 | M1 | 準通貨 | 現金 | 預金 | ? | CD | 広義流動性L | L季调`

So for 2026/7: **M1 = 1,090.5**, **M2 = 1,297.0**, **M3 = 1,641.2**, **L = 2,338.4**.

A delegate subagent read the columns left-to-right naively and reported "M1=1,297.0, M2=1,641.2" — WRONG (that's M2 and M3). **Two logic checks catch it instantly, always apply them:**
1. **Layer monotonicity: M1 < M2 < M3 < L must hold.** 1,090.5 < 1,297.0 < 1,641.2 < 2,338.4 ✓. The subagent's numbers (1,297 as M1, 1,641 as M2) with M3=1,641 would make M2==M3 — impossible.
2. **M1 identity: M1 = 現金通貨 + 存款通貨.** 109.9 + 980.6 = 1,090.5 = M1 exactly ✓. This pins which column is M1 unambiguously.

General lesson: **for any multi-column official-stat PDF, decode BOTH header rows and validate with a domain invariant (monotonic aggregate layers, or a component-sum identity) before trusting a value.** Independent-verify subagent-reported financial figures — the project's "子agent报告须独立重新验证" rule earned its keep here.

## Verified values (2026-08 baseline for the override file)

- **US** (2026-06, $B): 基础货币 5,488.4 / M1 19,831.5 / M2 23,155.2 — FRED, I curl-verified.
- **JP** (2026-07, 万亿円): 基础货币(Monetary Base) 554.9 / M1 1,090.5 / M2 1,297.0 / M3 1,641.2 — BOJ PDF, pdfplumber-verified with the two checks above.
- **CN** (2026-06, 万亿元): M0 14.7 / M1 118.5 / M2 356.71 — PBoC Q2 report, TE cross-checked. (Note TE tables label the unit "10亿¥" but the magnitude implies 十亿元 → ×10亿 gives the correct 万亿; sanity-check the scale, don't paste TE's raw number as 万亿.)

## ★Currency normalization — Chao REVERSED the "leave native" default → convert ALL to $B (2026-08)

The original build showed each country in its own currency (＄/¥/￥) with a "not directly comparable" caveat. **Chao then asked "把这三个货币全都变成美元，B作为单位，这样可以做横向的对比" — so the current default is `to_usd=True`: convert all three to $B.** Pattern (mirrors the CB balance-sheet `to_usd` fix):
- `fetch_money_supply(to_usd=True)` pulls live FX from FRED (`DEXJPUS`=JPY/USD, `DEXCHUS`=CNY/USD) and converts. Scale math: JP override is in **万亿円** (not 兆¥ like the CB block) so `万亿本币 × 1000 / rate → $B`; CN override in **万亿元** → same `× 1000 / rate`. (Watch the unit: money-supply override uses 万亿, the CB block used 兆¥/亿¥ — different factors.)
- **Keep 本币 provenance:** store the pre-conversion value in `orig_m0/orig_m1/orig_m2/orig_m3` + `orig_unit`; dashboard 括注 shows it `8,233 (1,297 万亿円)`. `_fx` records the rates + the intro line spells out "按 USD/JPY … 折算(FRED)".
- **Dashboard 递进条 must switch to CROSS-COUNTRY same scale** once in $B: compute ONE global `base = max` across all three countries' M0/M1/M2/M3, width every bar against it — otherwise per-country auto-scaling defeats the横向对比 Chao asked for. (Before the reversal each card self-scaled; after, they share one scale so bar LENGTH is comparable.)
- Verified 2026-08 (USD/JPY 157.54, USD/CNY 6.7474): US M2 $23,155B / JP M2 $8,233B (1,297万亿円) / CN M2 $52,866B (356.7万亿元) — now honestly comparable, CN M2 ≈ 2.3× US.

## ★M2 十年历史折线 sources (US/JP/CN, verified 2026-08) — feeds `fetch_m2_history()` + `_m2_history_html`

Chao asked for a 10-year M2 line chart per country under the M0/M1/M2 block. `fetch_m2_history(months=126, to_usd=True)` returns `{US/JP/CN:{unit,orig_unit,points:[{date:'YYYY-MM',value,[orig]}],latest,source,[status]}}`. Each country needs a LONG monthly series — the current-value sources above don't reach back 10y, so use these (all curl/web-extractable, no key):

- **US = FRED `M2SL` with `&cosd=`.** `curl "https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL&cosd=2015-01-01"` → ~139 monthly points, already $B. `&cosd=<start>` controls how far back.
- **JP = BOJ Time-Series CSV (NOT FRED — Japan FRED series all dead).** `curl "https://www.stat-search.boj.or.jp/ssi/mtshtml/csv/md02_m_1_en.csv"` → **★Shift_JIS encoded, must `.content.decode("shift_jis")`** (not utf-8). Date in col 1 (`YYYY/MM`), **M2 存量 in the 10th column (index 9)**, unit **亿円** (÷10000 → 万亿円). 2003→present, ~559 rows — plenty for 10y.
- **CN = East Money datacenter API (NOT FRED — China FRED series dead at 2019).** `GET https://datacenter-web.eastmoney.com/api/data/v1/get?columns=TIME,BASIC_CURRENCY&pageSize=400&pageNumber=1&sortColumns=REPORT_DATE&sortTypes=1&reportName=RPT_ECONOMY_CURRENCY_SUPPLY` with header `Referer: https://data.eastmoney.com/` + a UA. JSON `result.data[]`: `TIME`="2026年06月份" (regex `(\d{4})\D+(\d{1,2})`), `BASIC_CURRENCY`=M2 亿元 (÷10000 → 万亿元; `CURRENCY`=M1, `FREE_CASH`=M0). 222 months back to 2008-01.

**★★FX conversion for the M2 line chart — Chao REVERSED this to CURRENT-DAY rate for the whole series (2026-08). The per-month method below is OBSOLETE — do NOT re-implement it.** Original build used each month's OWN historical FX rate (reflecting both M2 growth AND FX drift), which made Japan look ~+0% in USD (yen depreciation cancelling本币 growth). Chao explicitly rejected that: he wants the chart to fetch the **CURRENT-DAY DEXJPUS/DEXCHUS ONCE and multiply the entire series by that single rate**, so the curve isolates 本币 M2 real growth (放水力度) with FX drift REMOVED. `fetch_m2_history` now does: `jpy_now,_ = fetch_fred_latest("DEXJPUS")` / `cny_now,_ = fetch_fred_latest("DEXCHUS")` (fallback = last value of the fredgraph series, then a built-in constant), convert every point with that one rate, and store `out["_fx"]={USDJPY,USDCNY}` for the dashboard intro to cite. **Result under unified current-day FX (verified 2026-08, USD/JPY 157.54 / USD/CNY 6.7474): Japan +41% (本币 918→1297 万亿円 real growth now visible), US +85%, China +150%.** The earlier "Japan ≈+0% in USD" fact is DEAD — the per-month method's flat-Japan artifact was exactly what Chao wanted gone. Dashboard label/intro: 当月汇率 → 当天汇率, wording "剥离汇率波动，曲线纯反映本币 M2 真实增长". **General口径 principle: per-period FX answers "what was it worth THEN in USD" (mixes in currency moves); single-current FX answers "how much did each country really print, in one comparable currency" (isolates local growth). The user owns that choice — Chao wants real-growth comparison, so single-current wins here.**

Cadence: all three M2 sources are live & backfillable, so the daily cron just re-fetches at render time (no separate GitHub json archive needed for the history — it's re-derivable). `_m2_line_svg(points)` reuses the custody-chart axis pattern (Y grid + labels, X = YYYY-MM at first/⅓/⅔/last since a 10y span needs YEAR labels not MM-DD).
