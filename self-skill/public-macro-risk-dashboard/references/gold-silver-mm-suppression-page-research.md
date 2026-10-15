# 「金银做市商砏盘」专页：先调研他的指标，再建页（2026-10 实测）

用户要求「抓 KOL(Steve=SilverChartist 创始人) 过去几年的金银/做市商砝盘判断→用他的指标 build 页→给建议」时的做法与发现。建页前的调研阶段已完成，页面未建。

## 调研方法（可复用）
1. 先确认「谁是 Steve」。人名常被脱敏成占位符，用 KOL 名册(`data/kol/backfill/*.json`)核对。拿不准就让用户选。
2. 一手来源优先：播客/访谈转写稿（exa.ai/library/podcast、YouTube 转写）、本人周报（FTMDaily 2016）。**转写稿不是逐字稿**，引用需标注。
3. 把指标清单落盘成文档，每条带「出处+时间」，分三段：本人说的 / 本人没说过（别替他编） / 别人的方法（仅对照，不归给他）。文档现在在 Economic-Dashboard/docs/steve_penny_indicators.md。
4. 再拿 Eco 项目现有数据文件对照，逐项标「有/缺」。

## ★核心发现（写页面口径有关）
- Steve 本人把 **COT 银行净空当「时机/情绪指标」**，不是操纵证据；他的「证据」是价格+成交量尖峰。他说金银是「被操纵最严重的市场」，但同时说「操纵总会失败、管得了日内管不住大趋势」；对 2026-01-30 暂跌他说「不确定 CME 起了多大作用」。
- 他本人点名的指标：COT 大银行净空、价+量、CME 保证金上调、欧洲银行净空、上海溢价、DXY、金银比/矿股比、关键价位。**没找到**他用 Disaggregated(Swap Dealer vs Producer)、Big-4/8 集中度、COMEX 交割 issue/stop、LBMA 库存——这些是 Ed Steer / Ted Butler 的，别归给 Steve。
- 公开数据**证明不了「谁在砏」**。页面只展示可核实关系（商业空头变化与价格下跌同步），不写「做市商砏盘」结论。COTInsight 反驳必须作口径提醒：互换交易商空头多是客户多头镜像；空头占比跳升可能只是 OI(分母)下降。
- 粗核：白银近一年 5 日跌幅最大 2026-01-26→02-02 −333%→实为 −33.3%（115.08→76.78），同期 commercial 净空在 −38.8k~−45.3k 张窄幅波动，周度 COT 看不到砏盘前后明显变化（只做了一次粗核对，未跑滞后相关，不当结论）。

## Eco 项目可直接只读复用的数据（~/Projects/Eco-and-Volatility-Checker/data/）
| 文件 | 内容 | 备注 |
|---|---|---|
| `silver_bank_positions.json` | Legacy commercial 净持仓，周度 2016起 + SI=F 价 | `points[]` 字段 comm_net/long/short/open_interest |
| `cot_managed_money.json` | Disaggregated(mm/sd/pm) 黄金白银铂近3年 + 价 | `[metal]['cot']` 列表 |
| `comex_issue_stop_weekly/firms.json` | 银行 issue/stop | 源为 PDF+Notion 双通道 |
| `comex_inventory.json` `silver_curve_cache.json` `gold_vol_cache.json` | 库存/期限结构/GVZ | |
| `comex_optpos_price_cache.json` | 金银日价 | |
**缺**：CME 保证金上调历史、成交量（价格文件只有收盘）、白银上海溢价。页面对这些写「未获取」，别用估算。

## 流程约定
调研→指标文档→数据对照→**方案给用户确认**→建页。先问：缺的数据要不要再花一轮抓（保证金、成交量）、更新频率（周度还是随日更 cron）、要不要加黄金。Eco 项目只读不改（Chao 曾要求摄回所有加到 Eco 项目的改动）。
