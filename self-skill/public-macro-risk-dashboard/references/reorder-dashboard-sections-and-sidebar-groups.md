# 重排 dashboard 板块 + 左侧菜单分组(2026-10-10 实战)

场景:Chao 要把散在页面各处的同主题板块(如金银板块)物理挪成连续一段。

## 流程
1. 先枚举页面全部顶级板块(src/dashboard.py 模板里 class="part-title" 且含 part-num 的行,约 66 个),列出同主题板块散在哪几段,给 Chao 最终顺序清单,等他回「按这个顺序」才动手。
2. 板块在模板里是「注释行 + part-title 行 + card 行」三行一块。用 Python 搬运:向上吃连续 <!-- --> 行得块起点 → 按块重排 → 断言 sorted(new_lines)==sorted(old_lines) 且行数相等(纯搬运证明)。先备份 dashboard.py 到 /tmp。
3. 菜单分组在 dashboard.py JS 的 GROUPS 数组(first-match-wins):新组放最前,match 用板块标题子串。菜单严格按 DOM 顺序,连续同组一个标题,被隔开则「（续）」。
4. 避免 1 项碎组:被挪走后留下的孤儿并入相邻组,删掉不再需要的旧组。
5. 隔离验证:rsync 项目到 /tmp/eco_iso_re(排除 .env/.git/.venv/scratch),跑 python src/build_dashboard.py(约 9 分钟,联网,必须 background=true+notify;前台 timeout 会静默 124 且日志为空);再用 python playwright 本地 chromium 开 dashboard/index.html 检查:pageerror=0、菜单 href 顺序===DOM 顺序、各组计数、与线上 docs/index.html 标题集合对比(差集应只含未发布新板块)。
6. browser_exec daemon 起不来时直接用 python playwright(~/.cache/ms-playwright 有 chromium)。

## 坑
- 标题计数脚本可能比 Chao 说的多 1,口径不同要如实说明,别硬凑。
- 清单若含尚未做的板块,实际挪位数少 1,汇报如实写 20+1。
- dashboard.py 常同时带别的未提交改动,提交前提醒 Chao 同文件混有其他板块改动。
