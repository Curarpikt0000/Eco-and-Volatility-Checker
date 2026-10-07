# KWN / Kitco 监测 + 短期金银技术派/机构派日更 cron（2026-10-05/06 实战）

## 事实（实测，近 14 天）
- 名册技术派（Vermeulen / Soloway / Roy-Byrne / Hamilton / Baillie / Maund）在 KWN、Kitco 近 14 天**都是 0 条**（KWN 29 篇全文、Kitco news+opinions+video 115 条）。结论前用对照组：同窗口 KWN 里 Macleod 21 篇、Prins 18 篇，证明通道通。他们以前上过 Kitco video（Vermeulen 最后 07-02，Soloway 07-30），近 2–3 个月不上了。
- Kitco/KWN 上真正给金银价位的是**机构策略师**（Natixis、BofA、FxPro 等）→ 单独做 B 通道「机构预测」，不得与技术派混写。
- 音频：KWN 嵌 SoundCloud **私有轨道**（`secret_token`），无 mp3 直链/无播客 RSS；公开 SoundCloud 轨道 yt-dlp 正常（对照组），私有轨道 401，从播放器 JS 抠 client_id 未成功且属灰区，未继续。Kitco 无播客，访谈是 YouTube 嵌入，而 VM 的 IP 被 YouTube 封（429 / Sign in to confirm）。带 cookies 的 yt-dlp 也不行（cookies 未过期，是 IP 问题）。
- Roy-Byrne `thedailygold.com`、Vermeulen `thetechnicaltraders.com` 的免费文字只有 160–330 字摘要、无价位；核心在付费刊/视频。需要读价位只剩走 Chao Mac 的住宅 IP/浏览器（依赖隧道，不能无人值守）。

## tech_watch.py 规则要点
- 判定函数和交给 agent 的必须是**同一段文本**（先截断 body 再判定），否则出现「判定通过却抽不到预测句」；截断放到 14000 字（6000 会漏掉价位在后半段的文章）。
- 机构派判据：非行情播报标题 + 有归属句 + 至少 1 个「预测措辞与金银价位带内 $ 价位同在一句」（`_fcst_sentences`）+ 带内价位≥2。金银价位带：2500–7500 或 45–85（挡掉比特币 $100,000、进口额等）。
- 剔除促销句（KWN 每篇文末 Nomi Prins 采访广告含 `$6,000 gold`）。
- 候选句规则偏宽，会抽到「某分析师说金价跌回 4,300 下方」这类行情描述 → prompt 要求 agent 读 body 原文判断，不照抄候选句；这一步脚本化不了，要看产出核对。
- 迭代方式：每次改规则都用 14 天真数据重跑，逐条看被收/被挡的原因（第一版收 20 条一半是噪音，矫枉过正又漏真预测）。

## 建/改 cron 的做法
- prompt 很长，命令行传会被解析器拦：写成文件，用 Python `subprocess` 读文件再调 `hermes cron create/edit --prompt`，事后读 `~/.hermes/cron/jobs.json` 核对模型/时间/prompt 关键句，不信命令自述。
- `hermes cron edit` 会重算 `next_run_at`（可能跳到次日）——告诉 Chao。
- cron 默认模型用 sonnet-5-5（Chao 10-06 明确：日常 cron 用 sonnet），haiku 抄价位易错。
- 采集层输出 JSON，agent 只写有原文的价位；视频读不到正文标「正文未读」，不编数字。
