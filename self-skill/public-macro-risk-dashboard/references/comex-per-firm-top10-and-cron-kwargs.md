# COMEX per-firm 交割明细 → top10 榜单 section

Realized 2026-08-22 on `~/Projects/Eco-and-Volatility-Checker` + `~/Projects/Comex-Daily-Report`.
Chao 的需求：「金/银/铂 各列 top10 交割方 + top10 接货方，日/周/月三个维度」。

---

## 0. 先查源头有没有 per-firm，别急着重新抓

现有 `comex_issue_stop_weekly.json` 只有 `all_net`/`core_net` 汇总，看起来像"没有 per-firm"。
但生成它的 `build_issue_stop_weekly.py` 里 `collect_archive()` / `collect_notion()`
**本来就是 per-firm 解析的**，只是 `aggregate()` 把 firm 维度加总扔了。

→ **教训：数据"没有"之前，先读生成脚本，看是不是聚合时丢的。** 本次因此省掉了全部重抓。

## 1. 两个数据集并存，不要改旧的

| 文件 | 口径 | 用途 |
|---|---|---|
| `comex_issue_stop_weekly.json` | 只 Gold/Silver、只大行(CODE_MAP)、周聚合净值 | 原有净值曲线图 |
| `comex_issue_stop_firms.json` **(新)** | 三金属含 Pt、**全部机构**含非银、日粒度 per-firm | top10 榜单 |

新建 `build_issue_stop_firms.py`，**不动 weekly 版**——改它会破坏已上线的图。

## 2. ⚠️ 铂金：parser 支持，但抽样会骗你

`cme_delivery_parser.METAL_MAP` 里本就有 `PLATINUM`。第一次实测 `2026-06-05` 的 PDF 只返回
Gold/Silver，差点得出"Pt 无数据"的错误结论 —— 实际是**那天没有铂金交割**。

正确做法：扫全部 PDF 统计 CONTRACT 类型，而不是抽一份看。
```python
contracts = Counter(re.findall(r'CONTRACT:\s*(.+)', txt))   # 跑遍 133 份
# 结果: PLATINUM FUTURES NYMEX 出现在 78/133 天
```
铂金最终 62 天有数据、22 家机构。**交割稀疏 ≠ 没有数据。**

## 3. 双通道拼接的对齐陷阱

archive PDF 到 `2026-06-05` 为止，之后靠 Notion「Daily auto tracking」DB 的
`Activity Note` 增量（`[Delivery] Silver: Advantage发1, Marex发10 / Wells接3...`）。

★ **两个通道的机构名必须归一到同一套展示名**，否则同一家会裂成两个名字、top10 排名失真：
- archive: `WELLS FARGO SECURITI`（PDF 截断到 20 字符）→ `DISPLAY` 映射
- Notion: `Wells` → `NOTION_ALIAS` 映射
- 两张表的**产物**必须一致（都产出 `Wells Fargo`）

未知简称一律 `stats["unmapped"]` 记录并**跳过不猜**，跑完打印 ⚠ 提示人工补。

## 4. 自洽校验是免费的，必须做

CME PDF 每个合约段有 `TOTAL: 863 863`，且交割天然守恒（每手必有一发一接）：
```python
if ti is not None and (si != ti or ss != ts):
    mismatches.append({...})      # 席位加总 vs PDF TOTAL
```
本次结果：**133/133 解析成功，0 失败，0 总量不符**；三金属全期 `total_i == total_s`。
这个数字可以直接写进 dashboard 的「数据诚实说明」，比任何形容词都有说服力。

## 5. 排名口径：总量，不是净额

Chao 拍板按**总量**排。理由：净额会让"大进大出"的做市商掉榜，
而「top10 交货方」的直觉就是"发货最多的十家"。
同一家可同时上两个榜（既发又接是正常做市行为），在「如何看」里说明。

## 6. 读数时要标注的两个真相

- **CME 占黄金近一月发货 38.6%** —— 它是清算所自身席位，**不是市场参与者**，必须在图注点破，
  否则读者会当成"某大行在疯狂交货"。
- **非银机构**（StoneX / Marex / Advantage）行为逻辑与 bullion bank 不同，
  加 `is_bank` 字段 + `非银` 徽章分开读。

## 7. ★★ cron 内联 generate 漏传参数（本次挖出的真 bug）

Eco 的每日 cron 步骤 6 用 `python -c "...dashboard.generate(...)"` 手抄 kwargs，
而 `dashboard.generate` 有 46 个可选参数 —— cron 只传了 28 个，**漏 18 个**：
`comex_issue_stop / comex_inventory / gold_exports / us_yield_century /
silver_bank_positions / ad_line_real / gold_premium / silver_imports / fiscal_budget /
basis_trade / debt_gdp / corp_credit / cips / ai_fcf / ai_credit /
comex_silver_issues_ref / kol_history` + 新加的 `comex_firms_top10`。

后果：**cron 每天产出的 dashboard 比手动 `python -m src.build_dashboard` 少 18 个板块**，
而且是静默的（模板占位符拿到 None → 渲染成"未就绪"）。

- **为什么不能直接改用 `build_dashboard.py`**：它不读 `data/ai_analysis_<date>.json`，
  切过去会丢每日 AI 短评（AGENTS.md 里早有这条警告，属实）。
- **正解**：补齐内联 kwargs 到 46/46，并在 cron prompt 里写死自检命令：
  ```bash
  python3 -c "import re;src=open('src/dashboard.py').read();m=re.search(r'def generate\((.*?)\):',src,re.S);print(sorted(set(re.findall(r'(\w+)=None',m.group(1)))))"
  ```
- ★**写 cron 内联代码前必须真机验证每个函数名存在**。我第一版猜错 4 个
  （`fetch_silver_imports` 实为 `fetch_silver_imports_data`、`fetch_basis_trade` 实为
  `fetch_basis_trade_monitor(years=2)`、`fetch_debt_gdp` 实为 `fetch_debt_to_gdp`、
  `fetch_corp_credit` 实为 `fetch_corporate_credit`），不验证的话 cron 次日直接崩：
  ```python
  bad = [n for n in names if not hasattr(e, n)]     # 先 hasattr
  for n in names: getattr(e, n)()                    # 再真机调一遍看 status
  ```

## 8. 前端 filter 的最省事实现

数据量不大时（本例 32 周 / 132 天），**把所有窗口一次性渲染成多个 pane，
点 tab 只切 `display`**，不做前端重算、不重新请求：
```python
_act = " tf-on" if k == "m" else ""        # 默认窗口
panes.append(f'<div class="tf-pane{_act}" data-tf="{slug}" data-k="{k}">...')
```
JS 用 `data-*` 双键定位（`data-tf` 金属 + `data-k` 窗口），
这样三个金属各自独立切换、互不影响。

验收要数柱子/行数，不能只看"有没有渲染"：
```
1周=2根 / 4周=8根 / 13周=26根 / 32周=64根   （每窗口两张图）
源JSON 榜单行 147 == HTML tf-row 147
```

## 9. build 与改代码的竞态

dashboard 重建约 5 分钟。**在 build 跑着的时候改 `dashboard.py`，改动不会进这次产物**。
本次踩到：第一次 build 启动后才加的 filter，验收时 `cis-tab 按钮数: 0`。
→ 改完代码要重新 build，或者改完再启动。
