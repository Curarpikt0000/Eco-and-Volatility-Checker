# 手动连续回填：循环不得每轮提交；X 网页回填“done”须按账号核零日（2026-10）

## 新 KOL 一年期回填循环
- 现成 `tools/kol_new_backfill.sh` 每轮提交 19MB `kol_store.sqlite`，提交走公司 pre-commit 钩子（`asd-cli`），**依赖 ssh 证书**；21~24 轮约 5 小时，证书中途失效是大概率事件（实测第 2 轮 `connection reset by peer` → 循环按设计停，数据已入库已 `git add` 但未提交，没丢）。
- 解法：脚本本就有开关 `KOL_BF_NOPUSH=1`（不 commit/push）。循环脚本每轮 `KOL_BF_NOPUSH=1 bash $ONE`，**全部跑完统一提交一次**（只 add `data/kol_store.sqlite` + `data/kol_backfill_ledger.json`，红线扫描 0 命中、sqlite 无 token 表）。权衡要告诉 Chao：循环期间本地 sqlite 无远端备份。
- 判据对账：循环自报新增条数 == 工作区 sqlite 行数 − `git show HEAD:data/kol_store.sqlite` 行数（本次 134 == 9491−9357）。循环停因读 `scratch/kol_loop.log` 的 `LOOP_END` 行（达到最大轮数 24 ≠ 故障）。每人最多试 2 次，所以跑完仍有「试满仍不足 12 个月」的人，如实报，不重试、不说“没发言”也不说“漏了”。
- 证书检查：`timeout 15 ssh-add -l`；“The agent has no identities”或卡 60 秒 = 需要 Chao 在 Mac 跑 `ussh`。
- 「今天又加了一个 KOL」：先 `tools/sync_kol_from_notion.py`（不带 `--apply` 预演）看 Notion 是否真多了人；本机名册只镜像，**不自行加人**，问名字。

## X 网页 6 个月回填（VM 专用 Chrome，端口 9444）审计
- 进程日志的 `■ @xxx done N/N 天` 只代表“每天都跑过”，0 条也算完成。核对表（按账号）：计划天/落盘天/0 条天/截断天/未去重条数/去重后条数/最早→最晚帖时间。
- 实测 14 账号 4491 条去重帖；**shaunrein 147 天里 146 天为 0 条**（总共 2 条）= 失败不是“没发”；CathieDWood 151 天里 94 天为 0（62%）、DavidSacks/LeveredUSTs 约 40~45% 需抽查。0 条天占比 >40% 的账号一律先不入库，抽几个 0 条日用网页直接搜对照，判断是真没发还是被拦。
- 入库只按帖自带时间戳取日期、按 id 去重（`since/until` 按 UTC 切会串日，日文件虚高约 21%）。
