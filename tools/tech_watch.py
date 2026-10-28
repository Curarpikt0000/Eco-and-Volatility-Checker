#!/usr/bin/env python3
"""短期技术派金银分析 — 采集层(no_agent 可跑, 也供 agent 模式作 pre-script)。
输出一份「今天有什么可读」的结构化清单(JSON)到 stdout, 由 agent 读后写成 Telegram 短报。
设计铁律:
  - 只收「有原文可读」的价位; 视频只记 标题+链接+发布日, 正文未读(VM IP 被 YouTube 判机器人, 字幕抓不到, 2026-10-05 实测)
  - 不编数字: 价位只能来自 body 里的原句
  - 对照组: 每个来源输出 fetched/ok/err 三数, 0 条不等于「没人说」
来源:
  A YouTube RSS(三位技术派) — 视频元数据, 不读字幕
  B Kitco: news + opinions + video sitemap 近 2 天 — 文章正文, 命中「技术派信号词」且含 gold/silver
  C Gold-Eagle / Zeal(goldseek) RSS — 文字文章
"""
import datetime, html, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'tech_watch')
STATE = os.path.join(D, 'state.json')
UA = {'User-Agent': 'Mozilla/5.0'}
SP = re.compile(r'\s+')
clean = lambda s: SP.sub(' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()
LOOKBACK = int(os.environ.get('TECH_LOOKBACK', '2'))
YT = {'Chris Vermeulen': 'UCenLy4V5NgxEz7pwosA9hiw', 'Gareth Soloway': 'UCwTu6kD2igaLMpxswtcdxlg', 'Jordan Roy-Byrne': 'UCE_edD0qJd_EyfwGCfLHSeQ'}
# 技术派信号词: 命中任一才算「技术分析」(不是宏观评论/新闻稿)
TECH = re.compile(r'support|resistance|breakout|breakdown|moving average|200[- ]day|50[- ]day|trend ?line|fibonacci|RSI|MACD|oversold|overbought|CTA|technical|chart|pivot|golden cross|death cross|retest|downside target|upside target', re.I)
METAL = re.compile(r'\bgold\b|\bsilver\b', re.I)
PRICE = re.compile(r'\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d{2,3}(?:\.\d+)?\b|\b\d{1,2},\d{3}\b|(?<![\d.,])[1-9]\d{3}(?![\d,])(?!\s*(?:年|%|-day|day))')
# 技术派白名单: Kitco 里只收这些作者/栏目的技术分析文(新闻稿类 'Gold prices see sold bid' 不是技术派, Chao 2026-10-05 要求只收技术分析派)
TECH_TITLE = re.compile(r'\b(technical|support at|key support|resistance|breakout|breakdown|trend|chart|trigger|moving average|oversold|overbought|retest|floor|price target|cycle|CTA)\b|\$\s?\d,\d{3}\s+support', re.I)
# 正文必须真有技术要素: 至少 2 个不同的技术词 + 至少 2 个价位数字, 才算技术分析(挡掉「标题含 supports 的基本面采访」)
TECH_BODY = re.compile(r'\b(support|resistance|moving average|200[- ]day|50[- ]day|trend ?line|fibonacci|RSI|MACD|oversold|overbought|breakout|breakdown|retest|pivot)\b', re.I)


def is_tech(body):
    """正文真是技术分析: >=2 个不同技术词 且 >=2 个价位数字。"""
    return len({w.lower() for w in TECH_BODY.findall(body)}) >= 2 and len(set(PRICE.findall(body))) >= 2


# B 通道「机构派短期价位」: 非技术派, 但原文里有明确的预测措辞 + 金银价位(Chao 2026-10-05 选 A+B)
FCST = re.compile(r'\b(price target|target|forecast|expects?|sees?|projects?|predicts?|could (?:reach|hit|fall|drop|test|rise)|will (?:reach|hit|test)|by (?:the )?(?:end of|year-end|december|november|october|q[1-4])|next (?:month|few weeks|quarter|three months|12 months)|short[- ]term|near[- ]term)\b', re.I)
ATTR = re.compile(r'\b(says?|said|told|according to|in a (?:note|report|interview)|expects?|sees?)\b', re.I)
NEWSWIRE = re.compile(r'^(gold|silver)[, ].{0,40}(prices?|rise|fall|slip|edge|climb|drop|struggl)|kitco (?:am|pm|asia|europe) report|\b(?:am|pm) report\b', re.I)   # 行情播报不算
# 金银价位带(2026-10 金约 4,000-4,500、银约 55-65): 正文要有至少 2 个落在带内的价位, 才算「在谈金银价」(挡掉比特币 $100,000、进口 $306 等)
def _metal_prices(body):
    out = set()
    for s in re.findall(r'\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?)\b', body):
        try: v = float(s.replace(',', ''))
        except ValueError: continue
        if 2500 <= v <= 7500 or 45 <= v <= 85:
            out.add(v)
    return out


PROMO = re.compile(r'click here|to listen to one of the greatest|subscribe|sign up|special offer|join (?:now|today)|limited[- ]time|free report|webinar', re.I)


def _fcst_sentences(body):
    """同一句里既有预测措辞、又有金银价位带内的 $ 价位 -> 才是「某人对价位的预测」。返回这些句子(给 agent 抄原句用)。
    促销句(CLICK HERE / 订阅 / 广告)一律剔除: KWN 每篇文末都有 Nomi Prins 采访广告, 含 '$6,000 gold' 但不是当天分析。"""
    sents = re.split(r'(?<=[.!?])\s+', body)
    hit = []
    for s in sents:
        if len(s) > 400 or PROMO.search(s): continue
        if (FCST2.search(s) or FCST3.search(s)) and _metal_prices(s):
            hit.append(s.strip())
    return hit
# 预测动词: 去掉 "see/sees" 的通用义项, 只保留 "sees ... (price|gold|silver) ... to/falling/rising/at" 这类结构
FCST2 = re.compile(r'(?:price target|year-end|by (?:the )?end of|forecast(?:s|ed)?|expects? (?:gold|silver|prices?|the (?:price|metal))|sees? (?:gold|silver|prices?) (?:fall|drop|rall|rise|climb|reach|hit|test|trad|averag|end)\w*|could (?:reach|hit|fall|drop|test|rise)|will (?:reach|hit|test|fall|drop|rise)|falling to|rising to|to (?:reach|hit) \$)', re.I)
# 条件/区间类措辞: "remain above $4,000" "break above $4,400" "target of $5,000" "downside to $3,750" "$6,000 target"
FCST3 = re.compile(r'(?:remain|stay|hold|trad\w+|break|close|move|fall|drop|slide|rall\w+|rise|climb|test)\w*\s+(?:back\s+)?(?:above|below|to|toward|towards|under|over)\s+\$|(?:target|goal|objective)s?\s+(?:of|at|is|to)\s+\$|\$\s?[\d,]+\s+(?:target|support|resistance|level)|(?:downside|upside)\s+(?:to|target|risk)', re.I)


def is_inst(title, body):
    """机构派: 非行情播报 + 有归属句 + 至少 1 个「预测措辞与金银价位同在一句」的句子 + 带内价位 >=2 个。
    判定与抽句用同一段文本(调用方传入的 body 即最终交给 agent 的那段), 否则出现「判定通过却抽不到句子」(2026-10-05 实测)。"""
    if NEWSWIRE.search(title.strip()):
        return False
    return bool(ATTR.search(body[:3000])) and len(_fcst_sentences(body)) >= 1 and len(_metal_prices(body)) >= 2


def get(u, t=30):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read().decode('utf-8', 'ignore')


def jl(p, d):
    return json.load(open(p)) if os.path.exists(p) else d


def jd(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p + '.tmp', 'w'), ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)


def _yt_rss(cid):
    """主通道: RSS(带发布日)。2026-10 起对这批频道返回 404, 失败则返回 (None, 原因)。"""
    try:
        return re.findall(r'<entry>(.*?)</entry>', get(f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}'), re.S), ''
    except urllib.error.HTTPError as ex:
        return None, f'rss HTTP {ex.code}'
    except Exception as ex:  # noqa: BLE001
        return None, f'rss {type(ex).__name__}: {str(ex)[:60]}'


def _yt_flat(cid, n=8):
    """备用通道: yt-dlp --flat-playlist 列 /videos(无需 cookie; 只给 id+标题, 没有发布日)。"""
    import subprocess
    try:
        p = subprocess.run(['yt-dlp', '--no-update', '--no-warnings', '--flat-playlist', '--playlist-end', str(n),
                            '--print', '%(id)s|%(title)s', f'https://www.youtube.com/channel/{cid}/videos'],
                           capture_output=True, text=True, timeout=150)
        rows = [l.split('|', 1) for l in p.stdout.splitlines() if '|' in l]
        if rows:
            return rows, ''
        return None, f'ytdlp rc={p.returncode} {(p.stderr or "").strip()[-80:]}'
    except Exception as ex:  # noqa: BLE001
        return None, f'ytdlp {type(ex).__name__}: {str(ex)[:60]}'


def src_yt(since, h):
    out = []
    for n, cid in YT.items():
        h['yt'][n] = {'fetched': 0, 'err': '', 'via': ''}
        ents, why = _yt_rss(cid)
        if ents is not None:
            h['yt'][n].update(via='rss', fetched=len(ents))
            for e in ents:
                d = re.search(r'<published>(.*?)</published>', e).group(1)[:10]
                if d >= since:
                    out.append(dict(kind='video', channel='tech', who=n, date=d, title=html.unescape(re.search(r'<title>(.*?)</title>', e).group(1)),
                                    url='https://youtu.be/' + re.search(r'<yt:videoId>(.*?)</yt:videoId>', e).group(1), body_read=False))
            continue
        rows, why2 = _yt_flat(cid)
        if rows is None:
            h['yt'][n]['err'] = f'{why} | {why2}'
            continue
        # 备用通道没有发布日: date 留空并标 date_unknown, 以 seen 去重(新 id 才算新); 不拿抓取日冒充发表日
        h['yt'][n].update(via='yt-dlp-flat', fetched=len(rows), err=f'{why}(已切备用通道, 无发布日)')
        for vid, title in rows:
            out.append(dict(kind='video', channel='tech', who=n, date='', date_unknown=True, title=html.unescape(title),
                            url='https://youtu.be/' + vid, body_read=False))
    return out


def kitco_item(u):
    h = get(u)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return None
    a = json.loads(m.group(1))['props']['pageProps'].get('articleData') or {}
    raw = (a.get('bodyWithEmbeddedMedia') or {}).get('value') or ''
    return (a.get('title') or ''), clean(raw)


def src_kitco(since, seen, h):
    out = []
    h['kitco'] = {'sitemap_urls': 0, 'new': 0, 'read': 0, 'err': []}
    for cat in ['news', 'opinions']:
        try:
            urls = re.findall(r'<loc>([^<]+)</loc>', get(f'https://www.kitco.com/static-sitemaps/{cat}.xml', 60))
        except Exception as ex:  # noqa: BLE001
            h['kitco']['err'].append(f'{cat}:{type(ex).__name__}'); continue
        h['kitco']['sitemap_urls'] += len(urls)
        for u in urls:
            m = re.search(r'/(\d{4}-\d{2}-\d{2})/', u)
            if not (m and m.group(1) >= since) or u in seen:
                continue
            if not METAL.search(u.split('/')[-1].replace('-', ' ')) and cat == 'news':
                # 标题 slug 不含 gold/silver 的新闻先跳过(省请求); 观点区不跳
                continue
            h['kitco']['new'] += 1
            try:
                r = kitco_item(u); time.sleep(0.5)
                if not r:
                    continue
                title, body = r; h['kitco']['read'] += 1
                if METAL.search(title + body[:1500]):
                    body = body[:14000]   # 判定与交给 agent 的是同一段文本, 否则会「判定通过、抽不到句」
                    if TECH_TITLE.search(title) and is_tech(body):
                        out.append(dict(kind='article', channel='tech', who='Kitco/' + cat, date=m.group(1), title=title, url=u, body=body, body_read=True))
                    elif is_inst(title, body):
                        out.append(dict(kind='article', channel='inst', who='Kitco/' + cat, date=m.group(1), title=title, url=u, body=body, body_read=True, fcst_sentences=_fcst_sentences(body)[:4]))
                seen.add(u)
            except Exception as ex:  # noqa: BLE001
                h['kitco']['err'].append(type(ex).__name__)
    return out


def src_rss(since, h):
    out = []
    for n, u in {'GoldSeek': 'https://goldseek.com/rss.xml', 'Gold-Eagle': 'https://www.gold-eagle.com/rss.xml'}.items():
        h['rss'][n] = {'fetched': 0, 'err': ''}
        try:
            x = get(u); items = re.findall(r'<item>(.*?)</item>', x, re.S); h['rss'][n]['fetched'] = len(items)
            import email.utils
            for b in items:
                t = clean(re.sub(r'<!\[CDATA\[|\]\]>', '', (re.search(r'<title>(.*?)</title>', b, re.S) or [0, ''])[1]))
                l = (re.search(r'<link>(.*?)</link>', b, re.S) or [0, ''])[1].strip()
                dm = re.search(r'<pubDate>(.*?)</pubDate>', b)
                try: d = email.utils.parsedate_to_datetime(dm.group(1)).date().isoformat()
                except Exception: d = ''
                c = clean(re.sub(r'<!\[CDATA\[|\]\]>', '', (re.search(r'<content:encoded>(.*?)</content:encoded>', b, re.S) or re.search(r'<description>(.*?)</description>', b, re.S) or [0, ''])[1]))
                c = re.sub(r'^.*?class="text-long">', '', c)   # GoldSeek 摘要带 Drupal 残留标签
                if d >= since and METAL.search(t + c[:800]) and TECH.search(t + ' ' + c):
                    out.append(dict(kind='article', channel='tech', who=n, date=d, title=t, url=l, body=c[:14000], body_read=len(c) > 600))
        except Exception as ex:  # noqa: BLE001
            h['rss'][n]['err'] = type(ex).__name__
    return out


def src_kwn(since, h):
    """KWN: wp-json 一次取近几天文章; 只收有归属+预测措辞+价位的(B 通道)。访谈页(标题是嘉宾名)正文多为空壳, 不进此通道。"""
    out = []
    h['kwn'] = {'fetched': 0, 'err': ''}
    try:
        arr = json.loads(get(f'https://kingworldnews.com/wp-json/wp/v2/posts?per_page=100&after={since}T00:00:00&_fields=date,link,title,content'))
        h['kwn']['fetched'] = len(arr)
        for p in arr:
            t = clean(p['title']['rendered']); b = clean(p['content']['rendered'])[:14000]
            if METAL.search(t + b[:1500]) and is_inst(t, b):
                out.append(dict(kind='article', channel='inst', who='KWN', date=p['date'][:10], title=t, url=p['link'], body=b, body_read=True, fcst_sentences=_fcst_sentences(b)[:4]))
    except Exception as ex:  # noqa: BLE001
        h['kwn']['err'] = type(ex).__name__
    return out


def main():
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=LOOKBACK)).isoformat()
    st = jl(STATE, {'seen': [], 'items': []}); seen = set(st['seen'])
    h = {'yt': {}, 'rss': {}}
    items = src_yt(since, h) + src_kitco(since, seen, h) + src_kwn(since, h) + src_rss(since, h)
    old = {i['url'] for i in st['items']}
    new = [i for i in items if i['url'] not in old]
    for i in new:
        if i.get('body'):
            i['prices_in_text'] = sorted(set(PRICE.findall(i['body'])))[:25]
    st['seen'] = sorted(seen)[-5000:]; st['items'] = (st['items'] + [{k: v for k, v in i.items() if k != 'body'} for i in new])[-400:]
    jd(STATE, st)
    print(json.dumps(dict(date=today.isoformat(), since=since, health=h, new=new), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
