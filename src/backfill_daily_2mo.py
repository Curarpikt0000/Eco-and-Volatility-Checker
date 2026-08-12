"""backfill_daily_2mo.py — 回填过去 ~2 个月【每日】真值到 Notion。

Chao 需求(2026-08): backfill 过去 2 个月数据到 Notion。诚实边界:
  - ✅ 真值可回填: FRED 日度系列(VIX/HY/收益率曲线/DXY/TIPS...) + CNN F&G 历史 + 金银 COT(周度 as-of)
  - ⚠️ 反爬 web 源(AAII/CBOE/GuruFocus/BofA牛熊/Insider/Buffett/CAPE/margin) 只有当前快照,
        拿不到 2 个月前历史真值 → 每天标 status="未找到", 绝不用当前值冒充历史(那是编)。
  - ⚠️ 每日 AI 分析结论无法真实重建 → DB_REPORT 的综合结论只用【规则兜底】+ 前缀标注
        "[历史回填·非当日AI分析]", 让 Chao 一眼分清回填 vs 真·当日报告。

写入:
  - DB_INDICATORS: 每个交易日一行(FRED/COT/F&G 真值, 其余留空+信号灯按可得值算)
  - snapshots/<date>.json: 每日快照(供 dashboard 折线 + history_getter)
  - DB_REPORT: 每个交易日一行(信号灯/触发数/规则结论, 标注历史回填)

幂等: 全走 nw.upsert(按日期 title), 重跑不重复。
用法: python -m src.backfill_daily_2mo [--days 65] [--dry]
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

BACKFILL_TAG = "[历史回填·非当日AI分析]"


def _asof(history, target):
    """history: [(date,val)] 升序 → <= target 的最近值。"""
    best = None
    for d, v in history:
        if d <= target:
            best = v
        else:
            break
    return best


def trading_days(days):
    """过去 days 个自然日里的工作日(周一~周五), 升序 YYYY-MM-DD。"""
    today = datetime.date.today()
    out = []
    for i in range(days, -1, -1):
        d = today - datetime.timedelta(days=i)
        if d.weekday() < 5:  # 0-4 = Mon-Fri
            out.append(d.strftime("%Y-%m-%d"))
    return out


def build_history():
    """拉 FRED 各系列 + F&G + COT 历史(一次性), 返回可 as-of 查询的字典。"""
    start = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    print(f"[hist] 拉 FRED 日度历史 (start={start})...", flush=True)
    fred_hist = {}
    for ind in c.INDICATORS:
        if ind.get("source") == "fred":
            h = fred.fetch_fred_history(ind["fred_id"], start=start)
            fred_hist[ind["key"]] = h
            print(f"  {ind['key']}: {len(h)} 点", flush=True)
    fg_hist = webf.fetch_fear_greed_history(start=start)
    print(f"  fear_greed: {len(fg_hist)} 点", flush=True)
    # COT 金银 as-of 历史(周度)
    cot_hist = {}
    for metal in ("gold", "silver"):
        rows = cot.fetch_history(metal, weeks=14)
        cot_hist[metal] = sorted(
            [(r["as_of"], r) for r in rows], key=lambda x: x[0]
        )
        print(f"  COT {metal}: {len(rows)} 周", flush=True)
    return fred_hist, fg_hist, cot_hist


def results_for_day(day, fred_hist, fg_hist, overrides=None):
    """组装某日 results(仅真值可得的填, 其余标 未找到)。
    overrides: manual_overrides.json。对反爬/search 源, 若其 as_of 与 day 相近(±7天)则用其值兜底,
    避免把 backfill 的 None 覆盖掉 agent 已抓到的真值(如 BofA Bull&Bear=9.7)。更早历史仍留空(诚实)。"""
    import datetime as _dt
    overrides = overrides or {}

    def _near(as_of, target, days=7):
        if not as_of:
            return False
        try:
            a = _dt.date.fromisoformat(as_of[:10])
            t = _dt.date.fromisoformat(target[:10])
            return abs((t - a).days) <= days
        except Exception:
            return False

    results = {}
    for ind in c.INDICATORS:
        key = ind["key"]
        v = None
        if key in fred_hist:
            v = _asof(fred_hist[key], day)
        elif key == "fear_greed":
            v = _asof(fg_hist, day)
        if v is not None:
            results[key] = {"key": key, "value": v, "as_of": day, "status": "ok"}
        elif key in overrides and overrides[key].get("value") is not None and _near(overrides[key].get("as_of"), day):
            # 反爬/search 源: overrides 有近日真值 → 用它兜底(不覆盖 agent 已抓到的真值)
            ov = dict(overrides[key])
            ov["key"] = key
            results[key] = ov
        else:
            # 反爬/月度源无历史真值 → 诚实留空
            results[key] = {"key": key, "value": None, "as_of": None, "status": "未找到"}
    return results


def cot_for_day(day, cot_hist):
    """某日 as-of 的金银 COT(用于触发判定)。"""
    out = {}
    for metal in ("gold", "silver"):
        best = None
        for d, r in cot_hist.get(metal, []):
            if d <= day:
                best = r
            else:
                break
        if best:
            out[metal] = best
    return out


def write_indicators_row(db, day, results, dry):
    props = {}
    for ind in c.INDICATORS:
        r = results[ind["key"]]
        props[ind["name_en"]] = nw.prop_num(r["value"])
        lt = signals.light(ind, r["value"])
        props[ind["name_en"] + " 信号"] = nw.prop_select(lt)
    trig = sum(1 for ind in c.INDICATORS if signals.light(ind, results[ind["key"]]["value"]) == "🔴")
    props["触发计数"] = nw.prop_num(trig)
    if dry:
        return "DRY"
    return nw.upsert(db, day, props)


def write_report_row(db, day, results, cot_results, dry):
    """规则兜底报告行, 结论前缀标注历史回填。"""
    getter = _snap_getter()
    gstats = signals.group_stats(results)
    checks, hit = signals.eval_sell_triggers(results, cot_results, getter)
    overall = signals.overall_signal(hit, gstats)

    def alerts_for(g):
        lines = []
        for ind in c.indicators_by_group(g):
            r = results.get(ind["key"], {})
            lt = signals.light(ind, r.get("value"))
            if lt in ("🟡", "🔴"):
                lines.append(f"{lt}{ind['name_zh']}={r.get('value')}")
        return "；".join(lines) if lines else "无警报"

    concl = f"{BACKFILL_TAG} 卖出触发 {hit}/7。" + (
        "⚠️达到分批卖出阈值(≥3)" if hit >= c.SELL_START_THRESHOLD else "未达分批卖出阈值")
    focus = "；".join(f"{cond}: {desc}" for cond, thr, desc, st in checks if st in ("✅", "⚠️"))[:1800]
    focus = (f"{BACKFILL_TAG} " + (focus or "无接近触发项"))[:1900]
    props = {
        "综合信号": nw.prop_select(overall),
        "卖出触发数": nw.prop_num(hit),
        "短期警报": nw.prop_text(alerts_for("short")),
        "中期警报": nw.prop_text(alerts_for("mid")),
        "长期警报": nw.prop_text(alerts_for("long")),
        "综合结论": nw.prop_text(concl),
        "今日焦点": nw.prop_text(focus),
    }
    if dry:
        return "DRY", hit, overall
    return nw.upsert(db, day, props), hit, overall


def _snap_getter():
    def getter(key):
        out = []
        for f in sorted(os.listdir(SNAP_DIR)):
            if f.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(SNAP_DIR, f)))
                    v = d.get("results", {}).get(key, {}).get("value")
                    if v is not None:
                        out.append((f[:-5], v))
                except Exception:
                    continue
        return out
    return getter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=65, help="回填过去 N 自然日(取其中工作日)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    fred_hist, fg_hist, cot_hist = build_history()
    # 读 overrides(agent 已抓的反爬/search 源真值), 用于近日兜底避免覆盖
    ov_path = os.path.join(os.path.dirname(__file__), "..", "data", "manual_overrides.json")
    overrides = {}
    if os.path.exists(ov_path):
        try:
            overrides = json.load(open(ov_path))
        except Exception:
            overrides = {}
    days = trading_days(args.days)
    print(f"[backfill-daily] 回填 {len(days)} 个交易日: {days[0]} ~ {days[-1]}", flush=True)

    db_ind = c.NOTION_DB["indicators"]
    db_rep = c.NOTION_DB["report"]
    wi = wr = 0
    for i, day in enumerate(days, 1):
        results = results_for_day(day, fred_hist, fg_hist, overrides)
        cotr = cot_for_day(day, cot_hist)
        # 先存快照(供后续 report 的 history_getter + dashboard 折线)
        snap = {"date": day, "results": results, "cot": cotr, "generated_at": "backfill-daily"}
        json.dump(snap, open(os.path.join(SNAP_DIR, f"{day}.json"), "w"),
                  ensure_ascii=False, indent=2, default=str)
        r1 = write_indicators_row(db_ind, day, results, args.dry)
        if r1:
            wi += 1
        r2, hit, overall = write_report_row(db_rep, day, results, cotr, args.dry)
        if r2:
            wr += 1
        if i % 5 == 0 or i == len(days):
            print(f"  [{i}/{len(days)}] {day} 触发{hit}/7 {overall} (ind={wi} rep={wr})", flush=True)
        if not args.dry:
            time.sleep(0.35)
    print(f"[backfill-daily] DONE 指标{wi} 报告{wr}", flush=True)


if __name__ == "__main__":
    main()
