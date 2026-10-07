#!/usr/bin/env python3
"""Chao 2026-10-07 定: 日更 20 个高质量 X 账号, 网页回填 6 个月(2026-04-07 ~ 今天)。
生成「每账号一个区间」的 JSON, 供 x_backfill_6m.py 顺序执行。不碰网络, 不删文件。
缺口 = [窗口起点, 已覆盖最早日-1]; 已覆盖最早日 = min(API oldest, 已抓网页日最早)。
API 已覆盖到窗口起点以前的账号跳过(ChinaIndicator/DAcemogluMIT/DaveHcontrarian/Jkylebass/RealJimRickards/TruthGundlach)。
"""
import datetime, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_daily_scan as S
TODAY = datetime.date.today()
START = datetime.date(2026, 4, 7)
cur = json.load(open(os.path.join(S.DATA, 'x_scan_cursor.json')))
exc = {x.lower() for x in json.load(open(os.path.join(S.DATA, 'x_scan_exclude.json')))}
api = json.load(open(os.path.join(S.DATA, 'x_backfill_api_state.json')))['done']
plan = {}
for a in sorted(cur, key=str.lower):
    if a.lower() in exc:
        continue
    old = (api.get(a) or {}).get('oldest') or ''
    wd = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(S.DATA, 'web_rows', a, '*.json')))
    cands = [x for x in [old] + wd[:1] if x]
    # 已有任何网页日文件的"连续性"不假设: 只按文件存在跳过, 区间取 [START, 最早覆盖-1]
    first = min(cands) if cands else str(TODAY)
    to = datetime.date.fromisoformat(first) - datetime.timedelta(days=1)
    if to < START:
        continue
    plan[a] = {'from': str(START), 'to': str(to), 'days': (to - START).days + 1, 'status': (api.get(a) or {}).get('status', '-')}
out = os.path.join(S.DATA, 'x_backfill_6m_plan.json')
json.dump(plan, open(out, 'w'), ensure_ascii=False, indent=1)
tot = sum(v['days'] for v in plan.values())
for a, v in sorted(plan.items(), key=lambda kv: kv[1]['days']):
    print(f"  @{a:<16} {v['from']}→{v['to']}  {v['days']:>3}天  [{v['status']}]")
print(f'\n共 {len(plan)} 账号 / {tot} 账号·日, 单日约 20s(12s 间隔+加载) ≈ {tot*20/3600:.1f} 小时')
