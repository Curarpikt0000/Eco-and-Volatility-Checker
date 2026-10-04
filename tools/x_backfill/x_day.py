"""抓取某 X 账号「本人」帖子(含回复), 单次查询一天, 读已登录 Chrome 调试端口 9333(只读)。
用法: python3 x_day.py <handle> <day YYYY-MM-DD> <out.json>
- 查询 from:<handle> since:day until:day+1  (加 -filter:replies: 回复多为评论区短回, 不收; 自己的串用 x_days 后处理按时间邻近识别)
- 只保留作者是 <handle> 的帖子(搜索结果会混入对方回复), 按推文 id 去重
- 滚动直到连续 3 次无新增; 若总数 >= 40 标记 capped(可能被截断, 需要人工复核)
"""
import json, sys, time, urllib.request, urllib.parse
sys.path.insert(0, '/tmp')
from cdp_probe import new_tab, run

handle, day, out = sys.argv[1], sys.argv[2], sys.argv[3]
import datetime
nxt = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
q = f'from:{handle} since:{day} until:{nxt} -filter:replies'
t = new_tab('https://x.com/search?q=' + urllib.parse.quote(q) + '&src=typed_query&f=live')
ws = t['webSocketDebuggerUrl']
time.sleep(7)
JS = """JSON.stringify([...document.querySelectorAll('article[data-testid=tweet]')].map(a=>{
 const tm=a.querySelector('time'); const u=[...a.querySelectorAll('a[href*="/status/"]')].map(x=>x.href).find(h=>/\\/status\\/\\d+$/.test(h))||'';
 const who=((a.querySelector('[data-testid=User-Name]')||{}).innerText||'').replace(/\\n/g,' ');
 const rep=/Replying to|回复/.test(a.innerText.slice(0,200));
 return {id:(u.match(/status\\/(\\d+)/)||[])[1]||'',when:tm?tm.getAttribute('datetime'):'',who:who,
  text:(a.querySelector('[data-testid=tweetText]')||{}).innerText||'',reply:rep,
  quoted:!!a.querySelector('[data-testid=quoteTweet], div[role=link][tabindex="0"] [data-testid=tweetText]'),url:u}}))"""
seen, stall = {}, 0
for i in range(30):
    r = json.loads(run(ws, JS) or '[]')
    before = len(seen)
    for x in r:
        if x['id'] and x['id'] not in seen:
            seen[x['id']] = x
    stall = stall + 1 if len(seen) == before else 0
    if stall >= 3:
        break
    run(ws, 'window.scrollBy(0, 2200)')
    time.sleep(3)
urllib.request.urlopen(f"http://localhost:9333/json/close/{t['id']}", timeout=8)
mine = [x for x in seen.values() if ('@' + handle.lower()) in x['who'].lower()]
rows = sorted(mine, key=lambda z: z['when'])
json.dump({'day': day, 'raw': len(seen), 'mine': len(mine), 'capped': len(seen) >= 40, 'rows': rows}, open(out, 'w'), ensure_ascii=False, indent=1)
print(f'{day} 原始{len(seen)} 本人{len(mine)} 回复{sum(1 for x in mine if x["reply"])}' + (' ⚠可能被截断' if len(seen) >= 40 else ''))
