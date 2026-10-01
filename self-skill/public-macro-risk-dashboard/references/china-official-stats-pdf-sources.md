# Chinese official statistics via PDF — CIPS and the general pattern

Probed and VERIFIED live 2026-08. Covers the CIPS (人民币跨境支付系统) usage series specifically, and
the *general* technique for pulling numbers off Chinese official sites, which almost never expose JSON.

---

## The general pattern (applies well beyond CIPS)

Chinese official/regulator sites (CIPS, PBOC, SAFE, 清算总中心 …) typically:
1. Render the statistics landing page **client-side** — the static HTML is an empty shell, and
   `browser_navigate` shows `loading...` with **no iframe and no data links**. Scraping the HTML is futile.
2. Publish the actual numbers as **linked PDF attachments** under `articleFileDir/` or `attachDir/`.
3. Keep **only the current year** on the live page, plus sometimes a separate "历年" (all-years) file.

So the workflow is: **find the PDF, not the API.** Fastest route to the PDF is a plain `web_search` for
the statistic name — the PDF itself ranks and hands you the exact URL, far quicker than crawling the site.
Then `pymupdf` (`pip install pymupdf`; import as `pymupdf`, `import fitz` warns as deprecated).

Also: the **old-version URL path often still works and is richer than the new one.** For CIPS the new
`/kjjqgs/cipsfw/ywtj/index.shtml` was empty, while legacy `/cips/xwzx/ywtj/index.html` still served the
PDF links. When a modern path renders empty, try the site's previous-generation path before giving up.

## Wayback is NOT a reliable backfill for these sites
CDX returned 22 archived `cips.com.cn` PDFs, but **none was the statistics table** — all were
rules/standards documents (`ICS`-headed spec PDFs). The statistics *landing pages* had **zero** snapshots.
Don't budget much time on Wayback for Chinese regulator statistics; check quickly, then move on.

---

## CIPS concrete endpoints (verified 2026-08)

```
当年(monthly, current year):
https://www.cips.com.cn/kjjqgs/articleFileDir/2025-12/05/c1ed77e02af749fb87cfb17484f9efb6.pdf
历年(annual, 2015→latest):
https://www.cips.com.cn/kjjqgs/articleFileDir/2025-12/05/14c90b4ac33f4440b0085632f2c1ee73.pdf
```
Both are linked from `https://www.cips.com.cn/cips/xwzx/ywtj/index.html`. **Re-discover the links from
that page each run — the hashed filenames will change.** Don't hardcode the hashes.

Monthly table columns: 月份 / 笔数 / 金额(亿元) / 工作日数量 / 日均笔数 / 日均金额(亿元)
```python
pat = re.compile(r"(\d{1,2})月\s+([\d,]+)\s+([\d,\.]+)\s+(\d+)\s+([\d,]+)\s+([\d,\.]+)")
# 历年: r"(20\d\d)年\s+([\d,]+)\s+([\d,\.]+)"
```

Verified values (use as regression fixtures):
- 2026-01 → 731,130 笔 / 169,858.0 亿元 / 22 工作日 / 33,233 日均笔 / 7,720.8 日均额
- 2026-03 → 786,441 / 202,500.9 / 22 / 35,747 / **9,204.6**
- 2026-07 → 836,827 / 193,509.3 / 23 / 36,384 / 8,413.4
- 年度 2023 → 6,613,290 笔 / 1,230,635.6 亿元 · 2024 → 8,216,891 / 1,754,928.1 · 2025 → 8,441,897 / 1,801,526.9

**Two independent cross-checks that both passed** (do this before trusting any parse):
- 2026-03 日均 9,204.6亿元 vs 证券时报报道「9205亿元」 ✅
- 2024 年度 8,216,891笔 / 175.49万亿元 vs 维基百科 ✅

---

## Coverage gap you must disclose, not paper over
The live site carries **only the current year's monthly file**. Verified misses: swapping the year in the
`articleFileDir/{YYYY-MM}/` path 404s for every other year; directory listing is 403/404; Wayback has none.

⇒ **2024 monthly and 2025-01/02 monthly are NOT obtainable from the official source.**
Report the real span ("月度只能做到 2025-03 → 2026-07，共17个月") and offer annual bars for earlier years.
Never interpolate or reverse-engineer the missing months into the monthly series.

### Third-party fill: chinadata.live
`https://chinadata.live/data/china-cips-payment-system-monthly/` supplies 2025-03 → 2026-06.
**All 6 overlapping months matched the official PDF exactly (0 discrepancies)** — that cross-check is
what earns it a place, and you must run it rather than assuming.
Caveat to state anyway: its 2025 values all end in `0`, consistent with being reverse-derived from
日均 × 工作日 rather than原始披露. Mark them as 第三方推算 in the UI, distinct from official months.

There is also a clean JSON/CSV endpoint (avoid scraping the HTML):
```
https://chinadata.live/api/v2/data/china-cips-payment-system-monthly            # JSON
https://chinadata.live/api/v2/data/china-cips-payment-system-monthly?format=csv # CSV
```

#### ⚠️ The column NAME lies about the unit — derive the scale, never trust the label
The CSV column is `amount_100m_rmb` (亿元), but the values are actually **billions RMB — off by 10×**:
official 2026-01 = 169,858.0 亿元 while the feed says 16,985.8. A label-trusting parse silently
publishes a series one order of magnitude wrong, and because the *shape* is identical nothing looks
broken.

Fix pattern — compute the multiplier from the officially-known overlap, and refuse the batch if it
isn't stable:
```python
ratios = [official[ym] / third[ym] for ym in overlap if third.get(ym)]
mult = sum(ratios) / len(ratios)
spread = max(ratios) - min(ratios)
if spread > 0.01 * mult:          # inconsistent -> the feed changed meaning; drop it entirely
    note = f"第三方金额倍率不稳定(mult={mult:.3f}, 离散={spread:.3f}), 已弃用第三方回补。"
    third_months = []             # keep official months untouched
```
This doubles as the corruption guard: feeding it deliberately garbled values made it reject the whole
backfill and state why, while all 7 official months survived. **Any third-party series merged with an
official one must carry this check** — it is the only thing standing between a unit mismatch and a
public chart that is wrong by 10×.

#### Reconcile the backfill against an independent official aggregate
Beyond per-month equality, sum the merged monthly series and compare to the official ANNUAL figure:
implied 2025 total came within **0.06%** of the official annual PDF value, and the implied Jan–Feb
residual (18.8% of annual transactions) was plausible for two months. That catches scale and
missing-month errors that a 6-month overlap check cannot.

---

## Charting caveat — use 日均金额, not 月度总额
Monthly totals are contaminated by working-day count (Feb has fewer days; July had 23 working days vs 22).
A month-total line manufactures fake seasonality. **日均金额/日均笔数 is the honest usage-intensity metric.**
Keep 月度总额 available in tooltip, but don't make it the trend line.

Interpretive warnings worth putting in the 图注: CIPS growth ≠ de-dollarisation (CIPS also clears a large
volume of HK offshore RMB), and CIPS volume is not directly comparable to SWIFT RMB *share*.
