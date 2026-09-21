#!/usr/bin/env python3
"""建 Notion DB: 贵金属期权波动率时序 (DB_OPTVOL)。
★复用项目既有 create_db / find_existing_db(幂等, 已存在则不重建)。
★字段设计对应两张图 + 一年可回填的历史:
  - 一年可回填: GVZ(FRED官方) / GLD·SLV 30日已实现波动率(自算, 字段名带 RV 标明)
  - 从今起累积: 25D 偏斜(GLD/SLV) / ATM IV 期限结构(1M/3M/6M/12M/24M)
★纪律: 拿不到的字段留空(upsert skip_none=True 不会覆盖真值), 绝不填估算值。
"""
import sys, os
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")

from build_notion_dbs import find_existing_db, create_db, _num_prop

TITLE = "贵金属期权波动率时序"

PROPS = {
    "Date": {"title": {}},
    # ── 一年可回填(官方/可复算) ──
    "GVZ_黄金波动率指数": _num_prop(),
    "GLD_已实现波动率30D": _num_prop(),
    "SLV_已实现波动率30D": _num_prop(),
    # ── 25D 偏斜(Put IV − Call IV, 正=偏空) 从今起累积 ──
    "GLD_25D偏斜_1M": _num_prop(),
    "GLD_25D偏斜_3M": _num_prop(),
    "GLD_25D偏斜_12M": _num_prop(),
    "SLV_25D偏斜_1M": _num_prop(),
    "SLV_25D偏斜_3M": _num_prop(),
    "SLV_25D偏斜_12M": _num_prop(),
    # ── ATM IV 期限结构 从今起累积 ──
    "GLD_ATM_IV_1M": _num_prop(),
    "GLD_ATM_IV_3M": _num_prop(),
    "GLD_ATM_IV_6M": _num_prop(),
    "GLD_ATM_IV_12M": _num_prop(),
    "GLD_ATM_IV_24M": _num_prop(),
    "SLV_ATM_IV_1M": _num_prop(),
    "SLV_ATM_IV_3M": _num_prop(),
    "SLV_ATM_IV_6M": _num_prop(),
    "SLV_ATM_IV_12M": _num_prop(),
    "SLV_ATM_IV_24M": _num_prop(),
    # ── 形态判读 ──
    "GLD_期限结构形态": {"select": {}},
    "SLV_期限结构形态": {"select": {}},
    "数据来源": {"select": {}},
}

if __name__ == "__main__":
    existing = find_existing_db(TITLE)
    if existing:
        print(f"已存在，不重建。db_id={existing}")
        print(f"DB_OPTVOL={existing}")
    else:
        db = create_db(TITLE, PROPS)
        print(f"✅ 已创建 {TITLE}")
        print(f"DB_OPTVOL={db}")
