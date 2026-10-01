# 指标口径核查：Chao 质疑算法时，先查权威定义再对照实现

2026-08-23 Chao：「你网上搜一下套利空间我这么计算正确么，是不是应该计算期货和现货？」
—— **他是对的**。这类质疑在他身上高频出现，处理流程要固定下来。

---

## 标准流程（不要跳步）

1. **联网查权威定义**（不要凭记忆答"差不多"）。优先级：
   央行/监管原文（Fed FEDS Notes、CFTC、BIS）> 同行评议论文 > 交易所规则手册 > 券商研报
2. **把定义和现有实现逐项对照**，列成表
3. **名不副实就改名 + 写清口径差异**，绝不含糊过去
4. 拿不到真口径时，**实测边界后如实说"没有"**，并给最接近的替代

★ 千万不要因为"指标本身算得没错"就认为不用改 —— **名字错了就是误导**。

## 本次案例：Basis Trade Carry

**权威定义**（Fed FEDS Notes 2024-03-08）：

> the position consists of a **repo-financed purchase of a Treasury security and the
> simultaneous sale of a corresponding Treasury futures contract** … profit is based on the
> difference in the prices paid and received for the cash and futures legs, net of carry
> and financing costs.

ScienceDirect《Hedge funds and the Treasury cash-futures basis trade》给的可操作判据：

> the basis is defined as **the difference between the implied repo rate and the available
> market repo rate**.

正确公式：
```
IRR = [(发票价格 − 债券脏价) / 债券脏价] × (年天数 / 距交割天数)
      发票价格 = 期货价 × 转换因子 + 交割日应计利息
Net basis ≈ IRR − 实际回购利率(SOFR / term repo)
```

**原实现算的是 `国债收益率 − SOFR`** —— 文献里叫 carry / cash-repo spread：

| | 原图（单腿） | 真正的 basis trade（双腿） |
|---|---|---|
| 腿数 | 只有现券 | 现券多 + 期货空 |
| 衡量 | 持券吃息差 | 期现价差收敛 |
| 风险 | **有久期风险**（利率涨就亏） | 久期被对冲掉，主要是融资+保证金风险 |
| 数据 | DGS10 − SOFR ✅ 免费可得 | 需 CTD 券 + 期货价 + 转换因子 ❌ |

## 三个选项的给法（Chao 选了 A）

给选项时**把成本和数据可得性讲清楚**，让他能判断：

- **A｜改名不改数**（零成本、立刻诚实）：标题「② 套利 Carry 空间 / Basis Trade Carry」
  → 「② **持券 Carry** / Cash Carry」，副标题加「注: 非期现 basis trade」
- **B｜补真 basis**：需 CME 期货结算价 + 转换因子 + CTD 判定；CME 反爬（本项目被封过），
  且转换因子需逐合约维护 → 工作量大、数据源不稳
- **C｜折中**：保留现图改名，另加 SOFR–IORB 利差 + SRF 用量作为融资压力代理
  （FRED 免费，文献里判断 basis trade 去杠杆风险的常用前瞻指标）

## 改名之后：图注要把口径差异写清

不是改个标题就完事。图注要说明：
- 这个数**是什么**（回购融资买入并持有现券的净收益 bp）
- **不是什么**（没有期货腿，不是套利，有久期风险）
- **为什么不做真的**（需 CTD 券与期货价，免费源不可得）
- 权威出处（Fed FEDS Notes / 达拉斯联储）

## ⚠️ patch 中文长文本时的转义坑

改这段图注时 `patch` 把 `\"` 变成了 `\\\\\\"`（六重反斜杠），会渲染出字面反斜杠。
中文说明里嵌 HTML 属性引号时**改完必须验一次**：

```python
s = open('src/dashboard.py', encoding='utf-8').read()
for m in re.finditer(r'跌破 0\(<span style=.{0,20}color:#d64545', s):
    print(repr(s[m.start():m.start()+60]))     # 看反斜杠层数是否与同文件其它块一致
```
修法：读出来 `str.replace` 回正确层数，再 `compile()` 验语法。

## 数据拿不到时的诚实做法

同一轮 Chao 要「各个级别的债券总量」。实测结论：

- 免费源**没有分评级（AAA…CCC 七档）未偿总额** —— 属 ICE/Bloomberg 商业授权
- **实测过 SIFMA**：`US-Fixed-Income-Securities-Statistics-SIFMA.xlsx` 的 Outstanding /
  Issuance 两表里 Corporates **只有单一合计**（1Q26 ≈ $11.74T），不分 IG/HY
- FRED 上带 `TRIV` 的分评级序列是**总回报指数不是余额**，拿来冒充会错一个量级

→ 把能拿到的三个口径都放上（Fed Z.1 非金融企业债务证券 $8.98T / 另一档 $14.45T /
SIFMA 全市场 $11.74T），**并在页面上写明"全市场口径·非分评级"和为什么拿不到**。

★ 顺带发现：Fed Z.1 未偿额其实**早就在渲染，只是排在页面最底部**，
Chao 截图看不到 → 先确认"是没做还是没看见"，再决定动手。
