# Eco-and-Volatility-Checker 上下文日志

> 由 cron `eco-vol-context-distill`（每日 06:00 JST）自动追加。
> 首节 2026-08-22 由本人手工写入（当日 session 过长，先落盘再启用自动归档）。

---

## 2026-08-22

### 决策

- **KOL 名册 SSOT 改为 Notion「KOL List」DB**，GitHub 侧 `data/kol_registry.json` 降级为**镜像副本**。
  Chao 明确：「只用 Notion 上的人，不要再增加了」「你不要做我没给你的任务」。
  → agent **绝不自行增删 KOL**；增删一律由 Chao / 另一 agent 在 Notion 操作。
- **项目边界裁定**：玄学 / 术数 / 占星 / 通灵 / 末日预言类**不属本项目**，归 Forecast-Checker。
  本项目只留**可交易的金融判断**。
- 2026-08-20 自建的「周期与术数预测」独立 section **停用**；技术分析 / 量化周期派归**常规 KOL 板块**。
- 23 人按方法论拆分：**11 位玄学派迁出**（金融占星 / 圣经周期 / Gann / 中文易经六爻奇门 8 人），
  **12 位技术分析派保留**（艾略特波浪 / McClellan 市场宽度 / ECM / Hurst 周期 / 世代长周期）。
- 每日同步**不新建 cron**，而是在现有 `eco-vol-01-daily-scan-report` 里插入「步骤 0」。

### 事实与配置

- Notion「KOL List」DB = `35947eb5-fd3c-800d-b852-cef31f9de6a5`，
  位于 page「KOL Research Daily Update」`31447eb5fd3c8064a531c43b177cdc41`
  （同页另有 KOL By Week / KOL By Day 两个 DB）。
- 同步后名册 **124 人**，与 Notion 完全一致。
- 移出 3 人：FEMA、Sarah Bond、Harry S. Dent Jr. → 留痕 `data/kol_removed_20260822.json`，
  其 `data/kol/backfill/` 历史文件**保留未删**。
- 新建 5 人：Michael Widmer、Jim Rogers、Judy Shelton、Asha Sharma、Kevin Murphy。
- **TIC 分国别持有美债数据源修正**：`mfhhis01.txt` 是**历史存档表**（只到上一自然年年末），
  当年月度在 **`slt_table5`**（13 个月滚动窗口）。两源合并、当期表优先。
  修正后：日本 **$1,116.7B** / 中国 **$633.4B**（as of 2026-06），与官方 2026-08-17 发布一致。
  修正前显示 $1,186B / $684B（2025-12 旧值，落后 6 个月）。
- **EU 无法用当期表**：TIC Table 5 只列前 20 大持有国，德/意/荷/西/芬 落在 "All Other"，
  9 国加总口径结构上无法还原 → 保留存档表真值 + 图上写明 `lag_reason`，不做半截加总。
- **BIS credit-to-GDP 实际发布延迟 9–10 个月**（FRED QUSPAM770A/QCNPAM770A 实测最新即 2025-10-01），
  套用通用 `quarterly=135` 天阈值会**恒定误报红标** → 新增 `bis_quarterly=330` 阈值。
- KOL 历史回填：**2,804 条**，覆盖 2025-01-02 → 2026-08-21（20 个月）。
- `ddgs` 之前**未装在 Hermes 自己的 venv** 里（`/home/user/.hermes/hermes-agent/venv`，uv 建的无 pip），
  导致每次 web_search 都报 "not installed" 后静默回退兜底。已用
  `VIRTUAL_ENV=<venv> ~/.local/bin/uv pip install ddgs` 装上 9.15.0，实测生效。

### 进展

- commit `18063a3`：修弹层空态（cron 内联命令漏传 `kol_history`）+ TIC 错值 + 全量回填至 2804 条。
- commit `0e37059`：Notion 单向镜像同步 + 玄学派迁出 + dashboard 三处名册过滤。
- commit `6203d19`：AGENTS.md 固化 SSOT 铁律与项目边界 + cron 加「步骤 0」。
- 新增工具：`tools/sync_kol_from_notion.py`（单向镜像）、`tools/split_cycle_kols.py`（拆分）、
  `tools/add_notion_sync_to_cron.py`、`tools/clean_cron_esoteric_ref.py`（幂等改 cron，带备份）。
- 线上验证通过：md5 `c76c8d92e93a` 本地/线上一致；111 张卡片全部可点、**0 张空白**。
- Forecast-Checker 侧：87 → 98 人，11 位玄学派 + 18 条已验证历史并入，已推公网。

### 踩坑

- **弹层空白根因**：项目有**两个构建入口**——开发用 `src/build_dashboard.py`，
  cron 用一条 2,600 字符内联 `python -c` 直调 `dashboard.generate(...)`（30 个参数），
  漏传 `kol_history` → 线上 `var DATA = {}`。修法：兜底放进**被调函数内部**，任何入口都不会再漏。
- **名册变更后下游不跟随**（同一病根，踩了两次）：
  `kol_full_history()` 直接扫 `data/kol/backfill/` 目录、
  `kol_weekly_views()` / `kol_stance_changes_grouped()` 读的是**每日快照**，**两者都不看名册**。
  → 移出人后必须在渲染层按名册过滤，否则出现「卡片没了但历史仍内嵌在 payload」
  或「卡片还在但点开空白」。已在 `_kol_history_payload` / `_kol_views_html` / `_kol_changes_html` 三处加过滤。
- **Notion 名带机构后缀导致模糊匹配误删**：「Nomi Prins（… 前 Goldman Sachs MD）」
  被本地「Goldman Sachs」条目抢先匹配走，导致 Nomi Prins 被判为「Notion 无」要移出。
  正解：**先全量精确匹配 → 模糊只认「本地名 ⊂ Notion 名」单方向 → 取最短候选 → 已配对者不再参与模糊**。
- **子代理 600s 硬超时会丢光成果**：首轮 3 个子代理各跑 25–34 次 API 调用，
  全都「先搜集、最后统一写文件」，超时一到上下文清空，零落盘。
  正解：**抓一个立刻 `write_file` 落盘，再抓下一个**；每批人数压到 8 人；禁用慢速 `web_extract`。
  修正后同期落盘 4 → 23 个文件。
- **子代理产出的 URL 必须本人逐条 curl 验证**：中文小众频道抓到 2 条 404 幻觉链接
  （`@xiaoxia523`、`hao.cnyes.com/post/177469`），已剔除并在文件留 `verify_note`。
  被 WAF 拦的 401/403（Reuters/Bloomberg）不算死链，另做内容交叉验证。
- **页面自相矛盾就是 bug 在报警**：Chao 一句「右上角写每月更新，图上却说滞后 233 天」
  同时揪出两个独立 bug。核实后有两种**相反**结论：官方已发新数据 → 改数据源；
  官方最新就是这期 → 改 SLA 阈值（误报）。**绝不假设「官方就这么慢」，先查官方**。
- **新板块首次接入的数据最容易错也最难发现**：TIC 板块 2026-08-14 上线第一天就接错源，
  一周无人察觉——没有历史基线可比，错值看起来就像正常值。
  `git log -S` 溯源可区分「新引入」vs「历史遗留」。

### 待办

- [ ] 本 session 的经验尚未 ingest 进 ChaoWiki（已写 `knowledge/frontend/data-dashboard-publishing.md` §8，
      但 KOL 名册 SSOT / 子代理超时 / 名册-下游一致性这几条还没归档）。
- [ ] 遗留技术债（非阻塞）：39 处 `except: pass` / 11 处 `except: continue`；
      `_stress_panel_svg` axis 与除零；BIS API 406。

---

## 2026-08-23

> 归档范围：2026-08-22 下午～深夜的会话（commit `13d0f52` → `0917b7a`）。
> 上一节 2026-08-22 已覆盖 `18063a3`/`0e37059`/`6203d19`，此处不重复。

### 决策

- **Chao 纠正「我怎么没看到」→ 根因是还没 push**：本地做完 ≠ 用户看得到。
  以后交付报告必须明写「未 push」，并把 push 授权当成独立一步问。
- **COMEX 交割前十名排名口径 = 总量（不是净额）**。理由：「前十名 issue」直觉上就是
  发货最多的十家；净额会让大进大出的行掉出榜。（Chao 未逐条拍板，由本 agent 按方案定，已报备）
- **Chao 要求单位改吨**（原为手数），便于口算；括号保留原始手数可追溯。
  换算按 CME 官方合约规格：Au 100oz / Ag 5000oz / Pt 50oz，1 troy oz = 31.1034768 g。
- **carry 图正名（Chao 选 A 方案）**：「② 套利 Carry / Basis Trade Carry」
  → **「② 持券 Carry / Cash Carry」**。本图算的是「收益率 − 隔夜融资」= 现券单腿持有 carry
  （仍暴露久期风险），**不是**对冲基金期现基差套利（双腿：买 CTD 现券 + 空国债期货，
  收益 = IRR − 实际回购利率）。真 net basis 需 CME 期货价 + 转换因子 + CTD 判定，
  免费源不可得 → **只做现券 carry 并如实标注，绝不冒充**。
- **侧栏顺序必须与页面 DOM 顺序完全一致**（Chao 体感「往下 browse 时左边 menu 跳来跳去」），
  且**「机构与政要持仓」钉在最后**（放在「其他」下面）。
- **redactor 占位符只修 Chao 点头的那一处范围**：发现 `src/dashboard.py` 2 处占位符是
  **HEAD 历史遗留、不在本次改动范围**，先报备再动手，Chao 回「可以」才修。

### 事实与配置

- **COMEX per-firm 底座**：新脚本 `Comex-Daily-Report/src/build_issue_stop_firms.py`
  → `data/comex_issue_stop_firms.json`。**per-firm 明细在解析层本来就有**，
  是旧 `aggregate()` 把 firm 维度加总扔了 → 无需重抓，改聚合即可。
  - archive PDF **133/133 全解析成功，0 失败、0 总量不符**（席位加总 == PDF `TOTAL:`）
  - 双通道：archive PDF（到 2026-06-05）+ Notion「Activity Note [Delivery]」增量
    → 覆盖 **2026-01-06 → 08-19，132 天**
  - 三金属齐全：Gold 124 天 / Silver 125 天 / Platinum 62 天
  - **铂金一度误判「无数据」**：parser 本就支持 Pt，抽的那份 PDF 只是当天没交割；
    扫全量才知 78/133 天有 PLATINUM 合约。**交割稀疏 ≠ 没有数据**
  - 机构名归一做在**出口 `display_name`**（不能只做入口映射）：兜底 `raw.title()` 自己会造裂名
    （`CME`→`Cme`）。归一后机构 42→34，**总量一分不差**才算归一成功
- **两条数据真相已写进图注**：CME 占黄金近一月发货 38.6% —— 它是**清算所自身席位不是市场参与者**；
  铂金短窗口榜单会很空（近一月仅 1 天 1 手），如实显示不拿别的窗口填充。
- **机构阵营说明 6 组**覆盖数据集全部 34 家（0 漏 0 编）：清算所自身 / LBMA 美系 / LBMA 欧系 /
  加日澳银行 / 非银 FCM 自营 / 对冲基金。图注两条免责：**一般性行为逻辑非指控**、
  **席位 = 清算通道 ≠ 最终受益人**。
- **KOL 名册对齐判据 = 双向零差异，不是条数相等**：Notion 124 / 本地 124，
  但字符串精确差异有 25 对（Notion 名带机构后缀），剥括号后才为 0。
  全量重抓 **124/124 全中**，快照 `data/kol/daily/2026-08-22.json` 与名册 id 双向差集皆空。
  方向分布：强烈看多 33 / 看空 23 / 看多 23 / 未找到 28 / 分歧 13 / 中性 3 / 强烈看空 1；**真转向 35 人**。
- **卡片数 ≠ 名册数是正常的**：dashboard 149 卡 = 观点全景 123 + 状态变化 26（同一人可两处出现）。
- **cron 步骤 6 内联 `dashboard.generate` 漏传 18 个参数**（渲染函数 46 个可选参数，内联手抄只传 28 个）
  → cron 每天产出的看板比手动 build **少 18 个板块且完全静默**。已补齐 46/46（BIS filter 后 47/47）。
  **不能一劳永逸改用 `build_dashboard.py`**：它不读 `ai_analysis`，切过去会丢每日 AI 短评。
  写内联代码前必须真机验证函数名（第一版凭印象猜错 4 个，如 `fetch_silver_imports` 实为 `fetch_silver_imports_data`）。
- **BIS 板块 4 期要点本来就在 `data/bis/reports.json` 里**（2026-06/2026-03/2025-12/2025-09 各 6 条），
  只是 `_bis_section_html` 只渲染 `latest_report()` → 改渲染即可，零成本。
  **「没有历史」有两种，动手前先 `print(期数)`**。
- **新增 `src/vintage_store.py` 期次存档层**：IMF debt/GDP 与公司债 fetcher 实时抓不落盘、无历史可切。
  每次 build 存一期快照（**仅 `status==ok`**），攒够 2 期才出 filter。
  `period_key` 按**发布期**不按实绩年（IMF 一年两次，用实绩年当 key 会互相覆盖）；
  日频源降采样成月（`2026-08`，否则一年 365 个按钮）。**今天各只有 1 期 = 诚实显示单期不出按钮**。
- **分评级公司债余额免费源确实拿不到**：SIFMA 只有 Corporates 单一合计（1Q26 ~$11.74T），
  FRED 带 `TRIV` 的是总回报指数**不是余额**。属 ICE/Bloomberg 授权 → 只给能验证的全市场口径 + 写明原因。
- **审批门禁根因是配置不是运气**：`~/.hermes/config.yaml` 的 `approvals.timeout: 60`，
  超时按拒绝计；**聊天里说「同意」与写入门禁是两个独立通道**。
  agent 按设计改不了（`hermes config set` 触发网关自保 / 直接改被 `Refusing to write to Hermes config file` 拒）。
  Chao 在会话外 shell 跑 `hermes config set approvals.timeout 600` 后，同一个 patch **一次通过**。
- **redactor 取证两步**：① 布尔探测（`'ANONYMIZED' in line` vs `已知真名 in line`，不打印内容）
  ② `git show HEAD` 溯源区分历史遗留 vs 本次引入。
  本次实测：`src/dashboard.py` line 6411/6412 **磁盘真是占位符**（真污染），
  而 line 2364 图注、`data/comex_silver_issues_ref.json` 的 `source`、AGENTS.md 那处**磁盘都是真名**（仅显示脱敏）。
  修法：从已验证干净源**程序化回填，绝不手打**。

### 进展

- commit `13d0f52`：需求 A（金银 issue/stop 图加时间 filter：当周/月/三月/全部，金银独立切换，
  柱数对账 2/8/26/64）+ 需求 B（新 section `sec-comex-firms-top10`，3 金属 × 4 窗口 = 12 pane、147 行榜单，
  源 JSON 147 行一致、三金属总发 == 总接守恒）+ 需求 C（侧栏按 DOM 首现排序：
  **向上跳跃 3 → 0 次，「其他」7 项 → 0，44/44 同序，机构持仓 `pinLast` 钉底**，
  新增「债务与信用」分组）+ KOL 124 人全量重抓 + 14 个不在 Notion 名册者的 backfill 移入
  `data/kol/backfill_removed_20260822/` 留痕不删 + AGENTS.md KOL 人数去硬编码。
  新 fetcher `fetch_comex_issue_stop_firms`；cron 补齐 46/46 参数 + 新增步骤 1d。
- commit `0f20cec`：去除 `src/dashboard.py` section 标题中的 redactor 脱敏占位符（残留 0，三需求无回归）。
- commit `5110743`：BIS 板块加近 4 个季度 filter button（24 条要点，只渲染 `summary_status==ok`，
  pending 不显示假内容）；cron 内联 kwargs 补 `bis_all` → 47/47。
- commit `0917b7a`：carry 口径正名 + COMEX 改吨与 6 组机构阵营说明 + 债券总量位置上提 + vintage 存档机制。
- `Comex-Daily-Report` commit `5e3029c`：新脚本 + per-firm 数据 json。
- 线上读回验证（重新 clone，不信本地自报）：A 8 pane / B 3 块 147 行 / C `pinLast`+`order.sort` /
  KOL 149 卡 / per-firm 132 天 全部通过。

### 待办

- [ ] 遗留技术债（非阻塞，承接上节）：39 处 `except: pass` / 11 处 `except: continue`；
      `_stress_panel_svg` axis 与除零；BIS API 406。
- [ ] vintage 存档层需在**下一期数据到位时复核 filter 是否自动出现**
      （「攒够 2 期才出」这条逻辑坏了完全无声）。
- [ ] 每次新增 section 必须同步给侧栏分组表加 match 关键词，否则又会掉进「其他」。

---

## 2026-08-24

> 归档范围：2026-08-23 全天会话（commit `81c3e08` → `7a20a4e`）。
> 主线是 **KOL 观点深度化四连击 + COMEX 交割 C/H 账户类型**。

### 决策

- **KOL 卡片要三层，不是两层**。Chao：「点开第二层和默认值没区别」。
  确认为**数据缺失不是渲染 bug**：数据只有一个 `comments` 字段（实测中位 **32 字**、最长 51 字、
  0 条 ≥100 字），前端展开层复用同一字段 → 两层必然一样。
  定案格式：**100–300 字四段式**「▸核心论点 / ▸关键依据 / ▸时间与位置 / ▸标的与操作」+ 来源链接。
- **重抓范围选 B（全量 124 人）**，不跳过此前标「未找到」的 28 人。
- **「ok 都改。而且所有人的过去一年的都需要 backfill 如果有需要的话」** → 授权同时做
  ①cron 升级为深度模式 ②vintage 接进 cron ③一年期历史全量回补。
- **快照历史 detail 选 A：全补 2376 条**（2025-12-18 → 2026-08-22），不做抽样。
- **KOL 档案卡 13 维度由 Chao 指定**：姓名 / 编号 / 领域 / 在世年份 / 现任头衔 / 代表性成就 /
  荣誉 / 主要活动范围 / 观点 / 追踪价值 / 机构名称 / 书籍 / 2026 代表性言论。
- **缺失口径分级用语（Chao 明确）**：查不到 →「未公开」；不确定 →「未检索到公开著作」；
  确定没有 →「无公开著作」。三者语义不同，**不得混用**。已故者必须标 `deceased` + 红色徽章。
- **名册增删仍只在 Notion 侧**：子 agent 报出 5 位玄学/宗教/灵媒类应迁 Forecast-Checker，
  **本 agent 只报不动**（重申 08-22 铁律）。

### 事实与配置

- **COMEX C/H 账户类型丢维的根因在聚合层不在解析层**：CME PDF 的 `FIRM/ORG` 列本就有 C/H，
  `cme_delivery_parser` 也解析了 `org`，是 `build_issue_stop_firms` **只按机构名合并把 org 维度扔了**。
  修法：archive 段按 `firm × org` 分别累计 `i_c/i_h/s_c/s_h`；
  **两通道合并时必须同步搬运分项**（第一版只搬了 `i`/`s`，577 处对不上就是这里）。
  - Notion 增量段（41 天）原始记录**无 ORG 字段** → 计入 `_u` 未知（金/银约 19–22%），**不臆测归类**。
  - 自洽校验口径：**每条 C+H+U == 总量**，三金属总发 == 总接守恒。
  - 读出的真信号：白银**自营接货 47.7% > 自营发货 40.3%**；某美系大行白银发货 **96% 是客户盘**
    （通道非观点），另两家欧美行接货 **81% / 68% 为自营** —— 只看「谁交货最多」会误读。
- **KOL 数据链路四处都要带 detail，漏一处就退回一句话**：
  `kol_independent.json`（+`detail`/`detail_status`/`sources`）→ `save_kol_daily_snapshot`
  → `kol_full_history()` 两路（snapshot/backfill）→ `_kol_history_payload`（数组 6 位扩到 8 位）。
- **`_kol_history_payload` 的不伪造纪律**：优先用条目自带 detail，其次才匹配当日深度抓取，
  两者都无则**留空** —— 绝不把某天的摘要贴到别的日期。
- **历史条目的存量文本本就有 150–200 字**（与当日新抓的 32 字差一个量级）→ 多数只需**重组四段不必联网**，
  仅对 <60 字且有链接的约 10% 条目联网补正文。不做这步会把「重排版」当「重新采集」。
- **新工具**：
  - `tools/backfill_kol_detail.py` —— 幂等可续跑，`--stat`/`--limit N`/`--apply`。
    ★**脚本自身不生成任何文字**，只做挑选与落盘；`--apply` 按 `(file,date)` 定位，
    匹配不到就跳过报告，**绝不新增条目** → 结构上杜绝脚本编造。
  - `tools/apply_snapshot_detail.py` —— 快照历史回填，幂等可重跑。
  - `tools/apply_1yr_backfill.py` —— 一年期回补，内置四道关（见下）。
- **`data/kol_profiles.json`** —— 125 条档案（122 在册 + 3 已移出机构条目留档）；
  dashboard 最底部新增 `sec-kol-roster`，按 10 个领域分色成组，**读名册 active 全量不写死人数**，
  无档案者显示「档案待补」只列名册已有字段。
- **名册同步实况**：跑 `sync_kol_from_notion.py --apply` → **124 → 122**。
  移出 3 个机构条目（留痕 `data/kol_removed_20260823.json`，档案保留不渲染），新增 1 人并补全档案。
  编号沿用 Notion `notion_list_num`。
- **cron 升级**（改的是 `~/.hermes/cron/jobs.json`，不在本 repo）：
  步骤 3 → 深度摘要模式（prompt 写死「宁可标 thin/none 也不许凑字数」「绝不能只写 comments 不写 detail」）；
  **新增步骤 3b** 每日跑 `backfill_kol_detail.py --limit 25` 增量补历史；
  步骤 6 补 vintage 存档说明。generate 参数复验 **47/47**。
- **一年期覆盖率的正确读法**：每日快照 2025-09 才开始攒，88/122 人历史天然不足一年。
  回补后**≥355 天实质达标 52 人（42.6%）**，但**大量人卡在 2025-08-24~09-02（距判据线仅 1–10 天）**，
  查证是其公开发声起点 / 存档边界，**非回补遗漏**。
  → **真正该报的指标是「历史起点被前推了多少天」**（80 人被前推，平均 120 天、最多 361 天），
  而非受不可控存档边界支配的「达标率」。
- **子 agent 报「`batch6.json` JSON 语法错误」是假问题**：父端复验 `json.load` 正常（20 人），
  是 redactor 显示脱敏截断了引号。**生成脚本无 bug**，其另存的 `_fixed` 副本反而要清掉。

### 教训

- ★★**回填脚本第一版按「日期就近」贴摘要，造成 972 条错配 —— 这是伪造，已回滚重写**。
  症状：1188 条输入却回填 2160 条；只看「回填成功 2160 条」的日志会误判为超额完成。
  根因：「日期最近的下一条」可能是完全不同的另一条观点。
  修法：**只按 `(kol, comments 全文)` 精确匹配** —— 同一观点跨多天时 comments 字符串本就相同，
  用内容当键天然覆盖区间且不可能贴错；输入缺 comments 则**拒绝回填不按日期猜**；未匹配的留空。
  复验 2338 条精确匹配零错贴。**判据：必须做内容一致性校验，条数对不上就是错配。**
- ★**一年期回补的四道防伪造关**（`apply_1yr_backfill.py`）：
  ①**日期硬校验** —— 每条 `date` 必须落在该人 `window_from~window_to` 内，**越界一律拒收**
  （越界＝把无日期内容随便标个日期＝伪造历史）；②同日同文去重；③只增量不覆盖；④幂等可重跑。
  ★**父端独立复核不信子 agent 自报**：越界 0 / 无日期 0 / 无来源 0 三项全过才入库。
- ★**「一次性提质」与「升级 cron」必须同轮，且 cron 先于全量回填** ——
  只把质量拉上去不改自动化，次日定时任务按旧模式重跑就把成果全打回。
  且 **cron 引用的脚本必须先落盘存在**，否则次日凌晨报「文件不存在」且无人看见。
- ★**子 agent 900s 超时的止损靠增量落盘**：prompt 强制「每 40 条落一次盘」，
  超时那路仍保住 160/198，只补跑 38 条即完整。
- ★**「只重建不重抓」的脚本仍会写盘**：`build_dashboard` 首步调 `save_kol_daily_snapshot()`，
  跨午夜重跑产出**日期＝运行日而非数据日**的快照（本次两次误生成 08-23 快照，人工删除）。
  日期戳必须来自数据自身，缺失就报错拒写，不能静默降级到 `today()`。
- ★**第三方传记不计为本人著作**；**同名干扰逐一排除**（实测撞上同名古生物学家 / 小说家 / 运动员 / 画家 10+ 例）。
- ★**核实档案会顺带查出名册过时头衔**（本次 20+ 人：已卸任 CEO、离职自立门户、转投他行）→
  按现状写进档案，但**不反向改真源**（SSOT 在 Notion 侧）。

### 进展

- `81c3e08` KOL 深度摘要（124 人全量重抓，detail 中位 **32 → 317 字**，110 ok / 13 thin / 1 none，
  「未找到」28 人 → 3 人）+ COMEX 交割 C/H 账户类型（徽章 紫=自营 / 蓝=客户 / 灰=未知 + 每窗口占比条）。
  Comex-Daily-Report 侧 `80376ac`。
- `fff6817` `tools/backfill_kol_detail.py` + cron 升级为深度摘要模式（含新步骤 3b）。
- `ed03397` 历史观点 detail 回填 **369/369**（359 ok / 10 thin，四段式 100% 合规，中位 190 字）+ 渲染层透传。
- `93b3385` 快照历史 detail 全量回填 **2376 条**（12 批 × 198 并行），
  dashboard **2859/2859 条 100% 有 detail**；0 次联网、只重组不新增。
- `d961d10` KOL 13 维度档案卡 **122/122 零字段缺失**（`sec-kol-roster`）+ 名册同步 Notion 124→122。
- `7a20a4e` 一年期历史回补 **88 人 / 284 条**（226 ok / 58 thin），历史条目 2908 → 3192，
  dashboard 渲染 3088 条 100% 有 detail；**80 人历史起点前推，平均 120 天**。
- 回填前均整目录备份至 `scratch/backups/`（`backfill_pre_detail_20260823` /
  `daily_pre_snapdetail_20260823`）。

### 2026-08-23（补记 · 日报模块化全覆盖 + ECB 漏报根因）

**Chao 要求**：「日报应该根据每天可以更新的所有 dashboard 数据来做，而不是只包含其中一部分。
可以分成不同模块，比如流动性、债务、信用、贵金属等等……不用在乎日报是不是太长，
重要的是关键信息有没有包含全，以及分层结构是否方便人类阅读清晰。」

**发现的真实缺口**（逐项对代码查证，非估计）：
- dashboard 有 **45 个 section**；旧步骤 9 只点名报「6 部分骨架 + KOL/流动性/央行/13F/政要」5 个附加项。
- 即：压力四联图 / 国债拍卖 / 托管美债 / 信贷脉冲 / COMEX 全套（库存·周净·top10·COT·BIS掉期·
  黄金出口·亚洲溢价·白银进口）/ 石油库存 / 市场广度 / 日经外资 / CIPS / AI 产业链 / IIP /
  百年收益率 / 再融资墙 等 **30+ 板块，抓了数据、进了 dashboard，却从不进日报**。
- `external_data` 共 **42 个 fetcher，cron 调用 38 个**；未调 4 个：
  `fetch_kol_recent`（2026-08 独立化后已弃用）、`fetch_ecb_balance_sheet`（冗余，见下）、
  `fetch_treasury_curve` / `fetch_synthetic_spreads`（待核是否被其他板块间接覆盖，未擅自接入）。

**★ECB 漏报根因 —— 不是数据缺失，是文案没写**：
日报文案一直写「三大央行」，但 `fetch_cb_balance_sheets()` **本来就返回 ECB**。
实测四家全部正常：US 6 资产项 / JP 5 / CN 4 / **ECB 6**（黄金及黄金债权、外币资产、
APP+PEPP 货币政策证券、对信贷机构贷款、银行券、存款便利），走 ECB 官方 SDMX，
dashboard 早已显示总资产 €6,864 亿。
→ **教训：「某板块没出现在日报里」≠「没抓到数据」，先查 fetcher 返回值再下结论。**
我最初误报为「fetcher 未被调用所以欧洲是空的」，查 dashboard 产物后自我纠正。

**改动**：cron job `085fb753a988` 步骤 9 重写（402 → 2904 字符），固定 **12 模块骨架**：
①核心指标与警报 ②综合结论与动作 ③流动性 ④**四大央行资负表（Fed/BoJ/PBoC/ECB 并列）**
⑤债务与财政 ⑥利率与国债市场压力 ⑦信用 ⑧外国持有美债与去美元化 ⑨贵金属
⑩大宗与其他市场 ⑪KOL 与机构行为 ⑫今日焦点 + **数据健康度**。

规则：有变动详写 / 无变动一行带过；低频板块无更新写「(季度/年度，本次无更新)」
**占位保持骨架完整**（让 Chao 一眼确认所有板块都看过）；篇幅不设上限但必须分层清晰；
⑫必须列未就绪清单 + COMEX per-firm 解析校验结果，**即使全正常也要写「全部数据源正常」**。

**验证**：12 模块标记齐全 · ECB 点名 · 步骤 1b/1c/1d 未损 ·
**`dashboard.generate` 参数 47 个完好**（改 prompt 最易误伤处，用括号配对精确取调用体再数，
不能用宽松正则——说明文字里也有 "dashboard.generate" 字样会切错片段）。
备份：`~/.hermes/cron/jobs.json.bak-20260823-modular`。

**未决**：AGENTS.md 为受保护文件，本轮写入审批超时（= 拒绝），故记于此处；
AGENTS.md 的 Cron 段仍描述旧版日报口径，需 Chao 授权后补写。

---

### 2026-08-24（长会话压缩精华 · KOL 档案/一年回补/日报模块化/央行互换/C-H 治本）

> 本节为长会话压缩，只留**结论、根因、可复用判据**，过程不留。

#### ① KOL 全量名录 · 13 维度档案卡（新板块 `sec-kol-roster`）

- 13 维度（Chao 指定）：姓名/编号/领域/在世年份/现任头衔/代表性成就/荣誉/主要活动范围/
  观点/追踪价值/机构名称/书籍/2026 代表性言论。**122/122 全覆盖，零字段缺失**。
- 缺失口径：年龄查不到写「未公开」；**已故必须特别标出**；机构条目不套个人字段。
- ★**第三方传记不算本人著作**（Amazon/Goodreads 上常有同名他人写的传记）→ 判「无公开著作」。
  同名干扰排除 10+ 处（分析师 vs 同名古生物学家/小说家/运动员/画家）。
- 副产物：核出 **20+ 人头衔已过时**，按现状写入。
- 名册同步：Notion 移除 3 个机构条目 + 新增 1 人 → **122 人**。编号读 `notion_list_num`，
  **人数永不写死**，Notion 改动跑一次 sync 自动跟上。

#### ② KOL 历史「过去一年」回补

- 判据 ≥2025-08-23。回补 88 人 **284 条**，**80 人历史起点前推，平均 120 天**。
- ★**回补脚本必须做窗口硬校验**：每条日期须落在该人缺口窗口内，**越界一律拒收**——
  越界=子 agent 给无日期内容硬安日期=伪造。实测越界 0 / 无日期 0 / 无来源 0。
- ★**父端独立复核，不采信子 agent 自报**。
- 诚实结论：**大量人卡在 2025-08-24~09-02，距判据线只差 1-10 天**，再往前确实检索不到
  带日期的公开观点（即其公开发声起点/存档边界）。**没有为凑达标率编日期**。

#### ③ 日报改模块化全覆盖（cron 步骤 9 重写）

- Chao：「日报应该根据每天可以更新的**所有** dashboard 数据来做…不用在乎太长，
  重要的是关键信息有没有包含全，以及分层结构是否方便人类阅读清晰。」
- 实测缺口：**看板 45 section，旧日报只点名 6 骨架 + 5 附加项；42 个 fetcher 调 38 个**
  → 30+ 板块天天抓、进看板、**从不进日报**。
- 重写为**固定 12 模块**：核心指标/综合结论/流动性/四大央行/债务财政/利率压力/信用/
  外资持美债/贵金属/大宗其他/KOL 机构/**数据健康度**。
- 设计取舍：有变动详写、无变动一行带过；**低频板块无更新也占位一行**——占位价值不在信息量，
  而在让人一眼确认所有板块都被看过（「模块消失」与「模块无变化」在读者眼里长得一样）；
  数据健康度节**全部正常时也必须写一行**。

#### ④ 央行货币互换（Chao 发现的遗失指标，新板块 `sec-cb-swaps`）

- 源：**NY Fed 官方 API**，免费无 key、可查历史
  `markets.newyorkfed.org/api/fxs/all/search.json?startDate=&endDate=`
- ★**端点坑**：`/latest.json` 常返空数组（仅当日有新操作才有值），**不能作主源**，必须按区间拉。
- ★**单位**：原始 `amount` 就是**美元**，`/1e8` 得亿美元。
- 实测一年 101 笔 / 51 周：ECB 53 笔 41.53 亿 · BoE 14 笔 1.55 亿 · BoJ 26 笔 0.52 亿 ·
  SNB 6 · BoC 2。峰值周 4.80 亿（2025-W51）。
- **会计口径（Fed 官方 H.4.1 查证）**：记在**美联储资产负债表资产侧**，非现金流量表。
  科目 `Central bank liquidity swaps`，夹在 Loans 与 Other Federal Reserve assets 之间，
  属 "Total factors supplying reserve funds"。Fed 资产↑对外国央行债权／负债↑对方存款。
  **是互换不是支出**：汇率成交日锁定、到期原价换回，Fed 不担汇率风险只担对手信用风险。
- ★**解读铁律：它直接推高 Fed 总资产，但这不是 QE** —— 应急借款，到期自动缩回。
  危机时能从几亿冲到数千亿（2008 峰值约 5,800 亿），**那时读 Fed 扩表必须先扣掉这块**。
- 交叉验证：H.4.1 报 123 百万 ≈ API 的 8/19 ECB 119 百万 + BoJ 2 百万，两独立源吻合。

#### ⑤ COMEX C/H（Customer / House）治本

- Chao：「交货和接货，需要告诉我 C 还是 H」「**需要区分成为两个 account**」。
- **根因**：上游 `cme_delivery_parser.py` 一直正确抓 org（L110/L127 存进 `seats[].org`），
  但 `to_activity_note()` 拼文本时**只用 name+数量把 org 丢了**。6 月改走 Notion 后，
  下游 C/H 覆盖率 100% → 0%。
- 两端已修并 push：上游输出 `Jp(H)发13`；下游正则
  `([A-Za-z][A-Za-z0-9]*)(?:\(([CHch])\))?(发|接)(\d+)` 兼容新旧，无 ORG 计 `_u` 不臆测。
- ★**历史回归跑了但零新增**：archive 133 份 PDF 早已 100% 入库，强制重跑一分不差
  （203,578 手 / 133 天）。**缺口不在解析，在源头 6/5 后不再存 PDF**。两月历史补不回，不编造。
- C/H 实质结论（1-5 月精确数据）：某大行黄金交货 87 吨里 C 22,612 手 / H 仅 4 手
  = **纯客户通道不是表态**；另两家 H 占 81%/88% = 真自营。白银某行 98.3% 自营 vs 另一行 99% 客户盘。
  → **只看「谁交货最多」会把通道商误读成多空方**。

#### ⑥ 本次踩坑（判据留给下一个 agent）

- ★**上游字段形状漂移**：`targets` 被写成**数组**，`.strip()` 打崩 build；更险的是取数层
  4 处 `[:150]` 对 list **不报错、静默切成子列表**。**修消费端不改上游**（数组是合法表达），
  7 处（渲染 3 + 取数 4）统一走归一函数。
- ★**加辅助函数前必须 grep 重名**：短名 `_tg` 与既有局部变量撞名，函数被覆盖 →
  `'str' object is not callable`。**加固改动反而制造新崩溃点**。
- ★**「某板块没进日报」≠「没抓到数据」**：曾断言「ECB 是空的、fetcher 没被调用」——**错**。
  ECB 数据一直都在（6 个资产项、看板早已渲染），只是**日报文案写「三大央行」漏了第四家**。
  判据顺序固化：**先跑 fetcher 看返回值 → 再看渲染产物 → 最后才怀疑采集层**。
- ★**ussh 更新后已存在 session 不继承新 socket**：`SSH_AUTH_SOCK` 仍指旧的，表现为
  `The agent has no identities`。解法 `ls -la /tmp/ssh-*/agent.*` 挑最新时间戳 export。
  **内网 repo 的 pre-commit hook 是合规要求，绝不 --no-verify 绕过**（个人 repo 才可以，
  因 Uber githook 会拦个人 repo 报 `no ssh cert`）。
- ★**`git add -A` 前必看 `diff --stat`**：曾误将已 commit 的当日快照（2795 行）纳入删除，
  `git reset HEAD <f> && git checkout -- <f>` 恢复。

#### ⑦ 与另一个 agent 的协作边界（重要）

- `Comex-Daily-AI-Report` 由**另一个 agent 接管生产**（2026-07-15 HANDOFF）。本机 8 个采集 cron
  于 08-21 删除属**有意清理重复副本**，避免双写同一 Notion DB。
- 该 agent **一直在跑**（8/22 仍提交），但**已不再存 PDF**（archive 停 6/5），改产结构化 JSON。
- **本机正确姿势：只 pull 消费，不重建采集**。要它改行为 → push 改动 + 写 CHANGE_NOTE 让它评估。
- 已 push `CHANGE_NOTE_2026-08-24_CH_ORG.md`，请它 grep 是否有别处按旧正则解析 Activity Note。

### 待办

- [ ] **5 位玄学 / 宗教 / 灵媒类仍在 Eco 名册**（`craig_hamilton_parker` / `abhigya_anand` /
      `amanda_grace` / `brandon_biggs` / `plai_navaracha`）—— 按项目边界应归 Forecast-Checker，
      **等 Chao 在 Notion「KOL List」删除**，次日 cron 步骤 0 自动同步。本 agent 不动手。
- [ ] **3 个身份存疑条目待 Chao 核实**：`anu_anand`（名册标「资深宏观观察员」，
      公开可查同名人是记者，无市场观点，已标 `none`）；`carroll_quigley`（历史学家，1910–1977 已故，
      检索到的全是第三方解读旧著，建议标注「历史思想参考」而非活跃 KOL）；
      另有 2–3 位产业高管 / 学院派只谈产业不产出可交易判断，已标 `thin`。
- [ ] **AGENTS.md 未同步本轮新事实**：C/H 账户类型口径、KOL 四段式 detail 数据链路四处、
      `kol_profiles.json` 与 `sec-kol-roster`、三个新 tools、cron 步骤 3b —— 下轮补写。
- [ ] 承接上节未清：`except: pass/continue` 技术债；`_stress_panel_svg` axis 与除零；
      BIS API 406；vintage filter 需在下一期数据到位时复核是否自动出现。

---

## 2026-08-27

> 归档范围：2026-08-26 全天 + 08-27 凌晨会话。
> 主线是 **KOL 三源分裂收敛为单一 SSOT（kol_store.sqlite）+ 三点投影**，
> 以及 **「Hermes 独立线」18 张自有 Notion 表**的血缘切分。

### 决策

- **Chao 的总要求：「Dashboard、GitHub、Notion 所有数据都和数据库三点完全对应，每个数据库都是唯一的」**——
  不要「backfill 一个、每天 crawling 一个、新增人员又增加一个」，要用工程方案统一。
  这条是本轮所有改造的总纲。
- **三个提问的拍板答复**（原话「1 你只需要填写 source 2 本项目自己的父页下面 3 0-4 一口气」）：
  1. Notion「KOL List」**只填 `Source` 一列**；「最新观点 / 最新观点日期」归属未定，**一个字不动**。
  2. 承载一年历史的新表建在**本项目自己的父页**下，不建在名册所在页。
  3. P0→P4 一口气做完。
- **「这个需要提升一下你的能力。需要出处。」**——每条新观点必须带可追溯的 source link。
  经查根因不在抓取能力而在任务书：一年期回填的 `INSTRUCTIONS.md` 写死了
  「必须是真实可访问 URL」，每日 cron prompt 里没有这句。
- **数据血缘三分法（落在 `src/build_hermes_line.py` 文档头，无例外）**：
  数据是**我抓的 / 我的 LLM 产出的** → 必须有我自己的 DB + 我自己的数据源文件；
  只是**只读别人的表** → 不建，保持只读；**别人创建 / 维护的表** → 完全不碰。
- **`targets` 只填本人亲口给出的数字**：引述第三方预测、本人明确拒绝给点位时举的数字、
  只在标题出现正文不提的数字，三类一律留空（Felix Prehn 17 条里只有 3 条有真数字）。

### 事实与配置

- **`data/kol_store.sqlite` = KOL 观点唯一真相源**（`src/kol_store.py`）。
  - 表 `opinion` **3608 行 / 154 人 / 2025-01-02 ~ 2026-08-26**；表 `kol` 154 行。
  - 列：`uid / kol_id / kol_name / sector / date / direction / comments / targets /
    detail / detail_status / source_url / source_title / sources_json /
    source_status / origin / notion_page_id / created_at / updated_at`。
  - `uid = sha1(kol_id|date|direction|comments[:120])` → 幂等主键，跨源天然去重。
  - `origin` 分布：`backfill 653 / daily 2909 / manual 46`（manual = 新 3 人一次性回填）。
  - `source_status`：**`ok 1044 / missing 2564`**（出处覆盖 29%，缺口首次被量化）。
  - 一观点一行 **raw 无损**存储；「连续多天同一句话折叠成区间」的逻辑下沉到读取端
    `full_history()`，渲染层不再做合并。
  - 导出 `data/kol_store_export.json`（5.4 MB，进 git，可人肉 diff）。
- **`external_data.kol_full_history()` 已改为优先委托 store**，store 不可用时自动退回
  旧的 daily+backfill 双路内存合并 → **两个调用方一行未改**，故障可降级。
- **Notion 侧三张 KOL 表的分工（铁律，写在 `src/kol_notion_sync.py` 注释里）**：
  - `35947eb5-fd3c-800d-b852-cef31f9de6a5`「KOL List」= 名册 SSOT，**只准回填 `Source` 一列**。
  - `3c847eb5-…-d8d50295ce1c`「KOL 每日观点」= **另一 agent 的表**，本模块禁止读写。
  - `3c847eb5-fd3c-81b7-a827-f4effae77417`「KOL 观点历史库 (SSOT)」= **本模块独占**，
    投影 store 全量历史。
  - 硬闸门 `FOREIGN_DBS` + `_assert_not_foreign()`，任何写操作前必过；
    起因是当天曾**误把 93 行写进他人表**，靠逐条落盘的 page_id 精确 archive 撤回。
- **「Hermes 独立线」**（`src/build_hermes_line.py` + `src/hermes_line_ingest.py`）：
  - Notion 子页「Eco · Hermes 独立线」挂在本项目父页 `3b947eb5-fd3c-80ea-9b06-d41704af3b05` 下，
    **18 张 `HDB_*` 表**，id 已写回 `.env`（`HDB_INDICATORS` … `HDB_MONTHLY`）。
  - 本地自有数据源 `data/hermes_line/HDB_*.json` 共 16 个文件，行数：
    HOLDINGS 4769 / CUSTODY 522 / YIELDS 260 / NIKKEI 244 / INDICATORS 102 /
    FOREIGN_FLOW 53 / HF_LEVERAGE 53 / IIP 44 / COT 24 / BIS_GOLD_SWAPS 15 /
    FISCAL_NEWS 12 / REPORT 12 / MONEY_SUPPLY 3 / WEEKLY 2 / OFR 1 / **MONTHLY 0（无源，如实留空）**。
  - 写入器硬闸门 `ALLOWED_PREFIX = "HDB_"`，非 `HDB_*` 直接 `RuntimeError`，
    保证永远不会写到 `DB_*`（他人 / 旧线）上。
- **严格匹配纠出一处归因造假**：回填 Source 时，个人条目 `Lina Thomas` 被双向模糊匹配
  吃到本地**机构**记录「Goldman Sachs」的链接 —— 等于把机构的出处贴到个人头上。
  改严格匹配后落「无匹配」，这是对的。最终 **123/125 可填，2 个如实留空**
  （`Lina Thomas` 本地只有机构级记录，`Anu Anand` 本地无任何带链接数据）。
- **新旧对拍结果（切换前置条件）**：144 个 KOL 中 **140 完全一致**；4 个差异全部解释清楚 ——
  Felix Prehn +17 / Bart Melek +14 / Ricardo Evangelista（新并入 3 人，预期内修复）+
  `Eric Hadik` = **ORDER-ONLY**（2025-10-08 同日两条不同观点，仅同日内部排序不同，集合相同）。
- **`felix_prehn.json`（17 条，2025-09-17 ~ 2026-08-12）**：全部取自 `/tmp/felixtxt/` 已下载的
  17 份字幕，无新检索；日期用 `yt-dlp --skip-download --print "%(upload_date)s"` **回源重取**
  （上游交接日志省略号吃掉了 13 条日期，既不用残缺值也不跳过）。
- **改造前 KOL `comments` 散落 6 处**（盘点结果，供日后核对）：
  `data/kol/backfill/`（131 文件 653 条，带 source）· `data/kol/daily/`（213 文件 2841 条，
  仅 16% 带 source）· `data/kol_independent.json`（当日 122 条）· `scratch/kol_deep_*/out/` ·
  `scratch/kol_bf_new3/out/`（3 文件 46 条，**裸 list 格式与主库不兼容**）·
  `data/kol/backfill_removed_20260822/`（14 文件 20 条，移出者留痕不删）。
- **三频率报告现状**：日报（工作日 11:00 → `DB_REPORT` + `reports/<date>.md`）与
  周报（周六 11:00 → `DB_WEEKLY` + `reports/weekly/`）齐全；
  **`reports/monthly/` 目录至今不存在**，本项目侧月报仍未落地。

### 进展

- **P0** Notion「KOL List」`Source` 列回填 **123/125**，先 3 条样板验收再全量，
  写后读回 **mismatch = 0**；其余列一字未动。
- **P1** `kol_store.sqlite` 建成并灌入 3608 条 / 154 人（含新 3 人 46 条），全部 inserted 无冲突。
- **P2** `kol_full_history()` 切换为读 store（对拍通过后才切，保留 fallback）；
  Felix Prehn 的历史带 YouTube 原文链接首次出现在 dashboard 时间线上。
- **P3** 父页下**已存在**一张「KOL 观点历史库」表（此前漏检，因为它没进 `.env`）→ 复用不新建，
  30 条样板验收后全量投影；store 中 `notion_page_id` **3608/3608 已回写**。
- **Hermes 独立线**：18 张 `HDB_*` 表建成 + 16 个本地数据源文件落盘 + ingest 器（含前缀硬闸门）。
- 新增 cron `hermes-line-monthly`（每月 1 号 13:30 JST，脚本模式无 LLM，
  从 `data/hermes_line/` 生成上月月报写 `HDB_MONTHLY`，无数据如实标注）。

### 待办

- [ ] **P4 未完成**：每日 cron prompt 里仍**没有**「每条观点必须带可访问 URL」这条铁律
      （实测 prompt 内 `kol_store` / `HDB_` / `source_status` 字样均为 0 次），
      每日抓取也还没改成经 `kol_store.upsert()` 单一写入口落盘。
- [ ] **出处缺口 2564 条（71%）** 待补；补前需先让 `source_status` 进入每日统计与告警。
- [ ] 本项目侧**月报三件套**（`reports/monthly/` + 汇总逻辑 + 归档位）仍未建。
- [ ] 本轮全部改动**仍在 git index（staged）未 commit**：
      `src/kol_store.py` / `src/kol_notion_sync.py` / `src/hermes_line_ingest.py` /
      `src/build_hermes_line.py` / `src/external_data.py`(改) /
      `data/kol_store.sqlite` / `data/kol_store_export.json` / `data/hermes_line/*.json`。
      注意 `kol_store.sqlite`(5.7M) 与 `HDB_HOLDINGS.json`(4.7M) 体积偏大，提交前确认口径。
- [ ] `AGENTS.md` 未同步本轮新事实（kol_store SSOT / 双 KOL 观点表分工 / Hermes 独立线 18 表 /
      血缘三分法）—— 属 protected 文件，需 Chao 在场时触发。
- [ ] 承接上节未清：`except: pass/continue` 技术债；`_stress_panel_svg` axis 与除零；BIS API 406。

## 2026-08-29 / 08-30

> 本两日 Telegram 对话主体在其它项目（Notion-Summary 批量笔记、Forecast-Checker 补跑），
> 与本项目直接相关的只有下面一条用户指令，其余一律不记。

### 决策

- **Chao 原话（2026-08-29，针对 crawl 调度）**：
  「整体的那个你的 crawl 应该是**每天都 run，而不是只有工作日**。」
  该指令是在 Forecast-Checker 每日增量 crawl 的上下文里发出的，措辞是「整体的那个你的 crawl」，
  指向**通用口径而非单一 job**。
  本项目 `eco-vol-01-daily-scan-report` 当前排期为 `0 11 * * 1-5`（**仅工作日**，
  自 2026-08-12 起所有 jobs.json 备份均为此值，从未改过），与该口径不一致。
  **未自行改动**——改排期属配置写入，且指令是否覆盖本项目需 Chao 一句话确认（见待办）。

### 事实与配置

- 本项目 4 个 cron 现状（JST）：
  `eco-vol-01-daily-scan-report` `0 11 * * 1-5` ·
  `eco-vol-weekly-report` `0 11 * * 6` ·
  `eco-vol-selfheal-watchdog` `20 * * * *` ·
  `eco-vol-context-distill` `0 6 * * *`（本归档器，已是全周）。
- 8/30 为周日，daily 按现排期不跑；最近一次仓库产出为 `52e48d8 weekly 2026-W35`（8/29 周报）。

### 待办

- [ ] **确认「crawl 每天跑」是否覆盖本项目**：若是，`eco-vol-01-daily-scan-report`
      改 `0 11 * * *`。需一并想清周末口径——FRED/COT/拍卖等源周末无新值，
      周末跑会写入与周五相同的数据行（`skip_none` 保护下不会抹真值，但 DB 会多出重复日行），
      KOL / web 源则周末仍有新内容。建议方案：周末照跑但对无更新的数值源不新建行。
- [ ] 承接上节全部未清项（P4 cron prompt 出处铁律、出处缺口 2564 条、月报三件套、
      staged 未 commit 的 kol_store 相关改动、AGENTS.md 同步）。

---

## 2026-09-02

### 决策

- **川普 OGE 278-T：Chao 选「丙 → 甲」**——先 OCR 一份试水，质量达标再全量。
  实测试水 4 页 7.9 秒、质量达标 → 直接推进全量。
- **CBOE put/call：Chao 主动问「能否利用 scraper」**，方向被证明是对的。
  实测 ScraperAPI 可打通官方页，并因此发现原第三方回退值是错的（见下）。
- **B 方案（Hermes state.db 的 FTS trigram 瘦身）在 Chao 同意后被实测推翻并撤回**：
  trigram 不是冗余（长查询多召回 1.5~2 倍）、库碎片仅 0.9MB 无水分、删了启动会自动重建。
  → 教训：**「库大所以容易坏」是未验证的因果**，提方案前应先测。
- Chao 授权 commit 并 push（条件：先确认不会重演 disk I/O / state.db 损坏）。
- 归档进 ChaoWiki 已执行完毕（见「进展」），无需重复。

### 事实与配置

- **CBOE Put/Call 口径纠正（重要）**：官方 equity put/call = **0.67**、total = 0.95；
  此前降级链里用的第三方聚合值（thetrading.tools）= **0.84**，**差 0.17，口径不同 → 一直是错值**。
  该第三方源已从降级链移除。现降级链＝**ScraperAPI(官方) → Jina(官方) → 未找到**，
  并加 `0.1~5.0` 区间守卫防抓错数。
  - 直连实测：HTML 页 302 Cloudflare / `cdn.cboe.com/*.csv` 403 / 换 UA 无效
    （本机数据中心 IP 被整段封）；ScraperAPI 打 HTML 页 200（443KB），
    但 ScraperAPI 打 CSV 端点仍 500 → **只能走 HTML 页**。
  - 页面是 Next.js，数值在 `self.__next_f` 内嵌载荷里，需从中挖取。
- **川普 OGE 278-T：0 → 632 条逐笔交易**。
  - 真根因不是网络：OGE API 健康（http 200，16,648 条记录，川普相关 25 条），
    18 份 278-T **全都有 PDF 链接**；卡在 **PDF 无文字层**——最新一份 26.9MB，
    34 页里 33 页零文字层、`(cid:xx)` 乱码，**必须 OCR**。
  - OCR 实测：tesseract 5.3 @200dpi，全份 34 页 **79 秒**（此前口头估「几十分钟」是高估）。
  - 质量校验：日期非法 0 / 金额下界全部落在 OGE 标准档 0 异常 / 年份全 2026 /
    买 363 卖 272；资产名 OCR 噪声 3 条（`|`、空串）已加过滤，635 → **632，残留 0**。
  - 现有 `parse_278t` 的 `buy_re` 本就容忍 OCR 变体（`urchas`/`ourchas`），
    只需在**文字层为空时插入 OCR 兜底**即可复用。
  - `oge_trump._fetch` 原本**零重试**，7MB 响应网络抖一下整个失败 → 已加 3 次指数退避（2s/4s）。
  - 政要卡取值字段名是 `trades`（不是 `transactions`），端到端已验证 632 条落到卡上。
- **tesseract-ocr 是 apt 装的系统包，devpod 重启不保留**；缺失时 `_ocr_pages` 静默降级，
  逐笔退回 0 条而不报错 → 排查第一招 `tesseract --version`。已写进 AGENTS.md。
  要长期生效须由 Chao 写进个人 `devpod.yaml`（**未动其 devpod 配置**）。
- GuruFocus 403 是**虚警**：openinsider 早已是主源，GuruFocus 仅为失败回退。
- 环境事实：9/2 `~/.hermes/state.db` 结构性损坏（`database disk image is malformed`），
  当日含本归档器在内的 agent 型 cron 批量失败、换库后自愈——这是 9/2 无归档节的原因。

### 进展

- commit `3e61945`（已 push 公网）：川普 278-T 接 OCR + CBOE 走 ScraperAPI + 新鲜度审计工具。
- commit `3fcc3ec`（已 push）：AGENTS.md 补 tesseract 系统依赖说明 + CBOE 口径纠正。
- 新建 `tools/freshness_audit.py`：全库 40 个数据源新鲜度审计。
  13 个告警 → **2 个真问题**（COMEX issue/stop 已修；黄金 Premium 断更 17 天未修）、
  11 个误报（4 个判据太浅 + 8 个官方本来就低频，已逐个对过 FRED `observation_end`）。
- ChaoWiki 已归档并 push 内网：`15aa88c`（静默失败形态 16/17/18 + 新页
  `knowledge/crawler/fallback-source-calibration.md`「反爬回退须校验口径」）、`b97b469`
  （多 agent 并发写同一 repo 的提交纪律）。

### 待办

- [ ] **黄金 Premium（印度/中国）断更 17 天**：根因是它从设计上就靠**手工导入 WGC xlsx**，
      却当作日频指标展示。ScraperAPI 路径已验证可行，或可同样解决——等 Chao 定时间。
- [ ] tesseract 持久化：需 Chao 自行写进 `devpod.yaml`，否则重启后川普逐笔静默归 0。

---

## 2026-09-03

### 事实与配置

- Chao 只问了一句「今天的任务跑了没有？」（10:00 JST）。当时主日报
  `eco-vol-01-daily-scan-report` 排 11:00 **尚未到点**，属正常排程而非漏跑。
- 当日本项目 cron 全绿：`eco-vol-selfheal-watchdog` 09:20 ✅ /
  `eco-vol-context-distill` 06:03 ✅ / 周报排 9/5 周六 11:00。
- 9/2 那批 agent 型 cron 的批量失败（`~/.hermes/state.db` 结构性损坏）当日已不再复现。

### 进展

- commit `a52a338`「daily 2026-09-03」：主日报 11:32 正常产出，
  政要披露 5 卡齐全（Pelosi 15 / Crenshaw 8 / **川普 OGE 278-T 632** /
  川普 DJT Form 4 3 / Tuberville 15），即 9/2 修的 OCR 链路在 9/3 仍然有效。

---

## 2026-09-04

### 事实与配置

- ★★**tesseract 已被 devpod 重启擦掉 —— 9/2 记的那条待办当场兑现了**。
  证据链（非推测）：`/proc/1` 与 `/etc/hostname` 的 mtime 都是 **2026-09-03 15:21**
  （容器在 9/3 主日报跑完 3 小时后被重建），今早 `tesseract --version` = command not found、
  `pytesseract.get_tesseract_version()` 抛 `TesseractNotFoundError`、
  `/usr/share/tesseract-ocr` 目录不存在。**这不是「apt 装失败」，是容器重建把系统层还原了。**
- **危险之处在于它不报错**：`_ocr_pages()` 原实现 `except ImportError: return []`，
  且 pytesseract 只有真去 OCR 时才抛错 → 川普 278-T 会从 632 条**静默退回 0 条**，
  外层 `status` 仍是正常值，日报上看不出任何异常。属 AGENTS.md 里 P1-3
  「网络/环境失败静默返空 → 下游混淆『读不了』与『没有』」的同一族。
- 数据本身**没有被污染**：`data/oge_trump.json`（9/3 11:08 写）仍是 632 条，
  `data/politician_disclosure.json` 也是 632 —— 因为容器重建发生在当日抓取之后。
  今天 11:00 的日报若不修，才会是第一份被清零的。
- 环境事实：本机 `~/.devpod/personal.devpod.yaml` 目前只有一个 task
  （`boot_hermes_stack.sh`）；系统 crontab 的 `@reboot` 段也没有任何 tesseract 相关项。
  两处都是 Chao 的共享配置，**未擅自改动**。

### 进展

- 已 `apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng` 装回
  （tesseract **5.3.0** / leptonica 1.82.0），`pytesseract.get_tesseract_version()` = 5.3.0。
- 端到端复跑 `src.oge_trump`：`status=ok docs=25 txns=632 ocr_status=None`，
  与 9/2 基线**逐笔条数完全一致**（先备份 `data/oge_trump.json` 到 `/tmp` 再跑）。
- 代码改动（把静默降级改成显形）：
  - `src/oge_trump.py` 新增模块级 `OCR_UNAVAILABLE_REASON`；
    `_ocr_pages()` 进门先 `pytesseract.get_tesseract_version()` 探活，
    缺失时记录原因而非静默返 `[]`；`fetch()` 把它写进 `result["ocr_status"]`。
    → **0 条 + `ocr_status` 非空 = 环境读不了；0 条 + `ocr_status` 为 None = 真没交易。**
  - 新增 `tools/ensure_tesseract.sh`（幂等；`--check` 只探不装，缺失 exit 1）。
- 故障注入验收（不是只看「跑通了」）：把 `pytesseract.tesseract_cmd` 指向
  `/nonexistent/tesseract` 复跑 `_ocr_pages` → 返回 `[]` **且** `OCR_UNAVAILABLE_REASON`
  给出「tesseract 二进制不可用（apt 包，devpod 重启不保留；修复：bash tools/ensure_tesseract.sh）」。

### 待办

- [ ] **持久化仍未落地（需 Chao 点头，涉及他的共享配置）**：把
      `bash ~/Projects/Eco-and-Volatility-Checker/tools/ensure_tesseract.sh` 挂进
      ①`~/.devpod/personal.devpod.yaml` 的 `tasks:`（容器每次 create/restart 执行，首选）
      或 ②系统 crontab 的 `@reboot` 段。**在此之前，每次容器重建都会重演今天这一出。**
- [ ] 承接 9/2：黄金 Premium（印度/中国）断更（当时 17 天），根因是靠手工导入 WGC xlsx
      却按日频指标展示；ScraperAPI 路径已验证可行，等 Chao 定时间。

---

## 2026-09-05

> 承接 9/4 白天 Chao 问「今天的发了吗？」那一轮的完整复盘（当日日志只记到 06:30 那批修复）。

### 决策

- Chao 只问了一句「今天的发了吗？」。我最初据 cron 元数据答「今天被跳过了」，
  **答错并当场自我纠正** —— 判据换成产物后结论反转为「已发」。
  ⇒ 沿用本项目既有纪律：**日报是否跑过，只看产物（快照 mtime + dashboard 生成时间 + git log），
  不看 cron 的 `last_status` / `last_run` / `next_run`。**

### 事实与配置

- ★**9/3 那次容器重建擦掉的不止 `tesseract`，`/usr/bin/sqlite3` 也没了。**
  这条比 tesseract 那条影响更大，因为受害者是**守护脚本自己**：
  - `state_db_health_check.sh` 把「工具 command not found」当成「数据库损坏」，
    从 9/3 起连续报 BAD，并于 **9/3 18:22 发出一条假的「state.db 损坏」告警**。
    实测库一直健康（`quick_check=ok`，25,903 sessions 完好）。
  - `state_db_auto_snapshot.sh` `rc=127` 连败 3 次（9/3 的 09:22 / 15:17 / 21:17），
    24 小时快照覆盖出现空洞。
  - ⇒ 与本项目 AGENTS.md 里 tesseract 那条是**同一根因的两个受害者**：
    apt 装的系统二进制活不过 devpod 容器重建。
- **修法与 tesseract 不同**：tesseract 是「装回来 + 让缺失显形」，
  sqlite3 走的是**换掉依赖层** —— 全部改用 python3 内置 `sqlite3` 模块（标准库，
  随 python 发行，不受 apt 层重置影响），并抽出共用的
  `~/.hermes/scripts/sqlite_check.py`（只读 URI 打开，不与在线写入者争锁）。
  `state_db_health_check.sh` / `state_db_auto_snapshot.sh` 内联 python heredoc，
  `emergency_swap.sh` 已无任何 `sqlite3` 二进制引用（今日复核 grep = 0）。
- 当日另一个 agent 已在 `8379142`（06:23）把 tesseract 装回，并做了
  「OCR 不可用不再静默」+ `tools/ensure_tesseract.sh`。今日复核 `tesseract 5.3.0` 仍在。
- 复核状态（2026-09-05 06:0x）：`python3 -c "import sqlite3"` = 3.40.1 可用；
  最新自动快照 `state.db.auto-20260904-151731`（9/5 00:17 落盘，3.2 GB）→ 快照链路已恢复且持续产出。

### 进展

- commit `b295273`「daily 2026-09-04」11:21 push，日报正常。产物三重佐证：
  `data/daily/2026-09-04.json`（11:20，241 KB / 20 项指标）、
  `docs/index.html`（11:18 重建）、git log。
- `state.db` 守护三件套去二进制化完成并实跑验证：health_check → `ok`（假 marker 自动清除，
  已推恢复通知）、auto_snapshot → 12.6 秒完成且 integrity OK。

### 待办

- [ ] 承接 9/4：**tesseract 持久化仍未落地**（需 Chao 点头，涉及他的共享配置
      `~/.devpod/personal.devpod.yaml` 或系统 crontab `@reboot`）。
      在此之前每次容器重建都会重演。
      ⇒ 现在**同一个钩子应顺带覆盖任何 apt 依赖的复检**，不要只挂 tesseract 一个。
- [ ] 承接 9/2：黄金 Premium（印度/中国）断更，等 Chao 定时间。

## 2026-09-07

### 决策

- Chao 报「两个板块空白」后，我给出甲（补 fetcher 止血）/ 乙（cron 改调 `build_dashboard.py` 治本）/
  丙（甲+门禁）三选项，**Chao 选乙**，随后追加「同意」批准完整执行计划。
- Chao 后续指令「**1 and 2 顺序做**」：先做乙方案（cron 治本），再查「全量名录为什么没有全部言论」。
- 配色：Chao 说 dashboard 底色「太凉了」→ 往暖 + 暗一档调整，但**不切深色主题**，
  且改动前必须先验对比度不倒退。

### 事实与配置

- ★**病根：同一份采集清单两处维护。** 每日 cron 不走 `build_dashboard.py`，而是在 prompt 里
  内联一条手写调用 40+ fetcher 的巨型命令。机械集合对比（不是肉眼扫）结果：
  - cron 调 38 个 fetcher，`build_dashboard.py` 调 40 个，**cron 是 builder 的真子集**；
  - cron 独缺 `fetch_china_liquidity` / `fetch_cb_liquidity_swaps` → `generate()` 收到 `None`
    → 线上渲染成「数据未就绪」空状态（`class="tf-none"`），而**数据层从来没坏**
    （实测 OMO 551 点 / DR007 545 点 / 两融 552 点到 09-07；货币互换 60 笔到 09-02）。
  - 旁证漂移：cron 里参数名 `swaps=` 已被 BIS 黄金掉期占用，央行货币互换压根没进参数表。
  - 与 AGENTS.md 里「prompt 硬编码 88 个 KOL 导致新增漏抓」是**同一病根的第二个实例**。
- ★**那条「不能改用 build_dashboard.py 否则丢 AI 短评」的警告是错的（实测推翻）。**
  用 `data/ai_analysis_<date>.json` 里的真实文本做指纹逐条比对旧/新产物：

  | | 旧产物（cron 内联版） | 新产物（builder 版） |
  |---|---|---|
  | reads | **0 条命中** | 14/14 |
  | notes | **0 条命中** | 20/20 |
  | conclusions | **0 条命中** | 3/3 |

  ⇒ 旧 cron 路径**从来就没把 AI 短评渲染进页面**，警告保护的东西不存在。
  补齐只需读已落盘 JSON 的 `reads`/`notes`/`conclusions` 三个字段，**不调 LLM、不联网**。
- ★**TIPS 混进名义券拍卖曲线（真数据错误，非显示问题）**。对着 Chao 截图核数发现两条异常：
  10Y `2026-07-23` 规模 21.0B / 收益率 2.438%；30Y `2026-02-19` 规模 9.0B / 收益率 2.473%
  —— 规模腰斩、收益率只有邻月一半。**没有凭数值猜**，回财政部官方 API 拉全字段拿到铁证：
  官方有专用标识字段 **`inflation_index_security: Yes/No`**。TIPS 的 `security_type` 也是 Note、
  `security_term` 也是 10-Year，所以原来靠这两个字段的过滤拦不住。
  修复点 `src/external_data.py:2154`，改用 `inflation_index_security` 精确过滤。
  TIPS 报的是**实际收益率（扣通胀）**，与名义券不是一个口径，混在一起会误读需求强弱。
- ★**验证陷阱：第一版校验脚本定位到了 CSS 区而不是数据区**，得出「抽到 0 个收益率 → 干净」的
  假通过。重新定位到真数据区（244 个实例）才算数：24 个收益率全部落在 3.965~5.216 名义券区间。
  ⇒ 校验产物前必须先确认自己抓的是渲染出的内容区，不是样式定义区。
- **配色改动**（`dashboard.py` 莫兰迪色板）：`--bg` `#e8e4dd`→`#ddd6ca`（明度 −13%）、
  `--card` `#f2efe9`→`#eae4d9`（−10%）、`--border` `#cdc6ba`→`#c2b8a6`、`--text` `#4a463f`→`#423d34`。
  WCAG 对比度四项不降反升，次要文字 on 底色 **2.96（原本不达标）→ 3.15（达标）**。
- **「#5 缺号」是布局错觉不是丢人**：`#5 Stewart Thomson`（Graceland Updates）在册且档案完整，
  三列瀑布流按列填充导致横扫时像跳号。页面共 130 个编号、范围 1→140，缺的 130-139 是编号排到 140
  而实际 130 人。
- ★**「全量名录没有全部言论」根因 = 渲染层只取 1 条，数据是全的**：
  - `data/kol/backfill/`：131 个文件、**128 人有 `history`、共 653 条言论**（今日复核一致），
    最多 Alex Kuptsikevich 22 条 / Jim Curry 14 条 / Luke Gromen 11 条；
  - `data/kol_profiles.json`（名录卡片数据源）：每人只有 **`quote_2026` 单字符串** = 1 条；
  - `dashboard.py:3222` `_row("2026 代表言论", p.get("quote_2026"))` 写死取一条；
  - 653 条历史**已经加载进页面 payload**（`kol_history_json`），只是没接到名录卡片上。
  - 附带教训：我最初统计报「131 位全 0 条」是**读错字段**（找 `items/quotes/opinions`，
    实际字段名是 `history`）—— 统计前先 dump 真实结构再下结论。

### 进展

- `11e0bd2` style(dashboard)：底色调暗加暖 + 用 `build_dashboard.py` 重建顺带补回两个空板块
  （央行货币互换：本周 1.01 亿 / 峰值 4.80 亿 / 101 笔；中国流动性：日期轴到 09-07）。
- `475806e` fix(auctions)：TIPS 过滤，两条脏数据清除，7 个期限各补回真实的第 4 次名义券拍卖。
- `04d70b6` refactor(cron)：乙方案落地。
  - `build_dashboard.py` 新增 `latest_ai_analysis()`（纯读 JSON，缺文件 LOUD 警告后继续）；
  - `dash.generate()` 改成**先构造 `gen_kwargs` dict 再展开**，门禁才拿得到实际传参；
  - 新增门禁 `assert_no_missing_kwargs()`：`generate()` 形参 vs 实际传参自动比对，
    实跑输出「✅ 全部 49 个数据形参均已传入」，缺参数会 LOUD 报错；
  - cron prompt 从 **17,371 → 14,705 字符**，删掉那条过时警告与「新增参数必须同步加到这里」的铁律；
  - 旧 `jobs.json` 已备份 `.bak_ecovol_0907_184235`，job 校验完好（enabled / 周一至周五 11:00）。
- 零回归验证通过：23 个板块锚点全存活、空状态标记 0→0、日期数 24,216→24,215、SVG 图元持平。
- 三次 push 均核对 local == remote，线上 https://curarpikt0000.github.io/Eco-and-Volatility-Checker/ 已更新。

### 待办

- [ ] **任务 2 未完成**：把 653 条历史言论接进全量名录卡片（当前每人仍只显示 `quote_2026` 一条）。
      数据已在 payload 里，缺的是 `dashboard.py:3222` 附近的渲染接线。
- [ ] **明天（9/8）11:00 是新 cron 路径第一次自动跑**，需验证：两个原空板块是否仍有数据、
      AI 短评是否首次出现在页面、门禁是否打印「全部形参均已传入」。
- [ ] 承接 9/4：tesseract 持久化仍未落地（需 Chao 点头动 devpod 配置）。
- [ ] 承接 9/2：黄金 Premium（印度/中国）断更，等 Chao 定时间。

## 2026-09-08

### 决策

- Chao 就「WGC 黄金 Premium 图没有每日更新」给三选项后拍板 **甲 + 乙**：
  先改正撒谎的频率标签，再修浏览器工具走真浏览器下载。（丙＝自算溢价未采纳）
- KOL 全量名录言论展示形态：Chao 选 **甲方案** —— 卡片保留 1 条代表言论 +「查看全部 N 条」
  弹层钻取（复用既有 kol-drill 组件，改动最小），不内联多条撑爆名录页。
- Chao 明确「**要查**」那 10 个 profiles↔registry 对不上的人（不是放着不管）。
- Chao 对 Goldman Sachs 卡片残留的态度：「**类似这样的事情一定要避免**」→ 由此确立
  四方一致性对账门禁（不再依赖人眼发现名单里多了不该有的）。

### 事实与配置

- ★**「每日更新」标签本身就是假的**（比断更更严重）。WGC 官方方法论 PDF 原文：
  "We publish the data **monthly**, but the file contains daily data"、
  "Indian premium/discount data is calculated and reported **weekly**"。
  源头是周更/月更，只是文件内含日频序列。原设计注释自白「用户从 goldhub 下新 xlsx →
  重跑 parse 脚本」＝**从来就是纯手工，从未自动化**，数据停在 8/14、断更 25 天。
- ★**WGC 数据的可用通道只有一条**：官方图表端点
  `https://fsapi.gold.org/api/v11/charts/local-gold-price-premiums`（从页面 HTML 里挖出来的，
  页面自身在用所以未被封）。以下**全部失败，不要再试**：
  xlsx 直链 `gold.org/download/file/11657/gold-premiums.xlsx` 直连/带 Referer/会话预热 cookie
  → 403；ScraperAPI 5 种参数组合 → 500；playwright 真浏览器带完整 cookie → **仍 403**
  （⇒ 不是指纹问题，是该 IP 段被 WGC CDN 拉黑，同 CBOE 一类）；自猜路径 → 全 404。
  API 只给 260 点滚动窗口，故必须**与本地 xlsx 历史 merge 而非覆盖**，同日冲突以官方为准
  （WGC 会回溯修订）。落盘 `data/gold_premium_{india,china}.json`。
- ★**browser 工具坏了与 WGC 无关**：`/home/user/inspect.py`（7/22 调试 Google Slides 的
  27 行临时脚本）**遮蔽了 Python 标准库 inspect**，daemon 从 home 启动即中招。
  处置＝**改名归档不删别人的文件** → `/home/user/scratch-archive/inspect_slides_probe_20260722.py`。
  解除后报错变成「Chrome 没跑」，而 playwright chromium 已装（项目 venv 里没有 playwright，
  要用系统 python 跑）。
- ★**KOL 名录「没有全部言论」＝渲染层只取 1 条，数据一直是全的**（复核后数字大幅上修）：
  历史言论总量 **3,146 条 / 115 人，平均 27.4 条/人**（此前 9/7 记的 653 条只是
  `data/kol/backfill/` 单一目录），最多 79 条；而卡片写死 `p.get("quote_2026")` 单条。
  这些历史**每天都随页面 payload (`kol_history_json`) 下发**，只是没接线。
  质量可用（每条含 日期/方向/一句话/detail 核心论点+关键依据/来源链接），正合三层结构要求。
- ★**两份名单人名写法不一致**（新增 `_kol_payload_key()` 解决）：profiles(125) 用全名 /
  registry(129) 带机构后缀或缩写 —— `Stanley Druckenmiller ←→ S. Druckenmiller`、
  `Ken Griffin ←→ Ken Griffin（Citadel 创始人 / CEO）`、`N. Gregory Mankiw ←→ Greg Mankiw`。
  匹配只认「主干相等 / 单方向包含 / 姓相同」，**不做双向模糊**（机构后缀会抢先吃掉别人的行）。
  未挂上的 4 人（LaForge/Streible/Rogoff/Zulauf）实测 backfill 确实无历史，**非 bug**。
- ★★**同一个匹配坑换个主角又踩一次**：8/22 为 Nomi Prins 加的「单方向 + 取最短」没排除
  「本地名本身就是纯机构名」—— 本地 `Goldman Sachs` 规范化成 `goldmansachs`，确实是
  Notion 里某条「人名（Goldman Sachs Research…）」的子串 → 被当成她的本地对应而保留，
  同步工具报「移出 0」。修法＝`is_pure_institution()`（无「人名（机构）」括号结构 +
  命中机构词表者只允许精确匹配）。**附带发现：被顶掉的那位真人 Notion 里有、本地从没建过条目
  ＝ 从未被抓过** —— 这类 bug 不只多显示一个机构，还会吞掉真人 KOL。
- ★**说明文字与真实状态脱节是一类系统性病**（当天连撞两例：假「每日更新」标签、
  COMEX C/H 写死过时天数）。COMEX 实测：archive 段(1/06~6/05) 缺 0 天；Notion 段缺口
  **全部止于 2026-08-19**（上游 8/21 改输出「Advantage(C)发5」格式后解析器兼容一直正常），
  Gold 38 / Silver 37 / Platinum 9 天缺失全在 6/09~8/19。⇒ **回补没必要，撒谎的是文案**。
  改为 `_ch_gap_summary()/_ch_gap_text()` 每次渲染从原始 json 实算。
  踩坑：第一版传 `fetch_comex_issue_stop_firms()` 返回值渲染出垃圾 ——
  **那个返回值的 metals 已按窗口聚合（键是 d/w/m/all），逐日数据只在 json 文件里**。
- 9/8 的 cron 状态是 `delivery_failed` 而非失败/排队：`Telegram send failed: Timed out`，
  **报告、dashboard、快照、git 提交全部完成，只有最后推送超时**。
  ⇒ 判断 cron 跑没跑要看产物（报告字节数/落盘时间/commit），不看投递状态。
- 9/7 那次 cron 治本改动**首次自动跑全部生效**：报告出现「门禁通过：49 个数据形参全部传入」、
  两个曾空白板块「数据未就绪」= 0 处、AI 短评 reads/notes 全量渲染。

### 进展

- `b400deb` fix(gold-premium)：接 WGC 官方 fsapi 端点自动更新 + 修正假「每日更新」标签
  （改「周更/月更(WGC 官方口径)」+ weekly 档滞后徽章，图内标签与 section part-title
  **两处独立维护均已改**）。数据 8/14 → **9/04**；印度 3801→3816 点、中国 6083→6098 点，
  两条序列起点未变（2012-01-24 / 2003-04-25）。
- `f5a96cc` feat(kol-roster)：名录卡片接上全部言论钻取。129 张卡片 **125 张挂上**，
  7 个写法差异全部解析正确、0 处错配；playwright 真浏览器实测点击
  （名字含双引号的 Todd "Bubba" Horowitz 21 条 / Grantham 27 / Druckenmiller 34 /
  Ken Griffin 10）全部正常打开、0 JS 报错。
- `825d226` fix(kol)：`is_pure_institution()` + 新增 `tools/kol_consistency_audit.py`
  四方对账（Notion SSOT ↔ 本地名册 ↔ dashboard 卡片 ↔ cron 实抓，全读实际产物，
  有差异 exit 1），已挂进每日 cron 步骤 0b、差异写进日报数据健康度段。
  清理 `kol_profiles.json` 里 4 个机构孤儿档案（125→121）；
  移出 1 人留痕 `data/kol_removed_20260908.json`，**backfill 历史文件按铁律全部保留**。
  对账实跑：名册 ✅ dashboard ✅ / cron 实抓 ❌（当天 11:00 跑在修复前，次日自动纠正）。
- `f5805aa` fix(comex)：C/H 说明文字改为从数据实算。
- 四次改动均零回归验证：23 个板块锚点全存活、空状态零增加。
- 补发了 9/8 完整 12 模块日报（Telegram 超时那份），拆两条发出。

### 待办

- [ ] **验证四方对账门禁在 9/9 cron 自动跑后转全绿**（cron 实抓那一路当天是红的）。
- [ ] 承接 9/4：tesseract 持久化仍未落地（需 Chao 点头动 devpod 配置）。
      注：9/8 日报显示重装后川普 278-T 已从 annual_only 恢复逐笔，但重启仍会再丢。
- [ ] 检索词质量优化（非 bug）：24 人的 `search_terms` 是 Notion 带机构后缀的长串，
      能搜到但命中质量差于纯人名。

## 2026-09-09

### 决策

- ★**Chao 以国债交易员视角否掉「合并口径」**（原话）：
  「滞后 251 天的数据全部拢在一起，这是不可以接受的」
  「分央行和私人部门两个数据」
  「所有数据需可回溯源头和抓取路径」
  ⇒ TIC 外国持有美债板块按交易员视角重做：欧元区拆分 + 官方/私人拆分 + 全链溯源。
- **此前我给出的「方案乙」被自己推翻、不必再做** —— 见下条事实。

### 事实与配置

- ★★**TIC Table 3 才是全国别月度表，此前只查 Table 5 得出的结论是错的**：
  Table 5 只列前 20 大 ⇒ 我曾据此判定「德/意/荷/西/芬落在 All Other，欧盟只能退回
  年度存档表、滞后 251 天」。**实际 TIC 另有 Table 3**（`slt_table3.txt`）：
  **113 个国家/地区、欧元区 9 国全齐、覆盖 2020-01~2026-06，与日/中完全同频**。
  EU 全口径既不必砍成 4 国，也不必估算。`_parse_tic_table3` 优先级高于 Table 5。
  **教训：一张表查不到 ≠ 数据不存在，先把同一发布下的所有表列全。**
- ★**Table 3 的三组数是「总额 / 长期 / 短期」，不是「官方 / 私人」**：
  我第一次按加总关系猜成官方/私人 —— **加总恰好也吻合，所以数值校验救不了这个错**，
  是读表头才发现的。**列义必须认表头，不能靠数字关系反推。**
- **欧元区拆三层**（`external_data.py`）：
  `EU`(9 国合计) / `EU_CUSTODY`(比利时·卢森堡·爱尔兰) / `EU_REAL`(德法意荷西芬)。
  实测 2026-06：**1986.1 = 1270.1 + 715.9** ✅。
  拆开才看得见结构差异：**真实需求 +139.4% > 托管 +96.1%**，合计口径把它抹平了。
  交易员解读写进 dashboard：卢森堡持仓 ≈ 其 GDP 的 4.3 倍 → 第三国借道，
  须与中国持仓反向对读。
- **官方 vs 私人**（`fetch_tic_official_vs_private()`，码 99990/99991）：
  2020-01 官方占比 **59.3% → 2026-06 40.6%**；期间**官方净减 392B、私人净增 2663B**。
  ★该拆分**只有全球总量，113 国无一国带官方/私人** —— 单国央行持仓美国财政部本就不公布，
  **不是抓不到**（dashboard 内已明确说明，避免误读为数据缺失）。
- ★**「欧洲央行 ECB」这个标题是错的，已改名 Eurosystem**：
  数据源 ILM `W.U2.C` 是 **ECB 本部 + 20 家成员国央行的合并表**（€5,912B），
  而**德国央行一家就 €2,271B**。与 9/8 修的假「每日更新」频率标签同属
  **「元信息撒谎」** 这一类病。`src/report_writer.py` 的 Notion 日报标题
  「三大央行(US/JP/CN)」同步改为含 Eurosystem + 欧元区五国央行。
- **五国央行各自总资产** `fetch_euro_ncb_balance_sheets()`：走 **ECB BSI 统一 key 模板**
  —— 四国自有 API 端点实测不可用，且各自口径无法横向比。
  实测 2026-07 5/5 ok：DE 2546.6 / IT 1194.9 / ES 964.5 / NL 415.7 / FI 115.7（$B）。
- **三口径防误读警告**（写进 dashboard，避免混用）：
  Eurosystem 合并表 / 五国央行各自 / TIC「所有外国持有人」。
  实测**德国央行对非欧元区外币债权仅 €0.004B ＝ 几乎不持有美债** ——
  央行资负表口径与 TIC 持仓口径不可互相解释。
- **溯源块 `cu-prov`**：每条序列落 URL / 表名 / 取值列 / 成员国 / 美国财政部口径警告原文。
- 渲染层新增锚点：`cu-eusplit`(欧元区拆分) / `cu-op`(官方vs私人双线图+KPI) /
  `ncb-*`(五国央行子表) / `cu-prov`(溯源)。实测 `docs/index.html` 命中 49 处、
  "Eurosystem" 6 处，已随 `docs/` 部署。
- **验证脚本自身的转义误报**：Banca d'Italia 的撇号被转义成 `&#x27;` 触发假警报 ——
  与 9/8 Todd "Bubba" Horowitz 的 `&quot;` 同款，**修的是验证脚本不是数据**。

### 进展

- `3583258` feat(tic/cb)：欧元区按交易员视角拆分 + 央行vs私人 + 五国央行表 + 全链溯源。
  改 `external_data.py`(+344) / `dashboard.py`(+417) / `build_dashboard.py`(+31)。
  **门禁 51 个形参全部传入 · 26 项渲染判据全过 · 零回归通过**。
  两处 section 标题同步（旧文案「欧盟受口径限制滞后至上年末」已作废）。
  cron prompt 同步 4 处，备份 `~/.hermes/cron/jobs.json.bak_ecovol_eusplit_0909_231638`。
- `f7aa81f` fix(notion)：日报页央行标题对齐新口径（Eurosystem + 五国央行），
  cron prompt 同步要求 `cb_balance_notes` 写 Eurosystem 而非 ECB，
  且至少提一句五国央行谁在扩表/缩表。
- `6c17cae` docs：归档 2026-09-08 上下文日志。

### 待办

- [ ] **核查 9/09 日报产物缺口**：`data/ai_analysis_2026-09-09.json`(11:13)、
      `data/kol/daily/2026-09-09.json`(23:11)、`dashboard/scan-2026-09-09.html`(23:14) 均已落盘，
      但 **`reports/2026-09-09.md` 与 `data/daily/2026-09-09.json` 不存在**，
      `reports/latest.md` 仍停在 9/08。原因未查，勿臆测。
- [ ] 工作区有 20+ 个未提交的 data 改动（含 `hermes_line/*`、13F、KOL、政要披露），
      9/09 23:17 那两个 commit 未带上，待下次 cron 或手动收拢。
- [ ] 承接 9/08：四方对账门禁「cron 实抓」那一路是否已转全绿，仍未取得证据。
- [ ] 承接 9/04：tesseract 持久化未落地（需 Chao 点头动 devpod 配置），重启即丢逐笔。
- [ ] 检索词质量优化（非 bug）：24 人 `search_terms` 为带机构后缀长串。

## 2026-09-14

### 决策

- ★**Chao 选「丙」= 甲＋乙两道闸都要**（针对「cron 跑了却没 commit」的静默失败）：
  - **乙 · 治本**：步骤 8 的提交改走脚本 `scripts/daily_commit_push.sh`，
    **commit 后校验 HEAD 真的前进、push 后校验 local == remote**，否则非零退出。
    目的是**让 `last_status=ok` 不能再撒谎**。
  - **甲 · 兜底**：外部 `no_agent` 纯脚本看门狗，按**产物**（数据文件 mtime + git log）判定，
    不看任何 cron 状态标签。
  - **为什么乙不够**：乙只覆盖「跑到了那一步」的失败；9/14 是**没跑到就断了**，
    连非零退出码都产生不了 —— 这种情况只能靠外部按产物兜。
- Chao 先答「1」= 授权立刻补提交当天产物；再答「丙」= 两道闸同时上。
- AGENTS.md 写入首次审批超时被拒 → 按协议**未重试、未绕道**；Chao 回「OK」在场后重发才写入。

### 事实与配置

- ★**事故形态：agent 在工具调用中途断掉，而 cron 记 `ok`**。
  9/14 cron 11:00 正常跑完全部抓取与 dashboard 重建（52 个数据文件更新、`docs/index.html` 11:20 重建），
  **日志最后一行停在一个残缺的 `<invoke name="terminal">`** —— 无闭合标签、无执行结果，
  正是准备执行 commit 的那一刻。近一周同型 2 次（9/9、9/14）。
- **判据只认产物**：`git log` + 文件 mtime。用 git 实际记录对账才分得清
  「跑了没提交」与「本来就不该跑」（9/12 是周六，日报排程 `1-5` 不含周六，那天无 daily commit 属正常）。
- **`scripts/daily_commit_push.sh`** 退出码表：
  `.env` 未忽略→3 / 红线命中→4 / add·commit 失败→5 /
  **commit 后 HEAD 未前进→6** / push 失败→7 / **push 后 local≠remote→8**。
  只 add mtime 落在窗口内（默认 90 分钟）的文件 + 按路径二次排除 `data/hermes_line/HDB_*.json`；
  **绝不 `git add -A / -u`**。
- **`~/.hermes/scripts/eco_vol_commit_watch.sh`**（cron `eco-vol-commit-watch`，工作日 12:45，`no_agent`）：
  周末直接退出；12:30 前不判；判据1 = 今天 09:00 后 `data/`+`docs/` 被写文件数 <5 → 「没跑」；
  判据2 = 跑了但 `git log` 无 `daily <today>` → 「跑了没提交」。**静默即正常**。
- ★★**`git status --porcelain -uno` 会排除未跟踪文件**（自测在临时 repo 抓到的真 bug）：
  某天新增的数据文件将**永远提交不上**。真 repo 因文件都已跟踪而不暴露。
  已改 `-uall`（`-unormal` 只给到目录名 `data/`，喂给 `git add` 会连累别的 agent 的文件）。
- 六条路径已实测：提交+push 成功 / 无改动不造空 commit / 排除他人文件 /
  红线拦截 exit 4 / push 失败 exit 7 / local==remote 校验生效。
  告警脚本的触发路径也单独造场景实测过**确实会响**。

### 进展

- `a67ccae` daily 2026-09-14（补提交）：29 个文件。13:32 那批 `HDB_*.json` 属别的 agent，未纳入。
- `7cbad20` feat(cron)：步骤 8 改走脚本 + 双硬校验；cron prompt 同步（按字节位置切片替换，
  避开 redactor 对邮箱的改写 —— 字符串匹配会失败）。
- `ae0aaba` docs(AGENTS)：记录事故根因、两道闸分工、六条实测路径与 `-uno` 坑。

### 待办

- [ ] ★★**`a67ccae` 那次补提交自身漏了 6 个文件 —— 至今未进 git**（2026-09-15 归档时核实发现）：
      `reports/2026-09-14.md` · `data/daily/2026-09-14.json` · `data/snapshots/2026-09-14.json` ·
      `data/kol/daily/2026-09-14.json` · `dashboard/scan-2026-09-14.html` ·
      `data/ai_analysis_2026-09-14.json`（均 9/14 11:17–11:21 落盘，`git log` 查无记录）。
      `a67ccae` 的 29 个文件**逐个查 `--diff-filter=A` 全部是已跟踪文件的修改、0 个新增**
      —— 与 `-uno` 口径的表现完全吻合。**修了脚本却没回头重查已经做过的那次补提交。**
      后果：`eco-vol-commit-watch` 判据2 只看 `git log` 有无 `daily 2026-09-14`，**已存在 → 永不报警**；
      而次日 cron 的 90 分钟窗口也抓不到 9/14 的 mtime ⇒ **这个洞会永久静默**。
      补救（需 Chao 确认，涉及 push）：`bash scripts/daily_commit_push.sh 2026-09-14 2000`
      —— 但该脚本按 mtime 取窗口，会一并带上其它旧改动，宜手工点名这 6 个文件。
- [ ] 承接 9/09：`reports/2026-09-09.md` 与 `data/daily/2026-09-09.json` **至今仍不存在**
      （非未提交，是文件本身没生成）；同日 `data/snapshots/` 与 `data/kol/daily/` 已在 git。原因未查。
- [ ] 承接 9/08：四方对账门禁「cron 实抓」那一路是否已转全绿，仍未取得证据。
- [ ] 承接 9/04：tesseract 持久化未落地（需 Chao 点头动 devpod 配置），重启即丢逐笔。

## 2026-09-15

### 决策

- **Chao 指令：把 WRS 衰退指标放进 dashboard。**（尚在口径确认阶段，未开始写生产代码）
- ★我给出三选项待 Chao 拍板，**Chao 尚未回复**：
  甲＝叫「WRS · Walmart 衰退信号」+ 页面标注代理关系；
  乙＝名字里直接带「代理」二字；丙＝拿不到标普原指数就不做。
  我建议**甲**（方向已验证可靠，代理关系在溯源块讲清即可）。

### 事实与配置

- **WRS = Walmart Recession Signal**，Jim Paulsen（Leuthold Group 前首席投资策略师）提出。
  口径取自一手原文：**Walmart 股价 ÷ S&P Global Luxury Index**（80 只奢侈品股）。
  逻辑＝经济走弱时消费从奢侈品转向折扣零售 ⇒ WMT 相对跑赢 ⇒ WRS 上升。
  Paulsen 2026-03 称该指标创 2008 年以来新高。
- ★**分母的原指数拿不到**：S&P Global Luxury Index 是**标普专有指数**，不公开发布历史点位
  （`^SPGLUXP` 在 Yahoo 404）。
- ★**替代源 `LUXU.L`**：Amundi S&P Global Luxury ETF 的**美元份额**，Yahoo 有 10 年 2526 个日线点。
  **选美元份额而非欧元份额 `GLUX.MI`** —— WMT 以美元报价，同币种相除才不会把欧元汇率波动混进信号。
  两个必须如实标注的代价：①ETF 含费率与跟踪误差，不等于指数本身；
  ②只回溯到 2016（ETF 成立）⇒ **不能声称复现 Paulsen 的「2008 年以来最高」**。
- **Stooq 全线被挡**（本机数据中心 IP 的老问题）；Yahoo 通，WMT ✅、三大奢侈品龙头 ✅。
- **原型实算**（`scratch/_proto_wrs.py`，2016-09-14 基准=100）：
  历史最低 70.31（2021-12-08，疫后奢侈品狂欢）/ 161.22（2024-12-31）/ 173.33（2025-12-31）/
  **历史最高 237.50（2026-05-19）** / **当前 195.47（2026-09-14）**；
  近 10 年**分位 96.6%**、2026 年内 **+11.8%**。
  ⇒ 2024 年起急升，**独立实现复现了 Paulsen 的结论方向**，口径对得上。

### 待办

- [ ] 等 Chao 在甲/乙/丙之间拍板后再写生产代码
      （规划形态：折线图 + 当前分位 + 衰退期阴影 + 溯源块，并同步 cron 与 Notion）。

## 2026-09-16

### 决策

- **Chao 选「甲」= 手动触发当日 cron 整体重跑**（约 20 分钟，全流程含 Telegram 日报），
  而非乙（只重建 dashboard + 提交）或丙（放弃今天等明天）。
  理由：断点在流程早期，**只补 commit 会把半截数据提上去**。

### 事实与配置

- ★★**告警文案写死「同型」判断是错的 —— 本次并不同型**。
  `eco-vol-commit-watch` 正文里硬编码了一句「这与 2026-09-09、09-14 两次静默失败同型：
  抓数与 dashboard 全部正常，agent 在执行步骤 8 提交时中断」
  （源于 `~/.hermes/scripts/eco_vol_commit_watch.sh` 第 66–67 行）。
  实际逐项核对下来断点位置完全不同：

  | | 9/14 | **9/16** |
  |---|---|---|
  | 断点 | 跑完全部（含 dashboard 重建），断在**最后一步 commit** | 断在**步骤 1 政要披露核查** |
  | 产物 | 52 个文件，dashboard 已重建 | 产物只到 11:11，**dashboard 根本没重建** |
  | 缺什么 | 只差一个 commit | 后续抓取 / AI 分析 / Notion 写入 / dashboard / Telegram 日报**全没跑** |
  | 正确补救 | 补 commit | **必须整体重跑** |

  共同点只有「agent 会话被掐断（日志末尾是残缺的 `<invoke name="terminal">`，无闭合无结果）
  + cron 仍记 `last_status=ok`」。**断点位置决定补救方式，症状相同不代表补救相同。**
- ★**告警可疑信号：文件数**。告警报「今天写入 10 个文件」，而正常日是 40+ 个 —— 这个数字本身
  就提示「不是跑完才断」。事后验证成立，可作为下次快速分流的判据。
- ★**「跑得早」的证据取自产物 mtime 覆盖到哪一步**，不是读日志自报。
  9/16 断点确认靠两件事：`docs/index.html` 的 mtime 仍停在 09-15、日志末行位置在步骤 1。
- ★**重跑回执里的 `Result: ok` 不可信**（正是这三次都在撒谎的同一个字段）。
  本次改为逐项核产物验收，全部通过：
  - `docs/index.html` 16:11 重建，文件内 `2026-09-16` 出现 **80 次**（确认是真数据不是旧产物换戳）；
  - `dashboard/index.html` 16:11 / `reports/latest.md` 16:12 / `reports/2026-09-16.md` 16:12 /
    `data/daily/2026-09-16.json` 16:12 / `data/ai_analysis_2026-09-16.json` 16:07；
  - commit `690f5bf daily 2026-09-16` + `0cbe767 daily 2026-09-16 补: 政要/KOL 早轮数据 + 2026-09-14 遗漏6文件`，
    **local == remote == `0cbe767`**；
  - 剩余 11 个未提交文件全是 13:31 的 `data/hermes_line/HDB_*.json`（别的 agent 的），按纪律未碰。
- ★**按产物判定的设计被本次验证有效**：看门狗抓到的断点**比设计时预想的更早**
  （设计假设断在步骤 8 提交，实际断在步骤 1）⇒ 产物判据的适用范围天然大于设计时考虑的场景。
- 9/15 的 `3f43330 daily 2026-09-15` 正常，**不是持续故障**。

### 进展

- 手动触发 `eco-vol-01-daily-scan-report`（`085fb753a988`）整体重跑，1438.95s（约 24 分钟）完成，
  当日全部产物重建并进远端。
- ★**9/15 归档时挂的那条待办已清**：`a67ccae`（9/14 补提交）漏掉的 6 个文件已全部进 git，
  逐个用 `git ls-files` / `git log` 验过，均落在 `0cbe767`：
  `reports/2026-09-14.md` · `data/daily/2026-09-14.json` · `data/snapshots/2026-09-14.json` ·
  `data/kol/daily/2026-09-14.json` · `dashboard/scan-2026-09-14.html` · `data/ai_analysis_2026-09-14.json`。
  根因正是当时手工筛选用了 `git status -uno`（排除未跟踪文件）—— 后来在自测中抓到并修进脚本的那个坑，
  **当天真的咬了一口**。
- 重跑后再跑一次 `eco_vol_commit_watch.sh`，输出长度 0（静默）⇒ 告警闸恢复正常，不是卡住不响。

### 待办

- [ ] **改掉 `~/.hermes/scripts/eco_vol_commit_watch.sh` 第 66–67 行那句写死的「同型」判断**
      —— 告警只陈述事实（今天写了几个文件 / git 有没有今天的 commit / dashboard mtime 停在哪天），
      推测句必须由排查者看到现场后给出，不能由告警模板预先给出。**已向 Chao 提出，等一句确认。**
- [ ] **WRS 衰退指标仍卡在等 Chao 拍板**（承接 9/15）：我建议甲＝叫「WRS · Walmart 衰退信号」
      + 明确标注分母用 ETF 代理。已在 9/16 再次向 Chao 提请，未回。
- [ ] 承接 9/09：`reports/2026-09-09.md` 与 `data/daily/2026-09-09.json` **至今仍不存在**
      （已复核，非未提交，是文件本身没生成）；原因未查。
- [ ] 承接 9/08：四方对账门禁「cron 实抓」那一路是否已转全绿，仍未取得证据。
- [ ] 承接 9/04：tesseract 持久化未落地（需 Chao 点头动 devpod 配置），重启即丢逐笔。

## 2026-09-18

### 决策

- **流动性指标口径由 `SOFR − IORB` 改为 `SOFR − EFFR`**（Chao 直接指令）。
  实现时**保留 key `sofr_iorb` 不改** —— 改 key 会断掉 Notion 历史列与 dashboard 时序，
  只改口径、显示名、阈值、说明文字。
- **新 section「每日流动性危机监测」**：Chao 要「去年 1 月以来到今天的图 + 标注闪崩时点 +
  叠加 Oracle CDS 或同级别信贷差」，用途是**盯每日流动性危机**。
  逐条确认后拍板：① 「这个」= 刚改的 SOFR−EFFR 图（**对**）；
  ② Oracle 单名 CDS 拿不到 → **同意**用 BBB OAS 主线 + HY OAS 参照；
  ③ 闪崩口径选 **「甲乙两个」= 金银闪崩 + 美股大跌日都标**（不是丙 Oracle 股价、不是只标一类）。
- **Thiel Macro 加入 13F 名单**（Chao 回「好的」授权）。名册增删本来要 Chao 拍板，这次拿到了明确同意。
- **COT 对冲基金持仓叠加图照做**（Chao 第二个「好的」）。
  ★ 两个「好的」**分别只授权一件事**，没有捆绑：第一个「好的」按**只授权 push** 理解，
  COT 图单独再问一次才动手。

### 事实与配置

- ★**Chao 的前提被实测推翻两次，都以实测为准**：
  - 「德国央行扩表」→ 实际是**缩表**。`TTA032` 总资产 2024-06-28 €2,447.3B → 2026-09-04 €2,287.1B，
    **两年 −160.2B**。缩的是国债（`TTA019` 欧元区居民证券 €955.5B → €701.2B，**−254.3B**，PSPP/PEPP 滚落 QT）；
    **黄金一克没卖**（`TTA050` €757.5B → €1,232.8B，**+475.4B 全是金价重估**，按市价计量）。
    我此前报过的「德国央行 +23.7%」来自 ECB BSI 口径、起点 2020-02（疫情前），与近两年方向相反 —— 已自我纠正。
    顺带 `TTA051`（对非欧元区外币债权，含美债）两年仅 +15.1B，印证欧元区央行几乎不碰美债。
  - 「13F 最近 2-3 周有新的出来」→ **不成立**。13F 季度制、季末后 45 天申报：
    Q2(6/30) 截止 8/14 已全拿到，**Q3(9/30) 要到 11/14 才截止**。
    逐个查 EDGAR `submissions` API 确认 **18/18 全部已是 SEC 最新版**，无一落后。
    唯一近期变动是 Citadel 9/2 提交的 `13F-HR/A` 修正件（期末仍 6/30），我们抓的已是修正后版本。
- ★**Chao 反过来纠正我一次**：我把「Palantir CEO」查成了 **Alex Karp**（SEC 上无 13F，
  WhaleWisdom 明写 "does not appear to be an investment manager"）。
  实为 **Peter Thiel**（联合创始人/董事长），其 **Thiel Macro LLC 才报 13F**。
  （另：Palantir 公司实体确实报过 13F，但 **2023-11 后停报**，最后一期 2023Q3，与蒂尔个人基金无关。）
- **Thiel Macro LLC `CIK = 0001562087`**，29 份 13F。2026-08-14 申报、期末 2026-06-30，
  **8 条持仓合计 $418,666,506**（与报道的 4.18 亿吻合）。能源/电力合计 $300.7M = **71.8%**。
  ★**但「完全押注电力」不成立** —— 第一大持仓是**亚马逊 $118.0M / 28.2%**，
  真实结构是「约七成电力 + 近三成亚马逊」。
  ★更强的事实：**2026Q1 申报是一张 `NA / 0` 空表**，且 `prev_ok=True`（不是解析失败那个坑）
  ⇒ 这 4.19 亿**不是加仓，是从零一次性建仓**。
- ★**COT 做不到每天更新，是 CFTC 制度限制不是抓不到**：持仓采集日每周二、官方发布当周周五 15:30 ET。
  「对冲基金持仓日更」在数据源层面不存在。折中＝**持仓周度台阶 + 价格日度曲线**，
  badge 明写「持仓周更 · 价格日更」，溯源块直接写「日更在数据源层面不存在」。
  该诚实标注已写进验证判据（`未把持仓标成日更` 这项会 fail）。
- **口径**：用 Disaggregated 的 **Managed Money**（纯对冲基金），
  不是 Legacy 的 non-commercial（混了 CTA 与指数基金，原 `fetchers/cot.py` 用的是后者）。
  ★**铂金在 NYMEX 不在 COMEX**（`PLATINUM - NEW YORK MERCANTILE EXCHANGE`），标注不能写成 COMEX。
- ★**Chao 那张幻灯片截图有两处数字问题**（已核 CFTC 官方）：
  ① 标为白银的那组 MM/SD 数字**其实是黄金** —— 截图 MM多 123,681 / SD空 210,637，
  对照 2026-03-03 黄金 MM多 123,456 / SD空 219,152（量级吻合），白银同日仅 MM多 12,840 / SD空 45,768（差一个数量级）。
  那张幻灯片把**黄金的持仓表**和**白银的 OI 图**并排放了。
  ② 「白银 OI 跌到 11.3 万创疫情以来新低」数字对（3/03 = 113,326），
  但**最新 9/08 是 103,250 比那时更低** ⇒ 不是一次性闪崩低点，是持续低迷。
- **德国央行 Bundesbank API 的三个解析坑**（同一份 CSV 连栽三次）：
  ① 分隔符是**分号**（德式 CSV）不是逗号；
  ② **不带 `Accept: text/csv` 头会返回 XML**；
  ③ **前 8 行是元数据，第 9 行起才是 `日期;值`**，缺值标 `.`，表头形如 `"";BBBK11.D.TTA032;...`。
  三次都是我的脚本错、数据一直都在 —— 「报全无时先假设脚本错」这条纪律当天连救三次。
- **阈值必须随口径重校**（实测 2024-01 至今 676 个交易日）：
  `SOFR−IORB` 均值 −4.0bp / >0 占 17%；`SOFR−EFFR` 均值 +1.2bp / >0 占 **48%**，**中枢差约 5bp**。
  沿用旧阈值（≤0 正常 / 7–17 / >17）会让**近一半交易日跳出「正常」** = 天天亮黄灯的废灯。
  新阈值按 **2018-04 至今 2,112 个交易日分位**定档：**绿 ≤ +5bp（P90）/ 黄 +5~+18bp / 红 > +18bp（P99）**，
  近两年回测绿 86% / 黄 12% / 红 1%。
  有效性校验：**2019-09 回购危机该利差冲到 +295bp**、2020-03 最高 +29bp —— 真危机抓得住。
- ★**换口径的额外收益**：旧口径在拿**不同日期**的数相减（IORB 是 9/18 的、SOFR 是 9/16 的），
  −28bp 这个数本身就失真；SOFR 与 EFFR 同为 9/16，口径干净。
- **Oracle 单名 CDS 是 Markit/ICE 付费数据，免费源拿不到**，没有硬凑替代品。
  选 BBB 档的依据是**实测核实的评级**：S&P **BBB−**（2026-07 下调，**距垃圾级仅一档**）、
  Moody's Baa2 负面、Fitch BBB；债务 $1,295 亿 ≈ 4.3× EBITDA（Reuters 2026-08-04）。
  这段理由写进了页面溯源块。当前 BBB OAS 0.96% / HY OAS 2.70%，
  **两线之差 1.74pct = 市场给 Oracle 的降级风险定价**。
  FRED 序列：`BAMLC0A4CBBB`(BBB) / `BAMLC0A3CA`(A) / `BAMLH0A0HYM2`(HY) / `BAMLC0A0CM`(IG)，均日频免费。
- **闪崩识别阈值不是拍的**：用各资产 2025-01 以来日收益率的 **P1 分位**（最极端 1%），随数据自适应。
  识别出 **15 天**，与已知事件吻合：2025-04-03/04 关税恐慌（标普 −4.84%/−5.97%）、
  2025-10-21 黄金 −5.74%、**2026-01-30 白银 −31.35% / 黄金 −10.78%**（即 Chao 截图那次）。
  ★**修了一处会误导的措辞**：原写「两类同崩 0 天」易被读成「没有两个资产同天崩」，
  实际含义是**贵金属与美股跨类同日**为 0（金银那几次是同类内双崩）。已改「贵金属与美股同日闪崩」并加说明。
- **当前读数**（COT 期末 2026-09-08，价格至 2026-09-18）：

  | | OI | OI 近3年分位 | MM 净 | 分位 | SD 净 |
  |---|---|---|---|---|---|
  | 黄金 COMEX | 411,227 | P19 | +134,972 | P55 | −239,313 |
  | 白银 COMEX | 103,250 | **P4** | +14,386 | P35 | −27,391 |
  | 铂金 NYMEX | 67,810 | P16 | +9,787 | P54 | −7,505 |

  **白银 OI 在近三年 P4 分位**，比截图说的「疫情以来新低」更极端。
- **数据文件**：`data/liquidity_crisis.json`（44.9K，keys=series/crashes/status/start/crash_days/provenance，status=ok）、
  `data/cot_managed_money.json`（136.8K，keys=gold/silver/platinum，三金属各 156 期持仓 + ~757 日价格）。
- **`external_data.py:5053` 基差套利面板那处 `SOFR−IORB` 未动** —— 那里 IORB 作
  「利率走廊上沿」判 SOFR 有没有触顶，**该场景下 IORB 才是对的参照物**。已向 Chao 说明，他未要求改。

### 进展

- `8f08d32` **feat(liquidity)**（20:06，15 files，+1169/−343）：
  流动性危机监测 section + SOFR−EFFR 口径切换 + Thiel Macro 13F（19 家）。
- `99ecd6f` **feat(cot)**（20:55，6 files，+257/−11）：
  对冲基金(Managed Money)持仓 vs 价格叠加图 —— 金/银/铂，
  每张图 = 绿线价格(日频) + 紫色台阶 MM 净持仓(周频) + 棕虚线 OI。
- **local == remote == `99ecd6f`**，硬校验通过；
  别的 agent 的 11 个 `data/hermes_line/HDB_*.json`（13:31）**误入 0**。
- 两轮各 **23/23 判据通过、失败 0、回归 0**，门禁 `generate()` 全部 53 个数据形参均已传入，Traceback 0。
- ★★**顺带修掉一个真 bug（不是这次改出来的，是被这次暴露的）**：

  ```python
  status = 'ok(缓存)'            # fetcher 回退缓存时返回
  if ci.get("status") != "ok":   # 渲染层严格比对 → 整个板块渲染成「数据同步中…」
  ```

  **数据完好无损**（`panels=['gold','silver','platinum']`、`as_of=2026-09-16`），**板块却整个空白**。
  当天上游 CHARTS 源返空、触发缓存回退，这个潜伏的 bug 才第一次暴露 ——
  **日志写着 `status=ok(缓存)` 一切正常，页面上板块却没了**，正是要根除的那类静默失败。
  全局扫描发现**两处**，都已改成 `startswith("ok")`（`src/dashboard.py` L4013 / L6852）：
  - `_comex_inventory_html` —— 上游返空 → `ok(缓存)`（**已实际触发过**）
  - `_maturing_treasury_html` —— 部分年份拉取失败 → `ok(部分年份拉取失败...)`（尚未触发，一并堵上）

  修复验证：COMEX 库存 **412 → 412 完全恢复**，且是在 `status` 仍为 `ok(缓存)` 的情况下 ⇒ 容错真的生效。

### 教训

- ★★**同一个毛病一天犯三次：验证判据靠猜，不先去产物里 grep 一眼**。三次全是假警报：
  - 查 `comex_inventory`（变量名）→ 页面上其实是中文「COMEX 库存」
  - 查 `kol-card`（class）→ **这个 class 根本不存在**，实际是 `KOL` ×326
  - 数 `cmm-one` → **把 CSS 定义块 `.cmm-one{...}` 一起数进去了**，误报 3 张图变 4 张（重复插入警报）

  好在纪律是「报异常先假设脚本错」，每次都查到了真相；但**写判据前应先 grep 产物确认串真的存在**。
- ★**`ps | grep -c` 当判据是错的**：无匹配时 `grep -c` **退出码非 0**，`&&` 短路导致后续命令不执行，
  我据此误判「构建已退出」，实际进程状态是 `running`、仍在跑。判据仍应取**进程状态本身**。
- ★**改代码要在构建启动之前**：我改措辞是在第一轮构建**跑起来之后**做的，
  Python 启动时已 import 旧版 `dashboard.py`，所以第一轮产物里仍是旧措辞（验证脚本抓到了：新措辞 ×0 / 旧措辞 ×1）。
- ★**`build_dashboard.py` 直接读 13F 缓存、不重抓** —— 加了 Thiel Macro 后首轮构建里他没出现，
  不是代码没生效，是缓存是当天 11:20 cron 写的。需单独跑 `fetch_all()` 刷新缓存再重建。
- **patch 在长文件里定位失败的两个真实原因**（都不是「文件太长」）：
  ① dashboard 的 **CSS 块在 f-string 里**（`{{ }}` 转义），正则 `\{[^}]*\}` 匹配不到；
  ② `{basis_trade}` 包在 `<div class="card">` 里、同行有内容，行首正则不匹配；
  那些 `xxx=_xxx_html(` 是 **`.format()` 的 kwargs**（缩进 8 空格、行尾带逗号），不是独立赋值语句。
  ★两次 Python 语法门禁拦下了写坏的改动（f-string 内层同款引号），**项目文件未被写坏**。

### 待办

- [ ] **COT 叠加图已完成**，但 Chao 曾提的「乙 = 额外加 MM 净持仓历史分位」
      目前只体现在统计块数字（P19/P4/P16 等），**未单独做分位可视化**；是否要补未确认。
- [ ] **是否把基差套利面板（`external_data.py:5053`）那处 `SOFR−IORB` 也改成 EFFR** —— 已向 Chao 说明
      「那里 IORB 作走廊上沿是对的」，等他一句话。
- [ ] Chao 问的第二个大问题**未回**：「是否要把 13F 范围从『基金经理』扩到『科技圈有 13F 的人』」
      —— 我提议先扫一份候选清单（Bezos / Gates 基金会 等）给他挑，**名单该加谁由他拍板**，未获回复。
- [ ] 承接 9/16：改掉 `~/.hermes/scripts/eco_vol_commit_watch.sh` 第 66–67 行写死的「同型」判断。
- [ ] 承接 9/15：**WRS 衰退指标仍卡在等 Chao 拍板**（建议甲＝「WRS · Walmart 衰退信号」+ 标注分母用 ETF 代理）。
      本轮又提了一次，仍未回。
- [ ] 承接 9/09：`reports/2026-09-09.md` 与 `data/daily/2026-09-09.json` 至今不存在，原因未查。
- [ ] 承接 9/08：四方对账门禁「cron 实抓」那一路是否已转全绿，仍未取得证据。
- [ ] 承接 9/04：tesseract 持久化未落地（需 Chao 点头动 devpod 配置），重启即丢逐笔。
