# Eco dashboard: extending the KOL roster + building drill-down sections

Companion to `add-new-dashboard-section.md`. That file covers "new DATA SOURCE → new chart section".
This one covers the other recurring request family on the same repo: **"给 KOL section 新加一批人 /
单独划分一个 section / 每天+每周的预测也要能看"**, and the **two-level drill-down** UI that makes a
one-line card expand into a person's full opinion history.

Realized 2026-08 adding a 周期与术数预测 (cycles / financial-astrology / I-Ching) roster of 23 people.

---

## A. The roster is a registry file, and the cron picks new people up for free

`data/kol_registry.json` → `{"kols":[ {...}, ... ]}`. **Read one record and copy its exact field
names before writing an insert script** — guessing them costs a silent no-op render:

| field | note |
|---|---|
| `display_name` | **the join key** to daily-snapshot opinions. NOT `name`. |
| `sector` / `domain` | `sector` is the raw grouping key; `domain` is its 中文 label |
| `forecast_cadence` | `daily`/`weekly`/`biweekly`/`monthly`/`irregular`. NOT `update_freq`. |
| `source_url` | the person's channel/site. NOT `url`. |
| `forecast_school`, `focus`, `region`, `institution`, `bio`, `active` | card body fields |

I wrote an insert script against invented names (`name` / `update_freq` / `url`) and got **23 cards
that rendered with 0 links, blank frequency, and everything dumped in one group** — every element
"present", all values empty. Dump one real record first:
```
.venv/bin/python -c "import json;print(json.dumps(json.load(open('data/kol_registry.json'))['kols'][0],ensure_ascii=False,indent=1))"
```

**No collector change is needed to onboard new people.** The daily cron prompt already says it scrapes
"名册全部 active KOL，只增不减". So a registry insert = the next daily run starts collecting them.
Do NOT go edit the collector. Until that run lands, the new cards must render an honest
`待采集` state — never a fabricated stance (project 铁律).

Registering a new `sector` needs **two** dict edits in `src/external_data.py` or the group renders
as unlabeled/default: the `sector → (中文 domain, English)` map **and** `_KOL_SECTOR_COLOR`.

## B. Two-level drill-down: card → full history → single entry

Request shape: *"卡片只有一句话，点开要能看到这个人所有的观点，再点开看完整内容"*.

**Data layer** — `kol_full_history()` in `external_data.py`, merging two real on-disk sources
(no new scraping):
- `data/kol/daily/*.json` — every day's full-roster snapshot (200+ files)
- `data/kol/backfill/*.json` — per-person historical entries

Collapse **adjacent identical opinions into a date RANGE** (`first`,`last`) — a person holding one
view for 40 days is 1 entry, not 40. 209 snapshots + 99 backfills → 115 people / 2,608 entries.

**Payload** — inline as JSON into the single-file HTML. Use **arrays, not objects**, per entry
(`[first,last,dir,comments,targets,source]`): dropping repeated keys took 1.13MB → fine to inline
(~421KB gzipped). Measure before assuming it's too big.

**Render** — mark drillable cards `class="kol-drill" data-kol="<display_name>" role="button"
tabindex="0"`, and have the JS **build the modal skeleton at runtime** (`document.createElement`)
rather than adding it to the static template — keeps the section self-contained and avoids the
template landing in `<head>` (I mis-placed it there once; `patch` put it before the Chart.js
`<script>` tag which lives in head, not body).

Group the modal list into 本周 / 更早; second click expands one row to full text + targets + source
link. Wire `Escape`, backdrop click, and restore `document.body.style.overflow` on close.

### ⚠️ The drill-down's #1 failure mode: payload renders as `{}` in production only
Chao's report: *「我点开第一集的时候，没有任何有时间标注的 comments，但是你 default view 上是有的。怎么可能
default view 上有，但你那个数据库里点开之后没有任何东西？」* — every card opened to
「该 KOL 暂无已归档的历史观点记录」while the data layer held 137 people / 2730 records.

The card face is rendered from `kol_weekly_views()` (always passed), but the modal reads the inlined
`kol_history` payload — so **a dropped `kol_history=` argument produces exactly this "face has dates,
modal is empty" asymmetry.** Cron used its own inline build command that never got the new parameter.
Full root cause + the self-loading fix in `dashboard-data-integrity-audit.md` §"Embedded JSON payload
silently `{}`". **Whenever the face and the drill-down disagree, suspect the payload argument first.**

Acceptance for this section is NOT "the modal opened" — it's every clickable card resolving:
```python
drill = {H.unescape(m.group(1)) for m in
         re.finditer(r'class="[^"]*kol-drill[^"]*"[^>]*data-kol="([^"]+)"', h)}
assert not [k for k in drill if not payload.get(k, {}).get('h')]   # 0 empty modals
assert drill == set(all_data_kol)   # no history ⇒ must not be clickable at all
```
2026-08-21 verified state: 125 clickable cards, 0 empty, 1–73 entries each (median 21).

### History depth: check coverage before assuming a backfill is needed
Asked for 「至少过去一年」, my first instinct was to plan a backfill. Dumping the actual date
distribution first showed `kol_full_history()` already spanned **2025-01-02 → 2026-08-21 (20 months,
2730 entries)** — the depth was never the problem, the empty payload was. **Measure coverage before
building a backfill**; the entries are dicts keyed `first_date`/`last_date`, so dump one record
rather than assuming tuple/array shape (indexing `it[0]` raises `KeyError: 0`).


**Reuse the card metadata helper across sections.** The bug that started this work: 状态变化 cards
lacked the 业界地位/机构 line that 观点全景 cards had, because each section built its own lookup.
Extract one `_kol_meta()` returning `{display_name: {standing, focus}}` and call it from both. After
the fix: 30/30 状态变化 cards carried the line; 观点全景 98/99 (one person genuinely has no
`institution`/`bio` → leave blank, don't invent).

### Carving people into a NEW section means REMOVING them from the old one
Splitting the 周期与术数 roster into its own section only ADDED a renderer; the 23 people kept
rendering in the general 观点全景 section too, so each appeared **twice on one page**. Filter at
every general renderer that iterates modules — `_kol_views_html` AND `_kol_changes_html`:
```python
modules = [m for m in modules if m.get("sector") != _CYCLE_SECTOR]
total   = sum(len(m.get("views") or []) for m in modules)   # recompute AFTER filtering
if not modules or total == 0: return '<p class="empty">…</p>'
```
**Recompute the header count after filtering.** `views["total"]` is the pre-filter number, so the
prose 「共 124 位」 would contradict the 101 cards actually rendered — the same self-contradiction
class that this project treats as a first-order bug indicator.
Verify the partition sums exactly: 101 general + 23 cycle = 124 with zero intersection.

### Not every duplicate is a bug — partition by SECTION before calling it one
A dedup check found 30 people twice and I nearly "fixed" it. They were 观点全景 + 状态变化 — the
same person legitimately appearing as *current stance* and as *this week's change*. **By-design
cross-section repeats must be distinguished from same-role repeats.** Attribute each occurrence to
a real section before judging; a crude nearby-substring tag classifier lumped everything into one
bucket (`('view','view')`) and manufactured the false positive. Locate section boundaries by known
title anchors and bisect by offset — an `<h2>` regex silently matched nothing here and returned
`('?','?')` for every hit:
```python
anchors = sorted((m.start(), name) for pat, name in TITLES for m in re.finditer(pat, h))
def which(pos): ...  # last anchor before pos
```
Expected healthy output: `{('观点全景','状态变化'): 30}` — cycle派 must not appear in any pair.

## C. Pitfalls (all cost real time this session)

### The page's own JS renumbers `.part-title` ids — verify against the live DOM, not your source
I set `id="sec-cycle-kol"`; `getElementById` returned null in the browser while the string was
present in the built HTML. The dashboard has JS that walks `.part-title` and reassigns sequential
`sec-N` ids — mine became `sec-10`. Not a bug, and the sidebar nav still resolved.
**Generalises: when an id you wrote is missing at runtime but present in the file, suspect runtime
rewriting before suspecting the build.** Confirm via the element's actual id:
```js
[...document.querySelectorAll('.part-title')].filter(t=>t.textContent.includes('<title>')).map(t=>t.id)
```

### …but first rule out an EMPTY console context — zeros there mean nothing
Same failure surface, different cause, and far more dangerous because it looks like a real finding.
Probes returned `.kol-drill → 0`, `.cyc-item → 0`, `[data-kol] → 0` on a page whose file contained
184 / 24 / 178 of them. The evaluation had run against `about:blank`. Guard every DOM probe:
```js
({len: document.documentElement.outerHTML.length, title: document.title})
// len ≈ 39, title "" → empty context; discard all counts from that probe
```
Those zeros led me to inspect the card-emitting f-string and provisionally declare an
HTML-attribute bug in `class="kol-item cyc-item{drill} data-kol=..."`. Offline parsing showed the
emitted markup was correct (`class="kol-item cyc-item kol-drill" tabindex="0" role="button"
data-kol="Avi Gilburt"`). **Never edit code because a probe reported zero — falsify the probe first.
When browser output and the on-disk artifact disagree, the artifact wins**, and offline
`re`-parsing of the built HTML should be the primary acceptance channel for this section.

### `?nocache=` is not always enough — start a server on a NEW PORT
After a rebuild the browser still served the previous document (old byte size, missing new ids) even
with a cache-busting query string. Starting `python3 -m http.server <newport> --directory docs`
gave the fresh file immediately. Confirm you're on the new build by size before debugging content:
`curl -s -o /dev/null -w "%{http_code} %{size_download}" <url>`.

Also: `python3 -m http.server` **without `--directory`** silently serves the shell's cwd — I got a
different project's `index.html` (200 OK, wrong site). Always pass `--directory`.

### Long pages exceed the vision backend's image-dimension cap → verify geometry in JS instead
`browser_vision` returned `400 … image dimensions exceed` on the full dashboard. Geometry assertions
are cheaper and more reliable than a screenshot re-read anyway:
```js
[...card.querySelectorAll('.item')].forEach((it,i)=>{
  const r=it.getBoundingClientRect();
  if(r.right>cardRect.right+2) issues.push(i+' overflow');
  if(it.scrollHeight>it.clientHeight+2) issues.push(i+' clipped');
});
```
Pair with a computed-style probe (`visible`,`color`,`backgroundColor`,`fontSize`) per key class.

### `scratch/` is gitignored — copy any keeper script out before committing
The roster-insert script written to `scratch/` was refused by `git add`. `cp` it to `tools/` (or
`src/`) so the insert is reproducible and auditable. Back up `kol_registry.json` before running any
bulk insert.
