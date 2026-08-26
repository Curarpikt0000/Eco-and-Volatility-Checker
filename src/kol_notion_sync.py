"""Notion ⇄ KOL SSOT 同步器。

三点对应 (Chao 2026-08-26):
    data/kol_store.sqlite  ──►  Notion
       (唯一真相源)              ├─ KOL List (一人一行, 只回填 Source 列)
                                └─ KOL Opinions (一观点一行, 承载一年全部历史)

铁律:
  - KOL List 的名册字段(编号/KOL/领域/背景/方向/最新观点/最新观点日期)由 Chao 与
    另一 agent 维护, 本模块【只写 Source 一列】, 绝不触碰其余字段。
  - 一切 URL 均来自 store 中 source_status='ok' 的真实记录, 拿不到就跳过, 绝不编造。
  - 幂等: 已写入的 opinion 记录 notion_page_id, 重跑只更新变化字段。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import kol_store as ks  # noqa: E402

KOL_LIST_DB = "35947eb5-fd3c-800d-b852-cef31f9de6a5"   # 名册 (Chao 的 SSOT)
PROP_SOURCE = "Source"
PROP_NAME = "KOL / 机构"


def _env(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, ".env")
    env = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip()
    return env


class Notion:
    def __init__(self, token: str | None = None, version: str | None = None):
        e = _env()
        self.tok = token or e["NOTION_TOKEN"]
        self.ver = version or e.get("NOTION_VERSION", "2022-06-28")

    def call(self, path: str, method: str = "GET", body: dict | None = None,
             retries: int = 4) -> dict:
        url = "https://api.notion.com/v1" + path
        data = json.dumps(body).encode() if body is not None else None
        for i in range(retries):
            req = urllib.request.Request(
                url, method=method, data=data,
                headers={"Authorization": f"Bearer {self.tok}",
                         "Notion-Version": self.ver,
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.load(r)
            except urllib.error.HTTPError as ex:
                msg = ex.read()[:400].decode("utf8", "ignore")
                if ex.code in (429, 502, 503, 504) and i < retries - 1:
                    time.sleep(1.5 * (i + 1))
                    continue
                raise RuntimeError(f"{ex.code} {msg}") from None
            except Exception:
                if i < retries - 1:
                    time.sleep(1.5 * (i + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    def query_all(self, db: str) -> list:
        out, cur = [], None
        while True:
            b = {"page_size": 100}
            if cur:
                b["start_cursor"] = cur
            r = self.call(f"/databases/{db}/query", "POST", b)
            out += r["results"]
            if not r.get("has_more"):
                return out
            cur = r["next_cursor"]


# ── 文本工具 ───────────────────────────────────────────────────────

def plain(prop) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("rich_text", "title"):
        return "".join(x["plain_text"] for x in prop[t])
    if t == "url":
        return prop.get("url") or ""
    if t == "date":
        return (prop.get("date") or {}).get("start", "") or ""
    if t == "select":
        return (prop.get("select") or {}).get("name", "") or ""
    return ""


def rt(s: str, limit: int = 2000) -> list:
    s = (s or "")[:limit]
    return [{"type": "text", "text": {"content": s}}] if s else []


# ── A. KOL List: 只回填 Source 列 ──────────────────────────────────

def sync_kol_list_source(dry_run: bool = True, limit: int | None = None) -> dict:
    """把 store 中每人【最新一条带 URL】的观点链接写进 KOL List 的 Source 列。

    严格匹配: 精确同名 或 归一化(去括号/去斜杠后缀)后唯一命中。
    模糊命中一律跳过 —— 曾把机构(Goldman Sachs)的链接误贴到个人(Lina Thomas)身上。
    """
    n = Notion()
    latest = ks.latest_with_source()
    by_norm: dict = {}
    for name in latest:
        by_norm.setdefault(ks.slugify(name), []).append(name)

    rows = n.query_all(KOL_LIST_DB)
    plan, unmatched, filled = [], [], 0
    for r in rows:
        nm = plain(r["properties"].get(PROP_NAME))
        cur_src = plain(r["properties"].get(PROP_SOURCE))
        hit = None
        if nm in latest:
            hit = nm
        else:
            c = by_norm.get(ks.slugify(nm), [])
            if len(c) == 1:
                hit = c[0]
        if not hit:
            unmatched.append(nm)
            continue
        url = latest[hit]["url"]
        if cur_src == url:
            filled += 1
            continue
        plan.append({"page": r["id"], "notion_name": nm, "local": hit,
                     "url": url, "date": latest[hit]["date"], "old": cur_src})

    if limit:
        plan = plan[:limit]
    res = {"rows": len(rows), "to_write": len(plan), "already_ok": filled,
           "unmatched": unmatched, "written": 0, "errors": []}
    if dry_run:
        res["preview"] = plan[:5]
        return res

    for p in plan:
        try:
            n.call(f"/pages/{p['page']}", "PATCH",
                   {"properties": {PROP_SOURCE: {"url": p["url"]}}})
            res["written"] += 1
            time.sleep(0.34)          # Notion 官方限速 3 req/s
        except Exception as ex:
            res["errors"].append(f"{p['notion_name']}: {ex}")
    return res


def verify_kol_list_source() -> dict:
    """写后读回: 统计 Source 列真实填充率, 并抽样校验 URL 与 store 一致。"""
    n = Notion()
    latest = ks.latest_with_source()
    rows = n.query_all(KOL_LIST_DB)
    filled = mismatch = 0
    samples = []
    for r in rows:
        nm = plain(r["properties"].get(PROP_NAME))
        src = plain(r["properties"].get(PROP_SOURCE))
        if src:
            filled += 1
            if len(samples) < 5:
                samples.append((nm[:30], src[:70]))
            hit = nm if nm in latest else None
            if hit and latest[hit]["url"] != src:
                mismatch += 1
    return {"rows": len(rows), "source_filled": filled,
            "source_empty": len(rows) - filled, "mismatch": mismatch,
            "samples": samples}


# ── B. KOL 观点历史库 (SSOT 投影): 一观点一行, store 全量 ──────────
#
# ★★2026-08-26 双 DB 分工铁律 (Chao 拍板, 不可违反):
#   本项目【同时存在两个 KOL 观点 Notion 表, 由两个 agent 各自维护, 互不合并】:
#
#     ┌ DB_KOL_VIEWS  3c847eb5-...-d8d50295ce1c 「KOL 每日观点」
#     │   owner = 另一 agent 的 src/kol_notion.py (daily cron 步骤 3.9)
#     │   粒度 = 当日增量, 方案A(跳过 未找到/thin/none)
#     │   ★本模块【绝对禁止】读写它。
#     │
#     └ OPINIONS_DB  3c847eb5-...-f4effae77417 「KOL 观点历史库 (SSOT)」
#         owner = 本模块, 投影 data/kol_store.sqlite 全量历史(2025-01 起)
#
#   历史教训: 2026-08-26 本模块曾误把 93 行写进 DB_KOL_VIEWS, 已全部 archived 撤回。
#   下方 _assert_not_foreign() 是硬闸门, 任何写操作前必过。

OPINIONS_DB = "3c847eb5-fd3c-81b7-a827-f4effae77417"   # 本模块独占
FOREIGN_DBS = {
    "3c847eb5-fd3c-813a-a975-d8d50295ce1c",            # 他人的「KOL 每日观点」
    "35947eb5-fd3c-800d-b852-cef31f9de6a5",            # KOL List 名册(只准改 Source)
}


def _assert_not_foreign(db_id: str):
    """硬闸门: 绝不允许本模块向他人拥有的 DB 写入观点行。"""
    if (db_id or "").replace("-", "") in {x.replace("-", "") for x in FOREIGN_DBS}:
        raise RuntimeError(
            f"REFUSED: {db_id} 属于其他 agent, 本模块禁止写入 (双 DB 分工铁律)")


# store 列 → Notion 属性
OP_PROPS = {
    "title": "记录", "kol": "KOL", "sector": "领域", "date": "日期",
    "direction": "方向", "comments": "一句话观点", "targets": "标的",
    "detail": "深度摘要", "source": "来源链接",
    "src_status": "出处状态", "origin": "来源链路", "uid": "UID",
}


def _op_payload(r: dict) -> dict:
    """store 行 → Notion properties。Source 为空时留空但不编造。"""
    p = {
        OP_PROPS["title"]: {"title": rt(f"{r['date']}｜{r['kol_name']}")},
        OP_PROPS["kol"]: {"rich_text": rt(r["kol_name"])},
        OP_PROPS["date"]: {"date": {"start": r["date"]}},
        OP_PROPS["comments"]: {"rich_text": rt(r["comments"])},
        OP_PROPS["targets"]: {"rich_text": rt(r["targets"])},
        OP_PROPS["detail"]: {"rich_text": rt(r["detail"])},
        OP_PROPS["uid"]: {"rich_text": rt(r["uid"])},
        OP_PROPS["src_status"]: {"select": {"name": r["source_status"]}},
    }
    if r["sector"]:
        p[OP_PROPS["sector"]] = {"select": {"name": r["sector"][:100]}}
    if r["direction"]:
        p[OP_PROPS["direction"]] = {"select": {"name": r["direction"][:100]}}
    if r["origin"]:
        p[OP_PROPS["origin"]] = {"select": {"name": r["origin"][:100]}}
    if (r["source_url"] or "").startswith("http"):
        p[OP_PROPS["source"]] = {"url": r["source_url"]}
    return p


def sync_opinions(dry_run: bool = True, limit: int | None = None,
                  since: str = "", batch_report: int = 200) -> dict:
    """把 store 中的观点全量投影到【本模块独占的】历史库。

    幂等键: UID (= store 主键), 与 store 一一对应, 天然防重。
    """
    _assert_not_foreign(OPINIONS_DB)
    n = Notion()
    conn = ks.connect()
    q = "SELECT * FROM opinion"
    args = []
    if since:
        q += " WHERE date>=?"
        args.append(since)
    q += " ORDER BY date DESC"
    rows = [dict(x) for x in conn.execute(q, args).fetchall()]
    conn.close()

    existing = {}
    for r in n.query_all(OPINIONS_DB):
        u = plain(r["properties"].get("UID"))
        if u:
            existing[u] = {"id": r["id"],
                           "src": plain(r["properties"].get("来源链接"))}

    todo, patch_src = [], []
    for r in rows:
        hit = existing.get(r["uid"])
        if hit is None:
            todo.append(r)
        elif not hit["src"] and (r["source_url"] or "").startswith("http"):
            patch_src.append((hit["id"], r["source_url"], r["uid"]))

    if limit:
        todo = todo[:limit]
    res = {"store_rows": len(rows), "notion_rows": len(existing),
           "to_create": len(todo), "to_patch_source": len(patch_src),
           "created": 0, "patched": 0, "errors": []}
    if dry_run:
        res["preview"] = [{"kol": r["kol_name"], "date": r["date"],
                           "src": r["source_url"][:60]} for r in todo[:5]]
        return res

    for i, r in enumerate(todo, 1):
        try:
            pg = n.call("/pages", "POST",
                        {"parent": {"database_id": OPINIONS_DB},
                         "properties": _op_payload(r)})
            ks.set_notion_page(r["uid"], pg["id"])
            res["created"] += 1
            time.sleep(0.34)
        except Exception as ex:
            res["errors"].append(f"{r['kol_name']} {r['date']}: {ex}")
            if len(res["errors"]) > 30:
                res["aborted"] = "错误过多, 提前中止"
                break
        if i % batch_report == 0:
            print(f"  ... 已创建 {res['created']}/{len(todo)}", flush=True)

    for pid, url, uid in patch_src:
        try:
            n.call(f"/pages/{pid}", "PATCH",
                   {"properties": {OP_PROPS["source"]: {"url": url}}})
            ks.set_notion_page(uid, pid)
            res["patched"] += 1
            time.sleep(0.34)
        except Exception as ex:
            res["errors"].append(f"patch {pid}: {ex}")
    return res


def verify_opinions() -> dict:
    """三点对账: store 条数 vs 本模块历史库行数 vs 出处填充率。"""
    n = Notion()
    conn = ks.connect()
    st = ks.stats(conn)
    conn.close()
    rows = n.query_all(OPINIONS_DB)
    with_src = sum(1 for r in rows if plain(r["properties"].get("来源链接")))
    uids = {plain(r["properties"].get("UID")) for r in rows}
    return {"store_opinions": st["opinions"], "notion_rows": len(rows),
            "gap": st["opinions"] - len(rows),
            "unique_uid_rows": len(uids - {""}),
            "dup_rows": len(rows) - len(uids - {""}),
            "store_source_ok": st["source_ok"],
            "notion_source_filled": with_src,
            "date_range_store": f"{st['date_min']}~{st['date_max']}"}


if __name__ == "__main__":
    import pprint
    dry = "--write" not in sys.argv
    if "--opinions" in sys.argv:
        pprint.pprint(sync_opinions(dry_run=dry))
    elif "--verify" in sys.argv:
        pprint.pprint(verify_opinions())
    else:
        pprint.pprint(sync_kol_list_source(dry_run=dry))