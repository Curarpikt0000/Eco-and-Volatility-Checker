"""Luke Gromen X 推文 -> 言论候选(规则筛选; Chao 2026-10-03 定口径)。
口径: 一条推文一条言论, 不合并、不去重; 引用转推保留(评论是他本人写的);
      剔除: 纯转发(RT/Via)、家事、感谢上节目、聊天、<40字、纯链接/表情、作者自述 FFTT 报告(分流到报告板块)。
输入: /tmp/lg_all.json(时间线) + /tmp/lg_full_text.json(>=250字的详情页完整正文, 以此覆盖截断文本)
输出: /tmp/lg_final.json {statements:[...], fftt_self:[...], dropped:{原因:[id..]}}
★每条记录 text_full 标记来源: 'detail'(详情页完整) / 'timeline'(时间线, <250字视为完整)
"""
import datetime
import json
import re

ALL = json.load(open('/tmp/lg_all.json'))
FULL = json.load(open('/tmp/lg_full_text.json'))

DROP_RULES = [
    ('转发RT', r'^\s*RT @'),
    ('家事', r'my (middle |oldest |youngest )?(son|daughter|wife)\b|Mrs\. FFTT|engaged|birthday|refrigerator|Frigidaire'),
    ('感谢/节目', r'^\W{0,3}(thanks?|thank you)\b|^1/ I.m recording a|come for the .{0,20}impression|catching up|why 40 years of US economic policy is reversing'),
    ('聊天', r'^\W{0,3}(fun|another fun|had the chance to talk)\b|laughing|my ribs'),
    ('BREAKING', r'^\s*BREAKING'),
]
# 作者自述 FFTT 报告(一手露出): 提到「某日期的 FFTT 报告/版本」
FFTT_SELF = re.compile(
    r'(edition of FFTT|FFTT full report|FFTT report|When we published this report|-\s*FFTT,|FFTT has been telling clients|FFTT remains)', re.I)


def clean(t):
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'\n\s*(x\.com|pic\.twitter)\S*', '', t)
    return re.sub(r'[ \t]+', ' ', t).strip()


def run():
    out = {'statements': [], 'fftt_self': [], 'dropped': {}}
    for x in ALL:
        raw = x['text']
        f = FULL.get(x['id'])
        if f and f.get('ok') and len(f['text']) >= len(raw):
            text, src = f['text'], 'detail'
        else:
            text, src = raw, 'timeline'
        t = clean(text)
        why = None
        t_wo_via = re.sub(r'\bVia\s+@\w+', '', t).strip()
        if len(t_wo_via) < 40:
            why = '<40字' if len(t) < 40 else '仅署名转发(Via)'
        else:
            for name, pat in DROP_RULES:
                if re.search(pat, t, re.I):
                    if name in ('感谢/节目', '聊天') and len(t) > 170:
                        continue  # 感谢 + 长文 = 后面带观点/数据, 保留
                    why = name
                    break
        if why:
            out['dropped'].setdefault(why, []).append(x['id'])
            continue
        jst = (datetime.datetime.fromisoformat(x['when'].replace('Z', '+00:00')) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
        rec = {'id': x['id'], 'date': jst, 'when': x['when'], 'url': x['url'], 'text': t, 'text_full': src,
               'quoted': str(x.get('quoted')) == 'True', 'tl_len': len(clean(raw)), 'full_len': len(t)}
        if FFTT_SELF.search(t):
            out['fftt_self'].append(rec)
        out['statements'].append(rec)  # Chao 2: FFTT 自述同时上言论卡片, 另抄一份进报告板块
    out['statements'].sort(key=lambda z: z['when'])
    out['fftt_self'].sort(key=lambda z: z['when'])
    return out


if __name__ == '__main__':
    r = run()
    json.dump(r, open('/tmp/lg_final.json', 'w'), ensure_ascii=False, indent=1)
    print('言论', len(r['statements']), '| FFTT自述(另抄报告板块)', len(r['fftt_self']),
          '| 剔除', {k: len(v) for k, v in r['dropped'].items()})
    print('来源: 详情页完整', sum(1 for s in r['statements'] if s['text_full'] == 'detail'),
          '| 时间线', sum(1 for s in r['statements'] if s['text_full'] == 'timeline'),
          '| 其中被补长', sum(1 for s in r['statements'] if s['full_len'] > s['tl_len'] + 5))
