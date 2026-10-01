# 离散事件卡片型 section（新闻/事件时间线，非时序数字）— Chao 2026-08

这个项目里绝大多数 section 是**结构化时序数字**（FRED/EIA/TIC… → 画折线/柱状 → 进 Notion 时序 DB）。
但有一类需求是**离散事件文本**——「美日财政政策事件」（债务上限/CR/政府关门/补正预算/国债发行），
它没有像 FRED 那样的结构化 API 可每天稳定吐数。这份 reference 是这类 section 的标准做法（首例：`data/fiscal_news.json`）。

## 何时用这个模式（vs 时序图）
- 内容是**离散事件**（每条=日期+标题+摘要+来源），不是能画折线的连续数值 → 用事件卡片。
- 想把日经225 那种指数点位和收益率(%)硬塞一张图 → **不要**（量级差几个数量级会压平），分开。
- 用户明确要「新闻/举措/事件」而非「一条曲线」→ 事件卡片。

## 架构：JSON 文件驱动 + cron agent 动态抓取（本项目已验证的难源模式）
和 `manual_overrides.json`（反爬指标）同一思路：**渲染只读文件，内容由 cron agent 写。**
1. **种子 JSON** `data/<topic>_news.json`：`{status,as_of,source,note,events:[{date,country,flag,category,title,summary,source_url,source_name}]}`。用真实 web_search 结果手填初始几条，**每条必带真实 source_url**。
2. **fetch 函数**（`external_data.fetch_<topic>_news`）：只读文件 → 过滤有 (date,title,source_url) 的条目 → 按日期倒序 → 截断 limit(~20)。文件缺失/空 → `status:"未获取"` 空 events（绝不编）。
3. **渲染函数**（`dashboard._<topic>_news_html`）：事件卡片列表，每卡=日期+国旗+分类标签(左色条按国/类)+标题+摘要+`<a class="src-lnk">来源 ↗</a>`。莫兰迪配色；空/未获取 → `<p class="empty">…待更新（cron 检索中，抓不到不编造）</p>`。
4. **Notion DB**（事件表，非时序）：title=`f"{date} {title}"`（日期+标题做唯一键，幂等 upsert），列 Date(rich_text)/Country(select)/Category/Summary/Source_URL(url)/Source_Name。**Source_URL 用 `{"url": val or None}` 手构造**（notion_writer 没有 prop_url helper）。
5. **cron 抓取步骤**（关键，A 方案的核心）：在 daily cron prompt 里加一个自然语言步骤，让 agent 每日 `web_search` 该主题最新事件 → 构造 dict list → 合并进 JSON（**读旧→按 (date,title) 去重→只增→按日期倒序留最近20条**）。合并用一行 python `-c`（读 json、set 去重、append、sort reverse、截断、写回、更新 as_of）。

## 铁律（写进 cron 步骤里，别只靠自觉）
- **抓不到就不加**：绝不编事件/编日期/编链接。
- **web_search 返空（后端故障）→ 整步跳过，保留已有事件不动**（本项目 searxng/ddgs 偶发限流返空是已知的，见 SKILL.md 的 search-backend note）。这是这类 section 的**固有边界**，要对用户诚实说明「每日自动更新这条腿依赖 web_search，故障时保留已有、不硬凑」。

## 侧栏分组陷阱（本 session 踩到）
侧栏 `groupOf()` 按 GROUPS 顺序返回**首个子串命中**。新 section 标题若含某个靠前分组的 match 关键词会被误吞。
- 例：国债组 match 里有 `'美日'`，会把「美日财政政策事件」标题吞进国债组，永远到不了新建的「财政政策」组。
- 修法：把过宽的关键词收窄到更长的唯一子串（`'美日'`→`'美日 10'` 只匹配收益率图），给新 section 用它自己标题里独有的词做 match。
- **加任何新 section 前：检查它的标题会不会命中已有靠前分组的 match 关键词。**

## 首例实现指针（fiscal_news，commit fc1aace）
`fetch_fiscal_news`/`_fiscal_news_html`(+`.fn-*` CSS) · DB_FISCAL_NEWS(build_us_jp_market_dbs) · daily cron「步骤 5.6」· 独立侧栏组「财政政策」。
