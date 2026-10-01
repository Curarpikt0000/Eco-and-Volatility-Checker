# 静默空板 & 上游 feed 复检 — 两类「看起来没数据其实有数据」的故障

Companion to `dashboard-data-integrity-audit.md`. That file triages **wrong / stale values**.
This one triages the case where a section renders an honest-looking **"暂无数据"空壳** while the data
is actually sitting on local disk or already fixed upstream. Both cases hit Eco-and-Volatility-Checker
on 2026-08-31 in the same rebuild, and both would have been re-broken by tomorrow's cron.

---

## ① `try/except` 包住一个 section = 会自我静默的空板

The build script isolates each section:
```python
try:
    ...build section...
except Exception as e:
    print(f"[dashboard] BIS 跳过: {e}")     # ← the ONLY trace
```
Good for isolation (one dead source can't kill the page), **terrible for visibility**: the section still
renders, just as a polite empty shell —「最新 BIS 报告摘要待更新（daily cron 扫描中，抓不到不编造）」—
and a reader reasonably concludes "upstream is quiet." Here the upstream was fine: **four quarters of BIS
summaries (2026-06 / 2026-03 / 2025-12 / 2025-09) were on local disk the whole time.**

### 本次根因：sys.path 形状不匹配，不是数据问题
The repo mixes two import styles:
- most modules: flat `import external_data as ed` — works because the entrypoint inserts `src/`
- two blocks: package form `from src import bis_reports` / `from src import vintage_store`

Run as `python src/build_dashboard.py`, only `src/` is on `sys.path`; the **project ROOT is not** →
`ModuleNotFoundError: No module named 'src'` → swallowed by the `except` → card blanked.

Fix = 2 lines at the entrypoint, not a rewrite:
```python
sys.path.insert(0, os.path.dirname(__file__))                                    # existing: src/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # add: project root
```
Both styles then resolve, and a future `from src import …` added by any other entrypoint also works.
This is the same failure FAMILY as the「多入口参数漏传」case in the companion file: a build path that
works on one entrypoint and silently degrades on another.

### 由此固化的纪律
1. **每次重建都读 build log 的 `跳过 / skipped / 失败` 行，每一条按缺陷处理直到定性。** They are not
   informational. Put this in the acceptance checklist next to the grep counts:
   ```bash
   grep -nE '跳过|skipped|失败|Error|Traceback' scratch/build.log   # 期望 0 行；非 0 必须逐条给出verdict
   ```
2. **先证明「数据不存在」，再相信空壳。** One isolated import + fetch settles it in seconds:
   ```bash
   .venv/bin/python -c "import sys,os;sys.path.insert(0,'src');sys.path.insert(0,os.path.abspath('.'));
   from src import bis_reports as b;r=b.latest_report();print(r.get('date'),len(r.get('summary') or []))"
   ```
   Returned `2026-06 / 6 bullets` → instantly reclassified「上游没出新的」→「我们的 bug」。
   Same reflex as 「先单独跑 fetcher」 in the companion file.
3. **验收要断言空壳标记 ABSENT，而不只是 section 存在。** Count the shell string and the populated
   widget separately. After the fix: 空壳 div gone, `bis-tab` ×11 with 4 quarter tabs.
   ⚠️ **坑**：空壳的 CSS 类名在 `<style>` 块里还会出现一次，`grep -c 'bis-na'` 返回 1 会被误读成"还没修好"。
   要么 grep 空壳的**整句中文**，要么 grep 发射出来的 `<div class="...">` 形态，不要只 grep 类名。
4. **`git diff` 是生成物上的免费回归探测器。** The broken rebuild's diff carried an extra `-/+` pair
   replacing the BIS block; after the fix that pair **vanished from the diff entirely**, proving the
   section was byte-identical to last-known-good HEAD. 若一次重建的 diff 动了你没打算改的 section，
   先解释清楚再 commit。

---

## ② 上游 feed「停更了」——先看时钟，再看代码

Chao relayed that a sibling project's feed (`comex-inventory-charts`, maintained by **another agent**)
had frozen at 2026-08-20, then later: *"我问了另外一个agent 刚刚修复了…这个问题你先再试一下"*.
The correct whole response is a **re-probe, not a code change**.

### 复检三步（顺序不能换）
1. **打上游页面，读它自己的更新戳 + 最新数据点**
   ```bash
   curl -sS -m 40 <upstream-url> -o /tmp/up.html -w "http=%{http_code}\n"
   grep -oE "更新[^<]{0,40}|20[0-9]{2}-[0-9]{2}-[0-9]{2}" /tmp/up.html | sort -u | tail
   ```
   → 页面标「更新：2026-08-31 15:00 JST」，点位到 08-28。
2. **隔离跑我方 fetcher，看 status 字段**——这两个状态就是全部诊断：
   - `status='ok'` + `as_of` 推进 = 上游真修好了，我方链路正常
   - `status='ok(缓存)'` + `stale_days=N` = 还在吃缓存，上游没通
3. **比对「产物构建时间」vs「上游发布时间」**——`build 14:28 < upstream 15:00`，
   **纯粹是时序错开，不是 bug**，唯一该做的动作是重建。
   直接告诉 Chao「不是我方 bug，只需重建」是诚实答案，也省掉一次无意义的修改。

### 配套认知
- **缓存回退设计在这里自证了价值**：`_fallback()` 遇上游不可用时**返回缓存真值 + `stale_days` 标注**，
  而不是返回空壳。所以上游停更 10 天只损失了新鲜度，不是整条 114 点曲线消失。
  任何**不由自己控制的跨项目 feed** 都该配这个模式（对应 Chao 铁律：抓不到标注，绝不空值覆盖真值）。
- **另一个 agent 说"修好了"属于自报，必须对着 live 页面验证**——同「子 agent 自报数字不可信，判据只有
  查库/查源」规则。Chao 转述的也是转述，不构成证据。
- 复检结束后要把**两件事分开报**：上游那件（无需改码）和顺带发现的本地那件（真 bug）。
  混在一起说会让 Chao 以为「上游修好了顺便也把我们的 bug 带好了」。

---

## 收尾时该主动提的那一条
两个 bug 都是**靠肉眼扫 build log 才发现的**——异常被 `try` 吞成一行「跳过」，明天 cron 再跑一次
会一模一样地静默空掉，没有任何人会知道。所以收尾报告里应当主动提议（而不是等 Chao 想到）：

> 加一个收尾自检：重建后扫关键板块，凡渲染成空壳/「待更新」的就在日志里 LOUD 报出来
> （不改渲染逻辑，只加告警）。

这与 Chao 的一条既有认知同源：**「给别人定了标准、自己却靠人工检查执行，迟早会在自己身上破例；
把标准写成代码里的硬门禁，比写进文档里可靠」**。本次「靠我这次刚好读了 log」正是那种迟早会破的人工门禁。
