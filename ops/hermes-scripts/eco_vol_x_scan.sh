#!/usr/bin/env bash
# eco-vol X 每日扫描(no_agent): 读已核实账号的「上次之后的新帖」, 写本地库。
# 有输出才发消息(异常/预警/有新帖一行汇总), 无输出即正常静默。
# 钱的上限在 x_daily_scan.py / xapi.py 里(每日 $1, 总账本上限, 402=余额耗尽立即停并告警)。
cd <PROJECT_ROOT>/tools/x_backfill 2>/dev/null || { echo "⚠️ X 扫描: 进不去 tools/x_backfill 目录"; exit 0; }
# flock: 防止上一轮没跑完又起一轮(重复付费)
exec flock -n /tmp/x_daily_scan.lock /usr/bin/python3 x_daily_scan.py 2>&1
