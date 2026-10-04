"""补全被 X 时间线折叠的长推文(只读: 不点赞/不关注/不展开回复)。
时间线里长推文只给前约 280 字; 详情页 /status/<id> 才有完整正文。
用法: python x_full.py <tweet_id> [<tweet_id> ...] -> 打印 JSON {id: {text, ok, n}}
★校验: 详情页第一个 article 必须就是该 id 本人推文(链接含 /status/<id>), 否则 ok=False(防读到别的串)。
"""
import json, sys, time, urllib.request
sys.path.insert(0, '/tmp')
from cdp_probe import new_tab, run

JS = r"""(()=>{
 const id=%s;
 const arts=[...document.querySelectorAll('article[data-testid=tweet]')];
 for(const a of arts){
   const links=[...a.querySelectorAll('a[href*="/status/"]')].map(x=>x.getAttribute('href')||'');
   const mine=links.some(h=>h.includes('/status/'+id));
   const who=((a.querySelector('[data-testid=User-Name]')||{}).innerText||'');
   if(mine && /LukeGromen/i.test(who+links.join(' '))){
     const t=(a.querySelector('[data-testid=tweetText]')||{}).innerText||'';
     const more=!!a.querySelector('[data-testid=tweet-text-show-more-link]');
     return JSON.stringify({text:t,more:more,n:arts.length});
   }
 }
 return JSON.stringify({text:'',more:false,n:arts.length});
})()"""


def fetch(tid, wait=7):
    t = new_tab(f'https://x.com/LukeGromen/status/{tid}')
    ws = t['webSocketDebuggerUrl']
    try:
        time.sleep(wait)
        r = json.loads(run(ws, JS % json.dumps(tid)) or '{}')
        # 还有 show more 链接 → 不应在详情页出现; 出现则视为未取全
        return {'text': r.get('text', ''), 'ok': bool(r.get('text')) and not r.get('more'), 'n': r.get('n', 0)}
    finally:
        try:
            urllib.request.urlopen(f"http://localhost:9333/json/close/{t['id']}", timeout=8)
        except Exception:
            pass


if __name__ == '__main__':
    out = {}
    for tid in sys.argv[1:]:
        out[tid] = fetch(tid)
    print(json.dumps(out, ensure_ascii=False))
