# Eco 看板：静默旧数据 / House 口径 / 菜单顺序 教训 (2026-10-06)

## 1. cron 标 ok ≠ 数据是活的
- 日报 cron 每天 ok，但「读别人产出」的板块(如 comex-inventory-charts 站)上游停更 20 天无人发现。
- 判据: 每个板块读【源头最新数据日】对照标注频率；别用页面里出现的日期(会抓到任意日期)。
- 现成工具: `tools/freshness_audit.py`(40 个 fetcher, 声明频率+容忍天数)。隔离副本里跑: rsync 到 /tmp, 把副本 `notion_writer.upsert` 置空操作 + `_req` 只放行 GET 与 `/query`, 副本含 .env(用完整目录删)。
- 审计 STALE 必回源头核: FRED 季度序列(IEAXGG 黄金出口末点 2026-04-01; 信贷脉冲 QCNPAM770A 等末点 2025-10-01)是源头低频, 非故障; 先拿日度对照组(DGS10)证明通道好。INTERNAL_MISMATCH 多为未来拍卖日/年末标记误报。
- 图上「每日更新」徽章与真实频率不符是展示问题, 应标「季度·最新某日」。

## 2. 上游生产者在哪台机器要查实物
- Notion 写入者是同一机器人账号, 分不出 Mac/VM; 「Notion 今天有新行」不能推出「Mac cron 在跑」。
- 接管上游脚本: 路径参数化(INV_BASE), 对 Notion 纯只读, 由 fetch_* 内部先自产、失败回落外站再缓存, 回落写 note 不静默; 不必改日报 cron prompt。

## 3. COMEX 做市商周净 issue/stop 只算 House(H)
- Chao 口径: 核心10家 + 只算 House(H); Customer(C) 与无标记(U)不进图; 无标记周留白(blank=None), 不画0不当H。
- C/H 标记在 Notion 自 2026-08-21 才有(06-06~08-20 无标记); PDF 段(1~6月)有 org 列且几乎全是 C(JPM 的 H 仅百余手), 切 H 后曲线形状大变, 属口径变化非错误。
- 独立对账: 另写一套算法, 金银各6周 H 值 12/12 一致才采信。
- 悬停标实际交割日数; 周四常只写库存不写交割(08-20 起), 上游原因未知。

## 4. 侧栏菜单与页面顺序
- 根因: 按关键词把相距几十屏的板块合并成一组, scrollspy 用 DOM 序 → 倒退。
- 根治: 菜单严格按 DOM 顺序渲染, 同组被隔开标「（续）」, 无命中并入相邻段。验证用本地无头 Chromium dump-dom 探针, 判据=页面 y 倒退次数 0 且菜单 id 序列==DOM 序列(别用空集合'一致 True')。

## 5. 流程
- 公司 pre-commit 钩子报 `no ssh cert`: 不绕, 请 Chao 在 Mac 跑 morning-ssh.sh/ussh, 回「好了」后重试同一提交即过(暂存区不丢)。
- 提交前核暂存区只含自己改的文件(.gitignore 夹带前轮遗留需看清)。
- 说「后台在跑」前 pgrep+读日志首行; 通知 completed normally 仍看 EXIT 码。
