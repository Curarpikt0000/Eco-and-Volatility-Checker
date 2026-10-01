# 期权希腊字母 / GEX / IV 期限结构 —— 免费数据源实测地图

2026-09-21 实测（Eco-and-Volatility-Checker）。所有结论都是**跑过探针看到真返回体**才写的。

## 1. CBOE delayed quotes —— 唯一可用的免费逐合约源

```
https://cdn.cboe.com/api/global/delayed_quotes/options/<TICKER>.json
```

GLD 实测：7,758 个合约，`data.current_price` 给现价，`data.options[]` 每个合约字段：

```
option  bid ask  iv  open_interest  volume
delta  gamma  vega  theta  rho  theo  prev_day_close …
```

非空率（GLD 7,758 合约）：`delta` 7,660 / `theta` 7,059 / `iv` 6,595 / `vega` 6,655 /
`gamma` 6,260 / `rho` 6,296 / `open_interest` 5,415。

**关键：gamma 是现成的，不必用 BS 公式自估。** 这决定了 GEX 可做。

合约代码解析：`^[A-Z]+(\d{6})([CP])(\d{8})$` → YYMMDD / C|P / strike×1000。
必须按 `exp >= today` 过滤，否则混入已过期合约。

### 致命陷阱：`?date=YYYY-MM-DD` 返回 200 但**参数被静默忽略**
判据不是状态码，是**比对两次返回的 `timestamp` 和 `current_price`**：加了 date 参数后
二者与不加时完全相同（实测 `2026-09-21 11:31:10` / 399.24 一模一样）→ 它压根没理你。
**结论：CBOE 只有当下快照，无历史。** 任何 IV 期限结构 / 偏斜的历史都只能从接入日起累积。

## 2. 各条历史源的实测结局（别再重复探）

| 源 | 结果 |
|---|---|
| Alpha Vantage `HISTORICAL_OPTIONS` | **premium endpoint**。demo key 能跑通 IBM 是官方样例白名单，≠ 免费 key 能跑 GLD |
| Alpha Vantage `REALTIME_OPTIONS` | 免费档返回**占位假数据**：symbol `XXYYZZ`、到期 `2099-99-99`、价格全 100 |
| ORATS | 401 付费 |
| Nasdaq Data Link（CBOE 数据集） | 403，已转付费 |
| FRED `GVZCLS`（黄金波动率指数） | ✅ 4,773 点，2008 起，可作历史打底 |
| FRED `VXSLVCLS`（白银） | **2022-02 已停更**，近一年 0 点 → 改用自算 RV30 并在字段名里写明 `RV`（非隐含） |
| CME 官网 API / ftp settlement / datamine | 403 / 403 / 付费 |
| Barchart | 403 |
| Yahoo 期货期权链 | 401（v7/v6 × 三种 symbol 写法全试过） |
| ScraperAPI 走 CME | 200 但返回**中文营销页**，不是 API 响应 —— 看响应体不要看状态码 |

## 3. ATM IV 期限结构算法

- ATM 取 **|delta|=0.5 处线性插值**，不要取最近行权价（离散跳变会造成假形态）。
- 25D 偏斜 = `25D put IV − 25D call IV`；负值 = call 更贵 = 偏多。
- **同一 ticker 出现重复到期日必须剔除**：SGOL 只有 4 个到期日，12M/18M/24M 会全部落回同一个
  179 天到期，画出来是三个一模一样的点（假数据）。代码里加通用保护，不要只对 SGOL 特判。

## 4. GEX（Gamma Exposure）

```
单合约 GEX = gamma × OI × 100 × spot² × 0.01
Net GEX = Σ；符号约定 call/put 相反
```

**符号约定是假设不是事实**：主流（SpotGamma 那套）假设做市商 short call / long put，
翻过来整张图上下颠倒。图上必须写明用了哪套假设。

已实测可算出：Net GEX、各行权价 GEX 柱、最大正/负 gamma 墙。
GLD 2026-09-21 现价 399.26：Net GEX +0.660 Bn$，最大负 GEX 在 K=390（-0.117 Bn），
最大正在 K=450（+0.203 Bn）。

**Flip Point 未解**：累计法算出 460（离现价 399 太远，不合理），spot 扫描法返回 None。
公开图（WGC/SpotGamma 类）的 flip 通常**紧贴现价**（如现价 399.24 / flip 400.17），
所以「flip 离现价很远」本身就是算错的信号。**有现成公开值时拿它当基准反推校验**，别自说自话。

**COMEX 期货期权 GEX 做不到** —— CME 不给逐合约希腊字母（见上表八条路径）。
只能做 GLD/SLV/IAU 这类 CBOE 覆盖的 ETF 期权。

## 5. ★不要用 ETF 期权 IV 冒充 COMEX 期货期权 IV

拿 GLD 的 IV 贴上「COMEX 黄金期权」标签，和 WGC `?metal=silver` 返回黄金数据是同一类错误，
只不过是自制版。做不到就在页面写明做不到，并列出封锁路径。
