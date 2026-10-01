# COMEX 交割榜的口径细节：账户类型 C/H、吨换算、机构别名归一

Companion to `comex-per-firm-top10-and-cron-kwargs.md`（那篇讲怎么建 per-firm 榜单）。
这篇是 2026-08-23 Chao **连问三次**「这个图上没有表明是 C 还是 H」之后补的口径层。

---

## 1. ★★ ORG 列 = 账户类型，聚合时最容易被抹掉

CME `MetalsIssuesAndStopsReport.pdf` 的席位行长这样：

```
FIRM  ORG  FIRM NAME              ISSUED  STOPPED
167    C   MAREX                            1      ← Customer 客户盘
167    H   MAREX                     52            ← House   自营盘
690    C   ABN AMRO CLR USA LLC      13      9
```

- **C = Customer**：代客户清算，背后是基金/实物商/散户 → **不代表该机构的观点**
- **H = House**：自营盘，机构自己的钱 → **才是机构真实表态**

★ 同一家常同时有 C 与 H 两行。`cme_delivery_parser` **本来就解析了 `org` 字段**
（席位行判定条件就是 `re.fullmatch(r"\d{3}", ws[0])` 且 `ws[1] in ("C","H")`），
但下游 `build_issue_stop_firms.py` 聚合时只按机构名合并，把这一维度扔了。

→ **和 per-firm 那次是同一类错误：源头有，聚合时丢的。** 加字段前先读 parser。

### 实现：分项累计 + 未知不猜

```python
org = (s.get("org") or "").strip().upper()
if org not in ("C", "H"):
    org = "U"                       # 未知: 单列, 不猜
metals[metal][bd][nm]["i"] += iss
metals[metal][bd][nm]["i_" + org.lower()] = ... + iss
```

Notion 增量通道的 `Activity Note` **没有 ORG 字段**（只记了机构简称与数量）
→ 一律计入 `_u`，前端如实标「账户类型未知」，**绝不臆测归到 C 或 H**。

### ⚠️ 双通道合并要同步搬运分项

第一版只在 archive 段做了拆分，合并 Notion 段时仍是：
```python
metals[m][d][f]["i"] += v["i"]      # ← 只搬总量, 分项丢了
```
结果 **577 处 C+H+U ≠ 总量**。修法是把 6 个分项一起搬：
```python
for k in ("i_c","i_h","i_u","s_c","s_h","s_u"):
    if v.get(k): metals[m][d][f][k] = metals[m][d][f].get(k,0) + v[k]
```

**自洽断言必须做**（免费且能立刻抓到这类漏搬）：
```python
assert ic+ih+iu == i and sc+sh+su == s   # 每个 (metal,date,firm) 条目
```

### 读出来的真信号（说明这个维度值得做）

| 金属 | 交货 H% | 接货 H% |
|---|---|---|
| 黄金 | 40.3% | 44.4% |
| **白银** | 40.3% | **47.7%** ← 自营净囤银 |
| 铂金 | 35.5% | 34.0% |

个股反差更大（白银全期）：**JP Morgan 发货 96% 是客户盘、自营仅 1%**（它是通道，不是在表态）；
而 **Deutsche Bank 接货 81% 自营、Wells Fargo 68% 自营**。
→ 只看"谁交割最多"会严重误读 JPM。**榜单要优先看 H 占比高的机构。**

UI：每行机构名后挂 `H 81%` / `C 96%` / `? 20%` 徽章（紫=自营 / 蓝=客户 / 灰=未知），
每个窗口顶部再放一条 C/H 占比条。

## 2. 手 → 吨换算：先算量级再决定显示位数

Chao：「单位用吨」。合约规格（CME 官方规则手册，已联网核对）：

| 金属 | oz/手 | 1 手 ≈ |
|---|---|---|
| Gold (Ch.113) | 100 troy oz | 0.00311 吨 |
| Silver (Ch.112) | 5,000 troy oz | 0.1555 吨 |
| Platinum (NYMEX PL) | 50 troy oz | 0.00156 吨 |

`1 troy oz = 31.1034768 g`。

★ **换算前先跑一遍各窗口的最小值**，否则黄金短窗口会变成 `0.00` 一片：
```
全期: 金 460.7 吨 / 银 7,846 吨 / 铂 7.7 吨
最小窗口(铂金近一周) 0.479 吨   → 2 位小数够用
```
最终显示 `0.48 吨 (154 手)` —— **主显吨，括号保留原始手数**，可追溯不丢信息。

## 3. 机构别名裂开会让排名失真

做单位换算时顺带发现：**8 组机构名裂成了两个**
（`CME`/`Cme`、`Bofa Securities`/`BofA`、`Citigroup`/`Citi`、`PTG`/`Ptg Division Of Sgas`、
`Marex`/`Marex Spec`、`Wedbush`/`Wedbush Securities`、`Phillip`/`Phillip Capital Inc`、
`Plus500`/`Plus500Us Financial`）。

根因：未命中 `DISPLAY` 映射的机构走 `raw.title()` 兜底，
于是 `CME` → `Cme`、`BOFA SECURITIES`（无 INC 后缀）→ `Bofa Securities`。

**后果是排名一直是错的** —— BofA 被拆两半，实际是全期第 2。

修法：在 `display_name()` 出口加一层 `CANON` 归一（小写键 → 标准名），
`NOTION_ALIAS` 通道也要过同一张表：
```python
return CANON.get(name.lower().strip(), name)
```

验收：**总量必须一分不差**，只有机构数下降：
```
总量 406,994 → 406,994 ✅   机构 42 → 34   三金属守恒不变
```
★ 任何"合并/归一"操作，都用总量守恒来证明没丢数据。

## 4. 机构阵营说明：只写数据里真实存在的

Chao 要「说明哪些是什么利益集团」。做法是先把真实名单打出来：
```python
firms = Counter(f for m in d['metals'] for dt in d['metals'][m]
                for f,v in d['metals'][m][dt].items())
```
按归一后的 34 家分 6 组（清算所自身 / LBMA 美系 / LBMA 欧系 / 加日澳银行 /
非银 FCM 自营商 / 对冲基金），并**断言覆盖率 34/34、0 漏 0 编**：
```python
assert not (real - set(名单里写到的))     # 不漏
assert not (set(名单里写到的) - real)     # 不编造不存在的机构
```

必须点破的两条：**CME 是清算所自身席位不是市场参与者**（占黄金发货 38.6%）；
**非银 FCM 是代客清算，不能读成机构观点**。
