#!/usr/bin/env python3
"""eco-vol COT 周度异动哨兵 (no_agent, 零 LLM 成本; 只读 CFTC, 不写 Notion)。
★2026-10-14 立(Chao「自动」): 做市商/对冲基金/商业 净持仓的「周变动」超过近 3 年周变动标准差的 2 倍才发消息。
  阈值校准(近 156 周): 各指标 |Δ|>2σ 的周占 4.5%~7.7%, 即约每 3~4 个月一次/指标; 不用相对变动%
  (白银对冲基金净多只有几千手, 相对变动>15% 的周占 44.5%, 会天天刷屏)。
调度: 周六 06:00 JST = 美东周五 17:00, CFTC 当周五 15:30 ET 已发布。
输出: 无异动 → 完全静默(exit 0, 不打印); 有异动 → 一段简短中文; 数据没更新到最新周二 → 静默(下周再看),
      但 CFTC 取数失败 → 一行 ❌ (避免「查不到=没异动」的误判)。
状态: scratch/cot_sentinel_state.json 记录已报告的 COT 日期, 同一期不重复报。
"""
import sys, os, json, statistics as st, datetime as dt
ROOT = "<PROJECT_ROOT>"
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "src"))
STATE = "scratch/cot_sentinel_state.json"; os.makedirs("scratch", exist_ok=True)
K = 2.0
try:
    import external_data as ed
    d = ed.fetch_cot_managed_money(years=3)
except Exception as e:
    print("❌ COT 哨兵: 取数异常 %s: %s" % (type(e).__name__, str(e)[:100])); sys.exit(1)
if not d or not all(m in d and d[m].get("status", "").startswith("ok") for m in ("gold", "silver")):
    print("❌ COT 哨兵: CFTC 取数状态非 ok(%s)" % ({m: (d or {}).get(m, {}).get("status") for m in ("gold", "silver")})); sys.exit(1)
latest = d["silver"]["latest"]["d"]
try:
    st_ = json.load(open(STATE))
except Exception:
    st_ = {}
if st_.get("last_reported") == latest:
    sys.exit(0)
# 数据新鲜度: 最新一期应在 10 天内(周二持仓周五发布), 否则 CFTC 可能晚发/休假 → 静默等下周
if (dt.date.today() - dt.date.fromisoformat(latest)).days > 10:
    sys.exit(0)
NAMES = {"sd_net": "做市商(掉期商)净持仓", "mm_net": "对冲基金净多", "pm_net": "生产商/商业净持仓"}
def series(c, key):
    if key == "pm_net": return [x["pm_long"] - x["pm_short"] for x in c]
    return [x[key] for x in c]
hits, rows = [], []
for m, mn in (("silver", "白银"), ("gold", "黄金")):
    c = d[m]["cot"]
    for key in ("sd_net", "mm_net", "pm_net"):
        s = series(c, key); w = [s[i] - s[i - 1] for i in range(1, len(s))]
        sd = st.pstdev(w); z = w[-1] / sd if sd else 0
        rows.append((mn, NAMES[key], s[-1], w[-1], z))
        if abs(z) > K:
            hits.append((mn, NAMES[key], s[-2], s[-1], w[-1], z, c[-2]["d"]))
# 无论有无异动都更新状态, 避免同一期重复评估
json.dump({"last_reported": latest, "n_hits": len(hits)}, open(STATE, "w"))
if not hits:
    sys.exit(0)
print("📊 COT 异动 · %s 周二持仓(周变动 > %.0f 倍标准差)" % (latest, K))
for mn, nm, a, b, dlt, z, pd in hits:
    print("· %s %s:%+d → %+d(周变动 %+d 手,%.1f 倍σ)" % (mn, nm, a, b, dlt, z))
print("口径: CFTC Disaggregated, 周二持仓; 做市商=Swap Dealer。仅陈述持仓变化, 不推断动机。")
