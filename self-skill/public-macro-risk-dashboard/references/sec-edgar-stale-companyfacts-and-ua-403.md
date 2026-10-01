# SEC EDGAR: reading fundamentals when `companyfacts` is stale or blocked

Companion to `references/free-macro-credit-data-sources.md` §③ (which covers the currency trap,
the stale-tag trap, and per-filer exceptions). **This file covers the two failure modes that make
SEC data look ABSENT when it is actually present** — both verified live 2026-08-31 on the
18-company AI-infrastructure FCF universe.

Both bugs share one dangerous property: **they surface as `None` / "no data", not as an error.**
So the natural (wrong) conclusion is "SEC doesn't have it" — and you report that to the user.

---

## ① The `_SEC_UA` trap — `www.sec.gov/Archives/` 403s while `data.sec.gov` works fine

SEC runs two hosts with **different User-Agent strictness**:

| host | UA requirement | symptom when the UA is wrong |
|---|---|---|
| `data.sec.gov` (companyfacts, submissions) | lenient | works — so the bug stays hidden |
| `www.sec.gov/Archives/` (raw filing files) | **must contain a real email** | **HTTP 403 on every call** |

Measured this session:

```
UA "EcoVolChecker research (contact: ANONYMIZED_EMAIL_ADDRESS_0_6)"   -> Archives HTTP 403
UA "Eco-Volatility-Checker ANONYMIZED_EMAIL_ADDRESS_0_5"     -> Archives HTTP 200
```

```python
_SEC_UA = {"User-Agent": "Eco-Volatility-Checker ANONYMIZED_EMAIL_ADDRESS_0_5"}   # email is MANDATORY
```

Why this is worse than a normal 403: helpers that read raw filings are usually wrapped in
`try/except: return None`. The 403 is swallowed, the caller sees `None`, and **any feature that
reads a filing's original document silently returns nothing** — with no log line and no failed
build. I reported "TSM 2025 年报 SEC 里没有" to Chao on the strength of such a `None`; the filing
had in fact existed since 2026-04-16.

**Rules**
- When adding ANY SEC reader, probe **both** hosts before trusting a negative result.
- Never infer "the data does not exist" from a bare `None` out of an `except`-wrapped fetch.
  Distinguish *fetch failed* from *data absent* — log which one it was.

---

## ② `companyfacts` lags badly for 20-F foreign private issuers

`companyfacts` is an **aggregation**, not the filings themselves, and it is not guaranteed current.

Measured 2026-08-31 — TSM (CIK 0001046179):

| source | newest annual period |
|---|---|
| `companyfacts` | **2024-12-31** (a full year stale) |
| actual 20-F on EDGAR | **2025-12-31**, filed 2026-04-16 |

The other 17 companies in the same universe were all at FY2025/FY2026, so a single laggard is easy
to misread as "that company just reports late". It didn't — the aggregator did.

### Fallback: read the filing's own XBRL instance

```
# 1) Is there an annual filing NEWER than what companyfacts returned?
https://data.sec.gov/submissions/CIK{cik:010d}.json      ->  filings.recent
    keep form in ("10-K", "20-F");  skip forms ending "/A" (amendments);
    take max reportDate  >  the fy companyfacts gave you

# 2) Read that filing's inline-XBRL instance
https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_without_dashes}/index.json
    -> choose the file whose name ends with "_htm.xml"
```

### Parsing gotchas (regex is enough; no lxml required)

- **No `xbrli:` prefix.** Contexts in these instances look like
  `<context id="c-1"><period><startDate>…</startDate><endDate>…</endDate></period></context>`.
  A regex written as `<xbrli:context …>` matches **nothing** and you get an empty dict —
  looking exactly like "no data". Cost me one debug cycle.
- **Skip any context containing `<segment>`** — those are per-segment/per-subsidiary breakdowns,
  not the consolidated figure.
- **Skip contexts where `startDate[:4] != endDate[:4]`** — kills partial and cumulative periods.

### ★ The currency trap, nastier here than in companyfacts

TSM reports the same tag under **both `twd` and `usd` in one filing**. Letting a dict overwrite
across units produced:

```
FCF = −11,999 億      # absurd: OCF 22,750 億 TWD  −  CapEx 40,561,400,000 USD
```

An obviously-wrong number, but one that would have rendered as a large red bar and might have
survived a casual glance. **Filter `unitRef` explicitly:**

```python
un = re.search(r'unitRef="([^"]+)"', attrs)
if not un or un.group(1).lower() != "usd":
    continue                       # never let another currency into the same series
```

Verified result after the fix:

```
TSM FY2025:  OCF 72.52B USD − CapEx 40.56B USD = FCF +32.0B USD
             (stale companyfacts value was FY2024 +26.5B)
universe total 327B -> 332B,  coverage 18/18
```

### Mark provenance on the record

When a row comes from the fallback path, say so in the data, e.g.
`src_note = "20-F XBRL 原文件(companyfacts 未收录该年)"`.
Future readers (and future you) need to know why one row took a different route.

---

## Reporting discipline when the user says "这些数据是不是过期了"

Chao asked "很多的数据都是 2024 年的了" about the AI-FCF chart. The instinct is to agree and start
fixing. **Measure first** — the actual distribution was:

```
FY2026: 3 companies      FY2025: 14 companies      FY2024: 1 company (TSM only)
```

So the honest answer was "只有一家过期，不是很多" plus the real root cause. Print the per-company
fiscal-year table before agreeing or disagreeing with a staleness complaint; the fix is usually
one filer, not the pipeline.

Related standing rule from the parent skill: fiscal years are NOT aligned across this universe
(MSFT 06-30, ORCL 05-31, NVDA 01-25, AVGO 11-02, MU 08-28), so **every cross-company chart must
print each company's own FY end** — never a single "2025" header.
