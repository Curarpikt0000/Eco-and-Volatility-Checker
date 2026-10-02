# 新 KOL 回填撞搜索上限 + 交接包每日自动刷新 (2026-10-01/02)

## 1. 回填 0 产出的真因: hermes 每轮 web_search 硬上限 50 次
- 现象: `tools/kol_new_backfill.sh` 子进程日志只剩一句 "hit the tool-call guardrail (loop_web_search_cap) after 50 ...", out/ 无文件, 汇总写「子进程未产出」。
- 机制: `~/.hermes/hermes-agent/agent/tool_guardrails.py` 的 `max_web_searches` 默认 50(每个 agent 轮, 非每人)。config.yaml 的 `tool_loop_guardrails.loop_caps.max_web_searches` 可调, 但属全机配置, 改要 Chao 批。
- 判据: 缺月≥11 的人最易撞顶; 一个子进程分 2 人必撞。搜索工具本身正常(自测泛 query 有结果)——别据此断言「搜索挂了/这些人没言论」。
- 修法(已落地, Chao 选 B): `PER=1; PAR=6`(每进程 1 人, 每日上限 PER*PAR=6 不变) + `scratch/kol_bf_gap110/INSTRUCTIONS.md` 加「搜索预算」(每人≤20 次、拿到首批可核实条目先落盘、同名多先用机构限定词或直接 web_extract 本人站点)。重跑后 6/6 有产出, 0 批撞顶。
- ★账本陷阱: 脚本不管有无产出都给 ledger tries+1, MAX_TRY=2 → 没跑起来的人也被耗掉次数, 次日不再入队。重跑前要清零, 且**先 copy.deepcopy 再删键**(遍历 dict 同时 del 会 RuntimeError, 我因此一次清零失败, 链式命令却继续把脚本拉起来跑了错的一批)。清零前备份账本。
- ★跨零点: 脚本按日期建目录 `kol_bf_auto_<date>`, 过 00:00 会当新一天重选人。长操作跨午夜要留意。
- ★勿对后台脚本用 `pkill -f kol_new_backfill`: 会误杀正在跑的进程; 后台脚本用 `setsid ... < /dev/null` 脱离会话。
- ★回填提交可能败在公司 pre-commit 钩子(`asd-cli: no ssh cert, run ussh first`), `-c commit.gpgsign=false` 解决不了, 要 ussh 证书续期; 数据已入库+暂存但未 push, 不要自行 hooksPath 绕过(先问 Chao)。

## 2. 公网交接包 + 每日自动刷新
- 包: `SETUP.md` + `ops/cron-jobs.json`(真实提示词) + `ops/hermes-scripts/` + `self-skill/` + `ops/kol_*`; 技能 agent-project-handoff 的流程, 公网版要剥内部域名/内部发布脚本/内网镜像 job(`eco-vol-codex-delivery-watch`)/个人邮箱/chat id。
- 每日刷新: `scripts/handover_refresh.py`(no_agent, 不花 token), cron `eco-vol-handover-refresh` 工作日 12:00, wrapper `~/.hermes/scripts/eco_vol_handover_refresh.sh`。解析 `docs/index.html` 的 `<div class="part-title">` 取板块标题+频率, 与 `ops/dashboard_sections.json` 比对, 新增/移除/频率变更写入 SETUP.md 的 AUTO 标记段与变更记录; 无变化静默不提交(as_of/exported 日期变动不算变化); 红线(密钥/内部标识)命中则整体还原并报 ❌。
- 踩坑: 红线正则要允许 SETUP.md 里「讲红线本身」的那一行; 脚本只 add `SETUP.md ops self-skill`, 新建的未跟踪脚本要另行 add。
- 费用心智: 日常 cron 里只有 KOL 全量抓取(6 并行 hermes, ~175 人)是大头; 估算为量级非账单, 要准数读 state.db 用量。可选省钱法(未批): 先廉价筛「今天可能有新言论」的人再深抓。
