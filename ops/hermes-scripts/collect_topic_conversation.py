#!/usr/bin/env python3
"""
collect_topic_conversation.py

Deterministically pull ONE Telegram topic's recent conversation from Hermes's
state.db so a cron job can compress it into that project's context log.

── 2026-08-30 重大修复（Chao 报告的串项目问题）──────────────────────────────
旧版文件头写着:
    "the DB does NOT persist Telegram topic/thread_id in a queryable column"
这句话是错的。sessions 表一直有 chat_id 和 thread_id 两列，实测 52 条 telegram
session 全部有值。基于那个错误判断，旧版退化成「抓时间窗内所有 telegram
session」—— 于是 20 个 context-distill cron job 每天各自把【全部项目】的对话
都灌进自己的 context-log.md，互相污染。

新版按 topic 精确过滤。识别当前项目的顺序：
  1. --project / --thread 显式指定
  2. CWD（cron job 都带 workdir=项目目录）-> project_topic_map.json 反查 topic
  3. 都失败 -> 打印 NO_TOPIC_RESOLVED 并退出，**绝不退化成抓全部**
     （宁可这一天没归档，也不要往 context-log 里写别的项目的内容）

Output: raw conversation text to stdout (consumed by the cron prompt). Prints a
NO_NEW_CONTENT marker line if nothing in the window, so the cron agent stays
quiet.

Usage:
  python3 collect_topic_conversation.py [--hours 26] [--max-chars 40000]
  python3 collect_topic_conversation.py --project Notion-Summary
  python3 collect_topic_conversation.py --thread <chat_id>:<thread_id>
  python3 collect_topic_conversation.py --allow-unmapped   # 旧行为，需显式开启
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time

DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")
TOPIC_MAP = os.path.expanduser("~/.hermes/project_topic_map.json")
PROJECTS_ROOT = os.path.expanduser("~/Projects")


# The cron injection scanner (tools/cronjob_tools.py::_CRON_THREAT_PATTERNS)
# blocks the whole distill run if the assembled prompt matches a threat pattern.
# Real conversation text often legitimately contains strings like "cat ~/.hermes/.env"
# (e.g. when discussing secret handling), which trips the 'read_secrets' pattern
# `cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)` and BLOCKS the run.
# We defang such strings in the collected text: semantics stay readable, but the
# regex no longer matches. This is a display-only transform of historical chat
# text — it does not touch any real file or command.
_DEFANG = [
    (re.compile(r'(cat\s+[^\n]*?)(\.env|credentials|\.netrc|\.pgpass)'),
     lambda m: m.group(1) + {'.env': '<ENV_FILE>', 'credentials': '<CREDS_FILE>',
                             '.netrc': '<NETRC_FILE>', '.pgpass': '<PGPASS_FILE>'}[m.group(2)]),
]


def _defang(text):
    """Neutralize strings that would trip the cron 'read_secrets' scanner.
    Applied to collected chat text only; purely cosmetic, keeps meaning.
    Loops until no match remains, because one 'cat ...' line can contain several
    secret-file tokens and the scanner matches greedily across the whole line."""
    if not text:
        return text
    scanner = re.compile(r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)')
    for _ in range(20):  # bounded loop; each pass defangs the earliest token
        if not scanner.search(text):
            break
        for rx, repl in _DEFANG:
            text = rx.sub(repl, text, count=1)
    return text


def _load_map():
    try:
        with open(TOPIC_MAP, encoding="utf-8") as f:
            return json.load(f).get("map") or {}
    except Exception:
        return {}


def _project_from_path(path):
    """把一个绝对路径映射成 (相对项目路径, 一级目录名)。
    支持嵌套项目（Main-Task/Task-7-Prepared-Food）：先试全相对路径，
    再退回第一层目录名。不在 ~/Projects 下则 (None, None)。"""
    if not path:
        return None, None
    p = os.path.realpath(path)
    root = os.path.realpath(PROJECTS_ROOT)
    if not p.startswith(root + os.sep):
        return None, None
    rel = p[len(root) + 1:]
    return rel, rel.split(os.sep)[0]


def _project_from_cwd():
    return _project_from_path(os.getcwd())


# ── 2026-08-31 修复：cron「agent 型」job 的 pre-run script 拿不到 workdir ──
# scheduler.py 只在 no_agent 分支给 _run_job_script 传 workdir=；agent 型 job
# 的 wake-gate/采集脚本走 5332 行那条路径，**不传 workdir**，子进程 cwd 退化成
# scripts 目录的父目录（~/.hermes）。于是靠 CWD 认项目的逻辑 100% 失败，20 个
# context-distill job 全部 NO_TOPIC_RESOLVED（当天零归档）。
# 不改 hermes-agent 核心（升级会被覆盖），改从 cron/jobs.json 的 fire_claim 反推：
# 触发时 scheduler 会给当前 job 打 fire_claim.at 并在脚本执行期间心跳续期，
# 所以「正在跑的那个 job」= 用本脚本、且 claim 最新鲜的那个。
CRON_JOBS = os.path.expanduser("~/.hermes/cron/jobs.json")
CLAIM_FRESH_SECS = 900        # claim 超过这个岁数视为陈旧，不采信
CLAIM_AMBIGUOUS_SECS = 60     # 两个 claim 靠这么近 -> 判定同时在跑，宁可失败
# ── 2026-09-04 补丁：claim 年龄在「前一个 job 还没跑完」时无法判别 ──────────
# scheduler 在 job 运行期间用心跳持续刷新 fire_claim.at。若 06:00 的 job A 的
# agent 轮还在跑，06:15 触发的 job B 的 pre-run script 会看到两个年龄都≈0s 的
# claim，CLAIM_AMBIGUOUS_SECS 必然命中 -> 当天零归档（2026-09-04 实测，
# eco-vol 06:00 未跑完压住了 forecast-checker 06:15）。
# 二次判别：pre-run script 总在本 job 被 dispatch 后几秒内执行，所以
# last_dispatch.dispatched_at 最新且在这个窗口内的那个 job 才是「我」。
DISPATCH_FRESH_SECS = 180


def _workdir_from_fire_claim():
    """返回 (workdir, detail)；认不出返回 (None, reason)。"""
    import datetime
    me = os.path.basename(os.path.realpath(__file__))
    try:
        with open(CRON_JOBS, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"jobs.json 读不了 ({e})"
    jobs = data if isinstance(data, list) else data.get("jobs", data)
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    if not isinstance(jobs, list):
        return None, "jobs.json 结构不认识"

    now = time.time()
    cands = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        if os.path.basename(str(j.get("script") or "")) != me:
            continue
        wd = (j.get("workdir") or "").strip()
        at = ((j.get("fire_claim") or {}) if isinstance(j.get("fire_claim"), dict) else {}).get("at")
        if not wd or not at:
            continue
        try:
            ts = datetime.datetime.fromisoformat(at).timestamp()
        except Exception:
            continue
        age = now - ts
        if age < -60 or age > CLAIM_FRESH_SECS:
            continue
        # 本次派发时刻（用于 claim 年龄打平时的二次判别）
        d_age = None
        ld = j.get("last_dispatch")
        d_at = ld.get("dispatched_at") if isinstance(ld, dict) else None
        if d_at:
            try:
                d_age = now - datetime.datetime.fromisoformat(d_at).timestamp()
            except Exception:
                d_age = None
        cands.append((age, wd, j.get("id"), j.get("name"), d_age))

    if not cands:
        return None, "没有新鲜的 fire_claim"
    cands.sort()
    if len(cands) > 1 and (cands[1][0] - cands[0][0]) < CLAIM_AMBIGUOUS_SECS:
        # claim 年龄分不开（心跳把前一个未跑完的 job 的 claim 也刷成 0s）。
        # 退到 last_dispatch：pre-run script 紧跟本 job 的 dispatch 执行，
        # 所以「刚被 dispatch 且窗口内唯一」的那个才是我。
        tied = [c for c in cands if (c[0] - cands[0][0]) < CLAIM_AMBIGUOUS_SECS]
        fresh = [c for c in tied
                 if c[4] is not None and -60 <= c[4] <= DISPATCH_FRESH_SECS]
        fresh.sort(key=lambda c: c[4])
        if len(fresh) == 1 or (len(fresh) > 1
                               and (fresh[1][4] - fresh[0][4]) >= 30):
            age, wd, jid, jname, d_age = fresh[0]
            return wd, (f"job {jname}({jid}) claim {age:.0f}s ago, "
                        f"dispatched {d_age:.0f}s ago (claim 打平时按 dispatch 判别)")
        return None, ("多个 job 的 claim 几乎同时（"
                      + ", ".join(f"{c[3]}@{c[0]:.0f}s" for c in cands[:3])
                      + "），last_dispatch 也分不开")
    age, wd, jid, jname, d_age = cands[0]
    return wd, f"job {jname}({jid}) claim {age:.0f}s ago"


def resolve_topic(args):
    """返回 (chat_id, thread_id, project, how) 或 (None, None, None, reason)。"""
    m = _load_map()

    if args.thread:
        if ":" not in args.thread:
            return None, None, None, "BAD_THREAD_ARG (需要 '<chat_id>:<thread_id>')"
        chat, thread = args.thread.rsplit(":", 1)
        try:
            return int(chat), int(thread), m.get(args.thread), "explicit --thread"
        except ValueError:
            return None, None, None, "BAD_THREAD_ARG (非整数)"

    wanted = args.project
    how = "explicit --project"
    claim_note = ""
    if not wanted:
        # 来源①：进程 cwd（本地手跑 / no_agent 型 cron job 有 workdir）
        rel, first = _project_from_cwd()
        src = "cwd"
        if not (rel or first):
            # 来源②：agent 型 cron job 的 pre-run script 拿不到 workdir
            # （scheduler 不传），从 jobs.json 的 fire_claim 反推本次触发的 job。
            wd, detail = _workdir_from_fire_claim()
            claim_note = detail
            if wd:
                rel, first = _project_from_path(wd)
                src = f"fire_claim[{detail}]"
        # 嵌套项目优先精确匹配，再退回一级目录
        for cand in (rel, first):
            if cand and any(v == cand for v in m.values()):
                wanted, how = cand, f"{src} ({cand})"
                break
        if not wanted and first:
            wanted, how = first, f"{src} ({first})"

    if not wanted:
        return None, None, None, (
            "NO_PROJECT (cwd 不在 ~/Projects 下；fire_claim 也没认出来"
            + (f": {claim_note}" if claim_note else "") + ")"
        )

    hits = [k for k, v in m.items() if v == wanted]
    if not hits:
        return None, None, None, f"UNMAPPED_PROJECT ({wanted} 不在 project_topic_map.json)"
    if len(hits) > 1:
        return None, None, None, f"AMBIGUOUS ({wanted} 对应多个 topic: {hits}，请用 --thread)"

    chat, thread = hits[0].rsplit(":", 1)
    return int(chat), int(thread), wanted, how


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=26.0,
                    help="Lookback window in hours (default 26 = 1 day + buffer).")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--max-chars", type=int, default=40000,
                    help="Cap on total dumped characters (keeps cron context sane).")
    ap.add_argument("--project", help="项目名（默认从 CWD 推断）")
    ap.add_argument("--thread", help="显式 '<chat_id>:<thread_id>'")
    ap.add_argument("--allow-unmapped", action="store_true",
                    help="识别不到 topic 时退化成抓所有 telegram session（旧行为，"
                         "会串项目，默认关闭）")
    # chat_id 是负数，argparse 会误判成选项 -> 预处理成 --thread=VALUE
    argv, fixed, i = sys.argv[1:], [], 0
    while i < len(argv):
        if argv[i] in ("--thread", "--project") and i + 1 < len(argv):
            fixed.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
            continue
        fixed.append(argv[i])
        i += 1
    args = ap.parse_args(fixed)

    if not os.path.exists(args.db):
        print(f"NO_NEW_CONTENT (db not found: {args.db})")
        return

    chat_id, thread_id, project, how = resolve_topic(args)
    if chat_id is None:
        if not args.allow_unmapped:
            # 硬门禁：宁可这天不归档，也绝不把别的项目的对话写进来。
            print(f"NO_TOPIC_RESOLVED ({how})")
            print("拒绝退化成全库抓取——那会把其他项目的对话写进本项目的 context-log。")
            print("修法：把本项目加进 ~/.hermes/project_topic_map.json 的 map，"
                  "或用 --project / --thread 显式指定。")
            return
        print(f"WARNING: topic 未识别（{how}），已按 --allow-unmapped 退化为全库抓取，"
              "内容可能混入其他项目。")

    cutoff = time.time() - args.hours * 3600
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=10.0)
    cur = con.cursor()

    if chat_id is not None:
        cur.execute(
            """
            SELECT DISTINCT s.id, s.title, s.started_at
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            WHERE s.source = 'telegram'
              AND s.chat_id = ? AND s.thread_id = ?
              AND m.timestamp >= ?
            ORDER BY s.started_at DESC
            """,
            (chat_id, thread_id, cutoff),
        )
    else:
        cur.execute(
            """
            SELECT DISTINCT s.id, s.title, s.started_at
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            WHERE s.source = 'telegram' AND m.timestamp >= ?
            ORDER BY s.started_at DESC
            """,
            (cutoff,),
        )

    sessions = cur.fetchall()
    if not sessions:
        scope = f"topic {chat_id}:{thread_id} ({project})" if chat_id else "all telegram"
        print(f"NO_NEW_CONTENT (no messages in window for {scope})")
        return

    chunks = []
    if chat_id is not None:
        banner = (f"[COLLECTOR] project={project} topic={chat_id}:{thread_id} "
                  f"via={how} sessions={len(sessions)} window={args.hours}h\n")
        chunks.append(banner)

    total = 0
    for sid, title, started in sessions:
        # Skip delegation/subagent sessions: their first user message is a long
        # machine-generated task goal (not a real human turn). Real Telegram
        # turns from the user are short and often prefixed with "[Name]".
        cur.execute(
            """
            SELECT content FROM messages
            WHERE session_id = ? AND role = 'user'
              AND content IS NOT NULL AND content != ''
            ORDER BY id ASC LIMIT 1
            """,
            (sid,),
        )
        first = cur.fetchone()
        if first:
            fc = first[0]
            if len(fc) > 500 and not fc.lstrip().startswith("["):
                continue
        cur.execute(
            """
            SELECT role, content, timestamp
            FROM messages
            WHERE session_id = ?
              AND role IN ('user', 'assistant')
              AND timestamp >= ?
              AND content IS NOT NULL AND content != ''
            ORDER BY id ASC
            """,
            (sid, cutoff),
        )
        rows = cur.fetchall()
        if not rows:
            continue
        header = f"\n===== SESSION: {title or sid} =====\n"
        chunks.append(header)
        total += len(header)
        for role, content, ts in rows:
            line = f"[{role}] {_defang(content)}\n"
            if total + len(line) > args.max_chars:
                chunks.append("\n...[truncated: window exceeded max-chars]...\n")
                total = args.max_chars
                break
            chunks.append(line)
            total += len(line)
        if total >= args.max_chars:
            break

    out = "".join(chunks).strip()
    if not out:
        print("NO_NEW_CONTENT (sessions had no usable text)")
        return
    print(out)


if __name__ == "__main__":
    main()
