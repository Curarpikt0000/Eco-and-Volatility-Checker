"""KOL 观点统一真相源 (SSOT).

设计目标 (Chao 2026-08-26):
  过去三条链路各写各的 —— data/kol/backfill/*.json (历史回填)、
  data/kol/daily/*.json (每日快照)、scratch/*/out/*.json (新增 KOL 一次性回填),
  只在 dashboard 渲染时于内存合并, 导致:
    - 新增 KOL 必须手工转格式才能进主库
    - Notion 完全不在这条链上
    - 出处(source)填充率无人统计
  本模块把三者收敛成【唯一】写入口 + 唯一存储:

      每日 crawl ─┐
      历史 backfill ─┼→ upsert() → data/kol_store.sqlite ─┬→ dashboard
      新人回填 ─┘        (唯一真相源)                      ├→ kol_store_export.json (进 git)
                                                          └→ Notion (幂等 upsert)

存储粒度: 一观点一行 (raw, 无损)。
  uid = sha1(kol_id | date | direction | comments[:120])
  同一句话连跑 N 天 → N 行 raw, 由 full_history() 在读取时折叠成区间,
  与旧 kol_full_history() 行为一致, 但原始数据不丢。

幂等保证:
  - 同 uid 重复写入不产生新行
  - 空值绝不覆盖已有真值 (skip_none)
  - origin 优先级: backfill/manual > daily (前者带 source 原文链接)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
DATA_DIR = os.path.join(ROOT, "data")
STORE_PATH = os.path.join(DATA_DIR, "kol_store.sqlite")
EXPORT_PATH = os.path.join(DATA_DIR, "kol_store_export.json")

BACKFILL_DIR = os.path.join(DATA_DIR, "kol", "backfill")
DAILY_DIR = os.path.join(DATA_DIR, "kol", "daily")

# origin 优先级: 数字大者胜出(可覆盖对方的空字段)
ORIGIN_RANK = {"manual": 3, "backfill": 2, "daily": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS opinion (
    uid            TEXT PRIMARY KEY,
    kol_id         TEXT NOT NULL,
    kol_name       TEXT NOT NULL,
    sector         TEXT DEFAULT '',
    date           TEXT NOT NULL,
    direction      TEXT DEFAULT '',
    comments       TEXT NOT NULL,
    targets        TEXT DEFAULT '',
    detail         TEXT DEFAULT '',
    detail_status  TEXT DEFAULT '',
    source_url     TEXT DEFAULT '',
    source_title   TEXT DEFAULT '',
    sources_json   TEXT DEFAULT '[]',
    source_status  TEXT DEFAULT 'missing',
    origin         TEXT DEFAULT '',
    notion_page_id TEXT DEFAULT '',
    created_at     TEXT DEFAULT '',
    updated_at     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_op_kol  ON opinion(kol_id);
CREATE INDEX IF NOT EXISTS ix_op_date ON opinion(date);
CREATE INDEX IF NOT EXISTS ix_op_src  ON opinion(source_status);

CREATE TABLE IF NOT EXISTS kol (
    kol_id         TEXT PRIMARY KEY,
    kol_name       TEXT NOT NULL,
    sector         TEXT DEFAULT '',
    notion_page_id TEXT DEFAULT '',
    updated_at     TEXT DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")


def slugify(name: str) -> str:
    """人名 → 稳定 kol_id。与既有 backfill 文件名规则保持一致(小写+下划线)。"""
    s = (name or "").strip()
    s = re.sub(r"[（(].*?[)）]", "", s)      # 去括号注释
    s = re.sub(r"\s*/\s*.*$", "", s)          # 去 " / 机构" 后缀
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", s).strip("_")
    return s or hashlib.sha1((name or "").encode()).hexdigest()[:12]


def make_uid(kol_id: str, date: str, direction: str, comments: str) -> str:
    raw = f"{kol_id}|{date}|{(direction or '').strip()}|{(comments or '').strip()[:120]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def connect(path: str = STORE_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ── 归一化 ─────────────────────────────────────────────────────────

def _tgs(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x)
    return str(v or "").strip()


def _pick_source(rec: dict) -> tuple:
    """返回 (url, title, sources_json, status)。绝不编造, 拿不到就 missing。"""
    srcs = rec.get("sources") or []
    if isinstance(srcs, dict):
        srcs = [srcs]
    url = (rec.get("source") or rec.get("source_url") or "").strip()
    title = (rec.get("source_title") or "").strip()
    if not url:
        for s in srcs:
            if isinstance(s, dict) and (s.get("url") or "").startswith("http"):
                url, title = s["url"].strip(), (s.get("title") or "").strip()
                break
    status = "ok" if url.startswith("http") else "missing"
    return url, title, json.dumps(srcs, ensure_ascii=False), status


def normalize(rec: dict, kol_name: str, sector: str, origin: str,
              kol_id: str = "") -> dict | None:
    """把任意来源的一条观点归一成 store 行。日期/正文缺失一律拒收(不猜不补)。"""
    date = (rec.get("date") or rec.get("first_date") or "").strip()[:10]
    comments = (rec.get("comments") or "").strip()
    if not date or not comments:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    kid = kol_id or slugify(kol_name)
    url, title, sjson, sstat = _pick_source(rec)
    return {
        "uid": make_uid(kid, date, rec.get("direction", ""), comments),
        "kol_id": kid,
        "kol_name": (kol_name or "").strip(),
        "sector": (sector or rec.get("sector") or "").strip(),
        "date": date,
        "direction": (rec.get("direction") or "").strip(),
        "comments": comments,
        "targets": _tgs(rec.get("targets")),
        "detail": (rec.get("detail") or "").strip(),
        "detail_status": (rec.get("detail_status") or "").strip(),
        "source_url": url,
        "source_title": title,
        "sources_json": sjson,
        "source_status": sstat,
        "origin": origin,
    }


# ── 唯一写入口 ─────────────────────────────────────────────────────

_FIELDS = ("kol_id", "kol_name", "sector", "date", "direction", "comments",
           "targets", "detail", "detail_status", "source_url", "source_title",
           "sources_json", "source_status", "origin")

# 这些字段为空时不覆盖已有真值
_PROTECTED = ("sector", "direction", "targets", "detail", "detail_status",
              "source_url", "source_title")


def upsert(records: list, conn: sqlite3.Connection | None = None) -> dict:
    """★唯一写入口。records 为 normalize() 产出的行。幂等。

    返回 {'inserted':n, 'updated':n, 'skipped':n}
    """
    own = conn is None
    conn = conn or connect()
    stat = {"inserted": 0, "updated": 0, "skipped": 0}
    now = _now()
    try:
        for r in records:
            if not r:
                stat["skipped"] += 1
                continue
            cur = conn.execute("SELECT * FROM opinion WHERE uid=?", (r["uid"],)).fetchone()
            if cur is None:
                cols = ", ".join(_FIELDS) + ", uid, created_at, updated_at"
                ph = ", ".join("?" * (len(_FIELDS) + 3))
                conn.execute(f"INSERT INTO opinion ({cols}) VALUES ({ph})",
                             [r[f] for f in _FIELDS] + [r["uid"], now, now])
                stat["inserted"] += 1
            else:
                old_rank = ORIGIN_RANK.get(cur["origin"], 0)
                new_rank = ORIGIN_RANK.get(r["origin"], 0)
                sets, vals = [], []
                for f in _FIELDS:
                    nv, ov = r[f], cur[f]
                    if f in ("kol_id", "date", "comments"):
                        continue
                    if f in _PROTECTED:
                        # 空不覆盖非空；非空时仅当来源等级 >= 现有才覆盖
                        if not nv:
                            continue
                        if ov and new_rank < old_rank:
                            continue
                    if f == "origin" and new_rank < old_rank:
                        continue
                    if nv != ov:
                        sets.append(f"{f}=?")
                        vals.append(nv)
                if sets:
                    # source_status 随 url 同步修正
                    conn.execute(
                        f"UPDATE opinion SET {', '.join(sets)}, updated_at=? WHERE uid=?",
                        vals + [now, r["uid"]])
                    conn.execute(
                        "UPDATE opinion SET source_status=CASE WHEN source_url LIKE 'http%' "
                        "THEN 'ok' ELSE 'missing' END WHERE uid=?", (r["uid"],))
                    stat["updated"] += 1
                else:
                    stat["skipped"] += 1
            conn.execute(
                "INSERT INTO kol (kol_id,kol_name,sector,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(kol_id) DO UPDATE SET kol_name=excluded.kol_name, "
                "sector=CASE WHEN excluded.sector<>'' THEN excluded.sector ELSE kol.sector END, "
                "updated_at=excluded.updated_at",
                (r["kol_id"], r["kol_name"], r["sector"], now))
        conn.commit()
    finally:
        if own:
            conn.close()
    return stat


# ── 各来源适配器 (全部汇入 upsert) ───────────────────────────────────

def ingest_backfill_dir(d: str = BACKFILL_DIR, conn=None) -> dict:
    rows = []
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            js = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        kid = os.path.basename(p)[:-5]
        name = (js.get("kol") or "").strip() or kid
        sector = js.get("sector") or ""
        for h in js.get("history", []):
            r = normalize(h, name, sector, "backfill", kol_id=kid)
            if r:
                rows.append(r)
    return {**upsert(rows, conn), "read": len(rows)}


def ingest_daily_dir(d: str = DAILY_DIR, conn=None) -> dict:
    rows = []
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            js = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ds = (js.get("date") or os.path.basename(p)[:-5]).strip()
        for k in js.get("kols", []):
            rec = dict(k)
            rec["date"] = ds
            r = normalize(rec, k.get("kol", ""), k.get("sector", ""), "daily")
            if r:
                rows.append(r)
    return {**upsert(rows, conn), "read": len(rows)}


def ingest_records(records: list, kol_name: str, sector: str = "",
                   origin: str = "manual", kol_id: str = "", conn=None) -> dict:
    """★新增 KOL / 一次性回填走这里 —— 裸 list 直接喂, 不需要任何格式包装。

    这就是 felix_prehn 那类 scratch 产物的正式入口。
    """
    rows = [normalize(r, kol_name, sector, origin, kol_id=kol_id) for r in records]
    rows = [r for r in rows if r]
    return {**upsert(rows, conn), "read": len(rows)}


def ingest_scratch_dir(d: str, sector: str = "", origin: str = "manual",
                       name_map: dict | None = None, conn=None) -> dict:
    """把 scratch/<batch>/out/*.json (裸 list, 文件名即 kol_id) 全量并入。"""
    name_map = name_map or {}
    tot = {"inserted": 0, "updated": 0, "skipped": 0, "read": 0}
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            js = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(js, list):
            continue
        kid = os.path.basename(p)[:-5]
        nm = name_map.get(kid) or kid.replace("_", " ").title()
        s = ingest_records(js, nm, sector, origin, kol_id=kid, conn=conn)
        for k in tot:
            tot[k] += s.get(k, 0)
    return tot


# ── 读取 ───────────────────────────────────────────────────────────

def full_history(conn=None) -> dict:
    """{kol_name: [ {first_date,last_date,direction,comments,targets,source,
                     origin,detail,sources}, ... ]}  按 last_date 倒序。

    连续同 (direction, comments) 折叠成区间 —— 与旧 kol_full_history() 等价。
    """
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT * FROM opinion ORDER BY kol_name, date ASC, "
            "CASE origin WHEN 'manual' THEN 0 WHEN 'backfill' THEN 1 ELSE 2 END"
        ).fetchall()
        out: dict = {}
        for r in rows:
            k = r["kol_name"]
            lst = out.setdefault(k, [])
            if (lst and lst[-1]["direction"] == r["direction"]
                    and lst[-1]["comments"] == r["comments"]):
                lst[-1]["last_date"] = max(lst[-1]["last_date"], r["date"])
                if r["detail"]:
                    lst[-1]["detail"] = r["detail"]
                if r["source_url"] and not lst[-1]["source"]:
                    lst[-1]["source"] = r["source_url"]
                continue
            lst.append({
                "first_date": r["date"], "last_date": r["date"],
                "direction": r["direction"], "comments": r["comments"],
                "targets": r["targets"], "source": r["source_url"],
                "origin": r["origin"], "detail": r["detail"],
                "sources": json.loads(r["sources_json"] or "[]"),
            })
        for k in out:
            out[k].sort(key=lambda x: x["last_date"], reverse=True)
        return out
    finally:
        if own:
            conn.close()


def latest_with_source(conn=None) -> dict:
    """{kol_name: {date,url,comments,direction}} —— 每人最新一条【带 URL】的观点。
    供 Notion KOL List 的 Source 列回填使用。"""
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT kol_name, date, source_url, comments, direction FROM opinion "
            "WHERE source_status='ok' ORDER BY date ASC").fetchall()
        out = {}
        for r in rows:
            out[r["kol_name"]] = {"date": r["date"], "url": r["source_url"],
                                  "comments": r["comments"], "direction": r["direction"]}
        return out
    finally:
        if own:
            conn.close()


def stats(conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    try:
        q = lambda s, *a: conn.execute(s, a).fetchone()[0]
        return {
            "opinions": q("SELECT COUNT(*) FROM opinion"),
            "kols": q("SELECT COUNT(DISTINCT kol_id) FROM opinion"),
            "source_ok": q("SELECT COUNT(*) FROM opinion WHERE source_status='ok'"),
            "source_missing": q("SELECT COUNT(*) FROM opinion WHERE source_status<>'ok'"),
            "date_min": q("SELECT MIN(date) FROM opinion"),
            "date_max": q("SELECT MAX(date) FROM opinion"),
            "by_origin": dict(conn.execute(
                "SELECT origin, COUNT(*) FROM opinion GROUP BY origin").fetchall()),
        }
    finally:
        if own:
            conn.close()


def export_json(path: str = EXPORT_PATH, conn=None) -> str:
    """导出人类可读 / 可 diff 的 JSON 快照(进 git), 与 sqlite 内容等价。"""
    own = conn is None
    conn = conn or connect()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM opinion ORDER BY kol_id, date").fetchall()]
        for r in rows:
            r["sources"] = json.loads(r.pop("sources_json") or "[]")
        payload = {"generated_at": _now(), "count": len(rows),
                   "stats": stats(conn), "opinions": rows}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        return path
    finally:
        if own:
            conn.close()


def set_notion_page(uid: str, page_id: str, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("UPDATE opinion SET notion_page_id=?, updated_at=? WHERE uid=?",
                     (page_id, _now(), uid))
        conn.commit()
    finally:
        if own:
            conn.close()


# ── 出处(source)质量守门 ────────────────────────────────────────────
#
# ★2026-08-26 溯源结论(git log -S'sources' 证实):
#   每日快照的 sources 字段是 2026-08-22 那次 commit 才加上的。因此:
#     - 2026-08-22 起: 填充率 98~99%, 管道本身没毛病
#     - 2026-08-21 及以前: 0%, 是【历史存量缺口】(约 2420 条)
#   之前把整体 16% 当成"抓取能力不行"是误判 —— 均值掩盖了阶跃。
#   所以这里不做"教爬虫存 URL"(已具备), 而是把缺口【量化 + 可回填 + 可告警】。

SOURCE_PIPELINE_FIXED_AT = "2026-08-22"


def source_gap_report(conn=None) -> dict:
    """出处缺口报表。区分「管道修复后的新缺口」(需告警) 与「历史存量」(需回填)。"""
    own = conn is None
    conn = conn or connect()
    try:
        q = lambda s, *a: conn.execute(s, a).fetchone()[0]
        recent_miss = q("SELECT COUNT(*) FROM opinion WHERE source_status<>'ok' "
                        "AND date>=?", SOURCE_PIPELINE_FIXED_AT)
        recent_tot = q("SELECT COUNT(*) FROM opinion WHERE date>=?",
                       SOURCE_PIPELINE_FIXED_AT)
        legacy_miss = q("SELECT COUNT(*) FROM opinion WHERE source_status<>'ok' "
                        "AND date<?", SOURCE_PIPELINE_FIXED_AT)
        by_day = [dict(r) for r in conn.execute(
            "SELECT date, SUM(source_status='ok') ok, COUNT(*) tot FROM opinion "
            "WHERE date>=? GROUP BY date ORDER BY date DESC LIMIT 14",
            (SOURCE_PIPELINE_FIXED_AT,)).fetchall()]
        return {
            "pipeline_fixed_at": SOURCE_PIPELINE_FIXED_AT,
            "recent_total": recent_tot,
            "recent_missing": recent_miss,
            "recent_fill_rate": round(100 * (recent_tot - recent_miss)
                                      / max(recent_tot, 1), 1),
            "legacy_missing": legacy_miss,
            "by_day": by_day,
        }
    finally:
        if own:
            conn.close()


def assert_source_quality(min_rate: float = 90.0, conn=None) -> dict:
    """落盘后校验: 管道修复日之后的出处填充率跌破阈值 → 返回 alert。

    供每日流程收尾调用。只报警不抛异常, 不打断主流程。
    """
    rep = source_gap_report(conn)
    rep["alert"] = rep["recent_fill_rate"] < min_rate
    if rep["alert"]:
        rep["message"] = (
            f"⚠️ 出处填充率 {rep['recent_fill_rate']}% 低于阈值 {min_rate}% "
            f"(近期缺 {rep['recent_missing']}/{rep['recent_total']} 条)")
    return rep


def missing_source_candidates(limit: int = 50, conn=None) -> list:
    """列出最值得回填出处的历史条目(按日期倒序), 供增量回填脚本消费。"""
    own = conn is None
    conn = conn or connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT uid, kol_name, date, comments FROM opinion "
            "WHERE source_status<>'ok' ORDER BY date DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        if own:
            conn.close()


def apply_source(uid: str, url: str, title: str = "", conn=None) -> bool:
    """给某条历史观点补上真实出处。绝不接受非 http 值(防编造)。"""
    if not (url or "").startswith("http"):
        return False
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "UPDATE opinion SET source_url=?, source_title=?, source_status='ok', "
            "updated_at=? WHERE uid=?", (url, title, _now(), uid))
        conn.commit()
        return True
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    import pprint
    pprint.pprint(stats())
