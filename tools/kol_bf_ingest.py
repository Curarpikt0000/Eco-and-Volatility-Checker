#!/usr/bin/env python3
"""KOL 一年期回填：校验 + 入库（2026-09-29 立，Chao 选 B「新人 + 110 个缺月的人全部补」）。

子 agent 产出在 <batch_dir>/out/<kol_id>.json（裸 JSON 数组）。本脚本逐条过门禁，
合格的以 origin=manual 写入 kol_store，**kol_name 用名册 display_name**
（看板历史按 display_name join，写成短名会“入库了但看板不显示”）。

门禁（全部机械判定，不调 LLM）：
  G1 字段：date=YYYY-MM-DD、comments 非空、source 是 http(s) URL
  G2 窗口：WIN_START <= date <= 今天（越界 / 未来日期拒收）
  G3 方向：归一到 看涨/看跌/中性，其他值拒收
  G4 出处实测：抓 source URL
       - 404/410/DNS 失败        → 拒收（链接不存在 = 不可追溯）
       - 200 且页面里找不到本人姓氏 → 拒收（张冠李戴 / 编造的高危信号）
       - 403/429/超时/付费墙      → 保留，记为「无法自动核验」并单列计数
  G5 去重：同人同日同 comments 只留一条（store 的 uid 也会再挡一次）

用法:
  .venv/bin/python tools/kol_bf_ingest.py scratch/kol_bf_new10            # 预演，只报告
  .venv/bin/python tools/kol_bf_ingest.py scratch/kol_bf_new10 --apply    # 入库
  --no-fetch 跳过 G4（仅调试用）
报告写 <batch_dir>/ingest_report.json（每次覆盖），stdout 打一行汇总。
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import kol_store  # noqa: E402

WIN_START = (dt.date.today() - dt.timedelta(days=365)).isoformat()   # 滚动一年(原固定 2025-09-29; 自动回填每天跑需滚动)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
DIR_MAP = {"看涨": "看涨", "看多": "看涨", "偏多": "看涨", "强烈看多": "看涨",
           "看跌": "看跌", "看空": "看跌", "偏空": "看跌", "强烈看空": "看跌",
           "中性": "中性", "观望": "中性"}


import unicodedata


def fold(s):
    """去重音: Sløk→slok, Stöferle→stoeferle。姓名关键词和网页正文两边都折叠后再比。"""
    s = s.replace("ø", "o").replace("Ø", "O").replace("ß", "ss")
    s = s.replace("ö", "oe").replace("ü", "ue").replace("ä", "ae")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def registry():
    r = json.load(open(os.path.join(ROOT, "data", "kol_registry.json"), encoding="utf-8"))["kols"]
    return {k["id"]: k for k in r}


def existing_kol_id(conn, display):
    """沿用该人在 store 里已有的 kol_id（daily 行用的是短 slug），保持一人一个 id。"""
    row = conn.execute("select kol_id, count(*) n from opinion where kol_name=? group by kol_id "
                       "order by n desc limit 1", (display,)).fetchone()
    return row[0] if row else None


def surname_keys(k):
    """页面里用来判定「确实提到了本人」的关键词：英文取姓，中文取全名。"""
    short = (k.get("short_name") or k["display_name"].split("（")[0]).strip()
    short = re.sub(r"^(Dr\.|Prof\.)\s*", "", short)
    short = re.sub(r"\s*(教授|博士)$", "", short)
    # ★2026-09-30 修: 名字含「/」(如「Doomberg / Kuppy」「Robert Prechter / Elliott Wave International」)
    #   时原来只取整串最后一个词 → 得到 'kuppy' / 'international', 误杀 18 条。现在每段各取姓;
    #   另加去重音变体(Sløk→slok: 网页常写 Slok), 防止非 ASCII 字母对不上。
    keys = set()
    segs = [short] + list(k.get("search_terms") or [])
    for seg in segs:
        for part in re.split(r"\s*/\s*", seg or ""):
            part = part.strip()
            if not part:
                continue
            if re.search(r"[\u4e00-\u9fff]", part):
                # ★2026-09-30 修: 中英混写名(「Shaun Rein 雷小山」)原来整串当关键词 → 英文页面永远对不上,
                #   10 条全误杀。拆开: 中文部分整体收, 英文部分走下面的取姓逻辑。
                for cj in re.findall(r"[\u4e00-\u9fff·・]{2,}", part):   # 带间隔号的整串保留(罗伯特·普莱切特), 不拆出泛名「罗伯特」
                    keys.add(cj)
                part = re.sub(r"[\u4e00-\u9fff·・]+", " ", part).strip()
                if not part:
                    continue
            words = [w for w in re.split(r"\s+", part) if w and not w.endswith(".")]
            if not words:
                continue
            last = words[-1].lower()
            # ★2026-09-30: search_terms 常是「人名 + 话题词」(Doug McMillon Fed)，取最后一词会得到 fed/economy 这类泛词 → 任何财经页都命中。
            if last not in ("international", "research", "capital", "group", "llc", "inc", "fed", "economy", "gold", "silver",
                            "inflation", "rates", "market", "markets", "stocks", "outlook", "interview", "podcast",
                            "forecast", "oil", "dollar", "bitcoin", "china", "ai", "recession", "bonds", "yields"):
                keys.add(last if len(words) > 1 else words[0].lower())
            if len(words) > 2 and words[-1].lower() in ("international", "research", "capital", "group", "llc", "inc"):
                keys.add(part.lower())  # 只有机构名(Elliott Wave International)才收整串; 「人名+话题词」不收
    keys |= {fold(x) for x in keys}
    return {x for x in keys if len(x) >= 2}


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,zh;q=0.8"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(1_500_000).decode("utf-8", "ignore")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001  DNS/超时/SSL
        msg = str(e)
        if "Name or service not known" in msg or "nodename nor servname" in msg or "No address" in msg:
            return -1, ""
        return 0, ""


JS_SHELL_HOSTS = ("x.com", "twitter.com", "www.linkedin.com", "linkedin.com")


def check_url(url, keys):
    # ★2026-09-30 修: x.com 对无登录抓取返回 16 万字节的 JS 空壳(200, 无正文),
    #   原逻辑把「>3000 字节且无姓名」判成拒收, 误杀 9 条。这类站点只做存在性判断。
    host = re.sub(r"^https?://([^/]+).*", r"\1", url).lower()
    if host in JS_SHELL_HOSTS:
        st, _ = fetch(url)
        if st in (404, 410, -1):
            return "reject", f"http {st}"
        return "unverifiable", f"js-shell {st}"
    st, body = fetch(url)
    if st in (404, 410, -1):
        return "reject", f"http {st}"
    if st == 200 and body[:5] == "%PDF-":
        # ★2026-09-30: PDF(财报电话会纪要等)正文是压缩流, 文本匹配必然失败 → 判不了, 不当成张冠李戴拒收
        return "unverifiable", "200 pdf"
    if st == 200:
        low = body.lower()
        flow = fold(low)
        # ★2026-09-30 修: 改为「整词」匹配。原来是子串 in, 短姓(Rein)会命中 reinvest/reinforce 等常见词,
        #   对照组里维基「Gold」页、美联储新闻页这两条假链接都被放行。英文关键词两侧须非字母; 中文仍子串。
        def _hit(k, text):
            k = k.lower()
            if re.search(r"[\u4e00-\u9fff]", k):
                return k in text
            return re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text) is not None
        if any(_hit(k, low) or _hit(fold(k), flow) for k in keys):
            return "ok", "200+name"
        if len(body) < 3000:  # JS 壳页面/同意页，判不了
            return "unverifiable", "200 shell"
        return "reject", "200 但页面无本人姓名"
    return "unverifiable", f"http {st}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    today = dt.date.today().isoformat()
    reg = registry()
    conn = kol_store.connect()
    report = {"dir": a.batch_dir, "people": {}, "totals": {}}
    T = dict(files=0, read=0, ok=0, unverifiable=0, reject_field=0, reject_window=0,
             reject_dir=0, reject_url=0, dup=0, inserted=0, updated=0, skipped=0, bad_json=0, not_in_registry=0)
    jobs = []
    per = {}
    for p in sorted(glob.glob(os.path.join(a.batch_dir, "out", "*.json"))):
        kid = os.path.basename(p)[:-5]
        T["files"] += 1
        if kid not in reg:
            T["not_in_registry"] += 1
            report["people"][kid] = {"error": "id 不在名册"}
            continue
        try:
            recs = json.load(open(p, encoding="utf-8"))
            assert isinstance(recs, list)
        except Exception:  # noqa: BLE001
            T["bad_json"] += 1
            report["people"][kid] = {"error": "JSON 损坏/非数组"}
            continue
        k = reg[kid]
        keys = surname_keys(k)
        seen = set()
        P = per[kid] = dict(read=len(recs), kept=[], rejects=[], unverifiable=0)
        T["read"] += len(recs)
        for r in recs:
            d = str(r.get("date") or "")[:10]
            cm = (r.get("comments") or "").strip()
            src = (r.get("source") or "").strip()
            if not src and r.get("sources"):
                src = (r["sources"][0].get("url") or "").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not cm or not re.match(r"https?://", src):
                T["reject_field"] += 1; P["rejects"].append([d, "字段缺失", src]); continue
            if not (WIN_START <= d <= today):
                T["reject_window"] += 1; P["rejects"].append([d, "窗口外", src]); continue
            di = DIR_MAP.get((r.get("direction") or "").strip())
            if not di:
                T["reject_dir"] += 1; P["rejects"].append([d, f"方向={r.get('direction')}", src]); continue
            key = (d, cm)
            if key in seen:
                T["dup"] += 1; continue
            seen.add(key)
            rr = dict(r); rr["direction"] = di; rr["source"] = src
            rr.setdefault("sources", [{"url": src, "date": d}])
            jobs.append((kid, rr, src, keys))
    # G4 并发抓取
    results = {}
    if a.no_fetch:
        results = {i: ("unverifiable", "no-fetch") for i in range(len(jobs))}
    else:
        with cf.ThreadPoolExecutor(12) as ex:
            futs = {ex.submit(check_url, j[2], j[3]): i for i, j in enumerate(jobs)}
            for f in cf.as_completed(futs):
                results[futs[f]] = f.result()
    for i, (kid, rr, src, _) in enumerate(jobs):
        verdict, why = results[i]
        P = per[kid]
        if verdict == "reject":
            T["reject_url"] += 1; P["rejects"].append([rr["date"], why, src]); continue
        if verdict == "unverifiable":
            T["unverifiable"] += 1; P["unverifiable"] += 1
        T["ok"] += 1
        P["kept"].append(rr)
    # 入库
    for kid, P in per.items():
        k = reg[kid]
        disp = k["display_name"]
        store_id = existing_kol_id(conn, disp) or kid
        months = sorted({r["date"][:7] for r in P["kept"]})
        report["people"][kid] = dict(name=disp.split("（")[0], read=P["read"], kept=len(P["kept"]),
                                     unverifiable=P["unverifiable"], months=len(months),
                                     range=[months[0], months[-1]] if months else [],
                                     rejects=P["rejects"])
        if a.apply and P["kept"]:
            s = kol_store.ingest_records(P["kept"], disp, k.get("domain", ""), "manual",
                                         kol_id=store_id, conn=conn)
            for x in ("inserted", "updated", "skipped"):
                T[x] += s.get(x, 0)
    report["totals"] = T
    report["applied"] = a.apply
    json.dump(report, open(os.path.join(a.batch_dir, "ingest_report.json"), "w"), ensure_ascii=False, indent=1)
    print(("APPLY " if a.apply else "DRY ") + json.dumps(T, ensure_ascii=False))


if __name__ == "__main__":
    main()
