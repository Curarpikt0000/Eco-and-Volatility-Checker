# X 采集：API 与网页实测对照 + 网站监测（2026-10-05 Eco 实战）

> 权威沉淀在 ChaoWiki `pipelines/kol-tracking/insight.md`「X 采集：API 与网页的实测对照」(commit 2350864)。本文件是操作要点，给下次直接开工用。

## 决策结论
- **日更走 API，网页只做兜底**。网页(浏览器逐日 `from:X since: until:`)对高产号漏约 24%(8 号 771 对 588)，对稀疏号≈0%(14 对 14)。漏抓与当日条数/发帖时刻/长推文/引用转推无关；换查询(去过滤/热门/6 小时窗)全试过无效，根因未查清。
- 网页补的数据只能标 `source=web` +「约漏四分之一」，不得冒充完整。
- 不为「补历史」充值：窗口压到每人 1 个月后，历史靠日更累积。

## 三个「显示正常实际没扫成」的坑
1. **`since_id` 必须在 7 天内**，否则 search/recent 返回 400；稀疏号游标帖龄>7 天会静默失败(今天 cron 6/42 这样没扫成，只显示「36/42」)。帖龄=`((id>>22)+1288834974657)`ms；≥6 天改 `start_time`。「N/M」汇总必须单列失败账号；熔断只看「连续 3 次」会漏分散失败。
2. **日志条数重复计数约 1.85 倍**(`since:/until:` 使同一帖落在相邻两日文件)；入账前按帖子 id 去重(1106→597)。
3. **HTTP 200 ≠ 有内容**：RSS 200 但 0 item，或最新一条停在一年前。接站前读条目数+最新日期。

## 计量/价格
- 读帖 $0.005/条，读用户 $0.01/个，同资源同 UTC 日去重；分页边界每页多 1 条也计费。
- `counts/all` 对 `-is:reply -is:retweet` 无效，不能估价；用「读最新 10 条推窗口总量」。
- 用量计数器非实时，不能据此说空扫免费；耗尽以 HTTP 402 为准，账本只是本地估算。
- 每页落盘；熔断写了必须实测拦得住才算数。

## 同名路人
机构词门禁会被通用词满足而放行同名路人(牧师/法学生/小说家)；verified 的也要抽查；维护可逆排除表。

## 网站监测(web_watch.py，no_agent cron)
- KWN: WordPress `wp-json/wp/v2/posts?per_page=100&after=...`；Kitco: 按类别 sitemap(`/static-sitemaps/{news,opinions,video}.xml`) + 文章页 `__NEXT_DATA__` 的 `props.pageProps.articleData.bodyWithEmbeddedMedia.value`(视频页用 ld+json)。不开浏览器、不花钱。
- **选站看名册命中数不看站名**：近 7 天只有 KWN、Kitco 命中；Zero Hedge/Peak Prosperity 通但 0 命中不接。
- **访谈判据收紧**：「正文含 interview」会把简介「曾被采访过」、引语标题评论文误判。要标题含 Interview/Broadcast/WEEKLY WRAP with/标题即嘉宾名，或 Kitco「Watch the full interview」；其余 `mention`，不当 KOL 言论。
- 匹配只认名册全名(≥2 词)在标题或正文前 900 字。
- 干跑验证入口脚本时库已含「已见」→首日 0 通知正常，要提前告诉 Chao。
- 音频：KWN 在 SoundCloud 私有轨道，Kitco 访谈嵌 YouTube；只记来源不转写，下载未验证。
- 名册没收的人不会命中；归因前先直接读 `data/kol_registry.json`，别凭推断说显示名被占位符化。

## 操作纪律
- 杀后台：`pgrep -af`→`kill <PID>`(不用 `pkill -f`)→再 `pgrep` 确认 0；遗留 `x_day.py` 子进程一并杀。
- inline heredoc 过长会被解析器 hard block：写 `/tmp/xxx.py` 再跑。
- 要留的诊断脚本存项目目录，`/tmp` 网关重启会丢。
- 隧道 `localhost:9333` 用前必 `curl /json/version`。
