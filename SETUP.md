# SETUP — 接手每日定时任务（公网版交接包）

> 给接手的 agent：`git clone` / `git pull` 本仓库后，从上到下照做，就能把每天的抓取、日报、KOL 回填、推送全部跑起来。
> 所有时间为东京时间（Asia/Tokyo，UTC+9）。
> 本包不含任何密钥。密钥只写进你自己的 `.env` 和 `~/.hermes/.env`，绝不进 git、绝不回显。

## 0. 总览

这个项目每天做什么：

1. 工作日 09:00 并行抓取全部 KOL 的最新言论（约 40 分钟）。
2. 工作日 11:00 日报 agent：同步 KOL 名册 → 抓指标 → 写 Notion → 生成看板 → 提交推送 → 发布 Cloudflare → 在 Telegram 发 12 模块日报。
3. 工作日 14:00 给「名册里新增的人」自动补一年历史言论。
4. 周六 11:00 周报。
5. 另有 5 个纯脚本的看门狗/投影任务，静默即正常，只在异常时发消息。

快照在 `ops/cron-jobs.json`（共 8 个任务，含线上真实运行的提示词）。**以快照为准，不要凭下面的摘要重写。**

| 任务名 | 时间(JST) | 类型 | 作用 |
|---|---|---|---|
| eco-vol-kol-notion-projection | 工作日 06:30 | 脚本 | KOL 言论库→Notion 投影，回写 notion_page_id 并推送 |
| eco-vol-context-distill | 每天 06:00 | agent | 把前一天的对话沉淀进 docs/context-log.md（不推送） |
| eco-vol-kol-prefetch | 工作日 09:00 | 脚本 | 起 6 个并行子进程抓全部 KOL，合并，写 STATUS |
| eco-vol-01-daily-scan-report | 工作日 11:00 | agent | 主日报，见 cron-jobs.json 里的 13 个步骤 |
| eco-vol-commit-watch | 工作日 12:45 | 脚本 | 查「跑了没提交 / 提交没推送」 |
| eco-vol-kol-new-backfill | 工作日 14:00 | 脚本 | 名册新增人自动补一年历史 |
| eco-vol-selfheal-watchdog | 每小时 :20 | 脚本 | eco-vol-* 任务 last_status=error 就重跑 |
| eco-vol-weekly-report | 周六 11:00 | agent | 周报 |

## 1. 前置条件

```bash
git clone https://github.com/Curarpikt0000/Eco-and-Volatility-Checker.git ~/Projects/Eco-and-Volatility-Checker
cd ~/Projects/Eco-and-Volatility-Checker
python3 -m venv .venv
.venv/bin/pip install requests pandas xlrd openpyxl pymupdf pytesseract pdfplumber matplotlib beautifulsoup4 lxml
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng   # 川普 OGE 278-T 是纯扫描件，没有它逐笔退回 0 条
```

注意：仓库里没有 requirements.txt，上面是实测在用的包。`tesseract` 在容器重启后可能丢失，政要板块川普逐笔突然变 0，先查 `tesseract --version`。

### 密钥（只列变量名）

写进项目根目录 `.env`（已被 .gitignore 忽略；先 `git check-ignore .env` 确认）：

- `FRED_API_KEY` — 美联储 FRED，指标、金油比、货运指数都用
- `EIA_API_KEY` — 美国能源信息署
- `NOTION_TOKEN`、`NOTION_VERSION=2022-06-28`
- `DB_*` / `HDB_*` — 各 Notion 数据库 ID（约 30 个，与 `src/config.py` 对应；向 Chao 要）
- `FINNHUB_KEY`、`ALPHAVANTAGE_API_KEY`（可选）

写进 `~/.hermes/.env`：

- `SCRAPER_API_KEY` — CBOE Put/Call 官方值，本机数据中心 IP 被 CBOE 封，必须走它；缺了该指标降级为「未找到」
- `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID` — Cloudflare Pages 发布

另需：wrangler（Cloudflare 命令行）装到 `~/.hermes/tools/node_modules/.bin/wrangler`（发布脚本按这个路径找，**不要装在 /tmp，重启会丢**）。

向 Chao 确认的东西：Notion 数据库 ID、Notion token（必须能访问「KOL List」「Daily auto tracking」等库）、Cloudflare 凭证。拿不到就停下问，别猜。

## 2. 装技能（必做）

```bash
mkdir -p ~/.hermes/skills/devops
cp -r self-skill/public-macro-risk-dashboard ~/.hermes/skills/devops/
```

里面的 `references/` 是踩坑记录（~100 篇），接手前至少读：
`kol-full-crawl-background-prefetch.md`、`new-kol-auto-backfill-and-notion-selfheal.md`、`kol-backfill-gated-ingest-and-daily-highlights.md`、`silent-scraper-failure-detection.md`、`watchdog-and-run-verification.md`。

## 3. 部署脚本

```bash
mkdir -p ~/.hermes/scripts
cp ops/hermes-scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*.sh
mkdir -p scratch && cp ops/kol_deep_run_batch.sh scratch/kol_deep_run_batch.sh
mkdir -p scratch/kol_bf_gap110 && cp ops/kol_bf_INSTRUCTIONS.md scratch/kol_bf_gap110/INSTRUCTIONS.md
```

**必须把脚本里的路径换成你自己的**（我已把原路径换成占位符 `<PROJECT_ROOT>` / `<HERMES_SCRIPTS>`）：

```bash
sed -i "s#<PROJECT_ROOT>#$HOME/Projects/Eco-and-Volatility-Checker#g; s#<HERMES_SCRIPTS>#$HOME/.hermes/scripts#g" ~/.hermes/scripts/eco_vol_*.sh ~/.hermes/scripts/eco_vol_*.py ~/.hermes/scripts/publish_cf_pages.sh scratch/kol_deep_run_batch.sh scratch/kol_bf_gap110/INSTRUCTIONS.md
grep -rn "/home/user" ~/.hermes/scripts/eco_vol_* scripts/ tools/*.sh   # 仓库自带脚本里还有写死的路径，也要换
```

仓库内这几个文件里写死了原作者路径 `/home/user/Projects/Eco-and-Volatility-Checker`，**接手方需要改**：
`scripts/daily_commit_push.sh`（`REPO=`）、`scripts/publish_vibe.sh`（不用，见 §7）、`tools/kol_new_backfill.sh`（`ROOT=` 与 DRY 守卫那行）、`src/fetchers/web.py`（读 `~/.hermes/.env`，通常不用改）。

两个脚本里还有需要你自己确认的：

- `scratch/kol_deep_run_batch.sh` 最后一行写的模型名是旧的，prefetch 脚本会用 `sed` 换成 `KOL_MODEL`（默认 `claude-sonnet-5`）。**换成你自己能用的模型**：`export KOL_MODEL=<你的模型名>`，或直接改两个脚本里的默认值。
- `tools/kol_new_backfill.sh` 里 `hermes -z ... --provider custom -m "${KOL_MODEL:-claude-sonnet-5}"` 的 `--provider custom` 也要换成你的 provider。

## 4. 从真源重建数据

Git 里已经有 KOL 名册、言论库（`data/kol_store.sqlite`）等，但名册以 Notion 为准：

```bash
.venv/bin/python tools/sync_kol_from_notion.py --apply     # 单向镜像 Notion → data/kol_registry.json
.venv/bin/python tools/kol_consistency_audit.py            # 四层对账，退出码 0 才算一致
```

## 5. 创建定时任务

用 `hermes cron create`（参数见 `hermes cron create --help`）。`ops/cron-jobs.json` 每个任务有这些字段，照抄：`schedule_cron`、`no_agent`、`script`、`workdir`、`enabled_toolsets`、`model`、`prompt`。示例：

```bash
# 纯脚本类（no_agent）
hermes cron create "0 9 * * 1-5" "<prompt 字段内容>" --name eco-vol-kol-prefetch \
  --no-agent --script eco_vol_kol_prefetch.sh --deliver <你的投递目标>

# agent 类
hermes cron create "0 11 * * 1-5" "<prompt 字段内容，把 <PROJECT_ROOT> 换成你的路径>" \
  --name eco-vol-01-daily-scan-report --workdir <你的项目路径> --deliver <你的投递目标> \
  --model <你的模型>
```

**要点：**

- `deliver` 在快照里是 `origin`（原作者的 Telegram 话题），接手方必须换成自己的目标（`telegram`、`platform:chat_id` 等）。
- **同一个 workdir 的任务共用目录锁**：日报 / 周报 / context-distill 带 workdir，不要排在重叠窗口，否则后面的会等满 660 秒后 TimeoutError。
- 时区必须是 Asia/Tokyo（`hermes cron` 按系统时区算）。
- **日报与 prefetch 是两段式，不要合并**：prefetch（09:00，脚本）抓 175+ 人需要 40 分钟，日报 agent（11:00）只读结果。一个 agent 轮里逐个抓会超时，旧版就是这样烂的。
- 新增任务时把名称统一用 `eco-vol-` 前缀，自愈看门狗按这个前缀重跑 `last_status=error` 的任务。

## 6. 验证（逐项）

```bash
# a. 看板能建出来（后台跑，约 8 分钟，别前台跑会被 420 秒杀）
nohup .venv/bin/python src/build_dashboard.py > /tmp/build.log 2>&1 &
# 日志末尾应有: ✅ 门禁: generate() 全部 NN 个数据形参均已传入

# b. prefetch 链路自测（不调大模型，约 30 秒）
KOL_PREFETCH_DATE=2099-01-01 KOL_PREFETCH_DRY=1 bash ~/.hermes/scripts/eco_vol_kol_prefetch.sh
cat scratch/kol_deep_2099-01-01/STATUS ; rm -rf scratch/kol_deep_2099-01-01

# c. 提交脚本（无改动时应打印「无需提交」，不造空 commit）
bash scripts/daily_commit_push.sh $(date +%F)

# d. 发布脚本
bash ~/.hermes/scripts/publish_cf_pages.sh eco-volatility-checker docs/index.html docs/.cf_last_sha256_eco-volatility-checker
# 应输出 LIVE https://eco-volatility-checker.pages.dev/ 或 no change
```

对 `tools/kol_new_backfill.sh` 做沙箱自测时，务必 `KOL_BF_ROOT=<副本目录> KOL_BF_DRY=1 KOL_BF_NOPUSH=1`。**曾经因为路径写死，自测把 7 条假数据写进了真库**，现在脚本会拒绝 DRY 对正式目录运行，但仍请先对 `data/kol_store.sqlite` 记 md5，测后比对。

## 7. 本包故意不含的东西

- **`eco-vol-codex-delivery-watch` 任务**：作者额外把成品同步到公司内部仓库和内部发布入口，只对作者有意义。接手方没有对应目标，不需要。
- `scripts/publish_vibe.sh`：同上，内部发布脚本，接手方不要用，也不要运行。
- 公网 GitHub Pages 目前对匿名访客返回 404（账号级限制，非仓库违规），**主入口是 Cloudflare：https://eco-volatility-checker.pages.dev/**。

## 8. 日常运维铁律（都是踩过坑的）

1. **名册只读**：KOL 名册的唯一真源是 Notion「KOL List」。**绝不自行增删任何人**，只跑 `sync_kol_from_notion.py` 单向镜像。新增人由 Chao 或另一个 agent 在 Notion 里加，14:00 的任务会自动补一年历史。
2. **绝不编数字**：取不到就标「未就绪/未找到」，不用昨天的冒充今天。
3. **提交只走 `scripts/daily_commit_push.sh`**，不手敲 git。它只提交窗口内产出的文件，**绝不 `git add -A`**（这个仓库有别的 agent 也在写，如 `data/hermes_line/HDB_*.json`）。
4. **看 exit 码，不看「ok」标签**：cron 记 `last_status=ok` 不代表做完。以前至少两次「数据全抓好了但没 commit」。
5. **成功信息以线上实测为准**：发布后匿名 curl 页面，HTTP 200 + sha256 一致才算成功。
6. 前台命令上限约 420 秒，建看板、全量抓取一律 `background` + 完成通知。
7. 密钥只进 `.env`；提交前跑红线扫描（`ghp_`/`sk-`/`ntn_`/`BEGIN PRIVATE`）。`daily_commit_push.sh` 已内置。
8. 改 cron 先问 Chao。
9. **Notion 写入先读 schema 再写**，缺列会整行 400（曾静默 8 天没写）。`src/run.py` 已有自愈：只加列，不删。
10. 项目文档：`AGENTS.md`（项目规则）、`handover.md`（看板全景与数据表）、`docs/context-log.md`（按日决策与进展）。

## 9. 待 Chao 决定的事项（接手前先问）

- KOL「立场转向」判定是否只认新言论（现在 30 条里只有少数来自当天新言论）。
- 周报 KOL 一节是否改为每人 1 条。
- 「美元奶昔」提出者（Santiago Capital 署名 12 条）保留还是删除（暂留）。
- AGENTS.md 里 3 段积压说明（prefetch、kol_bf_ingest 门禁、新 KOL 回填）尚未写入——写它们需要审批弹窗。内容在 `docs/PENDING_agents_md_kol_prefetch.md`。

## 10. 回滚

交接顺序：接手方先完成 §6 全部验证 → 通知原作者 agent 逐个**暂停**（不删）它名下的 `eco-vol-*` 任务 → 观察一个交易日。失败就 resume 原任务，接手方暂停自己的。**两边不要同时跑**：会重复抓取、抢着提交，且双倍烧模型额度（6 路并行 KOL 抓取在大模型上曾 3 小时烧掉 500 美元额度）。

## 11. 看板板块清单（自动更新）

<!-- AUTO:SECTIONS:BEGIN -->
_自动生成于 2026-10-14（`scripts/handover_refresh.py`，每个工作日检查一次，请勿手改此段）_

看板当前共 **44** 个板块（顺序＝页面顺序；频率＝页面上的更新标签）：

1. 指标卡片 · 18 项（短 → 中 → 长） ——**每日更新**
2. 警报统计速览 ——**每日更新**
3. 逐条简短解读 ——**每日更新**
4. 短中长期综合结论 ——**每日更新**
5. 卖出触发状态追踪（同时 ≥3 项 = 开始分批卖出） ——**每日更新**
6. 今日最需关注的一条信号 ——**每日更新**
7. 本周 KOL 状态变化 · 按模块 (态度转向 call-out) ——**每周更新**
8. 流动性要点 · 央行/国债 ——**每日更新**
9. 四大央行资产负债表 · 每日更新 (US/JP/CN/Eurosystem · 2x2 + 欧元区五国央行 · 当天汇率统一折$B) ——**每日更新**
10. 三国货币供应量 M0 / M1 / M2 · 月度 (央行资负表下延: 社会实际流通的钱) ——**每月更新**
11. 三国 M2 十年走势 · 折线 ($B 当天汇率统一折算 · 放水力度长期对比) ——**每月更新**
12. Credit Impulse 信贷脉冲 · 中期领先指标 (美/中/欧 · 季度 · 新增信贷的加速度 · 领先实体经济6-9月) ——**每季度更新**
13. 信用维度：杠杆与偿息能力
14. 国债市场收益率·波动性·压力 · 竖向四联图 (对齐 Morgan Stanley · 过去3年真实公开数据 · 每日更新) ——**每日更新**
15. 国债市场微观结构 · 成交量与交易成本 (对齐 Morgan Stanley Exhibit 3/4 · 成交量为 NY Fed 官方真数据 · 价差为代理) ——**每周更新**
16. 基差套利去杠杆预警 · 美债/日债 (SOFR 倒挂 + 持券 Carry + 波动触发 · 强平潮尾部风险 · 每日更新) ——**每日更新**
17. 中国模式断代监控 · 旧引擎停摆与新引擎接续 (NBS 官方分项 + 东财宏观 · 对照 Perkins 2025-12 判据) ——**每月更新**
18. WRS · Walmart 衰退信号 (Walmart ÷ 奢侈品指数 · Jim Paulsen 口径 · 分母用 ETF 代理) ——**每日更新**
19. 金银回调 · 历史类比路径 (金 2006/2008 · 银 2008/2011 · GDX÷SPY · 日度) ——**日更**
20. 黄金波动率 · GVZ / 布林带宽度 / ATR (COMEX 周线 · 2011 起) ——**日更**
21. 联邦基金利率 × 金价 × 油价 (1970 起 · 月度 · 右轴对数) ——**日更**
22. 金油比 · 黄金 ÷ WTI 原油 (1971 起 · 月度 · 对数轴) ——**每日更新**
23. 比特币 ÷ 黄金 · 暴涨暴跌与事件 (2010 起 · 月度 · 对数轴) ——**日更**
24. 股指 ÷ 黄金 · 50 年比值 (道指÷金价 · 标普500÷金价 · 月度对数坐标 · 1976 年至今) ——**每日更新**
25. 美元指数 vs 黄金 · 年初至今大事件标注 (双轴叠加 · 事件由价格异动反查并逐条核实出处) ——**价格每日 · 事件每周**
26. 白银期货 · 各月合约价差 (COMEX · 日度 · 对比持有成本) ——**日更**
27. COMEX 期货期权持仓 (金/银 · Managed Money 方向，非隐含波动率) ——**持仓周更**
28. 贵金属 ETF 期权波动率 (GLD/SLV/IAU · ATM IV 期限结构 + 25D 偏斜) ——**每日更新**
29. 黄金 ETF 分地区资金流 (北美/欧洲/亚洲/其他 · 世界黄金协会官方周度吨数) ——**每周更新**
30. 机构研究报告 · 被公开解读的线索 (按机构 · 近 6 个月 · 正文未读) ——**日更**
31. 消费者信心 vs 全要素生产率 (密歇根信心 · TFP 相对趋势 · 复刻 BofA Chart 10 · 1978 年至今) ——**每日检查**
32. 美国货运 · 铁路周度 (AAR 10 类商品 + 联运) 与公路月度 (ATA / Cass) ——**每周更新**
33. 中美 AI 投资 · 科技巨头资本开支 (美国五家 vs 阿里/腾讯/百度 · 季度 + 美国数据中心建设月度) ——**每日检查**
34. AI 算力价格 · LLM Token 支出指数 (Silicon Data SDLLMTK · 美元/百万 token · 全市场/闭源/开源) ——**每日更新**
35. 全球货币供应与放水加速度 (美/欧/日/英/中 · 30 年) ——**月度更新**
36. 美国国债拍卖 · 财政部 (最新+过去3次 · 规模/中标率/收益率/间接投标 · 下次日程) ——**每次拍卖**
37. 外国官方托管美债 · 纽约联储 (去美元化风向标) ——**每周更新**
38. 1年内到期可交易国债 · 再融资墙 (rollover 压力) ——**每月更新**
39. 美日 10年/30年国债收益率 · 过去一年 (四线同图 · 美日利差与套息) ——**每日更新**
40. 日本 / 中国 / 欧元区 持有美债 · 央行 vs 私人 · 近10年 + 2008长历史 (TIC 分国别口径) ——**每月更新 · 滞后约2月 · 三方同频**
41. 四国国际投资头寸 IIP · 过去十年 (美/日/德/中 对外资产·负债·净债权地位) ——**每年更新**
42. 美国石油库存运营红线 · 能源安全 (Brent-WTI 价差 / Cushing / SPR · tank bottom) ——**每周更新 · 价差每日**
43. 日经225 vs 外资净买入日股 · 过去一年 (日本市场 · 外资资金流) ——**指数每日 · 外资每周**
44. 机构持仓追踪 · 13F + Trump (对比上期变动) ——**每季度 · Trump不定期**

取数函数（`src/external_data.py`，共 69 个）：`fetch_kol_recent`、`fetch_china_liquidity`、`fetch_liquidity_points`、`fetch_ecb_balance_sheet`、`fetch_euro_ncb_balance_sheets`、`fetch_cb_balance_sheets`、`fetch_cb_liquidity_swaps`、`fetch_fiscal_budget`、`fetch_maturing_treasury`、`fetch_foreign_custody_ust`、`fetch_custody_acceleration`、`fetch_tic_official_vs_private`、`fetch_country_ust_holdings`、`fetch_treasury_auctions`、`fetch_money_supply`、`fetch_m2_history`、`fetch_credit_impulse`、`fetch_treasury_stress_panels`、`fetch_ofr_fsi`、`fetch_us_jp_yields`、`fetch_nikkei225`、`fetch_foreign_flow_japan`、`fetch_iip_four_countries`、`fetch_hf_leverage`、`fetch_bis_gold_swaps`、`fetch_silver_imports_data`、`fetch_gold_premium`、`fetch_ad_line_real`、`fetch_market_breadth`、`fetch_silver_bank_positions`、`fetch_comex_silver_issues_ref`、`fetch_gold_exports`、`fetch_us_yield_century`、`fetch_comex_issue_stop_firms`、`fetch_comex_issue_stop_weekly`、`fetch_fiscal_news`、`fetch_oil_inventory`、`fetch_basis_trade_monitor`、`fetch_liquidity_crisis_panel`、`fetch_cot_managed_money`、`fetch_comex_inventory`、`fetch_debt_to_gdp`、`fetch_corporate_credit`、`fetch_ai_credit`、`fetch_ai_fcf`、`fetch_synthetic_spreads`、`fetch_treasury_curve`、`fetch_cips`、`fetch_china_regime_shift`、`fetch_wrs_recession_signal`、`fetch_ust_microstructure`、`fetch_dxy_gold_events`、`fetch_gold_etf_flows_by_region`、`fetch_pm_option_vol`、`fetch_comex_option_positions`、`fetch_global_money_supply`、`fetch_wgc_weekly_iv`、`fetch_stock_gold_ratio`、`fetch_tfp_sentiment`、`fetch_llm_token_index`、`fetch_ai_capex`、`fetch_gold_oil_ratio`、`fetch_us_freight`、`fetch_btc_gold_ratio`、`fetch_gold_silver_tech`、`fetch_fed_gold_oil`、`fetch_gold_volatility`、`fetch_analog_corrections`、`fetch_silver_curve_spread`

运维工具（`tools/`，共 30 个）：`aar_rail_weekly.py`、`add_forecast_kols.py`、`add_kol_short_names.py`、`add_notion_sync_to_cron.py`、`apply_1yr_backfill.py`、`apply_full_backfill.py`、`apply_snapshot_detail.py`、`backfill_kol_detail.py`、`backfill_optvol.py`、`build_comexopt_db.py`、`build_globalm2_db.py`、`build_optvol_db.py`、`clean_cron_esoteric_ref.py`、`ensure_tesseract.sh`、`fix_globalm2_gaps.py`、`freshness_audit.py`、`kol_backfill_detect.py`、`kol_backfill_loop.sh`、`kol_bf_ingest.py`、`kol_consistency_audit.py`、`kol_highlights.py`、`kol_merge_deep.py`、`kol_new_backfill.sh`、`rename_kol_notion_person.py`、`snapshot_optvol.py`、`split_cycle_kols.py`、`sync_kol_from_notion.py`、`tech_watch.py`、`verify_backfill_urls.py`、`web_watch.py`

<!-- AUTO:SECTIONS:END -->

## 12. 变更记录（自动追加，新→旧）

<!-- AUTO:CHANGELOG:BEGIN -->
- 2026-10-12 新增板块：金银回调 · 历史类比路径 (金 2006/2008 · 银 2008/2011 · GDX÷SPY · 日度)（日更）
- 2026-10-12 新增板块：联邦基金利率 × 金价 × 油价 (1970 起 · 月度 · 右轴对数)（日更）
- 2026-10-12 新增板块：黄金波动率 · GVZ / 布林带宽度 / ATR (COMEX 周线 · 2011 起)（日更）
- 2026-10-05 新增板块：机构研究报告 · 被公开解读的线索 (按机构 · 近 6 个月 · 正文未读)（日更）
- 2026-10-05 新增板块：白银期货 · 各月合约价差 (COMEX · 日度 · 对比持有成本)（日更）
- 2026-10-05 新增板块：比特币 ÷ 黄金 · 暴涨暴跌与事件 (2010 起 · 月度 · 对数轴)（日更）
- 2026-10-01 初始化：登记 38 个看板板块基线（含金油比、美国货运、LLM Token、中美 AI 投资等）。
<!-- AUTO:CHANGELOG:END -->
