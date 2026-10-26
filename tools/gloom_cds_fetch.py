"""刷新 data/dtcc_cds_daily_cache.json: Oracle / CoreWeave / SoftBank 的逐日 5Y CDS 点位。
来源: DTCC 公开成交报告, 经 Gloom(gloomberb) 云接口汇总。口径 = 当日 5Y 点位(由成交汇总), 不是 S&P/Reuters 收盘价。
只读; 失败不覆盖旧缓存; 拿不到就如实写 status。构建(build_dashboard)只读缓存, 不调用本脚本。
Chao 2026-10-26 选 A(并入灰线)。无人值守定时调用须 Chao 另行明说, 本脚本目前只手动运行。
"""
import json, os, subprocess, sys, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "dtcc_cds_daily_cache.json")
ENVP = "/home/user/.local/gloom-env"
TS = os.path.join(ROOT, "tools", "gloom_cds_hist.ts")


def main():
    env = dict(os.environ)
    env["HOME"] = ENVP + "/home"
    env["PATH"] = ENVP + "/node_modules/.bin:" + env.get("PATH", "")
    try:
        p = subprocess.run(["bun", "run", TS], capture_output=True, text=True, timeout=240, env=env, cwd=tempfile.gettempdir())
    except Exception as e:
        print("取数失败:", type(e).__name__, str(e)[:120]); return 2
    if p.returncode != 0:
        print("bun 退出码", p.returncode, "| stderr:", (p.stderr or "")[:300]); return 2
    try:
        raw = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        print("输出解析失败:", e, "| 前200字:", p.stdout[:200]); return 2
    # 对照组自检: Oracle 必须有足够多的点, 否则判失败, 不覆盖旧缓存
    n = len((raw.get("Oracle") or {}).get("points") or [])
    if n < 200:
        print("Oracle 点数过少(%d), 不覆盖缓存; 各标的:" % n, {k: (len(v.get("points") or []), v.get("error")) for k, v in raw.items()}); return 3
    out = {"status": "ok", "source": "DTCC 公开成交报告 · 经 Gloom 云接口汇总", "fetched_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST"),
           "issuers": {}}
    for k, v in raw.items():
        pts = sorted(v.get("points") or [], key=lambda x: x[0])
        out["issuers"][k] = {"issuer": v.get("issuer"), "error": v.get("error"), "points": pts,
                             "first": pts[0][0] if pts else None, "last": pts[-1][0] if pts else None}
    json.dump(out, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print("写入", CACHE, {k: (len(v["points"]), v["first"], v["last"]) for k, v in out["issuers"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
