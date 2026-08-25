#!/usr/bin/env python3
"""
kol_channel_probe.py — KOL YouTube 频道 / 官网候选采集器（纯脚本，无 LLM）

## 为什么是脚本而不是子 agent
2026-08-25 实测：6 个子 agent 每人 20 位 KOL，全部在 900s 超时，**零输出落盘**。
它们每人做了 40~55 次 API 调用，工作质量没问题——是「逐个 HTTP 探针」这种
纯 I/O 活儿本来就不该由 agent 串行做。

拆分原则（parallel-subagent-orchestration 的 anti-timeout redesign）：
  - 阶段 1 = 昂贵 I/O → 本脚本，ThreadPoolExecutor 并发，无 agent 超时
  - 阶段 2 = 语义判断（这个频道真的是这个人吗）→ 交给 agent 读本脚本的产物

## 本脚本做什么
对每个 KOL：
  1. 打 YouTube 自己的搜索接口，抽 (channel_id, title, handle) 候选
  2. 对每个候选频道页做 HEAD/GET，拿真实 handle（canonicalBaseUrl）、订阅数、
     以及 /videos /shorts /streams 三个 tab 是否存在
  3. 拿最新一条内容的日期（判断是否活跃）
  ★ 全部是**观测**，不做任何判断。「这是不是本人」留给下游 agent。

## 反造假
- handle 一律从频道页 `canonicalBaseUrl` / `vanityChannelUrl` 读出，
  **绝不从人名拼**。拿不到就是 null。
- 每条候选都带 `probe_http` 状态码，下游能分辨 404(不存在) vs 403(被 WAF 拦)。

## 用法
    cd ~/Projects/Eco-and-Volatility-Checker
    .venv/bin/python scripts/kol_channel_probe.py            # 全量
    .venv/bin/python scripts/kol_channel_probe.py --limit 10 # 试跑
    .venv/bin/python scripts/kol_channel_probe.py --resume   # 只补没跑过的

产物：scratch/kol_enrich/probe/<kol_id>.json（一人一文件，断点续跑安全）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "data", "kol_registry.json")
OUTDIR = os.path.join(ROOT, "scratch", "kol_enrich", "probe")

# ★ 反机器人三件套（与 src/fetchers/youtube_shorts.py 保持一致，勿分叉）：
#   ① cookies ② player_client=web_safari ③ PATH 里有 deno
#   本 VM 是数据中心 IP，缺任一项 → 「标题拿得到、日期和字幕全空」
COOKIE_CANDIDATES = [
    os.path.expanduser("~/Projects/AI-Blog-Generator/.secrets/yt_cookies_new.txt"),
    os.path.expanduser("~/Projects/AI-Blog-Generator/.secrets/yt_cookies.txt"),
    os.path.expanduser("~/.hermes/secrets/yt_cookies.txt"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 20


def _get(url, tries=2):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            return r.status_code, r.text
        except Exception as e:
            last = f"{type(e).__name__}"
            time.sleep(0.8 * (i + 1))
    return None, last


def yt_search(query, max_hits=6):
    """YouTube 自身搜索 → [{channel_id, title, handle_hint}]。

    ★ 用 YouTube 自己的搜索而非泛化 web_search：后者对小众/非英语人物
      返回的全是内容农场噪音（实测）。
    """
    u = ("https://www.youtube.com/results?search_query="
         + urllib.parse.quote(query) + "&sp=EgIQAg%253D%253D")  # sp= 只看频道
    code, html = _get(u)
    if code != 200 or not html:
        return [], code
    out, seen = [], set()
    # channelRenderer 里成对出现 channelId 与 title
    for m in re.finditer(
            r'"channelRenderer":\{"channelId":"(UC[\w-]{22})".{0,400}?'
            r'"title":\{"simpleText":"((?:[^"\\]|\\.){1,80})"', html):
        cid, title = m.group(1), m.group(2)
        if cid in seen:
            continue
        seen.add(cid)
        try:
            title = title.encode().decode("unicode_escape")
        except Exception:
            pass
        out.append({"channel_id": cid, "search_title": title})
        if len(out) >= max_hits:
            break
    if not out:  # 退化：抓所有 browseId + 邻近 title
        for m in re.finditer(
                r'"browseId":"(UC[\w-]{22})".{0,300}?'
                r'"text":"((?:[^"\\]|\\.){1,80})"', html):
            cid, title = m.group(1), m.group(2)
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"channel_id": cid, "search_title": title})
            if len(out) >= max_hits:
                break
    return out, code


def probe_channel(cid):
    """频道页观测：真 handle / 名称 / 订阅数 / 三 tab 存在性 / 最新内容。

    ★★ 2026-08-25 重写（v1 有两个致命 bug，判定 agent 全体报告后确认）：

    BUG-1「Keyboard shortcuts」：v1 用正则从频道页 HTML 抓
      `"title":{"runs":[{"text":"..."` 当最新视频标题 —— 实测频道页 HTML 里
      **根本没有 ytInitialData 视频条目**（videoRenderer/richItemRenderer 全部 0 命中），
      正则于是命中了页面底部无障碍菜单的 "Keyboard shortcuts"。
      结果：1258/1258 个 tab 的活跃度数据全是垃圾，占比 100%，
      导致下游 6 个判定 agent 全都无法应用「三 tab 任一活跃」这条规则。

    BUG-2 订阅数错位：v1 退化正则 `([\\d.,]+[KMB]?) subscribers` 会在页面别处
      命中观看数一类的数字 → @strategysoftware 报 19.2M、@OxbowAdvisors 报 19.7M
      （真实值分别约 12.5 万与 1 万量级），把小号误判成巨型官方号。

    修法：**改用 yt-dlp --flat-playlist**（本项目 youtube_shorts.py 已验证过的路子），
    它解析的是 YouTube 内部 API 而非 HTML，返回结构化字段：
      - channel_follower_count → 精确整数订阅数（不再解析字符串）
      - entries[].title / .url → 真实视频标题
      - uploader_id → 真 handle
    HTML 只留着拿 canonicalBaseUrl 做 handle 兜底。

    ★ 教训：项目里已有验证过的采集路径时，不要自己再造 HTML 正则轮子。
    """
    info = {"channel_id": cid, "handle": None, "channel_title": None,
            "subscribers": None, "subs_num": None, "tabs": {}, "probe_http": None}

    # ── handle 兜底：从频道页元数据读，绝不从人名拼 ──
    code, html = _get(f"https://www.youtube.com/channel/{cid}")
    info["probe_http"] = code
    if code == 200 and html:
        m = (re.search(r'"canonicalBaseUrl":"/(@[\w.-]+)"', html)
             or re.search(r'"vanityChannelUrl":"http[^"]*?/(@[\w.-]+)"', html))
        if m:
            info["handle"] = m.group(1)
        m = re.search(r'<meta property="og:title" content="([^"]{1,120})"', html)
        if m:
            info["channel_title"] = m.group(1)

    # ── 三 tab 真实内容：yt-dlp ──
    for tab in ("videos", "shorts", "streams"):
        t = _ytdlp_tab(cid, tab)
        info["tabs"][tab] = t
        if t.get("channel_follower_count") and info["subs_num"] is None:
            info["subs_num"] = t["channel_follower_count"]
        if t.get("channel") and not info["channel_title"]:
            info["channel_title"] = t["channel"]
        if t.get("uploader_id") and not info["handle"]:
            info["handle"] = t["uploader_id"]
    if info["subs_num"] is not None:
        info["subscribers"] = f'{info["subs_num"]:,}'
    return info


def _ytdlp_tab(cid, tab, n=3):
    """yt-dlp 拉某个 tab 的前 n 条（flat，不下载）。

    返回 {has_content, n_items, latest_title, entries, channel_follower_count, ...}
    ★「该 tab 不存在」是**正常情况**（很多频道没有 shorts/streams tab），
      不是错误 —— 记 has_content=False 即可，别当失败。
    """
    out = {"has_content": False, "n_items": 0}
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.deno/bin") + ":" + env.get("PATH", "")
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(n), "-J",
           "--no-warnings", "--socket-timeout", "15",
           "--extractor-args", "youtube:player_client=web_safari,default",
           f"https://www.youtube.com/channel/{cid}/{tab}"]
    for ck in COOKIE_CANDIDATES:
        if os.path.exists(ck):
            cmd[1:1] = ["--cookies", ck]
            break
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=75, env=env)
    except Exception as e:
        out["err"] = f"{type(e).__name__}"
        return out
    if r.returncode != 0:
        err = (r.stderr or "")[:160]
        if "does not have a" in err and "tab" in err:
            out["err"] = "no_such_tab"          # 正常，不是故障
        else:
            out["err"] = err
        return out
    try:
        j = json.loads(r.stdout)
    except Exception:
        out["err"] = "json_parse_fail"
        return out
    for k in ("channel", "uploader_id", "channel_follower_count"):
        if j.get(k) is not None:
            out[k] = j[k]
    ents = [e for e in (j.get("entries") or []) if e.get("title")]
    out["n_items"] = len(ents)
    out["has_content"] = bool(ents)
    if ents:
        out["latest_title"] = ents[0]["title"][:120]
        out["entries"] = [e["title"][:90] for e in ents[:3]]
    return out


def probe_site(url):
    if not url:
        return None
    code, body = _get(url)
    out = {"url": url, "http": code}
    if code == 200 and body:
        m = re.search(r"<title[^>]*>(.{1,160}?)</title>", body, re.S | re.I)
        if m:
            out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()
        feeds = re.findall(
            r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', body)
        if feeds:
            out["feeds"] = list(dict.fromkeys(feeds))[:3]
    return out


def build_queries(k):
    """构造检索词：人名 + 机构，越具体越不容易撞同名。"""
    name = k.get("display_name") or k.get("id", "").replace("_", " ")
    name = re.sub(r"（.*?）|\(.*?\)", "", name).strip()
    qs = [name]
    inst = (k.get("institution") or "").split("，")[0].split(",")[0].strip()
    if inst and len(inst) < 40:
        qs.append(f"{name} {inst}")
    return [q for q in dict.fromkeys(qs) if q]


def work_one(k):
    kid = k.get("id")
    rec = {"id": kid, "display_name": k.get("display_name"),
           "institution": k.get("institution"), "focus": k.get("focus"),
           "queries": [], "candidates": [], "site": None}
    for q in build_queries(k):
        hits, code = yt_search(q)
        rec["queries"].append({"q": q, "http": code, "n": len(hits)})
        for hcand in hits:
            if any(c["channel_id"] == hcand["channel_id"] for c in rec["candidates"]):
                continue
            rec["candidates"].append({**hcand, **probe_channel(hcand["channel_id"])})
        if rec["candidates"]:
            break          # 第一个 query 就有结果则不再扩大，省时间
    if k.get("source_url"):
        rec["site"] = probe_site(k["source_url"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)
    d = json.load(open(REGISTRY, encoding="utf-8"))
    kols = d["kols"] if isinstance(d, dict) and "kols" in d else d
    if isinstance(kols, dict):
        kols = list(kols.values())
    todo = [k for k in kols if k.get("active", True)
            and not (k.get("youtube_channel_id") and k.get("source_url"))]
    if args.resume:
        todo = [k for k in todo
                if not os.path.exists(os.path.join(OUTDIR, f"{k['id']}.json"))]
    if args.limit:
        todo = todo[:args.limit]

    print(f"待处理 {len(todo)} 人 | 并发 {args.workers} | 输出 {OUTDIR}", flush=True)
    done = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work_one, k): k for k in todo}
        for fu in as_completed(futs):
            k = futs[fu]
            try:
                rec = fu.result()
                with open(os.path.join(OUTDIR, f"{k['id']}.json"), "w",
                          encoding="utf-8") as fh:
                    json.dump(rec, fh, ensure_ascii=False, indent=1)
                done += 1
                nc = len(rec["candidates"])
                print(f"  [{done+fail}/{len(todo)}] {k['id']}: {nc} 候选", flush=True)
            except Exception as e:
                fail += 1
                print(f"  [{done+fail}/{len(todo)}] {k['id']}: ERROR {e}", flush=True)
    print(f"\n完成 {done} / 失败 {fail}")


if __name__ == "__main__":
    main()
