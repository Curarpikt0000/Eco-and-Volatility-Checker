# 数据新鲜度 / 源头频率核查（2026-10-07 实战）

Chao 反复问「这个图怎么没更新」。结论常是：源头本来就慢 / 周频节奏 / 我们没跟上 / 上游静默停更。**先分类再动手，别凭页面日期下结论。**

## 四分法（每个板块必须归入其一）
1. 源头低频，我们已是官方最新（FRED 季度序列：黄金出口 IEAXGG 最新观测 2026-04-01；信贷脉冲四国最新 2025-10-01；COT 周二持仓周五发布）。→ 展示层写「⏳ 源头X更新 · 最新 Y 已是官方最新」，不用 🟡「数据滞后」。
2. 我们没跟上，源头有更新（BIS 黄金掉期：官方月报 2025-12~2026-07 共 8 个月 PDF 都存在，缓存只到 2025-11；IIP：IMF 季频已到 2026-Q2，我们只用年频）。→ 不能写「已是官方最新」，要写明缺口。
3. 静默停更（日本外资周流：JPX 自 2026 年 9 月第 3 周换发布格式 stock_val_1_*.xls → stock_1_w_YYYYMMDD_YYYYMMDD.xlsx 且只在 index 页；旧解析器不报错、缓存每天被重写但内容不变、日报仍标 ok，停在 09-11）。
4. 无法核对（IMF DataMapper 对本机 IP 返回 403 Access Denied HTML）。→ 保持原状，不下结论。

## 「已是官方最新」是强断言——先核后写
- 只对【回官方接口实测过「没有更新一期」】的板块用 `_srcslow_badge(as_of, cadence, verified_on, src_note)`（dashboard.py），调用方必须填核实日与核法。
- 没核实的继续用 `_stale_badge`。TIC 那次教训：「源就是这么慢」不能假设。
- 对照组：任何「查不到/没更新」先拿必然存在的对象走同一查询（BIS 用已知存在的 statofacc251130、必不存在的 999999）。

## 探测坑
- 非 200/错误页会被解析器读成空：IMF 403 返回 HTML，`.json()` 才炸；先看 HTTP 状态与 content-type。
- 路径别猜：BIS 月度账目真路径 `https://www.bis.org/banking/balsheet/statofacc{YYMMDD}.pdf`，会 302 到 `/publications/statement-account-31-july-2026`，真 PDF 是页内 `..._0.pdf`；HEAD 返回 200 且 content-type=text/html 不代表是 PDF，看魔数 `%PDF`。
- 现成工具：`tools/freshness_audit.py`（40 个 fetcher，声明频率+容忍天数）。隔离副本跑：复制项目到 /tmp、把 notion_writer 的 POST/PATCH 拦成空操作（读放行）、用完删副本（含 .env）。它的 INTERNAL_MISMATCH 常是误报（把未来的拍卖日/互换到期日当数据日），STALE 要回源核。
- 板块 id（sec-0、sec-5）是 JS 运行时分配的，静态 HTML 里找不到；静态审计用 `.part-title` 与 `chart-freq` 标签。

## COT 节奏
数据日=周二，CFTC 通常周五发布（联邦假日顺延）。页面只写日期会让读者以为没更新。`_cot_cadence_note(as_of)` 由最近数据日推算「下一期持仓日/预计发布日」，超预计发布日 2 天自动出 🟡。Socrata 数据集：config.COT_SOURCE=6dca-aqww，external_data 另用 72hh-3qpy。

## 单位复核（顺手抓到的真错）
黄金出口板块 `latest/1000` 标「亿美元」实为十亿美元（错 10 倍）；「约460吨」是峰值季换算却挂在最新季后。审每个换算文案：百万美元/100=亿美元；吨=美元÷金价÷32151。
