# X 日更扫描 + 网站监测：实测踩坑清单（Eco 2026-10-05）

只放可复用的判据与做法，不放账号明细/原文/密钥。

## 1. 网页 vs API（X 回填）
- 网页按天搜索(`from:X since: until:`)对**高产号漏约 24%**（8 号 771 对 588），稀疏号≈0%。漏抓与当日条数/发帖时刻/长推文/引用转推**都无关**（按条数分组 20-30% 平坦）；换查询(去过滤/热门/6h窗)无法找回。结论：网页只能标 `source=web`+「约漏四分之一」，高产号「每条都要」口径做不到。
- `counts/all` 对 `-is:reply -is:retweet` 无效，估价用「读最新10条推窗口总量」。用量计数器非实时，真实耗尽以 HTTP 402 为准。
- 汇总条数必须按**帖子 id 去重**：`since:/until:` 使同帖出现在相邻两日文件，日志约虚高 1.85 倍。

## 2. 日更脚本三个静默失败
1. `since_id` 必须在 7 天内，否则 API 400。稀疏账号游标帖龄>=6 天要改 `start_time`。帖龄 = `(id>>22)+1288834974657` 毫秒。
2. 「N/M 已扫」汇总必须**单独列出失败账号**；熔断只看「连续失败」会漏掉分散失败（实际 6/42 没扫成却显示正常）。
3. HTTP 200 ≠ 有内容：接站点前必读条目数与最新日期（RSS 空壳、停更近一年的站都返回 200）。
- 预算熔断必须实测拦得住才算数（设低上限实测被拦）。

## 3. 网站监测(no_agent)设计
- 取数用公开接口：WordPress `wp-json`(一次100篇)；无 RSS 的站用按类别 sitemap + 文章页 `__NEXT_DATA__`。不开浏览器、不花钱。
- **选站看「名册命中数」不看站名**：对名册全名做近7天匹配，0 命中不接。
- 名册匹配用整词全名(>=2词)；先读名册原文件再归因，别凭推断（曾误称「显示名被占位符化」，实为名册没收该人）。
- 访谈判据要收紧：「正文含 interview」会把简介里「曾被采访过」、标题是引语的评论文误判。只认：标题含 Interview/Broadcast/WEEKLY WRAP with/标题整个是嘉宾名，或「Watch the full interview」。评论类标 mention，不当 KOL 言论。
- 干跑验证入口脚本时库是空的：已见条目不补发，首日 0 通知是正常，须提前告知。
- 技术派筛选：标题含技术词 AND 正文>=2 个不同技术词 AND >=2 个价位数字，才算技术分析；价位只许抄原文原句。

## 4. 通用
- 脚本在 `tools/` 下取 `dirname×2` 作项目根，多一层读不到名册。
- 诊断脚本只放 /tmp 网关重启即丢，要留的存项目目录。
- 长 prompt 建 cron：命令行传会被解析器拦，用 Python 读文件后 subprocess 调 `hermes cron create`，再读 `~/.hermes/cron/jobs.json` 核对 model/schedule/prompt。
- 调 claude-opus-5-5 经 :8800 返回 `choices: null` 且 completion_tokens==max_tokens：是思考吃光 max_tokens，非限流；`max_tokens` 开到 7000+ 并在问题末尾加硬字数上限，脚本里判空就退出不编。

## 5. 数据源可达性实测（VM 数据中心 IP，2026-10-05）
- YouTube 字幕：`youtube_transcript_api` IpBlocked；`yt-dlp` 裸/带未过期 cookies 均 429 + 「Sign in to confirm you're not a bot」；视频页本身 429。换 cookies 无效，音频→ASR 也绕不开（拿流要先调同一 player 接口）。只有 RSS(`feeds/videos.xml?channel_id=`) 可读标题/发布日。
- KWN 访谈音频是 SoundCloud 私有轨道(secret_token)，无 mp3 直链/播客 RSS；公开单曲 yt-dlp 正常(对照组)，私有轨道 401，需 client_id（未取到，属灰区未继续）。Kitco 无音频/播客入口，访谈载体是 YouTube。
- 技术派频道的文字站：Vermeulen 站只有~330字配文无价位；Roy-Byrne 站需完整 Chrome UA(简单 UA 403)，免费摘要~200字、周刊为付费登录下载。点位在视频/付费刊里。
