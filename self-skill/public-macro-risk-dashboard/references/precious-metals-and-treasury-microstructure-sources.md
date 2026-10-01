# Free first-party sources: precious-metals ETF flows & Treasury microstructure

Probed and VALIDATED in a 2026-09 session. Each entry says what it gives, the exact endpoint,
and — where relevant — the trap that makes it look usable when it isn't.
Skip re-probing the ❌ rows; they were exhausted, not glanced at.

---

## ✅ WGC `fsapi.gold.org` — gold ETF flows BY REGION (the big win)

This is the **official data backend of the World Gold Council Goldhub "Gold ETF flows" chart** —
the exact chart that circulates in Chinese finance videos/screenshots. Free, no key, no signup.

Discovery path (reusable): the Goldhub HTML page
`https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows` embeds its own API URLs.
`re.findall(r'["\']([^"\']*api[^"\']*)["\']', html)` surfaced them. **Always grep a data page's
HTML for embedded `api/` paths before concluding "no API"** — the page has to get its numbers
from somewhere.

```
flows    https://fsapi.gold.org/api/v11/charts/etfv2/revised/flows-chart2
holdings https://fsapi.gold.org/api/v11/charts/etfv2/revised/holdings-chart2
archive  https://fsapi.gold.org/api/v11/charts/etfv2/revised/archive-tablegroup/all
```
Send `Referer: https://www.gold.org/` + a browser UA (plain requests works; no cookie needed).

Shape:
```
chartData.asOfDate                      # e.g. "2026-09-11", WGC updates weekly
chartData.data.{Yearly,Quarterly,Monthly,Weekly}.series.{tonnes,usd}
  -> [ {name: "North America"|"Europe"|"Asia"|"Other"|"Gold Price (rhs)",
        data: [[epoch_ms, value], ...]} ]
```
Weekly = 454 points back to 2018-01-05. Four regions + gold price on the same axis object.

**Validation anchor (do this before shipping):** the public WGC chart annotates 2026-06-12 =
−24.7t and 2026-06-26 = −38.2t. Summing the four regions from the API reproduced both exactly.
Always reproduce one published annotation before trusting a newly-found endpoint.

Also worth computing, because users quote claims like "biggest outflow since 2022-09":
rank the latest week's global total against the whole 454-week history. In this case 2026-06-26
(−38.2t) was **second**, not first — 2022-09-30 was −38.4t. State the rank honestly rather than
repeating the video's claim.

### ❌ TRAP: `?metal=silver` returns HTTP 200 with GOLD data
`.../flows-chart2?metal=silver` → **200, ~242KB, structurally perfect** — and byte-identical to
the gold response. The parameter is silently ignored. Shipping it would have put gold numbers on
the dashboard labelled "silver".

Detection (cheap, do it for ANY endpoint where you guessed a query param):
- fetch both with and without the param, compare the latest values — identical ⇒ param ignored;
- sanity-check magnitude: the series was still named `Gold Price (rhs)` at ~4400/oz; silver is ~50.

General rule: **HTTP 200 is not evidence the parameter did anything.** Prove the response actually
differs, or that a value is in the right order of magnitude, before wiring it.

---

## ❌ Silver ETF flows by region — NO free authoritative source (exhausted)

All of these were probed in one sweep; none yields a regional weekly tonnage series:

| Source | Result |
|---|---|
| WGC fsapi `?metal=silver` | 200 but returns gold (see trap above) |
| `fsapi.gold.org/.../silveretf/...`, `/etfv2/silver/...`, `/silver/...` | 404 |
| Silver Institute (silverinstitute.org) | pages 200 but zero data files, zero api paths; `/silver-etps/` 404 |
| iShares SLV/IAU `.ajax?fileType=csv` | 200 but body is the HTML page shell, not CSV |
| SPDR `GLD_US_archive_EN.csv` | 200 but body is a **PDF** (`%PDF-1.5`) |
| Sprott PSLV api/pages | 404 |
| abrdn SGOL/SIVR api | 504 |
| Yahoo `quoteSummary` (AUM / totalAssets) | **401 across all tickers** — can't get AUM this way |
| LBMA `prices.lbma.org.uk/json/silver.json` | 200, but it's **price** history (1968→), not flows |

What *is* reachable: Yahoo `v8/finance/chart/<ticker>` gives price+volume for all the regional
ETFs (GLD IAU SLV SGOL GLDM SIVR PHYS / PHAU.L SGLN.L PHAG.L 4GLD.DE XAD1.DE / 1540.T 2840.HK).
But **price ≠ flow** — without shares-outstanding or holdings you cannot derive a flow, and AUM
deltas conflate price effect with real creation/redemption. Do not dress a price series up as a
flow series.

**Correct handling:** build the gold section from WGC, and put an explicit "why no silver" note
in the UI listing these dead ends. Chao's rule — 拿不到就说没有 + 给最接近口径 — means naming the
limitation in the product, not just in a commit message.

---

## ✅ NY Fed FR2004 Primary Dealer survey — Treasury transaction volumes

Covers the "dealer volume" dimension of Morgan Stanley-style Treasury-microstructure exhibits.
Official, free, weekly, 700+ points back to 2013-04.

```
https://markets.newyorkfed.org/api/pd/get/{SERIES_ID}.json
https://markets.newyorkfed.org/api/pd/list/timeseries.json     # 1539 series, search here
```

**Critical naming distinction — getting this wrong silently swaps the metric:**
- `PDPOS*` = **POSITIONS** (inventory held)
- `PDTR*` / `PDGSW*` = **TRANSACTIONS** (volume traded)

For "trading volume" exhibits you want the TRANSACTIONS family. Useful IDs:
```
PDGSWOEXTTOT   US Treasuries ex-TIPS, total weekly transaction volume
PDTRGSC-L2     by remaining maturity  <= 2Y      <- the "2-year" dimension MS charts
PDTRGSC-G2L3   2-3Y
PDTRGSC-G3L6   3-6Y
PDTRGSC-G6L7   6-7Y
PDTRGSC-G7L11  7-11Y
```
**口径 caveat that must be labelled on the chart:** MS/BrokerTec-style exhibits plot **DV01-weighted**
volume (duration risk transferred); NY Fed publishes **notional** volume. Direction agrees, the
numbers are not the same metric. Say so on the chart, don't quietly imply equivalence.

## ❌ Treasury bid-ask spread — no free source
BrokerTec intraday bid-ask (MS Exhibit 3) is a CME commercial product. No free equivalent exists.
Closest honest proxies: **OFR Financial Stress Index `Funding` category** (official, daily,
currently maintained) and 10Y intraday high-low range. Label as proxy, prominently.

### ❌ TRAP: Cleveland Fed FSI liquidity component is DISCONTINUED
`LQTYSD678FRBCLE` ("Cleveland Financial Stress Index — Liquidity Spread") has a *perfect* name for
a bid-ask proxy. FRED metadata shows it **stopped 2016-05-05 (DISCONTINUED)**. Wiring it would have
put a ten-year-flat line on the dashboard that looks completely normal.

**Rule: for any FRED-family series you have not used before, read `series` metadata
(`observation_end` / notes / title containing DISCONTINUED) before wiring it.** A matching name is
not evidence of a live series. Record the exclusion reason in the UI so nobody re-adds it later.
