#!/usr/bin/env python3
"""VM 专用无头 Chrome + X 登录态(Chao 2026-10-07 选「甲」, 并亲自提供 cookie 文件)。
- 独立 profile: ~/.cache/x-vm-chrome (权限 700), 不与 Chao Mac 的 Chrome 共享任何东西
- 只监听 127.0.0.1:9444(CDP), 对外不暴露
- cookie 只从文件读, 经 Network.setCookies 注入; 不打印任何 value; 注入后删除工作副本
用法: python3 x_vm_chrome.py start | status | stop
"""
import glob, json, os, signal, subprocess, sys, time, urllib.request
import websocket
CHROME = '/home/user/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'
PROF = os.path.expanduser('~/.cache/x-vm-chrome')
PORT = 9444
PIDF = os.path.join(PROF, 'chrome.pid')


def alive():
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=3).read(); return True
    except Exception:
        return False


def start():
    if alive():
        print('已在运行'); return 0
    os.makedirs(PROF, mode=0o700, exist_ok=True)
    p = subprocess.Popen([CHROME, '--headless=new', '--no-sandbox', '--disable-gpu', f'--remote-debugging-port={PORT}',
                          '--remote-debugging-address=127.0.0.1', f'--user-data-dir={PROF}', '--window-size=1400,1000',
                          '--lang=en-US', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    open(PIDF, 'w').write(str(p.pid))
    for _ in range(40):
        if alive(): break
        time.sleep(0.5)
    else:
        print('Chrome 起不来'); return 2
    # 注入 cookie(只取 .x.com / x.com 条目; 不打印值)
    fs = sorted(glob.glob('/home/user/.hermes/cache/documents/doc_*x.com_json_*.json'), key=os.path.getmtime)
    ck = json.load(open(fs[-1], encoding='utf-8'))
    params = []
    for c in ck:
        d = {'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
             'secure': bool(c.get('secure')), 'httpOnly': bool(c.get('httpOnly'))}
        if c.get('expirationDate'): d['expires'] = c['expirationDate']
        ss = {'no_restriction': 'None', 'lax': 'Lax', 'strict': 'Strict'}.get(c.get('sameSite'))
        if ss: d['sameSite'] = ss
        params.append(d)
    br = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=5))['webSocketDebuggerUrl']
    ws = websocket.create_connection(br, timeout=20, suppress_origin=True)
    ws.send(json.dumps({'id': 1, 'method': 'Storage.setCookies', 'params': {'cookies': params}}))
    while True:
        m = json.loads(ws.recv())
        if m.get('id') == 1: break
    ws.close()
    print('cookie 注入:', 'ok' if 'error' not in m else f"失败 {m['error'].get('message', '')[:60]}", f'({len(params)} 条, 未打印任何值)')
    return 0


def stop():
    try:
        pid = int(open(PIDF).read()); os.kill(pid, signal.SIGTERM); print('已停止 PID', pid)
    except Exception as e:
        print('停止失败/未运行', type(e).__name__)


if __name__ == '__main__':
    a = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if a == 'start': sys.exit(start())
    elif a == 'stop': stop()
    else: print('运行中' if alive() else '未运行')
