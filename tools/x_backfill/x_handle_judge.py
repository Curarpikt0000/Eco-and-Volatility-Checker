"""X 候选账号 -> 置信度判定(机械规则, 不用 LLM 读)。
输入: data/x_backfill/x_handle_candidates.json + data/kol_registry.json
规则(★同名防护): 候选必须同时满足
  (a) 显示名与名册人名「姓+名」双命中(整词, 忽略大小写/重音);
  (b) 候选简介里出现名册 institution/display_name 里的「机构/职称关键词」至少 1 个(从名册文本里抽英文专有名词);
  (c) 简介不含 backup/fan/parody/not 之类声明, 且不是 0 粉丝空简介。
high = a+b+c 且候选排序第一或唯一; med = a+c 但 b 未命中(需人审); low = 其余。
输出 data/x_backfill/x_handle_review.json 和一张给人看的表。
"""
import json, os, re, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = os.path.join(ROOT, 'data', 'x_backfill', 'x_handle_candidates.json')
REG = os.path.join(ROOT, 'data', 'kol_registry.json')
OUT = os.path.join(ROOT, 'data', 'x_backfill', 'x_handle_review.json')

BAD = re.compile(r'back ?up|fan ?(account|page)|parody|not the real|unofficial|impersonat|archive|clip|quotes? from|\bcommentary\b|tribute|festival|poetry|literary|satire|\bI.m [A-Z]\w+ effin|\bfans?\b of', re.I)
GENERIC = {'china', 'chinese', 'group', 'capital', 'investment', 'investing', 'management', 'research', 'global', 'advisors', 'advisory',
           'financial', 'finance', 'economic', 'economics', 'markets', 'institute', 'international', 'partners', 'asset', 'assets',
           'strategy', 'strategies', 'macro', 'gold', 'silver', 'comment', 'outlook', 'indicator', 'force', 'bureau', 'credit', 'trading'}
STOP = {'the', 'and', 'of', 'for', 'university', 'institute', 'senior', 'research', 'fellow', 'founder', 'chief', 'officer', 'professor',
        'economist', 'analyst', 'author', 'host', 'former', 'managing', 'director', 'president', 'partner', 'head', 'global', 'markets', 'market'}


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub(r'[^a-z0-9 ]+', ' ', ''.join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def en_name(k):
    n = (k.get('short_name') or k.get('display_name') or '')
    n = re.split(r'[（(]', n)[0]
    n = re.sub(r'[\u3000-\u9fff·・]+', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def org_keywords(k):
    """从名册 institution/display_name 抽「机构/地点」类英文专有名词(首字母大写词/连续大写缩写)。"""
    txt = ' '.join([k.get('institution', ''), k.get('display_name', '')])
    own = set(norm(en_name(k)).split())  # 姓/名本身不能当机构词, 否则同名路人自己给自己背书
    kws = set()
    for m in re.findall(r"[A-Z][A-Za-z&.\-]{2,}(?: [A-Z][A-Za-z&.\-]{2,})*", txt):
        for w in re.split(r' ', m):
            w2 = norm(w)
            if w2 and w2 not in STOP and len(w2) >= 4 and w2 not in own:
                kws.add(w2)
    return kws


def org_hits(k, text):
    """返回命中的机构词(去掉通用词); 强命中=命中>=2 个, 或 1 个且长度>=6 的非通用词。"""
    t = norm(text)
    hit = [w for w in org_keywords(k) if w in t.split() or w in t]
    strong = [w for w in hit if w not in GENERIC]
    return hit, strong


def org_ok(k, text):
    hit, strong = org_hits(k, text)
    return len(strong) >= 2 or (len(strong) == 1 and len(strong[0]) >= 6)


def judge(k, cands):
    nm = norm(en_name(k)).split()
    if len(nm) < 2:
        return None, 'low', '名册名不足两个英文词'
    kws = org_keywords(k)
    best = None
    for rank, c in enumerate(cands):
        cn = norm(c['name'])
        a = all(w in cn.split() for w in (nm[0], nm[-1]))
        bio = norm(c['bio'])
        b = any(w in bio.split() or w in bio for w in kws)
        cc = not BAD.search(c['bio']) and bool(c['bio'].strip())
        score = (a, cc, b)
        if a and cc:
            conf = 'high' if (b and (rank == 0 or best is None)) else 'med'
            if best is None or (conf == 'high' and best[1] != 'high'):
                best = (c['handle'], conf, f"名{'✓' if a else '✗'} 机构词{'✓' if b else '✗'} 排{rank + 1} 认证{'是' if c['verified'] else '否'}")
    return best if best else (None, 'low', '无候选通过「姓名双命中+非备份号」')


if __name__ == '__main__':
    kols = {k['id']: k for k in json.load(open(REG))['kols']}
    cand = json.load(open(CAND))
    res = {}
    for kid, v in cand.items():
        h, conf, why = judge(kols[kid], v['cands'])
        res[kid] = {'idx': v['idx'], 'name': en_name(kols[kid]), 'handle': h, 'conf': conf, 'why': why,
                    'top3': [c['handle'] for c in v['cands'][:3]]}
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    import collections
    print(dict(collections.Counter(r['conf'] for r in res.values())))
    if '-v' in sys.argv:
        for kid, r in sorted(res.items(), key=lambda z: z[1]['idx']):
            print(f"{r['idx']:>3} {r['conf']:<4} {r['name'][:26]:<26} -> {('@'+r['handle']) if r['handle'] else '-':<18} {r['why']}")
