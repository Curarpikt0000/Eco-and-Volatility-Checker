#!/usr/bin/env python3
"""Pull full SLV Notion history + GLD SPDR historical archive, save ETF snapshot."""
import os, json, urllib.request, datetime, io, re

# ★2026-10-06 Eco 接管: 路径参数化(原写死 Mac 路径 /Users/chaojin/...)。INV_BASE 由调用方经环境变量传入。
INV_BASE = os.environ.get('INV_BASE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')

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

def api(url, payload=None, version='2022-06-28', method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + TOK,
                                          'Notion-Version': version,
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# --- SLV full history ---
SLV_DB = '2ba47eb5-fd3c-80c6-a0c1-ce9f47ec5d25'
rows, cursor = [], None
while True:
    payload = {"sorts": [{"property": "Date", "direction": "ascending"}], "page_size": 100}
    if cursor:
        payload["start_cursor"] = cursor
    res = api(f"https://api.notion.com/v1/databases/{SLV_DB}/query", payload)
    rows.extend(res.get('results', []))
    if res.get('has_more'):
        cursor = res['next_cursor']
    else:
        break
slv = []
for r in rows:
    p = r['properties']
    d = p.get('Date', {}).get('date', {}).get('start') if p.get('Date', {}).get('date') else None
    oz = p.get('Ounces In trus', {}).get('number')
    if d and oz:
        slv.append({'d': d, 'oz': oz})
slv.sort(key=lambda x: x['d'])
print("SLV rows:", len(slv), "range:", slv[0]['d'], "->", slv[-1]['d'])

# --- GLD from SPDR API ---
gld = []
try:
    req = urllib.request.Request('https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en',
                                 headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        xlsx = r.read()
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True)
    ws = wb['US GLD Historical Archive']
    it = ws.iter_rows(values_only=True)
    header = next(it)
    # find cols: Date, Total Ounces of Gold in the Trust, Tonnes of Gold
    ci = {h: i for i, h in enumerate(header)}
    for row in it:
        if not row or not row[ci['Date']]:
            continue
        ds = row[ci['Date']]
        if hasattr(ds, 'strftime'):
            d = ds.strftime('%Y-%m-%d')
        else:
            # parse DD-Mon-YYYY text
            import datetime as _dt
            try:
                d = _dt.datetime.strptime(str(ds).strip(), '%d-%b-%Y').strftime('%Y-%m-%d')
            except ValueError:
                continue
        oz = row[ci['Total Ounces of Gold in the Trust']]
        t = row[ci['Tonnes of Gold']]
        if oz is None or not isinstance(oz, (int, float)):
            continue
        try:
            ozf = float(oz)
        except (ValueError, TypeError):
            continue
        gld.append({'d': d, 'oz': ozf, 't': float(t) if isinstance(t, (int, float)) else None})
    gld.sort(key=lambda x: x['d'])
    print("GLD rows:", len(gld), "range:", gld[0]['d'], "->", gld[-1]['d'])
except Exception as e:
    print("GLD ERR:", e)

out = {
    'generated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST'),
    'gld': gld,
    'slv': slv,
}
with open(os.path.join(INV_BASE, 'data', 'etf_snapshot.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False)
print("saved etf_snapshot.json")
