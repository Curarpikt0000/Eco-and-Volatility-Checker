#!/usr/bin/env python3
"""全量核验回填记录: 抓每个 URL, 从一手元数据取发布日, 与记录 date 比对; 并检查最终 URL/标题是否改变。
判定: ok(日期差≤2天) / date_mismatch / no_meta(页面无可解析发布日) / fetch_fail / redirected(slug 变了)
"""
import json, glob, re, sys, urllib.request, datetime as dt, concurrent.futures as cf
OUT = "/home/user/Projects/Eco-and-Volatility-Checker/scratch/kol_bf_full/out"
PATS = [r'"datePublished"\s*:\s*"([^"]+)"', r'article:published_time"\s+content="([^"]+)"',
        r'"publishDate"\s*:\s*"([^"]+)"', r'"post_date"\s*:\s*"([^"]+)"', r'"uploadDate"\s*:\s*"([^"]+)"',
        r'<time[^>]+datetime="([^"]+)"']
MON = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
def page_date(h):
    for p in PATS:
        m = re.search(p, h)
        if m:
            try: return dt.date.fromisoformat(m.group(1)[:10]), p.split('"')[1] if '"' in p else "time"
            except ValueError: pass
    m = re.search(r"\|\s*(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (20\d\d)", h)
    if m: return dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1))), "byline"
    return None, None
_ACAST = None
def _acast_dates():
    """Acast 节目页的 publishDate 是页面重建时间(全部显示 2026-09-22), 不是首发日;
    首发日以官方 RSS <pubDate> 为准(2026-09-25 实测: 页面 3 条全显 9/22, RSS 为 2025-11-05/2026-03-18/2026-07-28)。"""
    global _ACAST
    if _ACAST is None:
        _ACAST = {}
        try:
            x = urllib.request.urlopen(urllib.request.Request("https://feeds.acast.com/public/shows/these-times",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read().decode("utf-8", "replace")
            import email.utils
            for it in re.findall(r"<item>(.*?)</item>", x, re.S):
                l = re.search(r"<link>(.*?)</link>", it); d = re.search(r"<pubDate>(.*?)</pubDate>", it)
                if l and d:
                    _ACAST[l.group(1).strip().rstrip("/")] = email.utils.parsedate_to_datetime(d.group(1)).date()
        except Exception as e:
            print("acast RSS 失败", type(e).__name__, e)
    return _ACAST

def check(item):
    kid, r = item
    u = r["source"]
    if "shows.acast.com/" in u:
        pd_ = _acast_dates().get(u.rstrip("/"))
        if pd_ is None:
            return kid, r, "no_meta", "acast RSS 无此集", None
        diff = abs((pd_ - dt.date.fromisoformat(r["date"])).days)
        return kid, r, ("ok" if diff <= 2 else "date_mismatch"), f"acast RSS {pd_} (差{diff}天)", pd_
    try:
        resp = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
        h = resp.read().decode("utf-8", "replace"); final = resp.geturl()
    except Exception as e:
        return kid, r, "fetch_fail", f"{type(e).__name__}", None
    pd_, how = page_date(h)
    slug0 = u.rstrip("/").split("/")[-1]; slug1 = final.rstrip("/").split("/")[-1]
    if slug0 != slug1:
        return kid, r, "redirected", final, pd_
    if pd_ is None:
        return kid, r, "no_meta", "", None
    diff = abs((pd_ - dt.date.fromisoformat(r["date"])).days)
    return kid, r, ("ok" if diff <= 2 else "date_mismatch"), f"{how} {pd_} (差{diff}天)", pd_
items = []
for f in sorted(glob.glob(f"{OUT}/*.json")):
    kid = f.split("/")[-1][:-5]
    for r in json.load(open(f, encoding="utf-8")): items.append((kid, r))
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(check, items))
from collections import Counter
print("总", len(res), dict(Counter(x[2] for x in res)))
for kid in sorted({x[0] for x in res}):
    c = Counter(x[2] for x in res if x[0] == kid); print(" ", kid[:30], dict(c))
print("\n问题条目:")
for kid, r, st, info, pd_ in res:
    if st != "ok": print(f"  [{st}] {kid[:14]} 记录 {r['date']} | {info} | {r['source'][:90]}")
json.dump([{"id": k, "status": s, "info": i, "page_date": str(p) if p else None, **r} for k, r, s, i, p in res],
          open("/tmp/bf_verify.json", "w"), ensure_ascii=False, indent=1)
