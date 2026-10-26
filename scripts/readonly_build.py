"""只读构建: 在项目目录(带 .env)跑 src/build_dashboard.py, 但在 HTTP 层拦住所有对 Notion 的写入。
放行: 非 Notion 的任何请求; Notion 的 GET; Notion 的 POST /databases/<id>/query(只读查询)。
拦截: 其余一切 Notion 请求(POST /pages, PATCH, DELETE, PUT, blocks/children 追加等), 返回假 403, 不发出网络请求。
拦截记录写 /tmp/ro_guard_blocked.log, 构建结束打印汇总。
用法:  python scripts/readonly_build.py            # 构建
       python scripts/readonly_build.py --selftest # 只自测闸门, 不联网, 不构建
Chao 2026-10-26「可以建」。重建自 /tmp/run_readonly_build.py(/tmp 被清后丢失); 原脚本内容未能找回, 以本文件为准。
"""
import os, re, sys, runpy, json, urllib.request, urllib.error
import requests
from requests.models import Response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = "/tmp/ro_guard_blocked.log"
BLOCKED = []
_QUERY = re.compile(r"/v1/databases/[0-9a-fA-F-]+/query/?(\?.*)?$")


def _is_notion(url):
    return "notion.com" in str(url).lower() or "notion.so" in str(url).lower()


def _allowed(method, url):
    if not _is_notion(url):
        return True
    m = str(method).upper()
    if m in ("GET", "HEAD"):
        return True
    if m == "POST" and _QUERY.search(str(url)):
        return True
    return False


def _fake_403(url):
    r = Response(); r.status_code = 403; r._content = b'{"object":"error","code":"readonly_guard","message":"blocked by readonly_build"}'
    r.url = str(url); r.headers["Content-Type"] = "application/json"
    return r


def install(_orig_session_request=None, _orig_urlopen=None):
    orig_req = _orig_session_request or requests.sessions.Session.request
    orig_open = _orig_urlopen or urllib.request.urlopen

    def guarded_request(self, method, url, *a, **k):
        if not _allowed(method, url):
            BLOCKED.append("%s %s" % (str(method).upper(), url)); return _fake_403(url)
        return orig_req(self, method, url, *a, **k)

    def guarded_urlopen(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = (req.get_method() if hasattr(req, "get_method") else "GET")
        if not _allowed(method, url):
            BLOCKED.append("%s %s (urllib)" % (method, url))
            raise urllib.error.HTTPError(url, 403, "blocked by readonly_build", {}, None)
        return orig_open(req, *a, **k)

    requests.sessions.Session.request = guarded_request
    urllib.request.urlopen = guarded_open = guarded_urlopen
    return orig_req, orig_open


def selftest():
    calls = []
    def stub(self, method, url, *a, **k):
        calls.append((str(method).upper(), str(url))); r = Response(); r.status_code = 200; r._content = b"{}"; return r
    install(_orig_session_request=stub, _orig_urlopen=lambda *a, **k: None)
    N = "https://api.notion.com/v1"
    cases = [  # (method, url, 应放行?)
        ("POST", N + "/databases/35947eb5-fd3c-800d-b852-cef31f9de6a5/query", True),
        ("POST", N + "/databases/abc123/query?x=1", True),
        ("GET", N + "/pages/abc", True),
        ("GET", N + "/databases/abc", True),
        ("POST", N + "/pages", False),
        ("PATCH", N + "/pages/abc", False),
        ("DELETE", N + "/blocks/abc", False),
        ("PATCH", N + "/blocks/abc/children", False),
        ("PUT", N + "/pages/abc", False),
        ("POST", N + "/databases", False),
        ("POST", N + "/databases/abc/query/../pages", False),
        ("GET", "https://api.stlouisfed.org/fred/series", True),
        ("POST", "https://example.com/pages", True),
    ]
    bad = 0
    for m, u, ok in cases:
        before = len(calls); r = requests.request(m, u); passed = len(calls) > before
        flag = "OK " if passed == ok else "错!"; bad += (passed != ok)
        print("  %s %-6s %-70s 期望%s 实际%s status=%s" % (flag, m, u[-68:], "放行" if ok else "拦截", "放行" if passed else "拦截", r.status_code))
    print("自测: %d 项, 不符 %d, 拦截记录 %d" % (len(cases), bad, len(BLOCKED)))
    return 1 if bad else 0


def main():
    install()
    sys.path.insert(0, os.path.join(ROOT, "src")); os.chdir(ROOT)
    print("[readonly_build] 闸门已装(Notion 仅放行 GET 与 databases/*/query); 开始构建 …", flush=True)
    rc = 0
    try:
        runpy.run_path(os.path.join(ROOT, "src", "build_dashboard.py"), run_name="__main__")
    except SystemExit as e:
        rc = int(e.code or 0)
    finally:
        open(LOG, "w").write("\n".join(BLOCKED))
        print("[readonly_build] 被拦截的 Notion 写入请求: %d 条 (明细 %s)" % (len(BLOCKED), LOG))
        for b in BLOCKED[:12]: print("   ", b[:150])
    return rc


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
