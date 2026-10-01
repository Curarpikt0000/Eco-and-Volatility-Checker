# Eastmoney native-API US-stock data + replacing unsourced qualitative indicators

Two reusable techniques from the Eco-and-Volatility-Checker session where Chao
questioned the "NYSE A/D Line" indicator ("no chart, no numbers — how can it be
'triggered'?").

## 1. Free US-stock daily K-line when akshare is blocked → Eastmoney push2his raw API

Problem: needed SPY/RSP (and any US stock/ETF) daily history for free, no key.
- **Stooq** ✗ whole site behind JS proof-of-work anti-bot wall (curl/requests get JS challenge).
- **Yahoo Finance** ✗ A/D symbols (`^ADLINE`/`^NYAD`/`^ADD`) all 404; historical CSV needs Gold sub.
- **FRED** ✗ no NYSE advancing/declining-issues series.
- **akshare** `stock_us_hist` / `stock_us_spot_em` ✗ **the akshare wrapper's request is blocked
  by Eastmoney** (`Connection aborted / RemoteDisconnected`) — but **the raw Eastmoney API
  itself is reachable**. Don't conclude "akshare is broken / data doesn't exist" — hit the
  native endpoint directly.

**Working path — Eastmoney (东方财富) native endpoints, free, no key:**

Symbol lookup (find the `secid` = `market.code`):
```
https://searchapi.eastmoney.com/api/suggest/get
  ?input=SPY&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=10
```
US market prefixes: `105`=NASDAQ, `106`=NYSE, `107`=AMEX/Arca.
Confirmed: **SPY = `107.SPY`** (标普500ETF-SPDR), **RSP = `107.RSP`** (平均加权指数ETF, equal-weight).

Daily K-line history:
```
https://push2his.eastmoney.com/api/qt/stock/kline/get
  ?secid=107.SPY
  &fields1=f1,f2,f3,f4,f5,f6
  &fields2=f51,f52,f53,f54,f55,f56,f57,f58
  &klt=101&fqt=1&beg=20180101&end=<YYYYMMDD>
```
Returns `data.klines`: list of `"date,open,close,high,low,vol,amount,pct"`. `close` = index 2.
Verified: SPY + RSP each **2167 daily bars 2018-01-02 → present**.

Also useful (returns full US universe as JSON, ~13.7k rows, quick reachability probe):
```
https://push2.eastmoney.com/api/qt/clist/get
  ?pn=1&pz=5&fs=m:105,m:106,m:107&fields=f12,f14
```

**Headers that help:** `User-Agent: Mozilla/5.0 (...)` + `Referer: https://quote.eastmoney.com/`,
via a `requests.Session()`.

### Rate-limit reality (the real gotcha)
Eastmoney **rate-limits a VM's egress IP on BURST**: probing works the first couple of times,
then a run of connected requests gets the IP soft-banned (curl AND requests return empty for
tens of minutes → possibly hours). It is **not** permanently blocked.
- A **low-frequency daily cron** pulls fine (it doesn't burst).
- **Do not debug it with repeated back-to-back calls** — you'll ban yourself for the session.
- Space the two K-line calls (SPY then RSP) with a `sleep(1)`; use 6-attempt increasing-backoff
  retries inside the fetcher.

### Cache-fallback discipline (matches the project's "never overwrite truth with empty" rule)
The fetcher must:
1. On success, write the full result to `data/<indicator>.json`.
2. On fetch failure, **read that cache and return it with `stale=True`** — never return
   "未获取" that would blank an existing real value. Render layer shows a "(缓存, 源限流)" note.
3. If no cache exists yet, return status `未获取`; the render + downstream must **degrade
   gracefully** (show "数据抓取中", not an exception) so a rate-limited source never breaks the
   whole dashboard build.
This is the same pattern as `manual_overrides` fallback / `skip_none` upsert elsewhere in the repo.

### moomoo OpenD — do NOT go down this road for a headless VM
Chao suggested moomoo OpenD (futu-api gateway). Findings:
- `futu-api` pip SDK installs fine, BUT the **OpenD gateway binary is 400M+** → over Chao's
  single-file size red-line, not worth transferring/hosting.
- moomoo's download page generates the `.tar.gz` link via heavy JS + a market-select dialog;
  the direct link is **not** exposed in static DOM (wasted many browser rounds trying to scrape it).
- OpenD also needs the user's moomoo login + market quote entitlement + likely an SMS code —
  can't be done unattended.
- Verdict: **Eastmoney native API + cache fallback beats OpenD** for this use case. Don't
  re-attempt OpenD unless the user explicitly wants live L2/entitled data and will log in.

## 2. Replace an UNSOURCED qualitative/boolean indicator with a real quantifiable proxy

Chao's quality standard (recurring): **a card that claims a threshold/trigger must have a chart,
numbers, and a reproducible rule** — a bare `source:search` boolean written by web_search with
no stored evidence is not acceptable ("no chart, no numbers, how did it hit the threshold?").

Method used to fix the "NYSE A/D Line 顶背离" boolean:
- **Find a real continuous proxy with the same meaning.** A/D line = market breadth.
  Breadth proxy = **RSP (equal-weight S&P) / SPY (cap-weight S&P)** ratio: ratio DOWN = few mega-caps
  leading, most stocks weak = breadth deteriorating = A/D top-divergence equivalent. Continuous,
  quantifiable, chartable.
- **Encode a reproducible numeric divergence rule** (no AI subjectivity):
  `SPY makes a new lookback-window high (>= 99.5% of lookback max) AND the RSP/SPY breadth ratio
  does NOT confirm (its recent high is > 2% below its lookback high) => top divergence = True`.
  Store the full evidence dict (SPY lookback high, recent high, ratio gap %, breadth_confirmed,
  the rule text itself) so the card can show WHY.
- **Wire the real result into the existing signal/trigger plumbing.** In `run.py` (the fetch/derive
  stage — signals.py stays pure/no-network), inject the real `divergence` bool into
  `results["ad_line"]["value"]`, overriding the old override boolean; on fetch-fail, **leave the
  old value untouched** (don't blank). `signals.py` then appends the evidence source to the
  check description so the sell-trigger row is traceable.
- **Purge the fabricated override.** Set the old unsourced `manual_overrides.json` entry to
  `value=null, status="待真数据"` so until real data lands the card shows "无数据" — never a
  phantom `True`.
- Render: dual-line chart (index price vs breadth ratio, each normalized to panel height because
  magnitudes differ ~770 vs ~100), a verdict badge (🔴顶背离 / 🟢广度确认 / ⚪未判定), the
  evidence line, and the rule text in the source line.

Generalize: whenever an indicator card is a hand-set boolean / qualitative "search" value with no
underlying series, look for a free continuous proxy + a numeric rule before accepting the boolean.
This is the same standard behind the project's "绝不编数字 / 阈值静态可复现" discipline.
