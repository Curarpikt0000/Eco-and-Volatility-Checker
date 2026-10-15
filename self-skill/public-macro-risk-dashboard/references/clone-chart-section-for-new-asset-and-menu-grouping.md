# 克隆一个已有图表板块给新资产类(铀=金银短线图的孪生) + 菜单分组坑 (2026-10-14 实战)

## 1. 克隆而非手写
- 需求「也给 X 做同样的短线图」→ 先看已有渲染函数是否通用(`_gs_tech_html`:每标的一图=收盘+MA20/50/200+上方 RSI14,窗口按钮,悬停读数)。通用就**程序化克隆**:读 dashboard.py 源码切出函数体 → `replace('def _gs_tech_html','def _ur_tech_html')`、`gst-`→`urt-`、`.gst`→`.urt`(元素 id 与内嵌 JS 的全局名同页冲突,前缀必须全换)→ 单独改「口径」整句 → 写回。不要手敲 100 行 SVG/JS。
- 采集器同理:`URANIUM_TECH_SYMBOLS=[(代码,名,分组,说明)]` + 复用 `_gs_sma/_gs_rsi`;单标的失败回旧缓存标「缓存」,绝不空覆盖。
- 接线 5 处:external_data 采集函数 / dashboard 渲染函数 / 模板 `<div class=part-title id=sec-xxx>`+`<div class=card>{xxx_html}</div>` / generate() 形参+`.format` 传参(新增 `ur_tech=None` 与 `ur_tech_html=`)/ build_dashboard.py try-block 取数+`ur_tech=ur_tech` 传参。generate 门禁会数形参:构建日志 `✅ 门禁: generate() 全部 N 个数据形参均已传入` 的 N 要 +1。
- 先 Yahoo 实测候选标的(24 个里 SPUT.TO 404、UX=F 仅 1 根=铀现货无免费日线;实物铀信托用 SRUUF 与 YCA.L 代理)。**页面口径句必须写明「代理价≠现货」**。

## 2. 菜单分组:新板块别插进别组成员之间
- 菜单严格按 DOM 顺序渲染,分组只是「相邻 section 的小标题」;**没命中关键词的板块并入相邻组**,「孤立离群(夹在同一组两侧、自成一组且只 1 项)会被并回两侧那组」。
- 我第一次把铀板块插在「金银短线图」与「金银回调」之间 → 菜单里铀被吞进「黄金白银 22」,还把黄金白银段切开。**正解:放在目标连续段的末尾(或段外),使它两侧不是同一组**;修后菜单出现独立「铀 1」组。
- 菜单 GROUPS 在 f-string 模板里:花括号写 `{{ name: '铀', match: ['铀与铀矿企'] }},`(双花括号)。插入新组时**按行尾 `}},` 之后另起一行**,别在上一组的 `]` 后用 `str.index('}')` 插(会插进该行中间,JS 对象被破坏,语法检查 ast.parse 查不出,只有页面里菜单异常才暴露)。
- 验证用无头浏览器读 `.sn-group-hdr` 文本(组名+计数)与 `#sidenav-links a` 顺序 == `.part-title` DOM 顺序。
- 挪板块用脚本:摘出整块(注释+part-title+card 共 6 行)→ 插到目标板块的「下一个 part-title 之前」(含其前置注释行)→ 再 ast.parse + 检查 `sec-xxx` 只出现 1 次。
