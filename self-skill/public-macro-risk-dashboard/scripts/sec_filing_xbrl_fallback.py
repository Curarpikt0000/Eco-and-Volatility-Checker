#!/usr/bin/env python3
"""SEC companyfacts 缺某年时的补充源：直接读那份 filing 的 XBRL 实例文件。

为什么需要（2026-08-31 实测）：
  SEC 的 companyfacts 聚合库对**外国私人发行人（20-F）收录严重滞后**。
  TSM 的 2025 年 20-F 已于 2026-04-16 申报，但 companyfacts 最新仍停在
  2024-12-31 → 看板上该公司落后整整一年，且看起来像「SEC 没有数据」。
  直接读 filing 的 XBRL 实例文件即可拿到，数据仍是官方申报值，口径不变。

用法:
    python3 sec_filing_xbrl_fallback.py 0001046179 --after 2024-12-31
    python3 sec_filing_xbrl_fallback.py 0001046179 --after 2024-12-31 --unit usd

四个必踩坑（全部已在本脚本内规避，改动前先读）:
  ① UA 必须含真实邮箱，否则 www.sec.gov/Archives/ 一律 403（data.sec.gov 却能过）
  ② IFRS 标签名 != US-GAAP，且必须先枚举真实标签（用 --list-tags）
  ③ 20-F 同时申报本币与美元 → 不按 unitRef 过滤会算出符号相反的荒谬值
  ④ context 标签**没有** xbrli: 前缀，是 <context id="c-1"> + <startDate>
"""
import argparse
import json
import re
import sys
import urllib.request

# 坑①: 必须含真实邮箱。缺邮箱时 Archives 域名一律 403，且失败是静默的。
SEC_UA = {"User-Agent": "Eco-Volatility-Checker <your-email@example.com>"}

# 坑②: IFRS 与 US-GAAP 标签名不同，两套都试
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    "CashFlowsFromUsedInOperatingActivities",            # IFRS
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",  # IFRS
]


def _get(url, timeout=60):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=SEC_UA), timeout=timeout
    ).read().decode("utf-8", "ignore")


def latest_annual_filing(cik, after):
    """找报告期晚于 after 的最新年报 accession。无更新则 None。"""
    u = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    r = json.loads(_get(u, 40)).get("filings", {}).get("recent", {})
    best = None
    for form, rep, accn in zip(r.get("form", []), r.get("reportDate", []),
                               r.get("accessionNumber", [])):
        if not form.startswith(("10-K", "20-F")):
            continue
        if form.endswith("/A"):
            continue                     # 修订件先不用，避免口径混乱
        if rep and rep > (after or "") and (best is None or rep > best[0]):
            best = (rep, accn)
    return best


def _instance_url(cik, accn):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"
    idx = json.loads(_get(base + "index.json", 40))
    names = [it["name"] for it in idx["directory"]["item"]]
    inst = next((n for n in names if n.endswith("_htm.xml")), None)
    return (base + inst) if inst else None


def parse_contexts(raw):
    """坑④: 是 <context id="..."> 不是 <xbrli:context>。返回 {id: (start, end, has_segment)}"""
    ctx = {}
    for m in re.finditer(r'<context id="([^"]+)">(.*?)</context>', raw, re.S):
        cid, body = m.group(1), m.group(2)
        s = re.search(r"<startDate>([^<]+)", body)
        e = re.search(r"<endDate>([^<]+)", body)
        if s and e:
            ctx[cid] = (s.group(1), e.group(1), "<segment>" in body)
    return ctx


def grab(raw, ctx, tags, unit):
    """取无 segment、币种匹配、完整自然年的事实。返回 {fy_end: value}"""
    got = {}
    for tag in tags:
        t = tag.split(":")[-1]
        for m in re.finditer(r'<[a-z-]+:%s([^>]*)>(-?[0-9.]+)</[a-z-]+:%s>' % (t, t), raw):
            attrs, val = m.group(1), m.group(2)
            cid = re.search(r'contextRef="([^"]+)"', attrs)
            un = re.search(r'unitRef="([^"]+)"', attrs)
            if not cid or not un:
                continue
            # 坑③: 币种不符必须跳过，否则本币/美元混算出荒谬值
            if un.group(1).lower() != unit:
                continue
            cid = cid.group(1)
            if cid not in ctx or ctx[cid][2]:
                continue                 # 带 segment 的是分部披露，只要合并数
            st, en, _ = ctx[cid]
            if st[:4] != en[:4]:
                continue                 # 非完整自然年
            got[en] = float(val)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cik")
    ap.add_argument("--after", default="", help="已有的最新财年末 YYYY-MM-DD")
    ap.add_argument("--unit", default="usd", help="unitRef 过滤 (usd/twd/...)")
    ap.add_argument("--list-tags", action="store_true",
                    help="枚举实例文件里的现金流相关标签名（坑②排查用）")
    a = ap.parse_args()

    found = latest_annual_filing(a.cik, a.after)
    if not found:
        print(f"无晚于 {a.after} 的年报 → companyfacts 已是最新，不需补充源")
        return 0
    rep, accn = found
    print(f"找到更新年报: reportDate={rep}  accn={accn}")

    url = _instance_url(a.cik, accn)
    if not url:
        print("未找到 _htm.xml 实例文件", file=sys.stderr)
        return 2
    raw = _get(url, 120)
    print(f"XBRL 实例: {len(raw)} 字节")

    if a.list_tags:
        for pat in (r"<[a-z-]+:([A-Za-z]*CashFlow[A-Za-z]*)[ >]",
                    r"<[a-z-]+:([A-Za-z]*PropertyPlantAndEquipment[A-Za-z]*)[ >]",
                    r"<[a-z-]+:(PurchaseOf[A-Za-z]*|PaymentsTo[A-Za-z]*)[ >]"):
            for t in sorted(set(re.findall(pat, raw))):
                print("   ", t)
        return 0

    ctx = parse_contexts(raw)
    print(f"contexts: {len(ctx)}")
    ocf = grab(raw, ctx, OCF_TAGS, a.unit)
    cap = grab(raw, ctx, CAPEX_TAGS, a.unit)
    print("OCF  :", ocf)
    print("CapEx:", cap)
    common = sorted(set(ocf) & set(cap))
    if not common:
        print("⚠ OCF/CapEx 无共同年度 —— 先跑 --list-tags 确认标签名（坑②）", file=sys.stderr)
        return 3
    fy = common[-1]
    fcf = ocf[fy] - cap[fy]
    print(f"\nFY{fy}  FCF = {fcf/1e9:.1f} B ({a.unit.upper()})")
    # 符号/量级自检：OCF 明显大于 CapEx 却算出负数 = 多半币种混用（坑③）
    if ocf[fy] > cap[fy] and fcf < 0:
        print("⚠ 荒谬值：OCF > CapEx 却得负 FCF —— 检查 unitRef 过滤（坑③）", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
