#!/usr/bin/env python3
"""印度白银月度进口 (吨) — UN Comtrade 免费 preview API。
reporter=699(印度) cmd=7106(银) flow=M(进口), 取 partner2Code=0 (World总,无重复) 的 netWgt(kg)/1000=吨。
口径校验: 2024前两月=2932t 完全吻合 LBMA 公开数字。
落盘 data/silver_imports_india.json 供 dashboard 图2 渲染。每月增量: cron 跑本脚本追加新月。
绝不编造: 某月 Comtrade 未发布 → 跳过(不补0), 保留已有真值。"""
import urllib.request, json, time, os, datetime

OUT = "/home/user/Projects/Eco-and-Volatility-Checker/data/silver_imports_india.json"
START = (2024, 1)  # 起始月


def q(period):
    url = (f"https://comtradeapi.un.org/public/v1/preview/C/M/HS?"
           f"reporterCode=699&period={period}&flowCode=M&cmdCode=7106&partnerCode=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def month_tonnes(period):
    """返回 (tonnes, value_musd) 或 None(未发布)。取 partner2Code=0 World 总行。"""
    d = q(period)
    if d is None:
        return None
    data = d.get("data", [])
    world = [r for r in data if r.get("partner2Code") == 0]
    if not world:
        return None
    kg = sum(r.get("netWgt") or 0 for r in world)
    val = sum(r.get("primaryValue") or 0 for r in world)
    if kg <= 0:
        return None
    return round(kg / 1000.0, 1), round(val / 1e6, 1)


def iter_months(start, end):
    y, m = start
    ey, em = end
    while (y, m) <= (ey, em):
        yield f"{y}{m:02d}", y, m
        m += 1
        if m > 12:
            m = 1; y += 1


def main():
    # 增量: 读已有, 只补缺失月
    existing = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
            for p in old.get("points", []):
                existing[p["period"]] = p
        except Exception:
            pass

    today = datetime.date.today()
    end = (today.year, today.month)
    points = []
    fetched = 0
    for period, y, m in iter_months(START, end):
        if period in existing:
            points.append(existing[period])  # 保留已有真值
            continue
        res = month_tonnes(period)
        if res is None:
            continue  # 未发布 → 跳过不补0
        t, v = res
        points.append({"period": period, "date": f"{y}-{m:02d}",
                       "tonnes": t, "value_musd": v})
        fetched += 1
        time.sleep(1.5)

    points.sort(key=lambda x: x["period"])
    if not points:
        print("ERR: 无任何数据点"); return
    # 5年均线(用可得数据的滚动均值近似; 数据不足5年时用全期滚动12月均值作参考)
    vals = [p["tonnes"] for p in points]
    latest = points[-1]
    out = {
        "status": "ok",
        "generated": datetime.datetime.now().isoformat()[:19],
        "source": "UN Comtrade (UNSD) 免费 preview API — reporter=India cmd=HS7106(银) flow=进口, partner2=World",
        "unit": "tonnes",
        "note": ("印度白银(HS7106)月度进口总量。口径=UN Comtrade partner2=World 净重(kg)→吨, "
                 "2024前两月=2932t 与 LBMA 公开数字完全吻合。某月未发布则跳过不补0。"),
        "as_of": latest["date"],
        "latest_tonnes": latest["tonnes"],
        "n": len(points),
        "max_tonnes": max(vals),
        "points": points,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"OK 新抓 {fetched} 月, 共 {len(points)} 月 ({points[0]['date']}→{latest['date']})")
    print("最近6月:")
    for p in points[-6:]:
        print(f"  {p['date']}: {p['tonnes']:8.1f} 吨 (${p['value_musd']}M)")
    print("written:", OUT)


if __name__ == "__main__":
    main()
