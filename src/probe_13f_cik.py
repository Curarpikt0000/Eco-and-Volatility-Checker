"""probe_13f_cik.py — 给定机构名, 查 SEC EDGAR 是否有 13F-HR + CIK。

用 SEC full-text search + company search 找 CIK, 再查 submissions 确认有 13F-HR。
输出候选清单供人工核对(避免错配 CIK)。绝不猜, 查不到就标 NONE。
"""
import sys, json, time, urllib.request, urllib.parse

UA = "EcoVolChecker research chao.jin@example.com"
HDRS = {"User-Agent": UA}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=HDRS)
    return urllib.request.urlopen(req, timeout=timeout).read()


def search_cik(name):
    """用 EDGAR company search (JSON) 找匹配 CIK。返回 [(cik,name),...]。"""
    q = urllib.parse.quote(name)
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={q}&type=13F-HR&dateb=&owner=include&count=10&output=atom"
    try:
        raw = _get(url).decode("utf-8", "replace")
    except Exception as e:
        return []
    import re
    # atom 里 CIK 在 <cik>...</cik>, 名字在 <title> 或 company-info
    ciks = re.findall(r"CIK=(\d+)", raw)
    names = re.findall(r"<title>(.*?)</title>", raw)
    out = []
    seen = set()
    for c in ciks:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:5]


def has_13f(cik):
    """确认该 CIK 有 13F-HR, 返回 (name, latest_date, count) 或 None。"""
    try:
        d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"))
    except Exception:
        return None
    rec = d["filings"]["recent"]
    forms = rec["form"]
    f13 = [i for i, f in enumerate(forms) if f.startswith("13F-HR")]
    if not f13:
        return (d.get("name", ""), None, 0)
    return (d.get("name", ""), rec["filingDate"][f13[0]], len(f13))


# 候选机构(从 KOL 名册筛出有基金关键词的) — 用最可能注册 13F 的实体名
CANDIDATES = [
    ("Larry Lepard", "Equity Management Associates"),
    ("Kyle Bass", "Hayman Capital Management"),
    ("Bill Gross", "PIMCO"),
    ("Jeffrey Gundlach", "DoubleLine Capital"),
    ("Lacy Hunt", "Hoisington Investment Management"),
    ("Rick Rule", "Rule Investment"),
    ("Matthew Piepenburg", "Matterhorn Asset Management"),
    ("Jeff Snider", "Alhambra Investments"),
    ("Ted Oakley", "Oxbow Advisors"),
    ("David Hunter", "Contrarian Macro Advisors"),
    ("Torsten Slok", "Apollo Global Management"),
]


def main():
    print("[probe] 查 KOL 机构 13F 覆盖...\n", flush=True)
    results = []
    for kol, inst in CANDIDATES:
        ciks = search_cik(inst)
        time.sleep(0.3)
        best = None
        for c in ciks:
            info = has_13f(c)
            time.sleep(0.3)
            if info and info[2] > 0:
                best = (c, info)
                break
        if best:
            c, (nm, latest, cnt) = best
            print(f"  ✅ {kol} / {inst} → CIK={c} '{nm}' 13F最新={latest} 期数={cnt}", flush=True)
            results.append({"kol": kol, "fund": inst, "cik": c, "sec_name": nm,
                            "latest_13f": latest, "count": cnt, "has_13f": True})
        else:
            print(f"  ❌ {kol} / {inst} → 无 13F (个人/债券/海外/雇员)", flush=True)
            results.append({"kol": kol, "fund": inst, "has_13f": False})
    json.dump(results, open("data/probe_13f_result.json", "w"), ensure_ascii=False, indent=2)
    ok = [r for r in results if r.get("has_13f")]
    print(f"\n[probe] 有13F: {len(ok)}/{len(CANDIDATES)}", flush=True)


if __name__ == "__main__":
    main()
