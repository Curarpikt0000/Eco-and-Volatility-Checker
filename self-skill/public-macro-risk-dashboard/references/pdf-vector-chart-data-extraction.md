# 从 PDF 矢量图里抠出真实数据点（WGC Weekly Markets Monitor 实战）

适用：权威机构把数据画成图印在公开 PDF 里，但不发原始数列。
2026-09-21 在 WGC「Weekly Markets Monitor」上跑通，一次拿到 36 个数据点。

## 为什么值得做

WGC 周报第 23 页同时有两张图：
- `ETF options: ATM IV term structure`（GLD / IAU / IGLN / SGOL US&LN Equity）
- `Futures: ATM IV term structure`（GC1 / AUA1 COMDTY）

**第二张是 COMEX 期货 ATM IV —— 直连 CME 八条路径全封的那个数据**。
WGC 从 Bloomberg 买来印进公开 PDF，等于免费开了一扇窗（周频）。
源标注：`Source: Bloomberg, World Gold Council`。

## 定位周报

```
https://www.gold.org/goldhub/gold-focus         → 列出各期
.../gold-focus/2026/09/weekly-markets-monitor-<slug>
PDF: /download/file/<id>/WMM_<DD>_<Month>_<YYYY>_<slug>.pdf
```
注意存在 `weekly-markets-monitor-no-release` 这种停发期 —— **不能假设每周都有**，
自己那条自算数据线要保留作为兜底。

## 提取配方（pymupdf）

1. `pg.get_text("dict")` 收集 span：两位数 = y 轴刻度，`1M/3M/6M/12M/18M/24M` = x 刻度。
2. 按 span 的 x 聚类把左右两张图分开（本例左 60–480、右 490–900）。
3. 用首尾两个 y 刻度做线性标定 `y → 数值`。
4. `pg.get_drawings()` 取折线：
   - 过滤灰网格：`max(color)-min(color) < 0.02 and color[0] > 0.7`
   - 每条路径收集 `it[0]=="l"` 的端点，落在图区 bbox 内的才要
   - 按颜色分组 = 按图例系列分组
5. 把点按 x 吸附到最近刻度，`y2v()` 反推数值。

## ★★两个必踩的坑

**坑 1：文字 bbox 的 x 是左边缘，数据点在文字中心。**
`"1M"` 宽约 13pt，中心比左边缘大 ≈6.6。我第一版用左边缘 + 容差 6 → 真数据点全被滤掉，
两组返回空，差点误判「图里没数据」。**一律用 `(x0+x1)/2` 中心，y 同理。**

**坑 2：分支早退吃掉整张图。**
右图成功、左图空时，第一反应不该是「左图没数据」，而是**先打印左图区域实际收到了什么**。
实测左图标签 7 个 y + 6 个 x 全齐 → 证明是循环逻辑 bug，不是数据问题。

## 入库前的硬校验（不通过不准用）

- 每条线点数 == 期限数（6）
- 全部反推值落在该图 y 轴范围内（±1.5 容差）
- 线条数 == 图例条目数（左图 4、右图 2）；对不上说明漏线或把网格当了数据
- 与自算源做量级比对：本例 WGC GLD 1M 20.53 vs 自算 CBOE 21.43（差 0.9，日期差 3 天、
  源不同 Bloomberg vs CBOE）→ **吻合，反向证明自算算法是对的**。这正是做交叉验证的价值。

## 仍待解决（别当已完成）

- **ticker↔颜色的对应是猜的**：图例文字和线条颜色要真正配对才能确定，
  「黑色通常是第一个」不是判据。
- 有几条线出现「12M 之后全平」，可能是真平，也可能是坐标吸附把多点归到同一 y —— 要验。
