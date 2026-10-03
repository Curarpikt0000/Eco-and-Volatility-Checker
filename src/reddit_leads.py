"""Reddit 渠道(Chao 2026-10-03 要求): 报告解读 + KOL 言论的搜索地方之一。

实测(2026-10-03): VM 直连被拦; Mac Chrome 读 search.json 也被 "blocked by network security";
唯一可用 = reddit.com/r/<sub>/search.rss (Atom), 但配额很低(连发 4 次即 429)。
故设计成: 低频、按子版块、走 RSS、间隔 >=8 秒、429 即停当天(不硬撞)。

★对照组铁律: 「查不到X」之前先拿必然存在的对照组走同一通道(r/<sub> 搜 'gold' 必有结果),
  对照组也空/429 → 判定「通道坏了」, 绝不据此写「Reddit 没人讲」。

输出 data/reddit_leads.json: {generated, subs, ok_control, orgs:{name:{items:[{title,date,sub,url,score?}]}}}
门禁沿用 report_leads: 名字锚点 + 语境词 + 同名排除词。
"""
import datetime as dt
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

import report_leads as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "reddit_leads.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SUBS = ["Gold", "Silverbugs", "wallstreetbets", "investing", "economy", "Economics", "Bitcoin", "stocks"]
NS = {"a": "http://www.w3.org/2005/Atom"}


class Throttled(Exception):
    pass


def rss_search(sub, q, sess):
    r = sess.get(f"https://www.reddit.com/r/{sub}/search.rss",
                 params={"q": q, "restrict_sr": 1, "sort": "new", "t": "year"},
                 headers={"User-Agent": UA}, timeout=25)
    if r.status_code == 429:
        raise Throttled("429")
    if r.status_code != 200:
        raise RuntimeError(f"http {r.status_code}")
    root = ET.fromstring(r.content)
    out = []
    for e in root.findall("a:entry", NS):
        title = e.findtext("a:title", "", NS)
        link = (e.find("a:link", NS).get("href") if e.find("a:link", NS) is not None else "")
        upd = e.findtext("a:updated", "", NS)[:10]
        body = re.sub(r"<[^>]+>", " ", html.unescape(e.findtext("a:content", "", NS)))
        out.append({"title": title.strip(), "date": upd, "url": link, "summary": re.sub(r"\s+", " ", body).strip()[:140],
                    "sub": sub, "platform": f"Reddit r/{sub}"})
    return out


def control_ok(sess):
    """对照组: r/Gold 搜 'gold' 必有结果。返回 (ok, 说明)"""
    try:
        items = rss_search("Gold", "gold", sess)
        return (len(items) > 0), f"对照组条数={len(items)}"
    except Throttled:
        return False, "对照组 429(限流)"
    except Exception as ex:  # noqa: BLE001
        return False, f"对照组失败 {type(ex).__name__}"


def collect(names=None, subs=None, sleep=8.0, log=print):
    sess = requests.Session()
    ok, why = control_ok(sess)
    log(f"[对照组] {why}")
    if not ok:
        return {"ok_control": False, "why": why, "orgs": {}}
    time.sleep(sleep)
    subs = subs or SUBS
    res = {}
    today = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=183)).isoformat()
    for name, (org, alias, ctx, _q) in R.TARGETS.items():
        if names and name not in names:
            continue
        # Reddit 搜索用英文名(锚点里第一个纯 ASCII 的), 避免中文音译
        en = next((a for a in alias if re.fullmatch(r"[A-Za-z .]+", a) and len(a) > 4), name)
        got = {}
        for sub in subs:
            try:
                items = rss_search(sub, f'"{en}"', sess)
            except Throttled:
                log(f"[{name}] r/{sub} 429, 停止本次(不硬撞)")
                return {"ok_control": True, "partial": True, "stopped_at": f"{name}/{sub}", "orgs": res}
            except Exception as ex:  # noqa: BLE001
                log(f"[{name}] r/{sub} 失败 {type(ex).__name__}")
                items = []
            for x in items:
                if not R.passes_gates(name, x, alias, ctx) or not (start <= x["date"] <= today):
                    continue
                got.setdefault(R._norm(x["title"]), x)
            time.sleep(sleep)
        res[name] = {"org": org, "items": sorted(got.values(), key=lambda z: z["date"], reverse=True)}
        log(f"[{name}] r/ 命中 {len(got)}")
    return {"ok_control": True, "partial": False, "orgs": res}


if __name__ == "__main__":
    import sys
    only = sys.argv[1:] or None
    r = collect(names=only)
    r["generated"] = dt.datetime.now().isoformat(timespec="seconds")
    r["subs"] = SUBS
    json.dump(r, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写入", OUT, "| 对照组", r.get("ok_control"), "| 机构", len(r.get("orgs", {})),
          "| 条数", sum(len(v["items"]) for v in r.get("orgs", {}).values()))
