# Eco and Volatility Checker

> Telegram topic: **Eco and Volatility Checker** (group: Uber 工作组, thread 31558)
> 目录名 kebab-case：`Eco-and-Volatility-Checker`

## 全局规则
> 本项目遵守 workspace 全局规则：~/uberhermes/Generalrule/antigravity/general-global-rule.md
> 通用规范与踩坑教训：~/Projects/ChaoWiki/

## 项目定位
**每日宏观风险扫描系统**。18 项关键市场指标（短/中/长期）+ 金银 COT commercial 持仓 →
Notion 3 时序 DB → 莫兰迪配色 dashboard（雷达图 + 仪表盘 + 6 部分报告）→ 每日 Telegram 简报。
判断市场过热/趋势转折/结构性周期顶，追踪 7 项硬性卖出触发（≥3 触发 = 开始分批卖出）。

## 技术栈
- Python venv (`.venv/`: requests/pandas/xlrd/openpyxl/**pymupdf**)
  - `pymupdf` 供 CIPS 官方 PDF 解析（`fetch_cips`）使用；缺失时该指标降级为「未就绪」，不影响其他板块。
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
- ★★**web_search 修复(2026-08-14 实测)**：本项目/本机 Hermes 默认 `web.search_backend=searxng`(本地SearXNG实例)。SearXNG 返空的根因常是**上游引擎全被限流/CAPTCHA**(诊断:`curl "$SEARXNG_URL/search?q=test&format=json"` 看 unresponsive_engines,会显示 brave "too many requests"/duckduckgo "CAPTCHA"/google cse 挂)。**修复=切到免key的 ddgs 后端**:`hermes config set web.search_backend ddgs`(ddgs=DuckDuckGo Search Python包,已装9.14.4,免key直连,`_is_backend_available`只需包可import)。切完**当前会话下一次 web_search 调用即生效**(不必重启,config被工具动态读)。Hermes 全部可选 search_backend(源码 tools/web_tools.py):exa/parallel/firecrawl/tavily(需key) · searxng(需SEARXNG_URL) · brave-free(需BRAVE_SEARCH_API_KEY) · ddgs(免key) · xai(需xai凭证)。本机已配 EXA_API_KEY(付费高质量备选)。web_extract(extract_backend)不受 search 故障影响,子agent靠它硬抓仍可用。
- ★★**幂等 upsert 空值覆盖真值(BofA 类回归的系统级根因)**：notion_writer.upsert 是 PATCH 全量 props。若某源当天抓不到→prop_num(None) 生成 {"number":None}→PATCH 会把 Notion 已有真值清空。修复=upsert 默认 skip_none=True:PATCH 已有行时剔除空值字段(number=None/select=None/rich_text=[]),不覆盖已有真值(title 永远保留;新建行不剔除)。同理 backfill_daily 重跑覆盖 overrides 真值→results_for_day 对 search 源近日(±7天)读 overrides 兜底。**任何"重跑/每日写入"逻辑都要检查:抓不到时是覆盖成空还是保留旧真值?**
- ★**13F 变动真实性**:①prev(上期)解析失败≠全新建,是"变动未知"→fetch_one 打 prev_ok=False,write_to_notion 遇 False 跳过变动字段不覆盖。②backfill_2025 变动基准必须是紧邻季度(report_date 相差75-105天),否则季度缺失会错配基准→标注"非紧邻季,未计变动"。③单位自适应用双阈值带(隐含股价中位数<0.5判千美元×1000/>5判美元/灰区保守不放大)+排期权+样本≥5才自适应。
- ★遗留待跟进(冷review发现,非阻塞):P1-3 external_data 网络失败静默返空→下游混淆"API故障"vs"数据不存在"(可加 error 标记区分);P2-1 backfill report 触发计数字段无回填标记(仅FRED/COT口径偏低,dashboard折线会当真历史);P3-1 _clear_page_blocks 只删前100块;P3-3 _latest_row 按title字符串排序取最新(依赖零填充ISO,格式漂移会错)。

## Cron (JST)
- eco-vol-01-daily-scan-report 每日 **11:00**(工作日)：抓数+KOL独立抓取+流动性+AI分析→写Notion 3DB+每日报告page内部+dashboard+GitHub副本+push→Telegram详细日报(6部分+分领域分析+KOL转向+流动性)。11点是为等 KOL/Economic Dashboard 的09:00数据跑完
- eco-vol-weekly-report 周六 **11:00**：汇总一周→周报DB+GitHub+Telegram周报(重点状态变化)
- eco-vol-selfheal 每小时 :20 自愈 watchdog(no_agent)

## 数据联动 (2026-08 扩展)
- **KOL 独立数据源**：名册 `data/kol_registry.json`，Eco **每日自己 web_search 全量 active KOL** 判方向→写 data/kol_independent.json(不共用另一 agent 的 Notion 结论,准确性独立)。★**cron prompt 不写死 KOL 数量**(2026-08-14 Chao 加 Craig Hamilton-Parker 时踩坑:prompt 曾硬编码"88个KOL"4处,新增会漏抓)——已改为"读名册取 active==true 的全部",新增 KOL 自动纳入,增减名册无需改 cron。
- ★★★**名册铁律(Chao 2026-08-22 重申，最高优先级)**：
  **SSOT = Notion「KOL List」DB** = `35947eb5-fd3c-800d-b852-cef31f9de6a5`
  （位于 page「KOL Research Daily Update」`31447eb5fd3c8064a531c43b177cdc41` 内，同页还有 KOL By Week / KOL By Day 两个 DB）。
  **本 agent 绝不自行增删任何 KOL** —— 增删一律由 Chao / 另一 agent 在 Notion 侧操作，
  本项目只跑 `tools/sync_kol_from_notion.py --apply` 做**单向镜像**到 GitHub。
  已挂进每日 cron 的**步骤 0**（在所有抓取之前），Notion 改动次日自动生效。
  - **教训**：2026-08-20 我未经指令自行往名册加了 23 人、且只写本地未同步 Notion，
    造成两边不一致，还把本属 Forecast-Checker 的玄学/术数类塞进了 Eco。
  - **同步保护**：本地独有采集配置(search_terms / youtube_channel_id / source_url)保留不被覆盖；
    移出者落盘 `data/kol_removed_<date>.json` 留痕，其 `data/kol/backfill/` 历史文件**一律保留不删**
    （日后在 Notion 加回来，历史立即可用）。
  - **★匹配坑**：Notion 名常带机构后缀，如「Nomi Prins（… 前 Goldman Sachs MD）」。
    若用双向子串模糊匹配，本地「Goldman Sachs」会抢先吃掉这一行，导致 Nomi Prins 被误判为
    "Notion 无"而错误移出。正解：**先全量精确匹配 → 模糊只认「本地名 ⊂ Notion 名」单方向 →
    取最短候选 → 已配对者不再参与模糊**。
  - **★名册变更后必须同步过滤下游**：`kol_full_history()` 直接扫 `data/kol/backfill/` 目录、
    `kol_weekly_views()/kol_stance_changes_grouped()` 读的是每日快照，**两者都不看名册**。
    移出人后若不在 dashboard 渲染层按名册过滤，会出现「卡片没了但历史仍内嵌在 payload」或
    「卡片还在但点开空白」。已在 `_kol_history_payload` / `_kol_views_html` / `_kol_changes_html` 三处加过滤。
- ★★**项目边界(Chao 2026-08-22 裁定)**：**玄学 / 术数 / 占星 / 通灵 / 末日预言类不属本项目**
  （易经 / 六爻 / 奇门遁甲 / 八字 / 金融占星 / 圣经周期择时）→ 归 **Forecast-Checker** 项目
  （见 `~/Projects/Forecast-Checker/AGENTS.md`，其源文件为 `data/batch_esoteric_finance.json`，
  已挂进该项目 `scripts/merge_backfill.py` 白名单）。
  本项目只留**可交易的金融判断**；技术分析 / 量化周期派（艾略特波浪 / 市场宽度 McClellan /
  ECM 经济信心模型 / Hurst 周期 / 世代长周期）归**常规 KOL 板块**，**不设独立 section**
  （`_cycle_kol_html` 已停用但函数保留，模板整段注释）。
- **2026-08 完全独立化(Chao要求)**: 每日 crawl 后 `save_kol_daily_snapshot()` 把全量方向落盘 data/kol/daily/YYYY-MM-DD.json(进 git, Eco 自己的数据仓库副本), `kol_weekly_changes()` 读这些快照做**本周最新 vs 上周最后**对比算转向, `kol_stance_changes_grouped()` 数据源=这些快照, **彻底不碰另一 agent 的 by_day DB**(fetch_kol_recent/kol_stance_changes 已弃用不再是主源)。快照不足跨周时诚实回退最新vs最早; 只1天时返回空(绝不编转向)。dashboard 标题=**"本周 KOL 状态变化"**。
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
- dashboard 底部板块(顺序):**本周KOL状态变化** → 流动性要点 → 三大央行资产负债表 → **三国货币供应量M0/M1/M2** → **三国M2十年折线** → **Credit Impulse信贷脉冲(美/中/欧/日,季度,+2008长历史参考图)** → **国债市场压力竖向四联图(对齐Morgan Stanley三图+OFR官方压力指数,过去3年,每日更新)** → 美国国债拍卖timeline → 外国官方托管美债(左近12月/右近10年双图) → **日本/中国分国别持有美债近10年(TIC MFH,左右双图,fetch_country_ust_holdings)** → 机构持仓13F+政要披露(5卡:佩洛西/Crenshaw/川普OGE 278-T/川普DJT Form 4/Tuberville)；每个 metric 卡片加 📌 当日短评
- ★**Credit Impulse 信贷脉冲(Chao 2026-08, 中期领先指标)**：fetch_credit_impulse() **四国(美/中/欧/日, 2026-08加日本)**。定义=新增信贷流量的【变化】÷GDP=信贷存量二阶差分/GDP,衡量【新增信贷的加速度】(非债务总量/非新增债务),领先实体经济6-9月,中国信贷脉冲=全球商品/风险资产最强领先指标之一。★口径:用BIS官方credit-to-GDP ratio(FRED QUSPAM770A/QCNPAM770A/QXMPAM770A/**QJPPAM770A日本**,季度,%GDP)的【二阶差分】近似CI。★★**日本序列QJPPAM770A只在免key CSV端点(fredgraph.csv)可得,带key API(fetch_fred_history)返EMPTY**——fetch_credit_impulse的_fred_ratio已API优先+CSV回退能兜住,但独立验证时须用curl CSV端点测(曾被子agent"API有数据"误导,实际API空)。★**2008至今长历史参考图(Chao 2026-08加)**:points_long走_fred_ratio_long(cosd=2006,带2次重试),BIS三国序列可回溯到1947(美)/1985(中)/1999(欧),日本亦全;dashboard _credit_impulse_long_svg多国折线(粗颗粒,标时间段,仅参考);**十年短图保持不动**(Chao明确)。★频率:季度更新滞后约1季。fredgraph CSV端点偶发超时(时好时坏),已加重试;8序列串行拉数可能慢,cron每天重试。dashboard `_credit_impulse_svg`带零轴+信号色空心圈;`.ci-cols-4`四列。绝不编:某国抓不到→points=[]+status="未找到"。★线上"数据未就绪"排查:先查是否GitHub Pages旧部署落后(本地fetcher正常但docs/index.html是旧commit)→重建+cp到docs/+push即修复,非数据源问题。
- ★**外国官方托管美债加速度图(Chao 2026-08)**：fetch_custody_acceleration(weeks=13) 对 FRED WMTSECL1(外国官方托管美债,**周度**as-of周三)做超短期加速度。★★**颗粒度铁律:H.4.1是周度非日度,做不到"每天"加速度,trailing 7/14/28天≡1/2/4周**(dashboard如实标注,别误导用户以为日频)。加速度=二阶差分(变化的变化):7天=v[i]-2v[i-1]+v[i-2],14天用i-2/i-4,28天用i-4/i-8;零轴上=流入加速/流出减速,下=流出加速/流入减速。主图=**7/14/28/56天四条折线**(短橙#c27a3e/中蓝#5b8fb5/中长绿#6f8f6a/长紫#9b6b9e,覆盖**过去6个月/26周**,带零轴+图例+最新点,Chao 2026-08要四折线看交叉点判读:短线穿越中长线=短期动能相对转向/领先信号;四线发散=趋势强化,收敛交叉=动能切换,8周线最平滑=中期基调),叠加7/14/28/56天四格原始二阶差分数值(7天最快最敏感/8周最稳滞后)。fetch weeks=26,a56需i>=16预热(need=weeks+20够);build_dashboard传weeks=26。dashboard `_custody_accel_html`插在托管美债卡下面,口径用WMTSECL1(外国官方账户,非WSHOSHO那是Fed自己SOMA)。★★★**fredgraph CSV端点(fred.stlouisfed.org/graph/fredgraph.csv)在本VM Python环境(requests且curl子进程)都偶发超时**,但**带key FRED API(fetchers.fred.fetch_fred_history)稳定**——所有拉FRED的fetcher优先用fetch_fred_history,CSV仅作回退。手动terminal curl能成功但Python子进程起的curl常超时(环境/并发差异),别依赖CSV端点做主通道。
- ★**KOL 半年历史导入作时序底座(Chao 2026-08)**：从另一 agent by_day DB(2025-12-18至今~205天,但每天仅6-13个KOL稀疏覆盖)一次性导出(scratch/import_kol_history.py)落盘 data/kol/daily/ 作时序底座, 与 Eco 自己每日全量91 KOL稠密快照并存(不覆盖)。用途:①kol_weekly_changes 本周vs上周真转向(伪转向过滤:direction为"未找到"/空的不算,曾误报"看空→未找到")②kol_weekly_views **过去一周(上周一→今天)滚动窗口聚合,每个KOL取窗口内最近一次有实质观点(不再只取最新一天,修复"最新快照空/稀疏→整个模块空"的bug,Chao 2026-08)** + since_date(当前方向连续保持起始日,回溯全历史算)+is_new(起始日>=本周一=本周新观点)。★现实:by_day历史稀疏(每天几个)+Eco稠密(一天全量91)粒度不同,跨源回溯易断档→当前观点多标"本周新观点";随Eco每日攒稠密快照,首现日期会越来越准。dashboard `_kol_views_html` 每卡显示🆕本周新观点/自X日持此观点。
- ★**ECB 欧洲央行资负表完整分项(Chao 2026-08, 已从选项A务实版升级)**：fetch_ecb_balance_sheet 走 **ECB 官方 Data Portal SDMX API** 的 ILM 数据集(Eurosystem 周度合并财务报表, 免费无key)。★关键:单条 series key 查询对 COUNT_AREA/CURRENCY_TRANS 维度取值敏感易 400, **用 wildcard `W.U2.C...` 一次拉全部43分项**最稳(format=csvdata,lastNObservations=1,单位百万€)。6维度=FREQ.REF_AREA.BS_REP_SECTOR.BS_ITEM.COUNT_AREA.CURRENCY_TRANS。已验证key:黄金A010000.Z5.Z0Z/外币A020000.U4.Z06/证券APP+PEPP A070100.U2.EUR(非A070000含其他)/对信贷机构贷款A050000.U2.EUR/银行券L010000.Z5.EUR/存款便利L020200.U2.EUR(子项)/总资产T000000.Z5.Z01。总资产与FRED ECBASSETSW三方一致校验。政策利率走FRED ECBMRRFR(MRO)/ECBDFR/ECBMLFR。折美元用当天DEXUSEU(1欧元=X美元,乘)。
- ★**央行负债侧层级修正(2026-08, Chao指出会计问题)**：中国 PBoC 负债侧"货币发行"⊂"储备货币"(是子项非并列),原来平列会误导相加。修复=CB_BS_SPEC 元组加第三元素`"sub"`标记子项,_bs_line 传 sub→dashboard side() 遇 sub 缩进+"└ 其中·"前缀+弱化字色(.bs-sub)。日本"银行券"也是基础货币子项但日本未单列"储备货币"总项故不标(它与经常项目存款并列相加=储备货币,无重复)。美国准备金/RRP/TGA 是独立科目无包含关系。**只有总项+子项并列才标 sub**。
- ★**国债市场压力竖向四联图(Chao 2026-08, 参照 Morgan Stanley 三图)**：`fetch_treasury_stress_panels(years=3)` + `fetch_ofr_fsi(years=3)`;dashboard `_stress_panels_html(sp, ofr)` + 双轴多线SVG `_stress_panel_svg`(左右轴各自缩放, single_axis时含0基准零轴)。**竖向排列**(Chao明确要竖不要横,`.sp-wrap` flex-direction:column, 每图全宽 viewBox 940x300)。四图=①收益率+波动性(DGS10/DGS2 + **真MOVE指数**)②市场压力代理③曲线信用压力④OFR官方压力指数。★★**MS 的图2(BrokerTec日内bid-ask价差)/图3(周度DV01量)是 Morgan Stanley BrokerTec 专有数据, 无免费公开源**(已搜索确认只对付费机构客户开放)→图②③改用**主题对齐的免费公开压力代理**(②=10yr期限溢价THREEFYTP10+IG企业债OAS BAMLC0A0CM;③=10Y-2Y曲线利差T10Y2Y+HY OAS BAMLH0A0HYM2), note 明确标注"非BrokerTec原指标"(绝不冒充)。★**MOVE指数**(ICE专有,FRED无免费序列)走 **yfinance `^MOVE`**(Yahoo有免费日线历史,已装yfinance;`df["Close"]`多列时取iloc[:,0]),抓不到返[]不编。★OFR FSI=OFR官方金融压力指数,源=`financialresearch.gov/financial-stress-index/data/fsi.csv`(免key日频2000至今,列OFR FSI/Credit/Funding/Safe assets/Volatility),0=历史正常/正=承压/负=平静。全部FRED带key API优先(fetch_fred_history)。周度降采样降噪(_weekly_resample周五as-of)。**数据落盘 data/stress/*.json 进git + Notion DB_STRESS/DB_OFR**(建库脚本 src/build_stress_ofr_dbs.py 增量幂等只追加.env)。★daily cron(eco-vol-01)步骤6内联 dashboard.generate 已补传 stress_panels/ofr_fsi(+顺带补回之前漏的 credit_impulse/custody_accel/country_ust/kol_views),**保留ai_reads注入**(未改成build_dashboard因它不读ai_analysis会丢每日AI短评)。当前(as of 2026-08-14):MOVE=70.88 / OFR FSI总指数=-2.74(压力低于正常)。
- ★**KOL 名册 +14 Kevin Warsh 美联储 task force 顾问(Chao 2026-08-17, 用户发信息图点名"图上所有人")**：美联储主席 Kevin Warsh 2026-07-09 任命的5个改革 task force(Communications/Balance Sheet Policy/Data/Productivity&Jobs-AI/Inflation Frameworks)外部顾问。名册94→**108**(scratch/add_warsh_kols.py, domain=宏观货币与金融体系/sector=Macro/detail_sector=Fed政策·央行)。14人:King/Fisher/Fraga(沟通)·Rajan/Stein/Dynan(资负表)·Chetty/McMillon(数据)·Andreessen/Chad Jones/Sarah Bond(生产力AI)·Mankiw/Sargent/White(通胀)。★**Data组第15人(芝加哥大学经济学家)真名各源(CNBC/Axios/BI/FedPR)均被redactor显示脱敏,唯一News24明文源子agent自评中-高存疑→绝不臆测暂不写,留待Chao确认**(注:Austan Goolsbee是现任芝加哥联储主席/FOMC成员,不可能当外部顾问,故那个明文很可能错)。★写入防污染:英文人名/机构为ASCII不触发脱敏可直接写(中文头衔会污染→institution/bio用英文描述);写后读回验证display_name无ANONYMIZED(污染0);红线"secret"命中是"Undersecretary/Assistant Secretary"头衔误报非密钥。★现实:这批多为学者/央行家/企业高管(Xbox CEO/沃尔玛前CEO/大数据学者Chetty),非典型有可交易市场观点的KOL,cron每日抓大概率多标"未找到"属正常(作Fed政策风向信号,其表态对利率预期有指示意义);cron动态读全部active无需改。源:Fed官方task-forces.htm 2026-07-09。
- ★**信号灯配色统一(2026-08, Chao要求)**：卡片右上角灯(.mc-dot/.dot)原用莫兰迪低饱和色(sage/mustard/clay)红黄绿难辨→改鲜明标准色(--lamp-g #2e9e5b/--lamp-y #e0a92e/--lamp-r #d64545);无信号灯(dot-n,=无阈值/无数据,非持平)改**空心圈**(transparent+描边)与实心红黄绿彻底区分。只改灯不动卡片其他莫兰迪配色。
- ★**三国货币供应量 M0/M1/M2(2026-08 接入, Chao要求; 2026-08 升级折美元+M2十年折线)**：external_data.fetch_money_supply(to_usd=True) 挂在三大央行资负表下方(央行资负表=央行造的"底钱"基础货币；M0/M1/M2=社会实际流通的钱,两层级别不同)。★数据源:US=FRED fredgraph.csv 直连免key(M1SL/M2SL/BOGMBASE, BOGMBASE基础货币代理"M0",自动最新)；JP/CN=无稳定免费API→读 data/money_supply_override.json(月度值,weekly cron agent 用web_extract从BOJ/PBoC官方更新)。★**折美元(Chao要求横向对比)**:to_usd=True默认,JP/CN 按 FRED DEXJPUS/DEXCHUS 当期汇率折成$B,本币原值存 orig_m0/m1/m2/m3+orig_unit(dashboard括注)。dashboard 递进条改**跨国同尺度**(全局最大值为满宽)才能横向比长度。★FRED坑:中国M2序列(MYAGM2CNM189N)2019停更、日本M1/M2/M3(OECD源)2013-2023停更→中日绝不用FRED抓当前值,走官方。★**M2十年折线折算口径变更(Chao 2026-08)**:从"各月历史汇率"改为**"当天crawl的最新汇率统一折算全序列"**(fetch_m2_history 抓当日DEXJPUS/DEXCHUS,整条乘同一汇率,_fx记录当天汇率供说明)→剥离汇率波动,曲线纯反映本币M2真实增长(放水力度)。**旧"日本美元计零增长/+0%"结论作废**:统一汇率后日本+41%(本币918→1297万亿円真实增长显现),美+85%,中+150%(本币142→356万亿元)。dashboard说明改"剥离汇率波动/真实增长",标签"$B·当天汇率折算"
- ★**三国 M2 十年历史折线(2026-08 接入, Chao要求)**：external_data.fetch_m2_history(months=126, to_usd=True) 挂在 M0/M1/M2 框图下方,三国各一折线卡(_m2_history_html+_m2_line_svg)。★十年月度数据源(均已独立复核):US=FRED M2SL(`&cosd=`控起始日,~139点)/JP=**BOJ Time-Series CSV** `www.stat-search.boj.or.jp/ssi/mtshtml/csv/md02_m_1_en.csv`(★Shift_JIS编码需decode,第10列=M2存量亿円,2003至今559行)/CN=**东方财富 datacenter API** `datacenter-web.eastmoney.com/api/data/v1/get?...reportName=RPT_ECONOMY_CURRENCY_SUPPLY`(需Referer头,BASIC_CURRENCY=M2/CURRENCY=M1/FREE_CASH=M0亿元,222月2008至今)。★折美元**当天最新汇率统一折算全序列**(Chao 2026-08改, 见上条; 剥离汇率波动看本币真实增长):日本+41%,中国+150%,美国+85%。daily cron 每日实时拉(数据源稳定可回溯,不单独存GitHub json)。
- ★**外国官方托管美债折线 6月→24月(2026-08 Chao要求扩长)**：fetch_foreign_custody_ust() 的 _custody_history_fred(start) 起始日改为动态"740天前"(~24个月,WMTSECL1周度约104-106周点);_custody_chart_svg X轴标签从 MM-DD 改 YYYY-MM(24个月跨度需显示年份)。
- ★**美国国债拍卖 timeline(2026-08 接入, Chao要求)**：external_data.fetch_treasury_auctions() 抓**美国财政部 fiscaldata 官方API**(api.fiscaldata.treasury.gov/.../accounting/od/auctions_query, 免费无key)。7个关键券种(2/3/5/7/10/20/30Y Note&Bond, Bill货币工具口径不同不纳入)每个**最新+过去3次**(共4次)+**下次拍卖日程**。字段:offering_amt发行规模/total_accepted中标额/bid_to_cover_ratio中标率BTC/high_yield最高中标收益率/indirect_bidder_accepted间接投标(占比≈外国央行代理需求,与托管美债互印证)。★坑:①"未来拍卖"必须用`auction_date>=today`筛(不能只看high_yield为null,老reopening行也是null会误判);②长债(20/30Y)一月一拍,需拉420天历史才凑齐过去3次;③API返字符串'null'非None,需_auc_num转换;④_req返回(status,json)tuple且path相对/v1。dashboard `_auctions_html`: 每券种一条timeline(最新大字+过去3次下挂节点+下次banner),中标率色标`_auc_btc_cls`(>2.5绿强需求/2.2-2.5灰正常/<2.2红偏弱=需求恶化早期信号)。三处产出:①dashboard timeline卡片(每日cron步骤6抓+传generate刷新)②Notion DB_AUCTIONS(每次拍卖一行,'券种 拍卖日'作title幂等,write_auctions_notion,**每周cron写存档**)③GitHub data/auctions/<week>.json(**每周cron**)。当前:10Y(8-12)BTC2.53/HY4.683%,3Y(8-11)BTC2.71,下次30Y(8-13)$25B。
- ★**外国官方托管美债(2026-08 接入, Chao附FT图; 2026-08 升级加折线图)**：external_data.fetch_foreign_custody_ust() 反映外国央行减持美债/去美元化趋势。★口径统一走 **FRED WMTSECL1**(Memorandum Items: Custody Holdings: Marketable U.S. Treasury Securities, 周度 as-of Wednesday, 2002至今**活跃**——注意无后缀的旧 WMTSECL/WMTSEC 2012已停更, 带`1`后缀的才是当前活跃版!)拉31周历史序列(_custody_history_fred, start 2026-01-01), H.4.1 HTML 降级为仅补总托管(含机构债/MBS)。当前$2.631T(2026-08-05周三口径), 周环比-25.5B(-0.96%), 7月区间-126B(-4.6%)。三处产出:①dashboard 底部独立卡片 _custody_html **含 6个月折线图**(_custody_chart_svg: 680x200, Y轴刻度+日期标签+最新点标注+趋势色 下降clay红/上升sage绿)+区间统计(首末回撤/区间高低)+大号值+周环比箭头 ②Notion 周度时序 DB_CUSTODY(write_custody_notion 以as_of作title幂等)③GitHub每日json副本。每日cron步骤6抓+写Notion+进dashboard,步骤7进json。fetcher返回向后兼容(多了 history 字段)。

## Notion 8 DB (id 在 .env)
- DB_INDICATORS 每日指标 · DB_COT 金银COT · DB_REPORT 每日报告(page内部写6部分+分领域+KOL+流动性+央行BS+持仓丰富blocks) · DB_WEEKLY 周报 · DB_HOLDINGS 机构持仓13F(3ba47eb5...) · DB_CUSTODY 外国官方托管美债(周度时序,3ba47eb5-fd3c-8143...) · DB_AUCTIONS 美国国债拍卖(每次拍卖一行,3bb47eb5-fd3c-814d...) · DB_MONEY_SUPPLY 货币供应量M0/M1/M2(每国一行月度时序)
- ★**三国货币供应量 M0/M1/M2(2026-08 接入, Chao要求)**：external_data.fetch_money_supply() 挂在三大央行资负表下方(央行资负表=央行造的"底钱"基础货币；M0/M1/M2=社会实际流通的钱,两层级别不同)。★数据源:US=FRED fredgraph.csv 直连免key(M1SL/M2SL/BOGMBASE, BOGMBASE基础货币代理"M0",自动最新)；JP/CN=无稳定免费API→读 data/money_supply_override.json(月度值,weekly cron agent 用web_extract从BOJ/PBoC官方更新)。★FRED坑:中国M2序列(MYAGM2CNM189N)2019停更、日本M1/M2/M3(OECD源)2013-2023停更→中日绝不用FRED,走官方。★口径:中国官方公布M0/M1/M2三口径;美日无"M0"用Monetary Base代理;日本额外有M3(=M2+邮储/农协,M3>M2>M1);三国各自本币量级不可跨国比。★数据坑(独立验证纠错):BOJ Money Stock速报PDF两行表头拼接,列序=M2|M2季调|M3|M3季调|M1|準通货|现金|存款,子agent曾读串(把M2报成M1);逻辑校验M1<M2<M3+"M1=现金+存款"精确对上才算对。dashboard `_money_supply_html`:三国卡片每国M0/M1/M2(+日M3)递进条(以最大值为满宽,一眼看层级包含)+顶部说明文字(基础货币≠流通量/货币乘数/口径差异)。三处产出:①dashboard卡片(daily cron步骤6 fetch+write_notion+传generate)②Notion DB_MONEY_SUPPLY(write_money_supply_notion,'国家 as_of'幂等,daily+weekly都写)③GitHub data/money_supply/<week>.json(weekly cron)。当前值:美M2 $23,155.2B/M1 $19,831.5B/基础货币 $5,488.4B(2026-06);日M2 ¥1,297万亿/M1 1,090.5/M3 1,641.2/基础货币 554.9(2026-07);中M2 ¥356.71万亿/M1 118.5/M0 14.7(2026-06)。更新周期:全月度(BOJ次月第2工作日/PBoC次月10-15日/FRED次月第4周)。

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

## SEC XBRL（AI 产业链 FCF / 信用维度）踩坑铁律
- **币种必须显式过滤 USD**：同一标签常同时申报 USD 与本币（TSM 同时报 TWD，差约 32 倍）。
  `_xbrl_annual` 早期实现遍历 `units` 全部币种、后写覆盖先写，取到哪个纯看 SEC JSON 的键序——
  一旦顺序变化就会静默放大 32 倍。现已硬性只取 `USD`。
- **绝不"每个标签各取最新值"**：会把不同财年的构件混算出假比率。
  实测 DLR 的 `LongTermDebtNoncurrent` 停更于 2011、ETN 的 `OperatingIncomeLoss` 停更于 2019；
  正解是取「各构件都存在的最近共同财年」（`_common_fy`）。
- **只认 10-K/20-F 年报**：GEV 的债务仅在 10-Q 申报，annual-only 过滤后为空 → 按铁律标 n/a，不用季报凑。
- **DLR 杠杆无解**：近年 10-K 无总债务年度标签，10-Q 分项（Secured/Unsecured）加总会低估 → 标 n/a。
- **单名企业债市场利差免费源已全灭**（FINRA TRACE 公开端点关闭、交易所/终端付费或 403）。
  故图二用财报口径（净债务/EBITDA、利息保障），并在图注明确声明「不是市场信用利差」。
  严禁用股价波动等替代指标冒充利差。
