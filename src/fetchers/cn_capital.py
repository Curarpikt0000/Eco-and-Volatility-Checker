"""
cn_capital.py — A 股资金面三组真数据采集（Chao 2026-10-12 选 A 方案）

## 三组数据（均来自东方财富 datacenter 披露库，一手披露口径，非推算）
1. 国家队直接持股（季频）：RPT_F10_EH_FREEHOLDERS，HOLDER_NEWTYPE="国家队"
   → 中央汇金投资 / 中央汇金资产管理 / 中国证券金融 三家，按季末汇总持股市值。
   ★口径坑（2026-10-12 实测）：这是「十大流通股东」披露，门槛随股价/他人持股浮动，
     证金持股只数 113→77→23 **不能当作撤退**（54 只掉出列表里有的是门槛变化、
     有的是持股在证金与汇金资管之间移动）。故同时输出「同一批股票」对比口径。
   ★不含汇金通过 ETF 的持仓（ETF 持有人只在半年报/年报披露前十大）。
2. 北向持股市值（季频快照）：RPT_MUTUAL_MARKET_STA（总量+占 A 股流通市值比）。
   ★北向日度净买入 2024-08-16 起交易所停披露（之后字段全空），本数据只能给季度存量。
   接口只返回最新 3 期 → **每次运行把拿到的期次并入本地存档**，不丢历史。
3. 南向日度净买入（日频）：RPT_MUTUAL_DEAL_HISTORY MUTUAL_TYPE=006（港股通合计），
   2014-11-17 起，附恒生指数收盘。单位：接口给「百万港元」。
   ★方向：南向 = 内地资金买港股，**不是外资**。

落盘 data/cn_capital.json（累积：季度键只增不改旧期，除非明确 --refresh）。
失败 → 沿用旧文件并在 warnings 里写明，绝不用空覆盖旧真值。
"""
from __future__ import annotations

import json
import os
import time
import datetime as dt

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "cn_capital.json")
U = "https://datacenter-web.eastmoney.com/api/data/v1/get"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
HOLDERS = ["中央汇金投资有限责任公司", "中央汇金资产管理有限责任公司", "中国证券金融股份有限公司"]
HSHORT = {"中央汇金投资有限责任公司": "汇金投资", "中央汇金资产管理有限责任公司": "汇金资管",
          "中国证券金融股份有限公司": "证金"}


def _get(params, tries=3):
    last = None
    for k in range(tries):
        try:
            r = requests.get(U, params=params, headers=H, timeout=45)
            j = r.json()
            if j.get("success") is False and "为空" in str(j.get("message")):
                return {"data": [], "pages": 1, "count": 0}
            if j.get("result") is None:
                raise RuntimeError(str(j.get("message"))[:60])
            return j["result"]
        except Exception as e:  # 网络/限流: 重试, 最后抛出让上层记 warning
            last = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{type(last).__name__}: {str(last)[:60]}")


def _all_pages(report, flt, cols, sort=None, ps=500):
    out, pn = [], 1
    while True:
        p = {"reportName": report, "columns": cols, "pageNumber": pn, "pageSize": ps,
             "source": "WEB", "client": "WEB", "filter": flt}
        if sort:
            p["sortColumns"], p["sortTypes"] = sort, "-1"
        r = _get(p)
        out += r.get("data") or []
        if pn >= (r.get("pages") or 1):
            break
        pn += 1
    return out


def _quarter_ends(n_back=32):
    """最近 n_back 个季末(含当前已结束的)。"""
    today = dt.date.today()
    q = []
    y, m = today.year, today.month
    # 当前季度末(未到则往前一季)
    ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    cand = []
    for yy in range(y, y - 10, -1):
        for mm, dd in reversed(ends):
            d = dt.date(yy, mm, dd)
            if d < today:
                cand.append(d)
    return cand[:n_back]


def fetch_holders(old):
    """国家队三家按季末汇总 + 同一批股票对比所需的逐股持股股数。"""
    q = old.get("holders_q", {})
    stocks = old.get("holders_stocks", {})
    warns = []
    for d in _quarter_ends(32):
        ds = d.isoformat()
        # 已存且非最近 2 期 → 不重抓(历史披露不改)
        recent = ds in [x.isoformat() for x in _quarter_ends(2)]
        if ds in q and not recent:
            continue
        try:
            rows = _all_pages("RPT_F10_EH_FREEHOLDERS",
                              f"(HOLDER_NEWTYPE=\"国家队\")(END_DATE='{ds}')",
                              "SECURITY_CODE,SECURITY_NAME_ABBR,HOLDER_NAME,HOLD_NUM,HOLDER_MARKET_CAP")
        except Exception as e:
            warns.append(f"国家队持股 {ds} 抓取失败({e})")
            continue
        if not rows:
            continue
        agg = {}
        per = {}
        for x in rows:
            nm = HSHORT.get(x["HOLDER_NAME"], x["HOLDER_NAME"])
            a = agg.setdefault(nm, {"n": 0, "cap": 0.0})
            a["n"] += 1
            a["cap"] += float(x["HOLDER_MARKET_CAP"] or 0)
            per.setdefault(x["SECURITY_CODE"], {})[nm] = float(x["HOLD_NUM"] or 0)
        q[ds] = {k: {"n": v["n"], "cap_yi": round(v["cap"] / 1e8, 1)} for k, v in agg.items()}
        stocks[ds] = per
        time.sleep(0.3)
    return q, stocks, warns


def fetch_north(old):
    """北向持股市值季度快照: 并入本地存档。"""
    arch = dict(old.get("north_q", {}))
    warns = []
    try:
        r = _get({"reportName": "RPT_MUTUAL_MARKET_STA", "columns": "ALL", "pageNumber": 1, "pageSize": 50,
                  "source": "WEB", "client": "WEB", "filter": '(MARKET_CODE="005")',
                  "sortColumns": "HOLD_DATE", "sortTypes": "-1"})
        for x in r.get("data") or []:
            ds = x["HOLD_DATE"][:10]
            arch[ds] = {"cap_yi": round(float(x["HOLD_MARKET_CAP"]) / 1e8, 1),
                        "ratio_pct": round(float(x["HOLD_MARKET_RATE"]) * 100, 3),
                        "add_yi": round(float(x["ADD_MARKET_CAP"]) / 1e8, 1)}
    except Exception as e:
        warns.append(f"北向持股抓取失败({e}), 沿用存档")
    return arch, warns


def fetch_south(old):
    """南向日度净买入(百万港元) + 恒指收盘; 增量: 只补存档最后一天之后。"""
    cur = {d: v for d, v in old.get("south_d", {}).items()}
    warns = []
    last = max(cur) if cur else None
    try:
        flt = '(MUTUAL_TYPE="006")' + (f"(TRADE_DATE>'{last}')" if last else "")
        rows = _all_pages("RPT_MUTUAL_DEAL_HISTORY", flt,
                          "TRADE_DATE,NET_DEAL_AMT,BUY_AMT,SELL_AMT,INDEX_CLOSE_PRICE", sort="TRADE_DATE", ps=500)
        for x in rows:
            if x["NET_DEAL_AMT"] is None:
                continue
            cur[x["TRADE_DATE"][:10]] = [round(float(x["NET_DEAL_AMT"]), 2),
                                         round(float(x["INDEX_CLOSE_PRICE"]), 2) if x["INDEX_CLOSE_PRICE"] else None]
    except Exception as e:
        warns.append(f"南向净买入抓取失败({e}), 沿用存档")
    return cur, warns


def fetch_cn_capital(path=OUT):
    try:
        old = json.load(open(path, encoding="utf-8"))
    except Exception:
        old = {}
    out = {"status": "ok", "as_of": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST"),
           "warnings": []}
    hq, hs, w1 = fetch_holders(old)
    nq, w2 = fetch_north(old)
    sd, w3 = fetch_south(old)
    out.update({"holders_q": hq, "holders_stocks": hs, "north_q": nq, "south_d": sd})
    out["warnings"] = w1 + w2 + w3
    if not hq and not nq and not sd:
        out["status"] = "error"
        return out
    if out["warnings"]:
        out["status"] = "partial"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return out


if __name__ == "__main__":
    o = fetch_cn_capital()
    print(o["status"], o["warnings"], "holders_q", len(o.get("holders_q", {})),
          "north_q", len(o.get("north_q", {})), "south_d", len(o.get("south_d", {})))
