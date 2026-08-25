"""
apply_kol_channels.py — 把已复核的 YouTube 频道判定写回名册

## 数据来源链条（每一步都可追溯）
1. `scripts/kol_channel_probe.py` → YouTube 真实 API 观测（yt-dlp）
2. 6 个离线子 agent 判定哪个候选是本人 → `scratch/kol_enrich/judge2/b*_out.json`
3. **父层逐个 HTTP 探针复核**（含 2 个已知控制组）→ `judge2/verify.json`
   实测 52/52 通过、0 handle 不符、控制组正常
4. 本脚本写回 `data/kol_registry.json`

## ★ 名册铁律（AGENTS.md，Chao 2026-08-22 重申）
**SSOT = Notion「KOL List」DB，本 agent 绝不自行增删任何 KOL。**
本脚本**只给已有的人补采集字段**（youtube_channel_id / youtube_handle），
不新增人、不删除人、不改名字。这与「同步保护：本地独有采集配置保留不被覆盖」一致。

## 只写高可信
默认只应用 confidence=high 的判定。medium/low 落到 `_review` 文件供人工过目，
不进名册 —— 选错一个山寨号 = 每天抓错人的内容进日报，比留空危害大。

## 用法
    cd ~/Projects/Eco-and-Volatility-Checker
    .venv/bin/python scripts/apply_kol_channels.py --dry-run
    .venv/bin/python scripts/apply_kol_channels.py
    .venv/bin/python scripts/apply_kol_channels.py --include-medium   # 需人工确认后再用
"""
import argparse
import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "data", "kol_registry.json")
JUDGE = os.path.join(ROOT, "scratch", "kol_enrich", "judge2", "ALL.json")
VERIFY = os.path.join(ROOT, "scratch", "kol_enrich", "judge2", "verify.json")
REVIEW = os.path.join(ROOT, "scratch", "kol_enrich", "judge2", "_needs_review.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-medium", action="store_true")
    args = ap.parse_args()

    judged = json.load(open(JUDGE, encoding="utf-8"))
    # 复核结果：只接受父层探针验证通过的
    verified_ok = set()
    if os.path.exists(VERIFY):
        for rec in json.load(open(VERIFY, encoding="utf-8")):
            kid, cid, handle, status = rec[0], rec[1], rec[2], rec[3]
            if kid.startswith("__CTRL"):
                continue
            if status.startswith("OK") and "match=False" not in str(rec[4]):
                verified_ok.add((kid, cid))
    print(f"父层探针复核通过: {len(verified_ok)} 条")

    accept = {"high"} | ({"medium"} if args.include_medium else set())
    apply_list, review_list = [], []
    for r in judged:
        if not r.get("pick"):
            continue
        conf = r.get("confidence")
        if conf in accept and (r["id"], r["pick"]) in verified_ok:
            apply_list.append(r)
        else:
            why = ("未通过父层探针复核" if (r["id"], r["pick"]) not in verified_ok
                   else f"置信度 {conf}")
            review_list.append({**r, "_hold_reason": why})

    print(f"将写入名册: {len(apply_list)} 人 | 留待人工复核: {len(review_list)} 人")

    reg = json.load(open(REGISTRY, encoding="utf-8"))
    kols = reg["kols"] if isinstance(reg, dict) and "kols" in reg else reg
    idx = {k["id"]: k for k in (kols.values() if isinstance(kols, dict) else kols)}

    changed = skipped = 0
    for r in apply_list:
        k = idx.get(r["id"])
        if k is None:
            print(f"  ⚠️ {r['id']} 不在名册（可能已被 Notion 侧移除）→ 跳过")
            skipped += 1
            continue
        old = k.get("youtube_channel_id")
        if old and old != r["pick"]:
            # ★ 已有值且不同 → 不覆盖，交人工。本地独有采集配置受同步保护。
            print(f"  ⚠️ {r['id']} 已有频道 {old} ≠ 新判定 {r['pick']} → 保留原值，记入复核")
            review_list.append({**r, "_hold_reason": f"与既有值冲突(原 {old})"})
            skipped += 1
            continue
        if old == r["pick"]:
            continue
        if not args.dry_run:
            k["youtube_channel_id"] = r["pick"]
            if r.get("handle"):
                k["youtube_handle"] = r["handle"]
            k["_yt_source"] = "probe+judge 2026-08-25 (parent-verified)"
        changed += 1
        print(f"  ✓ {r['id']:32} → {r.get('handle') or r['pick']}")

    print(f"\n{'[dry-run] 将' if args.dry_run else '已'}更新 {changed} 人，跳过 {skipped} 人")

    if args.dry_run:
        return

    # 备份后写回（Chao 铁律：改前必备份）
    bak = REGISTRY + "." + datetime.now().strftime("%Y%m%d_%H%M%S") + ".bak"
    shutil.copy2(REGISTRY, bak)
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    print(f"名册已写入（备份 {os.path.basename(bak)}）")

    with open(REVIEW, "w", encoding="utf-8") as f:
        json.dump(review_list, f, ensure_ascii=False, indent=1)
    print(f"待人工复核 {len(review_list)} 条 → {REVIEW}")

    # 读回验证
    reg2 = json.load(open(REGISTRY, encoding="utf-8"))
    k2 = reg2["kols"] if isinstance(reg2, dict) and "kols" in reg2 else reg2
    lst = list(k2.values()) if isinstance(k2, dict) else k2
    n_yt = sum(1 for x in lst if x.get("youtube_channel_id"))
    print(f"读回验证：名册 {len(lst)} 人，其中 {n_yt} 人有 youtube_channel_id")


if __name__ == "__main__":
    main()
