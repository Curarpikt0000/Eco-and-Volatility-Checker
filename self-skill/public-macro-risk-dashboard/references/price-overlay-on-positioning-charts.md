# 给持仓/COT 类图叠加价格（双轴 + 混频悬停）

Chao 常要求「在这张图上叠加 X 价格走势」（2026-09-25 白银做市商净持仓图，样板 `_silver_net_price_svg`）。

## 数据
- Yahoo chart API v8 直连（`SI=F`/`GC=F`/`PL=F`，`range=10y&interval=1d`，带 UA）。
- 在 fetch 函数里一并抓，写进同一缓存 JSON（`price`/`price_status`/`price_source`）；<20 点就读上次缓存标「缓存」，价格与 COT 互不拖累。
- 价格裁到 COT 起点之后。

## 渲染
- X 按真实日期序数映射（日线/周线密度不同，不能按索引）。
- 左轴持仓（零轴+「净持仓 0」标注+淡面积），右轴价格；刻度用各自线色。
- 图例加半透明底色 rect 防压线。
- 悬停：每个价格日一条 `_hover_bands`，内容＝当日价格＋截至当日最近一期持仓（as-of 不插值），写明「截至 YYYY-MM-DD」。
- 旧单线实现保留为 fallback。

## 交付时要提醒
- 右轴被近期极值撑开时，早年价格线会被压平，写出实际区间。
- 双轴交叉点无含义。

## 自检（不用等 8 分钟全量构建）
把渲染函数输出包成单独 HTML，用 playwright 缓存的 headless shell 截图再 vision 看版面：
`~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell --no-sandbox --window-size=1220,720 --screenshot=/tmp/x.png file:///tmp/x.html`
