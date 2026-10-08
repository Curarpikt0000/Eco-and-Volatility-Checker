# 手动接管 cron 回填 / 连续多轮回填循环（2026-10-07）

场景：Chao 说「cron 里还有没有 backfill，挑出来你来做，不需要 cron 做」。

## 1. 找「真回填」cron 的方法
- 读 `~/.hermes/cron/jobs.json`：对每个 job 的 **prompt + 它引用的脚本正文**同时 grep `backfill|回填|回补|补抓|补齐`。
- 命中 ≠ 在做回填。逐个读上下文分三类：纯回填（kol-new-backfill 14:00）/ 嵌在日报里的增量回填（日报步骤 3b `backfill_kol_detail.py --limit 25`）/ 只是名字带（目录名 tools/x_backfill、rsync 排除 *.bak、Notion 回写）。别的项目（war-kol、politics-checker、forecast-checker）的同名字样**不动**。
- 改 cron 需批准。「B 方案」= 入口脚本改成**只检测不抓取**（`tools/kol_backfill_detect.py`，选人判据与原脚本逐行一致，只读 sqlite `mode=ro`，有人要补才输出），保留「别忘了」的保险，同时不烧配额。只换 `~/.hermes/scripts/*.sh` 入口一行，不碰 cron 配置；先备份。

## 2. 连续多轮循环（`tools/kol_backfill_loop.sh`）
- 原脚本同一天 `STATUS=DONE` 即退出，一天一轮；循环每轮前把当天 `scratch/kol_bf_auto_<date>` **改名挪开不删**。
- 每轮 6 人并行，约 10~15 分钟；121 人≈21 轮≈5 小时。**先算对规模再报**（我首报「4 轮 3.5 小时」算错，被自己更正）。
- 停止条件：没人要补 / 某轮 STATUS 非 DONE / 最大轮数 / STOP 文件。失败即停不硬闯。
- **循环内必须 `KOL_BF_NOPUSH=1`（原脚本自带开关），全部跑完统一提交一次。** 原因：每轮 commit 要过公司 pre-commit 钩子，依赖 ssh 证书，5 小时内证书中途失效是大概率；第 2 轮 `asd-cli ... connection reset by peer`，数据已入库却未提交。证书断时 `ssh-add -l` 会挂住（用 `timeout 15`）。
- 证书失效处理：不绕钩子，请 Chao 在 Mac 跑 `ussh`；`ssh-add -l` 立即返回并显示 `Valid until` 才算恢复，再补提交暂存区。
- 取舍要告知：不提交 = 跑完前远端无备份。

## 3. VM 专用 Chrome 跑 X 网页回填
- 脚本 `tools/x_backfill/x_backfill_6m.py [账号…]`，无参数=按天数从少到多跑全部未完成账号，断点续跑，12 秒/天，连续 3 天失败自停。
- **启动命令只设 `CDP_PORT=9444`，不要设 `CDP_HOST=<IP>`**：展示层会把 IP 字面量改写成占位串，传进去脚本连不上（首跑「通道不通」即此因）。默认 localhost 即可；怀疑文件里的 IP 被改写时用 `ipaddress.ip_address()` 判是否回环，别靠肉眼。
- 通道检测 `tunnel_ok()` 要重试 3 次，瞬时抖动不应判死。
- 样板验收口径：`since:/until:` 按 UTC 切，单日文件会串日（960 条里 813 条时间戳日期≠文件日期）；入库必须**按帖自带时间戳取日期并按 id 去重**（960→792）。漏抓率无独立验证前不得说「完整」。
