#!/usr/bin/env python3
"""名册加 short_name(显示用) + search_terms 改为人名(搜索用)。display_name 不动(join key)。
★5 个无人名条目: 人名经各自 Source 官网 bio 页核实(2026-09-25 web_extract)。
★其余带括号条目: short_name = 括号前部分。
★只改本地独有字段(sync 对已存在条目保留本地字段), 不增删任何 KOL。
"""
import json, re, shutil, sys
from datetime import datetime
REG = "/home/user/Projects/Eco-and-Volatility-Checker/data/kol_registry.json"
APPLY = "--apply" in sys.argv

# display_name 前缀 → (人名, Source 证据)
MANUAL = {
    "The Trends Research Institute": ("Gerald Celente", "trendsjournal.com/about-gerald-celente-2"),
    "VON GREYERZ AG": ("Egon von Greyerz", "vongreyerz.gold/about-us"),
    "Miles Franklin Precious Metals": ("Bill Holter", "milesfranklin.com/bill-holter"),
    "Double Duty Money Management": ("Rupal Bhansali", "doubledutymm.com/our-team"),
    "McAlvany Financial Group CEO": ("David McAlvany", "mcalvany.com/teams/david-s-mcalvany"),
}
BR = re.compile(r"[（(]")

reg = json.load(open(REG, encoding="utf-8"))
kols = reg["kols"]
changed = []
for k in kols:
    dn = (k.get("display_name") or "").strip()
    sn = None
    for pre, (name, _) in MANUAL.items():
        if dn.startswith(pre):
            sn = name; break
    if sn is None and BR.search(dn):
        sn = BR.split(dn)[0].strip()
    if not sn or sn == dn:
        continue
    old_st = list(k.get("search_terms") or [])
    # 旧 search_terms 若只是长 display_name 本身 → 替换为人名; 若有自定义别名 → 人名放首位, 删掉长串
    new_st = [sn] + [t for t in old_st if t and t != dn and t != sn and len(t) <= 40]
    changed.append((dn, sn, old_st, new_st))
    if APPLY:
        k["short_name"] = sn
        k["search_terms"] = new_st
        k["_short_name_note"] = "2026-09-25 显示/搜索用短名; display_name 保持 Notion 原值作 join key"

print("将修改 %d 人" % len(changed))
for dn, sn, o, n in changed:
    print("  %-26s ← %s" % (sn, dn[:56]))
    print("      search_terms: %s → %s" % ([x[:30] for x in o], n))
if APPLY:
    bak = REG + ".bak_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(REG, bak)
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n✓ 已写入; 备份 %s" % bak)
    # 读回校验
    r2 = json.load(open(REG, encoding="utf-8"))
    n_sn = sum(1 for k in r2["kols"] if k.get("short_name"))
    ids_before = {k["id"] for k in kols}
    ids_after = {k["id"] for k in r2["kols"]}
    print("  读回: short_name %d 人; 人数 %d → %d; id 集合一致=%s" % (
        n_sn, len(kols), len(r2["kols"]), ids_before == ids_after))
else:
    print("\n[预演] 加 --apply 生效")
