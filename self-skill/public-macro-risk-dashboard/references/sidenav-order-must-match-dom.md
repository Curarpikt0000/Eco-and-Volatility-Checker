# 侧边菜单顺序 ≠ 页面顺序（scrollspy 跳来跳去）

Chao 2026-08-22 反馈：「右边从上到下 browse 的时候，左边 menu 会跳来跳去」。
Realized on `~/Projects/Eco-and-Volatility-Checker/src/dashboard.py`。

---

## 症状 → 根因

菜单是 JS 运行时从 `.part-title` 生成的（静态 grep `href="#sec-` 抓不到，别以为没有）。
旧实现把每个 section 按关键词分进 `GROUPS`，然后 **按 GROUPS 数组的固定顺序渲染**：

```js
GROUPS.forEach(function(g, i) { renderGroup(i, g.name); });
renderGroup(GROUPS.length, '其他');      // 「其他」永远垫底
```

页面是 DOM 顺序，菜单是 GROUPS 顺序 —— **两个独立排序**。于是 scrollspy 高亮
在往下滚时会往回跳。

## 先量化，别凭感觉改

把两个顺序都抽出来，算「向上跳跃次数」：

```python
titles = [清洗后的 .part-title 文本, 按 DOM 顺序]
seq = [groupOf(t) for t in titles]
jumps = sum(1 for a, b in zip(seq, seq[1:]) if b < a)   # 本例 = 3
```

本例实测：44 个 section，**3 次向上跳跃**，且 **7 个掉进「其他」**
（术数板块、政府债务/GDP、公司债、CIPS、AI 产业链×2，以及当天刚加的 COMEX 交割前十名）。
「其他」渲染在最底部 → 读到页面中部时高亮突然窜到菜单最下面，这是体感"跳"最强的来源。

## 修法：按「首个成员的 DOM 位置」排组

```js
{ name: '机构与政要持仓', match: [...], pinLast: true }    // 需要钉底的组加标记

var order = [];
for (var gi = 0; gi <= GROUPS.length; gi++) {
  var it = bucket[gi];
  if (!it || !it.length) continue;
  order.push({ gIdx: gi, gName: ..., first: it[0].idx,
               pinned: (gi < GROUPS.length && GROUPS[gi].pinLast) ? 1 : 0 });
}
order.sort(function(a, b) {
  if (a.pinned !== b.pinned) return a.pinned - b.pinned;  // pinLast 沉底
  return a.first - b.first;                                // 否则按 DOM 首现
});
order.forEach(function(o) { renderGroup(o.gIdx, o.gName); });
```

组内成员本来就是按 DOM 顺序 push 进 bucket 的，所以只需排「组」。

## 同时要清空「其他」

只改排序不够 —— 「其他」里的项仍会散落。给漏网 section 补 match 关键词，
必要时**新建分组**（本例加了「债务与信用」收编 政府债务/公司债/CIPS/AI 产业链）。

★ **每次新增 section，必须同步加 match 关键词**，否则它会掉进「其他」。
本次新加的 `COMEX 交割前十名` 就是现成的例子 —— 加进「能源与大宗」的 match 才归位。

## 验收：必须在真实产物上数，不能只看模拟

```python
flat = [i for 每组 in 排序后的order for i in bucket[组]]
assert len(flat) == len(titles)          # 无遗漏/无重复
assert flat == sorted(flat)              # ★菜单顺序 === 页面顺序
assert len(bucket.get(len(groups), [])) == 0   # 「其他」清零
assert order[-1][3] == '机构与政要持仓'          # 钉底生效
```

本例最终：44/44 同序、跳跃 0、「其他」0 项。

## 顺带的通用坑

- **运行时生成的 UI 不能用静态 grep 验收**，要在 HTML 里把 JS 的数据结构（GROUPS）
  和 DOM（.part-title）都抽出来，用 Python 复现那段 JS 逻辑再断言。
- dashboard 重建约 5–6 分钟，**改代码和 build 有竞态**：build 启动后再改的代码不会进这次产物。
  改完必须重新 build，验收要看文件 mtime 对不对得上。
