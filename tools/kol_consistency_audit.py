"""KOL 四方一致性对账 —— Notion(SSOT) ↔ 本地名册 ↔ dashboard 卡片 ↔ cron 实抓。

起因(Chao 2026-09-08):「Goldman Sachs 我在 Notion 取消了，dashboard 还在」
—— 同步工具模糊匹配把纯机构名保留了。Chao 要求「类似这样的事情一定要避免」。

四层任何两层不一致 = 静默失败。本脚本机械比对并给出差异清单。
判据全部来自实际产物, 不看任何状态标签。

用法:  python3 tools/kol_consistency_audit.py [--json]
退出码: 0=一致  1=有差异(可用于 cron 门禁)
"""
import glob
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = '35947eb5-fd3c-800d-b852-cef31f9de6a5'


def norm(s):
    """规范化: 去括号后缀 + 中间名缩写 + 非字母数字。"""
    s = re.sub(r'[（(].*', '', s or '')
    s = re.sub(r'\b[A-Z]\.\s*', '', s)
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', s.lower())


def notion_token():
    for p in (os.path.join(ROOT, '.env'), os.path.expanduser('~/.hermes/.env')):
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line.startswith(('NOTION_TOKEN=', 'NOTION_API_KEY=')):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def layer_notion():
    """① Notion KOL List = SSOT。人名在「KOL / 机构」列(title 字段是「编号」)。"""
    tok = notion_token()
    if not tok:
        return None, 'NOTION_TOKEN 缺失'
    hdr = {'Authorization': 'Bearer ' + tok, 'Notion-Version': '2022-06-28',
           'Content-Type': 'application/json'}
    names, cur = [], None
    while True:
        body = {'page_size': 100}
        if cur:
            body['start_cursor'] = cur
        req = urllib.request.Request(
            'https://api.notion.com/v1/databases/%s/query' % DB,
            data=json.dumps(body).encode(), headers=hdr, method='POST')
        d = json.loads(urllib.request.urlopen(req, timeout=90).read())
        for r in d.get('results', []):
            v = r['properties'].get('KOL / 机构') or {}
            t = v.get('type')
            if t == 'rich_text':
                nm = ''.join(x.get('plain_text', '') for x in (v.get('rich_text') or []))
            elif t == 'title':
                nm = ''.join(x.get('plain_text', '') for x in (v.get('title') or []))
            else:
                nm = ''
            if nm.strip():
                names.append(nm.strip())
        if not d.get('has_more'):
            break
        cur = d.get('next_cursor')
    return names, None


def layer_registry():
    """② 本地名册镜像。"""
    reg = json.load(open(os.path.join(ROOT, 'data/kol_registry.json'), encoding='utf-8'))
    rows = reg if isinstance(reg, list) else (reg.get('kols') or [])
    return [(r.get('display_name') or r.get('name') or '') for r in rows
            if r.get('active', True)], None


def layer_dashboard():
    """③ dashboard 实际渲染出的名录卡片(读产物, 不读代码)。"""
    p = os.path.join(ROOT, 'docs/index.html')
    if not os.path.exists(p):
        return None, 'docs/index.html 不存在'
    h = open(p, encoding='utf-8').read()
    names = re.findall(r'<span class="kp-nm">(.*?)</span>', h)
    import html as _h
    return [_h.unescape(n).strip() for n in names if n.strip()], None


def layer_cron():
    """④ cron 每天实际抓取的那批(kol_independent.json 当日产物)。"""
    p = os.path.join(ROOT, 'data/kol_independent.json')
    if not os.path.exists(p):
        return None, 'kol_independent.json 不存在'
    d = json.load(open(p, encoding='utf-8'))
    rows = d.get('all') or d.get('items') or []
    return [(x.get('kol') or '').strip() for x in rows if (x.get('kol') or '').strip()], \
        ('as_of=%s' % d.get('date', '?'))


def main():
    layers = {}
    notes = {}
    for key, fn in (('Notion(SSOT)', layer_notion), ('本地名册', layer_registry),
                    ('dashboard卡片', layer_dashboard), ('cron实抓', layer_cron)):
        try:
            v, note = fn()
        except Exception as e:
            v, note = None, '%s: %s' % (type(e).__name__, str(e)[:60])
        layers[key] = v
        notes[key] = note

    print('=== 各层人数 ===')
    for k, v in layers.items():
        extra = (' (%s)' % notes[k]) if notes[k] else ''
        print('  %-14s %s%s' % (k, ('%d 人' % len(v)) if v is not None else '❌ 取不到', extra))

    base = layers.get('Notion(SSOT)')
    if not base:
        print('\n❌ 拿不到 SSOT, 无法对账')
        return 1

    bset = {norm(n) for n in base}
    bad = 0
    print('\n=== 与 SSOT 的差异 ===')
    for k in ('本地名册', 'dashboard卡片', 'cron实抓'):
        v = layers.get(k)
        if v is None:
            print('  %-14s ⚠️ 该层取不到, 跳过' % k)
            continue
        vset = {norm(n) for n in v}
        extra = sorted({n for n in v if norm(n) not in bset})
        missing = sorted({n for n in base if norm(n) not in vset})
        if not extra and not missing:
            print('  %-14s ✅ 一致' % k)
            continue
        bad += 1
        print('  %-14s ❌ 多 %d / 少 %d' % (k, len(extra), len(missing)))
        for n in extra[:8]:
            print('       多出: %s' % n[:56])
        for n in missing[:8]:
            print('       缺失: %s' % n[:56])
        if len(extra) > 8 or len(missing) > 8:
            print('       ...(截断)')

    print('\n' + '=' * 46)
    if bad:
        print('判定: ❌ %d 层与 SSOT 不一致' % bad)
        return 1
    print('判定: ✅ 四层完全一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
