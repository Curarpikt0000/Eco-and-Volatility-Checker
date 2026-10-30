#!/usr/bin/env python3
"""AI 产业链信用维度 ⇄ SEC EDGAR 独立对账 (2026-10-31)。

为什么要有: 面板数据来自 external_data.fetch_ai_credit(), 它自己解析 SEC companyfacts。
如果解析器选错标签/选错财年, 面板会「看起来正常」但数不对, 没人知道。
本脚本绕开 fetch_ai_credit 的挑选逻辑: 对每家公司, 直接拉 SEC companyfacts, 用「面板里写的利息支出值」
去 SEC 全部 interest-expense 类标签里找「值完全相同 + 10-K/20-F + 同财年末」的条目。找不到 = 面板数不是任何一份官方申报值。

静默即正常; 有任何公司对不上才输出。退出码: 0 正常/ 1 有对不上/ 2 脚本自身故障。
★对照组: 脚本先用 MSFT 的已知真实申报(FY2026 InterestExpenseNonoperating)做自检, 自检失败 = SEC 通道/解析坏了, 报脚本故障而不是报数据错。
"""
import json, os, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
UA = {"User-Agent": "Mozilla/5.0 EcoVolChecker research chao.jin@uber.com"}
CIK = {  # 与 fetch_ai_credit 同一批公司; 只对 SEC 有 companyfacts 的做对账
    "MSFT": "0000789019", "ORCL": "0001341439", "NVDA": "0001045810", "GOOGL": "0001652044",
    "AMZN": "0001018724", "META": "0001326801", "AVGO": "0001730168", "AMD": "0000002488",
    "TSM": None, "CRWV": "0001769628",
}


def sec_interest_vals(cik):
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=UA, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"SEC HTTP {r.status_code}")
    out = set()
    facts = r.json()["facts"]
    for ns in ("us-gaap", "ifrs-full"):
        for tag, v in facts.get(ns, {}).items():
            if "interest" in tag.lower() and "expense" in tag.lower():
                for p in v.get("units", {}).get("USD", []):
                    if p.get("form") in ("10-K", "20-F", "10-K/A"):
                        out.add((p["val"], p["end"]))
    return out


def main():
    try:
        # 自检(对照组): MSFT 面板口径的已知真值必须能在 SEC 里找到, 否则是通道坏了
        s = sec_interest_vals(CIK["MSFT"])
        if (3051000000, "2026-06-30") not in s:
            print("⚠️ SEC 对账脚本自检失败: MSFT FY2026 利息 3,051,000,000 在 SEC 里找不到(通道或解析坏了), 今日未对账")
            return 2
        import external_data as ed
        rows = ed.fetch_ai_credit().get("rows", [])
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ SEC 对账脚本故障: {type(e).__name__}: {str(e)[:120]}")
        return 2
    bad, checked = [], 0
    for x in rows:
        t, c = x.get("ticker"), CIK.get(x.get("ticker"))
        if not c or x.get("interest") in (None, 0):
            continue
        try:
            vals = sec_interest_vals(c)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{t}: SEC 取数失败 {type(e).__name__}")
            continue
        checked += 1
        fy = str(x.get("fy"))
        if (int(x["interest"]), fy) not in vals:
            near = sorted(v for v, e in vals if e == fy)[:2]
            bad.append(f"{t}: 面板利息 {int(x['interest']):,}(财年末 {fy}) 在 SEC 申报里找不到; 同财年末 SEC 值: {near}")
        time.sleep(0.4)       # SEC 限速 10 次/秒, 留余量
    if bad:
        print("⚠️ eco-vol 信用维度 ⇄ SEC 对账: %d/%d 家对不上" % (len(bad), checked))
        for b in bad[:6]:
            print("  ", b)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
