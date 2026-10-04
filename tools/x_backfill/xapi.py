"""X API 封装(按量计费, 带花费账本与硬上限; Chao 2026-10-04 批准预算≈$6, 上限 $8)。
★钱的上限靠代码守: 每次请求前按官方价预估, 账本累计超过 HARD_CAP 就抛错, 不靠人记得。
官方价(docs.x.com/x-api/getting-started/pricing 2026-10-04 读取): 读帖 $0.005/条, 读用户 $0.010/个, 同一资源同一UTC日内去重。
token: .env 的 X_BEARER_TOKEN_2(只读环境变量, 不打印)。
"""
import json, os, time, datetime
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(ROOT, 'data', 'x_backfill', 'x_api_spend.json')
HARD_CAP = float(os.environ.get('X_API_HARD_CAP', '8.0'))
PRICE_POST, PRICE_USER = 0.005, 0.010
BASE = 'https://api.x.com/2'


def _load_env():
    p = os.path.join(ROOT, '.env')
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if ln and not ln.startswith('#') and '=' in ln:
                k, v = ln.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _spent():
    return json.load(open(LEDGER))['total'] if os.path.exists(LEDGER) else 0.0


def _record(kind, n, usd, note=''):
    d = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {'total': 0.0, 'log': []}
    d['total'] = round(d['total'] + usd, 4)
    d['log'].append({'t': datetime.datetime.utcnow().isoformat(timespec='seconds'), 'kind': kind, 'n': n, 'usd': round(usd, 4), 'note': note})
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, 'w'), indent=1)


class BudgetExceeded(Exception):
    pass


def _guard(est):
    if _spent() + est > HARD_CAP:
        raise BudgetExceeded(f'已花 ${_spent():.2f} + 预估 ${est:.2f} 将超过上限 ${HARD_CAP:.2f}, 停止')


def _get(path, params, kind, est):
    _guard(est)
    tk = os.environ['X_BEARER_TOKEN_2']
    for attempt in range(4):
        r = requests.get(BASE + path, params=params, headers={'Authorization': 'Bearer ' + tk}, timeout=40)
        if r.status_code == 429:
            time.sleep(min(int(r.headers.get('retry-after', '5')), 60) + 1); continue
        break
    if r.status_code == 402:
        raise BudgetExceeded('402 余额耗尽')
    r.raise_for_status()
    return r


def users_by_username(handles):
    """批量查用户(<=100/次)。返回 {handle_lower: data|None}; 花费=返回的用户数×$0.01。"""
    out = {}
    for i in range(0, len(handles), 100):
        chunk = handles[i:i + 100]
        r = _get('/users/by', {'usernames': ','.join(chunk), 'user.fields': 'public_metrics,verified,verified_type,description,created_at,protected,location'},
                 'users', len(chunk) * PRICE_USER)
        d = r.json()
        got = d.get('data', [])
        for u in got:
            out[u['username'].lower()] = u
        for h in chunk:
            out.setdefault(h.lower(), None)
        _record('users', len(got), len(got) * PRICE_USER, f'{len(chunk)}查')
    return out


def tweet_text(t):
    """★长推文: text 会被截断, note_tweet.text 才是全文。"""
    return (t.get('note_tweet') or {}).get('text') or t.get('text', '')


POSTS = os.path.join(ROOT, 'data', 'x_backfill', 'x_posts_store.json')  # post_id -> 原始 JSON(已付费内容, 每页即写盘)


def _store_load():
    return json.load(open(POSTS)) if os.path.exists(POSTS) else {}


def _store_add(items):
    d = _store_load()
    new = 0
    for t in items:
        if t['id'] not in d:
            d[t['id']] = t; new += 1
    os.makedirs(os.path.dirname(POSTS), exist_ok=True)
    json.dump(d, open(POSTS + '.tmp', 'w'))
    os.replace(POSTS + '.tmp', POSTS)
    return new


def search_all(query, start, end, max_pages=20, per_query_cap=4.0, page_size=100):
    """全历史搜索。按返回条数计费($0.005/条)。
    ★每页立即落盘(崩溃不丢已付内容); ★每个 query 单独熔断 per_query_cap(默认$4, 兑现对 Chao 的承诺);
    ★页大小默认100: 预估花费=100×$0.005=$0.5, 不再按500条/页预估而误拦或超支。"""
    items, tok, spent_q = [], None, 0.0
    for _ in range(max_pages):
        if spent_q + page_size * PRICE_POST > per_query_cap:
            _record('stop', 0, 0.0, f'per-query 熔断 ${per_query_cap}: {query[:40]}'); break
        p = {'query': query, 'start_time': start, 'end_time': end, 'max_results': page_size,
             'tweet.fields': 'created_at,note_tweet,referenced_tweets,public_metrics,lang,conversation_id,in_reply_to_user_id'}
        if tok:
            p['next_token'] = tok
        r = _get('/tweets/search/all', p, 'posts', page_size * PRICE_POST)
        d = r.json(); got = d.get('data', [])
        items += got
        spent_q += len(got) * PRICE_POST
        _store_add(got)
        _record('posts', len(got), len(got) * PRICE_POST, query[:40])
        tok = d.get('meta', {}).get('next_token')
        if not tok:
            break
        time.sleep(1.1)  # search/all: 1 req/sec
    return items


if __name__ == '__main__':
    print('已花 $%.3f / 上限 $%.2f' % (_spent(), HARD_CAP))
