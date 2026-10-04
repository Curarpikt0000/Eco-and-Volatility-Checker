"""Luke Gromen 言论中文逐句翻译(Chao 2026-10-04 定「甲」: 原文 + 中文翻译, 不写浓缩、不打方向标签)。
走本机 genai 代理 :8800, claude-haiku-4-5, 串行 + 1.5s 间隔(见 skill llm-batch-via-local-proxy)。
★硬门禁(不靠人工记得检查): 译文必须保留原文里的全部数字(含 $、%、b、T、年份)和 @用户名 和 #标签;
  不通过 -> 重试 1 次(把缺失项告诉模型) -> 仍不通过 -> translation_flag 标记, 不假装 OK。
★断点续跑: 已 ok 的不重译。输入 /tmp/lg_final.json; 输出 /tmp/lg_zh.json {id:{zh,ok,flag,tries}}
用法: python lg_translate.py [N]   (N=只翻前 N 条, 供试跑)
"""
import json, os, re, sys, time
import requests

URL = 'http://localhost:8800/v1/chat/completions'
MODEL = 'claude-haiku-4-5'
OUT = os.environ.get('LG_ZH_OUT', '/tmp/lg_zh.json')
IN = os.environ.get('LG_FINAL_IN', '/tmp/lg_final.json')
SEED = os.environ.get('LG_ZH_SEED', '')  # 增量: 旧译文库(逐条按新原文重过门禁, 通过才复用)
SYS = ("你是金融文本翻译。把推文逐句翻译成简体中文。硬规则:\n"
       "1) 只翻译,不总结、不评论、不加原文没有的信息、不删任何内容。\n"
       "2) 所有数字、百分比、金额($123b 这类写法保持原样,可在后面括号补换算)、年份、@用户名、#标签、股票/资产代码(UST、JGB、DXY、TGA、USDJPY 等)原样保留。\n"
       "3) 保留原文的语气:反讽、引号、'Let's watch.' 这类口头禅按字面译(如「走着瞧」),反讽用引号保留,不要改写成中性陈述。\n"
       "4) 保留换行和段落结构。引号内别人的原话照译并保留引号。\n"
       "5) 术语表(必须照此译): Bessent=贝森特, Warsh=沃什, Greer=格里尔, Hamiltonian=汉密尔顿式, Druck=德鲁肯米勒, "
       "Frisby=弗里斯比, Trump=特朗普, Powell=鲍威尔, Yellen=耶伦, Volcker=沃尔克, Greenspan=格林斯潘, Reagan=里根, Vance=万斯; "
       "FFTT、TGA、DXY、USDJPY、YCC、TBAC、FIMA、TIC 保留英文缩写; UST=美国国债(也可保留UST), JGB=日本国债, BOJ=日本央行, "
       "Fed=美联储, fiscal dominance=财政主导, debasement=货币贬值/贬值交易, neutral reserve asset=中性储备资产, bond vigilantes=债券义警。\n"
       "6) 只输出译文,不要任何前言后语。")


def facts(t):
    t0 = re.sub(r'\bWW\d\b', '', t)
    t0 = re.sub(r'\b\d+(st|nd|rd|th)\b', '', t0)  # 序数词(1st/2nd)译成「第一/第二」, 不算漏译
    nums = set(re.findall(r'\d[\d,.]*', t0))
    nums = {n.rstrip('.,') for n in nums if n.rstrip('.,')}
    return {'nums': nums, 'at': set(re.findall(r'@\w+', t)), 'tag': set(re.findall(r'#\w+', t))}


GLOSS_EN = {'Bessent', 'Warsh', 'Greer', 'Druck', 'Frisby', 'Trump', 'Powell', 'Yellen', 'Volcker', 'Greenspan', 'Reagan', 'Vance'}
REFUSE = re.compile(r'我需要看到|我需要你提供|请提供|请复制|无法翻译|没有粘贴|您只提供|你只提供|完整的推文|我会按照|我会立即|以下是翻译|翻译如下|译文如下|Here is|I need|I cannot|断片|缺乏具体')


def leaks_source(src, zh):
    """★门禁: 译文夹带原文连续 25 个字符(排除 @/#/数字串)=把英文原句原样抄进译文。"""
    a = re.sub(r'\s+', ' ', re.sub(r'https?://\S+', '', src)).strip()
    b = re.sub(r'\s+', ' ', re.sub(r'https?://\S+', '', zh)).strip()
    for i in range(0, max(len(a) - 25, 1), 5):
        w = a[i:i + 25]
        if len(w) == 25 and sum(c.isalpha() for c in w) >= 15 and '@' not in w and w in b:
            return w
    return ''


def check(src, zh):
    f = facts(src)
    miss = []
    if REFUSE.search(zh):
        miss.append('拒译/带前言')
    if leaks_source(src, zh):
        miss.append('夹带英文原句')
    for n in f['nums']:
        if n not in zh and n.replace(',', '') not in zh.replace(',', ''):
            miss.append(n)
    miss += [a for a in f['at'] if a not in zh]
    miss += [a for a in f['tag'] if a not in zh and a.lstrip('#') not in GLOSS_EN]
    return miss


def norm_src(t):
    return re.sub(r'\s+', ' ', re.sub(r'https?://\S+', '', t or '')).strip()


def call(text, extra=''):
    r = requests.post(URL, json={'model': MODEL, 'temperature': 0, 'max_tokens': 1800,
                                 'messages': [{'role': 'system', 'content': SYS},
                                              {'role': 'user', 'content': text + extra}]}, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f'http {r.status_code} {r.text[:120]}')
    return r.json()['choices'][0]['message']['content'].strip()


def main():
    items = json.load(open(IN))['statements']
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else len(items)
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    fails = 0
    if SEED and os.path.exists(SEED):
        seed = json.load(open(SEED)); reused = rejected = 0
        for x in items:
            z = seed.get(x['id'])
            if z and z.get('ok') and x['id'] not in done:
                # ★门禁1(新增): 译文是对「旧原文」做的; 新原文与旧原文(去空白/URL)不逐字相同 -> 不复用, 重翻
                #   (只查数字/标签查不出「原文被截断后变长」, 实测栽过: 译文停在截断处)
                if norm_src(x['text']) != norm_src(z.get('src', '')):
                    rejected += 1; continue
                miss = check(x['text'], z['zh'])  # 门禁2: 数字/标签/@ 仍须保留
                if not miss:
                    done[x['id']] = {'zh': z['zh'], 'ok': True, 'flag': [], 'tries': 0, 'reused': True}; reused += 1
                else:
                    rejected += 1
        print(f'复用旧译文 {reused} 条(已按新原文重过门禁); 门禁不通过需重翻 {rejected} 条', flush=True)
    for i, x in enumerate(items[:lim], 1):
        if done.get(x['id'], {}).get('ok'):
            continue
        src = x['text']; tries = 0; zh = ''; miss = ['未译']
        try:
            while tries < 2 and miss:
                extra = '' if tries == 0 else ("\n\n[注意: 上面就是完整的推文全文,哪怕只有一句话也请直接翻译成中文,不要要求补充内容,不要加任何说明。上次问题: " + ', '.join(miss) + "]")
                zh = call(src, extra); tries += 1
                miss = check(src, zh)
            done[x['id']] = {'zh': zh, 'ok': not miss, 'flag': miss, 'tries': tries, 'src': src}
            fails = 0
        except Exception as e:  # noqa: BLE001
            done[x['id']] = {'zh': '', 'ok': False, 'flag': [f'ERR {type(e).__name__} {str(e)[:80]}'], 'tries': tries}
            fails += 1
        json.dump(done, open(OUT, 'w'), ensure_ascii=False)
        d = done[x['id']]
        print(f"{i}/{lim} {x['id']} ok={d['ok']} tries={d['tries']} flag={d['flag'][:4]}", flush=True)
        if fails >= 3:
            print('连续 3 次失败, 停止(不硬撑)', flush=True); sys.exit(3)
        time.sleep(1.5)
    print('完成', sum(1 for v in done.values() if v['ok']), '/', len(items))


if __name__ == '__main__':
    main()
