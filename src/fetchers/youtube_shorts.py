"""YouTube Shorts 采集器（KOL 短视频标题 + 字幕）。

背景（Chao 2026-08-25）
----------------------
Martin Armstrong 官方频道 @MartinArmstrongAE 的长视频（/videos）停在 2026-04-03，
但 /shorts 一直在日更（实测 899 条，最新为当日）。原采集只走 web_search + 长视频，
**整条 Shorts 线被漏掉**，而那正是他现在的主要产出。

因此每日 crawl 必须把 Shorts 纳入：既取标题，也取字幕原话（"不要错过他的标题和对话"）。

设计
----
- 频道句柄/ID 来自 kol_registry.json 的 ``youtube_channel_id``（支持 ``@handle`` 或 ``UCxxxx``）。
- 两段式，避免整站重抓：
    1. ``--flat-playlist`` 拉近 N 条 Shorts 的标题（极快，实测 25 条约 1 秒），
       与上次落盘的 id 集合 diff，只处理**新增**的。
    2. 只对新增里**关键词命中**的条目下载字幕（英文 auto-sub），拿到原话。
- 全部落盘 ``data/kol/shorts/<kol_id>.json``（累积库，只增不删），
  当日新增另写 ``data/kol/shorts/daily/<date>.json`` 供 dashboard / 报告读取。

诚实边界
--------
- yt-dlp 不可用或频道 404 → status="未就绪"，**绝不编造标题或台词**。
- 无字幕的 Shorts → transcript=None，只保留标题（标题本身也是信号）。
- upload_date 只取 yt-dlp 元数据（一手），不从搜索摘要猜。

CLI::

    python -m src.fetchers.youtube_shorts                 # 跑全部配了频道的 KOL
    python -m src.fetchers.youtube_shorts --kol martinarmstrong
    python -m src.fetchers.youtube_shorts --limit 60 --no-subs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional

JST = timezone(timedelta(hours=9))

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
REGISTRY = os.path.join(ROOT, "data", "kol_registry.json")
SHORTS_DIR = os.path.join(ROOT, "data", "kol", "shorts")
DAILY_DIR = os.path.join(SHORTS_DIR, "daily")

# --------------------------------------------------------------------------- #
# 反机器人（★2026-08-25 实测踩坑，改前先读）
# --------------------------------------------------------------------------- #
# 本 VM 是数据中心 IP，YouTube 对单视频元数据/字幕请求会返回
#   "Sign in to confirm you're not a bot"
# ——注意 ``--flat-playlist`` 拉频道列表**不受影响**（列表页不校验），
# 所以症状是"标题拿得到、日期和字幕全空"，极易误判成"该视频没有字幕"。
#
# 修复三件套（缺一不可，实测组合有效）：
#   1. --cookies 指向导出的 YouTube cookies（COOKIE_CANDIDATES）
#   2. --extractor-args youtube:player_client=web_safari,default
#      （只给 cookies 仍会被拦，必须换 player client）
#   3. PATH 里要有 deno（yt-dlp-ejs 解 n-challenge 用），否则部分格式缺失
COOKIE_CANDIDATES = [
    os.path.expanduser("~/Projects/AI-Blog-Generator/.secrets/yt_cookies_new.txt"),
    os.path.expanduser("~/Projects/AI-Blog-Generator/.secrets/yt_cookies.txt"),
    os.path.expanduser("~/.hermes/secrets/yt_cookies.txt"),
]
PLAYER_CLIENT_ARGS = ["--extractor-args", "youtube:player_client=web_safari,default"]


def _cookie_file() -> Optional[str]:
    for p in COOKIE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _auth_args() -> List[str]:
    """单视频请求（元数据/字幕）必须带的反机器人参数。"""
    args = list(PLAYER_CLIENT_ARGS)
    ck = _cookie_file()
    if ck:
        args = ["--cookies", ck] + args
    return args


# 关键词表**不再用于过滤**（Chao 2026-08-25:「不要错过他的标题和对话」）。
# 教训：初版用它筛选下载哪些字幕，结果漏掉了
#   "JP Morgan Had to Bail Out the US in 1896!"（讲的正是资本流入美国的核心论据）
#   "US Economy The Power of Low Government Cost!"（讲美元为何最后倒下）
# ——标题不含关键词但内容是核心信号，是典型的假阴性。
# 现在默认对**全部新增** Shorts 下字幕；本表仅在新增量超过 max_subs 时用于**排序优先级**，
# 保证配额吃紧时先拿宏观相关的那些。
KEYWORDS = re.compile(
    r"capital|flow|flee|fleeing|flight|exodus|dollar|usd|euro|yen|yuan|currency|reset|"
    r"gold|silver|metal|bond|treasur|yield|debt|default|deficit|sovereign|"
    r"crash|collapse|crisis|panic|depression|recession|stagflation|inflation|deflation|"
    r"market|stock|equit|dow|nasdaq|s&p|nikkei|dax|"
    r"fed|central bank|ecb|boj|pboc|rate|qe|liquidity|repo|"
    r"tax|capital control|cbdc|confiscat|offshore|pension|"
    r"bank|credit|contagion|bubble|oil|crude|energy|"
    r"war|tariff|trade|china|japan|europe|russia|iran|"
    r"20\d\d",
    re.I,
)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _yt_dlp() -> Optional[str]:
    return shutil.which("yt-dlp")


def _channel_urls(channel: str) -> List[str]:
    """把 registry 里的频道标识转成 Shorts 列表页 URL（含备选写法）。"""
    c = (channel or "").strip()
    if not c:
        return []
    if c.startswith("http"):
        base = c.rstrip("/")
        if base.endswith("/shorts"):
            return [base]
        return [base + "/shorts"]
    if c.startswith("@"):
        return [f"https://www.youtube.com/{c}/shorts"]
    if c.startswith("UC"):
        return [
            f"https://www.youtube.com/channel/{c}/shorts",
            f"https://www.youtube.com/channel/{c}",
        ]
    return [f"https://www.youtube.com/@{c}/shorts"]


def _run(cmd: List[str], timeout: int = 240) -> subprocess.CompletedProcess:
    # deno 供 yt-dlp-ejs 解 n-challenge；不在默认 PATH 里，必须显式加。
    env = {**os.environ}
    deno_bin = os.path.expanduser("~/.deno/bin")
    if os.path.isdir(deno_bin) and deno_bin not in env.get("PATH", ""):
        env["PATH"] = deno_bin + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)



def list_shorts(channel: str, limit: int = 60) -> Dict[str, Any]:
    """拉频道最近 ``limit`` 条 Shorts 的 id/标题（flat，不下载）。"""
    exe = _yt_dlp()
    if not exe:
        return {"status": "未就绪", "reason": "yt-dlp 未安装", "items": []}

    last_err = ""
    for url in _channel_urls(channel):
        try:
            cp = _run([exe, "--flat-playlist", "--dump-json",
                       "--playlist-end", str(limit), "--no-warnings", url])
        except subprocess.TimeoutExpired:
            last_err = f"timeout: {url}"
            continue
        items = []
        for line in (cp.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            vid = d.get("id")
            if not vid:
                continue
            items.append({"id": vid, "title": (d.get("title") or "").strip(),
                          "url": f"https://youtu.be/{vid}"})
        if items:
            return {"status": "ok", "items": items, "source": url}
        last_err = (cp.stderr or "").strip().splitlines()[-1] if cp.stderr else f"empty: {url}"

    return {"status": "未找到", "reason": last_err or "no shorts", "items": []}


def fetch_dates(video_ids: Iterable[str]) -> Dict[str, str]:
    """批量取 upload_date（一手元数据，YYYYMMDD）。"""
    ids = [v for v in video_ids if v]
    if not ids:
        return {}
    exe = _yt_dlp()
    if not exe:
        return {}
    out: Dict[str, str] = {}
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(f"https://youtu.be/{v}" for v in ids))
        path = fh.name
    try:
        cp = _run([exe, "--skip-download", "--no-warnings", *_auth_args(),
                   "--print", "%(upload_date)s|%(id)s", "-a", path],
                  timeout=max(120, 12 * len(ids)))
        for line in (cp.stdout or "").splitlines():
            parts = line.strip().split("|")
            if len(parts) == 2 and parts[1]:
                out[parts[1]] = parts[0]
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return out


def _vtt_to_text(path: str) -> str:
    lines: List[str] = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or "-->" in ln:
                continue
            if ln.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            ln = re.sub(r"<[^>]+>", "", ln)
            if lines and (ln == lines[-1] or ln in lines[-1]):
                continue
            lines.append(ln)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def fetch_transcripts(video_ids: List[str], timeout_per: int = 25) -> Dict[str, str]:
    """下载英文（auto）字幕并转纯文本。取不到就没有该 key，不编。"""
    exe = _yt_dlp()
    if not exe or not video_ids:
        return {}
    out: Dict[str, str] = {}
    tmp = tempfile.mkdtemp(prefix="yt_shorts_")
    try:
        with open(os.path.join(tmp, "urls.txt"), "w") as fh:
            fh.write("\n".join(f"https://youtu.be/{v}" for v in video_ids))
        try:
            _run([exe, "--skip-download", "--write-auto-sub", "--write-sub",
                  "--sub-lang", "en.*", "--sub-format", "vtt", "--no-warnings",
                  *_auth_args(),
                  "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
                  "-a", os.path.join(tmp, "urls.txt")],
                 timeout=max(180, timeout_per * len(video_ids)))
        except subprocess.TimeoutExpired:
            pass  # 部分成功也要收
        for name in os.listdir(tmp):
            if not name.endswith(".en.vtt"):
                continue
            vid = name.split(".")[0]
            text = _vtt_to_text(os.path.join(tmp, name))
            if text:
                out[vid] = text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _load_registry() -> List[Dict[str, Any]]:
    with open(REGISTRY, encoding="utf-8") as fh:
        d = json.load(fh)
    return d if isinstance(d, list) else d.get("kols", [])


def _store_path(kol_id: str) -> str:
    return os.path.join(SHORTS_DIR, f"{kol_id}.json")


def _load_store(kol_id: str) -> Dict[str, Any]:
    p = _store_path(kol_id)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {"kol_id": kol_id, "videos": {}}


def _save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


def crawl_kol(kol: Dict[str, Any], limit: int = 60,
              with_subs: bool = True, max_subs: int = 25) -> Dict[str, Any]:
    """抓一个 KOL 的新增 Shorts。返回本次新增条目。"""
    kol_id = kol.get("id") or ""
    channel = (kol.get("youtube_channel_id") or "").strip()
    name = kol.get("display_name") or kol_id

    if not channel:
        return {"kol_id": kol_id, "name": name, "status": "无频道配置", "new": []}

    listing = list_shorts(channel, limit=limit)
    if listing["status"] != "ok":
        return {"kol_id": kol_id, "name": name, "status": listing["status"],
                "reason": listing.get("reason"), "new": []}

    store = _load_store(kol_id)
    known = store.get("videos", {})
    fresh = [it for it in listing["items"] if it["id"] not in known]

    if fresh:
        dates = fetch_dates([it["id"] for it in fresh])
        for it in fresh:
            it["upload_date"] = dates.get(it["id"]) or None

        if with_subs:
            # 全部新增都下字幕（不按关键词过滤，见 KEYWORDS 上方注释）。
            # 仅当新增量超过 max_subs 时，用关键词把宏观相关的排到前面优先消耗配额。
            ordered = sorted(
                fresh,
                key=lambda it: (0 if KEYWORDS.search(it.get("title") or "") else 1,),
            )
            targets = [it["id"] for it in ordered[:max_subs]]
            subs = fetch_transcripts(targets)
            for it in fresh:
                it["transcript"] = subs.get(it["id"])
            skipped = len(fresh) - len(targets)
            if skipped > 0:
                for it in ordered[max_subs:]:
                    it["transcript_status"] = "超出单轮字幕配额，待下轮补"
        else:
            for it in fresh:
                it["transcript"] = None

        for it in fresh:
            known[it["id"]] = it

    store["videos"] = known
    store["channel"] = channel
    store["last_crawl"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z")
    store["total"] = len(known)
    _save_json(_store_path(kol_id), store)

    return {"kol_id": kol_id, "name": name, "status": "ok",
            "total": len(known), "new": fresh}


def crawl_all(limit: int = 60, with_subs: bool = True,
              only: Optional[str] = None) -> Dict[str, Any]:
    date = datetime.now(JST).strftime("%Y-%m-%d")
    results = []
    for kol in _load_registry():
        if not kol.get("active"):
            continue
        if only and kol.get("id") != only:
            continue
        if not (kol.get("youtube_channel_id") or "").strip():
            continue
        try:
            results.append(crawl_kol(kol, limit=limit, with_subs=with_subs))
        except Exception as exc:  # 单个 KOL 失败不拖垮整轮
            results.append({"kol_id": kol.get("id"), "name": kol.get("display_name"),
                            "status": "错误", "reason": str(exc)[:200], "new": []})

    payload = {
        "date": date,
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z"),
        "kols": results,
        "new_count": sum(len(r.get("new") or []) for r in results),
    }
    _save_json(os.path.join(DAILY_DIR, f"{date}.json"), payload)
    return payload


def recent_shorts(kol_id: str, days: int = 7) -> List[Dict[str, Any]]:
    """取某 KOL 近 N 天的 Shorts（供报告/dashboard 读）。"""
    store = _load_store(kol_id)
    cutoff = (datetime.now(JST) - timedelta(days=days)).strftime("%Y%m%d")
    out = [v for v in store.get("videos", {}).values()
           if (v.get("upload_date") or "") >= cutoff]
    return sorted(out, key=lambda x: x.get("upload_date") or "", reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="YouTube Shorts 采集（KOL 标题 + 字幕）")
    ap.add_argument("--kol", help="只跑指定 kol id")
    ap.add_argument("--limit", type=int, default=60, help="每频道扫描最近 N 条")
    ap.add_argument("--no-subs", action="store_true", help="只取标题，不下字幕")
    args = ap.parse_args()

    res = crawl_all(limit=args.limit, with_subs=not args.no_subs, only=args.kol)
    print(f"日期 {res['date']} | 新增 {res['new_count']} 条")
    for r in res["kols"]:
        news = r.get("new") or []
        print(f"  {r['name']}: {r['status']} | 库存 {r.get('total', '-')} | 新增 {len(news)}")
        for it in news[:10]:
            has = "有字幕" if it.get("transcript") else "无字幕"
            print(f"    [{it.get('upload_date') or '?'}] {it['title'][:70]} ({has})")


if __name__ == "__main__":
    main()
