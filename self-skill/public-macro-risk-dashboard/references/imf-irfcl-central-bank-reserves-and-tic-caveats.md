# 央行口径美债/储备：IMF IRFCL 新 SDMX API + TIC 口径陷阱（2026-10 实测）

## 为什么需要
用户问「欧洲央行有没有抛美债」。TIC（美国财政部）是**按托管地、含私人部门**，不是央行行为：
法国非黄金储备上限≈$78B，TIC 记法国 $390B（5.0×）；比利时 $22B vs $482B（21.7×，Euroclear 托管效应）。
国别净卖（法 −24.8B / 挪 −11.5B / 德 −3.8B，26Q2）**不得说成央行卖出**。TIC 公开表无 official/private 国别拆分。
要央行口径 → IMF IRFCL（Int'l Reserves & Foreign Currency Liquidity，各国央行自愿申报，月度）。

## 可用端点（旧 dataservices.imf.org 已下线，DNS 解析不了）
`https://api.imf.org/external/sdmx/2.1/…`（data.imf.org / api.imf.org 可解析）
- dataflow 列表：`/dataflow/IMF.STA` → 找到 `IRFCL`。
- 元数据（3.6MB，存本地再解析）：`/datastructure/IMF.STA/…`；维度顺序 **COUNTRY.INDICATOR.SECTOR.FREQUENCY（4 维，别给多）**，国家用 ISO3（DEU/FRA/…）。
- 数据：`/data/IRFCL/<COUNTRY>.<INDICATOR>.<SECTOR>.<FREQ>?startPeriod=2019`。
- 关键指标 `IRFCLDT4_IRFCL11_DIC_USD_USD` = 储备中**美元计价**部分。
- 量纲：SCALE 字段写 "Millions" 但值是**美元**（德国 3.16e10 = $31.6B）。先用已知量级校验再下结论。

## 结果（德荷实测，法比空）
德国美元计价储备 2019-12 $32.9B → 2026-03 $31.6B（七年 −4%，窄幅 $29–33B）；荷兰 $2.6B→$6.6B（基数小）。
法国/比利时 89~91 期全为 0 = **未申报**（币种明细自愿披露），不是持有为零；意大利/西班牙/奥地利该序列直接 400。
→ 法国卖出无法直接验证，只能用「非黄金储备上限」做排除推断，必须标明强度（实测 vs 推断）。

## 方法论
- 「查不到/为 0」先怀疑口径：区分「申报为 0」与「未申报」，拿已知存在的对照组（德国）走同一查询。
- 国别 × 持有人类型必须写明口径；欧元区央行美元敞口本来就极小，增持主体是保险/养老/基金（利差驱动）。
- 黄金「27%」口径：COFER 不含黄金（IMF 原文 Monetary gold is not covered in COFER but included in reserve assets）；
  黄金 > 官方美债，但 < 美元资产总和。
- 本机 `pymupdf`/`fitz` 可能因环境污染导入即崩（`inspect.signature` AttributeError），年报 PDF 解析别死磕，优先 API 数据源。
