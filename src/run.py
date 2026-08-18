"""run.py — 每日主流程。

抓数(FRED+web+COT) → 算信号灯 → 算卖出触发 → 写 Notion 3 DB → 存快照供 dashboard。

用法:
  python -m src.run              # 每日跑
  python -m src.run --date 2026-08-07   # 指定日期(backfill 用)

纪律: 绝不编数字，取不到标 status。写后读回验证。时区 JST。
"""
import sys, os, json, argparse, datetime, time
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from fetchers import fred, cot
from fetchers import web as webf
from fetchers.util import with_timeout
import signals
import notion_writer as nw

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SNAP_DIR = os.path.join(DATA_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)


def jst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def load_manual_overrides():
    """agent 模式每日搜 BofA/AD line 后写入的值。{key:{value,as_of,status}}。"""
    p = os.path.join(DATA_DIR, "manual_overrides.json")
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            return {}
    return {}


def fetch_all():
    """抓 18 指标，返回 {key: {value, as_of, status, extra}}。"""
    results = {}
    overrides = load_manual_overrides()
    for ind in c.INDICATORS:
        key = ind["key"]
        src = ind["source"]
        if src == "fred":
            r = fred.fetch(ind)
        elif src == "web":
            fn = webf.WEB_FETCHERS.get(key)
            r = with_timeout(fn, timeout=90) if fn else {"value": None, "status": "无fetcher"}
            if r is None:
                r = {"value": None, "as_of": None, "status": "超时"}
            # web 源抓取失败 → 回退到 agent 补的 overrides(web_extract 更稳)
            if r.get("value") is None and key in overrides:
                ov = overrides[key]
                if ov.get("value") is not None or "付费" in str(ov.get("status", "")):
                    r = dict(ov)
        elif src in ("search", "derived"):
            # search: 由 agent 每日搜写入 overrides; derived: 下面单独算
            r = overrides.get(key, {"value": None, "as_of": None, "status": "待agent搜索" if src == "search" else "待派生"})
        else:
            r = {"value": None, "as_of": None, "status": "未知源"}
        r["key"] = key
        results[key] = r
        time.sleep(0.5)

    # ── 派生指标 ──
    # sofr_iorb = (SOFR - IORB) * 100 bps (货币市场压力)
    try:
        sofr_v, sofr_d = fred.fetch_fred_latest("SOFR")
        iorb_v, iorb_d = fred.fetch_fred_latest("IORB")
        if sofr_v is not None and iorb_v is not None:
            spread_bps = round((sofr_v - iorb_v) * 100, 1)
            results["sofr_iorb"] = {
                "key": "sofr_iorb", "value": spread_bps,
                "as_of": max(str(sofr_d), str(iorb_d)), "status": "ok",
                "extra": {"sofr": sofr_v, "iorb": iorb_v,
                          "sofr_as_of": str(sofr_d), "iorb_as_of": str(iorb_d)},
            }
        else:
            results["sofr_iorb"] = {"key": "sofr_iorb", "value": None,
                                    "as_of": None, "status": "SOFR/IORB取数失败"}
    except Exception as e:
        results["sofr_iorb"] = {"key": "sofr_iorb", "value": None,
                                "as_of": None, "status": f"错误:{e}"}

    # bank_funding_stress = (DCPF3M - DTB3) * 100 bps (银行无担保融资压力, 代理 swap spread)
    try:
        cp_v, cp_d = fred.fetch_fred_latest("DCPF3M")
        tb_v, tb_d = fred.fetch_fred_latest("DTB3")
        sofr_sv, _ = fred.fetch_fred_latest("SOFR")
        if cp_v is not None and tb_v is not None:
            bfs_bps = round((cp_v - tb_v) * 100, 1)
            results["bank_funding_stress"] = {
                "key": "bank_funding_stress", "value": bfs_bps,
                "as_of": max(str(cp_d), str(tb_d)), "status": "ok",
                "extra": {"cp3m": cp_v, "tbill3m": tb_v, "sofr": sofr_sv,
                          "spread_bps": bfs_bps},
            }
        else:
            results["bank_funding_stress"] = {"key": "bank_funding_stress", "value": None,
                                              "as_of": None, "status": "CP/Tbill取数失败"}
    except Exception as e:
        results["bank_funding_stress"] = {"key": "bank_funding_stress", "value": None,
                                          "as_of": None, "status": f"错误:{e}"}

    # margin_gdp = margin_debt / 名义GDP * 100
    md = results.get("margin_debt", {}).get("value")
    if md is not None:
        gdp_v, _ = fred.fetch_fred_latest("GDP")  # 十亿$ 年化
        if gdp_v:
            results["margin_gdp"] = {"key": "margin_gdp",
                                     "value": round(md / gdp_v * 100, 2),
                                     "as_of": jst_today(), "status": "ok"}

    # ad_line 顶背离 = 用真数据市场广度(RSP/SPY)覆盖旧的无依据 override 布尔
    # (2026-08 Chao 质疑: 原 ad_line 只有 web_search 主观布尔 True、无图无数据。
    #  改用东财 RSP/SPY 广度比数值化判定, 可复现、可回溯。抓不到则保留旧值不覆盖成空。)
    try:
        import external_data as _ed
        mb = _ed.fetch_market_breadth()
        if mb.get("status") == "ok" and mb.get("divergence") is not None:
            ev = mb.get("evidence", {})
            results["ad_line"] = {
                "key": "ad_line",
                "value": bool(mb["divergence"]),  # True=顶背离
                "as_of": mb.get("as_of", ""),
                "status": "ok",
                "extra": {
                    "source": "RSP/SPY 广度比(东方财富真数据)",
                    "spy_lookback_high": ev.get("spy_lookback_high"),
                    "spy_recent_high": ev.get("spy_recent_high"),
                    "spy_made_new_high": ev.get("spy_made_new_high"),
                    "ratio_gap_from_high_pct": ev.get("ratio_gap_from_high_pct"),
                    "breadth_confirmed": ev.get("breadth_confirmed"),
                    "rule": ev.get("rule"),
                    "stale": mb.get("stale", False),
                },
            }
        # 抓不到(status!=ok): 不动 results["ad_line"], 保留 override/旧值(绝不覆盖成空)
    except Exception as e:
        pass  # 广度抓取异常不影响主流程, ad_line 保留原值

    return results


def fetch_cot_all():
    out = {}
    for metal in ("gold", "silver"):
        r = cot.fetch_latest(metal)
        out[metal] = r
    return out


def build_notion_indicator_row(date_str, results):
    props = {}
    trig_lights = 0
    for ind in c.INDICATORS:
        r = results.get(ind["key"], {})
        v = r.get("value")
        props[ind["name_en"]] = nw.prop_num(v)
        lt = signals.light(ind, v)
        props[ind["name_en"] + " 信号"] = nw.prop_select(lt)
        if lt == "🔴":
            trig_lights += 1
    props["触发计数"] = nw.prop_num(trig_lights)
    return props


def write_indicators(date_str, results):
    db = c.NOTION_DB["indicators"]
    props = build_notion_indicator_row(date_str, results)
    pid = nw.upsert(db, date_str, props)
    return pid


def write_cot(cot_results):
    db = c.NOTION_DB["cot"]
    written = []
    for metal, r in cot_results.items():
        if not r:
            continue
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
            written.append(title)
    return written


def history_getter_factory():
    """给 signals 用的历史读取器(从 snapshots 读)。"""
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


def write_report(date_str, results, cot_results, checks, hit, gstats, overall):
    db = c.NOTION_DB["report"]

    def alerts_for(g):
        lines = []
        for ind in c.indicators_by_group(g):
            r = results.get(ind["key"], {})
            lt = signals.light(ind, r.get("value"))
            if lt in ("🟡", "🔴"):
                lines.append(f"{lt}{ind['name_zh']}={r.get('value')}")
        return "；".join(lines) if lines else "无警报"

    concl = f"卖出触发 {hit}/7。" + ("⚠️达到分批卖出阈值(≥3)" if hit >= c.SELL_START_THRESHOLD else "未达分批卖出阈值")
    # 今日焦点: 最接近触发的
    focus = "；".join(f"{cond}: {desc}" for cond, thr, desc, st in checks if st in ("✅", "⚠️"))[:1900] or "无接近触发项"

    props = {
        "综合信号": nw.prop_select(overall),
        "卖出触发数": nw.prop_num(hit),
        "短期警报": nw.prop_text(alerts_for("short")),
        "中期警报": nw.prop_text(alerts_for("mid")),
        "长期警报": nw.prop_text(alerts_for("long")),
        "综合结论": nw.prop_text(concl),
        "今日焦点": nw.prop_text(focus),
    }
    return nw.upsert(db, date_str, props)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-notion", action="store_true")
    args = ap.parse_args()
    date_str = args.date or jst_today()

    print(f"[run] {date_str} 开始抓数...", flush=True)
    results = fetch_all()
    cot_results = fetch_cot_all()

    # 存快照(供 dashboard + 历史判定)
    snap = {"date": date_str, "results": results,
            "cot": {m: r for m, r in cot_results.items() if r},
            "generated_at": datetime.datetime.utcnow().isoformat()}
    json.dump(snap, open(os.path.join(SNAP_DIR, f"{date_str}.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    # 信号 + 触发
    getter = history_getter_factory()
    gstats = signals.group_stats(results)
    checks, hit = signals.eval_sell_triggers(results, cot_results, getter)
    overall = signals.overall_signal(hit, gstats)

    print(f"[run] 综合信号={overall} 卖出触发={hit}/7", flush=True)
    for ind in c.INDICATORS:
        r = results.get(ind["key"], {})
        print(f"  {signals.light(ind, r.get('value'))} {ind['key']:16s} {r.get('value')} ({r.get('status')})", flush=True)

    if not args.no_notion:
        write_indicators(date_str, results)
        wc = write_cot(cot_results)
        write_report(date_str, results, cot_results, checks, hit, gstats, overall)
        print(f"[notion] 指标+报告已写; COT写入: {wc}", flush=True)

    return snap, checks, hit, gstats, overall


if __name__ == "__main__":
    main()
