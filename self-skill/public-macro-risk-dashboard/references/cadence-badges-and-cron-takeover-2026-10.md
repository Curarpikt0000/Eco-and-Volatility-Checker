# 频率徽章、低频源核对、cron 回填接管、X 网页回填(2026-10-07 实战)

## 1. 「每张图是否在更新」不能只看页面日期
- 页面写「9/29 周」≠ 没更新。先问官方接口:COT 全表 `report_date` 最大值(Socrata 数据集 `6dca-aqww`,config.COT_SOURCE)+ 对照组(另一数据集/另一商品)。节奏:**持仓日=周二,通常周五发布**(假日顺延),所以周三看到上周二的数据是最新一期。
- 展示层修法:卡片加一行「周频 · 持仓日周二 · 本期 X · 下一期持仓日 X+7、预计 X+10 发布」,下期日期由 as_of 推算不写死;超过预计发布日 2 天自动出 🟡 提醒(`_cot_cadence_note`)。
- 低频源(FRED 季度、BIS 汇编、IMF 年度)旧徽章会输出「🟡 数据滞后 N 天」吓人。新增 `_srcslow_badge(as_of, cadence, verified_on, src_note, extra)`:灰蓝 ⏳「源头季度更新 · 最新 X 已是官方最新」。**只给已回官方接口核实过「官方没有更新一期」的板块用**(本次仅 美国黄金出口 FRED IEAXGG、信贷脉冲 FRED 四国);BIS 掉期、IIP、IMF 债务/GDP 未核实不套用。「已是官方最新」是强断言,必须附核实日与方法(title 悬停)。
- 核实陷阱:IMF DataMapper 对本机 403(返回 HTML)——非 200 错误页不是「查无此物」;能出数的是 `api.imf.org/external/sdmx/2.1`。BIS 月报路径是 `bis.org/banking/balsheet/statofacc{YYMMDD}.pdf`(跳转到 publications 页,页内才有真 PDF);8 月起新路径 `publications/statement-account-31-august-2026.pdf`。我先猜 `about/`、`publ/` 路径得出「全 404」是错的,须带「缓存里已知存在」的对照组。

## 2. 渲染层单位错(顺手发现)
`黄金出口`:`latest/1000` 标成「亿美元」,实为十亿美元(错 10 倍);且「约 460 吨」是峰值季换算,挂在最新季后。改为 百万美元/100=亿美元,吨数按同一金价假设(约 $3200/oz)分别给最新季与峰值季。**改展示前用原始数 + 单位口算一遍。**

## 3. 缓存「最新」字段取错类型
`fetch_bis_gold_swaps` 原 `latest=pts[-1]`;补入月度点后会把 GATA 月度推算当成「年报确认」。改为取最后一个 `kind==annual` 点,`as_of` 另取最后一点。**往时序里追加不同 kind 的点前,先查所有「取最后一点」的消费者。**

## 4. 只写读到原文的值
BIS 月值:逐条回 GATA/GoldSeek 原文;只在搜索摘要里见到或由「from 146」反推的月份(2026-05、07)**不写**,缓存加 `gaps_note`,页面显示「缺口」。同日已有年报确认点(03-31 的 184)不再并存月度 181。

## 5. cron 回填接管(Chao:「cron 不做 backfill,你来做」)
- 找回填类 cron:读 `~/.hermes/cron/jobs.json` 的 prompt + 每个 job 的脚本正文,按 `backfill|回填|回补|补抓` 过滤,再逐个读上下文区分「真回填」vs「只是名字带」(别的项目的 war-kol/politics/forecast 只报不动)。嵌在日报 prompt 里的步骤(如 3b 每日 25 条 detail 回填)属于改 cron prompt,要 Chao 批。
- 选 B(cron 只检测):入口脚本 `~/.hermes/scripts/*.sh` 改为 exec 只读检测器 `tools/kol_backfill_detect.py`(同一选人判据,`--all` 出完整清单,绝不写文件),**不用改 cron 配置**;先备份原入口。
- 连续跑:现成 `tools/kol_new_backfill.sh` 同一天 STATUS=DONE 就退出;循环脚本每轮前把当天目录**改名挪开不删**;停止条件=没人要补/STATUS 非 DONE/退出码非 0/STOP 文件/最大轮数。起跑前核对依赖文件都在、无残留进程、起跑后读日志首行与进程。规模估算要用「每轮上限 PER×PAR 人」算轮数(121 人=21 轮≠4 轮),我曾口算错。
- 循环每轮会 commit `kol_store.sqlite`;期间自己的改动**不提交**,只留工作区,循环结束后再显式 add 自己的文件。

## 6. X 6 个月网页回填(VM 专用 Chrome)
- 起停/注入 cookie:`tools/x_backfill/x_vm_chrome.py`;CDP 端口 9444;脚本用环境变量 `CDP_PORT=9444`,**不要在命令里写 CDP_HOST**(见 uber-redactor-shell-safety 的 IP 字面值条目,默认 localhost 即可)。`tunnel_ok()` 加 3 次重试。
- Rory_Johnston 151 天样板:70.7 分钟、无验证页、去重后 792 条,但 `since/until` 按 UTC 切,960 条里 813 条时间戳日期≠所在日文件,168 条跨日重复;**入库按帖时间戳取日期、按 id 去重**,不得按文件名数帖。漏抓率无法用 API 独立验证(API 库不覆盖该区间),先挑高产日二分窗口重抓再放开全量。
- 90 天账号约 39~41 分钟,总量约 13 小时;进程结束通知的 exit 码以日志为准,别把已失败进程的迟到通知当新故障。
