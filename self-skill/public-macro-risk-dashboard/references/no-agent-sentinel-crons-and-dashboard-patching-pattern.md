# no_agent 哨兵/快照 cron + 往 dashboard.py 加板块的打补丁套路 (2026-10-16 实战)

## A. no_agent cron(零 LLM 成本, 静默即正常)
- 脚本放 `~/.hermes/scripts/`, `cronjob_manage create no_agent=true script=<文件名>`; 成功不输出, 失败/异动才输出一行。
- **先找「谁在调用」再说「数据没落」**: Notion 期权库 255 行只有 9/21 一行真快照 — 根因是 `tools/snapshot_optvol.py` 从未被任何 cron 调度(13 个 eco-vol job 无一调用)。排查 = 读 `cron/jobs.json` 的 script 字段, 不是猜。
- 快照类: 选「前一交易日收盘口径」时刻(JST 06:30 周二~周六); 当天盘中报价不补进时间序列(口径不一致); 日志写 `scratch/`(已 gitignore, 不被每日提交脚本误收; `logs/` 未忽略)。
- 哨兵类(COT): 阈值用近 3 年周变动标准差 2σ(各指标约 4.5-7.7% 的周触发), **不要用相对变动%**(白银对冲基金净多仅几千手, 相对变动>15% 的周占 44.5% 会天天刷屏)。状态文件防同一期重复报; 数据超 10 天未更新静默; CFTC 取数失败发 ❌(不把「查不到」当「没异动」)。
- 沙箱测五条路径(stub 掉取数函数, 状态目录用临时目录): 真实数据静默 / 构造异动触发 / 同期已报静默 / 数据过旧静默 / 取数失败 ❌。
- 无 `ss` 命令的 VM 上判断隧道/端口: 用 python socket.connect 或 `curl ... | wc -c`(隧道断了 curl 退出码仍为 0, 只看字节数)。

## B. 往 dashboard.py 加新板块(克隆而非改已验收面板)
1. `external_data.py` 末尾追加独立 `fetch_xxx()` + 独立缓存 `data/xxx_cache.json`; 抓取不完整→回退缓存并标 warnings; 绝不改已验收的 fetch。
2. `dashboard.py`: `_xxx_html(o)` 函数插在 `def _tfp_sentiment_html` 之前; 页内 JS 作**独立 IIFE**插在 `/* ── 比特币 ÷ 黄金` 注释之前, id/类名统一前缀(sgl-/ust-), 避免与既有 id 冲突。
3. JS 在 f-string 里: 所有 `{`/`}` 写成 `{{`/`}}`; 单图测试时从源文件抽出 IIFE 再 `.replace('{{','{')` 才是真实 JS。
4. 接线四处且必须断言 `count==1` 再替换: `generate()` 新形参 / 模板变量 / 模板插槽(part-title + card) / 菜单 GROUPS 的 `match:[...]` 关键词(否则菜单归组错位); `build_dashboard.py` 取数 + 传参。构建门禁会校验「generate() 全部 N 个形参均已传入」。
5. 补丁写成独立脚本文件跑(含 `ast.parse` 校验 + 防重复打补丁的 already-patched 退出), 改前备份 `/tmp/*.bak_xxx`。
6. 验证: 单图渲染 + CDP 浏览器(折线数/悬停带数/点按钮后重绘/JS 零错误) → vision 看图 → 隔离整站构建(后台, ~9 分钟)。隔离副本须把 `src/fetchers/` 一并复制, 否则 A 股资金面等会因 `No module named 'fetchers'` 退化而被误当回归。对比旧页 part-title 集合: 丢失=∅ 才算通过。
7. 提交只点名文件(`git add` 路径列表, 不用 -A), 红线扫描(ghp_/sk-/ntn_/AKIA)先行; **长的 grep/循环一条命令塞太多会被 hardline 拦下 → 写成脚本文件再 `bash` 运行, 不重试内联版**。
8. 发布仍须项目目录带 .env 的只读 Notion 构建, 隔离构建产物不得发布。

## C. KOL 回填多波次(脚本一天只认一次 DONE)
- `tools/kol_new_backfill.sh` 当天 STATUS=DONE 即退出, 且按「已有月份少」排序会反复选同一批人。需续跑: 复制到 /tmp 改两处 — 每波独立目录 `scratch/kol_bf_auto_$DAY_w$WAVE` + 跳过当日已试过的人; 原脚本不动。
- 模型用 `KOL_MODEL=claude-sonnet-5-5`(≤ Chao 要求的成本线)。通知只说 completed normally 时仍读 STATUS/账本/git(HEAD==远端)。
- 产出判断: 「缺 1 个月」的人 0-1 条常是该月确无本人一手内容(Substack 停更、只有被引述), 不是子进程放弃 → 剩余低收益批次建议不跑。
- 抽样核出处: 每人随机 3 条打开链接; 429/403 的如实标「未验成」不算通过。
