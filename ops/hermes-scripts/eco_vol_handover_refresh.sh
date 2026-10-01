#!/usr/bin/env bash
# no_agent cron 入口: 每工作日刷新公网交接包(SETUP.md / ops / self-skill)。逻辑在项目 scripts/handover_refresh.py。
# 无变化=静默; 有新增板块等=一行摘要; 失败/红线=❌ 一行+非零退出。不调用大模型。
exec python3 <PROJECT_ROOT>/scripts/handover_refresh.py
