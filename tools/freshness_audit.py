"""freshness_audit.py — 全量数据源新鲜度审计。

对 build_dashboard 调用的每个 fetcher:
  1. 实跑，取其 as_of / 最新数据点日期
  2. 对照声明的更新频率，算滞后交易日/自然日
  3. 判定 OK / 可疑 / 超期

绝不编: 抓不到就标 ERROR，不猜。
输出 JSON 到 scratch/freshness_audit.json + 控制台表格。
"""
import sys
import os
import json
import datetime as dt
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)

import external_data as ed  # noqa

TODAY = dt.date.today()


def biz_days_between(d0, d1):
    """两个日期间的工作日数(粗略,不含节假日)。"""
    if d0 > d1:
        return 0
    n = 0
    cur = d0
    while cur < d1:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def parse_date(v):
    """从各种形态里抠出一个 date。"""
    if v is None:
        return None
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    if not s:
        return None
    import re
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r'(\d{4})-(\d{2})$', s)
    if m:
        try:
            y, mo = int(m.group(1)), int(m.group(2))
            nxt = dt.date(y + (mo == 12), (mo % 12) + 1, 1)
            return nxt - dt.timedelta(days=1)
        except ValueError:
            return None
    m = re.search(r'^(\d{4})$', s)
    if m:
        return dt.date(int(m.group(1)), 12, 31)
    return None


def deep_max_date(obj, depth=0):
    """递归找结构里最大的日期(找时序末点)。"""
    if depth > 6:
        return None
    best = None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ('fetched_at', 'generated', 'source_url', 'note', 'source'):
                continue
            if k in ('date', 'week', 'd', 'as_of', 'asof', 'day', 'month'):
                c = parse_date(v)
                if c and (best is None or c > best):
                    best = c
            c = deep_max_date(v, depth + 1)
            if c and (best is None or c > best):
                best = c
    elif isinstance(obj, list):
        for v in obj[-400:]:
            c = deep_max_date(v, depth + 1)
            if c and (best is None or c > best):
                best = c
    elif isinstance(obj, str):
        c = parse_date(obj)
        if c and 2000 < c.year <= TODAY.year + 1 and (best is None or c > best):
            best = c
    return best


# name -> (调用, 声明频率, 容忍滞后天数, 备注)
# 容忍值 = 该频率下"正常"的最大滞后自然日；超过即判超期
SPECS = [
    ('comex_inventory',        lambda: ed.fetch_comex_inventory(),        'daily',    5,  'COMEX/上海库存+ETF'),
    ('comex_issue_stop_weekly', lambda: ed.fetch_comex_issue_stop_weekly(), 'daily',   7,  '做市商周净issue/stop'),
    ('comex_issue_stop_firms', lambda: ed.fetch_comex_issue_stop_firms(),  'daily',    7,  '交割前十名'),
    ('comex_silver_issues_ref', lambda: ed.fetch_comex_silver_issues_ref(), 'static', 9999, '手抄锚点(静态,已标注)'),
    ('liquidity_points',       lambda: ed.fetch_liquidity_points(),       'daily',    6,  'Fed准备金/RRP/TGA'),
    ('cb_balance_sheets',      lambda: ed.fetch_cb_balance_sheets(),      'weekly',   45, '三大央行资负表'),
    ('cb_liquidity_swaps',     lambda: ed.fetch_cb_liquidity_swaps(),     'weekly',   14, '央行货币互换'),
    ('china_liquidity',        lambda: ed.fetch_china_liquidity(),        'daily',    6,  '中国流动性OMO/DR007'),
    ('treasury_stress_panels', lambda: ed.fetch_treasury_stress_panels(), 'daily',    6,  '国债压力三联图'),
    ('ofr_fsi',                lambda: ed.fetch_ofr_fsi(),                'daily',    8,  'OFR金融压力指数'),
    ('us_jp_yields',           lambda: ed.fetch_us_jp_yields(),           'daily',    6,  '美日收益率'),
    ('nikkei225',              lambda: ed.fetch_nikkei225(),              'daily',    6,  '日经225'),
    ('foreign_flow_japan',     lambda: ed.fetch_foreign_flow_japan(),     'weekly',   21, '日本外资周流'),
    ('foreign_custody_ust',    lambda: ed.fetch_foreign_custody_ust(),    'weekly',   14, '托管美债'),
    ('custody_acceleration',   lambda: ed.fetch_custody_acceleration(),   'weekly',   14, '托管美债加速度'),
    ('treasury_auctions',      lambda: ed.fetch_treasury_auctions(),      'daily',    10, '国债拍卖'),
    ('maturing_treasury',      lambda: ed.fetch_maturing_treasury(),      'monthly',  45, '到期美债'),
    ('country_ust_holdings',   lambda: ed.fetch_country_ust_holdings(),   'monthly',  75, '各国持美债TIC'),
    ('money_supply',           lambda: ed.fetch_money_supply(),           'monthly',  60, '货币供应'),
    ('m2_history',             lambda: ed.fetch_m2_history(),             'monthly',  60, 'M2历史'),
    ('credit_impulse',         lambda: ed.fetch_credit_impulse(),         'monthly',  75, '信贷脉冲'),
    ('iip_four_countries',     lambda: ed.fetch_iip_four_countries(),     'quarterly', 150, '四国IIP'),
    ('hf_leverage',            lambda: ed.fetch_hf_leverage(),            'quarterly', 150, '对冲基金杠杆'),
    ('bis_gold_swaps',         lambda: ed.fetch_bis_gold_swaps(),         'monthly',  120, 'BIS黄金掉期'),
    ('silver_imports_data',    lambda: ed.fetch_silver_imports_data(),    'monthly',  90, '印度白银进口'),
    ('gold_premium',           lambda: ed.fetch_gold_premium(),           'daily',    10, '金价溢价'),
    ('gold_exports',           lambda: ed.fetch_gold_exports(),           'monthly',  90, '黄金出口'),
    ('silver_bank_positions',  lambda: ed.fetch_silver_bank_positions(),  'monthly',  60, '白银银行持仓'),
    ('fiscal_budget',          lambda: ed.fetch_fiscal_budget(),          'monthly',  60, '财政预算'),
    ('fiscal_news',            lambda: ed.fetch_fiscal_news(),            'daily',    14, '财政事件时间线'),
    ('market_breadth',         lambda: ed.fetch_market_breadth(),         'daily',    6,  '市场宽度'),
    ('ad_line_real',           lambda: ed.fetch_ad_line_real(),           'daily',    6,  'A/D腾落线'),
    ('oil_inventory',          lambda: ed.fetch_oil_inventory(),          'weekly',   14, '原油库存'),
    ('basis_trade_monitor',    lambda: ed.fetch_basis_trade_monitor(),    'daily',    6,  '基差套利预警'),
    ('debt_to_gdp',            lambda: ed.fetch_debt_to_gdp(),            'biannual', 250, 'IMF债务/GDP'),
    ('corporate_credit',       lambda: ed.fetch_corporate_credit(),       'daily',    8,  '公司债'),
    ('cips',                   lambda: ed.fetch_cips(),                   'monthly',  75, 'CIPS'),
    ('ai_fcf',                 lambda: ed.fetch_ai_fcf(),                 'quarterly', 150, 'AI自由现金流'),
    ('ai_credit',              lambda: ed.fetch_ai_credit(),              'quarterly', 150, 'AI信用'),
    ('us_yield_century',       lambda: ed.fetch_us_yield_century(),       'daily',    10, '百年收益率'),
]


def main():
    only = sys.argv[1:] or None
    results = []
    for name, fn, freq, tol, label in SPECS:
        if only and name not in only:
            continue
        rec = {'name': name, 'label': label, 'freq': freq, 'tol_days': tol}
        try:
            d = fn()
            rec['status'] = (d or {}).get('status') if isinstance(d, dict) else 'n/a'
            declared = parse_date((d or {}).get('as_of') or (d or {}).get('asof')) if isinstance(d, dict) else None
            deepest = deep_max_date(d)
            asof = declared or deepest
            rec['as_of_declared'] = declared.isoformat() if declared else None
            rec['as_of_deepest'] = deepest.isoformat() if deepest else None
            if asof:
                lag = (TODAY - asof).days
                rec['as_of'] = asof.isoformat()
                rec['lag_days'] = lag
                rec['lag_bizdays'] = biz_days_between(asof, TODAY)
                if freq == 'static':
                    rec['verdict'] = 'STATIC'
                elif lag > tol:
                    rec['verdict'] = 'STALE'
                elif lag > tol * 0.7:
                    rec['verdict'] = 'WATCH'
                else:
                    rec['verdict'] = 'OK'
            else:
                rec['as_of'] = None
                rec['lag_days'] = None
                rec['verdict'] = 'NO_DATE'
            # 内部时序错位检测: declared 与 deepest 差太多 = 某个子序列掉队
            if declared and deepest and (deepest - declared).days > 3:
                rec['verdict'] = 'INTERNAL_MISMATCH'
                rec['note'] = f'声明 as_of={declared} 但内部有更新的 {deepest}'
            elif declared and deepest and (declared - deepest).days > 3:
                rec['note'] = f'声明 as_of={declared} 比内部最深 {deepest} 还新(可能是发布日非数据日)'
        except Exception as e:
            rec['verdict'] = 'ERROR'
            rec['error'] = f'{type(e).__name__}: {e}'
            rec['tb'] = traceback.format_exc()[-400:]
        results.append(rec)
        v = rec['verdict']
        print(f"{v:<18}{name:<26}{str(rec.get('as_of')):<12}"
              f"lag={str(rec.get('lag_days')):<5}tol={tol:<5}{label}")
        if rec.get('note'):
            print(f"                  ↳ {rec['note']}")
        if rec.get('error'):
            print(f"                  ↳ {rec['error']}")

    out = os.path.join(ROOT, 'scratch', 'freshness_audit.json')
    with open(out, 'w') as f:
        json.dump({'run_at': dt.datetime.now().isoformat(), 'today': TODAY.isoformat(),
                   'results': results}, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n写入 {out}')
    bad = [r for r in results if r['verdict'] in ('STALE', 'ERROR', 'NO_DATE', 'INTERNAL_MISMATCH')]
    print(f'\n=== 需关注 {len(bad)}/{len(results)} ===')
    for r in bad:
        print(f"  {r['verdict']:<18}{r['name']:<26}{r['label']}  as_of={r.get('as_of')} lag={r.get('lag_days')}")


if __name__ == '__main__':
    main()
