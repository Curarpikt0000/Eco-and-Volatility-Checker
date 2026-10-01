# 时间窗口聚合口径 + fetcher 缓存安全

来源：2026-08-31 给 Eco dashboard 的两个 KOL 板块加「本日/本周/本月」三档 filter 时踩出来的。
三件事：①探测 fetcher 会毁数据 ②端点对比在长窗口下系统性失真 ③浏览器不可用时如何真验 JS。

---

## 1. ★最严重：探测 fetcher 会覆盖它自己的磁盘缓存

**事故**：为了摸清返回结构，我直接调了 `ed.fetch_foreign_flow_japan()`。
上游抓取失败 → 该 fetcher 把 `data/foreign_flow_japan.json`
**覆写成 `{"status":"未获取"}`**，53 周真实 JPX 数据被抹掉。靠 `git checkout` 才救回。

这是本项目 AGENTS.md 已记载的「空值覆盖真值」陷阱的**另一个变体**：
- 已记载的：`notion_writer.upsert` PATCH 全量 props，抓不到 → 把 Notion 已有真值清空
- 本次新增：**`fetch_*()` 自身会写盘**，抓失败 → 把本地缓存降级成 status 占位

### 规则

- **写抽取器 / 探测结构时，只读缓存文件，绝不调 `fetch_*()`。**
  ```python
  # ✅ 只读缓存，零网络、零副作用
  p = os.path.join(ROOT, "data", "foreign_flow_japan.json")
  d = json.load(open(p, encoding="utf-8"))
  if (d.get("status") or "") != "ok":
      return []          # 诚实返回空，不猜不补
  ```
- 想知道字段结构 → `json.load` 缓存文件后 `print(list(d))`，**不要**为了看结构去调 fetcher。
- 每个只读抽取器都在 docstring 里写死这条，防止后人「顺手改成调 fetcher 更新鲜」。

### 提交前的回退扫描（每次都跑）

改动碰到 `data/*.json` 时，提交前逐个比对 HEAD，任何 `status` 由 ok 变差、
或 `points` 由非空归零，都要停下来查清楚再决定：

```python
for f in changed_json_files:
    new = json.load(open(f))
    old = json.loads(subprocess.run(['git','show','HEAD:'+f],
                                    capture_output=True, text=True).stdout)
    if (old.get('status')=='ok' and new.get('status')!='ok') or \
       (len(old.get('points') or []) > 0 and len(new.get('points') or []) == 0):
        print('WARN 真值回退:', f)
```

**判据**：`as_of` 前进 + `status:ok` + points 数不减 = 真实刷新，可提交；
反之即为覆盖事故。实测区分过一次：08-14→08-21 是真更新，与被写成「未获取」完全不同。

---

## 2. 端点对比 vs 累计口径 —— 长窗口下端点对比会系统性失真

**现象**：给「KOL 状态变化」加月档后，本月转向 **2 人**，而本周（同样口径）**75 人**。

**根因**：端点对比 = 窗口内最新快照 vs 窗口起点前最后快照。
月窗口比 8-31 vs 7-31，**月初看多→月中转空→月末又转多的人首尾相同，被判为「没变」**。
这不是「更平滑」，是**给出「本月共识几乎没变」的错误结论**——对交易员是有害信号。

### 口径选择规则

| 窗口 | 口径 | 理由 |
|---|---|---|
| 日 / 周 | 端点对比 | 窗口短，中途摆动少，首尾差就是真变化 |
| 月及以上 | **累计 / 稳定度** | 端点会抵消中途摆动 |

### 月档改用「立场稳定度」三级分类

不做首尾对比，改为统计每人整月出现过的**阵营集合**（多/空/中三粗档）：

| 级别 | 判据 | 实测(2026-08) |
|---|---|---|
| `flip` 跨多空反转 | camps 同时含「多」与「空」 | 40 人 |
| `soft` 仅强度摆动 | 只在 多↔中 或 空↔中 之间 | 32 人 |
| `stable` 全月稳定 | 整月只落一个阵营 | 54 人 |

合计 126 = 40+32+54，与 total 自洽。

**★为什么必须分三级而不是两级**：只分「稳定/反复」会把
`Michael Saylor`（路径 `强烈看多→强烈看多→看多→看多→看多`，全程多头，
只因掺了个中性档）打成「立场反复」——对交易员就是假信号。
细档漂移（强烈看多↔看多）**不是换边**。

### ★不要声称数据撑不住的精度

一度想输出「月内第 N 次转向」，实测发现快照 `direction` 标注质量不够：

```
08-22 看多  17年来最防御：25%黄金不算过分…      ┐ 逐字相同的文本
08-24 看多  17年来最防御：25%黄金不算过分…      ┘
08-27 看空  AI芯片当长债抵押=见顶信号，持现金/黄金
08-28 看多  债王：2026不会降息，应囤现金、黄金与实物资产   ← 同一件事，方向标反
08-31 看空  避开长债，押2026加息，AI芯片抵押是顶部信号
```

细档切换 383 次，按三阵营归并后仍 252 次，**归并解决不了根本问题**。
逐次展示 = 把标注噪音当市场信号。故只输出「是否稳定」这一数据撑得住的结论。

### 日档的噪音率也要实测后再定默认

- 日频转向 **3 天内回摆（伪信号）= 53/188 ≈ 28%**
- 更隐蔽：**抓取覆盖率波动会伪装成转向**。08-19 覆盖率 46%（99人名册仅46人有效方向），
  08-20 回到 91% —— 中间「多出来」的 44 人在日频视角下全像新转向。
  日均转向 23.9，但单日 1~73，73 那天不是市场疯了，是覆盖率从 87% 跳到 98%。
- **结论：默认停在「本周」**。本日只在 FOMC/CPI/非农或价格暴动当天用（那种日子的转向是真的，有共同外生冲击）。

### 口径差异必须写在页面上

三档并列时最大风险是**混读**。月档头部直接写明：
> 日/周看「首尾对比的转向」，本月看「整月待过几个阵营」；
> 月内多空来回者在首尾对比下会被抵消成「没变」，故本档改判稳定性。
> 「跨多空反转」才是真换边；「强度摆动」只是档位漂移，未离开原阵营；
> 因标注精度不足，不声称具体转向次数。

---

## 3. 多档 filter 的实现模式（服务端预算 + 纯前端切换）

**不要**让前端发请求或重算。三份数据一次算好全部内嵌，点击只切 `display`：

```python
# 数据层：统一窗口换算，默认值必须与历史口径逐字段一致
def _kol_period_window(period="week"):
    today = date.today(); this_monday = today - timedelta(days=today.weekday())
    if period == "day":     start = new_base = today
    elif period == "month": start = new_base = today.replace(day=1)
    else:                   start, new_base = this_monday - timedelta(days=7), this_monday
    return start.isoformat(), today.isoformat(), new_base.isoformat()

# 调用方一次算三档
kol_views = {p: (ed.kol_weekly_views(period=p) or {}) for p in ("day","week","month")}
```

渲染成 `按钮组 + 三个 pane`，用 `data-kp-group` / `data-kp-pane` 配对，
事件委托一个 handler 搞定所有组（互不干扰）。

**两条硬要求**：
1. **默认参数不改变现有行为** —— 不传 `period` 必须与传 `week` 逐字段一致，
   现有 cron/调用方零改动。改完立刻断言验证。
2. **向后兼容退化** —— 渲染函数收到旧式单份数据（非三档字典）时，
   自动只渲一份、不显示按钮，不能崩。

---

## 4. 浏览器不可用时，如何真验生成 HTML 的 JS 交互

本次 browser harness 故障（`inspect.signature` AttributeError）。
**静态字符串检查（`'kp-btn' in html`）证明不了点击真的会切换**，不能拿它当验证。

可行替代：**从产物 HTML 正则抽出真实 DOM 属性 → 喂给与注入代码逐字相同的 handler → 在 node 里跑**。

```js
// 从真实产物抽属性，不是手写假数据
const btnRaw  = attrsOf(/<button type="button" class="(kp-btn(?: on)?)" data-kp-group="([^"]+)" data-kp="([^"]+)"/g);
const paneRaw = attrsOf(/<div class="kp-pane" data-kp-group="([^"]+)" data-kp-pane="([^"]+)"( style="display:none")?>/g);
// 手写最小 DOM 桩（classList / getAttribute / closest / querySelectorAll）
// 再原样粘贴 dashboard.py 注入的那段 handler，逐条 assert
```

覆盖：初始态 → 三档来回切 → **两个 group 互不干扰**。本次 9 项全过。

**诚实边界**：这比静态检查强得多，但**不等于真人点击**，汇报时要如实说明用的是哪种验证。
脚本留在 `scratch/`（已 gitignore），改 JS 后可随时重跑。

---

## 5. 批量改文案时，把校验写成硬门禁

给 20 个指标统一改写说明（四段式：【是什么】人话定义+数据源 →【怎么看】方向与传导 →
【怎么用】阈值+组合用法 →【注意】口径坑）时，最大风险是**把阈值写错**。

三道自动校验，缺一不可：
1. `git diff` 改动行**全部只含 `"note"`**，非 note 改动数必须为 0
2. 与备份逐一对比 `key/warn/trigger/source/direction/status_labels`，差异必须为 0
3. **note 文案里的阈值数字 vs `warn`/`trigger` 实参交叉核对** —— 17 个有阈值的指标全部对上才算过

第 3 条是关键：靠人眼看「文案有没有写错阈值」必然漏，写成脚本断言才可靠。

### 指标说明的写法要点（Chao 认可的口径）

- **方向陷阱显式标注**：`put_call`/`bofa_fms_cash`/`insider`/`lei` 是**越低越危险**；
  `vix` 对顶部预警而言危险的是**太低**；`yield_curve` 由倒挂**转正**才是衰退临近。
- **易混淆卡说清区别**：`aaii_bull_bear` 问「怎么想」，`aaii_alloc` 问「实际怎么放钱」。
- **给历史参照系**：CAPE 1929=33/2000=44/2009=13；巴菲特指标 2000=140-150%；
  HY OAS 2008 破 20%；SOFR-IORB 2019-09 回购危机；AAII 仓位 2000-03 约 77%。
- **标注不能用来做什么**：`cape` 可高位停留数年、拿它择时会持续踏空；`ad_line` 是预警非择时。
- **诚实边界进说明**：无固定免费源的（`bofa_bull_bear`/`ad_line`）写明靠 web_search 交叉验证，
  搜不到留空标「未找到」，绝不沿用旧值也不估算。
- **术语首次出现给白话解释**：如 CP = Commercial Paper 商业票据，银行发的短期无担保借条。
- **技术债降级到脚注**：「为什么用代理指标」属实现细节，别占【是什么】的位置。
