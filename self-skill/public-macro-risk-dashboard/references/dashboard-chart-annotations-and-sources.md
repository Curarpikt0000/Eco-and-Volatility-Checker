# Dashboard chart legibility: source hyperlinks, per-line stat annotations, official-index components

Durable techniques for the Eco-and-Volatility-Checker HTML dashboard (`src/dashboard.py`),
distilled from Chao's 2026-08 legibility requests. All apply to the hand-rolled SVG line-chart
renderers (`_stress_panel_svg`, custody/country/credit-impulse charts).

## 1. Make data-source indicator codes clickable (Chao's standing preference)
Chao does NOT want bare indicator codes like `BAMLH0A0HYM2` / `DGS10` / `THREEFYTP10` shown as
inert text — he wants each code to be a **clickable hyperlink to its official source page** so he
can one-click verify. Implement ONE helper reused across every chart, not per-panel string edits.

Pattern (`_linkify_sources(text)` in dashboard.py):
- HTML-escape first (`html.escape(str(text), quote=True)`), THEN inject `<a>` tags.
- Special-keyword map handled FIRST (before the FRED regex, so it can't eat them):
  `OFR FSI` / `Office of Financial Research` → financialresearch.gov/financial-stress-index/;
  `^MOVE` and `Yahoo Finance` → the Yahoo `%5EMOVE` quote page; `TIC` → treasury.gov TIC page;
  `fiscaldata.treasury.gov` → fiscaldata.treasury.gov.
- FRED series IDs via regex `\b([A-Z][A-Z0-9]{2,15})\b` but gated by an explicit **whitelist set**
  (`DGS10, DGS2, T10Y2Y, THREEFYTP10, BAMLC0A0CM, BAMLH0A0HYM2, WMTSECL1, …`) → link to
  `https://fred.stlouisfed.org/series/<ID>`. The whitelist is mandatory: a raw uppercase-word regex
  otherwise false-links ordinary abbreviations (US, JP, MS, OAS, IG, BofA).
- CSS class `.src-lnk` (morandi light-blue dotted underline, solid on hover) — subtle, not garish.
- Fixed-prose source lines (e.g. the auction/custody footnote sentences) are NOT wrapped through the
  helper (they contain `<b>` tags) — hand-wrap only the keyword in an `<a>` there.
- Swap every `数据源：{_esc(src)}` / `源：{_esc(...)}` render point to `_linkify_sources(...)`.
- Verify: regex-count `<a class="src-lnk"` in the generated HTML == count of `</a>`; assert no
  `href="[^"]*<a ` nesting breakage; confirm on the pushed raw GitHub file too.

## 2. Dual-axis charts: annotate每条线 high / low / current / median (NOT a shared zero axis)
Chao's rule: on a **dual-axis** chart (e.g. 10Y-2Y spread on left, HY OAS on right) a single shared
"zero axis" is misleading — 0 means different things per axis. He does NOT want the zero line there;
he wants, for EACH line, the concrete point levels so he can read "where are we now vs history":
- ▲ highest point + ▼ lowest point (small filled dot + value), placed with edge-aware text-anchor
  (`start` near left margin, `end` near right, else `middle`) so labels don't clip.
- Current point = white-stroked filled circle + "当前 X.XX".
- A faint dashed **median line** on that series' own axis (replaces the zero line's role).
- Right-side legend gains a compact numeric summary line per series:
  `现X.XX 高X.XX 低X.XX 中X.XX` (use `现/高/低/中` short labels — full `当前 · 高 · 低 · 中`
  with ` · ` separators overflows the legend gutter on 3-digit values like MOVE ~137).
- Single-axis panels (OFR FSI) DO keep the highlighted zero line ("0 = 历史正常").

## 3. Legend-gutter overflow is the recurring layout trap — widen the viewBox, don't shrink font blindly
Adding the per-line stat summary made legend text overrun `viewBox` width. Fix that stuck:
- widen SVG `w` (940 → 1000) AND the right margin `mr` (150 → 175) together so the plot area is
  unchanged but the legend gutter grows;
- start the stat text at `x=w-mr+8` (aligned with the legend swatch), not `+30`.
- **Verification without vision** (vision backend was down): compute each `<text>` element's estimated
  right edge = x + Σ(9px per CJK char via `east_asian_width in 'WF'`, else 5px) and assert `≤ viewBox
  width + margin`. This catches overflow deterministically. Screenshot + `MEDIA:` path to let Chao
  eyeball it, but don't block on the vision tool.

## 4. Official composite indices — render ALL official sub-components, verify the count
When a chart shows an official composite index, render exactly the official sub-component set.
OFR FSI = **5 components** (Credit, Equity valuation, Funding, Safe assets, Volatility) + the total.
An earlier `fetch_ofr_fsi` pulled only 4 (dropped "Equity valuation") — Chao noticed "6 vs 5". The CSV
header is `Date, OFR FSI, Credit, Equity valuation, Safe assets, Funding, Volatility`. Fix = add the
missing key to the `want` dict + a color, update the panel note (4→5 components), AND add the Notion
number column to the existing DB **before** writing (a Notion PATCH to a nonexistent property errors).
General rule: cross-check any composite chart's line count against the source's official definition.

OFR FSI reference facts (for the note/explanation): editor = US Treasury OFR; 33 global market
variables → 5 category components; **0 = historical-normal baseline**, positive = above-normal stress,
negative = calm; no fixed threshold line (relative to history); crisis peaks +15~+20 (2008/2020).
Components decompose the total → "which market is producing stress" (credit vs funding vs volatility).

## 5. `days`-since bug to watch for (KOL weekly-change payload)
`kol_stance_changes_grouped()` returned `days: 207` while `since` was 4 days prior — a date-diff
parse bug in the "距今 N 天" calc. Doesn't affect the转向 comparison itself (which correctly uses
本周最新 snapshot vs 上周最后 snapshot) but corrupts the displayed day count. Flag/fix if touched.
