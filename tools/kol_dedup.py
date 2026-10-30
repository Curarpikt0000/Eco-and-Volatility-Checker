#!/usr/bin/env python3
"""KOL 已见内容索引 + 三重排重（Chao 2026-10-30 定：先排重，确认全新才调 AI）。

三重排重（任一命中=已见，不再抽取/翻译/总结）:
  1. 链接重复  —— 归一化 URL(去 utm/www/末尾斜杠; YouTube 取 video id; X 取 status id)
  2. 内容重复  —— 归一化文本前 60 字的指纹(去空白标点大小写)
  3. 引用重复  —— 正文/comments/detail 里引用到的 URL 全部已收录

索引来源: data/kol_store.sqlite + data/kol/backfill/*.json + data/x_backfill/*statements*.json
落盘: data/kol/seen_index.json ; 账本 data/kol/dedup_savings.jsonl

用法:
  python tools/kol_dedup.py build                   # 重建索引(幂等)
  python tools/kol_dedup.py enrich <batches_dir>    # 每人 known_urls 写进 b*.json, 抓取端据此跳过
  python tools/kol_dedup.py gate <YYYY-MM-DD>       # 合并前门禁: 给 out/*.json 里全是旧料的条目打标+记账
  python tools/kol_dedup.py report [N]              # 最近 N 天省钱账
"""
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
IDX = os.path.join(DATA, "kol", "seen_index.json")
LEDGER = os.path.join(DATA, "kol", "dedup_savings.jsonl")
FP_LEN = 60
TAIL_LEN = 40
# 单条「抽取+LLM 摘要」估算成本(美元), 仅用于账本估算, 非实测计费
EST_COST_PER_ITEM = 0.04

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]，。；、]+")
_TRACK = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
          "fbclid", "gclid", "ref", "si", "feature", "s", "t", "mc_cid", "mc_eid"}


def norm_url(u):
    u = (u or "").strip().rstrip(".,;)")
    if u.startswith(("yt:", "x:")):
        return u
    if not u.startswith("http"):
        return ""
    try:
        p = urlparse(u)
    except Exception:
        return ""
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if host.startswith("m."):
        host = host[2:]
    if host in ("youtube.com", "music.youtube.com"):
        v = parse_qs(p.query).get("v", [""])[0]
        if v:
            return "yt:" + v
    if host == "youtu.be":
        return "yt:" + p.path.strip("/")
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        m = re.search(r"/status(?:es)?/(\d+)", p.path)
        if m:
            return "x:" + m.group(1)
    q = "&".join(sorted(k + "=" + v[0] for k, v in parse_qs(p.query).items() if k.lower() not in _TRACK))
    return host + p.path.rstrip("/") + ("?" + q if q else "")


def fingerprint(text):
    t = re.sub(r"[\W_]+", "", (text or "").lower())[:FP_LEN]
    return hashlib.sha1(t.encode()).hexdigest()[:16] if len(t) >= 12 else ""


def fingerprint_tail(text):
    """★2026-10-31 第二指纹: 取归一化正文『末尾』TAIL_LEN 字。
    实测(300 条抽样): 只用开头指纹时, 给原文前面加日期/『摘要』/『X 说』就漏掉 283/300 —— 同一内容换壳重来会再烧 AI 钱。
    库里观点正文中位仅 78 字, 只有 13% 够 180 字, 『取中段』方案对 87% 的内容不生效, 故改取末尾:
    加前缀对末尾完全无影响。要求归一化后 >= TAIL_LEN+20 字才出指纹(太短的句子末尾易与别条撞)。
    取舍: 若对方只改动结尾(加『转自…』后缀)则漏; 由开头指纹/链接排重兜底。"""
    t = re.sub(r"[\W_]+", "", (text or "").lower())
    if len(t) < TAIL_LEN + 20:
        return ""
    return "t" + hashlib.sha1(t[-TAIL_LEN:].encode()).hexdigest()[:15]


def urls_in(text):
    return {n for n in (norm_url(u) for u in _URL_RE.findall(text or "")) if n}


def _add(idx, kid, urls=(), texts=()):
    e = idx.setdefault(kid, {"urls": set(), "fps": set()})
    for u in urls:
        n = norm_url(u)
        if n:
            e["urls"].add(n)
    for t in texts:
        f = fingerprint(t)
        if f:
            e["fps"].add(f)
        ft = fingerprint_tail(t)
        if ft:
            e["fps"].add(ft)
        e["urls"] |= urls_in(t)


def build():
    idx = {}
    try:
        c = sqlite3.connect(os.path.join(DATA, "kol_store.sqlite"))
        for kid, su, sj, cm, dt in c.execute(
                "select kol_id,source_url,sources_json,comments,detail from opinion"):
            us = [su] if su else []
            try:
                us += [s.get("url", "") for s in json.loads(sj or "[]") if isinstance(s, dict)]
            except Exception:
                pass
            _add(idx, kid, us, [cm, dt])
    except Exception as ex:
        print("store 读取失败:", ex)
    for f in glob.glob(os.path.join(DATA, "kol", "backfill", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        kid = os.path.basename(f)[:-5]
        for h in d.get("history", []):
            _add(idx, kid, [h.get("source", "")], [h.get("comments", ""), h.get("detail", "")])
    for f in glob.glob(os.path.join(DATA, "x_backfill", "*statements*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        kid = re.sub(r"_statements.*", "", os.path.basename(f)[:-5])
        for it in d.get("items", []):
            _add(idx, kid, [it.get("url", "")], [it.get("text", ""), it.get("zh", "")])
    out, gl = {}, set()
    for k, v in idx.items():
        out[k] = {"urls": sorted(v["urls"]), "fps": sorted(v["fps"])}
        gl |= v["urls"]
    out["_global_urls"] = sorted(gl)
    os.makedirs(os.path.dirname(IDX), exist_ok=True)
    json.dump(out, open(IDX, "w", encoding="utf-8"), ensure_ascii=False)
    print("索引已建: %d 人, 全局唯一链接 %d, 指纹 %d" % (
        len(out) - 1, len(gl), sum(len(v["fps"]) for k, v in out.items() if k != "_global_urls")))
    return out


def load():
    return json.load(open(IDX, encoding="utf-8")) if os.path.exists(IDX) else build()


def is_seen(idx, kid, url="", text="", extra_text=""):
    e = idx.get(kid, {"urls": [], "fps": []})
    known = set(e["urls"])
    n = norm_url(url)
    if n and n in known:
        return True, "link"
    fps = set(e["fps"])
    f = fingerprint(text)
    if f and f in fps:
        return True, "content"
    ft = fingerprint_tail(text)
    if ft and ft in fps:
        return True, "content"
    cites = urls_in(text) | urls_in(extra_text)
    if cites and cites <= known:
        return True, "cite"
    return False, ""


def enrich(bdir):
    idx = load()
    nk = 0
    for f in sorted(glob.glob(os.path.join(bdir, "b*.json"))):
        batch = json.load(open(f, encoding="utf-8"))
        for k in batch:
            k["known_urls"] = idx.get(k["id"], {}).get("urls", [])[-60:]
            nk += len(k["known_urls"])
        json.dump(batch, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    print("enrich 完成: 批文件已注入已收录链接共 %d 条" % nk)


def gate(date):
    idx = load()
    outd = os.path.join(ROOT, "scratch", "kol_deep_" + date, "out")
    tot = seen = 0
    reasons = {}
    for f in glob.glob(os.path.join(outd, "*.json")):
        try:
            r = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        kid = os.path.basename(f)[:-5]
        tot += 1
        srcs = [s.get("url", "") for s in (r.get("sources") or []) if isinstance(s, dict) and s.get("url")]
        if srcs:
            hits = [is_seen(idx, kid, u)[1] for u in srcs]
            old, why = all(hits), hits[0]
        else:
            old, why = is_seen(idx, kid, text=r.get("comments", ""), extra_text=r.get("detail", ""))
        if old and r.get("direction") != "未找到":
            r["dedup"], r["dedup_reason"] = "all_seen", why
            seen += 1
            reasons[why] = reasons.get(why, 0) + 1
            json.dump(r, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    rec = {"date": date, "kols": tot, "all_seen": seen, "new": tot - seen, "reasons": reasons,
           "est_saved_usd": round(seen * EST_COST_PER_ITEM, 2)}
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("DEDUP-GATE", json.dumps(rec, ensure_ascii=False))


def report(n=7):
    if not os.path.exists(LEDGER):
        print("账本为空")
        return
    rows = [json.loads(x) for x in open(LEDGER, encoding="utf-8") if x.strip()][-n:]
    for r in rows:
        print(r)
    print("合计估算省 $%.2f (按 $%s/条估算, 非实测计费)" % (
        sum(r.get("est_saved_usd", 0) for r in rows), EST_COST_PER_ITEM))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build()
    elif cmd == "enrich":
        enrich(sys.argv[2])
    elif cmd == "gate":
        gate(sys.argv[2])
    elif cmd == "report":
        report(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
