# X 回填:API 用尽→网页兜底 + 日更扫描(2026-10-05 实测)

## Chao 定的规则
- API 超预算/402 → 自动转「逐个打开网页」(不停摆,不自行追加花费)。
- 每个 KOL 在 X 上最多回填 1 个月(嫌 6 个月太慢)。
- 日更扫描走 API(只读新帖,since_id 游标),cron `eco-vol-x-daily-scan` 工作日 09:30 JST,no_agent,成功静默。
- 「继续」=启动一轮网页兜底(一轮 8 账号);我的 turn 只由消息驱动,不能无人值守跑 28 小时。

## 代码(tools/x_backfill/)
- xapi.py(账本+HARD_CAP+每页落盘)/ x_daily_scan.py(日更,三处停止分支入队)/ x_backfill_api.py(估量>阈值标 high_volume 不烧钱)
- x_web_fallback.py + x_enqueue_gaps_1m.py(只补 API 没覆盖的缺口)/ cdp_probe.py(★必须放项目里,曾只在 /tmp,网关重启即丢)

## 实测坑
- 网页对同日连发多条只显示最后 1 条:Gundlach 8/6 API 4 条网页 1 条;切 6 小时窗/换 top/去过滤都找不回。漏抓率 Hunter 0%、Gromen 3.4%、Gundlach 22%(账号相关)。网页数据必须标 source=web。
- `counts/all` 对 -is:reply/-is:retweet 无效,不能估价;分页边界每页重复 1 条。
- 0 条≠没发帖:andrewmaguire1 用主页对照(最新帖 2025-12)才确认真没发。
- 扫描 `since_id` 无新帖=$0;稀疏账号无游标时要存 last-scan 时间,否则每天重读窗口重复付费。
- 隧道 localhost:9333 会反复断(只有 Chao 在 Mac 上能重建);启动前必 curl 验证;连续3次失败熔断。
- 杀后台任务:pgrep 看清再 kill 精确 PID;父脚本被杀后 x_day.py 子进程会遗留,要单独杀。
- 同名路人被 verified 门禁放行(RevAdamHamilton 牧师/JamesGrantJ6 法学生/pomeranian99 作家):用「简介无金融词」+名册身份逐个核,排除名单 data/x_backfill/x_scan_exclude.json。
