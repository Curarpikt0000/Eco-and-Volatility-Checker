# KOL 网站每日监测(KWN + Kitco) — 探测结论与匹配器坑 (2026-10-05)

Chao 要求: 挑几个像 kingworldnews/Kitco 的站放进 cron 每日检测(不 backfill), 尤其 Kitco 访谈。脚本 tools/web_watch.py (no_agent, 静默即正常)。

## 取数通道(均实测 200, 不用浏览器、不花钱)
- King World News: WordPress wp-json/wp/v2/posts?per_page=100&after=YYYY-MM-DDT00:00:00&_fields=id,date,link,title,content 一次 100 篇。正文里没有音频标记; 音频是页面渲染后才出现的 SoundCloud 嵌入(带 secret_token 私有链接), 接口取不到, 没验证能否下载/转写 → 只取文字, 不承诺音频。先用 REST 看正文判「无音频」是错的, 需渲染 DOM 查 iframe。
- Kitco: 无 RSS、无 wp-json(404)。用类别 sitemap /static-sitemaps/{news,opinions,video}.xml(URL 带日期, 可只取新增); 文章页是 Next.js, 正文在 __NEXT_DATA__ -> props.pageProps.articleData.bodyWithEmbeddedMedia.value(另有 title/createdAt/author/tags/summaryBullets); 视频页走 ld+json VideoObject(name/description/uploadDate/duration)。访谈特征 = 标题「嘉宾 says/is...」+ 正文末「Watch the full interview」+ 嵌入 YouTube; 近 30 篇仅 2 篇同时具备。

## 干跑暴露的匹配器漏洞(建 cron 前必须先修)
1. 名册显示名在本机被匿名化成占位符(display_name 读出 ANONYMIZED_PERSON_x), 用「全名」匹配对这类人天然失效 → Kitco 的 Lyn Alden 访谈被漏(命中 [])。改用 short_name/id/search_terms 多字段匹配前, 先验证这些字段是否也被占位符化。名册铁律: 不自行增删/改 KOL。
2. 「访谈」判据过松: 正文前 1500 字出现 interview 就判访谈 → 把嘉宾简介里的「has been interviewed in media」当成本篇是访谈; 引语型评论标题(如「RAY DALIO: ...」)被误标 interview。收紧: KWN 标题含 Interview / WEEKLY WRAP with, 或正文前 300 字出现嘉宾名+interview; 评论文章一律 mention; Kitco 要「Watch the full...」+嵌入 YouTube 同时满足。
3. 不要用姓氏单词匹配(同名污染); 命中口径=全名整词, 且只算标题/正文前 ~900 字。

## 其他
- 来源健康: 工作日某来源 0 条新条目 → 报「来源可疑」, 不写成「没内容」。
- 原文只落本地 _bodies/(gitignore), items.json 只存标题/链接/日期/来源/命中KOL/类型/媒体id。
- 未验证的站别接: Real Vision/Macrovoices/GoldSeek/SilverDoctors 等逐个先测接口与反爬再说。
- tools/ 下脚本 ROOT 只需上溯两层(写成三层会找不到 data/)。
