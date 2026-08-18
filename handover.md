# Eco and Volatility Checker — Online Dashboard Handover

> **What this is**: The single source-of-truth handover doc for the daily macro-risk
> dashboard. It describes every metric shown online, how each is computed and rendered,
> which columns/tables/Notion-DBs back it, how often each updates, how KOL data is
> extracted — and the known **data-storage consistency issues** with a proposed fix.
>
> **Live dashboard**: https://curarpikt0000.github.io/Eco-and-Volatility-Checker/
> **Repo**: https://github.com/Curarpikt0000/Eco-and-Volatility-Checker
> **Timezone**: All schedules are Asia/Tokyo (JST, UTC+9).
> **Last updated**: 2026-08-18

---

## 0. TL;DR — the storage-consistency answer (read this first)

**Q: Can the cron job cover ALL of one KOL's lists every run?**

There are **two independent KOL pipelines** with different guarantees:

| Pipeline | Cron | Coverage guarantee |
|---|---|---|
| **Daily direction scan** | `eco-vol-01-daily-scan-report` (weekdays 11:00) | ✅ **Full.** Reads `kol_registry.json` where `active==true` — the *entire* active roster, count NOT hardcoded. New KOLs auto-included. Writes `kol_independent.json` + snapshot `kol/daily/YYYY-MM-DD.json`. |
| **1-year history backfill** | `eco-vol-kol-backfill-1yr` (every 30 min) | ⚠️ **Not idempotent.** Queue-driven (`backfill_queue.json`), marks each person done once. Does NOT re-scan when the roster gains a new KOL or a KOL gets a new search term. One-shot, not "cover-all-every-run". |

**Q: Can we unify the many JSONs into one file?**

Partly yes. KOL data is currently scattered across **4 locations, 311 files**:

| Location | Count | Role | Verdict |
|---|---|---|---|
| `data/kol_registry.json` | 1 | Roster SSOT (all fields, active flags) | ✅ Keep — already the SSOT |
| `data/kol/daily/*.json` | 207 | Per-day direction snapshots (time series) | ⚠️ Keep as time series, but see §7 for consolidation option |
| `data/kol/backfill/*.json` | 98 | Per-person 1yr history (one file each) | 🔴 **Should merge** into one `kol_backfill.json` |
| `data/kol_batch_1/2/3.json` | 3 | Old batch files | 🔴 **Dead files — zero code references, delete** |

The KOL example you raised is a **real problem, not hypothetical**. Full details + fix in **§7**.

---

## 1. System overview

**Purpose**: Daily macro-risk scanner. 18 market indicators (short/mid/long term) +
gold/silver COT + KOL opinion tracking + central-bank balance sheets + money supply +
Credit Impulse + Treasury stress + auctions + custody/maturity/country holdings + 13F +
politician disclosures. Feeds Notion time-series DBs + a Morandi-palette HTML dashboard +
a public GitHub copy + a daily Telegram brief.

**Stack**: Python venv (`.venv/`: requests/pandas/xlrd/openpyxl). Data sources are all
free/public (FRED API, CFTC Socrata, CNN F&G JSON, Treasury fiscaldata API, TIC, BOJ,
web-extract for anti-scrape sources). No paid/keyed commercial APIs.

**Key files**:
- `src/config.py` — SSOT for the 18 indicators, thresholds, signal rules, 7 sell triggers, Notion DB map
- `src/external_data.py` — all `fetch_*` functions (bottom panels + KOL logic)
- `src/dashboard.py` — Morandi HTML renderer (cards + charts + sidebar)
- `src/build_dashboard.py` — orchestrates fetch → generate → write
- `src/holdings_13f.py`, `src/oge_trump.py`, `src/djt_form4.py`, `src/senate_ptr.py`, `src/politician_disclosure.py` — institutional & politician holdings
- `src/report_writer.py` — Telegram brief + GitHub markdown copy

---

## 2. The 18 core indicators (cards + line-by-line interpretation + sell triggers)

Each indicator renders as **one card** (title / value / threshold / signal light / mini
line-chart / "how to read" footer). All 18 also appear in the **line-by-line
interpretation** section (uses AI daily read, falls back to `note`), and 7 of them drive
the **sell-trigger tracker**. **Cards / interpretation / triggers are one-to-one by design.**

| key | Group | Source | Sell trigger? | Trigger condition |
|---|---|---|---|---|
| `vix` | short | FRED | ✅ | VIX breaks & holds > 25 |
| `fear_greed` | short | web (CNN JSON) | ✅ | F&G drops from >75 to <50 |
| `aaii_bull_bear` | short | web | — | |
| `put_call` | short | web (CBOE) | — | |
| `bofa_fms_cash` | short | search (web_search) | — | |
| `sofr_iorb` | short | derived (SOFR−IORB) | — | |
| `margin_debt` | mid | web (FINRA) | ✅ | Margin Debt down 3 consecutive months |
| `margin_gdp` | mid | derived | — | |
| `ipo_count` | mid | web (Renaissance) | — | |
| `insider` | mid | web (GuruFocus) | ✅ | Insider Buy/Sell < 0.17 |
| `bofa_bull_bear` | mid | search | ✅ | BofA Bull&Bear > 8.0 |
| `hy_oas` | mid | FRED (BAMLH0A0HYM2) | ✅ | HY OAS spread > 4.5% |
| `ad_line` | mid | search (web_search) | ✅ | A/D Line top divergence |
| `buffett` | long | web (GuruFocus) | — | |
| `cape` | long | web (multpl) | — | |
| `yield_curve` | long | FRED (T10Y2Y) | — | |
| `lei` | long | web (Conference Board) | — | |
| `aaii_alloc` | long | web | — | |

**Source types explained**:
- `fred` — FRED API, keyed, most reliable (daily/weekly).
- `web` — anti-scrape web sources, script fetches; hard ones fall back to `manual_overrides.json` written by the cron in agent mode via `web_extract`.
- `search` — no fixed URL (BofA Bull&Bear, NYSE A/D divergence). The cron does daily `web_search` cross-validation. If not found → left blank, **never fabricated**.
- `derived` — computed from other series (SOFR−IORB, Margin/GDP).

**Sell discipline**: ≥3 triggers firing = start scaling out. Thresholds are static —
never adjusted to sentiment.

**A/D Line note** (the one that looked "missing"): it's a qualitative indicator (value =
"top divergence", no number, no line chart), so its card looks visually plain among the
numeric cards — but it IS present in cards, interpretation, AND triggers.

---

## 3. Bottom panels (beyond the 18 cards)

Rendered in this order at the bottom of the dashboard. Each `fetch_*` lives in
`src/external_data.py` unless noted.

| Panel | fetch function | Source | Update freq |
|---|---|---|---|
| Gold/Silver COT | `fetchers/cot.py` | CFTC Socrata (publicreporting.cftc.gov) | Weekly (Fri release) |
| Weekly KOL stance changes | `kol_weekly_changes` / `kol_stance_changes_grouped` | Eco's own daily snapshots | Daily |
| Liquidity points | `fetch_liquidity_points` | Economic-Dashboard sheet (Fed reserves/RRP/TGA/yields) | Daily |
| 3 central-bank balance sheets (US/JP/CN) | `fetch_cb_balance_sheets` | Econ-Dashboard B7/B6/B5 (Fed weekly / BoJ 旬報 / PBoC monthly) | Fed weekly, BoJ ~10-day, PBoC monthly |
| Money supply M0/M1/M2 (3 countries) | `fetch_money_supply` | FRED + overrides | Monthly |
| M2 10-year lines | `fetch_m2_history` | FRED | Monthly |
| Credit Impulse (US/CN/EU/JP) | `fetch_credit_impulse` | BIS via FRED, quarterly + 2008 long history | Quarterly |
| Treasury stress 4-panel | `fetch_treasury_stress_panels` | FRED (7 series, 3yr) | Daily |
| OFR FSI (total + 5 official components) | `fetch_ofr_fsi` | OFR official CSV | Daily |
| Treasury auction timeline | `fetch_treasury_auctions` | TreasuryDirect / fiscaldata | Per-auction |
| Foreign official custody UST | `fetch_foreign_custody_ust` | FRED WMTSECL1 (weekly) | Weekly |
| Custody acceleration | `fetch_custody_acceleration` | FRED WMTSECL1 derived | Weekly |
| **Maturing Treasury (再融资墙, NEW)** | `fetch_maturing_treasury` | US Treasury MSPD table_3 | Monthly |
| Country UST holdings (JP/CN 10yr) | `fetch_country_ust_holdings` | TIC MFH | Monthly |
| 13F institutional holdings | `holdings_13f.py` | SEC EDGAR | Quarterly (13F filing) |
| Politician disclosures (5 cards) | `politician_disclosure.py` + `oge_trump.py` + `djt_form4.py` + `senate_ptr.py` | House Clerk PTR / OGE 278 / SEC Form4 / Senate EFD | Per-filing (Form4 daily) |

### 3.1 Maturing Treasury panel (newest, added 2026-08-18)
- **Metric**: total marketable Treasury debt maturing within 1 year (rolls over / "再融资墙").
- **Method**: MSPD table_3 per-security detail → for each monthly `record_date`, sum
  `outstanding_amt` of all securities with `0 ≤ (maturity_date − record_date) ≤ 366 days`.
- **Unit**: source is millions USD → `/1e6` → trillions.
- **Charts**: two — recent 2yr + full cycle 2001→now (307 monthly points).
- **Current**: ~$14.52T as of 2026-07.
- **Caveat (labeled on chart)**: total = Fed SOMA + private; Fed holdings NOT separately netted out.
- **⚠️ Known bug (found in code review, see §8)**: `_pull_year` `except: break` can cache
  partial data on mid-pagination network failure. Fix pending.
- **Cache**: `data/maturing_treasury.json`, incremental (skips fully-cached past years).

---

## 4. Notion tables / columns

10 Notion DBs (IDs in `config.py NOTION_DB`, values in `.env`):

| DB key | Purpose | Row title | Key columns |
|---|---|---|---|
| `indicators` | Daily 18-indicator time series | Date | one number col per indicator + signal light |
| `cot` | Gold/silver COT time series | Date | commercial long/short/net/WoW/surge flag |
| `report` | Daily scan report | Date | composite signal / trigger count / conclusion |
| `weekly` | Weekly summary | Week | stance changes highlights |
| `holdings` | 13F institutional | "机构-期" (inst-period) | issuer holdings + change (🆕/▲/▼/❌/→) |
| `custody` | Foreign custody UST | Date | value / WoW delta / acceleration |
| `auctions` | Treasury auctions | Date | auction results timeline |
| `money_supply` | M0/M1/M2 3 countries | Date | per-country per-aggregate |
| `stress` | Treasury stress panels | Date | 7 stress series |
| `ofr` | OFR FSI | Date | total + 5 components (信用/股票估值/融资/安全资产/波动性) |

**Idempotency rule (critical, see AGENTS.md)**: `notion_writer.upsert` PATCHes full props.
`skip_none=True` on existing rows — never overwrites an existing real value with a null
when a source fails that day. Any "rerun/daily-write" logic MUST check: does a fetch
failure overwrite-to-empty or keep-old-truth?

---

## 5. Update frequency (active crons)

Only 4 crons are enabled for THIS project (all JST):

| Cron | Schedule | What it does |
|---|---|---|
| `eco-vol-01-daily-scan-report` | Weekdays 11:00 | Fetch all data + KOL scan + liquidity + AI analysis → write 10 Notion DBs + report page + dashboard + GitHub copy + push → Telegram brief. (11:00 waits for KOL/Econ-Dashboard 09:00 data.) |
| `eco-vol-weekly-report` | Sat 11:00 | Weekly rollup → weekly DB + GitHub + Telegram weekly (stance-change focus) |
| `eco-vol-selfheal-watchdog` | Hourly :20 | no_agent watchdog, silent unless broken |
| `eco-vol-kol-backfill-1yr` | Every 30 min | Take 5 un-done KOLs from queue, web_search 1yr history, write per-person file, commit (deliver=local, no spam) |

Panel data freshness varies by source (see §3 table): FRED daily, custody weekly, money
supply/Credit Impulse monthly/quarterly, 13F quarterly. The dashboard shows each panel's
own `as_of` date.

---

## 6. KOL extraction method

**Roster (SSOT)**: `data/kol_registry.json` — dict with `_count`, `_last_updated`, and
`kols` list. Each KOL has `id`, `display_name`, `sector`, `domain`, `search_terms`,
`active`, `list_num`, `institution` (industry standing), `bio`. **Add-only** — never
delete; deletion requires explicit user confirmation; `list_num` only increases.

**Daily extraction** (`eco-vol-01-daily-scan-report`):
1. Read roster, filter `active==true` (count NOT hardcoded — new KOLs auto-included).
2. For each, `web_search` with their `search_terms` → LLM extracts direction/targets/comments.
3. Write `kol_independent.json` (today's full snapshot).
4. `save_kol_daily_snapshot()` → `data/kol/daily/YYYY-MM-DD.json` (git-tracked, for weekly diff).
5. `kol_weekly_changes()` compares this-week-latest vs last-week-last snapshot → stance changes.

**Fully independent**: Eco does NOT read the other (Economy-KOL) agent's Notion DB.
`fetch_kol_recent`/`kol_stance_changes` are **deprecated**; the live source is Eco's own
daily snapshots.

**Special KOL classes**: alt-prediction KOLs (domain=预测/sector=Alternative, e.g. psychics/
astrologers) are scanned via their `search_terms` as sentiment signals, NOT classified by
tradeable direction, and not held to the same standard as analyst KOLs.

**web_search backend note**: default `web.search_backend=ddgs` (free, no key). If SearXNG
returns empty it's usually upstream engines rate-limited/CAPTCHA'd, not "data doesn't
exist" — never conclude from empty results; the daily cron re-runs and fills.

**1-year backfill** (`eco-vol-kol-backfill-1yr`): queue-driven from `backfill_queue.json`;
per-person history → `data/kol/backfill/<id>.json`; marks done once. See §7 for the
consistency gap.

---

## 7. 🔴 Storage-consistency issues (the core of your question)

### 7.1 Problem: KOL data scattered across 4 locations / 311 files
See §0 table. Real issues:
1. **`kol_batch_1/2/3.json` are dead** — zero code references. Remnants. **Delete.**
2. **`kol/backfill/*.json` = 98 separate files** — no reason to be per-file. A single
   `kol_backfill.json` as `{id: {history, backfill_date, source_method, count}}` is cleaner,
   atomically updatable, and avoids "which file holds whom" ambiguity.
3. **`kol/daily/*.json` = 207 files** — this is legitimately a time series (weekly diff needs
   history accumulation). Merging into one file would grow unbounded and lose cheap
   incremental append. **Recommend: keep per-day, but document it clearly as an append-only
   time-series log, not scattered state.**

### 7.2 Problem: backfill is not idempotent / does not "cover all lists every run"
- Queue is one-shot. If the roster gains a KOL, or a KOL gets a new `search_term`, the
  backfill does NOT re-scan them.
- **Fix**: make backfill roster-driven like the daily scan — each run, diff roster's active
  KOLs against `kol_backfill.json` keys + check `backfill_date` staleness (e.g. >90 days →
  re-queue). This guarantees "every active KOL's full history is eventually covered and
  refreshed", matching your requirement.

### 7.3 Same problem elsewhere in the project
- `data/ai_analysis_2026-08-*.json` — one file per day at repo root (6 already). Should live
  under `data/ai_analysis/` or be a single append log.
- `data/probe_13f_result.json` — one-shot probe remnant. Archive/remove.
- Two override files (`manual_overrides.json`, `money_supply_override.json`) — intentional,
  keep, but document as the authoritative manual-override layer.

### 7.4 Recommended target layout (proposal — needs your approval before executing)
```
data/
  registry/        kol_registry.json         (roster SSOT — unchanged)
  kol/
    daily/         YYYY-MM-DD.json           (time series — unchanged, documented as append-log)
    backfill.json  {id: {...}}               (MERGE the 98 per-person files here)
  overrides/       manual_overrides.json, money_supply_override.json
  ai_analysis/     YYYY-MM-DD.json           (move from repo root)
  panels/          maturing_treasury.json, holdings_13f.json, ... (panel caches)
  (delete)         kol_batch_1/2/3.json, probe_13f_result.json
```
**Discipline**: any migration is add-only + verify-after-write + no data loss. Pilot the
backfill merge on a copy first, verify all 98 persons' history survives, then switch the
reader, then delete the per-file dir.

---

## 8. Known open issues / tech debt

| Item | Severity | Status |
|---|---|---|
| `fetch_maturing_treasury._pull_year` `except: break` caches partial data on mid-pagination failure, `>=11 months` skip makes it permanent | 🔴 Critical (data integrity) | Fix pending (code review 2026-08-18) |
| KOL backfill not idempotent / not roster-driven | 🟡 | §7.2 fix proposed |
| Dead `kol_batch_*.json` + scattered per-file storage | 🟡 | §7 cleanup proposed |
| P1-3: network failure returns empty silently, downstream can't tell "API failed" vs "no data" | 🟡 | Backlog (add error flag) |
| P2-1: backfill report trigger-count has no backfill marker | 🟢 | Backlog |
| P3-1: `_clear_page_blocks` only deletes first 100 blocks | 🟢 | Backlog |
| P3-3: `_latest_row` sorts by title string (depends on zero-padded ISO) | 🟢 | Backlog |

---

## 9. Discipline (non-negotiable)
- **Never fabricate numbers.** Can't fetch → mark status / "not found / lagged to [date]".
  Backfill can't find reliable text → drop or honestly mark "no trackable public statement".
- **KOL roster add-only**; deletion requires explicit user confirmation.
- **Static thresholds** — never adjust to sentiment.
- **Write-then-read-back verify**; `.env` never in git; red-line scan before commit;
  commit `--no-gpg-sign` to Curarpikt0000 public repo.
- **Public repo**: strip all uberinternal URLs before pushing (this dashboard is pure
  public macro data, safe to publish; internal URLs never go to personal GitHub).
