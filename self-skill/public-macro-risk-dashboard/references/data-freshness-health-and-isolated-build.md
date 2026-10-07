# 数据健康度排查 + 新鲜度徽章 + 隔离构建（2026-10-06 实战）

## 触发
Chao 说「今天数据健康度这么差」。看板里**没有叫这个名字的模块**（别硬找）；先问/推断他指的是指标卡新鲜度，再按下面分类，不要一上来就修。

## 排查顺序（每步都要实测，别采信推测）
1. 读 `data/daily/<date>.json` 的 `results`，按 as_of 距今天数排序；as_of 为 None / 非日期（如 `2026-YTD`）单列。
2. 分三类：A 正常（低频或源头 T+1）、B 真毛病（代码硬写 `as_of: None` 却 status=ok）、C 搜索源无确定数据源（ad_line / bofa_bull_bear，只报不乱修）。
3. FRED 日度序列（VIX/HY/DPRIME/SOFR/EFFR）官方 T+1~T+2：用 **FRED API**（`api.stlouisfed.org/.../observations?sort_order=desc&limit=6`）读最新观测证明「源头就是 10-02」。VM 上 `fred.stlouisfed.org` 网页/graph csv 会超时，但 API 通——别拿网页超时当结论，也别误判看板用网页。
4. 请 Opus 5.5 评审可以，但它的推测要逐条验：它猜 buffett「解析器抓到 GDP 日期」是错的（实际走 FRED Z.1 季度），猜 sofr_iorb=0.0 是公式错位也错（SOFR−EFFR 本就 3.88−3.88）。Opus 对的：T+1 假设、`as_of=None 且 ok` 是设计缺陷、margin_gdp 伪新鲜。

## 修复模式（只加标注，不改数值/信号灯）
- 源站页面里**本来就有日期**，改解析即可（均已实测）：
  - CBOE put/call：Next.js 载荷里 `selectedDate`（正则要同时兼容转义 `\"` 与未转义两种形态，反测过）。
  - openinsider：表内 Filing Date；买入榜/卖出榜取两者**较旧**的。
  - AAII 资产配置：表头 "Asset Allocation Results for September 2026" → `2026-09`（aaii.com 直连 403，但 `pd.read_html(..., storage_options=HEADERS)` 能拿到，别看 Jina 空就判失败）。
  - stockanalysis IPO：首列 IPO Date 取 max 作 as_of，YTD 语义放 extra.basis。
- 派生指标 as_of 取**所有输入里最旧的**（margin_gdp 原写运行日=伪新鲜 36 天）。
- 取不到日期就保持 None + `freshness=unknown`，**绝不拿抓取日冒充**。
- 看板 `_ind_fresh_badge(key, r)`：as_of 缺失→灰「⚪ 日期未知」；按 `_IND_FREQ` 复用 `_stale_badge`；FRED 日度容忍 7 天（`daily_fred`）。
- ★FRED 月度/季度序列用「期初日」（2026-08-01=8 月整月；2026-04-01=Q1）标日期，滞后必须从**周期末**起算，否则 LEI 被误报「滞后 66 天」（实际 36 天）。写边界用例逐条跑（缺失/None/10天/20天/FRED 4天/12天/YYYY-MM/非法串）。

## 隔离构建（验证渲染又不碰线上）
- `dashboard.generate` 同时写 `dashboard/` 与 `docs/index.html`（线上产物），输出路径由 `__file__` 决定 → **rsync 整个项目到 /tmp/<name>（排除 .git/.venv/大数据）再用原 venv python 跑**，副本里写，真目录不动。整站约 6~8 分钟，必须 `background=true, notify=true`，启动后读日志确认真在跑。
- 记下真站点 `docs/index.html` 的 sha+大小做基线，构建后复核没变。
- ★副作用坑：`build_dashboard.py` 在副本里仍会**写生产 Notion**（国债压力、OFR FSI 两页最新值）。下次隔离构建前先关掉这两步；这次靠比对落盘 JSON 完全一致证明是同值覆盖，但仍属事先没说的副作用。
- 通知写 completed normally 也要读 EXIT 码、构建日志尾、门禁行（70 形参 / 无字面星号）。

## 发布前必做：新旧页面逐块 diff
- 副本页（13:06 构建）比线上页（11:11 构建）**价格类数据反而退回一天**（白银 61.01→60.87，多个「日更」标签 10-06→10-05），快照 sha 一致但副本里 11 个 `data/*cache*.json` 与真目录不同——原因没查清。
- 结论：**不要把这种副本直接发布**；改动只提交代码，等次日 cron 用新代码在真目录重建发布（或查清缓存差异后再重建）。
- 日期类修复要等 cron 重新抓数才进快照；用旧快照构建的页面里 3 个指标仍显示「日期未知」属正常，别当修复失败。

## 小坑
- `patch` 工具写含反斜杠的正则会被二次转义：写完用 `search_files` 读回确认文件里真实内容。
- 复杂 grep/sed 串联命令会被命令解析器 hardline 拦（exit -1），改用 `search_files` / `read_file`。
- 项目 venv 没装 dotenv：探测脚本自己读 `.env` 进 os.environ。
