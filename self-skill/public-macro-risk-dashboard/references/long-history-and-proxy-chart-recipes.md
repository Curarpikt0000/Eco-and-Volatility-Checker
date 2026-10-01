# 长历史比值图 / 高频代理图 / 复刻第三方图 —— 做法与数据源（2026-09-30 实战）

Chao 常发截图（视频/研报里的图）问「这个图你能做吗」→ 做成 png 验收 → 他说「放 dashboard 每天更新」。
固定三步：**① 找公开源并如实说明口径差 → ② scratch 出 png + vision QA → ③ 接入看板（fetcher + _xxx_html + build_dashboard + 模板 section）**。

## 接入看板的固定骨架（本次 3 张图都照此）
- `external_data.fetch_xxx()`：**历史底表文件**（data/xxx_base.json，已完结月份，一次性生成入库）
  + **每日追加**（Yahoo/FRED 日线，只追底表之后的月份）+ 失败读 `data/xxx_cache.json` 并在 warnings 标「缓存」。
  低频源（季度 xlsx）：本地文件 24h 内不重下；下载后校验 `blob[:2]==b'PK'` 且体积合理再原子替换（防存成错误页）。
- `dashboard._xxx_html(o)`：空数据返回 `<p class="empty">…同步中</p>`；**每点 `_hover_bands()`**（Chao 铁律：悬停必显横纵坐标）；
  尚未发布的季度在 tooltip 写「该季尚未发布」，**不拿上季数顶替**。
- `build_dashboard.py` try/except 调 fetcher + 打印一行 → `generate(..., xxx=xxx)`；generate 形参门禁会自动核对。
- 模板 section 插在已有 section 锚注释前；CSS 双花括号 `{{ }}`（f-string 模板）。
- 验证：构建日志行 + `grep -c` 产物 + section 内 `data-tip=` 计数 + 发布后 curl 线上 grep。

## 数据源（实测可用）
- **中国原油进口月度（全国）**：JODI `world_primary_csv.zip` → REF_AREA=CN, CRUDEOIL, 进口；KBD+KTONS 两单位；最新月 JODI 未出时用海关万吨 × 上月桶/吨系数折算并虚线标注。
- **中国原油周度**：无免费全国源（Kpler/Vortexa 付费）→ 代理=隆众「山东独立炼厂原油周度到港量」（Mysteel 转载）。
  列表页 `nenghua.mysteel.com/list/article/pa7302a050301aaaaa{N}.html?keyWord=到港量`（不带 keyWord 翻页只重复第 1 条，只能回溯约 18 周）；
  正文句式「截至YYYY年M月D日，山东独立炼厂原油到港量X万吨，较上周涨/跌Y万吨」；更早的周用 web_search「截至YYYY年M月D日 山东独立炼厂原油到港量」按周末搜，
  再用下一周「较上周」反推交叉核对。curl 必须 `-m 15` 硬超时（urllib 挂死过 300s）。**图上必须写明只占全国约两成、非全国总量**。
- **道指 1976–1991**：github `fja05680/dow-sp500-100-years` DJA.csv（日）；1992 起接 Yahoo ^DJI 月线（range=max 只到 1992）；拼接处打印核对。
- **标普 1976+**：Yahoo ^GSPC `interval=1d&period1=189302400`（月线只到 1985）。
- **黄金月度 1833+**：github `datasets/gold-prices` monthly.csv（LBMA 月均）；之后月份用 GC=F 当月日收盘均值保持「月均」同口径。
- **美国季度 TFP**：旧金山联储 Fernald `frbsf.org/wp-content/uploads/quarterly_tfp.xlsx`，sheet `quarterly` 列 dtfp / dtfp_util（年化对数增速，/400 累加成水平）；readme 含 Produced on 日期=版本。
  FRED 上只有年度 TFP（RTFPNAUSA632NRUG / MFPNFBS）。
- **密歇根信心**：FRED UMCSENT（月度）。
- stooq CSV 在本机返回 JS 验证页 → 改用 Yahoo。

## 复刻第三方图（原作者未公布算法）
- 多种合理算法都算一遍（全样本线性/HP/滚动 10 年线性、普通/剔除开工率），报告**哪个结论依赖口径**；看板上把分歧口径一起画（实线+虚线），不挑一个最像原图的冒充。
- 如实告诉 Chao 原图卖点在公开数据下是否成立（例：「TFP 低于趋势」普通口径 −0.1% vs 剔除开工率 −1.9%；「走势很接近」2021 后背离）。
- Chao 报的点位（如「道指/金 13:1」）与算出值不符 → 说明差在哪天的价格，不迎合。

## matplotlib QA 坑（vision_analyze 逐轮查）
- 对数轴默认刻度成 `4×10¹` → FixedLocator([..]) + `f"{y:g}"`；标签白底 bbox 会遮线 → 去 bbox 改偏移；末端标签易压中位数线/右轴刻度 → 按与中位数上下自动选偏移、xlim 右扩留白。
- 长脚注用显式 `\n` + `va="top"`，别靠 wrap=True（会拦腰断词、压 x 刻度）。
- 跑脚本用项目 `.venv/bin/python`；跑错解释器报错时旧 png 还在，vision 会把旧图当新图查——先确认渲染成功再 QA。
- vision 说「线有缺口」先用数据核缺月，别盲信（陡降常被误判）。
