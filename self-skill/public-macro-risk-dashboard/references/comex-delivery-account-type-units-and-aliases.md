# COMEX 交割数据的三个语义陷阱（C/H · 单位 · 机构别名）

Realized 2026-08-22 on `Comex-Daily-Report/src/build_issue_stop_firms.py` +
`Eco-and-Volatility-Checker`。三个问题都是 Chao 看图时发现的，都属于
「数据能跑通但语义是错的」——这类 bug 不会报错，只会让人读出错误结论。

---

## 1. ★ ORG 列 = 账户类型 C/H，绝不能合并

CME 的 `MetalsIssuesAndStopsReport.pdf` 每行席位是这样的：

```
FIRM  ORG  FIRM NAME              ISSUED  STOPPED
167    C   MAREX                            1     ← Customer 客户盘
167    H   MAREX                     52           ← House 自营盘
```

- **C = Customer**：代客户清算，背后是基金/实物商/散户 → **不代表该机构观点**，它只是通道
- **H = House**：自营盘，机构用自己的钱 → **才代表机构的真实判断**

**同一家常同时有 C 和 H 两行。** 只按机构名聚合会把这个区分彻底抹掉。

实测出来的反差极大（白银全期）：

| 机构 | 行为 | 真相 |
|---|---|---|
| JP Morgan | 发货 9,702 手 | **96% 是客户盘**，自营仅 1% → 是通道不是表态 |
| Deutsche Bank | 接货 4,913 手 | **81% 自营** → 真在用自己的钱囤 |
| Wells Fargo | 接货 6,881 手 | **68% 自营** |

整体口径：白银**自营接货 47.7% vs 自营发货 40.3%** —— 做市商在自营净囤银。
只看总量榜完全读不出这一层。

**解析器本来就抓了 `org` 字段**（`cme_delivery_parser.py` line ~110 已有
`s["org"]`），是下游聚合时丢的。→ 教训同 per-firm：**先读上游解析器，
别假设数据不存在。**

### 落地方式

聚合时按 `i_c / i_h / i_u` 与 `s_c / s_h / s_u` 分列累计，`i`/`s` 保留为总量：

```python
org = (s.get("org") or "").strip().upper()
if org not in ("C", "H"):
    org = "U"          # 未知: 不猜, 单列
metals[metal][bd][nm]["i"] += iss                    # 总量
metals[metal][bd][nm]["i_" + org.lower()] = ... + iss  # 分项
```

### ★ 双通道合并时必须同时搬运分项（本次踩到）

archive PDF 段有精确 C/H；Notion 增量段的 Activity Note **没有 ORG 字段**。
第一次跑完出现 **577 处 `C+H+U != 总量`**，根因是合并循环只搬了 `i`/`s`：

```python
# 错：分项丢了
metals[m][d][f]["i"] += v["i"]
metals[m][d][f]["s"] += v["s"]

# 对：分项一起搬
for k in ("i_c","i_h","i_u","s_c","s_h","s_u"):
    if v.get(k):
        metals[m][d][f][k] = metals[m][d][f].get(k, 0) + v[k]
```

**Notion 段一律计入 `u`（未知），绝不臆测归到 C 或 H**，前端如实标 `?`。
金/银约 19-22% 是未知段，这个数字要在图注里写出来。

**验收断言**（必跑）：
```python
assert i_c + i_h + i_u == i  and  s_c + s_h + s_u == s   # 逐行
```

---

## 2. 单位：手 → 吨（Chao 明确要求）

Chao 要吨，因为要跟库存/产量口径直接对比。CME 官方合约规格（已联网核对
Chapter 112/113 + NYMEX PL）：

| 金属 | oz/手 | 吨/手 |
|---|---|---|
| Gold | 100 | 0.00311 |
| Silver | 5,000 | 0.15552 |
| Platinum | 50 | 0.00156 |

`1 troy oz = 31.1034768 g`（精确值）→ `吨 = 手数 × oz/手 × 31.1034768 / 1e6`

**换算前先算量级，别直接改。** 金 1 手才 0.003 吨，短窗口可能显示成 `0.00`。
本次实测最小值是金-日 top1 = 0.479 吨，够用；如果某维度会退化成 0.00，
应改用 kg 或保留更多小数。

**保留原始手数在括号里**（`0.48 吨 (154 手)`）—— 可追溯到原始 PDF。

---

## 3. 机构别名裂开 → top10 排名失真

未命中 DISPLAY 映射的名字走 `raw.title()` 兜底，把 `CME` 变成 `Cme`；
加上 PDF 内同一家有多种写法，实测 8 组裂开：

```
CME/Cme · Bofa Securities/BofA · Citigroup/Citi · PTG/Ptg Division Of Sgas
Marex/Marex Spec · Wedbush/Wedbush Securities · Phillip/Phillip Capital Inc
Plus500/Plus500Us Financial
```

后果：**BofA 被拆两半，全期排名一直是错的**（实际第 2）。

解法：在 `display_name()` 出口加一层**大小写无关的最终归一** `CANON`，
两条通道（archive + Notion）都经过它：

```python
return CANON.get(name.lower().strip(), name)
```

**验收必须证明总量没丢**：
```
总交割量 406,994 → 406,994 一分不差；机构 42 → 34（合并 8 个）
```
机构数变少 + 总量不变 = 合并正确；总量变了 = 合错了。

---

## 4. 通用教训

- **「数据能跑通」≠「语义正确」**。C/H 合并、别名裂开、单位不直观，
  三个都不报错，只会让人读出错的结论。
- 每次动交割数据，跑这三条断言：①席位加总 == PDF TOTAL ②总发 == 总接
  ③C+H+U == 总量。三条全过才算修好。
- 修完要用**真实 top1 的具体数字**向用户展示，而不是说「已修复」。
