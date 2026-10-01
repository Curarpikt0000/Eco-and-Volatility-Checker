# Defect provenance & reporting language (how to describe a bug to Chao)

Companion to `dashboard-data-integrity-audit.md`. That file is about FINDING defects.
This one is about **describing them without triggering a false alarm** — and about the
git work you must do before you're entitled to describe them at all.

## The incident

Wrapping up a fix list, I wrote to Chao: *"⚠️ 线上目前仍是坏产物"* / *"线上现在是坏的"*.

His reply, immediate and alarmed:

> 什么意思？什么叫线上现在是坏的呀？
> 为什么是坏的？**在你做这个项目之前还是好的，怎么现在是坏的？**

He was right to be alarmed, and I was wrong to use the word. 坏了 asserts a **regression** —
something that worked, stopped working, and you are the recent change. That is the single
most expensive thing you can imply about a shipped artifact, and I implied it about two
defects that were **neither of them regressions**:

| Defect | True provenance | Honest phrasing |
|---|---|---|
| Drill-down modal empty for every entity | **I introduced it this session** — shipped the cards clickable while the embedded payload rendered `{}` | 「我新加的功能上线时半残」 |
| TIC chart showing Japan $1,186B | **Predates me by a week** — wrong source file wired the day the section was created | 「一个我发现并修好的历史遗留错值」 |

Neither is "something that worked got broken." One was a **new feature that reached prod
half-wired**; the other was a **latent error that shipped correct-looking from birth**.

## Rule: answer "did you break what was working?" before the user has to ask

That is the user's first question about any defect on a shared artifact. Volunteering the
provenance verdict costs one sentence. Making them ask costs their trust in the whole report.

## Establish provenance from git BEFORE characterizing anything

Do not reason from memory about when a bug appeared. Two cheap probes settle it:

```bash
# (1) When was this code path introduced? -S searches for commits that changed the string.
git log --oneline --all -S "TIC_MFH_HIST_URL" -- src/external_data.py | tail -3
git log -1 --format="%h %ad %s" --date=short <that-commit>
#   → 2026-08-14 feat(custody): 新增日本/中国分国别持有美债近10年折线(TIC MFH)
#     i.e. the section was BORN with the wrong source. Not a regression.

# (2) Did the wrong VALUE ship in earlier artifacts? Definitive for generated output.
for c in 1d82e5a 14837cb 56e6f78 d0187fd; do
  echo -n "$c: "
  git show $c:docs/index.html | grep -o '日本持有美债[^$]*\$[0-9,]*' | grep -o '\$[0-9,]*$'
done
#   → all four printed $1,186 — the error was in every version before my involvement.
```

The converse probe is just as decisive when the feature is yours:

```bash
git show <last-live-commit>:docs/index.html | grep -c 'kol-drill'
#   → 0.  The drill-down did not exist at all before this session,
#     so "broken" was impossible by construction; "incomplete" was the only accurate word.
```

Quote these in the report. "It predates me" is an assertion; a commit hash and a date is evidence
(论断锚具名数据 applies to claims about your own work too).

## Vocabulary

| Word | Use only when |
|---|---|
| **regression / 坏了** | You can point to a commit where it worked and a commit where it stopped |
| **incomplete / half-shipped / 半残** | A NEW feature of yours reached prod partly wired — **say you own it** |
| **pre-existing / latent / 历史遗留** | Wrong before you touched the area — give the introducing commit + date |
| **false alarm / 误报** | The pipeline is fine; a threshold or label was wrong (see the audit ref's two-verdicts table) |

Avoid bare 坏了 / broken / 挂了 on a shared artifact entirely. Always scope the claim to a
**named component** plus a **provenance verdict**: not "线上是坏的" but "线上的 KOL 弹层是空的
（我这次新加的功能没接完），另外美债数字是错的（8-14 建这个板块时就错了，跟我的改动无关）".

## A latent-defect corollary worth stating to the user

The TIC error survived a week unnoticed because **a new section's FIRST data has no historical
baseline to contradict it** — a wrong value simply looks like a value. That generalizes into a
real practice change, and it's worth telling the user as the takeaway rather than burying it:

> 新板块首次接入的数据最容易错也最难发现（没有历史基线可比，错值看起来就像正常值），
> 以后新接数据源第一次就要拿官方最新一期做交叉验证。

## When you get the wording wrong

Correct it explicitly and unprompted, in the same turn you realize it:
「我用词不准，吓着你了 — 道歉」, then show the git evidence, then restate the accurate version.
Chao accepted the corrected framing immediately. The damage was never the defects — it was the
ambiguity about who caused them.
