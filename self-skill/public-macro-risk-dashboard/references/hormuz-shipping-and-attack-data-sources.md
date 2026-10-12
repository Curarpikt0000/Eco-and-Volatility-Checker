# 霍尔木兹通航/袭击事件的公开数据源（2026-10 实测）

- **通航日线（AIS）**：IMF PortWatch ArcGIS `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query`，`where=portid='chokepoint6'`，字段 `date,n_total,n_tanker,n_cargo…`，`resultRecordCount≤1000` 需 `resultOffset` 分页。与 `straits.live/data/transits.csv` 逐日对账 133 天 0 差异；通常滞后到 T-4 左右。月均：2026-02 78.3、03 3.2、06 12.9、08 4.7、09 3.6。
- **straits.live/data**：transits/events 等 CSV 可直下（真 CSV，非错误页）。`events.csv` 只有近 2 天约 57 行，覆盖不了历史袭击。
- **UKMTO 官网整站 403**（含 sitemap/api），但**官方 PDF 能通过 web_search 找到并 web_extract 读取**：`/-/media/ukmto/products/<日期>-ukmto_warning_<编号>.pdf`、JMIC 周期公告 `update-0NN-jmic-advisory-note-DD-month.pdf`（含「Confirmed Maritime Security Incidents List」带 UKMTO 编号+位置+叙述）。用编号+日期+地名的 web_search 逐条定位。
- **口径坑**：UKMTO 编号事件不全在霍尔木兹：红海(095/097/098)、亚丁湾海盗(069-071)、阿曼湾(085 Qalhat、096)、阿拉伯湾(130 Port Rashid)、美军封锁执法（7/15 Hellfire 打瘫油轮）都要剔除；同一编号在不同 JMIC 版本里描述不一致（088-26）则不采用；UKMTO 把部分真实袭击登记为 “Suspicious Activity”（143-26 Al Funtas）。只有新闻没读到编号的（8/31）不入库。Limah/Khasab/Kumzar 在 Musandam 半岛，归「海峡阿曼侧入口」并注明。
- **NCAGS vs AIS**：UKMTO 10-02 概览 PDF 官方写明美军 NCAGS 协调通航数约为 AIS 观测数的 **5 倍**（走南线的船不开 AIS）。NCAGS 日度表和 Kpler 日线原油流量无公开来源（Kpler 公开的只有周报快照与月度合计，如 9 月海湾原油出口 16.328 mb/d）。
- 已整理数据文件：`data/hormuz_events.json`（20 条带编号事件 + 7 条排除理由）；通航线抓取/渲染/接线尚未做（做时沿用 fetch_*→_*_html→generate 接线→隔离构建流程）。
