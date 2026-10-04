"""按天驱动 x_day.py, 断点续跑(已存在的日文件跳过), 每天间隔 12 秒, 连续 3 天失败即停(防限流)。
用法: python3 x_days.py <handle> <start> <end> <outdir>
"""
import json, sys, time, datetime, subprocess, os
handle = sys.argv[1]
d = datetime.date.fromisoformat(sys.argv[2]); end = datetime.date.fromisoformat(sys.argv[3]); outdir = sys.argv[4]
os.makedirs(outdir, exist_ok=True)
PY = '/home/user/.cdp-venv/bin/python'; HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0; done = 0; skipped = 0
while d < end:
    f = os.path.join(outdir, f'{d}.json')
    if os.path.exists(f):
        skipped += 1; d += datetime.timedelta(days=1); continue
    try:
        r = subprocess.run([PY, os.path.join(HERE, 'x_day.py'), handle, str(d), f], capture_output=True, text=True, timeout=200)
        line = (r.stdout.strip().splitlines() or [r.stderr.strip()[-120:]])[-1]
        ok = os.path.exists(f)
    except Exception as ex:
        line = f'{d} 失败 {type(ex).__name__}'; ok = False
    print(line, flush=True)
    if ok:
        fails = 0; done += 1
    else:
        fails += 1
        if fails >= 3:
            print('连续 3 天失败, 停止(疑似限流/登录态丢失), 已完成', done, '天'); break
    d += datetime.timedelta(days=1); time.sleep(12)
print('完成', done, '天, 跳过已有', skipped, '天')
