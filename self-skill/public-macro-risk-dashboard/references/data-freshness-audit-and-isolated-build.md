# 看板「数据健康度差」排查 + 隔离构建的坑 (2026-10-06 实测)

## 先分类再动手
用户说「健康度差」时先把每个指标按 as_of 分三类，别一律当 bug:
- 正常低频: 月/季更(FINRA/LEI/FMS/Z.1)，as_of 旧是常态。
- 正常 T+1: FRED 日度序列(VIX/HY/DPRIME/SOFR/EFFR)官方滞后 T+1~T+2；周二上午最新=上周五。先 `api.stlouisfed.org/fred/series/observations?sort_order=desc&limit=3` 看源头最新日再判，别看 fredgraph.csv(VM 上网页常超时，API 通)。
- 真毛病: fetcher 里 `as_of: None` 硬写(put_call/insider/aaii_alloc)、`as_of: "2026-YTD"` 非日期、派生指标 as_of 写运行日(margin_gdp 伪新鲜)。

## 修法(只加标注不改数值/信号灯)
- 源页面里找真日期: CBOE 载荷 `selectedDate`(转义形态 `\"` 与解转义两种都要匹配，写反测);openinsider 行内 Filing Date 取两榜较旧者;AAII 表头 "Results for September 2026" -> YYYY-MM;stockanalysis IPO 表首列取最新。
- 取不到保持 None 并标 `freshness=unknown`，绝不拿抓取日冒充。
- 派生指标 as_of 取输入里最旧者。
- 看板指标卡加徽章: as_of 缺失 -> 灰「日期未知」(原 _stale_badge 对 None 返回空串，等于无声显示正常)。
- ★FRED 月/季序列用「期初日」标日期(2026-08-01=8月整月)，滞后须从周期末起算，否则 LEI 被误报 66 天(实 36 天)。
- 每个指标的自然频率放 _IND_FREQ 表，FRED 日度单列 daily_fred=7 天。

## 隔离构建的坑
- generate() 同时写 dashboard/ 与 docs/index.html(线上产物)，路径由 __file__ 决定 -> 隔离=整项目 rsync 到 /tmp(排除 .git/.venv)，用原 venv 的 python 跑；先记真 docs/index.html 的 sha 构建后核对未被碰。
- ★副本构建仍会写生产 Notion(build_dashboard.py 的 write_stress_panels_notion / write_ofr_notion 两步)。下次隔离构建前先关掉这两步，或事先告知；本次读回两页确认同值覆盖同值才算无害。
- ★后构建的页面可能比先构建的更旧: 副本 11 个 data/*.json 缓存文件与真目录不同，白银 61.01(10-06)->60.87(10-05)。未查清原因前不得手动发布，等日更 cron 用新代码重抓重建。判据: 渲染前后页面逐块 diff，除预期徽章外有价格类差异就停。
- 用 `grep -c`/`sed` 等 + 管道的复合命令易被解析器拦(exit -1)，拆成 write_file 脚本再执行。
