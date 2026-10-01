# When a scheduled job shares the repo with your interactive session

These dashboards are driven by a **daily cron that builds AND commits** in the same working copy you
edit interactively. A long feature session (fetch → render → visual QA → rebuild ≈ 30-60 min) will
eventually overlap a cron tick. Realized on Eco-and-Volatility-Checker: cron `daily 2026-08-20`
fired at 11:35 JST mid-session and did two damaging things at once.

## The two failure modes

### 1. `git add .` sweeps up your half-finished code and ships it
The cron commits with a blanket `git add .`, so it committed **uncommitted, mid-edit source** —
the new fetchers were in, but the rendering defects were not yet fixed. `git status` afterwards
showed only `src/dashboard.py` as modified, which is misleading: the other files weren't "clean",
they had been **committed for me** by a job I didn't run.

### 2. A cron build with failing fetches ships a DEGRADED page over a good one
That build's COMEX/Shanghai fetch failed, so live got 6 × `未就绪`, 75 polylines, 9,036 tooltips —
versus 0 / 140 / 18,759 from the healthy build. The 铁律 held (cache-fallback rendered `未就绪`,
**not** fabricated numbers), but the public page silently regressed.

## Detection — do this BEFORE trusting any acceptance number
```
git log --oneline -3            # did HEAD move to a commit you didn't author?
git show --stat <new-sha> | head
```
If HEAD advanced, **your `scratch/backups/` snapshot is no longer the right baseline.**

> Trap that cost real time: comparing my build against the backup showed tooltips 9,036 → 18,759,
> ~2× — which reads exactly like a duplicate-rendering bug. It wasn't. The *backup* was the anomaly
> (it was the cron's degraded output). **When an acceptance count moves alarmingly, first verify
> WHICH baseline you're holding, before hunting a bug in your own diff.**

## Proving your build is a strict superset (the argument that justifies pushing)
Compare degraded-live vs yours on integrity-bearing counts, not just bytes:
```
for k in '未就绪' '未找到' '<polyline' '<svg' 'data-tip=' 'part-title'; do
  echo "$k: live=$(grep -o "$k" /tmp/head_index.html|wc -l)  mine=$(grep -o "$k" docs/index.html|wc -l)"
done
```
PASS = `未就绪` strictly decreases (ideally to 0) and no chart/section count goes DOWN. Anchor counts
that stay equal (`sec-*` ids, `未找到`) are good evidence you added rather than displaced.

Don't stop at section anchors — a section can be present but hollow. Anchors matched 3/3 and 2/2
while the段 itself had 2 polylines vs 6 and 4 × `未就绪`. Diff **inside** the section slice:
```
i = h.find('sec-comex-shanghai'); seg = h[i:i+60000]
print(seg.count('<polyline'), seg.count('data-tip'), seg.count('未就绪'))
```

## Prove the cron didn't poison cached truth (P0 check)
A cron that ran with dead sources may have rewritten `data/*.json`. Never eyeball the head of the
file — the first 200 chars matched perfectly while a field differed. Walk it recursively:
```
import json, subprocess
head = json.loads(subprocess.run(['git','show','HEAD:data/<f>.json'],capture_output=True,text=True).stdout)
cur  = json.load(open('data/<f>.json'))
# recursive walk printing only differing leaf paths
```
Verdict here: the **only** difference was `fetched_at`; every value identical → cache clean, safe.
That recursive-diff result is what you report, not "looks the same".

## Reporting it to Chao
Surface the cron collision **unprompted** as part of the pre-push message, with: what cron committed,
that live is currently degraded, the superset evidence, and the semantic-diff proof the cached truth
survived. Frame the push as *also repairing the live regression* — that materially changes the
decision. Then still wait for explicit approval (push stays 不可逆 → needs a yes).

Also recommend the durable fix rather than just noting the incident: **the cron should `git add` an
explicit whitelist** (`data/ docs/ dashboard/`), never `git add .`, so an in-progress source edit can
never be auto-published. Offer it; don't unilaterally rewrite the cron.
