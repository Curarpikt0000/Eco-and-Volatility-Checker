# 指标「数据健康度」审计与新鲜度徽章（2026-10-06 实测）

触发：Chao 说「今天数据健康度差」但没指具体页面。先别猜，也别自定义“健康度”。

## 排查顺序（每步实测）
1. `data/daily/<今日>.json['results']`：逐指标算「as_of 距今天数」，同时看 as_of 为 None / 非日期（如 `2026-YTD`）的。**`status=ok` 不代表新鲜**——ok 只说明抓到了数。
2. 区分三类，别混在一起报“差”：
   - 正常低频/T+1（FRED 日度序列最新就是 T-2~T-4，用 FRED API `observations?sort_order=desc&limit=3` 直接对账；月/季更指标本来就慢）；
   - 真毛病：fetcher 里 `as_of` 硬写 None / 写成运行日（派生指标伪新鲜）；
   - 搜索源（ad_line、bofa_bull_bear）真滞后——无确定性源，单独列，不顺手“修”。
3. 方案评审可用 `claude-opus-5-5`（max_tokens≥7000，否则 choices=null），**但它的根因推测必须逐条实测**：本次它猜“buffett 抓到了 GDP 日期”是错的（实际走 FRED Z.1 季度数据）；猜“sofr_iorb=0.0 公式错位”也错（SOFR 3.88−EFFR 3.88=0 本就对）。T+1 假设则实测成立。

## 修法（只加标注，不改数值/信号灯）
- 每个 fetcher 的 as_of 去**源页面自带的日期**取，取不到保持 None 并标 `freshness="unknown"`，**绝不拿抓取日冒充**：
  - CBOE put/call：Next.js 载荷里 `selectedDate`，正则要兼容转义/未转义引号：`selectedDate(?:\\)?"\s*:\s*(?:\\)?"(20\d\d-\d\d-\d\d)`（反测两种形态 + 无日期文本必须 None）。
  - openinsider：表内 Filing Date，买入榜/卖出榜取较旧者。
  - AAII 配置：`pd.read_html` 页内 “Asset Allocation Results for <Month YYYY>” → `YYYY-MM`。aaii.com 直连 urllib 403，但 `pd.read_html(..., storage_options=HEADERS)` 能过、Jina 取到 0 字——**别凭 urllib 403 断言取不到，现场调 fetcher 看哪条路径返回**。
  - stockanalysis IPO：表首列 IPO Date 最大值。
  - 派生指标（margin_gdp）as_of = 各输入 as_of 的 **min**，不是运行日。
- dashboard.py：`_IND_FREQ`（每指标自然频率）+ `_ind_fresh_badge(key, r)`；`_FRESH_TOL` 增 `daily_fred=7`；as_of 缺失 → 灰色「⚪ 日期未知」（`.sb-gray`）；value=None 不出徽章（交给 status）。
- **FRED 月/季序列的 as_of 是“期初日”**（2026-08-01=8 月整月；04-01=Q1）。滞后须从**周期末**起算，否则 LEI 会被误报“66 天”（实 36 天）。这是模拟全 20 指标徽章时才暴露的。

## 验证套路
- 先 `cp` 备份被改文件；用快照 as_of 覆盖成“修复后值”模拟全 20 指标徽章，再跑 9 个边界用例（None/抓不到/10 天/20 天/FRED 4 天与 12 天/YYYY-MM/非法串）。
- **整站构建会写 `OUT_DIR` 与 `docs/index.html`（线上产物），路径由 `__file__` 决定**：隔离验证 = rsync 项目到 `/tmp/eco_build_test`（排除 .git/.venv，复制 .env），用原 venv python 在副本里跑 `build_dashboard.py`，`background=true,notify=true`，启动后 `pgrep` + 读日志确认真在跑；事前记下真 `docs/index.html` 的 sha/大小，事后核对没被碰。
- 本项目无 python-dotenv：测试脚本自己解析 `.env` 进 `os.environ`。
- 工具坑：链式 grep+sed 的长命令会被解析器 hardline 拦（exit -1）→ 拆短或改用 search_files/read_file。
