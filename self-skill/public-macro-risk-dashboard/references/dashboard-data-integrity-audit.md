# Auditing & repairing an EXISTING dashboard (数据完整性体检)

Companion to `add-new-dashboard-section.md`. That file = building NEW sections. This one = the
recurring "review 一下 / 这些图有问题吗 / 排查断源" pass over a dashboard that already ships.
Worked end-to-end on Eco-and-Volatility-Checker (40+ sources, 2.3MB single-file HTML).

## The cardinal rule this whole audit serves
Chao 铁律: 抓不到数据必须标 `n/a` 或保留旧真值 — **绝不能用空值/估算值/常数近似/占位数覆盖真实历史数据**。
Any code path that silently truncates, silently blanks, or overwrites real data with fake data = **P0**.
Date labels must NEVER extrapolate into the future.

## Triage: "断源" is almost never actually a broken source
Before reporting anything as a dead source, classify into one of FOUR verdicts. In one full sweep of
6 suspected-dead sources, **zero were真断源**:

| Verdict | Symptom | How to prove it | Fix |
|---|---|---|---|
| **渲染层字段名错** | value renders, `as_of` shows empty `（）`, staleness badge silent | call the fetcher directly, print the returned dict's real keys | rename at the render site, with a `or` fallback |
| **取数层只拉1期** | the delta/环比 column is all `n/a` but VALUES are fine and fresh | check the fetcher's `lastNObservations` / `limit` / row-count param | pull N+1 periods, compute the diff |
| **源自然滞后** | lag matches the source's real release cadence (quarterly 100-150d, TIC ~60d+) | **check the PUBLISHER's latest release (news/data page/third-party report) — NOT just the file you already fetch.** A recent file-update stamp proves nothing; only the newest observation date counts | not a bug — label the lag honestly |
| **抓错源(存档表)** | fetch is healthy in every way (200, parses, 100+ points, file re-stamped recently) yet lag is 2×+ the cadence | the publisher has newer periods in a DIFFERENT file (`*hist*` archive vs `*_current`/`table5`) | merge both, current-table-wins; see the TIC correction below |
| **阈值设错(误报)** | badge screams 🔴 but the publisher's newest observation IS what you already have | look up the source's *measured* release delay, not its nominal cadence name | raise that source's SLA threshold — **do NOT touch the data or the fetcher** |
| **真断源** | official source itself has newer data than you're getting | compare fetched latest vs official published latest | fix the fetcher |

**Always run the fetcher in isolation before touching render code.** A one-liner that prints
`status / as_of / len(points)` per source separates "data problem" from "display problem" in one shot.
Probe the RIGHT nesting level — a fetcher returning `{"US":{...},"CN":{...}}` will look like `n=0`
if you read `.get("points")` at the top level and you'll false-alarm a healthy source.

### Case: empty `as_of` was a field-name mismatch, not a dead feed
HF-leverage rendered `（）` and its staleness badge never fired. The render read `ex.get("as_of")`
but the fetcher's sub-dicts actually carry **`latest_q`** (`as_of` exists only at the TOP level).
Data was perfectly healthy (53 points, 2026-03-31). Fix with a double fallback so an upstream rename
can't silence it again: `ex.get("latest_q") or hf.get("as_of")`.

### Case: 18 × `n/a` in a 环比 column = fetcher pulled only ONE observation
ECB balance sheet showed every 分项 with `delta=None, pct=None`. Root cause was literally commented
in the fetcher: `lastNObservations: 1` + `"周环比暂无(只拉最新1期)"`. You cannot diff one period.
- Fix: request `lastNObservations=2`, build `{tail: {period: value}}`, derive the global latest period
  as `max()` over ALL series (do NOT trust per-row order), keep a parallel `prev` dict, then compute
  `delta`/`pct` **only when the previous period genuinely exists** — otherwise leave `None`. 绝不用 0 冒充.
- **Verify the API actually returns both periods before writing the parser**: a raw probe showed
  `43/43` items present in both `2026-W32` and `2026-W33`. Result 18 n/a → 1 (the surviving one is a
  computed 差额 residual row that legitimately has no WoW — correct to leave blank).
- Generalizes: any "全列 n/a but values fresh" symptom → look for a `lastN=1` / `limit=1` in the fetcher.

## Staleness badges: never assert breakage you haven't proven — but never assume innocence either
A threshold-based badge can only prove "久未更新" — it CANNOT prove the fetch is broken. Wording like
「疑似源中断」is an unfounded inference and violates 论断锚具名数据.
- Correct wording: 「远超常规更新周期，请核对官方是否已发布新值」— states the fact, prompts verification,
  asserts no cause.
- Badge design that avoids noise: threshold per natural frequency (daily/weekly/monthly/quarterly/
  semiannual), stay SILENT when fresh, 🟡 over threshold, 🔴 over 2×. Always put the real date in the
  `title=` attribute so hovering shows the evidence.

### ⚠️ CORRECTION (2026-08-21): the TIC case in this file was WRONG for 5 months — read this
An earlier version of this reference concluded: *"TIC lag hit 232 days but `mfhhis01.txt` is stamped
7/14/2026 and its newest column IS Dec 2025 — the fetch chain is perfect, the US Treasury simply
hasn't published newer months."* **That conclusion was false and it kept a real P0 alive.**

Chao caught it by noticing the page contradicted itself: the chart said 滞后 233 天 while the badge in
the same corner said 每月更新·滞后约2月. Ground truth: TIC published **2026-06 on 2026-08-17** (Japan
$1,116.7B, China $633.4B); the dashboard was showing 2025-12 values (Japan $1,186B, China $684B) —
**6 months stale AND numerically wrong.**

Why the earlier audit was fooled, and the rule that follows:
- `mfhhis01.txt` is a **historical ARCHIVE table**: it is re-stamped every year (hence the fresh
  7/14/2026 date) but its content only ever reaches **the previous calendar year-end**. Current-year
  months live in a DIFFERENT file, `slt_table5` (13-month rolling window).
- **"The file's own update stamp is recent" is NOT evidence the data is current.** Neither is HTTP 200,
  nor successful parsing, nor 100+ returned points. Only the **newest observation date** counts.
- Government/institutional stats sites routinely split **archive** vs **current** into separate files
  with confusingly similar names (`*hist*` / `*_archive` vs `*_table5` / `*_current`). Wiring only the
  archive file makes data permanently 6–12 months stale while looking completely healthy.
- **The verdict "源自然滞后" must be proven against the PUBLISHER, not against the file you already
  fetched.** One `web_search` for the release would have surfaced Reuters/WolfStreet reporting the
  2026-06 numbers and killed the false conclusion instantly. Circular reasoning — "the file I fetch is
  the newest data, therefore the newest data is what this file has" — is what produced the error.

Fix pattern: fetch **both** files and merge with the current table winning
(`series.update(current)`) — the current table also carries official revisions, so overwriting the
archive is correct. If the current table can't be fetched or parsed, fall back to the archive; never
blank the series.

### Corollary: a per-entity 口径 limitation is NOT a fetch failure — label it, don't fake it
Same TIC chart, EU line: TIC has no "EU" row, so the series is a 9-country eurozone sum. But
`slt_table5` lists only the **top-20 holders** — Germany/Italy/Netherlands/Spain/Finland fall into
"All Other", so the 9-country 口径 is **structurally unreconstructible** from the current table.
- Right call: return `{}` from the current-table parser when members are missing (guard:
  `if len(seen) < len(EU_MEMBERS): return {}`), fall back to the archive, and surface a
  `lag_reason` string the renderer prints on the chart. **Never emit a partial sum** — a 4-of-9 total
  silently breaks series continuity at the join, which is worse than an honest stale value.
- The section header must then stop making one blanket frequency claim. Split it:
  「日/中 每月更新·滞后约2月 · 欧盟受口径限制滞后至上年末」.

### Investigating a red badge yields TWO opposite verdicts — decide which before editing anything
One sweep on 2026-08-21 produced two red badges whose correct fixes point in **opposite directions**:

| Badge | Verified against publisher | Verdict | Correct fix |
|---|---|---|---|
| TIC 滞后 233 天 | official had newer data (2026-06 released 08-17) | **抓错源** | change the data source |
| Credit Impulse 滞后 324 天 | FRED's newest observation really was 2025-10-01 | **阈值设错** | change the SLA number |

So "red badge → go fix the fetcher" is a **wrong reflex**. Verify against the publisher first, THEN
pick the direction. Editing the fetcher on a false-positive wastes effort and can damage a healthy source.

**Nominal cadence ≠ release delay.** BIS credit-to-GDP (FRED `QUSPAM770A`/`QCNPAM770A`) is a *quarterly*
series whose BIS-compilation + FRED-republication delay measures **9–10 months**. Applying a generic
`quarterly=135d` threshold makes it permanently red. Give slow series their own key
(`bis_quarterly: 330`) rather than loosening `quarterly` for everyone — and fix the on-page prose too
(「数据滞后约 1 季」was itself false; the truth was ~3 quarters). **Wrong copy is a defect, not cosmetics.**

Rules that follow:
1. **Every red badge must be resolved to an explicit verdict** (change source / change threshold). Never
   let one sit indefinitely — permanent red badges train the reader to ignore all badges (狼来了),
   which hides the real failure.
2. Set thresholds from each source's **measured** delay, never from the frequency word.
3. Once a lag's cause is known, the badge must stop saying 「请核对官方是否已发布新值」. Add a
   `known_reason=True` path rendering 「（原因见下方说明）」 plus the explanation — otherwise a
   correctly-working pipeline reads as broken.
4. Do a **full sweep, not just the reported chart**: extract every badge and triage all of them.
   ```bash
   grep -o 'title="最新数据日期 \([0-9-]*\)，距今 \([0-9]*\) 天；该源自然更新频率=\(\w*\)"' out.html | sort -u
   ```
   Chao asked about one contradiction; the sweep surfaced 8 badges / 5 distinct cases and a second real bug.

### PITFALL: a wrong assertion left in a CODE COMMENT keeps the bug alive for months
The stale-badge function carried a comment I had written earlier: *「已实测 TIC 官方本身未出新月, 抓取链路完好」*.
It was false, and because it read as settled/verified it deterred re-investigation for ~5 months.
- **Never write "已实测/已确认 <external system behaves thus>" into a comment unless you actually
  queried that external system** — and stamp it with the date and the method.
- When such a claim is disproven, **correct the comment in place** (state the old claim, why it was
  wrong, the new evidence) rather than silently deleting it. Same for the reference file that
  propagated it.
- Own it in the report to Chao unprompted — 诚实优先于讨好. That's expected, not optional.


The root enabler of both bugs: the frequency badge was a **hardcoded string in the template** while the
lag was **computed at runtime** — the two never spoke, so a page could contradict itself indefinitely.
```python
FRESHNESS_SLA = {"country_ust": ("月度", 75), "credit_impulse": ("季度", 120)}
# build time: actual_lag > sla → red badge + WARN in build log + notify
```
- Derive the on-page frequency text from that table; do not hardcode it (same principle as
  「分组名/配色不得硬编码」).
- **Lag exceeding SLA should be triaged as "wrong source / API changed" FIRST**, not as "the publisher
  is just slow". The slow-publisher verdict requires positive proof from the publisher.
- **A page contradicting itself is the single highest-signal bug indicator**, and the one most likely
  to be missed by programmatic acceptance checks — each module passes its own checks in isolation.
  When two labels on one chart disagree, stop and investigate; that is exactly how this was caught.


## 第七种判据：同一 term 下混入了**异种工具**（不是断源，是口径污染）
2026-09-07,国债拍卖板块。Chao 只是问「这个有没有 cron」,对着他的截图核数时发现两条离群值:

| 期限 | 日期 | 规模 | 高位收益率 | 邻月名义券 |
|---|---|---|---|---|
| 10-Year | 2026-07-23 | **21.0B** | **2.438%** | 42.0B / 4.68% |
| 30-Year | 2026-02-19 | **9.0B** | **2.473%** | 25.0B / 5.22% |

规模腰斩 + 收益率只有一半 = **TIPS(通胀保值债券)**,它报的是扣通胀后的**实际收益率**,
与名义券根本不是一个口径,混进来会让「需求强弱」被误读。

**关键**:TIPS 的 `security_type` 同样是 `Note`/`Bond`、`security_term` 同样是 `10-Year`,
原有的 `st in ("Note","Bond") and term in KEY_TERMS` 过滤**结构上拦不住它**。

### 方法:不许凭数值猜券种,去官方 API 拉全字段做「可疑行 vs 正常行」对照
```python
susp = q("auction_date:eq:2026-07-23")   # 可疑
norm = q("auction_date:eq:2026-08-12")   # 同期限的正常行
for k in sorted(set(a) | set(b)):
    if str(a.get(k)) != str(b.get(k)):
        print(k, a.get(k), b.get(k))     # 差异字段里找判别式
```
差异表里直接跳出铁证 `inflation_index_security: Yes / No`(旁证:TIPS 行才有
`cpi_base_reference_period`、`index_ratio_on_issue_date`)。修复就是一行 `continue`。
- **先证明再改**:我一开始的判断只是「像 TIPS」。数值像 ≠ 是,官方若真没有判别字段,
  就只能按规模/收益率启发式过滤(脆弱,须标注)。是 API 恰好提供了权威字段才敢硬过滤。
- **泛化**:任何按「类别名」聚合的官方数据(债券期限、商品合约、席位类型)都要问一句
  ——**这个类别名下会不会装着两种不同的东西?** 找官方的显式判别字段,别靠名字。
  同源前例:COMEX 席位 `JPM(C)` 代客 vs `JPM(H)` 自营,按机构名聚合同样会混算。
- **发现渠道值得记**:这两条脏数据在页面上完全「正常渲染」,没有任何 badge 会报。
  是**逐条核对用户截图里的数字**时才露馅的。定期拿一列同类数值扫离群值(规模/收益率
  相差一倍),比任何 status 检查都更能抓出口径污染。

## Tooltips on tiny stretched sparklines (hit-band pattern)
Adding hover to mini charts drawn with `preserveAspectRatio="none"`: circles become ellipses and are
nearly unhittable. Use **transparent full-height `<rect>` bands**, one per data point, width = point
spacing, `x = X(i) - bw/2`.
- If the page already has a delegated tooltip handler (`document.addEventListener('mouseover', … closest('[data-tip]'))`)
  then **no JS change is needed at all** — emitting `data-tip="日期||数值单位"` is sufficient. Check for an
  existing delegation handler before writing any new JS.
- Feed it REAL values: thread the true unit through from config (`ind["unit"]`) instead of hardcoding,
  and thread real dates. If the data pipeline dropped dates (`spark = [v for _, v in pts]`), add a
  parallel `spark_d = [d for d, _ in pts]` at every return site rather than reconstructing dates.
- Degrade honestly: no dates available → emit `||value` (empty date half), never invent a date.
- Verify by counting: `grep -o 'data-tip=' out.html | wc -l` and assert per-chart hit-band counts equal
  point counts.

## PITFALL: bulk programmatic replace on indentation-sensitive Python
Doing a multi-site `str.replace()` over a `.py` file, an 8-space-indented pattern ALSO matched as a
suffix inside a 16-space-indented nested block → the replacement inserted a wrongly-indented duplicate
line → `IndentationError`. Batch replaces on Python must anchor on the FULL leading indentation, apply
the most-indented variant FIRST, and **always `py_compile` immediately after**. When it breaks, read
the surrounding 10 lines and delete the stray line surgically instead of re-running the batch.

## Deleting dead code: prove zero behavior change with a body-hash
When two definitions of the same function exist (v1 shadowed by a later v2), don't trust "it compiles".
1. `grep -oP '^def \K\w+' file | sort | uniq -d` to enumerate genuinely duplicated names.
2. Confirm the LAST definition is the one bound at the call site, and `grep -rn` across `src/` + `scripts/`
   to prove no external module imports the earlier one.
3. Record the md5 of the SURVIVING function's body **before** deletion.
4. Delete bottom-up by line range, then re-hash: identical md5 = byte-level proof of zero behavior change.
Also confirm output size didn't shrink after rebuild (page grew 77KB from the new tooltips — content intact).

## Embedded JSON payload silently `{}` — the multi-entrypoint parameter drop
Symptom Chao reported: KOL cards showed today's view fine, but clicking one opened a drill-down saying
「该 KOL 暂无已归档的历史观点记录」— for **every** person, while the data layer held 137 people / 2730 records.

Root cause: the repo has **two build entrypoints** — `src/build_dashboard.py` (dev, full args) and a
**2600-character inline `python -c "...generate(<30 args>)"` inside the cron job prompt**. The new
`kol_history=` argument was added only to the former. Cron therefore rendered `var DATA = {}`, so the
front-end could never find anything. Dev-machine acceptance was fully green; production was empty.

- **Any repo where cron holds its own long inline build command will drift.** Every new parameter has
  to be added in two places and eventually won't be.
- **Fix it inside the callee, not at each call site** — then all present and future entrypoints are
  correct by construction:
  ```python
  if not kol_history:                       # caller didn't pass it → self-load
      kol_history = ed.kol_full_history() or {}
      print(f"[dashboard] auto-loaded KOL history: {len(kol_history)} people")   # leave a log trace
  ```
- **Skeleton counts do not prove data presence.** `grep -c 'kol-drill'` returned 161 and
  `grep -c 'kd-mask'` returned 5 — all healthy — while the payload was `{}`. Assert on the DECODED
  payload:
  ```bash
  python3 -c "import re,json;h=open('docs/index.html').read();
  d=json.loads(re.search(r'var DATA = (\{.*?\});\n',h,re.S).group(1));
  print('people',len(d),'records',sum(len(v['h']) for v in d.values()))"
  ```
- **`window.X` returning undefined in the console does NOT mean the data is missing** — payloads
  declared inside an IIFE are closure-scoped and invisible on `window`. Reading `window.DATA` here
  reported 178 empty cards and 0 records, contradicting a drill-down that had just rendered 40 rows.
  Verify by parsing the built file, or by simulating a click and reading the resulting DOM.
- **ALL-ZERO console probes are a tool artifact until proven otherwise — never a finding.**
  `querySelectorAll('.kol-drill').length === 0` and `.cyc-item === 0` came back on a page whose source
  file demonstrably contained 184 and 24 of them. The evaluation had run against an empty context, not
  the page. Confirm the context is real BEFORE trusting any zero:
  ```js
  ({len: document.documentElement.outerHTML.length, title: document.title})
  // len ≈ 39 and title === "" → about:blank, every count from this probe is garbage
  ```
  This nearly cost a bad "fix": the zeros led me to inspect an f-string building
  `class="... {drill} data-kol="..."` and provisionally call it an HTML-attribute bug. Offline parsing
  showed the emitted markup was flawless. **Falsify the measurement before editing code that the
  measurement condemns** — and when a probe contradicts the artifact on disk, the artifact wins.
- **Offline parsing of the built HTML is the primary acceptance channel; the browser is secondary.**
  It has no context/caching failure modes and answers the real question directly — for a drill-down,
  the question is "does every clickable card resolve to a non-empty payload entry?":
  ```python
  drill = {H.unescape(m.group(1)) for m in
           re.finditer(r'class="[^"]*kol-drill[^"]*"[^>]*data-kol="([^"]+)"', h)}
  missing = [k for k in drill if not d.get(k, {}).get('h')]   # must be 0
  ```
  Also assert the converse — entities WITHOUT history must not be rendered clickable, or the user
  clicks into an empty modal, which is exactly the reported symptom.

- Add to the cron-vs-dev parity check: after any build-signature change, grep the cron job prompt for
  the new parameter name before declaring the feature shipped.

### 复发实例 2026-09-07:cron 的手写清单**整个漏掉了两个 fetcher**(不是参数漂移,是采集缺失)
Chao 报「中国央行流动性」「央行货币互换」两个板块线上空白。链路排查结果:
- fetcher 实测**完全正常**(中国流动性 5 条序列全到 09-07:OMO 551/DR007 545/两融 552;
  货币互换 60 笔)。`build_dashboard.py` 里两个都在。**数据层零问题。**
- 每日 cron 不走 `build_dashboard.py`,而是 prompt 内联一条**调 40+ fetcher 的手写巨型命令**。
  那份清单里 `fetch_china_liquidity` / `fetch_cb_liquidity_swaps` **压根没登记** →
  `generate()` 收到 `None` → 渲染成「数据未就绪」。
- 佐证清单已长期漂移:cron 里 `swaps=` 这个参数名被 BIS 黄金掉期(`bg`)占用了,
  央行互换根本没进参数表。

诊断一步到位(不要逐个猜):
```bash
F=$(ls -t ~/.hermes/cron/output/<job>/*.md | head -1)
for fn in fetch_china_liquidity fetch_cb_liquidity_swaps ...; do
  grep -q "$fn" "$F" && echo "✅ $fn" || echo "❌ $fn 未在 cron"
done
# 对照 build_dashboard.py,凡「一边有一边无」的都是待爆的雷
```
- **用 `build_dashboard.py` 重建只是止血**:板块当场填满,但**明天 cron 一跑又会空**。
  必须向 Chao 讲清「这次修好的是产物,不是流水线」,否则他会以为已经根治。
- 治本受阻于 cron prompt 里写明的「★不能改用 build_dashboard.py:它不读
  `data/ai_analysis_<date>.json`,会丢每日 AI 短评」→ 顺序必须是
  **先给 build_dashboard 补读 AI 短评 → 验证产出与 cron 版一致 → 再切 cron**。
- 建议同时装门禁(这已是同类问题第二次):比对 `dashboard.generate()` 的形参表 vs
  cron 实际传的 kwargs,缺哪个就 LOUD 报错——**把「记得两处同步」变成硬校验**,
  否则第三次、第四次一定还会发生。

#### 治本已落地(2026-09-07,Chao 批「乙方案」)——完整可复用流程

**① 先用集合运算量化差异,不要肉眼扫 17000 字符的 prompt。**
```python
job = next(j for j in jobs if j['name'] == '<job>')
cron_f = set(re.findall(r'\be\.(fetch_[a-z0-9_]+)\(', job['prompt']))
bd_f   = set(re.findall(r'\bed\.(fetch_[a-z0-9_]+)\(', open('src/build_dashboard.py').read()))
print('只有 cron 有(换过去会丢):', sorted(cron_f - bd_f))   # 必须为空才敢切
print('只有 builder 有(空板块根因):', sorted(bd_f - cron_f))
# kwargs 同理: 用 inspect.signature(dash.generate) 的形参表分别减两边实际传参
```
实测:cron 38 个 ⊂ builder 40 个,**反向差集为空** → 切换零损失。这一步把「敢不敢改」
从直觉变成可验证的判据。
**坑**:提取 kwargs 时注意调用别名——builder 里是 `dash.generate(`,cron 里是
`dashboard.generate(`。正则只认一种会得出「builder 少传 54 个参数」的荒谬结论
(它明明能渲染出全部板块)。**结论荒谬时先怀疑自己的测量,别怀疑代码。**

**② 反转发现:prompt 里那条阻止重构的警告本身是假的。**
cron prompt 写着「★不能改用 build_dashboard.py:它不读 `ai_analysis_<date>.json`,会丢每日 AI 短评」。
用 AI 文件里的**真实文本前 18 字做指纹**逐条查两份产物:

| | 旧产物(cron 版) | 新产物(builder 版) |
|---|---|---|
| reads(14 条) | **命中 0** | 14/14 |
| notes(20 条) | **命中 0** | 20/20 |
| conclusions(3 条) | **命中 0** | 3/3 |

**旧的内联命令其实一直没把 AI 短评渲染进页面** —— 那条警告保护的东西根本不存在,
新方式反而是第一次真正显示出来。
> 泛化铁律:**代码/prompt 里写的「不能做 X,因为会失去 Y」必须先验证 Y 当前是否真的存在。**
> 同一文件上方已有先例(注释里那句「已实测 TIC 官方未出新月」把真 P0 掩护了 5 个月)。
> 这类断言的成本极不对称:写一句零成本,却能让一个真正的改进被搁置数月。

**③ 补能力的实现要点**:`latest_ai_analysis(snap_date)` 纯读已落盘 JSON,不调 LLM/不联网,
约 12 行。找不到当天文件**不静默**:打印 ⚠️⚠️ 并交给既有的 `_rule_conclusions()` 兜底;
日期对不上也要喊(否则会拿昨天短评配今天数据而无人察觉)。

**④ 门禁的正确装法——先把传参改成 dict 再展开,否则门禁看不见。**
```python
gen_kwargs = dict(ai_reads=..., cn_liq=..., cb_swaps=..., ...)
assert_no_missing_kwargs(gen_kwargs)          # 与 inspect.signature 形参表逐一比对
out = dash.generate(snap, checks, hit, gstats, overall, **gen_kwargs)
```
写成 `dash.generate(a=a, b=b, ...)` 的话「漏传了哪个」从外部无从检查。
只**警告不中断**(位置参数与可选参数需排除),目的是让漏登记立刻可见,而不是让产物生不出来。
实跑输出 `✅ 门禁: generate() 全部 49 个数据形参均已传入`。

**⑤ 零回归验证是能否动 cron 的硬关卡**,判据不是「文件生成了」而是逐板块内容量没变少:
空状态标记计数(变多=回归) / 板块锚点 `id="sec-*"` 逐个存活 / 日期与 SVG 图元密度(缩水 >5% = 回归)。
跑出「23 板块全存活、空状态零增加、密度持平」才继续。**不达标就停下报告,不硬推。**

**⑥ 改 cron prompt 用脚本 + 自校验,不要手改 JSON。**
脚本内先断言「其它步骤未被误伤」(步骤 7/8 还在、KOL 快照/13F/BIS 命令还在)、
「新命令已插入」「旧巨型命令已移除」,全绿才写盘并自动备份 `jobs.json.bak_*`。
> 实操中这道自校验**当场拦下过一次**:我的新文案里引述旧警告时也含「不能改用 build_dashboard.py」
> 这句,导致「过时警告已删除」判定失败。校验条件写得太宽会误报——**改精确检测串,而不是放宽条件**。

写盘后必须复查 job 完整性:`enabled` / `schedule` / `next_run_at` / prompt 长度,
确认没把 job 写坏。改完 prompt 17371 → 14705 字符。

> 另见 `references/watchdog-and-run-verification.md`:如何判断「今天到底跑没跑」,
> 以及守护脚本自身可靠性的设计红线。

## "已经 push 过了" ≠ "线上是好的" — verify the LIVE artifact, not git state
Asked whether everything was done, I checked `git log origin/main..HEAD`, saw it empty, and nearly
reported the work as shipped. It wasn't. **On a repo whose cron rebuilds and pushes on its own
schedule, git being clean tells you nothing about what the live page contains** — the daily job had
pushed its OWN rebuild (generated by the buggy inline command), so origin was "up to date" while
Pages still served `var DATA = {}` and the 6-month-stale TIC numbers.

Always verify against the deployed artifact, asserting on decoded content rather than HTTP 200:
```bash
curl -s <pages-url> -o /tmp/live.html -w "HTTP=%{http_code} size=%{size_download}\n"
python3 -c "import re,json;h=open('/tmp/live.html').read()
m=re.search(r'var DATA = (\{.*?\});\n',h,re.S)
print('live payload:', len(json.loads(m.group(1)) if m else {}), 'people')
print('has fixed value:', 'as of 2026-06' in h)"
```
Corollaries:
- **A code-level fix does not reach production until the code is pushed** — even a self-healing
  fallback inside the callee only helps the cron once cron is running the new code. Until then every
  scheduled run regenerates and republishes the broken artifact, so an unpushed fix silently decays.
  Say this explicitly when asking for push approval: *"线上现在是坏的，明早 cron 会再生成一份坏产物"* —
  the deadline is decision-relevant information, not pressure.
- When reporting completion, state **local vs live** separately. "Fixed and verified" without naming
  which of the two was verified is the ambiguity that produced this near-miss.
- Repos with an autonomous cron push need `git log HEAD..@{u}` checked too — the remote can move
  underneath you between sessions without any human action.

## Answer "任务都做完了吗" by re-deriving the list, never from recall
Asked point-blank whether everything was finished, my in-context sense was "yes". Re-checking
surfaced (a) an unfinished dedup item that had been carried in the plan for two sessions and never
executed, and (b) the live-vs-git gap above. **Treat that question as a trigger to re-enumerate
against the artifact** — grep the built output for each promised property, diff the remaining-work
list against what's actually verifiable — and answer with an explicit split of
done / just-completed / still-open. Reporting "还没全做完，刚补上一项漏的" is the correct and expected
answer when true; a confident "都做完了" that a 30-second check would falsify is the failure mode.

## Acceptance checklist for the rebuild (run these, don't eyeball)
```
grep -c '2026-08-2[0-9]' out.html          # future dates → must be 0 (see caveat)
grep -o 'class="stale-badge[^"]*"[^>]*>[^<]*' out.html | sed 's/.*>//' | sort | uniq -c
grep -o 'data-tip=' out.html | wc -l       # tooltip coverage
md5sum dashboard/index.html docs/index.html # the two outputs must match
```
- **Decode every embedded JSON payload and assert record counts > 0** — skeleton/CSS-class counts pass
  even when the payload is `{}` (see the multi-entrypoint section above).
- **Cross-check each chart's claimed cadence against its computed lag.** Any chart whose own two labels
  disagree is a bug until proven otherwise; this is the check that would have caught the TIC issue
  months earlier.
- **For every source, print `latest observation date`, not just `fetched OK`.** Compare against the
  publisher for anything over its SLA.
- **Caveat that will fool you:** a rebuild running past midnight JST puts TOMORROW's date in the
  "生成 YYYY-MM-DD HH:MM JST" build stamp. That is NOT the future-date regression. Grep the surrounding
  context before declaring a regression — confirm 数据日期 still shows the true observation date.
- Long rebuilds (40+ live sources ≈ 5-8 min) must run `background=true` + `notify_on_complete=true`;
  `process action=wait` is clamped to ~60s per call, so expect to re-issue it several times.

## Reporting the audit back to Chao
- Lead with the verdict that overturns the assumption ("一个真断源都没有"), then the per-item breakdown.
- **Volunteer your own mistakes.** The 「疑似源中断」wording was something I had introduced earlier the
  same session; flagging and correcting it unprompted is expected, not optional.
- Before offering to push: check `git log --oneline HEAD..@{u}` — being behind origin means the push
  WILL be rejected, and same-file remote commits mean a possible conflict. Surface that as a
  precondition WITH options (rebase / local-commit-only / show diff) rather than pushing.
- Never push without explicit approval.

## Rebasing an audit branch onto a remote commit that touched the SAME files
Chao picking "1" (rebase and push) is the common follow-up. Sequence that worked cleanly:

1. **Anchor + backup first.** Record `git rev-parse HEAD` as the rollback point and dump the dirty
   worktree: `git diff > scratch/backups/<date>_prepush/worktree.patch`, plus a copy of any untracked
   data JSON. `scratch/` is gitignored so this never pollutes the commit.
2. **Commit local work BEFORE rebasing** — a dirty tree can't rebase. Write the real fix rationale
   into the message (why each P0 was a P0), not just a file list.
3. `git fetch origin && git rebase origin/main`, then triage conflicts **by file KIND**:
   - **Source files** → resolve on meaning. Every conflict here was the same semantic pair:
     remote "failure returns empty shell" vs mine "failure falls back to cached truth". Chao's 铁律
     makes that a one-way decision — take the cache-fallback side.
     In a REBASE the sides are inverted from what you'd expect: `--ours` = upstream/origin,
     **`--theirs` = your replayed commit.** Getting this backwards silently reinstates the bug.
   - **Generated artifacts** (`dashboard/index.html`, `docs/index.html`) → do NOT hand-merge or
     cherry-pick hunks. Take either side to clear the conflict, finish the rebase, then **rebuild
     from the merged code** and commit the regenerated output separately. Hand-merged HTML will
     disagree with the code that supposedly produced it.
   - **Data JSON** → diff semantically before choosing. The add/add conflict here differed only in
     `fetched_at`; panels/flows/as_of were identical, so taking the newer one was safe. Check
     structure, don't just look at differing md5s.
4. **Post-merge completeness check — the step that catches a silently-dropped fix.** After
   `rebase --continue`, `py_compile` everything and grep-count a sentinel for EVERY fix from BOTH
   sides (mine: `failed_years`, `_fallback(`, `spark_d`, `lastNObservations=2`, `_stale_badge`;
   theirs: `fetch_comex_inventory`). A rebase that "succeeds" can still have eaten a hunk.
5. Rebuild → re-run the acceptance checklist above → commit the artifact → push → **verify the live
   site**: `curl` the Pages URL with a cache-buster and confirm `md5sum` matches local `docs/index.html`.
   Push exiting 0 is not proof the site updated.

A useful self-check that the badge logic is data-driven rather than hardcoded: across rebuilds a
badge legitimately moved 🔴112天 → 🟡51天 because a new period actually landed. Point that out as
evidence when reporting.

## Feasibility gate: vetting a NEW chart request before building it
Chao's red line 「先证明免费路走通再做」 applies to every "帮我做一张 X 图". Run this gate FIRST and
report the verdict — do not start rendering and discover the data isn't there.

1. **Correct false premises in the request itself, immediately.** Asked for a "每天都能拿到数据" version
   of a fundamentals chart: FCF comes from 10-Q/10-K, **4 points a year — daily is impossible by
   construction**. Only market-priced series update daily. Restate the answerable question (here: "is
   the *field* consistently disclosed across filers?") instead of quietly building something weaker.
2. **Probe every candidate source live, then report coverage as a fraction** (e.g. 標準 FCF 17/19,
   lease-adjusted 12/19). Chao's conditional instructions ("有可靠源就做租赁版，没有就做标准版") can only
   be executed against a measured number, not a guess.
3. **HTTP 200 is not proof of data — read the body.** A FINRA endpoint returned 200 whose body was an
   OpenSSO **login page**. Status-code-only probing would have "confirmed" a source that doesn't exist.
4. **A number that computes is not a number that's valid.** Implied funding cost (`InterestExpense ÷
   LongTermDebt`) ran without error yet produced AMD **13100 %** and ORCL **0.00 %** (debt tag → 0), on
   fiscal years scattered 2021-2026. Sanity-band every derived metric before it reaches a chart, and if
   it fails, say so — **never launder a broken derived metric into a plausible-looking picture.**
   Also check it's even the right *concept*: a book-average funding cost is not a market credit spread.
5. **When the free path is genuinely closed, say so plainly and offer real substitutes** rather than a
   proxy that resembles the ask. For single-name credit spreads: rating-tier OAS proxy (daily, real,
   but shared per rating) + SEC-XBRL leverage metrics (full coverage) — and state the structural
   blockers outright (private companies have no public debt/FCF; many names have no 30-year bond).
   Never substitute equity volatility or implied funding cost for a credit spread.
6. **Multi-entity charts: never print one shared year header.** Fiscal years differ across filers
   (MSFT 06-30, ORCL 05-31, NVDA 01-25). Render each entity's own period end.

Source-family verdicts already established (don't re-probe from zero):
`references/free-macro-credit-data-sources.md` §③ SEC XBRL fundamentals + §④ what is NOT free.

## 延伸阅读(2026-10-06 新增, 两份实战文件)
- `references/data-freshness-silent-staleness-and-house-basis.md` — 「cron 标 ok ≠ 图是活的」三类静默停更(上游生产者停了/源头改发布格式解析器抓不到不报错/源头本来低频)、隔离跑 `tools/freshness_audit.py`、JPX 外资周流 xlsx 新格式、COMEX 只算 House(H) 口径。
- `references/sidebar-menu-order-equals-dom-order.md` — 侧栏菜单「跳动感」根因=关键词分组把远距板块合并；按 DOM 顺序分 run 根治，无头 Chromium 探针量化 y 倒退。
- SKILL.md 已贴近 100K 字符上限，再加内容一律走 references/，不要往 SKILL.md 正文塞。
