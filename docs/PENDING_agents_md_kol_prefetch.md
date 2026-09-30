# PENDING：AGENTS.md「## Cron (JST)」段要插入的内容（2026-09-28，审批超时未写入）

状态：**待应用**。应用后把本文件标题改成「已应用 <日期>」，不要删除。

插在 `## Cron (JST)` 标题下第一行：

```
- **eco-vol-kol-prefetch 工作日 09:00**(no_agent，`~/.hermes/scripts/eco_vol_kol_prefetch.sh`，job `bd04a5f69ec8`，2026-09-28 立)：
  KOL 全量深度抓取。按名册切 6 批 → `setsid` 起 6 个独立 `hermes -z` 进程并行(每批约 26 人，prompt 模板 `scratch/kol_deep_run_batch.sh`)
  → 全部结束后跑 `tools/kol_merge_deep.py` 合并进 kol_independent.json + 当日快照 + kol_store → 状态写 `scratch/kol_deep_<date>/STATUS`
  (RUNNING/DONE/FAILED)。实测约 40 分钟 153/153。11:00 日报步骤 3 **只读 STATUS，不再自己逐个抓**。
  - 背景：单个 agent turn 里没法可靠并行子 agent，日报长期只「沿用旧快照+刷新一两人」，9/17 后多数人 11 天未刷新。
  - 合并规则：转向按「大类」(多/空/中性) 比，不逐字比；今日产物 <名册一半 → 拒绝合并、不覆盖旧数据(exit 2)；
    kol_store 只写当天快照，**不要用 `ingest_daily_dir()` 默认参数回扫整个 daily 目录**(会一次灌入全部历史快照)。
  - 自测：`KOL_PREFETCH_DATE=2099-01-01 KOL_PREFETCH_DRY=1 bash ~/.hermes/scripts/eco_vol_kol_prefetch.sh`(不调 LLM，验证拉起/等待/合并/STATUS 链路；测完删 scratch/kol_deep_2099-01-01)。
```

---
## 待写入 AGENTS.md「## Cron (JST)」段（2026-09-30 追加，同样待 Chao 审批）

- **eco-vol-kol-new-backfill 工作日 14:00**（no_agent，`~/.hermes/scripts/eco_vol_kol_new_backfill.sh` → `tools/kol_new_backfill.sh`）：
  Chao 2026-09-30「每次新增一个 KOL 都需要 backfill 他们的言论」。名册里过去 365 天覆盖 < 3 个月的人
  （11:00 步骤 0 刚从 Notion 同步进来的新人天然命中）→ 每批 2 人、3 批并行起 hermes 子进程按
  `scratch/kol_bf_gap110/INSTRUCTIONS.md` 铁律回填 → `tools/kol_bf_ingest.py --apply` 出处实测门禁入库 →
  只提交 `data/kol_store.sqlite` + `data/kol_backfill_ledger.json` 并校验 local==remote。
  每天最多 6 人（保证 1 小时脚本上限内跑完），其余顺延；账本里每人最多试 2 次（公开信息确实少的人不无限烧配额）。
  没人要补 = 完全静默；有人 = 发每人入库条数；失败 = ❌ 一行。自测：`KOL_BF_ROOT=<沙箱> KOL_BF_DRY=1 KOL_BF_NOPUSH=1`，
  DRY 对正式目录会被脚本拒绝（exit 2）——★初版沙箱测试曾因 ROOT 写死把 7 条假数据写进真库，已删并加此保险。
- **股指 ÷ 黄金 50 年比值**（随日报 build_dashboard 每日更新）：`ed.fetch_stock_gold_ratio()`，底表
  `data/stock_gold_ratio_base.json`（1976-01~2026-08，道指/标普月末 + 伦敦金月均），之后月份 Yahoo 日线追加
  （黄金=GC=F 当月均价）；Yahoo 失败读 `data/stock_gold_ratio_cache.json` 并标「缓存」。
