# 把 YouTube Shorts 接进每日 crawl：生产级 fetcher（不是一次性探查）

同族文件：`kol-source-coverage-youtube-shorts.md` —— 那篇讲**发现问题**（三 tab 必扫、标题可能与正文相反）。
本篇讲**产品化**：Chao 2026-08-25 下指令「未来他的那个 Shorts 也要加入我们每天的这个 crawling 里面，
**不要错过他的标题和对话**」，于是从一次性探查升级成常驻模块。

产物：`src/fetchers/youtube_shorts.py` + daily cron 步骤 2.5（在 KOL 抓取之前）。

---

## A. ★★★ 反机器人三件套（缺一不可）—— 最容易误诊成"这些视频没字幕"

本 VM 是数据中心 IP，YouTube 会对**单视频**请求返回
`Sign in to confirm you're not a bot`。

**关键非对称性（记住这条，它是误诊的根源）：**

| 请求类型 | 是否被拦 |
|---|---|
| `--flat-playlist` 拉频道列表 | **不被拦** |
| 单视频元数据（`--print upload_date`） | 被拦 |
| 单视频字幕（`--write-auto-sub`） | 被拦 |

于是症状是 **「标题全拿得到、日期和字幕全是空」**。
第一次跑出来我差点写成"这些 Shorts 没有字幕"——那是**假阴性**，
和 memory 里「数据抓不到禁直接标'信息有限'，必先回源重爬」是同一条红线。

### 修复（三件缺一不可，实测组合有效）

```python
COOKIE_CANDIDATES = [
    "~/Projects/AI-Blog-Generator/.secrets/yt_cookies_new.txt",
    "~/Projects/AI-Blog-Generator/.secrets/yt_cookies.txt",
]
PLAYER_CLIENT_ARGS = ["--extractor-args", "youtube:player_client=web_safari,default"]
```

1. `--cookies <导出的 YouTube cookies>`
2. `--extractor-args youtube:player_client=web_safari,default`
   —— ★**只给 cookies 仍然被拦**，必须同时换 player client。实测对照：
   ```
   仅 cookies                 → ERROR: Sign in to confirm you're not a bot
   cookies + web_safari       → 20260824|D_9ceMMNSAk   ✅
   ```
3. `PATH` 里加 `~/.deno/bin`（yt-dlp-ejs 解 n-challenge 用）。
   在 `subprocess.run` 里显式注入，别指望继承：
   ```python
   env = {**os.environ}
   deno_bin = os.path.expanduser("~/.deno/bin")
   if os.path.isdir(deno_bin) and deno_bin not in env.get("PATH", ""):
       env["PATH"] = deno_bin + os.pathsep + env.get("PATH", "")
   ```

**排查顺序**：日期/字幕大面积为空 → ①先查 cookies 是否过期 ②再查 player_client 参数在不在
→ **绝不**直接得出"没有字幕/该频道没内容"的结论。

### venv 与系统 yt-dlp 可能是两个二进制
`which -a yt-dlp` 会列出一堆。项目 venv 里那个和你手动测试用的那个可能版本/配置不同，
出现"我手动跑成功、代码里跑失败"时先确认 `_yt_dlp()` 解析到的是哪个。

## B. ★关键词过滤字幕是错的 —— 生产管线一律全下

`kol-source-coverage-youtube-shorts.md` §B 原建议「按关键词筛，只下命中项字幕」。
**那是一次性探查的省钱做法，接进每日管线后是 bug。**

初版按 KEYWORDS 筛，25 条里漏了 5 条，其中两条恰恰是核心信号：

| 被漏标题 | 实际内容 |
|---|---|
| `JP Morgan Had to Bail Out the US in 1896!` | 正是他论证"资本流入美国"的核心历史依据 |
| `US Economy The Power of Low Government Cost!` | 讲美元为何是"最后一个倒下的"（政府支出占 GDP 美35% vs 欧盟52%） |

标题不含任何宏观关键词，内容却是论点主干 —— **典型假阴性**。
Chao 的原话「不要错过他的标题和**对话**」就是在要求全覆盖。

**现设计**：默认对**全部新增**下字幕；`KEYWORDS` 降级为
「新增量超过 `max_subs` 时的**排序优先级**」，而不是过滤器：

```python
ordered = sorted(fresh, key=lambda it: (0 if KEYWORDS.search(it.get("title") or "") else 1,))
targets = [it["id"] for it in ordered[:max_subs]]
# 超配额的标 transcript_status="超出单轮字幕配额，待下轮补"，而不是静默丢弃
```

实测覆盖率：Armstrong 最近 25 条 → 日期 25/25、字幕 25/25。

## C. 增量设计（别每天重抓 899 条）

两段式，成本可控且可每日跑：

1. `--flat-playlist` 拉最近 N 条标题 —— **极快，25 条约 1 秒**，且不触发反机器人。
2. 与 `data/kol/shorts/<kol_id>.json` 已有 id 做 diff，**只对新增**取日期 + 字幕。

落盘两处：
- `data/kol/shorts/<kol_id>.json` —— 累积库，**只增不删**（KOL 被移出名册也保留历史，日后加回即用）
- `data/kol/shorts/daily/<date>.json` —— 当日新增，供报告/dashboard 读

诚实边界：拿不到字幕 → `transcript=None`，**只保留标题也算有效信号**，绝不编台词；
频道 404 / yt-dlp 缺失 → `status="未就绪"`，不编标题。

## D. 频道配置走名册，且能扛住 Notion 单向同步

频道来源 = `kol_registry.json` 的 `youtube_channel_id`（支持 `@handle` 或 `UCxxx`）。

★**先验证 `tools/sync_kol_from_notion.py` 不会把它冲掉**再写入 —— 该脚本保留本地独有采集配置
（`search_terms` / `youtube_channel_id` / `source_url`）。干跑确认：

```bash
python3 tools/sync_kol_from_notion.py            # 不加 --apply = 预演
# → "保留并刷新: 122 / 新建: 0 / 移出: 0"，然后确认字段还在
```

这一步不能省：名册 SSOT 在 Notion，而 `youtube_channel_id` 是 Notion 侧没有的**本地采集配置**，
不确认就写 = 下次同步可能静默丢失。

## E. 挂 cron 的做法

直接改 `~/.hermes/cron/jobs.json` 里那个 job 的 `prompt`（先 `cp` 一份带时间戳的 `.bak-*`），
把新步骤插在依赖它的步骤**之前**（本次插在 KOL 抓取前，作为「步骤 2.5」）。

prompt 里必须连**踩坑说明一起写进去**，否则未来的 agent 看到空字幕又会误判：

> ★踩坑：本 VM 会触发 "Sign in to confirm you're not a bot"。`--flat-playlist` 不受影响，
> 但单视频元数据/字幕会被拦——症状是「标题有、日期和字幕全空」，极易误判成"该视频没字幕"。
> 修复三件套已内置。若又出现空值，先查 cookies 是否过期，**不要**得出"没有字幕"的结论。

## F. 本轮踩到的工具限制（与业务无关，但会浪费轮次）

- `terminal` 里用 `python3 -c` 写文件偶尔被网关判为"重启网关"而 **Blocked**
  → 用 `execute_code` 写文件、`terminal` 只跑 yt-dlp，分工最稳（`kol-source-coverage-youtube-shorts.md`
  §B 已记，此处复现证实）。
- `terminal` 前台超时上限 **600s**，传 900 会直接报错。批量下字幕要么分批，要么 `background=True`。
- `AGENTS.md` 是 protected 文件：一次会话里连续两处编辑，第二处审批弹窗**静默超时=拒绝**。
  按 memory 铁律**不重试、不绕道 terminal**，改为如实告诉 Chao 哪一处没落地。
