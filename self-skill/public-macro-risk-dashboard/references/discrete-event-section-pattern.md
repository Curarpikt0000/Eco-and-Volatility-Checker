# 离散事件 section 模式（vs 时序数字 section）— Chao 2026-08

本 dashboard 绝大多数 section 是**结构化时序数据**（FRED/EIA/IMF 数字 → 画图 → Notion 时序 DB 每指标一列）。但有一类 section 是**离散事件文本**（财政政策事件、政策新闻、公告），呈现方式、数据源、Notion 结构都不同。第一次出现在"美日财政政策事件"section（债务上限/CR/政府关门/补正预算/国债发行）。

## 关键区别：时序 vs 离散事件

| 维度 | 时序 section（收益率/IIP/石油） | 离散事件 section（财政政策事件） |
|---|---|---|
| 数据形态 | 数字序列 (date,value) | 事件卡片 (date,国家,分类,标题,摘要,来源链接) |
| 呈现 | SVG 折线/柱状图 | 时间线卡片列表（倒序），无图 |
| 数据源 | 官方结构化 API（稳） | web_search 检索文本事件（脆），无 API |
| 更新腿 | cron 脚本 fetch（稳定每日进新数） | cron **agent 模式** web_search 抓最新事件（依赖不稳定的 web_search） |
| Notion | 时序 DB，每指标一 number 列 | 事件表：Event(title) + Date/Category/Summary(rich_text) + Source_URL(url) + Country(select) |

## 实现骨架（三件套同步照旧）

1. **JSON 文件驱动**：`data/fiscal_news.json`（`{status,as_of,source,note,events:[{date,country,flag,category,title,summary,source_url,source_name}]}`）。dashboard 只读这个文件渲染，不在渲染时抓网。cron agent 负责往这个文件写最新事件。
2. **fetch 函数**：`fetch_fiscal_news(limit=20)` = 读 JSON → 过滤有必需字段(date/title/source_url)的真实条目 → 按 date 倒序 → 截断 limit。**每条必须带真实 source_url**（可点击核实），绝不编造事件。
3. **渲染**：`_fiscal_news_html` = 事件卡片列表，每卡 border-left 用国家色(US 陶土红/JP 雾蓝) + head(日期+国旗+分类chip) + 标题 + 摘要 + 来源链接(`.src-lnk` target=_blank)。CSS 类 `.fn-wrap/.fn-card/.fn-head/.fn-date/.fn-flag/.fn-cat/.fn-title/.fn-sum/.fn-src`。
4. **Notion 事件表**（`build_us_jp_market_dbs.py` 加 DB_FISCAL_NEWS）：属性用 `rich_text`（Date/Category/Summary/Source_Name）+ `url`（Source_URL）+ `select`（Country）。upsert title = `f"{date} {title}"[:200]`（日期+标题做唯一键，避免同标题不同期覆盖）。URL 属性手动构造 `{"url": val or None}`（notion_writer 无 prop_url helper）。
5. **cron 接线**：daily cron inline generate 加 `fn=e.fetch_fiscal_news()` + `fiscal_news=fn`；`write_data_from_env()` 自动含事件表写入。

## ★侧栏分组 groupOf 子串首命中陷阱

dashboard 侧栏 `GROUPS[].match` 是**子串 indexOf 首命中**（`groupOf` 遍历 GROUPS 顺序，第一个 `label.indexOf(m)>=0` 就返回）。加新 section 时若某个已存在组的 match 关键词是新标题的子串，新 section 会被错误归到那个组、永远到不了自己的组。

- 实例：国债组 match 有 `'美日'`（本为"美日 10年/30年国债收益率"图），会先命中"**美日**财政政策事件"标题 → 财政新闻被吸进国债组。
- 修法：把过宽的子串关键词收窄到能唯一区分的更长串（`'美日'` → `'美日 10'`，只命中收益率图不命中财政事件）。**加新 section 后必检查：新标题是否被任何靠前组的 match 子串命中？** 靠前组永远赢。

## ★诚实交底原则（Chao 明确要的态度）

当某个 section 的**自动更新腿依赖不稳定的 web_search**（本项目 searxng/ddgs 常被限流返空，见 SKILL 主体的 web_search 后端故障判定），要**主动向用户交底**这张图"数据能不能可靠拿到"，一张一张说清楚：

- 硬数据图（FRED/MOF/EIA/IMF 官方 API）→ 明说"真能拿到、每天/每期稳定进新数"。
- 年频指标（如 IIP）→ 明说"年频，一年才更一次，as_of 停在去年是正常不是 bug"。
- 依赖 web_search 的离散事件图 → **诚实说软肋**："初始几条是真的可核实，但每日自动更新这条腿是脆的，web_search 一挂就停在已有事件，绝不编"。给用户 A/B/C 选择（照现状上 / 加一条硬数据腿补强 / 先不做只留硬数据图），不粉饰、不硬凑代理数据冒充真数据。

Chao 会直接问"老老实实告诉我这几张图你能不能找到数据"——这是他检验诚实的高频动作，答时逐图交底、软肋直说。
