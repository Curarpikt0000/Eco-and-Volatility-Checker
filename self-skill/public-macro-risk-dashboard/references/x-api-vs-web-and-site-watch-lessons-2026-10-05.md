# X 采集 API vs 网页实测 + 网站监测 + 技术派日报（2026-10-05，Eco 实战）

> 补充 `x-web-vs-api-and-site-watch-2026-10-05.md`（若存在）。本文件只记本轮新增的可复用判据与坑。

## 1. 网页兜底的真实质量（决策依据）
- 浏览器逐日搜索 `from:X since:D until:D+1`：稀疏号漏≈0%（14对14），高产号**漏约24%**（8号 API 771 条 vs 网页 588 条）。
- 漏抓与当日条数、发帖小时、长推文、引用转推**都无关**（按条数分组 20–30% 平坦）→ 「同日连发折叠」「UTC日界」两个假设均被证伪；换排序/去过滤/6小时窗都找不回。结论：**网页数据一律标 source=web+「约漏四分之一」，高产号「每条都要」只能走 API**。
- 日志条数按**帖子 id 去重**再汇报：`since:/until:` 使同帖出现在相邻两个日文件，日志≈真实×1.85。

## 2. 日更扫描三个静默失败
1. `since_id` 必须在 7 天内，否则 HTTP 400。稀疏号游标帖龄>7天会静默失败，脚本只显示「36/42」。帖龄=雪花ID>>22 +1288834974657ms；≥6天改 `start_time`。**任何「N/M」汇总必须单列失败账号**，只看「连续失败」的熔断会漏掉分散失败。
2. 上次自动 cron 跑完不等于成功：直接读账本/last 文件对账（本轮靠账本只有15个账号入账才发现）。
3. 预算熔断写了没实测不算有效；用把上限调到刚低于需求的方式实测会被拦。

## 3. 选站/接站判据
- 选站看「名册 205 人对近 7 天条目的命中数」，不看站名。实测只 KWN、Kitco 有命中；Zero Hedge/Peak Prosperity 接口通但 0 命中。
- **HTTP 200≠有内容**：RSS 返回 200 但 0 个 `<item>`（Real Vision、Hidden Forces），或最新条目停在一年前（SilverDoctors）。接站前必读条目数+最新日期。
- Kitco：无 RSS；用 `static-sitemaps/{news,opinions,video}.xml`（URL 带日期）+ 文章页 `__NEXT_DATA__`→`props.pageProps.articleData.bodyWithEmbeddedMedia.value`；视频页读 ld+json VideoObject。KWN：`wp-json/wp/v2/posts?per_page=100&after=`。
- 访谈判据要收紧：简介里「曾被采访过」、标题是引语的评论文会被「正文含 interview」误判。只认：标题含 Interview/Broadcast/WEEKLY WRAP with/标题整个是嘉宾名，或 Kitco 式「Watch the full interview」。评论类标 mention，**不当 KOL 言论**。
- 干跑验证入口脚本若先清库再跑，首日会 0 通知（已见条目不补发），要提前告知。

## 4. 归因前先读原始文件（本轮自己错过）
- 先断言「名册里某人显示名被占位符化」，直接读 `kol_registry.json` 才发现是名册根本没收她。归因前 `grep`/读原文件，不凭推断。

## 5. YouTube 字幕在 VM 上读不到（2026-10-05 实测，环境类，勿当永久结论）
- youtube_transcript_api 报 IpBlocked；yt-dlp 裸请求与带项目 cookies（15条未过期）均 429 + 「Sign in to confirm you're not a bot」→ VM 数据中心 IP 被判机器人，换 cookies 无效。
- 频道 RSS `youtube.com/feeds/videos.xml?channel_id=` 不受影响，可拿标题/发布日/视频ID。
- 因此日报对 Vermeulen/Soloway/Roy-Byrne 只能报「发了什么视频，正文未读」，不得从标题推断价位。读正文需走 Chao 已登录 Chrome 隧道（不能无人值守）。
- `yt-dlp` 在 `~/.local/bin`，`which` 找不到是 PATH 问题，用绝对路径。

## 6. 技术派金银日报 cron 设计（eco-vol-tech-gold-silver，每天 10:30）
- 采集脚本 `tools/tech_watch.py`：YouTube RSS + Kitco sitemap + GoldSeek/Gold-Eagle RSS；输出 health(fetched/ok/err)+new 条目 JSON，agent 只写日报。
- 「只收技术分析派」(Chao 要求)：Kitco 标题含技术词 **且** 正文≥2个不同技术词+≥2个价位数字（否则基本面采访如 “…supports strong outlook” 会混入）。Gold-Eagle 只给 350–580 字摘要→标「仅摘要」不写价位；GoldSeek 摘要带 Drupal 残留标签需剥。
- 价位正则要排除年份/百分比；全文可能 2 万字，只截前 6000 会漏结论，深读用 web_extract。
- agent 铁律：价位只抄原文原句；视频标「正文未读」；取现价至少2源互证；0条≠没人说；同篇多源转载只算一篇。
- 建 cron 的长 prompt 走 Python subprocess 传参（命令行内联会被解析器拦）：`hermes cron create '<cron>' '<prompt>' --name … --model claude-haiku-4-5 --provider custom --workdir …`。haiku 抄价位易错，若核对原文对不上换回 sonnet-5-5。
