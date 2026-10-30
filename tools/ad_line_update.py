#!/usr/bin/env python3
"""S&P500 A/D 腾落线 · 本地增量更新器 (Chao 2026-10-30: 每张图每天有人看管, 不再依赖他人目录/cron)。

背景: 原数据由 Economic-Dashboard 的 ad_backfill.py 写, 依赖 ~/.hermes/skills/moomooapi 的成分股 CSV,
  该目录在本机不存在, 每日 cron 也已不存在 → 数据停在 2026-10-01(滞后 29 天)。
本脚本: 成分股取自维基(503 只, 缓存本地) → yfinance 拉最近 N 天收盘 → 只补缺失交易日 → 累计腾落线续接。
  - 沿用旧文件格式 data/ad_line/ad_line_sp500_history.json (Economic-Dashboard 仓库内, fetch_ad_line_real 读它)。
  - 输出同时落一份到本项目 data/ad_line_sp500_history.json 作为备份(防再断)。
  - 只追加不改旧日(幂等); 新日 total<400 判为数据不全, 拒收并告警(不写不全的 A/D)。
用法: .venv/bin/python tools/ad_line_update.py [--days 12] [--dry-run]
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ED_FILE = os.path.expanduser("~/Projects/Economic-Dashboard/data/ad_line/ad_line_sp500_history.json")
BACKUP = os.path.join(ROOT, "data", "ad_line_sp500_history.json")
TICKERS = os.path.join(ROOT, "data", "sp500_constituents.csv")
MIN_TOTAL = 400


def constituents():
    try:
        import pandas as pd
        t = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                         storage_options={"User-Agent": "Mozilla/5.0"})[0]
        syms = [s.replace(".", "-") for s in t["Symbol"].astype(str)]
        if len(syms) >= 480:
            with open(TICKERS, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Symbol"])
                for s in syms:
                    w.writerow([s])
            return syms
    except Exception as e:  # noqa: BLE001
        print("维基成分股失败, 读本地缓存:", type(e).__name__, str(e)[:80], file=sys.stderr)
    if os.path.exists(TICKERS):
        return [r["Symbol"] for r in csv.DictReader(open(TICKERS, encoding="utf-8"))]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    import pandas as pd
    import yfinance as yf

    raw = json.load(open(ED_FILE, encoding="utf-8"))
    days = raw["days"]
    have = {d["date"] for d in days}
    last = days[-1]
    syms = constituents()
    if len(syms) < 480:
        print(f"❌ 成分股只有 {len(syms)} 只, 中止"); return 2

    end = dt.date.today()
    start = end - dt.timedelta(days=a.days + 8)
    prices = {}
    for i in range(0, len(syms), 25):
        b = syms[i:i + 25]
        for attempt in range(3):
            try:
                df = yf.download(b, start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
                                 progress=False, auto_adjust=False, group_by="ticker", threads=False)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        else:
            continue
        for t in b:
            try:
                c = (df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]).dropna()
                if len(c):
                    prices[t] = {d.strftime("%Y-%m-%d"): float(v) for d, v in c.items()}
            except Exception:  # noqa: BLE001
                continue
        time.sleep(0.4)
    spy = yf.download("SPY", start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
                      progress=False, auto_adjust=False, threads=False)
    tdays = [d.strftime("%Y-%m-%d") for d in spy.index]
    # ★2026-10-30 修: 原护栏按「本机 JST 小时<7」判断, 在 JST 23:05(纽约盘中 10:05)放行了盘中半成品。
    # 改为按纽约时间: 末日 == 纽约今天 且 纽约时间 < 16:15(收盘+15分钟缓冲) → 丢弃该日(只收已收盘交易日)。
    from zoneinfo import ZoneInfo
    _ny = dt.datetime.now(ZoneInfo("America/New_York"))
    _ny_close = _ny.replace(hour=16, minute=15, second=0, microsecond=0)
    if tdays and tdays[-1] == _ny.date().isoformat() and _ny < _ny_close:
        print(f"丢弃 {tdays[-1]}: 纽约现在 {_ny:%H:%M}, 未收盘", file=sys.stderr)
        tdays = tdays[:-1]
    print(f"成分 {len(prices)}/{len(syms)} 只有数据; 交易日 {tdays[0]}~{tdays[-1]}", file=sys.stderr)

    cum = last["cumulative"]
    added, rejected = [], []
    prev_close = {t: s.get(last["date"]) for t, s in prices.items()}
    for d in tdays:
        if d <= last["date"] or d in have:
            for t, s in prices.items():
                if d in s:
                    prev_close[t] = s[d]
            continue
        adv = dec = flat = 0
        for t, s in prices.items():
            if d in s and prev_close.get(t) is not None:
                chg = s[d] - prev_close[t]
                if chg > 1e-9: adv += 1
                elif chg < -1e-9: dec += 1
                else: flat += 1
            if d in s:
                prev_close[t] = s[d]
        tot = adv + dec + flat
        if tot < MIN_TOTAL:
            rejected.append((d, tot)); continue
        cum += adv - dec
        added.append({"date": d, "advance": adv, "decline": dec, "flat": flat, "total": tot,
                      "ad_net": adv - dec, "ad_ratio": round(adv / dec, 3) if dec else None,
                      "advance_pct": round(adv / tot * 100, 2), "cumulative": cum})
    print(f"新增 {len(added)} 天 {[x['date'] for x in added]}; 拒收(不全) {rejected}")
    for x in added[-3:]:
        print("  ", x)
    if a.dry_run or not added:
        return 0 if added or not rejected else 3
    raw["days"] = days + added
    raw["generated"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    raw["tickers"] = len(prices)
    for p in (ED_FILE, BACKUP):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(raw, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
    chk = json.load(open(ED_FILE, encoding="utf-8"))["days"][-1]["date"]
    print("写后读回 as_of =", chk, "OK" if chk == added[-1]["date"] else "MISMATCH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
