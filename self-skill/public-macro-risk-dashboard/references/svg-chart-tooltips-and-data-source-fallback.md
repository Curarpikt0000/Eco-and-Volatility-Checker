# SVG 图表 hover tooltip + 数据源失效兜底

本项目 dashboard.py 的所有图表都是**手写 SVG**（不是 Chart.js，radar 除外），逐点用
`<rect>`（柱）/`<polyline>`（线）/`<circle>`（标记点）拼出。两类高频运维任务的做法。

## 1. 给「所有图」统一加 hover tooltip（显示横纵坐标）

Chao 会要求「鼠标指到折线的点或柱子上，显示这个点/柱的横纵坐标，所有图都要」。
逐个数据元素手写 tooltip 不可行（21 个绘图函数、几百个元素）。正解 = **全局委托机制 + 数据元素塞 `data-tip` 属性**，一次基础设施改动 + 每个绘图函数循环处加一行。

### 基础设施（改一次，注入到 HTML 模板）
dashboard.py 的页面模板是 **`.format()` 字符串**（不是 f-string）——所有字面花括号必须双写 `{{ }}`，否则 build 时 `.format()` 报 KeyError。改动点：
- **CSS**：`</style>` 前加一个 `#chart-tip` 固定定位浮层（莫兰迪深底 `rgba(58,54,47,0.96)` + 琥珀边）、`.tip-d`（日期灰）/`.tip-v`（值粗体）、`[data-tip]{{cursor:crosshair}}`、`circle.tip-hit{{fill:transparent}}`（透明 hover 圈，hover 时淡染）。
- **JS**：`</script>` 前加一个 IIFE，事件**委托**在 `document` 上监听 `mouseover`/`mousemove`/`mouseout`，`ev.target.closest('[data-tip]')` 命中才显示。tooltip 内容格式约定 = `"横坐标||纵坐标"`，JS 按 `||` 分隔成两行（日期行 + 值行）。浮层跟随鼠标，靠右/靠顶时自动翻转避免出屏。

### 每个绘图函数的挂载（两种元素两种做法）
- **柱状图（`<rect>`）**：直接在生成 rect 的循环里加 `data-tip="{{日期}}||{{值}} {{单位}}"`。rect 面积大，天然好 hover。
  ```python
  _tip = f'{_esc(p["date"])}||{vals[i]:.1f} 吨'
  parts.append(f'<rect ... data-tip="{_tip}"/>')
  ```
- **折线图（`<polyline>`）**：polyline 是一整条线，**无法逐点 hover**。必须在每个数据点位置额外画一个**透明宽 hover 圈** `<circle class="tip-hit" r="7" data-tip=...>`（r=7 给足命中面积，CSS 设 fill:transparent）。在画完 polyline 之后遍历该 series 的点插入：
  ```python
  _unit = (panel.get("unit_left","") if axis=="left" else panel.get("unit_right","")) or ""
  for p in spts:
      _tip = f'{_esc(s["name"])} · {_esc(p["date"])}||{p["v"]:.2f}{_unit}'
      parts.append(f'<circle class="tip-hit" cx="{X:.1f}" cy="{Y:.1f}" r="7" data-tip="{_tip}"/>')
  ```
  双轴图注意：单位要按该 series 的 `axis`（left/right）取对应 `unit_left`/`unit_right`。

### 样板先行
大改（21 函数）先只改 **1 个柱状图 + 1 个折线** 做样板，build + 浏览器实测 hover 生效，再全量铺开——符合 Chao「大改先跑 1 样板验收」硬规则。验证靠 build 出的 HTML 里 grep `data-tip=` 计数 + 浏览器 hover（vision_analyze 常 400，靠 DOM 计数 + 截图发用户人眼确认）。

### 复查/回归审计（2026-09-25 实战：Chao 第二次要求「所有图 hover 至少显示横纵坐标」）
- **新增图的人常忘挂 data-tip**：首轮全量铺开后又新增了 9 个绘图函数（WRS/国债微观/DXY-金/WGC ETF/贵金属期权/COMEX 期权持仓/全球货币/COT MM/官方vs私人）全漏。
- **审计脚本**：`scripts/audit_chart_tooltips.py <built.html>`，BeautifulSoup 逐个 `<svg>`（viewBox 宽≥100 且数据元素≥4）数 `[data-tip]`，输出 0 tip 的图。★lxml 会把 `viewBox` 小写成 `viewbox`，要两个都读，否则审计出「0 张图」假阴性。
- **原生 `<title>` 不算合格**：延迟 ~1s、样式不同、多线图只显一条；一律改 data-tip。
- **通用补法 `_hover_bands(xs, tips, top, height, x_min, x_max)`**（dashboard.py 里）：每点一条透明全高竖条，边界取相邻点中点；多线图 tip 里用 `&lt;br&gt;` 同时列出当天各序列值（JS 遇 `<br>` 自动切多行样式）。混频图（日价+周持仓）按 as-of 取「截至当日最近一期」并在 tip 里注明截至日，不插值。
- **构建耗时 ~8 分钟**：前台 terminal 420s 会被杀（产物仍是旧的、日志只到一半），必须 `background=true, notify=true` 跑，完成后再审计。

### 截图自检：无头 Chrome 渲染单个图（不用等 8 分钟全量构建）
把渲染函数的 HTML 输出写进 `/tmp/x.html`（外包 `<body style="background:#f4efe4;width:1200px">`），再用 Playwright 自带的无头 Chrome 可执行文件直接截图：
`~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell --no-sandbox --disable-gpu --window-size=1220,720 --screenshot=/tmp/x.png file:///tmp/x.html`
然后用 vision_analyze 看版面（线是否可见、图例是否压线、零轴有无标注）。用 venv 调渲染函数前先单测 `data-tip` 内容（用 re 提取），再跑全量构建。

## 1b. 在已有单序列图上「叠加价格」（Chao 常见需求：「在这张图上叠加一下 X 价格走势」）
2026-09-25 实战：白银做市商 COT commercial 净持仓图（原来走通用单轴 `_yield_curves_svg`）叠加白银价格。做法：
- **抓数侧**：在该 section 的 fetch 函数里加价格，用 Yahoo chart API v8 直连（`SI=F`/`GC=F`/`HG=F`，`range=10y&interval=1d`，带 UA），存进同一个缓存 JSON 的 `price` 字段 + `price_status` + `price_source`。价格抓不到（<20 点）就读缓存 JSON 里上次的 `price`，并标注「缓存」；绝不留空，也不编数。价格和主数据的抓取互不影响。
- **渲染侧**：新写一个专用双轴 SVG（左轴=原序列，右轴=价格），不要硬塞进通用单轴 helper；价格数量 <20 时回退到原图。按真实日期序数算 X（周度和日度混排，不能用序号）。刻度文字颜色跟各自的线一致；零轴加文字「净持仓 0」；图例加半透明底色 rect，免得压线。
- **悬停**：每个价格日一条 `_hover_bands`；tip = 价格 + 截至当天最近一期的周度值（多/空）+「截至 YYYY-MM-DD」。
- **标题 + 说明行**：标题加「× 白银价格」，说明行加最新价格、日期和数据源。
- **回复里要说清楚的口径**：双轴图里线交叉没有含义；右轴要容纳尖峰，所以早年的价格线会被压平（给出那段的实际区间）。
- 交付前核对：tip 里最新值是否和用户截图里的数字一致（本次 −42,700 / 多 31,827 / 空 74,527）。

## 2. 指数数据源失效兜底：yfinance `^MOVE` → Yahoo chart API v8 直连

**症状**：图例四个统计值（现/高/低/中）全一样（如「现74.98 高74.98 低74.98 中74.98」），折线画不出来——因为只抓到 **1 个数据点**，1 点无法连线。

**根因**：yfinance 库对某些指数（`^MOVE` 等）从某时点起只返回**当日 1 个点**（Yahoo 库层面的限制/反爬），历史全丢。这是**库**的问题，不是数据不存在。

**修复**（通用，适用很多 Yahoo 指数）：绕开 yfinance 库，直接 curl **Yahoo chart API v8**（带 UA header）：
```
https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE?range=3y&interval=1d
```
（`^` 需 URL-encode 成 `%5E`）。返回 JSON 里 `chart.result[0].timestamp[]` + `indicators.quote[0].close[]` 就是完整历史。requests 实现时务必带 `User-Agent`（否则 401/空）。实测 `^MOVE` 3y range 拿回 700+ 个真实点。把 `_fetch_move_history` 改成**优先 chart API 直连、yfinance 降级备用**。

**判定原则**：折线消失/图例统计值全等 = 先怀疑「只抓到 1 点」的数据源问题，不是绘图 bug。chart API 直连比 yfinance 库稳，是 Yahoo 系指数的首选取数方式。

## 3. 独立纵轴配色呼应
双轴图（如①美债收益率与波动性：左轴 MOVE / 右轴收益率%）Chao 要求「某个轴单独一个颜色」时，把该轴刻度 `<text>` 的 `fill` 设成该轴专属序列的颜色（如左轴专属 MOVE → 用 MOVE 线的红褐 `#c17d6a`），跟线色呼应、与另一轴区分。注意 `_stress_panel_svg` 被 4 张四联图共用，改左轴颜色对每张图各自取其左轴序列色即可（自动合理）。
