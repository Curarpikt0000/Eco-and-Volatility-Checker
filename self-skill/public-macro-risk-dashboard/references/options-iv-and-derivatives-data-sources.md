# 期权 IV / 衍生品持仓 免费数据源地图（2026-09 实测）

> 缘起：Chao 要复刻行研截图里的三张图 —— ETF 期权 ATM IV 期限结构、
> 25-Delta 偏斜（risk reversal）、COMEX 期货期权。做之前先看这份，别再把八条死路重走一遍。

---

## 一、能用的：CBOE delayed quotes（ETF / 股票期权）

```
https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
```

- 免费、无 key、无需 ScraperAPI（本项目 AGENTS.md 记的「CBOE 全线封」是指
  `cboe.com` 的 HTML 与 csv 端点；**这个 cdn JSON 端点 2026-09 实测直连 200**）。
- 返回逐合约 `iv` + `delta` + `open_interest` + `current_price` + `timestamp`。
- 合约代码正则：`^[A-Z]+(\d{6})([CP])(\d{8})$` → YYMMDD / C或P / 行权价×1000。
- 实测规模：GLD 28 个到期日 / SLV 25 / IAU 14 / **SGOL 仅 4**。

### 两张图怎么算

| 图 | 算法 |
|---|---|
| ATM IV 期限结构 | 每个到期日在 `\|delta\|=0.50` 处**线性插值** IV，call/put 取均值 |
| 25D 偏斜（risk reversal） | `interp(put, 0.25) − interp(call, 0.25)`，**正=put 更贵=偏空** |

**必须插值不能取最近合约** —— 真实合约 delta 不会正好是 0.25/0.50，取最近点误差可达数个波动率点。

```python
def interp_iv_at_delta(arr, target):
    pts = sorted([(abs(x["d"]), x["iv"]) for x in arr if 0.01 < abs(x["d"]) < 0.99])
    if len(pts) < 2: return None
    for i in range(len(pts) - 1):
        (d0, v0), (d1, v1) = pts[i], pts[i + 1]
        if d0 <= target <= d1:
            return v0 if d1 == d0 else v0 + (v1 - v0) * (target - d0) / (d1 - d0)
    return min(pts, key=lambda p: abs(p[0] - target))[1]
```

### ★到期日不足会伪造出「假期限结构」

把 1M/3M/6M/12M/18M/24M 各自映射到「最接近该 DTE 的到期日」时，
**到期日稀少的标的会让多个 tenor 落到同一个到期** —— 表格里出现三行一模一样的值，
看起来像「远端曲线走平」，其实是重复值。

SGOL 就是：12M/18M/24M 全部回落到同一个 179 天到期。

**必做去重**：按 `exp` 去重，丢弃重复 tenor，记 `dup_dropped` 计数并在卡片上标注；
去重后 tenor 数不足就整只标的排除，不要凑数。

---

## 二、无免费历史：偏斜与期限结构只能每日快照累积

逐条实测，全部堵死：

| 源 | 结果 |
|---|---|
| CBOE `?date=YYYY-MM-DD` | **200，但 `timestamp` 与现价和不带参数时完全相同** —— 参数被静默忽略 |
| CBOE `/historical_data/`、`/historical_options/` | 403 |
| Alpha Vantage `HISTORICAL_OPTIONS` | `"This is a premium endpoint"`（付费） |
| Alpha Vantage `REALTIME_OPTIONS`（免费档） | ★**返回占位假数据** |
| ORATS | 401 |
| Nasdaq Data Link（CBOE 数据集） | 403 |

### ★★Alpha Vantage 免费档期权 = 占位假数据（最阴的陷阱）

免费 key 调 `REALTIME_OPTIONS` 会返回**结构完整、字段齐全、HTTP 200** 的响应，
但内容是官方放的示意样本：

```
contractID = XXYYZZ...
expiration = 2099-99-99
所有价格字段 = 100
```

**判据不能是「200 且非空」，必须看内容特征**（到期日是否是真日期、价格是否千篇一律）。

同类教训：demo key 能跑通 IBM **不等于**免费 key 能跑通 GLD —— demo 是官方样例白名单。
不要用 demo 跑通就推断免费档可用，要用真 key 对真标的实测。

### 可回溯一年的替代品（诚实降级）

| 指标 | 源 | 说明 |
|---|---|---|
| GVZ 黄金 ETF 波动率指数 | FRED `GVZCLS` | 官方，2008 至今 |
| 白银官方波动率指数 `VXSLVCLS` | ★**2022-02 已 DISCONTINUED**，近一年 0 点，不可用 |
| GLD/SLV 30 日已实现波动率 | 自算（Yahoo 日线滚动标准差年化） | **字段名必须带 RV 标明「已实现」非「隐含」** |

GVZ 回答的是「恐慌程度」，**不能替代偏斜**（偏斜回答的是「往哪个方向恐慌」）。

---

## 三、COMEX 期货期权 IV：无免费源，八条路全封

```
CME 官网 API (CmeWS/mvc/...)      403
CME ftp settlement (/ftp/pub/...) 403
CME datamine                      需付费订阅
Barchart proxies/core-api         403
Yahoo /v7|v6/finance/options/GC=F 401（三种 symbol 写法全试）
CBOE cdn                          不覆盖期货期权（只有股票/ETF 期权）
ScraperAPI 走 CME                 200 但返回中文营销页，不是 API 响应
```

**ScraperAPI 能绕 IP 封锁 ≠ 能拿到 API 数据** —— CME 把爬虫请求导向营销页，
`status=200 len=92882` 看着像成功，实际是 `<title>CME Group芝商所官网…</title>`。

### 绝不做的事

**不要拿 GLD/SLV 的 ETF 期权 IV 冒充「COMEX 黄金期权 IV」** —— 口径完全不同
（一个是股票期权走 OCC/CBOE，一个是期货期权走 CME）。这是自制版的
「WGC `?metal=silver` 返回黄金数据」陷阱。

### 能拿到的替代：COMEX 期权**持仓方向**（不是 IV）

```
期权部分 = CFTC Disaggregated(Futures AND Options) − Disaggregated(Futures Only)
           kh3c-gbw2                                72hh-3qpy
```

- 两者同为 Disaggregated 口径、同含 `m_money` 字段，**可以相减**。
- ★`6dca-aqww` 是 **Legacy 口径**（noncomm/comm），**无 `m_money`**，
  不能与 Disagg 混减 —— 曾在此绕了一整轮。
- **口径验证判据：期权 OI 差恒为正**。口径不匹配必然出现负数。
  实测 **170 周（2023-06 起，3 年+）金银两市场均 0 次为负** → 口径成立。
  ★先前只验 14 周就下结论，样本不足；长样本验证是零成本的，别省。
- 单位换算：COMEX 金 1 张 = 100 金衡盎司，银 1 张 = 5000 盎司；1 吨 = 32150.7 盎司。
  吨口径用于对齐 WGC / 行研图表的「吨」表述。
- 频率：CFTC 周度（周五发布、数据截至周二）→ 徽章必须写「持仓周更」，不许标日更。

---

## 四、Gold ETF 期权名义市值（US$bn）

行研图里的「Gold ETF options −230 亿美元」属 **WGC / Metals Focus 加工数据**，
CFTC 不含 ETF 期权（那是股票期权，归 OCC/交易所）。OCC 公开端点只有全市场总量，
无 GLD 单券。→ 无免费源，如实说明。
