# 2026-09-30 经验：Notion 列名漂移、新 KOL 自动回填、长历史免费数据源

## 1. Notion「缺列」= 整行被拒，不是缺一格（最容易误报成「非致命」）
- 症状：日报写「⚠ SOFR minus EFFR Spread 属性不存在（非致命，其余已写入）」。
- 真相：Notion 的 pages create/PATCH 只要 props 里有一个列名不存在，就返回 400，**整行都不写**。结果 9/21–9/30 共 8 天指标表整行缺失；同一次运行的 REPORT/COT 表不含该列，所以显得「其余正常」。
- 根因：config 里改了指标 name_en（口径 SOFR−IORB → SOFR−EFFR），Notion 表没加新列；写入函数不看 upsert 返回值，照样打印「已写」。
- 修法（已落地 src/run.py write_indicators）：
  1. 写前 GET database schema，config 里有而表里没有的列 → PATCH database 自动补列，**只加不删**；旧口径列保留（口径不同不能混一列）。
  2. 检查 upsert 返回的 page id，失败打印「❌ 指标行写入失败」，禁止打印「已写」。
  3. 缺的日子从 data/snapshots/<date>.json 回写，抽 4 天读回比对。
  4. 自测：临时加假列 → 写入 → 读回 → 删假列。
- 通用教训：任何「改名/改口径」都要查所有下游 sink 的 schema；AI 日报对 400 报错的定性不可信，要回原始错误看是「整请求被拒」还是「字段被忽略」。

## 2. 新 KOL 自动一年期回填（Chao 规则：每新增一个 KOL 都必须 backfill）
- 入口：cron `eco-vol-kol-new-backfill` 工作日 14:00（no_agent）→ `~/.hermes/scripts/eco_vol_kol_new_backfill.sh` → `tools/kol_new_backfill.sh`。
- 选人：名册 active 且过去 365 天在 kol_store 覆盖 < 3 个月（按 **kol_name = registry display_name** 统计，不能按 kol_id——store 里老人用短 slug）。账本 `data/kol_backfill_ledger.json` 每人最多试 2 次；每天最多 6 人（2 人/批 × 3 批并行，1 小时脚本上限内跑完），其余写 deferred 顺延。
- 流程：沿用 `scratch/kol_bf_gap110/INSTRUCTIONS.md` 铁律（sed 替换窗口为滚动一年）→ hermes -z 子进程 → `tools/kol_bf_ingest.py --apply`（出处实测门禁；WIN_START 已改为滚动 today-365）→ 只 add kol_store.sqlite + ledger → 校验 local==remote。
- 输出契约：没人要补 = 0 字节 stdout（连调试 print 都不能留，曾残留 `print(len(todo))` 会导致每天发一个「0」）；有人 = 每人入库条数；失败 = ❌ 一行 + 非零退出。
- ★沙箱自测事故：第一版 ROOT 写死，`KOL_BF_DRY=1`「沙箱」测试其实写进了真库 7 条假数据（comments='DRY 假数据'，source=example.invalid）。当场按内容精确删除、确认未进构建产物。
  **防线**：ROOT 可由 env 覆盖；脚本内硬判断「DRY=1 且 pwd 是正式目录 → exit 2 拒绝」。以后任何带 DRY/自测模式的写库脚本都要加这个闸，测前测后 md5 比对真库。
- 测试矩阵（全部实测过）：无人静默 / 有人汇总 / 同日重跑静默 / 试满 2 次放弃 / 入库失败 ❌ exit1 / DRY 指向正式目录拒绝。

## 3. 日报「立场转向」统计噪声
- 全量抓取标出 29 人转向，只有 4 人依据是新言论；25 人是 LLM 对同一篇旧文每天贴的多空标签不同。
- 汇报「转向」时必须按依据文章的发表日期过滤（依据日期 < 上次抓取日 → 不算转向），否则会夸大。已向 Chao 提出改判定规则，待批。

## 4. 长历史免费数据源（实测可用）
- **股指÷黄金 50 年**（已接入看板 `fetch_stock_gold_ratio`，底表 data/stock_gold_ratio_base.json + Yahoo 日更 + cache 兜底）：
  - 道指 1976–1991：GitHub `fja05680/dow-sp500-100-years` DJA.csv（日收盘取月末）；Yahoo ^DJI 月线只到 1992，FRED DJIA 只有 10 年。
  - 标普：Yahoo ^GSPC 日线可回到 1976（period1=189302400）。
  - 黄金：GitHub `datasets/gold-prices` monthly.csv（LBMA 月均，至上月）+ Yahoo GC=F 追加。
  - 衔接处打印核对（1991-12 3169 / 1992-01 3223）。
  - 口径：股指月末 vs 黄金月均，图注写明；「今日比值」用同日收盘单算。用户口头的「13:1」只是某天金价下的值，回答时给当前实算值并解释差异。
- **中国原油进口月度**：JODI `world_primary_csv.zip`（REF_AREA=CN, CRUDEOIL, 进口，KBD/KTONS），最新月用海关总署万吨 × 上月 JODI 桶/吨系数折算并虚线标注。
- **中国原油周度**：全国周度只有 Kpler/Vortexa（付费）。免费高频代理 = 隆众「山东独立炼厂原油周度到港量」（Mysteel 转载，nenghua.mysteel.com 列表 `pa7302a050301aaaaa{N}.html?keyWord=到港量` 约回溯 18 周；更早用 web_search 精确句「截至YYYY年M月D日 山东独立炼厂原油到港量」逐周找，正文「较上周涨/跌X」可反推上一周并交叉核对）。图上必须标注「仅山东地炼样本≈全国两成，不是全国总量」。

## 5. matplotlib 出图 QA 小坑
- 用错解释器报错时旧 PNG 还在，vision 复查看到的是旧图——重跑后先确认产物时间戳变了再 QA；本项目用 `.venv/bin/python`。
- vision 说「线有断口」时先用数据查缺月（常是陡降被误读）；注释 bbox 白底会盖住折线，端点标签改无底色并按与中位线相对位置上下错开；对数轴用 FixedLocator + `{y:g}` 避免 4×10¹ 类刻度。
