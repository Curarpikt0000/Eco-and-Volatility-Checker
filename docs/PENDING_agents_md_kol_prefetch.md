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
