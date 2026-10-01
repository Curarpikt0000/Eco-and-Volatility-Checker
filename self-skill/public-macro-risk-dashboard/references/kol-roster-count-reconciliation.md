# 「名册现在到底多少人？」— KOL roster count reconciliation

Companion to `kol-roster-and-drilldown-sections.md` (which covers *adding* people and the
drill-down UI). This file covers the recurring **question** family:

> 「上在 track 的 KOL 也是 124 人对么」 / 「dashboard 上是多少人」 / 「名册和 Notion 对得上么」

Realized 2026-08-22 on `~/Projects/Eco-and-Volatility-Checker`.

---

## 0. 铁律：never answer from prose

`AGENTS.md` / `SKILL.md` / `README` counts rot within days. At the moment Chao asked, the Eco
`AGENTS.md` still said 「全量 91 KOL」 and 「80 个 KOL」, and the sibling project's `AGENTS.md`
said 「95 位」 — the live roster was **124**. Chao's standing rule (`论断锚具名数据+可追溯出处`)
means the answer must come from live artifacts, with the read command shown.

## 1. Three artifacts, three different meanings — always report all three

| # | artifact | how to read | what it means |
|---|---|---|---|
| 1 | **Notion「KOL List」DB** `35947eb5-fd3c-800d-b852-cef31f9de6a5` | paginated `POST /v1/databases/<id>/query` until `has_more=false` | **the SSOT.** "In track" is defined by this and nothing else |
| 2 | `data/kol_registry.json` | `len([k for k in d['kols'] if k.get('active',True)])` | the GitHub mirror the collector actually reads |
| 3 | newest `data/kol/daily/YYYY-MM-DD.json` | `{s['kol'] for s in snap['kols']}` | who was really crawled last run = **what the dashboard currently shows** |

`scripts/reconcile_kol_roster.py` (this skill) runs all three + the normalization below.

`.env` here is a flat `KEY=value` file; parse it manually rather than assuming `dotenv`:
```python
env = {k.strip(): v.strip().strip('"').strip("'")
       for k, v in (l.split('=', 1) for l in Path('.env').read_text().splitlines()
                    if '=' in l and not l.strip().startswith('#'))}
```

### Notion property name gotcha
The title property is **`KOL / 机构`**, not `Name`. Looking up `properties['Name']` yields an empty
name list and makes a healthy 124-row DB look empty. Always
`print(list(rows[0]['properties']))` before extracting.

## 2. ⚠️ Normalize before diffing, or you invent 25 phantom mismatches

Notion titles carry institution suffixes — `Nomi Prins（… 前 Goldman Sachs MD）`,
`Carl Icahn（Icahn Enterprises 创始人 / 董事长）` — while the local registry stores the bare
`display_name`. A raw set-diff of 124 vs 124 reported **25 "Notion-only" + 25 "local-only"**, all
the same people.

```python
norm = lambda s: re.sub(r'\s+', '', re.sub(r'[（(].*?[)）]', '', s)).lower()
```
After normalization: **0 差异**. Same root cause as the `Nomi Prins` fuzzy-match pitfall recorded in
the project's 名册铁律 (one-directional 「local ⊂ notion」 matching, shortest candidate wins) —
here it bites the *reporting* path instead of the *sync* path.

## 3. Snapshot lagging the roster by one cron run is NORMAL, not breakage

Registry 124 vs newest snapshot 122 was not a bug: the Notion→registry sync landed as cron step 0
only after the last crawl had already run. Check the sync commit time against the snapshot mtime
before calling anything broken.

- **名册有 / 快照无**: newly added people, plus institution rows (`Goldman Sachs`,
  `Morgan Stanley`, `Citi / UBS`) that the collector never resolves to a person — expected.
- **快照有 / 名册无**: people just removed. In this session that was the 8-strong 玄学/术数 batch
  reassigned to the **Forecast-Checker** project, plus a few others.

Correct phrasing to Chao: *「名册 = 124（Notion 与本地一致）；最新快照 122，因为同步在上次抓取之后才落地，
下一次 cron（周一 11:00）才会按 124 跑，dashboard 当前卡片来自上一批快照」*.
Do **not** "fix" this by editing the collector or hand-patching a snapshot.

## 4. Report the direction distribution from the snapshot, not from HTML cards

```python
Counter(s['direction'] for s in snap['kols'])
# 2026-08-21: 强烈看多 28 / 看多 27 / 中性 14 / 看空 9 / 分歧 6 / 另类预言 8 / 未找到 30
```
「未找到」 is a real, expected bucket (~25%) and must be reported, not hidden. HTML card counts are
post-filter (109 cards from a 122-person snapshot) and will legitimately disagree — never quote the
card count as the roster size.

## 5. Sibling mirrors of the same SSOT drift silently — check them in the same pass

`~/Projects/Economy-KOL-to-Notion/data/kol_registry.json` mirrors the **same** Notion DB but is a
separate copy; it sat at **80** while Eco was at 124. Flag the drift in the answer, but do **not**
sync another project's roster unasked — Chao's project-boundary 铁律 (「你不要做我没给你的任务」).
Offer it as a one-line question instead.

## 6. Protected `AGENTS.md`: in-chat consent ≠ consent at the write gate

Chao replied 「同意重写」 in chat, yet `patch` on `AGENTS.md` still returned:
`BLOCKED: write to protected agent-instruction file(s) … approval prompt timed out … Do NOT retry
it or attempt the same edit via another path (terminal, execute_code, etc.)`.

Correct sequence:
1. **Back up first** — `cp AGENTS.md scratch/backups/<YYYYMMDD>_agentsmd/` (does not require approval).
2. Attempt the edit via `patch`.
3. If BLOCKED: **report the block honestly**, list the exact pending edits verbatim, and ask Chao to
   click the approval prompt when it appears. Never route around it, never silently drop it, never
   report the doc as updated.

Pending edits from this session (still unapplied):
- Eco `AGENTS.md`: 「全量 91 KOL」/「80 个 KOL」 → "以名册 active 数为准（当前 124），正文不写死数字"
- `Economy-KOL-to-Notion/AGENTS.md`: 「95 位」 → same treatment + note local mirror at 80 vs SSOT 124
