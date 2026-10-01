# 期权隐含波动率 / 期权持仓 / 全球货币供应 —— 免费源实测台账

实测日期 2026-09-21（Eco-and-Volatility-Checker）。全部结论来自真实请求，不是文档推断。
**用前先复测一次**（端点会变），但下面标「陷阱」的几条是方法论，长期有效。

---

## 一、ETF 期权 IV（GLD / SLV / IAU）—— ✅ 可做

### 可用端点
```
https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
```
- 免费、无 key、需常规浏览器 UA。
- 返回 `data.options[]`，每个合约含 **`iv`** 与 **`delta`**、`open_interest`，外加 `data.current_price`、顶层 `timestamp`。
- 合约代码形如 `GLD260918C00365000`：正则 `^[A-Z]+(\d{6})([CP])(\d{8})$` → 到期 YYMMDD / C或P / 行权价×1000。

### 两张图怎么算
- **ATM IV 期限结构**：按到期日分组，取 |delta|=0.50 处的 IV（call/put 各插值再平均），排成 1M/3M/6M/12M/18M/24M。近月 > 远月 = **倒挂**（市场预期近期震荡）。
- **25D 偏斜（风险逆转）**：`25-delta put IV − 25-delta call IV`。正值 = 看跌期权更贵 = 偏空；负值 = 偏多。
- ★**必须按 delta 线性插值**，不要「取最接近 0.25 的那张合约」——合约 delta 不会正好落在 0.25，取最近点误差可达零点几个波动率点，足以翻转结论。

### 标的选择陷阱
**SGOL 只有 4 个到期日** → 12M/18M/24M 三个期限会全部落到同一个到期日，表里出现三行一模一样的值，看起来像「远端持平」其实是重复值。
→ 代码里必须按 `exp` 去重，被剔除的期限数写进卡片标注；流动性不足的标的直接不画。

---

## 二、期权 IV 的**历史**—— ❌ 免费拿不到（已穷尽）

| 源 | 结果 |
|---|---|
| CBOE `?date=YYYY-MM-DD` | **200，但参数被静默忽略**（见下） |
| CBOE `/historical_data/`、`/historical_options/` | 403 |
| Alpha Vantage `HISTORICAL_OPTIONS` | `"This is a premium endpoint"` —— 付费 |
| Alpha Vantage `REALTIME_OPTIONS`（免费档） | **返回占位假数据**（见下） |
| ORATS | 401 |
| Nasdaq Data Link（CBOE 数据集） | 403，已转付费 |

### ★陷阱 1：`?date=` 返回 200 但参数无效
判据不是状态码，是**内容**：带参数与不带参数的返回，`timestamp` 与 `current_price` **完全相同** → 参数被忽略。
> 同型陷阱前科：WGC `fsapi.gold.org/...?metal=silver` 也返回 200，但三地区数值与黄金端点一字不差、`Gold Price (rhs)` 仍是金价。
> **凡是带参数的端点，一律请求两次不同参数值再逐字比对**，这是硬规矩。

### ★陷阱 2：demo key 跑通 ≠ 免费 key 能用
Alpha Vantage 的 demo key 只对 **IBM** 放行；换 GLD 即返回「请领取免费 key」。
领了免费 key 之后才发现 `HISTORICAL_OPTIONS` 本身就是付费端点 —— **别据 demo 成功就让用户去注册**。

### ★陷阱 3：免费档返回的「数据」是占位假数据
Alpha Vantage `REALTIME_OPTIONS` 免费档返回结构完整的 JSON，但：
```
contractID = XXYYZZ...      expiration = 2099-99-99      各价格字段全是 100
```
**结构合法、字段齐全、状态 200**，不看具体值就会当真数据入库。
→ 新接入任何行情源，第一件事是**肉眼看几行原始值是否物理合理**（到期日、价格量级、代码格式）。

### 可用的替代（历史波动率打底）
- `GVZCLS`（FRED，CBOE 黄金 ETF 波动率指数）：2008 起，官方日更 —— **能回填一年以上**。
- `^GVZ`（Yahoo）：501 点 / 2 年。
- ★**`VXSLVCLS`（白银）已于 2022-02 DISCONTINUED**，近一年 0 点；`^VXSLV`（Yahoo）只返 1 个点。白银没有官方波动率指数，只能用**自算 30 日已实现波动率**（Yahoo 日线 → 30 日滚动标准差 ×√252），**字段名里必须带 RV 标明它不是隐含波动率**。
- 注意 GVZ 是「恐慌程度」不是「往哪个方向恐慌」，**不能替代 put-call 偏斜**。

→ 结论：偏斜与期限结构只能**每日快照自行累积**（写 Notion，幂等 upsert 按日期一行）。

---

## 三、COMEX 期货期权 —— IV ❌ / 持仓 ✅

### IV 全封（八条路实测）
```
CME 官网 API (CmeWS/mvc/...)        403
CME ftp settlement (/ftp/pub/settle) 403
CME datamine                        需付费订阅
Barchart proxies/core-api           403
Yahoo /v7|/v6/finance/options/GC=F   401（三种 symbol 写法全试）
CBOE cdn                            不覆盖期货期权（只有股票/ETF 期权）
ScraperAPI → CME                    200 但返回**中文营销页**，不是 API 响应
```
★ScraperAPI 能绕 IP 封锁，但**绕过封锁 ≠ 拿到 API** —— CME 把非常规请求导向落地页，`len(body)=92882` 看着像成功，实际是 HTML。
★**绝不拿 GLD/SLV 的 ETF 期权 IV 冒充「COMEX 期货期权 IV」**，口径完全不同（股票期权 vs 期货期权）。

### 持仓可做：CFTC 官方相减
```
期权部分 = Disagg(Futures AND Options) − Disagg(Futures Only)
  kh3c-gbw2  = Disaggregated 期货+期权
  72hh-3qpy  = Disaggregated 仅期货
  6dca-aqww  = ✗ Legacy 口径(noncomm/comm)，无 m_money 字段，**不能与 Disagg 混减**
```
- 字段：`m_money_positions_long_all` / `..._short_all` / `open_interest_all`
- 市场名精确匹配 `GOLD - COMMODITY EXCHANGE INC.` / `SILVER - ...`（排除 MICRO）
- ★**口径验证判据**：期权 OI 差（F&O 的 OI − FO 的 OI）**必须恒为正**。口径不匹配会出现负数。
  实测 **170 周（2023-06 至今）金银两市场均 0 次为负** → 口径成立。
  ★教训：最初只验了 14 周就想下结论，样本不足。**长样本验证要在入库前做，不是入库后补。**
- 单位换算：COMEX 黄金 1 张 = 100 金衡盎司，白银 1 张 = 5000 盎司；1 吨 = 32150.7 金衡盎司。
  行研图表（WGC 等）常用「吨」，换算后可与截图对账（实测 2026-06-16 = 353.7 吨，与「近 350 吨」吻合）。

---

## 四、黄金 ETF 分地区资金流 —— ✅ WGC 官方
```
https://fsapi.gold.org/api/v11/charts/etfv2/...
```
免费无 key，`series.tonnes` 按北美/欧洲/亚洲/其他分组，Weekly/Monthly/Quarterly/Yearly，双单位（吨 + 美元），周度可回溯到 2018。与行研截图同源，数值可逐字对账。
**白银无同等官方源**（Silver Institute 无 API，各发行商全败），`?metal=silver` 是返回黄金数据的陷阱。

---

## 五、全球货币供应（M2/M3）30 年 —— ✅ 五大经济体可凑齐

### ★先讲口径：「全球货币供应」没有官方单一口径
任何这张图都是**自行聚合 + 按汇率折美元**的构造。图上必须写明「N 大经济体合计，非官方全球总量」，不能让人误以为有权威机构发布这个数。

| 经济体 | 源 | 区间 | 备注 |
|---|---|---|---|
| 美国 M2 | FRED `M2SL` | 1959-01 ~ 现在 | 月度，活的 |
| 欧元区 M3 | ECB SDMX `BSI/M.U2.Y.V.M30.X.1.U2.2300.Z01.E?format=csvdata` | 1996-01 ~ 现在 | 367 个月度点 ✅ |
| 日本 M2 | BOJ `stat-search.boj.or.jp/ssi/mtshtml/md02_m_1_en.html` | 1980-01 ~ 现在 | HTML 表，见下 |
| 英国 M4 | BoE `/boeapps/iadb/fromshowcolumns.asp?csv.x=yes&SeriesCodes=LPMAUYM&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N` | 1996-01 ~ 现在 | 真 CSV ✅ |
| 中国 M2 | 东方财富 `RPT_ECONOMY_CURRENCY_SUPPLY` | 2008-01 ~ 现在 | 只有 18 年 |
| 中国 1996-2007 补 | 世界银行 `FM.LBL.BMNY.CN`（CHN） | 1996 ~ 2024 | **年度**，插值须标灰 |

### 不能用的（名字对口但已死）
- FRED OECD 系列 `MABMM301*`：**欧元区/日本/英国全部停在 2023-11，中国停在 2018-12**。名字完美对口，一接就是死指标。
- `MABMM301WOM189S` / `MABMM301OEM189S`（全球/OECD 合计）：400，不存在。
- 世界银行 `EMU`（欧元区）：返回 200 但值**全是 None** —— 「API 通了」不代表每个国家都有数，必须逐国看非空计数。
- 英国 BoE `/boeapps/database/fromshowcolumns.asp`：返回 HTML 壳；**要用 `/boeapps/iadb/`** 那条路径才给 CSV。
- IMF IFS SDMX（`dataservices.imf.org`）：本机 URLError，未通。

### ★BOJ HTML 解析陷阱（差点画错图）
`md02_m_1_en.html` 一行有 17 列，**前 8 列是同比增速 %，第 9 列起才是存量（单位：亿円）**。
只按「第一个数字列」解析会拿到 `2`、`1.2` 这种增速值当成 M2 存量。

**救命判据 = 数量级检查**：日本 M2 约 1,250 兆日元 = **1.2e7 亿円**。解析出来的最新值若是个位数/两位数，那是增速不是存量。
正确列：第 9 列，`Series code = MD02'MAM1YAM2M2MO`，实测最新 `12,963,895` 亿円 = 1,296 兆円 ✅

→ **通用规矩：任何新解析的时序，入库前先做一次量级 sanity check**（拿该指标的公认量级对一下），比检查「有没有解析出数字」有效得多。

### 「加速度」怎么算
M2 同比增速的变化率（二阶导）：`accel_t = yoy_t − yoy_{t-1}`（或对 yoy 再取 N 月差分平滑）。有月度序列就能算，无需额外数据源。
