#!/usr/bin/env bash
# eco-vol 网站监测(no_agent): KWN + Kitco, 命中名册 KOL 才发消息, 静默即正常。
cd <PROJECT_ROOT> 2>/dev/null || { echo "⚠️ 网站监测: 进不去项目目录"; exit 0; }
# flock: 防重入; 不吞 stderr, 脚本异常会直接出现在通知里
exec flock -n /tmp/web_watch.lock /usr/bin/python3 tools/web_watch.py 2>&1
