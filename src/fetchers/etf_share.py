"""
etf_share.py — 宽基 ETF 份额时序采集（Chao 2026-08-25 指定，B 方案）

## 为什么看「份额」而不是「价格/规模」
- **价格**涨跌 = 市场情绪，不代表有钱进来。
- **规模（净值×份额）**会被价格污染：指数涨 10%、份额不变，规模也涨 10%，看着像"资金流入"其实没有。
- **份额**才是真金白银：份额增加 = 有人**申购**（真金进场），份额减少 = **赎回**（钱撤了）。
  这是判断「国家队/机构在不在场」唯一干净的口径。

## 为什么是这几只
SFISF 抵押品明确包含**股票 ETF 与沪深300 成分股**，机构拿到钱进场首选宽基。
510300（沪深300）/ 510050（上证50）/ 510500（中证500）是体量最大的三只，
"国家队"历史上多次通过它们入市。

## 数据源（2026-08-25 实测）
`akshare.fund_etf_scale_sse(date=YYYYMMDD)` —— **上交所官方**每日 ETF 规模表，
含「基金份额」列，一次返回全市场 800+ 只。一手源，非第三方推算。

★ 坑 1：**只有交易日有数据**，非交易日返回空表并抛
  `KeyError: None of [Index([...])]` —— 这是"当天没数据"不是"接口坏了"，必须捕获跳过。
★ 坑 2：**必须逐日请求**，没有区间接口 → 建时序只能循环，要限速。
★ 坑 3：份额单位是「份」，展示时换算成「亿份」。

## 用法
    .venv/bin/python -m src.fetchers.etf_share --days 400        # 回填
    .venv/bin/python -m src.fetchers.etf_share --days 5          # 日更增量
落盘 data/etf_share.json（累积，只增不改已有日期）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "etf_share.json")

# 代码 → 展示名。只放宽基，行业 ETF 不进（噪音大且与"托底"无关）
TARGETS = {
    "510300": "沪深300ETF",
    "510050": "上证50ETF",
    "510500": "中证500ETF",
}


def _load():
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def fetch_day(ak, date_str):
    """取某一交易日三只 ETF 的份额。非交易日返回 None（不是错误）。"""
    try:
        df = ak.fund_etf_scale_sse(date=date_str)
    except Exception:
        # ★ 非交易日：上交所返回空表 → akshare 重命名列时 KeyError。
        #   这是正常情况，不是抓取失败，直接跳过。
        return None
    if df is None or df.empty:
        return None
    try:
        sub = df[df["基金代码"].astype(str).isin(TARGETS)]
    except Exception:
        return None
    if sub.empty:
        return None
    out = {}
    for _, r in sub.iterrows():
        code = str(r["基金代码"])
        try:
            share = float(r["基金份额"])
        except Exception:
            continue
        out[code] = round(share / 1e8, 4)      # 份 → 亿份
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import akshare as ak

    store = _load()
    today = dt.date.today()
    todo = []
    for i in range(a.days):
        d = today - dt.timedelta(days=i)
        if d.weekday() >= 5:               # 周末必然无数据，省请求
            continue
        ds = d.strftime("%Y%m%d")
        if ds in store:                    # 已有不重取（增量友好）
            continue
        todo.append(ds)
    todo.sort()

    print(f"待取 {len(todo)} 个日期 | 已有 {len(store)} 天 | dry_run={a.dry_run}")
    if a.dry_run:
        print("  样例:", todo[:5], "...", todo[-3:] if len(todo) > 3 else "")
        return

    ok = skip = 0
    for i, ds in enumerate(todo, 1):
        rec = fetch_day(ak, ds)
        if rec:
            store[ds] = rec
            ok += 1
        else:
            skip += 1
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}  命中={ok} 非交易日/空={skip}")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
        time.sleep(a.sleep)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\n完成 命中 {ok} / 跳过 {skip} | 累计 {len(store)} 天 → {OUT}")
    if store:
        ks = sorted(store)
        print(f"覆盖 {ks[0]} ~ {ks[-1]}")
        for c, nm in TARGETS.items():
            vs = [(k, v[c]) for k, v in sorted(store.items()) if c in v]
            if vs:
                print(f"  {nm}({c}): {len(vs)} 天, 最新 {vs[-1][0]} = {vs[-1][1]:,.2f} 亿份")


if __name__ == "__main__":
    main()
