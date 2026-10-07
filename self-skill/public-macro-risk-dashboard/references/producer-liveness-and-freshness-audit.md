# 「图标每日更新、cron 也 ok、数据却停了」——上游生产者存活核查 + House 口径 + 菜单顺序根治 (2026-10-06 实测)

## 现象
Chao 发 GLD/SLV 周净流量图:「明显没有每日更新」。日报 cron 每天 `ok`,页面照常渲染,**20 天没人发现**。

## 根因类型:读「别人产出」的板块
`fetch_comex_inventory` 原本 curl 外站 `comex-inventory-charts.pages.dev`,站内最后一天停在 09-16。
外站生产者是**另一台机器(Mac)上的 cron + 写死 `/Users/...` 路径的脚本**;本机 jobs.json 没有它。
日报只证明「读到了页面」,没证明「页面是活的」。
**判据**:凡 fetcher 读 ①外站 URL ②别的项目产出的 data/*.json ③agent 写的 manual_overrides,
必须单独核「生产者是谁、在哪台机器、最近一次产出时间」。「进了 cron」≠「数据是活的」。

## 查法(按顺序)
1. 现场读源头最后一个数据点日期(不是页面里出现的任意日期)。
2. 找生产脚本:`search_files` 限定 `~/.hermes/scripts` 与姊妹项目目录;全盘 `grep -r ~/Projects` 会超时。
3. 查 `jobs.json` 有无对应 cron;脚本里有无写死他机路径。
4. Notion 库 `last_edited_time` 只能证明「有东西还在写库」,写入者常是同一机器人账号,**分不出哪台机器**,
   别据此断言「Mac 还在跑」(我曾说错,已更正)。

## 接管方案(Chao:「你都拿过来做」)
- 外站三脚本 vendoring 到 `tools/<name>/`,路径参数化(环境变量 `INV_BASE`),**对 Notion 纯只读** → 与另一 agent 写库不撞车;
  接管后不推外站,改 fetcher 内本地自产。
- fetcher 三级回落:本地自产 → 外站 → 缓存;原因写进 `note`,不静默。不改 cron prompt(日报本来就调 build_dashboard.py)。
- 滑动窗口使图最左端比旧站短不是数据错;缺本地历史底表(SGE)用 Eco 自有缓存按日期合并,合并前核共有日期值 0 不一致。

## 隔离审计副本(跑 `tools/freshness_audit.py` 这类会调用全部 fetcher 的脚本)
- rsync 到 /tmp,排除 `.git .venv scratch docs dashboard`;副本含 `.env`(600),用完整目录删除。
- **先把 `notion_writer.upsert` 改空操作,并在 `_req` 拦截一切非 GET、非 `/query` 的请求**。只拦 upsert 不够。
- `tools/freshness_audit.py` 已有(40 个 fetcher、声明频率+容忍天数、OK/WATCH/STALE/NO_DATE),先用它。
  它不覆盖约 20 个板块(KOL、机构研究、COMEX 期权、ETF 期权波动率、WRS、AI 算力、货运等),
  且「返回了日期」≠「真数据日」,STALE 项必须回源头核对。
- 60 个 fetcher 机械分类:22 个不联网(只读文件,风险最高)、24 个写本地缓存、9 个写 Notion/起子进程。

## 数据缺口 ≠ 解析错
周净 issue/stop 缺日:Notion 行 `Parse Status='OK (stock)'` 只写库存、无 `[Delivery]` 段(上游采集缺口,周四尤多)。
展示层诚实:每根柱悬停写实际交割日数;不足 5 天且该周已过完 → 浅色虚线柱+页脚统计;标题天数用各周实际日数之和(别用历史 PDF 数,会漏增量日)。

## House / Customer 口径(Chao 铁律:做市商图只要 House)
- 席位名后 `(H)`=自营、`(C)`=代客;Notion 通道 08-21 起才有标记,06-06~08-20 无标记 → 记 `U`,**不假装是 H**,整周留白(None,浅灰细线占位),页脚写明。
- CME PDF 通道 `org` 列早就有 C/H,聚合时被丢;JPM 等 1~6 月几乎全是 C,改 House 口径后历史曲线形状会大变,提前告知。
- 验证:用**另写的独立逻辑**算若干周 H 值与新代码逐周对账(12/12 一致才算数);渲染后断言旧含 C 数值零残留。
- 结论级影响要点出:黄金 09-28 周 含 C=−1970(「囤货看涨」),只算 H=+805(净发货),符号反了。
- 代码里「C/H 已捕获但暂不落盘」这类 NOTE 就是线索,看到要追问口径。

## 菜单顺序≠页面顺序(跳动感)根治 + 本地无头验证
根因:菜单把同组成员(相距几十屏)合并成一组,scrollspy 用 DOM 序号 → 页面 y 倒退;Eco 64 板块实测 3 处。
根治:菜单严格按 DOM 顺序渲染,分组只当小标题:连续同组一个标题,被隔开则第二段加「（续）」,无关键词命中并入相邻段,
夹在同组两侧的孤立离群项并入两侧;误归关键词移除、新增组收「其他」。代价:组标题变多(15 个),要如实告知。
验证(不依赖用户开着的页面、不整站构建):
1. 取 `docs/index.html`,`</body>` 前注入探针(load 后 2.5s 采集 `.part-title` 的 id/标题/top+scrollY 及 `#sidenav-links` 各 `<a>` 的 href/组),写进 `<pre id=PROBE>`。
2. `chrome --headless=new --no-sandbox --disable-gpu --window-size=1400,900 --virtual-time-budget=12000 --dump-dom file://...`,正则取 PROBE,`html.unescape` 后 json.loads。
3. 断言:菜单项数==板块数==64、href 无悬空、**页面 y 倒退次数==0**、菜单 id 序列==DOM id 序列;先对旧页跑确认能抓到 3 次倒退。
4. 新脚本从 `dashboard.py` 模板切出(f-string `{{ }}`→`{ }`)替换进现有 docs 页再探测。
小坑:验证脚本别混入一次性「删死代码」步骤,二次运行 `substring not found`,产物是旧的却像成功;先 `assert` 新代码确在。

## 沟通纪律
Chao 常用「1 同意 2 A 3 ok」压缩回复答前一轮多个问题:先对号入座,对不上再用 clarify 复述确认,不要把已答的问题原样再问一遍。
公司 pre-commit 钩子需 `ussh` 证书:过期时提交报 `no ssh cert is found`,不绕钩子,请 Chao 刷新后同命令重试。
