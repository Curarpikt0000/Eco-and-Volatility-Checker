#!/usr/bin/env python3
"""Build COMEX + SHFE inventory charts HTML (Au/Ag/Pt) from Notion sources.

Data sources:
- CME inventory DB (2e047eb5-fd3c-80d8-9d56-e2c1ad066138): COMEX Reg/Elig per metal, daily since 2026-01-06
  Activity Note [SHFE] annotation: daily SHFE kg since 2026-06-05
- Gold DB (2bc47eb5-fd3c-8083-966e-ecfd9f396b44): SHFE weekly tonnes
- Silver DB (2bc47eb5-fd3c-80f3-a71a-d8de149a4943): SHFE/SGE weekly tonnes

Output: inventory_charts.html (self-contained, ECharts CDN + embedded JSON)
"""
import os, json, re, urllib.request, datetime

# ★2026-10-06 Eco 接管: 路径参数化(原写死 Mac 路径 /Users/chaojin/...)。INV_BASE 由调用方经环境变量传入。
INV_BASE = os.environ.get('INV_BASE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')

# ---------- auth ----------
env = {}
with open(os.path.expanduser('~/.hermes/.env')) as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
TOK = None
for k, v in env.items():
    if k.startswith('NOTION_') and v.startswith('ntn_'):
        TOK = v; break
if not TOK:
    raise SystemExit("NO NOTION TOKEN")

def api(url, payload, version='2022-06-28'):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Authorization': 'Bearer ' + TOK,
                                          'Notion-Version': version,
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# ---------- pull all CME inventory ----------
CME_DB = '2e047eb5-fd3c-80d8-9d56-e2c1ad066138'
def pull_cme(metal):
    rows, cursor = [], None
    while True:
        payload = {"filter": {"property": "Metal Type", "select": {"equals": metal}},
                   "sorts": [{"property": "Date", "direction": "ascending"}],
                   "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = api(f"https://api.notion.com/v1/databases/{CME_DB}/query", payload)
        rows.extend(res.get('results', []))
        if res.get('has_more'):
            cursor = res['next_cursor']
        else:
            break
    out = []
    for r in rows:
        p = r['properties']
        d = p.get('Date', {}).get('date', {}).get('start')
        if not d:
            continue
        reg = p.get('Total Registered', {}).get('number')
        elig = p.get('Total Eligible', {}).get('number')
        note = ''
        rt = p.get('Activity Note', {}).get('rich_text', [])
        if rt:
            note = rt[0].get('plain_text', '')
        rec = {'d': d, 'reg': reg, 'elig': elig}
        if reg is not None and elig is not None:
            rec['total'] = reg + elig
        m = re.search(r'\[SHFE\] (\w+)库存 ([\d,]+)kg', note)
        if m:
            rec['shfe_kg'] = int(m.group(2).replace(',', ''))
        out.append(rec)
    return out

# ---------- pull east weekly DB ----------
def pull_weekly(db_id, date_prop, markets):
    rows, cursor = [], None
    while True:
        payload = {"sorts": [{"property": date_prop, "direction": "ascending"}], "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = api(f"https://api.notion.com/v1/databases/{db_id}/query", payload)
        rows.extend(res.get('results', []))
        if res.get('has_more'):
            cursor = res['next_cursor']
        else:
            break
    out = []
    for r in rows:
        p = r['properties']
        d = p.get(date_prop, {}).get('date', {}).get('start')
        mkt = p.get('市场', {}).get('select', {}).get('name') if p.get('市场', {}).get('select') else None
        sh = p.get('SH库存吨', {}).get('number')
        if d and mkt in markets and sh is not None:
            out.append({'d': d, 'mkt': mkt, 't': sh})
    return out

def fetch_sge_weekly_online(max_issues=14):
    """Fetch SGE silver weekly inventory from official site PDFs (sge.com.cn/sjzx/hqzb).

    Returns [{d: friday_of_week, mkt: 'SGE', t: tonnes}] newest-first ordering.
    """
    import requests, re, io
    HDR = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36',
           'Referer': 'https://www.sge.com.cn/'}
    try:
        r = requests.get('https://www.sge.com.cn/sjzx/hqzb', headers=HDR, timeout=30)
        if r.status_code != 200:
            print("SGE list HTTP", r.status_code); return []
        links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
        pdfs = []
        for href, text in links:
            t = re.sub(r'<[^>]+>', '', text).strip()
            if href.startswith('https://www.sge.com.cn/upload/file/') and '周报' in t:
                m = re.search(r'(\d{8})-(\d{8})周报', t)
                if m:
                    pdfs.append((m.group(2), href))  # end date, url
        pdfs.sort(key=lambda x: x[0], reverse=True)
        out = []
        import pdfplumber, datetime as _dt
        for end_d, url in pdfs[:max_issues]:
            pr = requests.get(url, headers=HDR, timeout=60)
            if pr.status_code != 200:
                continue
            with pdfplumber.open(io.BytesIO(pr.content)) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text() or ''
                    if '指定仓库库存周报' in txt:
                        for line in txt.split('\n'):
                            parts = line.split()
                            if len(parts) >= 4 and parts[0] == '白银':
                                try:
                                    kg = float(parts[3].replace(',', ''))
                                    d = f"{end_d[:4]}-{end_d[4:6]}-{end_d[6:]}"
                                    out.append({'d': d, 'mkt': 'SGE', 't': round(kg / 1000.0, 3)})
                                except (ValueError, IndexError):
                                    pass
                        break
        return out
    except Exception as e:
        print("SGE online ERR:", e)
        return []

GOLD_DB = '2bc47eb5-fd3c-8083-966e-ecfd9f396b44'
SILVER_DB = '2bc47eb5-fd3c-80f3-a71a-d8de149a4943'

data = {
    'generated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST'),
    'gold':   {'comex': pull_cme('Gold'),   'shfe': pull_weekly(GOLD_DB, 'Gold日期', ['SHFE'])},
    'silver': {'comex': pull_cme('Silver'), 'shfe': pull_weekly(SILVER_DB, 'Silver日期', ['SHFE']),
               'sge': pull_weekly(SILVER_DB, 'Silver日期', ['SGE'])},
    'platinum': {'comex': pull_cme('Platinum')},
}

# SGE silver: DB history (2025-11 ~ 2026-06) + local full archive (2021-12+) + official site weekly PDFs (newest)
sge_db = data['silver']['sge']
by_date = {r['d']: r for r in sge_db}
# 1) local backfilled archive
hist_path = os.path.join(INV_BASE, 'data', 'sge_history.json')
if os.path.exists(hist_path):
    with open(hist_path) as f:
        for r in json.load(f):
            by_date.setdefault(r['d'], r)
# 2) official site (newest issues, fills beyond archive)
sge_online = fetch_sge_weekly_online(max_issues=14)
added = 0
for r in sge_online:
    if r['d'] not in by_date:
        by_date[r['d']] = r
        added += 1
data['silver']['sge'] = sorted(by_date.values(), key=lambda x: x['d'])
print("SGE merged: db=%d history=%d online_added=%d total=%d" % (
    len(sge_db), len([r for r in data['silver']['sge'] if r['d'] < '2025-11-01']), added, len(data['silver']['sge'])))
# sort east weekly
for k in data:
    if k == 'generated' or not isinstance(data[k], dict):
        continue
    for sk in data[k]:
        v = data[k][sk]
        if isinstance(v, list) and v and isinstance(v[0], dict) and 'd' in v[0]:
            v.sort(key=lambda x: x['d'])

with open(os.path.join(INV_BASE, 'data', 'inventory_snapshot.json'), 'w') as f:
    json.dump(data, f, ensure_ascii=False)
print("gold comex:", len(data['gold']['comex']), "shfe:", len(data['gold']['shfe']))
print("silver comex:", len(data['silver']['comex']), "shfe:", len(data['silver']['shfe']), "sge:", len(data['silver']['sge']))
print("platinum comex:", len(data['platinum']['comex']))
