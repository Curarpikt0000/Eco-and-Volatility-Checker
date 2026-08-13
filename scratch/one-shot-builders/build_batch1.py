import json
from collections import Counter

# Batch 1 KOLs (exactly 20, in task order).
# web_search was attempted for every named KOL: "<name> <sector-keywords> 2026"
# plus broad fallback queries. The search backend returned EMPTY result sets
# for essentially all queries (19/20 zero results; the single non-empty query
# returned only generic gold-forecast articles with no view attributable to the
# named KOL). No recent, clearly attributed market view could be retrieved for
# any KOL. Per the iron rule, nothing is fabricated:
#   unfound -> direction "未找到", comments empty, targets empty.

kols = [
    {"kol": "Jim Curry",             "sector": "Precious Metals"},
    {"kol": "James Turk",            "sector": "Precious Metals"},
    {"kol": "Patrick Byrne",         "sector": "Precious Metals"},
    {"kol": "Jesse Colombo",         "sector": "Precious Metals"},
    {"kol": "Larry Lepard",          "sector": "Precious Metals"},
    {"kol": "Frank Giustra",         "sector": "Precious Metals"},
    {"kol": "Macro (unspecified KOL)", "sector": "Macro"},
    {"kol": "Bob Haberkorn",         "sector": "Precious Metals"},
    {"kol": "Marc Chandler(Macro",   "sector": "Precious Metals"},
    {"kol": "David Meger",           "sector": "Precious Metals"},
    {"kol": "Dan Loeb",              "sector": "Equities"},
    {"kol": "Todd Bubba Horowitz", "sector": "Precious Metals"},
    {"kol": "Ronny Stoeferle",       "sector": "Precious Metals"},
    {"kol": "Massimiliano Castelli", "sector": "Macro"},
    {"kol": "Timothy Arcuri(Equities",   "sector": "Precious Metals"},
    {"kol": "Jeff Currie",           "sector": "Energy & Commodities"},
    {"kol": "Andy Schectman",        "sector": "Precious Metals"},
    {"kol": "Jeff Snider",           "sector": "Government Debt"},
    {"kol": "Bill Gross",            "sector": "Government Debt"},
    {"kol": "Kyle Bass",             "sector": "Government Debt"},
]

records = [{
    "kol": k["kol"],
    "sector": k["sector"],
    "direction": "未找到",
    "comments": "",
    "targets": "",
} for k in kols]

payload = {"batch": 1, "kols": records}

out = "/home/user/Projects/Eco-and-Volatility-Checker/data/kol_batch_1.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

dist = Counter(r["direction"] for r in records)
found = sum(1 for r in records if r["direction"] != "未找到")
notfound = len(records) - found
print("total:", len(records))
print("found:", found)
print("not_found:", notfound)
print("direction_distribution:", dict(dist))
print("file:", out)
