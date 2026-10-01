# Build-time gates > "remember to check" (Eco dashboard)

Hard-won 2026-09-21. Chao's standing principle (already in memory): *when you set a quality bar for
others but enforce it on yourself by remembering, you will eventually break it on yourself.* This file
is the concrete pattern for turning a recurring defect into a gate the build itself enforces.

## The whack-a-mole smell → write a gate instead

Symptom: you fix a defect class, rebuild, it's still there, fix again, still there. Real case:
literal Markdown `**bold**` rendering as visible asterisks on the public page. Count went
**25 → 13 → 8 → 0** over FOUR rounds, because the render outlets are *divergent* (KOL bio, KOL
comment, roster profile rows, focus field, per-section caption text, JSON payload) and each round I
only fixed the outlets I happened to think of.

**Stop patching after the second failed round.** The tell is: the defect is only observable in the
PRODUCT (`docs/index.html`), never in the source, so source-side enumeration can never be proven complete.

### Gate implementation (copy this shape)
`src/build_dashboard.py` already has `assert_no_missing_kwargs()`; add siblings next to it and call
them right after `dash.generate(...)` returns the output path:

```python
def assert_no_literal_markdown(html_path):
    """warn-only gate: product must not contain literal ** markers"""
    h = open(html_path, encoding="utf-8").read()
    hits = re.findall(r"\*\*([^*\n]{2,80})\*\*", h)
    if not hits:
        print("[dashboard] ✅ 门禁: 产物无字面 Markdown 星号"); return
    print(f"[dashboard] ⚠️⚠️ 门禁: 产物有 {len(hits)} 处字面 Markdown 星号")
    for x in dedup(hits)[:6]:
        p = h.find("**" + x + "**")
        cls = re.findall(r'class="([a-z0-9\- ]{2,40})"', h[max(0, p-600):p])
        print(f"[dashboard]      ** {x[:48]} **  <- class=「{cls[-1] if cls else '?'}」")
    print("[dashboard]      修法: 该出口的 _esc(...) 改为 _esc_md(...)")
```

Design rules that made it useful:
- **Warn, don't abort.** Cosmetic/product defects must not prevent the dashboard from generating
  (same policy as the existing kwargs gate). Data-integrity gates may abort; display gates warn.
- **Print the locating hint** (nearest `class="..."` before the hit + the prescribed fix). A gate that
  only says "8 problems" costs you another debugging round; one that names the CSS class is actionable.
- **Test the gate three ways before trusting it** — a warner that never warns is worse than none:
  1. feed the current (still-dirty) product → must fire and locate;
  2. feed a clean synthetic file → must pass silently;
  3. feed a nonexistent path → must not crash the build.

## Markdown in data → TWO different helpers, never one

The data files (`data/kol_registry.json`, `kol_store_export.json`, `kol_profiles.json`) are Notion
one-way mirrors — **not editable by this agent** (名册铁律). So the fix must live in the render layer,
and it splits by destination:

| destination | helper | behavior | why |
|---|---|---|---|
| direct HTML output | `_esc_md(s)` | `html.escape` **then** `**x**`→`<b>x</b>` | order is critical: escape-first means the `<b>` you insert is the only raw tag; escape-after would turn it into `&lt;b&gt;` |
| JSON payload in `<script>` | `_strip_md(s)` | just delete the `**` markers | payload is rendered by JS via `textContent`; inserting `<b>` shows the literal tag, and switching JS to `innerHTML` to "fix" it opens an XSS surface |

XSS reverse-test for `_esc_md` (public repo → must be airtight). Correct criterion = **after removing
the `<b>`/`</b>` we inserted, zero bare angle brackets remain**:
```
<script>alert(1)</script>        -> &lt;script&gt;alert(1)&lt;/script&gt;      ✅
**<img src=x onerror=alert(1)>** -> <b>&lt;img src=x onerror=alert(1)&gt;</b>  ✅
**a**<svg onload=alert(1)>**b**  -> <b>a</b>&lt;svg onload=alert(1)&gt;<b>b</b> ✅
```
⚠️ My FIRST version of this test flagged the `<img>` cases as DANGEROUS because it grepped for the
string `onerror=` — but `&lt;img … onerror=alert(1)&gt;` is inert text. **A wrong detector produces both
false alarms and false clears.** Write the criterion in terms of what the browser can execute (bare
`<`/`>`), not in terms of scary substrings.

Boundary cases that must NOT convert: single `*`, unpaired `**`, `**` spanning a newline.

## Enumerate outlets with a script, not with your eyes

After the gate fires, find **every** outlet in one pass instead of the first grep hit:
```python
for m in re.finditer(r'.*kol-standing.*', src):      # same class, MULTIPLE render sites
    print(f"L{src[:m.start()].count(chr(10))+1}: {m.group(0).strip()[:120]}")
```
Real miss: `kol-standing` had **two** emitters (L2025 and L2185); I patched L2025, declared victory,
and the gate caught L2185. Same lesson as the memory rule *长名单必用 Python set-diff 不用眼睛*.

## Concurrency guard must be scoped to THIS project

The build guard `ps -eo cmd | grep -F "build_dashboard.py" | grep -v grep | wc -l` gave a **false
`exit 9`** because a *different* project (`~/Projects/Science-KOL`) has an identically-named
`build_dashboard.py`. Chao runs many projects on one VM — always include the project path:
```bash
N=$(ps -eo cmd | grep -F "Eco-and-Volatility-Checker" | grep -F "build_dashboard.py" | grep -v grep | wc -l)
[ "$N" -gt 0 ] && { ps -eo pid,etime,cmd | grep -F "Eco-and-Volatility-Checker" | grep -F "build_dashboard.py" | grep -v grep; exit 9; }
```
Also print the offending process line on trip — otherwise you cannot tell "real collision" from
"someone else's same-named script" without another round.

## Notion write-after-read: `read_back` needs `title_field`

`notion_writer.upsert()` accepts `title_field=`, but `read_back(db_id, title_value, field)` did **not** —
it passed the default `"Date"` to `query_by_title`. Any DB whose title column is named something else
(`Month`, `Week`, `Ticker`) therefore returned `None` **forever**, regardless of whether the write worked.

Danger profile: this reports **success as failure**, which feels safe, so the natural reaction is
"this table always reads back None, ignore it" — at which point that table's write verification is
permanently dead and a REAL write failure will never be noticed again. Fixed by adding the parameter
and sweeping all call sites. When you add a helper pair (`write` / `verify`), keep their signatures
symmetric.

Corollary: **verify with a set-diff over identifiers, not by eyeballing a log tail.** A backfill log
ending at `进度 350/367` with the DB showing 363 rows looked like 4 lost rows; a set-diff of
expected-vs-present months proved 367/367 (I had simply queried while the last writes were in flight).

## Small traps that cost a false alarm each

- **`f"...{re.findall(r'[^*\n]', s)}"` → `SyntaxError: f-string expression part cannot include a
  backslash`** (Python <3.12). A verification snippet crashing makes a *successful* build report
  `exit 1`. Keep regexes in a module-level constant, out of the f-string.
- **`grep -c` returns exit 1 on zero matches** — and zero is often the DESIRED result. Never chain it
  with `&&`, and never let it be the last command of a script whose exit code you report.
- **Don't grep the product for a phrase you remember writing.** I searched for `没有官方单一口径`, got 0
  hits, and nearly concluded the disclosure was missing — the page actually said `无官方单一口径`. Correct
  method: extract the rendered container and read it, e.g.
  `re.search(r'<div class="gms-caliber">(.*?)</div>', h, re.S)` then strip tags. Also beware that
  `h.find("gms-caliber")` lands on the **CSS rule**, not the rendered div — match on `class="..."`.
