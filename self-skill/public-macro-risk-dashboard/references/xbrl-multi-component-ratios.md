# Multi-component XBRL ratios (leverage / interest coverage) — fiscal-year alignment

Companion to `scripts/probe_sec_xbrl_fundamentals.py`, which solves the **single-metric** case
(FCF = OCF − CapEx). Ratios that need 4–6 line items are a strictly harder problem and the naive
approach produces numbers that are wrong but look completely plausible. Verified live 2026-08 on the
18-name AI-infra universe.

---

## The trap: "latest value per tag" silently mixes fiscal years

Fetching each component independently and taking its most recent value gives you this:

```
MSFT  interest 2.9B@2024-06   EBIT 155.2B@2026-06     ← 2 years apart
ETN   debt 8.0B@2014-12       D&A 1.0B@2025-12        ← 11 years apart
MU    debt 3.0B@2012-08       EBIT 9.8B@2025-08       ← 13 years apart
DLR   debt 2.9B@2011-12       EBIT 0.7B@2025-12       ← 14 years apart
```

Every one of those returns a float. Every chart renders. `净债务/EBITDA` computed from FY2012 debt
and FY2026 EBITDA is **garbage that passes all element-count and non-null assertions.**

Cause: filers migrate tags over time. `LongTermDebtNoncurrent` may stop in 2011 while
`LongTermDebt` starts in 2012; `OperatingIncomeLoss` may stop when a filer restructures segments.
The tag still exists in `companyfacts` with a decade-old series.

## The fix: anchor on the latest fiscal year where ALL required components co-exist

Not "the latest FY of the anchor metric" (that's the single-metric rule) — the latest FY in the
**intersection** of the components that specific ratio needs. Each ratio gets its own anchor,
because coverage and leverage need different inputs.

```python
def series(f, tags, ns, dur):
    """Merge sibling tags into one annual series; earlier tags win, later ones fill gaps."""
    out = {}
    for t in tags:
        for k, v in (_pick(f, [t], ns=ns, duration=dur) or {}).items():
            out.setdefault(k, v)
    return out

# leverage needs EBIT + D&A + LTD + CASH ; coverage needs EBIT + D&A + INT
lev_fy = max((y for y in e_s if y in d_s and y in l_s and y in c_s), default=None)
cov_fy = max((y for y in e_s if y in d_s and y in i_s and i_s[y] > 0), default=None)
```

Note `series()` merges **all** sibling tags rather than first-hit — a filer that switched tags
mid-history needs both halves to produce an unbroken series. First-hit returns only one era.

### Result on the 18-name universe
| stage | 净债务/EBITDA | 利息保障 |
|---|---|---|
| single `InterestExpense`, latest-per-tag | — | 8/18 |
| widened tag lists, latest-per-tag | 16/18 | 17/18 — **but FYs mixed, values invalid** |
| widened tags + common-FY anchor | 7/18 | 4/18 — honest, and far too sparse |
| + issuer fallbacks below | **17/18** | **18/18** |

The 4th row is the goal: broad coverage where every number is internally FY-consistent.

## Still stale-guard the anchor

Common-FY alignment makes a ratio *self-consistent*; it does not make it *current*. DLR anchored to
**FY2011** — perfectly aligned, utterly useless. Reject anchors older than ~2 fiscal years and render
`n/a` with the reason, rather than displaying an aligned-but-ancient ratio.

## Issuer-specific fallbacks that closed the gaps

Found by regexing the filer's own tag namespace rather than guessing:
```python
d = (facts.get("facts") or {}).get(ns) or {}
[t for t in d if re.search(r"debt|borrow", t, re.I)]
```
- **TSM** — IFRS filer, `us-gaap` namespace absent entirely. Needs `DepreciationExpense`,
  `CashAndCashEquivalents`, `CurrentPortionOfLongtermBorrowings` /
  `NoncurrentPortionOfLongtermBorrowings`. This alone took TSM from all-missing to fully computed.
- **ETN** — `OperatingIncomeLoss` ends at FY2019. Falls back to
  `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`
  (pretax income, available @2025-12).
- **GEV** — debt lives only in `LongTermDebtAndCapitalLeaseObligations`, and **only in 10-Q filings**,
  so an annual-forms-only filter drops it. Coverage computes; leverage → `n/a`.
- **DLR** — genuinely does not report total debt in any recent 10-K. Only `SecuredDebt` /
  `UnsecuredDebt` fragments in 10-Qs; **summing those understates real debt**, so do not.
  → `n/a` with the reason stated. Two unavoidable `n/a`s beat 18 fabricated numbers.

## Sanity-check the ratios against the real world before shipping
Aligned arithmetic can still be wired wrong. Confirm the output tells a story you can defend:
NVDA net cash −0.02x / coverage 514x, versus CRWV 7.56x levered / coverage 2.1x — the AI-debt
divergence. If every name looks identical, or a known-levered name shows net cash, the mapping is wrong.

## API-shape gotchas in this codebase
- `_pick()` returns a **dict `{end_date: value}`**, not a tuple. `got[k][1]` raises `KeyError: 1`.
  Print `list(r.keys())` on any unfamiliar helper before writing the consuming loop.
- `AI_UNIVERSE` is a **list of `(group_name, [(ticker, name, cik), …])`**, not a dict.
  `.items()` raises `AttributeError`. Check the literal before iterating.
