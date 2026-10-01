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
