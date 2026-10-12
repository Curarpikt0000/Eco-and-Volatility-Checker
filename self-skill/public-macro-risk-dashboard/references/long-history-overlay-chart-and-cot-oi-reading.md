# 长史叠加图（利率×金价×油价）+ COT/OI/库存读法（2026-10-10 实测）

## 1. 三线同图（联邦基金利率 + 金价 + 油价，1970 起，月度）
- 轴设计：**左轴利率线性(0–20%)；右轴一根对数美元轴，金价($/oz)与 WTI($/桶)共用**。线性金价会把 1970–2005 压成贴地线。页面口径说明必须写「两线单位不同，只是同尺度比较涨跌幅度」。
- 数据：利率 FRED `FEDFUNDS`(月，1954 起)，最新未发布月用 `DFF` 当月日均补；油 `WTISPLC`(**1973 前为官方管制标价**，页面注明)，补月用 `DCOILWTICO`；金价用项目既有底表同源 datahub gold-prices(世界银行 Pink Sheet)，补月用 Yahoo `GC=F` 当月日均。
- **先用代码对账再复用别的板块的金价底表**：datahub 与 `gold_oil_ratio_base.json` 逐月对 668 个月 0 个月差异>0.5%，口径一致才敢同图。补出来的月份页面里写明来源。
- 目标利率(DFEDTARU)1982 前不存在，1970 起必须用有效利率。
- 标注只标数据自带极值(利率峰值 19.1%/1981-06、金高点、油高点)，不写原因；事件(尼克松/沃尔克等)日期每条要回官方核，没核不写。
- 标注文字被自己的线压住 → `paint-order="stroke"` + 白色 `stroke-width=3` 描边 + 三个标注错开 dx/dy。改完用同一渲染函数单独出片段截图复核，不必再整站重建。
- 悬停验收坑：别凭感觉放鼠标。用数据索引算目标月 x 占比 `ML+(W-ML-MR)*i/(n-1)` 再除 viewBox 宽，逐个目标月(1980-01/1981-06/2008-06/2026-02/最新)比读数；第一次放错位置读到 1986-09 差点误判成 bug。视觉模型只当线索，回 DOM 复核。

## 2. 隔离整站构建硬检查（新板块每次都用）
脚本骨架：复制 `src/ data/` 到 `/tmp/eco_iso_<x>`、删 `.env`/kol_store/x_backfill/web_watch/tech_watch、把两个写 Notion 的函数首行改 `return None`，然后**脚本内断言**：`.env` 不存在、注入计数==2、新 fetch/新 render 函数已带上，任一失败 `exit 3-6`。构建后读 `BUILD_EXIT=` 末行、断言所有写入路径含隔离目录、逐标题对生产页(41→44，生产有新页无=[])、无头 Chromium(`--remote-allow-origins=*`)测 JS 零异常/菜单/SVG/开关/窄屏。后台启动后先 `pgrep`+读日志首行(日志刚创建时 read_file 会报不存在，别当失败)；把 pgrep、wc、ls 塞进一条命令会被解析器 hardline 拦(exit -1)→拆成单条重试。

## 3. COT「怎么还停在上周」= 发布时间差，不是 GitHub/cron 故障
CFTC 每周五美东 15:30 发布(=周六 04:30 JST，数据集 `rowsUpdatedAt` 可证)，cron 周五 11:00 JST 读到的必然是上一期。判据三件套：官方数据集最新 `report_date`、本地快照 as_of、`git log origin/main` 提交链是否连续。补抓没有单独入口(`run.py: fetch_cot_all` 绑定每日主流程，会写 Notion 3 库+覆盖当日快照)，不要为早几小时手补。
- 口径：`fetchers/cot.py` 是 **Legacy**(商业/非商业)，不是 Disaggregated。「商业净空缩小」≠「推升金价」：同周非商业多头减、空头增、OI 同降 → 是缩仓。回答「空头平仓么」要同表给：商业多/空、非商业多/空、OI 及一周变化。占 OI 百分比是单边口径，多头项与空头项各自≈OI，不能相加。

## 4. OI/持仓折吨、COMEX 库存
黄金每手 100 troy oz、白银 5000 oz(CFTC `contract_units` 字段可核)；1 oz=31.1035 g；吨=手数×oz/手×31.1035/1e6。金 OI 396,109 手≈1,232 吨(库存 730 吨的 1.7 倍)，银 OI 105,130 手≈16,350 吨。这是**纸面吨数**，不是实物，倍数不预测挤兑。库存数据在 `data/_comex_inv_work/data/inventory_snapshot.json`(盎司→吨；reg=在册、elig=待交割合格)，页面 `data/comex_inventory.json` summary 已折吨。周六问库存要说明最新日是周四(周五数据下周一才有)。

## 5. 30Y−2Y、银行融资压力
- FRED **没有** T30Y2Y；用 `DGS30−DGS2` 自算，先用 10Y−2Y 自算与官方 `T10Y2Y` 逐日对账(一致)再信。
- 银行融资压力(CP−Tbill，`DCPF3M−DTB3`)平时 0–8bp 摆动，单日 16bp→2bp 多是国库券利率更新滞后造成的一次性噪音；解读用「回到常态，不是改善」，阈值 20bp。日报「变化 X→Y」是 agent 润色、不在 `daily_brief.py`，要每天带解释需改 cron prompt(须 Chao 批准)；Chao 倾向「变化大才附」(如利差日变≥10bp)。

## 6. 提交纪律（本轮）
提交前：`timeout 15 ssh-add -l` 看证书、`git fetch` 比远端、红线扫描只扫新增行+新缓存全文、**只点名文件 add**、`git diff --cached --name-only` 核暂存区=预期、`git -c commit.gpgsign=false commit`、push 后比本地=远端 HEAD。不手动发布，等 cron 并 curl 读回。
