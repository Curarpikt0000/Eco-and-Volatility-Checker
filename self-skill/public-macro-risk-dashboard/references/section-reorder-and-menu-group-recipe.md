# 板块物理挪位 + 菜单分组 + 接线补完（2026-10-10 实战）

场景：Chao 要把散在页面各处的同主题板块（如金银 21 项）连成一段，并在左侧菜单成组。

## 1. 先查事实再提方案
- 菜单由 `.part-title`（带 `.part-num`）自动生成，**严格按 DOM 顺序渲染**（10-06 为消除「跳动感」定的）。分组只是相邻 section 的小标题，所以**想让菜单成一组 = 必须物理挪位**，只改关键词没用。
- 提议前用脚本列出各板块当前位置序号（本次发现金银散在 27~35/40~43/54~62 位）；提议里的数量以脚本计数为准——曾口头说 24 实为 21，后又因其中 1 项未做实为 20，**清单数字报前先数**。
- 他回「按这个顺序」后再动手；清单里没让他看过的项别擅自加。

## 2. 纯文本搬运脚本（dashboard.py 模板里每个板块 = 注释行 + part-title 行 + card 行）
- 找 `class="part-title"` 且含 `part-num` 的行号为锚；向上吞并紧邻的 `<!-- ... -->` 注释行作为块头；块尾 = 下一块头（最后一块到 `class="footnote"` 前）。
- 按目标顺序重排，**断言 `sorted(新行)==sorted(旧行)` 且行数相等**（证明只搬不改），标题用 `re.sub('<[^>]+>','',行)` 匹配；每个关键词必须 `len(匹配)==1`。
- 先 `cp dashboard.py /tmp/xxx.bak`。

## 3. 菜单分组（sidenav 脚本里的 GROUPS）
- 新组放 GROUPS **数组最前**（首个命中优先），含全部新成员关键词。
- 挪完必须在构建页里读 `.sn-group` 看实际分组：我首轮留下「跨资产与金银」只剩 WRS 1 项的碎组。修法=删该组、把非主题成员（WRS→国债流动性观测、机构研究报告→改名「实体、AI 与研报」）并到相邻组。**目标：不出现 1 项碎组**；剩下的「（续）」段不在授权范围就报告不动。
- 验收三件套（playwright 一次取）：分组名+数量、`菜单 href 序列 === DOM part-title id 序列`、pageerror=0。

## 4. 「函数写好了」≠「上线了」：接线三点
新板块要同时有：①模板里的 `part-title`+`<div class="card">{xxx_html}</div>` ②`build_dashboard.py` 里 try/except 调抓取函数 + `gen_kwargs` 传参 ③`generate()` 形参与 `xxx_html=_xxx_html(...)`。本次短线图缺 ①② 却已有缓存文件+渲染函数，**会误以为已接好**。核对法：grep `{xxx_html}` 在模板、`xxx=` 在 build_dashboard。cron 提示词里只要写明调用 `build_dashboard.py` 就无须改 cron（grep jobs.json 确认）。

## 5. 更快的验证法（对比 isolated-full-build 的重配方）
- 整站 ISO 构建约 9 分钟：`rsync -a --exclude .env --exclude .git --exclude .venv --exclude scratch ./ /tmp/eco_iso_x/`，用项目 venv 后台跑（`terminal(background=true, notify_on_complete=true)`）；`timeout 280 cmd` 前台跑会被杀(exit 124, 日志 0 字节)——别用。进程可用 `process_manage wait`(单次上限 180s)循环等。
- 只改了单个板块内部（标签/默认文案）时，**不必再跑整站**：`cd src && ../.venv/bin/python -c "import json,dashboard as d; open('/tmp/x.html','w').write('<meta charset=utf-8>'+d._xxx_html(json.load(open('../data/xxx_cache.json'))))"`，playwright 打开该文件验 pageerror、截图。报告里如实写「最后改动只单独渲染验证」。
- 板块集合对比：生产 `docs/index.html` vs 新页 part-title 集合，生产有新页无必须=0；多出的应恰好=未发布新板块。我的 JS 计数比口径 66 多 1（67/68），未查来源，别拿计数去和口头数字硬对，用集合差。
- 浏览器验证优先 `python3 playwright`（系统有 chromium 缓存）；`browser_exec` 在本机可能起不来 daemon，别耗时。
- 窄屏溢出要区分来源：遍历 `right>innerWidth` 的元素，看是否在新板块内（`closest('#sec-xxx')`）；新板块 0 溢出而溢出来自老板块（表格/徽章）→ 报告但不顺手改。

## 6. 图表小坑
- SVG 首个 x 轴日期标签居中会被左边界裁掉 → 首个用 `text-anchor=start` 并带年份 `YY-MM-DD`，其余 `MM-DD`。
- 悬停读数位空白时给默认提示文案，否则视觉检查会判成「空组件」。
- Yahoo 日线 `period1` 取 ~1250 天保证 1 年窗口内 200 日线完整；中国 ETF 日线晚一天是数据源未出，标出不替换。
- 中国矿企「指数」(申万有色/国证有色)源只返回当天 1 行画不了均线 → 用 ETF 代替并在页面注明。

## 7. 提交纪律
- 先 `git diff --stat` + grep 新增函数名确认 external_data/build_dashboard 里没夹带无关改动，再**只点名**文件 add；untracked 的新缓存 json（如 fed_gold_oil_cache.json）要单独 add，否则线上首次构建无缓存兜底。
- push 后 `git status -sb` 显示 `main...origin/main` 无 ahead 才算同步。
