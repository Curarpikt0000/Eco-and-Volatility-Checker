# 重建日志里的「跳过」行 = 缺陷，不是噪音；以及双入口 import 路径陷阱

2026-08-31，Chao 报「COMEX/上海库存 + GLD/SLV ETF 停在 8-21」。查完发现是**两件独立的事**，
其中一件根本不用改代码，另一件是我在排查过程中顺手抓出的**真回归**。
这个组合本身就是本文的价值：报障的那个症状和真正的 bug 不是同一个。

## 一、面板看着「停更」的第三种成因：产物生成时刻早于上游更新时刻

已有 `references/data-source-staleness-triage.md` 归纳了两种成因（源接错 / 阈值设错）。
本次是第三种，两者都不是：

- 上游 `curarpikt0000.github.io/comex-inventory-charts`（Chao 名下另一个 agent 维护的 repo）
  确实曾停更，但**当天 15:00 已被那个 agent 修好**。
- 我方抓取链路一直正常，且有缓存回退保护（抓不到就回退缓存真值 + 标 `stale_days`）。
- `docs/index.html` 是当天 **14:28** 生成的 —— 比上游 15:00 的更新早了半小时。
  所以页面上是 8-21，而实跑 fetcher 得到 `status=ok / as_of=2026-08-28`。

**判定顺序（改代码之前必须走完，否则会去修一个不存在的 bug）：**

1. `curl` 上游页面，抓头部的「更新：」时间戳和最新数据点日期 → 上游到底新不新？
2. 直接实跑本项目的 fetcher（不经 dashboard），看 `status` / `as_of` / 序列末点 →
   我方抓取到底通不通？`status='ok(缓存)'` + `stale_days` 才是我方降级；`status='ok'` 就是通的。
3. 比 `ls -l docs/index.html` 的 mtime 与上游更新时刻 → 是不是单纯产物旧了？
4. 三步都过还不对，才是真 bug。

本次 1~3 步就结案：**零代码改动，重建一次即可**。跨 agent/跨 repo 的上游，
「它坏了」和「它已经修好了只是我还没重建」长得一模一样 —— 先验证再动手。

## 二、★重建日志的每一行「跳过 / skip」都要当缺陷追到底

重建时日志里混着两行：

```
[dashboard] BIS 跳过: No module named 'src'
[dashboard] vintage 存档跳过: ModuleNotFoundError: No module named 'src'
```

`rc=0`、其余 40+ 板块全绿、页面照常产出 —— **BIS 卡片被静默降级成
「最新 BIS 报告摘要待更新（daily cron 扫描中，抓不到不编造）」占位文案**。
那句占位文案是我们自己写的诚实降级话术，恰恰因此它看起来完全正常，
不 diff 前后 HTML 根本发现不了。本地 BIS 数据其实完好（2026-06/03、2025-12/09 共 4 期摘要）。

**根因：同一个模块被两种入口调用，import 写法只兼容其中一种。**

- 文件顶部只有 `sys.path.insert(0, os.path.dirname(__file__))` → 只把 `src/` 放进路径。
- 但文件内部两段写的是 `from src import bis_reports` / `from src import vintage_store`（包路径写法）。
- `python -m src.build_dashboard`（cron 用）→ 项目根在 `sys.path`，能解析，正常。
- `python src/build_dashboard.py`（手工重建常用）→ 项目根不在，`ModuleNotFoundError`。
- 两段都被 `try/except Exception` 包着，只打印一行「跳过」，于是**只在手工重建时静默丢板块**。

修复（最小 diff，两种入口都能跑）：

```python
sys.path.insert(0, os.path.dirname(__file__))
# 本文件内部有 `from src import ...`(包路径写法)，入口 `python src/build_dashboard.py`
# 只把 src/ 放进 sys.path → ModuleNotFoundError: 'src' → 板块被 try/except 静默打空。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

验证要**隔离验证再全量**：先 `from src import bis_reports; bisr.latest_report()`
确认能读出 4 期摘要，再跑全量重建。别一上来就跑 10 分钟的全量。

### 可复用的规则

- **`try/except` + 一行「跳过」= 静默降级出口。** 这类代码在本项目遍地都是（每个板块一段），
  它保证了「一个源挂掉不拖垮整页」，代价是**缺陷会伪装成正常输出**。
  因此每次重建后必须：`grep -E "跳过|skip|失败|ERROR" <build.log>`，
  **逐行判定成三类之一**：(a) 真断供（预期空白，可接受）、(b) 代码/环境缺陷（立刻修）、
  (c) 可选板块（确认后归档）。留着不判定 = 下次还是看不见。
- **多入口模块禁止混用 import 写法。** 同一文件里要么全用同级 `import x`，
  要么全用 `from src import x` 并保证所有入口都把项目根塞进 `sys.path`。
  自查：`grep -n "from src import\|^import src" src/*.py`，命中的文件必须两种入口都实测跑一遍。
- **前后 diff 产物比读日志更硬。** 本次是 `git diff -U0 docs/index.html` 一眼看到
  BIS 卡片从「4 个季度 tab」变成「待更新」占位，才确认这是回归而不是本来就这样。
  重建后固定动作：`git diff --stat` + `git diff -U0 docs/index.html | grep '^[-+]' | cut -c1-200`。

## 三、操作性备注

- `src/build_dashboard.py` 全量重建 **> 180s**（本次 ~4 分钟，要抓几十个外部源），
  超过前台 terminal 上限。用 `terminal(background=True, notify_on_complete=True)`，
  日志重定向到 `scratch/build_<time>.log`，再 poll。别用前台硬等，也别因为 timeout 就以为失败。
- 重建前先备份产物：`cp docs/index.html scratch/backups/index.html.pre_<tag>_$(date +%Y%m%d_%H%M)`，
  这样任何板块被打空都能立刻 diff 出来并回退。
- `dashboard/index.html` 与 `docs/index.html` 是硬链接（同 inode），一次 generate 两边都更新，
  无需 cp；`ls -l` 看到大小/mtime 完全一致是正常的，不是没生成。
