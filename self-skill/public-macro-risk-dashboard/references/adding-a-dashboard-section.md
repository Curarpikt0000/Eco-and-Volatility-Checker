# Adding a NEW section/chart to the Eco-and-Volatility-Checker dashboard

Distilled from the "US oil inventory operational red line" section build (Brent-WTI spread /
Cushing / SPR) and the frequency-badge pass. This is the repeatable recipe + the traps.

## The 5 wiring points (miss one and the section silently breaks)

A new section touches FIVE places. Do ALL five or it works locally but vanishes on the next cron run.

1. **`src/external_data.py`** — add `fetch_<thing>()`. Returns `{status, as_of, ...series}`.
   Each sub-series carries its own `status` ("ok" / "未获取"), points list, source string.
   Write a cache JSON under `data/`. NEVER fabricate — missing → `status="未获取"`, empty list.
2. **`src/dashboard.py`** — add `_<thing>_html(data)` render fn + any new SVG helpers.
   Reuse existing SVG primitives (`_bar_chart_svg`, `_custody_chart_svg`) or write a variant.
3. **`src/dashboard.py` `generate()`** — TWO edits:
   (a) add the param to the `def generate(...)` signature (keyword, default None);
   (b) add `<thing>=_<thing>_html(<thing>)` into the `.format(...)` dict;
   (c) add the `<!-- section -->` + `<div class="part-title">…</div><div class="card">{<thing>}</div>`
       HTML block in the template body at the desired position.
4. **`src/build_dashboard.py`** — TWO edits: `fetch_<thing>()` call (wrapped in try/except with a
   print line) AND pass `<thing>=<thing>` into the `dash.generate(...)` call.
5. **★ THE PITFALL: the daily cron has its OWN inline `generate()` call.**
   `~/.hermes/cron/jobs.json` job `eco-vol-01-daily-scan-report` does NOT run `build_dashboard.py`;
   its prompt embeds a hand-written python one-liner: `...mt=e.fetch_maturing_treasury();...`
   then `dash.generate(...,maturing_treasury=mt,...)`. You MUST patch BOTH the fetch chain and the
   generate() call inside that JSON string, or the section renders in manual builds but DISAPPEARS
   every daily cron run. Patch via venv python editing jobs.json (back it up first), then read back
   and assert the two new substrings are present.

## Verification loop (vision backend is often down — use programmatic DOM checks)

- `python -m src.build_dashboard` writes to `docs/index.html` (public Pages dir) AND `dashboard/index.html`.
  Build can exceed the 60s foreground tool timeout (SPR = 500+ weekly points); run it BACKGROUND with
  notify_on_complete, or `process wait`.
- Verify with `browser_console` evaluating JS on the rendered file: count SVGs, red lines, chart titles,
  meta strings. This is the reliable check when `browser_vision` returns 400 (backend down) — the
  screenshot still saves; send it to the user via MEDIA: for their eyeball confirmation.
- grep the built HTML for the section title + key values before committing.

## Commit/push discipline (project-specific, already in umbrella but reaffirmed)

`git pull --rebase --autostash` → `git commit --no-gpg-sign -m "…"` → `git push origin main`.
Commit BOTH `docs/index.html` and `dashboard/index.html` (they should be identical — `diff -q` them).
Red-line scan the diff for internal URLs / keys before push (public repo). `.env` stays git-ignored.

## Frequency-badge pattern (每个图表标更新频率)

Chao wanted every section title to show its data cadence. Implementation:
- One `.freq-badge` span appended INSIDE each `.part-title`, colour-classed by cadence:
  `freq-daily`(green) / `freq-weekly`(blue) / `freq-monthly`(amber) / `freq-quarterly`(purple) /
  `freq-event`(grey, e.g. "每次拍卖"). `.part-title{display:flex}` + `margin-left:auto` right-aligns it.
- For flex titles that already hold a button (KOL全景/BIS), put the badge between the `<span>` and the
  `<a>` with inline `style="margin-left:0"` so it sits next to the title not fighting the button.
- Cadence MUST match the SOURCE's real publish rhythm, not our cron rhythm. Standard map for this repo:
  indicators/alerts/interp/conclusion/triggers/focus/KOL-panorama/liquidity/CB-balance/rates-quad = daily;
  KOL-stance-change/foreign-custody/oil-inventory = weekly; money-supply/M2/refi-wall/country-holdings = monthly
  (TIC lags ~2mo); Credit-Impulse/BIS/13F = quarterly; treasury-auction = per-event.
- **★ Sidebar-index contamination pitfall:** the left nav auto-builds link names from
  `.part-title` `textContent`. The badge text ("每日更新") gets concatenated into the link name.
  Fix: in the sidebar JS, `cloneNode(true)` the title, `.querySelector('.freq-badge')?.remove()`,
  THEN read `textContent`. Group-matching keywords live in the title body so removal doesn't break them.

## Per-chart update-frequency note + next-release date

For weekly sources, a `_eia_next_release(as_of)` helper computes the next publish date. EIA WPSR
releases every WEDNESDAY covering the prior Friday: from the Friday `period`, add 5 days then walk to
the next weekday()==2. The rendered "下次约 YYYY-MM-DD" auto-advances as each daily fetch pulls a newer week.

## EIA data source facts (see references/eia-fred-oil-data.md)
