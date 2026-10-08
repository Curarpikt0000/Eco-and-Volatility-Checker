# 频率徽章 / 官方节奏核对 / 回填接管（2026-10-07 实战沉淀）

## 1. 「怎么还是上周的数据」类质疑：先分四类，再动手
数据源本身低频 / 我们没跟上 / 日期字段取错 / 展示没写节奏。
- COT：持仓日=周二，CFTC 通常周五发布（联邦假日顺延）。周三看到上周二那期=最新，下期由「最近数据日+7天持仓、+10天发布」算出，不要写死。
- 核对法：问官方接口（Socrata `6dca-aqww` 项目在用 / `72hh-3qpy` 另一口径）取 `max(report_date_as_yyyy_mm_dd)`，并带对照组（另一数据集 + 原油）；对照组也同日才算通道没坏。
- 展示层函数：`_cot_cadence_note(as_of)`（超预计发布日+2天自动变🟡提醒）、`_srcslow_badge(as_of,cadence,verified_on,src_note,extra)`（灰蓝⏳「源头季度更新·最新X已是官方最新」）。
- **铁律：`_srcslow_badge` 只能用于已回官方接口核实「官方没有更新的一期」的板块**，调用方必须填 verified_on 与怎么核的。没核的继续用 `_stale_badge`。
- 本轮核实结果：美国黄金出口（FRED IEAXGG 最新 2026-04-01）、信贷脉冲（FRED 四国 2025-10-01）=源头低频，可用灰徽章。
- **反例（不能用灰徽章）**：BIS 黄金掉期——官方月报 PDF 2025-12~2026-07 共 8 个月都存在，我们缓存只到 2025-11+年报 2026-03，是我们没跟上。四国 IIP——IMF 年频到 2025，但**季频已到 2026-Q2**，年频本身不落后但有更新口径未接入。

## 2. 官方源 URL 与坑（实测）
- BIS 月度 Statement of Account：`https://www.bis.org/banking/balsheet/statofacc{YYMMDD}.pdf`（月末日，如 260731）。**会 302 到 `/publications/statement-account-31-july-2026` 页面**（content-type 显示 html，但页内有 `..._0.pdf` 真 PDF）；用 `r.content[:4]==b'%PDF'` 判真伪，别信 HEAD 200。PDF 只有 `Gold and gold loans / Gold deposits`，**没有直接的「黄金掉期吨数」**，吨数是 GATA/Lambourne 推算（年报 3/31 才明示：2026-03 =184t）。不自己推算入库，只消费已核实公开真值。
- 路径猜错（`/about/` `/publ/`）会 404 且页面像正常页，先从代码注释里找真实路径（`external_data.py` 注释里就有）。
- IMF IIP：`https://api.imf.org/external/sdmx/2.1/data/IIP/{ISO}.{A_P|L_P}.IIP.USD.{A|Q}?startPeriod=...`；`.Q` 季频到 2026-Q2；季频 Q4 值与年频同年值完全一致（口径相同，可接）。
- IMF DataMapper（`www.imf.org/external/datamapper/api/v1/...`）本机 IP 返回 403 `Access Denied` HTML（不是 JSON）——此时**不得下「已是官方最新」结论**，只能标无法核对。
- `r.json()` 报 JSONDecodeError 先 print status/content-type/前160字，别当「没数据」。

## 3. 看板单位/归属错误（顺手发现）
`_gold_exports_html`：`latest/1000` 得到十亿美元却标「亿美元」，错 10 倍；且「约460吨」是**峰值季**(47.2B)换算，被挂在最新季后。已改为最新季亿美元=百万美元/100，吨数用同一金价假设（$3200/oz，÷32151 oz/t）分别给最新季与峰值季。
教训：改展示徽章时顺带把整行文字读一遍，数字+单位+归属都核。

## 4. X 网页回填（VM 专用 Chrome）实测
- 启动：`CDP_PORT=9444 python3 -u tools/x_backfill/x_backfill_6m.py [账号...]`（无参=按天数少→多跑全部未完成，已完成跳过，断点续跑）。**不要传 `CDP_HOST=...`**：显示层会把 IP 字面量改写成占位串，脚本拿去连必失败（首启即 exit 2）；默认 localhost 即可。`tunnel_ok()` 已加 3 次重试。
- Rory_Johnston 151 天样板：70.7 分、没触发验证/限流、去重后 792 条（每月 145~176 均匀）。bgurley/ericnuttall 90 天各约 40 分钟。
- **串日**：`since:/until:` 按 UTC 切，960 条里 813 条帖时间戳日期≠所在日文件，168 条同帖跨多个日文件。入库必须按帖 id 去重、按帖自带时间戳取日期，不能按文件名；按文件数帖会虚高 21%。
- 漏抓率未验证：网页 792/151天 ≈ API 估算(est_total_91d=1755)的 27%，两种解释（外推偏高 / 网页漏）无法区分，**不得把 792 说成完整**；放开前用高产日二分窗口重抓测漏抓率。
- 后台进程「完成」通知可能是更早那个失败进程的迟到通知（exit 2 / exit 0 对不上预计时长）——必看日志、`pgrep`、进度文件。

## 5. 把 cron 回填「接过来自己做」的做法
Chao 指令：cron 不做回填，Hermes 来做。盘点法：`~/.hermes/cron/jobs.json` 的 prompt + 引用的脚本正文同时按 `backfill|回填|回补|补抓` 关键词扫，再**逐个读上下文**区分「真回填」和「名字带 backfill」（如 WW Discovery 的 backfill_notion 是写回 Notion、x_backfill 目录下的 x_daily_scan 是日更）。他人项目 cron（war-kol/politics-checker/forecast-checker）只报告不碰。
- 方案 B（Chao 选）：cron 入口脚本(`~/.hermes/scripts/eco_vol_kol_new_backfill.sh`)改为只调 `tools/kol_backfill_detect.py`（判据与 `kol_new_backfill.sh` 选人段逐行一致，只读 sqlite `mode=ro`，不写文件，有人要补才输出一行汇报，`--all` 输出完整清单）。改入口脚本不属于改 cron 配置，但改前备份到 `/tmp/bak_rl/`。
- 连续跑：`tools/kol_backfill_loop.sh` 每轮调现成 `kol_new_backfill.sh`；该脚本同日 `STATUS=DONE` 即退出，所以循环每轮前把 `scratch/kol_bf_auto_<日期>` **改名挪开不删**；任何一轮 STATUS≠DONE / EXIT≠0 即停；`touch scratch/kol_loop_STOP` 可叫停；最大 24 轮。写 shell 时别留重复/括号错位的 `N=$(...)` 行，`bash -n` 后再单测检测命令。
- 规模算清再答：每轮上限 = PER×PAR = 6 人，121 人要 21 轮（不是 4 轮），往日每轮约 15 分钟。我曾口算成「4 轮 3.5 小时」，被自己下一条更正。
- 每人最多试 2 次（账本 `data/kol_backfill_ledger.json`），试满的只报告不再试。
