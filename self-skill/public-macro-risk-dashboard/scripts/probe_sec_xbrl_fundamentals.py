#!/usr/bin/env python3
"""Probe SEC EDGAR XBRL for standard FCF (OCF - CapEx) across a company universe.

Encodes the STALE-TAG fix: anchor on OCF's latest fiscal year, then sum only the
CapEx tags that have a value at that SAME fiscal year. A naive "first tag that
returns anything" loop silently returns decade-old numbers (NVDA 0.1B@2012,
AMZN 6.7B@2016, EQIX 0.0B@2010) and the chart looks perfectly fine.

Usage:
    python probe_sec_xbrl_fundamentals.py            # default AI-infra universe
    python probe_sec_xbrl_fundamentals.py MSFT NVDA  # subset by ticker

Requires a descriptive User-Agent with contact info (SEC enforces this).
See references/free-macro-credit-data-sources.md §③ for the full rationale.
"""
import json
import sys
import time
import urllib.request
from datetime import date

UA = {"User-Agent": "research-probe (contact: set-your-email@example.com)"}

# ticker -> zero-padded CIK. Verified live 2026-08.
UNIVERSE = {
    # AI 应用/模型层
    "MSFT": "0000789019", "GOOGL": "0001652044", "META": "0001326801",
    "AMZN": "0001018724", "ORCL": "0001341439",
    # 芯片/加速器
    "NVDA": "0001045810", "AMD": "0000002488", "AVGO": "0001730168",
    "TSM": "0001046179", "MU": "0000723125",
    # 算力/数据中心
    "CRWV": "0001769628", "EQIX": "0001101239", "DLR": "0001297996",
    "VRT": "0001674101",
    # 电力/能源基建
    "CEG": "0001868275", "VST": "0001692819", "NEE": "0000753308",
    "GEV": "0001996810", "ETN": "0001551182",
}

OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]

# Several filers legitimately SPLIT capex across multiple tags -> sum, don't first-hit.
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    "PaymentsToAcquireMachineryAndEquipment",
    "PaymentsToAcquireBuildings",
    "PaymentsToDevelopRealEstateAssets",
    "PaymentsToAcquireRealEstate",
    "PaymentsForProceedsFromProductiveAssets",
]

# TSM files 20-F under IFRS: no us-gaap namespace at all.
IFRS_OCF = "CashFlowsFromUsedInOperatingActivities"
IFRS_CAPEX = "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"

ANNUAL_FORMS = ("10-K", "20-F", "10-K/A")


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def annual_points(facts, tag, namespace="us-gaap"):
    """(end_date, value) for ANNUAL duration facts only. De-duped, restatements win."""
    node = ((facts.get("facts") or {}).get(namespace) or {}).get(tag)
    if not node:
        return []
    pts = {}
    for unit, arr in (node.get("units") or {}).items():
        if "USD" not in unit and "TWD" not in unit:
            continue
        for it in arr:
            s, e = it.get("start"), it.get("end")
            if not s or not e or it.get("form") not in ANNUAL_FORMS:
                continue
            try:
                d1, d2 = date.fromisoformat(s), date.fromisoformat(e)
            except ValueError:
                continue
            # 330-400d window rejects quarterly and stub periods
            if not (330 <= (d2 - d1).days <= 400):
                continue
            pts[e] = it["val"]
    return sorted(pts.items())


def probe(ticker, cik):
    facts = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    time.sleep(0.15)
    namespaces = list((facts.get("facts") or {}).keys())
    ifrs = "ifrs-full" in namespaces and "us-gaap" not in namespaces

    if ifrs:
        ocf = annual_points(facts, IFRS_OCF, "ifrs-full")
        if not ocf:
            return {"ticker": ticker, "error": "IFRS filer, no OCF"}
        fy = ocf[-1][0]
        cap = dict(annual_points(facts, IFRS_CAPEX, "ifrs-full")).get(fy)
        if cap is None:
            return {"ticker": ticker, "fy": fy, "error": "IFRS filer, no CapEx at FY"}
        return {"ticker": ticker, "fy": fy, "ocf": ocf[-1][1],
                "capex": cap, "fcf": ocf[-1][1] - cap, "tags": [IFRS_CAPEX], "ifrs": True}

    ocf = []
    for t in OCF_TAGS:
        ocf = annual_points(facts, t)
        if ocf:
            break
    if not ocf:
        return {"ticker": ticker, "error": "no OCF tag"}

    fy = ocf[-1][0]                      # ← anchor: OCF's latest fiscal year
    total, hit = 0.0, []
    for t in CAPEX_TAGS:
        pts = dict(annual_points(facts, t))
        if fy in pts:                    # ← same-FY guard kills the stale-tag trap
            total += pts[fy]
            hit.append(t)
    if not hit:
        # e.g. NEE: utilities file capex in a company extension namespace
        return {"ticker": ticker, "fy": fy, "ocf": ocf[-1][1],
                "error": "no standard CapEx tag at latest FY (extension namespace?)"}
    return {"ticker": ticker, "fy": fy, "ocf": ocf[-1][1],
            "capex": total, "fcf": ocf[-1][1] - total, "tags": hit}


def main():
    want = [a.upper() for a in sys.argv[1:]]
    universe = {k: v for k, v in UNIVERSE.items() if not want or k in want}

    print(f"{'ticker':7s} {'FY end':>11s} {'OCF $B':>9s} {'CapEx $B':>9s} "
          f"{'FCF $B':>9s}  notes")
    print("-" * 78)
    ok = []
    for tk, cik in universe.items():
        try:
            r = probe(tk, cik)
        except Exception as e:                       # noqa: BLE001
            print(f"{tk:7s} fetch failed: {type(e).__name__} {str(e)[:40]}")
            continue
        if "error" in r:
            print(f"{tk:7s} {r.get('fy', '—'):>11s} {'':>9s} {'':>9s} {'':>9s}  "
                  f"✗ {r['error']}")
            continue
        ok.append(r)
        note = f"{len(r['tags'])} tag(s)" + (" [IFRS]" if r.get("ifrs") else "")
        print(f"{tk:7s} {r['fy']:>11s} {r['ocf']/1e9:9.1f} {r['capex']/1e9:9.1f} "
              f"{r['fcf']/1e9:9.1f}  {note}")

    print("-" * 78)
    print(f"standard FCF resolved: {len(ok)}/{len(universe)}")
    print("NOTE fiscal years are NOT aligned across filers — always render each "
          "company's own FY end, never a single shared year header.")


if __name__ == "__main__":
    main()
