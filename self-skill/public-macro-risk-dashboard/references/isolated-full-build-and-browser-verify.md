# 新板块上线前：隔离整站构建 + 无头浏览器验收（2026-10 实战配方）

（板块挪位/菜单成组/接线三点/单块快速验证见同目录 section-reorder-and-menu-group-recipe.md）
适用：给 Eco-and-Volatility-Checker 加/改板块后，要在**不碰生产、不写 Notion、不发布**的前提下证明「整页真能构建、板块真出现」。

## 1. 隔离目录（每次都用硬检查，别靠“应该没问题”）
1. `ISO=/tmp/eco_iso_<名>`；只 `cp -r src data`，**不拷 `.env`、`.git`、`docs`、`scratch`**；删 `data/kol_store.sqlite`（19MB）、`data/x_backfill`、`data/web_watch`、`data/tech_watch`。
2. 关 Notion 写入：用正则把 `write_stress_panels_notion`、`write_ofr_notion` 两个函数体首行改成 `return None`（`re.subn` 计数必须 ==2，否则 assert 退出）。其他写 Notion 的入口先 `grep api.notion.com` 确认没有漏。
3. 脚本末尾四条硬检查，任一失败 `exit 3-6`：`.env` 不存在 / Notion 屏蔽标记出现 2 次 / 新抓取函数在 ISO 里 / 新渲染函数在 ISO 里。
4. 后台跑 `cd $ISO && <项目 .venv>/bin/python -u src/build_dashboard.py > /tmp/x_build.log 2>&1; echo BUILD_EXIT=$? >> /tmp/x_build.log`（`background=true, notify_on_complete=true`，约 8 分钟）。
5. **启动后读日志首行**：第 3 行「KOL 当日快照已存: /tmp/eco_iso_…」证明写的是隔离目录；刚启动时日志文件可能还没创建（不是失败），用 `pgrep -af eco_iso_<名>` 数进程。

## 2. 构建后核对（不信通知的 exit 0）
- 日志末行 `BUILD_EXIT=0` + 门禁行「产物无字面 Markdown 星号」+ 新板块日志行 `status=ok`；`Traceback` 数；「已写 Notion」痕迹应为空。
- 板块清单对比：按 `<div class="part-title">` 抽标题，生产页 vs 新页做集合差——**生产有新页无 = 必须为 0**，新页有生产无 = 恰好是新加的。
- `div`/`script`/`style` 开闭数相等。

## 3. 无头 Chromium + CDP（复用 `~/.cdp-venv/bin/python`，它带 websocket）
- 浏览器：`~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome --headless=new --no-sandbox --remote-debugging-port=<空闲端口> --remote-allow-origins=*`。**缺 `--remote-allow-origins=*` 会 WebSocket 403**。每次用独立 `--user-data-dir`。
- 验：`Runtime.exceptionThrown` 数 =0；`#sidenav-links a` 含新板块（菜单靠 `.part-title` 自动生成，不用改菜单代码）；新板块内 `svg` 个数/`polyline` 数/`getBoundingClientRect`；窄屏 `Emulation.setDeviceMetricsOverride width=420 mobile=true` 后 `scrollWidth>innerWidth` 应为 false。
- **悬停测试的坑**：别随手选「屏宽 93%」当 2026 年初——位置要按数据算（`(ML+(W-ML-MR)*i/(n-1))/W`）。我选错位置读到 2025-10 的值，视觉分析误以为“曲线对不上”；改按数据算位置后读数与图一致。
- 截图后用 `vision_analyze` 逐条问：线色与图例、最粗线、轴标签重叠、线是否穿框、副图是否都出现；它说“看不清/被截断”就换滚动位置再截，别当通过。

## 4. 操作坑（本轮连踩）
- 一条命令里塞 `pgrep|wc && ls && cut`、或长 heredoc → 被 hardline 拦（exit -1，记录在 `~/.hermes/cache/blocked-scripts/`）。**拆成单命令重发，不要原样重试**。
- `/tmp` 会被系统清（`/tmp/bak_rl` 整个没了）：备份前先 `mkdir -p /tmp/bak_rl`，且 `&&` 链第一步失败会让后面全不执行——失败后先确认目标文件是否被改动（`grep -c 新函数名`）再继续。
- 提交前再测 ssh 证书：`timeout 15 ssh-add -l`（带 `Valid until` 即有效）；只 `git add` 点名文件，`git diff --cached --name-only` 对清单；红线正则含 `[0-9a-f]{40}`、`LOGIN_INFO`、`__Secure-1PSID`、`Bearer`。
