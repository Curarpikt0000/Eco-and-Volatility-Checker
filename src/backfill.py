"""backfill.py — 回填过去一年历史到 Notion。

策略:
  - FRED 指标(VIX/HY/收益率曲线): 拉一年日度历史
  - CNN F&G: 拉一年历史
  - COT 金银: 一年周度(CFTC 本就周频)
  - 指标 DB 按【周】采样(每周五 as-of 最近值)，约 52 行，信噪比足够且写入快
  - 月度源(Buffett/CAPE/LEI/margin): 当前无历史 API → 仅当日值，历史留空(诚实)
  - overrides 里的 search 源(BofA/AD): 无历史 → 留空

用法: python -m src.backfill [--weeks 52]
"""
import sys, os, json, datetime, argparse, time
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from fetchers import fred, cot
from fetchers import web as webf
import notion_writer as nw
import signals

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)


def val_asof(history, target_date):
    """history: [(date,val)] 升序。返回 <= target_date 的最近值，无则 None。"""
    best = None
    for d, v in history:
        if d <= target_date:
            best = v
        else:
            break
    return best


def week_fridays(weeks):
    """返回过去 weeks 周的每周五日期(升序, YYYY-MM-DD)。"""
    today = datetime.date.today()
    # 最近的周五
    offset = (today.weekday() - 4) % 7
    last_fri = today - datetime.timedelta(days=offset)
    out = []
    for i in range(weeks, -1, -1):
        out.append((last_fri - datetime.timedelta(weeks=i)).strftime("%Y-%m-%d"))
    return out


def backfill_indicators(weeks=52):
    start = (datetime.date.today() - datetime.timedelta(weeks=weeks + 2)).strftime("%Y-%m-%d")
    print(f"[backfill] 拉 FRED 历史 (start={start})...", flush=True)

    # 拉各 FRED 系列历史
    fred_hist = {}
    for ind in c.INDICATORS:
        if ind["source"] == "fred":
            h = fred.fetch_fred_history(ind["fred_id"], start=start)
            fred_hist[ind["key"]] = h
            print(f"  {ind['key']}: {len(h)} 点", flush=True)

    # CNN F&G 历史
    fg_hist = webf.fetch_fear_greed_history(start=start)
    print(f"  fear_greed: {len(fg_hist)} 点", flush=True)

    db = c.NOTION_DB["indicators"]
    fridays = week_fridays(weeks)
    print(f"[backfill] 写 {len(fridays)} 周指标行...", flush=True)
    written = 0
    for wd in fridays:
        results = {}
        for ind in c.INDICATORS:
            key = ind["key"]
            v = None
            if key in fred_hist:
                v = val_asof(fred_hist[key], wd)
            elif key == "fear_greed":
                v = val_asof(fg_hist, wd)
            results[key] = {"key": key, "value": v,
                            "as_of": wd if v is not None else None,
                            "status": "ok" if v is not None else "无历史"}
        # 派生 margin_gdp 历史不算(无 margin 历史)
        props = {}
        trig = 0
        for ind in c.INDICATORS:
            r = results[ind["key"]]
            props[ind["name_en"]] = nw.prop_num(r["value"])
            lt = signals.light(ind, r["value"])
            props[ind["name_en"] + " 信号"] = nw.prop_select(lt)
            if lt == "🔴":
                trig += 1
        props["触发计数"] = nw.prop_num(trig)
        pid = nw.upsert(db, wd, props)
        if pid:
            written += 1
        # 存快照
        snap = {"date": wd, "results": results, "cot": {},
                "generated_at": "backfill"}
        json.dump(snap, open(os.path.join(SNAP_DIR, f"{wd}.json"), "w"),
                  ensure_ascii=False, indent=2, default=str)
        if written % 10 == 0:
            print(f"    ...{written}/{len(fridays)}", flush=True)
        time.sleep(0.35)
    print(f"[backfill] 指标写入 {written}/{len(fridays)}", flush=True)
    return written


def backfill_cot(weeks=55):
    db = c.NOTION_DB["cot"]
    total = 0
    for metal in ("gold", "silver"):
        rows = cot.fetch_history(metal, weeks=weeks)
        print(f"[backfill] {metal} COT: {len(rows)} 周", flush=True)
        for r in rows:
            title = f"{metal} {r['as_of']}"
            props = {
                "Metal": nw.prop_select(metal),
                "Report Date": nw.prop_date(r["as_of"]),
                "Open Interest": nw.prop_num(r["open_interest"]),
                "Comm Long": nw.prop_num(r["comm_long"]),
                "Comm Short": nw.prop_num(r["comm_short"]),
                "Comm Net": nw.prop_num(r["comm_net"]),
                "Comm Net WoW": nw.prop_num(r.get("comm_net_wow")),
                "Comm Long WoW": nw.prop_num(r.get("comm_long_wow")),
                "Comm Short WoW": nw.prop_num(r.get("comm_short_wow")),
                "NonComm Net": nw.prop_num(r.get("noncomm_net")),
                "Surge": nw.prop_select("⚠️突增" if r.get("comm_surge") else "正常"),
            }
            pid = nw.upsert(db, title, props)
            if pid:
                total += 1
            time.sleep(0.3)
    print(f"[backfill] COT 写入 {total}", flush=True)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=52)
    ap.add_argument("--only", choices=["ind", "cot"], default=None)
    args = ap.parse_args()
    if args.only != "cot":
        backfill_indicators(args.weeks)
    if args.only != "ind":
        backfill_cot(args.weeks + 3)
    print("[backfill] DONE", flush=True)


if __name__ == "__main__":
    main()
