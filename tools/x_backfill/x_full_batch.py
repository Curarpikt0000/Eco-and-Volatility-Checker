"""批量补全时间线里 >=250 字的推文(详情页完整正文)。断点续跑, 间隔 12s, 连续 3 次失败即停。
输入 /tmp/lg_keep.json; 输出 /tmp/lg_full_text.json {id:{text,ok,tl_len,full_len}}。只读(不点赞/不关注)。
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from x_full import fetch

OUT = '/tmp/lg_full_text.json'
keep = json.load(open('/tmp/lg_keep.json'))
todo = [x for x in keep if len(x['t']) >= 250]
done = json.load(open(OUT)) if os.path.exists(OUT) else {}
fails = 0
for i, x in enumerate(todo, 1):
    if x['id'] in done and done[x['id']].get('ok'):
        continue
    try:
        r = fetch(x['id'])
    except Exception as e:  # noqa: BLE001
        r = {'text': '', 'ok': False, 'n': 0, 'err': type(e).__name__}
    r['tl_len'] = len(x['t']); r['full_len'] = len(r.get('text', ''))
    done[x['id']] = r
    json.dump(done, open(OUT, 'w'), ensure_ascii=False)
    fails = 0 if r['ok'] else fails + 1
    print(f"{i}/{len(todo)} {x['id']} ok={r['ok']} {r['tl_len']}->{r['full_len']}", flush=True)
    if fails >= 3:
        print('连续 3 次失败, 停止(不硬撑)', flush=True); sys.exit(3)
    time.sleep(12)
print('完成', sum(1 for v in done.values() if v.get('ok')), '/', len(todo))
