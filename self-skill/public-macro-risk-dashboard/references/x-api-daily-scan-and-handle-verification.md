# X 每日扫描 cron + 账号核对 + 公开仓库红线 (2026-10-04 续, 补充 x-api-backfill-lessons.md)

计费/接口/翻译复用门禁/费用估算见 `x-api-backfill-lessons.md`; 本文件只记它没有的。

## 账号核对(users/by 批量 $0.01/个)
- 网页「人物搜索」对约 37% 名册失灵(返回热门推荐: 特朗普/BBC), 对照组 Gromen/Dalio 也搜不到 → 搜索失灵 != 账号不存在。猜账号开页面 10 人 0 个自动通过, 不值得。
- 机械门禁: 显示名姓+名双命中 + 强机构词(剔除姓名本身与 capital/research/group/china 等通用词; >=2 个, 或 1 个且>=6 字母) 或 认证且粉丝>=1 万; 加 BAD 词(backup/parody/commentary/tribute/festival/poetry...)、受保护、账号<1 年降级。
- **门禁仍放行同名路人**: 50 个 verified 里 8 个其实不是名册那个人(James Grant->NC 法学生, Adam Hamilton->牧师, 瑞士银行家->NYT 作家, 术数/灵媒/阴谋论号)。用「简介里无任何金融词」「粉丝最少 10 个」两个角度抽验才查出; 判据没被证明能区分真假前不能当结论, 扫描名单要有 `x_scan_exclude.json` 显式排除。术数/灵媒/宗教类不属 Eco。

## 每日扫描脚本设计(tools/x_backfill/x_daily_scan.py, no_agent, 成功静默)
- 每人一次 `from:h -is:reply -is:retweet` + since_id 游标; 稀疏账号另存 last-scan 时间做 start_time(否则每天重读 2 天窗口重复付费)。
- 硬门禁写进代码: 每日上限 DAILY_CAP、累计预警 80%、402 即停并告警; 有新帖才一行汇总。
- 别每天花 $0.05 做通道探测(search 最小 10 条): 改为「扫 >=20 人却全 0 条」才报通道可疑且不更新 last。「没新帖」不得等同「没抓到」。
- 真跑一次再信: 实测一次 $0.15 扫 6 人 20 条, 第二次设更低上限被拦住(熔断实测有效)。
- 建 cron 要 Chao 明确批准(他已说「建cron」, 但我提议改一处设计需等「改/不改」)。

## 公开仓库红线
- 推文英文原文、账号简介属第三方内容: 公开仓库只放 id/日期/链接+中文译文; `x_posts_store.json`、`*_raw.json`、`x_handle_*.json`(含简介) 写 .gitignore; 提交前扫「暂存区含原文连续 40 字片段」数必须为 0。
- 旧提交里已推送的原文清除需 force push(不可逆, 需 Chao 明说); 默认只新提交去掉并如实告知历史仍在。

## 浏览器回填对照
- 稀疏账号 Hunter 14/14 与 API 一致($0, ~30 分钟); 单日 0 条先拿 API 已知有帖的日期跑同通道确认通路。高产账号需另行对照(Gromen 网页漏 9、截断 22)。

## 方案评审用 Opus
- 代理 :8800 的 claude-opus-5-5 评审需 max_tokens>=8000 且 prompt 要求控制字数, 否则 choices 为 null; 把「全部实测事实」打包并要求区分「实测/外推/纯假设」。
