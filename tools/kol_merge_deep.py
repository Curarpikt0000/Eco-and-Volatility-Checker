#!/usr/bin/env python3
"""把 scratch/kol_deep_<date>/out/<id>.json 合并进 data/kol_independent.json + 当日快照 + kol_store。

★2026-09-28 立（Chao 同意「cron 改为全量」）。由 ~/.hermes/scripts/eco_vol_kol_prefetch.sh 调用，
  也可手动跑:  .venv/bin/python tools/kol_merge_deep.py [YYYY-MM-DD]

规则:
- 名册 active 全部人都出现在 all 里；本轮没抓到的人沿用上次条目(date 保留旧值，一眼可辨未刷新)。
- 转向判定按「大类」(多/空/中性/混合)比较，不按原话逐字比 —— 逐字比会把措辞变化都算成转向。
  上次是「混合」或任一方是「未找到」时不计转向。
- 只把今天这份快照写进 kol_store(不回扫整个 daily 目录，避免顺带灌入历史快照)。
- 退出码: 0 成功；2 今日产物不足(<50% 名册)→ 不覆盖 kol_independent.json。
"""
import glob
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

D = sys.argv[1] if len(sys.argv) > 1 else os.popen("date +%F").read().strip()
BASE = os.path.join(ROOT, "scratch", f"kol_deep_{D}")
OUT = os.path.join(BASE, "out")
IND = os.path.join(ROOT, "data", "kol_independent.json")


def coarse(s):
    s = s or ""
    if "未找到" in s:
        return "未找到"
    b = "看多" in s or "偏多" in s
    e = "看空" in s or "偏空" in s
    return "多" if b and not e else "空" if e and not b else "混合" if b and e else "中性"


def main():
    active = [k for k in json.load(open(os.path.join(ROOT, "data", "kol_registry.json")))["kols"]
              if k.get("active")]
    fresh, bad = {}, []
    for f in glob.glob(os.path.join(OUT, "*.json")):
        try:
            fresh[os.path.basename(f)[:-5]] = json.load(open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad.append(f"{os.path.basename(f)}: {e}")
    hit = [k for k in active if k["id"] in fresh]
    if len(hit) < len(active) * 0.5:
        print(f"MERGE-ABORT 今日产物 {len(hit)}/{len(active)} 不足一半, 不覆盖 kol_independent.json")
        return 2

    shutil.copy(IND, os.path.join(BASE, "kol_independent.before.json"))
    prev = {x.get("kol"): x for x in json.load(open(IND, encoding="utf-8")).get("all", [])}
    rows, ch, miss = [], [], []
    for k in active:
        name = k["display_name"]
        sec = k.get("domain") or k.get("notion_domain") or ""
        r = fresh.get(k["id"])
        if not r:
            miss.append(name)
            rows.append(prev.get(name) or {"kol": name, "sector": sec, "direction": "未找到",
                                            "targets": "", "comments": "", "detail": "",
                                            "detail_status": "none", "sources": [], "date": D})
            continue
        r["kol"], r["sector"], r["date"] = name, sec, D
        rows.append(r)
        p = prev.get(name)
        if p:
            a, b = coarse(p.get("direction")), coarse(r.get("direction"))
            if a != b and "未找到" not in (a, b) and a != "混合":
                ch.append({"kol": name, "sector": sec, "prev_dir": p.get("direction", ""),
                           "new_dir": r.get("direction", ""), "prev_date": p.get("date", ""),
                           "date": D, "comments": r.get("comments", ""),
                           "targets": r.get("targets", ""), "detail": r.get("detail", "")})
    json.dump({"date": D, "all": rows, "changes": ch}, open(IND, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    import external_data as e
    snap = e.save_kol_daily_snapshot()
    import kol_store as ks
    tmp = tempfile.mkdtemp()
    shutil.copy(snap, tmp)
    res = ks.ingest_daily_dir(tmp)
    shutil.rmtree(tmp, ignore_errors=True)

    st = {}
    for r in rows:
        if r.get("date") == D:
            st[r.get("detail_status")] = st.get(r.get("detail_status"), 0) + 1
    print(f"MERGE-OK {D} 名册 {len(active)} | 今日抓到 {len(hit)} | 沿用旧条目 {len(miss)} | "
          f"大类转向 {len(ch)} | 质量 {st} | store {res}")
    if miss:
        print("  未刷新:", "、".join(m.split("（")[0] for m in miss))
    if bad:
        print("  坏文件:", bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
