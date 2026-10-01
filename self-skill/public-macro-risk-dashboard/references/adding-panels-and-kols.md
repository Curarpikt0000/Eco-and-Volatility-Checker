# 给 Eco-and-Volatility-Checker 加新板块 / 加 KOL 的实操模式

两类高频扩展需求的 proven 方法（2026-08，Chao）。

---

## A. 参照一张外部研究报告图（如 Morgan Stanley 三联图）复刻新 dashboard 板块

**触发**：Chao 发一张券商/研究机构的图，说"把这几个图的数据用过去 N 年真实数据新增到我的 html / dashboard"。

### 铁律：数据源可得性诊断先行（决定能不能诚实复刻）
动手前先对图里**每个指标**判定公开数据可得性，分档：
1. **FRED / 官方免费可得** → 直接用真数据（收益率 DGS10/DGS2、曲线利差 T10Y2Y、期限溢价 THREEFYTP10、各类 OAS BAMLC0A0CM/BAMLH0A0HYM2、VIX 等）。
2. **专有指数但有免费镜像** → MOVE 指数（ICE 专有，FRED 无免费序列）走 **yfinance `^MOVE`**（Yahoo 有免费日线历史；`df["Close"]` 多列 MultiIndex 时取 `.iloc[:,0]` 再 dropna；抓不到返 `[]` 不编）。OFR 金融压力指数走官方 CSV `financialresearch.gov/financial-stress-index/data/fsi.csv`（免 key、日频 2000 至今，列 `OFR FSI/Credit/Equity valuation/Safe assets/Funding/Volatility`；0=历史正常，正=承压，负=平静）。
3. **★机构专有、无任何免费源** → 例如 Morgan Stanley 用 **BrokerTec 专有交易数据**算的「2y OTR UST 日内 bid-ask 价差」「周度 DV01 成交量」，搜索确认只对付费机构客户开放。**绝不编、绝不冒充**。正解 = 换成**主题对齐的免费公开压力代理**，并在图的 note 里**明确标注"非 BrokerTec 原指标，用公开 XX 代理"**。
   - 「流动性/成本恶化」主题 → 10yr 期限溢价 + IG 企业债 OAS。
   - 「成交活跃度/风险传导」主题 → 10Y-2Y 曲线利差 + HY OAS。
   - 让三/四图讲一个真实故事：波动性(MOVE)↑ → 市场压力(期限溢价/IG OAS)↑ → 风险传导(曲线利差/HY OAS)，与原报告逻辑一致但 100% 真实公开数据。
4. **★官方源但反爬封禁脚本抓取（合规敏感，别撞墙）** → 典型 **CME/CMEgroup**。实测 curl CME `delivery_reports/*.pdf` 端点直接返回 JSON 错误体 `"This IP address is blocked due to suspected web scraping activity ... strictly prohibited by CME Group's website Data Terms of Use"`。这是**合规红线**（人家明说抓数据走商业渠道）。确认封禁后**立刻停手转语义等价替代**，别再花轮数用无头浏览器绕。

先用 `clarify` 让 Chao 拍板 proprietary/封禁图怎么处理（全做用代理 / 只做能真实复刻的 / 他指定代理），再动手。

**★决策方式（Chao 2026-08 明确）**：源可得性不确定时他常说"自己尝试一下你说的方法，抓数据对比哪个精确/简单/可行，然后选它"——**用真实调用实测各候选源、比对真实返回再选**，不是列菜单让他挑。只在免费路全部实测确认走不通后才升级问他。

**★结构性付费数据（如 single-name 公司 5Y CDS，Apollo 那张 Oracle vs 大厂图）**：单名 CDS 是 $9T 市场里 Markit/ICE/DTCC/Bloomberg 最值钱的资产，**无任何免费日频源**（本次实测 6 源确认）：FRED 只有评级/指数 OAS 无单名且评级档拆不出"含/不含 Oracle"；FINRA TRACE 免费 API 只有 breadth/sentiment 聚合、逐笔债券收益率要 WRDS/FINRA 付费；FMP 根本无 CDS 端点；BondbloX 是付费交易所 App。**唯一免费活路 = Finnhub 免费层其 pricing 页 Bond Profile/Bond Price/Bond Tick Data(FINRA Trace corporate) 均在 FREE 列打勾** → 免费 key 可能拿到公司债 yield → 算债券信用利差作 CDS 经济代理（IG 的 CDS-bond basis ≈ 20bp 内）。代理必须标注"债券利差代理，非 CDS 报价"，量级用公开新闻锚校验。**Chao 愿为一个 key 破"不引入需 key 商业 API"红线——但前提是你先证明免费路确实堵死；prove-then-ask，别先问**。

### ★封闭/反爬源图表的双轨替代法（B=一手语义等价，C=静态参考；2026-08 白银 issues/stops + FRED 货币黄金图）
封闭源图（CME 封禁 / 作者私有序列 / 嵌入 PNG）不能直抓、不能伪造。给 Chao 摆三条路选（A 近期二手可更新 / B 一手语义等价 / C 静态参考手抄锚点）+「你最在意这图哪个信息点」，他常给组合指令（如「C 先查作者更新频率，之后 B 也做」）。

**B 轨 = 语义等价一手替代（优先于伪造）**：封闭源图**别照抄标题**（作者标题/口径常不准），追问"这图真正想说什么信号"，找官方一手数据里语义等价的量：
- 例①：Michael Lynch「COMEX 白银投行累计 issues/stops」想说的是**做市商/投行头寸方向（接货 vs 压价）**。一手等价 = **CFTC COT commercial 净持仓**（commercial 主体就是 bullion banks；净空扩大=加空压价≈图里 Issued，净空收窄/转多=减空/被逼平≈图里 Stopped）。数据源已在项目：`fetchers/cot.py` 的 `fetch_history('silver', weeks=N)`，Socrata `6dca-aqww`，回溯到 1986，免 key，每周五更新。
- 例②：某图标题「Exports of Goods: **Monetary** gold」在 FRED **不存在**该序列；真正对应「黄金运回家暴涨」现象的是 **`IEAXGG` Exports of Goods: Nonmonetary gold**（季度 Mil USD，2026Q1≈47,248 从 2024 的 7-10K 暴涨）→ 用 FRED 真标题(Nonmonetary)诚实标注，不照抄作者那个不准的 Monetary。
- **诚实红线**：语义等价图数值不必逐点对上原图（口径不同很正常），但**趋势/信号必须真**，且在「如何看」里写清「这是 X 的一手真数据等价物，替代被封禁的 Y」。

**C 轨 = 静态参考（连语义等价一手源都没有时的诚实降级）**：作者图无 API、底层官方源被封、图是嵌入 PNG 不公开原始序列时：
- 从公开图**目视手抄关键锚点**存种子 JSON（照 `fetch_bis_gold_swaps` 读种子 JSON 模式），折线用**虚线**（`"dash":"6,4"`）区分真实性。
- section 徽章用 `⚪ 静态参考`（不用绿/黄频率徽章），标题带「静态参考·非实时·事件驱动」。
- 「如何看」必须写清 **为何静态不更新**：底层官方源封禁 + 作者事件驱动不规律更新 + 图为嵌入 PNG。写明「精度有限、绝不伪造每日折线」，并**指向同页的 B 一手数据 section**。
- 查作者更新频率：web_search 作者 handle + web_extract 其 Substack `/archive`，判断「定期日历」还是「事件驱动不规律」——不规律则不接 cron 纯静态。

**★程序化 DOM 验证（视觉后端常 400，别靠肉眼截图确认曲线）**：`browser_vision` 间歇返回 `Bad Request`(Error 400) → 改程序化读生成的 `dashboard/index.html`，`re.findall(r'<polyline[^>]*points="([^"]+)"', section_html)` 数折线点数确认曲线真画出（522 周应有 522 点），再 grep 关键数值/批注落在正确 section 区间。`browser_vision` 失败仍返回 `screenshot_path`，截图照发 Chao。确认 `docs/index.html`（公开 Pages 副本）与 `dashboard/index.html` 都含新 section（build 同时写两处）。

### ★FRED 系列"存在但前段全 0"陷阱（起点要取首个真实非零点）
FRED 系列元信息 `observation_start` 只是"序列建立日"，不等于"首个真实值日"。WMTSECL1（外国官方托管美债）名义 2002-12-18 起，但前 237 周全是 `0.0`，**首个真实非零点是 2007-07-04**。全周期图起点必须取首个非零点、标签如实写"2007 至今"，**绝不画一条贴地零线尾巴**（"数据没开始"≠"值为零"，画出来会误导）。所以当 Chao 要"2000 起"而源做不到时，诚实的 2007 起点胜过硬凑的假 2000/2002。动手改起点前先 `.../fred/series/observations?...&observation_start=...` 拉出来数 0 值点确认。

### ★Treasury fiscaldata API（MSPD 等）参数陷阱（错了耗数小时）
- `filter` 里的 `:` 和 `,` 是**语法字符不可 url-encode**——手工拼 filter 字符串，别用 requests params dict（它会把冒号逗号编码成 %3A/%2C 触发 400）。
- `page[size]`/`page[number]` 的**方括号要编码**（`page%5Bsize%5D`）。
- `page[size]` **上限 10000**，超了 HTTP 400 "Invalid Query Param"——分页循环，某页返回 < pagesize 即读完。
- MSPD 只有**月度**（每月末一个 record_date），无月内日/周频。若用户要"日/周，你定"，诚实答案可能是"这个口径只有月度"。maturing-treasury 口径 = `mspd_table_3_market` 逐券明细，按 `maturity_date` 筛"距 record_date ≤366 天"的 marketable 券加总 `outstanding_amt`（百万→`/1e6`→万亿）。

### ★分页增量 fetcher 的 cache-poisoning bug（code review 查出，任何分页缓存都适用）
`_pull_year` 里 `except: break` 遇分页中途网络错会**静默返回残缺数据**（跨页的月份加总被截断），caller 无条件写进缓存，再叠加">=11月已缓存→跳过"的增量逻辑 → **错误值永久固化不再重拉**。修法：page 抓取失败**显式抛出/返 None** 让 caller **跳过该期不缓存**；加 `resp.raise_for_status()`；只把"末页 < pagesize"当干净完成。

### ★报告型面板（BIS 国际清算银行）的 backfill + 摘要模式
- 面板 = 最新一份摘要要点 + 跳转独立页 button（复用 KOL button 的 `.part-title-flex`+`.kol-dash-btn`），独立页 `docs/<topic>/index.html` 同款莫兰迪配色 + 返回链接，公开 URL `.../Eco-and-Volatility-Checker/<topic>/`。
- BIS Quarterly Review PDF 命名规律 `https://www.bis.org/publ/qtrpdf/r_qtYYMM.pdf`（YYMM，3/6/9/12 月发），HEAD-200 确认存在，过去一年=4 份。BIS Bulletin 列表页 JS 渲染（curl/web_extract 抓不到）→ 交 cron agent 模式动态发现，别卡住 build。
- backfill 摘要 = 并行 subagent（toolset `["web"]`）各读一份 PDF（web_extract 直接吃 PDF URL）返回 4-6 条中文要点严格 JSON，主 agent 补最后一份 + `upsert_summary(id, points)` 写入。摘要必须来自实文，抽不到留 pending 绝不编。
- 侧栏可折叠分组：新面板 part-title 关键词要加进对应 GROUP 的 `match` 数组，否则落入"其他"兜底组。
- 改 jobs.json：**execute_code 在 cron_mode 被 BLOCK** → 写一次性 .py 用 `.venv` python 跑（`source .venv/bin/activate; python /tmp/patch.py`）。

### 排版偏好
Chao 常要**竖向排列**（不要像原图那样横向并排）——竖排每图全宽更清晰。实现 = `.sp-wrap { display:flex; flex-direction:column; gap; }`，每图独立 `.sp-panel` + 全宽 SVG（viewBox 940x300）。

### 代码接线（对齐现有 fetch→build→generate→_html 模式；单个新 section 六处，缺一不可）
每个新 section 六处接线：
1. **fetcher** `src/external_data.py`：`fetch_<x>()`，带**缓存兜底**（抓不到读上次真值绝不覆盖成空，status 分 ok/缓存/未获取）。全部 FRED 走带 key API 优先（`fetchers.fred.fetch_fred_history`），curl CSV 仅回退。周度降采样降噪（`_weekly_resample` 周五 as-of）。
2. **_html 渲染** `src/dashboard.py`：`_<x>_html(d)`，**优雅降级**（status 非 ok 返回 `<p class="empty">…抓取中/未就绪</p>`，绝不报错）。折线复用 `_yield_curves_svg({key:{status,name,color,dash,points,latest}}, yunit=...)`。★f-string 里不能含反斜杠转义——dash 逻辑先提到变量再插值（Python 3.11 SyntaxError: f-string expression part cannot include a backslash）。
3. **generate()** ①签名加 `<x>=None` 形参 ②format dict 加 `<x>=_<x>_html(<x>)`。
4. **HTML 模板** 加 `<div class="part-title" id="sec-<x>">…<span class="freq-badge freq-*">…</span></div>` + `<div class="card">{<x>}</div>`。整段 HTML 是 format 字符串 → 新增 CSS 花括号要**双写** `{{ }}`。
5. **侧栏 GROUPS** 把 section 标题关键词加进对应分组的 `match:[]`（白银归「能源与大宗」），否则落入兜底组。
6. **build_dashboard.py** ①try/except 调 `ed.fetch_<x>()` + print 日志 ②generate 调用传 `<x>=<x>` ③需要时数据落盘 `data/<x>.json`（进 git）+ 写 Notion（增量幂等，见下）。
- **Notion DB**：新指标存**最新一期读数（as-of 时序）**，完整历史序列在 GitHub `data/`。建库用**增量幂等脚本**（复用 `build_notion_dbs.create_db`），**只追加 .env 缺失的键，绝不跑原 `build_notion_dbs.build()`**（它写 .env 时只保留 3 个 DB，会清掉 DB_HOLDINGS/CUSTODY 等已有键）。写后**读回验证**数值。

### ★接入 daily cron 的关键陷阱
daily cron（eco-vol-01）步骤6 是 prompt 里**内联的 `python -c "...dashboard.generate(...)"`**，不是调 `build_dashboard.py`。
- **不要**把它改成 `python -m src.build_dashboard`——`build_dashboard.py` **不读 `ai_analysis_{date}.json`**，会丢掉步骤5 生成的每日 AI 短评/分领域分析（`ai_reads/ai_conclusions/daily_notes`）。
- 正解 = **只在内联调用里补传新参数**（`stress_panels=sp, ...`），保留 `ai_reads=ai.get('reads')` 注入。改 jobs.json 用 Python 脚本精确 `replace` 锚点，改前备份 `cp jobs.json /tmp/...`，改后 `json.load` 验证有效 + grep 确认新参数注入。cron 下次运行自动读文件，不必重启。
- 顺手检查内联调用是否漏传了之前新增的图。
- **注**：若新 fetch 已接进 `build_dashboard.py` 模块且 cron 用的正是该模块（部分 section 如 market_breadth/BIS/白银），则 cron 无需改，自动带上——先确认 cron 走内联 generate 还是 build_dashboard 模块。

---

## B. 从用户发的信息图往 KOL 名册批量加人

**触发**：Chao 发一张含人名的信息图，说"把这张图上的所有人放进我们的 KOL tracker"。

### 名册铁律（复用 kol-opinion-consensus-dashboard 的规矩）
- **只加点名者**：图上有谁加谁，绝不联想/替换/凭空多加。
- **只增不减**：`data/kol_registry.json` 只 append，删除必用户明确确认。
- 幂等查重（`display_name.lower()` 去重）→ 锚既有 `domain/sector` 枚举**不新建类**（Fed 政策顾问归 `domain=宏观货币与金融体系 / sector=Macro`）→ 写后读回验证 → 红线扫描 + commit push 公开 repo。
- cron 动态读全部 `active==true`，增减名册无需改 cron。

### ★真名核实：图 + 权威源交叉，redacted 名不臆测
1. 先 `vision_analyze` 读图拿人名 + 身份/头衔。
2. 图是公开事件 → web_search/web_extract 官方页 + 权威媒体交叉核实真名 + 准确头衔。可 delegate 给带 web 的 subagent 并行研究。
3. **redactor 会把新闻正文里的人名显示脱敏成 `ANONYMIZED_PERSON_*`**——但**明文常从 URL slug、副标题、引用叙述句里泄漏**。交叉多源锁定明文。
4. **某个名字在所有权威源都被脱敏、无法可靠锁定 → 绝不臆测、暂不写**，留占位待用户确认。宁可少一人先入册也不写一个可能错的名字。

### ★写入防 redactor 污染
- **英文人名/机构是 ASCII，不触发脱敏，可直接明文写进脚本**（`display_name`、`search_terms` 用英文名）。
- **中文头衔/描述会被污染** → `institution`/`bio` 里的身份描述**用英文**写，避免磁盘落字面占位符。
- 写完**读回磁盘验证**：`grep`/`json.load` 检查 `display_name` 里**没有** `ANONYMIZED`（污染数=0 才算成功；终端显示脱敏是渲染层，磁盘是真值）。
- 红线扫描误报注意：`grep secret` 会命中头衔 "Under**secret**ary" / "Assistant **Secret**ary" —— 用真密钥模式复核确认非密钥再 push。

### search_terms 与现实预期
- search_terms 用 `[name, f"{name} Fed", f"{name} inflation rates economy"]`。
- **诚实预期**：这批多为学者/央行家/企业高管，非典型有可交易市场观点的 KOL，cron 每日抓大概率多标"未找到"属正常。加人前用 `clarify` 让 Chao 知道这个实际效果。
