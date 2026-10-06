# X 网页抓取 vs API 实测 + 网站监测 cron (2026-10-05)

## 网页抓取(x_day.py 按天 since/until)对 API 真值的漏抓率
- Hunter 0/14, Gromen 9/261(3.4%)+22条截断, Gundlach 13/58(22%), 8 个高产号 185/771(24%) + 大量被截断。
- 已证伪: 「同日连发折叠」(当日仅1条也漏23%)、UTC日界、长推文、引用转推。根因未明, 疑 X 搜索索引不全。
- 结论: 低产账号网页够用; 高产账号不能冒充完整, 必须标 source=web「约漏四分之一」。
- 逐日文件同一帖会出现在相邻两个日文件(日志条数≈真实1.85倍), 汇总必须按帖子 id 去重。

## Chao 定的规则
- API 余额耗尽(402)/超预算 -> 自动回退网页逐个打开(队列 x_web_fallback_queue.json, 需 Chao 说「继续」才跑; 隧道只有他能重建)。
- 每个 KOL 在 X 上最多回填 1 个月; 日更只扫保留的 20 个账号(x_scan_exclude.json 排除 30 个), 月成本约 $3-6。
- 回填走 API 的口径: 估半年>240条的高产号不烧钱。

## 日更扫描坑
- search/recent 的 since_id 必须在7天内, 稀疏账号游标过期返回 400; 要改用 start_time=上次扫描时间。
- 单账号失败不能被吞: 曾显示「36/42 人」而6个账号全 400, 现输出「N 个账号没扫成」。
- cdp_probe.py 曾只放 /tmp, 网关重启后丢, 抓取报 ModuleNotFoundError -> 已放进 tools/x_backfill/。

## 网站监测(tools/web_watch.py, cron eco-vol-web-watch 每天 10:00 no_agent)
- 只接 King World News(wp-json) + Kitco(按类别 sitemap + 文章页 __NEXT_DATA__); 命中名册 KOL 才通知, 网站不 backfill。
- 实测不值得接: Zero Hedge/Peak Prosperity 近7天0个名册KOL; Real Vision/Hidden Forces RSS 是空壳; SilverDoctors 停更近一年; Financial Sense/Mining.com 403。★HTTP 200≠有内容, 要数 <item> 和 pubDate。
- Kitco 视频近8周46条仅命中名册4人; KWN 音频在 SoundCloud 私有轨道, 未转写。
- 访谈判据: 标题含 Interview/WEEKLY WRAP with/标题=嘉宾名, 或标题含嘉宾+正文「Watch the full interview」; 简介里「曾被采访」不算, 引语评论文标 mention。
- 名册无 Lyn Alden(Notion 未收); 我不能自行增删名册。我曾误判为「显示名被占位符化」, 实为名册里没有此人, 先读文件再断言。
