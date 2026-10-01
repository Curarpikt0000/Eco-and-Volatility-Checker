#!/usr/bin/env python3
"""handover_refresh.py — 每日检查交接包是否过期，有新增就更新 SETUP.md / ops/ / self-skill/ 并推送。

no_agent 脚本，不调用大模型，不花 token。
  · 没有任何变化 → 不输出、不提交（静默即正常）
  · 有变化       → 更新后提交推送，输出一行摘要
  · 失败/红线命中 → 输出 ❌ 一行并退出非零

它做四件事（都只改交接包，不碰业务数据）：
  1. 解析 docs/index.html 的板块标题+更新频率，与 ops/dashboard_sections.json 对比，
     新增/改名/删除的板块写进 SETUP.md 的「看板板块清单」自动段，并追加一行变更记录。
  2. 重新导出 ops/cron-jobs.json（来源：~/.hermes/cron/jobs.json，去路径/去内网标识）。
  3. 重新同步 ops/hermes-scripts/ 与 ops/kol_*（来源：~/.hermes/scripts 与 scratch）。
  4. 重新同步 self-skill/public-macro-risk-dashboard/（来源：~/.hermes/skills/devops/…）。

红线：同步结果里只要还出现内部域名/密钥/个人邮箱，就整体放弃本次提交（不写半成品）。
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.environ.get("EV_ROOT", os.path.expanduser("~/Projects/Eco-and-Volatility-Checker"))
HERMES = os.path.expanduser("~/.hermes")
DAY = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y-%m-%d")
NOPUSH = os.environ.get("EV_HANDOVER_NOPUSH") == "1"

MARK_A, MARK_B = "<!-- AUTO:SECTIONS:BEGIN -->", "<!-- AUTO:SECTIONS:END -->"
LOG_A, LOG_B = "<!-- AUTO:CHANGELOG:BEGIN -->", "<!-- AUTO:CHANGELOG:END -->"
OWN_PATHS = ["SETUP.md", "ops", "self-skill"]

# 公网包不带的东西
EXCLUDE_JOBS = {"eco-vol-codex-delivery-watch"}
EXCLUDE_SCRIPTS = {"eco_vol_codex_delivery_watch.sh", "publish_vibe.sh"}
EXCLUDE_SKILL_FILES = {"references/dual-github-publish-and-monorepo-safety.md"}

STEP8B = """## 步骤 8b：发布到 Cloudflare Pages（公网入口）

```
bash <HERMES_SCRIPTS>/publish_cf_pages.sh eco-volatility-checker <PROJECT_ROOT>/docs/index.html <PROJECT_ROOT>/docs/.cf_last_sha256_eco-volatility-checker
```
脚本做了什么：内容 sha256 未变→跳过(exit 0，不是失败)；密钥类红线命中 exit 4；
**部署后匿名 curl 取回页面，HTTP 必须 200 且 sha256 与本地一致，否则 exit 8**（不以 wrangler 的 "Success" 为准）。
★退出码必须如实汇报：exit 0 且输出含 `LIVE https://...` → 日报写「✅ 公网已更新」；含 `no change` → 当天内容未变；
任何非零 → 日报显著标出「❌ 步骤8b 失败(exit=N)」并贴输出末尾。常见非零：4=红线 5=凭证缺失 6=wrangler 缺失 7=部署失败 8=线上实测未通过。

"""

REDLINE = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ntn_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-|"
    r"BEGIN [A-Z ]*PRIVATE|tvly-|bot[0-9]{6,}:[A-Za-z0-9_-]{20,}|-100[0-9]{9,}|"
    r"uberinternal|code\.uber|vibe-mcp|ChaoProjects|@uber\.com|chao\.jin|INTERNAL_(VIBE|MIRROR)", re.I)
# SETUP.md 里讲「红线正则本身」的那一行允许存在
ALLOW_LINE = re.compile(r"ghp_.*sk-.*ntn_.*BEGIN PRIVATE")


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT, **kw)


def sanitize(t):
    t = t.replace(ROOT, "<PROJECT_ROOT>").replace("/home/user/Projects/ChaoProjects", "<INTERNAL_MIRROR_REPO>")
    t = t.replace(HERMES + "/scripts", "<HERMES_SCRIPTS>").replace("/home/user/.hermes/scripts", "<HERMES_SCRIPTS>")
    t = t.replace("/home/user/.hermes", "~/.hermes").replace("/home/user", "~")
    t = re.sub(r"-100\d{9,}:\d+", "<chat_id>:<thread_id>", t)
    t = t.replace("chao.jin@uber.com", "ANONYMIZED_EMAIL_ADDRESS_0_5").replace("(contact: chao.jin)", "(contact: ANONYMIZED_EMAIL_ADDRESS_0_6)")
    t = re.sub(r"SSH_AUTH_SOCK=\S+", "SSH_AUTH_SOCK=<your ssh agent socket>", t)
    t = t.replace("沿用 publish_vibe.sh 的教训", "沿用内部发布脚本的教训")
    # cf 发布脚本: 内部标识正则改为可选环境变量
    t = re.sub(
        r"if grep -qiE 'uberinternal[^\n]*\n[^\n]*\n  exit 4\nfi",
        "# 可选: 设 REDLINE_EXTRA_REGEX='内部域名1|内部域名2' 额外拦截不该上公网的内部标识\n"
        "if [ -n \"${REDLINE_EXTRA_REGEX:-}\" ] && grep -qiE \"$REDLINE_EXTRA_REGEX\" \"$SCAN_TARGET\" 2>/dev/null; then\n"
        "  echo \"cf[$PROJECT]: REDLINE HIT (internal identifier) in $SCAN_TARGET\" >&2\n  exit 4\nfi", t)
    return t


# ───────────────────────── 1. 看板板块 ─────────────────────────
def parse_sections():
    p = os.path.join(ROOT, "docs/index.html")
    h = open(p, encoding="utf-8").read()
    out, seen = [], set()
    for m in re.finditer(r'<div class="part-title">(.*?)</div>', h, re.S):
        inner = m.group(1)
        fm = re.search(r'<span class="freq-badge[^"]*">(.*?)</span>', inner, re.S)
        freq = re.sub(r"<[^>]+>", "", fm.group(1)).strip() if fm else ""
        title = re.sub(r'<span class="freq-badge.*?</span>', "", inner, flags=re.S)
        title = re.sub(r"<[^>]+>", "", title)
        title = re.sub(r"^\s*(＋|\d+)\s*", "", re.sub(r"\s+", " ", title)).strip()
        if title and title not in seen:
            seen.add(title)
            out.append({"title": title, "freq": freq})
    return out


def update_sections():
    reg_p = os.path.join(ROOT, "ops/dashboard_sections.json")
    old = json.load(open(reg_p))["sections"] if os.path.exists(reg_p) else None
    new = parse_sections()
    if len(new) < 20:  # 页面异常(空壳/构建失败)，不据此改交接包
        raise RuntimeError(f"docs/index.html 只解析出 {len(new)} 个板块，疑似构建异常，放弃更新")
    changes = []
    if old is not None:
        ot, nt = {s["title"] for s in old}, {s["title"] for s in new}
        changes += [f"新增板块：{t}（{next(s['freq'] for s in new if s['title']==t) or '频率未标'}）" for t in nt - ot]
        changes += [f"移除板块：{t}" for t in ot - nt]
        of = {s["title"]: s["freq"] for s in old}
        changes += [f"更新频率变更：{s['title']}：{of[s['title']]} → {s['freq']}" for s in new if s["title"] in of and of[s["title"]] != s["freq"]]
    json.dump({"as_of": DAY, "sections": new}, open(reg_p, "w"), ensure_ascii=False, indent=1)

    # fetcher 与 tools 清单（让接手方知道每个板块背后有哪些取数函数/工具）
    fetchers = re.findall(r"^def (fetch_\w+)\(", open(os.path.join(ROOT, "src/external_data.py"), encoding="utf-8").read(), re.M)
    tools = sorted(f for f in os.listdir(os.path.join(ROOT, "tools")) if f.endswith((".py", ".sh")))

    body = [MARK_A, f"_自动生成于 {DAY}（`scripts/handover_refresh.py`，每个工作日检查一次，请勿手改此段）_", "",
            f"看板当前共 **{len(new)}** 个板块（顺序＝页面顺序；频率＝页面上的更新标签）：", ""]
    body += [f"{i+1}. {s['title']}" + (f" ——**{s['freq']}**" if s["freq"] else "") for i, s in enumerate(new)]
    body += ["", f"取数函数（`src/external_data.py`，共 {len(fetchers)} 个）：" + "、".join(f"`{f}`" for f in fetchers), "",
             f"运维工具（`tools/`，共 {len(tools)} 个）：" + "、".join(f"`{f}`" for f in tools), "", MARK_B]
    return changes, "\n".join(body)


def write_setup(block, changes):
    p = os.path.join(ROOT, "SETUP.md")
    t = open(p, encoding="utf-8").read()
    if MARK_A not in t:
        t = t.rstrip() + "\n\n## 11. 看板板块清单（自动更新）\n\n" + MARK_A + "\n" + MARK_B + "\n\n## 12. 变更记录（自动追加，新→旧）\n\n" + LOG_A + "\n" + LOG_B + "\n"
    t = re.sub(re.escape(MARK_A) + r".*?" + re.escape(MARK_B), lambda m: block, t, flags=re.S)
    if changes:
        lines = "\n".join(f"- {DAY} {c}" for c in changes)
        t = t.replace(LOG_A, LOG_A + "\n" + lines, 1)
    open(p, "w", encoding="utf-8").write(t)


# ───────────────────────── 2-4. 同步 ops / skill ─────────────────────────
def sync_cron():
    jobs = json.load(open(f"{HERMES}/cron/jobs.json"))["jobs"]
    out = []
    for x in jobs:
        if not x["name"].startswith("eco-vol-") or x["name"] in EXCLUDE_JOBS:
            continue
        prompt = x.get("prompt") or ""
        if "## 步骤 8b" in prompt and "## 步骤 9" in prompt:
            a, b = prompt.index("## 步骤 8b"), prompt.index("## 步骤 9")
            prompt = prompt[:a] + STEP8B + prompt[b:]
        out.append({"name": x["name"], "schedule_cron": x["schedule"]["expr"], "tz": "Asia/Tokyo", "no_agent": x["no_agent"],
                    "script": x.get("script"), "workdir": "<PROJECT_ROOT>" if x.get("workdir") else None,
                    "deliver": x.get("deliver"), "enabled_toolsets": x.get("enabled_toolsets"),
                    "model": x.get("model"), "skills": x.get("skills"), "prompt": sanitize(prompt)})
    note = ("由 ~/.hermes/cron/jobs.json 自动导出（scripts/handover_refresh.py 每日更新）。<PROJECT_ROOT>=接手方自己的 clone 路径；"
            "<HERMES_SCRIPTS>=脚本目录(默认 ~/.hermes/scripts)；deliver=origin 表示发回创建该 job 的 Telegram 话题，接手方须改成自己的投递目标。"
            "公网版不含 eco-vol-codex-delivery-watch（同步到作者公司内部仓库用）。")
    json.dump({"_note": note, "exported": DAY, "jobs": out}, open(os.path.join(ROOT, "ops/cron-jobs.json"), "w"), ensure_ascii=False, indent=1)


def sync_scripts():
    d = os.path.join(ROOT, "ops/hermes-scripts")
    os.makedirs(d, exist_ok=True)
    want = {}
    for f in sorted(os.listdir(f"{HERMES}/scripts")):
        if (f.startswith("eco_vol_") or f in ("publish_cf_pages.sh", "collect_topic_conversation.py")) \
                and f not in EXCLUDE_SCRIPTS and not re.search(r"\.(bak|bak[.-].*)$", f):
            want[f] = sanitize(open(f"{HERMES}/scripts/{f}", encoding="utf-8").read()).replace("<HERMES_SCRIPTS>", "<HERMES_SCRIPTS>")
    for f in os.listdir(d):
        if f not in want:
            os.remove(os.path.join(d, f))
    for f, t in want.items():
        open(os.path.join(d, f), "w", encoding="utf-8").write(t)
    for src, dst in (("scratch/kol_deep_run_batch.sh", "ops/kol_deep_run_batch.sh"), ("scratch/kol_bf_gap110/INSTRUCTIONS.md", "ops/kol_bf_INSTRUCTIONS.md")):
        sp = os.path.join(ROOT, src)
        if os.path.exists(sp):
            open(os.path.join(ROOT, dst), "w", encoding="utf-8").write(sanitize(open(sp, encoding="utf-8").read()))


def sync_skill():
    src = f"{HERMES}/skills/devops/public-macro-risk-dashboard"
    dst = os.path.join(ROOT, "self-skill/public-macro-risk-dashboard")
    if not os.path.isdir(src):
        raise RuntimeError("技能源目录不存在: " + src)
    tmp = dst + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in EXCLUDE_SKILL_FILES:
        try:
            os.remove(os.path.join(tmp, rel))
        except FileNotFoundError:
            pass
    for r, _, fs in os.walk(tmp):
        for f in fs:
            p = os.path.join(r, f)
            try:
                t = open(p, encoding="utf-8").read()
            except UnicodeDecodeError:
                continue
            o = t
            t = sanitize(t)
            t = t.replace("Pelosi 15 trades (2026-05-29 买 INTC/UBER)", "Pelosi 15 trades (2026-05-29 买 INTC)")
            t = t.replace("SSH_AUTH_SOCK issues in uber-redactor-shell-safety", "SSH agent issues")
            t = t.replace("(grep for uberinternal/code.uber/@uber.com/明文key — public repo, must be clean)", "(grep for internal domains / plaintext keys — public repo, must be clean)")
            if f == "SKILL.md":
                t = t.replace("chao-vibe, ", "").replace("public GitHub repo + Pages (NOT Uber vibe)", "public GitHub repo + Pages + Cloudflare Pages")
                t = re.sub(r"\n- `chao-vibe` —[^\n]*", "", t)
                t = re.sub(r"1\. \*\*Publish to PUBLIC GitHub Pages, NOT Uber vibe\.\*\*[^\n]*\n",
                           "1. **Publish to a PUBLIC channel (GitHub Pages / Cloudflare Pages), never to a login-gated internal host.** Use `ops/hermes-scripts/publish_cf_pages.sh` (verifies live HTTP 200 + sha256 match).\n", t)
                t = re.sub(r"- \*\*git commit HANGS on this VM[^\n]*\n", "", t)
            if t != o:
                open(p, "w", encoding="utf-8").write(t)
    shutil.rmtree(dst, ignore_errors=True)
    os.rename(tmp, dst)


def redline_scan():
    hits = []
    for base in OWN_PATHS:
        p = os.path.join(ROOT, base)
        files = [p] if os.path.isfile(p) else [os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs]
        for fp in files:
            try:
                for n, line in enumerate(open(fp, encoding="utf-8"), 1):
                    if REDLINE.search(line) and not ALLOW_LINE.search(line):
                        hits.append(f"{os.path.relpath(fp, ROOT)}:{n}")
            except UnicodeDecodeError:
                pass
    return hits


def main():
    os.chdir(ROOT)
    # 备份自有路径，失败时整体还原（不留半成品）
    bak = f"/tmp/handover_bak_{os.getpid()}"
    shutil.rmtree(bak, ignore_errors=True)
    os.makedirs(bak)
    for pth in OWN_PATHS:
        sp = os.path.join(ROOT, pth)
        if os.path.exists(sp):
            (shutil.copytree if os.path.isdir(sp) else shutil.copy2)(sp, os.path.join(bak, pth))

    def restore():
        for pth in OWN_PATHS:
            sp, bp = os.path.join(ROOT, pth), os.path.join(bak, pth)
            if os.path.exists(bp):
                shutil.rmtree(sp, ignore_errors=True) if os.path.isdir(sp) else (os.path.exists(sp) and os.remove(sp))
                (shutil.copytree if os.path.isdir(bp) else shutil.copy2)(bp, sp)

    try:
        changes, block = update_sections()
        sync_cron()
        sync_scripts()
        sync_skill()
        write_setup(block, changes)
        hits = redline_scan()
        if hits:
            restore()
            print("❌ 交接包刷新放弃：同步结果含内部标识/密钥，已还原。位置：" + "、".join(hits[:6]))
            return 3
    except Exception as e:  # noqa: BLE001
        restore()
        print(f"❌ 交接包刷新失败：{type(e).__name__}: {str(e)[:160]}（已还原）")
        return 2
    finally:
        shutil.rmtree(bak, ignore_errors=True)

    st = sh("git status --porcelain -- SETUP.md ops self-skill").stdout.strip()
    # as_of / exported 日期会每天变：只有日期变而内容没变时不算更新
    meaningful = [l for l in st.splitlines()]
    if meaningful:
        diff = sh("git diff -U0 -- SETUP.md ops self-skill").stdout
        real = [l for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))
                and not re.search(r'"(as_of|exported)"|自动生成于 \d{4}-\d\d-\d\d', l)]
        untracked = [l for l in meaningful if l.startswith("??")]
        if not real and not untracked:
            sh("git checkout -- SETUP.md ops self-skill")
            return 0
    else:
        return 0
    if NOPUSH:
        print("（EV_HANDOVER_NOPUSH=1，已更新未提交）\n" + st)
        return 0
    before = sh("git rev-parse HEAD").stdout.strip()
    sh("git add -- SETUP.md ops self-skill")
    msg = "docs: 交接包自动刷新 " + DAY + (" — " + "；".join(changes[:3]) if changes else "")
    r = sh(f"git -c commit.gpgsign=false commit -q -m {json.dumps(msg, ensure_ascii=False)} -- SETUP.md ops self-skill")
    if r.returncode != 0 or sh("git rev-parse HEAD").stdout.strip() == before:
        print("❌ 交接包刷新：commit 失败 " + (r.stderr or r.stdout)[:150])
        return 6
    p = sh("git push -q origin HEAD")
    if p.returncode != 0:
        print("❌ 交接包刷新：已提交但 push 失败 " + p.stderr[:150])
        return 7
    sh("git fetch -q origin")
    if sh("git rev-parse HEAD").stdout.strip() != sh("git rev-parse @{u}").stdout.strip():
        print("❌ 交接包刷新：push 后 local≠remote")
        return 8
    print("交接包已刷新并推送：" + ("；".join(changes) if changes else "同步了 cron/脚本/技能的最新内容") + f"（{sh('git rev-parse --short HEAD').stdout.strip()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
