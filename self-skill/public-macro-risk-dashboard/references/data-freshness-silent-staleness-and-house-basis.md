# 「cron 标 ok」≠「图是活的」：静默停更排查 + House 口径（2026-10-06 实战）

Chao 连发三张截图说「这个图没有每日更新」。三张的根因完全不同，先分类再动手。

## 0. 方法：别信页面最新日期，逐板块回源头
- 日报 cron 的 `ok` 只证明脚本跑完，不证明数据新。三种静默停更都实测过：
  1. **上游生产者停了，我们只读它的成品**（COMEX 库存/GLD/SLV 图读 `comex-inventory-charts` 站，站自 09-16 起没更新，生产脚本写死 Mac 路径 `/Users/...`，cron 在另一台机器）。
  2. **源头换了发布格式，解析器抓不到新文件但不报错**（JPX 投资部门别周报，见 §2）。缓存文件每天被重写、内容不变。
  3. **源头本来就低频**（FRED 季度序列、BIS 年报、TIC 滞后 2 月）——不是故障，但页面若标「每日更新」就是展示欺骗。
- 现成工具：`tools/freshness_audit.py`（40 个 fetcher，各带声明频率+容忍天数，输出 OK/WATCH/STALE/NO_DATE/INTERNAL_MISMATCH）。**先跑它，别重造**。STALE 必须再回源头核；`INTERNAL_MISMATCH` 多是未来拍卖日/年末标记被当数据日（审计脚本抠日期的缺陷）；`NO_DATE` 多是日期藏在 `('2026-07', 值)` 元组里。
- **隔离跑审计**：整目录 rsync 到 `/tmp`（排除 .git/.venv/docs/scratch），副本里把 `notion_writer.upsert` 改空操作，并在 `_req` 里只放行 GET 与 `POST …/query`，其余写一律拦截并记日志。fetcher 里 `write_*_notion`（auctions/m2/custody/stress/ofr）会写生产 Notion，隔离构建/审计前必须先关。副本会带 `.env`，用完整目录删除。
- 判「谁在写 Notion」：本机与另一台 agent 共用同一个机器人账号，last_edited_by 分不出机器。只能说「Notion 里今天有新行」，**不要断言「Mac 上 cron 还在跑」**。
- 找生产者：`jobs.json` 里没有 ≠ 没人在跑（可能在别的 VM）。读项目 AGENTS.md 的 cron 表，并看脚本里写死的绝对路径。

## 1. 接管「读别人成品」的图
- 把上游脚本拷进 Eco `tools/<name>/`，路径参数化（环境变量 `INV_BASE`），对 Notion **纯只读**（避免和另一 agent 撞车）。`fetch_*` 内部：本地自产 → 失败回落旧站 → 再失败回落缓存，回落时把来源写进 note，不再静默。
- 这样**日报 cron 的 prompt 不用改**（它本来就调 `build_dashboard.py`），不触发「改 cron 要批准」。
- 历史存档缺失（如 `sge_history.json`）：用项目自有缓存按日期合并保住点数；对账「共有日期值不一致 = 0」后再用。
- 周图最后一根柱常是未满周（只有 1 天）：标「本周进行中，已有 N 个交割日」；不满 5 天且该周已过完标「仅 N/5 天，数值不完整」并用虚线浅色柱。

## 2. JPX 外资周流停在旧周（解析器过时）
- 现象：`foreign_flow_japan` 停 09-11，缓存每日被重写。
- 根因：JPX 自 9 月第 3 周起改发 `stock_1_w_YYYYMMDD_YYYYMMDD.xlsx`（只在 index.html，不在存档页；周范围在**文件名**里；横向 14 个投资者块，海外投資家「差引 Balance」在 col21，旧 xls 在 col6）。
- 修法：保留旧路径，另扫 index 页新格式；定位用 row3 含「海外」的起始列 +2；Prime 金额行取「東証プライム」下一行 Value；**自洽校验 买−卖==差引(±2)，不符丢弃**；单位以 PDF 页眉「千円 1,000 yen」核对=旧表同单位（/1e9→万亿日元）。
- 验证：旧 51 点 0 丢失 0 变化；新增两周用**不经函数的独立读法**再算一遍一致。index 页每个文件的 href 前缀不同（`vk0khi…-att/`），必须用页面原 href，自拼 URL 会 404，且 404 响应体不是 xlsx（`Excel format cannot be determined`）。

## 3. 「只要 House，C 不要」口径（COMEX 做市商周净 issue/stop）
- 交割明细里 `(C)` 代客、`(H)` 自营是**两笔不同性质的交割**，不能加总。原脚本把 C/H 捕获了但丢掉，致黄金 09-28 周 −1970 实为 H +805（符号反转）。
- 标记来源：CME PDF 的 FIRM ORG 列（PDF 段全有 H/C）；Notion 增量段 `(C)/(H)` 自 08-21 才有，06-06~08-20 为「无标记」。
- 处理：`org` 保留为 H/C/U（U=无标记），聚合只累计 H；**U 不假装是 H 也不当 0**——全周都是 U 的周输出 `blank=True`、数值 None，图上画浅灰细线+悬停说明，页脚写留白周范围。
- 对账：另写一份独立逻辑算金银各 6 周 H 值，与新代码逐周比，12/12 一致才提交。PDF 与 Notion 两段无重叠日，只能证明 org 语义一致（如 JPM 几乎全 C），无法逐笔证两段 H 同口径——汇报时要说。
- 口径变更后 PDF 段整体形状会明显不同（旧曲线主要由 C 推动），**事前告知**。
- 同日抓到的上游缺口：Notion CME 库自 08-20 起几乎每个周四只有库存（`OK (stock)`）无 `[Delivery]`，原因未知，不是我们解析错。

## 4. 验证清单
- 悬停/标注类改动：用上游同一份干跑 JSON 喂 `dashboard._xxx_html()`，查 div 开闭平衡、旧错误数值零残留、悬停文本；再无头 Chromium 截图给 vision 描述（数字以数据为准，vision 是估读）。
- 提交前红线扫描用显式文件列表，不用 `git add -A`；`.gitignore` 里本轮之外的遗留行先看清再决定带不带。
- 公司 pre-commit 钩子需 ussh 证书：过期时提交被拒，**不绕**；Chao 在 Mac 刷新后用同一暂存区重试即过。
