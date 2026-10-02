# 新 KOL 回填「子进程未产出」: 每轮 web_search 上限 + 账本陷阱 (2026-10-01/02)

## 现象
`tools/kol_new_backfill.sh` 对名册新增的人 (一年内 0 条言论) 回填: 12 人只有 2-3 人有产出, 其余
「子进程未产出」。子进程日志只剩一句: `hit the tool-call guardrail (loop_web_search_cap) after 50 repeated
non-progressing attempts`。同时用同样搜索词手测 web_search 完全正常 → **不是搜索后端挂了**
(别按「后端故障」套路等恢复, 也别据此断定这些人没有言论)。

## 已验证的根因 (读源码确认, 不是猜)
`~/.hermes/hermes-agent/agent/tool_guardrails.py`: `_DEFAULT_MAX_WEB_SEARCHES_PER_TURN = 50`, 每个 agent turn
(一次 `hermes -z`) 内累计 web_search 达 50 次就硬拦并结束该 turn, 与 `hard_stop_enabled` 无关。
配置键 `tool_loop_guardrails.loop_caps.max_web_searches` (0=不限制), 默认配置里没有这一段。
回填脚本原来每子进程 2 人 × 缺 12 个月 × 每月 1-3 次搜索 → 必撞顶, 且「每做完一人立即落盘」的
指令救不了: 撞顶发生在第一个人还没做完时。上午那轮 8 人成功只因他们本来已有几个月覆盖、缺月少。

## 修法与边界
- 选项 A: 全局放宽该键 → 影响整机所有任务的防失控保护, **须 Chao 批**。
- 选项 B (Chao 选了): 项目内 `tools/kol_new_backfill.sh` 改 `PER=1; PAR=6` (每进程 1 人, 每日上限
  PER*PAR=6 不变)。沙箱 DRY 验证: 6 个批次文件、每批 1 人, 真库 md5 前后一致。
- **B 并不彻底**: 实测同一晚 Abigail Coplin (只缺 9 月, 但有同名干扰) 一人仍撞 50 次。
  后续待做 (Chao 尚未批): 在 `scratch/kol_bf_gap110/INSTRUCTIONS.md` 加硬约束「每人最多 web_search 20 次,
  用完按已有结果落盘换下一人」。**这条没验证过, 不要当作已解决写进别处。**

## 账本 `data/kol_backfill_ledger.json` 的坑
1. `tries` 不区分「查了没找到」和「进程根本没跑起来/被强杀」, 失败的人也 +1, 到 2 就永不重试。
   → 看到「未产出」先读 `log_b*.txt` 判因, 再决定要不要清零重排, 别任其耗尽。
2. 清零必须「先 `shutil.copy` 备份 → `for k in list(l)` 或先收集 key 再删」。直接 `for k,v in l.items(): del l[k]`
   抛 `dictionary changed size during iteration`, **账本一字不改**。
3. **失败后的链式命令不会自动停**: 清零脚本报错后, 后面的 `mv STATUS...; bash tools/kol_new_backfill.sh`
   照常执行, 起了一个选错人的批次。多步操作要 `set -e` 或用 `&&` 串, 并在起跑前读回确认账本真的变了。
4. **跨零点**: 脚本用 `date +%F` 定目录与 STATUS; 23:59 之后重跑落到新的一天, 重新选人, 且昨天目录里的
   STATUS/ingest_report 不会拦它。重跑前把当天 STATUS、ingest_report.json 改名留档(别删), 并确认日期。
5. 对一个已在后台跑的批次别 `pkill -f kol_new_backfill.sh`: 会连带杀掉承载 notify 的包装进程 (EXIT=143),
   而真实子进程可能还活着。用 `pgrep -fa 'kol_new_backfill.sh|hermes -z' | grep -v 'bash -c'` 看真进程再决定。

## 汇报口径
「新增 N 条」不等于「新增 KOL 都补上了」: 汇总里逐人看「入库条数/覆盖月数」, 「子进程未产出」的人要单列,
不能含糊成回填完成。
