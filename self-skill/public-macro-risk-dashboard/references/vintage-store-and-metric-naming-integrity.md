# 指标口径正名 + vintage 期次存档层

两个 2026-08-22 从 Chao 提问里长出来的通用模式。共同主题：**dashboard 上的
每个标题都是一个断言，断言错了比没有更糟**；以及**「只有最新一期」的数据源
如何在不编造历史的前提下积累出可切换的期次**。

---

## A. 指标口径正名：carry ≠ basis trade（Chao 主动质疑，联网核实后确认他对）

Chao 问：「你网上搜一下套利空间我这么计算正确么，是不是应该计算期货和现货？」
—— 他是对的，我们的图名不副实。

### 事实（已联网核实，三处权威源一致）

- **Fed FEDS Notes 2024-03-08**："the position consists of a repo-financed
  purchase of a Treasury security and the **simultaneous sale of a corresponding
  Treasury futures contract**… net of carry and financing costs."
- **ScienceDirect《Hedge funds and the Treasury cash-futures basis trade》**：
  "the basis is defined as the difference between the **implied repo rate** and
  the available **market repo rate**."
- Dallas Fed 2025-07-15：讨论 funding 冲击对该交易的敏感度。

**真 basis trade 公式**：
```
IRR = [(发票价格 − 债券脏价) / 债券脏价] × (年天数 / 距交割天数)
      发票价格 = 期货价 × 转换因子 + 交割日应计利息
Net basis ≈ IRR − 实际回购利率(SOFR / term repo)
```

### 我们的图实际算的是什么

`国债收益率 − SOFR` = **现券持有 carry（单腿）**，文献里叫 cash-repo spread。

| | 我们的图 | 真 basis trade |
|---|---|---|
| 腿数 | 1（只有现券） | 2（现券多 + 期货空） |
| 久期风险 | **仍暴露** | 被期货腿对冲掉 |
| 数据需求 | DGS10 − SOFR（有） | 期货价 + 转换因子 + CTD 券（无，CME 反爬/商业授权） |

### 处理（Chao 选 A 方案）

**改名不改数**，并在图注写全口径差异：
- 「② 套利 Carry 空间 / Basis Trade Carry」→「② **持券 Carry** / Cash Carry」
- section 标题里的「Carry 空间」→「持券 Carry」
- 图注补：IRR 完整公式、双腿 vs 单腿、久期是否被对冲、为何免费源做不了真 net basis
- 保留一句「与真 basis trade 的强平压力**同向**（融资成本是共同分母），
  故仍是有效的预警代理」—— 说明它仍有用，不是废图

### 可复用的判断法则

**用户质疑一个指标算法时，先联网找权威定义，再对照我们的实现。**
如果名不副实：
- **A 改名不改数**（零成本、立刻诚实）← 多数情况选这个
- B 补真指标（先算清数据可得性，拿不到就别承诺）
- C 改名 + 加可得的代理指标

**绝不做的**：为了保住好听的名字而含糊过去。指标名是断言。

---

## B. vintage 期次存档层（`src/vintage_store.py`）

### 问题

Chao：「这个如果有过去一次的也同样做一个 filter button，未来有了新的也应该
利用 filter button」。但 IMF debt/GDP 与公司债的 fetcher **每次实时抓 API、
不落盘** → 磁盘上没有任何历史 vintage → 做不出「上一期」按钮。

**这与 BIS 的情况不同**：BIS 本来就有 4 期存档在 `data/bis/reports.json`，
所以能立刻做 filter。**动手前先查数据是否落盘。**

### 解法：通用存档层，今天建机制、未来自动积累

`src/vintage_store.py`：
```
data/vintages/<dataset>/<period_key>.json   # 每期一份快照
data/vintages/<dataset>/_index.json         # 期次索引(降序)
```

核心 API：`save_vintage(dataset, key, payload, label, max_keep=8)` /
`load_vintages(dataset, limit)` / `vintage_count(dataset)`

### ★ period_key 的设计是关键（踩过一次）

**必须用「发布期」而非「数据年份」**，否则会撞键覆盖、永远攒不出第 2 期：

| 数据集 | 错误 key | 正确 key | 理由 |
|---|---|---|---|
| IMF debt/GDP | `2025-H1`（实绩年） | `2026-H1`（发布期） | 实绩年一年内不变，一年两次发布会撞成同一键 |
| 公司债（日频） | `2026-08-20`（日） | `2026-08`（月） | 否则一年 365 个按钮没法看 |

公司债的月键要取**数据自身 `as_of` 的年月**（不是今天），数据滞后时期次才准。

### ★ 纪律

- **只存 `status == "ok"` 的期**，抓失败一律不存，避免空壳期次污染历史
- **今天只有 1 期 = 诚实显示 1 期、不出按钮**。绝不编造历史凑按钮
- 同键覆盖（幂等）—— 同期数据被修订属正常（如 IMF 修订历史值）
- `max_keep` 裁剪，防止无限膨胀

### 接入

挂进 `build_dashboard.py` 取数之后，每次 build 自动存一期：
```python
_okv, _why = _vs.save_vintage(_ds, _k, _payload, label=_lbl)
print(f"[dashboard] vintage[{_ds}]: key={_k} … 已积累 {_vs.vintage_count(_ds)} 期")
```
★ 别忘了同步加进 **cron 的内联 kwargs**，否则只有手动 build 会积累。

---

## C. 免费源边界要实测后再回答（不要凭印象说"没有"）

Chao：「各个级别的债券总量给我放上去一下」。

**实测过程**（这个动作本身值得复用）：
1. 查现有 `outstanding` → 只有 2 档 Fed Z.1 全市场口径，非分评级
2. 抓 SIFMA `US-Fixed-Income-Securities-Statistics-SIFMA.xlsx` → 有 Outstanding /
   Issuance 两个 sheet，但 **Corporates 只有单一合计**（1Q26 ≈ $11.74T），不分评级
3. 确认 FRED 上带 `TRIV` 的分评级序列是**总回报指数**（价格点位），不是余额

**结论**：分评级未偿余额属 ICE/Bloomberg 授权，免费源确实拿不到。

**怎么交付**：把能验证的全市场口径**放到显眼位置**（原先渲染在页面最底部，
用户截图根本看不到 → 提到评级表正下方），并把「为什么没有分评级总量」
连同实测证据写进页面。**用户要的东西拿不到时，给出「已实测的边界 + 能拿到的
最接近口径」，比一句"没有"有用得多。**
