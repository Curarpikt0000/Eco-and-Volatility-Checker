#!/usr/bin/env python3
"""微信(搜狗)渠道试跑 —— 只产出独立文件 data/report_leads_wechat.json, 不碰 report_leads.json(线上板块)。
Chao 2026-10-07: 「微信尝试跑」。先看效果, 满意再并入板块。
复用 report_leads 的门禁(G1 名字锚点/G1b 语境/G1c 排除词/G2 窗口/G3 去重/G4 类型)。
搜狗只给标题+摘要+公众号+发布时间戳, 正文读不了 -> 全部标「正文未读」。
防限流: 间隔 5 秒; 遇 antispider 立即停并记录, 绝不硬撞; 每个查询只翻 2 页。
★对照组: 开跑前先用必有结果的查询「黄金」确认通道通; 通道不通=整体停, 不当作「没人讲」。
"""
import datetime as dt, json, os, sys, time
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_leads as R

OUT = os.path.join(R.ROOT, 'data', 'report_leads_wechat.json')


def main():
    wd = 183
    today = dt.date.today(); start = (today - dt.timedelta(days=wd)).isoformat()
    sess = requests.Session()
    try:
        ctrl = R.sogou('黄金', 1, sess)
    except Exception as e:
        print('[停] 对照查询失败:', e); return 2
    if not ctrl:
        print('[停] 对照查询「黄金」返回 0 条: 通道异常, 不继续(0 条≠没人讲)'); return 2
    print(f'对照「黄金」{len(ctrl)} 条, 通道通。窗口 {start} → {today}', flush=True)
    res, stats, stopped = {}, {}, None
    for name, (org, alias, ctx, queries) in R.TARGETS.items():
        got, raw, drop = {}, 0, {'G1': 0, 'G2': 0}
        for q in queries:
            for pg in (1, 2):
                try:
                    items = R.sogou(q, pg, sess)
                except Exception as e:
                    stopped = f'{name} / {q} p{pg}: {type(e).__name__} {str(e)[:50]}'
                    print('[停]', stopped, flush=True); break
                raw += len(items)
                for x in items:
                    ts = x['ts']
                    d = dt.datetime.fromtimestamp(ts).date().isoformat() if ts else ''
                    it = {'title': x['title'], 'summary': x['summary']}
                    if not R.passes_gates(name, it, alias, ctx):
                        drop['G1'] += 1; continue
                    if not d or d < start or d > today.isoformat():
                        drop['G2'] += 1; continue
                    k = R._norm(x['title'])
                    e = got.setdefault(k, {'title': x['title'], 'date': d, 'summary': x['summary'], 'sources': [],
                                           'type': R.classify(x['title'], x['summary'])})
                    if not any(s['url'] == x['href'] for s in e['sources']):
                        e['sources'].append({'acct': x['acct'], 'url': x['href'], 'platform': '微信公众号'})
                time.sleep(5)
            if stopped:
                break
        res[name] = {'org': org, 'items': sorted(got.values(), key=lambda z: z['date'], reverse=True)}
        stats[name] = {'raw': raw, 'kept': len(got), **drop}
        print(f'[{name}] 原始 {raw} → 过门禁 {len(got)} (G1丢 {drop["G1"]}, 窗口外丢 {drop["G2"]})', flush=True)
        if stopped:
            break
    payload = {'generated': dt.datetime.now().isoformat(timespec='seconds'), 'window_days': wd,
               'channel': '搜狗微信搜索(摘要=平台自带,正文未读)', 'stopped': stopped, 'stats': stats, 'orgs': res}
    json.dump(payload, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('合计', sum(len(v['items']) for v in res.values()), '条 →', OUT, '| 中途停止:', stopped)
    return 3 if stopped else 0


if __name__ == '__main__':
    sys.exit(main())
