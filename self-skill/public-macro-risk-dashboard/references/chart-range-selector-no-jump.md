# 看板图加「时间段选取」且页面不跳动

来源：Eco-and-Volatility-Checker 比特币÷黄金、股指÷黄金两张图（2026-10）。Chao 要求「左边 menu 和右边的图不要有跳动感」。

## 实现要点（已实测页面位移 0px）

1. 数据内嵌 JSON（`<script type="application/json">`），页内 IIFE 绘图，按钮只改状态后重绘 SVG。Python 端 `json.dumps(...).replace("</","<\\/")` 防脚本截断。
2. **容器高度写死**：图区 380px、信息条 38px、事件表 360px+`overflow-y:auto`、多面板容器 640px+`overflow:hidden`。切换/开关/悬停/点击只替换容器内部。
3. 关掉一个面板时容器不能变矮：第一版用 `min-height`，关一个面板下方内容位移 8px；改固定 `height`（量好全部面板打开时的高度）才归零。
4. 区间统计量（中位数/峰值/谷底/分位）按所选区间重算，并在图下说明里写明；否则同一个「今日值」在不同区间分位不同会被当 bug。
5. **分位口径先读旧后端算法再对账全期值**：旧版用「今日收盘值」在月值序列里排位；我一度用「最后一个月的月值」，全期差 0.2 个点（50.3 vs 50.5）。
6. 对数轴短区间刻度：用 1/1.5/2/3/4/5/7×10^k，相邻刻度像素间距≥22，否则 10 年图只剩 1~2 条刻度。
7. 区间中位数文字右对齐、控件与图左右留 6px；`<input type=month lang="zh-CN">` 实际显示语言取决于浏览器，VM 上验不了，如实告知。

## ★验证位移：Playwright 点击前会自动滚页面 → 假警报

`page.click()` 在按钮不在视口内时先自动滚动，读到「位移 873px」。判别法：
- JS `el.click()`（不经鼠标定位）+ 挂 `scroll` 监听日志；日志为空 = 页面本身没滚。
- 真实姿势复测：先把板块滚到视口中部，再用 `page.mouse.click(x,y)`（x,y 来自 getBoundingClientRect），位移应为 0。
- 一次量齐：`scrollY / 板块 top / 板块高 / 下一个 card top+scrollY / documentElement.scrollHeight / #sidenav.scrollTop / 侧栏高亮文字`；另匀速向下、向上各滚过板块，高亮序列应对称无回跳。

## 省时流程
整页构建约 8 分钟（必须后台跑）。先用 `dash._xxx_html(...)` 渲染片段 + 复制站内 `<style>` 拼只含该板块的测试页，在测试页迭代并量位移；最后才跑整页构建，再用真实页面复测。拼测试页 CSS 时 f-string 的 `{{ }}` 要还原成 `{ }`。

## 截图只作线索
vision 会把「长截图拼接伪影」「控件换到第二行」说成缺陷。一律用 DOM 测量（getBoundingClientRect / 元素是否在图范围内）证伪后再改代码。

## 相关（用户自有 skill，不能由后台改）
`html-dashboard-sidebar-scrollspy` 的「验证法」一节建议补上「Playwright 自动滚动假位移」；需 Chao 执行 `hermes curator adopt html-dashboard-sidebar-scrollspy` 后才能补。
