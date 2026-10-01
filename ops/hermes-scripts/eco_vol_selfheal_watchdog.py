#!/usr/bin/env python3
"""eco_vol_selfheal_watchdog.py — Eco&Volatility 每日扫描自愈看门狗(no_agent)。

幂等：查 cron 真实状态，eco-vol-* 日任务 last_status==error 就 hermes cron run 重跑。
全绿 → 空 stdout 静默。失败仍在 → 下小时再试。
"""
import json, os, subprocess, sys

JOBS = os.path.expanduser("~/.hermes/cron/jobs.json")
HERMES = os.path.expanduser("~/.local/bin/hermes")


def main():
    if not os.path.exists(JOBS):
        return
    try:
        data = json.load(open(JOBS))
    except Exception:
        return
    jobs = data.get("jobs", [])
    healed = []
    for j in jobs:
        name = j.get("name", "")
        if not name.startswith("eco-vol-"):
            continue
        if not j.get("enabled", False):
            continue
        if j.get("last_status") == "error":
            jid = j.get("job_id") or j.get("id")
            if jid:
                try:
                    subprocess.run([HERMES, "cron", "run", jid],
                                   capture_output=True, timeout=30)
                    healed.append(name)
                except Exception:
                    pass
    if healed:
        print(f"[eco-vol selfheal] 重跑失败任务: {', '.join(healed)}")


if __name__ == "__main__":
    main()
