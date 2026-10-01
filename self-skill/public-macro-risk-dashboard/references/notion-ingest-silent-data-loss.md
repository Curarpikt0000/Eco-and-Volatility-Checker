# Notion 回填/增量同步的「静默型」数据事故 —— 六个真实 bug + 验收闸门

来源：2026-08-26 Eco-and-Volatility-Checker「Hermes 独立线」18 张 HDB_* 表建表 + 6116 行回填。
本轮一次抓出 **6 个 bug，全部是静默型**：不报错、不崩溃、exit code 0，只是悄悄少数据或多数据。
这类 bug 是本类流水线（本地数据源 → 抽取器 → Notion 表）的**主要失效模式**，必须靠验收闸门抓，
靠"跑完没报错"是抓不到的。

---

## ★★ 红线一：抽取器绝不调用 fetcher，只读缓存文件

**事故**：探测 11 个 fetcher 能拿到什么数据时，直接 `ed.fetch_foreign_flow_japan()`。
该 fetcher 抓取失败后**把自己的缓存文件覆写成 `{"status":"未获取"}`**，
`data/foreign_flow_japan.json` 里 53 周真实 JPX 数据被抹掉。靠 `git checkout` 才救回。

这正是本项目 AGENTS.md 早就记载的「空值覆盖真值」陷阱 —— 我知道这条规则，
但没意识到**"只是探测一下"也会写磁盘**，于是踩了进去。

**规则**：
- 抽取器（ex_* 函数）一律 `json.load(cache_path)`，**绝不 import 后调 fetch_\***。
- 探测 fetcher 结构时，先 `git status` 记录基线；探测后立刻复查有没有文件被改。
  能读缓存文件推断结构就别调函数。
- 缓存 `status != "ok"` 时返回 `[]`（0 行），不要写入 —— 但**也不要触发重抓**。

```python
def ex_foreign_flow():
    """★绝不调用 ed.fetch_foreign_flow_japan()：抓取失败会覆写缓存为 status=未获取。"""
    p = os.path.join(ROOT, "data", "foreign_flow_japan.json")
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding="utf-8"))
    if (d.get("status") or "") != "ok":
        return []          # 只读，不重抓
    ...
```

**副产品**：改读缓存后，这张表从"无数据源"变成有 53 行 —— 之前判它没数据本身就是误判。

---

## ★ 红线二：title 不唯一的表，幂等键必须加字段

**事故 A（COT）**：幂等键只用 title（日期）。COT 同一 as_of 有 gold/silver 两行。
样板阶段写了 3 行恰好含 `2026-06-09 gold`，全量跑时 `2026-06-09` 已在 `have` 集合里，
**silver 被静默跳过**。实测丢 1 行。

**事故 B（HOLDINGS）**：同季同标的可以有「清旧仓 + 建新仓」两个真实事件
（Berkshire 2026-06-30 BAC：新建 483,394,015 股 / 清仓 0 股，SEC issuer 名称变体）。
只按 title 去重，下次增量跑会漏掉其中一条。

**规则**：声明式补充键字段，且**本地键与 Notion 键必须同构**（两个函数各写一遍必错）。

```python
DEDUP_EXTRA = {
    "HDB_COT": ["品种"],
    "HDB_HOLDINGS": ["标的", "持股数"],
}

def _field_text(v: dict) -> str:
    """把任意属性值(本地构造 或 API 返回)压成可比字符串 —— 两侧共用这一个函数。"""
    if not v: return ""
    if "select" in v:  return str((v.get("select") or {}).get("name", ""))
    if "number" in v:
        n = v.get("number");  return "" if n is None else repr(float(n))
    if "rich_text" in v:
        return "".join(x.get("plain_text") or (x.get("text") or {}).get("content", "")
                       for x in v.get("rich_text") or [])
    if "date" in v:    return str((v.get("date") or {}).get("start", ""))
    return ""
```

**判定法**：某表的 title 能不能在同一天/同一期出现两次？能 → 必须进 `DEDUP_EXTRA`。

---

## ★ 红线三：本地构造的 payload ≠ Notion 返回的结构

`kns.plain()` 之类的解析函数是为 **Notion API 返回**写的（富文本项带 `plain_text`）。
本地构造的是 `{"type":"text","text":{"content":...}}`，**没有 `plain_text` 键** → `KeyError`。

两种结构必须分开取标题：

```python
def _local_title(props, title_field):     # 本地构造
    return "".join(x["text"]["content"] for x in props[title_field]["title"])

def _notion_key(props, title_field, tbl): # API 返回
    parts = [kns.plain(props.get(title_field))]
    ...
```

---

## ★ 红线四：字段路径读错 → 整表静默 0 行

两次都发生在"我以为字段叫什么"而没实测：

| 表 | 我读的 | 实际 | 后果 |
|---|---|---|---|
| HDB_HOLDINGS | `institutions[].holdings` | 该键**不存在**；数据在 `top_holdings` / `new_buys` / `exits` 三个桶 | 整表 0 行 |
| HDB_YIELDS | `series.<k>.value` | 该键不存在；序列在 `series.<k>.points = [[date, val], ...]` | 260 行只出 1 行 |

`.get()` 链条对不存在的键返回 None/[]，抽取器安静产出 0 行，**没有任何报错**。
更糟的是我据此向用户断言"本地无历史序列，需从 FRED 重抓" —— 是错的，数据一直在本地。

**规则**：接一个新数据源前，**先 dump 真实结构**再写抽取器：

```python
d = json.load(open(path)); print(list(d))
for k, v in d.items():
    if isinstance(v, list):  print(f"{k}: list[{len(v)}]", json.dumps(v[0])[:200])
    elif isinstance(v, dict): print(f"{k}: dict", list(v)[:8])
```
抽取器产出 0 行时，**先怀疑字段路径，别急着标 "无数据源"**。

---

## ★ 红线五：同一逻辑记录出现在多个桶 → 重复计数

13F 的 `top_holdings` 和 `new_buys` 会装**同一笔持仓**（新建仓大到进前十）。
实测 230 处重复（`new_buys+top_holdings` 195 例、`exits+top_holdings` 25 例）。
留着的话，任何按机构汇总的分析都会**把同一笔算两遍**。

修法：去重键含 `action + shares`，同一笔只留一行，并在数据源字段标注它来自哪些桶：

```python
rows.append((f"h13f|{q}|{name}|{tk}|{act}|{sh}", pr, bucket))
ded = {}
for uid, pr, bucket in rows:
    if uid in ded: ded[uid][1].add(bucket)   # 同一笔，只累加桶来源
    else:          ded[uid] = (pr, {bucket})
# 数据源写成 "... [new_buys/top_holdings]"
```

**但别过度去重**：剩下 8 组同 title 的逐条核过是**真实不同事件**（动作和股数都不同），保留才对。
去重前必须逐组打印出来人工判一次，不能只看数字降下去就收工。

---

## 验收闸门（缺一不可，全部是确定性检查）

### 1. 抽取数 vs 写入数的算术校验
样板跑过之后，全量跑的 `written` 应当恰好 = `extracted - sample`。对不上就是有行被跳过。

```
表                  抽取  样板  本轮写  预期写  差异
HDB_COT               24     3     20      21   -1 ← 需查   # 就是这样抓到 silver 丢失的
```

### 2. 三点对账（本地 / Notion / 重复）
```
表                    本地  Notion    差   重复
HDB_HOLDINGS          4769    4769   +0      0
...
合计                  6116    6116   +0
```
`差` 和 `重复` 任一非 0 都是失败，**不许解释过去**。

### 3. 键同构自测（比对账更强）
只比数量会漏掉"多了一条又少了一条"。要比**集合**：
```
本地键 4769(唯一 4769)  Notion 键 4769(唯一 4769)
本地独有 = 0   Notion 独有 = 0
```

### 4. 幂等复跑 —— 最后一道闸
```
幂等复跑: 补写 0 (期望 0)  errors=0
```
补写非 0 = 幂等键有问题，**下次 cron 会持续重复写入或持续漏写**。
这一步能抓住前面三步都放过的键设计缺陷。

### 5. 逐字段抽验（数字真实性）
每张表打印首行全部字段。空字段必须能解释：
- `HDB_YIELDS` 末行 US10Y 为空 → 查证：美债序列 250 点止于 08-24、日债 244 点止于 08-25，
  **两国交易日历不同**，并集 260 天。属真实差异，**如实留空，绝不补值**。
- `综合信号`/`触发数` 全空 → 查证：这两个字段**不在 `data/snapshots/`**，只在 `data/daily/`。
  双源合并解决（102 天取指标 + 12 天补信号灯），而不是删字段。

---

## 无数据源的表：保持 0 行，标注原因，绝不占位

`NOT_WIRED` 显式登记，让报告能如实说明：
```python
NOT_WIRED = {
    "HDB_AUCTIONS": "本地/fetcher 均无落盘序列, 需另接 Treasury 拍卖结果源",
    "HDB_STRESS":   "无历史序列 fetcher, 需另接",
}
```
Chao 的判定：**假数据占位 = 不可接受**；0 行 + 一句真实原因 = 合格。
但"标为无数据"之前必须先排除红线四（字段读错）—— 本轮 11 张"无数据"表里，
9 张其实有数据（947 行），只有 2 张是真的没有。

---

## 多 agent 共库时的血缘铁律（Chao 2026-08-26）

> 我抓的 / 我 LLM 产出的 → **我自己的 DB + 我自己的数据源文件**；
> 只读别人的表 → **不建镜像，保持只读**；
> 别人创建/维护的表 → **完全不碰**。
> 「只要是你去抓到的数据，而不是别人抓到的数据，你就要自己建，没有任何例外。」

实现成**代码里的硬闸门**，不能只靠自觉：

```python
ALLOWED_PREFIX = "HDB_"
def _guard(env_key: str):
    if not env_key.startswith(ALLOWED_PREFIX):
        raise RuntimeError(f"REFUSED: {env_key} 非 HDB_* 表, 本模块禁止写入")
```
外加 `_assert_not_foreign()` 黑名单（含他人 DB 的带/不带连字符两种 ID 形式），并自测两个外部 ID 确实被拒。

**判定"这张表是不是我的"要看血缘（谁抓的），不是看谁先建的表。**
本轮 grep `src/` 确认 17 张表全由我的代码写入 → 结论是 18 张全建，
推翻了我上一轮"只建 3 张"的判断。

---

## 时间估算：先量再报，别按行数拍脑袋

我先报"18 张表全量回填 2–4 小时"，实测本地只有 233 行 → 按 3 req/s 只需约 80 秒。
后来 13F 修好又从 0 变 15557 行 → 90 分钟。**两次都错，因为没先跑 `--plan` 量一遍。**

抽取器必须提供 `--plan` 干跑模式（只统计不写），报时间前先跑它。
量级超出预期时**停下来问用户要不要收窄窗口**，别自作主张全灌 —— 本轮 13F
15557 行（十年 42 季）经 Chao 选 B 收窄到近 3 年 4991 行。
