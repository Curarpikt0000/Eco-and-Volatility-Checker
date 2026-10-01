# 新增图表时的三类反复坑：导航跳动 / tooltip 规范 / 指标语义

补充 `add-new-dashboard-section.md`（那份讲「怎么把一个数据源接进来」），
本份讲「接进来之后，图本身怎么才不出错」。三类问题独立，但常在同一次改动里一起爆。
全部来自 Eco-and-Volatility-Checker 2026-08-25 中国流动性板块改造实战。

---

## 0. 硬门：建图前必须先读 wiki 规范

**新增任何图表前，先读 `~/Projects/ChaoWiki/knowledge/frontend/data-dashboard-publishing.md`。**

实际教训：新做的 4 张图 hover 全无 tooltip，Chao 直接问
「你是不是把我跟你说的东西忘了？你在建图之前，一定要先阅读我们建图的那个 Wiki」。
规范 §3「全图 hover tooltip」**早就存在** —— 不是规范缺失，是没读就动手。

Chao 会**逐图 hover 检查**。漏了就是返工。

---

## 1. 左侧目录 / 滚动高亮「跳动」

### 头号根因：新图的小标题复用了 section 的 class

用户报「左边目录和右边 chart 又开始跳动了」时，**先数导航选择器抓到几个元素**，
别急着调 `rootMargin` / 触发线。

实测：`querySelectorAll('.part-title')` 抓到 **52** 个，真正的顶级 section 只有 **46** 个 ——
多出的 6 个是**新图内部的小标题**（渲染函数里生成的「① 公开市场逆回购」「④ SFISF 互换便利」等，
顺手复用了 `.part-title`）。

坏在哪：图内小标题不匹配 GROUPS 里任何关键词 → 全掉进「其他」分组，
而「其他」按「首个成员的 DOM 位置」排序会插在**页面中部** →
向下滚动时高亮在「其他」和真实分组之间来回窜。

**修法不是改排序算法，是让导航只认顶级标题：**

```javascript
// 顶级 section 模板里都带 <span class="part-num">＋</span>，图内小标题没有
var titles = Array.prototype.slice.call(document.querySelectorAll('.part-title'))
                  .filter(function(t) { return t.querySelector('.part-num'); });
```

自检（先量再改）：
```bash
grep -c 'class="part-title"' dashboard/index.html                        # 52 全部
grep -c 'class="part-title"[^>]*>\s*<span class="part-num"' index.html   # 46 顶级
# 两数不等 => 导航正在收编图内小标题，必然跳动
```

**推广到本项目的一条纪律**：新增 section 内部若要分小标题，
要么另起一个 class，要么确保它没有 `.part-num`。

### 配套隐患：`t.id = 'sec-' + i` 冲掉语义 id

```javascript
var id = 'sec-' + i;           // ✗ 无条件覆盖
var id = t.id || ('sec-' + i); // ✓ 已有语义 id 就保留
t.id = id;
```

模板里手写的 `id="sec-cn-liq"`（`add-new-dashboard-section.md` §4 要求写的那个）
会被冲成 `sec-19` —— 页面看着正常，但**外链锚点/书签全部失效，且不报错**。

### 「其他」分组必须为空

`add-new-dashboard-section.md` §5 要求给 GROUPS 加关键词。补一条验收：
改完跑分组模拟，**「其他」计数必须是 0**。非 0 = 还有 section 没被收编。

本次实测把三项从「其他」归位：
中国央行流动性 + 央行货币互换 → 流动性与央行；KOL 全量名录 → KOL 观点。

---

## 2. tooltip：`data-tip` 不是 `<title>`

### 反模式

```python
# ❌ 能"显示"但体验完全不同 —— 浏览器要悬停 1-2 秒才弹系统级小黄框，
#    样式不受控、与全站其他图不一致，用户直接判定「没有 tooltip」
p.append(f'<rect ...><title>{_esc(tip)}</title></rect>')

# ✅ 走全站 data-tip 事件委托（#chart-tip 浮层），即时响应、样式统一
p.append(f'<rect ... data-tip="{_esc(tip)}"/>')
p.append(f'<circle class="tip-hit" cx=".." cy=".." r="7" fill="transparent" data-tip="{_esc(tip)}"/>')
```

折线整条 polyline 无法逐点 hover → **每个数据点叠一个透明 `circle.tip-hit`**。
（这与 `dashboard-proxy-metrics-and-sidebar-nav.md` 里记的全图 tooltip 机制是同一套，
新图必须接上，不能自己造。）

### 自检命令（新图写完必跑）

```bash
grep -c 'data-tip' dashboard/index.html   # 应 ≈ 数据点总数
grep -c '<title>'  dashboard/index.html   # 应为 1（只剩页面 <title>）
```

**修一处不够** —— 本次自检发现不止新图：CIPS(35 处) 与 AI-FCF(34 处) 也在用 `<title>`。
加了自检命令就顺手全站扫一遍，从 70 降到 1。

### tooltip 要带「派生量」

只显示图上画的那个数不够。若该指标有**必须合看才不误判**的配套量，一并塞进 tooltip：
MLF 柱状图画投放量，tooltip 要带 `到期 X｜净投放 +Y`（理由见 §3b）。
同理：库存图带环比、利率图带利差、持仓图带周变动。

---

## 3. 指标语义：三个会产出「语法正确但结论相反」的陷阱

### 3a. 流量 vs 存量，变动口径不可混用

判别口诀：**「这个数能不能在某一天『没有』？」**

| 类型 | 本项目例子 | 变动算法 |
|---|---|---|
| 流量 | 逆回购投放、MLF 操作量 | **区间求和**对比 |
| 存量/价格 | 两融余额、DR007、ETF 份额 | **点位差**对比 |

对流量用点位法会产出「逆回购较上周 −100%」这种假信号 —— 实际只是当天恰好没操作。

另两条：回溯用**自然日**而非"往前数 N 个点"（节假日会让"过去一周"跨十几天）；
无可比基准返 `None` 不凑数；变动引擎写完**必须与手算对账**。

### 3b. 只画「投放/流入」不画「到期/流出」= 方向可能相反

净额才是真实影响。到期量往往**不需要外部数据源，能从已有序列精确推算**：
MLF 全为 1 年期（实测 20/20 条 tenor 一致）→ 本月到期 ≡ 12 个月前的操作量。

```
2026-08   投放 5,000亿   到期 6,000亿  →  实为净回笼 1,000亿
```
只看柱高会得出「央行在放水」的**反向结论**。

先验证期限一致性再推算；不一致就不能这么算。前 12 个月无基准 → 显式留 `None`，
不外推、不用 0 冒充。

### 3c. ETF 只能看「份额」，不能看规模或价格

- **价格**涨跌 = 市场情绪，不代表有钱进来。
- **规模**（净值×份额）被价格污染 —— 指数涨 10%、份额没动，规模也涨 10%，
  看着像"资金流入"其实一分钱没进。
- **份额**增加 = 有人**申购**（真金进场），减少 = **赎回**。

三只宽基量级差 5 倍（300ETF 238 亿份 vs 500ETF 49 亿份），同图对比要
**归一化到「首日=100」**，否则小的那条压成直线。加一条 100 基准虚线标注「上方=净申购」。

数据源：`akshare.fund_etf_scale_sse(date=YYYYMMDD)` = **上交所官方**每日 ETF 规模表，
含「基金份额」列，一次返回全市场 800+ 只。一手源，非第三方推算。

### 3d. 代理指标必须在图上写明「不等于原指标」

原指标披露频率不满足需求时改用日频代理（两融 / ETF 份额），
**标题与说明必须写清是代理**，否则下一个读图的人当成原指标本身。

---

## 4. 数据缺口会画出「假崩盘」—— 渲染前必须截断

回填未跑完时时序会「两端有、中间空」。相邻两点跨越数月缺口，折线画出来就是一根悬崖 ——
本次实测沪深300ETF 显示 **−71.97%**，若直接发布，读图人必然得出"国家队大撤退"的结论。
**实际日内波动只有 ±2%。**

这类假象比缺数据危险得多（缺数据是空白，假象是错误结论）。

**护栏：相邻两点间隔 > 20 天判为缺口，从缺口处截断只保留最近连续段**，
回报 `gap_trimmed` 供上层标注。宁可少画一段，也不画出假崩盘。

```python
for code, s in list(series.items()):
    cut = 0
    for i in range(len(s) - 1, 0, -1):
        d1 = datetime.date.fromisoformat(s[i]["date"])
        d0 = datetime.date.fromisoformat(s[i - 1]["date"])
        if (d1 - d0).days > 20:
            cut = i
            break
    if cut:
        series[code] = s[cut:]
```
实测：裁掉 150 个跨缺口点，最大单步从 −71.97% 降到 5.13%。

**诊断顺序**：看到巨幅跳变，先查两点的**日期间隔**，再查数据源。
本次抽查缺口中间的日期，数据源完全正常（897→445→279→244 渐进下降），
证明是采集进度问题而非数据问题。

---

## 5. 裸 `except Exception` 会把代码 bug 伪装成「数据问题」

本项目 fetch 函数普遍有降级兜底（`add-new-dashboard-section.md` §1 的 cache-fallback 契约），
但 except 范围要收窄：

```python
except Exception as e:                 # ✗ 把 NameError 吞成"读取失败"，看板照常渲染，bug 永不浮现
except (OSError, ValueError) as e:     # ✓ 只吞「文件读不到 / JSON 坏了」这两类数据问题
    return {"status": f"读取失败: {type(e).__name__}", "series": {}}
```

本次实际后果：自己写的 `NameError`（模块级没导入 `json`）被吞成 `"读取失败: NameError"`。

配套：`external_data.py` 里 `json` 只在几个函数**内部** import，模块级没有 ——
新增的模块级函数用 `json.load` 会 `NameError`。
写新函数前 `grep -n "^import\|^from" src/external_data.py` 确认模块级有什么。

---

## 6. 表格行内嵌 HTML 时不能整体 `_esc()`

变动表要给「净投放/净回笼」染色、给字段名加 `<b>`，沿用 `f'<td>{_esc(name)}</td>'`
会把标签转义成字面量。

改为不 `_esc` 时**必须确认内容全是本函数自造的常量或数字格式化结果，无外部输入**，
并在代码注释里写明。混入外部数据的列仍要 `_esc`。

---

## 7. 采集器：非交易日不是抓取失败

`akshare.fund_etf_scale_sse(date=...)` 在非交易日返回空表，
akshare 重命名列时抛 `KeyError: None of [Index([...])]` —— 看着像接口坏了。

必须捕获跳过，**不记为失败**。实测 14 天窗口命中 13、跳过 1，那 1 个正是非交易日。

采集器要点：逐日循环（无区间接口）+ 限速；周末直接跳过省请求；
已有日期不重取（天然支持增量日更）；每 N 条落盘一次，长回填中断不丢进度。

---

## 8. CFETS DR007 两年历史：必须 POST + 起止同月

DR007 官方图表 CSV（`fdr-chrt.csv`）只回溯 **3 个月**，撑不起两年曲线。
从 akshare 源码 `akshare/rate/repo_rate.py` 挖到 CFETS 真实调用方式：

- **必须 POST**（GET 返回 200 但 `records` 为空 —— 极易误判成"没有历史数据"）
- **起止日期必须在同一个月内**（跨月返回空）
- 逐月循环 26 次 → 536 个交易日（2024-07 ~ 2026-08）

推广：**某接口"只有近 N 天数据"时，先去 akshare 源码里看它怎么调的**，
`.venv/lib/python3.11/site-packages/akshare/` 下按数据类型分目录，
常能挖到官方未文档化的真实参数。
