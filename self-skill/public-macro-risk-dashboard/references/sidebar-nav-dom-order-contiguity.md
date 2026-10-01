# Sidebar nav "跳跃感": DOM order must equal menu-group order

**Chao has reported this same complaint three times** (2026-08-22, 08-25, 08-31). The first two
fixes treated symptoms and it came back. This file records the actual root cause and the
verification that proves it's gone.

> Note: the dedicated skill `html-dashboard-sidebar-scrollspy` is **user-owned** (curator cannot
> edit it). It holds the scrollspy implementation, the script-timing pitfall, and the CDP
> verification workflow — read it too. This file records only the ordering root cause, which lives
> naturally with this dashboard's §5 "sidebar grouping" step.

---

## Symptom

"这张图在我 browse 的时候有跳跃感，它的安放位置并没有和右边 menu 的位置保持一致."

While scrolling steadily downward, the highlighted nav item jumps **backwards** to an earlier group,
then forward again.

## Root cause: interleaved groups, not a scrollspy bug

The sidebar assigns each section to a group by **keyword match on its title**. That's fine — but if
one group's members are **not contiguous in DOM order**, the highlight is *forced* to jump as you
scroll past them. No amount of `rootMargin` tuning fixes it; the ordering itself is contradictory.

Measured on this dashboard (48 sections):

```
KOL 观点        #9,10,11 .................. #48    <- 37 sections apart
流动性与央行     #12-17 ...... #21 ...... #47
债务与信用       #18,19,20 ...... #22
国债流动性观测   #23-32                            <- contiguous, fine
```

Scrolling into #21 yanked the highlight back up to the 流动性 group; reaching #47/#48 threw it back
to near the top of the menu.

**Prior fixes that did NOT solve it** (so don't repeat them):
- 08-22: sort groups by their first member's DOM position.
- 08-25: move stray sections that fell into the 「其他」 bucket into real groups.

Both improved the *group ordering* while leaving the *interleaving* intact.

## Measure before changing anything

Do not eyeball this and do not tune CSS margins. Build the group → DOM-index map:

```python
import re
h = open('dashboard/index.html', encoding='utf-8').read()

titles = []                                   # nav items, in DOM order
for m in re.finditer(r'class="part-title[^"]*"', h):
    s = h.rfind('<', 0, m.start()); e = h.find('</div>', m.start())
    seg = h[s:e]
    if 'part-num' not in seg:                 # only top-level titles are nav items
        continue
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', seg)).strip()
    titles.append(re.sub(r'^[＋\+\d\s]+', '', t))

seen, order = {}, []
for i, t in enumerate(titles, 1):
    g = group_of(t)                           # same keyword table as the sidebar JS
    seen.setdefault(g, []).append(i)
    if not order or order[-1] != g:
        order.append(g)

for g, idx in seen.items():
    ok = idx == list(range(idx[0], idx[0] + len(idx)))
    print(f'{g:14s} {idx} {"" if ok else "<<< 不连续"}')
print('重复出现的组(=会跳):', [g for g in set(order) if order.count(g) > 1] or '无')
```

**Pass requires all three:**
1. every group's indices are contiguous,
2. no group appears more than once in `order`,
3. menu group order === page DOM order.

## Two fixes — ask the user which

- **A. Reorder the DOM** (Chao chose this: 「根据 menu 顺序来改，分组可以」). Move outlier sections
  next to their group siblings. Root fix — and the interleaving usually reveals sections that were
  simply misplaced (「中国央行流动性」 belongs with the other central-bank content anyway).
  Cost: page reading order changes.
- **B. Change the grouping rule** — let a group split into multiple DOM-ordered runs, or drop
  grouping and list sections flat. Page untouched.

When moving sections: **position only — content, `id`, and data semantics unchanged.** List every
`原位置 → 新位置` in the commit message.

## ★ Moving a section INTO a commented-out block makes it vanish

This dashboard keeps disabled sections inside `<!-- ... -->` (e.g. `cycle_kol`). I inserted the KOL
roster *inside* that comment; the section disappeared from the render while **source grep still
matched it** — the same "grep 有、DOM 无" fingerprint as the duplicate-`id` pitfall.

Verify every moved section exists **and is non-empty**:

```python
for key, name in [('sec-cn-liq','中国央行流动性'), ('sec-cb-swaps','央行货币互换'),
                  ('sec-ai-fcf','AI 自由现金流'), ('sec-kol-roster','KOL 全量名录')]:
    i = h.find('id="%s"' % key)
    c = h.find('<div class="card">', i)
    print(name, '存在' if i > 0 else '缺失 ❌',
          '内容为空 ⚠' if (c > 0 and 'class="empty"' in h[c:c+400]) else '正常')
```

## ★ Truncated search windows manufacture fake "element missing" reports

While diagnosing, I sliced `h[i:i+6000]` to look for the second chart, didn't find it, and reported
"柱状图没渲染". It was simply beyond 6000 chars — **the chart had been fine the whole time.**

Before reporting anything missing, widen the window (12000+) or bound it by the next known heading
(`h.find('<next section title>')`) and confirm the search range actually covers the target.

## Corollary: "这张图只有美国，少了三个国家" was the same bug

Check the **data layer before the render layer**. `iip_four.json` had all four countries with full
11-year series, and the product HTML had 4 `<polyline>` elements plus all four country labels in the
bar chart. The chart was complete — it just sat at a jump point and read as truncated.

**Don't start backfilling data on a visual-truncation report.** Confirm the data is actually absent
first; here the real fix was the ordering.
