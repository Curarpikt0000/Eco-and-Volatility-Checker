#!/usr/bin/env python3
"""建 Notion DB: COMEX 期货期权持仓时序 (DB_COMEXOPT)。
★这不是 IV —— COMEX 期货期权的隐含波动率是 CME 商业数据, 无免费源
  (CME API/ftp 403、Barchart 403、Yahoo 期货期权链 401、CBOE 不覆盖期货期权,
   ScraperAPI 走 CME 被导向营销页)。
★本表记录的是**持仓方向**: Managed Money 在期权上是净多还是净空。
  口径 = Disagg(Futures+Options) − Disagg(Futures Only), 两者同为 CFTC 官方,
  已在 **170 周(3年+)** 长样本上验证期权 OI 差 0 次为负 —— 口径成立。
"""
import sys, os
sys.path.insert(0, "/home/user/Projects/Eco-and-Volatility-Checker/src")
os.chdir("/home/user/Projects/Eco-and-Volatility-Checker")
from build_notion_dbs import find_existing_db, create_db, _num_prop

TITLE = "COMEX期货期权持仓时序"
PROPS = {
    "Date": {"title": {}},
    # ── 黄金 ──
    "金_MM净多_张": _num_prop(),
    "金_MM净多_吨": _num_prop(),
    "金_期权净多_张": _num_prop(),
    "金_期权OI_张": _num_prop(),
    "金_总OI_含期权": _num_prop(),
    # ── 白银 ──
    "银_MM净多_张": _num_prop(),
    "银_MM净多_吨": _num_prop(),
    "银_期权净多_张": _num_prop(),
    "银_期权OI_张": _num_prop(),
    "银_总OI_含期权": _num_prop(),
    # ── 判读 ──
    "金_期权方向": {"select": {}},
    "银_期权方向": {"select": {}},
    "数据来源": {"select": {}},
}

if __name__ == "__main__":
    existing = find_existing_db(TITLE)
    db = existing or create_db(TITLE, PROPS)
    print(("已存在，不重建。" if existing else "✅ 已创建 ") + TITLE)
    print(f"DB_COMEXOPT={db}")
