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

## Cron (JST)
- eco-vol-01-daily-scan-report 每日 **11:00**(工作日)：抓数+KOL独立抓取+流动性+AI分析→写Notion 3DB+每日报告page内部+dashboard+GitHub副本+push→Telegram详细日报(6部分+分领域分析+KOL转向+流动性)。11点是为等 KOL/Economic Dashboard 的09:00数据跑完
- eco-vol-weekly-report 周六 **11:00**：汇总一周→周报DB+GitHub+Telegram周报(重点状态变化)
- eco-vol-selfheal 每小时 :20 自愈 watchdog(no_agent)

## 数据联动 (2026-08 扩展)
- **KOL 独立数据源**：从 KOL 项目 GitHub 拉名册 data/kol_registry.json(80 KOL)，Eco **每日自己 web_search 全量 80 个 KOL** 判方向→写 data/kol_independent.json(不共用另一 agent 的 Notion 结论,准确性独立)。external_data.load_independent_kol() 优先,kol_stance_changes() 读另一agent DB 仅兜底
- **Economic Dashboard 流动性**：external_data.fetch_liquidity_points() 读 Fed准备金/RRP/TGA(A5)+收益率(A1)+风控灯/关键变动(A6 750f9b46...)
- **三大央行资产负债表(US/JP/CN)**：external_data.fetch_cb_balance_sheets() 读 Economic Dashboard 已维护的 B7(Fed周度 dea7e939)/B6(BoJ旬报 481f6e19)/B5(PBoC月度 20b0eb37) 最新两行,每科目算环比(Fed=WoW / BoJ=较上期 / PBoC=MoM)。dashboard 底部 bs-grid 三 view:左资产/右负债,每值带涨跌箭头+%
- **机构持仓 13F + Trump**：holdings_13f.py 走 SEC EDGAR 官方(免费,可查历史)。8个知名机构(Berkshire/Bridgewater/Scion/Soros/ARK/Pershing/Appaloosa/Duquesne)最新vs上期13F,按issuer聚合算变动(🆕新建/▲加仓/▼减仓/❌清仓/→持平)。★单位自适应:部分旧式filer(如Druckenmiller)value填千美元,用中位数隐含股价<$1判定×1000。Trump无13F→cron agent web_search公开披露(PFD)append。写 Notion DB_HOLDINGS(title字段"机构-期",非Date→upsert传title_field) + dashboard 底部 h-grid 卡片
- dashboard 底部四板块(顺序):当日KOL状态变化 → 流动性要点 → 三大央行资产负债表 → 机构持仓13F+Trump；每个 metric 卡片加 📌 当日短评

## Notion 5 DB (id 在 .env)
- DB_INDICATORS 每日指标 · DB_COT 金银COT · DB_REPORT 每日报告(page内部写6部分+分领域+KOL+流动性+央行BS+持仓丰富blocks) · DB_WEEKLY 周报 · DB_HOLDINGS 机构持仓13F(3ba47eb5...)

## backfill 历史 (2026-08)
- backfill.py: 周采样一年(FRED日度as-of/COT周度) → DB_INDICATORS ~52行
- **backfill_daily_2mo.py**: 过去2月【每日】真值(FRED日度/COT as-of/CNN F&G) → DB_INDICATORS每日行 + snapshots + DB_REPORT每日行。诚实边界:反爬web源(AAII/CBOE/BofA/Insider/Buffett/CAPE/margin)无历史真值→标"未找到"不编;每日AI结论无法重建→DB_REPORT综合结论只用规则兜底+前缀"[历史回填·非当日AI分析]"

## GitHub 每日副本
- reports/<date>.md + reports/latest.md + data/daily/<date>.json + reports/weekly/<week>.md
- report_writer.py: write_daily_page_content(Notion blocks) / write_github_copy / write_weekly

## 每日报告必含 6 部分(硬骨架,Chao 强调)
①仪表盘 ②警报统计(短X/5中X/7长X/5) ③逐条解读2-3句 ④短中长综合结论(减仓/调仓/再平衡具体动作) ⑤卖出触发7项表 ⑥今日焦点一条 + 分领域分析500-1000字(重状态变化)

## 发布 (2026-08 改：公开 GitHub Pages，不用 Uber vibe)
- **宏观指标是公开信息** → 存公开个人 repo `Curarpikt0000/Eco-and-Volatility-Checker`(main)
- dashboard 公开地址: https://curarpikt0000.github.io/Eco-and-Volatility-Checker/ (GitHub Pages 从 docs/ 托管)
- dashboard.py 同时输出 dashboard/index.html + docs/index.html
- 数据快照(公开宏观数据)进 git；.env 绝不进
- 旧 Uber vibe app(eco-volatility-checker)已设 private 下线

## dashboard 结构 (6部分 + 交易员屏卡片)
- 第1部分：17指标卡片网格(交易员屏)——每卡: 大号等宽值 + 红绿黄灯 + threshold说明 + 近2周mini折线(SVG) + "如何看"注解(HOW_TO_READ)
- 第2部分：警报统计3卡片 + 三雷达图 + 金银COT
- 第3部分：逐条解读  第4部分：短中长综合结论(3彩卡,AI生成或规则兜底)
- 第5部分：卖出触发追踪(文字色标签)  第6部分：今日焦点
- 折线数据：日频快照(backfill_daily 回填近30天 + 每日cron追加)；周快照给一年趋势

## 红线
- 密钥只进 `.env`，绝不硬编码/进 git/回显
- 单文件 >500M 裁剪或忽略；破坏性操作先确认
- 时区一律 Asia/Tokyo (JST)

## 时区
所有时间默认 Asia/Tokyo (JST, UTC+9)
