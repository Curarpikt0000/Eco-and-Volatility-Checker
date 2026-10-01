# 新 KOL 自动回填 + Notion 缺列自愈（2026-09-30）

## Chao 规则
「每次新增一个 KOL 都需要 backfill 他们的言论，别忘了」→ 已制度化，不靠记忆：
cron `eco-vol-kol-new-backfill`（job 71db522f1e52，工作日 14:00，no_agent）→ `~/.hermes/scripts/eco_vol_kol_new_backfill.sh` → `tools/kol_new_backfill.sh`。
- 选人：名册里过去 365 天在 kol_store 覆盖 <3 个月（按 **display_name** join；store 的 kol_id 与名册 id 不一致）且账本 `data/kol_backfill_ledger.json` tries<2。
- 每批 2 人、3 批并行 hermes 子进程（沿用 `scratch/kol_bf_gap110/INSTRUCTIONS.md`，sed 改窗口为滚动一年）；每天上限 6 人（cron 脚本 1h 上限），其余 deferred 顺延。
- `tools/kol_bf_ingest.py --apply` 门禁（WIN_START 已改滚动一年）→ 只 add `data/kol_store.sqlite` + 账本 → push 后校验 local==remote。
- 无人=完全静默（stdout 必须 0 字节；内嵌 python 选人段别 print）；有人=每人入库条数；失败=❌ 一行+非零退出。
- 沙箱：`KOL_BF_ROOT=<副本> KOL_BF_DRY=1 KOL_BF_NOPUSH=1 [KOL_BF_DATE=… KOL_BF_MIN_MONTHS=0]`；
  已测 无人静默 / 有人汇总 / 同日重跑静默 / 试满 2 次放弃 / 入库失败告警。
- 看板在下次日报 build 时带上（脚本不自己重建 8 分钟的看板）。

## ★事故：沙箱测试写进真库
初版 ROOT 写死 → DRY 假数据 7 条进了正式 kol_store（按 comments+source 精确删除，构建产物 grep 0 条确认未发布，并如实告诉 Chao）。
**教训**：任何「可自测」脚本，ROOT 必须可覆盖，且 **DRY 模式检测到正式目录直接 exit 2 拒绝**；测试前后对真库 md5。
复制到沙箱后又改了源脚本要重新 cp，否则测的是旧版（本次因此误以为「静默」分支还在 print）。

## Notion 缺列 → 整行被拒（静默 8 天）
- 9/18 config 改指标 name_en（SOFR−IORB→SOFR−EFFR），Notion DB 没新列 → upsert PATCH **整行 400**，18 指标全没写；
  run.py 不看返回值照印「已写」，日报 AI 把报错当「非致命」。
- 修：`write_indicators` 写前比对 DB schema，缺列自动 PATCH 新增（只加不删旧列，旧口径列保留不混用）；返回 None 时打印「❌ 指标行写入失败」；
  从 data/snapshots 补写缺失日并抽样读回核对。自愈逻辑用假列实测后删除。
- 通用教训：日志里「属性不存在」对 Notion 就是整行失败，不是缺一格——回答前先读回 DB 看行在不在。

## KOL「转向」计数虚高
每日全量对同一篇旧文重新贴多空标签会漂移 → 9/30 的 29 人「转向」里 25 人依据是数周前旧文。
汇报 KOL 当日总结只认原文发表日 ≥ 昨天的新言论（`tools/kol_highlights.py`，默认带「原话要点」层，`--brief` 只要一句），转向要核依据是否新言论。
