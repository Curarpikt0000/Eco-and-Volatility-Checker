# Free data-source bank: 期权 IV / 偏斜 / 波动率 / 期权持仓

Probed and VERIFIED live 2026-09-21 on Eco-and-Volatility-Checker.
Use this before answering 「这张期权图能不能做」 — the vetting is done, don't re-probe from zero.

Chao 的截图来源多为 WGC / 行研 PPT（Bloomberg 终端出图）。终端数据 ≠ 免费可得。
先分清他要的是 **ETF 期权** 还是 **期货期权** —— 两者数据源完全不同，一个免费一个封死。

---

## ① ETF 期权（GLD / SLV / IAU）—— ✅ 免费真数据，但只有当下快照

```
https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
```
免费、无 key、无需 ScraperAPI（注意：项目 AGENTS.md 里「CBOE 本机 IP 被全线封」
指的是 **Put/Call ratio 的 HTML 与 csv 端点**；这个 delayed_quotes JSON 端点 2026-09 实测直连 200）。

逐合约返回 `option`(OCC代码) / `iv` / `delta` / `open_interest` / `current_price` / `timestamp`。
GLD 实测 7,676 合约、28 个到期日；SLV 25 个；IAU 14 个。

### 能算出的两张图
- **ATM IV 期限结构**：各到期日 |delta|=0.5 处的 IV，排成 1M/3M/6M/12M/18M/24M。
  近月 > 远月 = **倒挂**（市场预期近期震荡）；反之正常上倾。
- **25D 偏斜 / 风险逆转**：25-delta put IV − 25-delta call IV。
  正值 = 看跌期权更贵 = **偏空**；负值 = 偏多。

### 方法论要点
**用 delta 线性插值，不要取最近的合约。** 合约 delta 不会正好等于 0.25/0.50，
取最近点会因行权价网格疏密而抖动。
```python
pts = sorted([(abs(x["d"]), x["iv"]) for x in arr if 0.01 < abs(x["d"]) < 0.99])
# 在 target 两侧线性插值
```

### ★必须做的去重保护 —— 否则画出假的期限结构
到期日不足的标的，多个 tenor 会**落到同一个到期日**，表格里出现三行一样的数（看起来像真数据）。
实测 **SGOL 只有 4 个到期日**，12M/18M/24M 全部回落到同一个 179 天的到期。
```python
seen = set()
for a in term:
    if a["exp"] in seen: continue   # 同一到期只保留一次
    seen.add(a["exp"])
```
处理方式：剔除重复 + 在卡片上标注「期权到期日不足，无法构建完整期限结构」，**不要用重复值凑满六个期限**。

### ❌ 历史：没有。这条别再找了
| 尝试 | 结果 |
|---|---|
| CBOE `?date=YYYY-MM-DD` | **200，但 timestamp 与现价和不带参数时完全相同** → 参数被静默忽略 |
| CBOE `/historical_data/` `/historical_options/` | 403 |
| Alpha Vantage `HISTORICAL_OPTIONS` | **付费端点**（免费 key 返回 "This is a premium endpoint"）|
| Alpha Vantage `REALTIME_OPTIONS`（免费档）| **返回占位假数据** —— 见下方陷阱 |
| ORATS | 401 |
| Nasdaq Data Link（CBOE 数据集）| 403，已转付费 |

⇒ 偏斜与期限结构**只能从今天起每日快照累积**。老实告诉 Chao，别承诺回溯。

### ★★ Alpha Vantage 免费档的占位假数据陷阱
`REALTIME_OPTIONS` 免费 key 返回 HTTP 200 + 结构完整的 JSON，但内容是假的：
```
contractID: XXYYZZ...    expiration: 2099-99-99    价格字段全是 100
```
**差点当真数据接进 fetcher。** 判据：看 `expiration` 是否是合法日期、价格是否全等。
另一个前置教训：**demo key 能跑 IBM ≠ 免费 key 能跑 GLD**。demo 是官方样例白名单，
拿 demo 跑通就断言「免费档可用」是错误推断（我犯过，让 Chao 白注册了一个 key）。

---

## ② COMEX 期货期权 IV —— ❌ 免费路全封，八条都试过

| 源 | 结果 |
|---|---|
| CME 官网 API（product-slate / Settlements / Quotes / Volume）| 403 |
| CME `ftp/pub/settle/*.txt` | 403 |
| CME datamine | 需付费订阅 |
| Barchart `proxies/core-api` | 403 |
| Yahoo `v7/v6/finance/options/GC=F`（含 `GC%3DF`、`GCZ26.CMX`）| 401 全部 |
| CBOE | 只覆盖股票与 ETF 期权，**不含期货期权** |
| **ScraperAPI 走 CME** | 200 但**返回中文营销页**，不是 API 响应 —— IP 绕过了，反爬没绕过 |

COMEX 期货期权 IV 是 **CME 的商业数据产品**。
**绝不拿 GLD/SLV 的 ETF 期权 IV 贴上「COMEX 黄金期权」标签** —— 口径完全不同，
那是 WGC `?metal=silver` 陷阱的自制版。

### ✅ 但 COMEX 期权的「持仓方向」拿得到（诚实替代品）
```
期权部分 = CFTC Disagg(Futures AND Options) − CFTC Disagg(Futures Only)
           kh3c-gbw2                          72hh-3qpy
```
两者同为 Disaggregated 口径、同含 `m_money` 字段，可相减。

**★口径验证必须用长样本**：我先只验了 14 周就想入库，不够。
拉到 **170 周（2023-06 至今，3 年+）**，金银**期权 OI 差均 0 次为负** —— 口径不匹配必然出负数，故成立。
判据函数：`neg = sum(1 for d in common if fao[d].oi - fo[d].oi < 0)`，`neg > 0` 就在 UI 上标警告。

**不能用的**：`6dca-aqww` 是 **Legacy 口径**（noncomm/comm），无 `m_money`，不能与 Disagg 混减。

单位换算（对齐 WGC/行研的「吨」表述）：
```
COMEX 黄金 1 张 = 100 金衡盎司   白银 1 张 = 5000 盎司   1 吨 = 32150.7 盎司
吨 = 张数 × 每张盎司 / 32150.7
```
实测 2026-09-15：金 MM 净多 133,116 张 = **414.0 吨**（对上了 WGC 截图的「近 350 吨」@6月中 = 353.7 吨）。

---

## ③ 波动率指数 / 已实现波动率 —— 一年历史可回填

| 序列 | 源 | 区间 | 备注 |
|---|---|---|---|
| `GVZCLS` CBOE 黄金ETF波动率指数 | FRED | 2008~至今 | ✅ 官方，日频 |
| `^GVZ` | Yahoo | 2 年 501 点 | 同上，备用 |
| **`VXSLVCLS` 白银波动率指数** | FRED | **2022-02 DISCONTINUED** | ❌ 近一年 0 点，不可用 |
| `^VXSLV` | Yahoo | **只返 1 点** | ❌ 数据残缺 |
| GLD/SLV 30日已实现波动率 | 自算（Yahoo 日线滚动标准差年化）| 470 点 | ⚠️ 是 RV 不是 IV，**字段名必须带 RV 标明** |

白银官方 IV 指数停更 ⇒ 用自算 RV 替代，但**字段名与图例都要写明「已实现波动率」**，不能混进 IV 曲线。

---

## ④ 全球货币供应 M2 30 年（2026-09 探测）

**先纠正 Chao 的前提：「全球货币供应」没有官方单一口径。** 任何这张图都是自己聚合的，
必须在图上写明「N 大经济体合计，按当期汇率折美元，非官方总量」。

| 经济体 | 源 | 区间 | 状态 |
|---|---|---|---|
| 美国 M2 | FRED `M2SL` | 1959-01~ | ✅ 月度 |
| 欧元区 M3 | ECB SDMX `BSI/M.U2.Y.V.M30.X.1.U2.2300.Z01.E?format=csvdata` | 1996-01~2026-07（367点）| ✅ 月度 |
| 英国 M4 | BoE `boeapps/iadb/fromshowcolumns.asp?...SeriesCodes=LPMAUYM` | 1996-01~ | ✅ 月度真 CSV |
| 日本 M2 | BOJ `stat-search.boj.or.jp/ssi/mtshtml/md02_m_1_en.html` | 1980-01~ | ✅ 月度，需解析 HTML |
| 中国 M2 | 东财 `RPT_ECONOMY_CURRENCY_SUPPLY` | 2008~ | ⚠️ 只有 18 年 |
| 中国 1996-2007 补 | 世界银行 `FM.LBL.BMNY.CN` | 1996~2024 | ✅ 但**年度** |

### 已排除
- FRED OECD 系列 `MABMM301*`：**欧/日/英 停在 2023-11，中国停在 2018-12** —— 名字对口但不能用于「每年更新」。
- 世界银行 `country/EMU`：**欧元区全 None**（其他国家有数）—— API 通 ≠ 每国都有数。
- 世界银行 `country/WLD`（世界总计）：全 None。
- IMF IFS SDMX `dataservices.imf.org`：URLError，本机不通。
- 国家统计局 `data.stats.gov.cn/easyquery.htm`：403。

### ★★ BOJ HTML 解析的数量级陷阱
MD02 页面前 8 列是**同比增速百分比**，不是存量。我第一次解析抓到的就是 `2` / `1.2` 这些。
**日本 M2 存量约 1,250 兆日元 = 12,500,000 亿円（页面单位 100 million yen）**，
真正的存量在 **col 9**（`MD02'MAM1YAM2M2MO`，实测 12,963,895）。

**规则：解析任何陌生 HTML 表格后，先做数量级检查再入库。**
```python
mag = "存量" if 5e6 < abs(v) < 5e7 else ("增速%" if abs(v) < 100 else "其他")
```
差一点把增速当存量画成图 —— 图会很好看，且完全错。
