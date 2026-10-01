# 美国养老金资产配置：Fed Z.1 权威口径与两个会致命的分母/科目陷阱

用于回答「美国养老金持有多少国债 / 多少股票」这类问题，或把养老金敞口做成 dashboard 板块。
2026-08-25 Chao 提问时建立；数据全部来自 Fed 一手表，非二手估算。

---

## A. 权威源：Fed Z.1 Financial Accounts（四张表，别只看一张）

| 表 | 覆盖 | FRED 前缀 |
|---|---|---|
| **L.117** | 合并（私人 + 州地方 + 联邦） | `BOGZ1FL59…` / `BOGZ1LM59…` |
| **L.118** | 私人养老金（含 401k 等 DC） | `…FL57…` / `…LM57…` |
| **L.119** | 联邦政府雇员退休金（含 TSP） | `…FL34…` / `…LM34…` |
| **L.120** | 州与地方政府雇员退休金 | `…FL22…` / `…LM22…` |

两种取数路径，**FRED API 优先**（与本项目 FRED 铁律一致）：

```python
from src.fetchers.fred import fetch_fred_history
fetch_fred_history('BOGZ1LM593064105Q', start='2025-06-01')   # 合并·公司股票
```

HTML 表兜底（拿脚注/行标签时有用）：
`https://www.federalreserve.gov/releases/z1/<YYYYMMDD>/html/l118.htm`

- ★ `/releases/z1/preview/html/l117.htm` 存在但**数据格全是 `--`**，只有行名和 series id。
  要真数字必须用带日期的历史 release 目录，或直接走 FRED。
- 日期目录不是每个都有（`20260611` 对 l119/l120 返 404，`20260319` 有）。404 就换一期，别放弃。

## B. ★★陷阱一：`claims on pension fund on sponsor` 不是真资产，必须从分母剔除

Fed 的 "Total financial assets" **包含**一行
`Claims of pension fund on sponsor`（= 未拨备缺口，雇主欠计划的钱）。
它是会计意义上的应收，不是任何已持有的证券。**不剔除会把所有配置比例系统性摊薄。**

差异有多大（2026Q1）：

| 口径 | 合并总额 | 股票占比 |
|---|---|---|
| 原始 Total financial assets | $29.64T | 32.1% |
| **剔除 claims 后（正确）** | **$26.02T** | **36.5%** |

州地方最夸张：$10.01T → **$7.31T**（claims 高达 $2.70T），股票占比 36.2% → **49.6%**。

## C. ★★陷阱二：联邦 TSP 的 G Fund 记在 `Loans`，不在 `Treasury securities`

L.119 里 `Treasury securities` 只有 **$22B（0.5%）**，看上去联邦养老金几乎不持国债 —— **完全相反**。
TSP G Fund 是**不可交易特别国债**，Fed 把它归到
`Loans (other loans and advances)` = **$3.566T，占联邦真实资产 82.6%**。

脚注原文（l119.htm `</table>` 之后）明确写着：
> *Nonmarketable Treasury securities classified as loans and suspended reinvestments in the Thrift Savings Plan G Fund.*

→ 报"国债敞口"时必须分两个口径说：**直接持有** vs **含 G Fund 的广义**。

## D. 结论（2026Q1，剔除 claims 后的真实资产 $26.02T）

| 类别 | 金额 | 占比 |
|---|---|---|
| 国债（直接持有） | $1.203T | **4.6%** |
| 机构/GSE 债 | $0.491T | 1.9% |
| 企业与外国债 | $1.613T | 6.2% |
| Loans（主要是 TSP G Fund 国债） | $3.600T | 13.8% |
| **公司股票（直接）** | $9.501T | **36.5%** |
| **共同基金/ETF 份额** | $5.807T | **22.3%** |
| **股票 + 基金** | $15.31T | **58.8%** |
| 全部可交易债券类 | — | 14.7% |
| 广义国债（直接 + G Fund） | — | 18.3% |

分部门差异极大，**绝不可混谈**：

| | 真实资产 | 国债 | 股票 | 共同基金 | 股+基 |
|---|---|---|---|---|---|
| 私人（L.118） | $14.39T | 4.2% | 35.9% | 38.4% | **74.3%** |
| 州地方（L.120） | $7.31T | 7.9% | 49.6% | 3.8% | **53.4%** |
| 联邦（L.119） | $4.32T | 0.5% | 16.3% | 0% | 16.3%（另 82.6% G Fund） |

- 私人近 3/4 在权益：DC 计划占其中 $11.8T，全靠共同基金/ETF 承载。
- 州地方直接买股票最猛（49.6%），基金占比低 —— 用外部管理人直接持仓。

## E. 用途：给 KOL 论点做事实校验（本次的实战价值）

Armstrong 2026-06-24 Shorts 原话：
> "欧洲**法律规定养老金 80% 以上必须持有政府债**，政府一破产你的养老金就没了。"

他说的是**欧洲**。套到美国正好相反（直接国债 4.6%，股票+基金 58.8%），
这**削弱**了他"股灾不致萧条、债灾才致萧条"在美国语境下的说服力 —— 美国养老金真正的敞口在股市。

→ **若把这类 KOL 观点写进 dashboard/报告，必须标注适用地域**，否则误导。
这是「给出反向证据」原则（见 `kol-source-coverage-youtube-shorts.md` §D）在数据侧的落地：
拿一手数据去检验 KOL 的论断，而不是复述。

## F. 复用脚本骨架

```python
v = {  # 2026Q1, 百万美元, 已从 FRED 取回
 'L117': dict(total=29640944, tsy=1203049, eq=9501492, mf=5806636, claims=3619793, loans=3600202),
 'L118': dict(total=14588015, tsy=606993,  eq=5172167, mf=5531524, claims=195992),
 'L120': dict(total=10005124, tsy=573867,  eq=3625108, mf=275112,  claims=2695529),
 'L119': dict(total=5047805,  tsy=22189,   eq=704217,  loans=3566418, claims=728272),
}
for k, d in v.items():
    t = d['total'] - d.get('claims', 0)          # ★必须剔除
    print(k, f"股票{100*d['eq']/t:.1f}% 基金{100*d.get('mf',0)/t:.1f}% 国债{100*d['tsy']/t:.1f}%")
```

关键 series id：
`BOGZ1FL594090005Q`(合并总额) · `BOGZ1LM593061105Q`(国债) · `BOGZ1LM593064105Q`(股票) ·
`BOGZ1LM593064205Q`(共同基金) · `BOGZ1FL593073005Q`(claims) · `BOGZ1FL594023005Q`(loans) ·
`BOGZ1FL343069005Q`(联邦 G Fund loans)。
州地方的国债/股票在 FRED 上是 `…LM223061143Q` / `…LM223064145Q`（**尾号 143/145，不是 105**，
用 105 会返 EMPTY —— 拿不到时先怀疑 series id 后缀，别急着说"FRED 没这个数据"）。
