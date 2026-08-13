# Eco and Volatility Checker

> Telegram topic: **Eco and Volatility Checker** (group: Uber 工作组, thread 31558)
> 目录名 kebab-case：`Eco-and-Volatility-Checker`

## 全局规则
> 本项目遵守 workspace 全局规则：~/uberhermes/Generalrule/antigravity/general-global-rule.md
> 通用规范与踩坑教训：~/uberhermes/Generalrule/wiki/

## 项目定位
**每日宏观风险扫描系统**。18 项关键市场指标（短/中/长期）+ 金银 COT commercial 持仓 →
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
- ★**web_search 后端故障判定**：web_search 偶发整体返回空(success:true 但 data.web:[])，泛主题查询(如"gold price outlook 2026")也空=后端挂了/限流，非"人名检索限制"、更非"数据不存在"。诊断法:测一个必有结果的泛 query,若也空即确诊后端故障。此时 KOL 全量抓取会全"未找到"(诚实但无效),绝不据此下结论,等后端恢复 cron 每日 11:00 自动重跑填真值。
- ★★**幂等 upsert 空值覆盖真值(BofA 类回归的系统级根因)**：notion_writer.upsert 是 PATCH 全量 props。若某源当天抓不到→prop_num(None) 生成 {"number":None}→PATCH 会把 Notion 已有真值清空。修复=upsert 默认 skip_none=True:PATCH 已有行时剔除空值字段(number=None/select=None/rich_text=[]),不覆盖已有真值(title 永远保留;新建行不剔除)。同理 backfill_daily 重跑覆盖 overrides 真值→results_for_day 对 search 源近日(±7天)读 overrides 兜底。**任何"重跑/每日写入"逻辑都要检查:抓不到时是覆盖成空还是保留旧真值?**
- ★**13F 变动真实性**:①prev(上期)解析失败≠全新建,是"变动未知"→fetch_one 打 prev_ok=False,write_to_notion 遇 False 跳过变动字段不覆盖。②backfill_2025 变动基准必须是紧邻季度(report_date 相差75-105天),否则季度缺失会错配基准→标注"非紧邻季,未计变动"。③单位自适应用双阈值带(隐含股价中位数<0.5判千美元×1000/>5判美元/灰区保守不放大)+排期权+样本≥5才自适应。
- ★遗留待跟进(冷review发现,非阻塞):P1-3 external_data 网络失败静默返空→下游混淆"API故障"vs"数据不存在"(可加 error 标记区分);P2-1 backfill report 触发计数字段无回填标记(仅FRED/COT口径偏低,dashboard折线会当真历史);P3-1 _clear_page_blocks 只删前100块;P3-3 _latest_row 按title字符串排序取最新(依赖零填充ISO,格式漂移会错)。

## Cron (JST)
- eco-vol-01-daily-scan-report 每日 **11:00**(工作日)：抓数+KOL独立抓取+流动性+AI分析→写Notion 3DB+每日报告page内部+dashboard+GitHub副本+push→Telegram详细日报(6部分+分领域分析+KOL转向+流动性)。11点是为等 KOL/Economic Dashboard 的09:00数据跑完
- eco-vol-weekly-report 周六 **11:00**：汇总一周→周报DB+GitHub+Telegram周报(重点状态变化)
- eco-vol-selfheal 每小时 :20 自愈 watchdog(no_agent)

## 数据联动 (2026-08 扩展)
- **KOL 独立数据源**：从 KOL 项目 GitHub 拉名册 data/kol_registry.json(80 KOL)，Eco **每日自己 web_search 全量 80 个 KOL** 判方向→写 data/kol_independent.json(不共用另一 agent 的 Notion 结论,准确性独立)。external_data.load_independent_kol() 优先,kol_stance_changes() 读另一agent DB 仅兜底
- **Economic Dashboard 流动性**：external_data.fetch_liquidity_points() 读 Fed准备金/RRP/TGA(A5)+收益率(A1)+风控灯/关键变动(A6 750f9b46...)
- **三大央行资产负债表(US/JP/CN)**：external_data.fetch_cb_balance_sheets() 读 Economic Dashboard 已维护的 B7(Fed周度 dea7e939)/B6(BoJ旬报 481f6e19)/B5(PBoC月度 20b0eb37) 最新两行,每科目算环比(Fed=WoW / BoJ=较上期 / PBoC=MoM)。dashboard 底部 bs-grid 三 view:左资产/右负债,每值带涨跌箭头+%
- **机构持仓 13F + Trump**：holdings_13f.py 走 SEC EDGAR 官方(免费,可查历史)。9个有活跃13F的机构(Berkshire/Bridgewater/Scion/Soros/ARK/Pershing/Appaloosa/Duquesne + Oxbow[Ted Oakley,KOL名册里唯一有活跃13F的])最新vs上期13F,按issuer聚合算变动(🆕新建/▲加仓/▼减仓/❌清仓/→持平)。★单位自适应:部分旧式filer(如Druckenmiller)value填千美元,用中位数隐含股价<$1判定×1000。写 Notion DB_HOLDINGS(title字段"机构-期",非Date→upsert传title_field) + dashboard 底部 h-grid 卡片
- ★KOL名册13F覆盖真相(probe_13f_cik.py探明):80个KOL多为分析师/经济学家/海外/债券/加密,无季度13F。名册候选11个有基金关键词的,实际有活跃13F仅Oxbow(Ted Oakley);Hayman(Kyle Bass 2016停)/PIMCO(2012停)等早停报。所以机构持仓覆盖=8知名+Oxbow=9,已是诚实上限
- **2025全年回填**:holdings_13f.backfill_2025() 拉各机构2025四季度(+2024Q4基准)13F,每季vs上期算变动→DB_HOLDINGS写35机构-期行(Berkshire/Soros/ARK等各4期,Scion 3期)。CLI: python -m src.holdings_13f --backfill2025
- ★**政要披露四源(2026-08 接入,推翻"川普无逐笔源"旧结论)**：politician_disclosure.fetch_all 整合4源→data/politician_disclosure.json,dashboard 政要板块自动读。CLI: python -m src.politician_disclosure
  - ①众议院 PTR(src/politician_disclosure.py 原有)：disclosures-clerk.house.gov {year}FD.ZIP 索引→ptr-pdfs/{year}/{docid}.pdf,pdfplumber。佩洛西 CA11/Crenshaw TX02。
  - ②**川普 OGE 278-T 逐笔(src/oge_trump.py,新)**：★川普作为总统在报 278-T 期间交易报告=**逐笔交易**(非仅年度快照)!源=OGE XPages API `extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest?length=20000`(返全量~16600条JSON,客户端过滤→本地筛name含trump);type字段内嵌<a href>直达PDF(无需Request)。有 278ANNUAL 年度快照+多份 278-T(~300+笔/份)。★解析坑:OCR噪音(purchase→lourchaso;金额$15 001内部空格+bullet分隔);交易日=买卖词**之后**第一个日期(不是债券DUE到期日);金额边界snap到OGE标准档修正。无ticker(只有资产描述名)。
  - ③**川普 DJT Form 4(src/djt_form4.py,新,每日cron逐笔)**：SEC EDGAR CIK 947033=TRUMP DONALD J,submissions JSON里form=='4'→primary_doc.xml。code P买/S卖/G赠与/A授予/F扣税/M行权。带DJT ticker。川普持DJT股票最快逐笔信号。
  - ④**参议员 Tuberville PTR(src/senate_ptr.py,新)**：efdsearch.senate.gov 会话流程:GET /search/home/拿csrf→POST同意条款(prohibition_agreement=1)→★GET /search/建referer链(缺这步data端点503!)→POST /search/report/data/(report_types=[11]=PTR,带X-Requested-With+X-CSRFToken)→GET /search/view/ptr/<uuid>/明细HTML。★参议院数据带ticker质量优于众议院PDF。可扩其他参议员(SENATE_TARGETS只增不减)。
- dashboard 底部四板块(顺序):当日KOL状态变化 → 流动性要点 → 三大央行资产负债表 → 美国国债拍卖timeline → 外国官方托管美债 → 机构持仓13F+政要披露(5卡:佩洛西/Crenshaw/川普OGE 278-T/川普DJT Form 4/Tuberville)；每个 metric 卡片加 📌 当日短评
- ★**美国国债拍卖 timeline(2026-08 接入, Chao要求)**：external_data.fetch_treasury_auctions() 抓**美国财政部 fiscaldata 官方API**(api.fiscaldata.treasury.gov/.../accounting/od/auctions_query, 免费无key)。7个关键券种(2/3/5/7/10/20/30Y Note&Bond, Bill货币工具口径不同不纳入)每个**最新+过去3次**(共4次)+**下次拍卖日程**。字段:offering_amt发行规模/total_accepted中标额/bid_to_cover_ratio中标率BTC/high_yield最高中标收益率/indirect_bidder_accepted间接投标(占比≈外国央行代理需求,与托管美债互印证)。★坑:①"未来拍卖"必须用`auction_date>=today`筛(不能只看high_yield为null,老reopening行也是null会误判);②长债(20/30Y)一月一拍,需拉420天历史才凑齐过去3次;③API返字符串'null'非None,需_auc_num转换;④_req返回(status,json)tuple且path相对/v1。dashboard `_auctions_html`: 每券种一条timeline(最新大字+过去3次下挂节点+下次banner),中标率色标`_auc_btc_cls`(>2.5绿强需求/2.2-2.5灰正常/<2.2红偏弱=需求恶化早期信号)。三处产出:①dashboard timeline卡片(每日cron步骤6抓+传generate刷新)②Notion DB_AUCTIONS(每次拍卖一行,'券种 拍卖日'作title幂等,write_auctions_notion,**每周cron写存档**)③GitHub data/auctions/<week>.json(**每周cron**)。当前:10Y(8-12)BTC2.53/HY4.683%,3Y(8-11)BTC2.71,下次30Y(8-13)$25B。
- ★**外国官方托管美债(2026-08 接入, Chao附FT图; 2026-08 升级加折线图)**：external_data.fetch_foreign_custody_ust() 反映外国央行减持美债/去美元化趋势。★口径统一走 **FRED WMTSECL1**(Memorandum Items: Custody Holdings: Marketable U.S. Treasury Securities, 周度 as-of Wednesday, 2002至今**活跃**——注意无后缀的旧 WMTSECL/WMTSEC 2012已停更, 带`1`后缀的才是当前活跃版!)拉31周历史序列(_custody_history_fred, start 2026-01-01), H.4.1 HTML 降级为仅补总托管(含机构债/MBS)。当前$2.631T(2026-08-05周三口径), 周环比-25.5B(-0.96%), 7月区间-126B(-4.6%)。三处产出:①dashboard 底部独立卡片 _custody_html **含 6个月折线图**(_custody_chart_svg: 680x200, Y轴刻度+日期标签+最新点标注+趋势色 下降clay红/上升sage绿)+区间统计(首末回撤/区间高低)+大号值+周环比箭头 ②Notion 周度时序 DB_CUSTODY(write_custody_notion 以as_of作title幂等)③GitHub每日json副本。每日cron步骤6抓+写Notion+进dashboard,步骤7进json。fetcher返回向后兼容(多了 history 字段)。

## Notion 7 DB (id 在 .env)
- DB_INDICATORS 每日指标 · DB_COT 金银COT · DB_REPORT 每日报告(page内部写6部分+分领域+KOL+流动性+央行BS+持仓丰富blocks) · DB_WEEKLY 周报 · DB_HOLDINGS 机构持仓13F(3ba47eb5...) · DB_CUSTODY 外国官方托管美债(周度时序,3ba47eb5-fd3c-8143...) · DB_AUCTIONS 美国国债拍卖(每次拍卖一行,3bb47eb5-fd3c-814d...)

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
