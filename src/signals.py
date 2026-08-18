"""signals.py — 信号灯 + 卖出触发判定。纯逻辑，不碰网络。

信号灯规则(基于 config 静态阈值):
  high_bad: value>=trigger→🔴; >=warn→🟡; 否则🟢
  low_bad:  value<=trigger→🔴; <=warn→🟡; 否则🟢
  无值→⚪
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config as c


def light(indicator, value):
    """返回 🟢/🟡/🔴/⚪。"""
    if value is None:
        return "⚪"
    warn, trig, d = indicator.get("warn"), indicator.get("trigger"), indicator.get("direction")
    if warn is None or trig is None:
        return "⚪"  # 无阈值(如 margin_debt 绝对值/ipo)靠派生或人工
    if d == "high_bad":
        if value >= trig:
            return "🔴"
        if value >= warn:
            return "🟡"
        return "🟢"
    else:  # low_bad
        if value <= trig:
            return "🔴"
        if value <= warn:
            return "🟡"
        return "🟢"


def group_stats(results):
    """按组统计未警报数。results: {key: {value,...}}。返回 {group: (safe, total)}。"""
    out = {}
    for g in ("short", "mid", "long"):
        inds = c.indicators_by_group(g)
        total = len(inds)
        safe = 0
        for ind in inds:
            r = results.get(ind["key"], {})
            lt = light(ind, r.get("value"))
            if lt == "🟢":
                safe += 1
        out[g] = (safe, total)
    return out


def eval_sell_triggers(results, cot_results, history_getter=None):
    """判定 7 项硬性卖出触发。返回 [(cond, state, hit_bool), ...] + hit_count。
    state: ❌未触发 / ⚠️接近 / ✅触发
    history_getter(key)->[(date,val)] 供需要历史的判定(margin 连降/fg 回落)。
    """
    def get(k):
        return results.get(k, {}).get("value")

    checks = []
    hit = 0

    # 1. VIX > 25
    vix = get("vix")
    s = "✅" if (vix is not None and vix > 25) else ("⚠️" if vix is not None and vix > 20 else "❌")
    checks.append(("VIX 突破并站稳 > 25", "> 25", f"{vix}" if vix is not None else "无数据", s))
    if s == "✅": hit += 1

    # 2. Margin Debt 连续 3 个月下降
    mstate = "❌"; mdesc = "数据不足"
    if history_getter:
        hist = history_getter("margin_debt")
        if hist and len(hist) >= 4:
            vals = [v for _, v in hist[-4:]]
            downs = sum(1 for i in range(1, 4) if vals[i] < vals[i-1])
            if downs >= 3:
                mstate = "✅"; hit += 1
            elif downs >= 2:
                mstate = "⚠️"
            mdesc = f"近3月方向 {downs}/3 降"
    checks.append(("Margin Debt 连续 3 个月下降", "连续3月", mdesc, mstate))

    # 3. HY Spread > 4.5%
    hy = get("hy_oas")
    s = "✅" if (hy is not None and hy > 4.5) else ("⚠️" if hy is not None and hy > 4.0 else "❌")
    checks.append(("HY Spread 扩张 > 4.5%", "> 4.5%", f"{hy}%" if hy is not None else "无数据", s))
    if s == "✅": hit += 1

    # 4. Fear&Greed 从 >75 回落到 <50
    fg = get("fear_greed")
    fgstate = "❌"; fgdesc = f"{fg}" if fg is not None else "无数据"
    if history_getter and fg is not None:
        hist = history_getter("fear_greed")
        if hist:
            recent_high = any(v > 75 for _, v in hist[-30:])
            if recent_high and fg < 50:
                fgstate = "✅"; hit += 1
            elif fg > 75:
                fgstate = "⚠️"; fgdesc = f"{fg}(高位)"
    checks.append(("Fear&Greed 从>75回落<50", ">75→<50", fgdesc, fgstate))

    # 5. A/D Line 顶背离 (RSP/SPY 广度比真数据, 见 run.py 注入; 抓不到回退 override)
    ad = results.get("ad_line", {})
    adval = ad.get("value")  # True=背离
    adx = ad.get("extra", {}) or {}
    s = "✅" if adval is True else ("❌" if adval is False else "❌")
    if adval is True:
        addesc = "顶背离"
    elif adval is False:
        addesc = "广度确认(无背离)"
    else:
        addesc = "无数据"
    # 附证据来源(真数据时)
    if adx.get("source") and adval is not None:
        gap = adx.get("ratio_gap_from_high_pct")
        addesc += f"｜{adx['source']}"
        if gap is not None:
            addesc += f"(广度比距高点{gap}%)"
        if adx.get("stale"):
            addesc += "[缓存]"
    checks.append(("A/D Line 顶背离", "背离", addesc, s))
    if s == "✅": hit += 1

    # 6. BofA Bull&Bear > 8.0
    bb = get("bofa_bull_bear")
    s = "✅" if (bb is not None and bb > 8.0) else ("⚠️" if bb is not None and bb > 7.0 else "❌")
    checks.append(("BofA Bull&Bear > 8.0", "> 8.0", f"{bb}" if bb is not None else "无数据", s))
    if s == "✅": hit += 1

    # 7. Insider Buy/Sell < 0.17
    ins = get("insider")
    s = "✅" if (ins is not None and ins < 0.17) else ("⚠️" if ins is not None and ins < 0.25 else "❌")
    checks.append(("Insider Buy/Sell < 0.17", "< 0.17", f"{ins}" if ins is not None else "无数据", s))
    if s == "✅": hit += 1

    return checks, hit


def overall_signal(hit_count, group_stats_d):
    """综合信号。触发>=3→🔴减仓; 有🔴组或触发>=1→🟡; 否则🟢。"""
    if hit_count >= c.SELL_START_THRESHOLD:
        return "🔴 减仓"
    if hit_count >= 1:
        return "🟡 警戒"
    return "🟢 平静"
