# KOL 转向 semantics + past-year coverage backfill

For the Eco-and-Volatility-Checker KOL tracker (data/kol_registry.json roster,
data/kol/daily/*.json snapshots, data/kol/backfill/*.json history).

## "转向" (turn/stance-change) is WEEKLY, not same-day

When Chao asks "你说 KOL 转向，是今天转向的吗？还是本周转向的？" the honest answer is **weekly**.
`kol_weekly_changes()` / `kol_stance_changes_grouped()` compare:
  **this-week's latest snapshot direction  vs  last-week's last snapshot direction**
— a change between those two is a "转向". It is NOT a same-day flip. If cross-week data is
insufficient it falls back to earliest-vs-latest and flags a note. Read the docstring before
answering; don't guess the window from the dashboard's "本周 KOL 状态变化" title.

A "转向" batch is normally BIDIRECTIONAL and partial (e.g. 32 people, some 看多→强烈看多,
some 强烈看多→看多降温, some 看多→看空) — never describe it as "everyone turned strongly bullish".

Known bug to watch: the grouped result's `days` field can compute wildly wrong (e.g. 207 when
`since` is 4 days ago) — a date-diff parsing error. It doesn't affect the turn judgment itself
but makes the dashboard "距今 N 天" wrong; offer to fix separately.

## Verify a KOL is ACTUALLY in the roster before claiming you track them

Chao: "最近那个 Nomi Prins 是不是有了新的言论？" — she had fresh public comments, BUT
`grep -ic "prins" data/kol_registry.json` returned **0**: she was NOT in the roster, so the
dashboard could not possibly show her. When the user says "我记得我原来就有啊", still verify by
`id`/`display_name` exact match — a name they *remember* adding may have dropped in a past
iteration or lives in a different KOL project. Say so plainly, then add if they confirm.

**Add-one-KOL procedure** (roster is 只增不减; delete only on explicit confirmation):
1. Idempotent de-dup check (by `id` and `display_name`).
2. Anchor to an existing sector's field structure (e.g. Precious Metals: Peter Krauth /
   Keith Neumeyer) — do NOT invent a new sector; match `domain`/`sector`/`detail_sector`.
3. Write via a python script (not hand-typed JSON) with an ASCII `display_name` + English
   `search_terms` (avoids redactor poisoning), `list_num` = current max + 1, `notion_list_page_id` "".
4. Read back + assert 0 pollution (display_name/search_terms are real plaintext, no ANONYMIZED/
   os.pat…/*** placeholders) and `_count` incremented.
5. Red-line scan, commit `--no-gpg-sign` as Curarpikt0000, push. The daily cron reads
   "all active KOL" dynamically, so a new active KOL is auto-picked-up next run — no cron edit.

## Past-year coverage audit: count entries + span, NOT file existence

Chao: "所有 KOL 过去一年的数据都应该有扫描过，没有的人应该 backfill。"

A backfill file EXISTING ≠ adequate. Audit each active KOL's `data/kol/backfill/<id>.json`:
- keep only entries with a real `direction` (≠ "未找到") AND a `date`;
- classify: **ok** (≥3 real entries AND span ≥180 days), **shallow** (1-2 entries),
  **short_span** (<6 months), **empty** (0 real entries), **missing** (no file).
Real numbers from this session (98 active): ok 31 / shallow 40 / short_span 14 / empty 12 /
missing 1 → ~67 below target. Note active count (98) ≠ roster count (109) — some are active=false.

## Batch backfill = agent-mode cron (there is no fixed backfill script)

KOL backfill was always agent-mode (web_search + LLM extraction), so full backfill is too.
Pattern that worked:
1. Write the under-target list to `data/kol/backfill_queue.json` (each item carries id, name,
   sector, search_terms, reason, done=False).
2. Verify a 3-person sample manually first (Chao's "大改先跑1样板验收再全量" rule), then
   create a recurring cron (`every 30m`, toolsets web+terminal+file, deliver=local so no spam)
   that: pulls --rebase → takes the next 5 done==False → 2-3 web_search per person over the
   past year → extracts {date,direction,comments,targets,source} → writes/overwrites the file →
   marks the 5 done → commits+pushes. ~5/run keeps under search-backend rate limits; 66 people
   ≈ 14 rounds ≈ 7h.
3. Red-line in the prompt: **绝不编造** date/opinion/URL; 搜不到 → fewer entries or direction
   "未找到". Fed-advisor / academic / deceased / non-market names (raj_chetty, jeremy_stein,
   thomas_sargent, mervyn_king, peter_fisher, carroll_quigley, fema, ivan_zhao) legitimately
   have no trackable market views — write a low-count file, note "无可追踪公开市场言论",
   still mark done (don't loop on them).

## web_search backend health (recurring)

Backend is `ddgs` (免key) this session and worked well for KOL queries. If searches return
empty across even broad queries, the backend is rate-limited/down (see the parent skill's
notes) — do NOT conclude "no data / person untrackable"; the daily cron re-runs and fills真值.
