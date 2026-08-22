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
    kol_history = {}
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
        # ★全量历史观点(供卡片两层展开钻取): 每日快照 + 历史回填, 连续同言论合并成区间
        try:
            kol_history = ed.kol_full_history() or {}
            _n = sum(len(v) for v in kol_history.values())
            print(f"[dashboard] KOL 历史观点: {len(kol_history)} 人 / {_n} 条")
        except Exception as he:
            print(f"[dashboard] KOL 历史观点跳过: {he}")
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

    # ── 1年内到期需展期的可交易国债(再融资墙, MSPD) ──
    maturing_treasury = {}
    try:
        maturing_treasury = ed.fetch_maturing_treasury() or {}
        print(f"[dashboard] 1年内到期国债: status={maturing_treasury.get('status')} "
              f"latest={maturing_treasury.get('value')}T asof={maturing_treasury.get('as_of')}")
    except Exception as e:
        print(f"[dashboard] 1年内到期国债 跳过: {e}")

    # ── 日美年度财政花费(政府总支出/预算, 双轴柱状) ──
    fiscal_budget = {}
    try:
        fiscal_budget = ed.fetch_fiscal_budget() or {}
        print(f"[dashboard] 日美财政花费: status={fiscal_budget.get('status')} "
              f"as_of={fiscal_budget.get('as_of')} us={len(fiscal_budget.get('us',[]))}年 "
              f"jp={len(fiscal_budget.get('jp',[]))}年")
    except Exception as e:
        print(f"[dashboard] 日美财政花费 跳过: {e}")

    # ── 美国石油库存运营红线(Brent-WTI价差 / Cushing / SPR, EIA+FRED) ──
    oil_inventory = {}
    try:
        oil_inventory = ed.fetch_oil_inventory() or {}
        _sp = oil_inventory.get("spread", {})
        _cu = oil_inventory.get("cushing", {})
        _spr = oil_inventory.get("spr", {})
        print(f"[dashboard] 石油库存: spread={_sp.get('status')}({_sp.get('latest')}) "
              f"cushing={_cu.get('status')}({_cu.get('latest')}Mbbl) "
              f"spr={_spr.get('status')}({_spr.get('latest')}Mbbl)")
    except Exception as e:
        print(f"[dashboard] 石油库存 跳过: {e}")

    # ── 美日 10Y/30Y 收益率(FRED + MOF JGB) ──
    us_jp_yields = {}
    try:
        us_jp_yields = ed.fetch_us_jp_yields() or {}
        _ys = us_jp_yields.get("series", {})
        print(f"[dashboard] 美日收益率: " + " ".join(
            f"{k}={_ys.get(k,{}).get('status')}({_ys.get(k,{}).get('latest')})" for k in ("us_10y","us_30y","jp_10y","jp_30y")))
    except Exception as e:
        print(f"[dashboard] 美日收益率 跳过: {e}")

    # ── 日经225(FRED) ──
    nikkei225 = {}
    try:
        nikkei225 = ed.fetch_nikkei225() or {}
        print(f"[dashboard] 日经225: status={nikkei225.get('status')} latest={nikkei225.get('latest')} asof={nikkei225.get('as_of')}")
    except Exception as e:
        print(f"[dashboard] 日经225 跳过: {e}")

    # ── 外资净买入日股(JPX 周报) ──
    foreign_flow = {}
    try:
        foreign_flow = ed.fetch_foreign_flow_japan() or {}
        _fp = foreign_flow.get("points", [])
        print(f"[dashboard] 外资流入日股: status={foreign_flow.get('status')} 周数={len(_fp)} 最新={foreign_flow.get('latest')}万亿円")
    except Exception as e:
        print(f"[dashboard] 外资流入日股 跳过: {e}")

    # ── 四国 IIP 国际投资头寸(IMF SDMX) ──
    iip_four = {}
    try:
        iip_four = ed.fetch_iip_four_countries() or {}
        _ic = iip_four.get("countries", {})
        print(f"[dashboard] 四国IIP: status={iip_four.get('status')} as_of={iip_four.get('as_of')} " +
              " ".join(f"{k}={_ic.get(k,{}).get('latest_net')}T" for k in ("US","JP","DE","CN")))
    except Exception as e:
        print(f"[dashboard] 四国IIP 跳过: {e}")

    # ── 美日财政政策事件时间线(data/fiscal_news.json, cron agent 动态更新) ──
    fiscal_news = {}
    try:
        fiscal_news = ed.fetch_fiscal_news() or {}
        print(f"[dashboard] 美日财政事件: status={fiscal_news.get('status')} "
              f"as_of={fiscal_news.get('as_of')} 事件数={len(fiscal_news.get('events', []))}")
    except Exception as e:
        print(f"[dashboard] 美日财政事件 跳过: {e}")

    # ── 对冲基金美债杠杆监测(OFR Hedge Fund Monitor, 季度) ──
    hf_leverage = {}
    try:
        hf_leverage = ed.fetch_hf_leverage() or {}
        _hx = hf_leverage.get("exposure", {}); _hb = hf_leverage.get("borrow", {})
        print(f"[dashboard] 对冲基金杠杆: status={hf_leverage.get('status')} as_of={hf_leverage.get('as_of')} "
              f"敞口/GDP={_hx.get('latest_pct')}% Repo={_hb.get('latest_repo')}T")
    except Exception as e:
        print(f"[dashboard] 对冲基金杠杆 跳过: {e}")

    # ── BIS 自营黄金掉期(BIS 年报 + GATA/Lambourne 月度推算, 吨) ──
    bis_gold_swaps = {}
    try:
        bis_gold_swaps = ed.fetch_bis_gold_swaps() or {}
        print(f"[dashboard] BIS黄金掉期: status={bis_gold_swaps.get('status')} "
              f"latest={bis_gold_swaps.get('latest_t')}t@{bis_gold_swaps.get('latest_date')} "
              f"peak={bis_gold_swaps.get('peak_t')}t points={len(bis_gold_swaps.get('points',[]))}")
    except Exception as e:
        print(f"[dashboard] BIS黄金掉期 跳过: {e}")

    # ── 美股市场广度(RSP/SPY 等权比, 替代 A/D 腾落线, 东财原生API) ──
    market_breadth = {}
    try:
        market_breadth = ed.fetch_market_breadth() or {}
        print(f"[dashboard] 市场广度: status={market_breadth.get('status')} "
              f"as_of={market_breadth.get('as_of')} divergence={market_breadth.get('divergence')} "
              f"stale={market_breadth.get('stale')} pts={len(market_breadth.get('spy_points',[]))}")
    except Exception as e:
        print(f"[dashboard] 市场广度 跳过: {e}")

    # ── 真 A/D 腾落线(Economic-Dashboard cron, SP500 全成分股) ──
    ad_line_real = {}
    try:
        # 先 git fetch + fast-forward Economic-Dashboard 拿当日 A/D 数据(只读消费方)
        import subprocess as _sp
        _ed_repo = os.path.expanduser("~/Projects/Economic-Dashboard")
        if os.path.isdir(_ed_repo):
            try:
                _sp.run(["git", "-C", _ed_repo, "fetch", "origin", "main", "--quiet"],
                        timeout=40, check=False)
                _sp.run(["git", "-C", _ed_repo, "reset", "--hard", "origin/main", "--quiet"],
                        timeout=20, check=False)
            except Exception as _ge:
                print(f"[dashboard] A/D git sync 警告(用现有本地文件): {_ge}")
        ad_line_real = ed.fetch_ad_line_real() or {}
        print(f"[dashboard] A/D 腾落线(真): status={ad_line_real.get('status')} "
              f"as_of={ad_line_real.get('as_of')} divergence={ad_line_real.get('divergence')} "
              f"cum={ad_line_real.get('latest_cumulative')} pts={len(ad_line_real.get('spy_points',[]))}")
    except Exception as e:
        print(f"[dashboard] A/D 腾落线 跳过: {e}")

    # ── 印度/中国黄金 domestic premium (WGC goldhub xlsx 解析) ──
    gold_premium = {}
    try:
        gold_premium = ed.fetch_gold_premium() or {}
        gi = (gold_premium.get("india") or {})
        print(f"[dashboard] 黄金premium: status={gold_premium.get('status')} "
              f"as_of={gold_premium.get('as_of')} 印度n={gi.get('n')} latest={gi.get('latest')}")
    except Exception as e:
        print(f"[dashboard] 黄金premium 跳过: {e}")

    # ── 印度白银月度进口 (UN Comtrade 免费, 每月增量) ──
    silver_imports = {}
    try:
        # 先跑 fetch 脚本拉新月(幂等增量; Comtrade 未发布则跳过不覆盖)
        import subprocess as _sp
        _si_script = os.path.join(os.path.dirname(__file__), "fetch_silver_imports.py")
        try:
            _sp.run(["python3", _si_script], timeout=120, check=False)
        except Exception as _se:
            print(f"[dashboard] 白银进口 fetch 警告(用现有JSON): {_se}")
        silver_imports = ed.fetch_silver_imports_data() or {}
        print(f"[dashboard] 印度白银进口: status={silver_imports.get('status')} "
              f"as_of={silver_imports.get('as_of')} 最新={silver_imports.get('latest_tonnes')}t "
              f"n={silver_imports.get('n')}")
    except Exception as e:
        print(f"[dashboard] 印度白银进口 跳过: {e}")

    # ── 白银做市商头寸(CFTC COT commercial 净持仓, 一手官方) ──
    silver_bank_positions = {}
    try:
        silver_bank_positions = ed.fetch_silver_bank_positions() or {}
        print(f"[dashboard] 白银做市商头寸: status={silver_bank_positions.get('status')} "
              f"as_of={silver_bank_positions.get('as_of')} net={silver_bank_positions.get('latest_net')} "
              f"pts={len(silver_bank_positions.get('points',[]))}")
    except Exception as e:
        print(f"[dashboard] 白银做市商头寸 跳过: {e}")

    # ── COMEX 白银 issues/stops 静态参考(Michael Lynch, 手抄锚点) ──
    comex_silver_issues_ref = {}
    try:
        comex_silver_issues_ref = ed.fetch_comex_silver_issues_ref() or {}
        print(f"[dashboard] COMEX白银issues参考: status={comex_silver_issues_ref.get('status')} "
              f"as_of={comex_silver_issues_ref.get('as_of')} pts={len(comex_silver_issues_ref.get('points',[]))}")
    except Exception as e:
        print(f"[dashboard] COMEX白银issues参考 跳过: {e}")

    # ── 美国黄金出口(FRED IEAXGG Nonmonetary gold, 去美元化/回流实物金) ──
    gold_exports = {}
    try:
        gold_exports = ed.fetch_gold_exports() or {}
        print(f"[dashboard] 美国黄金出口: status={gold_exports.get('status')} "
              f"as_of={gold_exports.get('as_of')} latest={gold_exports.get('latest')}M$ "
              f"surge={gold_exports.get('surge_x')}x pts={len(gold_exports.get('points',[]))}")
    except Exception as e:
        print(f"[dashboard] 美国黄金出口 跳过: {e}")

    # ── 美国国债收益率百年周期(图5, FRED 4线月度) ──
    us_yield_century = {}
    try:
        us_yield_century = ed.fetch_us_yield_century() or {}
        print(f"[dashboard] 百年收益率: status={us_yield_century.get('status')} "
              f"as_of={us_yield_century.get('as_of')} series={len(us_yield_century.get('series',{}))}")
    except Exception as e:
        print(f"[dashboard] 百年收益率 跳过: {e}")

    # ── COMEX 三金属 per-firm top10 交货/接货方(需求B, Chao 2026-08-22) ──
    comex_firms_top10 = {}
    try:
        comex_firms_top10 = ed.fetch_comex_issue_stop_firms() or {}
        _cov = comex_firms_top10.get("coverage", {})
        print(f"[dashboard] COMEX交割前十名: status={comex_firms_top10.get('status')} "
              f"as_of={comex_firms_top10.get('as_of')} "
              f"覆盖={_cov.get('days','?')}天 "
              f"金属={list(comex_firms_top10.get('metals', {}).keys())}")
    except Exception as e:
        print(f"[dashboard] COMEX交割前十名 跳过: {e}")

    # ── COMEX 做市商每周净 issue/stop(图1, 金+银两口径) ──
    comex_issue_stop = {}
    try:
        comex_issue_stop = ed.fetch_comex_issue_stop_weekly() or {}
        print(f"[dashboard] COMEX做市商周净: status={comex_issue_stop.get('status')} "
              f"as_of={comex_issue_stop.get('as_of')} gold={len(comex_issue_stop.get('gold',[]))}周 "
              f"silver={len(comex_issue_stop.get('silver',[]))}周")
    except Exception as e:
        print(f"[dashboard] COMEX做市商周净 跳过: {e}")

    # ── BIS 国际清算银行报告(Quarterly Review 季度综述) ──
    bis_latest = None
    bis_all = []
    try:
        from src import bis_reports as bisr
        added, _store = bisr.sync_quarterly(5)   # 幂等: 发现最新几季 Quarterly, 不覆盖已有摘要
        bis_latest = bisr.latest_report()
        bis_all = bisr.all_reports() or []
        _bn = len((bis_latest or {}).get("summary", []))
        _bok = len([r for r in bis_all if r.get("summary_status") == "ok" and r.get("summary")])
        print(f"[dashboard] BIS: 新增{added}份, 最新={(bis_latest or {}).get('date','?')} 摘要{_bn}条 "
              f"| 可切换季度={_bok}期 {[r.get('date') for r in bis_all if r.get('summary_status')=='ok'][:4]}")
        _bp = bisr.build_standalone_page()   # 生成独立页 docs/bis/index.html
        print(f"[dashboard] BIS 独立页: {_bp}")
    except Exception as e:
        print(f"[dashboard] BIS 跳过: {e}")

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
    # ── 基差套利去杠杆预警(SOFR倒挂 + Carry空间 + 波动触发, 美债/日债) ──
    basis_trade = {}
    try:
        basis_trade = ed.fetch_basis_trade_monitor(years=2) or {}
        _bl = basis_trade.get("lights", {})
        print(f"[dashboard] 基差套利预警: status={basis_trade.get('status')} asof={basis_trade.get('asof')} "
              f"funding={_bl.get('funding')} carry={_bl.get('carry')} vol={_bl.get('vol')} "
              f"SOFR-IORB={_bl.get('sofr_iorb_gap_bp')}bp min_carry={_bl.get('min_carry_bp')}bp")
    except Exception as e:
        print(f"[dashboard] 基差套利预警 跳过: {e}")
    # ── COMEX & 上海贵金属库存 + GLD/SLV ETF 资金流(来源: comex-inventory-charts 公开数据) ──
    comex_inventory = {}
    try:
        comex_inventory = ed.fetch_comex_inventory() or {}
        _ci = comex_inventory
        print(f"[dashboard] COMEX/上海库存+ETF: status={_ci.get('status')} asof={_ci.get('as_of')} "
              f"panels={list(_ci.get('panels',{}).keys())} flows={list(_ci.get('flows',{}).keys())}")
    except Exception as e:
        print(f"[dashboard] COMEX/上海库存+ETF 跳过: {e}")
    # ── 世界前十经济体 政府债务/GDP (IMF WEO 官方, 年度) ──
    debt_gdp = {}
    try:
        debt_gdp = ed.fetch_debt_to_gdp() or {}
        _ok = [c for c in debt_gdp.get("countries", []) if c.get("status") == "ok"]
        print(f"[dashboard] 债务/GDP: status={debt_gdp.get('status')} "
              f"实绩年={debt_gdp.get('as_of_year')} 国家={len(_ok)}/10")
    except Exception as e:
        print(f"[dashboard] 债务/GDP 跳过: {e}")
    # ── 美国分评级公司债: 日频收益率/OAS + 季频真实未偿额 ──
    corp_credit = {}
    try:
        corp_credit = ed.fetch_corporate_credit() or {}
        _rk = [r for r in corp_credit.get("ratings", []) if r.get("status") == "ok"]
        _ou = [o for o in corp_credit.get("outstanding", []) if o.get("status") == "ok"]
        print(f"[dashboard] 公司债: status={corp_credit.get('status')} "
              f"as_of={corp_credit.get('as_of')} 评级={len(_rk)}/7 未偿额={len(_ou)}/2")
    except Exception as e:
        print(f"[dashboard] 公司债 跳过: {e}")
    cips = {}
    try:
        cips = ed.fetch_cips() or {}
        print(f"[dashboard] CIPS: status={cips.get('status')} "
              f"as_of={cips.get('as_of')} 月度={len(cips.get('monthly', []))} "
              f"(官方{cips.get('official_months', 0)}+回补{cips.get('third_months', 0)}) "
              f"年度={len(cips.get('annual', []))}")
    except Exception as e:
        print(f"[dashboard] CIPS 跳过: {e}")
    ai_fcf, ai_credit = {}, {}
    try:
        ai_fcf = ed.fetch_ai_fcf() or {}
        print(f"[dashboard] AI FCF: status={ai_fcf.get('status')} "
              f"as_of={ai_fcf.get('as_of')} "
              f"覆盖={ai_fcf.get('ok_count')}/{ai_fcf.get('total_count')}")
    except Exception as e:
        print(f"[dashboard] AI FCF 跳过: {e}")
    try:
        ai_credit = ed.fetch_ai_credit() or {}
        print(f"[dashboard] AI 信用: status={ai_credit.get('status')} "
              f"as_of={ai_credit.get('as_of')} "
              f"杠杆={ai_credit.get('lev_n')}/{ai_credit.get('total')} "
              f"利息保障={ai_credit.get('cov_n')}/{ai_credit.get('total')}")
    except Exception as e:
        print(f"[dashboard] AI 信用 跳过: {e}")
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
        kol_history=kol_history,
        liquidity=liquidity, cb_balance=cb_balance, custody=custody,
        auctions=auctions, money_supply=money_supply, m2_history=m2_history,
        country_ust=country_ust,
        credit_impulse=credit_impulse,
        custody_accel=custody_accel,
        stress_panels=stress_panels,
        ofr_fsi=ofr_fsi,
        basis_trade=basis_trade,
        comex_inventory=comex_inventory,
        debt_gdp=debt_gdp,
        corp_credit=corp_credit,
        cips=cips,
        ai_fcf=ai_fcf,
        ai_credit=ai_credit,
        maturing_treasury=maturing_treasury,
        oil_inventory=oil_inventory,
        us_jp_yields=us_jp_yields,
        nikkei225=nikkei225,
        foreign_flow=foreign_flow,
        iip_four=iip_four,
        fiscal_news=fiscal_news,
        hf_leverage=hf_leverage,
        bis_gold_swaps=bis_gold_swaps,
        market_breadth=market_breadth,
        ad_line_real=ad_line_real,
        gold_premium=gold_premium,
        silver_imports=silver_imports,
        silver_bank_positions=silver_bank_positions,
        comex_silver_issues_ref=comex_silver_issues_ref,
        gold_exports=gold_exports,
        us_yield_century=us_yield_century,
        comex_issue_stop=comex_issue_stop,
        comex_firms_top10=comex_firms_top10,
        bis_latest=bis_latest,
        bis_all=bis_all,
        fiscal_budget=fiscal_budget,
    )
    print(f"[dashboard] 生成: {out}")
    return out


if __name__ == "__main__":
    main()
