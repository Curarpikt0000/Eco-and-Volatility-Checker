# 新 KOL 回填：50 次搜索上限 / 名册同步顺序 / 账本操作（2026-10-02 实战）

## 1. 回填「子进程未产出」的真因 = 每轮 web_search 硬上限 50 次
- 症状：`tools/kol_new_backfill.sh` 汇总里一批人「0 条（子进程未产出）」，批日志只有一句
  `stopped retrying web_search ... guardrail (loop_web_search_cap) after 50 ... attempts`。
- 根因：Hermes `agent/tool_guardrails.py` 的 `max_web_searches` 默认 50（**每个 agent 轮**，hard cap，不受 `hard_stop_enabled` 影响）。
  一个子进程 = 一轮。原先 PER=2（每进程 2 人）×每人 12 个缺月×每月 1-2 次搜索，必撞顶，撞顶即终止，**尚未 write_file 的成果全丢**。
- 误判陷阱：我先怀疑「搜索服务挂/限流」，用同样查询自测却正常返回——**自测正常 ≠ 子进程没被卡**，先看日志里有没有 `loop_web_search_cap` 字样再下结论。
- 判别特征：缺月多(11-12)的人失败，缺月少的人(已有若干月覆盖)成功；成功者往往是「容易搜到」的人。
- 修法（均在项目内，不碰全局 config）：
  1. `tools/kol_new_backfill.sh`：`PER=1; PAR=${KOL_BF_PAR:-6}`（每进程 1 人，每天上限 PER*PAR=6 不变）。
  2. `scratch/kol_bf_gap110/INSTRUCTIONS.md` 末尾加「搜索预算」：每人最多 20 次 web_search；同名干扰先用 display 里的机构限定词/直接 web_extract 本人站点；拿到首批可核实条目就先落盘；总数近 40 立刻落盘回报。
  3. 实测：6 人 6 进程全部有产出（6~13 条，覆盖 4~11 月），0 批撞顶。
- **只改 PER=1 不够**：一个同名干扰多的人单人也能撞 50 次（Abigail Coplin 9 缺月就撞了）→ 必须配合「每人 20 次预算」指令。
- 另一种全局解法（需 Chao 批）：`config.yaml` 加 `tool_loop_guardrails.loop_caps.max_web_searches: 150`——影响全机所有任务的防失控保护，默认不用。

## 2. 账本语义坑
- `data/kol_backfill_ledger.json` 每跑一次对本批所有人 `tries+=1`，**不区分「查了没找到」和「根本没跑起来」**；满 2 次即不再入队。
  → 基础设施故障（撞顶/被杀/限流）会把人白白烧掉 2 次机会，事后要手工清零。
- 清零写法：**先 deepcopy 再删再写**，不要在遍历时 `del l[k]`（`RuntimeError: dictionary changed size during iteration`，且之前未备份就崩=账本没改，而我的后续链式命令照样往下跑把错误的一批启动了）。
  先 `cp` 备份，再 `new=copy.deepcopy(l)`，对 `new.pop(k)`，最后 dump。
- 清零/重跑属于改记录文件，先问 Chao（本次他批准了「做」）。

## 3. 重跑同一天的操作清单（脚本对同日有 STATUS 幂等闸）
1. `mv $D/STATUS $D/STATUS.<标签>`；`mkdir round_N && cp -r batches out todo.json round_N/`；`rm -rf batches out; rm -f log_b*.txt`（留档不删）。
2. 起跑用 `setsid bash tools/kol_new_backfill.sh > /tmp/xxx.log 2>&1 < /dev/null`，background+notify。
3. 不要用 `pkill -f kol_new_backfill`：命令行里含该字串的**所有**进程（包括我自己的通知壳、新起的批）一并被杀（本次 EXIT=143、状态文件滞留 RUNNING）；要杀先 `pgrep -fa` 逐个看 PID，且杀后要手工把 STATUS 改成 killed 标签，否则同日闸会永远拒绝重跑。
4. **跨午夜**：`D=scratch/kol_bf_auto_$(date +%F)` 按当天日期，00:00 前后启动的两条命令会指向不同目录（本次 23:59 起的批被记到 10-02 目录，选人也按新一天重算）——长任务链式命令别依赖 `$(date +%F)` 在多条命令间保持一致，先把 D 固定成变量。

## 4. 名册同步必须在抓取切批之前（顺序 bug）
- 事故：09:00 `eco_vol_kol_prefetch.sh` 按当时名册(192)切批；11:00 日报「步骤 0」才同步到 198。→ 6 位新增 KOL 当日既没抓、没回填、没上看板。
  （名册 Notion→本地镜像发生在日报里，prefetch 在日报之前。）
- 修法：prefetch 脚本在切批**前**先 `timeout 300 .venv/bin/python tools/sync_kol_from_notion.py --apply`，输出含「已写入」才算成功；失败**不中止**抓取，沿用旧名册并 echo 一行 ⚠️（no_agent cron 有输出才发消息）；`KOL_PREFETCH_DRY=1` 自测模式跳过联网同步。
- 自测只能验证「DRY 下切 198 批、md5 不变」；**同步这步本身要等下一次真实 09:00 才算实测**——汇报时如实说明，别说成已验证。
- 判定「某人有没有被抓/回填/上看板」的取证三件套：`kol_independent.json['all']` 人数与 date、`kol_store.sqlite` 一年内真言论按 display_name 的月数/条数（排除 direction='未找到'）、`docs/index.html` 里该名字是否出现在 KOL 板块（别把别的板块里出现的同名当成上了 KOL 卡片）。

## 5. 回填入库后提交被 pre-commit 钩子拦（asd-cli「no ssh cert」）
- `-c commit.gpgsign=false` 只关签名，**不绕过**公司 pre-commit 钩子（`core.hooksPath=/etc/git-hooks`）。钩子要 ussh 证书；证书过期是暂时状态，先 `ssh-add -l` 看 `Valid until`，有效则直接重试 commit 往往就过。
- 不要自作主张设 `core.hooksPath` 指空目录绕过；先查证书，必要时问 Chao（记忆里 general rule 保护红线禁用 --no-verify / hooksPath=/dev/null）。
- 数据已入库但没提交时，如实告诉 Chao「库里有、GitHub 没有、看板也没有」，三者状态分开说。
