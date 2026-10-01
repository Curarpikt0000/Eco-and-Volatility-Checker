# Political / power-circle holdings — verified fetchable sources (2026-08)

All URLs curl-verified this session. "Smart money / power circle holdings" tracking for the 政要持仓披露 block.
Built: `src/politician_disclosure.py` orchestrates ALL FOUR sources (2026-08, all verified & wired into the daily cron + dashboard 政要 block): House PTR (`politician_disclosure` fetch_politician — Pelosi/Crenshaw), Trump OGE 278-T逐笔+Annual (`src/oge_trump.py`), Trump DJT Form 4 (`src/djt_form4.py`), Senate PTR (`src/senate_ptr.py` — Tuberville). `fetch_all()` merges into `data/politician_disclosure.json`; dashboard `_holdings_political` renders 5 cards.

## 1. US House members — Periodic Transaction Reports (PTR) — BUILT
- Index ZIP: `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.ZIP` (200; 2024/2025/2026 all live)
- Inside: tab-delimited `{YEAR}FD.txt`, 9 cols `Prefix\tLast\tFirst\tSuffix\tFilingType\tStateDst\tYear\tFilingDate\tDocID`. `FilingType=='P'` = PTR.
- ★PDF path depends on type: PTR → `.../public_disc/ptr-pdfs/{Year}/{DocID}.pdf`; all others → `.../public_disc/financial-pdfs/{year}/{DocID}.pdf`. Wrong dir = 404. `{Year}` = index Year field (report year), not FilingDate year.
- PTRs have NO companion XML; PDFs are digital → `pdfplumber` (pip into venv), no OCR.
- Filter by `Last` + `StateDst` (Pelosi CA11, Crenshaw TX02) — index uses legal first names ("Daniel" not "Dan").
- Trade regex: line1 `(dir P/S/E)(txn date)(notice date)($lo - $hi?)`; ticker `(TICKER)` on line1/continuation; ETFs may lack ticker → fall back to asset name, ticker=None (don't fabricate).
- Verified: Pelosi 15 trades (2026-05-29 买 INTC), Crenshaw 8 (2026-06-01 卖 GOOG/AMZN/AAPL).

## 2. US Senate — efdsearch — BUILT (src/senate_ptr.py, Tuberville)
- Session flow (one `requests.Session()`): (a) `GET /search/home/` → csrftoken cookie + page `csrfmiddlewaretoken`; (b) `POST /search/home/` with `prohibition_agreement=1`+csrf (accept terms); (c) ★**`GET /search/` to establish the referer chain — MISSING THIS STEP is what returns 503 on the data endpoint (it was NOT Akamai maintenance as previously assumed).** (d) `POST /search/report/data/` with `report_types=[11]` (PTR) + csrf + headers `X-Requested-With: XMLHttpRequest` + `X-CSRFToken` → JSON DataTables rows; (e) `GET /search/view/ptr/{uuid}/` → HTML detail table.
- CSRF dual-channel: form field (from page) AND header `X-CSRFToken` (from cookie), values must match. Referer header `…/search/` on the data POST.
- PTR detail = HTML table `# | Date | Owner | Ticker | Asset | AssetType | Type | Amount` → regex/BeautifulSoup, no JS. ★Senate data CARRIES A TICKER (TSCO/MSFT/AAPL/GOOGL) — higher quality than the House PDF (which often lacks tickers).
- Verified: 22 Tuberville PTRs, per-trade parse works (e.g. 10/07/2025 卖 PEP/MSFT/AAPL/GOOGL). Extensible via `SENATE_TARGETS` (只增不减).
- Amount is a BAND only; no share count.

## 3. Trump OGE Form 278 — BUILT (src/oge_trump.py) — BOTH 278-T逐笔 AND 278ANNUAL
- Undocumented JSON REST index: `https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest?draw=1&start=0&length=20000` → `{recordsTotal, data:[{name,agency,title,level,docDate, type:<a href=...pdf>}]}` (~16.6k records, ~7MB). Occasionally 400 → exponential-backoff retry.
- ★**API is CLIENT-SIDE filtered — the server IGNORES search params and returns the FULL index.** Pull `length=20000`, then grep `name` for trump LOCALLY (25 Trump docs). Each row's `type` field embeds `<a href='…/PAS+Index/<docid>/$FILE/….pdf'>` = DIRECT PDF (no Request-form for Trump's own filings).
- ★★**CORRECTION to the old skill claim: Trump files 278-T PERIODIC TRANSACTION REPORTS = genuine per-TRADE flow, NOT only an annual snapshot.** Two label types:
  - `278 Transaction` → 278-T逐笔 PDF (~300 trades each; multiple filings across 2025→2026). Row = `# desc sale/purchase date Yes $lo-$hi`. **Parse pitfalls (pdfplumber):** OCR noise (purchase→lourchaso; amounts `$15 001 • $50,000` internal-space+bullet; company names garble `Gonoral MIiis`) → snap amount boundaries to standard OGE bands; ★txn_date = FIRST date AFTER the buy/sell keyword, NOT first date in line (bond `… DUE 10/01/35` maturity dates hijack it). NO ticker (asset description name only). Verified 315 trades from one 278-T.
  - `Annual (2026)` → `Donald-J-Trump-2026-278ANNUAL.pdf` (200, ~8.3MB, ~900pp, DIGITAL). Part 6 Other Assets and Income → per-asset value BANDS, verified 6,181 rows (CARNIVAL/COREWEAVE/COTY/NETFLIX…).
- So the Trump card carries BOTH 逐笔交易 (278-T) AND 年度持仓快照 (Annual). Candidate-period 278e = OGE Form 201 request-only (no direct link).

## 4. DJT (Trump Media) SEC Form 4 (per-trade, Trump-Media stake) — BUILT (src/djt_form4.py)
- ★Filter by Trump's OWN reporting-owner CIK **947033** (`data.sec.gov/submissions/CIK0000947033.json`) — this owner-feed is cleaner than filtering issuer Trump Media CIK 1849635's ~79 filings by name. Returns 18 Form 4s.
- form==4 (exact) → each `Archives/edgar/data/947033/<accn_nodash>/primary_doc.xml` (exclude `xslF345…` render versions). Parse (ElementTree, tolerate `<tag><value>X</value></tag>` and `<tag>X</tag>`): issuerName/issuerTradingSymbol(=DJT)/rptOwnerName, then per `nonDerivativeTransaction`+`derivativeTransaction`: transactionDate, transactionCode (**P买/S卖/G赠与/A授予/F扣税/M行权/C转换/D处置**), transactionShares, pricePerShare, acquiredDisposedCode.
- Verified: 2024-12 gift of 114.75M DJT shares into the Donald J. Trump Revocable Trust (code G), 2024-04 grant of 36M earnout shares (code A). Carries a REAL ticker (DJT). Daily cron scans for new accessions.
- UA must have deliverable email (`…@example.com` OK; `…@<owner>.github.io` → 403) + no parenthetical text; limit <10 req/s.

## Dead sources (do not re-probe)
housestockwatcher / senatestockwatcher S3 buckets → 403; Capitol Trades BFF → 503; Quiver → 404 + Cloudflare.
