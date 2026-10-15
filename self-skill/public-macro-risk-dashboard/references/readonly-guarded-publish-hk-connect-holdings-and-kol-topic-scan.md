# 只读守卫发布 / 港股通持股存量 / KOL 库主题扫描 (2026-10-13~14 实战)

## 1. 发布别用隔离构建产物(会让线上板块退化)
- 隔离目录无 `.env` → `fetch_china_liquidity()` 等 Notion 依赖板块变「未就绪」、ETF 份额/两融图为空。**拿它覆盖线上=线上退化**(实测对比:隔离页「宽基 ETF 份额」0 处、线上 3 处)。
- 发布前必做:抽 3~5 个依赖 Notion 的板块特征串,新页 vs 线上旧页逐项计数(`未就绪`/`同步中`/`宽基 ETF 份额`/`融资融券余额反映`),任何一项变少=不许发。
- 正解=**在项目目录(有 .env)构建,但 Notion 只读**。不改源码:用包装脚本在运行时替换 Notion 请求出口:
  `import notion_writer as nw; nw._req = guard; import external_data as ed; ed._req = guard`(external_data 是 `from notion_writer import _req`,导入时已绑定副本,**必须导入后再覆盖它自己的名字**;再遍历 `sys.modules` 把其余同引用的模块也换掉),`runpy.run_path('src/build_dashboard.py', run_name='__main__')`。
  guard 放行:GET、以及 `POST …/query`(Notion 查库是 POST);其余(PATCH/DELETE/POST /pages/blocks)返回 `(403,{})` 并记账,结束时打印「放行读 N 次/拒绝写 M 次」当证据。
- ★用前先写自测脚本:`_req` 换成假函数记录真正发出的请求,喂 6 种 method/path,确认只有 GET 与 /query 真发出(实测通过再跑真构建)。先 `grep requests.request|post|patch src/external_data.py` 确认没有绕过 `_req` 的直接 HTTP 写。
- 副作用要如实告诉 Chao:构建里「国债压力/OFR 最新值写 Notion」被拦(日志 `[notion] upsert FAIL 403`),当天不写,次日 cron 照写。
- 构建前备份 `docs/index.html` 到 /tmp;发完 `curl` 读回比 sha256。Chao 对「会写 Notion 的构建」要单独问「允许吗」,他答「允许」才跑。

## 2. 港股通(南向)持股存量日频(回填)
- 源:`RPT_MUTUAL_STOCK_HOLDRANKS`,`MUTUAL_TYPE=002`,**2024-10-14 起日频**(再早没有),每日约 667 只、2 页(500/页),~2.4 秒/日,473 个交易日≈18 分钟。
- ★**002(沪港通下)与 004(深港通下)返回同一份全量持股**(667 只持股数逐只相同)。两通道相加=翻倍(我曾报 9.73/11.76 万亿港元,正确是 5.88)。只取 002,采集器里写明。
- 采集器要点:交易日历借南向净买入存档的日期;**最近日期优先抓**、限时 budget_s、结束一次性原子落盘(tmp+replace)→ 回填过程中文件不变是正常,别误判卡住;空数据记 failed 下次重试;增量接入 build_dashboard(每次 120s 补缺)。
- 校验:单日大跌与恒指同日同幅(2025-04-03→04-07 持股市值 -13.3% vs 恒指 -13.2%=价格效应非错数);间隔>5 天都对应春节/五一/国庆休市。存量含价格涨跌,不等于净买入(粗对账:同期南向净买入 2.13 万亿 vs 持股增量 2.55 万亿)。
- 北向 `RPT_MUTUAL_MARKET_STA`(005)只存最近几期(当时 4 期,含新出现的 2026-09-30),无历史可补,靠每次运行并入存档逐季积累;`RPT_MUTUAL_HOLDSTOCKNORTH_STA` 只有 2 个季度快照。"能不能 backfill" 的答案=南向能、北向不能,别含糊。

## 3. 在 KOL 库里扫某主题(如铀/URA)——「到底了吗」的做法
- 查实物 `data/kol_store.sqlite`(opinion 表:kol_name/date/direction/comments/targets/detail/source_url),不查对话史。窗口用 `date>=今天-14`。
- 两档匹配:强=点名标的/公司/ETF 代码(`\bURA\b|URNM|SPUT|Cameco|NexGen|Kazatomprom|…|1164`),弱=只有「铀/uranium」一词;**对 comments/targets/detail/source_title 四个字段都搜**(铀常只出现在 detail 里)。
- 去重键 `(kol, url, comments[:60])`:同一条言论会按日重复入库(10-14 条 → 55 条去重)。输出「首现~末现 ×n」。
- 结论口径:强相关人数/条数 + 弱相关(标的清单里一带而过)分开报;**「没有专门分析」只在我们抓到的范围内成立**,缺人是名册问题,名册增删只能 Chao 在 Notion 做,我只列候选+证据让他选。
- 弱命中里要读片段区分「有论述」与「并列一句」(多数是后者,如 Lobo Tiggre「铜最高确信、铀次优」)。
