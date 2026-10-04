"""阶段一: 用 API 批量核对「X 人物搜索里出现过的候选账号」, 产出每人最佳候选 + 置信度。
输入 /tmp/x_cand_stage1.json {kol_id:[handle..]}; 输出 data/x_backfill/x_handle_api.json
★门禁(机械): 同 x_handle_verify.verdict 的规则, 但数据来自 API(简介/粉丝/认证更可靠):
  verified = 姓名双命中 + (强机构词 或 认证且粉丝>=1万) + 非备份/模仿/粉丝号 + 非受保护账号 + 账号年龄>=1年
  name_only = 姓名双命中但证据不足(需人审); 其余 reject
"""
import json, os, re, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xapi, x_handle_judge as J

OUT = os.path.join(J.ROOT, 'data', 'x_backfill', 'x_handle_api.json')


def verdict(k, u):
    if not u:
        return 'reject', '账号不存在', 0
    nm = J.norm(J.en_name(k)).split()
    if len(nm) < 2:
        return 'reject', '名册名不足两词', 0
    name_ok = all(w in J.norm(u.get('name', '')).split() for w in (nm[0], nm[-1]))
    bio = u.get('description', '') or ''
    pm = u.get('public_metrics', {}) or {}
    fol = pm.get('followers_count', 0)
    badge = u.get('verified') or (u.get('verified_type') not in (None, 'none'))
    if not name_ok:
        return 'reject', '显示名不含姓+名', fol
    if J.BAD.search(bio) or u.get('protected'):
        return 'reject', '备份/模仿/受保护', fol
    age_ok = True
    if u.get('created_at'):
        age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(u['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)).days
        age_ok = age >= 365
    if not age_ok:
        return 'name_only', '账号不足1年', fol
    org = J.org_ok(k, bio + ' ' + (u.get('location') or ''))
    if org:
        return 'verified', '姓名双命中+强机构词', fol
    if badge and fol >= 10000:
        return 'verified', f'姓名双命中+认证+粉丝{fol}', fol
    return 'name_only', f'姓名双命中, 无强机构词/无认证大号(粉丝{fol})', fol


if __name__ == '__main__':
    kols = {k['id']: k for k in json.load(open(J.REG))['kols']}
    plan = json.load(open('/tmp/x_cand_stage1.json'))
    allh = sorted({h for v in plan.values() for h in v}, key=str.lower)
    users = xapi.users_by_username(allh)
    res = {}
    for kid, hs in plan.items():
        best = None; rows = []
        for h in hs:
            u = users.get(h.lower())
            v, why, fol = verdict(kols[kid], u)
            rows.append({'handle': h, 'verdict': v, 'why': why, 'followers': fol, 'name': (u or {}).get('name'), 'bio': ((u or {}).get('description') or '')[:140]})
            rk = {'verified': 2, 'name_only': 1, 'reject': 0}[v]
            if best is None or (rk, fol) > (best[0], best[1]):
                best = (rk, fol, h, v)
        res[kid] = {'name': J.en_name(kols[kid]), 'final': best[3] if best else 'none', 'handle': best[2] if best and best[0] > 0 else None, 'rows': rows}
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    import collections
    print('结果:', dict(collections.Counter(r['final'] for r in res.values())))
    print('已花 $%.3f' % xapi._spent())
