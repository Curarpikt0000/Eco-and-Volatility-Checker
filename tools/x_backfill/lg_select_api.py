"""Luke Gromen: 用 X API 数据重做筛选(只换输入, 规则沿用 lg_select.py 一字不改, 以便新旧对账)。
输入: data/x_backfill/lukegromen_api_raw.json (API 原始, 本地不入库)
输出: /tmp/lg_final_api.json {statements, fftt_self, dropped, api_empty}
★API 的坑: ①长推文 text 会截断, 必须取 note_tweet.text; ②text 里 & 被转成 &amp;; ③仅链接/媒体的帖子 text 为空 -> 标 api_empty, 不进言论。
"""
import datetime, html, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lg_select as L  # 复用 DROP_RULES / FFTT_SELF / clean (注意: 其模块级会读 /tmp/lg_all.json, 需存在)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, 'data', 'x_backfill', 'lukegromen_api_raw.json')


def api_text(t):
    return html.unescape((t.get('note_tweet') or {}).get('text') or t.get('text', ''))


def run():
    raw = json.load(open(RAW))
    seen, items = set(), []
    for t in raw:  # 分页边界会重复返回同一条 -> 按 id 去重
        if t['id'] not in seen:
            seen.add(t['id']); items.append(t)
    out = {'statements': [], 'fftt_self': [], 'dropped': {}, 'api_empty': []}
    for x in items:
        text = api_text(x)
        t = L.clean(text)
        if not t:
            # ★引用转推且他本人无评论文字(API text 为空): 不静默丢, 单列 quote_only, 保留链接与被引用ID, 不进言论翻译
            qid = [r['id'] for r in x.get('referenced_tweets', []) if r['type'] == 'quoted']
            if qid:
                out.setdefault('quote_only', []).append({'id': x['id'], 'when': x['created_at'], 'url': f"https://x.com/LukeGromen/status/{x['id']}", 'quoted_id': qid[0]})
            out['api_empty'].append(x['id']); continue
        why = None
        t_wo_via = re.sub(r'\bVia\s+@\w+', '', t).strip()
        if len(t_wo_via) < 40:
            why = '<40字' if len(t) < 40 else '仅署名转发(Via)'
        else:
            for name, pat in L.DROP_RULES:
                if re.search(pat, t, re.I):
                    if name in ('感谢/节目', '聊天') and len(t) > 170:
                        continue
                    why = name
                    break
        if why:
            out['dropped'].setdefault(why, []).append(x['id']); continue
        jst = (datetime.datetime.fromisoformat(x['created_at'].replace('Z', '+00:00')) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
        rec = {'id': x['id'], 'date': jst, 'when': x['created_at'], 'url': f"https://x.com/LukeGromen/status/{x['id']}",
               'text': t, 'text_full': 'api_note_tweet' if x.get('note_tweet') else 'api_text',
               'quoted': any(r['type'] == 'quoted' for r in x.get('referenced_tweets', [])), 'full_len': len(t)}
        if L.FFTT_SELF.search(t):
            out['fftt_self'].append(rec)
        out['statements'].append(rec)
    out['statements'].sort(key=lambda z: z['when']); out['fftt_self'].sort(key=lambda z: z['when'])
    return out


if __name__ == '__main__':
    r = run()
    json.dump(r, open('/tmp/lg_final_api.json', 'w'), ensure_ascii=False, indent=1)
    old = {x['id'] for x in json.load(open('/tmp/lg_final.json'))['statements']}
    new = {x['id'] for x in r['statements']}
    print('API 版: 言论', len(new), '| FFTT自述', len(r['fftt_self']), '| 剔除', {k: len(v) for k, v in r['dropped'].items()}, '| API文本为空', len(r['api_empty']), '(其中引用转推无评论 %d 条, 单列保留)' % len(r.get('quote_only', [])))
    print('与旧(网页)版对账: 旧', len(old), '新', len(new), '| 两边都有', len(old & new), '| 仅新增', len(new - old), '| 仅旧版有', len(old - new))
