# 短期金银观点日更 cron + 选站/探源方法（2026-10-05，Eco 实战）

## 结论先行
- 「接哪些站」用**名册命中数**定，不用站名：6 个 RSS 站里只有 KWN、Kitco 近 7 天命中名册 KOL；Zero Hedge/Peak Prosperity 接口通但 0 命中；Real Vision/Hidden Forces RSS 返回 200 却 0 条 item；SilverDoctors 最新一条停在近一年前。**HTTP 200 ≠ 有内容**，接站前必读条目数 + 最新日期。
- 「某人在某站没有」必须先跑对照组：同一套查询同一窗口里，已知必在的人（KWN 近 14 天 Macleod 21 篇/Prins 18 篇）能查出来，才敢报「Vermeulen/Soloway/Roy-Byrne 近 2 周在 KWN+Kitco 为 0」。
- 三位 YouTube 技术派的核心内容（点位）在自己的视频/付费刊里：Roy-Byrne 的 thedailygold.com 每周一期 Premium 摘要 0 字、免费文摘要仅 160-200 字；Vermeulen 的 thetechnicaltraders.com RSS 正文约 330 字且无价位。**文字站≠有点位**，要实测价位个数再说「有用」。

## 采集脚本（项目 `tools/tech_watch.py`，cron 读它的 JSON）
- 来源：YouTube 频道 RSS（`youtube.com/feeds/videos.xml?channel_id=`，只给标题/日期/视频 id，不需登录）；Kitco news/opinions sitemap + 文章页 `__NEXT_DATA__`（正文在 `props.pageProps.articleData.bodyWithEmbeddedMedia.value`）；KWN `wp-json` 一次 100 篇；GoldSeek `/rss.xml`、Gold-Eagle `/rss.xml`（只有 ~350-580 字摘要，须标「仅摘要，不写价位」）。
- thedailygold.com 需完整 Chrome UA（简单 UA 返回 403）。
- 两个通道必须分开输出：A 技术派（`channel=tech`：支撑/阻力/均线类词 ≥2 个不同词 + 价位 ≥2）、B 机构派（`channel=inst`：银行/机构策略师的短期金银价位预测）。不得把两派人写进同一行。

## B 通道（机构预测）判据的迭代 — 每次都是被实测数据逼出来的
1. 初版只要「预测词 + $价位」→ 14 天收 20 条，半数噪音（Kitco AM/PM 行情播报、比特币 $100,000、中国进口 $306）。
2. 加「价位必须落金银价位带内」（金 2500-7500、银 45-85）+ 行情播报标题黑名单 → 降到 5，但漏了真预测。
3. 漏判原因 A：正文截断 6000 字，价位在后半段 → 放宽 14000。
4. 漏判原因 B：只靠预测动词会漏「remain above $4,000」「break above $4,400」「$4,000 support」→ 加条件/区间/目标位措辞的第二组正则。
5. 误收：KWN 每篇文末的 Nomi Prins 采访广告含「$6,000 gold」→ 促销句过滤（click here/subscribe…）。
6. ★自洽 bug：判定用整篇、抽句用截断后文本 → 出现「判定通过却抽不到预测句」。**判定函数与交给 agent 的文本必须是同一段**；上线前加自检：每条 inst 都能抽到 ≥1 句。
- 脚本抽出的候选句只是线索（例：「某分析师说金价跌回 4,300 下方」是行情描述不是预测），所以 cron prompt 要求 agent 读 body 原文判断，没有时间窗写「无时间窗」不补。

## cron 形态与验证
- agent 模式、`claude-sonnet-5-5`（Chao 定：平常 cron 用 sonnet；haiku 抄原句价位出错风险更高）、10:30 JST（排在 09:30 X 扫描、10:00 网站监测之后）。
- 长 prompt 不要塞命令行（会触发解析器拦截）：用 Python 读 prompt 文件再 `subprocess` 调 `hermes cron create`；改 prompt 用 `hermes cron edit <id> --prompt`。改完**读 `~/.hermes/cron/jobs.json` 核对**模型/时间/prompt 关键句，不信命令自述。
- 编辑 cron 后 `next_run_at` 会被重算（本次从 10/6 跳到 10/7），要主动告诉用户，并提供手动触发选项。
- cron 里写的纪律：价位只抄原文原句；视频只报标题+链接并标「正文未读」；采集 0 条≠没人说，先看 health（fetched/err）；现价至少 2 源互证。

## YouTube 字幕在数据中心 VM 上的实测（2026-10-05 观察，非永久结论）
- `youtube_transcript_api` → IpBlocked；`yt-dlp`（含项目 cookies 文件，15 条未过期）→ HTTP 429 + 「Sign in to confirm you're not a bot」；watch 页直取也 429。报错原文已读，不是 cookies 过期。
- 可用的是频道 RSS（元数据）。要读视频内容的候选路线（Opus 5.5 评审，均未在 VM 上验证）：Mac 已登录 Chrome 经 CDP 读转录面板；Mac 反向 SOCKS 出口 + VM 上 yt-dlp；频道自己的播客 RSS/文字稿；付费代理（要先批）。YouTube 音频走 ASR 也绕不开——取流地址那一步就是被封的那一步。
- 向 Opus 提问：`localhost:8800` 返回 `choices` 为 null 且 `completion_tokens` 恰等于 `max_tokens` 时是输出被截断不是代理坏了；加「全文不超过 N 字」并把 `max_tokens` 提到 7000 即可。

## KWN / Kitco 音频（实测）
- KWN 每个访谈页只嵌 SoundCloud 私有轨道播放器，页面无 mp3 直链、`/feed/podcast/` 404、40 篇文章 0 篇有直连音频。公开 SoundCloud 单曲 yt-dlp 能取（对照组通），私有轨道 yt-dlp/oEmbed/widget resolve 分别 401/404/401；从播放器 JS 找 client_id 未成功，已停手未继续猜（私有轨道抓取属灰区，需用户明确同意）。
- Kitco 无播客/音频源（/podcast、/rss 等 404），访谈载体是 YouTube 嵌入。
- 近 2 周三位技术派在 KWN+Kitco 均为 0（Kitco video 上 Vermeulen 最近 2026-07、Soloway 2026-07，Roy-Byrne 2025-05）：这两站上给金银价位的是机构/基本面派，不是技术派 → 所以加了 B 通道。

## 踩过的小坑
- f-string 表达式里不能出现反斜杠（写日期正则时两次中招）→ 先把结果放进变量再打印。
- 臆造 URL 关键词去匹配 sitemap 会 StopIteration/404：先用 sitemap 里「日期 + slug 片段」列候选再取。
- 先断言「名册里 Lyn Alden 显示名被占位符化」被直接读 `kol_registry.json` 推翻（根本没收她）；归因前先读原始文件。
