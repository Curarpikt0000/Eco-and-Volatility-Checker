"""dashboard.py — 生成莫兰迪配色的宏观风险扫描 dashboard (单文件 HTML)。

借鉴 KOL dashboard 的 format：卡片布局 + 红绿灯信号 + 雷达图分组 + 置顶信号 banner。
配色改为莫兰迪色系(低饱和、灰调、柔和)。
六部分报告：仪表盘表格 / 警报统计 / 逐条解读 / 短中长结论 / 卖出触发追踪 / 今日焦点。

雷达图：短/中/长三组指标归一化到 0-100 风险刻度(越大越危险)。
"""
import sys, os, json, datetime, html, re
sys.path.insert(0, os.path.dirname(__file__))
import config as c
import signals

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")
os.makedirs(OUT_DIR, exist_ok=True)


def _esc(s):
    """HTML 转义外部数据(KOL评论/政要资产名/API字段/OCR文本)后再拼进 f-string。
    防公开 dashboard 的 HTML 注入。None→空串; 非字符串先转 str。"""
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


# ── 数据新鲜度徽章 ────────────────────────────────────────────
# ★铁律配套设施: 低频源(季度/月度)天然滞后, 但页头写"每日更新"会让读者误以为
#   每个数字都是今天的。此处按各源的【自然更新频率】给出容忍阈值, 超阈值才标徽章:
#     绿(不显示) = 正常;  🟡 滞后N天 = 超过 1x 周期;  🔴 疑似断源 = 超过 2x 周期。
#   徽章只描述"数据有多旧", 绝不修改/伪造数据本身。
_FRESH_TOL = {
    "daily": 5,        # 日频(含周末+假日缓冲)
    "weekly": 12,      # 周频
    "biweekly": 25,    # 双周(如 CFTC COT)
    "monthly": 50,     # 月频
    "tic": 75,         # TIC 月频但发布滞后约 45 天
    "quarterly": 135,  # 季频
    # ★2026-08-21: BIS credit-to-GDP(FRED QUSPAM770A/QCNPAM770A) 虽是季度序列,
    #   但 BIS 汇编+FRED 转载的实际发布延迟长达 9-10 个月(已实测: 今日 2026-08-21,
    #   官方最新一期即 2025-10-01, 抓取链路正常)。套用 quarterly=135 会恒定误报红标,
    #   属"阈值设错"而非"数据陈旧" —— 与 §8.1 的存档表陷阱相反, 此处应改阈值不是改数据源。
    "bis_quarterly": 330,
    "semiannual": 250,  # 半年频(如 BIS)
    "imf_weo": 260,    # IMF WEO 一年发布两次(4月/10月), 且数据本身是年度值
    "cips": 75,        # CIPS 月度业务统计, 官方通常次月中下旬发布(留足缓冲)
    "annual_report": 500,  # 年报(10-K/20-F): 一年一更, 叠加最长约4个月申报期
}


def _stale_badge(as_of, freq="daily", label=None, known_reason=False):
    """按数据源自然频率生成滞后徽章。as_of 可为 'YYYY-MM-DD' 或 'YYYY-MM'。
    新鲜 → 返回空串(不干扰版面); 滞后 → 🟡; 严重滞后(>2x) → 🔴。
    known_reason=True 表示滞后原因已查明并在图上另行说明(如口径限制),
    此时不再提示"请核对官方"(否则误导读者以为抓取坏了)。"""
    if not as_of:
        return ""
    s = str(as_of)[:10]
    try:
        if len(s) == 7:            # YYYY-MM → 视为当月月末
            y, m = int(s[:4]), int(s[5:7])
            nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
            d0 = datetime.date(nm_y, nm_m, 1) - datetime.timedelta(days=1)
        else:
            d0 = datetime.date.fromisoformat(s)
    except Exception:
        return ""
    days = (datetime.date.today() - d0).days
    tol = _FRESH_TOL.get(freq, 5)
    if days <= tol:
        return ""
    sev = "red" if days > tol * 2 else "amber"
    icon = "🔴" if sev == "red" else "🟡"
    txt = f"{icon} 数据滞后 {days} 天"
    if sev == "red":
        # ★2026-08-21 更正: 此处原注释断言"TIC 官方本身未出新月, 抓取链路完好" —— **是错的**。
        #   实测 mfhhis01.txt 只是**历史存档表**(内容止于上一年年末), 当年月度在 slt_table5,
        #   官方 2026-08-17 已发 2026-06。教训: 红标超阈值时**先去官网核实最新一期**,
        #   绝不假设"源就是这么慢"(详见 ChaoWiki frontend/data-dashboard-publishing §8.1)。
        if known_reason:
            txt += "（原因见下方说明）"
        else:
            txt += "（远超常规更新周期，请核对官方是否已发布新值）"
    if label:
        txt = f"{label} {txt}"
    return f'<span class="stale-badge sb-{sev}" title="最新数据日期 {_esc(s)}，距今 {days} 天；该源自然更新频率={freq}">{txt}</span>'


# ── 数据源代码 → 官方链接映射 ──────────────────────────────────
# 把 source 字符串里的裸指标代码(FRED series / OFR / TIC 等)渲染成可点击超链接，
# 点击直达该指标的官方源页面，便于核实。一处逻辑，全 dashboard 复用。
# FRED series 统一跳 https://fred.stlouisfed.org/series/<ID>；其它源各自官方页。
_SRC_LINK_SPECIAL = {
    # 非 FRED、或需要专门落地页的代码/关键词 → (显示锚文本正则, URL)
    "OFR FSI": "https://www.financialresearch.gov/financial-stress-index/",
    "Office of Financial Research": "https://www.financialresearch.gov/financial-stress-index/",
    "^MOVE": "https://finance.yahoo.com/quote/%5EMOVE/",
    "Yahoo Finance": "https://finance.yahoo.com/quote/%5EMOVE/",
    "TIC": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
    "fiscaldata.treasury.gov": "https://fiscaldata.treasury.gov/",
}
# FRED series ID：2+ 位大写字母/数字组合(如 DGS10, BAMLH0A0HYM2, THREEFYTP10, T10Y2Y, WMTSECL1)
_FRED_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")
# 已知的 FRED series 白名单(避免误伤普通大写词如 US/JP/MS/OAS/IG/BofA)
_FRED_IDS = {
    "DGS10", "DGS2", "T10Y2Y", "THREEFYTP10", "BAMLC0A0CM", "BAMLH0A0HYM2",
    "WMTSECL1", "DTWEXBGS", "VIXCLS", "BAMLH0A0HYM2EY", "DFII10", "T10YIE",
    "WALCL", "WRESBAL", "RRPONTSYD", "WTREGEN", "QBPBSTAS",
}


def _fred_link(sid):
    return f'https://fred.stlouisfed.org/series/{sid}'


def _linkify_sources(text):
    """把 source 文本里的指标代码替换成可点击超链接(已含 HTML 转义)。
    - 已知 FRED series ID → fred.stlouisfed.org/series/<ID>
    - OFR/TIC/yfinance 等特殊源 → 各自官方页
    None→空串。链接 target=_blank，莫兰迪浅色下划线样式(.src-lnk)。"""
    if text is None:
        return ""
    esc = html.escape(str(text), quote=True)
    # 1) 特殊关键词(先处理，避免被 FRED 正则误吃)
    for kw, url in _SRC_LINK_SPECIAL.items():
        kw_esc = html.escape(kw, quote=True)
        if kw_esc in esc and f'>{kw_esc}<' not in esc:
            esc = esc.replace(
                kw_esc,
                f'<a class="src-lnk" href="{url}" target="_blank" rel="noopener">{kw_esc}</a>',
                1,
            )
    # 2) FRED series ID(白名单内才转，避免误伤普通大写缩写)
    def _repl(m):
        sid = m.group(1)
        if sid in _FRED_IDS:
            return (f'<a class="src-lnk" href="{_fred_link(sid)}" '
                    f'target="_blank" rel="noopener">{sid}</a>')
        return sid
    esc = _FRED_ID_RE.sub(_repl, esc)
    return esc


# 每个指标"如何看"——交易员视角的一句话解读法
HOW_TO_READ = {
    "vix": "<b>VIX=Volatility Index(CBOE 波动率指数)</b>，衡量S&P500未来30天预期波动。恐慌温度计。<13 市场自满(危险)，20-25 转紧张，>25 恐慌抛售。飙升=避险信号。",
    "fear_greed": "情绪钟摆。>75 极度贪婪(该减)，<25 极度恐惧(可贪)。从高位回落是顶部确认。",
    "aaii_bull_bear": "散户情绪。多空差 >30% = 散户太乐观(反向看空)，<-30% = 过度悲观(反向看多)。",
    "put_call": "对冲需求。越低=越少人买保险=越自满。<0.45 极度乐观(危险)，高=恐慌(可能见底)。",
    "bofa_fms_cash": "全球基金经理现金占比(BofA月度调查)。替NAAIM。现金<4%=满仓贪婪(反向卖出)，>5%=避险恐慌(反向买入)。极值反向信号。",
    "margin_debt": "借钱炒股总量。持续攀升=杠杆堆积；连续 3 月下降=去杠杆开始(历史顶部信号)。",
    "margin_gdp": "杠杆占经济比重。>3% 历史偏高，>3.5% 极端。回落往往伴随市场调整。",
    "ipo_count": "发行热度。IPO 井喷=市场情绪顶部特征(供给放量套现)。骤降=风险偏好收缩。",
    "insider": "内部人用脚投票。<0.17 内部人只卖不买(看空)，>1 大举买入(看多)。最聪明的钱。",
    "bofa_bull_bear": "华尔街情绪综合指标。>8 极度贪婪(卖出信号)，<2 极度恐慌(买入信号)。",
    "hy_oas": "信用市场压力。利差扩张=风险偏好收缩、违约担忧上升。>4.5% 信用警报。",
    "ad_line": "<b>A/D=Advance/Decline(上涨/下跌家数)</b>。腾落线=每日累加(NYSE上涨家数−下跌家数)的曲线，衡量市场广度。S&P创新高但腾落线不创新高=<b>顶背离</b>(指数只靠少数权重股撑，多数股走弱，危险)；同步创新高=健康。",
    "buffett": "总市值/GDP。巴菲特最爱的估值尺。>150% 显著高估，>180% 极端泡沫区。",
    "cape": "<b>CAPE=Cyclically Adjusted PE(席勒周期调整市盈率，又称PE10)</b>=股价/过去10年通胀调整后平均EPS，平滑经济周期。>30 历史高估，>35 逼近 2000/2021 泡沫峰值。均值回归压力大。",
    "yield_curve": "10Y-2Y 利差。倒挂(<0)历史预示衰退；由倒挂转正常是衰退临近的最后信号。",
    "lei": "<b>LEI=Leading Economic Index(Conference Board 领先经济指数)</b>，由10项领先分量合成。6个月变化率 <-4% 强烈预示衰退。领先实体经济约 7 个月。",
    "aaii_alloc": "家庭股票仓位。>70% 是历史仓位极值(2000年峰值区)，反向看空信号。",
    "sofr_iorb": "货币市场压力计。<b>SOFR=Secured Overnight Financing Rate(担保隔夜融资利率)</b>−<b>IORB=Interest on Reserve Balances(准备金余额利率)</b>。≤0 正常🟢；7–17bps 心绞痛🟡(准备金趋紧)；>17bps 心肌梗塞🔴(钱荒/回购危机,如2019年9月)。是美联储缩表触底、流动性拐点的最灵敏信号。",
}



def risk_score(ind, value):
    """把指标值归一化到 0-100 风险分(越高越危险)。用于雷达图。"""
    if value is None:
        return None
    warn, trig, d = ind.get("warn"), ind.get("trigger"), ind.get("direction")
    if warn is None or trig is None:
        return None
    if d == "high_bad":
        if value <= warn:
            return max(0, min(50, 50 * value / warn)) if warn else 25
        # warn~trig -> 50~100
        span = (trig - warn) or 1
        return min(100, 50 + 50 * (value - warn) / span)
    else:  # low_bad: 值越低越危险
        if value >= warn:
            return max(0, min(50, 50 * (2 * warn - value) / warn)) if warn else 25
        span = (warn - trig) or 1
        return min(100, 50 + 50 * (warn - value) / span)


def fmt_val(ind, r):
    v = r.get("value")
    if v is None:
        return "—"
    # 布尔型(A/D 背离)
    if ind.get("unit") == "布尔" or isinstance(v, bool):
        return "顶背离" if v else "无背离"
    u = ind.get("unit", "")
    if u in ("%",):
        return f"{v}%"
    if u == "点" or u == "倍" or u == "指数":
        return f"{v}"
    return f"{v}"


def load_history(snap_dir, key, days=21):
    """从周快照读某指标最近 N 天历史。返回 [(date, value),...] 升序。"""
    import glob
    out = []
    for f in sorted(glob.glob(os.path.join(snap_dir, "*.json"))):
        try:
            d = json.load(open(f))
            v = d.get("results", {}).get(key, {}).get("value")
            if v is not None and not isinstance(v, bool):
                out.append((os.path.basename(f)[:-5], float(v)))
        except Exception:
            continue
    return out[-days:] if out else out


def sparkline_svg(points, direction="high_bad", w=140, h=36, unit=""):
    """生成 mini 折线 SVG。points: [(date,val),...]。莫兰迪色。
    ★带 tooltip: 每点覆盖一条透明全高 hit-band(rect), 复用全站 data-tip 事件委托机制。
      用 band 而非 circle, 因该 SVG 用 preserveAspectRatio="none" 横向拉伸, 圆会变椭圆且难命中。"""
    vals = [v for _, v in points]
    if len(vals) < 2:
        return '<span class="spark-na">数据不足</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pad = 3
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    # 趋势颜色：最后 vs 前值
    rising = vals[-1] > vals[0]
    bad = (rising if direction == "high_bad" else not rising)
    color = "#c08a7d" if bad else "#9aab97"  # 陶土红=变差 / 鼠尾草绿=变好
    dot_x, dot_y = pts[-1].split(",")
    fill = "rgba(192,138,125,0.10)" if bad else "rgba(154,171,151,0.12)"
    area = f"{pad},{h-pad} " + " ".join(pts) + f" {w-pad},{h-pad}"
    # tooltip hit-band: 每个数据点一条透明竖条, 宽度=点间距
    bw = (w - 2 * pad) / (n - 1)
    _fmt = "{:,.2f}".format
    hits = "".join(
        f'<rect x="{max(0, pad + i * bw - bw / 2):.1f}" y="0" width="{bw:.1f}" height="{h}" '
        f'fill="transparent" data-tip="{_esc(str(points[i][0])[:10])}||{_fmt(vals[i])}{_esc(unit)}"/>'
        for i in range(n))
    return (f'<svg viewBox="0 0 {w} {h}" class="spark" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
            f'<circle cx="{dot_x}" cy="{dot_y}" r="2.8" fill="{color}"/>'
            f'{hits}</svg>')


def trend_arrow(points, direction="high_bad"):
    """返回 (箭头符号, css类)。基于最近 2 周首尾比较。"""
    vals = [v for _, v in points]
    if len(vals) < 2:
        return "→", "flat"
    delta = vals[-1] - vals[0]
    if abs(delta) < 1e-9:
        return "→", "flat"
    rising = delta > 0
    bad = (rising if direction == "high_bad" else not rising)
    arrow = "↑" if rising else "↓"
    return arrow, ("bad" if bad else "good")


def threshold_text(ind):
    """人类可读的红绿黄灯阈值说明。"""
    warn, trig, d = ind.get("warn"), ind.get("trigger"), ind.get("direction")
    if warn is None or trig is None:
        return "无数值阈值（定性判断）"
    u = ind.get("unit", "")
    us = "%" if u == "%" else ""
    if d == "high_bad":
        return f"🟢<{warn}{us} · 🟡{warn}–{trig}{us} · 🔴≥{trig}{us}"
    else:  # low_bad
        return f"🟢>{warn}{us} · 🟡{trig}–{warn}{us} · 🔴≤{trig}{us}"


def generate(snap, checks, hit, gstats, overall, ai_reads=None, ai_conclusions=None,
             daily_notes=None, kol_changes=None, liquidity=None, cb_balance=None,
             holdings=None, custody=None, auctions=None, money_supply=None, m2_history=None,
             country_ust=None, kol_views=None, credit_impulse=None, custody_accel=None,
             stress_panels=None, ofr_fsi=None, maturing_treasury=None, bis_latest=None,
             oil_inventory=None, us_jp_yields=None, nikkei225=None, foreign_flow=None,
             iip_four=None, fiscal_news=None, hf_leverage=None, bis_gold_swaps=None,
             market_breadth=None, silver_bank_positions=None, comex_silver_issues_ref=None,
             gold_exports=None, us_yield_century=None, comex_issue_stop=None,
             ad_line_real=None, gold_premium=None, silver_imports=None, fiscal_budget=None,
             basis_trade=None, comex_inventory=None, debt_gdp=None,
             corp_credit=None, cips=None, ai_fcf=None, ai_credit=None,
             kol_history=None):
    """snap: run.py 的快照; checks/hit/gstats/overall: signals 结果。
    ai_reads: {key: 通用解读}(第3部分); ai_conclusions: 短中长结论(第4部分)。
    daily_notes: {key: 当日一句话短评}(每卡片底部,AI生成)。
    kol_changes: [{kol,sector,prev_dir,new_dir,date,comments,targets},...] KOL状态变化。
    liquidity: Economic Dashboard 流动性关键点 dict。
    cb_balance: {US/JP/CN: 央行资产负债表 dict}(左资产右负债+WoW)。
    holdings: {date, institutions:[...]} 机构13F持仓+变动(+可含Trump)。
    返回 HTML 文件路径。"""
    results = snap["results"]
    cot = snap.get("cot", {})
    date_str = snap["date"]
    ai_reads = ai_reads or {}
    daily_notes = daily_notes or {}

    # ★2026-08-21 修复(Chao 报: 弹层点开显示"暂无已归档的历史观点记录"):
    # cron 走的是内联 `python -c "...dashboard.build(...)"`, 并未传 kol_history,
    # 导致内嵌 payload 恒为 {} —— 卡片有当日观点、弹层却空。
    # 这里做兜底自动加载: 调用方没传就自己从磁盘快照合并, 保证两个入口(build_dashboard.py
    # 与 cron 内联命令)行为一致。失败只降级为空, 绝不阻断整页构建。
    if not kol_history:
        try:
            from . import external_data as _ed
        except ImportError:
            import external_data as _ed
        try:
            kol_history = _ed.kol_full_history() or {}
            _n = sum(len(v) for v in kol_history.values())
            print(f"[dashboard] KOL 历史观点(自动加载): {len(kol_history)} 人 / {_n} 条")
        except Exception as e:
            print(f"[dashboard] KOL 历史观点自动加载失败, 弹层将无历史: {e}")
            kol_history = {}
    kol_changes = kol_changes or []
    liquidity = liquidity or {}
    cb_balance = cb_balance or {}
    holdings = holdings or {}
    custody = custody or {}
    # 综合结论：优先用 agent 生成，否则用规则兜底
    ai_conclusions = ai_conclusions or _rule_conclusions(results, checks, hit, cot)

    # ── 雷达图数据 ──
    radar = {}
    for g in ("short", "mid", "long"):
        labels, scores = [], []
        for ind in c.indicators_by_group(g):
            rs = risk_score(ind, results.get(ind["key"], {}).get("value"))
            if rs is not None:
                labels.append(ind["name_zh"])
                scores.append(round(rs, 1))
        radar[g] = {"labels": labels, "scores": scores}

    # ── 指标卡片网格(交易员屏风格：值+灯+threshold+2周折线+趋势+如何看) ──
    def metric_cards(g):
        html = ""
        for ind in c.indicators_by_group(g):
            key = ind["key"]
            r = results.get(key, {})
            lt = signals.light(ind, r.get("value"))
            cls = _sig_cls(lt)
            hist = load_history(SNAP_DIR, key, days=28)
            spark = sparkline_svg(hist, ind.get("direction", "high_bad"),
                                  unit=(" " + ind["unit"]) if ind.get("unit") and ind.get("unit") != "布尔" else "")
            arrow, acls = trend_arrow(hist, ind.get("direction", "high_bad"))
            st = r.get("status", "")
            st_badge = "" if st == "ok" else f'<span class="stwarn">{st}</span>'
            # 自定义状态标签(如 SOFR-IORB: 正常/心绞痛/心肌梗塞)
            slabels = ind.get("status_labels")
            slabel_html = ""
            if slabels and r.get("value") is not None:
                _lmap = {"g": "green", "y": "yellow", "r": "red"}
                _txt = slabels.get(_lmap.get(cls, ""), "")
                if _txt:
                    slabel_html = f'<span class="mc-slabel mc-slabel-{cls}">{_txt}</span>'
            how = HOW_TO_READ.get(key, ind.get("note", ""))
            note = daily_notes.get(key, "")  # 当日一句话短评
            note_html = f'<div class="mc-note">📌 {note}</div>' if note else ""
            # 2周变化
            chg = ""
            if len(hist) >= 2:
                d0, d1 = hist[0][1], hist[-1][1]
                diff = d1 - d0
                chg = f'<span class="chg chg-{acls}">{arrow} {"+" if diff>=0 else ""}{round(diff,2)}</span>'
            html += f"""<div class="mcard mcard-{cls}">
              <div class="mc-top">
                <div class="mc-name">{ind['name_zh']}<span class="mc-en">{ind['name_en']}</span></div>
                <span class="mc-dot dot-{cls}"></span>
              </div>
              <div class="mc-val">{fmt_val(ind, r)} {chg}{st_badge}{slabel_html}</div>
              <div class="mc-thr">{threshold_text(ind)}</div>
              <div class="mc-spark">{spark}<span class="mc-spark-lbl">近4周</span></div>
              {note_html}
              <div class="mc-how"><b>如何看：</b>{how}</div>
            </div>"""
        return html

    # ── 仪表盘表格行(保留,备用) ──
    def table_rows(g):
        rows = ""
        for ind in c.indicators_by_group(g):
            r = results.get(ind["key"], {})
            lt = signals.light(ind, r.get("value"))
            warn, trig = ind.get("warn"), ind.get("trigger")
            thr = f"{warn}/{trig}" if warn is not None else "—"
            asof = r.get("as_of") or "—"
            st = r.get("status", "")
            st_badge = "" if st == "ok" else f'<span class="stwarn">{st}</span>'
            rows += f"""<tr>
              <td class="ind-name">{ind['name_zh']}<span class="ind-en">{ind['name_en']}</span></td>
              <td class="ind-val">{fmt_val(ind, r)} {st_badge}</td>
              <td class="ind-date">{asof}</td>
              <td class="ind-thr">{thr}</td>
              <td class="ind-sig sig-{_sig_cls(lt)}"><span class="dot dot-{_sig_cls(lt)}"></span></td>
            </tr>"""
        return rows

    # ── 警报统计卡片 ──
    def stat_card(g):
        safe, total = gstats[g]
        return f'<div class="stat-card sc-{g}"><div class="sc-label">{c.GROUP_LABEL[g]}</div><div class="sc-num">{safe} / {total}</div><div class="sc-sub">未警报</div></div>'

    # ── 逐条解读 ──
    def interp_block():
        html = ""
        for g in ("short", "mid", "long"):
            html += f'<h4 class="interp-group">{c.GROUP_LABEL[g]}</h4>'
            for ind in c.indicators_by_group(g):
                r = results.get(ind["key"], {})
                lt = signals.light(ind, r.get("value"))
                read = ai_reads.get(ind["key"]) or ind.get("note", "")
                html += f'<div class="interp-item"><span class="ii-sig">{lt}</span><b>{ind["name_zh"]}</b> <span class="ii-val">{fmt_val(ind, r)}</span><p>{read}</p></div>'
        return html

    # ── 卖出触发表 ──
    def trigger_rows():
        rows = ""
        label = {"✅": "已触发", "⚠️": "接近", "❌": "未触发"}
        for cond, thr, desc, st in checks:
            cls = {"✅": "hit", "⚠️": "near", "❌": "no"}.get(st, "no")
            rows += f'<tr class="tr-{cls}"><td>{cond}</td><td>{thr}</td><td>{desc}</td><td class="tr-state"><span class="tr-badge trb-{cls}">{label.get(st, st)}</span></td></tr>'
        return rows

    # ── COT 卡片 ──
    def cot_cards():
        html = ""
        for metal in ("gold", "silver"):
            r = cot.get(metal)
            if not r:
                continue
            surge = "⚠️ 突增" if r.get("comm_surge") else "正常"
            wow = r.get("comm_net_wow")
            wow_s = f'{"+" if (wow or 0) >= 0 else ""}{wow:,}' if wow is not None else "—"
            arrow = "↑" if (wow or 0) > 0 else ("↓" if (wow or 0) < 0 else "→")
            name = "🥇 黄金" if metal == "gold" else "🥈 白银"
            html += f"""<div class="cot-card">
              <div class="cot-head">{name} <span class="cot-date">COT {r['as_of']}</span> <span class="cot-surge {'surge-on' if r.get('comm_surge') else ''}">{surge}</span></div>
              <div class="cot-grid">
                <div><span class="cl">Commercial 净持仓</span><span class="cv">{r['comm_net']:,}</span></div>
                <div><span class="cl">周环比 {arrow}</span><span class="cv">{wow_s}</span></div>
                <div><span class="cl">Comm 多头</span><span class="cv">{r['comm_long']:,}</span></div>
                <div><span class="cl">Comm 空头</span><span class="cv">{r['comm_short']:,}</span></div>
                <div><span class="cl">未平仓 (OI)</span><span class="cv">{r['open_interest']:,}</span></div>
                <div><span class="cl">大户投机净</span><span class="cv">{r.get('noncomm_net',0):,}</span></div>
              </div>
            </div>"""
        return html

    overall_cls = {"🔴 减仓": "danger", "🟡 警戒": "warn", "🟢 平静": "calm"}.get(overall, "calm")
    generated = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    html = _TEMPLATE.format(
        date=date_str, generated=generated,
        overall=overall, overall_cls=overall_cls,
        hit=hit, sell_thr=c.SELL_START_THRESHOLD,
        sell_verdict=("⚠️ 已达分批卖出阈值 (≥3)" if hit >= c.SELL_START_THRESHOLD else "未达分批卖出阈值 (需 ≥3)"),
        stat_short=stat_card("short"), stat_mid=stat_card("mid"), stat_long=stat_card("long"),
        rows_short=table_rows("short"), rows_mid=table_rows("mid"), rows_long=table_rows("long"),
        cards_short=metric_cards("short"), cards_mid=metric_cards("mid"), cards_long=metric_cards("long"),
        radar_json=json.dumps(radar, ensure_ascii=False),
        interp=interp_block(), trigger_rows=trigger_rows(), cot_cards=cot_cards(),
        focus=_focus_text(checks, results, cot),
        concl_short=ai_conclusions.get("short", ""),
        concl_mid=ai_conclusions.get("mid", ""),
        concl_long=ai_conclusions.get("long", ""),
        kol_changes=_kol_changes_html(kol_changes),
        kol_views=_kol_views_html(kol_views),
        cycle_kol=_cycle_kol_html(kol_views, kol_history),
        kol_history_json=_kol_history_payload(kol_history),
        liquidity=_liquidity_html(liquidity),
        cb_balance=_cb_balance_html(cb_balance),
        money_supply=_money_supply_html(money_supply),
        m2_history=_m2_history_html(m2_history),
        custody=_custody_html(custody),
        custody_accel=_custody_accel_html(custody_accel),
        maturing_treasury=_maturing_treasury_html(maturing_treasury),
        oil_inventory=_oil_inventory_html(oil_inventory),
        yield_curves=_yield_curves_html(us_jp_yields),
        nikkei_flow=_nikkei_flow_html(nikkei225, foreign_flow),
        iip_four=_iip_html(iip_four),
        fiscal_news=_fiscal_news_html(fiscal_news),
        hf_leverage=_hf_leverage_html(hf_leverage),
        bis_gold_swaps=_bis_gold_swaps_html(bis_gold_swaps),
        market_breadth=_market_breadth_html(market_breadth),
        ad_line_real=_ad_line_html(ad_line_real),
        gold_premium=_gold_premium_html(gold_premium),
        silver_imports=_silver_imports_html(silver_imports),
        silver_bank_positions=_silver_bank_positions_html(silver_bank_positions),
        comex_silver_issues_ref=_comex_silver_issues_ref_html(comex_silver_issues_ref),
        gold_exports=_gold_exports_html(gold_exports),
        us_yield_century=_us_yield_century_html(us_yield_century),
        comex_issue_stop=_comex_issue_stop_html(comex_issue_stop),
        fiscal_budget=_fiscal_budget_html(fiscal_budget),
        bis_section=_bis_section_html(bis_latest, "https://curarpikt0000.github.io/Eco-and-Volatility-Checker/bis/"),
        country_ust=_country_ust_html(country_ust),
        credit_impulse=_credit_impulse_html(credit_impulse),
        stress_panels=_stress_panels_html(stress_panels, ofr_fsi),
        basis_trade=_basis_trade_html(basis_trade),
        comex_inventory=_comex_inventory_html(comex_inventory),
        debt_gdp=_debt_gdp_html(debt_gdp),
        corp_credit=_corp_credit_html(corp_credit),
        cips=_cips_html(cips),
        ai_fcf=_ai_fcf_html(ai_fcf, ai_credit),
        auctions=_auctions_html(auctions),
        holdings=_holdings_html(holdings),
    )
    path = os.path.join(OUT_DIR, "index.html")
    open(path, "w", encoding="utf-8").write(html)
    # 也存一份带日期的历史
    open(os.path.join(OUT_DIR, f"scan-{date_str}.html"), "w", encoding="utf-8").write(html)
    # 同步输出到 docs/ 供 GitHub Pages 托管
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8").write(html)
    return path


def _sig_cls(lt):
    return {"🟢": "g", "🟡": "y", "🔴": "r", "⚪": "n"}.get(lt, "n")


_CYCLE_SECTOR = "周期与术数预测"


def _cycle_kol_html(kol_views, kol_history=None):
    """★周期与术数预测派 专属 section。
    把 sector=周期与术数预测 的 KOL 从常规板块中单独拎出来, 按【更新频率】分成
    「每日/每周预测」与「月度·不定期预测」两块, 便于按节奏对账。

    数据全部来自名册(data/kol_registry.json)与当日快照; 无观点的人显示"待采集",
    绝不编造方向或言论。
    """
    import os as _os
    import json as _json
    # 1) 名册: 取出该 sector 的全部成员及其元信息
    reg = []
    try:
        p = _os.path.join(_os.path.dirname(__file__), "..", "data", "kol_registry.json")
        with open(p, encoding="utf-8") as f:
            for k in (_json.load(f).get("kols") or []):
                if not k.get("active"):
                    continue
                sec = (k.get("sector") or "").strip()
                if sec in ("Cycles & Esoteric Forecasting", _CYCLE_SECTOR):
                    reg.append(k)
    except Exception:
        return ""
    if not reg:
        return ""

    # 2) 当日观点: 从 kol_views 各模块里按名字捞(该 sector 的模块 + 兜底全模块)
    views = {}
    for m in (kol_views or {}).get("modules", []):
        for v in m.get("views", []):
            nm = (v.get("kol") or "").strip()
            if nm:
                views[nm] = v

    hist = kol_history or {}

    # 3) 按更新频率分组: 高频(daily/weekly) vs 低频(biweekly/monthly/irregular)
    FREQ_LABEL = {"daily": "每日", "weekly": "每周", "biweekly": "每两周",
                  "monthly": "每月", "irregular": "不定期"}
    hi, lo = [], []
    for k in reg:
        (hi if (k.get("forecast_cadence") or "").lower() in ("daily", "weekly") else lo).append(k)
    # 组内排序: 有当日观点的排前, 再按频率(日>周>两周>月>不定期)
    _ford = {"daily": 0, "weekly": 1, "biweekly": 2, "monthly": 3, "irregular": 4}
    for grp in (hi, lo):
        grp.sort(key=lambda k: (0 if (k.get("display_name") or "").strip() in views else 1,
                                _ford.get((k.get("forecast_cadence") or "").lower(), 9),
                                k.get("display_name") or ""))

    n_view = sum(1 for k in reg if (k.get("display_name") or "").strip() in views)
    head = (
        '<div class="cyc-head">'
        f'<span class="cyc-count">{len(reg)} 位 · 周期理论 / 金融占星 / 易经术数</span>'
        f'<span class="cyc-sub">当日已采集观点 {n_view} / {len(reg)}</span>'
        '</div>'
        '<div class="cyc-note">⚠️ 本板块收录的是<b>非常规方法论</b>（长周期模型、金融占星、艾略特波浪、'
        '奇门遁甲、六爻卦象等）的市场预测者。收录只代表其预测<b>可被追踪与复盘</b>，'
        '不代表本报告认可其方法或结论。请与前述基本面/量化板块严格区分对待。</div>'
    )

    def _block(title, sub, items):
        if not items:
            return ""
        cards = ""
        for k in items:
            nm = (k.get("display_name") or "").strip()
            v = views.get(nm)
            freq = FREQ_LABEL.get((k.get("forecast_cadence") or "").lower(), "—")
            school = _esc(k.get("forecast_school") or k.get("detail_sector") or "")
            region = (k.get("forecast_region") or "").strip()
            inst = (k.get("institution") or k.get("bio") or "").strip()
            url = (k.get("source_url") or "").strip()
            focus = _esc(k.get("focus") or "")
            # 方向 / 言论: 有才显示, 没有明确标"待采集"
            if v:
                d = (v.get("direction") or "").strip() or "—"
                cls = {"强烈看多":"kv-bull2","看多":"kv-bull","分歧":"kv-mixed","中性":"kv-mixed",
                       "看空":"kv-bear","强烈看空":"kv-bear2","另类预言":"kv-mixed"}.get(d, "kv-mixed")
                body = _esc((v.get("comments") or "").strip()) or "—"
                tg = _esc((v.get("targets") or "").strip())
                dir_html = f'<span class="kol-dir {cls}">{_esc(d)}</span>'
                tg_html = f'<div class="kol-targets">🎯 {tg}</div>' if tg else ""
            else:
                dir_html = '<span class="kol-dir cyc-pending">待采集</span>'
                body = '<span class="cyc-muted">该 KOL 已入名册，下一轮每日采集后显示其最新预测。</span>'
                tg_html = ""
            link = (f'<a class="cyc-link" href="{_esc(url)}" target="_blank" rel="noopener">🔗 原始频道</a>'
                    if url.startswith("http") else "")
            nhist = len(hist.get(nm) or [])
            hint = f'<span class="cyc-hist">📚 {nhist} 条历史</span>' if nhist else ""
            rg = f'<span class="cyc-region">{_esc(region)}</span>' if region else ""
            fc = f'<div class="cyc-focus">🎯 关注：{focus}</div>' if (focus and not v) else ""
            drill = ' kol-drill" tabindex="0" role="button"' if nhist else '"'
            cards += (
                f'<div class="kol-item cyc-item{drill} data-kol="{_esc(nm)}">'
                f'<div class="kol-item-head"><span class="kol-name">{_esc(nm)}</span>{dir_html}</div>'
                f'<div class="cyc-meta">{rg}<span class="cyc-freq">{freq}更新</span>'
                f'<span class="cyc-school">{school}</span>{hint}</div>'
                f'<div class="kol-comment">{body}</div>{tg_html}{fc}'
                + (f'<div class="kol-standing">🏛 {_esc(inst)}</div>' if inst else "")
                + link + '</div>'
            )
        return (f'<div class="cyc-block"><div class="cyc-block-title">{title}'
                f'<span class="cyc-block-sub">{sub}</span></div>'
                f'<div class="kol-grid">{cards}</div></div>')

    body = _block("每日 / 每周预测", "更新节奏快，可做短周期对账", hi)
    body += _block("月度 / 不定期预测", "长周期与节气/节点式预测", lo)
    return head + body


def _kol_history_payload(kol_history):
    """把 kol_full_history() 结果压成内嵌 JSON(供前端两层展开钻取)。
    结构精简: {kol: {"s": 背景介绍, "f": 关注领域, "h": [[first,last,dir,comments,targets,source],...]}}
    数组形式而非对象, 省掉每条重复的键名(2600+ 条能省约 40% 体积)。
    无历史数据返回 '{}' —— 前端据此禁用钻取, 绝不显示假数据。"""
    if not kol_history:
        return "{}"
    meta = _kol_meta()
    out = {}
    for kol, recs in kol_history.items():
        if not recs:
            continue
        m = meta.get(kol, {})
        out[kol] = {
            "s": m.get("standing", ""),
            "f": m.get("focus", ""),
            "h": [[r.get("first_date", ""), r.get("last_date", ""),
                   r.get("direction", ""), r.get("comments", ""),
                   r.get("targets", ""), r.get("source", "")] for r in recs],
        }
    # </ 会提前闭合 <script> 标签 → 转义(XSS/断标签双重防护)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _kol_meta():
    """KOL 名册元信息(业界地位/机构声誉 + 关注领域), 供状态变化与观点全景两个板块共用。
    返回 {display_name: {"standing": institution或bio, "focus": focus}}。读不到返回 {}。"""
    out = {}
    try:
        import os as _os
        _reg_path = _os.path.join(_os.path.dirname(__file__), "..", "data", "kol_registry.json")
        _reg = json.load(open(_reg_path))
        for _k in _reg.get("kols", []):
            _nm = (_k.get("display_name") or "").strip()
            if not _nm:
                continue
            out[_nm] = {
                "standing": (_k.get("institution") or _k.get("bio") or "").strip(),
                "focus": (_k.get("focus") or "").strip(),
            }
    except Exception:
        return {}
    return out


def _kol_standing_html(meta, kol):
    """渲染 KOL 背景介绍块(业界地位 + 关注领域)。无资料返回空串, 绝不编造。"""
    m = meta.get((kol or "").strip()) or {}
    standing = m.get("standing", "")
    if not standing:
        return ""
    return f'<div class="kol-standing">🏛 {_esc(standing)}</div>'


def _kol_changes_html(kol_changes):
    """KOL 状态变化板块(模块化, 仿 13F 报告)。
    接收 kol_stance_changes_grouped() 的结果 {since,days,total,modules:[...]};
    向后兼容旧 list 结构(自动包一层"其他"模块)。
    每个 sector 一个彩色模块, 模块下列该模块转向的 KOL(主方向变化+言论+标的+日期)。"""
    # 空/无数据
    if not kol_changes:
        return '<p class="empty">本周暂无 KOL 主导方向变化（或快照尚在累积中）。</p>'
    # 兼容: 旧 list 结构 → 包成单模块
    if isinstance(kol_changes, list):
        kol_changes = {"since": "", "days": 0, "total": len(kol_changes),
                       "modules": [{"sector": "全部", "en": "", "color": "#8a8377", "changes": kol_changes}]}
    modules = kol_changes.get("modules", [])
    # ★2026-08-21 去重: 与 _kol_views_html 同理, 周期/术数派归入独立 section。
    modules = [m for m in modules if m.get("sector") != _CYCLE_SECTOR]
    _tot = sum(len(m.get("changes") or []) for m in modules)
    if not modules or _tot == 0:
        return '<p class="empty">本周暂无 KOL 主导方向变化（或快照尚在累积中）。</p>'

    # 方向 → 色 + 强弱排序(用于判断转多/转空)
    dir_rank = {"强烈看空": -2, "看空": -1, "分歧": 0, "中性": 0, "看多": 1, "强烈看多": 2}
    dir_cls = {"强烈看多": "r", "看多": "y", "分歧": "n", "中性": "n", "看空": "g", "强烈看空": "g"}

    def _shift_badge(prev_d, new_d):
        """转多(变乐观)=↑红 / 转空(变悲观)=↓绿(逆向: 看空是好的买点信号) / 平移=→。"""
        pr, nr = dir_rank.get(prev_d, 0), dir_rank.get(new_d, 0)
        if nr > pr:
            return '<span class="kol-arrow kol-up">▲ 转多</span>'
        if nr < pr:
            return '<span class="kol-arrow kol-down">▼ 转空</span>'
        return '<span class="kol-arrow kol-flat">→ 微调</span>'

    # 顶部总览
    since = kol_changes.get("since", "")
    total = kol_changes.get("total", 0)
    head = (f'<div class="kol-overview">本周 KOL 状态变化（对比基准 <b>{_esc(since)}</b>）共 '
            f'<b>{total}</b> 位 KOL 主导方向转向，涉及 <b>{len(modules)}</b> 个模块。'
            f'<span class="kol-ov-note">↑转多(变乐观) · ↓转空(变谨慎/逆向买点)</span></div>')

    html = head
    _meta = _kol_meta()
    for m in modules:
        color = m.get("color", "#8a8377")
        sector = m.get("sector", "其他")
        en = m.get("en", "")
        changes = m.get("changes", [])
        if not changes:
            continue
        cards = ""
        for ch in changes:
            pc = dir_cls.get(ch["prev_dir"], "n")
            nc = dir_cls.get(ch["new_dir"], "n")
            comment = (ch.get("comments") or "").strip()
            targets = (ch.get("targets") or "").strip()
            extra = ""
            if comment:
                extra += f'<div class="kol-cmt">{_esc(comment)}</div>'
            if targets:
                extra += f'<div class="kol-tgt">标的：{_esc(targets)}</div>'
            # Bug1 修复: 状态变化卡片补背景介绍(与"观点全景"板块口径一致, 均取名册 institution/bio)
            extra += _kol_standing_html(_meta, ch.get("kol", ""))
            cards += f"""<div class="kol-item kol-drill" data-kol="{_esc(ch['kol'])}" tabindex="0" role="button">
              <div class="kol-line"><b>{_esc(ch['kol'])}</b> {_shift_badge(ch['prev_dir'], ch['new_dir'])} <span class="kol-date">{_esc(ch['date'])}</span></div>
              <div class="kol-shift"><span class="kdir kdir-{pc}">{_esc(ch['prev_dir'])}</span> → <span class="kdir kdir-{nc}">{_esc(ch['new_dir'])}</span></div>
              {extra}
              <div class="kol-more">点击查看该 KOL 全部观点 →</div>
            </div>"""
        html += (
            f'<div class="h-module" style="border-color:{color}">'
            f'<div class="h-module-title" style="background:{color}">'
            f'<span class="h-mod-dot"></span>{_esc(sector)}<span class="h-mod-en">{_esc(en)}</span>'
            f'<span class="h-mod-n">{len(changes)} 转向</span></div>'
            f'<div class="kol-mod-inner">{cards}</div></div>'
        )
    return html


def _kol_views_html(views):
    """本周 KOL 观点板块(按模块, 每 KOL 一卡带多空方向)。
    接收 kol_weekly_views() 结果 {date,total,modules:[{sector,en,color,views:[...]}]}。
    这是'本周有意义的观点'全景(不只转向), 回答'88个KOL不可能一周没话说'。"""
    if not views or not views.get("modules") or views.get("total", 0) == 0:
        return '<p class="empty">本周暂无 KOL 观点数据（快照未就绪）。</p>'
    # 方向 → 徽章色 + 文案(看多暖/看空冷, 与转向徽章一致的语义)
    dir_badge = {
        "强烈看多": ("kv-bull2", "强烈看多"), "看多": ("kv-bull", "看多"),
        "分歧": ("kv-mixed", "分歧"), "中性": ("kv-mixed", "中性"),
        "看空": ("kv-bear", "看空"), "强烈看空": ("kv-bear2", "强烈看空"),
    }
    date = views.get("date", "")
    total = views.get("total", 0)
    modules = views["modules"]
    # ★2026-08-21 去重: 周期/术数派已有独立 section(_cycle_kol_html), 常规板块须剔除,
    #   否则同一人在页面出现两次。剔除后重算 total, 保证文案与实际卡片数一致。
    modules = [m for m in modules if m.get("sector") != _CYCLE_SECTOR]
    total = sum(len(m.get("views") or []) for m in modules)
    if not modules or total == 0:
        return '<p class="empty">本周暂无 KOL 观点数据（快照未就绪）。</p>'
    # 加载 KOL 名册的业界地位/机构声誉, 按名字匹配渲染到卡片底部(与"状态变化"板块共用同一口径)
    _meta = _kol_meta()
    head = (f'<div class="kol-overview">本周 KOL 观点全景（截至 <b>{_esc(date)}</b>）：'
            f'共 <b>{total}</b> 位 KOL 有实质观点，覆盖 <b>{len(modules)}</b> 个模块。'
            f'<span class="kol-ov-note">卡片按多空方向标色 · 强烈看多→强烈看空</span></div>')
    html = head
    for m in modules:
        color = m.get("color", "#8a8377")
        sector = m.get("sector", "其他")
        en = m.get("en", "")
        vs = m.get("views", [])
        if not vs:
            continue
        cards = ""
        for v in vs:
            bcls, btxt = dir_badge.get(v["direction"], ("kv-mixed", v["direction"] or "—"))
            comment = (v.get("comments") or "").strip()
            targets = (v.get("targets") or "").strip()
            since = (v.get("since_date") or "").strip()
            is_new = v.get("is_new")
            # 首现日期标注: 本周内新转成→🆕 新观点; 否则→自 X 日持有(旧观点延续)
            since_html = ""
            if since:
                if is_new:
                    since_html = f'<span class="kol-since kol-since-new">🆕 本周新观点</span>'
                else:
                    since_html = f'<span class="kol-since">自 {_esc(since)} 持此观点</span>'
            extra = ""
            if comment:
                extra += f'<div class="kol-cmt">{_esc(comment)}</div>'
            if targets:
                extra += f'<div class="kol-tgt">标的：{_esc(targets)}</div>'
            _standing = _kol_standing_html(_meta, v.get("kol", ""))
            if _standing:
                extra += _standing
            cards += f"""<div class="kol-item kol-drill" data-kol="{_esc(v['kol'])}" tabindex="0" role="button">
              <div class="kol-line"><b>{_esc(v['kol'])}</b> <span class="kv-badge {bcls}">{_esc(btxt)}</span> {since_html}</div>
              {extra}
              <div class="kol-more">点击查看该 KOL 全部观点 →</div>
            </div>"""
        html += (
            f'<div class="h-module" style="border-color:{color}">'
            f'<div class="h-module-title" style="background:{color}">'
            f'<span class="h-mod-dot"></span>{_esc(sector)}<span class="h-mod-en">{_esc(en)}</span>'
            f'<span class="h-mod-n">{len(vs)} 位</span></div>'
            f'<div class="kol-mod-inner">{cards}</div></div>'
        )
    return html


def _liquidity_html(liq):
    """底部流动性要点板块(来自 Economic Dashboard)。"""
    if not liq:
        return '<p class="empty">流动性数据未就绪。</p>'
    parts = []
    # Fed 流动性
    fed = []
    for label, key in [("Fed 准备金", "reserves_T"), ("ON RRP", "on_rrp_B"), ("TGA", "tga_B")]:
        d = liq.get(key)
        if d:
            unit = "T" if key == "reserves_T" else "B"
            delta = f' ({"+" if (d.get("delta") or 0)>=0 else ""}{d["delta"]})' if d.get("delta") is not None else ""
            fed.append(f'<span class="liq-k">{label}</span> <b>${d["value"]}{unit}</b>{delta}')
    if fed:
        parts.append('<div class="liq-row">' + " · ".join(fed) + '</div>')
    # 收益率
    ylds = liq.get("yields", {})
    if ylds:
        ys = []
        for f in ["10Y", "2Y", "30Y"]:
            if f in ylds:
                d = ylds[f]
                delta = f'({"+" if (d.get("delta") or 0)>=0 else ""}{d["delta"]})' if d.get("delta") is not None else ""
                ys.append(f'US {f} <b>{d["value"]}%</b>{delta}')
        if ys:
            parts.append('<div class="liq-row">' + " · ".join(ys) + '</div>')
    # 风控灯
    lights = liq.get("risk_lights", {})
    if lights:
        ls = " · ".join(f'{_esc(k)}: {_esc(v)}' for k, v in lights.items() if k not in ("运行状态",))
        parts.append(f'<div class="liq-row liq-lights">{ls}</div>')
    # 关键变动文本
    notes = liq.get("risk_notes", {})
    if notes.get("关键变动"):
        parts.append(f'<div class="liq-note"><b>关键变动</b><br>{_esc(notes["关键变动"]).replace(chr(10), "<br>")}</div>')
    if notes.get("AI短评"):
        parts.append(f'<div class="liq-note"><b>AI 短评</b><br>{_esc(notes["AI短评"]).replace(chr(10), "<br>")}</div>')
    return "".join(parts) or '<p class="empty">流动性数据未就绪。</p>'


def _cb_bs_num(v):
    """大数字千分位; 兆/亿保留合适小数。"""
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def _cb_delta_span(line, unit_period):
    """一个科目的 WoW/环比标记(带涨跌色+箭头)。"""
    d = line.get("delta")
    pct = line.get("pct")
    if d is None:
        return f'<span class="bs-wow bs-flat">{unit_period} n/a</span>'
    if abs(d) < 1e-9:
        arrow, cls = "→", "bs-flat"
    elif d > 0:
        arrow, cls = "▲", "bs-up"
    else:
        arrow, cls = "▼", "bs-down"
    pcs = f" ({pct:+.2f}%)" if pct is not None else ""
    return f'<span class="bs-wow {cls}">{arrow} {d:+,.2f}{pcs}</span>'


def _cb_one_view(d, fx=None):
    """单个央行资产负债表 view：左资产右负债 + 总资产 + WoW/环比。"""
    if not d or (not d.get("assets") and not d.get("liabilities")):
        return (f'<div class="bs-card"><div class="bs-head">{_esc(d.get("flag",""))} '
                f'{_esc(d.get("name",""))}</div><p class="empty">数据未找到</p></div>')
    up = d.get("period", "")  # WoW / 较上期 / MoM

    def side(items):
        rows = ""
        for it in items:
            if it.get("sub"):
                # 子项(如"货币发行"⊂"储备货币"): 缩进 + "其中·"前缀, 表明是上一总项的明细, 不与总项同层相加
                rows += (f'<div class="bs-line bs-sub"><span class="bs-name">└ 其中·{_esc(it["name"])}</span>'
                         f'<span class="bs-val">{_cb_bs_num(it["value"])}</span>'
                         f'{_cb_delta_span(it, up)}</div>')
            else:
                rows += (f'<div class="bs-line"><span class="bs-name">{_esc(it["name"])}</span>'
                         f'<span class="bs-val">{_cb_bs_num(it["value"])}</span>'
                         f'{_cb_delta_span(it, up)}</div>')
        return rows

    ta = d.get("total_assets")
    total_a_html = ""
    if ta:
        total_a_html = (f'<div class="bs-line bs-total"><span class="bs-name">总资产</span>'
                        f'<span class="bs-val">{_cb_bs_num(ta["value"])}</span>'
                        f'{_cb_delta_span(ta, up)}</div>')
    tl = d.get("total_liab")
    total_l_html = ""
    if tl:
        total_l_html = (f'<div class="bs-line bs-total"><span class="bs-name">总负债</span>'
                        f'<span class="bs-val">{_cb_bs_num(tl["value"])}</span>'
                        f'{_cb_delta_span(tl, up)}</div>')
    # 换算标注: 若从本币换成 $B, 标原口径+汇率
    fx_note = ""
    orig = d.get("orig_unit")
    if orig and fx:
        rate = None
        pair = ""
        if orig == "兆¥":
            rate, pair = fx.get("USDJPY"), "USD/JPY"
        elif orig == "亿¥":
            rate, pair = fx.get("USDCNY"), "USD/CNY"
        elif orig == "十亿€":
            rate, pair = (d.get("usd_per_eur") or fx.get("USDEUR")), "USD/EUR"
        if rate:
            fx_note = f' · 原口径 {orig} · 按 {pair} {rate:g} 折美元'
    # ECB 政策利率行(务实版: 无分项, 展示三大政策利率)
    rates_html = ""
    r = d.get("rates") or {}
    if r:
        parts = []
        if r.get("mro") is not None:
            parts.append(f'主再融资 MRO <b>{r["mro"]:g}%</b>')
        if r.get("dfr") is not None:
            parts.append(f'存款便利 DFR <b>{r["dfr"]:g}%</b>')
        if r.get("mlf") is not None:
            parts.append(f'边际贷款 MLF <b>{r["mlf"]:g}%</b>')
        if parts:
            rates_html = ('<div class="bs-rates">政策利率：' + ' · '.join(parts) + '</div>')
    partial_note = ""
    if d.get("note_partial"):
        partial_note = f'<div class="bs-partial">ⓘ {_esc(d["note_partial"])}</div>'
    return (
        f'<div class="bs-card">'
        f'<div class="bs-head">{_esc(d.get("flag",""))} {_esc(d.get("name",""))}'
        f'<span class="bs-meta">{_esc(d.get("date",""))} · 单位 {_esc(d.get("unit",""))} · 环比口径 {_esc(up)}{fx_note}</span></div>'
        f'<div class="bs-body">'
        f'<div class="bs-col bs-assets"><div class="bs-col-h">资产 (Assets)</div>{side(d.get("assets",[]))}{total_a_html}</div>'
        f'<div class="bs-col bs-liabs"><div class="bs-col-h">负债 (Liabilities)</div>{side(d.get("liabilities",[]))}{total_l_html}</div>'
        f'</div>'
        f'{rates_html}{partial_note}'
        f'</div>'
    )


def _auc_btc_cls(btc):
    """中标率(bid-to-cover)色标: >2.5 强需求(绿)/2.2-2.5 正常(灰)/<2.2 偏弱(红)。"""
    if btc is None:
        return "auc-n"
    if btc >= 2.5:
        return "auc-g"
    if btc >= 2.2:
        return "auc-m"
    return "auc-r"


def _auctions_html(auc):
    """美国国债拍卖 timeline 卡片: 每个关键券种一条 timeline,
    最新拍卖大字 + 过去3次下挂 + 下次日程。中标率色标(需求强弱)。"""
    if not auc or auc.get("status") != "ok" or not auc.get("terms"):
        st = (auc or {}).get("status", "数据未就绪")
        return f'<p class="empty">国债拍卖数据未就绪（{st}）。</p>'
    # 全局下次拍卖(醒目提示)
    up = auc.get("upcoming", [])
    up_html = ""
    if up:
        nx = up[0]
        up_html = (
            f'<div class="auc-next-banner">'
            f'<span class="auc-next-lbl">下次拍卖</span> '
            f'<b>{_esc(nx["auction_date"])}</b> · {_esc(nx["security_type"])} {_esc(nx["security_term"])} '
            f'· 规模 <b>${nx["offering_bn"]}B</b>'
            + (f' · 交割 {_esc(nx["issue_date"])}' if nx.get("issue_date") else "")
            + '</div>'
        )
    # 券种顺序(短→长)
    order = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]
    rows = []
    for term in order:
        blk = auc["terms"].get(term)
        if not blk or not blk["history"]:
            continue
        hist = blk["history"]
        latest = hist[0]
        past = hist[1:4]  # 过去3次
        nxt = blk.get("next")
        lcls = _auc_btc_cls(latest.get("bid_to_cover"))
        sec = latest["security_type"]
        # 最新拍卖(大字)
        latest_html = (
            f'<div class="auc-latest">'
            f'<div class="auc-date">{_esc(latest["auction_date"])}<span class="auc-tag">最新</span></div>'
            f'<div class="auc-metrics">'
            f'<span class="auc-m-item">规模 <b>${latest["offering_bn"]}B</b></span>'
            f'<span class="auc-m-item">中标率 <b class="{lcls}">{latest["bid_to_cover"]}</b></span>'
            f'<span class="auc-m-item">收益率 <b>{latest["high_yield"]}%</b></span>'
            + (f'<span class="auc-m-item">间接投标 <b>{latest["indirect_pct"]}%</b></span>' if latest.get("indirect_pct") else "")
            + '</div></div>'
        )
        # 过去3次下挂(timeline 节点)
        past_html = ""
        for p in past:
            pcls = _auc_btc_cls(p.get("bid_to_cover"))
            past_html += (
                f'<div class="auc-past-node">'
                f'<span class="auc-p-date">{_esc(p["auction_date"])}</span>'
                f'<span class="auc-p-m">${p["offering_bn"]}B</span>'
                f'<span class="auc-p-m">BTC <b class="{pcls}">{p["bid_to_cover"]}</b></span>'
                f'<span class="auc-p-m">{p["high_yield"]}%</span>'
                + (f'<span class="auc-p-m">间接{p["indirect_pct"]}%</span>' if p.get("indirect_pct") else "")
                + '</div>'
            )
        # 下次(该券种)
        next_html = ""
        if nxt:
            next_html = (
                f'<div class="auc-next-node">▶ 下次 {_esc(nxt["auction_date"])} · '
                f'规模 ${nxt["offering_bn"]}B'
                + (f' · 交割 {_esc(nxt["issue_date"])}' if nxt.get("issue_date") else "")
                + '</div>'
            )
        rows.append(
            f'<div class="auc-term">'
            f'<div class="auc-term-head"><span class="auc-term-name">{_esc(sec)} · {_esc(term)}</span></div>'
            f'{latest_html}'
            f'<div class="auc-timeline">{past_html}</div>'
            f'{next_html}'
            f'</div>'
        )
    grid = "".join(rows)
    return (
        f'<div class="auc-wrap">'
        f'{up_html}'
        f'<div class="auc-grid">{grid}</div>'
        f'<div class="auc-how"><b>如何看：</b>'
        f'<b>中标率(Bid-to-Cover)</b>=总投标额/发行额，>2.5 需求强劲（绿）、2.2-2.5 正常、<2.2 偏弱（红）——拍卖遇冷是美债需求恶化的早期信号。'
        f'<b>最高中标收益率</b>=清算利率，走高=融资成本上升。'
        f'<b>间接投标占比</b>≈外国央行/官方代理需求份额，与上方托管美债互为印证。'
        f'数据源：美国财政部 <a class="src-lnk" href="https://fiscaldata.treasury.gov/" target="_blank" rel="noopener">fiscaldata.treasury.gov</a>（官方，每次拍卖后更新）。</div>'
        f'</div>'
    )


def _custody_chart_svg(hist, w=680, h=200):
    """外国官方托管美债历史折线图(带 Y 轴刻度/日期标签/最新点标注)。
    hist: [(date,$T),...] 升序。莫兰迪配色。"""
    if not hist or len(hist) < 2:
        return '<div class="cust-chart-na">历史数据不足，无法绘制折线图</div>'
    dates = [d for d, _ in hist]
    vals = [v for _, v in hist]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 0.01
    # 留白: 左轴 52 / 右 14 / 上 16 / 下 30(日期)
    ml, mr, mt, mb = 52, 14, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(vals)
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)]
    _hits = "".join(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="7" data-tip="{_esc(dates[i][:7])}||{v:.3f} $T"/>' for i, v in enumerate(vals))
    # 趋势色: 期末 vs 期初(下降=去美元化风险 clay红 / 上升=回流 sage绿)
    rising = vals[-1] > vals[0]
    color = "#9aab97" if rising else "#c08a7d"
    fill = "rgba(154,171,151,0.10)" if rising else "rgba(192,138,125,0.10)"
    area = f"{X(0):.1f},{mt+ph:.1f} " + " ".join(pts) + f" {X(n-1):.1f},{mt+ph:.1f}"
    # Y 轴 4 条网格线 + 刻度
    yl = []
    for k in range(4):
        gv = lo + rng * k / 3
        gy = Y(gv)
        yl.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        yl.append(f'<text x="{ml-6}" y="{gy+3:.1f}" class="cc-ylab">{gv:.2f}</text>')
    # X 轴日期标签(首/中/末 + 每约1/4); 24个月跨度用 YYYY-MM 显示年月
    xl = []
    idxs = sorted(set([0, n // 4, n // 2, 3 * n // 4, n - 1]))
    for i in idxs:
        dd = dates[i][:7]  # YYYY-MM
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        xl.append(f'<text x="{X(i):.1f}" y="{h-10}" class="cc-xlab" text-anchor="{anchor}">{dd}</text>')
    # 最新点标注
    lx, ly = X(n - 1), Y(vals[-1])
    return (
        f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet">'
        + "".join(yl)
        + f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
        + f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{color}"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="8" fill="{color}" opacity="0.18"/>'
        + _hits
        + "".join(xl)
        + '</svg>'
    )


def _custody_html(cust):
    """外国官方在纽约联储托管美债卡片(去美元化风向标) + 6个月历史折线图。"""
    if not cust or cust.get("value") is None:
        st = (cust or {}).get("status", "数据未就绪")
        return f'<p class="empty">外国官方托管美债数据未就绪（{st}）。</p>'
    val = cust["value"]           # $T
    wow = cust.get("wow_delta_bn")  # 十亿$
    wow_pct = cust.get("wow_pct")
    total = cust.get("total_custody_tn")
    as_of = cust.get("as_of", "")
    hist = cust.get("history", [])
    hist_long = cust.get("history_long", [])
    hist_2008 = cust.get("history_2008", [])
    # 方向: 下降=去美元化风险(clay红), 上升=回流(sage绿)
    if wow is None:
        acls, arrow, wtxt = "n", "→", "—"
    elif wow < 0:
        acls, arrow = "r", "▼"
        wtxt = f"{arrow} {wow:+.1f}B ({wow_pct:+.2f}%)"
    elif wow > 0:
        acls, arrow = "g", "▲"
        wtxt = f"{arrow} {wow:+.1f}B ({wow_pct:+.2f}%)"
    else:
        acls, arrow, wtxt = "n", "→", "持平"
    # 区间统计(高/低/首末回撤)
    span_txt = ""
    if len(hist) >= 2:
        vals = [v for _, v in hist]
        chg = vals[-1] - vals[0]
        chg_pct = chg / vals[0] * 100 if vals[0] else 0
        span_txt = (
            f'<div class="cust-row"><span>区间（{_esc(hist[0][0])}→{_esc(hist[-1][0])}）</span>'
            f'<b class="cust-{"r" if chg<0 else "g"}">{chg*1000:+.0f}B ({chg_pct:+.1f}%)</b></div>'
            f'<div class="cust-row"><span>区间高 / 低</span><b>${max(vals):.3f}T / ${min(vals):.3f}T</b></div>'
        )
    total_rows = ""
    if total:
        total_rows = (
            f'<div class="cust-row"><span>托管总额(含机构债/MBS)</span><b>${total:.3f}T</b></div>'
            f'<div class="cust-row"><span>其中非美债部分</span><b>${total-val:.3f}T</b></div>'
        )
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-main">'
        f'<div class="cust-lbl">可流通美债 · 外国官方托管</div>'
        f'<div class="cust-val">${val:.3f}<span class="cust-unit">T</span> '
        f'<span class="cust-wow cust-wow-{acls}">{wtxt}</span></div>'
        f'<div class="cust-sub">周环比（as of {_esc(as_of)} · 周三口径）</div>'
        f'</div>'
        # === 左右双折线图: 左近12月(短期) / 右近10年(长期) ===
        f'<div class="cust-charts">'
        f'<div class="cust-chart-col">'
        f'<div class="cust-chart-title">近 {len(hist)} 周（约12个月 · 短期）</div>'
        f'{_custody_chart_svg(hist)}'
        f'{_custody_span_line(hist)}'
        f'</div>'
        f'<div class="cust-chart-col">'
        f'<div class="cust-chart-title">近 {len(hist_long)} 周（约10年 · 长期）</div>'
        f'{_custody_chart_svg(hist_long)}'
        f'{_custody_span_line(hist_long)}'
        f'</div>'
        f'</div>'
        # === 2007 至今全周期结构图(用户 2026-08 要求; WMTSECL1 该口径第一个真实非零值2007-07-04) ===
        + (
            f'<div class="cust-chart-col cust-chart-full">'
            f'<div class="cust-chart-title">2007 至今 · 全周期结构（{len(hist_2008)} 周 · 约{len(hist_2008)//52} 年）</div>'
            f'{_custody_chart_svg(hist_2008, w=920, h=210)}'
            f'{_custody_span_line(hist_2008)}'
            f'</div>'
            if len(hist_2008) >= 2 else ""
        )
        + f'<div class="cust-meta">'
        f'{span_txt}'
        f'{total_rows}'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>外国央行/官方机构在纽约联储托管的美债存量。'
        f'持续下降 = 外国官方减持美债 / 去美元化 / 抛售换汇干预，是主权层面对美债信心的风向标。'
        f'<b>短期图</b>看近期拐点/干预动作，<b>长期图</b>看去美元化大趋势(10年结构性方向)，'
        f'<b>2007至今全周期图</b>看更长的结构性拐点(如2015-16去美元化起点、疫情后再平衡)。'
        f'数据源：FRED <a class="src-lnk" href="https://fred.stlouisfed.org/series/WMTSECL1" target="_blank" rel="noopener">WMTSECL1</a>（Fed H.4.1 custody，每周三口径）。</div>'
        f'</div>'
    )


def _custody_accel_html(acc):
    """外国官方托管美债 超短期加速度分析(周度 WMTSECL1)。
    主图=EMA(3周)斜率差分零轴填色(绿上=流入加速/红下=流出加速);
    叠加 7/14/28天(1/2/4周)二阶差分作数值参考。诚实标注周度约束。"""
    if not acc or acc.get("status") != "ok" or not acc.get("points"):
        st = (acc or {}).get("status", "未就绪")
        return f'<p class="empty">托管美债加速度数据未就绪（{_esc(st)}）。</p>'
    pts = acc["points"]
    asof = acc.get("asof", "")
    # ── 主图: EMA 平滑加速度, 零轴填色柱 ──
    vals = [p["ema_accel"] for p in pts if p.get("ema_accel") is not None]
    if not vals:
        return '<p class="empty">托管美债加速度数据不足。</p>'
    # ── 四条折线: 7/14/28/56天(1/2/4/8周)加速度, 带零轴, 可看交叉点 ──
    lines = [("a7", "7天(1周)", "#c27a3e"), ("a14", "14天(2周)", "#5b8fb5"),
             ("a28", "28天(4周)", "#6f8f6a"), ("a56", "56天(8周)", "#9b6b9e")]
    n = len(pts)
    # 收集所有有效值定值域
    allv = [p[k] for k, _, _ in lines for p in pts if p.get(k) is not None]
    if not allv:
        return '<p class="empty">托管美债加速度数据不足。</p>'
    amax = max(abs(min(allv)), abs(max(allv)), 1.0) * 1.12
    w, h = 900, 260
    ml, mr, mt, mb = 56, 108, 16, 34
    pw, ph = w - ml - mr, h - mt - mb
    def X(i): return ml + (i * pw / (n - 1) if n > 1 else pw / 2)
    def Y(v): return mt + ph / 2 - (v / amax) * (ph / 2)
    zy = mt + ph / 2
    parts = [f'<svg viewBox="0 0 {w} {h}" class="ca-chart" preserveAspectRatio="xMidYMid meet">']
    # 网格 + Y标
    for frac in (1.0, 0.5, 0.0, -0.5, -1.0):
        gy = Y(amax * frac)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        parts.append(f'<text x="{ml-5}" y="{gy+3:.1f}" class="cc-ylab">{amax*frac:+,.0f}</text>')
    # 零轴(加粗) + 上下方向标注
    parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" class="ci-zero"/>')
    parts.append(f'<text x="{ml+3}" y="{mt+11:.1f}" class="ca-zlab" fill="#2e9e5b">▲ 零轴上 = 流入在加速 / 流出在减速</text>')
    parts.append(f'<text x="{ml+3}" y="{h-mb+13:.1f}" class="ca-zlab" fill="#d64545">▼ 零轴下 = 流出在加速 / 流入在减速</text>')
    # X 轴日期(每隔几个)
    step = max(1, n // 6)
    for i in range(0, n, step):
        anchor = "start" if i == 0 else ("end" if i >= n - step else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h-6}" class="cc-xlab" text-anchor="{anchor}">{pts[i]["date"][5:]}</text>')
    # 三条折线
    legend_y = mt + 8
    for key, lbl, color in lines:
        seg = [(X(i), Y(p[key]), p["date"], p[key]) for i, p in enumerate(pts) if p.get(key) is not None]
        if len(seg) >= 2:
            poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in seg)
            parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.1" stroke-linejoin="round" stroke-linecap="round"/>')
            for _sx, _sy, _sd, _sv in seg:
                parts.append(f'<circle class="tip-hit" cx="{_sx:.1f}" cy="{_sy:.1f}" r="6" data-tip="{_esc(lbl)} · {_esc(_sd[:7])}||{_sv:+.3f}"/>')
            # 最新点标记
            lx, ly = seg[-1][0], seg[-1][1]
            parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="{color}"/>')
        # 图例(右侧)
        parts.append(f'<line x1="{w-mr+8}" y1="{legend_y}" x2="{w-mr+26}" y2="{legend_y}" stroke="{color}" stroke-width="2.6"/>')
        parts.append(f'<text x="{w-mr+30}" y="{legend_y+4}" class="ca-leg" fill="{color}">{lbl}</text>')
        legend_y += 20
    parts.append('</svg>')
    chart = "".join(parts)
    # ── 最新读数三窗口 ──
    last = pts[-1]
    def _cell(v, lbl, color):
        if v is None:
            return f'<div class="ca-cell"><div class="ca-clbl">{lbl}</div><div class="ca-cval">—</div></div>'
        col = "#2e9e5b" if v >= 0 else "#d64545"
        arrow = "▲加速流入" if v >= 0 else "▼加速流出"
        return (f'<div class="ca-cell" style="border-top:2px solid {color}"><div class="ca-clbl">{lbl}</div>'
                f'<div class="ca-cval" style="color:{col}">{v:+,.0f}</div>'
                f'<div class="ca-cnote" style="color:{col}">{arrow}</div></div>')
    cells = (_cell(last.get("a7"), "trailing 7天(1周)", "#c27a3e")
             + _cell(last.get("a14"), "trailing 14天(2周)", "#5b8fb5")
             + _cell(last.get("a28"), "trailing 28天(4周)", "#6f8f6a")
             + _cell(last.get("a56"), "trailing 56天(8周)", "#9b6b9e"))
    return (
        f'<div class="ca-wrap">'
        f'<div class="cust-lbl">超短期加速度 · 托管美债流入/流出的加速度（零轴上下 · 四周期对比 · 过去6个月） · as of {_esc(asof)}</div>'
        f'<div class="ca-cells">{cells}</div>'
        f'{chart}'
        f'<div class="ci-how"><b>如何看：</b>四条线分别是 <span style="color:#c27a3e"><b>7天(短)</b></span>、<span style="color:#5b8fb5"><b>14天(中)</b></span>、<span style="color:#6f8f6a"><b>28天(中长)</b></span>、<span style="color:#9b6b9e"><b>56天/8周(长)</b></span> 周期的加速度（托管美债<b>变化的变化</b>=二阶差分），覆盖<b>过去 6 个月</b>。'
        f'<span style="color:#2e9e5b">线在零轴上=资金流入在加速（或流出在减速）</span>，'
        f'<span style="color:#d64545">线在零轴下=资金流出在加速（或流入在减速）</span>。'
        f'★<b>看交叉点</b>：短周期(7/14天)线穿越中长周期(28/56天)线时=短期动能相对中长期在<b>转向</b>——短线上穿=短期率先加速（可能领先反转），短线下穿=短期率先减速。四线同向发散=趋势强化，收敛交叉=动能切换；长周期(8周)线最平滑，代表中期基调。'
        f'数据源为 Fed H.4.1 <b>周度</b>（每周三 as-of），故 7/14/28/56 天 ≡ <b>1/2/4/8 周</b>。单位百万美元。{_linkify_sources(acc.get("source",""))}。</div>'
        f'</div>'
    )


def _custody_span_line(hist):
    """折线图下方一行区间统计: 首末变化 + 高低。"""
    if not hist or len(hist) < 2:
        return ""
    vals = [v for _, v in hist]
    chg = vals[-1] - vals[0]
    chg_pct = chg / vals[0] * 100 if vals[0] else 0
    cls = "r" if chg < 0 else "g"
    return (f'<div class="cust-chart-span">'
            f'{_esc(hist[0][0])}→{_esc(hist[-1][0])}：'
            f'<b class="cust-{cls}">{chg*1000:+.0f}B ({chg_pct:+.1f}%)</b>'
            f' · 高 ${max(vals):.3f}T / 低 ${min(vals):.3f}T</div>')


def _country_ust_svg(series, color, fill, w=680, h=200):
    """分国别持有美债月度折线图($B 口径)。series: [(YYYY-MM, $B),...] 升序。"""
    if not series or len(series) < 2:
        return '<div class="cust-chart-na">历史数据不足，无法绘制折线图</div>'
    dates = [d for d, _ in series]
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 56, 14, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(vals)
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)]
    _hits = "".join(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="7" data-tip="{_esc(dates[i][:7])}||{v:,.0f} $B"/>' for i, v in enumerate(vals))
    area = f"{X(0):.1f},{mt+ph:.1f} " + " ".join(pts) + f" {X(n-1):.1f},{mt+ph:.1f}"
    # Y 轴 4 条网格 + 刻度($B, 无小数)
    yl = []
    for k in range(4):
        gv = lo + rng * k / 3
        gy = Y(gv)
        yl.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        yl.append(f'<text x="{ml-6}" y="{gy+3:.1f}" class="cc-ylab">{gv:,.0f}</text>')
    # X 轴年月标签
    xl = []
    idxs = sorted(set([0, n // 4, n // 2, 3 * n // 4, n - 1]))
    for i in idxs:
        dd = dates[i][:7]
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        xl.append(f'<text x="{X(i):.1f}" y="{h-10}" class="cc-xlab" text-anchor="{anchor}">{dd}</text>')
    lx, ly = X(n - 1), Y(vals[-1])
    return (
        f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet">'
        + "".join(yl)
        + f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
        + f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{color}"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="8" fill="{color}" opacity="0.18"/>'
        + _hits
        + "".join(xl)
        + '</svg>'
    )


def _country_ust_col(c):
    """单国持有美债一列(标题 + 当前值/变动 + 折线 + 区间统计)。c: fetch_country_ust_holdings 单国 dict。"""
    if not c or c.get("status") != "ok" or not c.get("series"):
        st = (c or {}).get("status", "数据未就绪")
        nm = (c or {}).get("name", "")
        return (f'<div class="cust-chart-col"><div class="cust-chart-title">{_esc(nm)}</div>'
                f'<div class="cust-chart-na">数据未就绪（{_esc(st)}）</div></div>')
    series = c["series"]
    last_m, last_v = c["latest"]
    dbn, dpct = c.get("delta_bn"), c.get("delta_pct")
    # 下降=减持/去美元化(clay红) 上升=增持(sage绿)
    down = (dbn is not None and dbn < 0)
    color = "#c08a7d" if down else "#9aab97"
    fill = "rgba(192,138,125,0.10)" if down else "rgba(154,171,151,0.10)"
    dcls = "r" if down else "g"
    darrow = "▼" if down else "▲"
    dtxt = f"{darrow} {dbn:+.0f}B ({dpct:+.1f}%)" if dbn is not None else "—"
    # ★2026-08-21: 滞后原因若已知(如 EU 受 TIC 前20大口径限制), 如实写明,
    #   不要只甩一个"请核对官方"的红标让人以为是抓取坏了。
    _reason = c.get("lag_reason")
    reason_html = (f'<div class="cu-lagnote">ℹ️ {_esc(_reason)}</div>'
                   if _reason else "")
    return (
        f'<div class="cust-chart-col">'
        f'<div class="cust-chart-title">{c.get("flag","")} {_esc(c["name"])}持有美债（{len(series)}个月）</div>'
        f'<div class="cu-cur">${last_v:,.0f}<span class="cust-unit">B</span> '
        f'<span class="cust-wow cust-wow-{dcls}">{dtxt}</span> '
        f'<span class="cu-asof">as of {_esc(last_m)}</span>{_stale_badge(last_m, "tic", known_reason=bool(_reason))}</div>'
        f'{reason_html}'
        f'{_country_ust_svg(series, color, fill)}'
        f'<div class="cust-chart-span">{_esc(c["first"][0])}→{_esc(last_m)}：'
        f'<b class="cust-{dcls}">{dbn:+.0f}B ({dpct:+.1f}%)</b>'
        f' · 高 ${c["high"]:,.0f}B / 低 ${c["low"]:,.0f}B</div>'
        f'</div>'
    )


def _country_ust_long_svg(series_by_country, w=920, h=250):
    """三国(日/中/欧)持有美债 2008 至今长历史多国折线($B)。
    series_by_country: {key: {name,flag,color,points:[(YYYY-MM,$B)]}}。"""
    active = {k: d for k, d in series_by_country.items() if d.get("points") and len(d["points"]) >= 2}
    if not active:
        return '<div class="cust-chart-na">2008 长历史数据不足</div>'
    all_dates = sorted({m for d in active.values() for m, _ in d["points"]})
    all_vals = [v for d in active.values() for _, v in d["points"]]
    lo, hi = min(all_vals + [0.0]), max(all_vals)
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 56, 96, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(all_dates)
    didx = {d: i for i, d in enumerate(all_dates)}
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet">']
    # Y 轴 4 刻度
    for k in range(4):
        gv = lo + rng * k / 3
        gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" class="cc-ylab">{gv:,.0f}</text>')
    # X 轴年份标签(每2年)
    for i, d in enumerate(all_dates):
        if d[5:7] == "01" and int(d[:4]) % 2 == 0:
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-10}" class="cc-xlab" text-anchor="{anchor}">{d[:4]}</text>')
    legend_y = mt + 6
    for k, d in active.items():
        color = d["color"]
        pts = [f"{X(didx[m]):.1f},{Y(v):.1f}" for m, v in d["points"] if m in didx]
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                         f'stroke-width="2" stroke-linejoin="round" opacity="0.9"/>')
            for m, v in d["points"]:
                if m in didx:
                    parts.append(f'<circle class="tip-hit" cx="{X(didx[m]):.1f}" cy="{Y(v):.1f}" r="6" data-tip="{_esc(k)} · {_esc(m[:7])}||{v:,.0f} $B"/>')
            lm, lv = d["points"][-1]
            parts.append(f'<circle cx="{X(didx[lm]):.1f}" cy="{Y(lv):.1f}" r="3.5" fill="{color}"/>')
        parts.append(f'<line x1="{w-mr+8}" y1="{legend_y}" x2="{w-mr+24}" y2="{legend_y}" stroke="{color}" stroke-width="2.6"/>')
        parts.append(f'<text x="{w-mr+28}" y="{legend_y+4}" class="ci-leg" fill="{color}">{d["flag"]}{_esc(d["name"])}</text>')
        legend_y += 18
    parts.append('</svg>')
    return "".join(parts)


def _yield_curves_svg(series, w=920, h=280, yunit="%"):
    """美日 10Y/30Y 收益率四线图(过去一年,日频,共%轴)。
    series: {key:{name,color,dash('none'/'dash'),points:[(date,%)],latest}}。美实线/日虚线。
    yunit: Y轴与图例单位后缀(默认'%'; 复用于万亿图时传 'T' 等)。"""
    active = {k: d for k, d in series.items() if d.get("status") == "ok" and len(d.get("points", [])) >= 2}
    if not active:
        return '<div class="cust-chart-na">美日收益率数据不足</div>'
    all_dates = sorted({dd for d in active.values() for dd, _ in d["points"]})
    all_vals = [v for d in active.values() for _, v in d["points"]]
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.08 or 0.2
    lo -= pad; hi += pad
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 46, 104, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(all_dates)
    didx = {d: i for i, d in enumerate(all_dates)}
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    # Y 轴 5 刻度(%)
    for k in range(5):
        gv = lo + rng * k / 4
        gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{gv:.1f}{yunit}</text>')
    # X 轴标签: 动态间隔, 目标约 8 个均匀分布的标签(避免长跨度数据标签互相覆盖)。
    # 不论数据是 1 年日频 / 10 年周频 / 27 年季频, 都只显示 ~8 个不重叠标签。
    target_labels = 8
    step = max(1, round(n / target_labels))
    # 长跨度(>3年)显示"年"或"年-月", 短跨度显示"年-月"
    span_days = 0
    try:
        from datetime import date as _date
        d0 = _date.fromisoformat(all_dates[0][:10]); d1 = _date.fromisoformat(all_dates[-1][:10])
        span_days = (d1 - d0).days
    except Exception:
        span_days = 0
    long_span = span_days > 3 * 365
    label_idxs = list(range(0, n, step))
    if (n - 1) not in label_idxs:
        label_idxs.append(n - 1)  # 保证最后一个点有标签
    _prev_lbl = None
    for i in label_idxs:
        d = all_dates[i]
        lbl = d[:4] if long_span else d[:7]  # 长跨度只显示年, 短跨度显示年-月
        # 去重: 若与上一个标签相同则跳过(避免末尾重复, 如 2026/2026 或 2026-08/2026-08)
        if lbl == _prev_lbl:
            continue
        _prev_lbl = lbl
        anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h-9}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{lbl}</text>')
    # 四条线 + 图例
    legend_y = mt + 6
    order = ["us_10y", "us_30y", "jp_10y", "jp_30y"]
    # 先按固定顺序, 再补充任何其他 key(通用化: 支持复用于非收益率的多线图)
    ordered_keys = [k for k in order if k in active] + [k for k in active if k not in order]
    for key in ordered_keys:
        d = active[key]
        color = d["color"]
        dash = 'stroke-dasharray="5,3"' if d.get("dash") == "dash" else ''
        pts = [f"{X(didx[dd]):.1f},{Y(v):.1f}" for dd, v in d["points"] if dd in didx]
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.9" stroke-linejoin="round" opacity="0.92" {dash}/>')
            for dd, v in d["points"]:
                if dd in didx:
                    # ★tooltip 单位必须跟随序列自身单位(优先 series.unit, 回退 yunit),
                    #   绝不硬编码 '%' —— 本函数被复用于 吨/千oz/百万美元/万亿/合约数 等多种量纲。
                    _tu = d.get("unit", yunit)
                    _vs = (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}")
                    _tip_val = f"{_vs} {_tu}".strip()
                    parts.append(f'<circle class="tip-hit" cx="{X(didx[dd]):.1f}" cy="{Y(v):.1f}" r="6" data-tip="{_esc(str(d.get("name") or key))} · {_esc(dd)}||{_esc(_tip_val)}"/>')
            ld, lv = d["points"][-1]
            parts.append(f'<circle cx="{X(didx[ld]):.1f}" cy="{Y(lv):.1f}" r="3.2" fill="{color}"/>')
        # 图例(右侧): 线样 + 名称 + 最新值
        lx1, lx2 = w - mr + 8, w - mr + 26
        parts.append(f'<line x1="{lx1}" y1="{legend_y}" x2="{lx2}" y2="{legend_y}" stroke="{color}" stroke-width="2.4" {dash}/>')
        _lv = d.get("latest")
        _unit = d.get("unit", yunit)
        _lvs = (f"{_lv:.2f}{_unit}" if isinstance(_lv, (int, float)) else str(_lv))
        parts.append(f'<text x="{lx2+4}" y="{legend_y+4}" font-size="10.5" fill="{color}" font-weight="600">{_esc(d["name"])} {_lvs}</text>')
        legend_y += 19
    parts.append('</svg>')
    return "".join(parts)


def _yield_curves_html(yc):
    """美日 10Y/30Y 收益率四线图 section。yc: fetch_us_jp_yields()。绝不编造。"""
    if not yc or yc.get("status") != "ok":
        return '<p class="empty">美日国债收益率数据未就绪。</p>'
    ser = yc.get("series", {})
    chart = _yield_curves_svg(ser)
    # 各线区间统计(过去一年变动)
    rows = []
    for key in ("us_10y", "us_30y", "jp_10y", "jp_30y"):
        d = ser.get(key, {})
        if d.get("status") != "ok":
            continue
        pts = d["points"]
        chg = (pts[-1][1] - pts[0][1]) * 100  # bp
        col = "#d64545" if chg >= 0 else "#2e9e5b"
        rows.append(f'<span style="color:{d["color"]};font-weight:600">{_esc(d["name"])}</span> '
                    f'{pts[0][1]:.2f}%→<b>{pts[-1][1]:.2f}%</b>（<b style="color:{col}">{chg:+.0f}bp</b>）')
    meta = " · ".join(rows)
    srcs = "；".join(sorted({d.get("source", "") for d in ser.values() if d.get("status") == "ok"}))
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">美国 vs 日本 · 10年/30年国债收益率 · 过去一年（日频）'
        f'<span class="chart-freq">🟢 日频 · 每交易日更新</span></div>'
        f'{chart}'
        f'<div class="oil-meta">{meta}</div>'
        f'<div class="oil-src">数据源：{_esc(srcs)}（实线=美国，虚线=日本）</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>四条线同框对比中美两国长端利率的<b>相对走势与利差</b>：'
        f'<b>美债 10Y/30Y</b>反映全球无风险利率锚与期限溢价；<b>日债 10Y/30Y</b>是全球最后的低利率洼地——'
        f'日本长端利率快速上行(BOJ 退出 YCC/加息 + 财政赤字担忧)会<b>收窄美日利差</b>，削弱日元套息(carry trade)吸引力、'
        f'触发套息平仓回流日元，是全球流动性与汇率的重要变量。若日债 30Y 逼近甚至超过美债，说明市场对日本财政/通胀定价显著重估。'
        f'<br>实线=美国，虚线=日本；均为各国官方公开数据。</div>'
        f'</div>'
    )


def _nikkei_flow_svg(nk, ff, w=920, h=300):
    """日经225指数(折线,左轴,完整日频) + 外资净买入日股(周频柱状,右轴,正绿负红)双轴同图。
    nk: fetch_nikkei225(日频); ff: fetch_foreign_flow_japan(周频,滞后1-2周)。
    ★时间轴用日经【完整日频】范围,日经线画到最新交易日; 外资柱按各自周日期投影到该轴对应位置
    (外资滞后→最右侧留空,真实反映发布时滞,不再把日经截断到外资最后一周)。"""
    nk_ok = nk and nk.get("status") == "ok" and len(nk.get("points", [])) >= 2
    ff_ok = ff and ff.get("status") == "ok" and len(ff.get("points", [])) >= 2
    if not nk_ok and not ff_ok:
        return '<div class="cust-chart-na">日经225 / 外资流入数据不足</div>'
    ml, mr, mt, mb = 56, 62, 16, 32
    pw, ph = w - ml - mr, h - mt - mb
    # ── 时间轴: 用日经完整日频日期(若无则退回外资周日期) ──
    if nk_ok:
        axis_dates = [d for d, _ in nk["points"]]
    else:
        axis_dates = [d for d, _ in ff["points"]]
    n = len(axis_dates)
    d0, d1 = axis_dates[0], axis_dates[-1]
    import datetime as _dt
    _t0 = _dt.date.fromisoformat(d0)
    _span = (_dt.date.fromisoformat(d1) - _t0).days or 1
    # 按日期在总跨度中的比例定位 x(外资周日期即使非交易日也能落位)
    def XD(dstr):
        try:
            days = (_dt.date.fromisoformat(dstr) - _t0).days
        except Exception:
            return ml
        return ml + max(0, min(days, _span)) / _span * pw
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    # ── 右轴: 外资流入柱状(先画,当背景; 按周日期投影到日频轴) ──
    if ff_ok:
        fvals = [v for _, v in ff["points"]]
        fmax = max(abs(min(fvals)), abs(max(fvals))) or 1.0
        def FY(v): return mt + ph / 2 - (v / fmax) * (ph / 2 * 0.9)
        zero_y = FY(0)
        bw = pw / max(n / 5, len(ff["points"])) * 0.9  # 柱宽按周密度估算
        bw = max(4.0, min(bw, pw / len(ff["points"]) * 0.7))
        for d, v in ff["points"]:
            cx = XD(d)
            y = FY(v)
            col = "#5b9e6f" if v >= 0 else "#c0757d"
            top = min(y, zero_y); ht = abs(y - zero_y)
            parts.append(f'<rect x="{cx-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{ht:.1f}" fill="{col}" opacity="0.55" data-tip="外资净买入 · {_esc(d)}||{v:+.2f} ¥T"/>')
        # 0 线
        parts.append(f'<line x1="{ml}" y1="{zero_y:.1f}" x2="{w-mr}" y2="{zero_y:.1f}" stroke="#8a8578" stroke-width="1" opacity="0.5"/>')
        # 右轴刻度
        for frac in (1, 0, -1):
            yy = FY(fmax * frac * 0.9)
            parts.append(f'<text x="{w-mr+5}" y="{yy+3:.1f}" font-size="9" fill="#8a8578" text-anchor="start">{fmax*frac*0.9:+.1f}</text>')
        parts.append(f'<text x="{w-mr+5}" y="{mt+8}" font-size="8.5" fill="#8a8578">外资¥T</text>')
        # 外资数据截止标注(最新周 < 日经最新时, 提示滞后)
        ff_last = ff["points"][-1][0]
        if nk_ok and ff_last < d1:
            _lx = XD(ff_last)
            parts.append(f'<line x1="{_lx:.1f}" y1="{mt}" x2="{_lx:.1f}" y2="{mt+ph}" stroke="#c0757d" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>')
            parts.append(f'<text x="{_lx-3:.1f}" y="{mt+ph-4:.1f}" font-size="8" fill="#c0757d" text-anchor="end" opacity="0.85">外资数据截至{_esc(ff_last[5:])}</text>')
    # ── 左轴: 日经225 折线(完整日频, 画到最新交易日) ──
    if nk_ok:
        nvals = [v for _, v in nk["points"]]
        nlo, nhi = min(nvals), max(nvals)
        npad = (nhi - nlo) * 0.1 or 1
        nlo -= npad; nhi += npad
        nrng = (nhi - nlo) or 1
        def NY(v): return mt + (nhi - v) / nrng * ph
        line = [f"{XD(d):.1f},{NY(v):.1f}" for d, v in nk["points"]]
        parts.append(f'<polyline points="{" ".join(line)}" fill="none" stroke="#3a5a7d" stroke-width="2.3" stroke-linejoin="round"/>')
        # hover 点(日频, 抽稀避免过密: 每根都放但 r 小)
        for d, v in nk["points"]:
            parts.append(f'<circle class="tip-hit" cx="{XD(d):.1f}" cy="{NY(v):.1f}" r="5" data-tip="日经225 · {_esc(d)}||{v:,.0f}"/>')
        ld, lv = nk["points"][-1]
        parts.append(f'<circle cx="{XD(ld):.1f}" cy="{NY(lv):.1f}" r="3.5" fill="#3a5a7d"/>')
        parts.append(f'<text x="{XD(ld)-4:.1f}" y="{NY(lv)-6:.1f}" font-size="8.5" fill="#3a5a7d" text-anchor="end">最新 {lv:,.0f}</text>')
        # 左轴刻度
        for k in range(4):
            gv = nlo + nrng * k / 3
            gy = NY(gv)
            parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#3a5a7d" text-anchor="end">{gv:,.0f}</text>')
        parts.append(f'<text x="{ml-6}" y="{mt+8}" font-size="8.5" fill="#3a5a7d" text-anchor="end">日经</text>')
    # x 轴月标签(按日期跨度, 每隔月)
    last_ym = None
    for d in axis_dates:
        if d[:7] != last_ym and int(d[5:7]) % 2 == 1:
            last_ym = d[:7]
            _x = XD(d)
            anchor = "start" if d == d0 else ("end" if d >= axis_dates[-2] else "middle")
            parts.append(f'<text x="{_x:.1f}" y="{h-9}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{d[:7]}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _nikkei_flow_html(nk, ff):
    """日经225 + 外资净买入日股 双轴同图 section。nk/ff 各自 fetch。绝不编造,缺项标注。"""
    if (not nk or nk.get("status") != "ok") and (not ff or ff.get("status") != "ok"):
        return '<p class="empty">日经225 / 外资流入日股数据未就绪。</p>'
    chart = _nikkei_flow_svg(nk, ff)
    metas = []
    if nk and nk.get("status") == "ok":
        p = nk["points"]
        chg = (p[-1][1] - p[0][1]) / p[0][1] * 100
        col = "#d64545" if chg >= 0 else "#2e9e5b"
        metas.append(f'<span style="color:#3a5a7d;font-weight:600">日经225</span> '
                     f'{p[0][1]:,.0f}→<b>{p[-1][1]:,.0f}</b>（<b style="color:{col}">{chg:+.1f}%</b>，'
                     f'高{nk["hi"]:,.0f}/低{nk["lo"]:,.0f}）')
    if ff and ff.get("status") == "ok":
        p = ff["points"]
        net = sum(v for _, v in p)
        col = "#5b9e6f" if net >= 0 else "#c0757d"
        pos = sum(1 for _, v in p if v > 0); neg = sum(1 for _, v in p if v < 0)
        metas.append(f'<span style="color:#5b9e6f;font-weight:600">外资净买入</span> '
                     f'过去一年累计<b style="color:{col}">{net:+.1f}万亿円</b>（{pos}周净买/{neg}周净卖，'
                     f'最新周{p[-1][1]:+.2f}万亿円）')
    src_nk = nk.get("source", "") if nk and nk.get("status") == "ok" else ""
    src_ff = ff.get("source", "") if ff and ff.get("status") == "ok" else ""
    srcs = "；".join([s for s in (src_nk, src_ff) if s])
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">日经225 指数（折线·左轴） vs 外资净买入日股（柱状·右轴·周频） · 过去一年'
        f'<span class="chart-freq freq-w">🔵 指数日频 / 外资流入周频（JPX 每周4个工作日更新）</span></div>'
        f'{chart}'
        f'<div class="oil-meta">{" · ".join(metas)}</div>'
        f'<div class="oil-src">数据源：{_esc(srcs)}（绿柱=外资净买入，红柱=净卖出）</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>把<b>日经225 走势</b>与<b>外资资金流</b>叠在一起，看外资是不是日股行情的主要推手：'
        f'日本股市外资持仓/成交占比高(约6-7成成交)，<b>绿柱(外资净买入)持续＝外资加仓推升指数</b>；'
        f'<b>红柱(净卖出)＝外资撤离</b>，若指数仍涨则靠内资/自社股回购支撑，行情根基相对脆弱。'
        f'外资流向也与日元汇率、美日利差、全球风险偏好联动——套息交易(carry)活跃期外资倾向流入，平仓期则撤出。'
        f'<br>左轴=日经225 点位(蓝线)，右轴=外资单周净买卖(万亿日元,0 线上下)。数据均为官方公开。</div>'
        f'</div>'
    )


def _iip_net_svg(countries, w=920, h=280):
    """四国 IIP 净头寸(资产-负债)过去十年折线。正=净债权国,负=净债务国,0线。"""
    active = {k: c for k, c in countries.items() if c.get("status") == "ok" and len(c.get("net", [])) >= 2}
    if not active:
        return '<div class="cust-chart-na">四国 IIP 数据不足</div>'
    all_years = sorted({y for c in active.values() for y, _ in c["net"]})
    all_vals = [v for c in active.values() for _, v in c["net"]]
    lo, hi = min(all_vals + [0.0]), max(all_vals + [0.0])
    pad = (hi - lo) * 0.08 or 1
    lo -= pad; hi += pad
    rng = (hi - lo) or 1
    ml, mr, mt, mb = 52, 90, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(all_years)
    yidx = {y: i for i, y in enumerate(all_years)}
    def X(i): return ml + i * pw / (max(n - 1, 1))
    def Y(v): return mt + (hi - v) / rng * ph
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    for k in range(5):
        gv = lo + rng * k / 4; gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{gv:+.0f}</text>')
    # 0 线加粗
    zy = Y(0.0)
    parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" stroke="#8a8578" stroke-width="1.3" opacity="0.6"/>')
    # x 年份
    for i, y in enumerate(all_years):
        if i % 2 == 0 or i == n - 1:
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-9}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{y}</text>')
    legend_y = mt + 6
    for k in ("US", "JP", "DE", "CN"):
        if k not in active:
            continue
        c = active[k]; color = c["color"]
        line = [f"{X(yidx[y]):.1f},{Y(v):.1f}" for y, v in c["net"] if y in yidx]
        if len(line) >= 2:
            parts.append(f'<polyline points="{" ".join(line)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
            for y, v in c["net"]:
                if y in yidx:
                    parts.append(f'<circle class="tip-hit" cx="{X(yidx[y]):.1f}" cy="{Y(v):.1f}" r="6" data-tip="{_esc(c["name"])} · {_esc(str(y))}||{v:+.1f}"/>')
            ly, lv = c["net"][-1]
            parts.append(f'<circle cx="{X(yidx[ly]):.1f}" cy="{Y(lv):.1f}" r="3.4" fill="{color}"/>')
        parts.append(f'<line x1="{w-mr+8}" y1="{legend_y}" x2="{w-mr+24}" y2="{legend_y}" stroke="{color}" stroke-width="2.6"/>')
        parts.append(f'<text x="{w-mr+28}" y="{legend_y+4}" font-size="10" fill="{color}" font-weight="600">{c["flag"]}{_esc(c["name"])} {c["latest_net"]:+.1f}</text>')
        legend_y += 18
    parts.append('</svg>')
    return "".join(parts)


def _iip_assets_liab_svg(countries, w=920, h=230):
    """最新年四国 对外总资产 vs 总负债 分组柱状(每国两根:资产/负债)。"""
    active = [(k, c) for k, c in countries.items() if c.get("status") == "ok"]
    order = [x for x in ("US", "JP", "DE", "CN") if x in dict(active)]
    if not order:
        return '<div class="cust-chart-na">数据不足</div>'
    cd = dict(active)
    allv = [cd[k]["latest_assets"] for k in order] + [cd[k]["latest_liab"] for k in order]
    vmax = max(allv) * 1.12
    ml, mr, mt, mb = 46, 14, 20, 40
    pw, ph = w - ml - mr, h - mt - mb
    ng = len(order)
    gap = pw / ng
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    for k in range(4):
        gv = vmax * k / 3; gy = mt + ph - gv / vmax * ph
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#8a8578" text-anchor="end">{gv:.0f}</text>')
    bw = gap * 0.28
    for gi, k in enumerate(order):
        c = cd[k]
        cx = ml + gap * gi + gap / 2
        for off, val, col, lab in ((-bw*0.6, c["latest_assets"], "#7fa085", "资产"),
                                   (bw*0.6, c["latest_liab"], "#c0757d", "负债")):
            bh = val / vmax * ph
            by = mt + ph - bh
            parts.append(f'<rect x="{cx+off-bw/2:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" fill="{col}" opacity="0.85" data-tip="{_esc(c["name"])} · {lab}||{val:.1f}"/>')
            parts.append(f'<text x="{cx+off:.1f}" y="{by-3:.1f}" font-size="8.5" fill="{col}" text-anchor="middle">{val:.1f}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{h-pad_b_iip(mb)+14:.1f}" font-size="10" fill="#4a4a42" text-anchor="middle">{c["flag"]}{_esc(c["name"])}</text>')
    # 图例
    parts.append(f'<rect x="{ml}" y="{mt-2}" width="9" height="9" fill="#7fa085"/><text x="{ml+13}" y="{mt+6}" font-size="9" fill="#8a8578">对外总资产</text>')
    parts.append(f'<rect x="{ml+80}" y="{mt-2}" width="9" height="9" fill="#c0757d"/><text x="{ml+93}" y="{mt+6}" font-size="9" fill="#8a8578">对外总负债</text>')
    parts.append('</svg>')
    return "".join(parts)


def pad_b_iip(mb):
    return mb


def _iip_html(iip):
    """四国 IIP section: 净头寸十年折线 + 最新年资产/负债分组柱状。iip: fetch_iip_four_countries()。"""
    if not iip or iip.get("status") != "ok":
        return '<p class="empty">四国国际投资头寸(IIP)数据未就绪。</p>'
    cs = iip.get("countries", {})
    net_svg = _iip_net_svg(cs)
    al_svg = _iip_assets_liab_svg(cs)
    rows = []
    for k in ("US", "JP", "DE", "CN"):
        c = cs.get(k, {})
        if c.get("status") != "ok":
            continue
        net = c["latest_net"]
        col = "#2e9e5b" if net >= 0 else "#d64545"
        role = "净债权国" if net >= 0 else "净债务国"
        rows.append(f'<span style="color:{c["color"]};font-weight:600">{c["flag"]}{_esc(c["name"])}</span> '
                    f'资产${c["latest_assets"]:.1f}T/负债${c["latest_liab"]:.1f}T→'
                    f'净<b style="color:{col}">{net:+.1f}T</b>（{role}）')
    meta = " · ".join(rows)
    asof = iip.get("as_of", "")
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">四国对外净头寸 NIIP · 过去约十年（对外总资产 − 总负债 · $万亿）'
        f'<span class="chart-freq freq-w">🔵 年频 · IMF 年度更新</span></div>'
        f'{net_svg}'
        f'</div>'
        f'<div class="cust-chart-col cust-chart-full" style="margin-top:14px;">'
        f'<div class="cust-chart-title">最新年（{_esc(asof)}）· 四国对外总资产 vs 总负债（$万亿）</div>'
        f'{al_svg}'
        f'<div class="oil-meta">{meta}</div>'
        f'<div class="oil-src">数据源：{_esc(iip.get("source",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b><b>国际投资头寸(IIP)</b>是一国对外<b>金融资产与负债的存量</b>快照，'
        f'净头寸(NIIP=资产−负债)＝该国对世界其他地区的<b>净债权(正)或净债务(负)</b>：'
        f'<b>🇺🇸 美国</b>是全球最大<b>净债务国</b>(净头寸深度为负且持续恶化)——靠美元储备货币地位持续吸收外部资本；'
        f'<b>🇯🇵 日本 / 🇩🇪 德国 / 🇨🇳 中国</b>是主要<b>净债权国</b>(常年经常账户顺差累积对外资产)。'
        f'净债务国若外部融资条件收紧(利率↑/避险)会承压；净债权国则在全球动荡时资本回流本国、支撑本币。'
        f'是判断<b>全球资本流向与外部脆弱性</b>的结构性指标。<br>年频，IMF 官方公开数据。</div>'
        f'</div>'
    )


def _market_breadth_html(mb):
    """美股市场广度 section: SP500(SPY) vs RSP/SPY 广度比 双线折线, 数值化顶背离判定。
    mb: fetch_market_breadth()。替代原无数据源的 A/D 布尔判断, 真数据可复现。"""
    if not mb or mb.get("status") != "ok" or not mb.get("spy_points"):
        return ('<p class="empty">美股市场广度(RSP/SPY)数据抓取中——东方财富源间歇限流，'
                '每日 cron 低频重试，抓到即填真值，绝不编造。</p>')
    spy_pts = mb["spy_points"]
    ratio_pts = mb["ratio_points"]
    ev = mb.get("evidence", {})
    diverge = mb.get("divergence")
    stale = mb.get("stale", False)

    # 双线各自归一化到面板高度(量级差大: SPY~770 vs ratio~100)
    w, h = 920, 260
    ml, mr, mt, mb_ = 20, 160, 18, 30
    pw, ph = w - ml - mr, h - mt - mb_
    dates = [d for d, _ in spy_pts]
    n = len(dates)
    didx = {d: i for i, (d, _) in enumerate(spy_pts)}
    def X(i): return ml + i * pw / max(n - 1, 1)
    def norm(vals):
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1
        return lo, hi, rng
    spy_v = [v for _, v in spy_pts]
    rt_map = dict(ratio_pts)
    rt_v = [rt_map[d] for d in dates if d in rt_map]
    slo, shi, srng = norm(spy_v)
    rlo, rhi, rrng = norm(rt_v)
    def Ys(v): return mt + (shi - v) / srng * ph
    def Yr(v): return mt + (rhi - v) / rrng * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # 网格
    for k in range(5):
        gy = mt + ph * k / 4
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
    # x 年标签
    seen = set()
    for i, d in enumerate(dates):
        yr = d[:4]
        if yr not in seen and (i == 0 or i == n - 1 or i % max(n // 5, 1) == 0):
            seen.add(yr)
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-10}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{_esc(d)}</text>')
    # SP500 线(蓝)
    sp_line = [f"{X(i):.1f},{Ys(v):.1f}" for i, (_, v) in enumerate(spy_pts)]
    parts.append(f'<polyline points="{" ".join(sp_line)}" fill="none" stroke="#6b8fb5" stroke-width="2.2" stroke-linejoin="round"/>')
    for i, (dd, v) in enumerate(spy_pts):
        parts.append(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Ys(v):.1f}" r="6" data-tip="S&amp;P500 · {_esc(dd)}||{v:,.2f}"/>')
    # 广度比线(琥珀)
    rt_line = [f"{X(didx[d]):.1f},{Yr(rt_map[d]):.1f}" for d in dates if d in rt_map and d in didx]
    parts.append(f'<polyline points="{" ".join(rt_line)}" fill="none" stroke="#c9a94e" stroke-width="2.2" stroke-linejoin="round"/>')
    for d in dates:
        if d in rt_map and d in didx:
            parts.append(f'<circle class="tip-hit" cx="{X(didx[d]):.1f}" cy="{Yr(rt_map[d]):.1f}" r="6" data-tip="广度比 · {_esc(d)}||{rt_map[d]:.1f}%"/>')
    # 末点圈
    parts.append(f'<circle cx="{X(n-1):.1f}" cy="{Ys(spy_v[-1]):.1f}" r="3.4" fill="#6b8fb5"/>')
    parts.append(f'<circle cx="{X(n-1):.1f}" cy="{Yr(rt_v[-1]):.1f}" r="3.4" fill="#c9a94e"/>')
    # 图例
    ly = mt + 6
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#6b8fb5" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#6b8fb5">S&amp;P500 (SPY) {mb.get("latest_spy")}</text>')
    ly += 18
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#c9a94e" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#c9a94e">广度比 RSP/SPY {mb.get("latest_ratio")}</text>')
    parts.append("</svg>")
    svg = "".join(parts)

    # 判定徽标
    if diverge is True:
        badge = '<span style="color:#d64545;font-weight:700">⚠ 顶背离(广度恶化)</span>'
        verdict = "🔴 顶背离"
    elif diverge is False:
        badge = '<span style="color:#2e9e5b;font-weight:700">✓ 广度确认(健康)</span>'
        verdict = "🟢 广度确认"
    else:
        badge = '<span style="color:#8a8578">数据不足</span>'
        verdict = "⚪ 未判定"

    stale_note = (' <span style="color:#c08a2e">(缓存数据，东财源今日限流，最新真值待 cron 刷新)</span>'
                  if stale else "")
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">美股市场广度：S&amp;P500 vs 等权/市值加权比(RSP/SPY) · 判定：{badge}'
        f'<span class="chart-freq freq-d">🟢 每日 · 东方财富 push2his</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(mb.get("as_of",""))}）：{verdict}{stale_note}<br>'
        f'判定依据：SPY 近 {ev.get("lookback_days","?")} 日高点 <b>{ev.get("spy_lookback_high","?")}</b>，'
        f'近 {ev.get("nh_window","?")} 日高点 <b>{ev.get("spy_recent_high","?")}</b>'
        f'（{"创新高" if ev.get("spy_made_new_high") else "未创新高"}）；'
        f'广度比距其高点差 <b>{ev.get("ratio_gap_from_high_pct","?")}%</b>'
        f'（{"广度确认" if ev.get("breadth_confirmed") else "广度未跟上"}）</div>'
        f'<div class="oil-src">数据源：{_esc(mb.get("source",""))} · '
        f'判定规则：{_esc(ev.get("rule",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>市场广度(market breadth)</b>的真数据版——替代原先无数据源的「NYSE A/D 腾落线」定性判断。'
        f'<b>RSP</b>=等权标普(每只股权重相同)，<b>SPY</b>=市值加权标普(大票主导)。'
        f'<b>RSP/SPY 比值上行</b>=普涨、广度健康；<b>比值下行</b>=少数大权重股(如「七巨头」)领涨、多数股走弱=<b>广度恶化</b>，'
        f'与 A/D 腾落线「顶背离」同义。<br>'
        f'<b>顶背离判定(可复现数值规则)</b>：当 <b>S&amp;P 创新高、但 RSP/SPY 广度比未同步创高</b>(距其高点 &gt;2%) 时判为顶背离——'
        f'指数只靠少数股撑、内部走弱，历史上是<b>见顶前兆</b>。<br>'
        f'相比旧布尔判断，这里<b>有折线图、有数字、判定规则透明可回溯</b>，绝不靠 AI 主观。每日更新(东财源，间歇限流则用缓存真值兜底)。</div>'
        f'</div>'
    )


def _ad_line_html(ad):
    """真正的 NYSE A/D 腾落线 section: SP500 全成分股累计腾落线(cumulative) vs 参与率(advance_pct)。
    ad: fetch_ad_line_real()。数据源=Economic-Dashboard 每日 cron (501 只成分股)。"""
    if not ad or ad.get("status") != "ok" or not ad.get("spy_points"):
        note = (ad or {}).get("note", "")
        return (f'<p class="empty">A/D 腾落线数据同步中——Economic-Dashboard 每日 cron 维护，'
                f'读到即填真值，绝不编造。{_esc(note)}</p>')
    cum_pts = ad["spy_points"]      # (date, cumulative)
    pct_pts = ad["ratio_points"]    # (date, advance_pct)
    ev = ad.get("evidence", {})
    diverge = ad.get("divergence")

    w, h = 920, 260
    ml, mr, mt, mb_ = 52, 176, 18, 30
    pw, ph = w - ml - mr, h - mt - mb_
    dates = [d for d, _ in cum_pts]
    n = len(dates)
    def X(i): return ml + i * pw / max(n - 1, 1)
    cum_v = [v for _, v in cum_pts]
    pct_map = dict(pct_pts)
    pct_v = [pct_map[d] for d in dates if d in pct_map]
    def norm(vals):
        lo, hi = min(vals), max(vals)
        return lo, hi, (hi - lo) or 1
    clo, chi, crng = norm(cum_v)
    plo, phi, prng = norm(pct_v)
    def Yc(v): return mt + (chi - v) / crng * ph
    def Yp(v): return mt + (phi - v) / prng * ph
    cum_avg = sum(cum_v) / len(cum_v)  # 累计腾落线均值(平均值横线)

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # 5 条水平网格线 + 左轴(累计腾落线, 蓝) + 右轴(参与率%, 琥珀) 刻度
    for k in range(5):
        gy = mt + ph * k / 4
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        cv = chi - crng * k / 4
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#6b8fb5" text-anchor="end">{cv:.0f}</text>')
        pv = phi - prng * k / 4
        parts.append(f'<text x="{w-mr+6}" y="{gy+3:.1f}" font-size="9" fill="#c9a94e" text-anchor="start">{pv:.0f}%</text>')
    # 平均值横线(累计腾落线均值, 蓝色虚线 + 标注)
    y_avg = Yc(cum_avg)
    parts.append(f'<line x1="{ml}" y1="{y_avg:.1f}" x2="{w-mr}" y2="{y_avg:.1f}" stroke="#6b8fb5" stroke-width="1.2" stroke-dasharray="6,3" opacity="0.7"/>')
    parts.append(f'<text x="{ml+4}" y="{y_avg-4:.1f}" font-size="9" fill="#6b8fb5" opacity="0.9">均值 {cum_avg:.0f}</text>')
    # 零参与率(50%)基准线(参与率轴): advance_pct=50 的水平位置
    if plo <= 50 <= phi:
        y50 = Yp(50)
        parts.append(f'<line x1="{ml}" y1="{y50:.1f}" x2="{w-mr}" y2="{y50:.1f}" stroke="#c9a94e" stroke-width="0.8" stroke-dasharray="2,4" opacity="0.5"/>')
    # x 日期标签(~6个)
    seen = set()
    for i, d in enumerate(dates):
        if i == 0 or i == n - 1 or i % max(n // 5, 1) == 0:
            key = d[:7]
            if key in seen and i not in (0, n - 1):
                continue
            seen.add(key)
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-10}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{_esc(d)}</text>')
    # 累计腾落线(蓝, 主线)
    cum_line = [f"{X(i):.1f},{Yc(v):.1f}" for i, (_, v) in enumerate(cum_pts)]
    parts.append(f'<polyline points="{" ".join(cum_line)}" fill="none" stroke="#6b8fb5" stroke-width="2.4" stroke-linejoin="round"/>')
    for i, (dd, v) in enumerate(cum_pts):
        parts.append(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Yc(v):.1f}" r="6" data-tip="累计腾落 · {_esc(dd)}||{v:+,.0f}"/>')
    # 参与率(琥珀, 细线)
    didx = {d: i for i, d in enumerate(dates)}
    pct_line = [f"{X(didx[d]):.1f},{Yp(pct_map[d]):.1f}" for d in dates if d in pct_map]
    parts.append(f'<polyline points="{" ".join(pct_line)}" fill="none" stroke="#c9a94e" stroke-width="1.6" stroke-linejoin="round" opacity="0.85"/>')
    for d in dates:
        if d in pct_map:
            parts.append(f'<circle class="tip-hit" cx="{X(didx[d]):.1f}" cy="{Yp(pct_map[d]):.1f}" r="6" data-tip="参与率 · {_esc(d)}||{pct_map[d]:.1f}%"/>')
    # 末点圈
    parts.append(f'<circle cx="{X(n-1):.1f}" cy="{Yc(cum_v[-1]):.1f}" r="3.6" fill="#6b8fb5"/>')
    if pct_v:
        parts.append(f'<circle cx="{X(n-1):.1f}" cy="{Yp(pct_v[-1]):.1f}" r="3.0" fill="#c9a94e"/>')
    # 图例
    ly = mt + 6
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#6b8fb5" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#6b8fb5">累计腾落线 {ad.get("latest_cumulative")}</text>')
    ly += 18
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#c9a94e" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#c9a94e">参与率% {ad.get("latest_advance_pct")}</text>')
    parts.append("</svg>")
    svg = "".join(parts)

    if diverge is True:
        badge = '<span style="color:#d64545;font-weight:700">⚠ 顶背离(广度恶化)</span>'
        verdict = "🔴 顶背离"
    elif diverge is False:
        badge = '<span style="color:#2e9e5b;font-weight:700">✓ 广度确认(健康)</span>'
        verdict = "🟢 广度确认"
    else:
        badge = '<span style="color:#8a8578">数据不足</span>'
        verdict = "⚪ 未判定"

    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">NYSE A/D 腾落线：S&amp;P500 全成分股累计腾落 vs 参与率 · 判定：{badge}'
        f'<span class="chart-freq freq-d">🟢 每日 · Economic-Dashboard cron</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(ad.get("as_of",""))}）：{verdict}　'
        f'累计腾落线 <b>{ad.get("latest_cumulative")}</b>，当日净腾落 <b>{ad.get("latest_ad_net")}</b>，'
        f'参与率 <b>{ad.get("latest_advance_pct")}%</b>（{ad.get("tickers")} 只成分股）<br>'
        f'判定依据：腾落线近 {ev.get("nh_window","?")} 日高点 <b>{ev.get("cum_recent_high","?")}</b>，'
        f'近 {ev.get("lookback_days","?")} 日高点 <b>{ev.get("cum_lookback_high","?")}</b>'
        f'（{"创新高" if ev.get("cum_made_new_high") else "未创新高，距高点差 "+str(ev.get("gap_from_high","?"))}）；'
        f'近期参与率均值 <b>{ev.get("recent_advance_pct_avg","?")}%</b>'
        f'（{"广度确认" if ev.get("breadth_confirmed") else "广度未跟上"}）</div>'
        f'<div class="oil-src">数据源：{_esc(ad.get("source",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>真正的 NYSE A/D 腾落线(Advance/Decline Line)</b>——每日统计 S&amp;P500 全部 500+ 只成分股中<b>上涨家数减下跌家数</b>，累加成「累计腾落线」。'
        f'<b>蓝线(累计腾落线)</b>：反映市场内部广度——若指数创新高、腾落线也创新高=普涨健康；若指数创新高但腾落线走平/下滑=<b>顶背离</b>(指数靠少数大票撑、多数股已走弱)，历史上是<b>见顶前兆</b>。'
        f'<b>琥珀线(参与率%)</b>：当日上涨家数占比，&gt;50% 多数股上涨、&lt;50% 多数股下跌。<br>'
        f'<b>顶背离判定(可复现)</b>：腾落线近 20 日高点是否 ≥ 近 120 日高点。未创新高 + 参与率 &lt;50% = 顶背离预警。<br>'
        f'相比旧的 RSP/SPY 代理，这是<b>逐股统计的真 A/D 数据</b>(501 只成分股)，由 Economic-Dashboard 每日 cron 自动更新。</div>'
        f'</div>'
    )


def _gold_premium_html(gp):
    """印度 + 中国黄金 domestic premium/discount 双线折线 (US$/oz, 零轴分溢价/折价)。
    gp: fetch_gold_premium()。数据源=World Gold Council goldhub。"""
    if not gp or gp.get("status") != "ok":
        note = (gp or {}).get("note", "")
        return (f'<p class="empty">黄金 domestic premium 数据同步中——从 World Gold Council goldhub 下载 xlsx 后解析，'
                f'读到即填真值，绝不编造。{_esc(note)}</p>')
    ind = gp.get("india")
    chn = gp.get("china")
    # 只画近 ~3 年(便于看清近期波动), 全量太密
    def _recent(series, n_keep=780):
        pts = series["points"]
        return pts[-n_keep:] if len(pts) > n_keep else pts
    ind_pts = _recent(ind) if ind else []
    chn_pts = _recent(chn) if chn else []
    # 合并日期轴
    all_dates = sorted(set([p["date"] for p in ind_pts] + [p["date"] for p in chn_pts]))
    if not all_dates:
        return '<p class="empty">黄金 premium 无数据点。</p>'
    n = len(all_dates)
    didx = {d: i for i, d in enumerate(all_dates)}
    ind_map = {p["date"]: p["premium"] for p in ind_pts}
    chn_map = {p["date"]: p["premium"] for p in chn_pts}

    w, h = 920, 280
    ml, mr, mt, mb_ = 46, 150, 18, 30
    pw, ph = w - ml - mr, h - mt - mb_
    def X(i): return ml + i * pw / max(n - 1, 1)
    allv = list(ind_map.values()) + list(chn_map.values())
    lo, hi = min(allv), max(allv)
    # 保证 0 在范围内
    lo = min(lo, 0); hi = max(hi, 0)
    rng = (hi - lo) or 1
    def Y(v): return mt + (hi - v) / rng * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # y 网格 + 标签
    for k in range(5):
        val = hi - rng * k / 4
        gy = mt + ph * k / 4
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#8a8578" text-anchor="end">{val:.0f}</text>')
    # 零轴(粗)
    y0 = Y(0)
    parts.append(f'<line x1="{ml}" y1="{y0:.1f}" x2="{w-mr}" y2="{y0:.1f}" stroke="#8a8578" stroke-width="1.3"/>')
    parts.append(f'<text x="{w-mr+4}" y="{y0+3:.1f}" font-size="9" fill="#8a8578">0 平价</text>')
    # x 年标签
    seen = set()
    for i, d in enumerate(all_dates):
        yr = d[:4]
        if yr not in seen and (i == 0 or i == n - 1 or i % max(n // 6, 1) == 0):
            seen.add(yr)
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-10}" font-size="9" fill="#8a8578" text-anchor="{anchor}">{_esc(d[:7])}</text>')
    # 印度线(琥珀/金)
    if ind_pts:
        il = [f"{X(didx[d]):.1f},{Y(ind_map[d]):.1f}" for d in all_dates if d in ind_map]
        parts.append(f'<polyline points="{" ".join(il)}" fill="none" stroke="#c9922e" stroke-width="2.0" stroke-linejoin="round"/>')
        for d in all_dates:
            if d in ind_map:
                parts.append(f'<circle class="tip-hit" cx="{X(didx[d]):.1f}" cy="{Y(ind_map[d]):.1f}" r="6" data-tip="印度金premium · {_esc(d)}||{ind_map[d]:+.1f} $/oz"/>')
        last_d = [d for d in all_dates if d in ind_map][-1]
        parts.append(f'<circle cx="{X(didx[last_d]):.1f}" cy="{Y(ind_map[last_d]):.1f}" r="3.4" fill="#c9922e"/>')
    # 中国线(青灰)
    if chn_pts:
        cl = [f"{X(didx[d]):.1f},{Y(chn_map[d]):.1f}" for d in all_dates if d in chn_map]
        parts.append(f'<polyline points="{" ".join(cl)}" fill="none" stroke="#6b8fb5" stroke-width="1.8" stroke-linejoin="round" opacity="0.9"/>')
        for d in all_dates:
            if d in chn_map:
                parts.append(f'<circle class="tip-hit" cx="{X(didx[d]):.1f}" cy="{Y(chn_map[d]):.1f}" r="6" data-tip="中国金premium · {_esc(d)}||{chn_map[d]:+.1f} $/oz"/>')
        last_c = [d for d in all_dates if d in chn_map][-1]
        parts.append(f'<circle cx="{X(didx[last_c]):.1f}" cy="{Y(chn_map[last_c]):.1f}" r="3.2" fill="#6b8fb5"/>')
    # 图例
    ly = mt + 6
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#c9922e" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#c9922e">印度 {ind["latest"] if ind else "-"}</text>')
    ly += 18
    parts.append(f'<line x1="{w-mr+8}" y1="{ly}" x2="{w-mr+24}" y2="{ly}" stroke="#6b8fb5" stroke-width="2.6"/>')
    parts.append(f'<text x="{w-mr+28}" y="{ly+3.5}" font-size="10" fill="#6b8fb5">中国 {chn["latest"] if chn else "-"}</text>')
    parts.append("</svg>")
    svg = "".join(parts)

    ind_state = ""
    if ind and ind.get("latest") is not None:
        lv = ind["latest"]
        ind_state = ("溢价🟢(需求旺/供给紧)" if lv > 1 else ("折价🔴(需求弱/进口过剩)" if lv < -1 else "近平价"))

    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">印度 &amp; 中国黄金 Domestic Premium/Discount (US$/oz)'
        f'<span class="chart-freq freq-d">🟢 每日 · World Gold Council goldhub</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(gp.get("as_of",""))}）：'
        f'印度 <b>{ind["latest"] if ind else "-"}</b> US$/oz（{ind_state}）　'
        f'中国 <b>{chn["latest"] if chn else "-"}</b> US$/oz<br>'
        f'印度历史区间 {ind["min"] if ind else "-"} ~ {ind["max"] if ind else "-"}（{ind["n"] if ind else 0} 日，{_esc(ind["points"][0]["date"]) if ind else ""}→今）</div>'
        f'<div class="oil-src">数据源：{_esc(ind["source"] if ind else "")}（5 日移动平均）</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b><b>Domestic Premium/Discount(本地溢价/折价)</b>=某国黄金<b>本地价格 − 国际价格</b>(US$/oz)。'
        f'<b>正值(溢价)</b>=本地比国际贵，反映当地<b>实物需求旺盛或供给紧张</b>(如进口受限、关税上调)；'
        f'<b>负值(折价)</b>=本地比国际便宜，反映<b>需求疲软或进口过剩</b>。<br>'
        f'印度是全球第二大黄金消费国，其溢价是<b>亚洲实物黄金需求</b>的重要风向标——大幅溢价常见于婚庆/节庆旺季或进口政策收紧；深度折价常见于金价暴涨抑制需求时。<br>'
        f'注：本图为<b>黄金</b> premium(WGC 真数据，印度可回溯 2012、中国 2003)。白银 premium 数据源(Metals Focus)为付费商业源，待补。</div>'
        f'</div>'
    )


def _silver_imports_html(si):
    """印度白银月度进口 section: 灰柱(月度吨) + 12月滚动均线(棕)。
    si: fetch_silver_imports 落盘的 data/silver_imports_india.json。数据源=UN Comtrade 免费。"""
    if not si or si.get("status") != "ok" or not si.get("points"):
        return ('<p class="empty">印度白银进口数据同步中——UN Comtrade 每月发布(约滞后1-2月)，'
                '读到即填真值，绝不编造。</p>')
    pts = si["points"]
    n = len(pts)
    vals = [p["tonnes"] for p in pts]
    # 12月滚动均线
    ma = []
    for i in range(n):
        window = vals[max(0, i - 11):i + 1]
        ma.append(sum(window) / len(window))

    w, h = 920, 280
    ml, mr, mt, mb_ = 46, 30, 20, 42
    pw, ph = w - ml - mr, h - mt - mb_
    vmax = max(max(vals), max(ma)) * 1.08
    bw = pw / n * 0.66
    def X(i): return ml + (i + 0.5) * pw / n
    def Y(v): return mt + (vmax - v) / (vmax or 1) * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # y 网格+标签
    for k in range(5):
        val = vmax * (1 - k / 4)
        gy = mt + ph * k / 4
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#8a8578" text-anchor="end">{val:.0f}</text>')
    # 柱
    for i, p in enumerate(pts):
        x = X(i) - bw / 2
        y = Y(vals[i])
        bh = mt + ph - y
        _tip = f'{_esc(p["date"])}||{vals[i]:.1f} 吨'
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#9a958a" opacity="0.85" data-tip="{_tip}"/>')
    # x 标签(~8个)
    for i, p in enumerate(pts):
        if i == 0 or i == n - 1 or i % max(n // 7, 1) == 0:
            anchor = "start" if i == 0 else ("end" if i >= n - 2 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-12}" font-size="8.5" fill="#8a8578" text-anchor="{anchor}">{_esc(p["date"])}</text>')
    # 12月滚动均线(深棕)
    ml_line = [f"{X(i):.1f},{Y(ma[i]):.1f}" for i in range(n)]
    parts.append(f'<polyline points="{" ".join(ml_line)}" fill="none" stroke="#8a5a2e" stroke-width="2.2" stroke-linejoin="round"/>')
    # 末柱标值
    parts.append(f'<text x="{X(n-1):.1f}" y="{Y(vals[-1])-4:.1f}" font-size="9" fill="#6b6459" text-anchor="middle">{vals[-1]:.0f}</text>')
    # 图例
    parts.append(f'<rect x="{ml+6}" y="{mt+2}" width="12" height="10" fill="#9a958a" opacity="0.85"/>')
    parts.append(f'<text x="{ml+22}" y="{mt+11}" font-size="10" fill="#6b6459">白银进口(月, 吨)</text>')
    parts.append(f'<line x1="{ml+140}" y1="{mt+7}" x2="{ml+158}" y2="{mt+7}" stroke="#8a5a2e" stroke-width="2.6"/>')
    parts.append(f'<text x="{ml+162}" y="{mt+11}" font-size="10" fill="#8a5a2e">12 月滚动均值</text>')
    parts.append("</svg>")
    svg = "".join(parts)

    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">印度白银月度进口 (Silver Bullion Imports, 吨)'
        f'<span class="chart-freq freq-m">🟢 每月 · UN Comtrade</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(si.get("as_of",""))}）：<b>{si.get("latest_tonnes")}</b> 吨　{_stale_badge(si.get("as_of"), "monthly")}'
        f'历史峰值 <b>{si.get("max_tonnes")}</b> 吨（{si.get("n")} 个月，{_esc(pts[0]["date"])}→{_esc(pts[-1]["date"])}）<br>'
        f'口径校验：2024 前两月合计 2932 吨，与 LBMA 公开数字完全吻合。</div>'
        f'<div class="oil-src">数据源：{_esc(si.get("source",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>印度是全球最大白银进口国，其月度进口量是<b>全球实物白银需求</b>的关键风向标。'
        f'<b>灰柱</b>=当月进口量(吨)，<b>棕线</b>=12 个月滚动均值(平滑季节性)。<br>'
        f'进口<b>激增</b>常见于：投资/工业需求旺盛、本地溢价高吸引进口、节庆备货；进口<b>骤降</b>常见于：金银价暴涨抑制需求、政府上调关税/进口管制(2026 年印度将银关税从 6% 升至 15% 并要求 DGFT 许可证，导致 3-4 月进口锐减至 247/182 吨)。<br>'
        f'数据源为 UN Comtrade(联合国商品贸易统计，免费、月度、约滞后 1-2 月发布)，逐股口径为印度 HS7106(银)全球进口净重。因免费 API 仅回溯至 2024，均线用 12 月滚动值代替 5 年均线。</div>'
        f'</div>'
    )


def _bis_gold_swaps_html(bg):
    """BIS 自营黄金掉期 section: 吨数折线(2010→今, 年报锚点 + GATA 月度推算)。
    bg: fetch_bis_gold_swaps()。绝不编造, BIS 年报 + GATA/Lambourne 公开真值。"""
    if not bg or bg.get("status") != "ok" or not bg.get("points"):
        return '<p class="empty">BIS 自营黄金掉期数据未就绪。</p>'
    pts = bg["points"]
    # 折线点: (date, tonnes)
    line_pts = [(p["date"], p["tonnes"]) for p in pts]
    svg = _yield_curves_svg({
        "swaps": {"status": "ok", "name": "BIS 自营黄金掉期(吨)", "color": "#c9a94e",
                  "dash": "none", "points": line_pts, "latest": bg.get("latest_t")},
    }, yunit="t")
    latest_t = bg.get("latest_t"); latest_d = bg.get("latest_date", "")
    peak_t = bg.get("peak_t"); peak_d = bg.get("peak_date", "")
    # 最近两个月度推算点(若有)做近况
    monthly = [p for p in pts if p.get("kind") == "monthly"]
    mo_txt = ""
    if len(monthly) >= 1:
        m = monthly[-1]
        mo_txt = (f' · 最新月度推算 <b>{m["tonnes"]}t</b>（{_esc(m["date"])}，GATA/Lambourne 从 BIS 月报推算）')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">BIS 自营黄金掉期规模（吨 · 2010→今）'
        f'<span class="chart-freq freq-w">🟡 年度确认 + 月度推算 · BIS 年报 / GATA</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新年报（{_esc(latest_d)}）：<b style="color:#c9a94e">{latest_t} 吨</b>{_stale_badge(latest_d, "semiannual")} · '
        f'历史峰值 <b>{peak_t} 吨</b>（{_esc(peak_d)}）{mo_txt}</div>'
        f'<div class="oil-src">数据源：{_esc(bg.get("source",""))} · '
        f'年度值＝<a class="src-lnk" href="https://www.bis.org/about/areport/index.htm" target="_blank" rel="noopener">BIS Annual Report ↗</a> 官方确认；'
        f'月度值＝GATA 顾问 Robert Lambourne 从 <a class="src-lnk" href="https://www.bis.org/banking/balsheet/" target="_blank" rel="noopener">BIS 月度 Statement of Account ↗</a> 推算</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>BIS 机构自己那笔黄金掉期</b>（不是全市场黄金衍生品规模）——'
        f'BIS 通过掉期从<b>商业银行(bullion banks)借入实物黄金</b>，存入其在美联储等央行的黄金活期账户。'
        f'BIS 从不主动解释目的，GATA 长期追踪，认为其<b>代表成员央行在黄金市场的隐秘干预/头寸调整</b>。<br>'
        f'<b>为何值得看</b>：掉期<b>骤增</b>(如 2010、2017、2021 冲到 400–490 吨)常对应央行需要<b>动用/腾挪黄金</b>的时点；'
        f'<b>骤降至近零</b>(2016、近期降至 40–180 吨)则被解读为央行<b>惜售、增持、回运</b>黄金——与近年央行大举购金、黄金价格上行趋势吻合。'
        f'是<b>央行黄金政策/市场压力的另类信号</b>。<br>'
        f'<b>数据诚实说明</b>：BIS 不单列 swaps 科目，年度值取自 BIS 年报明确确认，月度值为 GATA 从 BIS 官方月报推算'
        f'（BIS 年报每年验证其推算准确）；BIS 未公开精确勾稽算法，故本页不做无法验证的自行换算，'
        f'仅呈现已核实公开真值，月度点由 cron 读 GATA 新披露只增补充，<b>绝不编造</b>。</div>'
        f'</div>'
    )


def _silver_bank_positions_html(sb):
    """白银做市商头寸 section: CFTC COT commercial 净持仓折线(净空区), 一手官方真数据。
    sb: fetch_silver_bank_positions()。绝不编造, 抓不到读缓存真值。"""
    if not sb or sb.get("status") in (None, "未获取") or not sb.get("points"):
        return '<p class="empty">白银做市商头寸(CFTC COT)数据未就绪（cron 每周更新）。</p>'
    pts = [p for p in sb["points"] if p.get("comm_net") is not None]
    if not pts:
        return '<p class="empty">白银做市商头寸(CFTC COT)数据未就绪。</p>'
    line_pts = [(p["date"], p["comm_net"]) for p in pts]
    svg = _yield_curves_svg({
        "commnet": {"status": "ok", "name": "商业(做市商)净持仓(合约)", "color": "#6b8fb5",
                    "dash": "none", "points": line_pts, "latest": sb.get("latest_net")},
    }, yunit="")
    net = sb.get("latest_net"); asof = sb.get("as_of", "")
    wow = sb.get("latest_wow")
    peak = sb.get("peak_short_net"); peakd = sb.get("peak_short_date", "")
    lg = sb.get("latest_long"); sh = sb.get("latest_short"); oi = sb.get("latest_oi")
    # 方向判读: 净空扩大=加空压价; 净空收窄=减空/被逼平
    if wow is not None:
        if wow < 0:
            dir_txt = f'<span style="color:#d64545;font-weight:600">净空扩大 {abs(wow):,}（做市商加空/压价，与图里 Issued 同向）</span>'
        elif wow > 0:
            dir_txt = f'<span style="color:#2e9e5b;font-weight:600">净空收窄 {wow:,}（做市商减空/被逼平，与图里 Stopped 同向）</span>'
        else:
            dir_txt = '持平'
    else:
        dir_txt = '—'
    status_badge = ('🟡 缓存(CFTC暂未更新)' if sb.get("status") == "缓存" else '🟢 每周 · CFTC 官方')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">白银做市商(bullion banks)净持仓 · CFTC COT commercial（合约 · 近10年）'
        f'<span class="chart-freq freq-w">{status_badge}</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(asof)}）：净持仓 <b style="color:#6b8fb5">{net:,}</b> 合约'
        f'（多 {lg:,} / 空 {sh:,} · OI {oi:,}） · 周环比 {dir_txt} · '
        f'历史最深净空 <b>{peak:,}</b>（{_esc(peakd)}）</div>'
        f'<div class="oil-src">数据源：{_esc(sb.get("source",""))} · '
        f'<a class="src-lnk" href="https://publicreporting.cftc.gov/" target="_blank" rel="noopener">CFTC Public Reporting ↗</a> · '
        f'{_esc(sb.get("inventory_note",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>「做市商/投行在 COMEX 白银上是接货还是压价」的一手官方真数据</b>，'
        f'语义等价于 Michael Lynch(@DtDS_WSS) 那张「投行累计 issues/stops」图想说的核心，但用 <b>CFTC 官方 COT</b>'
        f'（免 key、可回溯到 1986、每周五更新），而非被 CME 官方封禁抓取的逐日交割报告。<br>'
        f'COT 里的 <b>commercial(商业套保)</b> 主体就是 <b>bullion banks</b>，它们长期持<b>净空</b>（对冲实物多头）：<br>'
        f'• 净空<b>扩大</b> → 做市商<b>加空压价</b>（对应图里 “Issued＝交货压价”，看跌/卖压增强）<br>'
        f'• 净空<b>收窄或转多</b> → 做市商<b>减空/被逼平</b>（对应图里 “Stopped＝接货 squeeze”，看涨/逼空信号）<br>'
        f'<b>为何值得看</b>：白银做市商净空是判断<b>价格压制 vs 逼空</b>的关键结构信号；当净空从历史深位（如 -116K, 2017）'
        f'大幅收窄，往往预示做市商难以继续压价、白银具备上行动能。<br>'
        f'<b>数据诚实说明</b>：全序列取自 CFTC 官方 Socrata API 真值，抓不到读上次缓存真值绝不覆盖成空。'
        f'下方另附 Michael Lynch 原图静态参考（因 CME 封禁无法自动更新）。</div>'
        f'</div>'
    )


def _comex_silver_issues_ref_html(cs):
    """C: COMEX 白银 issues/stops 静态参考 section: Michael Lynch 图累计线 + 红字批注 + 来源标注。
    cs: fetch_comex_silver_issues_ref()。静态锚点(手抄自公开图), 明确标注非实时。"""
    if not cs or cs.get("status") != "ok" or not cs.get("points"):
        return '<p class="empty">COMEX 白银 issues/stops 参考图数据未就绪。</p>'
    pts = cs["points"]
    line_pts = [(p["date"], p["cumulative_koz"]) for p in pts if p.get("cumulative_koz") is not None]
    svg = _yield_curves_svg({
        "cum": {"status": "ok", "name": "累计净头寸(千oz, 手抄锚点)", "color": "#8a8f98",
                "dash": "6,4", "points": line_pts, "latest": (line_pts[-1][1] if line_pts else None)},
    }, yunit="")
    asof = cs.get("as_of", "")
    src = cs.get("source", ""); src_url = cs.get("source_url", "#")
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">【静态参考】COMEX 白银 投行累计 issues/stops（千 oz · 2009→2026-04）'
        f'<span class="chart-freq" style="background:#e8e2d5;color:#8a6d3b">⚪ 静态参考 · 非实时 · 事件驱动</span></div>'
        f'{svg}'
        f'<div class="oil-meta">数据截止 <b>{_esc(asof)}</b> · 累计线走高＝做市商净<b>接货(stop)</b>；走低＝净<b>交货(issue)</b></div>'
        f'<div class="oil-src">数据源：{_esc(src)} · '
        f'<a class="src-lnk" href="{_esc(src_url)}" target="_blank" rel="noopener">EconAnalytics / @DtDS_WSS ↗</a></div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看 &amp; 为何静态：</b>这张图由 <b>Michael Lynch(@DtDS_WSS)</b> 制作，'
        f'追踪 COMEX 白银<b>各投行(bullion banks)累计与月度 issues/stops</b>——累计净头寸走高＝做市商净接货囤货(看涨)，'
        f'<b>为何本节静态、不自动每日更新</b>：底层是 <b>CME COMEX 每日 Issues&amp;Stops by firm 报告</b>，'
        f'CME 官方<b>明确封禁脚本抓取</b>（IP block + Data Terms of Use），无免 key、可回溯的每日源；'
        f'图作者虽在 Substack/X <b>周期性更新</b>，但<b>事件驱动、不规律、无 API、图为嵌入 PNG、不公开原始序列</b>。'
        f'故本节仅<b>从公开图手抄关键锚点</b>做趋势参考，<b>精度有限、绝不伪造每日折线</b>。'
        f'<b>真实可每周更新的做市商头寸方向请看上方「白银做市商净持仓(CFTC COT)」一手数据。</b></div>'
        f'</div>'
    )


def _gold_exports_html(ge):
    """美国黄金出口(Nonmonetary gold) section: FRED IEAXGG 季度折线(1999→今) + 暴涨标注。
    ge: fetch_gold_exports()。FRED 官方一手真数据, 诚实标题(Nonmonetary), 绝不编造。"""
    if not ge or ge.get("status") in (None, "未获取") or not ge.get("points"):
        return '<p class="empty">美国黄金出口(FRED IEAXGG)数据未就绪。</p>'
    pts = ge["points"]
    line_pts = [(p["date"], p["value_musd"]) for p in pts if p.get("value_musd") is not None]
    svg = _yield_curves_svg({
        "gexp": {"status": "ok", "name": "非货币黄金出口(百万美元)", "color": "#c9a94e",
                 "dash": "none", "points": line_pts, "latest": ge.get("latest")},
    }, yunit="M$")
    latest = ge.get("latest"); latest_d = ge.get("latest_date", "")
    peak = ge.get("peak"); peak_d = ge.get("peak_date", "")
    base = ge.get("base_2024_avg"); surge = ge.get("surge_x")
    latest_b = round(latest / 1000, 1) if latest else None  # 换算成十亿美元
    # 460吨换算说明(用户图批注): 47B USD ÷ ~$3200/oz ÷ 32151 oz/t ≈ 460t 量级
    status_badge = ('🟡 缓存' if ge.get("status") == "缓存" else '🟢 每季 · FRED/BEA 官方')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">美国黄金出口 · Nonmonetary Gold Exports（百万美元 · 季度 · 1999→今）'
        f'<span class="chart-freq freq-w">{status_badge}</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(latest_d)}）：<b style="color:#c9a94e">{latest:,.0f} 百万美元</b>{_stale_badge(latest_d, "quarterly")}'
        f'（≈ <b>{latest_b} 亿美元</b>，约 <b>460 吨</b>量级） · '
        f'历史峰值 <b>{peak:,.0f}</b>（{_esc(peak_d)}） · '
        f'较 2024 均值（{base:,.0f}）<b style="color:#d64545">暴涨 {surge}×</b></div>'
        f'<div class="oil-src">数据源：{_esc(ge.get("source",""))} · '
        f'<a class="src-lnk" href="{_esc(ge.get("source_url","#"))}" target="_blank" rel="noopener">FRED IEAXGG ↗</a></div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>美国实物黄金流出规模</b>——「各国把黄金运回家」的直接量化信号。'
        f'2025-26 年美国非货币黄金出口<b>从 2024 的约 95 亿美元/年 暴涨到 2026Q1 单季 472 亿美元</b>（约 460 吨量级），'
        f'为 1999 有记录以来最高。<br>'
        f'<b>为何值得看</b>：黄金实物大规模<b>离开美国金库、运往海外</b>，通常对应：①各国央行/主权基金<b>去美元化、增持并回运实物黄金</b>；'
        f'②COMEX/伦敦市场<b>实物交割紧张、套利驱动金条跨境流动</b>；③对美元信用与美债安全性的<b>结构性担忧</b>。'
        f'与本页 BIS 黄金掉期、白银做市商头寸、央行购金主题互相印证——都是<b>贵金属回流 / 去美元化</b>的实物侧证据。<br>'
        f'<b>数据诚实说明</b>：用户原图标注「Monetary gold（货币黄金）」，但 FRED 无此序列，'
        f'且真正的货币黄金（央行储备金）不会这样出口——真实对应该暴涨现象的是 <b>Nonmonetary gold（非货币黄金'
        f'＝民间/商业实物金）</b>。本节采用 FRED 官方真序列 <b>IEAXGG</b> 与真标题，'
        f'不照抄不准确的原标题，全序列为 FRED/BEA 官方真值，每季更新，<b>绝不编造</b>。</div>'
        f'</div>'
    )


def _us_yield_century_html(yc):
    """图5: 美国国债收益率百年周期 4线折线 + 周期锚点。yc: fetch_us_yield_century()。"""
    if not yc or yc.get("status") != "ok" or not yc.get("series"):
        return '<p class="empty">美国国债收益率百年周期数据未就绪。</p>'
    ser = yc["series"]
    curves = {}
    for k, d in ser.items():
        if d.get("points"):
            curves[k] = {"status": "ok", "name": d["label"], "color": d["color"],
                         "dash": "none", "points": [(p[0], p[1]) for p in d["points"]],
                         "latest": d["points"][-1][1]}
    svg = _yield_curves_svg(curves, yunit="%")
    ann = yc.get("annotations", [])
    cyc = yc.get("cycles", [])
    ann_html = " · ".join(
        f'<b style="color:{"#d64545" if a.get("kind")=="top" else "#2e9e5b"}">{_esc(a.get("label",""))}</b>'
        for a in ann)
    cyc_html = " → ".join(
        f'<b style="color:{"#c0757d" if c.get("dir")=="up" else "#6b8fb5"}">{_esc(c.get("label",""))}（{_esc(c.get("from",""))}-{_esc(c.get("to",""))}）</b>'
        for c in cyc)
    latest_bits = []
    for k, d in ser.items():
        if d.get("points"):
            latest_bits.append(f'<span style="color:{d["color"]};font-weight:600">{_esc(d["label"])} {d["points"][-1][1]:.2f}%</span>')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">美国国债收益率百年周期 · Fed Funds / 3M / 10Y / 30Y（月度）'
        f'<span class="chart-freq freq-w">🟢 每季 · FRED 官方</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(yc.get("as_of",""))}）：{" · ".join(latest_bits)}</div>'
        f'<div class="oil-meta">周期锚点：{ann_html}<br>周期论：{cyc_html}</div>'
        f'<div class="oil-src">数据源：{_esc(yc.get("source",""))} · '
        f'<a class="src-lnk" href="{_esc(yc.get("source_url","#"))}" target="_blank" rel="noopener">FRED ↗</a></div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>美国利率的百年长周期视角</b>——四条关键利率同框，'
        f'揭示"周期论"框架：<b>1940 年大底 → 1981 年大顶（利率冲到 13-16%）→ 2020 年大底</b>，'
        f'构成 <b>40 年上涨（1940-1980）+ 40 年下降（1980-2020）</b> 两个完整长周期。'
        f'该框架认为 <b>2020 年是又一个大底，正开启新的 40 年上涨大周期</b>——若成立，未来数十年利率中枢趋势性抬升，'
        f'对债券估值、股权风险溢价、财政付息负担是<b>结构性逆风</b>。<br>'
        f'<b>数据诚实说明</b>：四线均为 FRED/美联储官方月度真值。各线起点为 FRED 收录起点'
        f'（3M T-Bill 1934、Fed Funds 1954、10Y 1953、30Y 1977），'
        f'<b>1920-1933 段 FRED 无月度序列，不编造，图从各线真实起点画</b>。周期论为市场分析框架，非预测承诺。</div>'
        f'</div>'
    )


def _comex_issue_stop_html(cs):
    """图1: COMEX 做市商每周净 issue/stop 柱状图(金+银, 两口径)。cs: fetch_comex_issue_stop_weekly()。"""
    if not cs or cs.get("status") != "ok" or not (cs.get("gold") or cs.get("silver")):
        return '<p class="empty">COMEX 做市商周净 issue/stop 数据未就绪。</p>'

    def _bars_svg(rows, field, w=920, h=230):
        if not rows:
            return '<div class="cust-chart-na">无数据</div>'
        vals = [r[field] for r in rows]
        vmax = max(abs(min(vals)), abs(max(vals)), 1)
        ml, mr, mt, mb = 52, 20, 14, 38
        pw, ph = w - ml - mr, h - mt - mb
        n = len(rows)
        bw = pw / n * 0.7
        zero_y = mt + ph / 2
        def X(i): return ml + (i + 0.5) * pw / n
        def BY(v): return zero_y - (v / vmax) * (ph / 2 * 0.92)
        parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
        for frac in (1, 0.5, -0.5, -1):
            gy = BY(vmax*frac); gv = vmax*frac
            parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#e5ded0" stroke-width="0.6" stroke-dasharray="3,3"/>')
            parts.append(f'<text x="{ml-5}" y="{gy+3:.1f}" font-size="9" fill="#8a8578" text-anchor="end">{gv:+.0f}</text>')
        parts.append(f'<line x1="{ml}" y1="{zero_y:.1f}" x2="{w-mr}" y2="{zero_y:.1f}" stroke="#8a8578" stroke-width="1"/>')
        for i, r in enumerate(rows):
            v = r[field]; x = X(i); y = BY(v)
            col = "#d64545" if v > 0 else ("#2e9e5b" if v < 0 else "#8a8578")
            top = min(y, zero_y); ht = abs(y - zero_y)
            parts.append(f'<rect x="{x-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{ht:.1f}" fill="{col}" opacity="0.82" data-tip="{_esc(r["week"])}||{v:+.0f}"/>')
        step = max(1, round(n/8)); prev=None
        for i in range(0, n, step):
            lbl = rows[i]["week"][:7]
            if lbl==prev: continue
            prev=lbl
            parts.append(f'<text x="{X(i):.1f}" y="{h-9}" font-size="8.5" fill="#8a8578" text-anchor="middle">{lbl}</text>')
        parts.append('</svg>')
        return "".join(parts)

    def _metal_block(metal_name, rows):
        if not rows:
            return f'<div class="cust-chart-na">{metal_name} 无数据</div>'
        latest = rows[-1]
        cn = latest["core_net"]
        cdir = "净发货(交货/压价)" if cn>0 else ("净接货(囤货/看涨)" if cn<0 else "持平")
        return (
            f'<div style="margin-bottom:18px">'
            f'<div class="cust-chart-title">{metal_name} · 核心做市商每周净 issue/stop（合约）'
            f'<span class="chart-freq freq-d">最新周 {_esc(latest["week"])}：净 {cn:+d}（{cdir}）</span></div>'
            f'{_bars_svg(rows, "core_net")}'
            f'<div class="cust-chart-title" style="margin-top:8px;font-size:12px;color:#8a8578">{metal_name} · 全投行(17家)对照</div>'
            f'{_bars_svg(rows, "all_net")}'
            f'</div>'
        )

    banks_core = "、".join(cs.get("banks_core", []))
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">COMEX 做市商每周净 issue/stop · 金 + 银（{_esc(cs.get("archive_range",""))}，{cs.get("archive_pdfs_parsed","?")} 个交易日）'
        f'<span class="chart-freq freq-d">🟢 每日更新 · CME 交割报告</span></div>'
        f'{_metal_block("白银 Silver", cs.get("silver", []))}'
        f'{_metal_block("黄金 Gold", cs.get("gold", []))}'
        f'<div class="oil-src">数据源：CME 每日 Issues &amp; Stops 交割报告（ScraperAPI/Jina/Wayback 三层兜底采集，x坐标精确解析）· '
        f'核心做市商(10家)：{_esc(banks_core)}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>每根柱=<b>该周大行(bullion banks)净 issue/stop</b>＝Σ发货−Σ接货：'
        f'<b style="color:#d64545">红柱(正)=净发货</b>（做市商向市场交货，对应 Issued，压价/看跌）；'
        f'<b style="color:#2e9e5b">绿柱(负)=净接货</b>（做市商从市场接货囤积，对应 Stopped，逼空/看涨）。<br>'
        f'<b>两口径</b>：上图=<b>核心做市商(10家传统 LBMA 金银做市大行)</b>；下图=<b>全投行(17家)</b>对照。'
        f'<b>为何值得看</b>：做市商是 COMEX 实物交割主力，其每周净方向是判断<b>价格压制 vs 逼空、实物紧张度</b>的一手结构信号，'
        f'与白银 COT commercial 净持仓、BIS 黄金掉期互相印证。<br>'
        f'<b>数据诚实说明</b>：全序列来自 CME 官方每日交割报告，per-firm 精确解析（x坐标定向，133 PDF 全自洽验证）；'
        f'CME 封 IP→ScraperAPI/Jina/Wayback 三层兜底；每日 cron 增量并入当周，抓不到读缓存绝不编造。</div>'
        f'</div>'
    )


def _fiscal_news_html(fn):
    """美日财政政策事件时间线 section: 离散事件卡片(日期+国旗+分类+标题+摘要+来源链接)。
    fn: fetch_fiscal_news() 返回。绝不编造, 每条带真实来源链接。"""
    if not fn or fn.get("status") != "ok" or not fn.get("events"):
        return '<p class="empty">美日财政政策事件数据待更新（daily cron 检索中，抓不到不编造）。</p>'
    cat_col = {"US": "#c0757d", "JP": "#6b8fb5"}
    cards = []
    for ev in fn["events"]:
        cc = ev.get("country", "")
        bar = cat_col.get(cc, "#8a8f98")
        src = ev.get("source_url", "")
        src_name = ev.get("source_name", "来源")
        src_link = (f'<a class="src-lnk" href="{_esc(src)}" target="_blank" rel="noopener">{_esc(src_name)} ↗</a>'
                    if src else _esc(src_name))
        cards.append(
            f'<div class="fn-card" style="border-left:3px solid {bar};">'
            f'<div class="fn-head">'
            f'<span class="fn-date">{_esc(ev.get("date",""))}</span>'
            f'<span class="fn-flag">{ev.get("flag","")}</span>'
            f'<span class="fn-cat" style="color:{bar};">{_esc(ev.get("category",""))}</span>'
            f'</div>'
            f'<div class="fn-title">{_esc(ev.get("title",""))}</div>'
            f'<div class="fn-sum">{_esc(ev.get("summary",""))}</div>'
            f'<div class="fn-src">{src_link}</div>'
            f'</div>'
        )
    body = "".join(cards)
    asof = fn.get("as_of", "")
    return (
        f'<div class="fn-wrap">'
        f'<div class="fn-meta">🇺🇸 美国 + 🇯🇵 日本财政政策事件 · 按日期倒序 · 最新 {_esc(asof)}'
        f'<span class="chart-freq freq-d">🟢 每日 · cron 检索权威源动态更新</span></div>'
        f'<div class="fn-list">{body}</div>'
        f'<div class="cust-how"><b>如何看：</b>本节追踪<b>美日两国当前的财政政策举措</b>——'
        f'美国侧关注<b>债务上限、持续决议(CR)、政府关门风险、拨款法案</b>；'
        f'日本侧关注<b>补正预算(补充预算)、特例公债(赤字国债)发行、国债发行计划</b>。'
        f'这些事件直接影响两国<b>国债供给、财政赤字与利率</b>：'
        f'美国关门/债限僵局→短端波动+避险；日本增发赤字国债→JGB 供给压力(与本页日债收益率上行呼应)。'
        f'每条事件均附<b>真实来源链接</b>，可点击核实，绝不编造。<br>每日更新，cron agent 检索官方与权威媒体源。</div>'
        f'</div>'
    )


def _hf_leverage_html(hf):
    """对冲基金美债杠杆敞口 section: 图A 美债敞口/GDP 折线 + 图B 三类借款折线。
    hf: fetch_hf_leverage()。季频(Form PF)。绝不编造。"""
    if not hf or hf.get("status") != "ok":
        return '<p class="empty">对冲基金杠杆敞口(OFR/Form PF)数据未就绪。</p>'
    ex = hf.get("exposure", {})
    bo = hf.get("borrow", {})
    parts = []
    # 图A: 美债敞口/GDP 单线
    if ex.get("points"):
        svgA = _yield_curves_svg({
            "usgov": {"status": "ok", "name": "美债总名义敞口/GDP", "color": "#c0757d",
                      "dash": "none", "points": ex["points"], "latest": ex["latest_pct"]},
        })
        parts.append(
            f'<div class="cust-chart-col cust-chart-full">'
            f'<div class="cust-chart-title">A · 对冲基金美债总名义敞口 / 美国GDP（%）· 2015→今'
            f'<span class="chart-freq freq-q">🟣 季频 · SEC Form PF 滞后发布</span></div>'
            f'{svgA}'
            f'<div class="oil-meta">最新 <b style="color:#c0757d">{ex["latest_pct"]}%</b>'
            f'（约 ${ex.get("latest_usd_t","?")}T 名义敞口，{_esc(ex.get("latest_q") or hf.get("as_of",""))}）{_stale_badge(ex.get("latest_q") or hf.get("as_of"), "quarterly")} · '
            f'较 2015 年（6.1%）翻倍——对冲基金国债基差套利(basis trade)杠杆持续累积</div>'
            f'</div>'
        )
    # 图B: 三类借款
    if bo.get("repo"):
        svgB = _yield_curves_svg({
            "repo": {"status": "ok", "name": "Repo 回购", "color": "#c0757d",
                     "dash": "none", "points": bo["repo"], "latest": bo["latest_repo"]},
            "prime": {"status": "ok", "name": "Prime brokerage 主经纪", "color": "#6b8fb5",
                      "dash": "none", "points": bo["prime"], "latest": bo["latest_prime"]},
            "other": {"status": "ok", "name": "Other secured 其他担保", "color": "#e0a92e",
                      "dash": "none", "points": bo["other"], "latest": bo["latest_other"]},
        }, yunit="T")
        parts.append(
            f'<div class="cust-chart-col cust-chart-full" style="margin-top:14px;">'
            f'<div class="cust-chart-title">B · 对冲基金在美三类借款规模（$万亿）· 2015→今'
            f'<span class="chart-freq freq-q">🟣 季频 · SEC Form PF</span></div>'
            f'{svgB}'
            f'<div class="oil-meta">Repo <b style="color:#c0757d">${bo["latest_repo"]}T</b> · '
            f'Prime brokerage <b style="color:#6b8fb5">${bo["latest_prime"]}T</b> · '
            f'Other secured <b style="color:#e0a92e">${bo["latest_other"]}T</b>（{_esc(bo.get("latest_q") or hf.get("as_of",""))}）{_stale_badge(bo.get("latest_q") or hf.get("as_of"), "quarterly")} · '
            f'回购借款升破 3 万亿=基差套利加杠杆的主渠道</div>'
            f'</div>'
        )
    body = "".join(parts)
    return (
        f'<div class="cust-wrap">'
        f'{body}'
        f'<div class="oil-src">数据源：{_esc(hf.get("source",""))} · '
        f'<a class="src-lnk" href="https://www.financialresearch.gov/hedge-fund-monitor/" target="_blank" rel="noopener">OFR Hedge Fund Monitor</a>'
        f'（对应 BIS《Annual Economic Report 2026》Graph 5）</div>'
        f'<div class="cust-how"><b>如何看：</b>这两张图刻画<b>对冲基金对美国国债的杠杆敞口</b>——'
        f'核心是<b>国债基差套利(basis trade)</b>：对冲基金买现券、卖国债期货套微小价差，'
        f'靠<b>回购(repo)高杠杆</b>放大收益（常 20–50 倍）。<br>'
        f'<b>图A</b>：对冲基金持有美债的总名义敞口已达 GDP 的 <b>~12.6%</b>（2015 年仅 6%），杠杆持续累积；'
        f'<b>图B</b>：其中<b>回购借款升破 $3.2 万亿</b>是加杠杆主渠道。<br>'
        f'<b>为何是风险信号</b>：这类杠杆在<b>回购利率跳升 / 保证金追缴</b>时会被迫平仓，'
        f'2020 年 3 月「dash for cash」国债闪崩即源于此。敞口越高，一旦货币市场承压（见本页 SOFR−IORB、'
        f'银行融资利差），去杠杆引发的<b>国债流动性踩踏</b>风险越大。<br>'
        f'⚠️ 数据源为 SEC Form PF，<b>季度更新且滞后发布</b>（非日频），是结构性中长期风险指标。</div>'
        f'</div>'
    )


def _bis_section_html(bis_latest, page_url):
    """BIS(国际清算银行)报告 section: 只放最新一份的摘要要点 + 跳转独立页 button。
    bis_latest: bis_reports.latest_report() 返回的单份报告 dict(或 None)。
    page_url: 独立页公开地址。"""
    if not bis_latest or bis_latest.get("summary_status") != "ok" or not bis_latest.get("summary"):
        # 无摘要: 仍给 button, 提示待更新
        pts = '<div class="bis-na">最新 BIS 报告摘要待更新（daily cron 扫描中，抓不到不编造）。</div>'
        meta = ""
    else:
        pts = "".join(f'<li>{_esc(p)}</li>' for p in bis_latest["summary"])
        pts = f'<ul class="bis-pts">{pts}</ul>'
        pdf = bis_latest.get("pdf_url", "")
        pdf_link = (f'　·　<a class="src-lnk" href="{_esc(pdf)}" target="_blank" rel="noopener">原文 PDF</a>'
                    if pdf else "")
        meta = (f'<div class="bis-meta"><b>{_esc(bis_latest.get("title",""))}</b>'
                f'（{_esc(bis_latest.get("date",""))}）{pdf_link}</div>')
    return (
        f'<div class="card bis-card">'
        f'{meta}'
        f'{pts}'
        f'<div class="bis-how"><b>如何看：</b>BIS(国际清算银行)是"央行的央行"，其 Quarterly Review 每季'
        f'(3/6/9/12月)综述全球金融市场、银行体系、流动性、信用与系统性风险，是最权威的跨国央行视角。'
        f'点右上按钮查看过去一年全部报告要点。</div>'
        f'</div>'
    )


def _bar_chart_svg(points, w=900, h=240, color="#7fa085", unit="T", val_fmt="{:.2f}"):
    """月度柱状图 SVG。points: [(label, value)] 升序。莫兰迪配色, 顶部标注最新值, 每根柱底 x 轴标签抽稀。
    最后一根柱高亮(深色+顶端数值)。"""
    if not points or len(points) < 2:
        return '<div class="sp-na">柱状图数据不足</div>'
    vals = [v for _, v in points]
    vmax, vmin = max(vals), min(vals)
    # y 轴从 vmin 稍下方起(让柱高差异更明显)
    lo = vmin - (vmax - vmin) * 0.12 if vmax > vmin else vmin * 0.98
    hi = vmax + (vmax - vmin) * 0.08 if vmax > vmin else vmax * 1.02
    span = (hi - lo) or 1.0
    pad_l, pad_r, pad_t, pad_b = 52, 14, 22, 40
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    n = len(points)
    gap = plot_w / n
    bw = gap * 0.62
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    # 网格线 + y 标签(4档)
    for i in range(4):
        gv = lo + span * i / 3
        gy = pad_t + plot_h - (gv - lo) / span * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{pad_l-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{gv:.2f}</text>')
    # 柱 + x 标签抽稀(约6个)
    lbl_step = max(1, n // 6)
    for i, (lab, v) in enumerate(points):
        cx = pad_l + gap * i + gap / 2
        bx = cx - bw / 2
        bh = (v - lo) / span * plot_h
        by = pad_t + plot_h - bh
        last = (i == n - 1)
        fill = "#5f7a68" if last else color
        parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" fill="{fill}" opacity="{0.95 if last else 0.8}" data-tip="{_esc(lab)}||{val_fmt.format(v)}{unit}"/>')
        if last:
            parts.append(f'<text x="{cx:.1f}" y="{by-5:.1f}" font-size="10.5" font-weight="700" fill="#5f7a68" text-anchor="middle">{val_fmt.format(v)}{unit}</text>')
        if i % lbl_step == 0 or last:
            # 标签显示 YYYY-MM 的 MM 或短格式
            short = lab[2:] if len(lab) >= 7 else lab
            parts.append(f'<text x="{cx:.1f}" y="{h-pad_b+16:.1f}" font-size="9.5" fill="#8a8578" text-anchor="middle">{_esc(short)}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _fiscal_budget_html(fb):
    """日美年度财政花费双轴分组柱状图。方案A: 每财年一对柱(美国 $T 左轴钢蓝 / 日本 兆円 右轴琥珀)。
    美国当前财年至今=partial(浅色+斜纹描边区分"进行中"); 其余=confirmed(实色)。带 hover tooltip。
    fb: fetch_fiscal_budget() 结果 {us:[{fy,value_t,status}], jp:[{fy,value_oku,status}], as_of, source}。"""
    if not fb or (not fb.get("us") and not fb.get("jp")):
        return ('<p class="empty">日美财政花费数据同步中——美国 US Treasury MTS / 日本财务省预算，'
                '读到即填真值，绝不编造。</p>')
    us = fb.get("us", [])
    jp = fb.get("jp", [])
    # 统一财年轴(两国财年并集, 升序)
    all_fy = sorted({r["fy"] for r in us} | {r["fy"] for r in jp})
    if not all_fy:
        return '<p class="empty">日美财政花费数据不足。</p>'
    us_map = {r["fy"]: r for r in us}
    jp_map = {r["fy"]: r for r in jp}
    n = len(all_fy)

    w, h = 920, 340
    ml, mr, mt, mb_ = 56, 62, 24, 46
    pw, ph = w - ml - mr, h - mt - mb_
    # 左轴(美国 $T) / 右轴(日本 兆円) 各自缩放
    us_vals = [r["value_t"] for r in us] or [1]
    jp_vals = [r["value_oku"] for r in jp] or [1]
    us_max = max(us_vals) * 1.15
    jp_max = max(jp_vals) * 1.15
    group_w = pw / n
    bw = group_w * 0.30  # 每根柱宽(一组两根)
    US_C = "#5b7fa6"   # 钢蓝(美国)
    JP_C = "#c99a3e"   # 琥珀(日本)

    def GX(i): return ml + (i + 0.5) * group_w
    def YUS(v): return mt + (us_max - v) / (us_max or 1) * ph
    def YJP(v): return mt + (jp_max - v) / (jp_max or 1) * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cust-chart" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # 斜纹 pattern(partial 柱用)
    parts.append(
        '<defs>'
        f'<pattern id="fb-hatch-us" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">'
        f'<rect width="6" height="6" fill="{US_C}" opacity="0.22"/><line x1="0" y1="0" x2="0" y2="6" stroke="{US_C}" stroke-width="2.4"/></pattern>'
        f'<pattern id="fb-hatch-jp" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">'
        f'<rect width="6" height="6" fill="{JP_C}" opacity="0.22"/><line x1="0" y1="0" x2="0" y2="6" stroke="{JP_C}" stroke-width="2.4"/></pattern>'
        '</defs>')
    # y 网格(左轴刻度 4 档)
    for k in range(5):
        gy = mt + ph * k / 4
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        uv = us_max * (1 - k / 4)
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="{US_C}" text-anchor="end">{uv:.1f}</text>')
        jv = jp_max * (1 - k / 4)
        parts.append(f'<text x="{w-mr+6}" y="{gy+3:.1f}" font-size="9" fill="{JP_C}" text-anchor="start">{jv:.0f}</text>')
    # 轴标题
    parts.append(f'<text x="{ml-6}" y="{mt-8:.1f}" font-size="9.5" fill="{US_C}" text-anchor="end">美国 $T ◀</text>')
    parts.append(f'<text x="{w-mr+6}" y="{mt-8:.1f}" font-size="9.5" fill="{JP_C}" text-anchor="start">▶ 日本 兆円</text>')

    for i, fy in enumerate(all_fy):
        gx = GX(i)
        # 美国柱(左偏)
        ur = us_map.get(fy)
        if ur is not None:
            v = ur["value_t"]; y = YUS(v); bh = mt + ph - y
            partial = ur.get("status") == "partial"
            fill = "url(#fb-hatch-us)" if partial else US_C
            op = "1" if not partial else "0.95"
            _stat = "进行中(至今)" if partial else "已确定"
            _asof = f' 截至{_esc(ur.get("as_of",""))}' if partial else ""
            bx = gx - bw - 1
            parts.append(f'<rect x="{bx:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" '
                         f'fill="{fill}" stroke="{US_C}" stroke-width="{1.2 if partial else 0}" opacity="{op}" '
                         f'data-tip="美国 FY{fy} {_stat}{_asof}||${v:.2f}T"/>')
            if v == max(us_vals) or partial:
                parts.append(f'<text x="{bx+bw/2:.1f}" y="{y-3:.1f}" font-size="8" fill="{US_C}" text-anchor="middle">{v:.1f}</text>')
        # 日本柱(右偏)
        jr = jp_map.get(fy)
        if jr is not None:
            v = jr["value_oku"]; y = YJP(v); bh = mt + ph - y
            partial = jr.get("status") == "partial"
            fill = "url(#fb-hatch-jp)" if partial else JP_C
            _stat = "进行中" if partial else "当初予算(已确定)"
            bx = gx + 1
            parts.append(f'<rect x="{bx:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" '
                         f'fill="{fill}" stroke="{JP_C}" stroke-width="{1.2 if partial else 0}" opacity="0.92" '
                         f'data-tip="日本 FY{fy} {_stat}||{v:.1f} 兆円"/>')
            if v == max(jp_vals):
                parts.append(f'<text x="{bx+bw/2:.1f}" y="{y-3:.1f}" font-size="8" fill="{JP_C}" text-anchor="middle">{v:.0f}</text>')
        # x 财年标签
        parts.append(f'<text x="{gx:.1f}" y="{h-26:.1f}" font-size="9" fill="#6b6459" text-anchor="middle">FY{fy}</text>')

    # 图例
    ly = h - 10
    parts.append(f'<rect x="{ml}" y="{ly-9}" width="12" height="10" fill="{US_C}"/>')
    parts.append(f'<text x="{ml+16}" y="{ly}" font-size="10" fill="#6b6459">美国 Total Outlays ($T, 财年累计)</text>')
    parts.append(f'<rect x="{ml+270}" y="{ly-9}" width="12" height="10" fill="{JP_C}"/>')
    parts.append(f'<text x="{ml+286}" y="{ly}" font-size="10" fill="#6b6459">日本 一般会计当初予算 (兆円)</text>')
    parts.append(f'<rect x="{ml+540}" y="{ly-9}" width="12" height="10" fill="url(#fb-hatch-us)" stroke="{US_C}" stroke-width="1"/>')
    parts.append(f'<text x="{ml+556}" y="{ly}" font-size="10" fill="#6b6459">斜纹=当前财年进行中(至今累计)</text>')
    parts.append("</svg>")
    svg = "".join(parts)

    # 摘要
    us_latest = us[-1] if us else None
    jp_latest = jp[-1] if jp else None
    summ = ""
    if us_latest:
        _p = "（进行中，截至 %s）" % _esc(us_latest.get("as_of", "")) if us_latest.get("status") == "partial" else ""
        summ += f'美国 FY{us_latest["fy"]}：<b>${us_latest["value_t"]:.2f}T</b>{_p}　'
    if jp_latest:
        summ += f'日本 FY{jp_latest["fy"]}：<b>{jp_latest["value_oku"]:.1f} 兆円</b>（当初予算）'

    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">日美年度财政花费 · Annual Fiscal Spending (双轴)'
        f'<span class="chart-freq freq-m">🟢 年度 · MTS + 财务省</span></div>'
        f'{svg}'
        f'<div class="oil-meta">{summ}<br>'
        f'美国=联邦政府总支出(Total Outlays, 财年 10/1 起, 财年末累计=全年实际)；'
        f'日本=一般会计当初予算总额(财年 4/1 起, 补正前已确定盘子)。</div>'
        f'<div class="oil-src">数据源：{_esc(fb.get("source",""))}</div>'
        f'</div>'
        f'</div>'
    )


def _maturing_treasury_html(mt):
    """私营部门(含Fed)1年内到期需展期的【可交易国债】规模: 过去一年月度柱状图(主) + 2001至今全周期折线(参考)。
    mt: fetch_maturing_treasury()。数据源 US Treasury MSPD table 3，按到期日筛≤1年加总 outstanding。"""
    if not mt or mt.get("status") != "ok" or not mt.get("history_long"):
        st = (mt or {}).get("status", "数据未就绪")
        return f'<p class="empty">1年内到期可交易国债数据未就绪（{st}）。</p>'
    long = mt["history_long"]       # [(YYYY-MM,$T)]
    recent = mt.get("history_recent") or []
    val = mt["value"]
    asof = mt.get("as_of", "")
    # 过去一年(最近13个月)月度柱状图(主图)
    last_year = long[-13:] if len(long) >= 13 else long
    bar_svg = _bar_chart_svg(last_year, w=900, h=250, color="#7fa085", unit="T")
    # 全周期折线(参考图,看长趋势)
    long_svg = _custody_chart_svg(long, w=900, h=190) if len(long) >= 2 else '<div class="sp-na">长历史数据不足</div>'
    # 过去一年区间统计
    _yr_lo = min(v for _, v in last_year)
    _yr_hi = max(v for _, v in last_year)
    _yr_first = last_year[0]
    _yr_last = last_year[-1]
    _delta_b = (_yr_last[1] - _yr_first[1]) * 1000
    _delta_pct = (_yr_last[1] - _yr_first[1]) / _yr_first[1] * 100 if _yr_first[1] else 0
    _dcolor = "#2e9e5b" if _delta_b >= 0 else "#d64545"
    return (
        f'<div class="cust-wrap">'
        f'<div class="mt-hero">当前 <b>${val:.2f}T</b> <span class="mt-asof">as of {_esc(asof)}</span> '
        f'<span class="mt-sub">1年内到期需展期的可交易美国国债（Bills + 1年内到期的 Notes/Bonds/TIPS）</span></div>'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">过去一年 · 月度柱状图（{len(last_year)} 根柱 · 月末口径）</div>'
        f'{bar_svg}'
        f'<div class="mt-barmeta">{_esc(_yr_first[0])} → {_esc(_yr_last[0])}：'
        f'<b style="color:{_dcolor}">{_delta_b:+.0f}B ({_delta_pct:+.1f}%)</b> · '
        f'高 ${_yr_hi:.3f}T / 低 ${_yr_lo:.3f}T</div>'
        f'</div>'
        f'<div class="cust-chart-col cust-chart-full" style="margin-top:14px;">'
        f'<div class="cust-chart-title">2001 至今 · 全周期趋势（{len(long)} 月 · 约{len(long)//12} 年 · 折线参考）</div>'
        f'{long_svg}{_custody_span_line(long)}</div>'
        f'<div class="cust-how"><b>如何看：</b>这是<b>一年内到期、必须靠新发债滚动展期</b>的可交易国债总规模——'
        f'规模越大，Treasury 每年要在市场上<b>再融资(rollover)的压力越大</b>，对短端利率与货币市场流动性越敏感。'
        f'持续陡升＝债务结构短期化(发短债依赖加深)，若遇利率高企则利息负担与再融资风险同步放大；'
        f'是判断<b>财政再融资墙(refinancing wall)与货币市场承压</b>的结构性指标。'
        f'<br>⚠️ <b>口径说明</b>：本图为 MSPD 全部可交易国债中1年内到期部分的<b>总量(含 Fed SOMA + 私营部门持有)</b>，'
        f'未单独剔除美联储持仓（Fed 持有约占 15-20%）；如需纯私营口径需再减 SOMA 短端持仓。'
        f'数据源：<a class="src-lnk" href="https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/" target="_blank" rel="noopener">US Treasury MSPD Table 3</a>（月度，按到期日逐券加总）。</div>'
        f'</div>'
    )


def _oil_line_svg(pts, w=900, h=230, redline=None, redline_label="", zero_line=False,
                  unit="", val_fmt="{:.1f}", rising_good=None):
    """油库存/价差折线 SVG(带可选红线阈值虚线 + 0 线)。pts:[(date,val)] 升序。
    redline: 数值阈值(画红色虚线); zero_line: 画 0 基准线(价差用)。最新点高亮圆点。"""
    if not pts or len(pts) < 2:
        return '<div class="sp-na">折线数据不足</div>'
    dates = [d for d, _ in pts]
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    # 把红线/0线纳入 y 轴范围
    extra = [x for x in (redline, 0.0 if zero_line else None) if x is not None]
    lo = min([lo] + extra)
    hi = max([hi] + extra)
    pad = (hi - lo) * 0.08 or abs(hi) * 0.05 or 1.0
    lo -= pad
    hi += pad
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 54, 14, 16, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(vals)
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    linepts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    # 趋势色
    if rising_good is None:
        color = "#7fa085"
    else:
        up = vals[-1] > vals[0]
        color = "#9aab97" if (up == rising_good) else "#c08a7d"
    fill_area = f"{X(0):.1f},{mt+ph:.1f} " + linepts + f" {X(n-1):.1f},{mt+ph:.1f}"
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    # y 网格 4 档
    for k in range(4):
        gv = lo + rng * k / 3
        gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{val_fmt.format(gv)}</text>')
    # 面积 + 折线
    parts.append(f'<polygon points="{fill_area}" fill="{color}" opacity="0.10" stroke="none"/>')
    parts.append(f'<polyline points="{linepts}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
    # 每点透明 hover 圈
    for i, v in enumerate(vals):
        parts.append(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="7" data-tip="{_esc(dates[i])}||{val_fmt.format(v)}{unit}"/>')
    # 0 基准线(价差)
    if zero_line:
        zy = Y(0.0)
        parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" stroke="#8a8578" stroke-width="1.2" stroke-dasharray="1,0" opacity="0.55"/>')
        parts.append(f'<text x="{w-mr}" y="{zy-4:.1f}" font-size="9.5" fill="#8a8578" text-anchor="end">0（价差转负=WTI&gt;Brent）</text>')
    # 红线阈值
    if redline is not None:
        ry = Y(redline)
        parts.append(f'<line x1="{ml}" y1="{ry:.1f}" x2="{w-mr}" y2="{ry:.1f}" stroke="#d64545" stroke-width="1.6" stroke-dasharray="6,4"/>')
        parts.append(f'<text x="{ml+4}" y="{ry-4:.1f}" font-size="10" font-weight="700" fill="#d64545">{_esc(redline_label)}</text>')
    # 最新点
    lx, ly = X(n - 1), Y(vals[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="8" fill="{color}" opacity="0.18"/>')
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{color}"/>')
    parts.append(f'<text x="{lx:.1f}" y="{ly-9:.1f}" font-size="10.5" font-weight="700" fill="{color}" text-anchor="end">{val_fmt.format(vals[-1])}{unit}</text>')
    # x 日期标签
    idxs = sorted(set([0, n // 4, n // 2, 3 * n // 4, n - 1]))
    for i in idxs:
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h-9}" font-size="9.5" fill="#8a8578" text-anchor="{anchor}">{dates[i][:7]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _oil_bar_redline_svg(pts, w=900, h=230, redline=None, redline_label="",
                         color="#b0895e", unit="", val_fmt="{:.1f}"):
    """周频柱状图 + 红线阈值。跌破红线的柱染红色。pts:[(date,val)] 升序。"""
    if not pts or len(pts) < 2:
        return '<div class="sp-na">柱状图数据不足</div>'
    vals = [v for _, v in pts]
    vmax = max(vals + ([redline] if redline is not None else []))
    vmin = min(vals + ([redline] if redline is not None else []))
    lo = vmin - (vmax - vmin) * 0.15 if vmax > vmin else vmin * 0.95
    hi = vmax + (vmax - vmin) * 0.08 if vmax > vmin else vmax * 1.05
    span = (hi - lo) or 1.0
    pad_l, pad_r, pad_t, pad_b = 54, 14, 20, 32
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    n = len(pts)
    gap = plot_w / n
    bw = gap * 0.6
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
             f'font-family="-apple-system,PingFang SC,sans-serif">']
    for i in range(4):
        gv = lo + span * i / 3
        gy = pad_t + plot_h - (gv - lo) / span * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{pad_l-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{val_fmt.format(gv)}</text>')
    lbl_step = max(1, n // 6)
    for i, (lab, v) in enumerate(pts):
        cx = pad_l + gap * i + gap / 2
        bx = cx - bw / 2
        bh = (v - lo) / span * plot_h
        by = pad_t + plot_h - bh
        breached = redline is not None and v < redline
        last = (i == n - 1)
        fill = "#d64545" if breached else color
        op = 0.9 if (last or breached) else 0.72
        parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" fill="{fill}" opacity="{op}" data-tip="{_esc(lab)}||{val_fmt.format(v)}{unit}"/>')
        if last:
            parts.append(f'<text x="{cx:.1f}" y="{by-4:.1f}" font-size="10.5" font-weight="700" fill="{fill}" text-anchor="middle">{val_fmt.format(v)}{unit}</text>')
        if i % lbl_step == 0 or last:
            parts.append(f'<text x="{cx:.1f}" y="{h-pad_b+15:.1f}" font-size="9" fill="#8a8578" text-anchor="middle">{_esc(lab[:7])}</text>')
    if redline is not None:
        ry = pad_t + plot_h - (redline - lo) / span * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{ry:.1f}" x2="{w-pad_r}" y2="{ry:.1f}" stroke="#d64545" stroke-width="1.6" stroke-dasharray="6,4"/>')
        parts.append(f'<text x="{pad_l+4}" y="{ry-4:.1f}" font-size="10" font-weight="700" fill="#d64545">{_esc(redline_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _eia_next_release(as_of_date):
    """EIA 周度石油状况报告(WPSR)固定每周三发布(覆盖上周五收盘的库存)。
    给定最新数据日期(YYYY-MM-DD, EIA period 为周五), 推算下次发布日(下一个周三)。失败返回 ''。"""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(as_of_date)[:10])
    except Exception:
        return ""
    # EIA period 是周五。下一份周报覆盖再下一个周五, 发布日=其后的周三。
    # 简化: 从数据日期起找下一个周三(weekday()==2)且在数据日期之后≥5天
    nd = d + _dt.timedelta(days=5)
    while nd.weekday() != 2:
        nd += _dt.timedelta(days=1)
    return nd.isoformat()


def _oil_inventory_html(oil):
    """美国石油库存运营红线三图: ①Brent-WTI价差(过去一年,日频折线,0线) ②Cushing库存(过去一年,周频柱状+2000万桶红线)
    ③SPR战略石油储备(过去十年,周频折线+3亿桶红线)。oil: fetch_oil_inventory()。绝不编造,缺项标未获取。"""
    if not oil or oil.get("status") != "ok":
        return '<p class="empty">美国石油库存数据未就绪。</p>'
    sp = oil.get("spread", {})
    cu = oil.get("cushing", {})
    spr = oil.get("spr", {})

    # ① Brent-WTI 价差
    if sp.get("status") == "ok":
        neg = sp.get("neg_days", 0)
        sp_meta = (f'{_esc(sp["points"][0][0])} → {_esc(sp["as_of"])}：最新 '
                   f'<b>${sp["latest"]:+.2f}/桶</b> · 区间 ${sp["lo"]:+.2f} ~ ${sp["hi"]:+.2f} · '
                   f'过去一年<b style="color:#d64545">{neg} 个交易日价差转负</b>（WTI&gt;Brent＝Cushing 库存逼近 tank bottom 信号）')
        sp_chart = _oil_line_svg(sp["points"], w=900, h=230, zero_line=True,
                                 unit="", val_fmt="{:.0f}", rising_good=None)
        sp_src = sp.get("source", "")
    else:
        sp_meta = "数据未获取"; sp_chart = '<div class="sp-na">未获取</div>'; sp_src = ""

    # ② Cushing 库存(柱状 + 红线)
    if cu.get("status") == "ok":
        breach_c = sum(1 for _, v in cu["points"] if v < 20.0)
        cstat = ("跌破" if cu["latest"] < 20.0 else "高于") + "红线"
        ccol = "#d64545" if cu["latest"] < 20.0 else "#2e9e5b"
        cu_meta = (f'{_esc(cu["points"][0][0])} → {_esc(cu["as_of"])}：最新 '
                   f'<b style="color:{ccol}">{cu["latest"]:.1f} 百万桶（{cstat}）</b> · '
                   f'区间 {cu["lo"]:.1f} ~ {cu["hi"]:.1f} · '
                   f'过去一年<b style="color:#d64545">{breach_c} 周跌破 2000 万桶运营红线</b>')
        cu_chart = _oil_bar_redline_svg(cu["points"], w=900, h=230, redline=20.0,
                                        redline_label="运营红线 20（tank bottom）",
                                        color="#b0895e", unit="", val_fmt="{:.0f}")
        cu_src = cu.get("source", "")
    else:
        cu_meta = "数据未获取"; cu_chart = '<div class="sp-na">未获取</div>'; cu_src = ""

    # ③ SPR(折线 + 红线)
    if spr.get("status") == "ok":
        sstat = ("跌破" if spr["latest"] < 300.0 else "高于") + "红线"
        scol = "#d64545" if spr["latest"] < 300.0 else "#2e9e5b"
        drop_pct = (spr["latest"] - spr["hi"]) / spr["hi"] * 100 if spr["hi"] else 0
        spr_meta = (f'{_esc(spr["points"][0][0])} → {_esc(spr["as_of"])}：最新 '
                    f'<b style="color:{scol}">{spr["latest"]:.1f} 百万桶（{sstat}）</b> · '
                    f'十年高 {spr["hi"]:.0f} → 今 {spr["latest"]:.0f}（<b style="color:#d64545">{drop_pct:+.0f}%</b>） · '
                    f'距 3 亿桶运营红线仅 <b>{spr["latest"]-300.0:+.1f}</b> 百万桶')
        spr_chart = _oil_line_svg(spr["points"], w=900, h=230, redline=300.0,
                                  redline_label="运营红线 300（Amos Hochstein 披露）",
                                  unit="", val_fmt="{:.0f}", rising_good=True)
        spr_src = spr.get("source", "")
    else:
        spr_meta = "数据未获取"; spr_chart = '<div class="sp-na">未获取</div>'; spr_src = ""

    # ── 更新频率说明(周频受限于 EIA 周报, 价差为日频) ──
    cu_next = _eia_next_release(cu.get("as_of", "")) if cu.get("status") == "ok" else ""
    spr_next = _eia_next_release(spr.get("as_of", "")) if spr.get("status") == "ok" else ""
    _daily_note = '<span class="chart-freq">🟢 日频 · 每个交易日更新（油价为市场实时报价）</span>'
    _cu_note = (f'<span class="chart-freq freq-w">🔵 周频 · EIA 每周三发布（数据截至上周五）'
                + (f' · 下次约 {_esc(cu_next)}' if cu_next else '') + '</span>')
    _spr_note = (f'<span class="chart-freq freq-w">🔵 周频 · EIA 每周三发布（数据截至上周五）'
                 + (f' · 下次约 {_esc(spr_next)}' if spr_next else '') + '</span>')

    return (
        f'<div class="cust-wrap oil-wrap">'
        # ①
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">① Brent-WTI 价差 · 过去一年（日频）{_daily_note}</div>'
        f'{sp_chart}<div class="oil-meta">{sp_meta}</div>'
        f'{f"<div class=&#39;oil-src&#39;>数据源：{_linkify_sources(sp_src)}</div>" if sp_src else ""}'
        f'</div>'
        # ②
        f'<div class="cust-chart-col cust-chart-full" style="margin-top:16px;">'
        f'<div class="cust-chart-title">② Cushing (Oklahoma) 原油库存 · 过去一年（周频柱状 · WTI 交割枢纽）{_cu_note}</div>'
        f'{cu_chart}<div class="oil-meta">{cu_meta}</div>'
        f'{f"<div class=&#39;oil-src&#39;>数据源：{_linkify_sources(cu_src)}</div>" if cu_src else ""}'
        f'</div>'
        # ③
        f'<div class="cust-chart-col cust-chart-full" style="margin-top:16px;">'
        f'<div class="cust-chart-title">③ 美国战略石油储备 SPR · 过去十年（周频）{_spr_note}</div>'
        f'{spr_chart}<div class="oil-meta">{spr_meta}</div>'
        f'{f"<div class=&#39;oil-src&#39;>数据源：{_linkify_sources(spr_src)}</div>" if spr_src else ""}'
        f'</div>'
        # 如何看
        f'<div class="cust-how"><b>如何看：</b>三图串起美国原油库存的<b>运营红线(tank bottom)</b>压力链：'
        f'<b>①Brent-WTI 价差</b>转负(WTI 反超 Brent)＝WTI 交割地 Cushing 库存逼近可动用下限，市场愿为"能立刻提货的现货"付溢价；'
        f'<b>②Cushing 库存</b>是 WTI 期货的实物交割枢纽，跌破约 2000 万桶(tank bottom / 管道与罐底最低运营量)则交割体系承压、易现逼仓；'
        f'<b>③SPR</b>是国家应急储备，其运营红线约 3 亿桶(时任能源安全顾问 Amos Hochstein 披露)——低于此则应急调节能力所剩无几。'
        f'三者同时逼近红线＝美国原油"缓冲垫"被抽薄，对地缘冲击/供给中断的抗压能力显著下降，是能源与通胀风险的结构性预警。'
        f'<br>红色虚线＝各自运营红线；跌破处以红色高亮。'
        f'<br>⏱️ <b>更新频率说明</b>：①价差为<b>日频</b>(市场实时油价)；②Cushing 与 ③SPR 受限于 <b>EIA 周度石油状况报告(WPSR)只发布周频数据</b>——'
        f'EIA 官方不采集日频库存(全美各储油设施盘点需时)，故每周三更新一次(覆盖上周五)，此即两张库存图能取到的<b>最细粒度</b>。'
        f'数据源：EIA 周度石油状况报告 + FRED 日频油价，均为官方公开数据。</div>'
        f'</div>'
    )


def _country_ust_html(cu):
    """日本 / 中国 / 欧盟 分国别持有美债近10年折线(三图) + 2008 至今三国长历史图。cu: fetch_country_ust_holdings()。"""
    _keys = ("Japan", "China", "EU")
    if not cu or all(cu.get(k, {}).get("status") != "ok" for k in _keys):
        return '<p class="empty">日本 / 中国 / 欧盟 持有美债数据未就绪。</p>'
    src = next((cu[k].get("source") for k in _keys if cu.get(k, {}).get("status") == "ok"),
               "US Treasury TIC")
    # 2008 长历史多国折线数据
    _long_colors = {"Japan": "#6b8fb5", "China": "#c0757d", "EU": "#7fa085"}
    long_series = {}
    for k in _keys:
        d = cu.get(k, {})
        sl = d.get("series_long") or []
        if len(sl) >= 2:
            long_series[k] = {"name": d.get("name", k), "flag": d.get("flag", ""),
                              "color": _long_colors.get(k, "#8a8377"),
                              "points": sl}
    long_range = ""
    if long_series:
        _alld = sorted({m for s in long_series.values() for m, _ in s["points"]})
        if _alld:
            long_range = f"{_alld[0]} → {_alld[-1]}"
    long_block = ""
    if long_series:
        long_block = (
            f'<div class="ci-long">'
            f'<div class="ci-long-title">📉 长历史 · 日/中/欧 持有美债 2008 至今（{_esc(long_range)}）'
            f'<span class="ci-long-note">同一 TIC 口径 · $B · 结构性趋势对比</span></div>'
            f'{_country_ust_long_svg(long_series)}'
            f'</div>'
        )
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-charts cust-charts-3">'
        f'{_country_ust_col(cu.get("Japan"))}'
        f'{_country_ust_col(cu.get("China"))}'
        f'{_country_ust_col(cu.get("EU"))}'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>美国财政部 TIC 口径下各国/地区持有的美债总额（含官方+私人，月度）。'
        f'与上方"外国官方托管美债"口径不同：托管是纽约联储账户的外国<b>官方合计</b>，这里是<b>分国别</b>总持仓。'
        f'<b>日本</b>是美债最大单一持有国，近10年高位震荡；<b>中国</b>近10年持续系统性减持，是去美元化/中美博弈的结构性信号；'
        f'<b>欧盟</b>为欧元区主要成员（德/法/意/荷/比/卢/爱/西/芬）加总（TIC 无欧盟合计口径），'
        f'其中比利时含 Euroclear 国际托管中心的第三方持仓，故欧盟合计偏高、趋势性增长明显。'
        f'数据源：{_linkify_sources(src)}。</div>'
        f'{long_block}'
        f'</div>'
    )


SIG_META = {
    "strong_pos": ("#2e9e5b", "强正·信贷加速"),
    "pos":        ("#2e9e5b", "正·温和扩张"),
    "neutral":    ("#e0a92e", "中性·基本持平"),
    "neg":        ("#d64545", "负·信贷收缩"),
    "strong_neg": ("#d64545", "强负·急剧收缩"),
    "unknown":    ("#9a9a9a", "数据未就绪"),
}


def _credit_impulse_svg(points, w=360, h=190):
    """Credit Impulse 折线图(带零轴, pp of GDP)。points: [{date, ci},...] 升序。
    正负值→需零轴基准; 最新点用信号色空心圈突出。"""
    if not points or len(points) < 2:
        return '<div class="ci-na">历史数据不足</div>'
    dates = [p["date"] for p in points]
    vals = [p["ci"] for p in points]
    lo, hi = min(vals), max(vals)
    # 对称留白, 保证零轴在图内
    lo = min(lo, 0.0)
    hi = max(hi, 0.0)
    pad = (hi - lo) * 0.10 or 0.5
    lo -= pad
    hi += pad
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 40, 12, 14, 26
    pw, ph = w - ml - mr, h - mt - mb
    n = len(vals)
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    zy = Y(0.0)  # 零轴
    # 分段折线: 正段绿、负段红(按点着色描边简化为整条中性描边 + 正负填充)
    pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)]
    _hits = "".join(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="7" data-tip="{_esc(dates[i][:7])}||{v:+.2f}"/>' for i, v in enumerate(vals))
    # 面积到零轴(正上负下)
    area = f"{X(0):.1f},{zy:.1f} " + " ".join(pts) + f" {X(n-1):.1f},{zy:.1f}"
    # Y 轴刻度(3 条)
    yl = []
    for k in range(3):
        gv = lo + rng * k / 2
        gy = Y(gv)
        yl.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        yl.append(f'<text x="{ml-5}" y="{gy+3:.1f}" class="cc-ylab">{gv:+.1f}</text>')
    # 零轴加粗
    yl.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" class="ci-zero"/>')
    # X 轴标签(首/中/末)
    xl = []
    for i in sorted(set([0, n // 2, n - 1])):
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        xl.append(f'<text x="{X(i):.1f}" y="{h-8}" class="cc-xlab" text-anchor="{anchor}">{dates[i][:7]}</text>')
    lx, ly = X(n - 1), Y(vals[-1])
    last = vals[-1]
    lc = "#2e9e5b" if last >= 0.15 else ("#d64545" if last <= -0.15 else "#e0a92e")
    return (
        f'<svg viewBox="0 0 {w} {h}" class="ci-chart" preserveAspectRatio="xMidYMid meet">'
        + "".join(yl)
        + f'<polygon points="{area}" fill="rgba(140,150,160,0.10)" stroke="none"/>'
        + f'<polyline points="{" ".join(pts)}" fill="none" stroke="#7d8a97" stroke-width="2" stroke-linejoin="round"/>'
        + _hits
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="7" fill="none" stroke="{lc}" stroke-width="2.4"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6" fill="{lc}"/>'
        + "".join(xl)
        + '</svg>'
    )


def _credit_impulse_col(d):
    """单国 Credit Impulse 一列(标题 + 最新值/信号 + 折线)。"""
    if not d or d.get("status") != "ok" or not d.get("points"):
        nm = (d or {}).get("name", "")
        flag = (d or {}).get("flag", "")
        return (f'<div class="ci-col"><div class="ci-title">{flag} {_esc(nm)}</div>'
                f'<div class="ci-na">数据未就绪</div></div>')
    latest = d["latest"]
    sig = d.get("signal", "neutral")
    color, label = SIG_META.get(sig, SIG_META["neutral"])
    return (
        f'<div class="ci-col">'
        f'<div class="ci-title">{d.get("flag","")} {_esc(d["name"])}</div>'
        f'<div class="ci-cur" style="color:{color}">{latest:+.2f}'
        f'<span class="ci-unit">pp GDP</span></div>'
        f'<div class="ci-sig"><span class="ci-dot" style="border-color:{color}"></span>'
        f'<span style="color:{color}">{label}</span> '
        f'<span class="ci-asof">as of {_esc(d.get("latest_date",""))[:7]}</span></div>'
        f'{_credit_impulse_svg(d["points"])}'
        f'</div>'
    )


def _credit_impulse_long_svg(series_by_country, w=920, h=240):
    """2008 至今长历史 Credit Impulse 多国折线(粗颗粒度参考图, 带零轴)。
    series_by_country: {cc: {"name","flag","color","points":[{date,ci}]}}。"""
    active = {cc: d for cc, d in series_by_country.items() if d.get("points")}
    if not active:
        return '<div class="ci-na">长历史数据不足</div>'
    # 统一时间轴 + 值域
    all_dates = sorted({p["date"] for d in active.values() for p in d["points"]})
    all_vals = [p["ci"] for d in active.values() for p in d["points"]]
    if len(all_dates) < 2:
        return '<div class="ci-na">长历史数据不足</div>'
    lo, hi = min(all_vals + [0.0]), max(all_vals + [0.0])
    pad = (hi - lo) * 0.08 or 1.0
    lo -= pad
    hi += pad
    rng = (hi - lo) or 1.0
    ml, mr, mt, mb = 44, 90, 16, 28
    pw, ph = w - ml - mr, h - mt - mb
    n = len(all_dates)
    didx = {d: i for i, d in enumerate(all_dates)}
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    zy = Y(0.0)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="ci-chart" preserveAspectRatio="xMidYMid meet">']
    # Y 轴 3 刻度
    for k in range(3):
        gv = lo + rng * k / 2
        gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        parts.append(f'<text x="{ml-5}" y="{gy+3:.1f}" class="cc-ylab">{gv:+.0f}</text>')
    parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" class="ci-zero"/>')
    # X 轴年份标签(每2年)
    for i, d in enumerate(all_dates):
        yr = d[:4]
        if d[5:7] == "01" and int(yr) % 2 == 0:
            anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
            parts.append(f'<text x="{X(i):.1f}" y="{h-8}" class="cc-xlab" text-anchor="{anchor}">{yr}</text>')
    # 每国一条线
    legend_y = mt + 6
    for cc, d in active.items():
        color = d["color"]
        pts = [f"{X(didx[p['date']]):.1f},{Y(p['ci']):.1f}" for p in d["points"] if p["date"] in didx]
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" opacity="0.85"/>')
            for p in d["points"]:
                _pd = p["date"]
                if _pd in didx:
                    _pcx = X(didx[_pd]); _pcy = Y(p["ci"])
                    parts.append(f'<circle class="tip-hit" cx="{_pcx:.1f}" cy="{_pcy:.1f}" r="6" data-tip="{_esc(str(cc))} · {_esc(_pd[:7])}||{p["ci"]:+.2f}"/>')
        # 图例
        parts.append(f'<line x1="{w-mr+6}" y1="{legend_y}" x2="{w-mr+22}" y2="{legend_y}" stroke="{color}" stroke-width="2.4"/>')
        parts.append(f'<text x="{w-mr+26}" y="{legend_y+3}" class="ci-leg" fill="{color}">{d["flag"]}{_esc(d["name"])}</text>')
        legend_y += 18
    parts.append('</svg>')
    return "".join(parts)


def _credit_impulse_html(ci):
    """Credit Impulse(信贷脉冲)四国对比——中期领先指标(领先实体经济 6-9 月)。"""
    _cc_all = ("US", "CN", "EA", "JP")
    if not ci or all((ci.get(cc, {}).get("status") != "ok") for cc in _cc_all):
        return '<p class="empty">Credit Impulse 数据未就绪。</p>'
    src = next((ci[cc].get("source") for cc in _cc_all
                if ci.get(cc, {}).get("status") == "ok"), "BIS via FRED")
    asof = next((ci[cc].get("latest_date") for cc in _cc_all
                 if ci.get(cc, {}).get("status") == "ok"), "")
    # 长历史(2008起)参考图数据: 收集各国 points_long + 配色
    _ci_colors = {"US": "#6b8fb5", "CN": "#c08a7d", "EA": "#9aab97", "JP": "#c9a86a"}
    long_series = {}
    for cc in _cc_all:
        d = ci.get(cc, {})
        pl = d.get("points_long") or []
        if pl:
            long_series[cc] = {"name": d.get("name", cc), "flag": d.get("flag", ""),
                               "color": _ci_colors.get(cc, "#8a8377"), "points": pl}
    long_range = ""
    if long_series:
        _alld = sorted({p["date"] for s in long_series.values() for p in s["points"]})
        if _alld:
            long_range = f"{_alld[0][:7]} → {_alld[-1][:7]}"
    long_block = ""
    if long_series:
        long_block = (
            f'<div class="ci-long">'
            f'<div class="ci-long-title">📉 长历史参考 · Credit Impulse 2008 至今（{_esc(long_range)}）'
            f'<span class="ci-long-note">粗颗粒度·仅作长周期参考·十年图见上</span></div>'
            f'{_credit_impulse_long_svg(long_series)}'
            f'</div>'
        )
    return (
        f'<div class="ci-wrap">'
        f'<div class="ci-cols ci-cols-4">'
        f'{_credit_impulse_col(ci.get("US"))}'
        f'{_credit_impulse_col(ci.get("CN"))}'
        f'{_credit_impulse_col(ci.get("EA"))}'
        f'{_credit_impulse_col(ci.get("JP"))}'
        f'</div>'
        f'<div class="ci-how"><b>如何看：</b>Credit Impulse（信贷脉冲）= 新增信贷流量的<b>变化</b> ÷ GDP，'
        f'衡量的不是债务总量、也不是新增债务，而是<b>新增信贷的加速度</b>。'
        f'<span style="color:#2e9e5b">正值=信贷在加速扩张</span>（利好增长/风险资产），'
        f'<span style="color:#d64545">负值=新增信贷放缓/收缩</span>（即使总债务仍在涨）。'
        f'领先实体经济约 <b>6-9 个月</b>——<b>中国信贷脉冲</b>是全球商品、周期股、风险资产最强的领先指标之一。'
        f'口径为 BIS credit-to-GDP ratio 的二阶差分（美/中/欧/日统一口径、国际可比），<b>季度序列、BIS 汇编发布滞后约 3 季</b>（as of {_esc(asof)[:7]}）{_stale_badge(asof, "bis_quarterly")}。'
        f'数据源：{_linkify_sources(src)}。</div>'
        f'{long_block}'
        f'</div>'
    )


def _stress_panel_svg(panel, w=1000, h=300):
    """双轴(或单轴)多线折线图, 用于国债市场压力四联图。竖向排列时每张全宽。
    panel: {series:[{name,color,axis(left/right),dash?,width?,points:[{date,v}]}], unit_left, unit_right, single_axis?}。
    左轴/右轴各自独立缩放; 带 x 轴年月标签; 图例在右侧。绝不编: 空序列跳过。"""
    series = [s for s in panel.get("series", []) if s.get("points")]
    if not series:
        return '<div class="sp-na">数据未就绪</div>'
    single = panel.get("single_axis")
    # 统一时间轴(所有 series 的日期并集)
    all_dates = sorted({p["date"] for s in series for p in s["points"]})
    if len(all_dates) < 2:
        return '<div class="sp-na">数据不足</div>'
    n = len(all_dates)
    didx = {d: i for i, d in enumerate(all_dates)}
    # 左右轴各自值域
    left_vals = [p["v"] for s in series if s.get("axis", "left") == "left" for p in s["points"]]
    right_vals = [p["v"] for s in series if s.get("axis") == "right" for p in s["points"]]
    def _range(vals, incl_zero=False):
        if not vals:
            return (0.0, 1.0)
        lo, hi = min(vals), max(vals)
        if incl_zero:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        pad = (hi - lo) * 0.10 or (abs(hi) * 0.1 or 1.0)
        return (lo - pad, hi + pad)
    # OFR 单轴含0基准; 其余左轴不强制0
    l_lo, l_hi = _range(left_vals, incl_zero=single)
    r_lo, r_hi = _range(right_vals)
    l_rng = (l_hi - l_lo) or 1.0
    r_rng = (r_hi - r_lo) or 1.0
    ml, mr, mt, mb = 52, (175 if not single else 175), 18, 30
    pw, ph = w - ml - mr, h - mt - mb
    def X(i): return ml + i * pw / (n - 1)
    def YL(v): return mt + (l_hi - v) / l_rng * ph
    def YR(v): return mt + (r_hi - v) / r_rng * ph
    parts = [f'<svg viewBox="0 0 {w} {h}" class="sp-chart" preserveAspectRatio="xMidYMid meet">']
    # 左轴刻度(4) —— 左轴专属 MOVE 指数, 刻度用 MOVE 红褐色呼应
    _left_color = None
    for s in series:
        if s.get("axis", "left") == "left":
            _left_color = s.get("color")
            break
    _lc = _left_color or "#8a8578"
    for k in range(4):
        gv = l_lo + l_rng * k / 3
        gy = YL(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="sp-grid"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" class="sp-ylab" fill="{_lc}" text-anchor="end">{gv:.2f}</text>')
    # 右轴刻度(单轴时不画)
    if not single and right_vals:
        for k in range(4):
            gv = r_lo + r_rng * k / 3
            gy = YR(gv)
            parts.append(f'<text x="{w-mr+6}" y="{gy+3:.1f}" class="sp-ylab sp-ylab-r" text-anchor="start">{gv:.2f}</text>')
    # 零轴(单轴 OFR 高亮)
    if single and l_lo <= 0 <= l_hi:
        zy = YL(0.0)
        parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" class="sp-zero"/>')
        parts.append(f'<text x="{ml+4}" y="{zy-4:.1f}" class="sp-zlab">0 = 历史正常</text>')
    # x 轴年月标签(每约6个月)
    step = max(1, n // 6)
    for i in range(0, n, step):
        d = all_dates[i]
        anchor = "start" if i == 0 else ("end" if i >= n - step else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h-8}" class="sp-xlab" text-anchor="{anchor}">{d[:7]}</text>')
    # 每条线
    legend_y = mt + 8
    for s in series:
        color = s["color"]
        axis = s.get("axis", "left")
        Y = YL if axis == "left" else YR
        spts = [p for p in s["points"] if p["date"] in didx]
        pts = [f"{X(didx[p['date']]):.1f},{Y(p['v']):.1f}" for p in spts]
        # ── 关键点位统计: 最高/最低/当前/中位 ──
        vals = [p["v"] for p in spts]
        stat = None
        if vals:
            sv = sorted(vals)
            m = len(sv)
            med = sv[m // 2] if m % 2 else (sv[m // 2 - 1] + sv[m // 2]) / 2
            hi_p = max(spts, key=lambda p: p["v"])
            lo_p = min(spts, key=lambda p: p["v"])
            cur_p = spts[-1]
            stat = {"cur": cur_p["v"], "hi": hi_p["v"], "lo": lo_p["v"], "med": med}
        if len(pts) >= 2:
            dash = ' stroke-dasharray="5,3"' if s.get("dash") else ""
            width = s.get("width", 1.7)
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                         f'stroke-width="{width}" stroke-linejoin="round" opacity="0.9"{dash}/>')
            # 每点透明 hover 圈 (显示日期+值)
            _unit = (panel.get("unit_left", "") if axis == "left" else panel.get("unit_right", "")) or ""
            for p in spts:
                _hx, _hy = X(didx[p["date"]]), Y(p["v"])
                _tip = f'{_esc(s["name"])} · {_esc(p["date"])}||{p["v"]:.2f}{_unit}'
                parts.append(f'<circle class="tip-hit" cx="{_hx:.1f}" cy="{_hy:.1f}" r="7" data-tip="{_tip}"/>')
            # 最高点标记(空心小圈 + 数值)
            hx, hy = X(didx[hi_p["date"]]), Y(hi_p["v"])
            parts.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="2.6" fill="{color}" opacity="0.9"/>')
            _ha = "start" if hx < ml + 40 else ("end" if hx > w - mr - 40 else "middle")
            parts.append(f'<text x="{hx:.1f}" y="{hy-5:.1f}" class="sp-pt" fill="{color}" '
                         f'text-anchor="{_ha}">▲{hi_p["v"]:.2f}</text>')
            # 最低点标记
            lx, ly = X(didx[lo_p["date"]]), Y(lo_p["v"])
            parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6" fill="{color}" opacity="0.9"/>')
            _la = "start" if lx < ml + 40 else ("end" if lx > w - mr - 40 else "middle")
            parts.append(f'<text x="{lx:.1f}" y="{ly+11:.1f}" class="sp-pt" fill="{color}" '
                         f'text-anchor="{_la}">▼{lo_p["v"]:.2f}</text>')
            # 中位虚线(该 series 所在轴)
            mzy = Y(med)
            parts.append(f'<line x1="{ml}" y1="{mzy:.1f}" x2="{w-mr}" y2="{mzy:.1f}" '
                         f'stroke="{color}" stroke-width="0.8" stroke-dasharray="2,4" opacity="0.5"/>')
            # 最新点(实心描边圈, 带当前值)
            cx0, cy0 = X(didx[cur_p["date"]]), Y(cur_p["v"])
            parts.append(f'<circle cx="{cx0:.1f}" cy="{cy0:.1f}" r="3.6" '
                         f'fill="{color}" stroke="#fff" stroke-width="1.2"/>')
            parts.append(f'<text x="{cx0-6:.1f}" y="{cy0-6:.1f}" class="sp-pt sp-pt-cur" '
                         f'fill="{color}" text-anchor="end">当前 {cur_p["v"]:.2f}</text>')
        # 图例(名称 + 轴 + 四点位摘要)
        axtag = "" if single else (" ◂L" if axis == "left" else " R▸")
        leg_dash = ' stroke-dasharray="5,3"' if s.get("dash") else ""
        parts.append(f'<line x1="{w-mr+8}" y1="{legend_y}" x2="{w-mr+26}" y2="{legend_y}" '
                     f'stroke="{color}" stroke-width="2.6"{leg_dash}/>')
        parts.append(f'<text x="{w-mr+30}" y="{legend_y+4}" class="sp-leg" fill="{color}">'
                     f'{_esc(s["name"])}{axtag}</text>')
        legend_y += 15
        if stat:
            parts.append(
                f'<text x="{w-mr+8}" y="{legend_y+4}" class="sp-leg-stat" fill="{color}">'
                f'现{stat["cur"]:.2f} 高{stat["hi"]:.2f} 低{stat["lo"]:.2f} 中{stat["med"]:.2f}</text>')
            legend_y += 17
        else:
            legend_y += 5
    parts.append('</svg>')
    return "".join(parts)


def _stress_panels_html(sp, ofr=None):
    """国债市场压力【竖向四联图】(对齐 Morgan Stanley 三图 + OFR 官方压力指数)。
    竖向排列(而非横向), 每张全宽大图, 更清晰。全部过去3年真实公开数据。
    sp: fetch_treasury_stress_panels() 结果; ofr: fetch_ofr_fsi() 结果(第4图)。"""
    panels = list((sp or {}).get("panels") or [])
    if ofr and ofr.get("panel"):
        panels.append(ofr["panel"])
    panels = [p for p in panels if any(s.get("points") for s in p.get("series", []))]
    if not panels:
        return '<p class="empty">国债市场压力数据未就绪。</p>'
    asof = (sp or {}).get("asof") or (ofr or {}).get("asof") or ""
    years = (sp or {}).get("years") or (ofr or {}).get("years") or 3
    blocks = []
    for p in panels:
        axinfo = ""
        if not p.get("single_axis"):
            axinfo = (f'<span class="sp-axk">左轴 ◂ {_esc(p.get("unit_left",""))}</span>'
                      f'<span class="sp-axk">{_esc(p.get("unit_right",""))} ▸ 右轴</span>')
        else:
            axinfo = f'<span class="sp-axk">{_esc(p.get("unit_left",""))}</span>'
        blocks.append(
            f'<div class="sp-panel">'
            f'<div class="sp-head"><span class="sp-title">{_esc(p["title"])}</span>'
            f'<span class="sp-sub">{_esc(p.get("subtitle",""))}</span></div>'
            f'<div class="sp-axrow">{axinfo}</div>'
            f'{_stress_panel_svg(p)}'
            f'<div class="sp-note">{p.get("note","")}</div>'
            f'<div class="sp-src">数据源：{_linkify_sources(p.get("source",""))}</div>'
            f'</div>'
        )
    intro = (
        f'<div class="sp-intro">参照 Morgan Stanley 三图（国债收益率+波动性 / 市场流动性价差 / 成交活跃度），'
        f'用<b>过去 {years} 年真实公开数据</b>竖向复刻。'
        f'MS 的 BrokerTec 日内价差与 DV01 成交量为其专有数据（无免费公开源），'
        f'图②③ 改用主题对齐的公开压力代理并已明确标注；图④ 为 OFR 官方金融压力指数。'
        f'<span class="sp-asof">as of {_esc(str(asof))} · 周度降噪 · 每日更新</span></div>'
    )
    return f'<div class="sp-wrap">{intro}{"".join(blocks)}</div>'


def _bt_sparkline(vals, w=88, h=22, color="#8a8578", dates=None, unit=" bp"):
    """迷你走势线(状态矩阵内用)。vals: [float]。绝不编: 空则返回占位。
    ★带 tooltip: 透明 hit-band 复用全站 data-tip 机制; dates 缺失则只显数值(不编造日期)。"""
    vals = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return '<span class="bt-spark-na">—</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pad = 2
    def X(i): return pad + i * (w - 2 * pad) / (n - 1)
    def Y(v): return pad + (hi - v) / rng * (h - 2 * pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    # 末点方向色: 涨(相对首点)红 / 跌绿(利差走窄=风险↑用红提示 —— 但这里spark只表走势, 用中性描边+末点方向色)
    up = vals[-1] >= vals[0]
    end_c = "#c0757d" if up else "#7fa085"
    ex, ey = X(n - 1), Y(vals[-1])
    dates = dates or []
    _bw = (w - 2 * pad) / (n - 1)
    hits = "".join(
        f'<rect x="{max(0, X(i) - _bw / 2):.1f}" y="0" width="{_bw:.1f}" height="{h}" fill="transparent" '
        f'data-tip="{_esc(str(dates[i])[:10]) if i < len(dates) else ""}||{vals[i]:+.1f}{_esc(unit)}"/>'
        for i in range(n))
    return (f'<svg class="bt-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.3" '
            f'stroke-linejoin="round" opacity="0.85"/>'
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="1.9" fill="{end_c}"/>'
            f'{hits}</svg>')


def _basis_trade_html(bt):
    """基差套利去杠杆预警面板(时序化「美债/日债基差套利 + SOFR 倒挂」监控)。
    bt: fetch_basis_trade_monitor() 结果。3 个双轴 panel(复用 _stress_panel_svg) + 分期限状态矩阵。
    绝不编: 缺失序列/期限显示占位。"""
    if not bt or bt.get("status") == "未获取" or not bt.get("panels"):
        return '<p class="empty">基差套利监控数据未就绪。</p>'
    panels_d = bt["panels"]
    lights = bt.get("lights", {})
    asof = bt.get("asof", "")
    matrix = bt.get("matrix", [])

    # ── 顶部合成风险灯条 ──
    def _lampcell(label, light, detail):
        light = light or "⚪"
        return (f'<div class="bt-lamp"><div class="bt-lamp-ico">{light}</div>'
                f'<div class="bt-lamp-lab">{_esc(label)}</div>'
                f'<div class="bt-lamp-det">{_esc(detail)}</div></div>')
    gap = lights.get("sofr_iorb_gap_bp")
    gap_txt = (f'SOFR−IORB {gap:+.0f}bp' if isinstance(gap, (int, float)) else '—')
    tonar_v = lights.get("tonar")
    jpc = lights.get("jp_min_carry_bp")
    jp_txt = (f'TONAR {tonar_v:.2f}% · 日债最紧 {jpc:+.0f}bp' if isinstance(tonar_v, (int, float)) and isinstance(jpc, (int, float))
              else (f'TONAR {tonar_v:.2f}%' if isinstance(tonar_v, (int, float)) else '—'))
    mc = lights.get("min_carry_bp")
    mc_txt = (f'最紧 {mc:+.0f}bp' if isinstance(mc, (int, float)) else '—')
    mv = lights.get("move")
    mv_txt = (f'MOVE {mv:.0f}' if isinstance(mv, (int, float)) else '—')
    lampbar = (
        f'<div class="bt-lampbar bt-lampbar-4">'
        f'{_lampcell("美债融资(SOFR触顶?)", lights.get("funding"), gap_txt)}'
        f'{_lampcell("日债融资(TONAR倒挂?)", lights.get("jp_funding"), jp_txt)}'
        f'{_lampcell("套利Carry空间", lights.get("carry"), mc_txt)}'
        f'{_lampcell("债市波动率(强平推手)", lights.get("vol"), mv_txt)}'
        f'</div>'
    )

    # ── 3 个双轴/单轴 panel ──
    order = ["funding", "carry", "trigger"]
    notes = {
        "funding": ("<b>怎么看：</b>SOFR(隔夜融资成本，粗红实线)是基差套利头寸的<b>资金成本</b>。"
                    "正常时 SOFR 应在走廊内(ON RRP 底 ~ IORB 顶)。<b>SOFR 上抬触顶甚至穿越 IORB(深红虚线)= 融资血管收缩</b>——"
                    "回购市场缺钱、加杠杆成本骤升，是基差套利被挤压的第一信号。2019-09 与 2020-03 强平潮前都出现过 SOFR 冲顶。"
                    "<br><b>怎么用：</b>SOFR−IORB 由负转 0 甚至转正 = 🔴 预警：融资端已封顶，任何波动都会放大强平压力。"),
        "carry": ("<b>怎么看：</b>carry = 各期限国债收益率 − 隔夜融资成本（美债用 SOFR，日债用 TONAR），即套利头寸的<b>持有净收益(bp)</b>。"
                  "carry 为正且宽 = 套利有肉、头寸稳；<b>carry 收窄甚至转负(倒挂)= 借钱持债反而亏损 = 强平动机爆发</b>。"
                  "短端(2Y/1M)对融资成本最敏感，最先转负。实线=美债(−SOFR)，虚线=日债(−TONAR)。"
                  "<br><b>怎么用：</b>任一期限 carry 跌破 0(<span style=\"color:#d64545\">红区</span>)= 🔴 该期限套利头寸开始亏损，"
                  "叠加融资触顶就是去杠杆的直接扳机。日债近端 carry 转负正是 TONAR 融资倒挂预警(对应表6)。"),
        "trigger": ("<b>怎么看：</b>去杠杆的「火药桶 + 火星」：<b>MOVE 债市波动率(左轴，橙线)</b>是火星——波动飙升直接抬高保证金要求、"
                    "逼迫降杠杆；<b>Fed 准备金(右轴，蓝线)</b>是缓冲垫——准备金越薄，市场吸收抛盘的能力越弱。"
                    "<br><b>怎么用：</b>MOVE 突破 120(🔴) + 准备金持续跌向 $2.8T 红线 = 火药桶已满、火星将至，"
                    "此时若 carry 又转负，三重共振 = 基差套利强平潮高风险，应提前减仓/对冲久期。"),
    }
    blocks = []
    for key in order:
        p = panels_d.get(key)
        if not p or not any(s.get("points") for s in p.get("series", [])):
            continue
        if p.get("single_axis"):
            axinfo = f'<span class="sp-axk">{_esc(p.get("unit_left",""))}</span>'
        else:
            axinfo = (f'<span class="sp-axk">左轴 ◂ {_esc(p.get("unit_left",""))}</span>'
                      f'<span class="sp-axk">{_esc(p.get("unit_right",""))} ▸ 右轴</span>')
        blocks.append(
            f'<div class="sp-panel">'
            f'<div class="sp-head"><span class="sp-title">{_esc(p["title"])}</span>'
            f'<span class="sp-sub">{_esc(p.get("subtitle",""))}</span></div>'
            f'<div class="sp-axrow">{axinfo}</div>'
            f'{_stress_panel_svg(p)}'
            f'<div class="sp-note">{notes.get(key,"")}</div>'
            f'<div class="sp-src">数据源：{_linkify_sources(p.get("source",""))}</div>'
            f'</div>'
        )

    # ── 分期限状态矩阵(美债 2/5/10/30 + 日债 10/30) ──
    mrows = []
    for m in matrix:
        mk, tn = m.get("market", ""), m.get("tenor", "")
        light = m.get("light", "⚪")
        carry = m.get("carry_bp")
        yld = m.get("yield")
        spark = _bt_sparkline(m.get("spark", []), dates=m.get("spark_d", []))
        if m.get("status") != "ok":
            carry_txt = '<span class="bt-na">未获取</span>'
            yld_txt = "—"
        else:
            if carry is None:
                carry_txt = '<span class="bt-na">n/a</span>'
            else:
                cc = "#d64545" if carry < 0 else ("#e0a92e" if carry < 30 else "#2e9e5b")
                carry_txt = f'<b style="color:{cc}">{carry:+.0f} bp</b>'
            yld_txt = (f'{yld:.2f}%' if isinstance(yld, (int, float)) else "—")
        note = m.get("note", "")
        note_html = (f'<span class="bt-mnote" title="{_esc(note)}">ⓘ</span>' if note else "")
        mrows.append(
            f'<div class="bt-mrow">'
            f'<span class="bt-mmkt">{_esc(mk)}</span>'
            f'<span class="bt-mten">{_esc(tn)}</span>'
            f'<span class="bt-mlight">{light}</span>'
            f'<span class="bt-mcarry">{carry_txt}</span>'
            f'<span class="bt-myld">{yld_txt}</span>'
            f'<span class="bt-mspark">{spark}{note_html}</span>'
            f'</div>'
        )
    matrix_html = (
        f'<div class="bt-matrix">'
        f'<div class="bt-mrow bt-mhead">'
        f'<span class="bt-mmkt">市场</span><span class="bt-mten">期限</span>'
        f'<span class="bt-mlight">灯</span><span class="bt-mcarry">Carry(收益率−SOFR)</span>'
        f'<span class="bt-myld">收益率</span><span class="bt-mspark">近30日走势</span>'
        f'</div>'
        f'{"".join(mrows)}'
        f'</div>'
    )

    intro = (
        f'<div class="sp-intro">把静态监控表升级为<b>时序预警面板</b>：追踪基差套利对冲基金'
        f'(买现券/卖期货、回购加 33–99x 杠杆)被迫<b>去杠杆强平</b>的三重触发链——'
        f'<b>①融资成本触顶 → ②套利 Carry 转负 → ③波动飙升×缓冲枯竭</b>。'
        f'三者共振 = 强平潮高风险(2020-03 式踩踏)。全部 FRED / 日本 MOF 真实公开数据。'
        f'<span class="sp-asof">as of {_esc(str(asof))} · 周度降噪 · 每日更新</span></div>'
    )
    matrix_intro = (
        '<div class="bt-mtitle">分期限风险矩阵 · 美债 vs 日债'
        '<span class="bt-mtsub">🟢 carry&gt;30bp 安全 · 🟡 0–30bp 收窄 · 🔴 &lt;0bp 倒挂(套利亏损)</span></div>'
    )
    return (f'<div class="sp-wrap bt-wrap">{intro}{lampbar}'
            f'{"".join(blocks)}'
            f'{matrix_intro}{matrix_html}'
            f'<div class="bt-mfoot">美债 carry = 收益率 − SOFR；日债 carry = 收益率 − TONAR（BoJ 无担保隔夜拆借加权平均，日债侧真实融资成本基准，对应美债 SOFR）。'
            f'两侧均为真实公开日频数据，走廊清晰、判定可靠。TONAR 本次未取到时日债 carry 诚实标 n/a(ⓘ)，绝不用近似冒充。</div></div>')


def _flow_bars_svg(bars, w=920, h=220, unit="t"):
    """ETF 周净流量正负柱状图。bars: [{date,v}] 升序。正=流入(绿)/负=流出(红)，含零轴。带 hover。"""
    bars = [b for b in (bars or []) if isinstance(b.get("v"), (int, float))]
    if len(bars) < 2:
        return '<div class="sp-na">资金流数据不足</div>'
    vals = [b["v"] for b in bars]
    vmax, vmin = max(vals), min(vals)
    hi = max(vmax, 0) * 1.12 or 1.0
    lo = min(vmin, 0) * 1.12 or -1.0
    span = (hi - lo) or 1.0
    ml, mr, mt, mb = 52, 14, 18, 34
    pw, ph = w - ml - mr, h - mt - mb
    n = len(bars)
    gap = pw / n
    bw = gap * 0.6
    def Y(v): return mt + (hi - v) / span * ph
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,sans-serif">']
    # y 网格(4档)
    for i in range(4):
        gv = lo + span * i / 3
        gy = Y(gv)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#d4cdbe" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="10" fill="#8a8578" text-anchor="end">{gv:+.0f}</text>')
    # 零轴高亮
    zy = Y(0.0)
    parts.append(f'<line x1="{ml}" y1="{zy:.1f}" x2="{w-mr}" y2="{zy:.1f}" stroke="#8a8578" stroke-width="1.2"/>')
    lbl_step = max(1, n // 8)
    for i, b in enumerate(bars):
        v = b["v"]
        cx = ml + gap * i + gap / 2
        bx = cx - bw / 2
        col = "#2e9e5b" if v >= 0 else "#d64545"
        y0 = Y(max(v, 0)); y1 = Y(min(v, 0))
        bh = abs(y1 - y0)
        last = (i == n - 1)
        parts.append(f'<rect x="{bx:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" '
                     f'fill="{col}" opacity="{0.95 if last else 0.72}" '
                     f'data-tip="{_esc(b["date"])}||{v:+.2f} {unit}"/>')
        if i % lbl_step == 0 or last:
            short = b["date"][2:] if len(b["date"]) >= 7 else b["date"]
            parts.append(f'<text x="{cx:.1f}" y="{h-mb+15:.1f}" font-size="9" fill="#8a8578" text-anchor="middle">{_esc(short)}</text>')
    parts.append('</svg>')
    return "".join(parts)


# ─────────── 世界前十经济体 政府债务/GDP ───────────
def _debt_gdp_bar_svg(countries, w=940, h=360):
    """横向条形图: 各国政府债务/GDP。实绩=实心, IMF 预测末年=斜纹延伸段。
    100% 处画警戒竖线(债务超过一年 GDP)。"""
    ok = [c for c in countries if c.get("status") == "ok"]
    if not ok:
        return ""
    ml, mr, mt, mb = 92, 118, 26, 50
    n = len(ok)
    band = (h - mt - mb) / max(n, 1)
    bh = min(band * 0.62, 20)
    vmax = max([c["latest"] for c in ok] +
               [(c.get("forecast") or [(0, 0)])[-1][1] for c in ok]) * 1.08
    vmax = max(vmax, 100)
    iw = w - ml - mr

    def x(v):
        return ml + (v / vmax) * iw

    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" '
         f'xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui">']
    # 预测段斜纹填充(与实绩实心段视觉区分)
    p.append('<defs><pattern id="dgFc" width="5" height="5" patternUnits="userSpaceOnUse" '
             'patternTransform="rotate(45)"><rect width="5" height="5" fill="#fff" '
             'opacity="0.55"/><line x1="0" y1="0" x2="0" y2="5" stroke="#7a7469" '
             'stroke-width="2.2" opacity="0.55"/></pattern></defs>')
    # X 轴刻度网格(让条长可自证, 不只靠端点数字)
    for gv in range(0, int(vmax) + 1, 50):
        gx = x(gv)
        p.append(f'<line x1="{gx:.1f}" y1="{mt-2}" x2="{gx:.1f}" y2="{h-mb:.1f}" '
                 f'stroke="#ece9e2" stroke-width="1"/>')
        p.append(f'<text x="{gx:.1f}" y="{h-mb+15}" font-size="9" fill="#a8a49b" '
                 f'text-anchor="middle">{gv}%</text>')
    # 100% 警戒线
    x100 = x(100)
    p.append(f'<line x1="{x100:.1f}" y1="{mt-6}" x2="{x100:.1f}" y2="{h-mb+4}" '
             f'stroke="#c0757d" stroke-width="1" stroke-dasharray="4 3" opacity="0.75"/>')
    p.append(f'<text x="{x100:.1f}" y="{mt-10}" font-size="9.5" fill="#c0757d" '
             f'text-anchor="middle">债务=100% GDP</text>')
    for i, c in enumerate(ok):
        cy = mt + band * i + band / 2
        v = c["latest"]
        fc = c.get("forecast") or []
        # 颜色: >150 深红 / >100 陶红 / >60 芥黄 / else 鼠尾草绿
        col = ("#b4636b" if v > 150 else "#c0757d" if v > 100
               else "#c9a86a" if v > 60 else "#7fa085")
        bx = x(v)
        p.append(f'<text x="{ml-8}" y="{cy+4:.1f}" font-size="11.5" fill="#5a564e" '
                 f'text-anchor="end">{_esc(c["name"])}</text>')
        # 预测延伸段(斜纹+虚线描边, 与实绩实心段明确区分)
        if fc:
            fv = fc[-1][1]
            if fv > v:
                fw = max(x(fv) - bx, 2.0)  # 极小增幅也保证可见
                p.append(f'<rect x="{bx:.1f}" y="{cy-bh/2:.1f}" width="{fw:.1f}" '
                         f'height="{bh:.1f}" fill="{col}" opacity="0.45"/>')
                p.append(f'<rect x="{bx:.1f}" y="{cy-bh/2:.1f}" width="{fw:.1f}" '
                         f'height="{bh:.1f}" fill="url(#dgFc)" '
                         f'stroke="{col}" stroke-width="1" stroke-dasharray="3 2" '
                         f'data-tip="{_esc(c["name"])} IMF 预测 {fc[-1][0]}: {fv}% of GDP（预测非事实）">'
                         f'</rect>')
            else:
                # IMF 预测下降: 在预测位置画回撤刻度, 避免"无预测"与"预测太小看不见"混淆
                fx = x(fv)
                p.append(f'<line x1="{fx:.1f}" y1="{cy-bh/2-3:.1f}" x2="{fx:.1f}" '
                         f'y2="{cy+bh/2+3:.1f}" stroke="#faf8f4" stroke-width="4.5"/>')
                p.append(f'<line x1="{fx:.1f}" y1="{cy-bh/2-3:.1f}" x2="{fx:.1f}" '
                         f'y2="{cy+bh/2+3:.1f}" stroke="#4a463f" stroke-width="1.8" '
                         f'stroke-dasharray="3 2"/>')
                p.append(f'<rect x="{fx-4:.1f}" y="{cy-bh/2-3:.1f}" width="8" '
                         f'height="{bh+6:.1f}" fill="transparent" '
                         f'data-tip="{_esc(c["name"])} IMF 预测 {fc[-1][0]}: {fv}% of GDP'
                         f'（低于当前实绩 {v}%，预测非事实）"/>')
        p.append(f'<rect x="{ml}" y="{cy-bh/2:.1f}" width="{bx-ml:.1f}" height="{bh:.1f}" '
                 f'fill="{col}" rx="2" data-tip="{_esc(c["name"])} {c["latest_year"]} 实绩: {v}% of GDP">'
                 f'</rect>')
        # 数值 + 5年变化
        # 数值标签放在"实绩+预测"整体右端外侧, 避免压在斜纹段上
        lab_x = bx + 7
        if fc and fc[-1][1] > v:
            lab_x = x(fc[-1][1]) + 7
        d5 = c.get("chg_5y")
        chg = ""
        if d5 is not None:
            arw = "▲" if d5 > 0 else ("▼" if d5 < 0 else "→")
            ccol = "#c0757d" if d5 > 0 else ("#7fa085" if d5 < 0 else "#8a8578")
            chg = f' <tspan fill="{ccol}" font-size="9.5">{arw}{abs(d5):.1f}pp</tspan>'
        p.append(f'<text x="{lab_x:.1f}" y="{cy+4:.1f}" font-size="11" fill="#4a463f" '
                 f'font-weight="600" stroke="#faf8f4" stroke-width="2.8" '
                 f'paint-order="stroke" stroke-linejoin="round" '
                 f'data-tip="{_esc(c["name"])}：{c["latest_year"]} 实绩 {v}% of GDP，'
                 f'较 5 年前{"上升" if (d5 or 0) > 0 else "下降"} {abs(d5 or 0):.1f}pp'
                 f'（此箭头为历史变化，与斜纹/刻度所示的 IMF 未来预测方向无关）">'
                 f'{v:.1f}%{chg}</text>')
    p.append(f'<line x1="{ml}" y1="{h-mb:.1f}" x2="{w-mr}" y2="{h-mb:.1f}" stroke="#d8d4cb"/>')
    # 图例: 实绩 vs 预测
    if any(c.get("forecast") for c in ok):
        fy = (ok[0].get("forecast") or [(None, 0)])[-1][0]
        lx, ly2 = ml, h - 6
        p.append(f'<rect x="{lx}" y="{ly2-8}" width="14" height="9" fill="#8a8377" rx="1.5"/>')
        p.append(f'<text x="{lx+19}" y="{ly2}" font-size="9.5" fill="#7a7469">实绩</text>')
        p.append(f'<rect x="{lx+56}" y="{ly2-8}" width="14" height="9" fill="#8a8377" '
                 f'opacity="0.45"/>')
        p.append(f'<rect x="{lx+56}" y="{ly2-8}" width="14" height="9" fill="url(#dgFc)" '
                 f'stroke="#8a8377" stroke-width="0.9" stroke-dasharray="3 2"/>')
        p.append(f'<text x="{lx+75}" y="{ly2}" font-size="9.5" fill="#7a7469">'
                 f'IMF {fy} 预测(上升)</text>')
        tx = lx + 172
        p.append(f'<line x1="{tx}" y1="{ly2-9}" x2="{tx}" y2="{ly2+1}" stroke="#8a8377" '
                 f'stroke-width="1.4" stroke-dasharray="2 2"/>')
        p.append(f'<text x="{tx+8}" y="{ly2}" font-size="9.5" fill="#7a7469">'
                 f'IMF {fy} 预测(下降)</text>')
    p.append('</svg>')
    return "".join(p)


def _debt_gdp_trend_svg(countries, w=940, h=260):
    """近 15 年实绩折线(多国), 看谁在加杠杆。"""
    ok = [c for c in countries if c.get("status") == "ok" and len(c.get("series") or []) >= 3]
    if not ok:
        return ""
    ml, mr, mt, mb = 46, 96, 16, 26
    yrs = sorted({y for c in ok for y, _ in c["series"]})
    vals = [v for c in ok for _, v in c["series"]]
    y0, y1 = yrs[0], yrs[-1]
    vmin, vmax = min(vals) * 0.95, max(vals) * 1.05
    iw, ih = w - ml - mr, h - mt - mb
    palette = ["#6b8fb5", "#c08a7d", "#9aab97", "#c9a86a", "#9b8aa6",
               "#7fa085", "#b4636b", "#8a9bb5", "#c2a06a", "#7d9b96"]

    def X(y):
        return ml + ((y - y0) / max(y1 - y0, 1)) * iw

    def Y(v):
        return mt + ih - ((v - vmin) / max(vmax - vmin, 1e-9)) * ih

    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" '
         f'xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui">']
    for gv in range(int(vmin // 50) * 50, int(vmax) + 50, 50):
        if vmin <= gv <= vmax:
            gy = Y(gv)
            p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#ece9e2"/>')
            p.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#a8a49b" '
                     f'text-anchor="end">{gv}%</text>')
    for i, c in enumerate(ok):
        col = palette[i % len(palette)]
        pts = " ".join(f"{X(y):.1f},{Y(v):.1f}" for y, v in c["series"])
        p.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.7" '
                 f'stroke-linejoin="round"/>')
        ly, lv = c["series"][-1]
        p.append(f'<circle cx="{X(ly):.1f}" cy="{Y(lv):.1f}" r="2.6" fill="{col}"/>')
        for y, v in c["series"]:
            p.append(f'<circle cx="{X(y):.1f}" cy="{Y(v):.1f}" r="5" fill="transparent" '
                     f'data-tip="{_esc(c["name"])} {y}: {v}% of GDP"/>')
    # 末端标签防重叠: 按 y 排序后贪心下推(最小间距 11px), 并用引导线连回真实点
    lbls = []
    for i, c in enumerate(ok):
        ly, lv = c["series"][-1]
        lbls.append({"y0": Y(lv), "x0": X(ly), "txt": f'{c["name"]} {lv:.0f}',
                     "col": palette[i % len(palette)]})
    lbls.sort(key=lambda d: d["y0"])
    minsep, prev = 11.0, -1e9
    for d in lbls:
        d["y"] = max(d["y0"], prev + minsep)
        prev = d["y"]
    # 整体上移避免溢出底部
    over = lbls[-1]["y"] - (mt + ih) if lbls else 0
    if over > 0:
        for d in lbls:
            d["y"] -= over
    for d in lbls:
        if abs(d["y"] - d["y0"]) > 1.5:
            p.append(f'<line x1="{d["x0"]:.1f}" y1="{d["y0"]:.1f}" x2="{w-mr+3}" '
                     f'y2="{d["y"]-3:.1f}" stroke="{d["col"]}" stroke-width="0.7" '
                     f'opacity="0.45"/>')
        p.append(f'<text x="{w-mr+6}" y="{d["y"]:.1f}" font-size="9.5" fill="{d["col"]}">'
                 f'{_esc(d["txt"])}</text>')
    for y in yrs:
        if (y - y0) % 3 == 0 or y == y1:
            p.append(f'<text x="{X(y):.1f}" y="{h-mb+15}" font-size="9" fill="#8a8578" '
                     f'text-anchor="middle">{y}</text>')
    p.append(f'<line x1="{ml}" y1="{h-mb:.1f}" x2="{w-mr}" y2="{h-mb:.1f}" stroke="#d8d4cb"/>')
    p.append('</svg>')
    return "".join(p)


def _debt_gdp_html(dg):
    """世界前十经济体 政府债务/GDP。dg: fetch_debt_to_gdp()。"""
    if not dg or dg.get("status") != "ok" or not dg.get("countries"):
        note = (dg or {}).get("note") or ""
        return (f'<p class="empty">世界前十经济体债务/GDP 数据未就绪。'
                f'{("（" + _esc(note) + "）") if note else ""}</p>')
    cs = dg["countries"]
    ok = [c for c in cs if c.get("status") == "ok"]
    yr = dg.get("as_of_year")
    # 徽章按 IMF WEO 年度口径: 用实绩年末作 as_of
    badge = _stale_badge(f"{yr}-12-31", "imf_weo") if yr else ""
    rising = [c for c in ok if (c.get("chg_5y") or 0) > 0]
    rising.sort(key=lambda c: -(c.get("chg_5y") or 0))
    top_r = "、".join(f'{c["name"]}(+{c["chg_5y"]:.1f}pp)' for c in rising[:3]) or "无"
    over100 = [c["name"] for c in ok if c["latest"] > 100]
    fc_yr = None
    for c in ok:
        if c.get("forecast"):
            fc_yr = c["forecast"][-1][0]
            break
    # 找一个"历史去杠杆但 IMF 预测回升"的真实反例(不写死国名, 随数据自适应)
    _cex = ""
    for c in cs:
        if c.get("status") != "ok" or not c.get("forecast"):
            continue
        d5c, fvc = c.get("chg_5y"), c["forecast"][-1][1]
        if d5c is not None and d5c < 0 and fvc > c["latest"]:
            _cex = (f'（例：{c["name"]}近 5 年 ▼{abs(d5c):.1f}pp 去杠杆，'
                    f'但 IMF 预测 {fc_yr} 年回升至 {fvc:.1f}%）')
            break
    return (
        f'<div class="dg-wrap">'
        f'<div class="dg-head">🌍 世界前十大经济体 · 政府债务 / GDP'
        f'<span class="dg-asof">实绩 {yr} 年{badge}</span></div>'
        f'{_debt_gdp_bar_svg(cs)}'
        f'<div class="dg-sub">近 15 年走势（实绩）</div>'
        f'{_debt_gdp_trend_svg(cs)}'
        f'<div class="ci-how"><b>如何看：</b>政府债务/GDP 衡量一国政府负债相对经济规模的水平，'
        f'是判断<b>主权债务可持续性</b>与长期利率压力的核心指标。'
        f'超过 <b>100%</b>（红色虚线）意味着政府债务已超过全年 GDP；'
        f'当前超过 100% 的有 <b>{_esc("、".join(over100)) if over100 else "无"}</b>。'
        f'比绝对水平更重要的是<b>方向</b>——近 5 年仍在加杠杆的：<b>{_esc(top_r)}</b>。'
        f'<br><b>⚠️ 频率与口径诚实说明：</b>该数据源自 <b>IMF WEO，本质是【年度】数据</b>，'
        f'一年仅发布两次（4 月 / 10 月）。本页每次构建都会重新拉取，'
        f'但<b>两次 WEO 之间数值不会变化</b>——请勿将其理解为周度/月度更新的指标。'
        f'条形图中<b>实心段为实绩</b>，'
        f'{f"<b>斜纹段为 IMF 对 {fc_yr} 年的预测</b>（预测非事实，仅供参考）；预测低于当前实绩时改画<b>虚线刻度</b>。" if fc_yr else ""}'
        f'注意：条形右侧的 <b>▲/▼ pp 箭头是「近 5 年历史变化」</b>，'
        f'与斜纹/刻度代表的「IMF 未来预测方向」是两回事，两者可能相反{_esc(_cex)}。'
        f'数据源：{_linkify_sources(dg.get("source", ""))}。</div>'
        f'</div>'
    )


# ─────────── 中国 CIPS 跨境人民币支付 ───────────
def _nice_top(v, divs=4):
    """把轴上限抬到「能被 divs 等分成整齐刻度」且尽量贴合数据的值。

    ★两个坑:
      ① 只把上限取整不够 —— 刻度是 top/divs, 25/4=6.25 依旧难读;
      ② 步长吸附太粗会把 21.7 顶到 40, 浪费近半图高。
      正解: 枚举候选步长, 取「能覆盖 v 的最小整齐步长」。
    """
    import math
    if v <= 0:
        return 1.0
    raw = v / divs
    exp = math.floor(math.log10(raw))
    for e in (exp, exp + 1):
        base = 10 ** e
        for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
            step = m * base
            if step * divs >= v:
                return step * divs
    return 10 ** (exp + 1) * divs


# ─────────── AI 产业链: 自由现金流 & 信用维度 ───────────
# ★颜色按 AI_UNIVERSE 的实际组名顺序分配, 绝不硬编码组名字符串:
#   曾因手写的组名与数据层不一致(如"芯片/半导体" vs 实际"芯片/加速器"),
#   导致 13 家静默落到灰色兜底色且图例只剩 1 项。
_AI_PALETTE = ["#4ea1ff", "#39c07c", "#e0a92e", "#c77dff", "#4fd1c5", "#f08fc0"]


def _ai_colors(names):
    """{组名: 颜色}, 按出现顺序取色。"""
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return {n: _AI_PALETTE[i % len(_AI_PALETTE)] for i, n in enumerate(seen)}


def _ai_fcf_svg(groups, w=940, h=380):
    """AI 产业链 FCF 分组柱状图。正负双向, 零轴居中按数据自适应。"""
    rows = []
    for g in groups:
        for m in g.get("members", []):
            rows.append((g["name"], m))
    if not rows:
        return ""
    vals = [m["fcf"] / 1e9 for _, m in rows if m.get("fcf") is not None]
    if not vals:
        return ""
    ml, mr, mt, mb = 62, 16, 30, 76
    pw, ph = w - ml - mr, h - mt - mb
    vmax, vmin = max(vals + [0]), min(vals + [0])
    top = _nice_top(vmax * 1.10, 4) if vmax > 0 else 0
    bot = -_nice_top(-vmin * 1.15, 2) if vmin < 0 else 0
    span = (top - bot) or 1
    y0 = mt + ph * top / span          # 零轴像素位置
    colors = _ai_colors([g for g, _ in rows])

    def py(v):
        return mt + ph * (top - v) / span

    n = len(rows)
    step = pw / n
    bw = step * 0.62
    p = [f'<svg viewBox="0 0 {w} {h}" class="aifcf-svg" '
         f'preserveAspectRatio="xMidYMid meet">']
    # 网格 + 刻度(正负分别等分, 保证 0 一定是一根线)
    ticks = [top * k / 4 for k in range(5)]
    if bot < 0:
        ticks += [bot * k / 2 for k in range(1, 3)]
    for tv in ticks:
        yy = py(tv)
        dash = "" if abs(tv) < 1e-9 else ' stroke-dasharray="3 3"'
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1"{dash}/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.0f}</text>')
    p.append(f'<text x="{ml-52}" y="{mt-12}" font-size="10" '
             f'fill="#8b93a7">十亿美元</text>')

    for i, (gname, m) in enumerate(rows):
        cx = ml + step * (i + 0.5)
        col = colors.get(gname, "#8b93a7")
        fcf = m.get("fcf")
        if fcf is None:
            p.append(f'<text x="{cx:.1f}" y="{y0-6:.1f}" text-anchor="middle" '
                     f'font-size="9" fill="#6b7280">n/a</text>')
        else:
            v = fcf / 1e9
            yv = py(v)
            ytop, hh = (yv, y0 - yv) if v >= 0 else (y0, yv - y0)
            fill = col if v >= 0 else "#e05c5c"
            tip = (f'{m["ticker"]}·{m["name"]}｜FY{(m.get("fy") or "")[:7]}'
                   f'｜经营现金流 {m["ocf"]/1e9:,.1f}B｜资本开支 '
                   f'{m["capex"]/1e9:,.1f}B｜自由现金流 {v:+,.1f}B')
            p.append(f'<rect x="{cx-bw/2:.1f}" y="{ytop:.1f}" width="{bw:.1f}" '
                     f'height="{max(hh,0.6):.1f}" fill="{fill}" opacity="0.88">'
                     f'<title>{_esc(tip)}</title></rect>')
            lv = f'{v:+,.0f}' if abs(v) >= 1 else f'{v:+,.1f}'
            ly = (ytop - 3) if v >= 0 else (ytop + hh + 9)
            p.append(f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                     f'font-size="8.5" fill="#aab3c5">{lv}</text>')
        p.append(f'<text x="{cx:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="10" fill="#c8cee0">{_esc(m["ticker"])}</text>')
        fy = (m.get("fy") or "")[:7]
        if fy:
            p.append(f'<text x="{cx:.1f}" y="{mt+ph+25:.1f}" '
                     f'text-anchor="middle" font-size="8.5" fill="#7c8496">'
                     f'{_esc(fy)}</text>')

    lx = ml
    for gname, col in colors.items():
        p.append(f'<rect x="{lx}" y="{h-30}" width="11" height="11" '
                 f'fill="{col}" opacity="0.88"/>')
        p.append(f'<text x="{lx+15}" y="{h-21}" font-size="9.5" '
                 f'fill="#8b93a7">{_esc(gname)}</text>')
        lx += 26 + len(gname) * 10.5
    p.append(f'<rect x="{lx}" y="{h-30}" width="11" height="11" '
             f'fill="#e05c5c" opacity="0.88"/>')
    p.append(f'<text x="{lx+15}" y="{h-21}" font-size="9.5" fill="#8b93a7">'
             f'负自由现金流</text>')
    p.append("</svg>")
    return "".join(p)


def _ai_credit_svg(rows, w=940, h=400):
    """信用维度散点: X=净债务/EBITDA(杠杆), Y=利息保障倍数(对数轴)。"""
    import math
    pts = [r for r in rows
           if r.get("leverage") is not None and r.get("coverage") is not None
           and r["coverage"] > 0]
    if not pts:
        return ""
    ml, mr, mt, mb = 62, 18, 20, 74
    pw, ph = w - ml - mr, h - mt - mb
    xs = [r["leverage"] for r in pts]
    xhi = _nice_top(max(xs + [1]), 4)
    xlo = -_nice_top(-min(xs + [0]), 2) if min(xs) < 0 else 0
    xspan = (xhi - xlo) or 1
    ymin, ymax = 1.0, max(r["coverage"] for r in pts) * 1.6
    colors = _ai_colors([r["group"] for r in rows])
    placed = []                       # 已放置标签坐标, 用于避让

    def px(v):
        return ml + pw * (v - xlo) / xspan

    def py(v):
        v = max(v, ymin)
        return (mt + ph - ph * (math.log10(v) - math.log10(ymin))
                / (math.log10(ymax) - math.log10(ymin)))

    p = [f'<svg viewBox="0 0 {w} {h}" class="aicr-svg" '
         f'preserveAspectRatio="xMidYMid meet">']
    # Y 轴(对数) 刻度
    yt = [1, 3, 10, 30, 100, 300, 1000]
    for tv in yt:
        if tv > ymax:
            break
        yy = py(tv)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,}x</text>')
    # X 轴刻度
    for k in range(5):
        tv = xlo + (xhi - xlo) * k / 4
        xx = px(tv)
        p.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" '
                 f'y2="{mt+ph}" stroke="#2a2f3a" stroke-width="1" '
                 f'stroke-dasharray="3 3"/>')
        p.append(f'<text x="{xx:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="10" fill="#8b93a7">{tv:,.1f}x</text>')
    # 零杠杆参考线(净现金/净负债分界)
    if xlo < 0 < xhi:
        zx = px(0)
        p.append(f'<line x1="{zx:.1f}" y1="{mt}" x2="{zx:.1f}" y2="{mt+ph}" '
                 f'stroke="#4a5262" stroke-width="1.4"/>')
        p.append(f'<text x="{zx-5:.1f}" y="{mt+11}" text-anchor="end" '
                 f'font-size="8.5" fill="#6b7280">← 净现金</text>')
        p.append(f'<text x="{zx+5:.1f}" y="{mt+11}" font-size="8.5" '
                 f'fill="#6b7280">净负债 →</text>')
    # 利息保障 <3x 警戒带
    wy = py(3)
    p.append(f'<rect x="{ml}" y="{wy:.1f}" width="{pw}" '
             f'height="{mt+ph-wy:.1f}" fill="#e05c5c" opacity="0.07"/>')
    p.append(f'<text x="{ml+pw-6}" y="{mt+ph-7:.1f}" text-anchor="end" '
             f'font-size="8.5" fill="#a8646e">利息保障 &lt; 3x 偿息压力区</text>')
    p.append(f'<text x="{ml-7}" y="{mt-6}" text-anchor="end" font-size="10" '
             f'fill="#8b93a7">利息保障</text>')
    p.append(f'<text x="{ml+pw}" y="{mt+ph+30:.1f}" text-anchor="end" '
             f'font-size="10" fill="#8b93a7">净债务 / EBITDA →</text>')

    for r in sorted(pts, key=lambda z: -z["coverage"]):
        cx, cy = px(r["leverage"]), py(r["coverage"])
        col = colors.get(r["group"], "#8b93a7")
        nd = r.get("net_debt")
        tip = (f'{r["ticker"]}·{r["name"]}｜FY{(r.get("fy") or "")[:7]}'
               f'｜净债务/EBITDA {r["leverage"]:+,.2f}x'
               f'｜利息保障 {r["coverage"]:,.1f}x'
               f'｜净债务 {nd/1e9:+,.1f}B｜EBITDA {r["ebitda"]/1e9:,.1f}B')
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{col}" '
                 f'opacity="0.85" stroke="#11141a" stroke-width="1">'
                 f'<title>{_esc(tip)}</title></circle>')
        # 标签避让: 与已放置标签太近则改放下方/左右, 避免糊成一团
        ly = cy - 10
        for _ in range(8):
            if not any(abs(ly - qy) < 11 and abs(cx - qx) < 34
                       for qx, qy in placed):
                break
            ly = (cy + 17) if abs(ly - (cy - 10)) < 0.1 else ly + 11
        placed.append((cx, ly))
        p.append(f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#c8cee0">{_esc(r["ticker"])}</text>')

    lx = ml
    for gname, col in colors.items():
        if not any(r["group"] == gname for r in pts):
            continue
        p.append(f'<circle cx="{lx+5}" cy="{h-25}" r="5" fill="{col}" '
                 f'opacity="0.85"/>')
        p.append(f'<text x="{lx+15}" y="{h-21}" font-size="9.5" '
                 f'fill="#8b93a7">{_esc(gname)}</text>')
        lx += 26 + len(gname) * 10.5
    p.append("</svg>")
    return "".join(p)


def _ai_fcf_html(fc, cr):
    """AI 产业链自由现金流 + 信用维度。fc: fetch_ai_fcf(), cr: fetch_ai_credit()。"""
    if not fc or fc.get("status") != "ok":
        return ('<p class="empty">AI 产业链自由现金流数据未就绪'
                '（SEC EDGAR 拉取失败）。</p>')
    rows = [(g["name"], m) for g in fc["groups"] for m in g.get("members", [])]
    oks = [m for _, m in rows if m.get("fcf") is not None]
    as_of = fc.get("as_of") or ""
    badge = _stale_badge(as_of, "annual_report") if as_of else ""
    pos = [m for m in oks if m["fcf"] > 0]
    neg = [m for m in oks if m["fcf"] <= 0]
    tot = sum(m["fcf"] for m in oks) / 1e9
    capex = sum(m["capex"] for m in oks) / 1e9
    neg_txt = "、".join(f'{m["ticker"]} {m["fcf"]/1e9:+,.1f}B'
                       for m in sorted(neg, key=lambda z: z["fcf"])) or "无"
    ex_txt = "；".join(f'{n}（{why}）' for n, why in fc.get("excluded", []))

    h = [f'<div class="oil-meta">最新财年（{_esc(as_of[:7])}）{badge} · '
         f'覆盖 <b>{fc.get("ok_count")}/{fc.get("total_count")}</b> 家 · '
         f'合计自由现金流 <b style="color:'
         f'{"#39c07c" if tot >= 0 else "#e05c5c"}">{tot:+,.0f}B</b> · '
         f'合计资本开支 <b style="color:#e0a92e">{capex:,.0f}B</b></div>']
    h.append(f'<div class="oil-meta">正自由现金流 <b>{len(pos)}</b> 家，'
             f'负自由现金流 <b>{len(neg)}</b> 家：{_esc(neg_txt)}。</div>')
    h.append(_ai_fcf_svg(fc["groups"]))
    h.append(f'<p class="cips-note">口径：标准自由现金流 = 经营现金流 − 资本开支，'
             f'取自各公司 10-K/20-F 年报官方申报值，未扣融资租赁本金'
             f'（多家未披露该字段，强行调整会造成口径不可比）。'
             f'各公司财年截止日不同（柱下已标注实际财年），'
             f'跨公司比较时须注意期间不完全重合。'
             f'年报一年更新一次，非日频指标。'
             f'{("排除：" + _esc(ex_txt) + "。") if ex_txt else ""}</p>')

    # ── 信用维度 ──
    if cr and cr.get("status") == "ok":
        crs = cr.get("rows") or []
        lev = [r for r in crs if r.get("leverage") is not None]
        na_lev = [r for r in crs if r.get("leverage") is None]
        hi = sorted([r for r in lev if r["leverage"] > 0],
                    key=lambda z: -z["leverage"])[:3]
        cash = [r for r in lev if r["leverage"] < 0]
        thin = sorted([r for r in crs if r.get("coverage") is not None
                       and r["coverage"] < 3], key=lambda z: z["coverage"])
        hi_txt = "、".join(f'{r["ticker"]} {r["leverage"]:,.2f}x'
                          for r in hi) or "无"
        thin_txt = "、".join(f'{r["ticker"]} {r["coverage"]:,.1f}x'
                            for r in thin) or "无"
        h.append(f'<div class="part-title">信用维度：杠杆与偿息能力</div>')
        h.append(f'<div class="oil-meta">杠杆覆盖 <b>{cr.get("lev_n")}/'
                 f'{cr.get("total")}</b> 家 · 利息保障覆盖 <b>{cr.get("cov_n")}/'
                 f'{cr.get("total")}</b> 家 · 净现金（负杠杆）<b>{len(cash)}</b> 家 · '
                 f'杠杆最高：{_esc(hi_txt)}</div>')
        h.append(f'<div class="oil-meta">利息保障低于 3x（偿息压力）：'
                 f'<b style="color:{"#e05c5c" if thin else "#39c07c"}">'
                 f'{_esc(thin_txt)}</b></div>')
        h.append(_ai_credit_svg(crs))
        na_txt = "；".join(f'{r["ticker"]}（{r["note"]}）'
                          for r in na_lev if r.get("note"))
        h.append(f'<p class="cips-note">口径：净债务 = 长期债务 + 短期债务 − '
                 f'现金及等价物 − 短期投资；EBITDA = 营业利润 + 折旧摊销'
                 f'（近似值，未加回股权激励等非现金项）；'
                 f'利息保障倍数 = EBITDA / 利息支出。纵轴为对数刻度。'
                 f'负杠杆表示净现金（现金及短投多于全部债务）。'
                 f'★本图为财报偿债能力指标，<b>不是市场信用利差</b>：'
                 f'免费公开源已无单名企业债成交利差'
                 f'（FINRA TRACE 公开端点关闭、交易所与财经终端均需付费或拒访），'
                 f'用股价波动等替代指标凑数会失真，故不采用。'
                 f'{("未能取得杠杆的公司：" + _esc(na_txt) + "。") if na_txt else ""}'
                 f'这些公司在其近年年报中未以标准 XBRL 科目申报相应字段，'
                 f'按项目铁律标注 n/a，不做估算填充。</p>')
    else:
        h.append('<p class="empty">信用维度（净债务/EBITDA、利息保障倍数）'
                 '未就绪。</p>')
    return "".join(h)


def _cips_svg(monthly, w=940, h=330):
    """月度金额柱(第三方回补月用斜纹) + 日均金额折线(仅官方月有)。

    ★双口径同图: 柱=月度总额(受工作日天数影响), 线=日均(剔除天数效应)。
    ★第三方回补月无工作日数 → 日均线在该段不画(绝不插值假装连续)。
    """
    if not monthly:
        return ""
    ml, mr, mt, mb = 74, 78, 22, 46
    pw, ph = w - ml - mr, h - mt - mb
    n = len(monthly)
    amax = max(m["amount_yi"] for m in monthly)
    if amax <= 0:
        return ""
    atop = _nice_top(amax * 1.15)
    bw = pw / n * 0.62
    step = pw / n

    def bx(i):
        return ml + step * i + (step - bw) / 2

    def by(v):
        return mt + ph - (v / atop) * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cips-svg" '
             f'preserveAspectRatio="xMidYMid meet">',
             '<defs><pattern id="cipsHatch" width="6" height="6" '
             'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<rect width="6" height="6" fill="#2563eb" opacity=".30"/>'
             '<line x1="0" y1="0" x2="0" y2="6" stroke="#2563eb" '
             'stroke-width="3" opacity=".75"/></pattern></defs>']

    # 左轴(金额 万亿元) —— 亿元/10000 = 万亿元
    for k in range(5):
        v = atop * k / 4
        y = by(v)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6b7280">{v/10000:.1f}</text>')
    parts.append(f'<text x="{ml-8}" y="{mt-8}" text-anchor="end" font-size="10" '
                 f'fill="#2563eb" font-weight="600">万亿元/月</text>')

    # 柱: 月度总额
    for i, m in enumerate(monthly):
        x, y = bx(i), by(m["amount_yi"])
        hh = mt + ph - y
        third = m["src"] == "third_party"
        fill = "url(#cipsHatch)" if third else "#2563eb"
        op = "1" if third else ".82"
        wd = m["workdays"]
        da = m["avg_amount_yi"]
        tip = (f'{m["ym"]}｜金额 {m["amount_yi"]:,.0f} 亿元'
               f'（{m["amount_yi"]/10000:.2f} 万亿）｜笔数 {m["count"]:,}'
               f'｜工作日 {wd if wd else "n/a"}'
               f'｜日均 {f"{da:,.0f} 亿元" if da else "n/a"}'
               f'｜{"第三方回补" if third else "CIPS 官方"}')
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{hh:.1f}" fill="{fill}" opacity="{op}" rx="2">'
                     f'<title>{_esc(tip)}</title></rect>')

    # 右轴 + 日均折线(仅官方月, 断开处不连)
    davg = [(i, m["avg_amount_yi"]) for i, m in enumerate(monthly)
            if m.get("avg_amount_yi")]
    if davg:
        dmax = _nice_top(max(v for _, v in davg) * 1.25)
        segs, cur = [], []
        for i, m in enumerate(monthly):
            v = m.get("avg_amount_yi")
            if v:
                cur.append((bx(i) + bw / 2,
                            mt + ph - (v / dmax) * ph, m["ym"], v))
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        for seg in segs:
            if len(seg) > 1:
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in seg)
                parts.append(f'<polyline points="{pts}" fill="none" '
                             f'stroke="#dc2626" stroke-width="2.4" '
                             f'stroke-linejoin="round"/>')
            for x, y, ym, v in seg:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" '
                             f'fill="#fff" stroke="#dc2626" stroke-width="2">'
                             f'<title>{_esc(f"{ym}｜日均 {v:,.0f} 亿元")}</title>'
                             f'</circle>')
        for k in range(5):
            v = dmax * k / 4
            y = mt + ph - (v / dmax) * ph
            parts.append(f'<text x="{ml+pw+8}" y="{y+4:.1f}" font-size="11" '
                         f'fill="#dc2626">{v/10000:.2f}</text>')
        parts.append(f'<text x="{ml+pw+8}" y="{mt-8}" font-size="10" '
                     f'fill="#dc2626" font-weight="600">万亿元/日</text>')

    # X 轴标签(每 2 个month 标一次, 避免拥挤)
    lab_every = 1 if n <= 12 else 2
    for i, m in enumerate(monthly):
        if i % lab_every and i != n - 1:
            continue
        x = bx(i) + bw / 2
        parts.append(f'<text x="{x:.1f}" y="{mt+ph+16}" text-anchor="middle" '
                     f'font-size="9.5" fill="#6b7280" '
                     f'transform="rotate(-38 {x:.1f} {mt+ph+16})">'
                     f'{m["ym"][2:]}</text>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="#9ca3af" stroke-width="1.2"/>')

    # 图例
    lx, ly = ml, h - 8
    parts.append(f'<rect x="{lx}" y="{ly-9}" width="11" height="11" '
                 f'fill="#2563eb" opacity=".82" rx="2"/>')
    parts.append(f'<text x="{lx+16}" y="{ly}" font-size="10.5" fill="#374151">'
                 f'月度总额(官方)</text>')
    parts.append(f'<rect x="{lx+112}" y="{ly-9}" width="11" height="11" '
                 f'fill="url(#cipsHatch)" rx="2"/>')
    parts.append(f'<text x="{lx+128}" y="{ly}" font-size="10.5" fill="#374151">'
                 f'月度总额(第三方回补)</text>')
    parts.append(f'<line x1="{lx+272}" y1="{ly-4}" x2="{lx+296}" y2="{ly-4}" '
                 f'stroke="#dc2626" stroke-width="2.4"/>')
    parts.append(f'<circle cx="{lx+284}" cy="{ly-4}" r="3.6" fill="#fff" '
                 f'stroke="#dc2626" stroke-width="2"/>')
    parts.append(f'<text x="{lx+302}" y="{ly}" font-size="10.5" fill="#374151">'
                 f'日均金额(仅官方月，剔除工作日天数效应)</text>')
    parts.append("</svg>")
    return "".join(parts)


def _cips_annual_svg(annual, w=940, h=190):
    """历年金额柱(官方一手, 2015 至今)。"""
    if not annual:
        return ""
    ml, mr, mt, mb = 74, 24, 18, 30
    pw, ph = w - ml - mr, h - mt - mb
    n = len(annual)
    amax = _nice_top(max(a for _, _, a in annual) * 1.14, divs=3)
    step, bw = pw / n, pw / n * 0.6
    parts = [f'<svg viewBox="0 0 {w} {h}" class="cips-svg" '
             f'preserveAspectRatio="xMidYMid meet">']
    for k in range(4):
        v = amax * k / 3
        y = mt + ph - (v / amax) * ph
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6b7280">{v/10000:.0f}</text>')
    parts.append(f'<text x="{ml-8}" y="{mt-6}" text-anchor="end" font-size="10" '
                 f'fill="#0f766e" font-weight="600">万亿元/年</text>')
    prev = None
    for i, (y_, c, a) in enumerate(annual):
        x = ml + step * i + (step - bw) / 2
        yy = mt + ph - (a / amax) * ph
        yoy = f"｜同比 {((a/prev-1)*100):+.1f}%" if prev else ""
        prev = a
        parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{bw:.1f}" '
                     f'height="{mt+ph-yy:.1f}" fill="#0f766e" opacity=".78" '
                     f'rx="2"><title>'
                     f'{_esc(f"{y_} 年｜金额 {a:,.0f} 亿元（{a/10000:.1f} 万亿）｜笔数 {c:,}{yoy}")}'
                     f'</title></rect>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{mt+ph+14}" '
                     f'text-anchor="middle" font-size="10" fill="#6b7280">'
                     f'{y_}</text>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="#9ca3af" stroke-width="1.2"/>')
    parts.append("</svg>")
    return "".join(parts)


def _cips_html(cp):
    """中国 CIPS 使用量。cp: fetch_cips()。"""
    if not cp or cp.get("status") != "ok" or not cp.get("monthly"):
        note = (cp or {}).get("note") or ""
        return (f'<p class="empty">CIPS 跨境人民币支付数据未就绪。'
                f'{("（" + _esc(note) + "）") if note else ""}</p>')
    ms = cp["monthly"]
    ann = cp.get("annual") or []
    as_of = cp.get("as_of") or ""
    badge = _stale_badge(f"{as_of}-28", "cips") if as_of else ""
    last = ms[-1]
    off_ms = [m for m in ms if m["src"] == "official"]

    # 同比: 与去年同月比(只在两端都有真实值时算)
    idx = {m["ym"]: m for m in ms}
    y, mo = int(as_of[:4]), int(as_of[5:7])
    prev_ym = f"{y-1}-{mo:02d}"
    yoy_txt = "n/a（缺去年同月数据）"
    if prev_ym in idx:
        p = idx[prev_ym]["amount_yi"]
        if p:
            yoy_txt = (f'{(last["amount_yi"]/p-1)*100:+.1f}%'
                       f'（对比 {prev_ym}）')

    # 日均金额的真实极值(仅官方月)
    da_txt = "n/a"
    if off_ms:
        hi = max(off_ms, key=lambda m: m["avg_amount_yi"] or 0)
        lo = min(off_ms, key=lambda m: m["avg_amount_yi"] or 9e18)
        if hi.get("avg_amount_yi") and lo.get("avg_amount_yi"):
            da_txt = (f'最高 {hi["ym"]} {hi["avg_amount_yi"]:,.0f} 亿元/日，'
                      f'最低 {lo["ym"]} {lo["avg_amount_yi"]:,.0f} 亿元/日')

    # 年度同比(官方一手)
    ann_txt = ""
    if len(ann) >= 2:
        (py, _, pa), (ly, _, la) = ann[-2], ann[-1]
        ann_txt = (f'{ly} 年全年 <b>{la/10000:.1f} 万亿元</b>'
                   f'（较 {py} 年 {((la/pa-1)*100):+.1f}%）；')

    third_n = cp.get("third_months", 0)
    off_n = cp.get("official_months", 0)
    _lav = last.get("avg_amount_yi")
    kpi_avg = f"{_lav:,.0f} 亿元" if _lav else "n/a"
    src_note = ""
    if third_n:
        src_note = (f'图中 <b>{off_n} 个月为 CIPS 官方逐月披露</b>，'
                    f'<b>{third_n} 个月（斜纹）为第三方 chinadata.live 回补</b>'
                    f'——官方仅在网站挂当年月度表，往年月度表已下架。'
                    f'回补数据已用官方重叠月<b>逐月比对验证一致</b>后才采用；'
                    f'该源不含工作日数，故这些月份<b>不画日均线</b>（标 n/a），'
                    f'绝不用插值伪造。')

    return (
        f'<div class="cips-wrap">'
        f'<div class="cips-head">🇨🇳 中国 CIPS · 跨境人民币支付系统使用量'
        f'<span class="cips-asof">最新 {_esc(as_of)}{badge}</span></div>'
        f'<div class="cips-kpis">'
        f'<div class="cips-kpi"><span>最新月金额</span>'
        f'<b>{last["amount_yi"]/10000:.2f} 万亿元</b></div>'
        f'<div class="cips-kpi"><span>最新月笔数</span>'
        f'<b>{last["count"]:,}</b></div>'
        f'<div class="cips-kpi"><span>同比(金额)</span>'
        f'<b>{_esc(yoy_txt)}</b></div>'
        f'<div class="cips-kpi"><span>最新月日均</span>'
        f'<b>{kpi_avg}</b>'
        f'</div></div>'
        f'{_cips_svg(ms)}'
        f'<div class="cips-sub">历年全年金额（CIPS 官方一手）</div>'
        f'{_cips_annual_svg(ann)}'
        f'<div class="ci-how"><b>如何看：</b>CIPS 是中国人民银行主导的<b>跨境人民币清算基础设施</b>，'
        f'常被视作观察<b>人民币国际化进程</b>与跨境结算去美元化叙事的一个量化抓手。'
        f'{ann_txt}近 {len(ms)} 个月区间内，日均金额 {_esc(da_txt)}。'
        f'<br><b>⚠️ 口径陷阱（重要）：</b>'
        f'①<b>看日均、别只看月度总额</b>——月度总额受当月<b>工作日天数</b>影响很大'
        f'（如春节所在月工作日少，总额天然回落，并不代表使用强度下降）；'
        f'红线的<b>日均金额已剔除天数效应</b>，是更干净的趋势指标。'
        f'②<b>CIPS 增长 ≠ 去美元化</b>——CIPS 处理的是<b>人民币</b>跨境清算，'
        f'其增长同时包含中国自身贸易/投资规模扩张、原本走代理行渠道的业务<b>迁移至 CIPS</b>、'
        f'以及离岸人民币资金调拨，<b>不能直接换算为美元份额的等量流失</b>。'
        f'③该口径为<b>支付指令处理金额</b>，同一笔跨境交易可能涉及多腿清算，'
        f'与 SWIFT 人民币报文份额<b>口径不同、不可直接相加或相互替代</b>。'
        f'{f"<br><b>📌 数据来源构成：</b>{src_note}" if src_note else ""}'
        f'<br>数据源：{_linkify_sources(cp.get("source", ""))}。</div>'
        f'</div>'
    )


# ─────────── 美国分评级公司债 ───────────
def _corp_credit_svg(ratings, key="oas_series", w=940, h=280, unit=" %"):
    """各评级序列多线图(OAS 或 收益率)。CCC 波动极大 → 用对数式压缩不做, 保持真实比例,
    但把 CCC 单独用粗线+高亮色, 避免其它线被压平到看不见。"""
    ok = [r for r in ratings if r.get(key)]
    if not ok:
        return ""
    ml, mr, mt, mb = 48, 92, 16, 28
    alld = sorted({d for r in ok for d, _ in r[key]})
    if len(alld) < 2:
        return ""
    d0, d1 = alld[0], alld[-1]
    vals = [v for r in ok for _, v in r[key]]
    vmin, vmax = min(vals), max(vals)
    pad = (vmax - vmin) * 0.08 or 0.5
    vmin, vmax = max(0, vmin - pad), vmax + pad
    iw, ih = w - ml - mr, h - mt - mb
    t0 = datetime.date.fromisoformat(d0).toordinal()
    t1 = datetime.date.fromisoformat(d1).toordinal()
    colors = {"AAA": "#7fa085", "AA": "#8a9bb5", "A": "#6b8fb5", "BBB": "#c9a86a",
              "BB": "#c08a7d", "B": "#b4636b", "CCC及以下": "#8e3b47"}

    def X(ds):
        return ml + ((datetime.date.fromisoformat(ds).toordinal() - t0) / max(t1 - t0, 1)) * iw

    def Y(v):
        return mt + ih - ((v - vmin) / max(vmax - vmin, 1e-9)) * ih

    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" '
         f'xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui">']
    step = 2 if (vmax - vmin) > 8 else 1
    gv = 0
    while gv <= vmax:
        if gv >= vmin:
            gy = Y(gv)
            p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#ece9e2"/>')
            p.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="9" fill="#a8a49b" '
                     f'text-anchor="end">{gv}%</text>')
        gv += step
    for r in ok:
        lab = r["label"]
        col = colors.get(lab, "#8a8377")
        wdt = 2.1 if lab == "CCC及以下" else 1.5
        pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in r[key])
        p.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{wdt}" '
                 f'stroke-linejoin="round" opacity="0.92"/>')
        ld, lv = r[key][-1]
        p.append(f'<circle cx="{X(ld):.1f}" cy="{Y(lv):.1f}" r="2.6" fill="{col}"/>')
        # hit-band tooltip(稀疏采样避免 DOM 爆炸)
        n = len(r[key])
        stp = max(1, n // 90)
        for i in range(0, n, stp):
            d, v = r[key][i]
            p.append(f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="4.5" fill="transparent" '
                     f'data-tip="{_esc(lab)} {d}: {v:.2f}{_esc(unit)}"/>')
    # 末端标签防重叠(评级线常挤在一起, 尤其 IG 段)
    lbls = []
    for r in ok:
        ld, lv = r[key][-1]
        lbls.append({"y0": Y(lv), "x0": X(ld), "txt": f'{r["label"]} {lv:.2f}',
                     "col": colors.get(r["label"], "#8a8377"),
                     "bold": r["label"] == "CCC及以下"})
    lbls.sort(key=lambda d: d["y0"])
    minsep, prev = 11.0, -1e9
    for d in lbls:
        d["y"] = max(d["y0"], prev + minsep)
        prev = d["y"]
    over = lbls[-1]["y"] - (mt + ih) if lbls else 0
    if over > 0:
        for d in lbls:
            d["y"] -= over
    for d in lbls:
        if abs(d["y"] - d["y0"]) > 1.5:
            p.append(f'<line x1="{d["x0"]:.1f}" y1="{d["y0"]:.1f}" x2="{w-mr+3}" '
                     f'y2="{d["y"]-3:.1f}" stroke="{d["col"]}" stroke-width="0.7" '
                     f'opacity="0.45"/>')
        p.append(f'<text x="{w-mr+6}" y="{d["y"]:.1f}" font-size="9.5" fill="{d["col"]}" '
                 f'font-weight="{600 if d["bold"] else 400}">{_esc(d["txt"])}</text>')
    # X 轴标签(真实观测日, 绝不外推)
    for i in range(0, len(alld), max(1, len(alld) // 6)):
        ds = alld[i]
        p.append(f'<text x="{X(ds):.1f}" y="{h-mb+16}" font-size="9" fill="#8a8578" '
                 f'text-anchor="middle">{ds[:7]}</text>')
    p.append(f'<line x1="{ml}" y1="{h-mb:.1f}" x2="{w-mr}" y2="{h-mb:.1f}" stroke="#d8d4cb"/>')
    p.append('</svg>')
    return "".join(p)


def _corp_outstanding_svg(rec, w=452, h=200):
    """季度真实未偿额柱状/面积图。"""
    s = rec.get("series") or []
    if len(s) < 2:
        return ""
    ml, mr, mt, mb = 58, 14, 16, 26
    vals = [v for _, v in s]
    vmin, vmax = min(vals) * 0.97, max(vals) * 1.03
    iw, ih = w - ml - mr, h - mt - mb
    n = len(s)

    def X(i):
        return ml + (i / max(n - 1, 1)) * iw

    def Y(v):
        return mt + ih - ((v - vmin) / max(vmax - vmin, 1e-9)) * ih

    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" '
         f'xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui">']
    area = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(s))
    p.append(f'<polygon points="{ml},{mt+ih} {area} {ml+iw:.1f},{mt+ih}" '
             f'fill="#6b8fb5" opacity="0.13"/>')
    p.append(f'<polyline points="{area}" fill="none" stroke="#6b8fb5" stroke-width="1.8"/>')
    for gv in (vmin, (vmin + vmax) / 2, vmax):
        gy = Y(gv)
        p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" stroke="#ece9e2"/>')
        p.append(f'<text x="{ml-6}" y="{gy+3:.1f}" font-size="8.5" fill="#a8a49b" '
                 f'text-anchor="end">{gv/1000:.1f}T</text>')
    for i, (d, v) in enumerate(s):
        p.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4.5" fill="transparent" '
                 f'data-tip="{_esc(rec["label"])} {d}: ${v:,.1f}B"/>')
    ld, lv = s[-1]
    p.append(f'<circle cx="{X(n-1):.1f}" cy="{Y(lv):.1f}" r="3" fill="#6b8fb5"/>')
    for i in (0, n // 2, n - 1):
        p.append(f'<text x="{X(i):.1f}" y="{h-mb+15}" font-size="8.5" fill="#8a8578" '
                 f'text-anchor="middle">{s[i][0][:7]}</text>')
    p.append(f'<line x1="{ml}" y1="{h-mb:.1f}" x2="{w-mr}" y2="{h-mb:.1f}" stroke="#d8d4cb"/>')
    p.append('</svg>')
    return "".join(p)


def _corp_credit_html(cc):
    """美国分评级公司债: 收益率/利差(日频) + 真实未偿总额(季频)。"""
    if not cc or cc.get("status") != "ok":
        return '<p class="empty">美国公司债数据未就绪。</p>'
    rs = [r for r in cc.get("ratings") or [] if r.get("status") == "ok"]
    if not rs:
        return '<p class="empty">美国公司债数据未就绪。</p>'
    asof = cc.get("as_of") or ""
    badge = _stale_badge(asof, "daily")

    # 评级表格
    rows = []
    for r in rs:
        y = r.get("yield_latest")
        o = r.get("oas_latest")
        c1 = r.get("chg_1m_bp")
        oc1 = r.get("oas_chg_1m_bp")

        def _d(v, suf="bp"):
            if v is None:
                return '<span class="cc-na">n/a</span>'
            col = "#c0757d" if v > 0 else ("#7fa085" if v < 0 else "#8a8578")
            arw = "▲" if v > 0 else ("▼" if v < 0 else "→")
            return f'<span style="color:{col}">{arw}{abs(v):.0f}{suf}</span>'
        tier = "投资级" if r["ig"] else "高收益"
        tcol = "#6b8fb5" if r["ig"] else "#c08a7d"
        rows.append(
            f'<tr><td><b>{_esc(r["label"])}</b> '
            f'<span class="cc-tier" style="color:{tcol}">{tier}</span></td>'
            f'<td class="cc-num">{y:.2f}%</td><td class="cc-num">{_d(c1)}</td>'
            f'<td class="cc-num">{o:.2f}%</td><td class="cc-num">{_d(oc1)}</td></tr>'
            if y is not None and o is not None else
            f'<tr><td><b>{_esc(r["label"])}</b></td>'
            f'<td class="cc-num">{f"{y:.2f}%" if y is not None else "n/a"}</td>'
            f'<td class="cc-num">{_d(c1)}</td>'
            f'<td class="cc-num">{f"{o:.2f}%" if o is not None else "n/a"}</td>'
            f'<td class="cc-num">{_d(oc1)}</td></tr>'
        )
    table = (
        '<table class="cc-tbl"><thead><tr><th>评级</th><th>有效收益率</th>'
        '<th>近1月Δ</th><th>期权调整利差 OAS</th><th>OAS近1月Δ</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )

    # 信用分层观察: IG 与 CCC 的 OAS 背离
    ig_oas = [r["oas_latest"] for r in rs if r["ig"] and r.get("oas_latest") is not None]
    ccc = next((r for r in rs if r["label"].startswith("CCC")), None)
    divergence = ""
    if ig_oas and ccc and ccc.get("oas_chg_1m_bp") is not None:
        ig_chg = [r.get("oas_chg_1m_bp") for r in rs
                  if r["ig"] and r.get("oas_chg_1m_bp") is not None]
        if ig_chg:
            ig_avg = sum(ig_chg) / len(ig_chg)
            gap = ccc["oas_chg_1m_bp"] - ig_avg
            if gap > 25:
                divergence = (
                    f'<div class="cc-alert">⚠️ <b>信用分层信号</b>：近 1 个月 '
                    f'<b>CCC 及以下 OAS 扩大 {ccc["oas_chg_1m_bp"]:.0f}bp</b>，'
                    f'而投资级平均仅 {ig_avg:+.0f}bp（差 {gap:.0f}bp）。'
                    f'风险偏好正在<b>最低评级层单点撕裂</b>——这通常是信用周期转折的早期特征，'
                    f'而非全面risk-off。</div>')

    # 历史分位: 当前 OAS 在自身可得区间中的位置(判断"贵/便宜", 与1月变化互补)
    def _pctile(r):
        ser = r.get("oas_series") or []
        s = [v for _, v in ser]
        if len(s) < 30 or r.get("oas_latest") is None:
            return None
        cur = r["oas_latest"]
        # (分位, 样本数, 区间起始"日期", 最小值, 最大值)
        return (100.0 * sum(1 for v in s if v <= cur) / len(s),
                len(s), ser[0][0], min(s), max(s))

    pct_bits, ccc_pct, ig_pcts = [], None, []
    for r in rs:
        pr = _pctile(r)
        if not pr:
            continue
        p = pr[0]
        pct_bits.append((r["label"], p, r["oas_latest"], pr[3], pr[4]))
        if r["label"].startswith("CCC"):
            ccc_pct = p
        elif r["ig"]:
            ig_pcts.append(p)
    pct_html = ""
    if pct_bits:
        span = next((_pctile(r) for r in rs if _pctile(r)), None)
        yrs_txt = ""
        if span:
            yrs_txt = f'（区间起自 {span[2]}，{span[1]} 个交易日）'
        items = "".join(
            f'<span class="cc-pchip"><b>{_esc(lb)}</b> {p:.0f}%'
            f'<i data-tip="{_esc(lb)} 当前 OAS {cur:.2f}%，'
            f'处于可得区间 [{lo:.2f}%, {hi:.2f}%] 的第 {p:.0f} 百分位">ⓘ</i></span>'
            for lb, p, cur, lo, hi in pct_bits)
        note = ""
        if ccc_pct is not None and ig_pcts:
            iga = sum(ig_pcts) / len(ig_pcts)
            if ccc_pct - iga > 30:
                note = (f'<br>→ <b>CCC 处第 {ccc_pct:.0f} 百分位（接近区间高位）'
                        f'，投资级平均仅第 {iga:.0f} 百分位</b>：'
                        f'市场并未整体定价信用紧缩，压力集中在最弱发行人。')
            elif iga - ccc_pct > 30:
                note = (f'<br>→ CCC 第 {ccc_pct:.0f} 百分位低于投资级平均第 {iga:.0f} 百分位，'
                        f'高收益相对投资级偏紧，属risk-on特征。')
        pct_html = (f'<div class="cc-pct"><b>OAS 历史分位</b>{yrs_txt}：{items}'
                    f'<span class="cc-pnote">分位越高＝利差越接近该评级自身区间的高位'
                    f'（越贵/越紧张）。{note}</span></div>')

    # 未偿总额
    outs = [o for o in cc.get("outstanding") or [] if o.get("status") == "ok"]
    ocards = []
    for o in outs:
        yoy = o.get("chg_yoy_pct")
        ycol = "#c0757d" if (yoy or 0) > 0 else "#7fa085"
        yarw = "▲" if (yoy or 0) > 0 else "▼"
        ytxt = (f'<span style="color:{ycol}">{yarw} {abs(yoy):.1f}% YoY</span>'
                if yoy is not None else '<span class="cc-na">YoY n/a</span>')
        ocards.append(
            f'<div class="cc-ocard"><div class="cc-olabel">{_esc(o["label"])}</div>'
            f'<div class="cc-oval">${o["latest"]/1000:.2f}T <span class="cc-oyoy">{ytxt}</span></div>'
            f'<div class="cc-odate">as of {_esc(o.get("latest_date", ""))}'
            f'{_stale_badge(o.get("latest_date"), "quarterly")}</div>'
            f'{_corp_outstanding_svg(o)}</div>')
    ohtml = (f'<div class="cc-osec"><div class="dg-sub">真实未偿总额（Fed Z.1 · 季度）</div>'
             f'<div class="cc-ogrid">{"".join(ocards)}</div></div>') if ocards else ""

    return (
        f'<div class="cc-wrap">'
        f'<div class="dg-head">🏦 美国公司债 · 分评级 收益率 / 利差 / 总额'
        f'<span class="dg-asof">as of {_esc(asof)}{badge}</span></div>'
        f'{table}{divergence}{pct_html}'
        f'<div class="dg-sub">期权调整利差 OAS 走势（近 3 年 · 纯信用风险溢价）</div>'
        f'{_corp_credit_svg(rs, "oas_series", unit=" %")}'
        f'<div class="dg-sub">有效收益率走势（近 3 年 · 含无风险利率）</div>'
        f'{_corp_credit_svg(rs, "yield_series", unit=" %")}'
        f'{ohtml}'
        f'<div class="ci-how"><b>如何看：</b>'
        f'<b>有效收益率</b>=投资者实际拿到的总收益率，它同时包含无风险利率与信用风险；'
        f'国债利率上行时它也会涨，所以<b>不能单看它判断信用风险</b>。'
        f'<b>OAS（期权调整利差）</b>剔除了国债基准，是<b>纯粹的信用风险溢价</b>——'
        f'看信用状况是否恶化应以 OAS 为准。'
        f'OAS 走阔=市场要求更高风险补偿（信用收紧）；收窄=风险偏好回升。'
        f'评级越低对经济下行越敏感，<b>CCC 通常最先动</b>，是信用周期的先行哨兵。'
        f'<br><b>⚠️ 口径诚实说明：</b>免费公开源<b>不存在「每日 · 分评级 · 未偿总额」</b>'
        f'（该数据属 ICE / Bloomberg 商业授权）。'
        f'FRED 上带 TRIV 的序列是<b>总回报指数</b>（随价格涨跌波动），<b>不是</b>债券余额，'
        f'本页<b>未</b>将其当作总额使用。'
        f'因此总量改用 <b>Fed Z.1 官方季度真实未偿额</b>（季频、滞后约 1 季），'
        f'日频部分只提供收益率与利差。'
        f'数据源：{_linkify_sources(cc.get("source", ""))}。</div>'
        f'</div>'
    )


def _comex_inventory_html(ci):
    """COMEX & 上海贵金属库存 + GLD/SLV ETF 资金流。ci: fetch_comex_inventory()。
    3 库存双轴图(复用 _stress_panel_svg) + 2 ETF 周净流量柱状。绝不编: 缺失显示占位。"""
    if not ci or ci.get("status") != "ok" or not ci.get("panels"):
        return ('<p class="empty">COMEX/上海库存 + ETF 资金流数据同步中'
                '（来源 comex-inventory-charts 公开数据，读到即填真值）。</p>')
    panels = ci.get("panels", {})
    flows = ci.get("flows", {})
    summ = ci.get("summary", {})
    as_of = ci.get("as_of", "")

    # 库存双轴图(gold/silver/platinum)
    blocks = []
    inv_notes = {
        "gold": "COMEX(左轴)是西方交割库存，上海 SHFE(右轴)是东方实物库存。两地库存背离/共振反映东西方黄金实物流向——COMEX 持续流出而上海累积，往往指向实物东移、逼仓压力。",
        "silver": "白银 COMEX(左轴) vs 上海 SHFE+SGE(右轴)。白银工业+货币双属性，东西方库存此消彼长是实物紧张的领先信号；COMEX 注册库存骤降 + 上海累积 = 潜在挤兑。",
        "platinum": "铂金 COMEX 库存(上海无公开库存数据)。铂金库存薄、流动性差，库存快速下降易放大价格波动。",
    }
    for key in ("gold", "silver", "platinum"):
        p = panels.get(key)
        if not p or not any(s.get("points") for s in p.get("series", [])):
            continue
        if p.get("single_axis"):
            axinfo = f'<span class="sp-axk">{_esc(p.get("unit_left",""))}</span>'
        else:
            axinfo = (f'<span class="sp-axk">COMEX ◂ {_esc(p.get("unit_left",""))}</span>'
                      f'<span class="sp-axk">{_esc(p.get("unit_right",""))} ▸ 上海</span>')
        blocks.append(
            f'<div class="sp-panel">'
            f'<div class="sp-head"><span class="sp-title">{_esc(p["title"])}</span>'
            f'<span class="sp-sub">{_esc(p.get("subtitle",""))}</span></div>'
            f'<div class="sp-axrow">{axinfo}</div>'
            f'{_stress_panel_svg(p)}'
            f'<div class="sp-note">{inv_notes.get(key,"")}</div>'
            f'<div class="sp-src">数据源：{_linkify_sources(p.get("source",""))}</div>'
            f'</div>'
        )

    # ETF 资金流(GLD/SLV 周净流量)
    flow_blocks = []
    for key, meta in (("gld", ("GLD 黄金ETF 周净流量", "gld")), ("slv", ("SLV 白银ETF 周净流量", "slv"))):
        f = flows.get(key)
        if not f:
            continue
        s = summ.get(key, {})
        net = s.get("net"); last = s.get("last"); wd = s.get("w_d") or s.get("d")
        stat = ""
        if isinstance(net, (int, float)):
            nc = "#2e9e5b" if net >= 0 else "#d64545"
            stat = (f'近1年净流量 <b style="color:{nc}">{net:+.0f} t</b>'
                    + (f' · 最新周 <b>{last:+.2f} t</b>（{_esc(str(wd))}）' if isinstance(last, (int, float)) else ""))
        flow_blocks.append(
            f'<div class="sp-panel">'
            f'<div class="sp-head"><span class="sp-title">{_esc(f["name"])}</span></div>'
            f'{_flow_bars_svg(f["bars"])}'
            f'<div class="oil-meta">{stat}</div>'
            f'</div>'
        )

    intro = (
        f'<div class="sp-intro">COMEX 与上海(SHFE/SGE)贵金属<b>实物库存对照</b> + GLD/SLV <b>ETF 资金流</b>。'
        f'东西方库存背离揭示实物流向与逼仓压力；ETF 资金流反映纸面配置意愿。全部公开数据，每日自动更新。'
        f'<span class="sp-asof">as of {_esc(str(as_of))} · COMEX 日频 · 上海周频 · 来源 comex-inventory-charts</span></div>'
    )
    flow_intro = ('<div class="bt-mtitle">GLD / SLV ETF 周净流量'
                  '<span class="bt-mtsub">🟢 净流入 · 🔴 净流出（单位：吨）</span></div>')
    return (f'<div class="sp-wrap">{intro}{"".join(blocks)}'
            f'{flow_intro}{"".join(flow_blocks)}</div>')


def _cb_balance_html(cb):
    """底部四大央行资产负债表板块(US/JP/CN/ECB), 2x2 布局。统一当天汇率折 $B 横向可比。"""
    if not cb:
        return '<p class="empty">央行资产负债表数据未就绪。</p>'
    fx = cb.get("_fx")
    order = ["US", "JP", "CN", "ECB"]
    cards = "".join(_cb_one_view(cb.get(cc, {}), fx=fx) for cc in order if cc in cb)
    return cards or '<p class="empty">央行资产负债表数据未就绪。</p>'


def _ms_num(v):
    """货币供应量数字格式化(千分位, 保留原量级)。"""
    if v is None:
        return "—"
    try:
        return f"{v:,.1f}" if v < 1000 else f"{v:,.0f}"
    except Exception:
        return _esc(str(v))


def _money_supply_html(ms):
    """三国货币供应量 M0/M1/M2 模块。ms: fetch_money_supply() 结果(已折 $B)。
    每国一卡: M0(基础货币)⊂M1⊂M2 递进条(跨国同尺度,可横向比长度) + $B值+本币原值括注 + 口径/日期/源;
    顶部一段层级说明(回答"基础货币≠流通量" + 折美元横向对比说明)。"""
    if not ms:
        return '<p class="empty">货币供应量数据未就绪。</p>'
    fx = ms.get("_fx") or {}
    fx_note = ""
    if fx.get("USDJPY") or fx.get("USDCNY"):
        parts = []
        if fx.get("USDJPY"):
            parts.append(f"USD/JPY {fx['USDJPY']:g}")
        if fx.get("USDCNY"):
            parts.append(f"USD/CNY {fx['USDCNY']:g}")
        fx_note = "，按 " + " · ".join(parts) + " 折算(FRED)"
    # 层级说明(交易员视角一段话)
    intro = (
        '<div class="ms-intro">'
        '<div class="ms-intro-l"><b>怎么读：</b>上面的央行资负表是"央行造了多少<u>底钱</u>"(基础货币/储备货币)；'
        '这里的 M0/M1/M2 才是"社会上<u>实际流通</u>多少钱"。两者不是一回事。</div>'
        '<div class="ms-intro-l"><b>包含关系(层层扩大)：</b>'
        'M0(现金) ⊂ M1(现金+活期) ⊂ M2(M1+定期/储蓄)。层级越高口径越广，<b>不能相加</b>。</div>'
        '<div class="ms-intro-l"><b>为什么 M2 远大于基础货币：</b>'
        '商业银行放贷—存款—再放贷把底钱放大数倍(货币乘数)。M2 ≈ 基础货币 × 乘数，是"放水/收水"的真实力度。</div>'
        '<div class="ms-intro-l ms-cav"><b>口径 & 单位：</b>'
        '中国官方直接公布 M0/M1/M2；美国、日本官方无"M0"，用<b>基础货币(Monetary Base)</b>代理(日本另有 M3=M2+邮储/农协)。'
        f'三国已<b>统一折成 $B(十亿美元)</b>横向可比{_esc(fx_note)}，括号内为本币原值。</div>'
        '</div>'
    )
    order = ["US", "JP", "CN"]
    # 跨国同尺度: 取三国所有 M0/M1/M2/M3 的全局最大值作为满宽基准, 这样条长可横向比
    allvals = []
    for cc in order:
        d = ms.get(cc) or {}
        if d.get("status") == "未找到":
            continue
        allvals += [x for x in (d.get("m0"), d.get("m1"), d.get("m2"), d.get("m3")) if x is not None]
    base = max(allvals) if allvals else 1
    cards = ""
    for cc in order:
        d = ms.get(cc)
        if not d:
            continue
        if d.get("status") == "未找到" or (d.get("m2") is None and d.get("m1") is None):
            cards += (f'<div class="ms-card"><div class="ms-head">{_esc(d.get("flag",""))} '
                      f'{_esc(d.get("name",cc))}</div><p class="empty">数据未找到</p></div>')
            continue
        unit = d.get("unit", "")
        orig_unit = d.get("orig_unit")
        m0, m1, m2 = d.get("m0"), d.get("m1"), d.get("m2")
        m3 = d.get("m3")

        def bar(label, val, cls, orig=None):
            if val is None:
                return (f'<div class="ms-row"><span class="ms-lbl">{_esc(label)}</span>'
                        f'<span class="ms-bar-wrap"><span class="ms-bar {cls}" style="width:0"></span></span>'
                        f'<span class="ms-v">—</span></div>')
            w = max(2, round(val / base * 100))
            orig_html = f'<span class="ms-orig">({_ms_num(orig)} {_esc(orig_unit)})</span>' if (orig is not None and orig_unit) else ""
            return (f'<div class="ms-row"><span class="ms-lbl">{_esc(label)}</span>'
                    f'<span class="ms-bar-wrap"><span class="ms-bar {cls}" style="width:{w}%"></span></span>'
                    f'<span class="ms-v">{_ms_num(val)}{orig_html}</span></div>')
        m0_lbl = d.get("m0_label", "M0")
        rows = (bar(m0_lbl, m0, "ms-b0", d.get("orig_m0"))
                + bar("M1", m1, "ms-b1", d.get("orig_m1"))
                + bar("M2", m2, "ms-b2", d.get("orig_m2")))
        if m3 is not None:
            rows += bar("M3", m3, "ms-b3", d.get("orig_m3"))
        src = _linkify_sources(str(d.get("source", "")))
        cards += (
            f'<div class="ms-card">'
            f'<div class="ms-head">{_esc(d.get("flag",""))} {_esc(d.get("name",cc))}'
            f'<span class="ms-meta">{_esc(str(d.get("as_of","")))} · 单位 {_esc(unit)}</span></div>'
            f'<div class="ms-body">{rows}</div>'
            f'<div class="ms-src">源：{src}</div>'
            f'</div>'
        )
    grid = f'<div class="ms-grid">{cards}</div>' if cards else '<p class="empty">货币供应量数据未就绪。</p>'
    return intro + grid


def _m2_line_svg(points, w=360, h=150):
    """M2 月度历史折线图(单国)。points: [{date:'YYYY-MM', value:$B},...] 升序。
    Y轴刻度($B, 大数用k简写)/年份标签/最新点标注。上升=sage绿(放水),整体一律上升多→用统一强调色 dust-blue。"""
    pts_in = [p for p in (points or []) if p.get("value") is not None]
    if len(pts_in) < 2:
        return '<div class="m2-chart-na">历史数据不足</div>'
    dates = [p["date"] for p in pts_in]
    vals = [p["value"] for p in pts_in]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 0.01
    ml, mr, mt, mb = 46, 10, 14, 26
    pw, ph = w - ml - mr, h - mt - mb
    n = len(vals)
    def X(i): return ml + i * pw / (n - 1)
    def Y(v): return mt + (hi - v) / rng * ph
    pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)]
    _hits = "".join(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="6" data-tip="{_esc(dates[i][:7])}||{v:,.0f} $B"/>' for i, v in enumerate(vals))
    rising = vals[-1] >= vals[0]
    color = "#9aab97" if rising else "#c08a7d"
    fill = "rgba(154,171,151,0.10)" if rising else "rgba(192,138,125,0.10)"
    area = f"{X(0):.1f},{mt+ph:.1f} " + " ".join(pts) + f" {X(n-1):.1f},{mt+ph:.1f}"

    def _fmt(v):
        return f"{v/1000:.1f}k" if v >= 10000 else f"{v:,.0f}"
    yl = []
    for k in range(4):
        gv = lo + rng * k / 3
        gy = Y(gv)
        yl.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{w-mr}" y2="{gy:.1f}" class="cc-grid"/>')
        yl.append(f'<text x="{ml-5}" y="{gy+3:.1f}" class="cc-ylab">{_fmt(gv)}</text>')
    # X 轴年份标签(首/末 + 每约1/3, 只显示年份)
    xl = []
    idxs = sorted(set([0, n // 3, 2 * n // 3, n - 1]))
    for i in idxs:
        yr = dates[i][:4]
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        xl.append(f'<text x="{X(i):.1f}" y="{h-8}" class="cc-xlab" text-anchor="{anchor}">{yr}</text>')
    lx, ly = X(n - 1), Y(vals[-1])
    return (
        f'<svg viewBox="0 0 {w} {h}" class="m2-chart" preserveAspectRatio="xMidYMid meet">'
        + "".join(yl)
        + f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
        + f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{color}"/>'
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="7" fill="{color}" opacity="0.18"/>'
        + _hits
        + "".join(xl)
        + '</svg>'
    )


def _m2_history_html(m2h):
    """三国 M2 十年历史折线图卡片。m2h: fetch_m2_history() 结果。
    每国一卡: 折线图($B, 当月汇率折算) + 十年涨幅 + 首末值 + 源。放在 M0/M1/M2 框图下方。"""
    if not m2h:
        return '<p class="empty">M2 历史数据未就绪。</p>'
    order = ["US", "JP", "CN"]
    fx = m2h.get("_fx") or {}
    fx_txt = ""
    if fx.get("USDJPY") or fx.get("USDCNY"):
        parts = []
        if fx.get("USDJPY"):
            parts.append(f"USD/JPY {fx['USDJPY']:g}")
        if fx.get("USDCNY"):
            parts.append(f"USD/CNY {fx['USDCNY']:g}")
        fx_txt = "（当天汇率 " + " · ".join(parts) + "）"
    intro = (
        '<div class="ms-intro">'
        '<div class="ms-intro-l"><b>怎么读：</b>三国 M2 广义货币<b>十年月度走势</b>，'
        f'已按<u>当天最新汇率</u>{_esc(fx_txt)}把整条历史序列统一折成 $B(十亿美元)横向可比——'
        '<b>剥离了汇率波动</b>，曲线纯粹反映各国本币 M2 的真实增长(放水力度)。</div>'
        '<div class="ms-intro-l ms-cav"><b>看点：</b>用同一汇率折算后，日本 M2 本币十年真实增长清晰可见(不再被日元贬值掩盖)；'
        '中国 M2 绝对规模已是全球最大且增速最猛。斜率越陡=印钞越猛。</div>'
        '</div>'
    )
    cards = ""
    for cc in order:
        b = m2h.get(cc) or {}
        pts = b.get("points", [])
        if not pts:
            cards += (f'<div class="m2-card"><div class="m2-head">{_esc(b.get("flag",""))} '
                      f'{_esc(b.get("name",cc))} M2</div><p class="empty">历史数据未找到</p></div>')
            continue
        v0, v1 = pts[0]["value"], pts[-1]["value"]
        chg_pct = (v1 - v0) / v0 * 100 if v0 else 0
        span_yr = f"{pts[0]['date']} → {pts[-1]['date']}"
        chg_cls = "g" if chg_pct >= 0 else "r"
        cards += (
            f'<div class="m2-card">'
            f'<div class="m2-head">{_esc(b.get("flag",""))} {_esc(b.get("name",cc))} · M2'
            f'<span class="m2-meta">$B · 当天汇率折算</span></div>'
            f'<div class="m2-chart-box">{_m2_line_svg(pts)}</div>'
            f'<div class="m2-stats">'
            f'<div class="m2-stat"><span>最新</span><b>{_ms_num(v1)}</b></div>'
            f'<div class="m2-stat"><span>{_esc(str(len(pts)))}月涨幅</span><b class="cust-{chg_cls}">{chg_pct:+.0f}%</b></div>'
            f'<div class="m2-stat"><span>区间</span><b>{_ms_num(v0)}→{_ms_num(v1)}</b></div>'
            f'</div>'
            f'<div class="m2-span">{_esc(span_yr)}</div>'
            f'<div class="ms-src">源：{_linkify_sources(str(b.get("source","")))}</div>'
            f'</div>'
        )
    grid = f'<div class="m2-grid">{cards}</div>' if cards else '<p class="empty">M2 历史数据未就绪。</p>'
    return intro + grid


def _action_cls(action):
    """持仓变动 → 色标 class。"""
    if "新建" in action:
        return "h-new"
    if "加仓" in action:
        return "h-add"
    if "减仓" in action:
        return "h-cut"
    if "清仓" in action:
        return "h-exit"
    return "h-flat"


def _holdings_one(r):
    """单个机构持仓卡片: 头部(基金/KOL/报告期/总市值) + 两句话介绍 + TOP持仓+变动。"""
    try:
        import institution_meta as im
        meta = im.meta_for(r.get("fund", ""))
    except Exception:
        meta = {}
    if r.get("status") != "ok":
        return (f'<div class="h-card"><div class="h-head">{_esc(r.get("fund","?"))} '
                f'<span class="h-kol">{_esc(r.get("kol",""))}</span></div>'
                f'<p class="empty">{_esc(r.get("status","数据未找到"))}</p></div>')
    tv = r.get("total_value", 0) / 1e9
    lines = ""
    for h in r.get("top_holdings", [])[:10]:
        pct = f' <span class="h-pct">{h["pct"]:+.0f}%</span>' if h.get("pct") is not None else ""
        val = f'${h["value"]/1e6:,.0f}M' if h.get("value") else "—"
        # issuer 展示: 有 ticker 就加后缀 (TICKER)
        tk = h.get("ticker", "")
        iss_disp = _esc(h["issuer"])
        if tk and not tk.endswith("?") and "/" not in tk and "多" not in tk:
            iss_disp = f'{_esc(h["issuer"])} <span class="h-tk">{_esc(tk)}</span>'
        lines += (f'<div class="h-line"><span class="h-act {_action_cls(h["action"])}">{_esc(h["action"])}</span>'
                  f'<span class="h-iss">{iss_disp}</span>'
                  f'<span class="h-val">{val}{pct}</span></div>')
    # 两句话介绍
    intro = ""
    if meta.get("desc_type") or meta.get("desc_status"):
        intro = (f'<div class="h-intro">'
                 f'<div class="h-intro-l"><b>类型</b> {_esc(meta.get("desc_type",""))}</div>'
                 f'<div class="h-intro-l"><b>地位</b> {_esc(meta.get("desc_status",""))}</div></div>')
    return (
        f'<div class="h-card">'
        f'<div class="h-head">{_esc(r.get("fund",""))}<span class="h-kol">{_esc(r.get("kol",""))}</span>'
        f'<span class="h-meta">13F {_esc(r.get("report_date",""))} · ${tv:,.1f}B · {r.get("n_positions",0)}持仓 · vs {_esc(r.get("prev_report_date","-"))}</span></div>'
        f'{intro}'
        f'<div class="h-body">{lines}</div></div>'
    )


def _holdings_political(figures):
    """政要持仓披露板块(国会交易披露 STOCK Act, 非13F)。真数据来自 politician_disclosure.json。"""
    if not figures:
        return ""
    cards = ""
    for f in figures:
        trades = f.get("trades", [])
        lines = ""
        for t in trades[:12]:
            dir_cn = t.get("dir_cn", t.get("direction", ""))
            act_cls = "h-buy" if "买" in dir_cn else ("h-sell" if "卖" in dir_cn else "")
            # ticker 优先; 缺失时回退资产名(川普 278-T 只有资产描述, 无 ticker)
            tk = t.get("ticker") or (t.get("asset") or "—")
            if len(tk) > 28:
                tk = tk[:27] + "…"
            amt = t.get("amount_range", "")
            txn = t.get("txn_date", "")
            lines += (f'<div class="h-line"><span class="h-act {act_cls}">{_esc(dir_cn)}</span>'
                      f'<span class="h-iss">{_esc(tk)}</span>'
                      f'<span class="h-val">{_esc(txn)} · {_esc(amt)}</span></div>')
        status = f.get("status", "")
        if lines:
            body = lines
        elif status == "no_free_source":
            body = f'<p class="empty">{_esc(f.get("note","无免费逐笔交易结构化源"))}</p>'
        elif status in ("no_filings", "no_reports", "no_trades"):
            body = '<p class="empty">近期无披露交易记录</p>'
        elif status == "fetch_error":
            body = '<p class="empty">数据源暂时不可达(下次 cron 重试)</p>'
        else:
            body = '<p class="empty">暂无最新交易明细</p>'
        nf = f.get("n_filings")
        src = f.get("source", "")
        if nf:
            meta_line = f'{nf} 笔披露交易' if src.startswith("OGE") else f'披露 {nf} 份'
        else:
            meta_line = src or '政要交易披露'
        note = f.get("note", "")
        note_html = f'<div class="h-pol-note">{_esc(note)}</div>' if note and lines else ""
        cards += (
            f'<div class="h-card">'
            f'<div class="h-head">{_esc(f.get("name",""))}'
            f'<span class="h-kol">{_esc(f.get("title",""))}</span>'
            f'<span class="h-meta">{_esc(meta_line)}</span></div>'
            f'<div class="h-body">{body}{note_html}</div></div>'
        )
    return cards


def _holdings_html(hd):
    """机构持仓板块 — 按模块分组展示(每组带色标题+线框), 机构名下两句话介绍。"""
    insts = hd.get("institutions", []) if hd else []
    try:
        import institution_meta as im
    except Exception:
        im = None
    if not insts and not im:
        return '<p class="empty">机构持仓数据未就绪(季度 13F 披露后更新)。</p>'
    # 按模块分组
    groups = {}
    for r in insts:
        if r.get("source") == "PFD" or str(r.get("kol", "")).lower().startswith("trump"):
            continue  # 政要单列
        meta = im.meta_for(r.get("fund", "")) if im else {}
        mod = meta.get("module", r.get("sector", "其他"))
        groups.setdefault(mod, []).append(r)
    # 模块顺序 + 配色
    mod_order = ["价值传奇", "宏观对冲", "科技成长", "价值宏观", "量化多策略", "贵金属/另类", "其他"]
    html = ""
    for mod in mod_order:
        if mod not in groups:
            continue
        color = im.module_color(mod) if im else "#8a8a80"
        en = im.MODULES.get(mod, {}).get("en", "") if im else ""
        cards = "".join(_holdings_one(r) for r in groups[mod])
        html += (
            f'<div class="h-module" style="border-color:{color}">'
            f'<div class="h-module-title" style="background:{color}">'
            f'<span class="h-mod-dot"></span>{mod}<span class="h-mod-en">{en}</span>'
            f'<span class="h-mod-n">{len(groups[mod])} 家</span></div>'
            f'<div class="h-grid-inner">{cards}</div></div>'
        )
    # 政要板块 — 读 politician_disclosure.json 真数据(国会 PTR)
    pol_figs = []
    try:
        import politician_disclosure as pol
        pd = pol.load_disclosure()
        pol_figs = pd.get("politicians", [])
    except Exception:
        pol_figs = []
    if pol_figs:
        pcolor = im.MODULES["政要披露"]["color"] if im else "#a88a6a"
        pol_cards = _holdings_political(pol_figs)
        html += (
            f'<div class="h-module" style="border-color:{pcolor}">'
            f'<div class="h-module-title" style="background:{pcolor}">'
            f'<span class="h-mod-dot"></span>政要持仓披露<span class="h-mod-en">Political · STOCK Act PTR</span>'
            f'<span class="h-mod-n">{len(pol_figs)} 位</span></div>'
            f'<div class="h-grid-inner">{pol_cards}</div></div>'
        )
    meta_note = ('<div class="h-note">机构数据源：SEC EDGAR 官方 13F（季度，季末后约45天更新，dashboard 显最新期、全部历史存 Notion）。'
                 '政要数据源：美国众议院官方财务披露 STOCK Act PTR（disclosures-clerk.house.gov，逐笔交易真数据）；'
                 '川普/参议员暂无免费逐笔源(诚实标注)。'
                 '变动＝最新期 vs 上一期持股数：🆕新建 ▲加仓 ▼减仓 ❌清仓 →持平。</div>')
    return (html or '<p class="empty">机构持仓数据未就绪。</p>') + meta_note


def _rule_conclusions(results, checks, hit, cot):
    """规则兜底的短中长综合结论(agent 未生成时用)。返回 {short,mid,long}。"""
    def gv(k):
        return results.get(k, {}).get("value")

    # 短期(1-3月): 看 VIX/Fear&Greed/put_call
    vix, fg = gv("vix"), gv("fear_greed")
    if vix is not None and vix > 25:
        short = "VIX 已破 25 恐慌区，短期避险；可考虑买入保险(put/VIX call)对冲。"
    elif fg is not None and fg > 75:
        short = f"Fear&Greed {fg} 处极度贪婪区，短期过热，建议减仓 10-15% 锁定利润、暂缓追高。"
    elif fg is not None and fg > 60:
        short = f"Fear&Greed {fg} 偏贪婪但未极端，短期持有为主，不追高，留意情绪见顶。"
    else:
        short = "短期情绪与波动率处正常区间，无需减仓或买保险，维持现有仓位。"

    # 中期(3-12月): 看 HY spread/margin/BofA/insider
    hy, bb = gv("hy_oas"), gv("bofa_bull_bear")
    mid_parts = []
    if hy is not None and hy > 4.5:
        mid_parts.append("HY 利差破 4.5%，信用市场转向，减配高收益债/高杠杆板块")
    if bb is not None and bb > 8:
        mid_parts.append(f"BofA 牛熊 {bb} 极度贪婪(反向看空)，中期趋势临近顶部，逐步获利了结成长股")
    if not mid_parts:
        mid = "中期趋势未见转折信号，信用利差平稳，维持配置；关注杠杆与情绪拐点。"
    else:
        mid = "；".join(mid_parts) + "。"

    # 长期(1-3年+): 看 Buffett/CAPE/收益率曲线/LEI
    buf, cape, yc, lei = gv("buffett"), gv("cape"), gv("yield_curve"), gv("lei")
    long_parts = []
    if buf is not None and buf > 180:
        long_parts.append(f"巴菲特指标 {buf}% 处极端泡沫区")
    if cape is not None and cape > 35:
        long_parts.append(f"CAPE {cape} 接近历史泡沫峰值")
    if yc is not None and yc < 0:
        long_parts.append(f"收益率曲线 10Y-2Y {yc} 倒挂(历史衰退领先信号)")
    if lei is not None and lei < -4:
        long_parts.append(f"LEI 领先指标 {lei}% 深度收缩(经济下行压力)")
    if long_parts:
        long = "、".join(long_parts) + "——长期估值结构性偏高，组合应逐步再平衡：降低美股权重、增配现金/防御/非美资产，为均值回归做准备。"
    else:
        long = "长期估值虽高但未达极端，维持核心配置，定期再平衡。"

    return {"short": short, "mid": mid, "long": long}


def _focus_text(checks, results, cot):
    # 最接近触发 / 变化最剧烈
    near = [(cond, desc) for cond, thr, desc, st in checks if st in ("✅", "⚠️")]
    parts = []
    for cond, desc in near:
        parts.append(f"<b>{cond}</b>：{desc}")
    # COT 突增
    for metal in ("gold", "silver"):
        r = cot.get(metal)
        if r and r.get("comm_surge"):
            parts.append(f"<b>{metal} COT commercial 突增</b>：周环比净变动 {r.get('comm_net_wow'):,}，聪明钱异动值得关注")
    if not parts:
        return "今日无接近触发的信号，市场处于平静区间。"
    return "<br>".join(parts)


# ─────────────────────── 莫兰迪配色 HTML 模板 ───────────────────────
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>宏观风险扫描 · Eco & Volatility Checker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    /* 莫兰迪色板 (低饱和灰调) */
    --bg: #e8e4dd;          /* 燕麦灰 */
    --card: #f2efe9;        /* 米白 */
    --card2: #e3ddd3;       /* 浅陶土 */
    --border: #cdc6ba;      /* 灰褐边 */
    --text: #4a463f;        /* 深咖灰 */
    --muted: #8a8377;       /* 灰褐 */
    --sage: #9aab97;        /* 鼠尾草绿(正常) */
    --sage-bg: #dfe6dc;
    --clay: #c08a7d;        /* 陶土红(危险) */
    --clay-bg: #ecd9d3;
    --mustard: #c9ac6b;     /* 芥末黄(警戒) */
    --mustard-bg: #ece2c8;
    --dust-blue: #8ea1ad;   /* 雾霾蓝(强调) */
    --dust-blue-bg: #dbe2e6;
    --mauve: #a693a0;       /* 灰紫 */
    --gold: #bfa06a;
    /* 信号灯专用鲜明红绿黄(仅用于小圆点,与莫兰迪大色块区分,便于一眼辨别) */
    --lamp-g: #2e9e5b;      /* 鲜明绿(正常) */
    --lamp-y: #e0a92e;      /* 鲜明琥珀黄(警戒) */
    --lamp-r: #d64545;      /* 鲜明红(危险) */
    --lamp-n: #9a938a;      /* 无信号灰(改空心圈,不填充) */
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; min-height: 100vh; line-height: 1.5; }}
  header {{ background: var(--card); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
  header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: .3px; }}
  header h1 span {{ color: var(--dust-blue); }}
  #update-time {{ font-size: 12px; color: var(--muted); }}
  .container {{ max-width: 1280px; margin: 0 auto; padding: 22px 28px 60px; }}

  /* ═══ 左侧模块索引栏(sticky nav) ═══ */
  .sidenav {{ position: fixed; top: 0; left: 0; width: 230px; height: 100vh; overflow-y: auto;
    background: var(--card2, #efece5); border-right: 1px solid var(--border); padding: 18px 12px 40px;
    z-index: 90; box-sizing: border-box; transition: transform .25s ease; }}
  .sidenav-title {{ font-size: 12px; font-weight: 800; color: var(--muted); text-transform: uppercase;
    letter-spacing: 1px; padding: 0 8px 10px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }}
  .sidenav a {{ display: block; font-size: 12.5px; line-height: 1.35; color: var(--text); text-decoration: none;
    padding: 7px 9px; border-radius: 7px; margin-bottom: 2px; border-left: 3px solid transparent; transition: all .15s; }}
  .sidenav a:hover {{ background: rgba(140,155,175,.14); }}
  .sidenav a.sn-active {{ background: rgba(140,155,175,.20); border-left-color: var(--dust-blue); font-weight: 700; color: var(--text); }}
  .sidenav a .sn-num {{ display: inline-block; min-width: 18px; color: var(--dust-blue); font-weight: 800; font-family: var(--mono); margin-right: 4px; }}
  /* 侧栏主题分组(可折叠) */
  .sn-group {{ margin-bottom: 6px; }}
  .sn-group-hdr {{ display: flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 800; color: var(--dust-blue);
    text-transform: none; letter-spacing: .3px; padding: 7px 8px; cursor: pointer; border-radius: 6px; user-select: none; }}
  .sn-group-hdr:hover {{ background: rgba(140,155,175,.10); }}
  .sn-caret {{ font-size: 10px; transition: transform .18s; }}
  .sn-collapsed .sn-caret {{ transform: rotate(-90deg); }}
  .sn-cnt {{ margin-left: auto; font-size: 10px; color: var(--muted); background: rgba(140,155,175,.16); padding: 1px 6px; border-radius: 8px; font-family: var(--mono); }}
  .sn-group-list {{ overflow: hidden; transition: max-height .22s ease; max-height: 600px; padding-left: 4px; }}
  .sn-collapsed .sn-group-list {{ max-height: 0; }}
  /* 宽屏: 主体右移给侧栏留位; 章节标题锚点偏移(避免被顶部遮挡) */
  .part-title {{ scroll-margin-top: 16px; }}
  #sn-toggle {{ display: none; }}
  @media (min-width: 1101px) {{
    body {{ padding-left: 230px; }}
  }}
  @media (max-width: 1100px) {{
    .sidenav {{ transform: translateX(-100%); box-shadow: 2px 0 16px rgba(0,0,0,.15); }}
    .sidenav.sn-open {{ transform: translateX(0); }}
    #sn-toggle {{ display: flex; position: fixed; top: 12px; left: 12px; z-index: 95;
      width: 42px; height: 42px; align-items: center; justify-content: center;
      background: var(--dust-blue); color: #fff; border: none; border-radius: 10px;
      font-size: 20px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.2); }}
  }}
  .section-title {{ font-size: 13px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin: 26px 0 12px; }}
  /* 编号章节标题(6部分) */
  .part-title {{ display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 800; color: var(--text); margin: 30px 0 14px; padding-bottom: 8px; border-bottom: 2px solid var(--border); }}
  .part-num {{ display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; background: var(--dust-blue); color: #fff; font-size: 14px; font-weight: 800; flex-shrink: 0; }}
  .freq-badge {{ margin-left: auto; font-size: 10.5px; font-weight: 700; padding: 3px 9px; border-radius: 10px; white-space: nowrap; letter-spacing: .02em; align-self: center; }}
  .freq-daily {{ background: rgba(46,158,91,0.14); color: #2e7d52; border: 1px solid rgba(46,158,91,0.3); }}
  .freq-weekly {{ background: rgba(107,143,181,0.16); color: #4a6d95; border: 1px solid rgba(107,143,181,0.34); }}
  .freq-monthly {{ background: rgba(224,169,46,0.16); color: #a9791a; border: 1px solid rgba(224,169,46,0.36); }}
  .freq-quarterly {{ background: rgba(150,120,175,0.16); color: #7a5a95; border: 1px solid rgba(150,120,175,0.34); }}
  .freq-event {{ background: rgba(138,133,120,0.14); color: #6d685c; border: 1px solid rgba(138,133,120,0.3); }}
  /* 普通(非flex) part-title 用 flex 让徽章能靠右 */
  .part-title {{ display: flex; align-items: center; gap: 10px; }}
  /* 综合结论卡片 */
  .concl-card {{ border-radius: 12px; padding: 16px 18px; border: 1px solid var(--border); }}
  /* ── 指标卡片网格(交易员屏) ── */
  .grp-label {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; margin: 16px 0 10px; padding: 5px 12px; border-radius: 6px; display: inline-block; }}
  .grp-short {{ background: var(--sage-bg); color: #5c6b58; }}
  .grp-mid {{ background: var(--mustard-bg); color: #7a6a3e; }}
  .grp-long {{ background: var(--clay-bg); color: #8a5648; }}
  .mcard-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(215px, 1fr)); gap: 12px; margin-bottom: 8px; }}
  .mcard {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 13px; border-left: 4px solid var(--muted); }}
  .mcard-g {{ border-left-color: var(--sage); }}
  .mcard-y {{ border-left-color: var(--mustard); }}
  .mcard-r {{ border-left-color: var(--clay); }}
  .mcard-n {{ border-left-color: var(--border); opacity: .8; }}
  .mc-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; }}
  .mc-name {{ font-size: 13px; font-weight: 700; line-height: 1.25; }}
  .mc-en {{ display: block; font-size: 9px; color: var(--muted); font-weight: 400; }}
  .mc-dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; margin-top: 2px; }}
  .mc-val {{ font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 24px; font-weight: 700; margin: 6px 0 2px; letter-spacing: -.5px; }}
  .chg {{ font-size: 12px; font-weight: 700; font-family: "SF Mono", monospace; margin-left: 4px; }}
  .chg-bad {{ color: var(--clay); }}
  .chg-good {{ color: var(--sage); }}
  .chg-flat {{ color: var(--muted); }}
  .mc-thr {{ font-size: 10.5px; color: var(--muted); margin-bottom: 6px; line-height: 1.4; }}
  .mc-spark {{ display: flex; align-items: center; gap: 6px; height: 38px; margin-bottom: 6px; }}
  .spark {{ width: 140px; height: 36px; }}
  .spark-na {{ font-size: 10px; color: var(--muted); font-style: italic; }}
  .mc-spark-lbl {{ font-size: 9px; color: var(--muted); }}
  .mc-how {{ font-size: 10.5px; color: var(--text); line-height: 1.5; background: var(--card2); border-radius: 6px; padding: 6px 8px; }}
  .mc-how b {{ color: var(--dust-blue); }}
  .mc-note {{ font-size: 11px; color: var(--text); line-height: 1.5; background: var(--dust-blue-bg); border-radius: 6px; padding: 6px 8px; margin-bottom: 5px; font-weight: 500; }}
  /* KOL 状态变化板块 */
  .kol-wrap {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
  .kol-item {{ background: var(--card2); border-radius: 8px; padding: 10px 12px; border-left: 3px solid var(--mauve); }}
  .kol-line b {{ font-size: 13px; }}
  .kol-sec {{ font-size: 10px; color: var(--muted); background: var(--card); padding: 1px 6px; border-radius: 4px; }}
  .kol-date {{ font-size: 10px; color: var(--muted); float: right; }}
  .kol-shift {{ font-size: 13px; font-weight: 700; margin: 5px 0; }}
  .kdir {{ padding: 1px 7px; border-radius: 4px; font-size: 12px; }}
  .kdir-r {{ background: var(--clay-bg); color: #8a5648; }}
  .kdir-y {{ background: var(--mustard-bg); color: #7a6a3e; }}
  .kdir-g {{ background: var(--sage-bg); color: #5c6b58; }}
  .kdir-n {{ background: var(--card); color: var(--muted); }}
  .kol-cmt {{ font-size: 11px; color: var(--muted); line-height: 1.5; margin-top: 4px; }}
  .kol-tgt {{ font-size: 10.5px; color: var(--dust-blue); margin-top: 3px; }}
  .kol-standing {{ font-size: 10px; color: var(--muted); margin-top: 5px; padding-top: 5px; border-top: 1px dashed var(--border); line-height: 1.45; }}
  /* KOL 状态变化模块化(仿13F) */
  .part-title-flex {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
  .kol-dash-btn {{ font-size: 12px; font-weight: 600; color: #fff; background: var(--dust-blue); padding: 6px 14px; border-radius: 6px; text-decoration: none; white-space: nowrap; transition: opacity .15s; }}
  .kol-dash-btn:hover {{ opacity: .82; }}
  .bis-card {{ line-height: 1.7; }}
  .bis-meta {{ font-size: 13px; color: var(--ink); margin-bottom: 8px; }}
  .bis-pts {{ margin: 6px 0 10px 0; padding-left: 20px; }}
  .bis-pts li {{ margin-bottom: 6px; font-size: 13px; color: var(--ink); }}
  .bis-how {{ font-size: 12px; color: var(--muted); border-top: 1px dashed var(--line); padding-top: 8px; margin-top: 6px; }}
  .bis-na {{ font-size: 13px; color: var(--muted); padding: 8px 0; }}
  .kol-overview {{ font-size: 12.5px; color: var(--text); line-height: 1.6; background: var(--card2); border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; }}
  .kol-overview b {{ color: var(--dust-blue); }}
  .kol-ov-note {{ display: block; font-size: 10.5px; color: var(--muted); margin-top: 4px; }}
  .kol-mod-inner {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; padding: 12px; }}
  .kol-arrow {{ font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 4px; margin-left: 4px; }}
  .kol-up {{ color: #fff; background: var(--clay); }}
  .kol-down {{ color: #fff; background: var(--sage); }}
  .kol-flat {{ color: var(--muted); background: var(--card); }}
  /* 本周 KOL 观点方向徽章(多空标色: 看多暖红/看空冷绿) */
  .kv-badge {{ font-size: 10.5px; font-weight: 700; padding: 1px 8px; border-radius: 4px; margin-left: 4px; vertical-align: middle; }}
  .kv-bull2 {{ color: #fff; background: var(--clay); }}
  .kv-bull {{ color: #8a3a2c; background: rgba(192,138,125,.30); }}
  .kv-mixed {{ color: var(--muted); background: var(--card2); border: 1px solid var(--border); }}
  .kv-bear {{ color: #2f5a3f; background: rgba(154,171,151,.32); }}
  .kv-bear2 {{ color: #fff; background: var(--sage); }}
  /* KOL 观点首现日期标注 */
  .kol-since {{ font-size: 9.5px; color: var(--muted); margin-left: 6px; font-family: var(--mono); }}
  .kol-since-new {{ color: #8a3a2c; font-weight: 700; }}
  /* ── 周期与术数预测 独立板块 ── */
  .cyc-head {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:8px; }}
  .cyc-count {{ font-size:13px; font-weight:700; color:#6d5f80; }}
  .cyc-sub {{ font-size:11px; color:var(--muted); font-family:var(--mono); }}
  .cyc-note {{ font-size:11.5px; line-height:1.65; color:#6b6357; background:#f6f3f9;
               border-left:3px solid #9d8bb0; padding:8px 11px; border-radius:0 4px 4px 0;
               margin-bottom:14px; }}
  .cyc-block {{ margin-bottom:18px; }}
  .cyc-block-title {{ font-size:12.5px; font-weight:700; color:#5f5468;
                      border-bottom:1px solid #e2dced; padding-bottom:5px; margin-bottom:10px;
                      display:flex; align-items:baseline; gap:8px; }}
  .cyc-block-sub {{ font-size:10.5px; font-weight:400; color:var(--muted); }}
  .cyc-item {{ border-left:3px solid #9d8bb0; }}
  .cyc-meta {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:3px 0 5px; }}
  .cyc-freq {{ font-size:9.5px; font-family:var(--mono); background:#ece6f2; color:#6d5f80;
               padding:1px 6px; border-radius:3px; font-weight:700; }}
  .cyc-school {{ font-size:10.5px; color:#7a7266; }}
  .cyc-region {{ font-size:9.5px; font-family:var(--mono); background:#e6ecf0; color:#4f6272;
                 padding:1px 6px; border-radius:3px; font-weight:700; }}
  .cyc-focus {{ font-size:10.5px; color:#7a7266; margin-top:4px; }}
  .cyc-hist {{ font-size:9.5px; font-family:var(--mono); color:#8a8377; }}
  .cyc-pending {{ background:#eee9e1 !important; color:#8a8377 !important; }}
  .cyc-muted {{ color:var(--muted); font-style:italic; }}
  .cyc-link {{ display:inline-block; margin-top:6px; font-size:10.5px; color:#6d5f80;
               text-decoration:none; border-bottom:1px dotted #9d8bb0; }}
  .cyc-link:hover {{ color:#4d4159; }}
  /* ── KOL 两层展开钻取(卡片 → 时间列表 → 单条详情) ── */
  .kol-drill {{ cursor: pointer; transition: box-shadow .15s, transform .15s; }}
  .kol-drill:hover {{ box-shadow: 0 3px 12px rgba(0,0,0,.10); transform: translateY(-1px); }}
  .kol-drill:focus-visible {{ outline: 2px solid var(--dust-blue); outline-offset: 2px; }}
  .kol-more {{ font-size: 10px; color: var(--dust-blue); margin-top: 6px; opacity: .75; }}
  .kol-drill:hover .kol-more {{ opacity: 1; }}
  .kd-mask {{ position: fixed; inset: 0; background: rgba(30,28,25,.52); z-index: 900;
              display: none; align-items: flex-start; justify-content: center; padding: 40px 16px; overflow-y: auto; }}
  .kd-mask.on {{ display: flex; }}
  .kd-panel {{ background: var(--bg); border-radius: 12px; max-width: 860px; width: 100%;
               box-shadow: 0 18px 50px rgba(0,0,0,.28); padding: 0 0 18px 0; }}
  .kd-head {{ position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line);
              padding: 16px 22px 12px; border-radius: 12px 12px 0 0; z-index: 2; }}
  .kd-name {{ font-size: 19px; font-weight: 700; color: var(--ink); }}
  .kd-close {{ float: right; cursor: pointer; font-size: 22px; line-height: 1; color: var(--muted);
               background: none; border: none; padding: 0 4px; }}
  .kd-close:hover {{ color: var(--ink); }}
  .kd-bio {{ font-size: 11.5px; color: var(--muted); line-height: 1.6; margin-top: 8px; }}
  .kd-bio b {{ color: var(--ink); font-weight: 600; }}
  .kd-count {{ font-size: 11px; color: var(--dust-blue); margin-top: 8px; font-family: var(--mono); }}
  .kd-body {{ padding: 6px 22px 0; }}
  .kd-grp {{ font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: .06em;
             margin: 16px 0 8px; padding-bottom: 4px; border-bottom: 1px dashed var(--line); }}
  .kd-row {{ border-left: 3px solid var(--border); padding: 8px 12px; margin-bottom: 6px;
             background: var(--card2); border-radius: 0 8px 8px 0; cursor: pointer; }}
  .kd-row:hover {{ background: var(--card); }}
  .kd-row-hd {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
  .kd-date {{ font-size: 11px; font-family: var(--mono); color: var(--muted); white-space: nowrap; }}
  .kd-one {{ font-size: 12px; color: var(--ink); line-height: 1.5; flex: 1 1 260px;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .kd-row.open .kd-one {{ white-space: normal; overflow: visible; }}
  .kd-caret {{ font-size: 10px; color: var(--muted); }}
  .kd-detail {{ display: none; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); }}
  .kd-row.open .kd-detail {{ display: block; }}
  .kd-full {{ font-size: 12.5px; color: var(--ink); line-height: 1.7; white-space: pre-wrap; }}
  .kd-kv {{ font-size: 11px; color: var(--muted); margin-top: 6px; }}
  .kd-kv a {{ color: var(--dust-blue); }}
  .kd-empty {{ font-size: 12px; color: var(--muted); padding: 18px 0; }}
  @media (max-width: 640px) {{
    .kd-mask {{ padding: 12px 8px; }}
    .kd-one {{ white-space: normal; }}
  }}
  /* 流动性板块 */
  .liq-row {{ font-size: 13px; margin-bottom: 8px; line-height: 1.7; }}
  .liq-k {{ color: var(--muted); }}
  .liq-lights {{ background: var(--card2); border-radius: 6px; padding: 6px 10px; }}
  .liq-note {{ font-size: 12px; color: var(--text); line-height: 1.7; background: var(--card2); border-radius: 8px; padding: 10px 12px; margin-top: 8px; }}
  .liq-note b {{ color: var(--dust-blue); }}
  .empty {{ color: var(--muted); font-size: 13px; font-style: italic; }}
  /* 三大央行资产负债表 view */
  .bs-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 8px; }}
  @media (max-width: 780px) {{ .bs-grid {{ grid-template-columns: 1fr; }} }}
  .bs-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .bs-rates {{ margin-top: 10px; padding-top: 8px; border-top: 1px dashed rgba(160,160,150,.28); font-size: 11.5px; color: var(--muted); }}
  .bs-rates b {{ color: var(--dust-blue); font-family: var(--mono); }}
  .bs-partial {{ margin-top: 6px; font-size: 10.5px; color: var(--muted); font-style: italic; }}
  /* 货币供应量 M0/M1/M2 模块 */
  .ms-intro {{ background: var(--card2); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }}
  .ms-intro-l {{ font-size: 11.5px; color: var(--text); line-height: 1.6; margin-bottom: 3px; }}
  .ms-intro-l b {{ color: var(--dust-blue); }}
  .ms-intro-l u {{ text-decoration: underline; text-underline-offset: 2px; }}
  .ms-cav {{ color: var(--muted); }}
  .ms-cav b {{ color: var(--clay); }}
  .ms-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
  .ms-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .ms-head {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: baseline; gap: 8px; }}
  .ms-meta {{ font-size: 10.5px; color: var(--muted); font-weight: 400; margin-left: auto; }}
  .ms-body {{ display: flex; flex-direction: column; gap: 8px; }}
  .ms-row {{ display: grid; grid-template-columns: 92px 1fr auto; align-items: center; gap: 8px; }}
  .ms-lbl {{ font-size: 11px; color: var(--text); font-weight: 600; }}
  .ms-bar-wrap {{ background: var(--bg); border-radius: 4px; height: 16px; overflow: hidden; }}
  .ms-bar {{ display: block; height: 100%; border-radius: 4px; }}
  .ms-b0 {{ background: var(--dust-blue); }}
  .ms-b1 {{ background: var(--sage); }}
  .ms-b2 {{ background: var(--gold); }}
  .ms-b3 {{ background: var(--mauve); }}
  .ms-v {{ font-size: 13px; font-weight: 700; font-family: var(--mono); color: var(--text); text-align: right; min-width: 62px; }}
  .ms-orig {{ display: block; font-size: 9px; font-weight: 400; color: var(--muted); }}
  .ms-src {{ font-size: 9.5px; color: var(--muted); margin-top: 10px; line-height: 1.4; border-top: 1px dotted var(--border); padding-top: 6px; }}
  /* M2 十年历史折线卡片 */
  .m2-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }}
  .m2-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .m2-head {{ font-size: 14px; font-weight: 700; margin-bottom: 10px; display: flex; align-items: baseline; gap: 8px; }}
  .m2-meta {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: auto; }}
  .m2-chart-box {{ margin: 4px 0 8px; }}
  .m2-chart {{ width: 100%; height: auto; }}
  .m2-chart-na {{ color: var(--muted); font-size: 11px; font-style: italic; padding: 20px 0; text-align: center; }}
  .m2-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 4px; }}
  .m2-stat {{ text-align: center; }}
  .m2-stat span {{ display: block; font-size: 9.5px; color: var(--muted); }}
  .m2-stat b {{ font-size: 13px; font-family: var(--mono); }}
  .m2-span {{ font-size: 9.5px; color: var(--muted); text-align: center; margin-top: 6px; }}
  .bs-head {{ font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 10px; display: flex; flex-direction: column; gap: 3px; }}
  .bs-meta {{ font-size: 10px; font-weight: 400; color: var(--muted); font-family: var(--mono); }}
  .bs-body {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  .bs-col {{ background: var(--card2); border-radius: 8px; padding: 8px 10px; }}
  .bs-assets {{ border-top: 3px solid var(--sage); }}
  .bs-liabs {{ border-top: 3px solid var(--clay); }}
  .bs-col-h {{ font-size: 11px; font-weight: 700; letter-spacing: .04em; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; }}
  .bs-line {{ display: flex; flex-direction: column; padding: 4px 0; border-bottom: 1px dashed var(--border); }}
  .bs-line:last-child {{ border-bottom: none; }}
  .bs-name {{ font-size: 11px; color: var(--text); }}
  .bs-val {{ font-size: 14px; font-weight: 700; font-family: var(--mono); color: var(--text); }}
  .bs-wow {{ font-size: 10px; font-family: var(--mono); }}
  .bs-up {{ color: var(--sage); }}
  .bs-down {{ color: var(--clay); }}
  .bs-flat {{ color: var(--muted); }}
  .bs-total {{ margin-top: 4px; padding-top: 6px; border-top: 1.5px solid var(--border); }}
  .bs-total .bs-name {{ font-weight: 700; }}
  .bs-total .bs-val {{ font-size: 15px; }}
  /* 子项(如货币发行⊂储备货币): 缩进+弱化, 表明是上一总项明细而非并列科目 */
  .bs-sub {{ padding-left: 14px; border-bottom: 1px dotted var(--border); }}
  .bs-sub .bs-name {{ font-size: 10px; color: var(--muted); }}
  .bs-sub .bs-val {{ font-size: 12px; font-weight: 600; color: var(--muted); }}
  /* 机构持仓 13F 卡片 */
  .h-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 8px; }}
  .h-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .h-trump {{ border-left: 3px solid var(--mustard); }}
  .h-head {{ font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 8px; display: flex; flex-direction: column; gap: 2px; }}
  .h-kol {{ font-size: 12px; font-weight: 500; color: var(--dust-blue); }}
  .h-meta {{ font-size: 10px; font-weight: 400; color: var(--muted); font-family: var(--mono); }}
  .h-body {{ display: flex; flex-direction: column; gap: 2px; }}
  .h-line {{ display: grid; grid-template-columns: 54px 1fr auto; gap: 6px; align-items: center; padding: 3px 0; border-bottom: 1px dashed var(--border); font-size: 11px; }}
  .h-line:last-child {{ border-bottom: none; }}
  .h-act {{ font-size: 10px; font-weight: 700; padding: 1px 4px; border-radius: 4px; text-align: center; white-space: nowrap; }}
  .h-new {{ background: var(--sage); color: #fff; }}
  .h-add {{ background: rgba(122,153,122,.22); color: var(--sage); }}
  .h-cut {{ background: rgba(179,122,110,.22); color: var(--clay); }}
  .h-exit {{ background: var(--clay); color: #fff; }}
  .h-flat {{ background: var(--card2); color: var(--muted); }}
  .h-buy {{ background: var(--sage); color: #fff; }}
  .h-sell {{ background: var(--clay); color: #fff; }}
  .h-tk {{ font-family: var(--mono); font-size: 9.5px; font-weight: 700; color: var(--sage); background: rgba(122,153,122,.14); padding: 0 3px; border-radius: 3px; margin-left: 3px; }}
  .h-pol-note {{ font-size: 10px; color: var(--muted); font-style: italic; margin-top: 6px; padding-top: 5px; border-top: 1px dashed rgba(160,160,150,.25); }}
  .h-iss {{ color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .h-val {{ font-family: var(--mono); font-weight: 700; color: var(--text); white-space: nowrap; }}
  .h-pct {{ color: var(--muted); font-weight: 500; }}
  .h-extra {{ font-size: 11px; color: var(--text); margin-top: 6px; line-height: 1.5; }}
  .h-note {{ grid-column: 1/-1; font-size: 11px; color: var(--muted); margin-top: 4px; line-height: 1.6; }}
  /* 机构持仓分模块展示 */
  .h-module {{ border: 2px solid; border-radius: 12px; margin-bottom: 16px; overflow: hidden; }}
  .h-module-title {{ display: flex; align-items: center; gap: 8px; padding: 8px 14px; color: #fff; font-size: 14px; font-weight: 700; }}
  .h-mod-dot {{ width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,.85); }}
  .h-mod-en {{ font-size: 11px; font-weight: 400; opacity: .85; }}
  .h-mod-n {{ margin-left: auto; font-size: 11px; font-weight: 500; background: rgba(255,255,255,.22); padding: 1px 8px; border-radius: 10px; }}
  .h-grid-inner {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; padding: 12px; }}
  .h-intro {{ font-size: 10.5px; color: var(--muted); line-height: 1.5; margin-bottom: 8px; background: var(--card2); border-radius: 6px; padding: 6px 8px; }}
  .h-intro-l {{ margin-bottom: 2px; }}
  .h-intro-l b {{ color: var(--dust-blue); font-weight: 700; margin-right: 3px; }}
  .dot-g {{ background: var(--lamp-g); }}
  .dot-y {{ background: var(--lamp-y); }}
  .dot-r {{ background: var(--lamp-r); }}
  .dot-n {{ background: transparent; border: 1.5px solid var(--lamp-n); box-shadow: none; }}
  .cc-short {{ background: var(--sage-bg); border-color: var(--sage); }}
  .cc-mid {{ background: var(--mustard-bg); border-color: var(--mustard); }}
  .cc-long {{ background: var(--clay-bg); border-color: var(--clay); }}
  .cc-head {{ font-size: 14px; font-weight: 700; margin-bottom: 8px; }}
  .cc-body {{ font-size: 13px; line-height: 1.7; color: var(--text); }}

  /* 综合信号 banner */
  .verdict {{ border-radius: 14px; padding: 18px 22px; margin-bottom: 20px; display: flex; align-items: center; gap: 20px; }}
  .verdict.calm   {{ background: var(--sage-bg);   border: 1px solid var(--sage); }}
  .verdict.warn   {{ background: var(--mustard-bg);border: 1px solid var(--mustard); }}
  .verdict.danger {{ background: var(--clay-bg);   border: 1px solid var(--clay); }}
  .verdict-main {{ font-size: 22px; font-weight: 800; }}
  .verdict-sub {{ font-size: 13px; color: var(--muted); }}
  .verdict-hit {{ margin-left: auto; text-align: right; }}
  .verdict-hit .hn {{ font-size: 28px; font-weight: 800; color: var(--clay); }}
  .verdict-hit .hl {{ font-size: 11px; color: var(--muted); }}

  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1.1fr 1fr; gap: 16px; }}

  /* 警报统计卡片 */
  .stat-card {{ border-radius: 12px; padding: 16px 18px; border: 1px solid var(--border); }}
  .sc-short {{ background: var(--sage-bg); }}
  .sc-mid   {{ background: var(--mustard-bg); }}
  .sc-long  {{ background: var(--clay-bg); }}
  .sc-label {{ font-size: 12px; font-weight: 600; color: var(--text); }}
  .sc-num {{ font-size: 30px; font-weight: 800; margin: 4px 0; }}
  .sc-sub {{ font-size: 11px; color: var(--muted); }}

  /* 雷达图 */
  #radar-wrap {{ display: flex; gap: 10px; }}
  .radar-cell {{ flex: 1; display: flex; flex-direction: column; align-items: center; }}
  .radar-sub {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
  .radar-box {{ position: relative; width: 100%; height: 240px; }}

  /* 仪表盘表格 */
  table.gauge {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.gauge th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 8px 10px; border-bottom: 2px solid var(--border); }}
  table.gauge td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); }}
  .group-head td {{ background: var(--card2); font-weight: 700; font-size: 12px; color: var(--text); letter-spacing: .5px; }}
  .ind-name {{ font-weight: 600; }}
  .ind-en {{ display: block; font-size: 10px; color: var(--muted); font-weight: 400; }}
  .ind-val {{ font-weight: 700; }}
  .ind-date, .ind-thr {{ color: var(--muted); font-size: 12px; }}
  .ind-sig {{ text-align: center; font-size: 16px; width: 44px; }}
  /* 红绿灯彩色圆点(鲜明红绿黄,与主指标灯统一,一眼可辨;无信号=空心圈) */
  .dot {{ display: inline-block; width: 13px; height: 13px; border-radius: 50%; vertical-align: middle; }}
  .dot-g {{ background: var(--lamp-g); box-shadow: 0 0 0 3px rgba(46,158,91,.20); }}
  .dot-y {{ background: var(--lamp-y); box-shadow: 0 0 0 3px rgba(224,169,46,.22); }}
  .dot-r {{ background: var(--lamp-r); box-shadow: 0 0 0 3px rgba(214,69,69,.20); }}
  .dot-n {{ background: transparent; border: 1.5px solid var(--lamp-n); box-shadow: none; opacity: 1; }}
  .stwarn {{ font-size: 10px; color: var(--clay); background: var(--clay-bg); padding: 1px 5px; border-radius: 4px; }}
  .stale-badge {{ display: inline-block; font-size: 10px; font-weight: 600; padding: 1.5px 6px; border-radius: 4px;
                  margin-left: 6px; white-space: nowrap; letter-spacing: .2px; vertical-align: middle; }}
  .sb-amber {{ color: #8a6d1f; background: rgba(224,169,46,.16); border: 1px solid rgba(224,169,46,.38); }}
  .sb-red   {{ color: #8a3f47; background: rgba(192,117,125,.16); border: 1px solid rgba(192,117,125,.42); }}
  .mc-slabel {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px; margin-left: 4px; }}
  .mc-slabel-g {{ color: #3f5a3f; background: rgba(154,171,151,.30); }}
  .mc-slabel-y {{ color: #8a6a2a; background: rgba(212,178,110,.32); }}
  .mc-slabel-r {{ color: #fff; background: var(--clay); }}
  /* 外国官方托管美债卡片 */
  .cust-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .mt-hero {{ font-size: 14px; color: var(--text); padding: 8px 12px; background: rgba(140,155,175,.10); border-radius: 8px; }}
  .mt-hero b {{ font-size: 20px; color: var(--sage); font-family: var(--mono); }}
  .mt-asof {{ font-size: 11px; color: var(--muted); font-family: var(--mono); margin-left: 6px; }}
  .mt-sub {{ display: block; font-size: 11px; color: var(--muted); margin-top: 3px; }}
  .mt-barmeta {{ font-size: 12px; color: var(--text); text-align: center; margin-top: 6px; }}
  .oil-meta {{ font-size: 12px; color: var(--text); text-align: center; margin-top: 6px; line-height: 1.5; }}
  .oil-src {{ font-size: 10.5px; color: var(--muted); text-align: center; margin-top: 3px; }}
  .fn-wrap {{ display: flex; flex-direction: column; gap: 12px; }}
  .fn-meta {{ font-size: 12px; color: var(--muted); display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }}
  .fn-list {{ display: flex; flex-direction: column; gap: 10px; }}
  .fn-card {{ background: var(--card2); border-radius: 8px; padding: 11px 14px; }}
  .fn-head {{ display: flex; align-items: center; gap: 9px; margin-bottom: 4px; }}
  .fn-date {{ font-family: var(--mono); font-size: 11.5px; color: var(--muted); }}
  .fn-flag {{ font-size: 14px; }}
  .fn-cat {{ font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 4px; background: rgba(160,160,150,.14); }}
  .fn-title {{ font-size: 13.5px; font-weight: 700; color: var(--text); line-height: 1.4; margin-bottom: 3px; }}
  .fn-sum {{ font-size: 12px; color: var(--muted); line-height: 1.6; }}
  .fn-src {{ font-size: 11px; margin-top: 5px; }}
  .cust-lbl {{ font-size: 12px; color: var(--muted); font-weight: 600; }}
  .cust-val {{ font-family: var(--mono); font-size: 34px; font-weight: 800; color: var(--text); line-height: 1.1; }}
  .cust-unit {{ font-size: 18px; color: var(--muted); margin-left: 2px; }}
  .cust-wow {{ font-size: 14px; font-weight: 700; margin-left: 10px; padding: 2px 8px; border-radius: 5px; vertical-align: middle; }}
  .cust-wow-g {{ color: #3f5a3f; background: rgba(154,171,151,.28); }}
  .cust-wow-r {{ color: #fff; background: var(--clay); }}
  .cust-wow-n {{ color: var(--muted); background: var(--card2); }}
  .cust-sub {{ font-size: 10px; color: var(--muted); font-family: var(--mono); }}
  .cust-meta {{ display: flex; gap: 20px; flex-wrap: wrap; padding: 8px 0; border-top: 1px dashed rgba(160,160,150,.25); border-bottom: 1px dashed rgba(160,160,150,.25); }}
  .cust-row {{ font-size: 12px; color: var(--dust-blue); }}
  .cust-row b {{ font-family: var(--mono); color: var(--text); margin-left: 6px; }}
  .cust-how {{ font-size: 11.5px; color: var(--muted); line-height: 1.6; }}
  .cust-how b {{ color: var(--dust-blue); }}
  .cust-g {{ color: #3f5a3f !important; }}
  .cust-r {{ color: var(--clay) !important; }}
  /* 托管美债折线图 */
  .cust-chart-box {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 6px; }}
  /* 左右双图: 短期(12月) / 长期(10年) */
  .cust-charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .cust-charts-3 {{ grid-template-columns: 1fr 1fr 1fr; }}
  @media (max-width: 720px) {{ .cust-charts, .cust-charts-3 {{ grid-template-columns: 1fr; }} }}
  @media (min-width: 721px) and (max-width: 1000px) {{ .cust-charts-3 {{ grid-template-columns: 1fr 1fr; }} }}
  .cust-chart-col {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 8px; }}
  .cust-chart-full {{ margin-top: 12px; }}
  .cust-chart-span {{ font-size: 10px; color: var(--muted); margin-top: 4px; text-align: center; }}
  .cust-chart-title {{ font-size: 11px; color: var(--muted); font-weight: 600; margin-bottom: 4px; font-family: var(--mono); }}
  .chart-freq {{ display: inline-block; margin-left: 8px; font-size: 10px; font-weight: 600; font-family: -apple-system, "PingFang SC", sans-serif; color: #4a6d95; background: rgba(107,143,181,0.12); border: 1px solid rgba(107,143,181,0.28); border-radius: 9px; padding: 1px 8px; vertical-align: middle; }}
  .chart-freq.freq-w {{ color: #4a6d95; }}
  .cust-chart {{ width: 100%; height: auto; display: block; }}
  .cust-chart-na {{ font-size: 12px; color: var(--muted); padding: 20px; text-align: center; }}
  .cc-grid {{ stroke: rgba(160,160,150,.20); stroke-width: 1; stroke-dasharray: 3 3; }}
  .cc-ylab {{ fill: var(--muted); font-size: 9px; font-family: var(--mono); text-anchor: end; }}
  .cc-xlab {{ fill: var(--muted); font-size: 9px; font-family: var(--mono); }}
  /* 分国别持有美债(TIC) 列头当前值 */
  .cu-cur {{ font-family: var(--mono); font-size: 20px; font-weight: 800; color: var(--text); line-height: 1.2; margin: 2px 0 6px; }}
  .cu-asof {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 6px; }}
  .cu-lagnote {{ font-size: 10.5px; color: #c9a227; background: rgba(201,162,39,.08);
                 border-left: 2px solid rgba(201,162,39,.5); border-radius: 3px;
                 padding: 4px 7px; margin: 4px 0 2px; line-height: 1.5; }}

  /* Credit Impulse 信贷脉冲(中期领先指标, 三国) */
  .ci-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .ci-cols {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
  .ca-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .ca-cells {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
  .ca-cell {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; text-align: center; }}
  .ca-clbl {{ font-size: 10px; color: var(--muted); margin-bottom: 3px; }}
  .ca-cval {{ font-family: var(--mono); font-size: 20px; font-weight: 800; line-height: 1.1; }}
  .ca-cnote {{ font-size: 10px; margin-top: 2px; }}
  .ca-chart {{ width: 100%; height: auto; }}
  .ca-leg {{ font-size: 11px; font-family: var(--mono); font-weight: 700; }}
  .ca-zlab {{ font-size: 9.5px; opacity: 0.75; }}
  @media (max-width: 720px) {{ .ca-cells {{ grid-template-columns: 1fr; }} }}
  .ci-cols-4 {{ grid-template-columns: repeat(4, 1fr); }}
  .ci-long {{ margin-top: 12px; background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 6px; }}
  .ci-long-title {{ font-size: 12px; color: var(--text); font-weight: 700; margin-bottom: 6px; }}
  .ci-long-note {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 8px; }}
  .ci-leg {{ font-size: 10px; font-family: var(--mono); }}
  .ci-col {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 8px; }}
  .ci-title {{ font-size: 12px; color: var(--text); font-weight: 700; margin-bottom: 4px; }}
  .ci-cur {{ font-family: var(--mono); font-size: 24px; font-weight: 800; line-height: 1.1; }}
  .ci-unit {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 5px; }}
  .ci-sig {{ font-size: 11px; margin: 2px 0 4px; display: flex; align-items: center; gap: 5px; }}
  .ci-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; border: 2px solid; background: transparent; }}
  .ci-asof {{ color: var(--muted); font-weight: 400; margin-left: auto; font-family: var(--mono); }}
  .ci-chart {{ width: 100%; height: auto; display: block; }}
  .ci-na {{ font-size: 12px; color: var(--muted); padding: 24px; text-align: center; }}
  .ci-zero {{ stroke: rgba(160,160,150,.55); stroke-width: 1.2; }}
  .ci-how {{ font-size: 11px; color: var(--muted); line-height: 1.6; background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; }}
  .ci-how b {{ color: var(--text); }}
  /* ── 世界前十经济体 债务/GDP ── */
  .dg-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .cips-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .cips-head {{ font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .cips-asof {{ font-size: 11px; font-weight: 400; color: var(--muted); }}
  .cips-sub {{ font-size: 12px; font-weight: 600; color: var(--text); margin-top: 4px; border-left: 3px solid var(--border); padding-left: 8px; }}
  .cips-svg {{ width: 100%; height: auto; display: block; }}
  .cips-kpis {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .cips-kpi {{ flex: 1 1 150px; background: var(--bg2, #fafafa); border: 1px solid var(--border); border-radius: 6px; padding: 7px 10px; display: flex; flex-direction: column; gap: 2px; }}
  .cips-kpi span {{ font-size: 10.5px; color: var(--muted); }}
  .cips-kpi b {{ font-size: 14px; color: var(--text); }}
  .dg-head {{ font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .dg-asof {{ font-size: 11px; font-weight: 400; color: var(--muted); }}
  .dg-sub {{ font-size: 12px; font-weight: 600; color: var(--text); margin-top: 4px; padding-left: 2px; border-left: 3px solid var(--border); padding-left: 8px; }}
  /* ── 美国分评级公司债 ── */
  .cc-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
  .cc-tbl {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  .cc-tbl th {{ text-align: right; font-weight: 600; color: var(--muted); font-size: 10.5px; padding: 5px 8px; border-bottom: 1px solid var(--border); }}
  .cc-tbl th:first-child {{ text-align: left; }}
  .cc-tbl td {{ padding: 5px 8px; border-bottom: 1px solid var(--border); color: var(--text); }}
  .cc-tbl tbody tr:hover {{ background: var(--card2); }}
  .cc-num {{ text-align: right; font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; }}
  .cc-tier {{ font-size: 9.5px; margin-left: 5px; }}
  .cc-na {{ color: var(--muted); opacity: 0.65; }}
  .cc-alert {{ font-size: 11.5px; line-height: 1.6; color: var(--text); background: rgba(192,117,125,0.09); border: 1px solid rgba(192,117,125,0.32); border-left: 3px solid #c0757d; border-radius: 8px; padding: 9px 12px; }}
  .cc-pct {{ font-size: 11.5px; line-height: 1.8; color: var(--muted); background: rgba(138,131,119,0.06); border: 1px solid rgba(138,131,119,0.2); border-radius: 8px; padding: 9px 12px; }}
  .cc-pct > b {{ color: var(--text); }}
  .cc-pchip {{ display: inline-block; margin: 0 4px; padding: 1px 7px; background: var(--card); border: 1px solid rgba(138,131,119,0.28); border-radius: 999px; font-size: 11px; white-space: nowrap; }}
  .cc-pchip b {{ color: var(--text); font-weight: 600; }}
  .cc-pchip i {{ font-style: normal; color: #a8a49b; cursor: help; margin-left: 3px; }}
  .cc-pnote {{ display: block; margin-top: 5px; font-size: 11px; }}
  .cc-pnote b {{ color: var(--text); }}
  .cc-osec {{ display: flex; flex-direction: column; gap: 8px; }}
  .cc-ogrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }}
  .cc-ocard {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }}
  .cc-olabel {{ font-size: 11px; color: var(--muted); }}
  .cc-oval {{ font-size: 19px; font-weight: 600; font-family: ui-monospace, monospace; color: var(--text); margin: 2px 0; }}
  .cc-oyoy {{ font-size: 11px; font-family: ui-sans-serif, system-ui; font-weight: 400; }}
  .cc-odate {{ font-size: 10px; color: var(--muted); margin-bottom: 4px; }}
  @media (max-width: 720px) {{ .ci-cols, .ci-cols-4 {{ grid-template-columns: 1fr; }} }}

  /* 国债市场压力四联图(竖向, 对齐 Morgan Stanley) */
  .sp-wrap {{ display: flex; flex-direction: column; gap: 18px; }}
  .sp-intro {{ font-size: 11.5px; color: var(--muted); line-height: 1.65; background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 13px; }}
  .sp-intro b {{ color: var(--text); }}
  .sp-asof {{ display: block; margin-top: 5px; font-family: var(--mono); font-size: 10.5px; color: var(--dust-blue); }}
  .sp-panel {{ background: var(--card2); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px 10px; }}
  .sp-head {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 2px; }}
  .sp-title {{ font-size: 14px; font-weight: 700; color: var(--text); }}
  .sp-sub {{ font-size: 11px; color: var(--muted); font-style: italic; }}
  .sp-axrow {{ display: flex; gap: 14px; margin: 2px 0 6px; }}
  .sp-axk {{ font-size: 10.5px; color: var(--muted); font-family: var(--mono); }}
  .sp-chart {{ width: 100%; height: auto; display: block; }}
  .sp-grid {{ stroke: rgba(160,160,150,.18); stroke-width: 1; stroke-dasharray: 3 3; }}
  .sp-zero {{ stroke: rgba(214,69,69,.55); stroke-width: 1.3; }}
  .sp-zlab {{ fill: rgba(214,69,69,.8); font-size: 9.5px; font-family: var(--mono); }}
  .sp-ylab {{ fill: var(--muted); font-size: 9.5px; font-family: var(--mono); }}
  .sp-ylab-r {{ fill: var(--muted); }}
  .sp-xlab {{ fill: var(--muted); font-size: 9.5px; font-family: var(--mono); }}
  .sp-leg {{ font-size: 10.5px; font-family: var(--mono); }}
  .sp-note {{ font-size: 11px; color: var(--muted); line-height: 1.6; margin-top: 6px; padding: 6px 10px; background: rgba(140,155,175,.08); border-radius: 6px; }}
  .sp-note b {{ color: var(--text); }}
  .sp-src {{ font-size: 10px; color: var(--muted); font-family: var(--mono); margin-top: 5px; opacity: .8; }}
  .src-lnk {{ color: #7fa0b8; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 2px; }}
  .src-lnk:hover {{ color: #a8c4d8; text-decoration-style: solid; }}
  .sp-pt {{ font-size: 9px; font-family: var(--mono); font-weight: 600; }}
  .sp-pt-cur {{ font-size: 9.5px; font-weight: 700; }}
  .sp-leg-stat {{ font-size: 8.5px; font-family: var(--mono); opacity: .92; }}
  .sp-na {{ font-size: 12px; color: var(--muted); padding: 24px; text-align: center; }}

  /* 基差套利去杠杆预警面板 */
  .bt-lampbar {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 4px 0 10px; }}
  .bt-lampbar-4 {{ grid-template-columns: repeat(4, 1fr); }}
  .bt-lamp {{ background: var(--card2); border: 1px solid var(--border); border-radius: 9px; padding: 10px 12px; text-align: center; }}
  .bt-lamp-ico {{ font-size: 20px; line-height: 1; margin-bottom: 4px; }}
  .bt-lamp-lab {{ font-size: 11px; color: var(--text); font-weight: 700; }}
  .bt-lamp-det {{ font-size: 10.5px; color: var(--muted); font-family: var(--mono); margin-top: 2px; }}
  .bt-mtitle {{ font-size: 13px; font-weight: 800; color: var(--text); margin: 14px 0 8px; display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; }}
  .bt-mtsub {{ font-size: 10.5px; font-weight: 500; color: var(--muted); }}
  .bt-matrix {{ border: 1px solid var(--border); border-radius: 9px; overflow: hidden; }}
  .bt-mrow {{ display: grid; grid-template-columns: 56px 52px 34px 1fr 72px 116px; align-items: center; gap: 6px; padding: 7px 12px; border-bottom: 1px solid rgba(160,160,150,.14); font-size: 12px; }}
  .bt-mrow:last-child {{ border-bottom: none; }}
  .bt-mhead {{ background: rgba(140,155,175,.1); font-size: 10.5px; color: var(--muted); font-weight: 700; }}
  .bt-mmkt {{ color: var(--text); font-weight: 600; }}
  .bt-mten {{ font-family: var(--mono); color: var(--muted); }}
  .bt-mlight {{ font-size: 14px; text-align: center; }}
  .bt-mcarry {{ font-family: var(--mono); }}
  .bt-myld {{ font-family: var(--mono); color: var(--muted); text-align: right; }}
  .bt-mspark {{ display: flex; align-items: center; gap: 5px; }}
  .bt-spark {{ width: 88px; height: 22px; }}
  .bt-spark-na {{ color: var(--muted); font-size: 11px; }}
  .bt-na {{ color: var(--muted); font-size: 11px; }}
  .bt-mnote {{ font-size: 11px; color: var(--dust-blue); cursor: help; }}
  .bt-mfoot {{ font-size: 10.5px; color: var(--muted); line-height: 1.55; margin-top: 8px; padding: 6px 10px; background: rgba(140,155,175,.07); border-radius: 6px; }}
  @media (max-width: 560px) {{
    .bt-lampbar {{ grid-template-columns: 1fr 1fr; }}
    .bt-mrow {{ grid-template-columns: 44px 40px 28px 1fr 56px; }}
    .bt-mspark {{ display: none; }}
  }}

  /* 国债拍卖 timeline */
  .auc-wrap {{ display: flex; flex-direction: column; gap: 12px; }}
  .auc-next-banner {{ background: rgba(140,155,175,.14); border: 1px solid var(--border); border-left: 3px solid var(--dust-blue); border-radius: 6px; padding: 8px 12px; font-size: 13px; color: var(--text); }}
  .auc-next-lbl {{ font-size: 11px; color: var(--dust-blue); font-weight: 700; margin-right: 6px; }}
  .auc-next-banner b {{ font-family: var(--mono); }}
  .auc-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }}
  .auc-term {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }}
  .auc-term-head {{ margin-bottom: 6px; }}
  .auc-term-name {{ font-size: 13px; font-weight: 800; color: var(--text); }}
  .auc-latest {{ padding: 6px 0 8px; border-bottom: 1px dashed rgba(160,160,150,.28); }}
  .auc-date {{ font-family: var(--mono); font-size: 13px; color: var(--text); font-weight: 700; margin-bottom: 4px; }}
  .auc-tag {{ font-size: 9px; background: var(--dust-blue); color: #fff; padding: 1px 5px; border-radius: 4px; margin-left: 6px; vertical-align: middle; font-weight: 600; }}
  .auc-metrics {{ display: flex; flex-wrap: wrap; gap: 10px; }}
  .auc-m-item {{ font-size: 11.5px; color: var(--muted); }}
  .auc-m-item b {{ font-family: var(--mono); color: var(--text); margin-left: 2px; }}
  .auc-timeline {{ display: flex; flex-direction: column; gap: 3px; padding: 6px 0 0; position: relative; }}
  .auc-past-node {{ display: flex; flex-wrap: wrap; gap: 8px; font-size: 10.5px; color: var(--muted); padding: 2px 0 2px 12px; border-left: 2px solid rgba(160,160,150,.30); }}
  .auc-p-date {{ font-family: var(--mono); color: var(--dust-blue); min-width: 66px; }}
  .auc-p-m {{ font-family: var(--mono); }}
  .auc-p-m b {{ font-family: var(--mono); }}
  .auc-next-node {{ font-size: 11px; color: var(--dust-blue); font-family: var(--mono); margin-top: 6px; padding-top: 5px; border-top: 1px dashed rgba(160,160,150,.28); }}
  .auc-g {{ color: #3f5a3f !important; font-weight: 700; }}
  .auc-m {{ color: var(--muted) !important; }}
  .auc-r {{ color: var(--clay) !important; font-weight: 700; }}
  .auc-n {{ color: var(--muted) !important; }}
  .auc-how {{ font-size: 11.5px; color: var(--muted); line-height: 1.7; }}
  .auc-how b {{ color: var(--dust-blue); }}

  /* 逐条解读 */
  .interp-group {{ font-size: 13px; color: var(--dust-blue); margin: 16px 0 8px; font-weight: 700; }}
  .interp-item {{ padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }}
  .interp-item p {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
  .ii-sig {{ margin-right: 6px; }}
  .ii-val {{ color: var(--dust-blue); font-weight: 700; margin-left: 6px; }}

  /* 卖出触发表 */
  table.trig {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.trig th {{ text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; padding: 8px 10px; border-bottom: 2px solid var(--border); }}
  table.trig td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); }}
  .tr-state {{ text-align: center; font-weight: 700; }}
  .tr-badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; }}
  .trb-hit {{ background: var(--clay); color: #fff; }}
  .trb-near {{ background: var(--mustard); color: #4a463f; }}
  .trb-no {{ background: var(--card2); color: var(--muted); }}
  tr.tr-hit  {{ background: var(--clay-bg); }}
  tr.tr-near {{ background: var(--mustard-bg); }}

  /* COT */
  .cot-card {{ background: var(--card2); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }}
  .cot-head {{ font-weight: 700; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }}
  .cot-date {{ font-size: 11px; color: var(--muted); font-weight: 400; }}
  .cot-surge {{ margin-left: auto; font-size: 11px; color: var(--muted); }}
  .cot-surge.surge-on {{ color: var(--clay); font-weight: 700; }}
  .cot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }}
  .cot-grid > div {{ display: flex; justify-content: space-between; font-size: 13px; border-bottom: 1px dashed var(--border); padding-bottom: 4px; }}
  .cl {{ color: var(--muted); }}
  .cv {{ font-weight: 700; }}

  .focus-box {{ background: var(--dust-blue-bg); border: 1px solid var(--dust-blue); border-radius: 12px; padding: 18px 20px; font-size: 14px; line-height: 1.7; }}
  .footnote {{ font-size: 11px; color: var(--muted); margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--border); }}
  @media (max-width: 860px) {{ .grid-3, .grid-2 {{ grid-template-columns: 1fr; }} #radar-wrap {{ flex-direction: column; }} }}

  /* 统一 hover tooltip: 折线点/柱子悬停显示 横纵坐标 */
  #chart-tip {{
    position: fixed; z-index: 9999; pointer-events: none;
    background: rgba(58,54,47,0.96); color: #f4efe4;
    border: 1px solid rgba(192,138,125,0.5); border-radius: 7px;
    padding: 6px 10px; font-size: 12px; line-height: 1.5;
    font-family: -apple-system,PingFang SC,sans-serif;
    box-shadow: 0 4px 14px rgba(0,0,0,0.28);
    opacity: 0; transition: opacity 0.08s; white-space: nowrap;
    max-width: 260px;
  }}
  #chart-tip.show {{ opacity: 1; }}
  #chart-tip .tip-d {{ color: #c9c2b2; font-size: 11px; }}
  #chart-tip .tip-v {{ font-weight: 700; font-size: 13px; }}
  /* 数据元素 hover 视觉反馈 */
  [data-tip] {{ cursor: crosshair; }}
  rect[data-tip]:hover {{ opacity: 1 !important; filter: brightness(1.12); }}
  circle.tip-hit {{ fill: transparent; stroke: none; }}
  circle.tip-hit:hover {{ fill: rgba(192,138,125,0.18); }}
</style>
</head>
<body>
<button id="sn-toggle" aria-label="模块索引" onclick="document.getElementById('sidenav').classList.toggle('sn-open')">☰</button>
<nav class="sidenav" id="sidenav">
  <div class="sidenav-title">📑 模块索引</div>
  <div id="sidenav-links"></div>
</nav>
<header>
  <h1>宏观风险扫描 · <span>Eco &amp; Volatility Checker</span></h1>
  <span id="update-time">数据日期 {date} · 生成 {generated}</span>
</header>
<div class="container">

  <!-- 综合信号 -->
  <div class="verdict {overall_cls}">
    <div>
      <div class="verdict-main">{overall}</div>
      <div class="verdict-sub">{sell_verdict}</div>
    </div>
    <div class="verdict-hit">
      <div class="hn">{hit} / 7</div>
      <div class="hl">硬性卖出触发</div>
    </div>
  </div>

  <!-- ═══ 第一部分：指标卡片(短/中/长分区，每卡带2周折线+threshold+如何看) ═══ -->
  <div class="part-title"><span class="part-num">1</span>指标卡片 · 18 项（短 → 中 → 长）<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="grp-label grp-short">🟢 短期指标 · 天-周 · 判断过热回调</div>
  <div class="mcard-grid">{cards_short}</div>
  <div class="grp-label grp-mid">🟡 中期指标 · 周-月 · 判断趋势转折</div>
  <div class="mcard-grid">{cards_mid}</div>
  <!-- 中期指标 · A/D 腾落线详情图 (SP500 全成分股真数据, Economic-Dashboard cron) -->
  <div class="part-title" id="sec-ad-line" style="font-size:15px;margin-top:14px"><span class="part-num">＋</span>NYSE A/D 腾落线详情 · S&amp;P500 全成分股累计腾落 (中期广度·顶背离判定·真数据)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{ad_line_real}</div>
  <div class="grp-label grp-long">🔴 长期指标 · 月-年 · 判断结构性周期顶</div>
  <div class="mcard-grid">{cards_long}</div>

  <!-- ═══ 第二部分：警报统计速览 + 雷达图 ═══ -->
  <div class="part-title"><span class="part-num">2</span>警报统计速览<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="grid-2">
    <div class="card">
      <div class="grid-3">{stat_short}{stat_mid}{stat_long}</div>
      <div class="section-title">风险雷达 (越大越危险 0-100)</div>
      <div id="radar-wrap">
        <div class="radar-cell"><div class="radar-sub">🟢 短期</div><div class="radar-box"><canvas id="rShort"></canvas></div></div>
        <div class="radar-cell"><div class="radar-sub">🟡 中期</div><div class="radar-box"><canvas id="rMid"></canvas></div></div>
        <div class="radar-cell"><div class="radar-sub">🔴 长期</div><div class="radar-box"><canvas id="rLong"></canvas></div></div>
      </div>
    </div>
    <div class="card">
      <div class="section-title" style="margin-top:0">金银 COT · commercial 持仓</div>
      <div style="display:grid;grid-template-columns:1fr;gap:12px">{cot_cards}</div>
    </div>
  </div>

  <!-- ═══ 第三部分：逐条解读 ═══ -->
  <div class="part-title"><span class="part-num">3</span>逐条简短解读<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{interp}</div>

  <!-- ═══ 第四部分：短中长期综合结论 ═══ -->
  <div class="part-title"><span class="part-num">4</span>短中长期综合结论<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="grid-3">
    <div class="concl-card cc-short">
      <div class="cc-head">🟢 短期（1-3 个月）</div>
      <div class="cc-body">{concl_short}</div>
    </div>
    <div class="concl-card cc-mid">
      <div class="cc-head">🟡 中期（3-12 个月）</div>
      <div class="cc-body">{concl_mid}</div>
    </div>
    <div class="concl-card cc-long">
      <div class="cc-head">🔴 长期（1-3 年+）</div>
      <div class="cc-body">{concl_long}</div>
    </div>
  </div>

  <!-- ═══ 第五部分：卖出触发状态追踪 ═══ -->
  <div class="part-title"><span class="part-num">5</span>卖出触发状态追踪（同时 ≥3 项 = 开始分批卖出）<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">
    <table class="trig">
      <thead><tr><th>触发条件</th><th>阈值</th><th>今日状态</th><th>达成</th></tr></thead>
      <tbody>{trigger_rows}</tbody>
    </table>
  </div>

  <!-- ═══ 第六部分：今日最需关注的一条信号 ═══ -->
  <div class="part-title"><span class="part-num">6</span>今日最需关注的一条信号<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="focus-box">{focus}</div>

  <!-- ═══ 附三·十二C：美股市场广度(RSP/SPY, A/D 腾落线代理补充) ═══ -->
  <div class="part-title" id="sec-market-breadth"><span class="part-num">＋</span>美股市场广度 · RSP/SPY 等权比 (广度代理·补充顶背离判定)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{market_breadth}</div>

  <!-- ═══ 附一·零：本周 KOL 观点全景(按模块+多空, Eco 独立每日快照) ═══ -->
  <div class="part-title part-title-flex"><span><span class="part-num">＋</span>本周 KOL 观点全景 · 按模块 (多空方向卡片)</span><span class="freq-badge freq-daily" style="margin-left:0">每日更新</span><a class="kol-dash-btn" href="https://curarpikt0000.github.io/kol-dashboard/" target="_blank" rel="noopener">📊 打开 KOL Dashboard →</a></div>
  <div class="card">{kol_views}</div>

  <!-- ═══ 附一：本周 KOL 状态变化(模块化, Eco 独立每日快照周对比) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>本周 KOL 状态变化 · 按模块 (态度转向 call-out)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{kol_changes}</div>

  <!-- ═══ 附一·二：周期与术数预测派(独立 section, 非常规方法论) ═══ -->
  <div class="part-title" id="sec-cycle-kol"><span class="part-num">＋</span>周期与术数预测 · 独立板块 (周期理论 / 金融占星 / 易经术数)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{cycle_kol}</div>

  <!-- ═══ 附二：流动性要点(联动 Economic Dashboard) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>流动性要点 · 央行/国债<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card liq-wrap">{liquidity}</div>

  <!-- ═══ 附三：四大央行资产负债表 (US/JP/CN/ECB, 2x2) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>四大央行资产负债表 · 每日更新 (US/JP/CN/ECB · 2x2 · 当天汇率统一折$B)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="bs-grid">{cb_balance}</div>

  <!-- ═══ 附三·一半：BIS 国际清算银行报告 (央行的央行 · 摘要+独立页) ═══ -->
  <div class="part-title part-title-flex"><span><span class="part-num">＋</span>BIS 国际清算银行报告 · 最新要点 (Quarterly Review 季度综述)</span><span class="freq-badge freq-quarterly" style="margin-left:0">每季度更新</span><a class="kol-dash-btn" href="https://curarpikt0000.github.io/Eco-and-Volatility-Checker/bis/" target="_blank" rel="noopener">📄 查看 BIS 报告全库 →</a></div>
  {bis_section}

  <!-- ═══ 附三·二：三国货币供应量 M0/M1/M2 (央行资负表的延伸: 从"央行造多少底钱"到"社会流通多少钱") ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国货币供应量 M0 / M1 / M2 · 月度 (央行资负表下延: 社会实际流通的钱)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{money_supply}</div>

  <!-- ═══ 附三·二·二：三国 M2 十年历史折线 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国 M2 十年走势 · 折线 ($B 当天汇率统一折算 · 放水力度长期对比)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{m2_history}</div>

  <!-- ═══ 附三·二·三：Credit Impulse 信贷脉冲 (中期领先指标, 领先实体经济6-9月) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>Credit Impulse 信贷脉冲 · 中期领先指标 (美/中/欧 · 季度 · 新增信贷的加速度 · 领先实体经济6-9月)<span class="freq-badge freq-quarterly">每季度更新</span></div>
  <div class="card">{credit_impulse}</div>
  <!-- ═══ 附三·A1：世界前十经济体 政府债务/GDP ═══ -->
  <div class="part-title" id="sec-debt-gdp"><span class="part-num">＋</span>世界前十大经济体 · 政府债务 / GDP (主权债务可持续性 · IMF WEO)<span class="freq-badge freq-quarterly">年度 · IMF 一年发布两次</span></div>
  <div class="card">{debt_gdp}</div>
  <!-- ═══ 附三·A2：美国分评级公司债 收益率/利差/总额 ═══ -->
  <div class="part-title" id="sec-corp-credit"><span class="part-num">＋</span>美国公司债 · 分评级 收益率 / OAS 利差 / 未偿总额 (信用周期先行哨兵)<span class="freq-badge freq-daily">利差每日 · 总额季度</span></div>
  <div class="card">{corp_credit}</div>
  <!-- ═══ 附三·A3：中国 CIPS 跨境人民币支付 ═══ -->
  <div class="part-title" id="sec-cips"><span class="part-num">＋</span>中国 CIPS · 跨境人民币支付系统使用量 (人民币国际化 · 月度总额 / 日均强度)<span class="freq-badge freq-monthly">月度 · 官方次月发布</span></div>
  <div class="card">{cips}</div>

  <div class="part-title" id="sec-ai-fcf"><span class="part-num">＋</span>AI 产业链 · 自由现金流与信用维度 (资本开支强度 · 杠杆 · 偿息能力)<span class="freq-badge freq-monthly">年度 · 随年报更新</span></div>
  <div class="card">{ai_fcf}</div>

  <!-- ═══ 附三·二·四：国债市场压力四联图 (对齐 Morgan Stanley 三图 + OFR官方压力指数, 竖向) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>国债市场收益率·波动性·压力 · 竖向四联图 (对齐 Morgan Stanley · 过去3年真实公开数据 · 每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{stress_panels}</div>
  <!-- ═══ 附三·二B：基差套利去杠杆预警 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>基差套利去杠杆预警 · 美债/日债 (SOFR 倒挂 + Carry 空间 + 波动触发 · 强平潮尾部风险 · 每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{basis_trade}</div>
  <!-- ═══ 附三·三：美国国债拍卖 timeline ═══ -->
  <div class="part-title"><span class="part-num">＋</span>美国国债拍卖 · 财政部 (最新+过去3次 · 规模/中标率/收益率/间接投标 · 下次日程)<span class="freq-badge freq-event">每次拍卖</span></div>
  <div class="card">{auctions}</div>
  <!-- ═══ 附三·五：外国官方在纽约联储托管的美债 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>外国官方托管美债 · 纽约联储 (去美元化风向标)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{custody}</div>
  <div class="card">{custody_accel}</div>
  <!-- ═══ 附三·六：1年内到期需展期的可交易国债(再融资墙) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>1年内到期可交易国债 · 再融资墙 (rollover 压力)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{maturing_treasury}</div>
  <!-- ═══ 附三·八：美日 10Y/30Y 国债收益率四线图 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>美日 10年/30年国债收益率 · 过去一年 (四线同图 · 美日利差与套息)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{yield_curves}</div>
  <!-- ═══ 附三·八B：美国国债收益率百年周期(4线, 1934→今) ═══ -->
  <div class="part-title" id="sec-us-yield-century"><span class="part-num">＋</span>美国国债收益率百年周期 · Fed Funds/3M/10Y/30Y (40年长周期·1940大底/1980大顶/2020大底)<span class="freq-badge freq-quarterly">每季更新</span></div>
  <div class="card">{us_yield_century}</div>
  <!-- ═══ 附三·六：日本 / 中国 分国别持有美债 (TIC, 近10年) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>日本 / 中国 / 欧盟 持有美债 · 近10年 + 2008长历史 (TIC 分国别口径)<span class="freq-badge freq-monthly">日/中 每月更新·滞后约2月 · 欧盟受口径限制滞后至上年末</span></div>
  <div class="card">{country_ust}</div>
  <!-- ═══ 附三·十：四国国际投资头寸 IIP (对外资产/负债/净头寸) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>四国国际投资头寸 IIP · 过去十年 (美/日/德/中 对外资产·负债·净债权地位)<span class="freq-badge freq-quarterly">每年更新</span></div>
  <div class="card">{iip_four}</div>
  <!-- ═══ 附三·十二：对冲基金美债杠杆监测 (OFR) ═══ -->
  <div class="part-title" id="sec-hf-leverage"><span class="part-num">＋</span>对冲基金美债杠杆监测 · 敞口/GDP + 回购借款 (美债隐性杠杆)<span class="freq-badge freq-quarterly">每季度更新</span></div>
  <div class="card">{hf_leverage}</div>
  <!-- ═══ 附三·七：美国石油库存运营红线 (Brent-WTI价差 / Cushing / SPR) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>美国石油库存运营红线 · 能源安全 (Brent-WTI 价差 / Cushing / SPR · tank bottom)<span class="freq-badge freq-weekly">每周更新 · 价差每日</span></div>
  <div class="card">{oil_inventory}</div>
  <!-- ═══ 附三·十二A：COMEX & 上海贵金属库存 + GLD/SLV ETF 资金流 ═══ -->
  <div class="part-title" id="sec-comex-inventory"><span class="part-num">＋</span>COMEX &amp; 上海贵金属库存 + GLD/SLV ETF 资金流 (金/银/铂 东西方库存对照 · 实物流向/逼仓信号)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{comex_inventory}</div>
  <!-- ═══ 附三·十二B：BIS 自营黄金掉期 ═══ -->
  <div class="part-title" id="sec-bis-gold-swaps"><span class="part-num">＋</span>BIS 自营黄金掉期 · 央行黄金市场隐秘干预信号 (吨 · 2010→今)<span class="freq-badge freq-quarterly">年度确认+月度推算</span></div>
  <div class="card">{bis_gold_swaps}</div>
  <!-- ═══ 附三·十二B2：美国黄金出口(FRED IEAXGG, 去美元化/回流实物金) ═══ -->
  <div class="part-title" id="sec-gold-exports"><span class="part-num">＋</span>美国黄金出口 · Nonmonetary Gold Exports (各国黄金运回家·去美元化实物信号·2026Q1暴涨4.9×)<span class="freq-badge freq-quarterly">每季更新</span></div>
  <div class="card">{gold_exports}</div>
  <!-- ═══ 附三·十二B1：印度/中国黄金 domestic premium (WGC goldhub) ═══ -->
  <div class="part-title" id="sec-gold-premium"><span class="part-num">＋</span>印度 &amp; 中国黄金 Domestic Premium/Discount (亚洲实物黄金需求风向标·WGC 真数据)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{gold_premium}</div>
  <!-- ═══ 附三·十二B1b：印度白银月度进口 (UN Comtrade) ═══ -->
  <div class="part-title" id="sec-silver-imports"><span class="part-num">＋</span>印度白银月度进口 · Silver Bullion Imports (全球最大白银进口国·实物需求风向标·UN Comtrade 免费月度)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{silver_imports}</div>
  <!-- ═══ 附三·十二D：白银做市商头寸(CFTC COT, 一手) ═══ -->
  <div class="part-title" id="sec-silver-bank-positions"><span class="part-num">＋</span>白银做市商头寸 · CFTC COT commercial 净持仓 (做市商接货 vs 压价·一手真数据)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{silver_bank_positions}</div>
  <!-- ═══ 附三·十二E：COMEX 白银 issues/stops 静态参考(ANONYMIZED_PERSON_0_15) ═══ -->
  <div class="part-title" id="sec-comex-silver-issues"><span class="part-num">＋</span>COMEX 白银 投行累计 issues/stops · 静态参考 (ANONYMIZED_PERSON_0_23 @DtDS_WSS·CME封禁无法自动更新)<span class="freq-badge" style="background:#e8e2d5;color:#8a6d3b">静态参考</span></div>
  <div class="card">{comex_silver_issues_ref}</div>
  <!-- ═══ 附三·十二F：COMEX 做市商每周净 issue/stop 柱状图(金+银, 一手) ═══ -->
  <div class="part-title" id="sec-comex-issue-stop"><span class="part-num">＋</span>COMEX 做市商每周净 issue/stop · 金+银 (一手·大行发货vs接货·每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{comex_issue_stop}</div>
  <!-- ═══ 附三·十一：美日财政政策事件时间线 ═══ -->
  <div class="part-title" id="sec-fiscal-news"><span class="part-num">＋</span>美日财政政策事件 · 债务上限/CR/补正预算/国债发行 (每日检索)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{fiscal_news}</div>
  <!-- ═══ 附三·十一B：日美年度财政花费(双轴柱状) ═══ -->
  <div class="part-title" id="sec-fiscal-budget"><span class="part-num">＋</span>日美年度财政花费 · 政府总支出/预算 (双轴 · 已确定vs进行中)<span class="freq-badge freq-monthly">年度</span></div>
  <div class="card">{fiscal_budget}</div>
  <!-- ═══ 附三·九：日经225 vs 外资净买入日股 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>日经225 vs 外资净买入日股 · 过去一年 (日本市场 · 外资资金流)<span class="freq-badge freq-weekly">指数每日 · 外资每周</span></div>
  <div class="card">{nikkei_flow}</div>
  <!-- ═══ 附四：知名机构持仓 (13F) + Trump ═══ -->
  <div class="part-title"><span class="part-num">＋</span>机构持仓追踪 · 13F + Trump (对比上期变动)<span class="freq-badge freq-quarterly">每季度 · Trump不定期</span></div>
  <div class="h-grid">{holdings}</div>

  <div class="footnote">
    数据源：<a class="src-lnk" href="https://fred.stlouisfed.org/" target="_blank" rel="noopener">FRED</a> (VIX/HY/收益率曲线) · CNN F&amp;G · CBOE · AAII · GuruFocus · Conference Board · Renaissance · currentmarketvaluation · multpl · <a class="src-lnk" href="https://www.cftc.gov/dea/futures/deacmxsf.htm" target="_blank" rel="noopener">CFTC COT</a> (金银 commercial)。<br>
    阈值基于历史经验静态设定，不随市场情绪调整。取不到的指标标注"—"或状态，绝不以训练数据/猜测填充。时区 JST。
  </div>
</div>

<script>
const RADAR = {radar_json};
function mkRadar(id, d) {{
  const el = document.getElementById(id);
  if (!el || !d.labels.length) return;
  new Chart(el, {{
    type: 'radar',
    data: {{ labels: d.labels, datasets: [{{
      label: '风险分', data: d.scores,
      backgroundColor: 'rgba(192,138,125,0.28)',
      borderColor: 'rgba(192,138,125,0.9)', borderWidth: 2,
      pointBackgroundColor: 'rgba(142,161,173,0.95)', pointRadius: 3,
    }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ r: {{
        min: 0, max: 100, ticks: {{ stepSize: 25, color: '#8a8377', font: {{ size: 9 }}, backdropColor: 'transparent' }},
        grid: {{ color: '#cdc6ba' }}, angleLines: {{ color: '#cdc6ba' }},
        pointLabels: {{ color: '#4a463f', font: {{ size: 10 }} }}
      }} }}
    }}
  }});
}}
mkRadar('rShort', RADAR.short);
mkRadar('rMid', RADAR.mid);
mkRadar('rLong', RADAR.long);

// ═══ 自动生成左侧模块索引栏(按主题分组 + 可折叠) ═══
(function() {{
  var titles = Array.prototype.slice.call(document.querySelectorAll('.part-title'));
  var box = document.getElementById('sidenav-links');
  if (!titles.length || !box) return;

  var GROUPS = [
    {{ name: '核心风险扫描', match: ['指标卡片','警报统计','逐条','综合结论','卖出触发','今日最需关注','A/D 腾落线','市场广度'] }},
    {{ name: 'KOL 观点', match: ['KOL 观点全景','KOL 状态变化'] }},
    {{ name: '流动性与央行', match: ['流动性要点','央行资产负债表','国际清算银行','货币供应','M2 十年','Credit Impulse','信贷脉冲'] }},
    {{ name: '国债流动性观测', match: ['国债市场收益率','市场压力','基差套利去杠杆预警','SOFR 倒挂','国债拍卖','托管美债','再融资墙','1年内到期','持有美债','分国别','10年/30年国债收益率','美日 10','国际投资头寸','IIP','净头寸','对冲基金美债杠杆','回购借款','百年周期'] }},
    {{ name: '能源与大宗', match: ['石油库存','能源安全','Cushing','SPR','Brent','COMEX & 上海','贵金属库存','ETF 资金流','白银做市商','COMEX 白银','投行累计','做市商每周净','issue/stop','自营黄金掉期','黄金出口','Nonmonetary','黄金 Domestic Premium','Premium/Discount','白银月度进口','Silver Bullion'] }},
    {{ name: '财政政策', match: ['美日财政政策事件','债务上限','补正预算','国债发行','年度财政花费','财政花费','政府总支出'] }},
    {{ name: '日本市场', match: ['日经225','外资净买入','日本市场'] }},
    {{ name: '机构与政要持仓', match: ['机构持仓','13F','Trump'] }}
  ];
  function groupOf(label) {{
    for (var g = 0; g < GROUPS.length; g++) {{
      for (var m = 0; m < GROUPS[g].match.length; m++) {{
        if (label.indexOf(GROUPS[g].match[m]) >= 0) return g;
      }}
    }}
    return GROUPS.length;
  }}

  var links = [];
  var bucket = {{}};
  titles.forEach(function(t, i) {{
    var id = 'sec-' + i;
    t.id = id;
    var _tc = t.cloneNode(true);
    var _fb = _tc.querySelector('.freq-badge'); if (_fb) _fb.remove();
    var label = (_tc.textContent || '').trim();
    var short = label.split('·')[0].split('（')[0].split('(')[0].trim();
    short = short.replace(/^[0-9０-９＋+\s]+/, '').trim();
    if (short.indexOf('打开 KOL Dashboard') >= 0) short = short.split('打开')[0].trim();
    if (short.length > 18) short = short.slice(0, 18) + '…';
    var a = document.createElement('a');
    a.href = '#' + id;
    a.innerHTML = short;
    a.addEventListener('click', function(e) {{
      e.preventDefault();
      document.getElementById(id).scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      if (window.innerWidth <= 1100) document.getElementById('sidenav').classList.remove('sn-open');
    }});
    var g = groupOf(label);
    (bucket[g] = bucket[g] || []).push({{ a: a, idx: i }});
    links[i] = a;
  }});

  function renderGroup(gIdx, gName) {{
    var items = bucket[gIdx];
    if (!items || !items.length) return;
    var wrap = document.createElement('div');
    wrap.className = 'sn-group';
    var hdr = document.createElement('div');
    hdr.className = 'sn-group-hdr';
    hdr.innerHTML = '<span class="sn-caret">▾</span>' + gName + '<span class="sn-cnt">' + items.length + '</span>';
    var list = document.createElement('div');
    list.className = 'sn-group-list';
    items.forEach(function(it) {{ list.appendChild(it.a); }});
    hdr.addEventListener('click', function() {{ wrap.classList.toggle('sn-collapsed'); }});
    wrap.appendChild(hdr);
    wrap.appendChild(list);
    box.appendChild(wrap);
  }}
  GROUPS.forEach(function(g, i) {{ renderGroup(i, g.name); }});
  renderGroup(GROUPS.length, '其他');

  function onScroll() {{
    // 用 getBoundingClientRect (相对视口, 不受父元素定位上下文影响) 判定当前章节。
    // 触发线 = 视口顶部下方 120px; 找最后一个标题顶部已越过触发线的 section。
    var trigger = 120;
    var active = 0;
    for (var i = 0; i < titles.length; i++) {{
      var top = titles[i].getBoundingClientRect().top;
      if (top - trigger <= 0) active = i; else break;
    }}
    // 到达页面底部时高亮最后一项(最后一节可能不够长无法越过触发线)
    if ((window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 4)) {{
      active = titles.length - 1;
    }}
    links.forEach(function(l, i) {{
      if (!l) return;
      var on = (i === active);
      l.classList.toggle('sn-active', on);
      if (on) {{
        // 展开所在分组(若被折叠) + 把激活项滚进侧栏可视区
        var grp = l.closest ? l.closest('.sn-group') : null;
        if (grp) grp.classList.remove('sn-collapsed');
        var nav = document.getElementById('sidenav');
        if (nav) {{
          // 侧栏 menu 跟随: 若高亮项不在侧栏可视区内, 平滑滚动侧栏使其居中偏上
          var lr = l.getBoundingClientRect(), nr = nav.getBoundingClientRect();
          var margin = 24;
          if (lr.top < nr.top + margin || lr.bottom > nr.bottom - margin) {{
            // 高亮项相对侧栏内容顶部的偏移 = 当前scrollTop + (项视口top - 侧栏视口top)
            var offsetInNav = nav.scrollTop + (lr.top - nr.top);
            // 目标: 让高亮项出现在侧栏可视区 1/3 处
            var target = offsetInNav - nr.height * 0.33;
            if (target < 0) target = 0;
            nav.scrollTo ? nav.scrollTo({{ top: target, behavior: 'smooth' }}) : (nav.scrollTop = target);
          }}
        }}
      }}
    }});
  }}
  window.addEventListener('scroll', onScroll, {{ passive: true }});
  window.addEventListener('resize', onScroll, {{ passive: true }});
  onScroll();
}})();

/* ── 统一图表 tooltip: hover 折线点/柱子显示横纵坐标 ── */
(function() {{
  var tip = document.getElementById('chart-tip');
  if (!tip) {{
    tip = document.createElement('div');
    tip.id = 'chart-tip';
    document.body.appendChild(tip);
  }}
  function show(el, ev) {{
    var raw = el.getAttribute('data-tip');
    if (!raw) return;
    // 格式: "日期||数值"  (|| 分隔横纵坐标)
    var parts = raw.split('||');
    var d = parts[0] || '';
    var v = parts.length > 1 ? parts[1] : '';
    var html = '';
    if (d) html += '<div class="tip-d">' + d + '</div>';
    if (v) html += '<div class="tip-v">' + v + '</div>';
    tip.innerHTML = html || raw;
    tip.classList.add('show');
    move(ev);
  }}
  function move(ev) {{
    var x = ev.clientX, y = ev.clientY;
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var nx = x + 14, ny = y - th - 10;
    if (nx + tw > window.innerWidth - 8) nx = x - tw - 14;
    if (ny < 8) ny = y + 16;
    tip.style.left = nx + 'px';
    tip.style.top = ny + 'px';
  }}
  function hide() {{ tip.classList.remove('show'); }}
  // 事件委托: 整个 document 监听, 只对带 data-tip 的元素响应
  document.addEventListener('mouseover', function(ev) {{
    var el = ev.target.closest ? ev.target.closest('[data-tip]') : null;
    if (el) show(el, ev);
  }});
  document.addEventListener('mousemove', function(ev) {{
    if (tip.classList.contains('show')) {{
      var el = ev.target.closest ? ev.target.closest('[data-tip]') : null;
      if (el) move(ev); else hide();
    }}
  }});
  document.addEventListener('mouseout', function(ev) {{
    var el = ev.target.closest ? ev.target.closest('[data-tip]') : null;
    if (el) hide();
  }});
}})();

/* ── KOL 两层展开钻取: 卡片 → 全部历史观点列表 → 单条完整详情 ── */
(function() {{
  var DATA = {kol_history_json};
  // 弹层骨架运行时注入(避免污染静态模板结构)
  var mask = document.createElement('div');
  mask.className = 'kd-mask';
  mask.id = 'kd-mask';
  mask.setAttribute('role', 'dialog');
  mask.setAttribute('aria-modal', 'true');
  mask.innerHTML = '<div class="kd-panel">' +
      '<div class="kd-head">' +
        '<button class="kd-close" type="button" aria-label="关闭">&times;</button>' +
        '<div class="kd-name" id="kd-name"></div>' +
        '<div class="kd-bio" id="kd-bio"></div>' +
        '<div class="kd-count" id="kd-count"></div>' +
      '</div>' +
      '<div class="kd-body" id="kd-body"></div>' +
    '</div>';
  document.body.appendChild(mask);
  var elName = mask.querySelector('#kd-name');
  var elBio = mask.querySelector('#kd-bio');
  var elCount = mask.querySelector('#kd-count');
  var elBody = mask.querySelector('#kd-body');

  function esc(s) {{
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }}
  // 本周 = 本周一(含) 之后; 与页面其它板块"本周"口径一致(周一为周首日)
  function mondayStr() {{
    var d = new Date();
    var wd = (d.getDay() + 6) % 7;           // 周一=0
    d.setDate(d.getDate() - wd);
    var m = String(d.getMonth() + 1), day = String(d.getDate());
    return d.getFullYear() + '-' + (m.length < 2 ? '0' + m : m) + '-' + (day.length < 2 ? '0' + day : day);
  }}
  var MON = mondayStr();

  function rowHtml(r, idx) {{
    // r = [first, last, direction, comments, targets, source]
    var first = r[0] || '', last = r[1] || '', dir = r[2] || '', cmt = r[3] || '';
    var tgt = r[4] || '', src = r[5] || '';
    // 日期区间: 同一言论连续多日持有 → 显示 "起 ~ 止"; 单日 → 只显一个日期
    var dateTxt = (first && last && first !== last) ? (first + ' ~ ' + last) : (last || first);
    var kv = '';
    if (dir) kv += '<span class="kd-kv-i">方向：<b>' + esc(dir) + '</b></span>';
    if (tgt) kv += (kv ? ' · ' : '') + '标的：' + esc(tgt);
    if (first && last && first !== last) {{
      kv += (kv ? ' · ' : '') + '该观点连续见于 ' + esc(first) + ' 至 ' + esc(last);
    }}
    var srcHtml = src
      ? '<div class="kd-kv">原文出处：<a href="' + esc(src) + '" target="_blank" rel="noopener">' + esc(src) + '</a></div>'
      : '<div class="kd-kv">出处：每日快照汇总（无单条原文链接）</div>';
    return '<div class="kd-row" data-i="' + idx + '">' +
             '<div class="kd-row-hd">' +
               '<span class="kd-date">' + esc(dateTxt) + '</span>' +
               (dir ? '<span class="kd-date">[' + esc(dir) + ']</span>' : '') +
               '<span class="kd-one">' + esc(cmt) + '</span>' +
               '<span class="kd-caret">▸</span>' +
             '</div>' +
             '<div class="kd-detail">' +
               '<div class="kd-full">' + esc(cmt) + '</div>' +
               (kv ? '<div class="kd-kv">' + kv + '</div>' : '') +
               srcHtml +
             '</div>' +
           '</div>';
  }}

  function open(kol) {{
    var d = DATA[kol];
    elName.textContent = kol;
    if (!d || !d.h || !d.h.length) {{
      elBio.innerHTML = '';
      elCount.textContent = '';
      elBody.innerHTML = '<div class="kd-empty">该 KOL 暂无已归档的历史观点记录。</div>';
    }} else {{
      var bio = '';
      if (d.s) bio += '<div><b>业界地位：</b>' + esc(d.s) + '</div>';
      if (d.f) bio += '<div style="margin-top:5px"><b>关注领域：</b>' + esc(d.f) + '</div>';
      elBio.innerHTML = bio;
      var hs = d.h;
      // 分组: 本周 / 更早(均按时间倒序, 数据层已排好)
      var wk = [], older = [];
      for (var i = 0; i < hs.length; i++) {{
        ((hs[i][1] || '') >= MON ? wk : older).push([hs[i], i]);
      }}
      var html = '';
      if (wk.length) {{
        html += '<div class="kd-grp">本周观点 · ' + wk.length + ' 条</div>';
        for (var a = 0; a < wk.length; a++) html += rowHtml(wk[a][0], wk[a][1]);
      }}
      if (older.length) {{
        html += '<div class="kd-grp">更早观点 · ' + older.length + ' 条（时间倒序）</div>';
        for (var b = 0; b < older.length; b++) html += rowHtml(older[b][0], older[b][1]);
      }}
      elBody.innerHTML = html;
      elCount.textContent = '共 ' + hs.length + ' 条归档观点 · 最早 ' + (hs[hs.length - 1][0] || '—') +
                            ' · 数据源：Eco 每日快照 + 历史回填';
    }}
    mask.classList.add('on');
    document.body.style.overflow = 'hidden';
  }}
  function close() {{
    mask.classList.remove('on');
    document.body.style.overflow = '';
  }}

  // 卡片点击 → 打开钻取层(事件委托, 兼容动态渲染)
  document.addEventListener('click', function(ev) {{
    var card = ev.target.closest ? ev.target.closest('.kol-drill') : null;
    if (card) {{
      var kol = card.getAttribute('data-kol');
      if (kol) {{ ev.preventDefault(); open(kol); }}
      return;
    }}
    // 第二层: 点某条记录 → 展开完整内容
    var row = ev.target.closest ? ev.target.closest('.kd-row') : null;
    if (row) {{
      row.classList.toggle('open');
      var c = row.querySelector('.kd-caret');
      if (c) c.textContent = row.classList.contains('open') ? '▾' : '▸';
      return;
    }}
    if (ev.target.closest && ev.target.closest('.kd-close')) {{ close(); return; }}
    // 点遮罩空白处关闭(点面板内部不关)
    if (ev.target === mask) close();
  }});
  // 键盘可达性: Enter/Space 打开, Esc 关闭
  document.addEventListener('keydown', function(ev) {{
    if (ev.key === 'Escape' && mask.classList.contains('on')) {{ close(); return; }}
    if ((ev.key === 'Enter' || ev.key === ' ') && document.activeElement &&
        document.activeElement.classList && document.activeElement.classList.contains('kol-drill')) {{
      ev.preventDefault();
      var k = document.activeElement.getAttribute('data-kol');
      if (k) open(k);
    }}
  }});
}})();
</script>
</body>
</html>"""
