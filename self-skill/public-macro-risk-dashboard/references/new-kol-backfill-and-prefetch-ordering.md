# 新 KOL 一年期回填 + 名册/抓取时序 (2026-10 实战教训)

## 1. Hermes 单轮 web_search 上限 = 50 次
- `agent/tool_guardrails.py` 的 `max_web_searches=50`/轮，日志 `loop_web_search_cap`；撞顶即强杀子进程，**0 条落盘**，表现为“子进程未产出”。
- 判据：先用同搜索词自测搜索服务正常，再看子进程日志是否停在第 50 次搜索——别误判成搜索后端坏了。
- 对策(不改全局 config)：回填脚本 `PER=1`(每子进程 1 人)、并行 `PAR=6`；子进程指令里写“搜索预算”：每人 ≤20 次、同名干扰先用机构限定词或直开本人站点、拿到首批可核实条目先落盘、接近 40 次必须落盘并回报。
- 注意：PER=1 仍不够(Abigail Coplin 同名干扰一人吃满 50 次)，必须同时加每人预算。

## 2. 名册同步必须在抓取切批之前
- 09:00 全量抓取读名册切批，而名册同步原先在 11:00 日报步骤 0 → 当天新增 KOL 既没抓取也没上看板(198 人名册只抓 192)。
- 修复：`~/.hermes/scripts/eco_vol_kol_prefetch.sh` 开头先跑 `sync_kol_from_notion.py --apply`；同步失败不中止，沿用旧名册并打印 ⚠️。自测用 DRY 模式验证切批人数合计 == 名册人数。
- 改 cron 脚本需 Chao 批准；备份 `/tmp/*.before_sync`。

## 3. 操作纪律(都是踩过的)
- **账本清零**：先 `list(d.keys())` 复制再改，失败必须中断；**禁止把清零和启动回填链式写在一条命令里**(清零报 `dictionary changed size during iteration` 但后面命令照跑，且过零点后脚本按新日期选错 6 人)。
- **别用 `pkill -f "tools/kol_new_backfill.sh"`**：会匹配到自己的终端包装进程，通知出现 EXIT=143 + tcsetattr 警告，但脚本本体可能仍在跑——先 `pgrep -fa` 看实物。
- 长任务用 `setsid bash ... < /dev/null` 脱离会话，`background=true, notify=true`。
- 提交钩子报 `no ssh cert ... run ussh`：先 `ssh-add -l` 看证书有效期，别急着用 hooksPath 绕；证书恢复后重提即可(数据已入库、暂存，不丢)。
- 状态文件残留 FAIL/RUNNING 会挡下一轮：先改名留档(`STATUS.fail_xxx`)、把 batches/out 挪进 `roundN/`。
- 选人规则：覆盖月数少者优先，所以零覆盖新人会排最前；上限 CAP=12/天实际 PAR 决定每日人数。
