# A股资金面 / 金银板块 / 发布安全 (2026-10-10~14 实战)

## 1. 发布安全: 隔离构建页绝不能覆盖线上 (最重要)
- 隔离副本(rsync 掉 .env)整站构建读不到 Notion → `中国央行流动性` 整块变「未就绪」,ETF 份额图/两融图为空,`同步中/未获取` 标记数上升。
- 发布前必做: 对比 线上现行页 / 隔离构建页 的退化标记(`未就绪`、`同步中`、`宽基 ETF 份额`、`融资融券余额反映` 是否还在)。隔离页只用来验证「新板块渲染/JS/菜单顺序/板块不丢」,**不是发布物**。
- 发布物 = 带 .env 的正式构建(cron 的 `python src/build_dashboard.py`)。先确认它不会写 Notion 再跑,或等 11:00 cron。
- 10-10 曾用隔离页发布,事后才发现这条风险;线上随后被 cron 覆盖才恢复。

## 2. 先单块渲染验证,再跑 9 分钟整站构建
`import dashboard as d; d._xxx_html(真数据)` → 写成最小 HTML → playwright 截图 + 数 `[data-tip]`。改图表细节只重跑这一块,最后才整站一次。vision 能抓到: 单位标签压最高刻度(ylab 放到 x=ml、mt 加到 24)、首个日期标签被裁(i==0 用 text-anchor=start)。

## 3. 板块物理挪位 + 菜单分组
- 模板里每个板块 = 注释 + part-title + card 约 3 行;用脚本按 part-title 定位块重排,断言 `sorted(new_lines)==sorted(old_lines)` 证明纯搬运。
- 菜单严格按 DOM 序渲染(分组只是相邻小标题)。新组放 GROUPS 数组**最前**(首个匹配优先),并把被孤立的 1 项小组并入相邻组。
- 校验: 浏览器里 `#sidenav-links a` 的 href 序列 === 带 .part-num 的 `.part-title` id 序列;旧标题集合无丢失。新板块要给 `id="sec-xxx"`。

## 4. 东方财富 datacenter-web 接口实测 (A股/港股资金)
基址 `https://datacenter-web.eastmoney.com/api/data/v1/get`,params: reportName/columns/filter/pageNumber/pageSize(≤500)/sortColumns/sortTypes/source=WEB/client=WEB,Referer 设 data.eastmoney.com。
- `RPT_F10_EH_FREEHOLDERS` 十大流通股东: `(HOLDER_NEWTYPE="国家队")(END_DATE='YYYY-MM-DD')` → 汇金投资/汇金资管/证金三家; 2018 起季频。**陷阱**: 掉出前十就不再出现,证金持股只数 113→77→23 不是撤退(同一篮子股数 566→460→286 亿股,最新期 163/195 只无记录)。区分不了「掉出前十」与「真减持」,页面只能写明不下撤退结论。汇金经 ETF 的持仓不在此(ETF 持有人仅半年报/年报前十)。
- `RPT_MUTUAL_DEAL_HISTORY` 沪深港通日度: `MUTUAL_TYPE` 005北向/006南向/001沪/003深/002港股通沪/004港股通深。**北向 NET_DEAL_AMT 2024-08-16 之后全部为空**(交易所停披露,只剩成交额); 南向日度净买入 2014-11-17 起完整(单位百万港元,带恒指收盘)。十大成交股净买入同样已空。
- `RPT_MUTUAL_MARKET_STA`(MARKET_CODE=005): 北向持股市值季度快照,**只返回最近 4 期**,无历史接口 → 采集器每次运行并入本地存档逐季积累。市值含价格涨跌,不等于外资买卖。
- `RPT_MUTUAL_HOLDSTOCKNORTH_STA` 北向个股持股只有最新 1~2 个季度; 其余候选报表名均「报表配置不存在」。
- `RPT_MUTUAL_STOCK_HOLDRANKS` 港股通个股持股日频 2024-10-14 起(约 27 万行)。**重复计算陷阱**: MUTUAL_TYPE 002 与 004 返回**同一份**港股通全量(667 只逐只持股数完全一致),相加会翻倍(我曾报 9.73/11.76 万亿都是错数,正确 5.88 万亿)。只取一个通道。单日约 2.4 秒,473 日约 18 分钟,后台跑+增量+限时落盘。
- 空表返回 `success:false, message:返回数据为空` 不是接口坏;过滤用 `(FIELD='value')` 拼接。
- 行情软件「超级平准/超级外资累计净买入」是软件自定义口径,公开查不到定义: 不复刻,页面顶部写明「不等同」。

## 5. 小结
- 复用函数 `_etf_share_svg`/`_cn_line_svg` 自带的「指数化」标签仍可能压刻度,不为此改复用函数。
- 改 `dashboard.py` 这类受保护文件时: 补丁写成 `/tmp/patch_xxx.py` 再单条运行;被批准超时拦下后**先 grep 特征串确认是否生效**,不重试同命令。
- 回填通知只写 "completed normally" 时,读回落盘文件核对条数/断档/异常跳变(2025-04-03→07 港股通 -13.3% 与恒指 -13.2% 吻合=价格效应)。
