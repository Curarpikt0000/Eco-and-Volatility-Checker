# EIA + FRED oil/energy data sources (for Eco-and-Volatility-Checker)

Durable, verified facts from building the oil-inventory section. All free, official, public.

## What FRED has vs does NOT have

- FRED **HAS** daily oil PRICES (free, existing FRED_API_KEY):
  - `DCOILBRENTEU` = Brent, daily
  - `DCOILWTICO` = WTI (Cushing, OK), daily
  - Brent-WTI spread = `DCOILBRENTEU - DCOILWTICO` aligned on common dates. Spread turning NEGATIVE
    (WTI > Brent) is a Cushing tank-bottom stress signal.
- FRED does **NOT** have oil INVENTORY series. `WCESTUS1`, `WCSSTUS1`, `WCRSTUS1`,
  `W_EPC0_SAX_YCUOK_MBBL` etc. all return `count: None` / NOT FOUND on FRED. Inventory is EIA-only.
  (FRED `series/search` DOES work — "Cushing" returns only the price series, confirming no inventory mirror.)

## EIA API v2 (needs a free key)

- Register free at https://www.eia.gov/opendata/register.php (email → key in ~1 min). Key is 40 chars.
- Stored in project `.env` as `EIA_API_KEY=...` (git-ignored). Reader must tolerate the redactor:
  match line with a regex, don't hardcode the literal `EIA_API_KEY=` string inside a Python string
  literal in a heredoc (redactor poisons it → SyntaxError). Load via
  `re.match(r'^EIA_'+'API_KEY='+r'(.+)$', line)` split trick, or read env var.
- Endpoint (weekly petroleum stocks):
  `https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key=KEY&frequency=weekly&data[0]=value&facets[series][]=<SID>&sort[0][column]=period&sort[0][direction]=asc&length=5000`
- Series IDs (value unit = THOUSAND barrels; divide by 1000 for million-barrel display):
  - **SPR** = `WCSSTUS1` (Strategic Petroleum Reserve, 1982→present, ~2289 weeks)
  - **Cushing** = `W_EPC0_SAX_YCUOK_MBBL` (Cushing OK crude stocks, ~1166 weeks)
- **★ Frequency is WEEKLY ONLY.** The route metadata (`GET /v2/petroleum/stoc/wstk/`) lists
  `frequency: [('weekly', 'One data point for each week.')]`. Requesting `frequency=daily` → HTTP 400.
  EIA does not collect daily inventory — the Weekly Petroleum Status Report (WPSR) every Wednesday is
  the finest granularity that exists anywhere (Bloomberg terminal shows the same EIA weekly number).
  So "can you make SPR/Cushing daily?" → NO, it's a hard data-source limit, not a project choice.

## Operational red lines (real, cited — for red-line threshold overlays)

- **Cushing tank bottom ≈ 20 million barrels** (pipeline + tank-bottom minimum operating level).
- **SPR operational red line ≈ 300 million barrels** — disclosed by Amos Hochstein (then Biden-admin
  senior energy security adviser): below 300M physically risks the salt caverns; "70M is nonsense."
  Draw as a red dashed line; render breaching bars/points in red (#d64545). Below 300M = "跌破红线".

## Shell/quoting note
`facets[series][]=` contains `[` `]` — inside single-quoted shell + a python heredoc these collide.
Prefer running probes via a `.venv/bin/python3` heredoc using urllib, or `curl` with the whole URL
double-quoted, to avoid "unexpected EOF while looking for matching quote".
