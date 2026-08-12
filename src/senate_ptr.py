"""senate_ptr.py — 参议员 Periodic Transaction Report(PTR) fetcher。

Chao 需求(2026-08): 政要披露板块补参议员 Tuberville(以及可扩展其他参议员)逐笔交易。

背景: 参议员受 STOCK Act 约束报 PTR, 但披露在 efdsearch.senate.gov(独立于众议院),
  需**会话流程**(先同意条款拿 cookie)才能查询, 且明细是 **HTML 页(非 PDF)带 ticker**。
  ★参议院数据质量优于众议院: 直接带 ticker + 公司全名 + 交易类型 + 金额区间。

会话流程(2026-08-12 实测通过, 关键坑已标):
  1. GET /search/home/ → 拿 csrfmiddlewaretoken(表单) + csrftoken(cookie)
  2. POST /search/home/ {csrfmiddlewaretoken, prohibition_agreement=1} → 同意条款
  3. ★GET /search/ → 建立 referer 链(缺这步 data 端点回 503!)
  4. POST /search/report/data/ (DataTables server-side) → PTR 列表 JSON
     必带 header: X-Requested-With, X-CSRFToken; report_types=[11](PTR)
  5. GET /search/view/ptr/<uuid>/ → 明细 HTML 表格
     行: # | 日期 | Owner | Ticker | 公司名 | 类型 | 买卖 | 金额区间

绝不编: 503/解析失败标状态; 无交易标 no_trades。
"""
import os
import re
import html
import json
import time
import datetime

try:
    import requests
except ImportError:
    requests = None

BASE = "https://efdsearch.senate.gov"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_JSON = os.path.join(DATA_DIR, "senate_ptr.json")

# 追踪的参议员(可扩展; 只增不减)
SENATE_TARGETS = [
    {"name": "Tommy Tuberville", "last": "Tuberville",
     "title": "参议员 (阿拉巴马)"},
]

DIR_CN = {
    "purchase": "买入", "sale (full)": "卖出", "sale (partial)": "部分卖出",
    "sale": "卖出", "exchange": "交换",
}


def _session():
    """建立同意条款后的会话。"""
    if requests is None:
        raise RuntimeError("requests 未安装")
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    r = s.get(f"{BASE}/search/home/", timeout=30)
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    tok = m.group(1) if m else s.cookies.get("csrftoken")
    s.post(f"{BASE}/search/home/",
           data={"csrfmiddlewaretoken": tok, "prohibition_agreement": "1"},
           headers={"Referer": f"{BASE}/search/home/"}, timeout=30)
    # ★建立 referer 链(缺这步 data 端点 503)
    s.get(f"{BASE}/search/", timeout=30)
    return s


def search_ptr(s, last_name, since="01/01/2024 00:00:00"):
    """查某参议员的 PTR 列表 → [{name, report, filed, url}]。"""
    csrf = s.cookies.get("csrftoken")
    payload = {
        "draw": "1", "order[0][column]": "1", "order[0][dir]": "desc",
        "start": "0", "length": "50", "search[value]": "", "search[regex]": "false",
        "report_types": "[11]", "filer_types": "[]",
        "submitted_start_date": since, "submitted_end_date": "",
        "candidate_state": "", "senator_state": "", "office_id": "",
        "first_name": "", "last_name": last_name,
    }
    r = s.post(f"{BASE}/search/report/data/", data=payload,
               headers={"Referer": f"{BASE}/search/",
                        "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf,
                        "Accept": "application/json, text/javascript, */*; q=0.01"},
               timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"search HTTP {r.status_code}")
    j = r.json()
    out = []
    for row in j.get("data", []):
        link = re.search(r'href="([^"]+)"', str(row[3]) if len(row) > 3 else "")
        report = re.sub(r"<[^>]+>", "", str(row[3])).strip() if len(row) > 3 else ""
        filed = re.sub(r"<[^>]+>", "", str(row[4])).strip() if len(row) > 4 else ""
        out.append({
            "report": report, "filed": filed,
            "url": BASE + link.group(1) if link else None,
        })
    return out


def parse_ptr_page(s, url):
    """解析 PTR 明细 HTML → [{ticker, asset, direction, dir_cn, txn_date, amount_range}]。"""
    r = s.get(url, timeout=30, headers={"Referer": f"{BASE}/search/"})
    if r.status_code != 200:
        raise RuntimeError(f"ptr page HTTP {r.status_code}")
    txt = r.text
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c).strip())
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c]
        # 行: # 日期 Owner Ticker 公司名 Stock 买卖 金额
        if len(cells) < 7:
            continue
        if not re.match(r"\d{1,2}/\d{1,2}/\d{4}", cells[1]):
            continue
        ticker = cells[3] if cells[3] and cells[3] != "--" else None
        asset = cells[4]
        raw_dir = cells[6].lower()
        out.append({
            "ticker": ticker, "asset": asset,
            "txn_date": cells[1], "owner": cells[2],
            "direction": cells[6],
            "dir_cn": DIR_CN.get(raw_dir, cells[6]),
            "amount_range": cells[7] if len(cells) > 7 else None,
        })
    return out


def fetch_senator(s, target, max_reports=3):
    """抓一个参议员最近 max_reports 份 PTR + 明细。"""
    try:
        reports = search_ptr(s, target["last"])
    except Exception as e:
        return {"name": target["name"], "title": target["title"],
                "status": "search_error", "error": str(e), "trades": []}
    trades = []
    for rep in reports[:max_reports]:
        if not rep["url"]:
            continue
        try:
            tr = parse_ptr_page(s, rep["url"])
            for t in tr:
                t["filed"] = rep["filed"]
            trades += tr
            time.sleep(0.5)
        except Exception as e:
            print(f"  [{target['name']}] PTR 解析失败: {e}")

    def tkey(t):
        try:
            return datetime.datetime.strptime(t["txn_date"], "%m/%d/%Y")
        except Exception:
            return datetime.datetime.min
    trades.sort(key=tkey, reverse=True)
    return {
        "name": target["name"], "title": target["title"],
        "n_reports": len(reports), "n_parsed": min(len(reports), max_reports),
        "trades": trades[:15],
        "status": "ok" if trades else ("no_trades" if reports else "no_reports"),
    }


def fetch(save=True):
    """抓所有追踪参议员。"""
    result = {"as_of": datetime.date.today().isoformat(), "senators": []}
    try:
        s = _session()
    except Exception as e:
        result["status"] = "session_error"
        result["error"] = str(e)
        if save:
            _save(result)
        return result
    for t in SENATE_TARGETS:
        print(f"[参议员] 抓 {t['name']}...", flush=True)
        result["senators"].append(fetch_senator(s, t))
    if save:
        _save(result)
    return result


def _save(result):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(result, open(OUT_JSON, "w"), ensure_ascii=False, indent=2)


def load():
    if os.path.exists(OUT_JSON):
        return json.load(open(OUT_JSON))
    return None


if __name__ == "__main__":
    r = fetch()
    for sen in r.get("senators", []):
        print(f"\n=== {sen['name']} ({sen['title']}) status={sen['status']} "
              f"reports={sen.get('n_reports')} ===")
        for t in sen.get("trades", [])[:10]:
            print(f"  {t['txn_date']:10} {t['dir_cn']:6} {(t.get('ticker') or '--'):6} "
                  f"{(t.get('amount_range') or ''):22} {t['asset'][:30]}")
