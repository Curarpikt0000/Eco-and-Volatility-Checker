"""X 账号核对: 对名册 KOL 搜 X 人物, 取候选账号(简介/粉丝/认证), 输出核对表供 Chao 审。
★铁律(同名防护): 只有「账号简介/显示名与名册里的机构/职称有可核对的重合」才标 match=high; 否则 low/none, 不自动采用。
只读: 不点赞/不关注。间隔 >=10s; 连续 3 次失败即停。断点续跑。
输出 data/x_backfill/x_handle_candidates.json: {kol_id:{name, q, cands:[{handle,name,bio,followers,verified}]}}
用法: python x_handle_probe.py [起始序号] [条数]
"""
import json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, '/tmp')
from cdp_probe import new_tab, run

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REG = os.path.join(ROOT, 'data', 'kol_registry.json')
OUT = os.path.join(ROOT, 'data', 'x_backfill', 'x_handle_candidates.json')

JS = r"""(()=>{
 const cells=[...document.querySelectorAll('[data-testid=UserCell]')].slice(0,5);
 return JSON.stringify(cells.map(c=>{
   const links=[...c.querySelectorAll('a[href^="/"]')].map(a=>a.getAttribute('href'));
   const handle=(links.find(h=>/^\/[A-Za-z0-9_]{1,15}$/.test(h))||'').slice(1);
   const txt=c.innerText.split('\n').filter(Boolean);
   const ver=!!c.querySelector('[data-testid=icon-verified]');
   const bio=txt.slice(2).filter(x=>x!=='Follow'&&x!=='Following').join(' ');
   return {handle:handle,name:txt[0]||'',bio:bio.slice(0,260),verified:ver};
 }));
})()"""


def short_query(k):
    """搜索词: display_name 的英文部分(去掉括号后的长简介和中文译名)。"""
    n = k.get('short_name') or k.get('display_name') or ''
    n = re.split(r'[（(]', n)[0]
    n = re.sub(r'[\u3000-\u9fff·・]+', ' ', n)  # 去 CJK
    return re.sub(r'\s+', ' ', n).strip()


def probe(q, wait=7):
    # ★实测: 直接带 f=user 会被带到「热门/推荐」(返回特朗普/纳德拉等噪声); 必须先搜索再点 People 标签(只读导航)。
    u = 'https://x.com/search?q=' + urllib.parse.quote(q) + '&src=typed_query'
    t = new_tab(u)
    ws = t['webSocketDebuggerUrl']
    try:
        time.sleep(wait)
        run(ws, """(()=>{const a=[...document.querySelectorAll('a[role=tab]')].find(x=>/People/i.test(x.innerText)); if(a) a.click(); return !!a})()""")
        time.sleep(5)
        return json.loads(run(ws, JS) or '[]')
    finally:
        try:
            urllib.request.urlopen(f"http://localhost:9333/json/close/{t['id']}", timeout=8)
        except Exception:
            pass


if __name__ == '__main__':
    kols = json.load(open(REG))['kols']
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    fails = 0
    for i, k in enumerate(kols[start:start + cnt], start):
        if k['id'] in done:
            continue
        q = short_query(k)
        try:
            c = probe(q)
            done[k['id']] = {'idx': i, 'name': k.get('short_name') or k.get('display_name'), 'q': q, 'cands': c}
            fails = 0
            print(f"{i} {q!r} -> {[x['handle'] for x in c]}", flush=True)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"{i} {q!r} 失败 {type(e).__name__}", flush=True)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(done, open(OUT, 'w'), ensure_ascii=False, indent=1)
        if fails >= 3:
            print('连续 3 次失败, 停止', flush=True); sys.exit(3)
        time.sleep(10)
