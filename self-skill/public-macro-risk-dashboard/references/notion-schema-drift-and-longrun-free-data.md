# Notion 缺列整行被拒 + 长周期/高频免费数据源（2026-09-30）

## Notion schema drift（真事故）
- 9/18 config 把指标 `name_en` 从 `SOFR minus IORB Spread` 改成 `... EFFR ...`，Notion 表没加列 →
  Notion 对**任一未知属性整行 400** → 9/21–9/30 指标行全缺；`write_indicators` 返回 None 却打印「已写」，
  日报把报错写成「非致命缺一列」。
- 修法（已在 src/run.py）：写前 GET 表 schema，缺列自动 PATCH 加（number / select 🟢🟡🔴⚪，只加不删，旧口径列保留不混用）；
  upsert 返回 None 必须显式打「❌ 指标行写入失败」。补历史：从 `data/snapshots/<date>.json` 重建行 upsert，再按真实列名读回核对（VIX 列名是 `CBOE VIX`，别用 key 猜）。
- 通用教训：任何「改名/新增字段」都要问下游 schema 有没有；「非致命」判断前先查同一次写入的其他字段是否也丢了。

## 中国原油进口
- 月度全国：**JODI** `https://www.jodidata.org/_resources/files/downloads/oil-data/world_primary_csv.zip`（23MB，免 key），
  CSV 过滤 `REF_AREA=CN, ENERGY_PRODUCT=CRUDEOIL, FLOW_BREAKDOWN=TOTIMPSB, UNIT_MEASURE=KBD|KTONS`，2002 起，滞后约 2 月。
  最新月可用海关总署吨数 × 上月 JODI 桶/吨系数折算，图上用空心点区分。EIA international API 对中国只有年度。
- 周度：全国周度只有 Kpler/Vortexa 付费。公开代理＝隆众「山东独立炼厂原油周度到港量」(Mysteel 转载，正文摘要含
  「截至YYYY年M月D日，山东独立炼厂原油到港量X万吨，较上周涨/跌Y万吨」)。列表页 `nenghua.mysteel.com/list/article/pa7302a050301aaaaa1.html?keyWord=到港量` 约 18 周；
  更早的逐周 web_search 该句式；缺周用下一周「较上周」反推并交叉验证。必须在图上标注「仅山东地炼样本≈全国两成」。

## 股指/黄金 50 年比值
- 道指 1992 前：GitHub `fja05680/dow-sp500-100-years/DJA.csv`（日收盘到 2019）；1992 起 Yahoo ^DJI 月线（`period1` 取负数时间戳可拉全历史）。
- 标普：Yahoo ^GSPC 日线 1976 起取月末。黄金：`datasets/gold-prices/data/monthly.csv`（伦敦月均价，1833 起），当月用 GC=F。
- stooq 现在要 JS 验证，macrotrends 403。拼接处打印核对（1991-12 vs 1992-01）。
- 参考值：道/金 1980-01 1.3 最低、1999-08 42.1 最高、2011-09 6.2、中位数 12.1；标/金 0.17 / 5.5 / 0.64、中位数 1.44。

## 出图 QA
- matplotlib 在项目 `.venv`；CJK 字体 NotoSansCJKsc 注册。每次改后 vision 复查（标签压线/脚注压刻度/白底框遮线）；
  vision 说「曲线断开」先用数据核对是否真缺月（曾是急跌被误读）。子图叠加：上长周期、下高频，上图用浅灰带标出下图区间。
