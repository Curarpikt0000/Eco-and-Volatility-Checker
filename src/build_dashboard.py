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
    kol_changes, liquidity, cb_balance, custody, auctions = {}, {}, {}, {}, {}
    kol_views = {}
    try:
        import external_data as ed
        # ★先把当日全量方向落盘为 Eco 独立快照(data/kol/daily/), 供周对比累积
        try:
            sp = ed.save_kol_daily_snapshot()
            if sp:
                print(f"[dashboard] KOL 当日快照已存: {sp}")
        except Exception as se:
            print(f"[dashboard] KOL 快照保存跳过: {se}")
        kol_changes = ed.kol_stance_changes_grouped() or {}
        kol_views = ed.kol_weekly_views() or {}
    except Exception as e:
        print(f"[dashboard] KOL 变化跳过: {e}")
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
    country_ust = {}
    try:
        import external_data as ed
        country_ust = ed.fetch_country_ust_holdings(years=10) or {}
    except Exception as e:
        print(f"[dashboard] 分国别持美债跳过: {e}")

    credit_impulse = {}
    try:
        import external_data as ed
        credit_impulse = ed.fetch_credit_impulse(years=8) or {}
    except Exception as e:
        print(f"[dashboard] Credit Impulse 跳过: {e}")

    custody_accel = {}
    try:
        custody_accel = ed.fetch_custody_acceleration(weeks=26) or {}
    except Exception as e:
        print(f"[dashboard] 托管美债加速度 跳过: {e}")

    # ── 国债市场压力四联图(对齐 Morgan Stanley 三图 + OFR官方压力指数) ──
    stress_panels = {}
    ofr_fsi = {}
    try:
        stress_panels = ed.fetch_treasury_stress_panels(years=3) or {}
        print(f"[dashboard] 国债压力三联图: status={stress_panels.get('status')} asof={stress_panels.get('asof')}")
    except Exception as e:
        print(f"[dashboard] 国债压力三联图 跳过: {e}")
    try:
        ofr_fsi = ed.fetch_ofr_fsi(years=3) or {}
        print(f"[dashboard] OFR FSI: status={ofr_fsi.get('status')} asof={ofr_fsi.get('asof')} latest={ofr_fsi.get('latest',{}).get('OFR FSI 总指数')}")
    except Exception as e:
        print(f"[dashboard] OFR FSI 跳过: {e}")
    # ★数据落盘 GitHub 副本(完整历史序列进 git)
    try:
        _data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "stress")
        os.makedirs(_data_dir, exist_ok=True)
        if stress_panels.get("panels"):
            with open(os.path.join(_data_dir, "treasury_stress_panels.json"), "w", encoding="utf-8") as f:
                json.dump(stress_panels, f, ensure_ascii=False, indent=2)
            print(f"[dashboard] 国债压力数据已落盘 data/stress/treasury_stress_panels.json")
        if ofr_fsi.get("panel"):
            with open(os.path.join(_data_dir, "ofr_fsi.json"), "w", encoding="utf-8") as f:
                json.dump(ofr_fsi, f, ensure_ascii=False, indent=2)
            print(f"[dashboard] OFR FSI 数据已落盘 data/stress/ofr_fsi.json")
    except Exception as e:
        print(f"[dashboard] 国债压力数据落盘跳过: {e}")
    # ★写 Notion(最新值时序, 失败不阻塞)
    try:
        pid = ed.write_stress_panels_notion(stress_panels)
        if pid:
            print(f"[dashboard] 国债压力最新值已写 Notion: {pid}")
    except Exception as e:
        print(f"[dashboard] 国债压力写 Notion 跳过: {e}")
    try:
        pid = ed.write_ofr_notion(ofr_fsi)
        if pid:
            print(f"[dashboard] OFR FSI 最新值已写 Notion: {pid}")
    except Exception as e:
        print(f"[dashboard] OFR 写 Notion 跳过: {e}")

    out = dash.generate(
        snap, checks, hit, gstats, overall,
        holdings=holdings, kol_changes=kol_changes,
        kol_views=kol_views,
        liquidity=liquidity, cb_balance=cb_balance, custody=custody,
        auctions=auctions, money_supply=money_supply, m2_history=m2_history,
        country_ust=country_ust,
        credit_impulse=credit_impulse,
        custody_accel=custody_accel,
        stress_panels=stress_panels,
        ofr_fsi=ofr_fsi,
    )
    print(f"[dashboard] 生成: {out}")
    return out


if __name__ == "__main__":
    main()
