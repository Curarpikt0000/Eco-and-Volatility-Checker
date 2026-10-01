# 单一 SSOT + 三点投影：消灭「backfill 一个库 / 每日 crawl 一个库 / 新增人再一个库」

Chao 2026-08 明确要求（原话）：

> 「把 daily crawl、backfill 和每次新 backfill 或者 crawl 的数据，都放到一个数据库或者一个 JSON
> 里面。这样我们总是更新一个数据库，就不需要跨多个数据库了。**而且，你这个项目的所有其他数据库，
> 都应该按照这个逻辑来处理。**」
> 「我未来想实现的是：我们的 Dashboard、GitHub 和 Notion 所有数据都和数据库三点完全对应，
> 每个数据库都是唯一的。」

这是**架构级的常驻偏好**，不是一次性任务。任何「新增一类数据 / 新增一批人 → 顺手再开一个
JSON 目录或 Notion DB」的做法，在他这里都算倒退。本文件是 Eco 项目 KOL 链路的诊断实录 +
目标架构 + 迁移次序，其他数据链路照此套用。

---

## A. 先看清楚碎片化长什么样（诊断命令）

不要凭印象说「有几个库」。实测 Eco 的 KOL comments 散在 **6 处**：

```python
# 逐目录统计：文件数 / 记录数 / 有 comments 数 / 人数 / 日期范围
# 注意每处的外层包装都不一样，extract 必须逐个写
scan('data/kol/backfill/*.json',  lambda d,f: [(r, d.get('kol')) for r in (d.get('history') or [])])
scan('data/kol/daily/*.json',     lambda d,f: [(r, r.get('kol')) for r in (d.get('kols')    or [])])
scan('data/kol_independent.json', lambda d,f: [(r, r.get('kol')) for r in (d.get('all')     or [])])
scan('scratch/kol_deep_*/out/*.json', lambda d,f: [(d, d.get('kol'))])          # 单人单文件，裸 dict
scan('scratch/kol_bf_new3/out/*.json',lambda d,f: [(r, basename(f)[:-5]) for r in d])  # 裸 list！
```

2026-08-26 实测结果：

| 角色 | 路径 | 外层形状 | 规模 |
|---|---|---|---|
| 一年历史主库 | `data/kol/backfill/<id>.json` | `{kol,sector,history:[]}` | 131 文件 / 653 条 / 121 人 |
| 每日全量快照 | `data/kol/daily/<date>.json` | `{date,count,source,kols:[]}` | 213 文件 / 2841 条 / 140 人 |
| 当日结论（每天覆盖） | `data/kol_independent.json` | `{date,all:[],changes:[]}` | 122 条 |
| 当日深挖 | `scratch/kol_deep_<date>/out/<id>.json` | 裸 dict | 125 文件 |
| 新人一次性回填 | `scratch/kol_bf_new3/out/<id>.json` | **裸 list** | 3 文件 / 46 条 |
| 移出者留痕 | `data/kol/backfill_removed_<date>/` | 同主库 | 14 文件 / 20 条 |

**五种不同外层形状**，这本身就是病灶：新增一批人产出的 `scratch/.../felix_prehn.json` 是裸
list，主库要 `{kol,sector,history:[]}` —— **没写转换脚本之前 dashboard 上这个人一条都不显示**，
而且这个「不显示」是静默的，不报错。Chao 的原话：「这个能否用工程解决一下？」

`scratch/backups/*` 与 `crawl_<date>/out/` 是改结构前的旧副本，**统计时必须排除**，否则条数
虚高一倍还以为数据很全。

## B. 「渲染层合并」≠「已经统一了」

Eco 的 `external_data.kol_full_history()` 每次被 dashboard 调用时在内存里合并两路
（daily 快照连续同内容收敛成 `first_date~last_date` 区间；backfill 带 `source` 优先；
跨路 key=`(last_date, comments[:80])` 去重）。这让表面看起来「历史是活的」，掩盖了三个真问题：

1. **`data/kol/backfill/` 事实上冻结**——最后一条停在人工回填批次那天，**没有任何 cron 往里追加**。
   每日抓的只进 daily。一旦 daily 目录被清理或换格式，历史就断。
2. **新增人不进任何一路**，除非人工搬格式。
3. **Notion 完全不在这条链上**（见 §C）。

判据：**合并逻辑写在渲染函数里 = 还没统一。** 统一的标志是「写入只有一个入口」，渲染只负责读。

## C. Notion 侧的真相（先查 schema，别猜）

`GET /v1/databases/<id>` 一把查清属性与类型，再 query 全量统计每列填充率：

```python
for k, v in d['properties'].items():
    print(f'{k!r:32s} {v["type"]}')
```

**KOL List** `35947eb5-fd3c-800d-b852-cef31f9de6a5`（父页 `KOL Research Daily Update`
`31447eb5fd3c8064a531c43b177cdc41`），125 行，8 属性：

| 属性 | 类型 | 已填 / 125 |
|---|---|---|
| 编号 | title | 125 |
| KOL / 机构 | rich_text | 125 |
| 领域 | select | 125 |
| 核心背景 / 身份 | rich_text | 124 |
| 主要分析方向 / 监控维度 | rich_text | 125 |
| 最新观点 | rich_text | 103 |
| 最新观点日期 | date | 103 |
| **Source** | **url** | **0** |

两个结论：

- **Source 是新增空列，一条没填。** 本地比对后 **124/125 行可回填**（129 个 KOL 本地有带 URL
  的观点；唯一匹配不上的是 `Anu Anand`）。匹配用名册铁律那套：**全量精确 → 模糊只认「本地名 ⊂
  Notion 名」单向 → 取最短候选 → 已配对者不再参与模糊**（Notion 名常带机构后缀）。
- **这张表是「一人一行」，字段叫「最新观点」，物理上只能存 1 条。** 用户说「应该储存每个 KOL
  过去一年所有数据的 Notion Database」时，**它承担不了**——653 条历史塞不进 125 行。
  正解是**再建一张「一观点一行」的 DB**，KOL List 继续当人物名册 + 最新快照。
  ⚠️ 这一点要主动讲清楚，别默默往 rich_text 里塞拼接文本。

**字段归属必须先问再写。** KOL List 按铁律是 Notion 侧 SSOT，由 Chao / 另一个 agent 维护，
本项目只单向镜像。`最新观点`/`最新观点日期` 那 103 行是谁写的不明——**贸然写入 = 两个 agent 抢
同一字段**。`Source` 是全空的新列，没人碰，填它安全。**动别人可能在写的字段前，先 clarify。**

## D. 出处（source）填充率低是「契约问题」，不是「能力问题」

现象：daily 快照 2966 条里只有 489 条（16%）带 `sources`；backfill 653 条几乎 100% 带。
**历史时间线上越近的记录反而越查不到出处**，与直觉相反。

排查顺序（**别一上来就说"要提升抓取能力"**）：

1. **先看字段在不在**。daily 单条字段实测是
   `kol, sector, direction, targets, comments, detail, detail_status, sources` —— **字段是有的**，
   结构没问题，纯粹是填充率。字段缺失和填充率低是两种病，修法完全不同。
2. **对比高填充率的那一路凭什么高**。backfill 的任务书 `INSTRUCTIONS.md` 写死了铁律：
   「每条记录必须能追溯到一个真实可访问的 URL，检索不到就少写几条，宁缺毋滥」。
   每日 cron 的 prompt **没有这条**，于是 agent 抓到就填、没抓到静默留空，也无校验拦截。

修法（**把契约搬过去，而不是换更强的抓取器**）：

- 每日 cron prompt 加同款硬性验收条件；
- 落盘前校验：拿不到 URL 的条目写 `source_status="missing"`，**不要静默留空**；
- 每日产出统计 `ok/partial/missing` 三档计数并告警——**缺口必须可见可统计**，否则永远不会被修。

这条推广到任何采集链路：**「某字段大面积为空」先查 ①字段是否存在 ②高填充率的同类路径靠什么契约保证，
最后才怀疑抓取能力。**

## E. 目标架构：一个 store，三点投影

```
  每日 crawl ─────┐
  历史 backfill ──┼──→  data/kol_store.sqlite   ──→ dashboard（只读）
  新人一次性回填 ─┤    （唯一真相源 SSOT）      ──→ data/kol_store_export.json（进 git，可 diff）
  Notion 名册同步 ┘                             ──→ Notion（幂等 upsert）
```

**核心表 `opinion`（一观点一行）**

| 列 | 说明 |
|---|---|
| `uid` | `sha1(kol_id + date + comments[:80])` 幂等主键，**跨源天然去重** |
| `kol_id` / `kol_name` | 关联名册 |
| `date` | 观点日期，**硬校验，越界拒收**（沿用 `apply_1yr_backfill.py` 的四层防伪造） |
| `direction` / `comments` / `targets` / `detail` | 内容 |
| `source_url` / `source_title` / `sources_json` | 出处 |
| `source_status` | `ok` / `missing` / `partial` ← §D 的缺口可统计 |
| `origin` | `daily` / `backfill` / `manual` ← **保留血缘，不丢来源** |
| `first_seen` / `last_seen` | 连续同内容收敛成区间，**取代渲染层合并** |
| `notion_page_id` | 回写后记录，实现幂等 |

**为什么 SQLite 而不是「一个大 JSON」**（Chao 原话给了「一个数据库或者一个 JSON」两个选项，
要主动选并说明理由）：3000+ 条且每天增长；JSON 每次全量读写、并发写互相覆盖、无法按人/按日期
索引。SQLite 单文件、进 git（几 MB）、`UPSERT ... ON CONFLICT(uid)` 天然满足「总是更新一个库」。
**同时导出一份 `*_export.json` 进 git**，保住人肉 diff 和外部直读——两者不矛盾。

**写入只有一个入口** `kol_store.upsert(records, origin=...)`：
- 每日 crawl / backfill / 新人一次性回填全调它；
- **新增人再也不用管格式包装**，裸 list 直接喂；
- 幂等：同 uid 重跑不产生重复；
- **空值不覆盖已有真值**（复用主 SKILL 里 `notion_writer.upsert` 的 `skip_none` 教训——
  这是同一个 bug 家族，SSOT 层必须内建）。

## F. 迁移次序（每步可独立验收，别一次性大爆炸）

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 回填 Notion KOL List 的 `Source` 列（124/125），写后读回 | Notion 上直接看到链接 |
| P1 | 建 store + 统一 `upsert()`；导入现有全部条目跑去重；**顺带把 scratch 里的新人喂进去** | 条数对得上、新人出现在 dashboard |
| P2 | `kol_full_history()` 改读 store，**保留旧路径做对拍**，两边输出一致才切 | 新旧渲染 diff 为空 |
| P3 | 建 Notion「一观点一行」DB + 全量回填 + 挂进每日 cron | Notion 上按人按日可筛 |
| P4 | 每日 cron prompt 加 URL 铁律 + 落盘校验 + `source_status` 告警 | 次日填充率跳升 |

**P2 的对拍是关键**：切换 SSOT 时新旧两条路径并行、比对输出，一致才拆旧的。直接切会把
「渲染层合并」里那些隐式规则（区间收敛、backfill 优先、跨路去重 key）悄悄丢掉。

## G. 推广到项目里其他 DB 时先分诊，别推倒重来

Chao 说「所有其他数据库都按这个逻辑」，但要区分**真分裂**与**单源单写**：

- **真分裂（该改）**：KOL 链路（本文件）；`DB_REPORT`/`DB_WEEKLY` 各写各的、无统一 report_store
  且**月报整层缺失**（`reports/monthly/` 目录不存在、无 cron、无 DB_MONTHLY——不是坏了，是从没建过，
  如实说，别找借口）；指标快照 `data/daily/*.json` 与 `DB_INDICATORS` 是两套写入。
- **本来就单源单写（别动）**：custody / auctions / money_supply / stress / ofr 等，各自
  一个 fetcher → 一个 Notion DB，不存在多源合并问题。**把它们也「统一」只会制造无谓改动。**

报告层的对应解法是 `report_store`：**日/周/月同一张表，用 `period_type` 区分**，而不是
三个频率各开一个库——这正是「每个数据库都是唯一的」在报告链路上的落地形态。

## H. 回答「一共有多少个 database」这类问题：查 .env，别背

```
grep -o '^DB_[A-Z_]*' .env | sort
```

2026-08-26 实测 Eco 有 **17 个**：INDICATORS / COT / REPORT / WEEKLY / HOLDINGS / CUSTODY /
AUCTIONS / MONEY_SUPPLY / STRESS / OFR / YIELDS / NIKKEI / FOREIGN_FLOW / IIP / HF_LEVERAGE /
BIS_GOLD_SWAPS / FISCAL_NEWS。**没有 DB_MONTHLY，没有 DB_KOL。**
配套查「哪些有写入函数」：`grep -rn 'def write_.*notion\|def .*_notion' src/*.py`——
**有 DB 不等于有人写它**，两边都要列才算答完。
