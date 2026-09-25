#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notion「KOL List」→ data/kol_registry.json 单向镜像同步。

★ 铁律(Chao 2026-08-22 明确):
    Notion KOL List DB 是**唯一真源**。GitHub 侧名册只是它的镜像副本。
    本 agent **绝不自行增删** KOL —— 增删一律在 Notion 侧做, 这里只负责同步。
    (背景: 2026-08-20 我自行往名册加了 23 人未同步 Notion, 导致两边不一致。)

源:
    page  KOL Research Daily Update
          https://app.notion.com/p/KOL-Research-Daily-Update-31447eb5fd3c8064a531c43b177cdc41
    DB    KOL List = 35947eb5-fd3c-800d-b852-cef31f9de6a5

同步语义:
    Notion 有 + 本地有  → 保留本地条目全部字段(search_terms/source_url/youtube_channel_id
                          等采集配置是本地独有的, 绝不能被覆盖丢失), 仅刷新 Notion 侧字段。
    Notion 有 + 本地无  → 新建条目(仅含 Notion 能提供的字段; search_terms 留空待补)。
    Notion 无 + 本地有  → 移出名册, 并落盘到 data/kol_removed_<date>.json 留痕,
                          **绝不静默丢失**(其 backfill 历史文件也一律保留不删)。

用法:
    python3 tools/sync_kol_from_notion.py           # 预演, 只打印差异不写盘
    python3 tools/sync_kol_from_notion.py --apply   # 实际写入
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data", "kol_registry.json")
ENV = os.path.join(ROOT, ".env")
DB_ID = "35947eb5-fd3c-800d-b852-cef31f9de6a5"
NOTION_VER = "2022-06-28"


def _token():
    for ln in open(ENV, encoding="utf-8"):
        m = re.match(r"\s*NOTION_TOKEN\s*=\s*(.+)", ln)
        if m:
            return m.group(1).strip().strip("\"'")
    raise SystemExit("✗ .env 中找不到 NOTION_TOKEN")


def fetch_notion():
    tok = _token()
    h = {"Authorization": f"Bearer {tok}", "Notion-Version": NOTION_VER,
         "Content-Type": "application/json"}
    rows, cur = [], None
    while True:
        body = json.dumps({"page_size": 100, **({"start_cursor": cur} if cur else {})}).encode()
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{DB_ID}/query",
            data=body, headers=h, method="POST")
        r = json.load(urllib.request.urlopen(req, timeout=45))
        rows += r["results"]
        if not r.get("has_more"):
            break
        cur = r["next_cursor"]

    out = []
    for p in rows:
        rec = {}
        for k, v in p.get("properties", {}).items():
            t = v.get("type")
            if t == "title":
                rec[k] = "".join(x.get("plain_text", "") for x in v["title"]).strip()
            elif t == "rich_text":
                rec[k] = "".join(x.get("plain_text", "") for x in v["rich_text"]).strip()
            elif t == "select":
                rec[k] = (v["select"] or {}).get("name", "")
            elif t == "number":
                rec[k] = v["number"]
            elif t == "checkbox":
                rec[k] = v["checkbox"]
        if rec.get("KOL / 机构"):
            out.append(rec)
    return out


def norm(s):
    return re.sub(r"[\s·・/｜|（）()、,，.。\-]+", "", (s or "").lower())


def slugify(s):
    t = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return t or re.sub(r"\W+", "", s)[:24]


# ★2026-09-08(Chao 报「Goldman Sachs 是机构不是 KOL, 我在 Notion 取消了但
#   dashboard 还在」): 8/22 为 Nomi Prins 修的模糊匹配坑, 换个主角又踩了一次。
#
#   当时的修法是「模糊只认 本地名 ⊂ Notion 名 单方向 + 取最短候选」, 方向没错,
#   但漏了一类: **本地名本身就是纯机构名**。Notion 里有
#       「Lina Thomas（Goldman Sachs Research 高级大宗商品分析师…）」
#       「Nomi Prins（… 前 Goldman Sachs MD）」
#   本地那条纯机构条目「Goldman Sachs」规范化后是 goldmansachs, 确实是这两个长串
#   的子串 → 被判定为「Lina Thomas 那行的本地对应」而保留, 于是 Notion 明明删了,
#   本地却报「移出 0」, 卡片继续留在 dashboard 上。
#
#   正解: 纯机构名不参与模糊匹配, 只允许精确匹配。判据 = 无「人名（机构）」结构
#   且命中机构词表 —— 真人条目要么带括号后缀, 要么不含这些词。
_INST_WORDS = (
    "sachs", "stanley", "citi", "ubs", "jpmorgan", "j p morgan", "barclays",
    "nomura", "hsbc", "deutsche", "santander", "bnp", "socgen", "wells fargo",
    "bank of", "foundation", "institute", "research", "capital", "securities",
    "asset management", "partners", "associates", "consulting", "group",
)


def is_pure_institution(name):
    """本地条目是否为「纯机构名」(而非「人名（机构后缀）」)。

    纯机构名不得参与模糊匹配, 否则会把 Notion 里任何带该机构后缀的真人行吃掉,
    导致该机构条目被永久保留、Notion 侧的删除同步不过来。
    """
    n = (name or "").strip()
    if not n:
        return False
    if "（" in n or "(" in n:      # 「人名（机构 …）」结构 → 是真人
        return False
    low = re.sub(r"[^a-z ]+", " ", n.lower())
    return any(w in low for w in _INST_WORDS)


def main(apply_it):
    notion = fetch_notion()
    reg = json.load(open(REG, encoding="utf-8"))
    is_list = isinstance(reg, list)
    local = reg if is_list else reg.get("kols", reg)

    lmap = {}
    for k in local:
        n = k.get("display_name", "")
        if n:
            lmap[norm(n)] = k

    # ★2026-08-22 修复匹配 bug:
    #   Notion 名常带括号后缀(如「Nomi Prins（… 前 Goldman Sachs MD）」)。
    #   若只做双向子串匹配, 本地「Goldman Sachs」会抢先匹配掉这一行,
    #   导致真正的 Nomi Prins 被误判为"Notion 无" → 错误移出。
    #   正解: ①先全量精确匹配, 已配对的本地条目不再参与模糊 ②模糊只认
    #   「本地名 ⊂ Notion 名」这一个方向(Notion 名更长带后缀), 且取最短本地名,
    #   避免长 Notion 串误吞短的无关本地名。
    used = set()
    exact = {}
    # ★2026-09-25(Chao: 「KOL 都是人, 机构只是备注」→ Notion 5 行改名):
    #   只按名字匹配时, Notion 侧改名 = 「移出旧人 + 新建新人」, id / 历史 / 快照 join 全断。
    #   Notion「编号」是行的稳定身份 → **先按编号匹配**, 编号相同名字不同即视为改名:
    #   保留本地条目(id/search_terms/short_name 等本地字段), 只换 display_name,
    #   旧名记进 _prev_display_names, 并在 --apply 时迁移派生数据里的 kol 字段(见 migrate_renames)。
    renames = []
    by_num = {}
    for k in local:
        n = k.get("notion_list_num")
        if n:
            by_num.setdefault(str(n), []).append(k)
    for r in notion:
        n = str(r.get("编号") or "")
        cand = by_num.get(n) or []
        if len(cand) != 1:
            continue
        lk = cand[0]
        key_old = norm(lk.get("display_name", ""))
        if key_old in used:
            continue
        new_name = r["KOL / 机构"]
        old_name = lk.get("display_name", "")
        # 只有「新旧名互不包含」才算真改名。本地名本来就常是 Notion 名去掉后缀的短版
        # (如「Craig Hamilton-Parker」⊂「Craig Hamilton-Parker（英国灵媒…）」), 那由下方
        # 既有的名字匹配处理, 这里不碰 —— 否则会把几十个正常行误判成改名。
        no, nn = norm(old_name), norm(new_name)
        if old_name == new_name or (no and (no in nn or nn in no)):
            continue
        renames.append((old_name, new_name))
        prev = lk.setdefault("_prev_display_names", [])
        if old_name and old_name not in prev:
            prev.append(old_name)
        lk["display_name"] = new_name
        lk["notion_select_name"] = new_name
        exact[new_name] = lk
        used.add(key_old)
    for r in notion:
        if r["KOL / 机构"] in exact:
            continue
        key = norm(r["KOL / 机构"])
        if key in lmap:
            exact[r["KOL / 机构"]] = lmap[key]
            used.add(key)

    def match_local(name):
        if name in exact:
            return exact[name]
        nk = norm(name)
        # ★2026-09-08: 纯机构名(如「Goldman Sachs」)不参与模糊 —— 否则它会吃掉
        #   Notion 里任何带该机构后缀的真人行, 使 Notion 侧的删除永远同步不过来。
        cands = [(lk, lv) for lk, lv in lmap.items()
                 if lk not in used and len(lk) > 4 and lk in nk
                 and not is_pure_institution(lv.get("display_name", ""))]
        if not cands:
            return None
        lk, lv = min(cands, key=lambda x: len(x[0]))
        used.add(lk)
        return lv

    new_reg, added, kept, matched_keys = [], [], 0, set()
    for r in notion:
        name = r["KOL / 机构"]
        hit = match_local(name)
        if hit:
            matched_keys.add(norm(hit.get("display_name", "")))
            # 保住本地采集配置, 只刷新 Notion 侧字段
            hit["notion_domain"] = r.get("领域", "")
            hit["notion_list_num"] = r.get("编号")
            if r.get("核心背景 / 身份"):
                hit["institution"] = r["核心背景 / 身份"]
            if r.get("主要分析方向 / 监控维度"):
                hit["focus"] = r["主要分析方向 / 监控维度"]
            hit["active"] = True
            # ★2026-09-25: Notion「KOL / 机构」可能只填机构介绍或「人名（长简介）」。
            #   short_name/search_terms 是本地独有字段(本分支保留不覆盖);
            #   但若 search_terms 仍等于整段长串, 自动收成括号前人名, 避免拿百字简介当搜索词。
            _dn = hit.get("display_name", "")
            if not hit.get("short_name") and re.search(r"[（(]", _dn):
                hit["short_name"] = re.split(r"[（(]", _dn)[0].strip()
            if hit.get("search_terms") in ([_dn], [name]) and hit.get("short_name"):
                hit["search_terms"] = [hit["short_name"]]
            hit["_sot"] = "Notion KOL List (mirror)"
            new_reg.append(hit)
            kept += 1
        else:
            _sn = re.split(r"[（(]", name)[0].strip() or name
            new_reg.append({
                "id": slugify(name),
                "display_name": name,
                "short_name": _sn,
                "notion_select_name": name,
                "domain": r.get("领域", ""),
                "notion_domain": r.get("领域", ""),
                "notion_list_num": r.get("编号"),
                "institution": r.get("核心背景 / 身份", ""),
                "bio": r.get("核心背景 / 身份", ""),
                "focus": r.get("主要分析方向 / 监控维度", ""),
                "search_terms": [_sn],
                "active": True,
                "added_date": datetime.now().strftime("%Y-%m-%d"),
                "_sot": "Notion KOL List (mirror)",
                "_note": "由 Notion 同步新建; search_terms 仅含姓名, 可后续在本地补充别名",
            })
            added.append(name)

    removed = [k for k in local if norm(k.get("display_name", "")) not in matched_keys]

    print(f"Notion: {len(notion)} 人 | 本地原有: {len(local)} 人 → 同步后: {len(new_reg)} 人\n")
    print(f"● 保留并刷新: {kept}")
    print(f"● 新建(Notion 有本地无): {len(added)}")
    for n in added:
        print("    +", n)
    print(f"● 移出(本地有 Notion 无): {len(removed)}")
    for k in removed:
        print("    -", k.get("display_name"))
    print(f"● 改名(同编号, Notion 侧改了名字): {len(renames)}")
    for o, n in renames:
        print(f"    ~ {o[:40]}  →  {n[:60]}")

    if not apply_it:
        print("\n[预演] 未写盘。加 --apply 生效。")
        return 0

    if removed:
        rp = os.path.join(ROOT, "data", f"kol_removed_{datetime.now():%Y%m%d}.json")
        json.dump({"removed_date": datetime.now().strftime("%Y-%m-%d"),
                   "reason": "不在 Notion KOL List(唯一真源)中; backfill 历史文件一律保留未删",
                   "count": len(removed), "kols": removed},
                  open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n✓ 移出条目留痕: {rp}")

    if is_list:
        json.dump(new_reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        reg["kols"] = new_reg
        json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ 已写入 {REG} ({len(new_reg)} 人)")
    if renames:
        migrate_renames(renames)
    return 0


def migrate_renames(renames):
    """改名后把派生数据里 kol == 旧名 的字段改成新名, 使快照/历史/变化继续 join 到同一人。
    只动 key 恰好为 "kol" 且值与旧名完全相等的字段; 迁移前整文件备份到 data/.rename_bak/。"""
    import glob, shutil
    mp = dict(renames)
    bak_dir = os.path.join(ROOT, "data", ".rename_bak", datetime.now().strftime("%Y%m%d_%H%M%S"))
    files = [os.path.join(ROOT, "data", "kol_independent.json")]
    files += glob.glob(os.path.join(ROOT, "data", "kol", "daily", "*.json"))
    files += glob.glob(os.path.join(ROOT, "data", "daily", "*.json"))
    files += glob.glob(os.path.join(ROOT, "data", "kol", "backfill", "*.json"))
    total = 0
    for f in files:
        try:
            raw = open(f, encoding="utf-8").read()
        except Exception:
            continue
        if not any(o in raw for o in mp):
            continue
        d = json.loads(raw)
        cnt = [0]

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "kol" and isinstance(v, str) and v in mp:
                        o[k] = mp[v]
                        cnt[0] += 1
                    else:
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
        if cnt[0]:
            os.makedirs(bak_dir, exist_ok=True)
            shutil.copy2(f, os.path.join(bak_dir, os.path.basename(os.path.dirname(f)) + "__" + os.path.basename(f)))
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            total += cnt[0]
            print(f"  迁移 {os.path.relpath(f, ROOT)}: {cnt[0]} 处")
    print(f"✓ 改名迁移完成: {total} 处 kol 字段(备份 {os.path.relpath(bak_dir, ROOT)})")


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
