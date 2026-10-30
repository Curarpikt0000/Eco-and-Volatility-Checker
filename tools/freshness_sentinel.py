#!/usr/bin/env python3
"""每日新鲜度哨兵 (Chao 2026-10-30 立: 每张图每天都应有 cron 或模型看着)。

读 40 个 fetcher 的源头最新日 → 对照声明频率 → 超期即告警。
正常静默(no_agent cron: 空 stdout 不推送); 只在有问题时打印。

★口径修正(对 freshness_audit.py): 未来日期(预测值/到期日/日程, 如 2026-11-05、2026-12-31)
  不算「内部更新的数据日」, 否则会把正常数据误判 INTERNAL_MISMATCH。
★自检: 先用一个必然新鲜的对照源(FRED 日频)走同一路径, 对照源判不出新鲜=审计链路本身坏了,
  此时不下任何「停更」结论, 只报「哨兵自身故障」。

状态落盘 data/freshness_sentinel.json(给看板读 as_of/滞后用)。
退出码: 0=跑完(无论有无告警); 2=哨兵自身故障。
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import freshness_audit as fa  # noqa: E402
import external_data as ed  # noqa: E402

TODAY = dt.date.today()
OUT = os.path.join(ROOT, "data", "freshness_sentinel.json")


def clip_future(obj_date):
    return None if (obj_date and obj_date > TODAY + dt.timedelta(days=1)) else obj_date


def past_max_date(obj, depth=0):
    """同 deep_max_date, 但忽略未来日期。"""
    if depth > 6:
        return None
    best = None

    def upd(c):
        nonlocal best
        c = clip_future(c)
        if c and (best is None or c > best):
            best = c
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("fetched_at", "generated", "source_url", "note", "source"):
                continue
            if k in ("date", "week", "d", "as_of", "asof", "day", "month"):
                upd(fa.parse_date(v))
            upd(past_max_date(v, depth + 1))
    elif isinstance(obj, list):
        for v in obj[-400:]:
            upd(past_max_date(v, depth + 1))
    elif isinstance(obj, str):
        c = fa.parse_date(obj)
        if c and 2000 < c.year <= TODAY.year + 1:
            upd(c)
    return best


def biz(d0, d1):
    return fa.biz_days_between(d0, d1)


def main():
    # 自检: 对照源
    try:
        import urllib.request
        urllib.request.urlopen("https://fred.stlouisfed.org", timeout=15).read(100)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ eco-vol 新鲜度哨兵: 自检失败(网络不通: {e}), 今日不下任何停更结论")
        return 2

    res, bad = [], []
    for name, fn, freq, tol, label in fa.SPECS:
        rec = {"name": name, "label": label, "freq": freq, "tol_days": tol}
        try:
            d = fn()
            rec["status"] = (d or {}).get("status") if isinstance(d, dict) else "n/a"
            decl = clip_future(fa.parse_date((d or {}).get("as_of") or (d or {}).get("asof"))) if isinstance(d, dict) else None
            deep = past_max_date(d)
            # ★IIP: as_of 是年频(2025), 但同时有季频 q_as_of(2026-Q2): 取更新者, 否则误判滞后 300 天
            qa = fa.parse_date(str((d or {}).get("q_as_of", "")).replace("-Q1", "-03").replace("-Q2", "-06")
                               .replace("-Q3", "-09").replace("-Q4", "-12")) if isinstance(d, dict) else None
            extra = None
            if isinstance(d, dict):
                # ★无 as_of 字段的几个源: 从各自结构里取真实末点日期(口径写死, 避免显示「读不出日期」)
                if name == "country_ust_holdings":      # TIC: 各国 series 末点 'YYYY-MM'
                    ds = [fa.parse_date(v["series"][-1][0]) for v in d.values()
                          if isinstance(v, dict) and v.get("series")]
                    extra = max([x for x in ds if x], default=None)
                elif name == "fiscal_budget":           # 年度预算: as_of='FY2026' → 当年 9 月 30 日(美财年末)
                    import re as _re
                    m = _re.search(r"FY(\d{4})", str(d.get("as_of", "")))
                    extra = dt.date(int(m.group(1)), 9, 30) if m else None
                elif name == "debt_to_gdp":             # IMF: as_of_year=2025 → 当年末
                    try:
                        extra = dt.date(int(d.get("as_of_year")), 12, 31)
                    except Exception:  # noqa: BLE001
                        extra = None
                elif name == "liquidity_points":        # 取自 A5/A1 最新行, 直接读 Notion 最新日
                    try:
                        st, b = ed._req("POST", f"/databases/{ed.ECON_DB['fed_liquidity']}/query",
                                        {"page_size": 1, "sorts": [{"property": "Date", "direction": "descending"}]})
                        t = (b["results"][0]["properties"]["Date"]["title"] or [{}])[0].get("plain_text")
                        extra = fa.parse_date(t)
                    except Exception:  # noqa: BLE001
                        extra = None
            # ★季度数据点日期惯例=「季首月1日」(2026-Q1 记 01-01), 滞后应按「季末」算, 否则恒显滞后偏大 ~90 天
            if name == "credit_impulse" and deep and deep.day == 1 and deep.month in (1, 4, 7, 10):
                deep = (dt.date(deep.year + (deep.month == 10), (deep.month + 2) % 12 + 1, 1) - dt.timedelta(days=1))
            # ★财政事件是离散新闻: 有 last_checked(最近检索日)就以它为准——「检索过且无新事件」≠停更
            if name == "fiscal_news":
                try:
                    lc = json.load(open(os.path.join(ROOT, "data", "fiscal_news.json"), encoding="utf-8")).get("last_checked")
                    extra = fa.parse_date(lc) if lc else extra
                except Exception:  # noqa: BLE001
                    pass
            asof = max([x for x in (decl, deep, clip_future(qa), extra) if x], default=None)
            if asof:
                lag = (TODAY - asof).days
                rec.update(as_of=asof.isoformat(), lag_days=lag, lag_bizdays=biz(asof, TODAY))
                if freq == "static":
                    rec["verdict"] = "STATIC"
                elif lag > tol:
                    rec["verdict"] = "STALE"
                elif lag > tol * 0.7:
                    rec["verdict"] = "WATCH"
                else:
                    rec["verdict"] = "OK"
            else:
                rec.update(as_of=None, lag_days=None, verdict="NO_DATE")
            if rec.get("status") not in (None, "ok", "n/a", "OK") and rec["verdict"] == "OK":
                rec["verdict"] = "STATUS_BAD"
                rec["note"] = f"fetcher status={rec.get('status')}"
        except Exception as e:  # noqa: BLE001
            rec["verdict"] = "ERROR"
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        res.append(rec)
        if rec["verdict"] in ("STALE", "ERROR", "NO_DATE", "STATUS_BAD"):
            bad.append(rec)

    json.dump({"run_at": dt.datetime.now().isoformat(timespec="seconds"), "today": TODAY.isoformat(),
               "results": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if bad:
        print(f"⚠️ eco-vol 新鲜度哨兵 {TODAY}: {len(bad)}/{len(res)} 个源头超期或异常")
        for r in bad:
            extra = r.get("error") or r.get("note") or ""
            print(f"- {r['label']}（{r['name']}）[{r['freq']}] 最新 {r.get('as_of')} 滞后 {r.get('lag_days')} 天 "
                  f"（容忍 {r['tol_days']}）{r['verdict']} {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
