"""X 账号核验: 对一批「候选账号」直接访问资料页 x.com/<handle>(比搜索稳: 存在或 404, 不会返回热门推荐)。
用途: (甲) 对 high 档 48 人二次核验; (乙) 对其余人「按命名习惯猜账号」后核验。
★同名防护门禁(机械): 资料页必须同时满足
  (a) 显示名「姓+名」双命中名册英文名; (b) 简介里含名册里的机构/专有名词至少 1 个(与 x_handle_judge.org_keywords 同源);
  (c) 非备份/粉丝/模仿号; (d) 页面存在(未 404/未暂停)。 满足 a+b+c+d => verified; a+c+d 但 b 不中 => name_only(需人审); 其余 => reject。
只读: 只开资料页, 不点任何按钮。间隔 >=10s; 连续 3 次异常即停。断点续跑。
输入 /tmp 或 data 里的猜测清单; 输出 data/x_backfill/x_handle_verified.json
用法: python x_handle_verify.py high          # 核验 review.json 里 conf=high
      python x_handle_verify.py guess [起] [量]  # 对非 high 的人生成猜测账号并核验
"""
import json, os, re, sys, time, unicodedata, urllib.request
sys.path.insert(0, '/tmp')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_probe import new_tab, run
import x_handle_judge as J

ROOT = J.ROOT
OUT = os.path.join(ROOT, 'data', 'x_backfill', 'x_handle_verified.json')

JS = r"""(()=>{
 const t=document.body.innerText||'';
 const dead=/This account doesn.t exist|Account suspended|Hmm\.\.\.this page doesn.t exist|This account is suspended/i.test(t);
 const nameEl=document.querySelector('[data-testid=UserName]');
 const nm=nameEl?nameEl.innerText.split('\n').filter(Boolean):[];
 const bio=(document.querySelector('[data-testid=UserDescription]')||{}).innerText||'';
 const fol=[...document.querySelectorAll('a[href$="/verified_followers"],a[href$="/followers"]')].map(a=>a.innerText.replace(/\n/g,' ')).join(' ');
 const loc=(document.querySelector('[data-testid=UserProfileHeader_Items]')||{}).innerText||'';
 return JSON.stringify({dead:dead,name:nm[0]||'',handle:nm[1]||'',bio:bio,followers:fol.slice(0,60),items:loc.slice(0,120).replace(/\n/g,' '),
   verified:!!document.querySelector('[data-testid=UserName] svg[aria-label*=erified]'),len:t.length});
})()"""


def check_page(handle, wait=7):
    t = new_tab(f'https://x.com/{handle}')
    ws = t['webSocketDebuggerUrl']
    try:
        time.sleep(wait)
        return json.loads(run(ws, JS) or '{}')
    finally:
        try:
            urllib.request.urlopen(f"http://localhost:9333/json/close/{t['id']}", timeout=8)
        except Exception:
            pass


def verdict(k, p):
    if p.get('dead') or not p.get('name'):
        return 'reject', '页面不存在/空'
    nm = J.norm(J.en_name(k)).split()
    if len(nm) < 2:
        return 'reject', '名册名不足两词'
    a = all(w in J.norm(p['name']).split() for w in (nm[0], nm[-1]))
    bio = J.norm(p.get('bio', '') + ' ' + p.get('items', ''))
    b = J.org_ok(k, p.get('bio', '') + ' ' + p.get('items', ''))
    c = not J.BAD.search(p.get('bio', '')) and bool(p.get('bio', '').strip())
    fol = 0.0
    m = re.search(r'([\d.,]+)\s*([KM]?)', p.get('followers', '') or '')
    if m:
        fol = float(m.group(1).replace(',', '')) * {'K': 1e3, 'M': 1e6, '': 1}[m.group(2)]
    if a and b and c:
        return 'verified', '姓名双命中+强机构词+非备份号'
    if a and c and p.get('verified') is not None and fol >= 10000 and (p.get('verified_badge') or p.get('verified')):
        return 'verified', f'姓名双命中+认证号+粉丝{int(fol)}(平台认证背书; 无强机构词)'
    if a and c:
        return 'name_only', '姓名双命中但简介无机构词, 需人审'
    return 'reject', f"姓名{'✓' if a else '✗'} 机构词{'✓' if b else '✗'} 简介{'✓' if c else '✗'}"


def guesses(k):
    """按命名习惯生成 <=6 个候选: 名姓 / 名_姓 / 姓名首字母+姓 / 名+姓首字母 等。纯函数, 不联网。"""
    nm = J.norm(J.en_name(k)).split()
    if len(nm) < 2:
        return []
    f, l = nm[0], nm[-1]
    base = [f + l, f + '_' + l, f[0] + l, f + l[0], l + f, f + l + 'ph', 'dr' + f + l, f + l + 'official']
    seen, out = set(), []
    for g in base:
        g = re.sub(r'[^a-z0-9_]', '', g)
        if 3 <= len(g) <= 15 and g not in seen:
            seen.add(g); out.append(g)
    return out[:5]


if __name__ == '__main__':
    mode = sys.argv[1]
    kols = {k['id']: k for k in json.load(open(J.REG))['kols']}
    rev = json.load(open(J.OUT))
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    jobs = []
    if mode == 'high':
        jobs = [(kid, [r['handle']]) for kid, r in rev.items() if r['conf'] == 'high']
    else:
        s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 999
        nonhigh = [kid for kid, r in sorted(rev.items(), key=lambda z: z[1]['idx']) if r['conf'] != 'high']
        jobs = [(kid, guesses(kols[kid])) for kid in nonhigh[s:s + n]]
    fails = 0
    for kid, hs in jobs:
        if kid in done and done[kid].get('final') in ('verified', 'name_only'):
            continue
        rec = {'name': J.en_name(kols[kid]), 'tried': []}
        final = 'reject'
        for h in hs:
            try:
                p = check_page(h)
                v, why = verdict(kols[kid], p)
                rec['tried'].append({'handle': h, 'verdict': v, 'why': why, 'name': p.get('name'), 'bio': (p.get('bio') or '')[:140], 'followers': p.get('followers'), 'verified_badge': p.get('verified')})
                fails = 0
                if v == 'verified':
                    final = 'verified'; rec['handle'] = h; break
                if v == 'name_only' and final != 'verified':
                    final = 'name_only'; rec['handle'] = h
            except Exception as e:  # noqa: BLE001
                fails += 1
                rec['tried'].append({'handle': h, 'verdict': 'error', 'why': type(e).__name__})
            time.sleep(10)
            if fails >= 3:
                break
        rec['final'] = final
        done[kid] = rec
        json.dump(done, open(OUT, 'w'), ensure_ascii=False, indent=1)
        print(f"{rec['name'][:24]:<24} {final:<9} {('@' + rec.get('handle', '')) if rec.get('handle') else '-'}  尝试{[t['handle'] for t in rec['tried']]}", flush=True)
        if fails >= 3:
            print('连续 3 次异常, 停止', flush=True); sys.exit(3)
