# KOL-changes block EVOLUTION: 当日 → 上周至今 → 本周·完全独立自建快照 (Chao corrections 2026-08)
(原在 SKILL.md 正文, 2026-10-16 因正文触 100K 字符上限下沉到此; 内容逐字保留要点)

Three versions, each a Chao correction. **v3 is current — the block is built ENTIRELY from Eco's OWN daily snapshots, touching NO other agent's DB.** Don't re-implement v2.

- **v1 "当日"** (rejected): most days only 1-2 KOLs change direction → a "当日" grid reads as "没有任何变化", looks empty/broken.
- **v2 "上周一至今"** (superseded): widened to a week window but sourced the look-back from the OTHER agent's Notion by_day DB (`fetch_kol_recent`/`kol_stance_changes`). Chao then rejected the DEPENDENCY itself.
- **v3 "本周·完全独立"** (CURRENT): the KOL data must NOT depend on another agent's Notion DB; Eco crawls all KOL itself, snapshots to its OWN git-tracked vault, does its own week-over-week diff. General **"own-your-derived-metric" decoupling pattern**. Confirmed prefs: (Q1) keep the v2 仿-13F sector-modular RENDER, (Q2) snapshots in THIS repo `data/kol/daily/`, (Q3) recompute weekly, title = "本周 KOL 状态变化".

## Independent daily-snapshot data-vault pattern (reusable for ANY derived metric you want to own)
Accumulate your OWN history (a single overwritten daily file can't diff across days):
- `save_kol_daily_snapshot(date_str=None)` — after the daily crawl persist FULL current directions to `data/kol/daily/YYYY-MM-DD.json` (`{date,count,source,kols:[{kol,sector,direction,targets,comments}]}`). Idempotent (same-day rerun overwrites; two runs → identical md5). Git-tracked dir IS the vault (public repo; `.env` never). `data/kol/` is NOT in `.gitignore`, daily cron's git add picks it up.
- `load_kol_daily_snapshots()` → `{YYYY-MM-DD: {kol: {...}}}`.
- `kol_weekly_changes()` — diff 本周最新快照 vs 上周最后一天快照 (week boundaries from `date.today()`); a turn per KOL whose `direction` changed. KOL with NO last-week record is SKIPPED (newly-covered ≠ turned). No cross-week snapshots yet → honest fallback earliest-vs-latest; **only ONE day exists → return `[]`, never fabricate a turn.**
- `kol_stance_changes_grouped()` sources `kol_weekly_changes()` ONLY (`fetch_kol_recent`/`kol_stance_changes` other-agent-DB path DEPRECATED). Returns `{since, days, total, modules:[…]}`, shape unchanged.
- **Honest empty state EXPECTED at first**: block legitimately EMPTY ("本周暂无 KOL 主导方向变化（或快照尚在累积中）") until ≥2 cross-week snapshots exist. 绝不编数字 — tell user it attaches automatically; OFFER (don't auto-do) one-time seed backfill.
- Render + sector-归一 unchanged from v2: `_KOL_SECTOR_MAP` (maps BOTH 中文 and 英文 vocab → one 中文 module + 英文 subtitle + `_KOL_SECTOR_COLOR`; unmapped→"其他"); `_kol_changes_html` = overview + one `.h-module` per sector + `.kol-mod-inner` cards with **shift badge** (rank 强烈看空 -2 … 强烈看多 +2; new>old ⇒ ▲转多 clay红; new<old ⇒ ▼转空 sage绿 = 逆向 buy-point; equal ⇒ →微调) + prev→new chips + 言论 + 标的. A plain `list` gets wrapped in one "全部" module.
- Threading: `build_dashboard.py` calls `save_kol_daily_snapshot()` BEFORE `kol_stance_changes_grouped()`; part-title → "本周 KOL 状态变化 · 按模块".
- Window is a one-place preference (weekly boundary lives in `kol_weekly_changes()`).

## VIEWS (观点全景) vs CHANGES (转向) — a turn-only block is TOO NARROW
Chao: "本周你没找到任何有意义的更新吗？…不可能 88 个 KOL 这一周什么话都没说吧？". **"状态变化" and "本周有意义的观点" are two different products — a diff-only block shows near-nothing most weeks and reads as broken.** Fix = SECOND complementary block, not replacing changes:
- `kol_weekly_views(min_comment_len=10)` — every KOL with a substantive comment, grouped by sector; source = same independent snapshots (latest day preferred; fall back to `kol_independent.json` `all`). Filter `len < min_comment_len` so "有实质观点" is real. (60 of 91 had real views across 7 sectors.)
- `_kol_views_html` — one card per KOL with 多空方向 badge (`.kv-badge`: 强烈看多 clay红填充 / 看多 浅红 / 分歧·中性 灰描边 / 看空 浅绿 / 强烈看空 sage绿填充 — warm=bull, cool=bear) + 言论 + 标的, in `.h-module` sector boxes; sort by direction strength, modules by view-count desc.
- Layout: VIEWS block ("本周 KOL 观点全景 · 按模块") ABOVE CHANGES block. `generate()` kwarg `kol_views=None` + template slot + build_dashboard threading.
- SECTOR-MAP dedup gotcha: "贵金属" and "贵金属与商品周期" mapped to two modules → collapse synonyms to ONE canonical 中文 module.
- General rule: when a "what changed" block is legitimately sparse, the user usually ALSO wants a "current state / what everyone said" companion — offer both.

## Per-opinion DATE labeling — a snapshot only records CRAWL-day
Every views-card carried the SAME date (crawl day) — MISLEADING. 1) **DON'T regex-extract a 发表日 from comment text** (price-target years 2028-30, forecast years 奇点2029, ranges 25-30 produce WRONG dates). Chao chose Option A: REMOVE the uniform date (keep KOL+方向+言论+标的); dates the KOL wrote INTO the comment (8/3发) stay naturally. 2) Durable fix: **import the sibling agent's by_day HISTORY into your own vault as a one-time seed** — without cross-day HISTORY you cannot tell a NEW opinion from a REPEATED one. KOL_BY_DAY_DB via `fetch_kol_recent(days,limit)` covered ~2026-01-06→, ~94 KOL, ~2339 rows.
- EXECUTED 2026-08: `scratch/import_kol_history.py` (one-shot) pulled `fetch_kol_recent(days=240, limit=20000)` → 205 day-snapshots (2025-12-18→08-13) into `data/kol/daily/` (skips existing days), vault 206 snapshots ~1.6M. Commit 1589cb2.
- `kol_weekly_views` emits `since_date` (当前方向连续保持起始日) + `is_new` (起始日 ≥ 本周一). Renders `🆕 本周新观点` or `自 <date> 持此观点`.
- ★粒度 REALITY: imported by_day history is SPARSE (~6-13 KOL/day) while Eco's own crawl is DENSE (all 91) → backfilling from the dense snapshot into sparse history makes `since_date` stop at the first dense day → ALL views label "本周新观点". NOT a bug; self-corrects as Eco accumulates its own dense snapshots. Tell user plainly.
- 伪转向 FILTER: `kol_weekly_changes` emitted fake turns "看空→未找到" when a KOL wasn't covered. Fix `_invalid_dir = {"","未找到","无","n/a","未知","数据滞后","-","—"}` skip any turn where EITHER end invalid (9 with fakes → 6 real). Rule: a "not observed" value is NOT a real state in any period-diff over sparse coverage.

## KOL 一年历史 comments BACKFILL — delegate_task fan-out with DATED-opinion extraction
- ★**web_search CANNOT time-travel** — returns currently-indexed content. Say so up-front. Achievable: have an LLM EXTRACT only opinions with a REAL source-confirmed date; no confirmable date → discard.
- **Sample-before-full** (Chao 硬规则 "先1样板验收才全量"): 3-5 representative KOLs first (well-known / newly-added / alt-prophecy), show yield, get OK, then full roster.
- Mechanics: `delegate_task` fan-out (subagents have `web`; a script CANNOT call web_search). One task per KOL, toolset `["web"]`, strict output contract: JSON array `{date:"YYYY-MM-DD"(真实发表日),direction,comments(中文50-150字),targets,source(URL/节目名)}` + 绝不编 + "搜不到就返回 [] 并说明". ★max_concurrent_children=3 → batch in 3s. Subagent summaries are SELF-REPORTS — spot-check.
- Realistic yield: well-covered analyst 5-7+ dated items (extensible 30-50 with per-month 深挖); mid-tier ~5 over 11 months; alt-prophecy ~6. Expect ~300-500 dated rows over ~83 active KOL, NOT a dense daily year.
- Alt-prophecy KOL still maps to a direction (崩盘/衰退预警→看空, 复苏→看多) but tag it as such.
- Write path: merge each subagent's dated array into `data/kol/daily/YYYY-MM-DD.json` (append per-date, idempotent, dedup by kol+date), commit+push.
