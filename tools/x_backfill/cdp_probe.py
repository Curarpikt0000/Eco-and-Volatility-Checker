"""CDP 小工具(经 Chao 的 Chrome 隧道 localhost:9333): 开标签页 / 在页面里执行 JS。
x_day.py / x_days.py / x_web_fallback.py 都依赖它。曾只放在 /tmp, 网关重启后丢失 -> 现存进项目。
只读: 本模块只做「打开页面、读 DOM」, 不点击、不输入。
"""
import json, os, sys, time, urllib.parse, urllib.request
import websocket

PORT = int(os.environ.get('CDP_PORT', '9333'))
HOST = os.environ.get('CDP_HOST', 'localhost')


def tabs():
    return json.load(urllib.request.urlopen(f'http://{HOST}:{PORT}/json/list', timeout=8))


def new_tab(url):
    """后台开标签(不抢焦点): 浏览器级 CDP Target.createTarget(background=True)。
    Chao 2026-10-07: 「background去跑, 不要阻碍我chrome正常使用」。/json/new 会把新标签放前台, 已弃用。"""
    br = json.load(urllib.request.urlopen(f'http://{HOST}:{PORT}/json/version', timeout=8))['webSocketDebuggerUrl']
    ws = websocket.create_connection(br, timeout=20, suppress_origin=True)
    ws.send(json.dumps({'id': 1, 'method': 'Target.createTarget', 'params': {'url': url, 'background': True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get('id') == 1:
            ws.close()
            tid = m['result']['targetId']
            break
    for _ in range(20):                      # 等标签出现在 /json/list 以拿到页面级 ws 地址
        for t in tabs():
            if t.get('id') == tid:
                return t
        time.sleep(0.5)
    raise RuntimeError('后台标签未出现')


def run(ws_url, expr, wait=0):
    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    time.sleep(wait)
    ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                        'params': {'expression': expr, 'returnByValue': True, 'awaitPromise': True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get('id') == 1:
            ws.close()
            return m['result'].get('result', {}).get('value')


if __name__ == '__main__':
    t = new_tab(sys.argv[1]); ws = t['webSocketDebuggerUrl']; time.sleep(7)
    print(run(ws, "JSON.stringify({url:location.href,title:document.title,len:document.body.innerText.length})"))
    urllib.request.urlopen(f"http://localhost:{PORT}/json/close/{t['id']}", timeout=8)
