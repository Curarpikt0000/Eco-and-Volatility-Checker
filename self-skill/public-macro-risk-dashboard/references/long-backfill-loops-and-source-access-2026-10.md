# 长回填循环 / 源头可达性 / 低频标注 — 2026-10 实测要点

（SKILL.md 已满，本文件无正文指针；开工 X/KOL/YouTube 回填或加频率徽章前先读。）

## 1. KOL 全量回填循环：提交不能放进每轮
- `tools/kol_new_backfill.sh` 每轮 6 人并行(~6-16 分钟)，每人最多试 2 次；循环 `tools/kol_backfill_loop.sh` 最多 24 轮。
- **事故**：第 2 轮抓取+入库成功，卡在 `git commit`——pre-commit 钩子(asd-cli)靠 ssh 证书，`ssh-add -l` 超时/"no identities" 即钩子失败，数据已入库却未提交。证书有效期仅数小时，5 小时循环中途过期是大概率事件。
- **解法**：循环里传 `KOL_BF_NOPUSH=1`(原脚本自带开关)，跑完统一 `git add` 点名文件(kol_store.sqlite + 账本)提交一次。不绕钩子。每轮前把当天 `scratch/kol_bf_auto_日期` 改名挪开不删，否则同日 STATUS=DONE 直接退出。
- 提交前先 `timeout 15 ssh-add -l` 验证证书（Chao 说「好了」也要自己验）。
- 判终止原因读 `scratch/kol_loop.log` 的 LOOP_END 行，不信「completed normally」。对账：sqlite 行数(工作区 vs `git show HEAD:...`)之差 = 循环自报新增条数。
- 「待补」口径：`tools/kol_backfill_detect.py --all`；已试满 2 次仍不足 12 个月的人不再自动重试，只报告。

## 2. X 网页回填「done」≠有数据
- 进程报 `done 147/147` 因为「抓到 0 条」也算完成。**入库前必须按账号核落盘**：计划天/落盘天/0 条天占比/去重后条数。实例：shaunrein 147 天 146 天为 0 条(只 2 帖)——失败；CathieDWood 62% 天为 0 条——存疑；>40% 零条天的账号都要抽样对照。
- 日期取帖自带时间戳、按帖 id 去重；`since/until` 按 UTC 切，单日文件会串日(样板：日文件条数虚高 ~21%)。
- VM 专用 Chrome 走 `CDP_PORT=9444`，**不要传 CDP_HOST**(显示层把 IP 字面值改写成占位串→连不上)。

## 3. YouTube：VM 机房 IP 被封，cookie 不可持续
- `yt-dlp --flat-playlist` 能列整个频道(标题+ID)但**无上传日期**；单视频页 429 + "Sign in to confirm you're not a bot"。
- 用户给的登录 cookie 只管用了一两次：yt-dlp 每次运行会回写 cookie 文件，**服务端撤销后 LOGIN_INFO/SID/__Secure-1PSID/SAPISID 等 8 个登录字段被删**，全新原始 cookie 重测同一视频也失败 = 会话被 YouTube 作废(机房 IP 触发)。不要再让用户贴 cookie 重试同一路线；用完立即删临时 cookie 文件(核路径后 rm)。
- **绕开 YouTube 的可达通道**(均无需登录、VM 通)：
  - 频道官方 RSS `https://www.youtube.com/feeds/videos.xml?channel_id=UC...`(channel_id 从频道主页 HTML 抓；只有最近 15 条，带精确 published)。
  - **播客 RSS**：iTunes 搜索 API `itunes.apple.com/search?media=podcast&term=...` 取 `feedUrl`(如 anchor.fm)，整档全量历史，每期有精确 pubDate/时长/简介/音频直链(Range 取 200KB 可验证可下)。David Lin Report 实测 1026 期，半年窗口 226 期。
- 访谈频道标题格式「主题 | 嘉宾」→ 机械抽嘉宾；与名册匹配用「名+姓整词同时一致」，名册取 `short_name` 开头拉丁字母部分(registry 字段是 display_name/short_name，没有 name)。实测半年窗口命中 36 期/16 人。
- 语音转写：VM 未装 whisper；成本/通道须先问再做，不自行开跑。一手言论口径：只摘嘉宾本人话，不收主持人。

## 4. 低频板块徽章与官方源核对
- 「已是官方最新」是强断言：只对回官方源实测过的才用(美国黄金出口 FRED IEAXGG、信贷脉冲)。BIS 黄金掉期是「我们没跟上」(8 月起 PDF 路径改为 `publications/statement-account-31-august-2026.pdf`)，不能用该措辞。
- COT：数据日=周二，发布=周五(CFTC 数据集 `6dca-aqww`)；「怎么还是上周」先查官方全表最新日 + 对照组，再决定是否只是缺说明行。
- 只写读到原文的月值(GATA/GoldSeek)，从摘要反推的月份留断点并标注。`latest` 取最后一个 annual 点，别让月度推算点被标成年报。

## 5. IIP 季频接入模式
- IMF 季频到 2026-Q2；折线=年频实线+季频虚线空心点，柱状图用最新季。**任一国缺季频则整体退回年频**(不混期别)。
- 验证：新抓取用临时文件，逐字节 `cmp` 真实缓存未变；年频序列与旧缓存逐点一致；模拟缺季频时 svg 与旧版逐字节相同。

## 6. 复制别人的图前先探源(霍尔木兹案例)
- 先逐条线判可复制性再动手：AIS 日度通航=IMF PortWatch ArcGIS(`Daily_Chokepoints_Data`, portid=chokepoint6)，与 straits.live CSV 逐日对账 133 天 0 差异；袭击事件=UKMTO 逐条编号核对；NCAGS 日度、Kpler 日度流量无公开表(Kpler 付费，仅博客周快照)→如实标「无公开日度数据」，不描图造数。
- 图上文字数字(如 AIS 峰值 61)与官方逐日最大值(51)对不上时，写官方值并说明口径未知，不抄。
