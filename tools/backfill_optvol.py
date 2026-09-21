#!/usr/bin/env python3
"""回填一年历史到 DB_OPTVOL。
★只回填**真有一年历史**的字段:
   GVZ_黄金波动率指数     ← FRED GVZCLS(官方, CBOE 黄金ETF波动率指数)
   GLD/SLV_已实现波动率30D ← 自算(Yahoo 日线 30日滚动标准差年化), 字段名已标 RV
★**不回填** 25D 偏斜 / ATM IV 期限结构 —— CBOE 只有当下快照, 无历史。
   这些字段留空, 从今天起每日累积。留空 != 0, upsert skip_none 不会写 0 进去。
★白银官方波动率指数 VXSLVCLS 已于 2022-02 停更, 近一年 0 点 → 不用, 以 RV 替代并标注。
"""
import sys, os, json, ssl, urllib.request, datetime, statistics as st, time
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")
from notion_writer import upsert, prop_num, prop_select, prop_title

DB = None
for ln in open(".env"):
    if ln.startswith("DB_OPTVOL="): DB = ln.split("=",1)[1].strip()
assert DB, "DB_OPTVOL 未在 .env"

_CTX=ssl.create_default_context(); _CTX.check_hostname=False; _CTX.verify_mode=ssl.CERT_NONE
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
FRED=""
for ln in open(".env"):
    if ln.startswith("FRED_API_KEY"): FRED=ln.split("=",1)[1].strip().strip('"\'')

START = (datetime.date.today() - datetime.timedelta(days=370)).isoformat()

def fred(sid):
    u=(f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
       f"&api_key={FRED}&file_type=json&observation_start={START}")
    d=json.loads(urllib.request.urlopen(u,timeout=45,context=_CTX).read())
    return {o["date"]: float(o["value"]) for o in d.get("observations",[]) if o["value"] not in (".","")}

def yahoo(sym):
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d"
    r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=45,context=_CTX)
    d=json.loads(r.read())["chart"]["result"][0]
    ts=d.get("timestamp") or []; cl=d["indicators"]["quote"][0].get("close") or []
    return [(datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c)
            for t,c in zip(ts,cl) if c is not None]

def rv30(sym):
    px=yahoo(sym)
    rets=[(px[i][1]/px[i-1][1]-1) for i in range(1,len(px))]
    out={}
    for i in range(30,len(rets)):
        out[px[i+1][0]] = st.pstdev(rets[i-30:i])*(252**0.5)*100
    return out

print("抓取中…")
gvz = fred("GVZCLS")
gld_rv = rv30("GLD")
slv_rv = rv30("SLV")
print(f"  GVZ(FRED官方)      {len(gvz)} 点")
print(f"  GLD RV30(自算)     {len(gld_rv)} 点")
print(f"  SLV RV30(自算)     {len(slv_rv)} 点")

dates = sorted(set(gvz) | set(gld_rv) | set(slv_rv))
dates = [d for d in dates if d >= START]
print(f"  合并日期 {len(dates)} 天  {dates[0]} ~ {dates[-1]}")

ok=fail=0
for i, d in enumerate(dates, 1):
    props = {
        "GVZ_黄金波动率指数":   prop_num(round(gvz[d],2)    if d in gvz    else None),
        "GLD_已实现波动率30D":  prop_num(round(gld_rv[d],2) if d in gld_rv else None),
        "SLV_已实现波动率30D":  prop_num(round(slv_rv[d],2) if d in slv_rv else None),
        "数据来源": prop_select("FRED官方+自算RV(回填)"),
    }
    try:
        upsert(DB, d, props, title_field="Date")
        ok+=1
    except Exception as e:
        fail+=1
        if fail<=3: print(f"  ✗ {d}: {type(e).__name__} {str(e)[:70]}")
    if i%40==0:
        print(f"  进度 {i}/{len(dates)}  ok={ok} fail={fail}")
    time.sleep(0.12)

print(f"\n完成: ok={ok} fail={fail} / 共 {len(dates)}")
