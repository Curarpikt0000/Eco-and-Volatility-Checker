# Dashboard chart legibility polish (SVG line charts in dashboard.py)

Session-tested techniques for the Eco-and-Volatility-Checker trader-screen dashboard.
All live in `src/dashboard.py`. Chao repeatedly asks for these once a chart exists —
treat them as the default finish for any new multi-line panel.

## 1. Data-source codes → clickable hyperlinks

Chao: "所有图表的数据源能不能直接换成一个链接，而不是给我写一个指标代码？在指标代码上加超链接。"

Bare indicator codes (`BAMLH0A0HYM2`, `DGS10`, `THREEFYTP10`, `WMTSECL1`, …) shown in
the `数据源：…` footer are opaque. Make them clickable so a click jumps to the official
source page for verification.

Build ONE shared helper (not per-panel logic), placed right after `_esc()`:

```python
import re
_SRC_LINK_SPECIAL = {          # non-FRED / needs a dedicated landing page
    "OFR FSI": "https://www.financialresearch.gov/financial-stress-index/",
    "Office of Financial Research": "https://www.financialresearch.gov/financial-stress-index/",
    "^MOVE": "https://finance.yahoo.com/quote/%5EMOVE/",
    "Yahoo Finance": "https://finance.yahoo.com/quote/%5EMOVE/",
    "TIC": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
    "fiscaldata.treasury.gov": "https://fiscaldata.treasury.gov/",
}
_FRED_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")
_FRED_IDS = {"DGS10","DGS2","T10Y2Y","THREEFYTP10","BAMLC0A0CM","BAMLH0A0HYM2",
             "WMTSECL1","DTWEXBGS","VIXCLS","DFII10","T10YIE","WALCL","WRESBAL",
             "RRPONTSYD","WTREGEN","QBPBSTAS"}   # WHITELIST — avoids clobbering US/JP/MS/OAS/IG

def _linkify_sources(text):
    if text is None: return ""
    esc = html.escape(str(text), quote=True)
    for kw, url in _SRC_LINK_SPECIAL.items():          # special keywords FIRST
        kw_esc = html.escape(kw, quote=True)
        if kw_esc in esc and f'>{kw_esc}<' not in esc:
            esc = esc.replace(kw_esc,
                f'<a class="src-lnk" href="{url}" target="_blank" rel="noopener">{kw_esc}</a>', 1)
    def _repl(m):                                       # then FRED IDs (whitelist only)
        sid = m.group(1)
        return (f'<a class="src-lnk" href="https://fred.stlouisfed.org/series/{sid}" '
                f'target="_blank" rel="noopener">{sid}</a>') if sid in _FRED_IDS else sid
    return _FRED_ID_RE.sub(_repl, esc)
```

Then swap every `数据源：{_esc(src)}` → `数据源：{_linkify_sources(src)}` across ALL panels
(stress panels, custody, country-UST, central-bank, M-supply, credit-impulse, footer).
For hard-coded prose footers (fiscaldata / WMTSECL1 lines) wrap the keyword in `<a>` by hand.
CSS: `.src-lnk { color:#7fa0b8; text-decoration:underline dotted; text-underline-offset:2px; }`.

**Pitfalls**
- The FRED regex WILL match plain uppercase words (US, JP, MS, OAS, IG, BofA). The whitelist
  set is what prevents false links — never drop it and never widen it to "any all-caps token".
- `OFR FSI` may not be a contiguous substring (real source string was
  `OFR (Office of Financial Research, US Treasury) FSI 官方 CSV`) — add the longer
  `"Office of Financial Research"` key so the linkify actually fires.
- Verify programmatically after build: regex-count `<a class="src-lnk"` in the generated
  index.html AND in docs/index.html (the Pages copy), and assert `<a>`/`</a>` counts match
  (no broken/nested tags). Vision backend is often down — rely on this DOM check.

## 2. Per-line point annotations: ▲max / ▼min / current / median

Chao: "你至少给我标注一下最高点、最低点、当前点，以及中值，否则根本不知道现在的具体点位。"

In the multi-line SVG (`_stress_panel_svg`), for EACH series compute
`{cur, hi, lo, med}` (median inline, no statistics import) and draw:
- filled dot + `▲{hi:.2f}` at the max point; filled dot + `▼{lo:.2f}` at the min point
  (anchor = start/end/middle depending on x, so labels don't clip the edges);
- a faint per-axis **median dashed line** (`stroke-dasharray="2,4"` opacity .5) — NOT a shared zero;
- the latest point as a white-stroked filled circle + `当前 {cur:.2f}`;
- a right-side legend stat line: `现{cur} 高{hi} 低{lo} 中{med}` in the series color.

## 3. Dual-axis charts: NO shared zero line — use per-axis median instead

Chao asked "零轴你没写呀？" on a dual-axis chart (left = 10Y-2Y spread, right = HY OAS).
A single horizontal zero line is WRONG on a dual-axis panel because 0 means different pixel
positions / different meanings for the two axes — it misleads. The right answer is the
per-line median dashed line + the four numeric readouts above. Only draw a real zero line on
SINGLE-axis panels where 0 is meaningful (e.g. OFR FSI where 0 = 历史正常水平).

## 4. Layout math so stat text never overflows

Legend stat strings with 3-digit values (e.g. `现137.26 高… 中…`) are wide. Widen the SVG
viewBox `w` (940→1000) AND the right margin `mr` (150→175) together, keep the plot area from
shrinking, and put the stat text start at `x = w-mr+8`. After build, assert no `<text>` element's
`x + estimated_width` exceeds `w` for every panel (CJK ≈ 9px, ASCII ≈ 5px per char).

## 5. OFR FSI factual reference (avoid the "5 vs 6" mistake)

The OFR Financial Stress Index (US Treasury, financialresearch.gov) is built from ~33 global
variables aggregated into **5 official component categories**: Credit, Equity valuation,
Funding, Safe assets, Volatility. Total index = sum of the 5. Baseline 0 = historical normal;
>0 承压, <0 平静 (no fixed threshold line; crises hit +15~+20, e.g. 2008/2020).
CSV columns: `Date, OFR FSI, Credit, Equity valuation, Safe assets, Funding, Volatility`.
Original fetcher only pulled 4 of the 5 components (dropped "Equity valuation") → the chart
showed total + 4 lines instead of total + 5. When wiring `fetch_ofr_fsi`, take ALL 5, and
adding a component to an existing Notion DB needs the DB property created FIRST (a PATCH to a
nonexistent Notion property errors).
