"""
cn_capital_hk_hold.py — 港股通(南向)持股存量日频采集(Chao 2026-10-13 选 B)

数据: 东方财富 RPT_MUTUAL_STOCK_HOLDRANKS (MUTUAL_TYPE=002), 2024-10-14 起日频。
★重复计算陷阱(2026-10-13 实测): MUTUAL_TYPE 002(沪港通下)与 004(深港通下)返回的是
  **同一份**港股通全量持股(667 只、持股数逐只完全一致), 两通道相加会把总量翻倍。
  只取 002 一个通道, 并在落盘里记 n_stocks 供核对。
★这是存量(南向资金在港股持有的市值), 含港股价格涨跌, 不等于净买入。
落盘 data/cn_capital_hk_hold.json: {日期: [持股市值亿港元, 只数, 前十大合计占比%]}。
增量: 只补已存最后一日之后; 失败的日子记 failed, 下次重试, 绝不用空覆盖。
单日约 5 秒(每页 500 行, 约 2 页); 首次回填 ~500 个交易日约 45 分钟 → 分批, 每批限时落盘。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "cn_capital_hk_hold.json")
U = "https://datacenter-web.eastmoney.com/api/data/v1/get"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/hsgt/"}
START = "2024-10-14"


def _page(flt, pn, cols, tries=3):
    last = None
    for k in range(tries):
        try:
            p = {"reportName": "RPT_MUTUAL_STOCK_HOLDRANKS", "columns": cols, "pageNumber": pn, "pageSize": 500,
                 "source": "WEB", "client": "WEB", "filter": flt}
            r = requests.get(U, params=p, headers=H, timeout=45).json()
            if r.get("result") is None:
                if "为空" in str(r.get("message")):
                    return {"data": [], "pages": 1}
                raise RuntimeError(str(r.get("message"))[:50])
            return r["result"]
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{type(last).__name__}: {str(last)[:50]}")


def fetch_day(d):
    """返回 [总市值亿港元, 只数, 前十大市值占比%] 或 None(当日无数据=非交易日/未披露)。"""
    rows, pn = [], 1
    flt = f"(MUTUAL_TYPE=\"002\")(HOLD_DATE='{d}')"
    while True:
        r = _page(flt, pn, "SECURITY_CODE,HOLD_MARKET_CAP", )
        rows += r.get("data") or []
        if pn >= (r.get("pages") or 1):
            break
        pn += 1
    if not rows:
        return None
    caps = sorted((float(x["HOLD_MARKET_CAP"] or 0) for x in rows), reverse=True)
    tot = sum(caps)
    return [round(tot / 1e8, 1), len(rows), round(sum(caps[:10]) / tot * 100, 1) if tot else None]


def _trade_days(start, end):
    """用南向日度净买入存档(cn_capital.json 的 south_d)作交易日历, 缺失则退化为工作日。"""
    cal = []
    try:
        sd = json.load(open(os.path.join(ROOT, "data", "cn_capital.json"), encoding="utf-8")).get("south_d", {})
        cal = sorted(d for d in sd if start <= d <= end)
    except Exception:
        pass
    if cal:
        return cal
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out = []
    while d0 <= d1:
        if d0.weekday() < 5:
            out.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    return out


def run(budget_s=240, path=OUT):
    try:
        old = json.load(open(path, encoding="utf-8"))
    except Exception:
        old = {}
    data = dict(old.get("d", {}))
    failed = dict(old.get("failed", {}))
    end = dt.date.today().isoformat()
    todo = [d for d in _trade_days(START, end) if d not in data]
    warns, t0, done = [], time.time(), 0
    # 最近的日子优先, 保证日更先拿到最新点
    for d in sorted(todo, reverse=True):
        if time.time() - t0 > budget_s:
            break
        try:
            v = fetch_day(d)
            if v is None:
                failed[d] = "empty"      # 交易日历内却无数据: 记下, 以后重试(最近 3 天可能尚未披露)
            else:
                data[d] = v
                failed.pop(d, None)
                done += 1
        except Exception as e:
            failed[d] = str(e)[:40]
            warns.append(f"{d} 抓取失败({e})")
        time.sleep(0.25)
    left = len([d for d in todo if d not in data])
    out = {"status": "ok" if not warns else "partial",
           "as_of": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST"),
           "note": "MUTUAL_TYPE=002 单通道(002/004 同一份数据, 不可相加); 市值亿港元; 存量含价格涨跌",
           "d": dict(sorted(data.items())), "failed": failed, "remaining": left, "warnings": warns[:5]}
    tmp = path + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return out, done


if __name__ == "__main__":
    b = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    o, n = run(b)
    print(o["status"], "本次新增", n, "累计", len(o["d"]), "剩余", o["remaining"], "failed", len(o["failed"]), o["warnings"][:2])
