# Eco and Volatility Checker

> Telegram topic: **Eco and Volatility Checker** (group: Uber 工作组, thread 31558)
> 目录名 kebab-case：`Eco-and-Volatility-Checker`

## 全局规则
> 本项目遵守 workspace 全局规则：~/uberhermes/Generalrule/antigravity/general-global-rule.md
> 通用规范与踩坑教训：~/uberhermes/Generalrule/wiki/

## 项目定位
**每日宏观风险扫描系统**。17 项关键市场指标（短/中/长期）+ 金银 COT commercial 持仓 →
Notion 3 时序 DB → 莫兰迪配色 dashboard（雷达图 + 仪表盘 + 6 部分报告）→ 每日 Telegram 简报。
判断市场过热/趋势转折/结构性周期顶，追踪 7 项硬性卖出触发（≥3 触发 = 开始分批卖出）。

## 技术栈
- Python venv (`.venv/`: requests/pandas/xlrd/openpyxl)
- 数据源：FRED API(VIX/HY/收益率曲线/TIPS/DXY) · CNN F&G JSON API · CFTC Socrata(金银COT) ·
  AAII/CBOE/GuruFocus/ConferenceBoard/Renaissance/Buffett/multpl(web，Jina/web_extract 绕反爬)
- Notion REST v1 直连(token 复用 Economic-Dashboard) · 幂等 upsert + 写后读回
- skill: monitoring-pipeline(数值时序变体) + economic-dashboard-daily-pipeline(cron/backfill 模式)

## 架构 (src/config.py 是 SSOT)
- `config.py` — 17 指标 + COT 定义、阈值、信号灯规则、7 卖出触发、Notion DB 映射
- `fetchers/` — fred.py(含历史) / cot.py(CFTC官方,含历史) / web.py(反爬源) / util.py(Jina重试+硬超时)
- `notion_writer.py` — 幂等 upsert + 读回
- `signals.py` — 信号灯(🟢🟡🔴⚪) + 7 卖出触发判定
- `run.py` — 每日主流程(抓数→信号→写3DB→存快照)
- `dashboard.py` — 莫兰迪 HTML(借鉴 KOL dashboard format + 红绿灯)
- `daily_brief.py` — 结构化简报数据(确定性,供 agent 润色)
- `backfill.py` — 回填历史(FRED日度/COT周度/指标按周采样)
- `build_notion_dbs.py` — 幂等建 3 DB

## Notion 3 DB (id 在 .env)
- DB_INDICATORS: 每日 17 指标时序(每指标一列 + 信号灯)
- DB_COT: 金银 COT 时序(commercial 多空/净/周环比/突增标记)
- DB_REPORT: 每日扫描报告(综合信号/触发数/结论)
- 父页: https://app.notion.com/p/3b947eb5fd3c80ea9b06d41704af3b05

## 关键设计 / 踩坑
- **反爬源分层**：脚本抓 FRED/COT/能抓的 web；难源(AAII/CBOE/GuruFocus/LEI)由 cron **agent 模式用 web_extract** 补写 `data/manual_overrides.json`(web_extract 比脚本内 Jina 稳)；run.py web 源失败回退 overrides。
- **无固定源指标**(BofA Bull&Bear / NYSE A/D 背离)：agent 每日 web_search 交叉验证写 overrides，拿不到留空。
- **NAAIM 已于 2026-08-01 转付费停更** → 标注不编。
- **金银 COT 用 CFTC 官方 Socrata API**(publicreporting.cftc.gov)，非 barchart(反爬/付费)，同源但更稳可 backfill。COMEX 主力合约精确匹配 `GOLD/SILVER - COMMODITY EXCHANGE INC.`(排除 MICRO)。
- **纪律**：绝不编数字，取不到标 status；阈值静态不随情绪调；写后读回验证。

## Cron (JST，避开 08:00/09:00/:00/:30 拥挤时段)
- eco-vol-01 每日 08:30 抓数+dashboard(agent 模式,先 web_extract 补难源)
- eco-vol-02 每日 08:40 Telegram 简报(高信噪比)
- eco-vol-03 周一 08:20 增强版 4 指标
- eco-vol-selfheal 每小时 :20 自愈 watchdog(no_agent)

## 红线
- 密钥只进 `.env`，绝不硬编码/进 git/回显
- 单文件 >500M 裁剪或忽略；破坏性操作先确认
- 时区一律 Asia/Tokyo (JST)

## 时区
所有时间默认 Asia/Tokyo (JST, UTC+9)
