# 把视频截图里的图复制进看板 + 隔离整站验证（2026-10 实战）

适用：Chao 发一张直播/视频截图问「这图能做吗，放进 dashboard」。三张实例：金银「类比路径」图、黄金波动率图(StockCharts)、霍尔木兹通航时间线。

## 一、先分线核数据源，再决定做不做（诚实版）
1. 立即把截图转录成文字落盘（vision 逐项抄：标题/图例/轴/Source/标注），**不要指望图缓存还在**——`~/.hermes/cache/images/` 会被清，霍尔木兹原图一小时后就没了，之后无法逐行抄袭击表。
2. 每条线单独判：公开可得 / 部分可得 / 付费(Bloomberg、LSEG、Kpler、ICI 403)。付费的**不画、不拿别的数据冒充**，页面写「无公开日度数据」；图上明显笔误(如 "$895 Trillion" 实为 Billion)不照抄，写明。
3. 回复格式：先列「每条线能不能做」，再给「诚实版」方案和 2~3 个待决问题；Chao 回「agree/do/做」才动手。
4. 手画元素(阻力虚线、走势设想、圈、框)一律不画，页面写明。

## 二、常用公开源（均实测过）
- 金/银/GDX/SPY 日、周线：Yahoo chart API `GC=F`/`SI=F`/`GDX`/`SPY`（period1/period2 分段取，1980 年以前为空）。是 COMEX 连续期货，**不是现货/LBMA**，页面必须写。LBMA JSON、macrotrends、Nasdaq Data Link 本机 403/Cloudflare。
- 1973 金价：datahub `gold-prices/monthly.csv`(1833 起,仅月度)；FRED 无 1973/74 银日度。月度不画成日度，写说明。
- GVZ：FRED `GVZCLS`（API 通；fredgraph.csv 官网偶超时）。
- 霍尔木兹通航：IMF PortWatch ArcGIS `Daily_Chokepoints_Data` (portid=chokepoint6)，与 straits.live CSV 逐日对账 133 天 0 差异。
- 袭击事件：UKMTO 官网本机 403，但 `ukmto.org/-/media/.../*.pdf`（如 20261002-ukmto_vra_overview）web_extract 能读，有 143-26…147-26 编号；JMIC advisory PDF、gCaptain、Seatrade 可交叉印证。UKMTO 官方说明 **NCAGS 协调数约为 AIS 观测的 5 倍**（走南线的船多不开 AIS）——两条线口径不同。straits.live events.csv 只有近 3 天，覆盖不了半年。
- 别把红海/阿曼湾的 UKMTO 编号(095-26…098-26)算进霍尔木兹。

## 三、类比路径图的对齐（反推，不是真相）
- 以「1/28 起点缩放」做会对不上原图(2006 金线冲到 6,747 > 原图上限 6,000)。
- 改成：取各年 1 月底起 120 天内**最高收盘**对齐 2026 高点日，并缩放到 2026 高点价 → 金 2008 低点 +241 天≈3,737(原图 ~240 天/$3,850)，银 2008 +238 天≈$48(原图 ~$50)。只核了这两条线，页面如实写「其余未逐条核对」。

## 四、指标自算要拿图上读数对账
- 用图上标出的某日读数反推公式：5 条均线 SMA 偏差一致 +0.5%（=期货 vs 现货基差，且证明是 SMA；EMA 偏差 -0.4%~+8.8% 发散）；BB 宽度=(上-下)/中×100 总体σ，差 1~3%；ATR 用 Wilder，同量级；GVZ 完全一致。偏差一致=口径/基差，不一致=公式错。
- Yahoo 周线标记日为周六，最后一根是「本周未收完」，页面注明；悬停测试要选有代表性的位置(曾选在 2025-10 被视觉判读误以为不一致)。

## 五、隔离整站构建（会写生产 Notion 的构建脚本必须这样跑）
`scripts` 思路（用脚本文件，别 inline heredoc，长命令会被解析器拦 exit -1）：
1. 只拷 `src/` 和 `data/`，删 `.env`、`kol_store.sqlite`、`x_backfill`、`web_watch`、`tech_watch`。
2. 用 re.sub 把 `write_stress_panels_notion`/`write_ofr_notion` 两个函数体首行插入 `return None`。
3. **硬检查再启动**：`.env` 不存在、插桩计数==2、新函数在新副本里、渲染函数在 dashboard.py —— 任一失败 exit。
4. `background=true,notify_on_complete=true` 跑 `python -u src/build_dashboard.py > log; echo BUILD_EXIT=$? >> log`，约 8 分钟。
5. 完成后：读日志末行 BUILD_EXIT + 门禁行 + 新板块行；日志里写入路径全在隔离目录；对 **生产 docs/index.html 比 part-title 清单**（生产有新页无 必须为空，新页多出的只能是本轮新增）；div/script 开闭平衡。
6. 浏览器：`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --headless=new --no-sandbox --remote-debugging-port=P --remote-allow-origins=*`（缺最后一项 WebSocket 403），用 `~/.cdp-venv/bin/python` 的 websocket：查 JS 异常数、菜单含新板块、svg 数/polyline 数、dispatchEvent 悬停读数、420px 窄屏溢出、截图交 vision 看（截图要滚到下半部分再拍，否则只看到一半）。

## 六、本轮踩过的坑
- `/tmp/bak_rl` 备份目录会被清：`cp` 前先 `mkdir -p`，链式 `&&` 在此处中断导致后续没执行——写文件前断言+事后 grep 确认。
- 脚本里 `rep(旧,新)` 若新旧相同会因 count==0 断言失败，断言在写盘前所以文件没坏；别用 sed 删行去修脚本(会把 for 循环体删空)，重写整个脚本。
- 循环任务每轮 `git commit` 依赖 ssh 证书，几小时必过期：循环内设 `KOL_BF_NOPUSH=1`，跑完统一提交；提交前 `timeout 15 ssh-add -l` 看 Valid until。
- 后台进程「exit 0」通知不可信：读日志 BUILD_EXIT、产物、对账条数(sqlite 行数差==自报新增)。PortWatch/yt-dlp 类 exit 0 只表示命令跑完。
- 板块「done 147/147」≠有数据：按账号统计 0 条天占比(shaunrein 146/147 天为 0)。
- yt-dlp 带 cookie 时会回写 cookie 文件；YouTube 在机房 IP 上几次请求后会服务端撤销登录态(LOGIN_INFO/SID/__Secure-1PSID 被删)→ 带 cookie 也 429/Sign in。别指望它做半年回填；备选=播客 RSS(anchor.fm iTunes feed 有精确日期/时长/简介/音频直链,VM 不被封)。用后立刻删临时 cookie 文件并告知聊天里的值已失效。
