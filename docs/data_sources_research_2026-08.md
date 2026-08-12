# 8 个美股长期估值/结构性指标 —— 稳定免费可编程数据源实测报告

> 实测日期: 2026-08-12 (JST)  ·  环境: .venv (requests / pandas / akshare 1.18.81)
> 铁律: 绝不编数字。以下每个"实测最新值"均为本次真实拉取所得。
> 验证脚本: `scratch/verify_all.py`(一次性复现全部 6 个可用源)
> 通用请求头(多数网页源需要正常浏览器 UA,不需要 Jina):
> `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36`

## 结论速览

| # | 指标 | 结果 | 源 | 实测最新值 |
|---|------|------|----|-----------|
| 1 | 巴菲特指标 | ✅ 找到(FRED,免维护) | FRED NCBEILQ027S / GDP | 218.1% (2026-Q1) |
| 2 | 希勒 CAPE | ✅ 找到(网页直连) | multpl.com | 42.24 (2026-08-11) |
| 3 | Conference Board LEI | ⚠️ 真源付费,给替代 | FRED OECD CLI USALOLITOAASTSAM | 100.80 / 6m +0.58pt (2026-06) |
| 4 | AAII 股票配置% | ✅ 找到(网页直连) | aaii.com/assetallocationsurvey | Stocks Total 70.38% (2026-07) |
| 5 | 内部人买卖比 | ✅ 找到(网页直连,替 gurufocus) | openinsider.com | 买/卖($)=0.270 (近30日榜) |
| 6 | IPO 发行量 | ✅ 找到(网页直连,替 Renaissance) | stockanalysis.com/ipos/2026 | 2026 YTD 225 宗 |
| 7 | 保证金负债/GDP | ⚠️ 依赖 #8,给 FRED 替代 | 见下 | — |
| 8 | FINRA 保证金负债 | ❌ 官方 API 需鉴权,给替代 | 见下 | — |

---

## 1. 巴菲特指标 (Buffett Indicator, 美股总市值/GDP)

**✅ 推荐: FRED,纯 API,零反爬,免维护。**

- 分子: `NCBEILQ027S` = Nonfinancial Corporate Business; Corporate Equities; Liability (市值口径, 单位=百万美元, 季度)
- 分母: `GDP` (单位=十亿美元, 季度)
- 公式: `NCBEILQ027S / (GDP * 1000) * 100`

获取(已有 fetchers/fred.py::fetch_fred_latest 可直接复用):
```
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id=NCBEILQ027S&api_key=<KEY>&file_type=json&sort_order=desc&limit=2
GET 同上 series_id=GDP
```
**实测最新值: 218.1%** (2026-Q1: 市值 69,511,628M / GDP 31,865.721B×1000)。

说明: 这是美联储 Z.1 Flow of Funds 官方口径的"公司股权/GDP",是巴菲特指标最权威的季度版本(currentmarketvaluation.com 的备用算法即用此)。缺点=季度频率有滞后(约 Q+2.5 月发布)。
若要每日高频值,可用 Wilshire 5000 全收益指数近似分子,但 FRED 的 WILL5000* 已停更;故日频无稳定免费源,季度 FRED 为最佳可编程方案。

akshare `stock_buffett_index_lg` 实测=A股口径,与美股无关,不采用。
currentmarketvaluation.com 用普通 UA 可 200(不需 Jina),但当前数值经 JS 渲染,静态 HTML 只含 meta "较历史均值高 64.84% / Strongly Overvalued" 文字,拿不到干净数字 → 不如 FRED。

---

## 2. 希勒 CAPE (Shiller PE / CAPE Ratio)

**✅ 推荐: multpl.com 网页直连,普通 UA 即 200,不需 Jina。**

```
GET https://www.multpl.com/shiller-pe/table/by-month   (普通浏览器 UA)
解析: pandas.read_html -> 表 0, 列 [Date, Value], 第 0 行为最新
      值含 UTF-8 空格前缀 &#x2002;, 用 re.sub(r"[^\d.]","",value) 清洗
```
**实测最新值: CAPE = 42.24 (2026-08-11)** (次新 Jul 1 2026 = 40.73)。

数据出处=Robert Shiller 官方数据,月度更新+当月按最近收盘滚动。同域 `/s-p-500-pe-ratio/table/by-month` 给 **P/E TTM = 29.77 (2026-08-11)**,是天然的 CAPE 备份/交叉验证。
FRED 无 Shiller CAPE 系列(实测 "shiller cape"/"cyclically adjusted" 搜索均空)。

---

## 3. Conference Board 领先经济指数 LEI (6 个月变化率)

**⚠️ 真源已闭源: conference-board.org 反爬严重且 LEI 具体数值为付费内容,无免费 API/CSV。FRED 旧 USSLIND 已于 2020-02 停更。**

**替代(同类领先指标, FRED 纯 API, 更新至 2026-06):**
- `USALOLITOAASTSAM` = OECD Composite Leading Indicator for US (振幅调整, 基准=100, 月度)
- 判读: >100 且上升=扩张; <100 或下行=转弱。可算 6 个月变化(取最新与 6 期前之差)。
```
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id=USALOLITOAASTSAM&api_key=<KEY>&file_type=json&sort_order=desc&limit=7
6m 变化 = obs[0].value - obs[6].value
```
**实测: 100.80 (2026-06),6 个月变化 = +0.58pt**(仍在扩张区且回升)。

其它可选 FRED 领先系: `BBKMLEIX` (Brave-Butters-Kelley Leading Index, 月度, 2026-06)。
若坚持要"经济动能转折"信号,ISM/PMI 制造业 PMI 是市场最认的 LEI 平替(但 ISM 官方数亦付费; 免费可用 FRED `MANEMP`/`INDPRO` 或 markit 报道值)。**建议采用 OECD CLI**,因其纯 API、无鉴权、月度稳定。

---

## 4. AAII 家庭股票配置 % (Asset Allocation, Stocks%)

**✅ 推荐: aaii.com/assetallocationsurvey 公开页,普通 UA 即 200,不需登录/不需 Jina。**

```
GET https://www.aaii.com/assetallocationsurvey   (普通浏览器 UA)
解析: pandas.read_html -> 找 shape==(10,4) 的表
      行 "Stock Funds"(0)/"Stocks"(1)/"Stocks Total"(2 号索引3) 
      即 iloc[3,2] = 股票总配置%
```
**实测最新值 (2026-07): Stocks Total = 70.38%** (= Stock Funds 39.78% + Stocks 30.60%);
Bonds Total 15.43%,Cash 14.19%。含环比("# change from last month"列)。

说明: 这是"家庭股票配置"官方口径且免费公开,月度更新。比 gurufocus 抓取稳得多。

---

## 5. 内部人买卖比 (Insider Buy/Sell Ratio)

**✅ 推荐: openinsider.com 网页直连(替代被 Cloudflare 403 的 gurufocus)。**

gurufocus.com 实测 = **403(Cloudflare 拦截)**,已弃。openinsider 普通 UA 即 200。
```
GET http://openinsider.com/insider-purchases   (近期内部人买入榜)
GET http://openinsider.com/insider-sales       (近期内部人卖出榜)
解析: pandas.read_html -> 取含 'Ticker' 列的主表; 'Value' 列去 $,+ 后求和(取绝对值)
比值 = 买入$总额 / 卖出$总额
```
**实测: 买入 $146,835,549 / 卖出 $544,811,576 → 买卖比($) = 0.270**(卖压占优)。

⚠️ 局限: openinsider 每页封顶 100 行,该值为"近期榜单前 100 笔"口径的比率,非全市场完整聚合;适合做趋势方向信号(比率↑=买盘转强),不宜当精确绝对量。
另可用页面 `http://openinsider.com/latest-cluster-buys` / `latest-insider-sales` 或 SEC EDGAR Form 4 全量(免费但需自聚合,工程量大)。作为脆弱源替代,openinsider 已是最优性价比。

---

## 6. Renaissance IPO 发行量 (IPO count / 发行数)

**✅ 推荐: stockanalysis.com/ipos/ 网页直连(替代 Renaissance Capital 反爬)。**

```
GET https://stockanalysis.com/ipos/2026/    (当年全部已完成 IPO 列表)
解析: pandas.read_html -> 表 0 (列 [IPO Date, Symbol, Company Name, IPO Price, Current, Return])
      len(表0) = 当年 YTD IPO 宗数
```
**实测: 2026 YTD IPO 数 = 225 宗**(表内含每宗代码/日期/发行价/回报)。
`https://stockanalysis.com/ipos/` 首页含"近期/即将上市"日历(表 [Date, Symbol, Name])。

说明: 可按年拉 `/ipos/<year>/` 做同比;发行量趋势(放量=市场情绪高涨/顶部信号)与 Renaissance IPO 口径一致。stockanalysis 的 `api.stockanalysis.com/api/ipos/statistics` 实测 404,故用网页表解析(稳定)。

---

## 7. 保证金负债/GDP (Margin Debt / GDP %)

**⚠️ 分子(FINRA 月度保证金负债)无免费可编程源(见 #8);分母 GDP 有 FRED。故该比率无法用官方月度数直接自动化。**

**替代方案(季度, 纯 FRED API):** 用美联储 Z.1 的券商客户信贷代理分子:
- `BOGZ1FL663067003Q` 类"Security Brokers and Dealers; Payables to Customers"科目(实测 `BOGZ1FL663167003Q` 更新至 2026-Q1)——近似客户在券商的融资/信贷规模。
- 除以 `GDP` 得季度比率。
局限: 这是季度 Flow-of-Funds 口径,与 FINRA 月度"margin debt"数值不等价,只能反映趋势方向,不能替代精确月度水平。
若必须要 FINRA 精确口径,只能人工/agent 从 finra.org 页面读取后写 overrides(与项目现有"难源 agent web_extract 补 overrides"机制一致)。

---

## 8. FINRA 保证金负债 (Margin Debt, 月度)

**❌ 无免费可编程源。实测全部失败,记录如下:**

- `finra.org/investors/.../margin-statistics` 网页: **403**(反爬)
- FINRA 站内 xlsx/csv 猜测路径: **403**
- FINRA 公开 API 网关 `api.finra.org`: **部分数据集可匿名 200**(实测 `otcMarket/consolidatedShortInterest`、`regShoDaily` 均返回真数据),**但 margin statistics 数据集不在免费匿名开放集内** —— 暴力枚举 `marginStatistics`/`margin`/`marginData`… × 多个 group 全部 **404**。FINRA Margin Statistics 属需注册鉴权(FINRA Data API 账户)的数据集。
- Nasdaq Data Link (旧 Quandl) `FINRA/MARGIN_DEBT`: **403 (Incapsula 拦截)**
- advisorperspectives / yardeni 转载页: **403 / 307**,不可编程。

**可落地替代(择一):**
1. **趋势代理(自动化):** FRED 券商客户信贷季度系列(见 #7),纯 API,免维护,给方向。
2. **精确月度值(半自动):** 沿用项目现有"难源"模式 —— cron agent 用 web_extract 从 finra.org margin-statistics 页面读最新月 Debit/Credit,写 `data/manual_overrides.json`;脚本失败回退 overrides。这是 FINRA 精确口径唯一免费途径。

---

## 附:一次性复现命令
```
cd /home/user/Projects/Eco-and-Volatility-Checker
.venv/bin/python scratch/verify_all.py
```
(脚本读 .env 里的 FRED_API_KEY,实测全部 6 个可用源并打印带日期的最新值。)
