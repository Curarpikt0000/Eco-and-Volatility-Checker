"""金价历次高点叠加: 纯函数, 输入 spx_gold_long['rows'] -> 各轮高点后 N 个月路径(高点月=100)。可单测。"""
PEAK_WIN = 36        # 判定「局部最高」的左右窗口(月)
MIN_DD = 0.20        # 峰后 5 年内最大回撤 >= 20% 才算「见顶」
AFTER = 36           # 叠加图向后看多少个月
BEFORE = 12          # 向前看多少个月


def find_peaks(rows):
    by = {r["m"]: r["gold"] for r in rows if r.get("gold")}
    ms = sorted(by)
    peaks = []
    for i, m in enumerate(ms):
        if m < "1968":
            continue
        lo, hi = max(0, i - PEAK_WIN), min(len(ms), i + PEAK_WIN + 1)
        if by[m] != max(by[x] for x in ms[lo:hi]):
            continue
        after = ms[i:i + 61]
        dd = min(by[x] for x in after) / by[m] - 1
        if dd <= -MIN_DD:
            peaks.append(m)
    return peaks, by, ms


def overlay(rows):
    """返回 dict: past=[{peak_m, peak, dd5y, path:{offset:val}}], cur={peak_m, peak, path, last_off, last_pct} 或 None。
    当前轮: 最近一个「局部最高」(只要求其后已有 >= 3 个月数据, 不要求已回撤 20%), 且峰值月在最近 36 个月内。"""
    peaks, by, ms = find_peaks(rows)
    idx = {m: i for i, m in enumerate(ms)}

    def path_of(pm):
        i0 = idx[pm]; base = by[pm]; p = {}
        for off in range(-BEFORE, AFTER + 1):
            j = i0 + off
            if 0 <= j < len(ms):
                p[off] = round(by[ms[j]] / base * 100, 2)
        return p

    past = []
    for pm in peaks:
        i0 = idx[pm]
        aft = ms[i0:i0 + 61]
        past.append({"peak_m": pm, "peak": by[pm], "dd5y": round((min(by[x] for x in aft) / by[pm] - 1) * 100, 1),
                     "path": path_of(pm), "trough_off": min(range(len(aft)), key=lambda k: by[aft[k]])})
    # 当前轮: 最近 36 个月内的最高点(月均), 且不在 past 里
    last = ms[-1]; i_last = idx[last]
    win = ms[max(0, i_last - 36):]
    cm = max(win, key=lambda x: by[x])
    cur = None
    if cm != last and cm not in peaks:
        pth = path_of(cm)
        lo = max(k for k in pth)
        cur = {"peak_m": cm, "peak": by[cm], "path": pth, "last_off": lo, "last_pct": round(pth[lo] - 100, 1), "last_m": last}
    return {"past": past, "cur": cur}


if __name__ == "__main__":
    import json, sys
    d = json.load(open(sys.argv[1]))
    o = overlay(d["rows"])
    for p in o["past"]:
        print("PAST", p["peak_m"], p["peak"], "5年内最大回撤", p["dd5y"], "%", "谷底在峰后", p["trough_off"], "月", "| +12月", p["path"].get(12), "+36月", p["path"].get(36))
    c = o["cur"]
    print("CUR", c and (c["peak_m"], c["peak"], "至今", c["last_off"], "月", c["last_pct"], "%", "末月", c["last_m"]))
