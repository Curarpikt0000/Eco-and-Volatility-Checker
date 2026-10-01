# 静默型数据 bug 目录（不报错、不崩溃，只是悄悄丢/多算数据）

2026-08-27 回填 18 张 `HDB_*` 表时一次性抓出 5 类。这是本项目最危险的一类问题：
跑完一切正常、日志全绿、exit 0，**只有做三点对账才看得见**。

| # | 现象 | 根因 | 教训 |
|---|---|---|---|
| 1 | 丢 `2026-06-09 silver` | COT 同日有 gold/silver **两行**，幂等键只用 title（日期） | title 不唯一的表必须声明附加去重字段 |
| 2 | 整表 0 行 | 13F 按 `institutions[].holdings` 取，**该键根本不存在** | 结构靠实测不靠猜 |
| 3 | 虚增 230 行，按机构汇总会翻倍 | `top_holdings` 与 `new_buys` **装同一笔持仓**（实测 195 例） | 多桶数据源必须查桶间重叠 |
| 4 | 260 行只出 1 行 | 收益率按 `.value` 取，真实序列在 **`.points`** | 曾据此向 Chao 误报「本地无历史序列，需从 FRED 重抓」—— 是错的，数据一直在 |
| 5 | 53 周真实数据被抹掉 | 探测时调 `fetch_foreign_flow_japan()`，它抓取失败后**把缓存覆写成 `{"status":"未获取"}`** | fetcher 会写盘，见下 |

## 幂等键：title 不唯一就必须加字段

```python
DEDUP_EXTRA = {
    "HDB_COT": ["品种"],                   # 同日 gold/silver 两行
    "HDB_HOLDINGS": ["标的", "持股数"],     # 同季同标的可有「清旧仓+建新仓」两个真实事件
}
```

★ HOLDINGS 最后剩的 8 组同 title **是真实不同事件不是重复**
（Berkshire 2026-06-30 BAC：新建 483,394,015 股 vs 清仓 0 股，SEC issuer 名称变体）。
不把它们纳入唯一键，下次增量跑就会静默漏掉其中一条 —— 和 bug #1 同一个病。

**本地键与 Notion 键必须同构**，两种结构的解析函数不能混用：

```python
# ❌ kns.plain() 解析的是 Notion【返回】的结构（带 plain_text）
#    本地构造的是 {"type":"text","text":{"content":...}} → 无 plain_text 键 → KeyError
def _local_title(props, tf):
    return "".join(x["text"]["content"] for x in props[tf]["title"])
```

验收：本地键集与 Notion 键集**双向独有为 0**，然后幂等复跑**补写为 0**。

## ★★ fetcher 会写盘 —— 探测前先确认

`fetch_foreign_flow_japan()` 抓取失败时会把 `data/foreign_flow_japan.json`
覆写成 `{"status":"未获取"}`。只是「探测一下有没有数据」就抹掉 53 周真值，
靠 `git checkout` 才救回。**这正是 AGENTS.md 记载的「空值覆盖真值」陷阱。**

抽取器一律**只读缓存文件，绝不调 fetcher**：

```python
def ex_foreign_flow():
    d = json.load(open(os.path.join(ROOT, "data", "foreign_flow_japan.json"), encoding="utf-8"))
    if (d.get("status") or "") != "ok":
        return []          # 缓存本身是失败态就返空，不触发任何网络抓取
```

同日两次事故是**同一类**：以为是只读的操作，实际会写/会删
（fetcher 写磁盘、`git reset --hard` 清工作区）。动手前先问「这个操作会不会写？」

## 结构靠实测：先 probe 再写抽取器

```python
d = ed.fetch_xxx()
print(list(d))
for k, v in d.items():
    if isinstance(v, list):   print(f"{k}: list[{len(v)}]", v[:2])
    elif isinstance(v, dict): print(f"{k}: dict", list(v)[:6])
```

实测到的真实结构（省得再猜）：

| fetcher | 数据在哪 | 形状 |
|---|---|---|
| `fetch_foreign_custody_ust()` | `.history_long` | `[[date, 万亿], ...]` 522 点 |
| `fetch_nikkei225()` | `.points` | `[[date, close], ...]` |
| `fetch_iip_four_countries()` | `.countries.<CC>.{assets,liab,net}` | `[[year, val], ...]` |
| `fetch_hf_leverage()` | `.exposure.points` / `.borrow.repo` | `[(date, val), ...]` |
| `fetch_bis_gold_swaps()` | `.points` | `[{date, tonnes, kind, src}, ...]` |
| `fetch_fiscal_news()` | `.events` | `[{date,country,category,title,summary,source_url}]` |
| `fetch_ofr_fsi()` | `.latest` | 只有截面无序列 → 只能 1 行 |
| `fetch_money_supply()` | `.US/.JP/.CN` 各 `{m0,m1,m2,as_of}` | — |
| `us_jp_yields.json` | `.series.<k>.points` | **不是 `.value`** |
| `data/snapshots/*.json` | `.results` 有指标值 | **`overall`/`hit` 不在这里，在 `data/daily/*.json`** |
| `holdings_13f.json` | `institutions[].{top_holdings,new_buys,exits}` | **没有 `.holdings` 键** |

## 数字对不上：先查口径再查 bug

回填时数字与预估不符，先算清是不是口径问题，别急着当 bug 修：

- COT 抽 24 行而非预估 116 —— **COT 是周频**，102 天快照里很多天引用同一周。
  116 是「快照×品种」出现次数，24 才是真实唯一周报（金 12 + 银 12）。去重是对的。
- 日报 12 行而非 13 —— 13 个 md 里有一个是 `latest.md`（软链副本），被日期正则正确排除。
- 收益率末行美债为空 —— **不是缺失**：美债 250 点止于 08-24、日债 244 点止于 08-25，
  两国交易日历不同，并集 260 天。**如实留空，绝不补值。**

## 三点对账模板

```
表                本地   Notion   差   重复
HDB_HOLDINGS      4769    4769    0     0
...
合计              6116    6116    0     0
幂等复跑：补写 0，errors 0
```

无数据源的表**保持 0 行并标明原因**，绝不放假数据占位
（`HDB_AUCTIONS` / `HDB_STRESS` 确无源，如实留空）。

## Notion 写入的两条硬闸门

1. `_assert_not_foreign()` —— 只允许写 `HDB_*` 前缀的自有表，
   黑名单含他人的 `DB_KOL_VIEWS` 和用户的 KOL List（含无连字符形式）。
2. **每次写入记 `notion_page_id`** —— 曾误写 93 行进他人表，
   靠 store 里记的 page_id 才精确归档撤回、0 失败。

建表判重**不要用 Notion `/search`**（模糊命中会返回他人的同名表，导致自己的表永远建不出来），
改用父页 `child_database` 精确标题匹配。
