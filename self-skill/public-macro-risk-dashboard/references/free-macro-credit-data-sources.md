# Free data-source bank: sovereign debt/GDP + US corporate credit by rating

Probed and VERIFIED live (2026-08). Use this before answering "能不能做这张图" for these two
families — the vetting is already done, don't re-probe from zero.

Chao's standing rule this serves: 愿为一 key 破"不引入需 key 商业 API"红线，但须先证明免费路堵死才问。
So: prove the free path, and be explicit about what the free path genuinely CANNOT deliver.

---

## ① Sovereign 债务/GDP (前十经济体等)

**IMF DataMapper API — free, no key, official, 226 countries.**
```
https://www.imf.org/external/datamapper/api/v1/GGXWDG_NGDP
→ {"values": {"GGXWDG_NGDP": {"USA": {"1990": …, "2031": …}, "CHN": {...}, ...}}}
```
- Indicator `GGXWDG_NGDP` = General government gross debt, % of GDP. ISO-3 country keys.
- Verified pull: USA / CHN / JPN / DEU / IND / GBR / FRA / ITA / CAN / BRA all present,
  n = 31–52 annual points each.
- **Frequency trap — state this to Chao BEFORE building:** the series is **ANNUAL**, refreshed only
  twice a year with the IMF WEO (April / October). A "weekly or monthly updating" chart built on it
  will re-fetch on schedule but **the numbers will not move**. Offer honestly: the cron can run weekly
  and the freshness badge shows "距上次 WEO 发布 N 天", but do not imply the data is weekly.
- **The tail years are FORECASTS, not actuals.** IMF ships projections several years out (a 2026 pull
  returns values through 2031). Rendering those as历史实测 would be fabrication-by-omission. Split the
  line: solid = actual, dashed = IMF projection, and label the split year explicitly.
- Higher-frequency alternative is NOT equivalent: BIS `WS_TC` credit-to-GDP is quarterly but measures
  **credit-to-GDP (private/total credit)**, a different concept from **government gross debt/GDP**.
  Don't silently substitute it to win frequency. (BIS SDMX v2 returned HTTP 406 on the naive
  `?format=jsondata` call — needs an `Accept:` header negotiation if you do pursue it.)

---

## ② US corporate bonds by rating — 利率 ✅ 日频免费 / 总额 ⚠️ 只有季度

### The trap that will silently produce a WRONG chart
FRED ICE BofA series ending in **`TRIV` are `Total Return Index Value` — an INDEX, not an amount.**
Verified metadata:
```
BAMLCC0A0CMTRIV    → "ICE BofA US Corporate Index Total Return Index Value", units = Index
BAMLHYH0A0HYM2TRIV → "ICE BofA US High Yield Index Total Return Index Value", units = Index
```
Plotting these as "公司债总额度" yields a curve that moves with **price/total return**, not with debt
outstanding — it would rise in a bond rally while issuance shrank. **Always call the FRED
`/fred/series` metadata endpoint and read `title` + `units` before charting an unfamiliar series ID.**
A plausible-looking ID suffix is not proof of what the series measures.

### 利率 by rating — daily, free, current (all verified, obs date 2026-08-18)
Effective yield:
`BAMLC0A1CAAAEY` AAA · `BAMLC0A2CAAEY` AA · `BAMLC0A3CAEY` A · `BAMLC0A4CBBBEY` BBB ·
`BAMLH0A1HYBBEY` BB · `BAMLH0A2HYBEY` B · `BAMLH0A3HYCEY` CCC&lower

**Prefer OAS over raw yield when the question is "利率是否波动 / 风险是否上升":**
`BAMLC0A1CAAA` · `BAMLC0A4CBBB` · `BAMLH0A3HYC` · `BAMLC0A0CM` (IG all) · `BAMLH0A0HYM2` (HY all)
— all daily, units = Percent. Raw effective yield moves when the *Treasury* curve moves; **OAS is the
pure credit risk premium.** A yield chart alone will mislead Chao about credit stress.

Rating-split TRIV variants DO exist (`BAMLCC0A1AAATRIV`, `BAMLCC0A4BBBTRIV`, `BAMLHYH0A3CMTRIV`) —
still total-return indices, still not amounts.

### 总额 (outstanding) — quarterly only, no free daily equivalent
Fed Z.1 Flow of Funds via FRED, units = Millions of USD, Quarterly End of Period:
- `BCNSDODNS` Nonfinancial Corporate Business; Debt Securities **and Loans**; Liability, Level
- `NCBDBIQ027S` Nonfinancial Corporate Business; **Debt Securities**; Liability, Level
- `TODNS` Domestic Nonfinancial Sectors; Debt Securities and Loans (broader)
- (`ASTLL` is **DISCONTINUED** — metadata says so; don't wire it.)

**There is NO free source for daily, rating-split outstanding amounts.** That dataset is commercial
(ICE / Bloomberg index constituent files). Say this plainly rather than approximating it with an index.
`sifma.org/resources/research/us-corporate-bonds-statistics/` 404s — SIFMA reorganised; their xlsx is
quarterly anyway, so it adds nothing over Z.1.

### Honest decomposition to offer Chao for "整体公司债务是否增加，利率是否波动"
- **利率 / 波动** → daily OAS by rating (+ effective yield as secondary). Real-time, free.
- **总量** → quarterly Z.1 outstanding, with the quarterly-lag badge.
- If he actually wants **新发行量** (a plausible reading of "总额度"), that's a THIRD source family
  (SIFMA issuance tables / FINRA TRACE) — ask which he means instead of guessing; the three answers
  look completely different on a chart.

### A read worth surfacing unprompted
The verified 2026-08-18 curve was AAA 5.33 / AA 5.26 / A 5.28 / BBB 5.60 / BB 5.99 / B 7.27 /
**CCC 14.52** — a ~7pt gap between B and CCC. Rating-tier dispersion like that is a stronger credit
signal than the aggregate level; lead the report with it rather than with the index average.

### Percentile beats level AND beats 1-month delta (built 2026-08, same session)
Both the level table and the "近1月Δ" column understate the story. Ranking each rating's current OAS
within its OWN available window is what makes the dispersion legible:

| rating | OAS | 1m Δ | percentile of own 3y range |
|---|---|---|---|
| AAA | 0.42% | +1bp | 84% |
| AA | 0.60% | +4bp | 89% |
| A | 0.69% | +3bp | 43% |
| BBB | 1.00% | +3bp | 26% |
| BB | 1.63% | 0bp | 11% |
| B | 2.94% | +3bp | 30% |
| **CCC** | **10.27%** | **+52bp** | **98%** |

Reading: CCC near its 3-year high while BB/BBB sit near their tights ⇒ the market is **not** pricing
broad credit tightening; distress is isolated to the weakest issuers — the early-turn signature,
distinct from a general risk-off. Render this as a chip row with an interpretive note derived from
`ccc_pct - mean(ig_pct)` (>30 ⇒ isolated-distress wording; <-30 ⇒ risk-on wording), never hand-written.
Implementation + the date-vs-value pitfall: `references/chart-visual-qa-and-integrity-verification.md` §C.

---

## ③ Company-level fundamentals (FCF, debt, capex) — SEC EDGAR XBRL, free, no key

Probed and VERIFIED live 2026-08 on a 19-company AI-infrastructure universe.

```
https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-zero-padded}.json   # everything, 1 call
https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json    # one tag
```
Requires a descriptive `User-Agent` with contact info. Throttle ~0.15 s between calls.
Prefer **companyfacts** (one call per company) over per-tag companyconcept (N calls, rate-limit pain).

标准 FCF = `OCF − CapEx`. Coverage achieved: **17–18 / 19**.

### ★★ The CURRENCY trap — a silent 32× error that depends on JSON key order
**The single most dangerous XBRL bug found so far.** `companyfacts` reports the SAME tag under
MULTIPLE currency units simultaneously:
```json
"CashFlowsFromUsedInOperatingActivities": {"units": {
    "TWD": [...],        // 1,826,000,000,000
    "USD": [...]         // 55,693,100,000     ← ~32× smaller
}}
```
A helper that loops `for unit, rows in node["units"].items()` and lets later writes overwrite earlier
ones returns **whichever currency SEC happened to serialise last**. It was returning USD correctly —
purely by luck. A change in SEC's key order (or a `dict` rebuild) silently multiplies TSM by 32 and
every derived ratio with it. Nothing in the output looks wrong; the number is just 32× too big.

**Rule: filter the unit key explicitly, never iterate all units.**
```python
rows = node.get("units", {}).get("USD")     # hard requirement, not a preference
if not rows:
    return {}                                # no USD ⇒ genuinely unusable, return empty
```
Applies to every `us-gaap` AND `ifrs-full` pull. Any foreign private issuer (TSM, and by extension
most 20-F filers) is exposed. Verified fix: TSM OCF `55.7B USD`, cash `64.9B USD` — unchanged after
the fix, which is exactly the point: **a latent bug that currently returns the right answer still
must be fixed**, because the correctness isn't guaranteed by anything.

### ★ The stale-tag trap — the #1 way this silently produces a WRONG chart
Companies migrate between XBRL tags over time, and **the deprecated tag often still has old data
sitting in it**. A naive "first tag that returns anything wins" loop happily returns a 14-year-old
number and the chart looks fine:

| ticker | naive first-hit CapEx | correct latest-FY CapEx |
|---|---|---|
| NVDA | `0.1B @2012` ❌ | `6.0B @FY2026` |
| AMZN | `6.7B @2016` ❌ | `131.8B @FY2025` |
| EQIX | `0.0B @2010` ❌ | `9.6B @FY2025` |

**Rule: never accept a tag hit without checking its period end.** The fix that worked:
1. Pull OCF first, take its **latest fiscal-year end** as the anchor `latest_fy`.
2. For CapEx, iterate ALL candidate tags and **sum only those with a value at that same `latest_fy`**
   (several filers legitimately split capex across multiple tags — EQIX = ProductiveAssets +
   OtherPropertyPlantAndEquipment + RealEstate; AMD = PropertyPlantAndEquipment + PaymentsForProceedsFrom…).
3. Restrict to `form ∈ {10-K, 20-F, 10-K/A}` AND duration 330–400 days (kills quarterly/partial rows).
4. De-dupe by `end` date, later entries overwrite (picks up restatements).

Candidate CapEx tags that were actually needed: `PaymentsToAcquirePropertyPlantAndEquipment`,
`PaymentsToAcquireProductiveAssets`, `PaymentsForCapitalImprovements`,
`PaymentsToAcquireOtherPropertyPlantAndEquipment`, `PaymentsToDevelopRealEstateAssets`,
`PaymentsToAcquireRealEstate`, `PaymentsForProceedsFromProductiveAssets`.

### Known per-filer exceptions (don't burn time rediscovering)
- **TSM** files 20-F under **IFRS** — no `us-gaap` namespace at all. Use `ifrs-full`:
  `CashFlowsFromUsedInOperatingActivities` +
  `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`.
- **NEE (utilities)** has OCF in us-gaap but **no standard capex tag** — its only `Payments*` tags are
  NuclearFuel / DecommissioningFund / dividends etc. Capex lives in a company **extension namespace**
  not exposed by companyfacts. Exclude with a stated reason; do NOT substitute a scraped figure.
- Fiscal years are NOT aligned (MSFT 06-30, ORCL 05-31, NVDA 01-25, AVGO 11-02, MU 08-28). Any
  cross-company chart MUST print each company's own FY end, never a single "2025" header.

### Lease-adjusted FCF — coverage too thin, don't promise it
`FinanceLeasePrincipalPayments` / `RepaymentsOfFinanceLease` /
`RepaymentsOfLongTermCapitalLeaseObligations` were **missing for 7/19** (AMD, TSM, DLR, VRT, CEG, NEE,
GEV), and several `0.0B` hits are tag-convention artifacts rather than genuine zero lease activity.
Chao's rule "有可靠源就做，没有就做标准的" ⇒ ship standard FCF only, say why.

### Frequency reality — state it before building
**FCF cannot be daily.** It comes from 10-Q/10-K: 4 points a year. When Chao asks for a "每天都能拿到
数据" version of a fundamentals chart, correct the premise up front — only market-priced series update
daily. The right question to test instead is whether the *field* is consistently disclosed.

---

## ④ Single-name corporate credit spread (company bond yield − matching-maturity UST)

**Free path is CLOSED. Verified 2026-08 — do not re-probe hopefully, and do not fake it.**

- **FINRA TRACE**: every documented endpoint 404s
  (`services-dynarep.ddwa.finra.org/public/reporting/v2/...` corporateBondSearch / bondSearch /
  CorporateAndAgencyDebtMarketBreadth). One URL returns **HTTP 200 but the body is an OpenSSO login
  page** — a 200 is not proof of data; always inspect the body.
- **Implied funding cost** (`InterestExpense ÷ LongTermDebt` from XBRL) — computable but the output is
  visibly garbage and must NOT be laundered into a chart: AMD **13100 %**, ORCL **0.00 %** (debt tag
  resolved to 0 while interest was $4.6 B), DLR 14.9 %, and fiscal years scattered 2021–2026 so nothing
  is comparable. It is also a **backward-looking book average, not a market spread** — conceptually the
  wrong quantity even when it computes cleanly.
- Treasury benchmark leg is fine and free: FRED `DGS2/DGS5/DGS10/DGS30` all HTTP 200.
  **The missing leg is always the corporate one.**
- Structural blockers independent of any API: OpenAI / Anthropic / xAI are **private — no public debt,
  no FCF disclosure**; and many AI names have **no 30-year bond at all**, so "vs 30Y UST" is undefined
  for them.

**Honest substitutes to offer instead** (all real data, all free):
1. **Rating-proxy spread** — map each company to its credit rating and use the daily rating-tier OAS
   curve from §②. Real and daily; cost is that same-rating companies share one spread (not single-name).
2. **Only the few names with genuine coverage**, everything else explicitly `n/a`.
3. **Leverage metrics that need no bond quote** — Net debt/EBITDA, interest-coverage, all from SEC XBRL,
   full coverage. Pair with the FCF chart for a burn + balance-sheet view.
Recommend 1 + 3 together: market-pricing view (daily) plus fundamentals view (full coverage).
Never substitute equity volatility or implied funding cost for a credit spread.

### Round 2 — the UNOFFICIAL / personal-site sweep (Chao asked for it explicitly; also closed)
When you report "免费源堵死", Chao's likely follow-up is **"再扩展一下范围，看看有没有个人网站上的非官方源"**.
Run that sweep *before* he has to ask. Verified 2026-08, all dead ends:
- **Boerse-Frankfurt** bond pages → **HTTP 403** (bot-blocked even with a full browser UA).
- **WSJ** market-data bond quotes → **HTTP 401**.
- **Business Insider / markets.businessinsider.com bond search** → returns 200 with real HTML, but
  **silently ignores the issuer filter**: a search for NVDA bonds came back with Uzbek mining bonds.
  A 200 + plausible-looking page is NOT coverage — always assert the returned rows actually match
  the entity you queried.

### The ONE unofficial source that does parse — Damodaran synthetic spreads (use with a loud caveat)
`https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.htm` — NYU Stern, free, no key.
Full **15-tier** table parses cleanly out of the HTML:
```python
txt = re.sub(r"<[^>]+>", " ", html); txt = re.sub(r"&nbsp;?", " ", txt); txt = re.sub(r"\s+", " ", txt)
pat = re.compile(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+([A-Da-z0-9+\-/]{1,8})\s+(\d+\.\d+)%")
# → (coverage_lo, coverage_hi, rating, spread_pct); require ≥10 tiers or treat as parse failure
```
**What it actually is: interest-coverage-ratio → synthetic rating → default spread. A MODEL MAPPING,
not observed market pricing.** It answers "按财务比率这家公司该有多少利差", never "市场实际怎么给它定价".
It is also refreshed **annually** — it can never back a daily chart.
Ship it only as an optional secondary axis, labelled `★模型估算，非市场报价` in the UI, and say the same
in chat. Do NOT let a parseable table tempt you into presenting it as a spread quote.
- Note the sibling trap: Damodaran's `ratings.xls` is a **synthetic-rating template**, not per-company
  spreads. Downloading a real .xls is not evidence it contains what you want — open it and check.

### What to actually ship for "单公司信用维度" (the settled answer — BUILT & SHIPPED 2026-08)
Net debt/EBITDA + interest coverage from SEC XBRL (real filings, near-full coverage), Damodaran
synthetic spread optional/secondary. Watch coverage: `InterestExpense` resolved for only **8/18** on the
first pass — `_INT_TAGS` needs the full alias list (`InterestExpense`, `InterestExpenseDebt`,
`InterestExpenseNonoperating`, `InterestAndDebtExpense`, IFRS `FinanceCosts`) and even then some filers
only report it inside the income-statement text block. Report the real N/18, don't imply full coverage.

**Final shipped coverage: 16/18 leverage · 17/18 interest coverage** (up from 8/18) — via the
common-fiscal-year anchor below plus per-issuer fallback tags.

#### ★★ Anchor on the COMMON fiscal year — never "latest value per tag"
Taking each component's own latest value fabricates ratios from mismatched years. Measured tag
end-of-life dates on this universe:
- **DLR** `LongTermDebtNoncurrent` stops at **2011**
- **ETN** `OperatingIncomeLoss` stops at **2019**

So a naive build divides FY2011 debt by FY2026 EBITDA and prints a confident, meaningless number.
Correct approach — intersect the available years, take the most recent one present in ALL components:
```python
def _common_fy(*series):                 # each series is {end_date: value}
    common = set(series[0])
    for s in series[1:]:
        common &= set(s)
    return max(common) if common else None
```
Report that anchor year per company in the UI (fiscal years are not aligned — this universe spanned
FY2024-12 through FY2026-06 simultaneously).

#### Per-issuer fallback tags that were actually required
- **TSM** → IFRS namespace throughout (`DepreciationExpense`, `CashAndCashEquivalents`).
- **ETN** → `OperatingIncomeLoss` dead after 2019 ⇒ fall back to pre-tax income.
- **GEV** → debt filed **only in 10-Q**; `LongTermDebtAndCapitalLeaseObligations` recovers it. If your
  helper is annual-only (10-K/20-F), GEV's debt is legitimately absent — that's correct behaviour,
  not a bug to work around with quarterly data.

#### Where to STOP and mark n/a — DLR leverage
Recent DLR 10-Ks carry **no total-debt annual tag**. Only 10-Q components exist
(`SecuredDebt 0.84B` + `UnsecuredDebt 0.43B`), and summing those **understates** true total debt.
Per the project's 铁律: mark `n/a` with the reason surfaced in the caption. Do not sum partial
components to manufacture coverage — a plausible number is worse than an honest gap.

#### Caption obligation for this chart
Because users read "credit" as "spread", the caption must state outright that this is a
**财报口径 (filings-based) leverage/coverage view, NOT a market credit spread**, and why (§④ free
path closed). Otherwise the chart implies market pricing it does not contain.

Re-runnable probe: `scripts/probe_sec_xbrl_fundamentals.py`.

