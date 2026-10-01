# Dashboard SVG 图表增强技术 (dashboard.py)

本文件记录 Eco-and-Volatility-Checker 的 `src/dashboard.py` 里对手写 SVG
折线图做的两类可复用增强，以及围绕它们的工作流陷阱。所有图表都在
`_stress_panel_svg()`（双轴多线折线）和同类 SVG 函数里画。

---

## 1. 数据源指标代码 → 可点击超链接 (`_linkify_sources`)

**需求（Chao 2026-08）**：dashboard 上每张图脚注的"数据源"是裸指标代码
（`BAMLH0A0HYM2` / `DGS10` / `THREEFYTP10` / `WMTSECL1` …），用户看着发懵。
要求：把这些代码渲染成**可点击超链接**，点了直达官方源页面便于核实。

**做法**：建一个 helper 一处覆盖全 dashboard，替代所有 `数据源：{_esc(...)}`：

```python
import re, html

_SRC_LINK_SPECIAL = {              # 非 FRED / 需专门落地页的关键词
    "OFR FSI": "https://www.financialresearch.gov/financial-stress-index/",
    "Office of Financial Research": "https://www.financialresearch.gov/financial-stress-index/",
    "^MOVE": "https://finance.yahoo.com/quote/%5EMOVE/",
    "Yahoo Finance": "https://finance.yahoo.com/quote/%5EMOVE/",
    "TIC": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
    "fiscaldata.treasury.gov": "https://fiscaldata.treasury.gov/",
}
_FRED_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")
_FRED_IDS = {  # 白名单，避免误伤 US/JP/MS/OAS/IG/BofA 这类普通大写缩写
    "DGS10","DGS2","T10Y2Y","THREEFYTP10","BAMLC0A0CM","BAMLH0A0HYM2",
    "WMTSECL1","DTWEXBGS","VIXCLS","DFII10","T10YIE","WALCL","WRESBAL",
    "RRPONTSYD","WTREGEN","QBPBSTAS",
}

def _linkify_sources(text):
    if text is None: return ""
    esc = html.escape(str(text), quote=True)
    for kw, url in _SRC_LINK_SPECIAL.items():           # 特殊词先处理
        kw_esc = html.escape(kw, quote=True)
        if kw_esc in esc and f'>{kw_esc}<' not in esc:
            esc = esc.replace(kw_esc, f'<a class="src-lnk" href="{url}" target="_blank" rel="noopener">{kw_esc}</a>', 1)
    def _repl(m):
        sid = m.group(1)
        if sid in _FRED_IDS:
            return f'<a class="src-lnk" href="https://fred.stlouisfed.org/series/{sid}" target="_blank" rel="noopener">{sid}</a>'
        return sid
    return _FRED_ID_RE.sub(_repl, esc)
```

**关键设计点（都是踩过的坑）**：
- **FRED series 走白名单**，不是"任何大写词都转链接"——否则 `US`/`JP`/`MS`/
  `OAS`/`IG`/`BofA` 会被误当成 series ID。所有 FRED series 统一跳
  `fred.stlouisfed.org/series/<ID>`。
- **特殊关键词先替换**（在 FRED 正则之前），避免 `OFR`/`TIC` 被吃掉。
- source 字符串里 `"OFR (Office of Financial Research, US Treasury) FSI …"`
  ——`"OFR FSI"` 不是连续子串（中间隔括号），所以要额外加
  `"Office of Financial Research"` 关键词才能命中。
- **固定中文文案里的源**（如拍卖脚注 `数据源：美国财政部 fiscaldata.treasury.gov`、
  托管美债 `数据源：FRED WMTSECL1`、footer 的 `FRED`/`CFTC COT`）不是动态
  source 字段，不能整段 linkify（会破坏内嵌的 `<b>` 标签）——直接手动把关键词
  包成 `<a>`。
- CSS：`.src-lnk { color:#7fa0b8; text-decoration:underline dotted; text-underline-offset:2px }`
  （莫兰迪浅蓝虚下划线，可辨识不刺眼）。

**验证**：`grep -o '<a class="src-lnk" href="[^"]*">[^<]*</a>'` 统计链接数 +
锚文本；检查 `href="..." <a ` 无嵌套破损；`<a` 数 == `</a>` 数。

---

## 2. 双轴折线图的点位标注（最高/最低/当前/中位）

**需求（Chao 2026-08）**：双轴图（如"收益率曲线与信用压力"：左轴 10Y-2Y 利差、
右轴 HY OAS，单位不同）**光看线不知道当前具体点位是多少**。Chao 明确：
"你可能因为左右单位不一样没画统一零轴——那至少给我标注最高点/最低点/当前点/
中位，标在线上，否则不知道现在具体点位。"

**做法**：在画每条 series 的循环里，对每条线算 `cur / hi / lo / med` 四个值，
并在 SVG 上画：
- **▲最高点 / ▼最低点**：小实心圆 + 数值，`text-anchor` 按 x 位置自适应
  （靠左 start / 靠右 end / 中间 middle）避免出界。
- **当前点**：白边实心圆（`r=3.6 stroke="#fff"`）+ "当前 X.XX"。
- **中位虚线**：该 series 所在轴的水平虚线 `stroke-dasharray="2,4" opacity=0.5`。
- **右侧图例下方**：紧凑摘要 `现X.XX 高X.XX 低X.XX 中X.XX`（各线同色）。

中位数内联算（不引 statistics）：
```python
sv = sorted(vals); m = len(sv)
med = sv[m//2] if m % 2 else (sv[m//2-1] + sv[m//2]) / 2
```

**关键设计点**：
- **双轴不能画统一零轴**——0 对左轴和右轴含义不同，画一条会误导。用
  **每轴各自的中位虚线 + 四点位数值**替代，比零轴更能表达"现在处于历史什么位置"。
  （单轴图如 OFR FSI 才画 `0 = 历史正常` 零轴。）
- **图例摘要宽度会溢出 viewBox**：三位数值（如 `现137.26 高…`）比两位宽。
  实测把 `当前` 缩成 `现`、去掉 ` · ` 分隔仍不够；**根治是加宽 viewBox
  `w=1000` + 图例右边距 `mr=175`**（绘图区靠 ml/mr 定位不变，只扩右侧图例带）。
- 这个增强对**所有压力图**通用（不只用户点名的那张），一次改全部受益。

**验证（无 vision 时的程序化替代）**：对每张 panel 渲染 SVG，正则抽所有
`<text x=..>内容`，用 east_asian_width 估算文字宽度（中文9px/数字5px），
断言 `float(x)+宽度 <= viewBox宽+容差`（无溢出）；断言中位虚线数==线数、
当前点描边圈数==线数。

---

## 3. 工作流陷阱：daily cron 会吞掉你手头的 work-tree 改动

**现象**：改完 dashboard.py 后自己跑 `git add … && git commit && git push`，
结果 `git diff --stat` 空、`git status` 干净、HEAD 是 `daily 2026-08-18`
——不是我的 commit message。

**根因**：Eco-and-Volatility-Checker 的 daily cron（11:00 JST，内联 generate）
在我编辑期间恰好触发，它 `git add` **整个 work tree**（含我未提交的 src 改动）
一起 commit + push 了。我的改动**已经上线**，只是被 cron 的 commit 收走。

**判定 + 应对**：
- 别慌以为"没提交成功"。先 `git show HEAD:src/dashboard.py | grep -c <你的新代码标记>`
  确认 HEAD 是否已含你的改动；`git rev-parse HEAD` == `git rev-parse origin/main`
  确认已 push。
- 若 HEAD 已含改动且本地==远程，任务已完成，**不需要再 commit**。
- 教训：在这个 repo 编辑源码时，若正好临近 cron 触发时刻（每日 11:00 / 周六 11:00），
  work-tree 改动可能被 cron 顺带提交——这是正常的，不是丢失。

---

## 4. Vision 后端故障时的图表验证

本 VM 的 `browser_vision` / `vision_analyze` 后端偶发全故障（HTTP 400）。
此时**不能靠肉眼确认 SVG 布局**。替代方案：
1. 程序化解析 SVG（正则抽 text/line/circle 坐标）断言无溢出/无重叠/元素齐全（见上）。
2. `browser_navigate` file:// + accessibility snapshot 确认 `<a>` 链接实体在位。
3. 把 `browser_vision` 拍下的 `screenshot_path`（即使分析失败也存了图）用
   `MEDIA:<path>` 发给用户亲自确认视觉。
