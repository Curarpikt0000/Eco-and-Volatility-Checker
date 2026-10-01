# 指标/图表说明文案：四段式规范（Chao 2026-08-27 拍板）

适用：`src/config.py` 的 `INDICATORS[].note`、dashboard 卡片的「📌 如何看」注解，
以及任何要给非工程背景读者解释一个数字的地方。

## 为什么改

旧版 note 只有 30–50 字，典型写法是：

```
"note": "银行/机构无担保融资压力预警。派生=(3M金融商票DCPF3M − 3M国库券DTB3)×100 bps。
⚠真swap spread(IRS−国债)无免费源(FRED DSWP2/10已停更2016/OFR无swap曲线...)"
```

Chao 的实际反馈是「让它更清晰一点」。问题有三层：

1. **开头就是公式和代号**，没解释 CP 是什么（他直接问「你的那个 CP 是什么意思？」）
2. **把内部技术债放最显眼位置** —— 「为什么用代理源」是实现细节，不是判读依据
3. **真正该说的「这数字怎么用」被埋在最后**

## 四段式结构（强制顺序）

```
【是什么】 人话定义 + 数据源。所有英文缩写首次出现必须展开并解释
           （CP = Commercial Paper 商业票据，银行发的短期无担保借条）
【怎么看】 数字方向 + 传导链 + 为什么这个数能当信号
【怎么用】 阈值（必须与 warn/trigger 实参一致）+ 组合用法 + 防误读
【注意】   口径坑 / 替代源理由 / 样本局限（可选，但技术债只能放这里）
```

目标长度 **250–320 字**。改写后 20 个指标平均落在这个区间。

## 四条必须写进去的东西

### 1. 方向陷阱要显式标注
凡是「越低越危险」的卡，开头就用 ★ 标出来，否则必被看反：

- `put_call` / `bofa_fms_cash` / `insider` / `lei` —— 都是越低越危险
- `vix` —— 对**顶部预警**而言危险的是**太低**（低波动诱发杠杆堆积），不是太高
- `yield_curve` —— 最易误读：倒挂只是「衰退在路上（可能还1-2年）」，
  **由倒挂转正（bull steepening）才是「衰退临近（数月级）」**
- `bank_funding_stress` —— swap spread 承压时是「缩窄」，本指标承压时是「走阔」，方向相反

### 2. 给历史参照系，让数字有坐标
CAPE 1929≈33 / 2000≈44 / 2009低点≈13 · 巴菲特指标 2000顶部≈140-150% ·
HY OAS 2008破20%、2020-03≈11% · SOFR-IORB 参照2019-09回购危机 ·
AAII家庭股票配置 2000-03峰值≈77% · CP−Tbill 2008雷曼前夜同类利差300+bps

### 3. 写清「不能用来做什么」
这条最容易漏，但最防止误用：
- `cape` —— 长期估值指标，**可在高位停留数年，拿它择时会持续踏空**
- `ad_line` —— 背离通常数周至数月才兑现，是**预警不是择时**
- `yield_curve` —— 领先 6–24 个月，跨度太大不能当择时信号

### 4. 诚实边界写进说明本身
`bofa_bull_bear` / `ad_line` 无固定免费源、靠 web_search 交叉验证 →
明写「搜不到时留空标『未找到』，绝不沿用旧值也不估算」。
`bofa_fms_cash` 注明 NAAIM 已于 2026-08-01 转付费停更、本系统不再采集。

### 易混淆的卡要互相点名
`aaii_bull_bear` 问的是**怎么想**（问卷态度），`aaii_alloc` 问的是**实际怎么放钱**（真实仓位）
—— 两张卡的 note 里各写一句指向对方，后者是更硬的证据。

## 批量改写的做法

一次性脚本放 `scratch/rewrite_notes.py`（scratch 已 gitignore），用正则**只替换 note 字段**：

```python
km = re.search(r'\{"key":\s*"%s"' % re.escape(key), src)          # 先定位条目
nm = re.compile(r'"note":\s*"((?:[^"\\]|\\.)*)"').search(src, km.end())
if re.search(r'\{"key":\s*"', src[km.end():nm.start()]):          # 防越界到下一条目
    missed.append(key)
```

**任一 key 未命中就整体不写盘**，避免改一半。改前先 `cp src/config.py /tmp/config.py.bak`。

## 三道验收（缺一不可）

改文案最大的风险是**把阈值写错**，所以第 3 道是硬要求：

```bash
# 1) git diff 必须只动 note 行
git diff src/config.py | grep '^[+-]' | grep -v '^[+-][+-]' | grep -cv '"note"'   # 期望 0

# 2) 口径字段逐一对比备份（key/warn/trigger/source/direction/status_labels 差异必须为 0）
cp /tmp/config.py.bak /tmp/cfg_old.py    # ★.bak 后缀 importlib 加载不了，必须先改名 .py
```

```python
# 3) 阈值文字 vs 实参交叉核对 —— note 里写的每个阈值都要能在 warn/trigger 找到
for m in config.INDICATORS:
    for label, v in (("warn", m.get("warn")), ("trigger", m.get("trigger"))):
        if v is None: continue
        s = "%g" % v
        assert s in m["note"] or s+"%" in m["note"] or s+"bps" in m["note"], (m["key"], label)
```

## 渲染验证的坑

`dashboard.generate()` **返回的是文件路径，不是 HTML 字符串**——它直接写盘。
把返回值当 HTML 会得到 74 字节还以为渲染失败。
正确做法是读真正的产物：

```python
html = open("dashboard/index.html", encoding="utf-8").read()   # ~2.0 MB
assert html.count("【是什么】") >= 20
for m in config.INDICATORS:
    assert m["note"][:24] in html, m["key"]     # 逐条确认说明真进了页面
```

调用签名（易记错）：
`signals.eval_sell_triggers(results, cot_results)` 返回 `(checks, hit)`；
`signals.light(indicator_dict, value)` 第一参是**指标 dict 不是 key 字符串**；
`signals.overall_signal(hit_count, group_stats_d)`。
