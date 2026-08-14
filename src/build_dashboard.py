"""build_dashboard.py — 从现有快照 + 数据文件独立重建 dashboard(不重抓)。

用途:
  1. 改 dashboard.py 后独立验证渲染(不跑整个 daily cron)
  2. daily cron 可调本脚本简化生成步骤

数据来源(全部读已存文件, 不联网):
  - 最新 snapshot(data/snapshots/*.json) → snap
  - signals → checks/hit/gstats/overall
  - holdings_13f.json → 机构持仓
  - politician_disclosure.json → 政要(dashboard 内部自己 load)
  - external_data → kol_changes/liquidity/cb_balance(读其它 DB, 会联网; 失败则跳过)
"""
import sys
import os
import glob
import json

sys.path.insert(0, os.path.dirname(__file__))
import signals as sg
import dashboard as dash
import holdings_13f as h13


def latest_snapshot():
    snaps = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "*.json")))
    if not snaps:
        raise SystemExit("无快照, 先跑 run.py")
    return json.load(open(snaps[-1])), snaps[-1]


def history_getter_factory(snap_dir):
    def getter(key, days=21):
        return dash.load_history(snap_dir, key, days=days)
    return getter


def main():
    snap, path = latest_snapshot()
    snap_dir = os.path.dirname(path)
    print(f"[dashboard] 用快照 {os.path.basename(path)} (date={snap['date']})")

    results = snap["results"]
    cot = snap.get("cot", {})

    # signals
    hg = history_getter_factory(snap_dir)
    checks, hit = sg.eval_sell_triggers(results, cot, history_getter=hg)
    gstats = sg.group_stats(results)
    overall = sg.overall_signal(hit, gstats)

    # holdings
    holdings = h13.load_holdings()

    # 可选: 联网读的板块(失败不阻塞)
    kol_changes, liquidity, cb_balance, custody, auctions = [], {}, {}, {}, {}
    # kol_changes 需 [{prev_dir,new_dir,...}] 结构, 由 daily cron 的 kol_stance_changes() 产出;
    # 本独立重建脚本不重算 KOL 变化(留空), 只验证机构/政要/流动性/央行板块渲染。
    try:
        import external_data as ed
        liquidity = ed.fetch_liquidity_points() or {}
    except Exception as e:
        print(f"[dashboard] 流动性跳过: {e}")
    try:
        import external_data as ed
        cb_balance = ed.fetch_cb_balance_sheets() or {}
    except Exception as e:
        print(f"[dashboard] 央行资负表跳过: {e}")
    try:
        import external_data as ed
        custody = ed.fetch_foreign_custody_ust() or {}
    except Exception as e:
        print(f"[dashboard] 外国托管美债跳过: {e}")
    try:
        import external_data as ed
        auctions = ed.fetch_treasury_auctions() or {}
    except Exception as e:
        print(f"[dashboard] 国债拍卖跳过: {e}")
    money_supply = {}
    try:
        import external_data as ed
        money_supply = ed.fetch_money_supply() or {}
    except Exception as e:
        print(f"[dashboard] 货币供应量跳过: {e}")
    m2_history = {}
    try:
        import external_data as ed
        m2_history = ed.fetch_m2_history() or {}
    except Exception as e:
        print(f"[dashboard] M2历史跳过: {e}")

    out = dash.generate(
        snap, checks, hit, gstats, overall,
        holdings=holdings, kol_changes=kol_changes,
        liquidity=liquidity, cb_balance=cb_balance, custody=custody,
        auctions=auctions, money_supply=money_supply, m2_history=m2_history,
    )
    print(f"[dashboard] 生成: {out}")
    return out


if __name__ == "__main__":
    main()
