"""daily_brief.py — 输出当日扫描的结构化简报数据(JSON)，供 cron agent 润色成人话。

确定性：所有数字来自最新快照 + Notion，AI 不碰数字(零编造风险)。
高信噪比：平静日只给核心锚点；有触发/异动才展开。
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
import config as c
import signals

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")


def jst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def latest_snapshot():
    files = sorted([f for f in os.listdir(SNAP_DIR) if f.endswith(".json")])
    if not files:
        return None
    return json.load(open(os.path.join(SNAP_DIR, files[-1])))


def prev_snapshot():
    files = sorted([f for f in os.listdir(SNAP_DIR) if f.endswith(".json")])
    if len(files) < 2:
        return None
    return json.load(open(os.path.join(SNAP_DIR, files[-2])))


def build():
    snap = latest_snapshot()
    if not snap:
        return {"error": "无快照"}
    results = snap["results"]
    cot = snap.get("cot", {})
    prev = prev_snapshot()
    prev_res = prev["results"] if prev else {}

    getter = None
    gstats = signals.group_stats(results)
    checks, hit = signals.eval_sell_triggers(results, cot, None)
    overall = signals.overall_signal(hit, gstats)

    # 核心锚点(始终给)
    def anchor(key):
        r = results.get(key, {})
        ind = next((i for i in c.INDICATORS if i["key"] == key), None)
        v = r.get("value")
        pv = prev_res.get(key, {}).get("value")
        arrow = "→"
        if v is not None and pv is not None:
            arrow = "↑" if v > pv else ("↓" if v < pv else "→")
        lt = signals.light(ind, v) if ind else "⚪"
        return {"name": ind["name_zh"] if ind else key, "value": v, "arrow": arrow, "light": lt}

    anchors = [anchor(k) for k in ["vix", "fear_greed", "hy_oas", "buffett", "cape", "yield_curve", "bofa_bull_bear"]]

    # 触发/警报(展开条件)
    triggered = [(cond, desc) for cond, thr, desc, st in checks if st == "✅"]
    near = [(cond, desc) for cond, thr, desc, st in checks if st == "⚠️"]

    # COT 异动
    cot_alerts = []
    for metal in ("gold", "silver"):
        r = cot.get(metal)
        if r and r.get("comm_surge"):
            cot_alerts.append({"metal": metal, "comm_net_wow": r.get("comm_net_wow"),
                               "comm_net": r.get("comm_net")})

    return {
        "date": snap["date"],
        "overall": overall,
        "hit": hit,
        "sell_threshold_reached": hit >= c.SELL_START_THRESHOLD,
        "group_stats": {g: {"safe": gstats[g][0], "total": gstats[g][1]} for g in gstats},
        "anchors": anchors,
        "triggered": triggered,
        "near": near,
        "cot_alerts": cot_alerts,
        "calm": (hit == 0 and not cot_alerts and not near),
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2, default=str))
