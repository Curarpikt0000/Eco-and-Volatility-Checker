# 基差套利解杠杆诊断（Chao 问「美债收益突升会不会造成基差套利基金解杠杆」类问题）

## 回答框架（先纠正因果，再给三闸数据）
收益率上行本身**不直接**逼平：现券多头亏、期货空头赚，大体对冲。真正的平仓触发是三件事同时出现：
1. **保证金上调**：MOVE 飙升后 CME 提高期货保证金。警戒线约 MOVE>120（2023-10 高点 141）。
2. **融资变贵或被抽贷**：SOFR 冲破 IORB，或回购抵押折扣上调。
3. **基差走阔**：现券相对期货被抛售（2020-03 型）。
另看 carry（收益率−SOFR）：carry 变厚＝没有主动撤的理由。

## 项目内现成数据
- `data/basis_trade_monitor.json`：panels.funding（SOFR/IORB/EFFR/ON RRP/TONAR）、carry（2Y/5Y/10Y/30Y−SOFR，JGB−TONAR）、MOVE+Fed 准备金；`lights`（sofr_iorb_gap_bp / funding / carry / vol）。
- `data/stress/treasury_stress_panels.json`：10Y/2Y、MOVE、期限溢价、10Y−2Y、IG/HY OAS。
- 每序列取 last / -5 / -22 点对比 + max/min 看离极值多远。
- ★走廊整体平移（如 IORB 3.65→3.90）时「SOFR 升」可能只是政策利率上调，看 SOFR−IORB 差，不看绝对值。

## 杠杆基金美债期货空头（CFTC TFF）
```
https://publicreporting.cftc.gov/resource/gpe5-46if.json?$select=report_date_as_yyyy_mm_dd,market_and_exchange_names,lev_money_positions_long,lev_money_positions_short&$where=report_date_as_yyyy_mm_dd>'YYYY-MM-DD'&$order=report_date_as_yyyy_mm_dd&$limit=5000
```
- 市场名取 ` - ` 前：`UST 2Y NOTE` / `UST 5Y NOTE` / `UST 10Y NOTE` / `ULTRA UST 10Y` / `UST BOND` / `ULTRA UST BOND`。
- ★别用 `like '%TREASURY%'` 过滤——名字里没有 TREASURY，返回空（假阴性）。先拉全量再在 Python 里过滤。
- 净空头＝short−long。2026-09 实测：07-07 757 万张 → 09-22 652 万张（−14%）。
- 诚实边界（回答必写）：①混有方向性做空；②按张数相加未做 DV01 折算；③截至周二、周五发，最近大涨可能未进数据。
- 已提议做成基差板块第 ④ 图，待 Chao 批。
