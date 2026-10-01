# Verified per-indicator data-source map (Eco-and-Volatility-Checker)

Hard-won 2026-08 from a `delegate_task` source-hunt that actually tested each candidate (33 live probes). Rule: prefer official pure API → direct plain-Chrome-UA requests/read_html → Jina/web_extract only if truly 403 → `manual_overrides.json` last. A normal Chrome UA + `pandas.read_html(url, storage_options=HEADERS)` works for far more sources than assumed; Jina was over-defense.

`HEADERS` = the browser header dict in `src/fetchers/util.py` (real Chrome UA). Every "OK direct" below was verified returning HTTP 200 to that UA.

## The 8 long-term valuation/structural indicators

| # | Indicator | Verified source | How | Latest test value |
|---|-----------|-----------------|-----|-------------------|
| 1 | Buffett Indicator (mkt-cap/GDP) | **FRED pure API** (zero-scrape, official Z.1) | `NCBEILQ027S` (corp equities liability, $M, quarterly) ÷ (`GDP` $B ×1000) ×100. Reuse `fetchers.fred.fetch_fred_latest`. sanity 50–400. | 214–218% (2026-Q1) |
| 2 | Shiller CAPE | **multpl.com direct** (plain UA 200, NO Jina) | `read_html("https://www.multpl.com/shiller-pe/table/by-month")` table 0, row 0 = latest, cols [Date, Value]; clean value `re.sub(r"[^\d.]","",v)`. sanity 5–100. Sister `/s-p-500-pe-ratio/table/by-month` gives P/E TTM as cross-check. FRED has NO Shiller series. | 42.24 (2026-08-11) |
| 3 | Conference Board LEI | **PAYWALLED** → substitute **FRED OECD CLI** | CB LEI is paid + anti-scrape; old FRED `USSLIND` stopped 2020. Use `USALOLITOAASTSAM` (US OECD composite leading indicator, monthly, base=100); value = 6-month change = obs[-1]−obs[-7]. Alt `BBKMLEIX`. | 100.80 / 6m +0.58 (2026-06) |
| 4 | AAII household stock allocation % | **aaii.com direct** (plain UA 200, no login, NO Jina) | `read_html("https://www.aaii.com/assetallocationsurvey")`; find the row labeled "Stocks Total", take its %-column. | 70.38% (2026-07) |
| 5 | Insider Buy/Sell ratio | **openinsider.com direct** (replaces gurufocus which now 403s Cloudflare) | `read_html("http://openinsider.com/insider-purchases")` + `.../insider-sales`; sum the "Value" col (strip $,+ , abs) on each; ratio = buys$ / sells$. Caveat: top-100-of-recent-list口径 → trend signal, not exact aggregate. | 0.27 (sell-heavy) |
| 6 | IPO issuance count | **stockanalysis.com direct** (replaces Renaissance anti-scrape) | `read_html(f"https://stockanalysis.com/ipos/{year}/")` table 0 row-count = YTD IPO count. `api.stockanalysis.com/api/ipos/statistics` 404s → use the HTML table. | 225 (2026 YTD) |
| 7 | Margin Debt / GDP | **NO free API for the numerator** (see #8). Proxy: FRED broker-customer-credit quarterly series ÷ `GDP` — trend only, not FINRA-exact. | — |
| 8 | FINRA Margin Debt (monthly) | **NO free programmatic source** (all real attempts failed) | finra.org page 403; FINRA public API gateway (`api.finra.org`) serves some datasets anonymously (regShoDaily, consolidatedShortInterest) but the margin dataset needs an authed FINRA Data API account (all enum paths 404); Nasdaq Data Link `FINRA/MARGIN_DEBT` 403 (Incapsula). → keep the半-automatic path: cron agent `web_extract`s finra.org monthly Debit into `manual_overrides.json`; script falls back to `data/margin_debt_history.json`. | — |

## SEC EDGAR 13F (institutional holdings)

- Submissions: `https://data.sec.gov/submissions/CIK{cik:010d}.json` → `filings.recent`; keep `form` starting `13F-HR`, EXCLUDE `/A` amendments.
- Filing files: `https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/index.json`; the information-table XML is the entry that is NOT `primary_doc.xml`.
- Parse per `<infoTable>` block: `nameOfIssuer` / `value` / `sshPrnamt`; aggregate by issuer.
- **UA MUST look deliverable**: `"AppName research name@example.com"` passes; a github.io email domain or parenthetical text → 403. 403 from EDGAR = UA format, not rate-limit.
- **Value unit is not uniform** — new filers = whole dollars, some (Druckenmiller) = thousands. Detect per-filing: exclude PUT/CALL rows, need ≥5 samples, median implied price (value/shares) `<0.5` ⇒ ×1000, `>5` ⇒ ×1, 0.5–5 grey ⇒ don't scale + flag ambiguous.
- 18 verified active-13F CIKs (base 9 + sector-3×3): Berkshire 1067983, Bridgewater 1350694, Scion 1649339, Soros 1029160, ARK 1697748, Pershing 1336528, Appaloosa 1656456, Duquesne 1536411, Oxbow 1564770; Tiger Global 1167483, Coatue 1135730, Whale Rock 1387322, Baupost 1061768, Third Point 1040273, Icahn 921669, Renaissance 1037389, Citadel 1423053, Millennium 1273087.
- Trump / individuals: no 13F → separate card, agent web_search of public financial disclosure (PFD), source=PFD; can't be backfilled.

## Foreign official UST custody at NY Fed (去美元化风向标) — FRED WMTSECL1 is LIVE (use it), H.4.1 HTML is a supplement

★★CORRECTION (2026-08, verified — supersedes the earlier "all FRED custody series are dead, only H.4.1 HTML is live" note that lived here): the **bare-named** series (`WMTSECL`/`WMTSEC`/`WSEFINT`) DID stop 2012-11-07 when the Fed restructured & RE-KEYED the H.4.1 memorandum items, but the **currently-active** versions carry a **`1` suffix** and update weekly to present:
- **`WMTSECL1`** = "Custody Holdings: Marketable U.S. Treasury Securities: Wednesday Level" — WEEKLY (as-of Wednesday), 2002→present, still updating. **This is the去美元化 line (the FT-chart line).**
- `WSEFINTL1` = total custody incl. agency/MBS. `WFASEC1` = agency debt & MBS.
- Diagnostic that catches the wrong-id trap: `fred/series/search?search_text=H.4.1 custody` lists the dead bare series AND the live `…1` series side by side with their `observation_end` — **pick the row whose `observation_end` is recent.** A stale `observation_end` = "grabbed the OLD id", NOT "no data".
- **Preferred impl (single consistent口径):** `external_data.fetch_foreign_custody_ust()` pulls the full weekly history via `fetch_fred_history("WMTSECL1", start)` (÷1e6 → $T), takes current value + WoW from the last two points, returns a `history:[(date,$T),…]` field for the line-chart. Verified 2026-08: WMTSECL1 = $2.631T (2026-08-05 Wed), WoW −$25.5B.
- **H.4.1 HTML is now only a SUPPLEMENT** for the total-custody (agency/MBS) line: `https://www.federalreserve.gov/releases/h41/current/h41.htm`, strip tags → `&#xa0;`→space → find `"held in custody for foreign official and international accounts"` (first number = total custody). (Its "Marketable U.S. Treasury securities" row = latest + `[+/-]`WoW is the older scrape path, still valid but the ~$16B gap vs WMTSECL1 is just the取数日 difference — Wed-level vs latest-release-day; prefer FRED for a consistent series.) UA must be plain `"<App> research <name>@example.com"` (Fed 403s parenthetical/undeliverable UAs, same as SEC).
- Dashboard: `_custody_html` bottom card WITH a full line-chart `_custody_chart_svg` (see SKILL.md bottom-block step 7); Notion weekly DB `DB_CUSTODY` via `write_custody_notion()` (upsert keyed on `as_of`, title prop "Date").
- **General rule: when the Fed/BLS restructures a statistical release, FRED often DISCONTINUES the old series id and MINTS a new (often suffixed) one rather than continuing the same id. A stale `observation_end` is a "wrong id" signal, not a "no data" signal — search for the live variant BEFORE falling back to HTML scraping.**

## US Treasury auctions (fiscaldata API) — 国债拍卖 timeline block

Official free API, NO key, for auction size / bid-to-cover / high-yield / indirect-bidder + upcoming schedule. Powers the auction timeline bottom-block.

- Endpoint: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query`
- Query all recent: `?sort=-auction_date&page[size]=800&filter=auction_date:gte:<YYYY-MM-DD>`. **Filter to a wide window (~420 days) — long bonds (20/30Y) auction only ~monthly (+reopenings), so a short window won't gather "past 3" for them.** Short/mid notes (2/3/5/7/10Y) fill 4 easily in a few months.
- Fields per row: `security_type` (Note/Bond/Bill), `security_term` (2-Year…30-Year), `auction_date`, `issue_date`, `offering_amt`, `total_accepted`, `bid_to_cover_ratio`, `high_yield`, `indirect_bidder_accepted` (indirect % of accepted ≈ foreign-official proxy demand — cross-validates the custody block), `direct_bidder_accepted`, `primary_dealer_accepted`, `reopening`.
- **Scope = Note/Bond key coupons only** (2/3/5/7/10/20/30Y); Bills (4W/8W/13W…) are money-market tools, different口径 → exclude. This is a口径 choice worth confirming with the user (Chao didn't reply in time; the recommended default is key coupons).
- ★**TRAP 1 — "upcoming" auctions must be filtered by `auction_date >= today`, NOT by `high_yield == null`.** Old reopening/announcement rows also have `high_yield` null but a PAST auction_date → filtering only on null-yield falsely flags them as future. Correct: `has_result = high_yield not in (None,'null','')`; a row is FUTURE iff `date >= today AND not has_result`, DONE iff `has_result`.
- ★**TRAP 2 — the API returns numbers as STRINGS incl. the literal `'null'`, not JSON null.** Convert with a helper: `x in (None,'','null') → None; else float(x)`.
- Shape the fetcher returns: `{terms: {term: {history:[latest+past3], next:{…}|None}}, upcoming:[…6], as_of, status, source}`. `offering_bn`/`accepted_bn` = `/1e9`; `indirect_pct` = `indirect_bidder_accepted / total_accepted * 100`.
- Impl: `external_data.fetch_treasury_auctions()` → `_auctions_html` timeline card + `write_auctions_notion()` (one row/auction, title `<type> <term> <date>`) into **DB_AUCTIONS** (the 7th DB). Bid-to-cover colour band: >2.5 强 / 2.2-2.5 正常 / <2.2 弱=需求恶化早期信号.
- Cadence: dashboard card每日刷新 (daily cron fetches + passes to generate); Notion存档 + GitHub `data/auctions/<week>.json` 只每周 (weekly cron) — per Chao's "每周 cron" instruction for this block.
- Verified 2026-08: 10Y(8-12) BTC 2.53 / HY 4.683% / indirect 61%; 3Y(8-11) BTC 2.71; next 30Y Bond (8-13) $25B, issue 8-17.

## Country-level UST holdings (日本 / 中国 分国别, TIC) — 10-year monthly line-chart block

★DISTINCT口径 from the NY-Fed-custody block above — do NOT conflate them:
- **Custody (WMTSECL1)** = NY Fed custody account, foreign **OFFICIAL合计** (all countries pooled), weekly.
- **TIC Major Foreign Holders** = **分国别** total holdings (official + private), **monthly** — the authoritative per-country series. This is the source for a "日本持有美债 / 中国持有美债 近10年" chart (Chao asked 2026-08 for both, side-by-side, under the custody block).

- **Source: US Treasury TIC history file `https://ticdata.treasury.gov/Publish/mfhhis01.txt`** (official, TSV, 2000-03→present,免key). Parses to 310+ monthly points per country → easily covers 10 years (`years=10` → ~115 points).
- ★★**THE TRAP: `ticdata.treasury.gov/Publish/mfh.txt` (no `his`) is a STALE CACHED snapshot** (was stuck at 2023-01). The HISTORY **and** the latest data both live in the **`mfhhisNN.txt`** series (`mfhhis01.txt` is the current one). Always use `mfhhis01.txt`, never `mfh.txt`.
- **Parse recipe (year-block TSV, `_parse_tic_country`):** the file is a stack of year-blocks; each block has a **month-row** (cells contain `Jan…Dec` abbrevs — detect a row with ≥6 month names → record col→month) then a **year-row** (`cells[0]=='Country'`, other cells = 4-digit years → col→year), then data rows. On a `Japan` row (exact) or a `China` row (`startswith('China')` — the file label is `"China, Mainland"` with quotes/comma), for each month-col pull the value, key `f"{yy:04d}-{mm:02d}"`, `float()` (strip commas; skip non-numeric). Cutoff to last N years by `>= (today − N*365 − 45days)` as YYYY-MM.
- Impl: `external_data.fetch_country_ust_holdings(years=10)` → `{"Japan":{...}, "China":{...}}`, each `{name,flag,series:[(YYYY-MM,$B)…]升序, latest,first, delta_bn,delta_pct, high,low, status,source}`; `status="未找到"/"数据不足"` when the fetch/parse yields <2 points (never fabricate). Unit is $B (billions, as the file already reports).
- Render: a bottom-block card with `.cust-charts` 2-col grid (same machinery as the custody dual-chart) — left 🇯🇵 / right 🇨🇳, each a `_country_ust_svg` ($B-scale monthly line, Y-labels `{:,.0f}`, X-labels YYYY-MM) + a current-value line + 首末区间 stat. Falling=陶土红 (减持/去美元化), rising=鼠尾草绿. Standard `generate()` 4-slot threading + `build_dashboard.py` `country_ust = ed.fetch_country_ust_holdings(years=10)`.
- Verified 2026-08: 🇯🇵 $1,147B(2016-06)→$1,186B(2025-12) +3.3% (高位震荡); 🇨🇳 $1,241B→$684B **−556B / −44.8%** (10-year systematic减持 — the去美元化/中美博弈 structural signal a 10-year view exposes that a 12-month view can't). Note the口径-difference in the card's 如何看.

## Central-bank balance sheets (US/JP/CN) — read siblings, don't scrape

Read Economic-Dashboard's own Notion DBs (latest two rows, diff line-items):
- Fed B7 weekly `dea7e939bb394d538f3cea3ff0da5a6b` — 环比 = WoW.
- BoJ B6 10-day 旬报 `481f6e1960e4444383d66a1e1cafb49b` — 环比 = 较上期.
- PBoC B5 monthly `20b0eb37d69744109cca9fba0c61b929` — 环比 = MoM.
Label the 环比 口径 per country; never force "WoW" on all three.

### Four-CB block enhancements (Chao 2026-08 — ECB added, 2x2, RMP sub-item, residual totals, unified same-day FX)

- **Layout is now 2×2 (US/JP/CN/ECB), not 3-across.** `_cb_balance_html` order `["US","JP","CN","ECB"]`; CSS `.bs-grid{grid-template-columns:repeat(2,1fr)}` (collapse to 1col `@media(max-width:780px)`). A card grid growing past 3 → give it an explicit 2-col grid rather than `auto-fit`.
- **RMP (储备管理购买) = a SUB-ITEM of 美国国债 Treasuries, NOT a sibling line.** Fed's `WSHOBL` (Bills held, $533.5B) is 11.8% OF `TREAST` (total Treasuries, $4,538B) — Bills ARE part of the Treasuries total. Chao wanted RMP's存量+变量 shown, so label the Bills line `短期国债 Bills（RMP 储备管理购买）` and mark it `"sub"` in `CB_BS_SPEC` (indented `└ 其中·`, EXCLUDED from the total-assets sum). Listing it as a sibling double-counts (the −$600 residual before the fix was exactly this). Same accounting rule as CN 货币发行⊂储备货币.
- **Force totals to reconcile — auto-append a "其他 Other（差额）" residual line.** Chao caught CN 总负债 7170 ≠ 5798.1(储备货币)+891.5(政府存款). `_add_residual(blk)`: for each side with a listed total, `residual = total − sum(non-sub line values)`; if `abs(residual) > max(1, 0.5%×total)` append `{name:"其他 Other（差额）", value:residual}` so the listed items + 其他 == the stated total. Runs for US/JP/CN/ECB. (US assets residual can be slightly NEGATIVE — small口径/rounding gap once Bills is sub'd — acceptable at ~1% of total.)
- **Unify ALL banks to the CURRENT-DAY FX (Chao要求 横向可比), not each row's crawl-time rate.** `fetch_cb_balance_sheets(to_usd=True)` pulls `DEXJPUS`/`DEXCHUS`/`DEXUSEU` ONCE via `fetch_fred_latest`, converts every bank with the same-day rate: JP `兆¥ ×1000/USDJPY`, CN `亿¥ ×0.1/USDCNY`, ECB `十亿€ × USDEUR` (EUR is USD-per-EUR → MULTIPLY, opposite of JPY/CNY which are foreign-per-USD → divide). Store `out["_fx"]={USDJPY,USDCNY,USDEUR}`; each card's meta line prints the audit trail "原口径 X · 按 PAIR rate 折美元".

### ECB (欧洲央行) — official Data Portal ILM dataset (Eurosystem weekly financial statement)

★The 4th central bank. FRED only has ECB TOTAL assets (`ECBASSETSW`) + policy rates — NO分项. The分项 (gold/securities/banknotes/…) come from the **ECB official Data Portal SDMX API, dataset ILM** (免费, no key). Verified 2026-08 (independently re-run, not just subagent-reported).

- **Base:** `https://data-api.ecb.europa.eu/service/data/ILM/<key>?lastNObservations=1&format=csvdata`, plain `Mozilla/5.0` UA. Unit = **百万欧元 (EUR mn, UNIT_MULT=6)**.
- **6 dimensions:** `FREQ.REF_AREA.BS_REP_SECTOR.BS_ITEM.COUNT_AREA.CURRENCY_TRANS` = `W.U2.C.<item>.<cnt>.<cur>`.
- ★★**DON'T query single series keys — they 400 (the COUNT_AREA/CURRENCY_TRANS取值 per item is easy to guess wrong). Use the WILDCARD `W.U2.C...` to pull ALL ~43 items in ONE call**, then index by `f'{BS_ITEM}.{COUNT_AREA}.{CURRENCY_TRANS}'`. This is the whole trick (my per-key probe 400'd; the wildcard returned everything). Parse with `csv.DictReader`; each row → `(OBS_VALUE, TIME_PERIOD)`; period looks like `2026-W32`.
- **Verified item keys (tail = `BS_ITEM.COUNT_AREA.CURRENCY_TRANS`), latest EUR mn 2026-W32:**
  - Assets: 黄金 `A010000.Z5.Z0Z`=1,232,856 · 外币(非欧元区) `A020000.U4.Z06`=525,192 · 外币(欧元区) `A030000.U2.Z06`=20,563 · 对信贷机构MPO贷款 `A050000.U2.EUR`=30,092 (MRO `A050100`, LTRO `A050200`) · **货币政策证券APP+PEPP `A070100.U2.EUR`=3,381,432** (NOT `A070000`, which includes other securities) · 其他资产 `A110000.Z5.Z01` · 总资产 `T000000.Z5.Z01`=5,923,023.
  - Liabilities: 流通银行券 `L010000.Z5.EUR`=1,638,475 · 对信贷机构负债 `L020000.U2.EUR`=2,327,267 (经常账户 `L020100`, **存款便利 `L020200`=1,981,262** → mark sub) · 对其他居民负债 `L050000.U2.EUR` · 重估账户 `L140000.Z5.Z01` · 资本与储备 `L150000.Z5.Z01` · 其他负债 `L120000.Z5.Z01`.
- **Cross-check:** all asset分项 sum == 总资产 5,923,023 == FRED `ECBASSETSW` (three-way agreement = trust).
- **Policy rates** (still FRED): `ECBMRRFR`=MRO 2.40 · `ECBDFR`=存款便利 2.25 · `ECBMLFR`=边际贷款 2.65. Render as a `.bs-rates` footer line on the ECB card.

## Credit Impulse 信贷脉冲 (美/中/欧) — DERIVED-metric line-chart block (Chao 2026-08)

A MID-TERM leading indicator (领先实体经济约 6-9 月; 中国信贷脉冲 = 全球商品/风险资产最强领先指标之一). This is the worked example of a **DERIVED bottom-block card**: no raw single-value source — you compute the metric FROM a FRED series, then render a zero-axis line chart. `external_data.fetch_credit_impulse(years=8)`.

- **Definition (Chao's, = BIS/学界 standard):** `Credit Impulse = Δ(new-credit FLOW) / GDP = 信贷存量的二阶差分 / GDP` — measures the **ACCELERATION of new credit**, NOT total debt, NOT new debt. (Total debt can rise while the impulse turns negative — that's the whole point of the metric.)
- ★**口径 CHOICE — use the BIS credit-to-GDP RATIO's second difference, NOT the absolute-level flow method.** Two equivalent computations exist; a source-hunt this session verified they agree in direction/turning-points to within <0.2pp on US (where both inputs are available):
  - *ratio method (CHOSEN):* pull BIS **credit-to-GDP ratio** series (already normalized, % of GDP) and take its 2nd difference `(r_t − r_{t-1}) − (r_{t-1} − r_{t-2})`. GDP denominator changes far slower than credit → the ratio's 2nd diff ≈ Δflow/GDP.
  - *level method:* pull absolute BIS credit level + GDP, `((L_t−L_{t-1})−(L_{t-1}−L_{t-2}))/GDP_t`.
  - **Why ratio wins for a 3-country card:** (1) three countries share ONE BIS口径 → internationally comparable (BIS explicitly maintains cross-country comparability); (2) all three ratio series reach 2025-10, whereas FRED's **China quarterly GDP denominator stops at 2023** (`CHNGDPNQDSMEI` ends 2023-07, `MKTGDPCNA646NWDB` annual only) → the level method can't do China cleanly; (3) BIS official ratio = authoritative.
- **FRED series (免key, all quarterly, BIS-sourced):** US `QUSPAM770A` · CN `QCNPAM770A` · EA(欧元区) `QXMPAM770A` — all = "credit to private non-financial sector, % of GDP". (Absolute-level siblings, if ever needed: `CRDQUSAPABIS`/`CRDQCNAPABIS`/`CRDQXMAPABIS`.)
- ★**Fetch channel — prefer the带key API, the免key fredgraph CSV endpoint is FLAKY.** `fred.stlouisfed.org/graph/fredgraph.csv?id=…` intermittently ReadTimeouts on this VM (hit it repeatedly this session). `fetch_credit_impulse` tries `fetchers.fred.fetch_fred_history(sid, start=cosd)` (带 `FRED_API_KEY`, stable) FIRST, falls back to the fredgraph CSV only if that returns nothing. **General rule for any new FRED pull in this project: go through `fetchers.fred.*` (API-key channel), not a raw fredgraph GET.**
- **Frequency reality — state it honestly on the card.** BIS credit is **quarterly, lagged ~1 quarter** (latest = prior quarter-end; there is NO weekly/monthly BIS credit series — this is the only跨国-comparable口径). So the card is a **季度更新的中期指标**, labelled "季度更新·数据滞后约1季（as of YYYY-MM）". If the user asks for a faster信贷 signal, the honest alternative is US weekly bank-credit `TOTBKCR` momentum (single-country, NOT true Credit Impulse) — offer it as a separate "信贷动能" card, don't relabel this one.
- **signal buckets:** `strong_pos ≥0.8 / pos ≥0.15 / neutral / neg ≤-0.15 / strong_neg ≤-0.8` (pp of GDP), mapped in dashboard `SIG_META` to vivid green `#2e9e5b` / amber `#e0a92e` / red `#d64545` + a 中文 label.
- Impl: `fetch_credit_impulse` returns `{US:{name,flag,points:[{date,ci}],latest,latest_date,signal,source,status}, CN:{…}, EA:{…}}`; some-country-fail → `points:[]`, `status:"未找到"` (never fabricate).
- **Render = `_credit_impulse_html` + `_credit_impulse_col` + `_credit_impulse_svg`** — a 3-col card (`.ci-cols grid-template-columns:repeat(3,1fr)`, collapse to 1col `@media(max-width:720px)`). Each column = flag+country title + big signal-coloured latest value (`+0.10pp GDP`) + `.ci-sig` (hollow signal dot + 中文 label + as-of) + the line chart. Standard `generate()` 4-slot threading (`credit_impulse=None` kwarg + `{credit_impulse}` template slot + `.format` + `build_dashboard.py` fetch).
- ★**The ZERO-AXIS line chart is the reusable primitive for any SIGNED derived metric.** Unlike the custody/country-UST charts (all-positive $ levels), Credit Impulse crosses zero, so `_credit_impulse_svg` (1) forces `lo=min(lo,0)`, `hi=max(hi,0)` so the zero line is always in-frame, (2) draws a bolder zero axis (`.ci-zero` stroke), (3) area-fills to the zero baseline (not the bottom), (4) marks the latest point with a **signal-coloured HOLLOW ring** (`circle fill=none stroke=color` + tiny solid center) — same hollow-ring vocabulary as the no-signal indicator lights. Reuse this SVG shape for any future ±-valued metric (net flows, YoY deltas, spreads that go negative).
- Verified 2026-08 (2025Q4, ratio-2nd-diff, n=32 quarters): 🇺🇸 **+0.10** neutral (from 2025Q1 spike +1.10 → cooled) · 🇨🇳 **−0.20** neg (2025Q1 spiked +4.90 then急跌 negative — CN impulse is policy-driven & volatile) · 🇪🇺 **+0.40** pos.
- Impl: `external_data.fetch_ecb_balance_sheet(to_usd=True, usd_per_eur=None)` — wildcard pull → map ASSETS/LIABS display-name→tail → `×(usd_per_eur/1000)` for $B → `total_liab=None` (so residual補 only runs asset side) → returns the standard `{name,flag,unit,period,date,assets,liabilities,total_assets,rates,usd_per_eur,source}`. `fetch_cb_balance_sheets` calls it with the same-day `usd_per_eur` and appends `out["ECB"]`. Verified $B: 黄金$1,425B / 证券$3,909B / 银行券$1,894B / 存款便利$2,290B, 总资产$6,846B.

## 日债10Y/30Y · 日经225 · 外资流入日股 · 四国IIP (Chao 2026-08, 全免key真源)

四个新数据源一次 session 全实测打通。新 Notion DB 建库+写入 = `src/build_us_jp_market_dbs.py`（`build()` 幂等建 DB_YIELDS/DB_NIKKEI/DB_FOREIGN_FLOW/DB_IIP 写回 .env；`write_data_from_env()` 供每日 cron 调用）。每图按三件套同步：GitHub `data/*.json` + Notion DB + daily cron inline generate（加 fetch + generate 参数 + 一行 `import build_us_jp_market_dbs as _bm;_bm.write_data_from_env()`）。

### 日债收益率 10Y/30Y (日频) — 日本财务省 MOF 每日 CSV
- 当月 `https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv`（仅当月~14行）+ 历史 `.../historical/jgbcme_all.csv`（13000+行 2002→now）合并覆盖过去一年。
- 格式 row1 表头 `Date,1Y..10Y(列idx10)..30Y(列idx14),40Y`；日期 `2026/8/17`。`_mof_jgb_yields(term_idx)` 传 10 或 14。
- 美债对手方 FRED `DGS10`/`DGS30`。四线共%轴同图 `_yield_curves_svg`（美实线/日虚线）。验证 2026-08：美10Y 4.68/美30Y 5.25/日10Y 2.92(+134bp一年)/日30Y 4.05。`fetch_us_jp_yields()`。

### 日经225 (日频) — FRED `NIKKEI225`，`fetch_nikkei225()`。

### 外资净买入日股 (周频) — JPX 投资部门别周报 Excel
- archive 页取链接：`.../investor-type/00-00-archives-00.html`(本年)/`-01.html`(上年)各~52周，正则抓 `stock_val_1_*.xls`（val金额非vol）。
- ★文件名 code `260801`=26年08月第01週非日期！周结束日从 Excel row3 内文 `(8/3 - 8/7)` 正则解析。
- ★数值：海外投資家行(row~29) 差引き Balance 在第6列 idx6 在'売り'行（'買い'行第6列是nan）；带逗号+△/▲负号去除后 float。
- ★★单位=千円(row4 [4,10]标注)→转万亿日元 `/1e9`（别 /1e8 会小1000倍显示全0）。
- `_jpx_foreign_flow_weekly()`+`fetch_foreign_flow_japan()`。与日经双轴同图 `_nikkei_flow_svg`（日经折线左轴+外资周柱状右轴0线，绿买红卖，日经日频对齐到周取<=周末最近交易日）。验证一年外资累计+11.8万亿円/日经+58%。

### 四国 IIP 国际投资头寸 (年频, 美/日/德/中) — IMF SDMX 2.1 免认证
- Endpoint `https://api.imf.org/external/sdmx/2.1/data/IIP/{USA|JPN|DEU|CHN}.{A_P|L_P}.IIP.USD.A?startPeriod=2014`（plain Mozilla UA，公开端点无需认证；IMF凭证存.env IMF_API_USER/PASS 但2.1用不到）。
- ★★维度 `COUNTRY.BOP_ACCOUNTING_ENTRY.INDICATOR.UNIT.FREQ`；资产/负债 entry 是 `A_P`/`L_P`（Assets/Liabilities Position）不是 A_T/L_T（那组合合法但返空）；INDICATOR=`IIP`；国家 ISO 3字母。找对 key 诀窍：完全通配拉 `IIP/USA?startPeriod=2024` 看 Series 真实维度属性。
- ★★`sdmx1` 库能列 dataflow/codelist 但解析 IMF StructureSpecificData 有 bug 返空 → 绕过：requests 直取 XML，`xml.etree` 遍历 Obs 取 TIME_PERIOD/OBS_VALUE 属性（`_imf_iip_series`）。÷1e12→$T，NIIP=资产−负债。验证 2025：美净-21.9T(全球最大净债务且恶化)/日+3.6/德+4.3/中+4.1。`fetch_iip_four_countries()`，渲染 `_iip_html`（净头寸十年折线0线+最新年资产/负债分组柱状）。
- World Bank API 无 IIP 存量（只 FDI 流量）；IMF 旧 dataservices.imf.org 域名已下线；DataMapper 只有 WEO 流量无 IIP 且本 VM 403 → SDMX 2.1 直连是唯一通路。
- ★**用户按常识质疑某国数值时的正确核查顺序(Chao 2026-08 质疑「中国 IIP 怎么是负值？中国是最大债权国」)**：① 派 `delegate_task` 独立对权威源核实(中国=SAFE 官方 net IIP +4.07T 2025正值)；② **再亲验自己的 fetch + render 当前输出**，别只信子agent"符号反了"就改。本次实测发现 fetch 中国 net=+4.07T(与官方吻合)、render `net>=0→绿色净债权国` 也对、本地HTML/docs/公开Pages 三处全显示 +4.1T 绿色 → **代码无 bug，用户看到的负值 = 浏览器/CDN 缓存的旧版本**(IIP 首上线 87f5dad 后数据刷新过)。教训：常识质疑既可能是真 bug 也可能是 stale-cache/误读，**先双向核查(权威 + 自己当前产物)再下结论**，请用户强刷；仍异常再让其截图定位具体位置(折线/柱状/文字行)。net IIP 正负常识锚：美国最大净债务国(~-22T)，日/德/中均净债权国(正)。

## 对冲基金美债杠杆 + 短期融资压力指标 (Chao 2026-08, 全免key真源)

一次 session 加 1 section(图A/B) + 2 短期指标 card。数据源全 `delegate_task` 子agent实测(每候选 curl 返 2026 数据才算数)。

### 对冲基金美债杠杆 (季度) — OFR Hedge Fund Monitor 免key JSON API
- 源自 BIS《Annual Economic Report 2026》ar2026e2.pdf Graph 5，底层=美国 OFR / SEC Form PF。
- **端点 `https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic=<code>`**（★注意路径是 `/hf/v1/` 不是 `/v1/`；免key无注册）。返回 `[[date,val],…]` list。
- 图A 美债总名义敞口/GDP：`FPF-ASSETCLASS_USGOV_GNE_SUM`(GNE $, 季末) ÷ (FRED GDP $B×1e9) ×100。验证 2026Q1 $4.03T = GDP 12.65%(2013 5.75%翻倍多)。
- 图B 三类借款 $万亿：Repo `FPF-BORROW_REPO_SUM` / Prime brokerage `FPF-BORROW_PRIMEBROKER_SUM` / Other secured `FPF-BORROW_OTHERSECURED_SUM`。验证 Repo $3.24T/Prime $3.22T/Other $0.78T。53季 2013Q1→2026Q1。
- 频率=**季度**(SEC Form PF 滞后发布)，cron 每日跑但数据每季才变，card 标"季频·OFR/SEC Form PF"。
- ★图C「零折扣(zero haircut)占比 USD/EUR」**拿不到时间序列**：OFR NCCBR / ESMA-ESRB 只在报告 PDF 出静态图，SDMX/API 全零命中 → 如实标注未纳入，**绝不用代理冒充**(Chao 铁律)。
- 全 497 个可用序列代码可从 `data/hf_leverage.json`-hunt 或 wildcard 探。`fetch_hf_leverage()`+`_hf_leverage_html`(图A单线`_hf_line_svg`+图B三线，通用季度折线原语)+Notion DB_HF_LEVERAGE。

### 短期指标① 股票杠杆融资成本 — FRED `DPRIME`(最优贷款利率)
- 券商保证金/杠杆贷款成本多挂钩 broker call/prime rate。config `source:fred, fred_id:DPRIME, direction:high_bad, warn7 trig8`。验证 6.75%🟢。配合已有 margin_debt(规模)看成本。走 run.py 通用 fred 路径自动抓，无需 derived 代码。

### 短期指标② 银行融资压力 (CP−Tbill) — 代理真 swap spread
- ★★**真 swap spread(IRS固定腿−国债)在任何免费无key源都拿不到**：FRED swap 序列 DSWP1/2/3/5/7/10/30 全停更 2016-10(LIBOR退役)；OFR API 442序列 swap/OIS/IRS 零命中；term SOFR swap 曲线全商业付费(ICE/CME/Bloomberg)。别再花时间找 swap spread 免费源。
- 最贴近「银行去杠杆→融资成本↑」语义的免费真数据代理 = **3M金融商业票据 − 3M国库券 = `DCPF3M` − `DTB3`**(银行无担保融资溢价)。config `source:derived, direction:high_bad, warn20 trig40 bps`；run.py 派生段 `(cp−tb)×100`，`extra` 存短端 SOFR。验证 +11bps🟢。
- ★**方向修正**：Chao 原述"swap spread 缩窄=卖出"是 IRS 特性；货币市场代理在压力下是**走阔**非缩窄 → 信号定义为「利差走阔 + 短端利率升(SOFR/DGS3MO) = 短期卖出」。给用户交底代理与真 swap spread 的差异(融资端利差 vs IRS定价)+方向反转，Chao 认可。
- 短端利率腿 100% 真数据：`SOFR`(3.62)/`DGS3MO`(3.86)/`DTB3`(3.71)，实测均到 2026-08。

### BIS Gold Swaps — 两个含义天差地别(Chao 2026-08 问，子agent实测)
- ★**含义① OTC 市场黄金衍生品(含 forwards&swaps 名义额)** ✅ 可脚本抓真序列：BIS SDMX API `https://stats.bis.org/api/v1/data/BIS,WS_OTC_DERIV2,1.0/H...L..........?format=csv`(免key)，14维 `DER_RISK=L`(Gold)、`DER_INSTR=C`(Forwards&swaps)/`A`(全部)/`R`(Options)、`DER_TYPE=A`(名义额)。半年度 1998-S1→2025-S2。★用 wildcard 拉全量再本地筛(单key易猜错维度 404)。bulk 备选 `https://data.bis.org/static/bulk/WS_OTC_DERIV2_csv_col.zip`。验证黄金 F&S 名义额 $858.7B(2025-S2)。
- ★**含义② BIS 机构自身资产负债表 gold swaps(GATA 追踪的、2010年$349亿那个)** ❌ 无API仅PDF：SDMX 零命中；月度 Statement of Account PDF `statofaccYYMMDD.pdf` 只有 "Gold and gold loans"+"Gold deposits" 两行余额**无 swaps 行**(GATA 吨数是反推)；官方确切数只在**年度报告财报附注**(ar2010e.pdf 起)每年一次 PDF 抠数。
- 问 Chao 要哪个再动手：①能做自动更新 section，②只能 PDF 抠数半自动。

### BIS Gold Swaps 含义② 已实现 (Chao 选「自己那笔」, 2026-08) — `fetch_bis_gold_swaps` + `_bis_gold_swaps_html`
Chao 确认要的是**含义②(BIS 机构自营账户那笔, GATA/Robert Lambourne 追踪的吨数)**, 不是全市场衍生品规模。做成吨数折线 section, 归侧栏「流动性与央行」组(标题含 'BIS' 自动命中)。
- **两个真值层级(都免费公开, 存 `data/bis_gold_swaps.json` 种子驱动, `points:[{date,tonnes,kind,src}]`)**:
  - **年度锚点(kind=annual)** = BIS 年报明确确认值(2010-03→今连续, 每年3/31): 346→409→355→404→236→47→**0(2016)**→438→361→175→326→**490(2021峰值)**→…→**184(2026-03最新)**。来源=GATA 公开汇总表(goldseek/gata.org, 逐年可查) + BIS 年报原文。
  - **月度点(kind=monthly)** = GATA 顾问 Lambourne 从 BIS 官方月度 Statement of Account 推算(如 2025-10=54t, 2025-11=39t)。
- ★★**诚实数据处理铁律(本 session 关键决策)**: 我实测想从月度 PDF 自动推算吨数, `Gold deposits`(负债端 40777.6 SDRmn) ÷ 当期金价直接折吨 → 得 ~430-520t, 但 GATA 报近月才 39-54t — **差一个量级 = 我复现不出 GATA 的精确勾稽算法**(BIS 不单列 swaps 科目, 也不公开算法)。→ **绝不硬凑自算换算冒充真数据**(会造错数)。正解: 只消费已核实的公开真值(年报官方值 + GATA 推算值), 月度更新靠 cron 读 GATA 新披露**只增**补充。这是「取不到精确算法时, 用权威二手真值 + 如实标注, 而非自行错算」的范式。
- ★**给用户交底「能不能对上你发的图」的正确姿势**: Chao 的原图是**含义①(全市场 F&S 名义额 $858B, 美元级)**, 含义②是**吨数(几百吨级)** — **数值不能精确对应, 但趋势能对上**(2021 都是高点, 都反映央行借道 bullion bank 的黄金掉期活动)。诚实说清「不是同一个东西, 但方向一致」, 不假装数值吻合。
- **月度 PDF 抓取已验证可行(供 cron agent 未来补月度点用, 但只抠余额不自算吨数)**: `curl -A "Mozilla/5.0" https://www.bis.org/banking/balsheet/statofacc{YYMMDD}.pdf`(如 `statofacc260731.pdf`=2026-07-31), `pdfplumber` 抠出 `Gold and gold loans`/`Gold deposits` 两行 SDRmn + `USD 1 = SDR x.xxx` 汇率行。命名规律 `statofacc` + YYMMDD(月末日)。
- 三件套同步: `data/bis_gold_swaps.json`(公开 repo) + Notion `DB_BIS_GOLD_SWAPS`(15点, Kind select 区分 annual/monthly) + cron(fetch `bg=e.fetch_bis_gold_swaps()` + generate `bis_gold_swaps=bg`, DB 写入走 `write_data_from_env` 自动含)。`build_us_jp_market_dbs.py` 串第7个 DB(注意该文件用固定位置参数链 yid,nid,fid,iid,gid,hid,bid — 加 DB 要改 build return/write_data 签名/write_data_from_env/__main__ 共5处, patch 后检查有无遗留旧的短参数调用行需删)。

## ★Boolean / search-source 指标的正当性问题 + breadth-proxy 替代 (Chao 2026-08 纠正)

Chao 质疑 `ad_line`(NYSE 腾落线背离) card：**「这个卡片没有任何折线图或数字，你怎么就判断达到阈值了？」** — 直击 `source:"search"` + `unit:"布尔"` 指标的设计缺陷。这是 class-level 教训，任何 search/布尔源指标都适用。

- **缺陷根因(三条)**：① `manual_overrides.json` 里只存了 `{"value":true}`，**没存判定证据**(当时 S&P 点位/A/D 状态/来源链接/理由) → card 说"顶背离"但无法回溯凭什么。② A/D 线原始序列没抓 → **没底层数据 = 没法画图 = 用户无从验证**。③ `value:true` 是某次 cron agent web_search 后**主观判断**写入 → 若那次搜索质量低/AI 判偏，就把未经数据验证的 True 当既成事实喂进"7 卖出触发"计数。
- **铁律**：**任何进入信号灯/触发计数的 card，若只有一个布尔/定性结论而无(可画图的数字 OR 存证的判定依据)，就是设计缺陷**。要么升级成真数据数值指标(方案A)，要么至少强制 override 存 `evidence`(数字+来源链接+理由)供 card 展示回溯(方案B)。绝不让"无依据的 True"驱动卖出计数。

### A/D 线真数据源探测结论 + breadth-proxy 替代范式
- **NYSE A/D 腾落线每日原始序列 = 无稳定免费可程序化源**(2026-08 实测)：Stooq 全站 JS PoW 反爬墙(`^NYAD`/`^ADLN` 挡)；Yahoo A/D 符号 `^ADLINE`/`^NYAD`/`^ADD` 全 404 + 历史下载要 Gold 订阅；FRED 无 NYSE 每日涨跌家数；Finnhub breadth 在付费档(违"不引 key 商业 API"纪律)；IB/TradingView 要客户端/是脚本非数据接口。
- ★★**关键姿态**：结论**不是**"A/D 线无法做"(那会硬化成拒绝)，**而是**「A/D 原始序列拿不到 → 换等价的免费可测**广度代理(market breadth proxy)**」。A/D 线本质=衡量普涨 vs 少数权重股撑盘的**市场广度**。等价免费代理：
  - **RSP(等权标普 ETF) ÷ SPY(市值加权)** 比值 — 两者 yfinance/Yahoo 日线都能抓；比值下行=少数大票领涨、广度恶化=与 A/D 顶背离**同义**，且是**连续数值可画折线 + 可量化背离判定**。
  - 或 "% of stocks above 200MA" 类广度指标。
- **背离判定改成可复现数值规则**(替代 AI 主观布尔)：如"指数近 N 日创新高 且 广度代理同期未创新高"→ 程序算。这样 card 才有图、有数、可回溯，满足 Chao"有图有数字能验证"的核心诉求。`fetch_market_breadth()`+`_market_breadth_html`(SPY 价 vs RSP/SPY 归一广度比双线折线 + 数值背离判定，规则存 `evidence.rule`)。

### ★美股 ETF/指数日线的实际可用通道 = 东方财富原生 API(免key)，NOT yfinance/akshare 封装 (2026-08 实测)
拿 SPY/RSP 等美股日线做广度代理时，逐个实测的真相(排除法很关键，别默认 yfinance 能用)：
- **yfinance** △ `^GSPC .history()` 的 Close 常返 **NaN**(加 `auto_adjust=False`/`.dropna()` 也不稳)；A/D 专用符号 `^ADLINE`/`^NYAD`/`^ADD` 全 404。
- **akshare `stock_us_hist`/`stock_us_spot_em`** ✗ 库封装的请求头/session **被东财远端 reset**(`Connection aborted / RemoteDisconnected`)，连 A 股 `stock_zh_index_spot_em` 也 abort → 不是符号问题，是 akshare 封装被挡。
- ★★**正解：绕过 akshare，直接打东财原生 push2 API(免key，plain Mozilla UA + `Referer: https://quote.eastmoney.com/`)**：
  - **搜 secid**：`https://searchapi.eastmoney.com/api/suggest/get?input=<kw>&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=10` → `QuotationCodeTable.Data[].{Code,Name,MktNum}`；secid=`{MktNum}.{Code}`。验证 SPY=`107.SPY`(标普500ETF-SPDR)、RSP=`107.RSP`(平均加权指数ETF)。美股市场号 105=NASDAQ/106=NYSE/107=AMEX·Arca。
  - **拉日线**：`https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=107.SPY&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=20180101&end=<YYYYMMDD>` → `data.klines[]` 每行 `"date,open,close,high,low,vol,amount,pct"`(close=split[2])。验证 SPY/RSP 各 2167 日 2018-01-02→2026-08。
  - **同理 clist 全量美股**：`https://push2.eastmoney.com/api/qt/clist/get?fs=m:105,m:106,m:107&fields=f12,f14&pz=...`(f12=代码 f14=名称)，实测 total 13765 支，直连 200 OK。
- ★**东财对连续请求限流(反爬)**：单发/低频通，**连续调试几次后同一出口 IP 被临时封**(curl/requests 齐返空，冷却几分~几十分自恢复)。→ ① 用 `requests.Session()` + 递增退避重试(`sleep 1.5*(attempt+1)`, 6 次)+ 两 secid 请求间 `sleep 1`；② **必须缓存兜底**：抓到就落盘 `data/*.json`，抓不到读缓存(不覆盖成空)——符合项目"抓不到保留旧真值"铁律；cron 每日**低频**跑正常能刷新，调试期被封别误判为"源不可用"。这套「原生 API + Session 退避 + 缓存兜底」是所有东财数据源的标准打法。

### 授权数据通道备选：moomoo OpenD（当爬取源被限流/需正规行情权限时，Chao 2026-08 提议）
当东财等爬取源不稳、或需要正规授权的美股广度/行情数据时，Chao 有 moomoo 账号可登录 OpenD 供数取数。架构与前提(实测记录，供未来复用)：
- **两件套**：`futu-api` Python SDK(`pip install futu-api`，本项目 .venv 已装 v10.9.6908，纯 pip 即得) + **OpenD 本地网关程序**(需另下载运行，SDK 通过它连 moomoo 服务器，默认监听 127.0.0.1:11111)。
- **OpenD 命令行版**支持 Ubuntu/CentOS(headless VM 用命令行版非可视化版)，官方下载页 moomoo.com/download/OpenAPI → 切 Moomoo OpenD tab → Linux。★**下载直链是重度 JS 动态生成(走登录态/DownloadMarketDialog 弹窗)，无头浏览器抠静态 DOM/getConfigData/getSoftInfo 均拿不到干净 tar 直链** → 最省事是**让 Chao 在自己电脑点下载后把 tar.gz 链接或文件发来**(OpenD 本就需要他账号登录，顺带一步到位)，别在无头浏览器里反复钻直链(本 session 钻了多轮无果，低效)。
- **前提须 Chao 在场配合**：① 账号需**开通对应市场行情权限**(美股 LV1 一般免费够用，某些 breadth 可能要 LV2/订阅)；② 新版 OpenD(≥10.10.7008，2026-08-13)**已从配置文件移除账号密码**，改交互式登录，可能需**手机验证码** → 登录这步必须用户参与，不能纯自动化。
- 用途：指数/个股/ETF 历史 K 线、涨跌家数/市场广度、Market Fundamentals(机构追踪/宏观/股息财报日历/Market Movers) 等，是比爬东财更稳的授权源；作为爬取源的**升级备选**，不阻塞已跑通的东财+缓存兜底方案。

## ★加新 bottom-block section 的可复用套路 + 踩坑 (2026-08 累积)

每加一图/一 section 走固定 6 步(≈5+ tool call)，全部一次做完不留半成品：
1. **fetch 函数**(external_data.py 或 fetchers/)：★**函数内必须局部 `import requests`**——external_data.py **顶部没有 module-level import requests**，每个函数各自 `import requests`(或 `import json, requests`)。漏了 → `NameError` 被 except 静默吞 → 函数返 status="未获取" 但你以为是数据源问题，白 debug。
   ★**fredgraph.csv 端点对 python `requests` 偶发 ReadTimeout(curl 秒回)** → GDP 等 FRED CSV 用 **curl subprocess 回退**(`subprocess.run(["curl","-s","--max-time","20",url])` ×3重试)或走带key `fetchers.fred.*`。这是本项目反复踩的坑，已在 credit-impulse/custody 段记过，任何新 FRED 拉取默认走 API-key 通道或 curl。
2. **渲染函数**(dashboard.py)：复用现有 SVG 原语(`_hf_line_svg` 通用季度多线 / `_credit_impulse_svg` 零轴带符号 / `_iip_net_svg` / `_yield_curves_svg`)。莫兰迪配色(陶土红#c0757d/雾霾蓝#6b8fb5/鼠尾草绿#7fa085/琥珀#e0a92e)，信号点绿#2e9e5b/黄#e0a92e/红#d64545 空心圈，红线阈值#d64545 虚线。用 `_esc()`。
3. **generate() 4-slot 接线**：签名加 `xxx=None` kwarg + format dict 加 `xxx=_xxx_html(xxx)` + section 模板 `<div class="card">{xxx}</div>` + build_dashboard.py 加 `xxx = ed.fetch_xxx()` + generate 调用传 `xxx=xxx`。
4. **侧栏分组**(dashboard.py GROUPS JS)：★★**`groupOf` 按 GROUPS 顺序返回首个 substring 命中** → 新组关键词若是既有组关键词的子串会被先吞。踩坑：国债组有 `'美日'` → "美日财政政策事件" 被误归国债组永远进不了"财政政策"组。修法：把宽泛子串改精确(`'美日'`→`'美日 10'`)，或新组关键词避开既有子串。加完必程序化验证 `groupOf(标题)` 落对组。
   ★侧栏 clone 节点取 label 前先 `.freq-badge` remove(否则"每日更新"拼进链接名)。
5. **Notion**：时序数据进新 DB(`build_us_jp_market_dbs.py` 加 create_db 幂等+write_data 段+`write_data_from_env` env入口，返回 tuple 逐个加 id)。★**指标 card(config.INDICATORS)走 DB_INDICATORS——create_db 幂等不会给已存在 DB 加新列**，新指标要单独 `_req("PATCH", f"/databases/{dbid}", {"properties":{name_en:{number:{}}, name_en+" 信号":{select:{options:[🟢🟡🔴⚪]}}}})` 补值列+信号列，否则 run.py 写入 400 "not a property that exists"。
6. **cron 接线**(jobs.json inline generate)：Python 精确替换(execute_code 被 cron 禁 → venv python via terminal)，fetch 段加 `xxx=e.fetch_xxx();`，generate 段加 `xxx=xxx,`；Notion 写入若走 `write_data_from_env` 则读全部 DB 自动含新 DB 无需额外行。离散事件/难源(如财政新闻)加自然语言"步骤 N.M"让 cron agent 每日 web_search 合并进 json(只增/去重/绝不编/抓不到保留旧)。改完 `assert pr.count(锚点)==1` 验证唯一匹配。
7. **收尾**：build 后台跑(含慢抓取 notify_on_complete)→ 程序化验证(`browser_console` 查 SVG polyline/rect 数 + 侧栏分组，视觉后端故障时靠这个)→ 截图发 Chao(MEDIA)→ 红线扫描(内网URL/密钥，`.env` git check-ignore)→ commit `--no-gpg-sign` 后台 push(前台常超时)。★part-title 的 `id=` 会被侧栏 JS 重设 `sec-N` → 程序化定位 section 用标题文本 find 不用原 id。
