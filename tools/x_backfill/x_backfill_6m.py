#!/usr/bin/env python3
"""X 网页 6 个月回填执行器(Chao 2026-10-07: 「X全量」+「用我的chrome background慢慢backfill」)。
顺序跑 x_backfill_6m_plan.json 里每个账号的区间; 断点续跑(已存在日文件跳过, 靠 x_days.py);
隧道每个账号前检查, 不通就停(只有 Chao 能在 Mac 上重建); 连续 3 天失败由 x_days 自停, 本脚本再整体停。
进度: data/x_backfill/x_backfill_6m_progress.json + stdout 日志; 只读, 不点赞不关注; source=web, 标「可能漏」。
用法: python3 x_backfill_6m.py [handle ...]   (不给则按计划里 缺口小→大 全跑)
"""
import datetime, json, os, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import x_daily_scan as S
PY = '/home/user/.cdp-venv/bin/python'
PLAN = os.path.join(S.DATA, 'x_backfill_6m_plan.json')
PROG = os.path.join(S.DATA, 'x_backfill_6m_progress.json')


def tunnel_ok():
    try:
        urllib.request.urlopen(f"http://{os.environ.get('CDP_HOST', 'localhost')}:{os.environ.get('CDP_PORT', '9333')}/json/version", timeout=6).read(); return True
    except Exception:
        return False


def main():
    plan = json.load(open(PLAN)); prog = json.load(open(PROG)) if os.path.exists(PROG) else {}
    only = sys.argv[1:]
    order = sorted(plan, key=lambda a: plan[a]['days']) if not only else only
    for a in order:
        if a not in plan:
            print(f'[跳过] @{a} 不在计划里'); continue
        v = plan[a]
        if prog.get(a, {}).get('status') == 'done':
            print(f'[已完成] @{a}'); continue
        if not tunnel_ok():
            print('[停] CDP 通道不通(端口 %s), 停在 @%s。恢复后重跑本脚本即断点续跑。' % (os.environ.get('CDP_PORT', '9333'), a)); return 2
        end = datetime.date.fromisoformat(v['to']) + datetime.timedelta(days=1)   # x_days 的 end 是开区间
        outdir = os.path.join(S.DATA, 'web_rows', a)
        t0 = time.time()
        print(f'[{datetime.datetime.now():%m-%d %H:%M}] ▶ @{a} {v["from"]}→{v["to"]} ({v["days"]}天)', flush=True)
        r = subprocess.run([PY, os.path.join(HERE, 'x_days.py'), a, v['from'], str(end), outdir], text=True, capture_output=True)
        tail = (r.stdout.strip().splitlines() or [''])[-1]
        n_have = sum(1 for d in range(v['days']) if os.path.exists(os.path.join(outdir, f'{datetime.date.fromisoformat(v["from"]) + datetime.timedelta(days=d)}.json')))
        stopped = '连续 3 天失败' in r.stdout
        prog[a] = {'status': 'stopped_fail' if stopped else ('done' if n_have >= v['days'] else 'partial'), 'days_have': n_have, 'days_need': v['days'], 'last': tail[:120], 'min': round((time.time() - t0) / 60, 1)}
        json.dump(prog, open(PROG, 'w'), ensure_ascii=False, indent=1)
        print(f'   ■ @{a} {prog[a]["status"]} {n_have}/{v["days"]} 天 用时 {prog[a]["min"]} 分 | {tail[:90]}', flush=True)
        if stopped:
            print('[停] 连续失败(疑似限流/登录态丢失), 整体停止, 不硬撑。'); return 3
    print('全部账号处理完'); return 0


if __name__ == '__main__':
    sys.exit(main())
