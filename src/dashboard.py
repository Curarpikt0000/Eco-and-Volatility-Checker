"""dashboard.py — 生成莫兰迪配色的宏观风险扫描 dashboard (单文件 HTML)。

借鉴 KOL dashboard 的 format：卡片布局 + 红绿灯信号 + 雷达图分组 + 置顶信号 banner。
配色改为莫兰迪色系(低饱和、灰调、柔和)。
六部分报告：仪表盘表格 / 警报统计 / 逐条解读 / 短中长结论 / 卖出触发追踪 / 今日焦点。

雷达图：短/中/长三组指标归一化到 0-100 风险刻度(越大越危险)。
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
import config as c
import signals

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")
os.makedirs(OUT_DIR, exist_ok=True)


# 每个指标"如何看"——交易员视角的一句话解读法
HOW_TO_READ = {
    "vix": "恐慌温度计。<13 市场自满(危险)，20-25 转紧张，>25 恐慌抛售。飙升=避险信号。",
    "fear_greed": "情绪钟摆。>75 极度贪婪(该减)，<25 极度恐惧(可贪)。从高位回落是顶部确认。",
    "aaii_bull_bear": "散户情绪。多空差 >30% = 散户太乐观(反向看空)，<-30% = 过度悲观(反向看多)。",
    "put_call": "对冲需求。越低=越少人买保险=越自满。<0.45 极度乐观(危险)，高=恐慌(可能见底)。",
    "naaim": "主动经理仓位。>100% 加杠杆满仓(过热)，<20% 空仓避险。极值是反向信号。",
    "margin_debt": "借钱炒股总量。持续攀升=杠杆堆积；连续 3 月下降=去杠杆开始(历史顶部信号)。",
    "margin_gdp": "杠杆占经济比重。>3% 历史偏高，>3.5% 极端。回落往往伴随市场调整。",
    "ipo_count": "发行热度。IPO 井喷=市场情绪顶部特征(供给放量套现)。骤降=风险偏好收缩。",
    "insider": "内部人用脚投票。<0.17 内部人只卖不买(看空)，>1 大举买入(看多)。最聪明的钱。",
    "bofa_bull_bear": "华尔街情绪综合指标。>8 极度贪婪(卖出信号)，<2 极度恐慌(买入信号)。",
    "hy_oas": "信用市场压力。利差扩张=风险偏好收缩、违约担忧上升。>4.5% 信用警报。",
    "ad_line": "市场广度。S&P 创新高但腾落线不创新高=顶背离(少数股撑指数，危险)。同步创新高=健康。",
    "buffett": "总市值/GDP。巴菲特最爱的估值尺。>150% 显著高估，>180% 极端泡沫区。",
    "cape": "10年周期市盈率。>30 历史高估，>35 逼近 2000/2021 泡沫峰值。均值回归压力大。",
    "yield_curve": "10Y-2Y 利差。倒挂(<0)历史预示衰退；由倒挂转正常是衰退临近的最后信号。",
    "lei": "领先经济指数。6个月变化率 <-4% 强烈预示衰退。领先实体经济约 7 个月。",
    "aaii_alloc": "家庭股票仓位。>70% 是历史仓位极值(2000年峰值区)，反向看空信号。",
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


def sparkline_svg(points, direction="high_bad", w=140, h=36):
    """生成 mini 折线 SVG。points: [(date,val),...]。莫兰迪色。"""
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
    return (f'<svg viewBox="0 0 {w} {h}" class="spark" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
            f'<circle cx="{dot_x}" cy="{dot_y}" r="2.8" fill="{color}"/></svg>')


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
             holdings=None):
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
    kol_changes = kol_changes or []
    liquidity = liquidity or {}
    cb_balance = cb_balance or {}
    holdings = holdings or {}
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
            hist = load_history(SNAP_DIR, key, days=14)
            spark = sparkline_svg(hist, ind.get("direction", "high_bad"))
            arrow, acls = trend_arrow(hist, ind.get("direction", "high_bad"))
            st = r.get("status", "")
            st_badge = "" if st == "ok" else f'<span class="stwarn">{st}</span>'
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
              <div class="mc-val">{fmt_val(ind, r)} {chg}{st_badge}</div>
              <div class="mc-thr">{threshold_text(ind)}</div>
              <div class="mc-spark">{spark}<span class="mc-spark-lbl">近2周</span></div>
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
        liquidity=_liquidity_html(liquidity),
        cb_balance=_cb_balance_html(cb_balance),
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


def _kol_changes_html(kol_changes):
    """底部 KOL 状态变化板块。"""
    if not kol_changes:
        return '<p class="empty">近日无 KOL 主导方向变化。</p>'
    dir_cls = {"强烈看多": "r", "看多": "y", "分歧": "n", "中性": "n", "看空": "g", "强烈看空": "g"}
    rows = ""
    for ch in kol_changes[:12]:
        pc = dir_cls.get(ch["prev_dir"], "n")
        nc = dir_cls.get(ch["new_dir"], "n")
        comment = (ch.get("comments") or "").strip()
        targets = (ch.get("targets") or "").strip()
        extra = ""
        if comment:
            extra += f'<div class="kol-cmt">{comment}</div>'
        if targets:
            extra += f'<div class="kol-tgt">标的：{targets}</div>'
        rows += f"""<div class="kol-item">
          <div class="kol-line"><b>{ch['kol']}</b> <span class="kol-sec">{ch['sector']}</span> <span class="kol-date">{ch['date']}</span></div>
          <div class="kol-shift"><span class="kdir kdir-{pc}">{ch['prev_dir']}</span> → <span class="kdir kdir-{nc}">{ch['new_dir']}</span></div>
          {extra}
        </div>"""
    return rows


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
        ls = " · ".join(f'{k}: {v}' for k, v in lights.items() if k not in ("运行状态",))
        parts.append(f'<div class="liq-row liq-lights">{ls}</div>')
    # 关键变动文本
    notes = liq.get("risk_notes", {})
    if notes.get("关键变动"):
        parts.append(f'<div class="liq-note"><b>关键变动</b><br>{notes["关键变动"].replace(chr(10), "<br>")}</div>')
    if notes.get("AI短评"):
        parts.append(f'<div class="liq-note"><b>AI 短评</b><br>{notes["AI短评"]}</div>')
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


def _cb_one_view(d):
    """单个央行资产负债表 view：左资产右负债 + 总资产 + WoW/环比。"""
    if not d or (not d.get("assets") and not d.get("liabilities")):
        return (f'<div class="bs-card"><div class="bs-head">{d.get("flag","")} '
                f'{d.get("name","")}</div><p class="empty">数据未找到</p></div>')
    up = d.get("period", "")  # WoW / 较上期 / MoM

    def side(items):
        rows = ""
        for it in items:
            rows += (f'<div class="bs-line"><span class="bs-name">{it["name"]}</span>'
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
    return (
        f'<div class="bs-card">'
        f'<div class="bs-head">{d.get("flag","")} {d.get("name","")}'
        f'<span class="bs-meta">{d.get("date","")} · 单位 {d.get("unit","")} · 环比口径 {up}</span></div>'
        f'<div class="bs-body">'
        f'<div class="bs-col bs-assets"><div class="bs-col-h">资产 (Assets)</div>{side(d.get("assets",[]))}{total_a_html}</div>'
        f'<div class="bs-col bs-liabs"><div class="bs-col-h">负债 (Liabilities)</div>{side(d.get("liabilities",[]))}{total_l_html}</div>'
        f'</div></div>'
    )


def _cb_balance_html(cb):
    """底部三国央行资产负债表板块(JP/CN/US)。"""
    if not cb:
        return '<p class="empty">央行资产负债表数据未就绪。</p>'
    order = ["US", "JP", "CN"]
    cards = "".join(_cb_one_view(cb.get(cc, {})) for cc in order if cc in cb)
    return cards or '<p class="empty">央行资产负债表数据未就绪。</p>'


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
    """单个机构持仓卡片: 头部(KOL/基金/报告期/总市值) + TOP持仓+变动 + 新建/清仓。"""
    if r.get("status") != "ok":
        return (f'<div class="h-card"><div class="h-head">{r.get("fund","?")} '
                f'<span class="h-kol">{r.get("kol","")}</span></div>'
                f'<p class="empty">{r.get("status","数据未找到")}</p></div>')
    tv = r.get("total_value", 0) / 1e9
    lines = ""
    for h in r.get("top_holdings", [])[:10]:
        pct = f' <span class="h-pct">{h["pct"]:+.0f}%</span>' if h.get("pct") is not None else ""
        val = f'${h["value"]/1e6:,.0f}M' if h.get("value") else "—"
        lines += (f'<div class="h-line"><span class="h-act {_action_cls(h["action"])}">{h["action"]}</span>'
                  f'<span class="h-iss">{h["issuer"]}</span>'
                  f'<span class="h-val">{val}{pct}</span></div>')
    newb = "、".join(x["issuer"] for x in r.get("new_buys", [])[:5])
    exits = "、".join(x["issuer"] for x in r.get("exits", [])[:5])
    extra = ""
    if newb:
        extra += f'<div class="h-extra"><b class="h-new">🆕新建</b> {newb}</div>'
    if exits:
        extra += f'<div class="h-extra"><b class="h-exit">❌清仓</b> {exits}</div>'
    return (
        f'<div class="h-card">'
        f'<div class="h-head">{r.get("fund","")}<span class="h-kol">{r.get("kol","")}</span>'
        f'<span class="h-meta">13F {r.get("report_date","")} · ${tv:,.1f}B · {r.get("n_positions",0)}持仓 · vs {r.get("prev_report_date","-")}</span></div>'
        f'<div class="h-body">{lines}</div>{extra}</div>'
    )


def _holdings_trump(inst):
    """Trump 卡片(数据来自公开披露, 由 cron agent 填 holdings 里 kol=Trump 的项)。"""
    lines = ""
    for h in inst.get("top_holdings", [])[:10]:
        act = h.get("action", "")
        lines += (f'<div class="h-line"><span class="h-act {_action_cls(act)}">{act or "持有"}</span>'
                  f'<span class="h-iss">{h.get("issuer","")}</span>'
                  f'<span class="h-val">{h.get("note","")}</span></div>')
    src = inst.get("source_note", "公开财务披露(PFD)")
    return (
        f'<div class="h-card h-trump">'
        f'<div class="h-head">🇺🇸 Donald Trump<span class="h-kol">公开披露</span>'
        f'<span class="h-meta">{inst.get("report_date","")} · 来源: {src}</span></div>'
        f'<div class="h-body">{lines or "<p class=empty>暂无最新披露数据</p>"}</div></div>'
    )


def _holdings_html(hd):
    """底部机构持仓(13F)+Trump 板块。"""
    insts = hd.get("institutions", []) if hd else []
    if not insts:
        return '<p class="empty">机构持仓数据未就绪(季度 13F 披露后更新)。</p>'
    cards = ""
    for r in insts:
        if str(r.get("kol", "")).lower().startswith("trump") or r.get("source") == "PFD":
            cards += _holdings_trump(r)
        else:
            cards += _holdings_one(r)
    meta = f'<div class="h-note">数据源：SEC EDGAR 官方 13F（季度披露，季末后约45天更新）+ Trump 公开财务披露。变动＝最新一期 vs 上一期持股数：🆕新建 ▲加仓 ▼减仓 ❌清仓 →持平。</div>'
    return cards + meta


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
    buf, cape, yc = gv("buffett"), gv("cape"), gv("yield_curve")
    long_parts = []
    if buf is not None and buf > 180:
        long_parts.append(f"巴菲特指标 {buf}% 处极端泡沫区")
    if cape is not None and cape > 35:
        long_parts.append(f"CAPE {cape} 接近历史泡沫峰值")
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
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; min-height: 100vh; line-height: 1.5; }}
  header {{ background: var(--card); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
  header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: .3px; }}
  header h1 span {{ color: var(--dust-blue); }}
  #update-time {{ font-size: 12px; color: var(--muted); }}
  .container {{ max-width: 1280px; margin: 0 auto; padding: 22px 28px 60px; }}
  .section-title {{ font-size: 13px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin: 26px 0 12px; }}
  /* 编号章节标题(6部分) */
  .part-title {{ display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 800; color: var(--text); margin: 30px 0 14px; padding-bottom: 8px; border-bottom: 2px solid var(--border); }}
  .part-num {{ display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; background: var(--dust-blue); color: #fff; font-size: 14px; font-weight: 800; flex-shrink: 0; }}
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
  /* 流动性板块 */
  .liq-row {{ font-size: 13px; margin-bottom: 8px; line-height: 1.7; }}
  .liq-k {{ color: var(--muted); }}
  .liq-lights {{ background: var(--card2); border-radius: 6px; padding: 6px 10px; }}
  .liq-note {{ font-size: 12px; color: var(--text); line-height: 1.7; background: var(--card2); border-radius: 8px; padding: 10px 12px; margin-top: 8px; }}
  .liq-note b {{ color: var(--dust-blue); }}
  .empty {{ color: var(--muted); font-size: 13px; font-style: italic; }}
  /* 三大央行资产负债表 view */
  .bs-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 14px; margin-bottom: 8px; }}
  .bs-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
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
  .h-iss {{ color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .h-val {{ font-family: var(--mono); font-weight: 700; color: var(--text); white-space: nowrap; }}
  .h-pct {{ color: var(--muted); font-weight: 500; }}
  .h-extra {{ font-size: 11px; color: var(--text); margin-top: 6px; line-height: 1.5; }}
  .h-note {{ grid-column: 1/-1; font-size: 11px; color: var(--muted); margin-top: 4px; line-height: 1.6; }}
  .dot-g {{ background: var(--sage); }}
  .dot-y {{ background: var(--mustard); }}
  .dot-r {{ background: var(--clay); }}
  .dot-n {{ background: var(--muted); opacity: .4; }}
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
  /* 红绿灯彩色圆点(无 emoji 字体也能靠颜色区分) */
  .dot {{ display: inline-block; width: 13px; height: 13px; border-radius: 50%; vertical-align: middle; }}
  .dot-g {{ background: var(--sage); box-shadow: 0 0 0 3px var(--sage-bg); }}
  .dot-y {{ background: var(--mustard); box-shadow: 0 0 0 3px var(--mustard-bg); }}
  .dot-r {{ background: var(--clay); box-shadow: 0 0 0 3px var(--clay-bg); }}
  .dot-n {{ background: var(--muted); opacity: .4; }}
  .stwarn {{ font-size: 10px; color: var(--clay); background: var(--clay-bg); padding: 1px 5px; border-radius: 4px; }}

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
</style>
</head>
<body>
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
  <div class="part-title"><span class="part-num">1</span>指标卡片 · 17 项（短 → 中 → 长）</div>
  <div class="grp-label grp-short">🟢 短期指标 · 天-周 · 判断过热回调</div>
  <div class="mcard-grid">{cards_short}</div>
  <div class="grp-label grp-mid">🟡 中期指标 · 周-月 · 判断趋势转折</div>
  <div class="mcard-grid">{cards_mid}</div>
  <div class="grp-label grp-long">🔴 长期指标 · 月-年 · 判断结构性周期顶</div>
  <div class="mcard-grid">{cards_long}</div>

  <!-- ═══ 第二部分：警报统计速览 + 雷达图 ═══ -->
  <div class="part-title"><span class="part-num">2</span>警报统计速览</div>
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
  <div class="part-title"><span class="part-num">3</span>逐条简短解读</div>
  <div class="card">{interp}</div>

  <!-- ═══ 第四部分：短中长期综合结论 ═══ -->
  <div class="part-title"><span class="part-num">4</span>短中长期综合结论</div>
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
  <div class="part-title"><span class="part-num">5</span>卖出触发状态追踪（同时 ≥3 项 = 开始分批卖出）</div>
  <div class="card">
    <table class="trig">
      <thead><tr><th>触发条件</th><th>阈值</th><th>今日状态</th><th>达成</th></tr></thead>
      <tbody>{trigger_rows}</tbody>
    </table>
  </div>

  <!-- ═══ 第六部分：今日最需关注的一条信号 ═══ -->
  <div class="part-title"><span class="part-num">6</span>今日最需关注的一条信号</div>
  <div class="focus-box">{focus}</div>

  <!-- ═══ 附一：当日 KOL 状态变化(联动 KOL 追踪) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>当日 KOL 状态变化</div>
  <div class="card kol-wrap">{kol_changes}</div>

  <!-- ═══ 附二：流动性要点(联动 Economic Dashboard) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>流动性要点 · 央行/国债</div>
  <div class="card liq-wrap">{liquidity}</div>

  <!-- ═══ 附三：三大央行资产负债表 (JP/CN/US) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三大央行资产负债表 · 每日更新 (左资产 / 右负债 · 带环比)</div>
  <div class="bs-grid">{cb_balance}</div>

  <!-- ═══ 附四：知名机构持仓 (13F) + Trump ═══ -->
  <div class="part-title"><span class="part-num">＋</span>机构持仓追踪 · 13F + Trump (对比上期变动)</div>
  <div class="h-grid">{holdings}</div>

  <div class="footnote">
    数据源：FRED (VIX/HY/收益率曲线) · CNN F&amp;G · CBOE · AAII · GuruFocus · Conference Board · Renaissance · currentmarketvaluation · multpl · CFTC COT (金银 commercial)。<br>
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
</script>
</body>
</html>"""
