# Eco-and-Volatility-Checker 上下文日志

> 由 cron `eco-vol-context-distill`（每日 06:00 JST）自动追加。
> 首节 2026-08-22 由本人手工写入（当日 session 过长，先落盘再启用自动归档）。

---

## 2026-08-22

### 决策

- **KOL 名册 SSOT 改为 Notion「KOL List」DB**，GitHub 侧 `data/kol_registry.json` 降级为**镜像副本**。
  Chao 明确：「只用 Notion 上的人，不要再增加了」「你不要做我没给你的任务」。
  → agent **绝不自行增删 KOL**；增删一律由 Chao / 另一 agent 在 Notion 操作。
- **项目边界裁定**：玄学 / 术数 / 占星 / 通灵 / 末日预言类**不属本项目**，归 Forecast-Checker。
  本项目只留**可交易的金融判断**。
- 2026-08-20 自建的「周期与术数预测」独立 section **停用**；技术分析 / 量化周期派归**常规 KOL 板块**。
- 23 人按方法论拆分：**11 位玄学派迁出**（金融占星 / 圣经周期 / Gann / 中文易经六爻奇门 8 人），
  **12 位技术分析派保留**（艾略特波浪 / McClellan 市场宽度 / ECM / Hurst 周期 / 世代长周期）。
- 每日同步**不新建 cron**，而是在现有 `eco-vol-01-daily-scan-report` 里插入「步骤 0」。

### 事实与配置

- Notion「KOL List」DB = `35947eb5-fd3c-800d-b852-cef31f9de6a5`，
  位于 page「KOL Research Daily Update」`31447eb5fd3c8064a531c43b177cdc41`
  （同页另有 KOL By Week / KOL By Day 两个 DB）。
- 同步后名册 **124 人**，与 Notion 完全一致。
- 移出 3 人：FEMA、Sarah Bond、Harry S. Dent Jr. → 留痕 `data/kol_removed_20260822.json`，
  其 `data/kol/backfill/` 历史文件**保留未删**。
- 新建 5 人：Michael Widmer、Jim Rogers、Judy Shelton、Asha Sharma、Kevin Murphy。
- **TIC 分国别持有美债数据源修正**：`mfhhis01.txt` 是**历史存档表**（只到上一自然年年末），
  当年月度在 **`slt_table5`**（13 个月滚动窗口）。两源合并、当期表优先。
  修正后：日本 **$1,116.7B** / 中国 **$633.4B**（as of 2026-06），与官方 2026-08-17 发布一致。
  修正前显示 $1,186B / $684B（2025-12 旧值，落后 6 个月）。
- **EU 无法用当期表**：TIC Table 5 只列前 20 大持有国，德/意/荷/西/芬 落在 "All Other"，
  9 国加总口径结构上无法还原 → 保留存档表真值 + 图上写明 `lag_reason`，不做半截加总。
- **BIS credit-to-GDP 实际发布延迟 9–10 个月**（FRED QUSPAM770A/QCNPAM770A 实测最新即 2025-10-01），
  套用通用 `quarterly=135` 天阈值会**恒定误报红标** → 新增 `bis_quarterly=330` 阈值。
- KOL 历史回填：**2,804 条**，覆盖 2025-01-02 → 2026-08-21（20 个月）。
- `ddgs` 之前**未装在 Hermes 自己的 venv** 里（`/home/user/.hermes/hermes-agent/venv`，uv 建的无 pip），
  导致每次 web_search 都报 "not installed" 后静默回退兜底。已用
  `VIRTUAL_ENV=<venv> ~/.local/bin/uv pip install ddgs` 装上 9.15.0，实测生效。

### 进展

- commit `18063a3`：修弹层空态（cron 内联命令漏传 `kol_history`）+ TIC 错值 + 全量回填至 2804 条。
- commit `0e37059`：Notion 单向镜像同步 + 玄学派迁出 + dashboard 三处名册过滤。
- commit `6203d19`：AGENTS.md 固化 SSOT 铁律与项目边界 + cron 加「步骤 0」。
- 新增工具：`tools/sync_kol_from_notion.py`（单向镜像）、`tools/split_cycle_kols.py`（拆分）、
  `tools/add_notion_sync_to_cron.py`、`tools/clean_cron_esoteric_ref.py`（幂等改 cron，带备份）。
- 线上验证通过：md5 `c76c8d92e93a` 本地/线上一致；111 张卡片全部可点、**0 张空白**。
- Forecast-Checker 侧：87 → 98 人，11 位玄学派 + 18 条已验证历史并入，已推公网。

### 踩坑

- **弹层空白根因**：项目有**两个构建入口**——开发用 `src/build_dashboard.py`，
  cron 用一条 2,600 字符内联 `python -c` 直调 `dashboard.generate(...)`（30 个参数），
  漏传 `kol_history` → 线上 `var DATA = {}`。修法：兜底放进**被调函数内部**，任何入口都不会再漏。
- **名册变更后下游不跟随**（同一病根，踩了两次）：
  `kol_full_history()` 直接扫 `data/kol/backfill/` 目录、
  `kol_weekly_views()` / `kol_stance_changes_grouped()` 读的是**每日快照**，**两者都不看名册**。
  → 移出人后必须在渲染层按名册过滤，否则出现「卡片没了但历史仍内嵌在 payload」
  或「卡片还在但点开空白」。已在 `_kol_history_payload` / `_kol_views_html` / `_kol_changes_html` 三处加过滤。
- **Notion 名带机构后缀导致模糊匹配误删**：「Nomi Prins（… 前 Goldman Sachs MD）」
  被本地「Goldman Sachs」条目抢先匹配走，导致 Nomi Prins 被判为「Notion 无」要移出。
  正解：**先全量精确匹配 → 模糊只认「本地名 ⊂ Notion 名」单方向 → 取最短候选 → 已配对者不再参与模糊**。
- **子代理 600s 硬超时会丢光成果**：首轮 3 个子代理各跑 25–34 次 API 调用，
  全都「先搜集、最后统一写文件」，超时一到上下文清空，零落盘。
  正解：**抓一个立刻 `write_file` 落盘，再抓下一个**；每批人数压到 8 人；禁用慢速 `web_extract`。
  修正后同期落盘 4 → 23 个文件。
- **子代理产出的 URL 必须本人逐条 curl 验证**：中文小众频道抓到 2 条 404 幻觉链接
  （`@xiaoxia523`、`hao.cnyes.com/post/177469`），已剔除并在文件留 `verify_note`。
  被 WAF 拦的 401/403（Reuters/Bloomberg）不算死链，另做内容交叉验证。
- **页面自相矛盾就是 bug 在报警**：Chao 一句「右上角写每月更新，图上却说滞后 233 天」
  同时揪出两个独立 bug。核实后有两种**相反**结论：官方已发新数据 → 改数据源；
  官方最新就是这期 → 改 SLA 阈值（误报）。**绝不假设「官方就这么慢」，先查官方**。
- **新板块首次接入的数据最容易错也最难发现**：TIC 板块 2026-08-14 上线第一天就接错源，
  一周无人察觉——没有历史基线可比，错值看起来就像正常值。
  `git log -S` 溯源可区分「新引入」vs「历史遗留」。

### 待办

- [ ] 本 session 的经验尚未 ingest 进 ChaoWiki（已写 `knowledge/frontend/data-dashboard-publishing.md` §8，
      但 KOL 名册 SSOT / 子代理超时 / 名册-下游一致性这几条还没归档）。
- [ ] 遗留技术债（非阻塞）：39 处 `except: pass` / 11 处 `except: continue`；
      `_stress_panel_svg` axis 与除零；BIS API 406。
