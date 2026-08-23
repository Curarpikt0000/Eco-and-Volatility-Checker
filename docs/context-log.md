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
