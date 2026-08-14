"""dashboard.py — 生成莫兰迪配色的宏观风险扫描 dashboard (单文件 HTML)。

借鉴 KOL dashboard 的 format：卡片布局 + 红绿灯信号 + 雷达图分组 + 置顶信号 banner。
配色改为莫兰迪色系(低饱和、灰调、柔和)。
六部分报告：仪表盘表格 / 警报统计 / 逐条解读 / 短中长结论 / 卖出触发追踪 / 今日焦点。

雷达图：短/中/长三组指标归一化到 0-100 风险刻度(越大越危险)。
"""
import sys, os, json, datetime, html
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


# 每个指标"如何看"——交易员视角的一句话解读法
HOW_TO_READ = {
    "vix": "恐慌温度计。<13 市场自满(危险)，20-25 转紧张，>25 恐慌抛售。飙升=避险信号。",
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
    "ad_line": "市场广度。S&P 创新高但腾落线不创新高=顶背离(少数股撑指数，危险)。同步创新高=健康。",
    "buffett": "总市值/GDP。巴菲特最爱的估值尺。>150% 显著高估，>180% 极端泡沫区。",
    "cape": "10年周期市盈率。>30 历史高估，>35 逼近 2000/2021 泡沫峰值。均值回归压力大。",
    "yield_curve": "10Y-2Y 利差。倒挂(<0)历史预示衰退；由倒挂转正常是衰退临近的最后信号。",
    "lei": "领先经济指数。6个月变化率 <-4% 强烈预示衰退。领先实体经济约 7 个月。",
    "aaii_alloc": "家庭股票仓位。>70% 是历史仓位极值(2000年峰值区)，反向看空信号。",
    "sofr_iorb": "货币市场压力计。SOFR(隔夜回购利率)−IORB(准备金利率)。≤0 正常🟢；7–17bps 心绞痛🟡(准备金趋紧)；>17bps 心肌梗塞🔴(钱荒/回购危机,如2019年9月)。是美联储缩表触底、流动性拐点的最灵敏信号。",
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
             holdings=None, custody=None, auctions=None, money_supply=None, m2_history=None,
             country_ust=None, kol_views=None):
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
            spark = sparkline_svg(hist, ind.get("direction", "high_bad"))
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
        liquidity=_liquidity_html(liquidity),
        cb_balance=_cb_balance_html(cb_balance),
        money_supply=_money_supply_html(money_supply),
        m2_history=_m2_history_html(m2_history),
        custody=_custody_html(custody),
        country_ust=_country_ust_html(country_ust),
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
    if not modules or kol_changes.get("total", 0) == 0:
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
            cards += f"""<div class="kol-item">
              <div class="kol-line"><b>{_esc(ch['kol'])}</b> {_shift_badge(ch['prev_dir'], ch['new_dir'])} <span class="kol-date">{_esc(ch['date'])}</span></div>
              <div class="kol-shift"><span class="kdir kdir-{pc}">{_esc(ch['prev_dir'])}</span> → <span class="kdir kdir-{nc}">{_esc(ch['new_dir'])}</span></div>
              {extra}
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
            cards += f"""<div class="kol-item">
              <div class="kol-line"><b>{_esc(v['kol'])}</b> <span class="kv-badge {bcls}">{_esc(btxt)}</span> {since_html}</div>
              {extra}
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
        f'数据源：美国财政部 fiscaldata.treasury.gov（官方，每次拍卖后更新）。</div>'
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
        f'<div class="cust-meta">'
        f'{span_txt}'
        f'{total_rows}'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>外国央行/官方机构在纽约联储托管的美债存量。'
        f'持续下降 = 外国官方减持美债 / 去美元化 / 抛售换汇干预，是主权层面对美债信心的风向标。'
        f'<b>短期图</b>看近期拐点/干预动作，<b>长期图</b>看去美元化大趋势(10年结构性方向)。'
        f'数据源：FRED WMTSECL1（Fed H.4.1 custody，每周三口径）。</div>'
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
    return (
        f'<div class="cust-chart-col">'
        f'<div class="cust-chart-title">{c.get("flag","")} {_esc(c["name"])}持有美债（{len(series)}个月）</div>'
        f'<div class="cu-cur">${last_v:,.0f}<span class="cust-unit">B</span> '
        f'<span class="cust-wow cust-wow-{dcls}">{dtxt}</span> '
        f'<span class="cu-asof">as of {_esc(last_m)}</span></div>'
        f'{_country_ust_svg(series, color, fill)}'
        f'<div class="cust-chart-span">{_esc(c["first"][0])}→{_esc(last_m)}：'
        f'<b class="cust-{dcls}">{dbn:+.0f}B ({dpct:+.1f}%)</b>'
        f' · 高 ${c["high"]:,.0f}B / 低 ${c["low"]:,.0f}B</div>'
        f'</div>'
    )


def _country_ust_html(cu):
    """日本 / 中国 分国别持有美债近10年折线(左右两图)。cu: fetch_country_ust_holdings()。"""
    if not cu or (cu.get("Japan", {}).get("status") != "ok" and cu.get("China", {}).get("status") != "ok"):
        return '<p class="empty">日本 / 中国 持有美债数据未就绪。</p>'
    src = (cu.get("Japan") or cu.get("China") or {}).get("source", "US Treasury TIC")
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-charts">'
        f'{_country_ust_col(cu.get("Japan"))}'
        f'{_country_ust_col(cu.get("China"))}'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b>美国财政部 TIC 口径下各国持有的美债总额（含官方+私人，月度）。'
        f'与上方"外国官方托管美债"口径不同：托管是纽约联储账户的外国<b>官方合计</b>，这里是<b>分国别</b>总持仓。'
        f'<b>日本</b>是美债最大持有国，近10年高位震荡；<b>中国</b>近10年持续系统性减持，是去美元化/中美博弈的结构性信号。'
        f'数据源：{_esc(src)}。</div>'
        f'</div>'
    )


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
        src = _esc(str(d.get("source", "")))
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
            f'<div class="ms-src">源：{_esc(str(b.get("source","")))}</div>'
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
  /* KOL 状态变化模块化(仿13F) */
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
  .mc-slabel {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px; margin-left: 4px; }}
  .mc-slabel-g {{ color: #3f5a3f; background: rgba(154,171,151,.30); }}
  .mc-slabel-y {{ color: #8a6a2a; background: rgba(212,178,110,.32); }}
  .mc-slabel-r {{ color: #fff; background: var(--clay); }}
  /* 外国官方托管美债卡片 */
  .cust-wrap {{ display: flex; flex-direction: column; gap: 10px; }}
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
  @media (max-width: 720px) {{ .cust-charts {{ grid-template-columns: 1fr; }} }}
  .cust-chart-col {{ background: var(--card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 8px; }}
  .cust-chart-span {{ font-size: 10px; color: var(--muted); margin-top: 4px; text-align: center; }}
  .cust-chart-title {{ font-size: 11px; color: var(--muted); font-weight: 600; margin-bottom: 4px; font-family: var(--mono); }}
  .cust-chart {{ width: 100%; height: auto; display: block; }}
  .cust-chart-na {{ font-size: 12px; color: var(--muted); padding: 20px; text-align: center; }}
  .cc-grid {{ stroke: rgba(160,160,150,.20); stroke-width: 1; stroke-dasharray: 3 3; }}
  .cc-ylab {{ fill: var(--muted); font-size: 9px; font-family: var(--mono); text-anchor: end; }}
  .cc-xlab {{ fill: var(--muted); font-size: 9px; font-family: var(--mono); }}
  /* 分国别持有美债(TIC) 列头当前值 */
  .cu-cur {{ font-family: var(--mono); font-size: 20px; font-weight: 800; color: var(--text); line-height: 1.2; margin: 2px 0 6px; }}
  .cu-asof {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 6px; }}

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
  <div class="part-title"><span class="part-num">1</span>指标卡片 · 18 项（短 → 中 → 长）</div>
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

  <!-- ═══ 附一·零：本周 KOL 观点全景(按模块+多空, Eco 独立每日快照) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>本周 KOL 观点全景 · 按模块 (多空方向卡片)</div>
  <div class="card">{kol_views}</div>

  <!-- ═══ 附一：本周 KOL 状态变化(模块化, Eco 独立每日快照周对比) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>本周 KOL 状态变化 · 按模块 (态度转向 call-out)</div>
  <div class="card">{kol_changes}</div>

  <!-- ═══ 附二：流动性要点(联动 Economic Dashboard) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>流动性要点 · 央行/国债</div>
  <div class="card liq-wrap">{liquidity}</div>

  <!-- ═══ 附三：四大央行资产负债表 (US/JP/CN/ECB, 2x2) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>四大央行资产负债表 · 每日更新 (US/JP/CN/ECB · 2x2 · 当天汇率统一折$B)</div>
  <div class="bs-grid">{cb_balance}</div>

  <!-- ═══ 附三·二：三国货币供应量 M0/M1/M2 (央行资负表的延伸: 从"央行造多少底钱"到"社会流通多少钱") ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国货币供应量 M0 / M1 / M2 · 月度 (央行资负表下延: 社会实际流通的钱)</div>
  <div class="card">{money_supply}</div>

  <!-- ═══ 附三·二·二：三国 M2 十年历史折线 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国 M2 十年走势 · 折线 ($B 当天汇率统一折算 · 放水力度长期对比)</div>
  <div class="card">{m2_history}</div>

  <!-- ═══ 附三·三：美国国债拍卖 timeline ═══ -->
  <div class="part-title"><span class="part-num">＋</span>美国国债拍卖 · 财政部 (最新+过去3次 · 规模/中标率/收益率/间接投标 · 下次日程)</div>
  <div class="card">{auctions}</div>

  <!-- ═══ 附三·五：外国官方在纽约联储托管的美债 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>外国官方托管美债 · 纽约联储 (去美元化风向标)</div>
  <div class="card">{custody}</div>

  <!-- ═══ 附三·六：日本 / 中国 分国别持有美债 (TIC, 近10年) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>日本 / 中国 持有美债 · 近10年 (TIC 分国别口径)</div>
  <div class="card">{country_ust}</div>

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
