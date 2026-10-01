# Report coverage ≠ collection coverage (the silently-widening blind spot)

Distilled 2026-08-23, Eco-and-Volatility-Checker. Chao asked:
「这些基础数据是如何取得的？你基本上考虑了所有的表格，还是说只考虑了其中一部分？」
Answer, after counting: **only a part**. This file is the audit method + the misdiagnosis trap.

## The failure mode

A dashboard pipeline grows by **adding fetchers and sections**. The daily-report step of the
cron prompt, however, was written **once, early**, and names a fixed handful of things to report.
Nothing links the two. So every new section widens a gap that:

- does not error,
- does not warn,
- looks perfect on the dashboard,
- and is invisible until the user asks "are you covering everything?"

Measured on this project:

| Thing | Count |
|---|---|
| dashboard `part-title` sections | **45** |
| modules the report step actually named | 6-part skeleton + 5 add-ons |
| `external_data` fetchers defined | **42** |
| fetchers the cron prompt calls | **38** |

→ 30+ sections (stress panels, auctions, custody, credit impulse, the whole COMEX suite,
inventories, breadth, CIPS, AI-chain financials, IIP, century yields, maturity wall) were
collected daily, rendered daily, and **never once reported**.

## Audit recipe (portable to any cron-report pipeline)

```python
# 1) how many sections does the artifact actually have?
secs = re.findall(r'<div class="part-title"[^>]*>(.*?)</div>', html, re.S)

# 2) which fetchers exist vs which the cron prompt calls
avail = sorted(n for n in dir(mod) if n.startswith('fetch_') and callable(getattr(mod, n)))
used  = set(re.findall(r'\b(fetch_[a-z0-9_]+)\s*\(', cron_prompt))
missing = sorted(set(avail) - used)      # then triage each: deprecated? redundant? real gap?

# 3) count the modules the report step NAMES, compare to (1)
```
The delta in (3) is the blind spot. Triage (2) into **deprecated / redundant / genuinely missing** —
do not assume every uncalled fetcher is a bug.

## ★ The misdiagnosis trap (I got this wrong first)

I asserted: *"the ECB block is empty because `fetch_ecb_balance_sheet` is never called."*
**Wrong.** The main `fetch_cb_balance_sheets()` already returned four central banks; the ECB
entry had 6 asset lines and the dashboard had been rendering its total assets all along.
The standalone same-named fetcher was **redundant**, and its non-use was correct.
The actual defect was that **the report copy said "three central banks"** — a wording omission,
not a data gap. The separate `fetch_*` name existing made the wrong story feel plausible.

**Fixed diagnostic order — never skip a step:**

1. **Run the fetcher, print its return value.** Does the data exist right now?
2. **Grep the rendered artifact** for the section and its numbers. Is it being displayed?
3. **Only then** suspect the collection layer.

Skipping 1–2 turns a copywriting defect into a phantom "data source is broken", and you go
fix the wrong layer. Corollary worth memorising:
**"this block never appears in the report" ≠ "we never fetched it".**

## Structural fix: fixed module skeleton + placeholders + health section

Chao's instruction: 「日报应该根据每天可以更新的所有 dashboard 数据来做，而不是只包含其中一部分…
不用在乎日报是不是太长，重要的是关键信息有没有包含全，以及分层结构是否方便人类阅读清晰」

So the report step becomes a **fixed, ordered module list** (this project uses 12: core
indicators/alerts · conclusions+actions · liquidity · **four** central banks · debt & fiscal ·
rates & treasury stress · credit · foreign UST holdings & de-dollarisation · precious metals ·
commodities & other markets · KOL & institutional behaviour · focus + **data health**), with:

- **changed → detail; unchanged → one line.** Length is not the constraint; completeness is.
- **low-frequency blocks with no update still emit a placeholder line** —
  `(季度/年度，本次无更新)`. The placeholder carries no information *value*; it carries
  **proof of coverage**. To a reader, "module absent" and "module unchanged" look identical
  but mean opposite things. Placeholders make the skeleton auditable at a glance.
- a final **data-health module**: list anything not-ready / failed validation this run,
  **and write one line even when everything is fine** ("all sources normal").
  Without the always-on line, a source can die quietly and no one notices.
- length uncapped, but **layering is mandatory** (module heading → 2-6 bullet lines,
  key numbers bolded, deltas with ↑↓ and %).

## Cron-prompt surgery discipline

These prompts inline long calls like `dashboard.generate(...)` with dozens of kwargs.
Editing anything nearby can silently drop parameters (whole sections then vanish from the build).

**After every cron-prompt edit, re-count that call's kwargs.** Take the call body by
**bracket-matching** from `dashboard.generate(`, then count `\w+=` inside it:

```python
i = p.find('dashboard.generate(')
depth = 0
for k, ch in enumerate(p[i:]):
    if ch == '(': depth += 1
    elif ch == ')':
        depth -= 1
        if depth == 0: end = k; break
kw = re.findall(r'(\w+)\s*=', p[i:i+end+1])   # this project: must stay 47
```

Do **not** use a loose regex over the whole prompt: the prose sections mention
`dashboard.generate` too, so a sloppy pattern grabs the wrong fragment and reports a
phantom "parameters lost" (this project produced two such false alarms historically).
Also re-assert that sibling steps (`步骤1b/1c/1d`) survived the splice.

## Related
- `references/dashboard-data-integrity-audit.md` — the numbers-are-real audit
- `references/add-new-dashboard-section.md` — when adding a section, also add its report module
