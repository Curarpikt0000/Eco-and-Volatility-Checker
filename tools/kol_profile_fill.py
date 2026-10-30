#!/usr/bin/env python3
"""KOL 档案卡每日小批量补全 (Chao 2026-10-30 批准, 每天 8 人, 约 12 天补完 91 人)。

铁律(写成代码门禁, 不靠记得检查):
  - 名册 data/kol_registry.json 只读, 本脚本绝不增删任何 KOL(名册 SSOT 是 Notion)。
  - 子进程(sonnet-5-5, 每进程 1 人)只许写 /tmp/profile_work/<id>.json; 合并由本脚本做。
  - 合并前过 preflight(): 任一条不过就不入库, 并记入 data/kol_profile_rejects.jsonl(下次不重复烧钱, 除非 --retry)。
  - 名册显示名/简介含 ANONYMIZED 占位符的人 = 身份读不到, 不猜, 直接记 rejects 留给 Chao 给链接。

用法:
  python3 tools/kol_profile_fill.py --pick N          # 只列今天要做的 N 人
  python3 tools/kol_profile_fill.py --run N           # 取 N 人 → 子进程检索 → 门禁 → 合并
  python3 tools/kol_profile_fill.py --merge-only      # 只对 /tmp/profile_work 已有结果做门禁+合并(测试用)
"""
import argparse, concurrent.futures as cf, datetime, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data", "kol_registry.json")
PROF = os.path.join(ROOT, "data", "kol_profiles.json")
REJ = os.path.join(ROOT, "data", "kol_profile_rejects.jsonl")
WORK = "/tmp/profile_work"
TPL = os.path.join(ROOT, "tools", "kol_profile_prompt.txt")
FIELDS = ["id", "name", "num", "domain", "lifespan", "deceased", "title", "achievements", "honors",
          "scope", "viewpoint", "track_value", "institution", "books", "quote_2026", "sources"]
TEXT_FIELDS = ["lifespan", "title", "achievements", "honors", "scope", "viewpoint", "track_value", "institution", "books", "quote_2026"]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
NOT_FOUND_MARK = "未检索到"


def load_json(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def registry_active():
    r = load_json(REG, {})
    reg = r if isinstance(r, list) else r.get("kols", [])
    return [k for k in reg if k.get("active")]


def profiles():
    p = load_json(PROF, [])
    return p.get("profiles", []) if isinstance(p, dict) else p


def rejected_ids():
    out = {}
    if os.path.exists(REJ):
        for l in open(REJ, encoding="utf-8"):
            try:
                x = json.loads(l); out[x["id"]] = x
            except Exception:
                pass
    return out


def _num(k):
    v = k.get("notion_list_num")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return 9999


def pick(n, retry=False):
    have = {x["id"] for x in profiles()}
    rej = set() if retry else set(rejected_ids())
    todo = []
    for k in registry_active():
        if k["id"] in have or k["id"] in rej:
            continue
        todo.append(k)
    todo.sort(key=lambda k: (_num(k), k["id"]))
    return todo[:n], len(todo)


def clean(s):
    return re.sub(r"\*+|⭐", "", s or "").strip()


# ───────────────────────── 硬门禁 ─────────────────────────
def preflight(d, reg_item, check_urls=True):
    """返回 (ok, reasons[])。任何一条不过 → 不入库。"""
    bad = []
    if not isinstance(d, dict):
        return False, ["不是 JSON 对象"]
    for f in FIELDS:
        if f not in d:
            bad.append(f"缺字段 {f}")
    if bad:
        return False, bad
    if d["id"] != reg_item["id"]:
        bad.append(f"id 不符: {d['id']} != {reg_item['id']}")
    blob = json.dumps(d, ensure_ascii=False)
    if re.search(r"ANONYMIZED_\w+", blob):
        bad.append("含 ANONYMIZED 占位污染串")
    if "身份未能确认" in str(d.get("title")):
        bad.append("身份未能确认(同名闸)")
    for f in TEXT_FIELDS:
        if not str(d.get(f) or "").strip():
            bad.append(f"字段为空 {f}")
    nf = sum(1 for f in TEXT_FIELDS if NOT_FOUND_MARK in str(d.get(f)))
    if nf > 5:
        bad.append(f"「未检索到」字段过多({nf}/{len(TEXT_FIELDS)}), 档案太空")
    if not isinstance(d.get("deceased"), bool):
        bad.append("deceased 不是 bool")
    srcs = d.get("sources") or []
    if len(srcs) < 3:
        bad.append(f"出处不足 3 条({len(srcs)})")
    q = str(d.get("quote_2026") or "")
    if NOT_FOUND_MARK not in q and not re.search(r"2026-\d{2}-\d{2}|2026年\d{1,2}月", q):
        bad.append("quote_2026 没有 2026 年日期")
    if check_urls and len(srcs) >= 3:
        import requests
        okn = 0
        for x in srcs:
            try:
                r = requests.get(x.get("url", ""), headers=UA, timeout=20)
                body = re.sub(r"\s+", " ", r.text).lower()
                key = [w.lower() for w in re.findall(r"[A-Za-z]{5,}", x.get("title", "")) if w.lower() not in ("bloomberg", "intelligence", "strategist", "research")][:3]
                hit = sum(1 for w in key if w in body)
                if r.status_code == 200 and (hit >= 1 or not key):
                    okn += 1
                elif r.status_code in (401, 402, 403, 429) and re.match(r"https?://", x.get("url", "")):
                    okn += 0.5      # 付费墙/反爬: 半票, 不算假链接但也不算核实
            except Exception:
                pass
        if okn < 3:
            bad.append(f"可核实出处 {okn}/{len(srcs)} < 3(打开后标题对不上或打不开)")
    return (not bad), bad


def run_one(k):
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, f"{k['id']}.json")
    if os.path.exists(out):
        os.remove(out)
    t = open(TPL, encoding="utf-8").read()
    t = (t.replace("{ID}", k["id"]).replace("{NAME}", clean(k.get("display_name")))
          .replace("{BIO}", clean(k.get("bio"))[:700]).replace("{DOMAIN}", k.get("domain", "")))
    try:
        subprocess.run(["hermes", "-z", t, "--provider", "custom", "-m", "claude-sonnet-5-5", "-t", "web,terminal,file"],
                       capture_output=True, text=True, timeout=600, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return k["id"], "timeout"
    return k["id"], ("ok" if os.path.exists(out) else "no_output")


def merge(items):
    """对每个有产出的人做门禁, 通过者一次性写回 kol_profiles.json(原文件备份)。"""
    prof = profiles()
    have = {x["id"] for x in prof}
    added, rejected = [], []
    for k in items:
        p = os.path.join(WORK, f"{k['id']}.json")
        if not os.path.exists(p):
            rejected.append((k["id"], ["子进程无产出"])); continue
        d = load_json(p)
        ok, why = preflight(d, k)
        if ok and k["id"] not in have:
            d["num"] = _num(k) if _num(k) != 9999 else d.get("num", 0)
            prof.append({f: d[f] for f in FIELDS})
            added.append(k["id"])
        else:
            rejected.append((k["id"], why))
    if added:
        bak = PROF + ".bak." + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        open(bak, "w", encoding="utf-8").write(open(PROF, encoding="utf-8").read())
        json.dump(prof, open(PROF + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(PROF + ".tmp", PROF)
        # 写后读回: 新增的 id 必须都在
        back = {x["id"] for x in profiles()}
        miss = [i for i in added if i not in back]
        if miss:
            raise RuntimeError(f"读回失败, 缺 {miss}")
    with open(REJ, "a", encoding="utf-8") as f:
        for i, why in rejected:
            f.write(json.dumps({"id": i, "date": datetime.date.today().isoformat(), "reasons": why}, ensure_ascii=False) + "\n")
    return added, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int)
    ap.add_argument("--run", type=int)
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.pick:
        todo, total = pick(a.pick, a.retry)
        print(f"缺档案且未被拒 {total} 人, 今天取 {len(todo)}:")
        for k in todo:
            print(" ", k["id"], "|", clean(k.get("display_name"))[:50])
        return 0
    if a.merge_only:
        todo, _ = pick(999, a.retry)
        added, rejected = merge(todo)
        print("入库", added, "| 拒收", rejected)
        return 0
    if a.run:
        todo, total = pick(a.run, a.retry)
        if not todo:
            print("名册里没有待补档案的人"); return 0
        # 同名闸: 名册信息含占位符 = 读不到真名, 不猜, 直接拒并留痕
        skip, go = [], []
        for k in todo:
            (skip if re.search(r"ANONYMIZED_\w+", (k.get("display_name") or "") + (k.get("bio") or "")) else go).append(k)
        with open(REJ, "a", encoding="utf-8") as f:
            for k in skip:
                f.write(json.dumps({"id": k["id"], "date": datetime.date.today().isoformat(), "reasons": ["名册信息含占位符, 真名读不到, 需 Chao 给链接"]}, ensure_ascii=False) + "\n")
        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            res = list(ex.map(run_one, go))
        added, rejected = merge(go)
        print(f"今日 {len(todo)} 人: 占位符跳过 {len(skip)} | 子进程 {dict((i, s) for i, s in res)}")
        print(f"入库 {len(added)}: {added}")
        for i, w in rejected:
            print("  拒收", i, w)
        print(f"剩余待补(未被拒) {total - len(todo)} | 耗时 {int(time.time()-t0)}s")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
