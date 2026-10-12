# 两条通用经验（2026-10-08，Eco-and-Volatility-Checker）

## 1. 长循环任务不要每轮 commit
新 KOL 回填循环（每轮 6 人、约 10 分钟、共 24 轮）每轮调 kol_new_backfill.sh 并 commit。pre-commit 钩子依赖 ssh 证书（asd-cli 经 ssh-agent），证书中途失效时第 2 轮「入库成功但 commit 失败」，循环按设计 exit 2 停下，数据留在暂存区。判据：`ssh-add -l` 超时或 `The agent has no identities`。
处置：循环脚本给子脚本传 `KOL_BF_NOPUSH=1`（原脚本已有该开关，不必改原脚本），只抓取+入库，**全部跑完后点名文件一次性提交**（kol_store.sqlite + 账本）。代价：中途无远端备份，要向用户说明。证书失效只能用户在 Mac 跑 ussh，不绕钩子。
对账：循环自报新增条数 == sqlite 行数差（9357→9491=134）。循环到最大轮数上限停止≠全部完成：每人最多试 2 次，需另报「已试满仍不足」名单，别说「全量做完」。

## 2. 用户发来一张图要求「复制进 dashboard」
1. 先用 vision 逐项转录：标题、图例、轴、Source、标注；图上没有 Source 就明说。
2. 逐线探数据源，只读：Yahoo chart API(period1/period2 分段)、官方 API 与第二源逐日对账、LBMA/Nasdaq/ICI/macrotrends 常 403，Bloomberg/LSEG 私有指标拿不到。四线里能做几条如实报，做「诚实版」：拿不到的线留空写「无公开日度数据」，不拿别的数据冒充。
3. 图上数字自洽性检查（如 "$895 Trillion" 实为 Billion：24万亿×3.7%）——不照抄。
4. 类比路径图（历史年份叠到当年）的对齐规则图上不会写。先假设再用图上圈出的低点位置反推；「起点价缩放」被证伪（2006 金线冲到 6,747>原图上限 6,000），「当年 1 月底起 120 天内最高收盘对齐 2026 高点并缩放到高点价」低点天数吻合。口径写进板块说明，并如实写「只核对了几条线、原作者算法未公开」。
5. 新板块接线三处：external_data.fetch_*（失败回退缓存、不以空覆盖）、build_dashboard 取数+传参、dashboard.generate 形参+渲染+`.part-title`（菜单自动生成）。整站隔离构建前必须切断 write_*_notion，且不拷 .env；生产 docs/index.html 的 mtime 用来证明隔离有效。
