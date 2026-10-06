"""机构/个人研究报告「被公开解读」线索采集（Chao 2026-10-03 立）。

口径(Chao 定): 只要是「报告内容的分享/解读」就收, 不要求原报告付费; 只收第三方解读线索,
不收原文大段, 不写我们自己的推断。本模块只产出「线索表」: 机构/人 + 解读标题 + 发布日 + 公众号
+ 平台自带摘要(≤140 字) + 链接, 并标「正文未读」(搜狗微信正文被反爬, 实测读不了)。

采集: 搜狗微信搜索(无需登录, requests 直连)。命中门禁(机械判定, 不调 LLM):
  G1 名字: 标题+摘要必须含该人别名之一(防同名/无关)
  G2 窗口: 发布日 >= 窗口起点(默认 183 天), 且 <= 今天
  G3 去重: 按 (标题归一) 去重; 同标题多号转载保留全部来源
  G4 类型: 标「报告/周报/专栏」关键词命中=report, 否则 other(访谈/新闻); 看板默认只显示 report
防限流: 每次请求间隔 4 秒; 出现 antispider 页即停(不硬撞)。
"""
import datetime as dt
import html
import json
import os
import re
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "report_leads.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/124 Safari/537.36")

# 机构/人 → (机构名, 名字锚点[必须命中其一], 语境词[锚点是常见词时必须再命中其一, 空=不要求], 查询词)
# ★2026-10-03 实测: 「美银」「汤普森」「双线」是常见词, 放进别名会混入越野胎/银饰/游戏; 锚点只放该人独有的写法
TARGETS = {
    "Michael Hartnett": ("BofA Global Research · The Flow Show",
        ["哈特奈特", "哈内特", "哈特内特", "hartnett", "flow show", "the flow show"], ["美银", "策略", "资金流", "flow show", "bofa", "美股", "牛熊", "债券"],
        ["哈特奈特 美银", "哈内特 美银 报告", "Flow Show 美银", "Hartnett 美银 周报"]),
    "Luke Gromen": ("FFTT (Forest for the Trees)",
        ["格罗门", "格罗曼", "gromen", "fftt"], ["美债", "美元", "黄金", "美联储", "财政", "债务", "通胀", "加息", "标普", "央行", "宏观"],
        ["卢克 格罗门", "Luke Gromen", "格罗曼 FFTT", "FFTT 报告 美债"]),
    "Louis-Vincent Gave": ("Gavekal Research",
        ["gavekal", "路易斯·加夫", "路易-文森特", "加夫卡"], [],
        ["Gavekal 报告", "Gavekal 戴维", "Gavekal 研究 观点"]),
    "Zoltan Pozsar": ("Ex Uno Research / 前 Credit Suisse",
        ["pozsar", "波萨尔", "波扎尔", "佐尔坦·波"], [],
        ["Pozsar 美债 回购", "波萨尔 货币 报告", "Pozsar Ex Uno"]),
    "Jeff Snider": ("Alhambra Partners",
        ["alhambra", "斯奈德 欧元美元", "杰夫·斯奈德", "jeff snider"], [],
        ["Jeff Snider 欧元美元", "杰夫 斯奈德 Alhambra", "斯奈德 欧元美元 报告"]),
    "Alasdair Macleod": ("Goldmoney / 独立研究",
        ["阿拉斯代尔", "alasdair", "麦克劳德", "macleod"], ["黄金", "金价", "白银", "法币", "央行", "金融", "银行"],
        ["麦克劳德 黄金", "阿拉斯代尔麦克劳德", "Alasdair Macleod 黄金", "麦克劳德 金融崩溃"]),
    "Stewart Thomson": ("Graceland Updates (Graceland Investment Mgmt)",
        ["斯图尔特·汤姆森", "斯图尔特汤姆森", "汤姆森", "graceland", "stewart thomson"], ["黄金", "白银", "金价", "贵金属", "报告", "美联储", "加息", "美林"],
        ["斯图尔特汤姆森", "斯图尔特·汤姆森 黄金", "汤姆森 报告解读", "汤姆森 黄金 加息", "Graceland 汤姆森"]),
    "AG Thorson": ("AG Thorson 黄金播报 (Gold/Silver Daily)",
        ["托尔森", "thorson", "ag thorson"], ["黄金", "白银", "贵金属", "矿业", "美联储", "非农", "pce", "cpi", "早报", "播报"],
        ["托尔森 黄金", "AG托尔森", "托尔森 报告", "托尔森 早报"]),
    "Felix Zulauf": ("Zulauf Consulting",
        ["祖劳夫", "祖拉夫", "楚劳夫", "zulauf"], [],
        ["Felix Zulauf", "祖劳夫 观点", "费利克斯 祖劳夫"]),
    "Jeffrey Gundlach": ("DoubleLine Capital",
        ["冈拉克", "刚拉克", "贡拉克", "冈德拉克", "gundlach", "doubleline"], [],
        ["Gundlach DoubleLine", "冈拉克 债券", "刚拉克 观点", "贡拉克 DoubleLine"]),
}
# 同名排除词: 标题/摘要含其一即丢(实测噪声: 越野胎/型号/杂图/Clive Thompson/游戏)
EXCLUDE = re.compile(r"越野|轮胎|型号|杂图|合集|clive|克莱夫|游戏|手游|球鞋|签名|蛋仔|玩具|模型|开箱|试驾|演员|电影|影片|Galaxy|Annihilation|BTA|段落|josh hartnett|乔什", re.I)
INTERVIEW_KW = re.compile(r"访谈|对话|对谈|专访|论坛|播客|采访|字幕|配音|直播|圆桌|演讲|峰会|podcast|interview", re.I)
REPORT_KW = re.compile(r"报告|研报|周报|月报|早报|晚报|播报|专栏|策略|展望|解读|付费|收费|Flow Show|Updates", re.I)


def classify(title, summary=""):
    """report=报告内容的分享/解读(Chao 口径); interview=访谈/对话/配音(默认不进看板); other=无法判定
    标题判定优先: 标题含访谈类词 → interview(即便简介里出现'报告'); 标题含报告类词 → report"""
    if INTERVIEW_KW.search(title):
        return "interview"
    if REPORT_KW.search(title):
        return "report"
    if INTERVIEW_KW.search(summary):
        return "interview"
    return "report" if REPORT_KW.search(summary) else "other"


def _strip(s):
    return re.sub(r"<[^>]+>", "", html.unescape(s or "")).strip()


def sogou(q, page=1, session=None):
    s = session or requests
    r = s.get("https://weixin.sogou.com/weixin",
              params={"type": 2, "query": q, "page": page},
              headers={"User-Agent": UA, "Referer": "https://weixin.sogou.com/"}, timeout=25)
    if "antispider" in r.url or "请输入验证码" in r.text[:4000]:
        raise RuntimeError("antispider")
    out = []
    for m in re.finditer(r'<li id="sogou_vr_\d+_box_\d+".*?</li>', r.text, re.S):
        b = m.group(0)
        a = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not a:
            continue
        sm = re.search(r'class="txt-info"[^>]*>(.*?)</p>', b, re.S)
        ac = re.search(r'class="all-time-y2"[^>]*>(.*?)</span>', b, re.S)
        ts = re.search(r"timeConvert\('(\d+)'\)", b)
        href = a.group(1)
        out.append({"title": _strip(a.group(2)),
                    "href": ("https://weixin.sogou.com" + href) if href.startswith("/") else href,
                    "summary": _strip(sm.group(1))[:140] if sm else "",
                    "acct": _strip(ac.group(1)) if ac else "",
                    "ts": int(ts.group(1)) if ts else 0})
    return out


def _norm(t):
    return re.sub(r"[\s\W_]+", "", t.lower())[:40]


def bili(q, page=1, session=None):
    """B 站搜索(agent-reach 同款端点 search/all/v2, 无需登录, 带精确发布日)。"""
    s = session or requests
    r = s.get("https://api.bilibili.com/x/web-interface/search/all/v2",
              params={"keyword": q, "page": page},
              headers={"User-Agent": UA, "Referer": "https://www.bilibili.com"}, timeout=20)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"bili code {d.get('code')} {d.get('message')}")
    out = []
    for g in (d.get("data") or {}).get("result", []):
        if g.get("result_type") == "video":
            for x in g["data"]:
                out.append({"title": _strip(x["title"]),
                            "date": dt.datetime.fromtimestamp(x["pubdate"]).date().isoformat(),
                            "acct": x["author"], "url": x["arcurl"],
                            "summary": (x.get("description") or "")[:140].replace("\n", " "),
                            "platform": "B站视频"})
    return out


def passes_gates(name, item, alias, ctx):
    """机械门禁(不调 LLM): G1 名字锚点  G1b 语境词(锚点易同名时)  G1c 同名排除词"""
    text = (item["title"] + " " + item["summary"]).lower()
    if not any(k.lower() in text for k in alias):
        return False
    if EXCLUDE.search(item["title"] + " " + item["summary"]):
        return False
    if ctx and not any(c.lower() in text for c in ctx):
        return False
    return True


def _vid_params(url):
    """从 B 站视频链接取 aid/bvid; 解析不出返回 None。"""
    m = re.search(r"av(\d+)|(BV[0-9A-Za-z]+)", url or "")
    if not m:
        return None
    return {"aid": m.group(1)} if m.group(1) else {"bvid": m.group(2)}


def fetch_full_desc(url, session=None):
    """★2026-10-06 (Chao: 点击要能看到完整简介): 搜索接口的 description 被 [:140] 截断, 详情接口 /x/web-interface/view
    能一次返回完整简介(实测 9/9 code=0, 完整长度 145~279 字)。返回 (完整简介 or None)。
    失败/空一律返回 None, 调用方据此「保留旧值不覆盖」, 绝不写空。"""
    p = _vid_params(url)
    if not p:
        return None
    s = session or requests
    try:
        r = s.get("https://api.bilibili.com/x/web-interface/view", params=p,
                  headers={"User-Agent": UA, "Referer": "https://www.bilibili.com"}, timeout=20).json()
        if r.get("code") != 0:
            return None
        v = r.get("data") or {}
        d2 = v.get("desc_v2") or []
        full = "".join(x.get("raw_text", "") for x in d2) if d2 else (v.get("desc") or "")
        full = re.sub(r"\s+", " ", full).strip()
        return full or None
    except Exception:  # noqa: BLE001
        return None


def enrich_full(items, sleep=2.5, log=print, only_truncated=True):
    """给条目补 summary_full。只补「摘要疑似被 140 字截断」的(>=130 字); 已有 summary_full 的跳过; 取不到不写。
    返回 (补成功数, 失败数)。"""
    sess = requests.Session()
    ok = bad = 0
    for it in items:
        if it.get("summary_full"):
            continue
        if only_truncated and len(it.get("summary") or "") < 130:
            continue
        srcs = it.get("sources") or []
        url = next((s.get("url") for s in srcs if "bilibili" in (s.get("url") or "")), None)
        full = fetch_full_desc(url, sess) if url else None
        if full and len(full) > len(it.get("summary") or ""):
            it["summary_full"] = full
            ok += 1
        elif full:
            ok += 0          # 完整简介不比摘要长 = 并未被截断, 不需要展开
        else:
            bad += 1
            log(f"  补全失败(保留原摘要): {it.get('date')} {str(it.get('title'))[:24]}")
        time.sleep(sleep)
    return ok, bad


def collect(window_days=183, targets=None, pages=(1, 2), sleep=3.0, log=print):
    today = dt.date.today()
    start = (today - dt.timedelta(days=window_days)).isoformat()
    sess = requests.Session()
    res, stats = {}, {}
    for name, (org, alias, ctx, queries) in (targets or TARGETS).items():
        got, raw = {}, 0
        for q in queries:
            for pg in pages:
                try:
                    items = bili(q, pg, sess)
                except Exception as e:  # noqa: BLE001
                    log(f"[{name}] {q} p{pg} 失败 {type(e).__name__}: {str(e)[:50]}")
                    items = []
                raw += len(items)
                for x in items:
                    if not passes_gates(name, x, alias, ctx):
                        continue                                  # G1/G1b/G1c
                    if x["date"] < start or x["date"] > today.isoformat():
                        continue                                  # G2 窗口
                    k = _norm(x["title"])                         # G3 去重
                    e = got.setdefault(k, {"title": x["title"], "date": x["date"], "summary": x["summary"],
                        "sources": [],
                        "type": classify(x["title"], x["summary"])})
                    if not any(s["url"] == x["url"] for s in e["sources"]):
                        e["sources"].append({"acct": x["acct"], "url": x["url"], "platform": x["platform"]})
                time.sleep(sleep)
        res[name] = {"org": org, "items": sorted(got.values(), key=lambda z: z["date"], reverse=True)}
        stats[name] = {"raw": raw, "kept": len(got)}
        log(f"[{name}] 原始 {raw} → 过门禁 {len(got)}")
    return res, stats


def save(res, window_days):
    payload = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
               "window_days": window_days, "channel": "B站搜索(摘要=平台自带简介,正文未读)",
               "orgs": res}
    # 与旧数据合并: 同标题保留(不因某次没搜到就丢历史)
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8")).get("orgs", {})
        except Exception:  # noqa: BLE001
            old = {}
        for n, v in old.items():
            cur = payload["orgs"].setdefault(n, {"org": v["org"], "items": []})
            have = {_norm(i["title"]) for i in cur["items"]}
            for it in v["items"]:
                if _norm(it["title"]) not in have:
                    cur["items"].append(it)
            cur["items"].sort(key=lambda z: z["date"], reverse=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return payload


if __name__ == "__main__":
    import sys
    wd = int(sys.argv[1]) if len(sys.argv) > 1 else 183
    r, st = collect(window_days=wd)
    p = save(r, wd)
    # ★2026-10-06: 采集+合并旧数据之后, 对「摘要疑似被 140 字截断」的条目补完整简介(已补过的跳过, 取不到保留原摘要)
    _all = [it for v in p["orgs"].values() for it in v["items"]]
    _ok, _bad = enrich_full(_all)
    if _ok or _bad:
        json.dump(p, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("完成", {k: (v if isinstance(v, str) else v) for k, v in st.items()}, "| 补全简介 成功", _ok, "失败", _bad)
    print("合计", sum(len(v["items"]) for v in p["orgs"].values()), "条 →", OUT)
