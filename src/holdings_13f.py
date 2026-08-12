"""holdings_13f.py — 抓取知名机构 13F 持仓 + 对比上一期变动。

Chao 需求(2026-08): KOL 所代表机构 + Trump 的持仓报告, 每个持仓品对比上次报告变动(新增/加/减/清),
展示在 dashboard 最后卡片 + 写 Notion。

数据源: SEC EDGAR 官方(免费, 可查历史, 算变动)。
  - submissions/CIK{cik}.json → 找 13F-HR filings(季度)
  - Archives/.../index.json → 找 information table XML
  - 解析 nameOfIssuer/value/sshPrnamt, 按 issuer 聚合
  - 最新一期 vs 上一期 → 变动: 🆕新建 / ▲加仓 / ▼减仓 / ❌清仓 / →持平
13F 是季度披露(季末后45天), 非每日; cron 每日检查"是否有比已存更新的 13F", 有才更新。
Trump 无 13F(非投资经理) → 单独卡片, 数据由 cron agent web_search 最新公开披露(PFD)填, 标注来源。

绝不编: 拿不到的机构/期数标状态, 不虚构持仓。
"""
import sys, os, json, re, time, urllib.request, datetime

sys.path.insert(0, os.path.dirname(__file__))

UA = "EcoVolChecker research chao.jin@example.com"
HDRS = {"User-Agent": UA}
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HOLDINGS_JSON = os.path.join(DATA_DIR, "holdings_13f.json")

# 最小可用版: 8 个知名、SEC EDGAR 一定查得到的机构(对应 KOL)。CIK 已核对。
# 可后续扩到 KOL 名册里其它有实体基金的机构。
INSTITUTIONS = [
    {"kol": "Warren Buffett", "fund": "Berkshire Hathaway", "cik": "1067983"},
    {"kol": "Ray Dalio", "fund": "Bridgewater Associates", "cik": "1350694"},
    {"kol": "Michael Burry", "fund": "Scion Asset Mgmt", "cik": "1649339"},
    {"kol": "George Soros", "fund": "Soros Fund Mgmt", "cik": "1029160"},
    {"kol": "Cathie Wood", "fund": "ARK Investment Mgmt", "cik": "1697748"},
    {"kol": "Bill Ackman", "fund": "Pershing Square", "cik": "1336528"},
    {"kol": "David Tepper", "fund": "Appaloosa", "cik": "1656456"},
    {"kol": "Stanley Druckenmiller", "fund": "Duquesne Family Office", "cik": "1536411"},
]


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=HDRS)
    return urllib.request.urlopen(req, timeout=timeout).read()


def find_13f_filings(cik, limit=2):
    """返回该 CIK 最近的 13F-HR filings: [(filingDate, accession, reportDate),...] 降序。"""
    cik10 = f"{int(cik):010d}"
    d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    rec = d["filings"]["recent"]
    forms, accs, fdates = rec["form"], rec["accessionNumber"], rec["filingDate"]
    rdates = rec.get("reportDate", [""] * len(forms))
    out = []
    for i, f in enumerate(forms):
        if f.startswith("13F-HR") and not f.endswith("/A"):  # 排除修正版, 只取正式
            out.append((fdates[i], accs[i], rdates[i] if i < len(rdates) else ""))
        if len(out) >= limit:
            break
    return out, d.get("name", "")


def parse_info_table(cik, accession):
    """解析某期 13F 信息表 → {issuer: {shares, value}} 聚合。value 单位美元。"""
    accn = accession.replace("-", "")
    idx = json.loads(_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json"))
    items = idx["directory"]["item"]
    xmls = [it["name"] for it in items if it["name"].lower().endswith(".xml")]
    # information table = 非 primary_doc.xml 的那个
    cands = [x for x in xmls if x.lower() != "primary_doc.xml"]
    if not cands:
        return {}
    time.sleep(0.2)
    raw = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{cands[0]}").decode("utf-8", "replace")
    # 逐条 infoTable 块解析(保证 issuer/value/shares 对齐)
    blocks = re.findall(r"<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>", raw, re.S)
    agg = {}
    rows = []
    for b in blocks:
        nm = re.search(r"<(?:\w+:)?nameOfIssuer>(.*?)</(?:\w+:)?nameOfIssuer>", b, re.S)
        vl = re.search(r"<(?:\w+:)?value>(.*?)</(?:\w+:)?value>", b, re.S)
        sh = re.search(r"<(?:\w+:)?sshPrnamt>(.*?)</(?:\w+:)?sshPrnamt>", b, re.S)
        if not nm:
            continue
        issuer = nm.group(1).strip().upper()
        try:
            value = int(re.sub(r"[^\d]", "", vl.group(1))) if vl else 0
        except Exception:
            value = 0
        try:
            shares = int(re.sub(r"[^\d]", "", sh.group(1))) if sh else 0
        except Exception:
            shares = 0
        rows.append((issuer, value, shares))
    # ── 单位自适应: 新版 13F 填美元全额, 部分旧式 filer 仍填千美元 ──
    # 判据: 若多数持仓的隐含股价(value/shares) < $1, 说明 value 是千美元 → ×1000。
    per_share = [r[1] / r[2] for r in rows if r[2] > 0 and r[1] > 0]
    scale = 1
    if per_share:
        per_share.sort()
        median_ps = per_share[len(per_share) // 2]
        if median_ps < 1.0:  # 隐含股价 <$1 → value 是千美元
            scale = 1000
    for issuer, value, shares in rows:
        if issuer not in agg:
            agg[issuer] = {"shares": 0, "value": 0}
        agg[issuer]["shares"] += shares
        agg[issuer]["value"] += value * scale
    return agg


def diff_holdings(cur, prev):
    """对比两期持仓, 返回每个 issuer 的变动 [{issuer,value,shares,prev_shares,action,pct}]。
    action: 🆕新建 / ▲加仓 / ▼减仓 / ❌清仓 / →持平。"""
    out = []
    all_issuers = set(cur) | set(prev)
    for iss in all_issuers:
        c_sh = cur.get(iss, {}).get("shares", 0)
        c_vl = cur.get(iss, {}).get("value", 0)
        p_sh = prev.get(iss, {}).get("shares", 0)
        if c_sh > 0 and p_sh == 0:
            action = "🆕新建"
        elif c_sh == 0 and p_sh > 0:
            action = "❌清仓"
        elif c_sh > p_sh:
            action = "▲加仓"
        elif c_sh < p_sh:
            action = "▼减仓"
        else:
            action = "→持平"
        pct = round((c_sh - p_sh) / p_sh * 100, 1) if p_sh else (None if c_sh else 0)
        out.append({"issuer": iss.title(), "value": c_vl, "shares": c_sh,
                    "prev_shares": p_sh, "action": action, "pct": pct})
    # 按当前市值降序(清仓的排后)
    out.sort(key=lambda x: (x["value"], x["shares"]), reverse=True)
    return out


def fetch_one(inst):
    """抓单个机构最新+上一期 13F, 算变动。返回 dict 或 {status}。"""
    try:
        filings, name = find_13f_filings(inst["cik"], limit=2)
    except Exception as e:
        return {**inst, "status": f"submissions失败:{type(e).__name__}"}
    if not filings:
        return {**inst, "status": "无13F"}
    cur_f = filings[0]
    time.sleep(0.25)
    try:
        cur = parse_info_table(inst["cik"], cur_f[1])
    except Exception as e:
        return {**inst, "status": f"解析失败:{type(e).__name__}"}
    prev = {}
    if len(filings) > 1:
        time.sleep(0.25)
        try:
            prev = parse_info_table(inst["cik"], filings[1][1])
        except Exception:
            prev = {}
    changes = diff_holdings(cur, prev)
    total_val = sum(v["value"] for v in cur.values())
    return {
        **inst, "sec_name": name, "status": "ok",
        "report_date": cur_f[2] or cur_f[0], "filing_date": cur_f[0],
        "prev_report_date": (filings[1][2] or filings[1][0]) if len(filings) > 1 else None,
        "total_value": total_val, "n_positions": len(cur),
        "top_holdings": changes[:12],  # TOP12 + 变动
        "new_buys": [c for c in changes if c["action"] == "🆕新建"][:6],
        "exits": [c for c in changes if c["action"] == "❌清仓"][:6],
    }


def fetch_all(institutions=None, save=True):
    """抓全部机构。返回 {date, institutions:[...]}。幂等: 覆盖写 holdings_13f.json。"""
    institutions = institutions or INSTITUTIONS
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    results = []
    for inst in institutions:
        r = fetch_one(inst)
        results.append(r)
        st = r.get("status")
        rd = r.get("report_date", "")
        print(f"  {inst['fund']}: {st} report={rd} positions={r.get('n_positions','-')}", flush=True)
        time.sleep(0.4)
    out = {"date": today, "institutions": results}
    if save:
        json.dump(out, open(HOLDINGS_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    return out


def load_holdings():
    """读已存的持仓数据(dashboard 用)。返回 dict 或 {}。"""
    if os.path.exists(HOLDINGS_JSON):
        try:
            return json.load(open(HOLDINGS_JSON))
        except Exception:
            pass
    return {}


def _fmt_holdings_text(items, with_val=True):
    """把持仓变动列表格式化为 Notion 文本。"""
    lines = []
    for h in items:
        pct = f" {h['pct']:+.0f}%" if h.get("pct") is not None else ""
        val = f" ${h['value']/1e6:,.0f}M" if with_val and h.get("value") else ""
        lines.append(f"{h['action']} {h['issuer']}{val}{pct}")
    return "\n".join(lines)


def write_to_notion(data=None):
    """把 holdings 数据写入 Notion 持仓 DB(幂等, 一机构一期一行)。"""
    import config as c
    import notion_writer as nw
    data = data or load_holdings()
    db = c.NOTION_DB.get("holdings")
    if not db:
        print("[13F] DB_HOLDINGS 未配置, 跳过 Notion 写入")
        return 0
    written = 0
    for r in data.get("institutions", []):
        if r.get("status") != "ok":
            continue
        title = f"{r['fund']} {r['report_date']}"
        props = {
            "KOL": nw.prop_text(r.get("kol", "")),
            "基金": nw.prop_text(r.get("fund", "")),
            "报告期": nw.prop_date(r.get("report_date")),
            "上期": nw.prop_text(r.get("prev_report_date") or "无上期"),
            "总市值_B": nw.prop_num(round(r.get("total_value", 0) / 1e9, 2)),
            "持仓数": nw.prop_num(r.get("n_positions", 0)),
            "TOP持仓与变动": nw.prop_text(_fmt_holdings_text(r.get("top_holdings", []))),
            "新建仓": nw.prop_text(_fmt_holdings_text(r.get("new_buys", [])) or "无"),
            "清仓": nw.prop_text(_fmt_holdings_text(r.get("exits", []), with_val=False) or "无"),
            "数据源": nw.prop_select("SEC 13F"),
        }
        if nw.upsert(db, title, props, title_field="机构-期"):
            written += 1
    print(f"[13F] Notion 写入 {written} 机构行")
    return written


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", help="只测一个 fund 关键字")
    args = ap.parse_args()
    insts = INSTITUTIONS
    if args.one:
        insts = [i for i in INSTITUTIONS if args.one.lower() in i["fund"].lower()]
    print(f"[13F] 抓 {len(insts)} 个机构...", flush=True)
    d = fetch_all(insts, save=not args.one)
    for r in d["institutions"]:
        if r.get("status") == "ok":
            print(f"\n=== {r['fund']} ({r['kol']}) | {r['report_date']} | ${r['total_value']/1e9:.1f}B | {r['n_positions']}持仓 ===")
            for h in r["top_holdings"][:6]:
                pct = f" {h['pct']:+.0f}%" if h["pct"] is not None else ""
                print(f"    {h['action']} {h['issuer']}: ${h['value']/1e6:.0f}M{pct}")
