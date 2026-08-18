"""build_us_jp_market_dbs.py — 建 3 个新 Notion DB(幂等) + 写入时序数据, db_id 写回 .env。

DB_YIELDS       美日 10Y/30Y 国债收益率(日频): Date + US_10Y/US_30Y/JP_10Y/JP_30Y
DB_NIKKEI       日经225 指数(日频): Date + Close
DB_FOREIGN_FLOW 外资净买入日股(周频, 万亿日元): Week + Net_Buy_JPY_T

收益率/日经 写最近 60 个日频点(够看趋势, 不刷屏); 外资流入写全部周(约53)。
幂等: upsert by title(Date/Week), 重跑不重复。绝不编造, 数据来自 fetch_*。
CLI: python -m src.build_us_jp_market_dbs
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from notion_writer import _req, upsert, prop_title, prop_num
import external_data as ed

PARENT = c.NOTION_PARENT_PAGE
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def _num_prop():
    return {"number": {"format": "number"}}


def find_existing_db(title):
    st, body = _req("GET", f"/blocks/{PARENT}/children?page_size=100")
    if st == 200:
        for b in body.get("results", []):
            if b.get("type") == "child_database":
                if b.get("child_database", {}).get("title", "") == title:
                    return b["id"]
    return None


def create_db(title, properties):
    existing = find_existing_db(title)
    if existing:
        print(f"[db] '{title}' 已存在: {existing}")
        return existing
    payload = {
        "parent": {"type": "page_id", "page_id": PARENT},
        "is_inline": True,
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    st, body = _req("POST", "/databases", payload)
    if st == 200:
        print(f"[db] '{title}' 建成: {body['id']}")
        return body["id"]
    print(f"[db] '{title}' 建库失败 {st}: {str(body)[:200]}")
    return None


def _write_env(key, val):
    """幂等把 key=val 写入 .env(已存在则替换)。"""
    lines = []
    found = False
    if os.path.exists(ENV_PATH):
        for ln in open(ENV_PATH):
            if ln.startswith(key + "="):
                lines.append(f"{key}={val}\n"); found = True
            else:
                lines.append(ln)
    if not found:
        lines.append(f"{key}={val}\n")
    open(ENV_PATH, "w").writelines(lines)


def build():
    # ── DB-1 美日收益率 ──
    yid = create_db("Eco-美日国债收益率(10Y/30Y,日频)", {
        "Date": {"title": {}},
        "US_10Y": _num_prop(), "US_30Y": _num_prop(),
        "JP_10Y": _num_prop(), "JP_30Y": _num_prop(),
    })
    # ── DB-2 日经225 ──
    nid = create_db("Eco-日经225指数(日频)", {
        "Date": {"title": {}}, "Close": _num_prop(),
    })
    # ── DB-3 外资流入日股 ──
    fid = create_db("Eco-外资净买入日股(周频,万亿日元)", {
        "Week": {"title": {}}, "Net_Buy_JPY_T": _num_prop(),
    })
    for k, v in (("DB_YIELDS", yid), ("DB_NIKKEI", nid), ("DB_FOREIGN_FLOW", fid)):
        if v:
            _write_env(k, v)
    return yid, nid, fid


def write_data(yid, nid, fid, recent_days=60):
    # 美日收益率: 按日期对齐四序列, 写最近 recent_days 天
    yc = ed.fetch_us_jp_yields()
    if yid and yc.get("status") == "ok":
        ser = yc["series"]
        # 合并所有日期
        bydate = {}
        keymap = {"us_10y": "US_10Y", "us_30y": "US_30Y", "jp_10y": "JP_10Y", "jp_30y": "JP_30Y"}
        for sk, col in keymap.items():
            for d, v in ser.get(sk, {}).get("points", []):
                bydate.setdefault(d, {})[col] = v
        dates = sorted(bydate)[-recent_days:]
        n = 0
        for d in dates:
            props = {"Date": prop_title(d)}
            for col in keymap.values():
                if col in bydate[d]:
                    props[col] = prop_num(bydate[d][col])
            upsert(yid, d, props, title_field="Date")
            n += 1
        print(f"[data] 美日收益率写入 {n} 日")

    # 日经225: 最近 recent_days 天
    nk = ed.fetch_nikkei225()
    if nid and nk.get("status") == "ok":
        pts = nk["points"][-recent_days:]
        for d, v in pts:
            upsert(nid, d, {"Date": prop_title(d), "Close": prop_num(v)}, title_field="Date")
        print(f"[data] 日经225写入 {len(pts)} 日")

    # 外资流入: 全部周(约53)
    ff = ed.fetch_foreign_flow_japan()
    if fid and ff.get("status") == "ok":
        for wk, v in ff["points"]:
            upsert(fid, wk, {"Week": prop_title(wk), "Net_Buy_JPY_T": prop_num(v)}, title_field="Week")
        print(f"[data] 外资流入写入 {len(ff['points'])} 周")


def write_data_from_env(recent_days=60):
    """从 .env 读三个 db_id 后写入(供每日 cron 调用, DB 已存在时无需重新建库)。
    若 .env 缺 db_id 则先 build()。"""
    def _env(k):
        if os.path.exists(ENV_PATH):
            for ln in open(ENV_PATH):
                if ln.startswith(k + "="):
                    return ln.strip().split("=", 1)[1]
        return os.environ.get(k)
    yid, nid, fid = _env("DB_YIELDS"), _env("DB_NIKKEI"), _env("DB_FOREIGN_FLOW")
    if not (yid and nid and fid):
        yid, nid, fid = build()
    write_data(yid, nid, fid, recent_days=recent_days)


if __name__ == "__main__":
    yid, nid, fid = build()
    write_data(yid, nid, fid)
    print("完成。db_id 已写回 .env (DB_YIELDS/DB_NIKKEI/DB_FOREIGN_FLOW)")
