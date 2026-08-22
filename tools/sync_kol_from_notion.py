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
    for r in notion:
        key = norm(r["KOL / 机构"])
        if key in lmap:
            exact[r["KOL / 机构"]] = lmap[key]
            used.add(key)

    def match_local(name):
        if name in exact:
            return exact[name]
        nk = norm(name)
        cands = [(lk, lv) for lk, lv in lmap.items()
                 if lk not in used and len(lk) > 4 and lk in nk]
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
            hit["_sot"] = "Notion KOL List (mirror)"
            new_reg.append(hit)
            kept += 1
        else:
            new_reg.append({
                "id": slugify(name),
                "display_name": name,
                "notion_select_name": name,
                "domain": r.get("领域", ""),
                "notion_domain": r.get("领域", ""),
                "notion_list_num": r.get("编号"),
                "institution": r.get("核心背景 / 身份", ""),
                "bio": r.get("核心背景 / 身份", ""),
                "focus": r.get("主要分析方向 / 监控维度", ""),
                "search_terms": [name],
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
