#!/usr/bin/env python3
"""Render inventory_charts.html from data/inventory_snapshot.json + data/etf_snapshot.json.

Charts:
1. Au: COMEX (left axis) + SHFE (right axis)
2. Ag: COMEX (left) + SHFE/SGE (right)
3. Pt: COMEX only (no SHFE data)
4. GLD ETF daily flow (bar, last 365d, tonnes, +inflow/-outflow)
5. SLV ETF daily flow (bar, last 365d, tonnes, +inflow/-outflow)

Output: /tmp/inventory_charts.html (self-contained, ECharts CDN + embedded JSON)
"""
import json, os, datetime

# ★2026-10-06 Eco 接管: 路径参数化(原写死 Mac 路径 /Users/chaojin/...)。INV_BASE 由调用方经环境变量传入。
INV_BASE = os.environ.get('INV_BASE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')

BASE = INV_BASE
OZ_TO_T = 0.0000311035

# 图表统一显示最近 1 年（历史档案保留在 data/，仅渲染裁剪）
cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()

with open(os.path.join(BASE, 'data/inventory_snapshot.json')) as f:
    data = json.load(f)
with open(os.path.join(BASE, 'data/etf_snapshot.json')) as f:
    etf = json.load(f)

def merge_shfe(weekly, daily_kg_list):
    merged = {}
    for w in weekly:
        merged[w['d']] = w['t']
    for r in daily_kg_list:
        if r.get('shfe_kg') is not None:
            merged[r['d']] = r['shfe_kg'] / 1000.0
    return [{'d': d, 't': v} for d, v in sorted(merged.items())]

def series_comex(rows):
    return [[r['d'], round(r['total'] * OZ_TO_T, 2)] for r in rows if r.get('total') is not None]

def series_weekly(rows, mkt):
    return [[r['d'], r['t']] for r in rows if r.get('mkt') == mkt]

gold_shfe = merge_shfe(data['gold']['shfe'], data['gold']['comex'])
silver_shfe = merge_shfe(data['silver']['shfe'], data['silver']['comex'])
silver_sge = [x for x in series_weekly(data['silver']['sge'], 'SGE') if x[0] >= cutoff]

charts = {
    'gold': {
        'title': '黄金 Gold — COMEX vs 上海 (SHFE) 库存',
        'series': [
            {'name': 'COMEX 库存 (吨)', 'type': 'line', 'data': series_comex(data['gold']['comex']), 'color': '#1f6feb', 'axis': 0},
            {'name': 'SHFE 库存 (吨)', 'type': 'line', 'data': [[x['d'], x['t']] for x in gold_shfe], 'color': '#e8590c', 'axis': 1},
        ],
    },
    'silver': {
        'title': '白银 Silver — COMEX vs 上海 (SHFE/SGE) 库存',
        'series': [
            {'name': 'COMEX 库存 (吨)', 'type': 'line', 'data': series_comex(data['silver']['comex']), 'color': '#1f6feb', 'axis': 0},
            {'name': 'SHFE 库存 (吨)', 'type': 'line', 'data': [[x['d'], x['t']] for x in silver_shfe], 'color': '#e8590c', 'axis': 1},
            {'name': 'SGE 库存 (吨)', 'type': 'line', 'data': silver_sge, 'color': '#2f9e44', 'axis': 1},
        ],
    },
    'platinum': {
        'title': '铂金 Platinum — COMEX 库存 (上海无库存数据)',
        'series': [
            {'name': 'COMEX 库存 (吨)', 'type': 'line', 'data': series_comex(data['platinum']['comex']), 'color': '#1f6feb', 'axis': 0},
        ],
    },
}

# ---- ETF daily flow (last 365 days) ----
def daily_flow(rows, key='oz'):
    """rows sorted by date; returns [[date, delta_tonnes]] using oz->t."""
    out = []
    prev = None
    for r in rows:
        v = r.get(key)
        if v is None or not isinstance(v, (int, float)):
            continue
        if prev is not None:
            out.append([r['d'], round((v - prev) * OZ_TO_T, 2)])
        prev = v
    return out

def last365(pairs):
    return [[d, v] for d, v in pairs if d >= cutoff]

gld_flow = last365(daily_flow(etf['gld'], 'oz'))
slv_flow = last365(daily_flow(etf['slv'], 'oz'))

def flow_summary(pairs):
    if not pairs:
        return "N/A"
    tot_in = sum(v for _, v in pairs if v > 0)
    tot_out = sum(v for _, v in pairs if v < 0)
    net = tot_in + tot_out
    last = pairs[-1][1]
    return {'net': round(net, 0), 'in': round(tot_in, 0), 'out': round(tot_out, 0), 'last': round(last, 2), 'd': pairs[-1][0]}

def weekly_flow(pairs):
    """Aggregate daily flow pairs [[date, delta]] into ISO weeks (Mon start)."""
    weeks = {}
    for d, v in pairs:
        dt = datetime.date.fromisoformat(d)
        monday = dt - datetime.timedelta(days=dt.weekday())
        weeks[monday] = weeks.get(monday, 0) + v
    return [[m.isoformat(), round(v, 2)] for m, v in sorted(weeks.items())]

gld_s = flow_summary(gld_flow)
slv_s = flow_summary(slv_flow)

gld_flow_weekly = weekly_flow(gld_flow)
slv_flow_weekly = weekly_flow(slv_flow)

charts['gld_flow'] = {
    'title': 'GLD 黄金ETF — 每日净流入/流出 (近1年, 吨)',
    'series': [
        {'name': 'GLD 日净流量 (吨)', 'type': 'bar', 'data': gld_flow, 'color': '#f59f00'},
    ],
}
charts['gld_flow_weekly'] = {
    'title': 'GLD 黄金ETF — 周度净流入/流出 (近1年, 吨)',
    'series': [
        {'name': 'GLD 周净流量 (吨)', 'type': 'bar', 'data': gld_flow_weekly, 'color': '#f59f00'},
    ],
}
charts['slv_flow'] = {
    'title': 'SLV 白银ETF — 每日净流入/流出 (近1年, 吨)',
    'series': [
        {'name': 'SLV 日净流量 (吨)', 'type': 'bar', 'data': slv_flow, 'color': '#868e96'},
    ],
}
charts['slv_flow_weekly'] = {
    'title': 'SLV 白银ETF — 周度净流入/流出 (近1年, 吨)',
    'series': [
        {'name': 'SLV 周净流量 (吨)', 'type': 'bar', 'data': slv_flow_weekly, 'color': '#868e96'},
    ],
}

# summary stats
def last_val(rows):
    vals = [r for r in rows if r.get('total') is not None]
    return vals[-1] if vals else None

def last_shfe(merged):
    return merged[-1] if merged else None

g_last, g_sh = last_val(data['gold']['comex']), last_shfe(gold_shfe)
s_last, s_sh, s_sge = last_val(data['silver']['comex']), last_shfe(silver_shfe), (silver_sge[-1] if silver_sge else None)
p_last = last_val(data['platinum']['comex'])

def fmt_t(v): return f"{v['total']*OZ_TO_T:,.0f} t" if v else "N/A"
def fmt_sh(v):
    if not v:
        return "N/A"
    t = v['t'] if isinstance(v, dict) else v[1]
    return f"{t:,.0f} t"

summary = {
    'gold': {'comex': fmt_t(g_last), 'shfe': fmt_sh(g_sh), 'd': g_last['d'] if g_last else '-'},
    'silver': {'comex': fmt_t(s_last), 'shfe': fmt_sh(s_sh), 'sge': fmt_sh(s_sge), 'd': s_last['d'] if s_last else '-'},
    'platinum': {'comex': fmt_t(p_last), 'd': p_last['d'] if p_last else '-'},
    'gld': {'net': gld_s['net'], 'in': gld_s['in'], 'out': gld_s['out'], 'last': gld_s['last'], 'd': gld_s['d'],
            'w_net': round(sum(v for _, v in gld_flow_weekly), 0), 'w_last': gld_flow_weekly[-1][1] if gld_flow_weekly else 0, 'w_d': gld_flow_weekly[-1][0] if gld_flow_weekly else '-'},
    'slv': {'net': slv_s['net'], 'in': slv_s['in'], 'out': slv_s['out'], 'last': slv_s['last'], 'd': slv_s['d'],
            'w_net': round(sum(v for _, v in slv_flow_weekly), 0), 'w_last': slv_flow_weekly[-1][1] if slv_flow_weekly else 0, 'w_d': slv_flow_weekly[-1][0] if slv_flow_weekly else '-'},
}

TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>COMEX & 上海 贵金属库存 + ETF 资金流</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #fff; color: #1a1a1a; margin: 0; padding: 24px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .card { border: 1px solid #e5e5e5; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }
  .card h2 { font-size: 16px; margin: 0 0 8px; }
  .stats { display: flex; gap: 24px; flex-wrap: wrap; font-size: 13px; color: #444; margin-bottom: 8px; }
  .stats b { color: #1a1a1a; }
  .chart { width: 100%; height: 400px; }
  .chart-sub { font-size: 13px; color: #666; font-weight: 600; margin: 12px 0 2px; }
  .note { font-size: 12px; color: #999; margin-top: 16px; }
  @media (max-width: 600px) { .chart { height: 320px; } }
</style>
</head>
<body>
<h1>COMEX & 上海 贵金属库存 + GLD/SLV ETF 资金流</h1>
<div class="sub">数据更新：__GENERATED__ ｜ COMEX 日频 (Notion CME 库存库) ｜ SHFE/SGE 周频 + 日频注解 ｜ GLD: SPDR 官方 ｜ SLV: Notion SLV 库</div>
__CARDS__
<div class="note">COMEX 用左轴、上海用右轴（单位均为公吨，COMEX oz × 0.0000311035）。SHFE/SGE：每周库存 DB + CME Activity Note [SHFE] 日频注解（2026-06-05 起）。Pt 无上海库存。ETF 日净流量 = 当日持有量 − 前日持有量（正=净流入，负=净流出）。图表由脚本每日自动生成。</div>
<script>
const CHARTS = __CHARTS__;
const SUMMARY = __SUMMARY__;
function render(el, cfg) {
  const chart = echarts.init(document.getElementById(el));
  const series = cfg.series.map(s => ({
    name: s.name, type: s.type || 'line', data: s.data,
    showSymbol: false, smooth: true,
    lineStyle: { width: 2, color: s.color },
    itemStyle: s.type === 'bar'
      ? { color: params => params.value[1] >= 0 ? '#2f9e44' : '#e03131' }
      : { color: s.color },
    connectNulls: true,
    yAxisIndex: s.axis || 0,
  }));
  const yAxes = cfg.series.some(s => s.axis === 1)
    ? [
        { type: 'value', name: 'COMEX (吨)', scale: true },
        { type: 'value', name: '上海 (吨)', scale: true, splitLine: { show: false } },
      ]
    : [{ type: 'value', name: '吨', scale: true }];
  chart.setOption({
    tooltip: { trigger: 'axis', valueFormatter: v => (v == null ? '-' : v.toLocaleString() + ' t') },
    legend: { data: cfg.series.map(s => s.name), top: 0 },
    grid: { left: 60, right: 60, top: 40, bottom: 40 },
    xAxis: { type: 'time' },
    yAxis: yAxes,
    series,
  });
  window.addEventListener('resize', () => chart.resize());
}
document.addEventListener('DOMContentLoaded', () => {
  render('chart-gold', CHARTS.gold);
  render('chart-silver', CHARTS.silver);
  render('chart-platinum', CHARTS.platinum);
  render('chart-gld-flow', CHARTS.gld_flow);
  render('chart-gld-flow-weekly', CHARTS.gld_flow_weekly);
  render('chart-slv-flow', CHARTS.slv_flow);
  render('chart-slv-flow-weekly', CHARTS.slv_flow_weekly);
});
</script>
</body>
</html>
"""

def card_html(title, stats_html, chart_ids, chart_titles=None):
    charts_div = ''
    for i, cid in enumerate(chart_ids):
        sub = f'<div class="chart-sub">{chart_titles[i]}</div>' if chart_titles else ''
        charts_div += f'{sub}<div id="{cid}" class="chart"></div>'
    return f"""<div class="card">
  <h2>{title}</h2>
  <div class="stats">{stats_html}</div>
  {charts_div}
</div>"""

cards = []
cards.append(card_html(charts['gold']['title'],
    f"""<span>COMEX: <b>{summary['gold']['comex']}</b> ({summary['gold']['d']})</span><span>SHFE: <b>{summary['gold']['shfe']}</b></span>""",
    ['chart-gold']))
cards.append(card_html(charts['silver']['title'],
    f"""<span>COMEX: <b>{summary['silver']['comex']}</b> ({summary['silver']['d']})</span><span>SHFE: <b>{summary['silver']['shfe']}</b></span><span>SGE: <b>{summary['silver']['sge']}</b></span>""",
    ['chart-silver']))
cards.append(card_html(charts['platinum']['title'],
    f"""<span>COMEX: <b>{summary['platinum']['comex']}</b> ({summary['platinum']['d']})</span><span>SHFE: 无数据</span>""",
    ['chart-platinum']))
cards.append(card_html('GLD 黄金ETF — 净流入/流出 (近1年, 吨)',
    f"""<span>近1年净流量: <b>{summary['gld']['net']:+,.0f} t</b> (流入 {summary['gld']['in']:,.0f} / 流出 {summary['gld']['out']:,.0f})</span><span>最新一日: <b>{summary['gld']['last']:+,.2f} t</b> ({summary['gld']['d']})</span><span>最新一周: <b>{summary['gld']['w_last']:+,.2f} t</b> ({summary['gld']['w_d']} 周)</span>""",
    ['chart-gld-flow', 'chart-gld-flow-weekly'],
    ['每日净流量', '每周净流量 (周一起始)']))
cards.append(card_html('SLV 白银ETF — 净流入/流出 (近1年, 吨)',
    f"""<span>近1年净流量: <b>{summary['slv']['net']:+,.0f} t</b> (流入 {summary['slv']['in']:,.0f} / 流出 {summary['slv']['out']:,.0f})</span><span>最新一日: <b>{summary['slv']['last']:+,.2f} t</b> ({summary['slv']['d']})</span><span>最新一周: <b>{summary['slv']['w_last']:+,.2f} t</b> ({summary['slv']['w_d']} 周)</span>""",
    ['chart-slv-flow', 'chart-slv-flow-weekly'],
    ['每日净流量', '每周净流量 (周一起始)']))

out = TPL.replace('__GENERATED__', data['generated'])
out = out.replace('__CARDS__', '\n'.join(cards))
out = out.replace('__CHARTS__', json.dumps(charts, ensure_ascii=False))
out = out.replace('__SUMMARY__', json.dumps(summary, ensure_ascii=False))

with open(os.path.join(INV_BASE, 'inventory_charts.html'), 'w') as f:
    f.write(out)
print("written", os.path.join(INV_BASE, 'inventory_charts.html'), len(out), "bytes")
print("gld_flow points:", len(gld_flow), "slv_flow points:", len(slv_flow))
