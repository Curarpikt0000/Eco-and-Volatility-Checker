# 发布前重建:只读 Notion 守卫 + 隔离构建陷阱(2026-10-14 实测)

## 隔离副本构建不能直接发布
`/tmp/eco_iso_re`(rsync 排除 .env)整站构建约 9-10 分钟,适合验证新板块,但**读不到 Notion**:
依赖 `fetch_china_liquidity()`(ECON_DB['pboc'])的「中国央行流动性/ETF 份额/两融」会变「未就绪」或空图。
→ 隔离页只用来验收,**发布一律用项目目录(带 .env)重建**。线上页 cron 每天 11:00 本来就带全量。

## 想「重建但不写 Notion」:运行时替换 _req(不改源码)
构建流程里有写 Notion 的调用(`ed.write_stress_panels_notion` / `write_ofr_notion` 等,走 `notion_writer._req`)。
包装脚本思路:先 `import notion_writer as nw`,把 `nw._req` 换成守卫(GET 放行;POST 且路径以 `/query` 结尾放行;其余 PATCH/DELETE/POST 返回 `(403, {})` 并计数),
再 `import external_data as ed; ed._req = guard`(它是 `from notion_writer import _req` 绑定的副本,必须导入后再覆盖),
最后 `runpy.run_path('src/build_dashboard.py', run_name='__main__')`。结束打印「放行读 N 次/拦截写 M 次」作为「没写 Notion」的证据。
先对假 `_req` 自测守卫(6 种请求),再跑真构建。前提:grep 确认 external_data 里没有绕过 `_req` 的直接 requests 写调用。
代价:被拦的最新值(国债压力/OFR)当天不入 Notion,次日 cron 补写,汇报时写明。

## 发布前核对清单(每次)
1. 板块标题集合与旧页对比:丢失=0、新增=预期。`未就绪` 计数不高于旧页。
2. playwright 开本地 file://:`pageerror` 为空;菜单 href 序列 == DOM 板块 id 序列。
3. 红线 grep(ghp_/sk-/ntn_/AKIA/SAPISID/LOGIN_INFO)0 命中。
4. 发布前备份旧页;`publish_cf_pages.sh eco-volatility-checker <abs docs/index.html>` → `scripts/publish_vibe.sh`。
5. curl 读回线上,sha256 与本地 docs/index.html 一致,再 grep 新板块标题。
用户说「发布吧」才发;「允许」类批复要对准他批的具体问题(这次是「允许带 .env 重建、Notion 只读」)。
