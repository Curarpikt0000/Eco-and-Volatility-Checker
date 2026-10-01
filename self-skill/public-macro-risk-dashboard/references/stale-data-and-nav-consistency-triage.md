# 「这个数据怎么这么旧 / 这个图怎么不更新」的三层归因 + 侧栏跳跃

Companion to `dashboard-data-integrity-audit.md`。那份讲**审计一遍全站**；这份讲
Chao 指着**某一张图**问「怎么没自动取」「怎么还是去年的」「browse 有跳跃感」时的定位流程。
全部来自 Eco-and-Volatility-Checker 2026-08-31 实测。

## 铁律：先归因到层，再动手

用户报「数据旧了」时，**四种根因的修法完全不同，且互斥**。不先归因就改代码，
大概率修错地方（对照主 audit 文件的四判决表，这里是「单图版」的快速通道）：

| 根因 | 判据（必须实测，不能推测） | 修法 |
|---|---|---|
| **上游还没发** | 直接问官方 API 最新一期 | 不是 bug，别改 |
| **上游断供** | 上游页面自报的更新时间戳停了 | 换源 / 修上游项目 |
| **聚合库滞后**（源已发但你读的库没收录） | 申报索引里有更新的 filing，但聚合端点没有 | 加「读原始文件」补充源 |
| **我方 UA/请求头被拒** | 换一个 UA 立刻 200 | 修请求头 |

### 案例 A：EIA 石油库存「怎么 8/26 没更新」→ 上游还没发，不是 cron 漏了

图上写「下次约 2026-08-26」是**预告文案**，不是已有数据。先别查 cron：

```python
# 直接问 EIA 官方，看最新一期到底是哪天
u = ("https://api.eia.gov/v2/petroleum/stoc/wstk/data/?frequency=weekly"
     "&data[0]=value&facets[series][]=W_EPC0_SAX_YCUOK_MBBL"
     "&sort[0][column]=period&sort[0][direction]=desc&length=5&api_key=DEMO_KEY")
# → 最新 period = 2026-08-21，08-28 那期根本没发
```
`DEMO_KEY` 足够做这种「最新一期是哪天」的探针，不需要申请正式 key。
本地 `data/oil_inventory.json` 的 `as_of` 是当天、文件当天被写过 → 抓取链路完好。
**结论：cron 正常，EIA 周报延迟。**

### 案例 B：COMEX/上海库存 + GLD/SLV ETF 卡在 08-20 → 上游 GitHub Pages 停更

这两张图的源不是交易所，而是**另一个自建 GitHub Pages 项目**
（`curarpikt0000.github.io/comex-inventory-charts`，解析页面内联的 `const CHARTS`）。

```bash
curl -s --max-time 40 -H "User-Agent: Mozilla/5.0" \
  "https://curarpikt0000.github.io/comex-inventory-charts/" > /tmp/up.html
grep -oE '"20[0-9]{2}-[0-9]{2}-[0-9]{2}"' /tmp/up.html | sort -u | tail -5   # 页面内最大日期
grep -oE '更新：[^｜<]*' /tmp/up.html                                          # 页面自报更新时间
```
实测：页面自报「更新：2026-08-21 08:15 JST」、内含最大日期 2026-08-20 → **上游自己停更**。
我方抓取正常（且有缓存回退保护，所以曲线没变空，见下）。

**排查顺序**：自家 fetcher → 上游产物 → 上游的 cron。跳过中间一层就会误判成自己的 bug。

### 案例 C：TSM 财报停在 FY2024 → SEC companyfacts 对 20-F 收录滞后

图上 18 家公司里 **只有 1 家**是 2024 年（不是用户以为的「很多都是 2024」——
先把真实分布列出来再回答，别顺着用户的判断走）：

```python
d = ed.fetch_ai_fcf()
for g in d["groups"]:
    for m in g["members"]:
        print(m["ticker"], m["fy"], m["fcf"])
# 2026年3家 / 2025年14家 / 2024年1家(TSM)
```

根因链（第一轮我误判成「SEC 没有数据」，**是错的**）：
1. `data.sec.gov/api/xbrl/companyfacts` 最新只到 2024-12-31 → 看起来像「没有」
2. 但查申报索引，**2025 年 20-F 早在 2026-04-16 就报了**：
   ```python
   u = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
   r = json.load(...)["filings"]["recent"]
   for form, rep, accn in zip(r["form"], r["reportDate"], r["accessionNumber"]):
       if form.startswith(("10-K","20-F")): print(form, rep, accn)
   ```
3. 结论：**companyfacts 聚合库对外国私人发行人（20-F）收录严重滞后**，
   直接读那份 filing 的 XBRL 实例文件即可拿到，数据仍是官方申报值、口径不变。

复用方案见 `scripts/sec_filing_xbrl_fallback.py`（本目录）。

## SEC 取数的三个必踩坑

### ① UA 必须含真实邮箱，否则 `www.sec.gov/Archives/` 一律 403

**影响面远超单张图**：任何「读 filing 原文」的功能都会静默失效返回 None。

```python
# ✗ data.sec.gov 能过，Archives 一律 403
{"User-Agent": "EcoVolChecker research (contact: ANONYMIZED_EMAIL_ADDRESS_0_6)"}
# ✓ 两个域名都过
{"User-Agent": "Eco-Volatility-Checker ANONYMIZED_EMAIL_ADDRESS_0_5"}
```
实测对照（同一 URL）：前者 `HTTP Error 403: Forbidden`，后者 `200`。
**新增任何 SEC 端点后，先单独测一次 Archives 域名**，别假设 `data.sec.gov` 能过就都能过。

### ② IFRS 标签名和 US-GAAP 不同，且必须先枚举

`PaymentsToAcquirePropertyPlantAndEquipment`（US-GAAP）在 IFRS filing 里**命中 0**。
真名是 `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`。
**别凭记忆写标签名**，一条命令枚举：

```python
tags = set(re.findall(r"<ifrs-full:([A-Za-z]*PropertyPlantAndEquipment[A-Za-z]*)[ >]", raw))
tags2 = set(re.findall(r"<ifrs-full:(PurchaseOf[A-Za-z]*)[ >]", raw))
```

### ③ 20-F 同时申报本币和美元 → 不按 `unitRef` 过滤会算出荒谬值

TSM 的 XBRL 里同一年度同时有 `unitRef="twd"` 和 `unitRef="usd"` 两条事实。
用 `{end_date: value}` 建 dict 时后者覆盖前者，混算出
**FCF = −11999 億**（而实际 OCF 22750 > CapEx 12724，本该是正数）。

```python
un = re.search(r'unitRef="([^"]+)"', attrs)
if not un or un.group(1).lower() != unit:   # unit="usd"
    continue                                 # 币种不符 → 跳过，防混算
```
配套两条过滤：
- `if cid not in ctx or ctx[cid][2]: continue` —— 跳过带 `<segment>` 的分部披露，只取合并数
- `if st[:4] != en[:4]: continue` —— 跳过非完整自然年区间

**荒谬值（符号反了 / 量级差百倍）永远先怀疑单位混用，别先怀疑数据源。**

### ④ context 标签**没有** `xbrli:` 前缀

filing 实例文件里是 `<context id="c-1">` + `<startDate>`，不是 `<xbrli:context>`。
按后者写正则会解析出 0 个 context，导致所有事实被「context 不存在」过滤掉 → 静默返回空。
先 `print(raw[raw.find("<context"):][:420])` 看真实结构再写正则。

## 「多产物 / 多数据源」项目的陈旧度盘点

一次性列出所有数据文件的落后天数，比逐张图问快得多：

```python
import json, glob, os, datetime as dt
today = dt.date.today()
rows = []
for p in sorted(glob.glob('data/*.json')):
    try: d = json.load(open(p, encoding='utf-8'))
    except Exception: continue
    if not isinstance(d, dict): continue
    aso = d.get('as_of') or d.get('asof') or d.get('date') or ''
    age = None
    if isinstance(aso, str) and len(aso) >= 10:
        try: age = (today - dt.date.fromisoformat(aso[:10])).days
        except Exception: pass
    rows.append((age if age is not None else -1, os.path.basename(p), aso[:10],
                 d.get('status',''), dt.date.fromtimestamp(os.path.getmtime(p))))
for age, n, aso, st, mt in sorted(rows, reverse=True)[:26]:
    print(f"{n:34s} {aso:12s} 落后{age:>4} {str(st)[:10]:11s} mtime={mt}"
          + ("  <<<" if age >= 7 else ""))
```

**关键判读：`as_of` 旧 + `mtime` 是今天 = 抓取跑了但没拿到新数据**（上游问题），
不是 cron 漏了。两个字段必须一起看，只看其一必误判。

年频/季频源天然落后（`bis_gold_swaps` 153 天属正常），
按 audit 文件的 `FRESHNESS_SLA` 分频率设阈值，别用统一天数。

## 缓存回退保护：让上游断供不至于让曲线消失

上游停更时曲线仍在，是因为 fetcher 有这层保护。新写 fetcher 时照抄：

```python
def _fallback(note):
    """★铁律: 抓取/解析失败绝不返回空壳让曲线整块消失。
    有缓存 → 回退缓存真值 + status='ok(缓存)' + stale_days 标滞后天数; 无缓存才认输。"""
    try:
        cached = json.load(open(cache_path))
        if cached.get("panels") or cached.get("flows"):
            cached = dict(cached)
            stale_since = cached.get("fetched_at") or cached.get("as_of")
            days = (dt.date.today() - dt.date.fromisoformat(str(stale_since)[:10])).days
            cached.update(status="ok(缓存)", stale_since=stale_since, stale_days=days,
                          note=f"实时源不可用({note}), 展示缓存真值, 滞后 {days} 天")
            return cached
    except Exception as e:
        print(f"[x] 缓存回退也失败: {e}")
    return {"status": "未获取", "as_of": None, "note": note}
```
代价是**上游断供会被这层保护掩盖**——所以陈旧度盘点必须查 `as_of` 而不是 `status`
（`status` 会显示 `ok(缓存)`，看着像正常）。

## 侧栏菜单「跳跃感」：分组必须与 DOM 顺序连续

用户说「图的位置和右边 menu 对不上 / browse 有跳跃感」时，
**根因通常不是某一张图，而是关键词分组算法**。

侧栏若按关键词把 section 归组（`GROUPS = [{name, match:[...]}]`），
同一组成员在 DOM 里可能**不连续**，滚动时高亮在菜单上下反复横跳。

```python
# 判据: 每组成员的 DOM 序号必须是一段连续区间
seq = [(i+1, grp(t)) for i, t in enumerate(titles)]   # titles 按 DOM 顺序
seen = {}
for i, g in seq: seen.setdefault(g, []).append(i)
for g, idxs in seen.items():
    ok = idxs == list(range(idxs[0], idxs[0] + len(idxs)))
    print(f"{g:14s} {idxs} {'' if ok else '  <<< 不连续!'}")
```

实测（48 个 section，3 组断裂）：
```
核心风险扫描   [1..8]              OK
KOL 观点      [9,10,11,48]        <<< 不连续!
流动性与央行   [12..17,21,47]      <<< 不连续!
债务与信用     [18,19,20,22]       <<< 不连续!
```

两种修法，**先问用户再动**（A 会改变页面阅读顺序，不是纯视觉改动）：
- **A. 改 DOM 顺序**——把游离 section 挪进它该在的组。根治，且往往页面逻辑本就该如此。
- **B. 改分组规则**——允许同名组按 DOM 位置拆多段，或取消分组、菜单纯按 DOM 平铺。

历史教训：本项目修过两次同类问题，**两次都只修了「其他」组掉到底部的表象**。
所以修完必须跑上面的连续性断言，不能「看着不跳了」就收工。

## 用固定窗口 grep 产物 → 会得出假的「功能没渲染」

用户报「IIP 图只有美国、少了三个国家」，我 `h.find(标题)` 后取 `h[i:i+6000]`
数 `<svg>`，只找到 1 个，据此断言「第二张柱状图没渲染」。**实际两张都在**——
第二张起点距标题 7387 字符，被 6000 的窗口切掉了。

```python
i = h.find('四国对外净头寸'); j = h.find('对外总资产 vs 总负债')
print(i, j)          # 2542206 / 2549283 → 间隔 7077，6000 窗口必漏
```
更稳：**按数据层预期值对撞**，而非数 DOM 元素。四国数据齐全就断言
`seg.count('<rect') == 10 and all(n in seg for n in ('美国','日本','德国','中国'))`。

与主 audit 文件的「ALL-ZERO 探针是工具假象」同源：
**「计数为 0 / 少了」先怀疑测量方法，再怀疑功能。**

## 回答「是不是 cron 忘了」这类归因问题的纪律

Chao 连续问了三张图「是不是 cron 漏了」。三张的真实根因**没有一张是 cron**：
上游未发布 / 上游停更 / 聚合库滞后。

- **别顺着用户的假设查**。先跑上面的陈旧度盘点 + 直接问上游，拿到事实再回答。
- **用户说「很多数据是 2024 年」时，先把真实分布列出来**（实测只有 1/18 家）。
  纠正前提比顺着答更有价值，但要给出完整名单让他自己核对。
- 三张图的答案不同就分三段讲清楚，别合并成一句「都正常」。
- 自己上一轮的错误结论（如「SEC 没有 2025 数据」）**主动更正并说明为什么错**。
