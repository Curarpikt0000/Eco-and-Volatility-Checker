# 数据源核验日志 2026-09（Eco-and-Volatility-Checker）

实测记录，每条都有当时的判据。用于避免重复排查同一批源。

---

## 1. SEC EDGAR：可用端点与 503 陷阱

**★最重要的一条**：`https://www.sec.gov/cgi-bin/browse-edgar?...&action=getcompany`
本机访问会返回 **HTTP 503 错误页（非空、7.7KB）**。若只按「页面里没有 CIK / 没有公司行」
解析，会把 503 误判成「EDGAR 无此公司」——**碰巧对的时候，过程全是错的**。

```
实测 2026-09-25:
  browse-edgar?company=Thiel+Macro&type=13F   → HTTP 503, 不含 1562087  ❌
  cgi-srv/browse-edgar ... &output=atom        → HTTP 404               ❌
  efts.sec.gov/LATEST/search-index?q=...       → HTTP 200, 命中 Thiel   ✅
  www.sec.gov/files/company_tickers.json       → HTTP 200, 797KB        ✅
```

**可用通道**：
- 全文检索：`https://efts.sec.gov/LATEST/search-index?q=<urlencoded>&forms=13F-HR`
  - 返回 JSON：`hits.total.value` = 命中数，`hits.hits[]._source` 有 `form` / `file_date` / `display_names`
  - `display_names` 是**申报主体**，必须看它 —— 「全文含某人名」经常是别人的文件里引用他
- 公司名全量表：`https://www.sec.gov/files/company_tickers.json`
- UA 必须带联系方式（SEC 要求），`Accept: application/json`

**纪律**：任何「EDGAR 查不到 X」的结论，先拿**已知一定存在的实体**（本项目用 Thiel Macro
CIK 1562087）走同一查询跑一遍。对照组也查不到 = 通道坏了，结论作废。

## 2. 哪些 KOL 不可能有 13F（结构性，别反复查）

13F 申报义务 = 管理 ≥$1亿美元的 13(f) 证券。**订阅制研究机构不管钱，无申报义务。**

| 人 / 机构 | 13F | 原因 |
|---|---|---|
| Luke Gromen / FFTT (Forest for the Trees) | ❌ 0 条 | 卖 newsletter 的研究机构 |
| Zoltan Pozsar、Lyn Alden 等同类 | ❌ | 同上 |
| Peter Thiel / Thiel Macro (CIK 1562087) | ✅ | 真家族办公室 |

噪声警告：`Forest for the Trees` 在 EDGAR 全文有 74 条命中，**全是英文成语**
（「只见树木不见森林」）；`Gromen` 的 7 条是 Seabridge Gold / Sprott 引用他的观点。
**命中数 > 0 不等于他申报了**，必须 `forms=13F-HR` 过滤 + 看 `display_names`。

→ 这类人只能进 **KOL 观点线**，进不了 **13F 持仓线**。

## 3. ★FIMA 口径错误（已确认的真 bug，待修）

日报里的「FIMA 海外回购 $318.4B」**抓错了科目**，方向正好相反：

| | 真 FIMA | 日报实际抓的 |
|---|---|---|
| FRED series | `WORAL` | `WLRRAFOIAL` |
| H.4.1 科目 | Repurchase agreements – foreign official | **Reverse** repos – Foreign official & intl |
| 表侧 | **资产** | **负债** |
| 含义 | Fed **借美元给**外国央行 | 外国央行把美元**存在** Fed |
| 2026-09-16 实测 | **$0.255B**（255 百万） | **$318,428M = $318.4B** |

```
WORAL       2026-09-16  255      2026-09-09  6        2026-09-02  0    ← 常态≈0
WLRRAFOIAL  2026-09-16  318,428  2026-09-09  349,231  2026-09-02  357,217
```

**后果**：把「外国央行存钱」说成「外国央行借钱」。日报那句「FIMA −30.8B ← 值得注意」
听起来像「海外美元压力缓解」，实际是外国央行从逆回购池撤走 $308 亿（在动用美元）。
而真 FIMA 同期从 $6M 升到 $255M —— 量级仍极小，但**方向是升**。

**修法**：①`WLRRAFOIAL` 正名「外国央行逆回购（存放于 Fed）· 负债侧」
②另加一行真 FIMA（`WORAL`），标注「常态≈0，跳升=海外美元荒」③解读文案跟着改。
代码位置：`src/external_data.py` L1071 `("FIMA 海外回购", "资产_FIMA_B")`。

## 4. WGC 周报 PDF（Weekly Markets Monitor）

- 列表页 → 详情页 → PDF 链接，两跳；**列表 API 存档只到 2025**（约 48 期，page=10 即 HTTP 错误）
- **第 23 页** = `ETF options: ATM IV term structure` + `Futures: ATM IV term structure`
  - 矢量坐标可反推真数值，图例 ticker↔色块 6/6 可硬配对
  - **这里能拿到 COMEX 期货期权 IV（GC1/AUA1）** —— 此前判定「八条路全封」的那个数据
  - 与 CBOE 自算交叉验证：12/12 点差 ≤1.5pt，平均 +0.21，**证明 delta 插值算法正确**
- **第 24 页** = `Gold options delta skew`，口径 **`25D C-P IVOL`（call 减 put）**

**★三种 skew 口径符号互不相同，并排前必须对齐**：
```
高盛     put IV ÷ call IV   >1 偏空   (截图里 6M 冲到 1.03 = 2017 年来最高)
本项目   put IV − call IV   >0 偏空
WGC      call IV − put IV   >0 偏多   ← 与上面两个反向
```
弄错会让整张图上下颠倒，而且看起来还挺「合理」。

## 5. Michael Lynch / EconAnalytics（COMEX issues & stops 图）

那张「做市商累计囤货 1.7 亿 oz」的图 —— **原始序列拿不到，已实测，别再查**。

```
Substack API 可用:  /api/v1/archive?sort=new&limit=50&offset=N
                    /api/v1/posts/by-id/<id>   → 正文在 d["post"]["body_html"]，不在顶层
免费无付费墙 (audience: everyone)，正文 3.2 万字符全可取
★ 但 <table> x0，<img> x6 —— 数据全做成 PNG 贴上去
★ 全站仅 23 篇，2025-02-28 ~ 2026-02-26
★ 已停更（archive API + RSS feed 两条独立通道互证，最新一篇距今 208 天）
```

**读列表时注意 Substack 是最新在前**（我曾读反，误判成「存档只到 2025-10」）。

本项目 `data/comex_silver_issues_ref.json` 里的 18 个点是**从图上手抄的锚点**，非真序列。
真数据在 `comex_issue_stop_firms`（逐 firm × 日粒度，2026-01 起，133 份 archive PDF）
和 `comex_issue_stop_weekly`（35 周）—— 同口径但只有 9 个月，做不出 2011 年起的长历史。

## 6. 注入 fetcher 时的两个坑

**★`src/external_data.py` 顶层没有 `import requests`** —— 所有 fetcher 都是
**在函数内部** `import requests`。直接写 `requests.get` 会 `NameError`，
然后被自己的 `except Exception` 吞掉，只剩一句业务错误（「未找到 PDF 链接」）。

我因此朝**正则转义**方向排查了三轮（还改了两次文件、做了字节级核对），全是错方向。
真正的判据一行就够：`hasattr(ed, 'requests')` → `False`。

两条纪律：
1. **写新 fetcher 前先读同类已有实现**。我凭印象编了 `_http_get_text` / `_http_get_bytes` /
   `_save_cache` / `_load_cache` 四个**根本不存在**的函数。
2. **`except Exception` 里必须打出真实异常类型**，否则下次还是只看到业务错误往错方向查。

同类毛病（同一天撞了三次）：猜 CBOE 返回的字段名 —— 实际 `tickers` 是 dict 不是 list，
期限结构字段叫 `term` 不是 `atm_iv`。**先 dump 真实结构再写代码。**

## 7. KOL backfill 缺口的正确算法

`131 个文件` vs `146 人名册` **不能相减得缺口**。正解：

1. `set(名册 active id) - set(backfill 文件名)` → 原始缺 26
2. **再排除命名变体**（规范化：去下划线 + 小写 + 用孤儿文件里的真实人名反查）
   - `charlesnenner` ←→ `charles_nenner`、ANONYMIZED_PERSON_0_15 ←→ `goldman_sachs`
   - 不排除就会给已有历史的人重复建档，旧历史继续当孤儿
3. → **真缺 24 人**

```
apply_1yr_backfill.py --stat  实测:
  在册 146 | ✅满一年 35 | ⚠️不足一年 82 | ❌无历史 29 | 覆盖率 24.0%
```

**★关键约束**：`apply_1yr_backfill.py` 与 `backfill_kol_detail.py`
**自己不产出任何文字**，代码注释明写「真正的摘要由调用方用 web_search + web_extract
产出，脚本自身不生成任何文字」。所以「全套 backfill」= 逐人联网检索，不是跑个脚本。
报工作量时必须讲清这点。

另：15 人 `direction=未找到` 里有 Asha Sharma（微软副总裁）、Kevin Murphy（芝大教授）、
Carroll Quigley（**已故历史学家**）—— 这类人本就不发表市场方向观点，
该在**名册侧**处理（Notion SSOT），不是反复抓。

## 8. ChaoWiki 收拢：hook 给的文件清单可能不全

learn-gate hook 提示「2 个已修改未 commit」，但实际必须提 **3 个**：
README 本次新增的那一行正是 `[[headless-visual-acceptance]]`，而该文件还是**未跟踪**状态。
只按 hook 清单提交 → wiki 断链（索引指向远端不存在的页面）。

**纪律**：收拢归档时先看 `git diff` 里新增的 wikilink，再看 `git status -uall` 的未跟踪文件，
**引用与被引用必须同一个 commit**。（仍然绝不用 `git add -A/-u`，只 add 具体文件名。）
