# KOL 全量深度抓取：后台 prefetch + 日报只读状态（2026-09-28）

## 问题
日报 cron 是**单个 agent turn**，在里面没法可靠地并行子 agent；逐个深度抓 150+ KOL 必超时。
结果日报长期「沿用旧快照 + 定向刷新 1-2 人」，但快照日期照样推进 → 看起来是新的，实际 9/17 后多数人 11 天没刷新。

## 解法（已上线）
- no_agent cron `eco-vol-kol-prefetch` 工作日 09:00 → `~/.hermes/scripts/eco_vol_kol_prefetch.sh`：
  切 6 批 → `setsid` 脱离 cron 起 6 个独立 `hermes -z` 进程 → 立刻返回（不占 no_agent 脚本 1h 超时）。
  runner 等全部结束 → `tools/kol_merge_deep.py` → 写 `scratch/kol_deep_<date>/STATUS`（RUNNING/DONE/FAILED）。
- 日报 11:00 步骤 3 只读 STATUS：DONE 直接用；RUNNING 最多等 20 分钟后部分合并；FAILED 沿用旧数据并在「数据健康度」显著写明。
- 实测：6 批约 40 分钟，153/153 落盘，117 ok / 34 thin / 2 none。9/29 首次 cron 自动跑：09:23 DONE 153/153。
- 全量抓到 ≠ 有新言论：日报要列「当日言论」必须再过一道出处日期筛选，见 `kol-highlights-freshness-and-weekly-digest.md`。

## 坑
- **转向必须按大类比**（多/空/中性/混合）。逐字比方向字符串会把措辞变化都算成转向。上次「混合」或任一方「未找到」不计。
- 上次条目停在很久以前时，变化是多日累积的 —— changes 里带 `prev_date`，日报要注明，不要说成一天内转向。
- `kol_store.ingest_daily_dir()` 默认参数会**回扫整个 daily 目录**，一次灌入所有历史快照（本次误灌 2,790 条，已回滚后经批准再补）。只想写当天就把当天快照拷到临时目录再 ingest。
- 合并闸：今日产物 < 名册一半 → exit 2 拒绝覆盖（防 web_search 后端挂掉时把全员刷成「未找到」）。
- 自测不烧配额：`KOL_PREFETCH_DATE=2099-01-01 KOL_PREFETCH_DRY=1`（批进程只 sleep），验证拉起→防重复→等待→合并→STATUS；测完删目录。
- 在真 repo 上重跑 merge 会把「上次」变成今天本身 → 转向清零。测试用沙箱副本（拷 src/tools/.venv + before.json）。
