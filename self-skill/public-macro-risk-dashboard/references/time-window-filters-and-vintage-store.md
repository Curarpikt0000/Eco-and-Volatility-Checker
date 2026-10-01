# 时间窗口 filter：先查有没有历史，没有就建 vintage 机制

Chao 反复出现的一类需求：「这个也做一个 filter button，未来有了新的也应该用 filter」。
2026-08-22~23 在 Eco dashboard 上做了三次（COMEX issue/stop、BIS 季报、IMF 债务/公司债），
三次的答案完全不同 —— **关键是先判定数据源属于哪一类**。

---

## 判定：三类数据源，三种做法

| 类型 | 判定方法 | 做法 |
|---|---|---|
| **A. 历史已存在** | 数据文件里已有多期 | 直接渲染多 pane，纯前端切 display |
| **B. 只存最新一期** | fetcher 每次实时抓、不落盘 | **先建 vintage 存档**，攒够 2 期才有按钮 |
| **C. 时序连续** | 有 daily/weekly 序列 | 按时间窗口切片（当周/1月/3月/全部） |

★ **动手前先确认属于哪类**，别假设。BIS 那次我以为要重新抓取+翻译，
实测发现 `data/bis/reports.json` **已有 4 个季度、每期 6 条中文要点**，
只是 `_bis_section_html(bis_latest, ...)` 只渲染了 `latest_report()` 一份 ——
**改成接 `all_reports()` 即可，零采集成本**。

```python
d = json.load(open('data/bis/reports.json'))
for r in d['reports']:
    print(r['date'], r['summary_status'], len(r.get('summary') or []))
# 2026-06 ok 6 / 2026-03 ok 6 / 2025-12 ok 6 / 2025-09 ok 6  ← 4 期都在
```

## B 类：vintage 存档机制（`src/vintage_store.py`）

IMF debt/GDP 与美国公司债的 fetcher 都是**实时抓 API、不落盘**，
磁盘上没有任何历史 vintage → 想做「上一期」按钮时无米下锅。

机制：每次 build 时把当期快照存 `data/vintages/<name>/<period_key>.json` + `_index.json`，
攒够 2 期后板块自动出现 filter。

### ★ period_key 必须用「发布期」而不是「实绩年」

第一版我用 IMF 的实绩年做 key，得到 `2025-H1` —— **错的**。
IMF WEO 一年发两次，但实绩年一年内不变，两次发布会撞成同一个 key、
第二次覆盖第一次，**永远攒不出第 2 个按钮**。

```python
def period_key_debt_gdp(payload):
    # 发布期: 当前月 <=9 → 上半年发布(H1), 否则 H2
    y, m = today.year, today.month
    return f"{y}-H{1 if m <= 9 else 2}"        # 2026-H1 · 实绩2025
```

公司债是日频 → 按**月**存（`2026-08`），否则一年 365 个按钮。
**key 的粒度要匹配"用户会想对比的间隔"，不是数据本身的更新频率。**

### 诚实处理"只有一期"

今天存完各只有 1 期 → **诚实显示单期、不出按钮**，不要造假的"上一期"。
在 build 日志里打印 `已积累 N 期`，让人知道机制在跑。

## 挂进管线，两个地方都要

1. `build_dashboard.py` 里抓完数据后调 `vintage_store.save(...)`
2. **cron 步骤 6 走内联 `dashboard.generate` 不经过 build_dashboard** →
   需要额外单独跑一次存档调用，否则只有手动 build 才积累

（这是 `comex-per-firm-top10-and-cron-kwargs.md` §7 那个 kwargs 漏传坑的同族问题：
**任何加在 `build_dashboard.py` 里的新逻辑，都要检查 cron 内联路径是否覆盖。**）

## 前端实现：统一的 tab/pane 模式

三处 filter 用了同一套形状，可直接复用：

```python
_act = " xx-on" if k == 默认窗口 else ""
tabs.append(f'<button class="xx-tab{_act}" data-xx="{slug}" data-k="{k}">{label}</button>')
panes.append(f'<div class="xx-pane{_act}" data-xx="{slug}" data-k="{k}">…</div>')
```
JS 用 `data-*` 双键定位（`data-xx` 分组 + `data-k` 窗口），
这样同页多组 filter（3 个金属 / 2 张图）各自独立切换、互不影响。

数据量不大时（≤200 天）**把所有窗口一次性内嵌成多 pane，点 tab 只切 `display`**，
不做前端重算、不重新请求。

## 验收：数 pane、数行，不能只看"有没有渲染"

```
需求A(issue/stop 4窗口 × 金银):  cis-pane = 8;  柱数 1周=2 / 4周=8 / 13周=26 / 32周=64
需求B(3金属 × 4窗口):            tf-metal=3, tf-pane=12, tf-row=147 == 源JSON 147
BIS(4季度):                      bis-tab=4, bis-pane=4, 要点 24 条 = 4期×6条
```
★ 源 JSON 的行数与 HTML 的行数要精确相等，这是最强的"没丢数据"证明。
