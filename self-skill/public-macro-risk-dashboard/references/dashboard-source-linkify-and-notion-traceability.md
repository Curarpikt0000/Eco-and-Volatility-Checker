# Dashboard 数据源可点超链接 + 每图表 Notion 可回溯

两条 Chao 明确提出、可复用到任何 public-macro-risk-dashboard 类项目的增强 pattern。

## 1. 数据源指标代码 → 可点击超链接（Chao 2026-08 要求）

**需求**：dashboard 上每张图的「数据源：」行现在显示裸指标代码（`BAMLH0A0HYM2`、`DGS10`、`THREEFYTP10`、`WMTSECL1`、`T10Y2Y` 等），Chao 看到一串代码发懵。要求把代码变成可点击超链接，点了直达该指标官方源页面便于核实。

**正解 = 一个集中 helper，全 dashboard 复用**（不要在各处散落硬编码 `<a>`）：

在 `src/dashboard.py` 的 `_esc` 后面加：

```python
import re  # 加到文件顶部 import 行

_SRC_LINK_SPECIAL = {   # 非 FRED、或需要专门落地页的关键词 → URL
    "OFR FSI": "https://www.financialresearch.gov/financial-stress-index/",
    "Office of Financial Research": "https://www.financialresearch.gov/financial-stress-index/",
    "^MOVE": "https://finance.yahoo.com/quote/%5EMOVE/",
    "Yahoo Finance": "https://finance.yahoo.com/quote/%5EMOVE/",
    "TIC": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
    "fiscaldata.treasury.gov": "https://fiscaldata.treasury.gov/",
}
_FRED_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")
_FRED_IDS = {   # 白名单：只转已知 series，避免误伤 US/JP/MS/OAS/IG/BofA 等普通大写词
    "DGS10","DGS2","T10Y2Y","THREEFYTP10","BAMLC0A0CM","BAMLH0A0HYM2",
    "WMTSECL1","DTWEXBGS","VIXCLS","DFII10","T10YIE","WALCL","WRESBAL",
    "RRPONTSYD","WTREGEN","QBPBSTAS",
}

def _linkify_sources(text):
    """把 source 文本里的指标代码替换成可点击超链接(已含 HTML 转义)。None→空串。"""
    if text is None:
        return ""
    esc = html.escape(str(text), quote=True)
    for kw, url in _SRC_LINK_SPECIAL.items():          # 1) 特殊关键词先处理
        kw_esc = html.escape(kw, quote=True)
        if kw_esc in esc and f'>{kw_esc}<' not in esc:
            esc = esc.replace(kw_esc,
                f'<a class="src-lnk" href="{url}" target="_blank" rel="noopener">{kw_esc}</a>', 1)
    def _repl(m):                                        # 2) FRED series 白名单
        sid = m.group(1)
        if sid in _FRED_IDS:
            return (f'<a class="src-lnk" href="https://fred.stlouisfed.org/series/{sid}" '
                    f'target="_blank" rel="noopener">{sid}</a>')
        return sid
    return _FRED_ID_RE.sub(_repl, esc)
```

CSS（f-string 里双花括号转义）：
```css
.src-lnk {{ color: #7fa0b8; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 2px; }}
.src-lnk:hover {{ color: #a8c4d8; text-decoration-style: solid; }}
```
莫兰迪浅蓝虚下划线，可辨识不刺眼（符合 Chao 交易员屏审美）。

**替换所有 source 渲染点**：把各 HTML 生成函数里的 `数据源：{_esc(src)}` / `源：{_esc(str(...))}` / `{_esc(p.get("source",""))}` 全部换成 `_linkify_sources(...)`。搜 `_esc.*source` + `数据源：{_esc` + `源：{_esc` 定位（本项目共 ~6 处动态 source + 2 处固定文案）。固定文案里的关键词（`fiscaldata.treasury.gov`、`WMTSECL1`、footer 的 `FRED`/`CFTC COT`）不是动态 source 字段，手动包 `<a class="src-lnk">` 即可（不能整段 linkify，会破坏已有 `<b>` 标签）。

**关键坑**：
- `_esc` 转义必须在 linkify 内部先做，否则外部数据仍有注入风险；helper 已内置。
- FRED ID 用**白名单**不用纯正则——`\b[A-Z]{2,}\b` 会误伤 `US`/`JP`/`MS`/`OAS`/`IG`/`BofA` 等普通缩写。
- source 里若关键词被括号打断（如 `OFR (...) FSI`，"OFR FSI" 不连续），special 匹配落空——补一个精确唯一的替代关键词（如 `Office of Financial Research`）。

**验证法**（不必跑完整 build 抓网络，但最终要跑一次真实 build 验证完整 HTML）：
1. 单测 helper：喂几条真实 source 字符串，看输出 `<a>` 正确。
2. 单测单个 panel HTML 函数（喂 `data/stress/*.json` 落盘数据）。
3. 跑真实 `python build_dashboard.py`（后台 + notify，抓网络 1-3min），对生成的 `dashboard/index.html` 和 `docs/index.html`（Pages 源）统计 `src-lnk` 链接数、验证 `<a>` 全闭合、`re.findall(r'href="[^"]*<a ')` 为空（无嵌套破损）。
4. push 后 `curl` raw.githubusercontent 确认线上更新。

## 2. 每图表一 Notion DB，长期可回溯（Chao 2026-08 追加原则）

Chao 要求：所有 code+数据在 GitHub 有备份（已满足：code 进 repo，`data/**.json` 进 git），**并且每张图表的时序数据都要有一个对应的 Notion DB 存起来**，"长期来讲就有可回溯的空间"。

**盘点铁律（建 DB 前必做，避免重复/漏建）**：列一张「图表 → 当前是否已有 Notion DB / 数据是否已进 git」清单。config.py 的 `NOTION_DB` dict 是 SSOT。本项目盘点结果（2026-08）：

已有 10 DB：indicators / cot / report / weekly / holdings / custody / auctions / money_supply / stress / ofr。

缺专属 DB（回溯有缺口，待补）：
- Credit Impulse 信贷脉冲（四国 + 2008 长历史）— 只算不存 Notion
- 国别持仓美债（日/中/欧 TIC）— 只算不存 Notion
- 本周 KOL 状态变化 — 有 git 快照(`data/kol/daily/`)但无 Notion DB
- 托管美债加速度四折线 — 可并入现有 custody DB
- 央行资负表/流动性 — 现读 Economic-Dashboard 跨库，可选是否本项目也存一份

**建库坑**（沿用本项目既有做法）：
- 用增量建库脚本（只建新 DB + 追加 `.env`，**绝不跑原始 build() 全建**——那会覆盖只留初始几个 DB，破坏已有）。
- 给已存在的 DB 加新列（如给 DB_OFR 补「股票估值」列）：**必须先用 Notion API 加 property，再 PATCH 写值**——PATCH 一个不存在的 property 会报错。
- 幂等 upsert 用 `skip_none=True`：抓不到当天数据时剔除空值字段，不覆盖 Notion 已有真值。
- 写后必读回验证。
