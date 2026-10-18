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


def _strip_md(s):
    """剥掉 Markdown 粗体标记, 只留文字 —— 用于**进 JSON payload** 的文本。

    ★为什么 payload 不能用 _esc_md(2026-09-21): payload 由 json.dumps 序列化后
      内嵌进 <script>, 前端用 textContent / 拼字符串渲染。往里塞 <b> 要么被当
      纯文本原样显示(比 ** 更难看), 要么就得让前端 innerHTML —— 那是 XSS 面。
      所以 payload 侧的正确做法是**剥掉标记**, 只有直接产出 HTML 的地方才转 <b>。
    """
    if s is None:
        return ""
    return re.sub(r"\*\*([^*\n]{1,120}?)\*\*", r"\1", str(s))


def _esc_md(s):
    """先 HTML 转义, 再把 Markdown 的 **粗体** 渲染成 <b>。

    ★为什么需要(2026-09-21): 数据文件(如 data/kol_profiles.json 的人物档案)里
      写的是 Markdown 语法, 但 HTML 不认 ** —— 直接 _esc() 输出会让读者在页面上
      看到一堆字面星号 `**BG2Pod**`。实测产物里有 13 处。
    ★为什么在渲染层做而不是改数据: kol_registry / kol_profiles 属 Notion 侧 SSOT
      的单向镜像, 本 agent 不得自行改动(见 AGENTS.md 名册铁律)。
    ★顺序不能反: 必须**先转义后替换**, 否则先插入的 <b> 会被转义成 &lt;b&gt;。
      转义后原文里的真 `<` 已变 &lt;, 此时再插 <b> 是安全的, 不构成注入面。
    """
    if s is None:
        return ""
    t = html.escape(str(s), quote=True)
    return re.sub(r"\*\*([^*\n]{1,120}?)\*\*", r"<b>\1</b>", t)


# ── 数据新鲜度徽章 ────────────────────────────────────────────
# ★铁律配套设施: 低频源(季度/月度)天然滞后, 但页头写"每日更新"会让读者误以为
#   每个数字都是今天的。此处按各源的【自然更新频率】给出容忍阈值, 超阈值才标徽章:
#     绿(不显示) = 正常;  🟡 滞后N天 = 超过 1x 周期;  🔴 疑似断源 = 超过 2x 周期。
#   徽章只描述"数据有多旧", 绝不修改/伪造数据本身。
_FRESH_TOL = {
    "daily": 5,        # 日频(含周末+假日缓冲)
    # ★2026-10-06: FRED 日度序列(VIX/HY/DPRIME/SOFR/EFFR)官方 T+1~T+2 发布, 实测 10-06 上午 FRED 最新就是 10-02,
    #   故这几项容忍 7 天(含周末), 不当「滞后」误报; 其余 daily=5 不变。
    "daily_fred": 7,
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
        # ★2026-08-21 更正: 此处原注释断言"TIC 官方本身未出新月, 抓取链路完好" —— <b>是错的</b>。
        #   实测 mfhhis01.txt 只是<b>历史存档表</b>(内容止于上一年年末), 当年月度在 slt_table5,
        #   官方 2026-08-17 已发 2026-06。教训: 红标超阈值时<b>先去官网核实最新一期</b>,
        #   绝不假设"源就是这么慢"(详见 ChaoWiki frontend/data-dashboard-publishing §8.1)。
        if known_reason:
            txt += "（原因见下方说明）"
        else:
            txt += "（远超常规更新周期，请核对官方是否已发布新值）"
    if label:
        txt = f"{label} {txt}"
    return f'<span class="stale-badge sb-{sev}" title="最新数据日期 {_esc(s)}，距今 {days} 天；该源自然更新频率={freq}">{txt}</span>'


def _srcslow_badge(as_of, cadence, verified_on, src_note, extra=""):
    """★2026-10-07 (Chao「怎么还是上周的数据」): 低频源「官方最新就是这一期」时, 不能用 🟡「数据滞后」吓人。
    只用于【已回官方接口核实过「官方没有更新的一期」】的板块, 调用方必须填 verified_on(核实日) 与 src_note(怎么核的)。
    灰色 ⏳ 只陈述事实: 最新是哪天、该源多久一更。没核实过的板块一律继续用 _stale_badge, 不得套用本函数。"""
    if not as_of:
        return ""
    return (f'<span class="stale-badge sb-slow" title="{_esc(src_note)}（核实于 {_esc(verified_on)}）">'
            f'⏳ 源头{_esc(cadence)}更新 · 最新 {_esc(str(as_of)[:10])} 已是官方最新{(" · " + _esc(extra)) if extra else ""}</span>')


# ★2026-10-06 指标卡新鲜度(Chao 报「今天数据健康度差」后的修复; Opus 5.5 评审 + 本地实测)。
#   每个指标的自然更新频率。依据: FRED 日度序列 T+1~T+2(实测 10-06 上午最新=10-02);
#   AAII 资产配置=月度调查; FINRA/LEI=月度; BofA FMS=月度; BofA Bull&Bear=周度; Z.1 巴菲特=季度;
#   IPO/insider/put_call/CNN/CAPE/腾落线=日度。
_IND_FREQ = {
    "vix": "daily_fred", "hy_oas": "daily_fred", "margin_cost": "daily_fred",
    "sofr_iorb": "daily_fred", "bank_funding_stress": "daily_fred", "yield_curve": "daily_fred",
    "fear_greed": "daily", "put_call": "daily", "cape": "daily", "ad_line": "daily", "insider": "daily",
    "ipo_count": "daily",
    "aaii_bull_bear": "weekly", "bofa_bull_bear": "weekly",
    "margin_debt": "monthly", "lei": "monthly", "bofa_fms_cash": "monthly", "aaii_alloc": "monthly",
    "margin_gdp": "quarterly", "buffett": "quarterly",
}


def _ind_fresh_badge(key, r):
    """指标卡的新鲜度徽章。只描述「数据有多旧」, 不修改任何数值/信号灯。
    - as_of 缺失(源站不给日期且代码取不到)→ 灰色「日期未知」, 不得显示为正常;
    - 滞后超过该指标自然频率的容忍天数 → 复用 _stale_badge 的 🟡/🔴;
    - 新鲜 → 空串(不干扰版面)。"""
    if r.get("value") is None:
        return ""
    a = r.get("as_of")
    if not a:
        return '<span class="stale-badge sb-gray" title="该指标的数据源页面没有可解析的日期, 无法判断是不是最新">⚪ 日期未知</span>'
    freq = _IND_FREQ.get(key, "daily")
    # FRED 的月度/季度序列用「期初日」(如 2026-08-01 = 8 月整月; 2026-04-01 = Q1)标日期, 实际数据覆盖整个周期。
    # 滞后要从「周期末」起算, 否则必然误报(2026-10-06 实测 LEI 8/01 被报 66 天, 实际 8 月才刚结束 36 天)。
    a = str(a)[:10]
    if freq in ("monthly", "quarterly") and len(a) == 10 and a.endswith("-01"):
        try:
            y, m = int(a[:4]), int(a[5:7])
            span = 1 if freq == "monthly" else 3
            em = m + span
            ey = y + (em - 1) // 12
            em = (em - 1) % 12 + 1
            a = (datetime.date(ey, em, 1) - datetime.timedelta(days=1)).isoformat()
        except Exception:
            pass
    return _stale_badge(a, freq)


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
    "sofr_iorb": "货币市场压力计。<b>SOFR=Secured Overnight Financing Rate(担保隔夜融资利率，有国债抵押)</b>−<b>EFFR=Effective Federal Funds Rate(联邦基金有效利率，银行间无抵押拆借的市场成交加权中位价)</b>。有抵押本该比无抵押便宜，故常态下该差为负或贴零；转正并走阔＝<b>押着最安全的抵押品借钱反而比无抵押还贵</b>，说明回购市场资金供给出问题。≤5bps 正常🟢；5–18bps 心绞痛🟡(回购趋紧)；>18bps 心肌梗塞🔴(钱荒)。阈值按 2018-04 至今 2,112 个交易日分位校准(P90/P99)，2019年9月回购危机时该利差曾冲到 +295bps。<b>★2026-09-18 由 SOFR−IORB 改为本口径</b>：IORB 是美联储行政设定的走廊上沿、阶梯状不动，EFFR 是每日市场成交价，对回购压力更灵敏；两口径中枢差约 5bp，跨该日的历史值不可直接比较。",
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


def _hover_bands(xs, tips, top, height, x_min=None, x_max=None):
    """★2026-09-25(Chao「所有图鼠标凑上去至少显示横纵坐标」复查补漏):
    通用 hover 命中带 —— 每个数据点一条透明全高竖条(左右边界=与相邻点的中点),
    复用全站 data-tip 事件委托。多线图一次悬停可同时显示该日所有序列数值。
    xs: 升序像素横坐标; tips: 已 _esc 的 "横坐标||纵坐标(可含<br>)"。
    必须拼在 SVG 最后(最上层)才能接住鼠标。"""
    n = len(xs)
    if n == 0:
        return ""
    out = []
    for i, x in enumerate(xs):
        l = (xs[i - 1] + x) / 2 if i > 0 else (x_min if x_min is not None else x - 3)
        r = (x + xs[i + 1]) / 2 if i < n - 1 else (x_max if x_max is not None else x + 3)
        out.append(f'<rect x="{l:.1f}" y="{top:.1f}" width="{max(r - l, 0.6):.2f}" '
                   f'height="{height:.1f}" fill="transparent" data-tip="{tips[i]}"/>')
    return "".join(out)


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



def _liquidity_crisis_html(lq):
    """每日流动性危机监测盘: SOFR−EFFR(资金面) + BBB/HY OAS(信用面) + 闪崩日标注。

    ★2026-09-18 新增。Chao: 「我需要这两个来观察每天的流动性危机」。
      资金面与信用面<b>同时</b>恶化才是真危机; 只有一边动 = 局部事件。
    ★Oracle 单名 CDS 是付费数据拿不到 —— 用同评级 BBB 档 OAS 替代,
      并叠 HY 作降级风险参照(Oracle 现 S&P BBB−, 距垃圾级一档)。
    """
    if not lq or lq.get("status") != "ok":
        return ('<section class="sec"><h2>每日流动性危机监测</h2>'
                '<div class="muted">数据未就绪</div></section>')

    ser = lq.get("series") or {}
    sofr = (ser.get("sofr_effr") or {}).get("data") or []
    bbb = (ser.get("bbb_oas") or {}).get("data") or []
    hy = (ser.get("hy_oas") or {}).get("data") or []
    ig = (ser.get("ig_oas") or {}).get("data") or []
    crash_days = lq.get("crash_days") or []
    if not sofr or not bbb:
        return ('<section class="sec"><h2>每日流动性危机监测</h2>'
                '<div class="muted">数据不足</div></section>')

    # ════════════════════════════════════════════════════════════════
    # ★2026-09-25 重做(Chao 四点):
    #   1 鼠标悬停要看到「这天发生了什么」 → 事件说明来自 data/liquidity_crisis_events.json
    #     (每条带真实出处, 子 agent web_extract 核实) + 美元/黄金事件库 dxy_gold_events.json
    #   2 BBB 曲线过分平滑 → 原来 BBB(0.9~1.5%) 与 HY(2.6~4.6%) 共用一根右轴, BBB 被压成一条线。
    #     改为上下两栏: 上栏 资金面 SOFR−EFFR + 黄金价格; 下栏 信用面, BBB 独占左轴(自适应放大),
    #     HY 在右轴 —— BBB 的每一次抬升都看得见
    #   3 黄金曲线加进图(原需求「闪崩时点」本来就含金银, 只有竖线没价格)
    #   4 鼠标放任一曲线任一点 → 显示该点横坐标(日期)+纵坐标(各线数值)
    #     实现: 每个交易日一条透明全高竖条(data-tip), 复用全站 data-tip 事件委托
    # ════════════════════════════════════════════════════════════════
    import datetime as _dt
    gold = (ser.get("gold") or {}).get("data") or []
    W = 1180
    PL, PR = 64, 70
    iw = W - PL - PR
    H1, H2, GAP, PT, PB = 250, 190, 30, 24, 44
    top1, top2 = PT, PT + H1 + GAP
    H = top2 + H2 + PB

    alld = sorted({d for d, _ in sofr} | {d for d, _ in bbb} | {d for d, _ in gold})
    d0, d1 = alld[0], alld[-1]
    t0 = _dt.date.fromisoformat(d0).toordinal()
    span = max(1, _dt.date.fromisoformat(d1).toordinal() - t0)

    def X(d):
        return PL + iw * (_dt.date.fromisoformat(d).toordinal() - t0) / span

    def _rng(vals, pad_frac=0.10, floor_pad=0.0):
        lo, hi = min(vals), max(vals)
        pad = max(floor_pad, (hi - lo) * pad_frac)
        return lo - pad, hi + pad

    s_lo, s_hi = _rng([v for _, v in sofr], 0.10, 2.0)
    g_lo, g_hi = _rng([v for _, v in gold], 0.06, 1.0) if gold else (0, 1)
    b_lo, b_hi = _rng([v for _, v in bbb], 0.10, 0.02)
    h_lo, h_hi = _rng([v for _, v in hy], 0.08, 0.05) if hy else (0, 1)

    def Y(v, lo, hi, top, h):
        return top + h * (1 - (v - lo) / ((hi - lo) or 1))

    def path(pts, lo, hi, top, h):
        return ("M" + " L".join(f"{X(d):.1f},{Y(v, lo, hi, top, h):.1f}" for d, v in pts)) if pts else ""

    # ── 事件库: 本图专属(闪崩/资金面尖峰/信用峰值) + 美元黄金事件库 ──
    import json as _json, os as _os
    ev = {}
    _base = _os.path.join(_os.path.dirname(__file__), "..", "data")
    for fn in ("dxy_gold_events.json", "liquidity_crisis_events.json"):   # 后者优先覆盖
        try:
            for e in _json.load(open(_os.path.join(_base, fn), encoding="utf-8")).get("events", []):
                if e.get("date") and e.get("event") and e.get("event") != "原因未查实":
                    ev.setdefault(e["date"], []).append(e)
        except Exception as _e:
            print(f"[dashboard] 流动性危机 事件库 {fn} 读取失败 {type(_e).__name__}: {_e}")
    crash_map = {c["d"]: c for c in crash_days}

    sm, bm, hm, gm = dict(sofr), dict(bbb), dict(hy), dict(gold)
    p = [f'<svg viewBox="0 0 {W} {H}" class="lqc-chart" preserveAspectRatio="xMidYMid meet" '
         f'font-family="-apple-system,PingFang SC,Helvetica,sans-serif">']

    def grid(top, h, lo_l, hi_l, lo_r, hi_r, fl, fr):
        for i in range(5):
            y = top + h * i / 4
            p.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{PL+iw}" y2="{y:.1f}" '
                     f'stroke="#d8d2c6" stroke-width="0.6" stroke-dasharray="2,3"/>')
            p.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" font-size="10.5" fill="#8a8070" '
                     f'text-anchor="end">{fl(hi_l - (hi_l-lo_l)*i/4)}</text>')
            p.append(f'<text x="{PL+iw+8}" y="{y+3.5:.1f}" font-size="10.5" fill="#8a8070" '
                     f'text-anchor="start">{fr(hi_r - (hi_r-lo_r)*i/4)}</text>')

    # ── 上栏: SOFR−EFFR(左 bp) + 黄金(右 $/oz) ──
    grid(top1, H1, s_lo, s_hi, g_lo, g_hi, lambda v: f"{v:.0f}", lambda v: f"{v:,.0f}")
    for thr, col, lab in ((5, "#c9a227", "警戒 +5bp"), (18, "#b5533c", "危机 +18bp")):
        if s_lo <= thr <= s_hi:
            y = Y(thr, s_lo, s_hi, top1, H1)
            p.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{PL+iw}" y2="{y:.1f}" stroke="{col}" '
                     f'stroke-width="0.9" stroke-dasharray="5,4" opacity="0.55"/>')
            p.append(f'<text x="{PL+4}" y="{y-4:.1f}" font-size="9.5" fill="{col}">{lab}</text>')
    if s_lo <= 0 <= s_hi:
        y0 = Y(0, s_lo, s_hi, top1, H1)
        p.append(f'<line x1="{PL}" y1="{y0:.1f}" x2="{PL+iw}" y2="{y0:.1f}" stroke="#9a9184" stroke-width="0.8"/>')
    p.append(f'<text x="{PL}" y="{top1-8}" font-size="11" fill="#4a4338" font-weight="600">'
             f'资金面 SOFR − EFFR（左 bp） × 黄金价格（右 $/oz）</text>')

    # ── 下栏: BBB(左 %, 独占轴) + HY(右 %) ──
    grid(top2, H2, b_lo, b_hi, h_lo, h_hi, lambda v: f"{v:.2f}", lambda v: f"{v:.2f}")
    p.append(f'<text x="{PL}" y="{top2-8}" font-size="11" fill="#4a4338" font-weight="600">'
             f'信用面 BBB 级 OAS（左 %·Oracle 同级，独立刻度） × 高收益 HY OAS（右 %）</text>')

    # ── 闪崩竖线(贯穿两栏) ──
    for c in crash_days:
        d = c["d"]
        if not (d0 <= d <= d1):
            continue
        x = X(d)
        both = c.get("both")
        col = "#a04545" if both else ("#8c6d4f" if "贵金属" in (c.get("groups") or [""])[0] else "#5a6b8c")
        for tp, hh in ((top1, H1), (top2, H2)):
            p.append(f'<line x1="{x:.1f}" y1="{tp}" x2="{x:.1f}" y2="{tp+hh}" stroke="{col}" '
                     f'stroke-width="{1.6 if both else 1.0}" opacity="{0.55 if both else 0.38}"/>')
        p.append(f'<circle cx="{x:.1f}" cy="{top1+6}" r="{3.6 if both else 2.8}" fill="{col}" opacity="0.9"/>')

    # ── 事件小三角(非闪崩但有事件说明的日子, 标在上栏顶部) ──
    for d in sorted(ev):
        if d0 <= d <= d1 and d not in crash_map:
            x = X(d)
            p.append(f'<path d="M{x-3.2:.1f},{top1-1} L{x+3.2:.1f},{top1-1} L{x:.1f},{top1+5}Z" '
                     f'fill="#6b8fb5" opacity="0.75"/>')

    # ── 曲线 ──
    if gold:
        p.append(f'<path d="{path(gold, g_lo, g_hi, top1, H1)}" fill="none" stroke="#c9a227" '
                 f'stroke-width="1.5" opacity="0.9"/>')
    p.append(f'<path d="{path(sofr, s_lo, s_hi, top1, H1)}" fill="none" stroke="#3f6b52" stroke-width="1.6"/>')
    if hy:
        p.append(f'<path d="{path(hy, h_lo, h_hi, top2, H2)}" fill="none" stroke="#c98b5e" stroke-width="1.4"/>')
    p.append(f'<path d="{path(bbb, b_lo, b_hi, top2, H2)}" fill="none" stroke="#7d5ba6" stroke-width="2.0"/>')

    # 峰值标注(BBB / HY / SOFR−EFFR / 黄金)
    def peak(pts, lo, hi, top, h, col, fmt):
        if not pts:
            return
        d, v = max(pts, key=lambda z: z[1])
        x, y = X(d), Y(v, lo, hi, top, h)
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{col}"/>')
        anchor = "end" if x > PL + iw * 0.85 else "start"
        dx = -6 if anchor == "end" else 6
        p.append(f'<text x="{x+dx:.1f}" y="{y-5:.1f}" font-size="10" fill="{col}" '
                 f'text-anchor="{anchor}">峰 {fmt(v)}（{d}）</text>')
    peak(sofr, s_lo, s_hi, top1, H1, "#3f6b52", lambda v: f"{v:+.0f}bp")
    peak(gold, g_lo, g_hi, top1, H1, "#a8861c", lambda v: f"${v:,.0f}")
    peak(bbb, b_lo, b_hi, top2, H2, "#7d5ba6", lambda v: f"{v:.2f}%")
    peak(hy, h_lo, h_hi, top2, H2, "#c98b5e", lambda v: f"{v:.2f}%")

    # x 轴月份
    seen = set()
    for d in alld:
        ym = d[:7]
        if ym in seen:
            continue
        seen.add(ym)
        if int(ym[5:]) % 3 != 1:
            continue
        x = X(d)
        p.append(f'<text x="{x:.1f}" y="{top2+H2+17}" font-size="10" fill="#8a8070" text-anchor="middle">{ym}</text>')
        p.append(f'<line x1="{x:.1f}" y1="{top2+H2}" x2="{x:.1f}" y2="{top2+H2+4}" stroke="#b0a696" stroke-width="0.8"/>')

    # ── 悬停: 每个交易日一条透明全高竖条, 显示 日期 + 四条线数值 + 当天事件/闪崩 ──
    # 用 ffill 让没有交易的线(如 OAS 美国假日)显示最近值并注明日期
    def _ff(m):
        last = [None, None]
        out_ = {}
        for d in alld:
            if d in m:
                last = [d, m[d]]
            out_[d] = tuple(last)
        return out_
    fs, fb, fh, fg = _ff(sm), _ff(bm), _ff(hm), _ff(gm)
    xs = [X(d) for d in alld]
    for i, d in enumerate(alld):
        xl = (xs[i - 1] + xs[i]) / 2 if i else PL
        xr = (xs[i] + xs[i + 1]) / 2 if i + 1 < len(xs) else PL + iw
        def _v(tpl, fmt):
            dd, vv = tpl
            if vv is None:
                return "—"
            return fmt(vv) + ("" if dd == d else f"（{dd[5:]}）")
        lines = [f"SOFR−EFFR {_v(fs[d], lambda v: f'{v:+.1f} bp')}",
                 f"BBB OAS {_v(fb[d], lambda v: f'{v:.2f}%')}",
                 f"HY OAS {_v(fh[d], lambda v: f'{v:.2f}%')}"]
        if gold:
            lines.append(f"黄金 {_v(fg[d], lambda v: f'${v:,.1f}')}")
        extra = []
        if d in crash_map:
            extra.append("⚡ 闪崩：" + " / ".join(f"{it['asset']} {it['ret']:+.2f}%" for it in crash_map[d]["items"]))
        for e in ev.get(d, []):
            src = e.get("source") or ""
            extra.append(f"📌 {e['event']}" + (f"（{src}）" if src else ""))
            if e.get("detail"):
                extra.append(e["detail"][:150])
        # 两层转义: 内层把外部文本转成安全 HTML 并用 <br> 连接; 外层再转义整串放进属性。
        #   浏览器 getAttribute 解掉外层 → 前端 innerHTML 只看到 <br> 和已转义的外部文本, 无注入面。
        _inner = "<br>".join(_esc(x) for x in (lines + extra))
        tip = _esc(d) + "||" + _esc(_inner)
        p.append(f'<rect x="{xl:.1f}" y="{top1}" width="{max(0.6, xr-xl):.2f}" height="{top2+H2-top1}" '
                 f'fill="transparent" data-tip="{tip}"/>')
    p.append("</svg>")
    chart = "".join(p)

    # ── 图例 ──
    leg = ('<div class="lqc-leg">'
           '<span><i style="background:#3f6b52"></i>SOFR − EFFR（上栏左轴 bp·资金面）</span>'
           '<span><i style="background:#c9a227"></i>黄金 COMEX 连续（上栏右轴 $/oz）</span>'
           '<span><i style="background:#7d5ba6"></i>BBB 级 OAS（下栏左轴 %·Oracle 同级）</span>'
           '<span><i style="background:#c98b5e"></i>高收益 HY OAS（下栏右轴 %）</span>'
           '<span><i style="background:#8c6d4f"></i>闪崩·贵金属</span>'
           '<span><i style="background:#5a6b8c"></i>闪崩·美股</span>'
           '<span><i style="background:#a04545"></i>贵金属与美股同日闪崩</span>'
           '<span><i style="background:#6b8fb5"></i>▼ 有事件说明的日子</span>'
           '</div>')

    # ── 当前读数 ──
    def _last(s):
        return (s or [(None, None)])[-1]

    ls, lb, lh = _last(sofr), _last(bbb), _last(hy)
    sv = ls[1] if ls[1] is not None else 0
    s_light = "危机" if sv > 18 else ("趋紧" if sv > 5 else "正常")
    s_cls = "bad" if sv > 18 else ("warn" if sv > 5 else "good")
    cards = (
        f'<div class="lqc-cards">'
        f'<div class="lqc-c"><div class="lqc-k">资金面 SOFR−EFFR</div>'
        f'<div class="lqc-v {s_cls}">{sv:+.1f} bp</div>'
        f'<div class="lqc-s">{ls[0]} · {s_light}（≤5 正常 / 5–18 趋紧 / &gt;18 危机）</div></div>'
        f'<div class="lqc-c"><div class="lqc-k">信用面 BBB OAS</div>'
        f'<div class="lqc-v">{lb[1]:.2f} %</div>'
        f'<div class="lqc-s">{lb[0]} · Oracle 同评级参照</div></div>'
        f'<div class="lqc-c"><div class="lqc-k">风险偏好 HY OAS</div>'
        f'<div class="lqc-v">{lh[1]:.2f} %</div>'
        f'<div class="lqc-s">{lh[0]} · 与 BBB 之差 '
        f'{(lh[1]-lb[1]):.2f} pct = 降级风险定价</div></div>'
        f'<div class="lqc-c"><div class="lqc-k">窗口内闪崩</div>'
        f'<div class="lqc-v">{len(crash_days)} 天</div>'
        f'<div class="lqc-s">其中贵金属与美股同日 '
        f'{sum(1 for c in crash_days if c.get("both"))} 天</div></div>'
        f'</div>')

    # ── 闪崩清单 ──
    rows = []
    for c in reversed(crash_days):
        items = " · ".join(f'{i["asset"]} <b>{i["ret"]:+.2f}%</b>' for i in c["items"])
        tag = ('<span class="lqc-tag both">跨类同崩</span>' if c.get("both")
               else ('<span class="lqc-tag pm">贵金属</span>' if "贵金属" in (c.get("groups") or [""])[0]
                     else '<span class="lqc-tag eq">美股</span>'))
        rows.append(f'<tr><td class="lqc-d">{c["d"]}</td><td>{tag}</td><td>{items}</td></tr>')
    table = ('<details class="lqc-det"><summary>闪崩日清单（'
             f'{len(crash_days)} 天，阈值＝各资产日收益率 P1 分位，随数据自适应）</summary>'
             '<table class="lqc-tb"><thead><tr><th>日期</th><th>类别</th>'
             '<th>当日跌幅</th></tr></thead><tbody>'
             + "".join(rows) + '</tbody></table></details>')

    prov = lq.get("provenance") or {}
    prov_html = ('<details class="lqc-det"><summary>数据溯源与口径</summary><ul class="lqc-prov">'
                 + "".join(f'<li><b>{k}</b>：{v}</li>' for k, v in prov.items())
                 + '</ul></details>')

    return (
        '<section class="sec" id="liquidity-crisis">'
        '<h2>每日流动性危机监测'
        '<span class="freq-badge">全部日更 · 2025-01 至今</span></h2>'
        '<div class="sec-note">把<b>资金面</b>（回购市场缺不缺钱）和<b>信用面</b>'
        '（愿不愿意借钱给高杠杆企业）画在同一张图上。'
        '两者<b>同时</b>恶化才是真流动性危机；只有一边动，多半是局部事件。'
        '竖线为闪崩日，贵金属与美股分色，贵金属与美股<b>同日一起</b>闪崩的用红色加粗——那才是系统性流动性事件，而非单一市场的事。</div>'
        + cards + chart + leg
        + '<div class="lqc-hint">鼠标放在图上任意位置，会显示该日的四条线数值；闪崩日和标了 ▼ 的日子还会显示当天发生了什么及出处。'
          'Oracle 单名 CDS 属付费数据无法取得，故以其<b>同评级 BBB 档 OAS</b> 为主线、'
          'HY OAS 为降级风险参照——Oracle 现为 S&amp;P BBB−，距垃圾级仅一档。</div>'
        + table + prov_html +
        '</section>')



def _cot_mm_one(key, m):
    """单个金属: 价格日线(左轴) + MM 净持仓周度台阶(右轴) + OI 周度线。"""
    import datetime as _dt
    cot = m.get("cot") or []
    price = m.get("price") or []
    if len(cot) < 2 or len(price) < 2:
        return f'<div class="cmm-one"><div class="cmm-t">{m.get("name","")}</div>' \
               f'<p class="empty">数据不足</p></div>'

    W, H = 1160, 300
    PL, PR, PT, PB = 64, 70, 22, 40
    iw, ih = W - PL - PR, H - PT - PB

    d0 = min(cot[0]["d"], price[0][0])
    d1 = max(cot[-1]["d"], price[-1][0])
    t0 = _dt.date.fromisoformat(d0).toordinal()
    span = max(1, _dt.date.fromisoformat(d1).toordinal() - t0)

    def X(d):
        return PL + iw * (_dt.date.fromisoformat(d).toordinal() - t0) / span

    pv = [v for _, v in price]
    pmin, pmax = min(pv), max(pv)
    ppad = (pmax - pmin) * 0.1 or 1
    pmin, pmax = pmin - ppad, pmax + ppad

    nets = [c["mm_net"] for c in cot]
    ois = [c["oi"] for c in cot]
    nmin, nmax = min(nets + [0]), max(nets)
    npad = (nmax - nmin) * 0.12 or 1
    nmin, nmax = nmin - npad, nmax + npad

    def YP(v):
        return PT + ih * (1 - (v - pmin) / (pmax - pmin))

    def YN(v):
        return PT + ih * (1 - (v - nmin) / (nmax - nmin))

    p = [f'<svg viewBox="0 0 {W} {H}" class="cmm-chart" preserveAspectRatio="xMidYMid meet" '
         f'font-family="-apple-system,PingFang SC,Helvetica,sans-serif">']

    for i in range(5):
        y = PT + ih * i / 4
        p.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{PL+iw}" y2="{y:.1f}" '
                 f'stroke="#d8d2c6" stroke-width="0.6" stroke-dasharray="2,3"/>')
        p.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" font-size="10" fill="#8a8070" '
                 f'text-anchor="end">{pmax-(pmax-pmin)*i/4:,.0f}</text>')
        p.append(f'<text x="{PL+iw+8}" y="{y+3.5:.1f}" font-size="10" fill="#8a8070" '
                 f'text-anchor="start">{(nmax-(nmax-nmin)*i/4)/1000:,.0f}k</text>')

    # MM 净持仓: 周度台阶面积(零轴基准, 正=净多 负=净空)
    y0 = YN(0)
    if nmin <= 0 <= nmax:
        p.append(f'<line x1="{PL}" y1="{y0:.1f}" x2="{PL+iw}" y2="{y0:.1f}" '
                 f'stroke="#9a9184" stroke-width="0.9"/>')
    step = []
    for i, c in enumerate(cot):
        x = X(c["d"])
        xn = X(cot[i + 1]["d"]) if i + 1 < len(cot) else PL + iw
        y = YN(c["mm_net"])
        step.append(f'{x:.1f},{y:.1f} {xn:.1f},{y:.1f}')
    p.append(f'<polyline points="{" ".join(step)}" fill="none" stroke="#7d5ba6" '
             f'stroke-width="1.5" opacity="0.9"/>')
    p.append(f'<polygon points="{PL},{y0:.1f} {" ".join(step)} {PL+iw},{y0:.1f}" '
             f'fill="#7d5ba6" opacity="0.13"/>')

    # OI 周度线(用右轴, 但缩放到同轴范围以便共存 —— 单独标注)
    omin, omax = min(ois), max(ois)
    def YO(v):
        return PT + ih * (1 - (v - omin) / ((omax - omin) or 1)) * 0.42 + ih * 0.03
    p.append('<polyline points="' +
             " ".join(f'{X(c["d"]):.1f},{YO(c["oi"]):.1f}' for c in cot) +
             '" fill="none" stroke="#b08968" stroke-width="1.1" '
             'stroke-dasharray="4,3" opacity="0.8"/>')

    # 价格日线(左轴, 画最上层)
    p.append('<path d="M' + " L".join(f'{X(d):.1f},{YP(v):.1f}' for d, v in price) +
             '" fill="none" stroke="#3f6b52" stroke-width="1.6"/>')

    seen = set()
    for c in cot:
        ym = c["d"][:7]
        if ym in seen or int(ym[5:]) % 3 != 1:
            continue
        seen.add(ym)
        x = X(c["d"])
        p.append(f'<text x="{x:.1f}" y="{PT+ih+16}" font-size="9.5" fill="#8a8070" '
                 f'text-anchor="middle">{ym}</text>')

    p.append(f'<text x="{PL-8}" y="{PT-8}" font-size="9.5" fill="#6f665a" '
             f'text-anchor="end">价格 $</text>')
    p.append(f'<text x="{PL+iw+8}" y="{PT-8}" font-size="9.5" fill="#6f665a" '
             f'text-anchor="start">MM净(手)</text>')
    # hover: 每个价格日一条命中带; 周度持仓取「截至当日最近一期」(as-of, 不插值不编造)
    _xs, _tips, _ci = [], [], -1
    for d, v in price:
        while _ci + 1 < len(cot) and cot[_ci + 1]["d"] <= d:
            _ci += 1
        _t = f'价格 ${v:,.2f}'
        if _ci >= 0:
            _c = cot[_ci]
            _t += (f'<br>MM 净持仓 {_c["mm_net"]:+,} 手<br>未平仓 OI {_c["oi"]:,} 手'
                   f'<br>（持仓周度 · 截至 {_c["d"]}）')
        _xs.append(X(d)); _tips.append(f'{_esc(d)}||{_esc(_t)}')
    p.append(_hover_bands(_xs, _tips, PT, ih, PL, PL + iw))
    p.append("</svg>")

    last, prev = m.get("latest") or {}, m.get("prev") or {}
    pc = m.get("pctile") or {}
    dn = last.get("mm_net", 0) - prev.get("mm_net", 0)
    doi = last.get("oi", 0) - prev.get("oi", 0)
    plast = m.get("price_latest") or ("", 0)
    oi_p, net_p = pc.get("oi", 0), pc.get("mm_net", 0)
    oi_flag = ("<b>极低</b>" if oi_p <= 10 else ("偏低" if oi_p <= 30 else
               ("偏高" if oi_p >= 70 else "中性")))

    stat = (
        f'<div class="cmm-stat">'
        f'<span><i>价格</i><b>{plast[1]:,.2f}</b><em>{plast[0]} 日更</em></span>'
        f'<span><i>MM 净持仓</i><b>{last.get("mm_net",0):+,}</b>'
        f'<em>{last.get("d","")} · 周环比 {dn:+,} · 近3年 P{net_p:.0f}</em></span>'
        f'<span><i>未平仓 OI</i><b>{last.get("oi",0):,}</b>'
        f'<em>周环比 {doi:+,} · 近3年 P{oi_p:.0f}（{oi_flag}）</em></span>'
        f'<span><i>MM 多 / 空</i><b>{last.get("mm_long",0):,} / {last.get("mm_short",0):,}</b>'
        f'<em>做市商(SD)净 {last.get("sd_net",0):+,}</em></span>'
        f'</div>')

    return (f'<div class="cmm-one">'
            f'<div class="cmm-t">{m.get("name","")}'
            f'<span class="cmm-ex">{m.get("exchange","")}</span></div>'
            f'{stat}{"".join(p)}</div>')


def _cot_mm_html(cm):
    """COMEX/NYMEX 对冲基金(Managed Money)持仓 vs 价格叠加。

    ★2026-09-18 新增。Chao 要「开仓量和价格叠加图, 每天更新」。
      ★持仓做不到日更 —— CFTC COT 是周度(周二持仓/周五 15:30 ET 发布), 全世界都只有周度。
        故做成「持仓周度台阶 + 价格日度曲线」, 频率标签分别如实标注。
    ★口径用 Disaggregated 的 Managed Money(纯对冲基金/CTA),
      不是 Legacy 的 non-commercial(混了指数基金)。
    """
    if not cm or not isinstance(cm, dict):
        return ('<section class="sec"><h2>对冲基金持仓 vs 价格</h2>'
                '<div class="muted">数据未就绪</div></section>')
    oks = [(k, v) for k, v in cm.items() if isinstance(v, dict) and v.get("status") == "ok"]
    if not oks:
        return ('<section class="sec"><h2>对冲基金持仓 vs 价格</h2>'
                '<div class="muted">数据未就绪</div></section>')

    order = {"gold": 0, "silver": 1, "platinum": 2}
    oks.sort(key=lambda z: order.get(z[0], 9))
    charts = "".join(_cot_mm_one(k, v) for k, v in oks)

    leg = ('<div class="cmm-leg">'
           '<span><i style="background:#3f6b52"></i>价格（左轴 · <b>日更</b>）</span>'
           '<span><i style="background:#7d5ba6"></i>Managed Money 净持仓（右轴 · <b>周更</b>）</span>'
           '<span><i style="background:#b08968"></i>未平仓量 OI（周更 · 相对走势）</span>'
           '</div>')

    src0 = (oks[0][1].get("source") or "")
    prov = ('<details class="lqc-det"><summary>数据溯源与口径</summary><ul class="lqc-prov">'
            f'<li><b>持仓</b>：{src0}。数据集 CFTC Socrata Disaggregated futures-only '
            '(<code>72hh-3qpy</code>)，免 key。</li>'
            '<li><b>为何用 Managed Money 而非 non-commercial</b>：Legacy 口径的 '
            'non-commercial 把对冲基金、CTA、指数基金混在一起；Disaggregated 的 '
            'Managed Money 才是纯投机资金，Swap Dealer 则是其对手方（做市商/银行）。</li>'
            '<li><b>频率</b>：CFTC 每周二收盘持仓、当周<b>周五 15:30 ET 发布</b>，'
            '故持仓永远滞后 3–10 天，<b>日更在数据源层面不存在</b>；价格为日频。</li>'
            '<li><b>交易所</b>：黄金/白银在 <b>COMEX</b>，铂金在 <b>NYMEX</b>，'
            '均排除 MICRO 迷你合约。</li>'
            '<li><b>分位</b>：P 值为该读数在近 3 年（约 156 期）中的历史分位。</li>'
            '</ul></details>')

    return ('<section class="sec" id="cot-managed-money">'
            '<h2>对冲基金持仓 vs 价格'
            '<span class="freq-badge">持仓周更 · 价格日更</span></h2>'
            '<div class="sec-note">绿线是价格（日频），紫色台阶是对冲基金'
            '（Managed Money）净持仓（周频），棕色虚线是未平仓量 OI 的相对走势。'
            '<b>价格涨而 MM 净持仓不跟进</b>＝涨势缺乏投机资金背书；'
            '<b>OI 持续收缩</b>＝整个市场在去杠杆，波动会被放大。</div>'
            + leg + charts + prov + '</section>')



def _mm_ratio_html(o):
    """白银/黄金 对冲基金(Managed Money) 多空比 vs 价格。多空比=多头手数/空头手数(CFTC Disaggregated 周度)。
    两口径: Combined(期货+期权, 与 MacroMicro「期货/选择权」同口径) 与 Futures-only(与看板上方「对冲基金持仓」同口径)。2026-10-18 Chao 贴 MacroMicro 白银图「这个我们有做么」→「做」。"""
    import json as _json, html as _h
    if not o or not isinstance(o, dict) or not (o.get("metals") or {}):
        return '<p class="empty">对冲基金多空比同步中（源：CFTC Disaggregated，免 key）。</p>'
    cards = ""
    pay = {}
    for key in ("silver", "gold"):
        m = (o.get("metals") or {}).get(key)
        if not m or len(m.get("rows") or []) < 10: continue
        rows = m["rows"]; L = rows[-1]; P = rows[-2]
        cb = [r["cb_ratio"] for r in rows]; lo = min(cb); hi = max(cb)
        rk = sum(1 for v in cb if v <= L["cb_ratio"]) / len(cb) * 100
        pay[key] = {"rows": rows, "price": m.get("price") or [], "name": m["name"], "gaps": m.get("gaps") or []}
        diff = L["cb_ratio"] - L["fo_ratio"]
        _med = sorted(cb)[len(cb) // 2]; _mx = max(rows, key=lambda r: r["cb_ratio"])
        _ext = (f'<br>最高值 {_mx["cb_ratio"]:.2f} 出现在 {_mx["d"]}（当周空头仅 {_mx["cb_short"]:,} 手，真实数据），约为中位数 {_med:.2f} 的 {_mx["cb_ratio"]/_med:.0f} 倍；切到「2 年」时纵轴会被拉高'
                if _mx["cb_ratio"] > _med * 3 else "")
        stat = (f'<div class="mmr-stat">'
                f'<span><i>多空比（期货+期权）</i><b>{L["cb_ratio"]:.2f}</b><em>{L["d"]} · 周变动 {L["cb_ratio"]-P["cb_ratio"]:+.2f}<br>近 2 年分位 P{rk:.0f}（越低＝越偏空）</em></span>'
                f'<span><i>多 / 空（手）</i><b>{L["cb_long"]:,} / {L["cb_short"]:,}</b><em>上周 {P["cb_long"]:,} / {P["cb_short"]:,}</em></span>'
                f'<span><i>近 2 年区间</i><b>{lo:.2f} – {hi:.2f}</b><em>最新{"为区间最低" if L["cb_ratio"] <= lo + 1e-9 else ("为区间最高" if L["cb_ratio"] >= hi - 1e-9 else "在区间内")}{_ext}</em></span>'
                f'<span><i>仅期货口径</i><b>{L["fo_ratio"]:.2f}</b><em>与期货+期权相差 {diff:+.2f}</em></span>'
                f'</div>')
        cards += (f'<div class="mmr-one" id="mmr-{key}"><div class="mmr-t">{_h.escape(m["name"])} Managed Money 多空比 vs {_h.escape(m["name"])}期货价格<span class="mmr-ex">COMEX</span></div>'
                  f'{stat}<div class="mmr-ctl"><span class="mmr-lab">口径</span>'
                  f'<button class="mmr-b mmr-on" data-k="{key}" data-g="cb">期货+期权</button><button class="mmr-b" data-k="{key}" data-g="fo">仅期货</button>'
                  f'<span class="mmr-lab" style="margin-left:14px">区间</span>'
                  f'<button class="mmr-r mmr-on" data-k="{key}" data-w="52">1 年</button><button class="mmr-r" data-k="{key}" data-w="110">2 年</button></div>'
                  f'<div class="mmr-box" id="mmr-box-{key}"></div></div>')
    if not cards:
        return '<p class="empty">对冲基金多空比：本期无数据。</p>'
    js = "(function(){var D=" + _json.dumps(pay, ensure_ascii=False, separators=(",", ":")) + r"""
;var ST={};
function fmt(n){return n.toLocaleString('en-US')}
function draw(k){var d=D[k],st=ST[k],rows=d.rows.slice(-st.w),g=st.g;if(!rows.length)return;
 var W=1100,H=340,PL=54,PR=92,PT=26,PB=34,iw=W-PL-PR,ih=H-PT-PB;
 var d0=rows[0].d,d1=rows[rows.length-1].d,t0=Date.parse(d0),t1=Date.parse(d1),sp=Math.max(1,t1-t0);
 function X(s){return PL+iw*(Date.parse(s)-t0)/sp}
 var pr=d.price.filter(function(p){return p[0]>=d0});
 var rv=rows.map(function(r){return g=='cb'?r.cb_ratio:r.fo_ratio}),rmax=Math.max.apply(null,rv)*1.12;
 var pv=pr.map(function(p){return p[1]}),pmin=Math.min.apply(null,pv),pmax=Math.max.apply(null,pv),pp=(pmax-pmin)*0.08||1;pmin=Math.max(0,pmin-pp);pmax+=pp;
 function YR(v){return PT+ih*(1-v/rmax)}function YP(v){return PT+ih*(1-(v-pmin)/(pmax-pmin))}
 var s='<svg viewBox="0 0 '+W+' '+H+'" class="mmr-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,Helvetica,sans-serif">';
 var ns=5,i;for(i=0;i<=ns;i++){var y=PT+ih*i/ns;s+='<line x1="'+PL+'" y1="'+y+'" x2="'+(PL+iw)+'" y2="'+y+'" stroke="#e6e0d4" stroke-width="0.7"/>';
  s+='<text x="'+(PL-8)+'" y="'+(y+4)+'" font-size="12" fill="#4a443c" text-anchor="end">'+(rmax*(1-i/ns)).toFixed(1)+'</text>';
  s+='<text x="'+(PL+iw+18)+'" y="'+(y+4)+'" font-size="12" fill="#8c4a3a" text-anchor="start">'+(pmax-(pmax-pmin)*i/ns).toFixed(k=='gold'?0:0)+'</text>'}
 s+='<text x="'+PL+'" y="'+(PT-12)+'" font-size="11" fill="#5a534a" text-anchor="start">绿柱：多空比（左轴）</text><text x="'+(W-4)+'" y="'+(PT-12)+'" font-size="11" fill="#8c4a3a" text-anchor="end">红线：价格 $（右轴）</text>';
 var bw=Math.max(1.5,iw/rows.length*0.62);
 rows.forEach(function(r){var v=g=='cb'?r.cb_ratio:r.fo_ratio,x=X(r.d),y=YR(v);s+='<rect x="'+(x-bw/2).toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+(PT+ih-y).toFixed(1)+'" fill="#7aa88a" opacity="0.78"/>'});
 s+='<path d="M'+pr.map(function(p){return X(p[0]).toFixed(1)+','+YP(p[1]).toFixed(1)}).join(' L')+'" fill="none" stroke="#c0553a" stroke-width="1.6"/>';
 var last=null;rows.forEach(function(r){var ym=r.d.slice(0,7),mo=parseInt(ym.slice(5));if(ym!==last&&(mo%3==1)){last=ym;s+='<text x="'+X(r.d).toFixed(1)+'" y="'+(PT+ih+16)+'" font-size="11" fill="#5a534a" text-anchor="middle">'+ym+'</text>'}});
 var xs=[],tips=[],ci=-1;
 rows.forEach(function(r,idx){var x=X(r.d),L=g=='cb'?r.cb_long:r.fo_long,S=g=='cb'?r.cb_short:r.fo_short,v=g=='cb'?r.cb_ratio:r.fo_ratio;
  var pj=-1;for(var j=0;j<pr.length;j++){if(pr[j][0]<=r.d)pj=j;else break}
  var t='多空比 <b>'+v.toFixed(2)+'</b>（'+(g=='cb'?'期货+期权':'仅期货')+'）<br>多头 '+fmt(L)+' 手 / 空头 '+fmt(S)+' 手'+(pj>=0?'<br>价格 $'+pr[pj][1].toFixed(2)+'（'+pr[pj][0]+' 收盘）':'')+'<br>（持仓周度 · CFTC 周二持仓）';
  s+='<circle class="tip-hit" cx="'+x.toFixed(1)+'" cy="'+YR(v).toFixed(1)+'" r="9" fill="transparent" data-tip="'+r.d+'||'+t.replace(/"/g,'&quot;')+'"/>'});
 s+='</svg>';document.getElementById('mmr-box-'+k).innerHTML=s}
['silver','gold'].forEach(function(k){if(!D[k])return;ST[k]={g:'cb',w:52};draw(k)});
document.querySelectorAll('.mmr-b').forEach(function(b){b.addEventListener('click',function(){var k=b.dataset.k;ST[k].g=b.dataset.g;document.querySelectorAll('.mmr-b[data-k="'+k+'"]').forEach(function(x){x.classList.toggle('mmr-on',x===b)});draw(k)})});
document.querySelectorAll('.mmr-r').forEach(function(b){b.addEventListener('click',function(){var k=b.dataset.k;ST[k].w=parseInt(b.dataset.w);document.querySelectorAll('.mmr-r[data-k="'+k+'"]').forEach(function(x){x.classList.toggle('mmr-on',x===b)});draw(k)})});
})();"""
    foot = ('<div class="sgr-foot"><b>怎么读：</b>多空比＝对冲基金（Managed Money）多头手数 ÷ 空头手数。比值越高越偏多，接近 1 表示多空接近均衡。'
            '绿柱是多空比（周更，周二持仓、周五发布，所以永远滞后几天），红线是价格（日更，Yahoo 连续合约）。'
            '<br><b>口径：</b>默认「期货+期权」（CFTC Disaggregated Combined，数据集 <code>kh3c-gbw2</code>），与 MacroMicro 标题「期货/选择权」同类；'
            '切到「仅期货」（<code>72hh-3qpy</code>）则与上方「对冲基金持仓 vs 价格」同口径。<b>两者最多相差约 0.6，与 MacroMicro 原图的数值也不一定逐点相同</b>（我们取 COMEX 主合约、排除 MICRO，未必与对方的合约范围一致）。'
            '<br><b>2025-11 那一段：</b>MacroMicro 原图在 2025-11 中旬有一段缺失。CFTC 的数据里这一段<b>没有缺周</b>，但 2025-11-10 这期的报告日是周一（通常是周二），其后到 11-18 间隔 8 天——这是美国联邦政府停摆后 CFTC 补发时调整了日期，所以这几根柱子的间距比其他周略不均匀，不是我插值或补出来的。'
            '<br>页面只陈述数据，不对价格方向做判断。</div>')
    return ('<section class="sec" id="mm-ratio"><h2>对冲基金多空比 vs 价格'
            '<span class="freq-badge freq-weekly">持仓周更 · 价格日更</span></h2>'
            '<div class="sec-note">对冲基金在 COMEX 金银上的多头手数相对空头手数的比值，叠加期货价格。口径是 CFTC 官方周度数据，免费、可回溯。</div>'
            + cards + foot + '<script>' + js + '</script></section>')


def _h8_deposits_html(o):
    """美国商业银行存款(美联储 H.8, FRED 周度, 十亿美元)。2026-10-18 Chao 贴 H.8 周表「这个图能做么」→「做」。"""
    import json as _json, html as _h
    rows = (o or {}).get("rows") or []
    if not o or len(rows) < 12:
        return '<p class="empty">美国银行存款（H.8）同步中（源：FRED / 美联储，周三发布）。</p>'
    L, P = rows[-1], rows[-2]
    def dv(k, tag): return L["%s_%s" % (k, tag)] - P["%s_%s" % (k, tag)]
    def sg(x): return ("+" if x >= 0 else "−") + f"{abs(x):,.1f}"
    tot_sa, tot_nsa = dv("tot", "sa"), dv("tot", "nsa")
    verb = lambda x: ("增加" if x >= 0 else "减少")
    banner = (f'<div class="h8-ban"><b>{L["d"]} 当周</b>　季调（SA）总存款{verb(tot_sa)} <b>{abs(tot_sa) * 1:,.1f}</b> 十亿美元（约 {abs(tot_sa) * 10:,.0f} 亿美元）'
              f'（大型银行 {sg(dv("lg", "sa"))}，小型银行 {sg(dv("sm", "sa"))}，外国相关机构 {sg(dv("fr", "sa"))}）；'
              f'未季调（NSA）{verb(tot_nsa)} <b>{abs(tot_nsa):,.1f}</b>（大型 {sg(dv("lg", "nsa"))}，小型 {sg(dv("sm", "nsa"))}，外国 {sg(dv("fr", "nsa"))}）。'
              f'<span class="h8-u">单位：十亿美元；H.8 周三发布，数据为周三余额。</span></div>')
    stat = (f'<div class="h8-stat"><span><i>总存款（SA）</i><b>{L["tot_sa"]:,.1f}</b><em>{L["d"]} · 周变动 {sg(tot_sa)}</em></span>'
            f'<span><i>总存款（NSA）</i><b>{L["tot_nsa"]:,.1f}</b><em>周变动 {sg(tot_nsa)}</em></span>'
            f'<span><i>大型 / 小型国内银行（SA）</i><b>{L["lg_sa"]:,.0f} / {L["sm_sa"]:,.0f}</b><em>周变动 {sg(dv("lg", "sa"))} / {sg(dv("sm", "sa"))}</em></span>'
            f'<span><i>外国相关机构（SA）</i><b>{L["fr_sa"]:,.0f}</b><em>周变动 {sg(dv("fr", "sa"))}</em></span></div>')
    # 表: 最近 8 周
    trs = ""
    for i in range(len(rows) - 1, max(len(rows) - 9, 0), -1):
        a, p = rows[i], rows[i - 1]
        f = lambda k, t: a["%s_%s" % (k, t)] - p["%s_%s" % (k, t)]
        cls = lambda x: ' style="color:#a8442f"' if x < 0 else ' style="color:#2f6f4f"'
        trs += (f'<tr><td style="white-space:nowrap">{a["d"]}</td><td class="r">{a["tot_sa"]:,.1f}</td><td class="r"{cls(f("tot","sa"))}>{sg(f("tot","sa"))}</td>'
                f'<td class="r"{cls(f("lg","sa"))}>{sg(f("lg","sa"))}</td><td class="r"{cls(f("sm","sa"))}>{sg(f("sm","sa"))}</td><td class="r"{cls(f("fr","sa"))}>{sg(f("fr","sa"))}</td>'
                f'<td class="r">{a["tot_nsa"]:,.1f}</td><td class="r"{cls(f("tot","nsa"))}>{sg(f("tot","nsa"))}</td>'
                f'<td class="r"{cls(f("lg","nsa"))}>{sg(f("lg","nsa"))}</td><td class="r"{cls(f("sm","nsa"))}>{sg(f("sm","nsa"))}</td><td class="r"{cls(f("fr","nsa"))}>{sg(f("fr","nsa"))}</td></tr>')
    m2 = o.get("m2") or []
    m2txt = ""
    if len(m2) >= 2:
        m2txt = ("　".join(f'{x[0][:7]} {x[1]:,.1f}' for x in m2[-3:]) + f'　（最新较上月 {sg(m2[-1][1] - m2[-2][1])}）')
    table = ('<table class="h8-tab"><thead><tr><th rowspan="2">周（周三）</th><th colspan="5">季调 SA</th><th colspan="5">未季调 NSA</th></tr>'
             '<tr><th>总存款</th><th>周变动</th><th>大型</th><th>小型</th><th>外国</th><th>总存款</th><th>周变动</th><th>大型</th><th>小型</th><th>外国</th></tr></thead>'
             f'<tbody>{trs}</tbody></table>'
             + (f'<div class="h8-m2">月度 M2（SA，十亿美元，FRED M2SL）：{m2txt}</div>' if m2txt else ''))
    pay = {"rows": rows}
    ctl = ('<div class="h8-ctl"><span class="h8-lab">口径</span><button class="h8-b h8-on" data-g="sa">季调 SA</button><button class="h8-b" data-g="nsa">未季调 NSA</button>'
           '<span class="h8-lab" style="margin-left:14px">区间</span><button class="h8-r h8-on" data-w="52">1 年</button><button class="h8-r" data-w="110">2 年</button></div>')
    js = "(function(){var D=" + _json.dumps(pay, ensure_ascii=False, separators=(",", ":")) + r"""
;var ST={g:'sa',w:52};
function fm(n){return n.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}
function sg(n){return (n>=0?'+':'−')+fm(Math.abs(n))}
function draw(){var rows=D.rows.slice(-(ST.w+1)),g=ST.g,n=rows.length;if(n<3)return;
 var W=1100,H=380,PL=64,PR=64,PT=22,PB=34,iw=W-PL-PR,ih=H-PT-PB;
 var split=PT+ih*0.62;       // 上 62% 总存款折线, 下 38% 周变动柱
 var tv=rows.map(function(r){return r['tot_'+g]}),tmin=Math.min.apply(null,tv),tmax=Math.max.apply(null,tv),tp=(tmax-tmin)*0.12||1;tmin-=tp;tmax+=tp;
 var ch=[];for(var i=1;i<n;i++)ch.push(rows[i]['tot_'+g]-rows[i-1]['tot_'+g]);
 var cm=Math.max.apply(null,ch.map(Math.abs))*1.15||1;
 var t0=Date.parse(rows[1].d),t1=Date.parse(rows[n-1].d),sp=Math.max(1,t1-t0);
 function X(s){return PL+iw*(Date.parse(s)-t0)/sp}
 function YT(v){return PT+(split-PT-14)*(1-(v-tmin)/(tmax-tmin))}
 var by0=split+14,bh=H-PB-by0,mid=by0+bh/2;function YC(v){return mid-(bh/2)*(v/cm)}
 var s='<svg viewBox="0 0 '+W+' '+H+'" class="h8-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,Helvetica,sans-serif">';
 var i2;for(i2=0;i2<=4;i2++){var y=PT+(split-PT-14)*i2/4;s+='<line x1="'+PL+'" y1="'+y+'" x2="'+(PL+iw)+'" y2="'+y+'" stroke="#e6e0d4" stroke-width="0.7"/><text x="'+(PL-8)+'" y="'+(y+4)+'" font-size="11" fill="#4a443c" text-anchor="end">'+Math.round(tmax-(tmax-tmin)*i2/4).toLocaleString('en-US')+'</text>'}
 s+='<text x="'+PL+'" y="'+(PT-8)+'" font-size="11" fill="#4a443c">折线：总存款（'+(g=='sa'?'季调':'未季调')+'，十亿美元）</text>';
 s+='<line x1="'+PL+'" y1="'+mid+'" x2="'+(PL+iw)+'" y2="'+mid+'" stroke="#9a9184" stroke-width="0.9"/><text x="'+PL+'" y="'+(by0-3)+'" font-size="11" fill="#4a443c">柱：周变动（十亿美元，零轴为分界）</text>';
 s+='<text x="'+(PL-8)+'" y="'+(mid+4)+'" font-size="11" fill="#4a443c" text-anchor="end">0</text><text x="'+(PL-8)+'" y="'+(YC(cm*0.85)+4)+'" font-size="10.5" fill="#6b645a" text-anchor="end">+'+Math.round(cm*0.85)+'</text><text x="'+(PL-8)+'" y="'+(YC(-cm*0.85)+4)+'" font-size="10.5" fill="#6b645a" text-anchor="end">−'+Math.round(cm*0.85)+'</text>';
 var bw=Math.max(2,iw/(n-1)*0.62);
 for(var i3=1;i3<n;i3++){var c=ch[i3-1],x=X(rows[i3].d),y2=YC(c),top=Math.min(y2,mid),h2=Math.abs(y2-mid);s+='<rect x="'+(x-bw/2).toFixed(1)+'" y="'+top.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(0.6,h2).toFixed(1)+'" fill="'+(c>=0?'#7aa88a':'#c0553a')+'" opacity="0.85"/>'}
 s+='<polyline points="'+rows.slice(1).map(function(r){return X(r.d).toFixed(1)+','+YT(r['tot_'+g]).toFixed(1)}).join(' ')+'" fill="none" stroke="#3d372f" stroke-width="1.8"/>';
 var last='';rows.slice(1).forEach(function(r){var ym=r.d.slice(0,7),mo=parseInt(ym.slice(5));if(ym!==last&&(mo%3==1)){last=ym;s+='<text x="'+X(r.d).toFixed(1)+'" y="'+(H-12)+'" font-size="11" fill="#4a443c" text-anchor="middle">'+ym+'</text>'}});
 for(var i4=1;i4<n;i4++){var r=rows[i4],p=rows[i4-1],x3=X(r.d),dd=function(k){return r[k+'_'+g]-p[k+'_'+g]};
  var t='总存款 <b>'+fm(r['tot_'+g])+'</b>（周变动 '+sg(dd('tot'))+'）<br>大型 '+sg(dd('lg'))+' · 小型 '+sg(dd('sm'))+' · 外国 '+sg(dd('fr'))+'<br>（'+(g=='sa'?'季调':'未季调')+'，十亿美元；H.8 周三余额）';
  s+='<circle class="tip-hit" cx="'+x3.toFixed(1)+'" cy="'+YT(r['tot_'+g]).toFixed(1)+'" r="10" fill="transparent" data-tip="'+r.d+'||'+t.replace(/"/g,'&quot;')+'"/>'}
 s+='</svg>';document.getElementById('h8-box').innerHTML=s}
draw();
document.querySelectorAll('.h8-b').forEach(function(b){b.addEventListener('click',function(){ST.g=b.dataset.g;document.querySelectorAll('.h8-b').forEach(function(x){x.classList.toggle('h8-on',x===b)});draw()})});
document.querySelectorAll('.h8-r').forEach(function(b){b.addEventListener('click',function(){ST.w=parseInt(b.dataset.w);document.querySelectorAll('.h8-r').forEach(function(x){x.classList.toggle('h8-on',x===b)});draw()})});
})();"""
    foot = ('<div class="sgr-foot"><b>口径：</b>美联储 H.8 报告的<b>商业银行存款</b>（FRED 序列 <code>DPSACBW027</code> 总存款、<code>DPSLCBW027</code> 大型国内银行、<code>DPSSCBW027</code> 小型国内银行、<code>DPSFRIW027</code> 外国相关机构，各有 SA 季调与 NSA 未季调两套），'
            '每周三发布，数值为周三余额。<b>总存款 = 大型 + 小型 + 外国相关机构</b>（页面构建时逐周校验，容差 0.5）。'
            '<br><b>不含</b>货币市场基金、国债等，所以不等于「市场上的钱」。H.8 数据会被事后小幅修订，与第三方截图的数值可能相差零点几十亿美元。'
            '<br>页面只陈述数据，不对「存款外流」或原因做判断。</div>')
    return ('<section class="sec" id="h8-deposits"><h2>美国银行存款 · H.8 周度'
            '<span class="freq-badge freq-weekly">每周三更新</span></h2>'
            '<div class="sec-note">美联储 H.8 报告中商业银行存款的每周变化，按大型国内银行、小型国内银行、外国相关机构拆分，季调与未季调并列。</div>'
            + banner + stat + ctl + '<div class="h8-box" id="h8-box"></div>' + table + foot + '<script>' + js + '</script></section>')


def _hf_ust_html(o):
    """英国/开曼/巴哈马 持有美债(TIC SLT Table 3, 百万美元, 月度)。2026-10-18 Chao 贴 Excel「做」。"""
    import json as _json
    rows = (o or {}).get("rows") or []
    if not o or len(rows) < 12:
        return '<p class="empty">对冲基金常用注册地持美债同步中（源：美国财政部 TIC，月度）。</p>'
    L, P = rows[-1], rows[-2]
    hi = max(rows, key=lambda r: r["tot"])
    sg = lambda x: ("+" if x >= 0 else "−") + f"{abs(x):,.0f}"
    sgb = lambda x: ("+" if x >= 0 else "−") + f"{abs(x) / 1000:,.1f}"
    pct = lambda a, b: ("+" if a >= b else "−") + f"{abs(a / b - 1) * 100:,.1f}%"
    first = rows[0]
    stat = (f'<div class="hf-stat"><span><i>三地合计 · {L["m"]}</i><b>{L["tot"] / 1000:,.1f}</b><em>十亿美元 · 较上月 {sgb(L["tot"] - P["tot"])}（{pct(L["tot"], P["tot"])}）</em></span>'
            f'<span><i>英国（十亿美元）</i><b>{L["uk"] / 1000:,.1f}</b><em>较上月 {sgb(L["uk"] - P["uk"])}</em></span>'
            f'<span><i>开曼群岛（十亿美元）</i><b>{L["cy"] / 1000:,.1f}</b><em>较上月 {sgb(L["cy"] - P["cy"])}</em></span>'
            f'<span><i>巴哈马（十亿美元）</i><b>{L["bs"] / 1000:,.1f}</b><em>较上月 {sgb(L["bs"] - P["bs"])}</em></span>'
            f'<span><i>历史最高合计（十亿美元）</i><b>{hi["tot"] / 1000:,.1f}</b><em>{hi["m"]}（{first["m"]} 起；当月 {first["tot"] / 1000:,.1f}）</em></span></div>')
    trs = ""
    for i in range(len(rows) - 1, max(len(rows) - 13, 0), -1):
        a, p = rows[i], rows[i - 1]
        trs += (f'<tr><td>{a["m"]}</td><td class="r">{a["uk"]:,}</td><td class="r">{a["cy"]:,}</td><td class="r">{a["bs"]:,}</td><td class="r"><b>{a["tot"]:,}</b></td>'
                f'<td class="r" style="color:{"#2f6f4f" if a["tot"] >= p["tot"] else "#a8442f"}">{sg(a["tot"] - p["tot"])}</td></tr>')
    table = ('<table class="hf-tab"><thead><tr><th>月份（百万美元）</th><th>英国</th><th>开曼群岛</th><th>巴哈马</th><th>三地合计</th><th>合计月变动</th></tr></thead>'
             f'<tbody>{trs}</tbody></table><div class="hf-u">单位：百万美元（TIC 原始口径）。</div>')
    js = "(function(){var R=" + _json.dumps(rows, separators=(",", ":")) + r"""
;var W=1100,H=400,PL=66,PR=150,PT=22,PB=34,iw=W-PL-PR,ih=H-PT-PB;
function fm(n){return n.toLocaleString('en-US',{maximumFractionDigits:0})}
function sg(n){return (n>=0?'+':'−')+fm(Math.abs(n))}
var S=[['tot','三地合计','#3d372f',2.4],['uk','英国','#4f7aa8',1.9],['cy','开曼群岛','#d08a3e',1.9],['bs','巴哈马','#b5a24a',1.9]];
var mx=0;R.forEach(function(r){if(r.tot>mx)mx=r.tot});mx=Math.ceil(mx/200000)*200000;
var n=R.length;function X(i){return PL+iw*i/(n-1)}function Y(v){return PT+ih*(1-v/mx)}
var s='<svg viewBox="0 0 '+W+' '+H+'" class="hf-chart" preserveAspectRatio="xMidYMid meet" font-family="-apple-system,PingFang SC,Helvetica,sans-serif">';
for(var t=0;t<=5;t++){var v=mx*t/5,y=Y(v);s+='<line x1="'+PL+'" y1="'+y+'" x2="'+(PL+iw)+'" y2="'+y+'" stroke="#e6e0d4" stroke-width="0.7"/><text x="'+(PL-8)+'" y="'+(y+4)+'" font-size="11" fill="#4a443c" text-anchor="end">'+fm(v/1000)+'</text>'}
s+='<text x="'+PL+'" y="'+(PT-8)+'" font-size="11" fill="#4a443c">十亿美元</text>';
var lastY='';R.forEach(function(r,i){var y=r.m.slice(0,4);if(y!==lastY&&r.m.slice(5)=='01'){lastY=y;s+='<line x1="'+X(i)+'" y1="'+(PT+ih)+'" x2="'+X(i)+'" y2="'+(PT+ih+4)+'" stroke="#9a9184"/><text x="'+X(i)+'" y="'+(H-12)+'" font-size="11" fill="#4a443c" text-anchor="middle">'+y+'</text>'}});
S.forEach(function(k){s+='<polyline points="'+R.map(function(r,i){return X(i).toFixed(1)+','+Y(r[k[0]]).toFixed(1)}).join(' ')+'" fill="none" stroke="'+k[2]+'" stroke-width="'+k[3]+'" stroke-linejoin="round"/>'});
// 右侧直接标注末值(避免图例对照), 纵向防重叠
var lab=S.map(function(k){return {k:k,y:Y(R[n-1][k[0]]),v:R[n-1][k[0]]}}).sort(function(a,b){return a.y-b.y});
for(var q=1;q<lab.length;q++){if(lab[q].y-lab[q-1].y<15)lab[q].y=lab[q-1].y+15}
lab.forEach(function(l){s+='<circle cx="'+X(n-1)+'" cy="'+Y(l.v)+'" r="3" fill="'+l.k[2]+'"/><text x="'+(PL+iw+8)+'" y="'+(l.y+4)+'" font-size="11.5" fill="'+l.k[2]+'" font-weight="600">'+l.k[1]+' '+fm(l.v/1000)+'</text>'});
// 巴哈马 2025-02 断崖标注
var bi=R.findIndex(function(r){return r.m=='2025-02'});
if(bi>0){var bx=X(bi),by=Y(R[bi].bs);s+='<line x1="'+bx+'" y1="'+(by-3)+'" x2="'+bx+'" y2="'+(by-30)+'" stroke="#7a6f3a" stroke-width="1"/><circle cx="'+bx+'" cy="'+by+'" r="3.2" fill="#fff" stroke="#7a6f3a" stroke-width="1.4"/><text x="'+bx+'" y="'+(by-35)+'" font-size="11.5" fill="#5f5527" font-weight="600" text-anchor="middle">巴哈马 2025-02 月降 19.3 十亿美元</text>'}
R.forEach(function(r,i){var p=i?R[i-1]:null;
 var t='三地合计 <b>'+fm(r.tot)+'</b>'+(p?'（月变动 '+sg(r.tot-p.tot)+'）':'')+'<br>英国 '+fm(r.uk)+' · 开曼 '+fm(r.cy)+' · 巴哈马 '+fm(r.bs)+'<br>（百万美元；TIC 按托管/登记地统计）';
 s+='<circle class="tip-hit" cx="'+X(i).toFixed(1)+'" cy="'+Y(r.tot).toFixed(1)+'" r="9" fill="transparent" data-tip="'+r.m+'||'+t.replace(/"/g,'&quot;')+'"/>'});
s+='</svg>';document.getElementById('hf-box').innerHTML=s})();"""
    foot = ('<div class="sgr-foot"><b>口径：</b>美国财政部 TIC 报告（SLT Table 3）中，英国、开曼群岛、巴哈马<b>登记/托管的美国国债持有额</b>，月度，百万美元。'
            '三地常被作为对冲基金的注册或托管地，但 TIC 按托管账户登记地统计，<b>不是「对冲基金持有」</b>，三地合计也不等于全体对冲基金。'
            '<br>数据在每月中旬发布，滞后约六周。巴哈马 2025-02 当月下降 19,282 百万，图中如实呈现，未平滑。页面只陈述数据，不对原因做判断。</div>')
    return ('<section class="sec" id="hf-ust"><h2>对冲基金常用注册地 · 持美债'
            '<span class="freq-badge freq-monthly">每月更新</span></h2>'
            '<div class="sec-note">英国、开曼群岛、巴哈马登记/托管的美国国债持有额（TIC 月度），2020 年以来的变化。</div>'
            + stat + '<div class="hf-box" id="hf-box"></div>' + table + foot + '<script>' + js + '</script></section>')


def _china_regime_html(cn):
    """中国模式断代监控 —— 旧引擎停摆 / 新引擎接续。"""
    if not cn or not str(cn.get("status", "")).startswith("ok"):
        return ('<p class="empty">中国模式断代数据同步中'
                '（源：NBS 官方月度发布稿 + 东方财富宏观 API）。</p>')
    bd = cn.get("breakdown") or []
    mo = cn.get("monthly") or []
    if not bd and not mo:
        return '<p class="empty">中国模式断代：本期无数据。</p>'

    period = cn.get("period") or "最新期"
    by = {b["key"]: b for b in bd}
    mby = {m["key"]: m for m in mo}

    def v(k, src="bd"):
        d = (by if src == "bd" else mby).get(k)
        return d["value"] if d else None

    # ── 判据: 旧引擎/新引擎 各自成色 ──
    fai, infra, estate = v("fai_total"), v("infra"), v("estate_inv")
    ip_p, manuf = v("ip_products"), v("manuf")
    retail = v("retail_c", "mo")
    old_dead = sum(1 for x in (fai, infra, estate, v("private")) if x is not None and x < 0)
    new_alive = sum(1 for x in (ip_p, manuf) if x is not None and x > 0)

    if old_dead >= 3 and new_alive <= 1:
        verdict, vcls = "旧引擎全线收缩，新引擎尚未接续", "bad"
    elif old_dead >= 2:
        verdict, vcls = "旧引擎多数收缩，新引擎部分接续", "warn"
    else:
        verdict, vcls = "旧引擎尚未全面失速", "ok"

    def fmt(x, unit="%"):
        return "—" if x is None else f"{x:+.1f}{unit}" if unit == "%" else f"{x:.1f}{unit}"

    # ── 分项表(按引擎分组) ──
    GRP = [("old", "旧引擎 · 投资 / 地产 / 信贷"),
           ("new", "新引擎 · 消费 / 产业升级"),
           ("social", "社会压力 · 区域分化")]
    rows = []
    for eng, label in GRP:
        items = [b for b in bd if b["engine"] == eng]
        if not items:
            continue
        rows.append(f'<tr class="crs-grp"><td colspan="4">{label}</td></tr>')
        for b in sorted(items, key=lambda x: x["value"]):
            cls = "neg" if b["value"] < 0 else "pos"
            pk = (f'<span class="crs-pk">伯金斯 2025-12 引 {b["perkins_ref"]}</span>'
                  if b.get("perkins_ref") else "")
            rows.append(
                f'<tr><td class="crs-n">{b["name"]}</td>'
                f'<td class="crs-v {cls}">{b["value"]:+.1f}%</td>'
                f'<td class="crs-b">{b["basis"]}</td><td>{pk}</td></tr>')
    table = "".join(rows)

    # ── 月度总量卡 ──
    cards = []
    for m in mo:
        arrow = ""
        if m.get("mom") is not None:
            arrow = f'<span class="crs-mom {"neg" if m["mom"] < 0 else "pos"}">{m["mom"]:+.2f}</span>'
        cards.append(
            f'<div class="crs-card"><div class="crs-card-n">{m["name"]}</div>'
            f'<div class="crs-card-v">{m["value"]:.2f}<span class="crs-u">{m["unit"]}</span></div>'
            f'<div class="crs-card-m">{m["ym"]} · {m["basis"]} {arrow}</div>'
            f'<div class="crs-card-r">近12月 {m["yr_min"]:.1f} ~ {m["yr_max"]:.1f}（均 {m["yr_avg"]}）</div>'
            f'</div>')

    # ── 拿不到的(诚实边界) ──
    una = "".join(
        f'<li><b>{u["name"]}</b>　伯金斯引 <code>{u["perkins_ref"]}</code>'
        f'<div class="crs-why">{u["reason"]}</div></li>'
        for u in (cn.get("unavailable") or []))

    # ── 出处 ──
    srcs = "".join(
        f'<li><a href="{d["url"]}" target="_blank" rel="noopener">{d["title"]}</a></li>'
        for d in (cn.get("sources") or {}).values())

    err = ""
    if cn.get("errors"):
        err = ('<div class="crs-err">抓取告警：'
               + "；".join(cn["errors"][:4]) + "</div>")

    # ★缓存标注: NBS 抓取失败时分项走缓存, 必须让人看见是旧数据, 不能悄悄用
    _cache_bar = ""
    if cn.get("breakdown_cached"):
        _cache_bar = (f'<div class="crs-cached">⚠ NBS 官方发布稿本次抓取失败，'
                      f'下方 8 项官方分项为 <b>{cn.get("breakdown_cache_age_days","?")} 天前缓存</b>，'
                      f'非本次实时取得；东财月度数据不受影响。</div>')

    return f"""
<div class="crs-wrap">
  {_cache_bar}
  <div class="crs-verdict {vcls}">
    <div class="crs-verdict-t">{verdict}</div>
    <div class="crs-verdict-s">
      {period}累计同比：固投 {fmt(fai)}　地产 {fmt(estate)}　基建 {fmt(infra)}　
      知识产权投资 {fmt(ip_p)}　社零 {fmt(retail)}
    </div>
  </div>

  <p class="crs-intro">
    Ryan Perkins《China's Economic Crossroads》(2025-12-08) 判断：中国已无法靠投资实现充分就业，
    也无法在旧模式的失业问题解决前靠消费拉动增长；结局二元 —— 软着陆，或长期停滞加社会压力。
    本板块把他引用的判据变成可月度跟踪的指标，并与他当时引用的数值逐项对照。
  </p>

  <table class="crs-table">
    <thead><tr><th>分项</th><th>最新</th><th>口径</th><th>对照</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
  <div class="crs-note">以上为 NBS 官方发布稿原文数值，{period}累计同比。</div>

  <div class="crs-cards">{"".join(cards)}</div>

  <details class="crs-det">
    <summary>伯金斯引用但公开源拿不到的（{len(cn.get("unavailable") or [])} 项，不以近似值冒充）</summary>
    <ul class="crs-una">{una}</ul>
  </details>

  <details class="crs-det">
    <summary>数据出处</summary>
    <ul class="crs-src">{srcs}</ul>
    <div class="crs-why">
      月度总量来自东方财富宏观 API；分项来自 NBS 官方英文发布稿（每月 15-16 日更新）。
      ★口径提示：东财「固定资产投资」字段为<b>单月同比</b>，与 NBS <b>累计同比</b>不是同一口径，
      两者并列展示但不可直接比较。
    </div>
  </details>
  {err}
</div>"""



def _wrs_html(w):
    """WRS · Walmart 衰退信号(分母用 ETF 代理, 甲方案: 图上明确标注)。"""
    if not w or not str(w.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(w.get("errors", [])[:2])) if w and w.get("errors") else ""
        return f'<p class="empty">WRS 衰退信号数据同步中{err}。</p>'
    ser = w.get("series") or []
    if len(ser) < 20:
        return '<p class="empty">WRS：历史点不足，暂不成图。</p>'

    vals = [p["v"] for p in ser]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    W, H, PL, PR, PT, PB = 900, 260, 52, 14, 14, 26
    iw, ih = W - PL - PR, H - PT - PB

    def X(i): return PL + iw * i / max(len(ser) - 1, 1)
    def Y(v): return PT + ih * (1 - (v - lo) / rng)

    pts = " ".join(f"{X(i):.1f},{Y(p['v']):.1f}" for i, p in enumerate(ser))
    # 峰值标记
    pk_i = max(range(len(ser)), key=lambda i: ser[i]["v"])
    pk = ser[pk_i]

    # y 轴刻度
    ticks = ""
    for k in range(5):
        v = lo + rng * k / 4
        y = Y(v)
        ticks += (f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" class="wrs-grid"/>'
                  f'<text x="{PL-7}" y="{y+3.5:.1f}" class="wrs-ytick">{v:.2f}</text>')
    # x 轴年份
    xt = ""
    seen = set()
    for i, p in enumerate(ser):
        yr = p["d"][:4]
        if yr not in seen and (i == 0 or i > 8):
            seen.add(yr)
            xt += f'<text x="{X(i):.1f}" y="{H-8}" class="wrs-xtick">{yr}</text>'

    lvl = w.get("level", "green")
    cur, pct = w["latest"], w["pct_rank"]
    newhigh = w.get("is_new_high")

    # ★诚实标注: 当前是否创新高
    hi_txt = ("<b>当前即历史最高</b>" if newhigh else
              f'历史峰值 <b>{w["peak"]:.4f}</b>（{w["peak_date"]}），当前<b>未</b>创新高')

    def sgn(x):
        return "—" if x is None else f'<span class="{"up" if x>0 else "down"}">{x:+.2f}%</span>'

    return f"""
<div class="wrs-wrap">
  <div class="wrs-head">
    <div class="wrs-title">WRS · Walmart 衰退信号
      <span class="wrs-lvl {lvl}">{w.get("level_txt","")}　分位 {pct}%</span>
    </div>
    <div class="wrs-formula">WRS ＝ Walmart 股价 ÷ 奢侈品指数　·　比值上行 = 消费降级 = 衰退压力上升</div>
  </div>

  <div class="wrs-proxy">
    ⚠ <b>分母为代理指标</b>：Jim Paulsen 原式用 <b>S&amp;P Global Luxury Index</b>（S&amp;P 专有指数，
    公开源不可得）。本图分母为 <b>{w["denominator"]["name"]}（{w["denominator"]["sym"]}）</b>
    —— 该 ETF 追踪的正是该指数，且与 Walmart 同为 <b>USD</b> 计价（无汇率噪声）。
    但 ETF 存在管理费、跟踪误差与折溢价，<b>绝对水平不可与 Paulsen 原值直接比对</b>，
    此处只用其<b>方向与历史分位</b>。
  </div>

  <div class="wrs-stat">
    <span>最新 <b>{cur:.4f}</b><i>{w["latest_date"]}</i></span>
    <span>历史分位 <b>{pct}%</b><i>{w["n"]} 个交易日 · 自 {w["start"]}</i></span>
    <span>近 3 月 <b>{sgn(w.get("chg_3m"))}</b><i>季度动能</i></span>
    <span>近 1 年 <b>{sgn(w.get("chg_1y"))}</b><i>年度动能</i></span>
  </div>

  <svg viewBox="0 0 {W} {H}" class="wrs-chart" preserveAspectRatio="xMidYMid meet">
    {ticks}
    <polyline points="{pts}" class="wrs-line"/>
    <circle cx="{X(pk_i):.1f}" cy="{Y(pk['v']):.1f}" r="3.4" class="wrs-peak"/>
    <circle cx="{X(len(ser)-1):.1f}" cy="{Y(vals[-1]):.1f}" r="4" class="wrs-now"/>
    {xt}
    {_hover_bands([X(i) for i in range(len(ser))], [f"{_esc(p['d'])}||WRS {p['v']:.4f}" for p in ser], PT, ih, PL, W - PR)}
  </svg>

  <div class="wrs-foot">
    区间 {lo:.4f} ~ {hi:.4f}　·　{hi_txt}　·　
    实心点＝当前值，空心点＝历史峰值。数据源 Yahoo Finance 日线，随 dashboard 每日更新。
  </div>
</div>"""




def _stock_gold_html(o):
    """道指÷黄金 · 标普500÷黄金 50 年月度比值(对数坐标)。页内 JS 绘制(数据内嵌 JSON), 带时间段选取:
    切换只替换 SVG 内容、容器高度固定 → 不改变页面布局, 左侧菜单与右侧图不跳动。统计量随所选区间重算。"""
    import json as _json
    if not o or not o.get("rows"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">股指/黄金比值数据同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    rows = o["rows"]; td = o.get("today") or {}
    data = {"r": [[r["m"], r["dow"], r["spx"], r["gold"], r["dg"], r["sg"], 0 if r["src"] == "base" else 1] for r in rows],
            "td": {"dg": td.get("dow_gold", o["dg"]["latest_month"]), "dgd": td.get("dow_date", rows[-1]["m"]),
                   "sg": td.get("spx_gold", o["sg"]["latest_month"]), "sgd": td.get("spx_date", rows[-1]["m"])}}
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="sgr-wrap" id="sgz">
  {warn}
  <div class="sgz-ctl">
    <span class="sgz-lab">时间段</span>
    <button type="button" class="sgz-r" data-y="5">5 年</button><button type="button" class="sgz-r" data-y="10">10 年</button>
    <button type="button" class="sgz-r" data-y="20">20 年</button><button type="button" class="sgz-r" data-y="30">30 年</button>
    <button type="button" class="sgz-r on" data-y="0">全部</button>
    <span class="sgz-sep"></span>
    <label class="sgz-lab" lang="zh-CN">自选 <input type="month" id="sgz-from" min="1976-01" lang="zh-CN"> 至 <input type="month" id="sgz-to" lang="zh-CN"></label>
    <button type="button" id="sgz-go">应用</button>
    <span class="sgz-sep"></span>
    <label class="sgz-chk"><input type="checkbox" data-s="dg" checked><i style="background:#4a6fa5"></i>道指÷黄金</label>
    <label class="sgz-chk"><input type="checkbox" data-s="sg" checked><i style="background:#7a8f5a"></i>标普500÷黄金</label>
  </div>
  <div id="sgz-panels"></div>
  <div class="sgr-foot">
    比值＝指数点 ÷ 金价（美元/盎司），对数坐标；比值越低＝股票相对黄金越便宜。月度序列：股指取月末收盘，
    黄金取当月均价（1976-01 至 2026-08 为伦敦金月均价，之后为 COMEX 期金当月日收盘均值）；
    「今日」＝最新股指收盘 ÷ 同日期金收盘。<b>中位数、峰值、谷底、分位都按所选时间段重算</b>（选 5 年就是这 5 年里的中位数与分位，不是 50 年的）。
    数据：道指 1976–1991 fja05680/dow-sp500-100-years，1992 起 Yahoo ^DJI；标普 Yahoo ^GSPC；黄金 datasets/gold-prices（LBMA）+ Yahoo GC=F。随 dashboard 每日更新。
  </div>
  <script type="application/json" id="sgz-data">{js}</script>
</div>"""



def _sgl_html(o):
    """标普500÷黄金 1929 起长历史(对数) + MA40/MA78 月 + 自动「跌破两均线」标记 + 三段回撤。页内 JS 绘制, 悬停每月一点。"""
    import json as _json
    if not o or not o.get("rows"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">标普÷黄金长历史数据同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    rows = o["rows"]
    data = {"r": [[r["m"], r["sg"], r["spx"], r["gold"], r["ma40"], r["ma78"]] for r in rows],
            "ev": o.get("events", []), "dd": o.get("drawdowns", []), "streak": o.get("streak", 0),
            "ma": o.get("ma_latest", {})}
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    ev = "、".join(o.get("events", [])) or "无"
    return f"""
<div class="sgr-wrap" id="sgl">
  {warn}
  <div class="sgz-ctl">
    <span class="sgz-lab">时间段</span>
    <button type="button" class="sgl-r" data-y="20">20 年</button><button type="button" class="sgl-r" data-y="50">50 年</button>
    <button type="button" class="sgl-r on" data-y="0">全部（1929 起）</button>
    <span class="sgz-sep"></span>
    <label class="sgz-chk"><input type="checkbox" id="sgl-ma" checked><i style="background:#c0793a"></i>40 / 78 月均线</label>
    <label class="sgz-chk"><input type="checkbox" id="sgl-ev" checked><i style="background:#b0493a"></i>跌破两线标记</label>
  </div>
  <div id="sgl-box"></div>
  <div class="sgr-foot">
    <b>这是对 StockCharts 公开图「S&amp;P 500 vs. Gold」的自制复现，不是原图数据。</b>比值＝标普500 ÷ 金价（美元/盎司），对数坐标。
    均线为<b>月度 40 期与 78 期</b>（约等于原图周线 170 / 340 期，但窗口不同，数值不会与原图一致）。
    <b>「跌破两线」由规则自动判定</b>：此前 12 个月内曾同时站上两条均线，此后连续 12 个月以上同时低于两线，取起点，间隔至少 24 个月；
    本次判定出 <b>{_esc(ev)}</b>，当前已连续 <b>{o.get("streak", 0)}</b> 个月同时低于两线。这是对历史形态的描述，不构成对未来的判断。
    <b>回撤</b>为标普月度序列的峰→谷跌幅（月均值口径，比日内最高最低口径浅）：
    {"；".join(_esc(d["label"]) + " " + str(d["pct"]) + "%（" + _esc(d["peak_m"]) + "→" + _esc(d["trough_m"]) + "）" for d in o.get("drawdowns", []))}。
    <b>口径说明：</b>① 标普 1929–2026 用 Shiller 月度数据（月均值），与上方 1976 起面板的「月末收盘」口径不同，所以同一个月数值有约 ±4% 的差异；
    ② 灰带为黄金<b>固定官价期</b>（1934-02 至 1971-08，每盎司 35 美元；1934-01 前为 20.67 美元），这段比值基本等于标普指数本身除以常数，不反映黄金市场定价，请勿与 1971 年之后直接比较；
    ③ 本图最后一个月为当月数据，未走完。数据：标普 datasets/s-and-p-500（Shiller），黄金 datasets/gold-prices。随 dashboard 每日更新。
  </div>
  <script type="application/json" id="sgl-data">{js}</script>
</div>"""


def _ust_trio_html(o, which):
    """美债三图之一: which = 'yld' | 'tpm' | 'agg'。数据内嵌 JSON, 页内 JS 绘制(id 前缀 ust-)。"""
    import json as _json
    if not o or not o.get("yields") or o.get("status") == "error":
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">美债图数据同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    if which == "yld":
        data = {"k": "yld", "y2": o["yields"]["y2"], "y10": o["yields"]["y10"], "y30": o["yields"]["y30"], "last": o["yields"]["last"]}
        foot = ("2 年 / 10 年 / 30 年美国国债收益率(%)，FRED 日频→周度末值，2019 年至今；灰带为 2020 年新冠衰退（NBER）。"
                "「曲线倒挂」＝2 年高于 10 年。数据：FRED DGS2 / DGS10 / DGS30。随 dashboard 每日更新。")
    elif which == "tpm":
        data = {"k": "tpm", "tp": o["tpm"]["tp"], "move": o["tpm"]["move"], "y10": o["tpm"]["y10"], "last": o["tpm"]["last"]}
        foot = ("10 年期限溢价（纽约联储 ACM 模型，左轴 %）、10 年收益率（左轴 %）与 MOVE 债市波动率（右轴，指数点）。"
                "MOVE 周度保留周内尖峰；<b>ACM 期限溢价发布滞后数日，末值日期早于其他两条线</b>，悬停处各线标各自日期。"
                "数据：FRED THREEFYTP10 / DGS10，Yahoo ^MOVE（ICE BofA，专有指数的免费历史）。随 dashboard 每日更新。")
    else:
        _a, _b = o["agg"]["agg"], o["agg"]["bnd"]
        _d0 = max(_a[0][0], _b[0][0]) if _a and _b else None
        def _norm(ser):
            base = next((v for d, v in ser if d >= _d0), None) if _d0 else None
            return [[d, round(v / base * 100, 3)] for d, v in ser if base and d >= _d0]
        _la, _lb = o["agg"]["last"].get("agg"), o["agg"]["last"].get("bnd")
        _na, _nb = _norm(_a), _norm(_b)
        data = {"k": "agg", "agg": _na, "bnd": _nb, "last": {"agg": ({"d": _na[-1][0], "v": _na[-1][1]} if _na else None), "bnd": ({"d": _nb[-1][0], "v": _nb[-1][1]} if _nb else None)},
                "px": {"agg": _la, "bnd": _lb}, "d0": _d0}
        foot = ("<b>这不是彭博美国综合债券指数本身（专有、需订阅），而是跟踪该指数的 ETF 价格代理：</b>iShares 核心美国综合债券 ETF（AGG）与先锋整体债券市场 ETF（BND）。"
                "两只 ETF 价格量级不同（AGG 约 95 美元、BND 约 71 美元），所以图中<b>都折算成起点（取两者共同起始日）=100 的相对值</b>画在同一纵轴上，看它们的走势是否一致；最新实际价格见图例括号。纵轴不是指数点位，与彭博终端上的 1 万点量级数值不可对比；"
                "ETF 含管理费与跟踪误差，且分红时价格会下跌一次。数据：Yahoo Finance 日线，近 2 年。随 dashboard 每日更新。")
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""
<div class="sgr-wrap" id="ust-{which}">
  {warn}
  <div id="ust-{which}-box"></div>
  <div class="sgr-foot">{foot}</div>
  <script type="application/json" id="ust-{which}-data">{js}</script>
</div>"""


def _jpy_carry_html(o, which):
    """日元套息: facts | cftc | spread | kline。数据内嵌 JSON, 页内 JS 绘制(id 前缀 jpy-)。"""
    import json as _json
    if not o or o.get("status") == "error" or not o.get("cftc"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">日元套息数据同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    if which == "facts":
        rows = "".join(f'<li><b>{_esc(f["tag"])}</b>　{_esc(f["txt"])}</li>' for f in o.get("facts", []))
        return (f'<div class="sgr-wrap">{warn}<ul class="jpy-facts">{rows}</ul>'
                '<div class="sgr-foot">以上每条都是按固定阈值从官方/公开数据直接算出的<b>事实</b>（CFTC 周度净头寸、日本财务省日债、FRED 美债、Yahoo 汇率），'
                '不含预测、不含买卖建议。「3%」「5%」「160」是你周报里点名的关口，仅用于陈述当前在其上方还是下方。'
                '本页不含主权 CDS（付费数据）与谈判/油价等事件判断。随 dashboard 每日更新（CFTC 每周五美东 15:30 发布，其余日频）。</div></div>')
    if which == "cftc":
        data = {"k": "cftc", "noncomm": o["cftc"]["noncomm"], "lev": o["cftc"]["lev"], "last": o["cftc"]["last"]}
        foot = ("CME 日元期货持仓（CFTC 官方，每周二数据、周五发布）：<b>非商业净头寸</b>＝非商业多头 − 空头（传统报告口径）；"
                "<b>杠杆基金</b>＝TFF 报告里的 Leveraged Funds 净头寸（对冲基金口径，与非商业<b>不是同一个口径</b>，二者并列只为对照）。"
                "正值＝净做多日元期货（押日元升值），负值＝净做空。近 3 年。")
    elif which == "spread":
        data = {"k": "spread", "spread": o["spread"]["spread"], "usdjpy": o["spread"]["usdjpy"], "last": o["spread"]["last"]}
        foot = ("美日 10 年国债利差（美债 10Y 取 FRED，日债 10Y 取日本财务省官方日度数据，百分点，左轴）与美元/日元（Yahoo，周度，<b>右轴已反转：线向上＝日元走强</b>），近 2 年。"
                "利差大＝套息有肉；日元走强是套息平仓的结果之一，但二者相关≠因果。")
    else:
        data = {"k": "kline", "kl": o["kline"]["k"], "rv": o["kline"]["rv"], "last_rv": o["kline"]["last_rv"], "last": o["spread"]["last"]}
        foot = ("美元/日元周 K 线（Yahoo，红涨绿跌的习惯在此用<b>涨＝日元贬值</b>色，下方有说明）与 MA5/10/20/30 周均线；副图为 <b>20 日已实现波动率</b>（日线对数收益率标准差×√252，年化 %）。"
                "<b>这是已实现波动率，不是隐含波动率</b>：CBOE 日元波动率指数 JYVIX 已于 2022-11 停更，免费渠道没有日元隐含波动率，所以用已实现值代理。"
                "MacroMicro 原图的「隐含波动率差值」是其专有构造，本页不复现。")
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""
<div class="sgr-wrap" id="jpy-{which}">
  {warn}
  <div id="jpy-{which}-box"></div>
  <div class="sgr-foot">{foot}</div>
  <script type="application/json" id="jpy-{which}-data">{js}</script>
</div>"""


def _ai_cds_html(o, bbb=None):
    """AI 债务 CDS 快照: 读 data/ai_cds_snapshots.json 的 rows。新闻转引, 非连续序列, 离散点不连线。"""
    import json as _json, html as _h
    rows = (o or {}).get("rows") or []
    if not rows:
        return '<p class="empty">AI 债务 CDS 暂无读数（新闻转引，有报道才记）。</p>'
    colors = {"Oracle": "#c0553a", "CoreWeave": "#6a4c93", "SoftBank": "#2f6f9f", "Nvidia": "#2f8a6a", "Amazon": "#e0a030", "Alphabet": "#8a6d3b", "Meta": "#1f7a7a", "Microsoft": "#555", "Broadcom": "#a05a8a", "SpaceX": "#444", "STMicroelectronics": "#999"}
    zh = {"Oracle": "甲骨文 Oracle", "CoreWeave": "CoreWeave", "SoftBank": "软银 SoftBank"}
    by = {}
    for r in rows: by.setdefault(r["name"], []).append(r)
    for k in by: by[k].sort(key=lambda r: r["asof"])
    def _mark(r):
        n = r.get("note") or ""
        return "≥" if ("past" in n or "blew" in n or "超过" in n) else ("近 " if "near" in n else "")
    order = sorted(by, key=lambda n: -by[n][-1]["bp"])
    # 顶部: 每家最近读数
    cards = ""
    for k in order:
        L = by[k][-1]; prev = by[k][-2] if len(by[k]) > 1 else None
        ge = _mark(L)
        chg = ""
        if prev:
            d = L["bp"] - prev["bp"]
            if _mark(L) or _mark(prev):
                chg = f'<i>较 {prev["asof"][5:]} {_mark(prev)}{prev["bp"]:g} bp：两端含下限或近似值，不算确切变动</i>'
            else:
                chg = f'<i>较 {prev["asof"][5:]} {prev["bp"]:g} bp：{d:+g} bp</i>'
        cards += (f'<div class="aic-card" style="border-top:3px solid {colors.get(k, "#888")}"><div class="aic-n">{_h.escape(zh.get(k, k))}</div>'
                  f'<div class="aic-v">{ge}{L["bp"]:g}<small> bp</small></div><div class="aic-d">{L["asof"]}　{chg}</div></div>')
    # 明细表
    trs = ""
    for r in sorted(rows, key=lambda r: (r["asof"], r["name"]), reverse=True):
        cf = ' <b style="color:#c0553a">⚠来源数值冲突</b>' if r.get("conflict") else ""
        trs += (f'<tr><td style="white-space:nowrap">{r["asof"]}</td><td style="white-space:nowrap">{_h.escape(zh.get(r["name"], r["name"]))}</td><td style="text-align:right;white-space:nowrap"><b>{_mark(r)}{r["bp"]:g}</b></td>'
                f'<td><a href="{_h.escape(r["src_url"])}" target="_blank" rel="noopener" style="color:#2f6f9f">{_h.escape(r["src_name"])}</a></td>'
                f'<td>{_h.escape(r["basis"])}</td><td>{_h.escape(r.get("note", ""))}{cf}</td></tr>')
    # ── 图 A: 甲骨文近 3 年(纵轴按 Oracle+BBB 缩放) ──
    import datetime as _dt
    bser = (bbb or {}).get("series") or []
    def _chart(sel, title, hi_cap=None, with_bbb=False, lab_last=None, h=300):
        rs = [r for r in rows if sel(r)]
        if not rs: return ""
        W, H, PL, PR, PT, PB = 900, h, 54, (96 if with_bbb else 22), 14, 26
        d0 = min([r["asof"] for r in rs] + ([bser[0][0]] if (with_bbb and bser) else []))
        d1 = max([r["asof"] for r in rs] + ([bser[-1][0]] if (with_bbb and bser) else []))
        span = max((_dt.date.fromisoformat(d1) - _dt.date.fromisoformat(d0)).days, 1)
        _pad = 0.08 if span <= 200 else 0.0
        X = lambda dd: PL + (W - PL - PR) * (_pad + (1 - 2 * _pad) * ((_dt.date.fromisoformat(dd) - _dt.date.fromisoformat(d0)).days / span))
        vals = [r["bp"] for r in rs] + ([p[1] for p in bser] if (with_bbb and bser) else [])
        hi = (hi_cap or max(vals)) * 1.12; lo = 0
        Y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
        g = ""; step = 50 if hi <= 400 else (100 if hi <= 800 else 200); v = 0
        while v <= hi:
            g += f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="sgr-grid"/><text x="{PL-6}" y="{Y(v)+3.5:.1f}" class="sgr-yt">{v}</text>'; v += step
        g += f'<text x="{PL-6}" y="10" class="sgr-yt">bp</text>'
        if span > 200:
            seen = set(); y0 = int(d0[:4])
            for yy in range(y0, int(d1[:4]) + 1):
                for mm in ("01", "07"):
                    dd = f"{yy}-{mm}-01"
                    if d0 <= dd <= d1: g += f'<line x1="{X(dd):.1f}" y1="{PT}" x2="{X(dd):.1f}" y2="{H-PB}" stroke="#eee8dc" stroke-width="1"/><text x="{X(dd):.1f}" y="{H-8}" class="sgr-xt">{dd[2:7]}</text>'
        else:
            for dd in sorted({r["asof"] for r in rs}): g += f'<text x="{X(dd):.1f}" y="{H-8}" class="sgr-xt">{dd[5:]}</text>'
        if with_bbb and bser:
            g += '<polyline points="' + " ".join(f"{X(p[0]):.1f},{Y(p[1]):.1f}" for p in bser) + '" fill="none" stroke="#b9b2a6" stroke-width="1.8"/>'
            g += f'<text x="{PL+6}" y="{Y(bser[0][1])-8:.1f}" style="font-size:11px;fill:#6b645a">灰线：BBB 档全行业利差（行业背景，不是甲骨文）</text>'
        # Oracle 相邻读数虚线(>120天断开)
        byname = {}
        for r in rs: byname.setdefault(r["name"], []).append(r)
        for nm, lst in byname.items():
            if nm != "Oracle": continue
            dm = {}
            for r in lst: dm.setdefault(r["asof"], []).append(r["bp"])
            seg = []; segs = []
            for dd in sorted(dm):
                if seg and (_dt.date.fromisoformat(dd) - _dt.date.fromisoformat(seg[-1][0])).days > 120: segs.append(seg); seg = []
                seg.append((dd, sum(dm[dd]) / len(dm[dd])))
            segs.append(seg)
            for sg in segs:
                if len(sg) > 1: g += '<polyline points="' + " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in sg) + f'" fill="none" stroke="{colors[nm]}" stroke-width="1.5" stroke-dasharray="4 3" opacity=".7"/>'
        # 点: 同日多读数横向错开
        hit = ""; same = {}
        for r in rs: same.setdefault((r["name"], r["asof"]), []).append(r)
        for (nm, dd), lst in same.items():
            lst.sort(key=lambda r: r["bp"])
            for k, r in enumerate(lst):
                off = (k - (len(lst) - 1) / 2) * 9; cx = X(dd) + off; cy = Y(r["bp"]); c = colors.get(nm, "#888"); mk = _mark(r)
                if mk: g += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="#fff" stroke="{c}" stroke-width="2.2"/>'
                else:  g += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{c}" stroke="#fff" stroke-width="1.2"/>'
                tip = f'{r["asof"]}||{zh.get(nm, nm)} {mk}{r["bp"]:g} bp<br>{_h.escape(r["src_name"])}'
                hit += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="transparent" data-tip="{tip}" class="tip-hit"/>'
        # 标签放置器: 同日多读数合并为一个标签; 逐个尝试候选位置, 与已放矩形/点相交则换位, 避免重叠
        placed = []
        def _rect(x, y, w, hh): return (x, y - hh, x + w, y + 3)
        def _hit(r1, r2): return not (r1[2] < r2[0] or r2[2] < r1[0] or r1[3] < r2[1] or r2[3] < r1[1])
        pts_rects = []
        for (nm, dd), lst in same.items():
            for k, r in enumerate(sorted(lst, key=lambda r: r["bp"])):
                cx = X(dd) + (k - (len(lst) - 1) / 2) * 9; cy = Y(r["bp"]); pts_rects.append((cx - 8, cy - 8, cx + 8, cy + 8))
        if lab_last:
            want = lab_last(rs)
            groups = {}
            for r in want: groups.setdefault((r["name"], r["asof"]), []).append(r)
            # 右缘簇: 最近 5 个读数日(含 2026-09-11 以后)的标签统一放到右侧标签栏, 按 y 排序等距, 细引线连点
            _all = sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))
            _right = [kv for kv in _all if kv[0][1] >= "2026-09-11"]
            _left = [kv for kv in _all if kv[0][1] < "2026-09-11"]
            if with_bbb and _right:
                items = []
                for (nm, dd), lst in _right:
                    for r in sorted(lst, key=lambda r: r["bp"]):
                        k = sorted(same[(nm, dd)], key=lambda q: q["bp"]).index(r); n_ = len(same[(nm, dd)])
                        items.append((r, X(dd) + (k - (n_ - 1) / 2) * 9, Y(r["bp"])))
                items.sort(key=lambda t: t[2])                      # 自上而下
                ys = [t[2] for t in items]; gap = 15.0
                for i in range(1, len(ys)):                         # 保证相邻标签 >= gap
                    if ys[i] - ys[i - 1] < gap: ys[i] = ys[i - 1] + gap
                over = ys[-1] - (H - PB - 4)
                if over > 0: ys = [y - over for y in ys]
                lx = W - PR + 14
                for (r, px, py), ly in zip(items, ys):
                    g += f'<line x1="{px + 6:.1f}" y1="{py:.1f}" x2="{lx - 3:.1f}" y2="{ly - 4:.1f}" stroke="#c9c2b6" stroke-width=".8"/>'
                    g += f'<text x="{lx:.1f}" y="{ly:.1f}" style="font-size:11px;fill:#3d372f;text-anchor:start">{r["asof"][5:]}　{_mark(r)}{r["bp"]:g}</text>'
                    placed.append(_rect(lx, ly, 70, 12))
            for (nm, dd), lst in (_left if (with_bbb and _right) else _all):
                lst = sorted(lst, key=lambda r: r["bp"])
                txt = "/".join(f'{_mark(r)}{r["bp"]:g}' for r in lst)
                cx = X(dd); cy = sum(Y(r["bp"]) for r in lst) / len(lst)
                tw = 6.6 * len(txt) + 4
                done = False
                for dy in (-16, 22, -32, 38, -48, 54):
                    for ax in ("middle", "end", "start"):
                        x0 = cx - tw / 2 if ax == "middle" else (cx - tw + 4 if ax == "end" else cx - 4)
                        rect = _rect(x0, cy + dy, tw, 12)
                        if rect[0] < PL - 2 or rect[2] > W - 2 or rect[1] < 2: continue
                        if any(_hit(rect, q) for q in placed) or any(_hit(rect, q) for q in pts_rects): continue
                        placed.append(rect); tx = (cx if ax == "middle" else (cx + 4 if ax == "end" else cx - 4))
                        if abs(dy) > 24: g += f'<line x1="{cx:.1f}" y1="{cy + (-8 if dy < 0 else 8):.1f}" x2="{cx:.1f}" y2="{cy + dy + (3 if dy < 0 else -9):.1f}" stroke="#b9b2a6" stroke-width=".8"/>'
                        g += f'<text x="{tx:.1f}" y="{cy + dy:.1f}" style="font-size:11px;fill:#3d372f;text-anchor:{ax}">{txt}</text>'
                        done = True; break
                    if done: break
        key = ""
        if with_bbb:
            key = (f'<circle cx="{PL+10}" cy="{PT+8}" r="5" fill="#c0553a" stroke="#fff"/><text x="{PL+19}" y="{PT+12}" style="font-size:11px;fill:#3d372f">实心＝原文给了确切数字</text>'
                   f'<circle cx="{PL+160}" cy="{PT+8}" r="5" fill="#fff" stroke="#c0553a" stroke-width="2"/><text x="{PL+169}" y="{PT+12}" style="font-size:11px;fill:#3d372f">空心＝原文只给「超过」或「接近」</text>')
        g += key
        return f'<div class="sgr-title" style="margin-top:8px">{title}</div><svg viewBox="0 0 {W} {H}" class="sgr-chart aic-svg" style="height:{H-30}px" preserveAspectRatio="xMidYMid meet">{g}{hit}</svg>'
    def _lab_oracle(rs):
        return sorted([r for r in rs if r["name"] == "Oracle"], key=lambda r: (r["asof"], r["bp"]))
    chart = _chart(lambda r: r["name"] == "Oracle", "甲骨文 5 年期 CDS · 近 3 年（有报道的读数；灰线为 BBB 全行业背景）", hi_cap=None, with_bbb=True, lab_last=_lab_oracle, h=300)
    others = [r for r in rows if r["name"] != "Oracle"]
    chart2 = (_chart(lambda r: r["name"] != "Oracle", "其他 AI 债务标的（读数很少，纵轴单独缩放）", lab_last=lambda rs: [by[n][-1] for n in by if n != "Oracle"], h=240, hi_cap=1200) if others else "")
    chart = chart + chart2
    leg = "".join(f'<span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{colors.get(k, "#888")};margin-right:5px"></i>{_h.escape(zh.get(k, k))}</span>' for k in order)
    return f"""
<div class="sgr-wrap">
  <div class="aic-row">{cards}</div>
  <div class="sgz-st" style="margin-top:8px">{leg}</div>
  {chart}
  <div style="font-size:12px;color:#3d372f;margin:2px 0 4px">每个圆点＝一个报道里的读数；<b>甲骨文的虚线只是把相邻两次报道连起来（相隔超过 120 天不连）</b>，两点之间<b>不是日更行情、也没有插值</b>，中间的涨跌图上看不到；<b>空心圆＝原文只给了「超过」或「接近」</b>（下限或近似值），实心圆＝原文给了确切数字。<b>灰色实线是 BBB 档全行业利差（FRED 日度，换算成 bp），是行业背景，不是甲骨文自己的。</b>2025-11 之前新闻里没有甲骨文 CDS 的报道，所以三年里前约 2 年多是空白，不是没数据被我藏起来。</div>
  <div class="sgr-title" style="margin-top:10px">全部读数</div>
  <div style="overflow-x:auto"><table class="aic-tab"><thead><tr><th>日期</th><th>标的</th><th style="text-align:right">bp</th><th>来源</th><th>口径</th><th>备注</th></tr></thead><tbody>{trs}</tbody></table></div>
  <div class="sgr-foot"><b>5 年期单名 CDS 利差（bp）</b>：每年为对冲 100 万美元债务付的保费 ≈ 利差 × 100 美元（288 bp ≈ 2.88 万美元）。
  <b>数据来自 Reuters 等新闻转引（S&amp;P Global Market Intelligence / LSEG 口径），不是可日更的付费序列</b>：每个读数一个圆点、<b>不连线</b>，点与点之间的空白＝当天没有报道，不是没变化；
  「≥」「近」沿用原文措辞（盘中近似或下限），不当收盘精确值。与上方的 BBB OAS 是<b>两个口径</b>（BBB OAS 是全行业评级档利差，这里是单名 CDS）。
  更新方式：每个工作日由日报任务检索当日新闻，有来源链接且通过入库校验才写入，查不到就写「当日无新读数」。</div>
</div>"""


def _tfp_sentiment_html(o):
    """密歇根信心(左轴,月) vs TFP 相对趋势(右轴,季, 普通+剔除开工率两口径)。每月一个悬停点。"""
    if not o or not o.get("tfp") or not o.get("umcsent"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">生产率/信心数据同步中{("：" + _esc(err)) if err else ""}。</p>'
    um = [x for x in o["umcsent"] if x["m"] >= "1978-01"]
    tq = {x["q"]: x for x in o["tfp"]}
    W, H, PL, PR, PT, PB = 900, 300, 44, 50, 14, 24
    iw, ih = W - PL - PR, H - PT - PB
    n = len(um)

    def X(i): return PL + iw * i / max(n - 1, 1)
    def YL(v): return PT + ih * (1 - (v - 40) / 80)          # 40~120
    def YR(v): return PT + ih * (1 - (v + 0.06) / 0.11)      # -6%~+5%

    def qof(m):
        return f"{m[:4]}:Q{(int(m[5:7]) - 1) // 3 + 1}"
    g = ""
    for v in range(40, 121, 20):
        g += (f'<line x1="{PL}" y1="{YL(v):.1f}" x2="{W-PR}" y2="{YL(v):.1f}" class="tfs-grid"/>'
              f'<text x="{PL-6}" y="{YL(v)+3.5:.1f}" class="tfs-yl">{v}</text>')
    for v in (-0.06, -0.04, -0.02, 0, 0.02, 0.04):
        g += f'<text x="{W-PR+6}" y="{YR(v)+3.5:.1f}" class="tfs-yr">{v*100:+.0f}%</text>'.replace("+0%", "0%")
    g += f'<line x1="{PL}" y1="{YR(0):.1f}" x2="{W-PR}" y2="{YR(0):.1f}" class="tfs-zero"/>'
    xt = "".join(f'<text x="{X(i):.1f}" y="{H-6}" class="tfs-xt">{x["m"][:4]}</text>'
                 for i, x in enumerate(um) if x["m"].endswith("-01") and int(x["m"][:4]) % 4 == 0)
    sent = " ".join(f"{X(i):.1f},{YL(x['v']):.1f}" for i, x in enumerate(um))

    def step(key):
        pts, last = [], None
        for i, x in enumerate(um):
            t = tq.get(qof(x["m"]))
            if t is None:
                continue
            y = YR(t[key])
            if last is not None and abs(y - last) > 1e-6:
                pts.append(f"{X(i):.1f},{last:.1f}")
            pts.append(f"{X(i):.1f},{y:.1f}"); last = y
        return " ".join(pts)
    tips = []
    for x in um:
        t = tq.get(qof(x["m"]))
        extra = (f"<br>" + _esc(f"TFP 相对趋势（{qof(x['m']).replace(':', ' ')}）：普通 {t['raw']*100:+.1f}% · 剔除开工率 {t['util']*100:+.1f}%")
                 if t else "<br>" + _esc("TFP：该季尚未发布"))
        tips.append(_esc(x["m"]) + "||" + _esc(f"消费者信心 {x['v']:.1f}") + extra)
    band = _hover_bands([X(i) for i in range(n)], tips, PT, ih, PL, W - PR)
    lt = o["tfp"][-1]; lu = um[-1]
    lo = min(um, key=lambda x: x["v"])
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="tfs-wrap">
  {warn}
  <div class="sgr-stat">
    <span>消费者信心 <b>{lu['v']:.1f}</b><i>{lu['m']} · 1978 年以来最低 {lo['v']:.1f}（{lo['m']}）</i></span>
    <span>TFP 相对趋势·普通 <b>{lt['raw']*100:+.1f}%</b><i>{lt['q'].replace(':', ' ')}</i></span>
    <span>TFP 相对趋势·剔除开工率 <b>{lt['util']*100:+.1f}%</b><i>{lt['q'].replace(':', ' ')}</i></span>
    <span>相关系数 <b>{o.get('corr_raw', '—')}</b><i>信心 vs TFP 普通口径（季度，1978 年起）</i></span>
  </div>
  <div class="tfs-legend"><i class="l1"></i>密歇根消费者信心指数（左轴，月度）<i class="l2"></i>TFP 相对趋势·普通（右轴，季度）<i class="l3"></i>TFP 相对趋势·剔除开工率（右轴）</div>
  <svg viewBox="0 0 {W} {H}" class="sgr-chart" preserveAspectRatio="xMidYMid meet">
    {g}
    <polyline points="{step('util')}" fill="none" stroke="#9fc5e8" stroke-width="1.2" stroke-dasharray="3 2"/>
    <polyline points="{step('raw')}" fill="none" stroke="#5b9bd5" stroke-width="1.6"/>
    <polyline points="{sent}" fill="none" stroke="#1f3a68" stroke-width="1.3"/>
    {xt}{band}
  </svg>
  <div class="sgr-foot">
    复刻 BofA Global Research「全要素生产率低于趋势水平」（Chart 10）。TFP＝旧金山联储 Fernald 季度 TFP（美国商业部门，{_esc(o.get('tfp_vintage', ''))} 版），
    趋势＝每季用过去 10 年（40 季）对数水平线性拟合，右轴为偏离该趋势的百分比；BofA 未公布趋势算法与口径，本图为公开数据复刻，
    数值与原图不完全一致——普通口径与剔除开工率口径差异可达 2 个百分点，一并列出。信心指数：FRED UMCSENT。
    TFP 每季更新、信心指数每月更新，随 dashboard 每日检查。
  </div>
</div>"""



def _llm_token_html(o):
    """Silicon Data LLM Token 支出指数(日度, 美元/百万 token): 全市场 + 开源 + 闭源三线, 每日悬停。"""
    ser = (o or {}).get("series") or []
    if len(ser) < 3:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">LLM Token 指数同步中{("：" + _esc(err)) if err else ""}。</p>'
    W, H, PL, PR, PT, PB = 900, 260, 46, 16, 14, 24
    iw, ih = W - PL - PR, H - PT - PB
    n = len(ser)
    hi = max(max(x["prop"] for x in ser), max(x["all"] for x in ser)) * 1.08
    lo = 0.0

    def X(i): return PL + iw * i / max(n - 1, 1)
    def Y(v): return PT + ih * (1 - (v - lo) / (hi - lo))
    g = ""
    step = 0.5 if hi <= 3 else 1.0
    v = 0.0
    while v <= hi:
        g += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="sgr-grid"/>'
              f'<text x="{PL-6}" y="{Y(v)+3.5:.1f}" class="sgr-yt">${v:.1f}</text>')
        v += step
    xt = "".join(f'<text x="{X(i):.1f}" y="{H-6}" class="sgr-xt">{x["d"][5:]}</text>'
                 for i, x in enumerate(ser) if i % max(1, n // 8) == 0 or i == n - 1)
    lines = ""
    for k, col, wd, dash in (("prop", "#b07a5a", 1.3, ""), ("all", "#1f3a68", 2.0, ""), ("open", "#7a8f5a", 1.3, "")):
        pts = " ".join(f"{X(i):.1f},{Y(x[k]):.1f}" for i, x in enumerate(ser))
        lines += f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{wd}"/>'
    tips = [_esc(x["d"]) + "||" + _esc(f"全市场 ${x['all']:.4f}") + "<br>" +
            _esc(f"闭源模型 ${x['prop']:.4f} · 开源模型 ${x['open']:.4f}（每百万 token）") for x in ser]
    band = _hover_bands([X(i) for i in range(n)], tips, PT, ih, PL, W - PR)
    L, lo_x, hi_x = o["latest"], o["lo"], o["hi"]
    c7 = o.get("chg_7d")
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="tfs-wrap">
  {warn}
  <div class="sgr-stat">
    <span>全市场 <b>${L['all']:.4f}</b><i>{L['d']} · 每百万 token</i></span>
    <span>近 7 日 <b>{'—' if c7 is None else f'{c7:+.1f}%'}</b><i>全市场</i></span>
    <span>闭源 / 开源 <b>${L['prop']:.2f} / ${L['open']:.2f}</b><i>闭源约为开源 {L['prop']/L['open']:.1f} 倍</i></span>
    <span>本站存档区间 <b>${lo_x['all']:.2f} ~ ${hi_x['all']:.2f}</b><i>{ser[0]['d']} 起 · 低点 {lo_x['d']}</i></span>
  </div>
  <div class="tfs-legend"><i class="l1"></i>全市场（用量加权）<i style="border-color:#b07a5a"></i>闭源模型<i style="border-color:#7a8f5a"></i>开源模型</div>
  <svg viewBox="0 0 {W} {H}" class="sgr-chart" preserveAspectRatio="xMidYMid meet">{g}{lines}{xt}{band}</svg>
  <div class="sgr-foot">
    Silicon Data LLM Token Expenditure Index（Bloomberg 代码 SDLLMTK）：全市场按实际用量加权的每百万 token 价格，反映「花出去的钱」而非标价，
    模型结构向便宜模型迁移也会拉低它。官方只公开滚动 7 天、不提供历史下载，本站每天抓取追加自建历史；
    2026-08-22 之前的数据（彭博图中 2025-12 约 $1.05、2026-05 下旬高点约 $2.05）拿不到逐日原值，未画入。
    8/22–9/28 种子数据取自第三方每日存档，与官方页面重叠日逐日核对一致。随 dashboard 每日更新。
  </div>
</div>"""



def _ai_capex_html(o):
    """中美 AI 资本开支(季度, 美元十亿; 美国五家堆叠 vs 中国三家堆叠) + 美国数据中心建设支出(月度, 折年率)。"""
    tbl = [r for r in (o or {}).get("table", []) if r.get("us") is not None and r.get("cn") is not None]
    dc = (o or {}).get("dc") or []
    if len(tbl) < 4:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">中美 AI 资本开支同步中{("：" + _esc(err)) if err else ""}。</p>'
    US_C = {"亚马逊": "#2f4b7c", "微软": "#4a6fa5", "谷歌": "#6f93c4", "Meta": "#9ab4d8", "甲骨文": "#c5d4ea"}
    CN_C = {"阿里": "#b0613e", "腾讯": "#d08f6a", "百度": "#e8bfa3"}
    W, H, PL, PR, PT, PB = 900, 300, 50, 16, 14, 26
    iw, ih = W - PL - PR, H - PT - PB
    n = len(tbl)
    top = max(r["us"] for r in tbl) * 1.1
    slot = iw / n
    bw = slot * 0.36

    def Y(v): return PT + ih * (1 - v / top)
    g = ""
    stepv = 50 if top > 150 else 25
    v = 0
    while v <= top:
        g += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="sgr-grid"/>'
              f'<text x="{PL-6}" y="{Y(v)+3.5:.1f}" class="sgr-yt">${v:g}B</text>')
        v += stepv
    bars, xt, xs, tips = "", "", [], []
    for i, r in enumerate(tbl):
        x0 = PL + slot * i + slot * 0.12
        base = 0.0
        for nm, col in US_C.items():
            val = r["us_parts"][nm]
            bars += f'<rect x="{x0:.1f}" y="{Y(base+val):.1f}" width="{bw:.1f}" height="{Y(base)-Y(base+val):.2f}" fill="{col}"/>'
            base += val
        base = 0.0
        x1 = x0 + bw + slot * 0.04
        for nm, col in CN_C.items():
            val = r["cn_parts_rmb"][nm] / r["fx"]
            bars += f'<rect x="{x1:.1f}" y="{Y(base+val):.1f}" width="{bw:.1f}" height="{max(Y(base)-Y(base+val),0.3):.2f}" fill="{col}"/>'
            base += val
        if r["q"].endswith("Q1") or i == n - 1:
            xt += f'<text x="{PL + slot*(i+0.5):.1f}" y="{H-8}" class="sgr-xt">{r["q"][:4]} {r["q"][4:]}</text>'
        xs.append(PL + slot * (i + 0.5))
        us_d = " · ".join(f"{k} {v:.1f}" for k, v in r["us_parts"].items())
        cn_d = " · ".join(f"{k} {v:.1f}" for k, v in r["cn_parts_rmb"].items())
        tips.append(_esc(r["q"]) + "||" + _esc(f"美国五家 ${r['us']:.1f}B · 中国三家 ${r['cn']:.1f}B · 美/中 {r['us']/r['cn']:.1f} 倍") +
                    "<br>" + _esc(f"美国（十亿美元）：{us_d}") + "<br>" +
                    _esc(f"中国（十亿人民币）：{cn_d}；汇率 {r['fx']:.3f}"))
    band = _hover_bands(xs, tips, PT, ih, PL, W - PR)
    L = tbl[-1]; F = next((r for r in tbl if r["q"] == f"{int(L['q'][:4])-1}{L['q'][4:]}"), None)
    yoy = lambda a, b: f"{(a/b-1)*100:+.0f}%" if b else "—"
    leg = "".join(f'<i style="background:{c};border:none;height:9px;width:12px"></i>{k}' for k, c in US_C.items())
    leg += '<span style="width:14px"></span>' + "".join(f'<i style="background:{c};border:none;height:9px;width:12px"></i>{k}' for k, c in CN_C.items())
    # 月度数据中心
    dc_html = ""
    d2 = [x for x in dc if x["m"] >= "2014-01"]
    if len(d2) > 12:
        W2, H2 = 900, 200
        ih2 = H2 - PT - PB
        top2 = max(x["v"] for x in d2) * 1.12
        X2 = lambda i: PL + iw * i / (len(d2) - 1)
        Y2 = lambda v: PT + ih2 * (1 - v / top2)
        g2 = ""
        v = 0
        while v <= top2:
            g2 += (f'<line x1="{PL}" y1="{Y2(v):.1f}" x2="{W2-PR}" y2="{Y2(v):.1f}" class="sgr-grid"/>'
                   f'<text x="{PL-6}" y="{Y2(v)+3.5:.1f}" class="sgr-yt">${v:g}B</text>')
            v += 20
        pts = " ".join(f"{X2(i):.1f},{Y2(x['v']):.1f}" for i, x in enumerate(d2))
        xt2 = "".join(f'<text x="{X2(i):.1f}" y="{H2-8}" class="sgr-xt">{x["m"][:4]}</text>'
                      for i, x in enumerate(d2) if x["m"].endswith("-01") and int(x["m"][:4]) % 2 == 0)
        tips2 = [_esc(x["m"]) + "||" + _esc(f"数据中心建设支出 ${x['v']:.1f}B（折年率）" + (f"·{x['flag']}" if x["flag"] else "")) for x in d2]
        band2 = _hover_bands([X2(i) for i in range(len(d2))], tips2, PT, ih2, PL, W2 - PR)
        ld = d2[-1]; ly = next((x for x in d2 if x["m"] == f"{int(ld['m'][:4])-1}{ld['m'][4:]}"), None)
        dc_html = f"""
  <div class="sgr-title">美国数据中心建设支出（月度，经季调折年率）</div>
  <div class="sgr-stat"><span>最新 <b>${ld['v']:.1f}B</b><i>{ld['m']} {ld['flag']}</i></span>
    <span>同比 <b>{yoy(ld['v'], ly['v']) if ly else '—'}</b><i>较 {ly['m'] if ly else '—'}（${ly['v']:.1f}B）</i></span>
    <span>2014 年起 <b>{d2[0]['v']:.1f} → {ld['v']:.1f}</b><i>十亿美元</i></span></div>
  <svg viewBox="0 0 {W2} {H2}" class="sgr-chart" preserveAspectRatio="xMidYMid meet">{g2}
    <polyline points="{pts}" fill="none" stroke="#2f4b7c" stroke-width="1.6"/>{xt2}{band2}</svg>"""
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="tfs-wrap">
  {warn}
  <div class="sgr-title">中美科技巨头资本开支（季度，十亿美元）</div>
  <div class="sgr-stat">
    <span>美国五家 <b>${L['us']:.1f}B</b><i>{L['q']} · 同比 {yoy(L['us'], F['us']) if F else '—'}</i></span>
    <span>中国三家 <b>${L['cn']:.1f}B</b><i>{L['q']} · 同比 {yoy(L['cn'], F['cn']) if F else '—'}</i></span>
    <span>美 / 中 <b>{L['us']/L['cn']:.1f} 倍</b><i>{L['q']}</i></span>
    <span>近四季合计 <b>${sum(r['us'] for r in tbl[-4:]):.0f}B / ${sum(r['cn'] for r in tbl[-4:]):.0f}B</b><i>美国 / 中国</i></span>
  </div>
  <div class="tfs-legend">{leg}</div>
  <svg viewBox="0 0 {W} {H}" class="sgr-chart" preserveAspectRatio="xMidYMid meet">{g}{bars}{xt}{band}</svg>
  {dc_html}
  <div class="sgr-foot">
    资本开支＝现金流量表「购置固定资产」类支出（含数据中心、服务器，也含非 AI 部分，与原图高盛「AI capex」口径不完全相同）。
    季度按自然季归属（甲骨文财季 6–8 月记为三季度，其余同理），各季要等五家都发布才计入。美国五家：SEC 官方 XBRL 财务数据；
    中国三家：阿里、百度取 SEC 6-K 原文，腾讯取季报新闻稿表格，阿里/腾讯各季加总与年报逐一相符；人民币按当季美元兑人民币均价（FRED DEXCHUS）折算。
    字节跳动未上市、不公布资本开支，未计入；原图 2026–2027 年为高盛预测，本图只画已发布数据。
    数据中心：美国统计局 C30 私营建筑支出「Data center」项（经季调折年率，最新月为初值，之后会修订）。季报每季、数据中心每月更新，随 dashboard 每日检查。
  </div>
</div>"""



def _gold_oil_html(o):
    """金油比(黄金 ÷ WTI, 月度, 1971 起) 对数轴 + 长期均值/中位线, 每月悬停。"""
    import math
    ser = (o or {}).get("rows") or []
    if len(ser) < 24:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">金油比同步中{("：" + _esc(err)) if err else ""}。</p>'
    st = o["stats"]; td = o.get("today") or {}
    W, H, PL, PR, PT, PB = 900, 300, 46, 16, 14, 26
    iw, ih = W - PL - PR, H - PT - PB
    n = len(ser)
    lo, hi = math.log10(5), math.log10(120)
    X = lambda i: PL + iw * i / (n - 1)
    Y = lambda v: PT + ih * (1 - (math.log10(v) - lo) / (hi - lo))
    g = ""
    for v in (5, 10, 20, 40, 80):
        g += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="sgr-grid"/>'
              f'<text x="{PL-6}" y="{Y(v)+3.5:.1f}" class="sgr-yt">{v}</text>')
    for v, lab, dash in ((st["mean"], f"1971 年以来均值 {st['mean']:.1f}", "5,4"), (st["median"], f"中位数 {st['median']:.1f}", "2,3")):
        g += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#b07a5a" stroke-width="1" stroke-dasharray="{dash}"/>'
              f'<text x="{W-PR-4}" y="{Y(v)-4:.1f}" class="sgr-yt" text-anchor="end" fill="#b07a5a">{lab}</text>')
    xt = "".join(f'<text x="{X(i):.1f}" y="{H-8}" class="sgr-xt">{x["m"][:4]}</text>'
                 for i, x in enumerate(ser) if x["m"].endswith("-01") and int(x["m"][:4]) % 5 == 0)
    pts = " ".join(f"{X(i):.1f},{Y(max(x['r'],5.01)):.1f}" for i, x in enumerate(ser))
    tips = [_esc(x["m"]) + "||" + _esc(f"金油比 {x['r']:.1f}") + "<br>" +
            _esc(f"黄金 ${x['gold']:,.0f}/盎司 · WTI ${x['oil']:.2f}/桶（月均）" + ("" if x["src"] == "base" else "·本月实时")) for x in ser]
    band = _hover_bands([X(i) for i in range(n)], tips, PT, ih, PL, W - PR)
    cur = td.get("ratio", ser[-1]["r"])
    oil_at_mean = (td.get("gold") or ser[-1]["gold"]) / st["mean"]
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="tfs-wrap">
  {warn}
  <div class="sgr-stat">
    <span>今日金油比 <b>{cur:.1f}</b><i>{_esc(td.get('date',''))} · 金 ${td.get('gold',0):,.0f} / WTI ${td.get('oil',0):.2f}</i></span>
    <span>历史分位 <b>{st['pct_rank']:.0f}%</b><i>1971 年以来 {n} 个月</i></span>
    <span>长期均值 / 中位 <b>{st['mean']:.1f} / {st['median']:.1f}</b><i>剔除 2020 年 3–5 月后均值 {st['mean_ex2020']:.1f}</i></span>
    <span>回到均值需 <b>WTI ${oil_at_mean:.0f}</b><i>金价不变时；或金价 ${cur and (td.get('oil') or ser[-1]['oil'])*st['mean']:,.0f}（油价不变）</i></span>
  </div>
  <svg viewBox="0 0 {W} {H}" class="sgr-chart" preserveAspectRatio="xMidYMid meet">{g}
    <polyline points="{pts}" fill="none" stroke="#1f3a68" stroke-width="1.5"/>{xt}{band}</svg>
  <div class="sgr-foot">
    金油比＝1 盎司黄金能换几桶 WTI 原油（对数纵轴）。最高 {st['max']:.0f}（{st['max_m']}，疫情期间油价跌到个位数）、最低 {st['min']:.1f}（{st['min_m']}，油价 $130+）。
    1973 年以前原油为管制标价，波动小。黄金：伦敦金月均价（datasets/gold-prices），当月用 COMEX 期货日收盘均值；
    原油：FRED WTISPLC 月均，当月用 FRED DCOILWTICO 日均。「今日」取两者都有报价的最近一天。随 dashboard 每日更新。
  </div>
</div>"""



def _report_leads_html(o):
    """机构/个人研究报告「被公开解读」线索表(Chao 2026-10-03 立)。
    口径: 只要是报告内容的分享/解读就收(不要求原报告付费); 只收第三方解读线索, 不收原文大段;
    摘要=平台自带简介, 正文未读。主表只放 type=report, 访谈折叠, other 不显示。按机构分组, 组内按日期倒序。"""
    orgs = (o or {}).get("orgs") or {}
    if not orgs:
        return '<p class="empty">报告解读线索同步中。</p>'
    gen = _esc((o.get("generated") or "")[:10])
    chan = _esc(o.get("channel") or "")
    n_rep = sum(1 for v in orgs.values() for i in v.get("items", []) if i.get("type") == "report")
    n_itv = sum(1 for v in orgs.values() for i in v.get("items", []) if i.get("type") == "interview")

    def row(i, name):
        srcs = i.get("sources") or []
        links = " ".join(
            f'<a href="{_esc(x.get("url", ""))}" target="_blank" rel="noopener">{_esc(x.get("acct", "") or "来源")}</a>'
            f'<span class="rpl-pf">{_esc(x.get("platform", ""))}</span>' for x in srcs[:3])
        summ = _strip_md(i.get("summary") or "").strip().lstrip("，,、；;。 ")
        _tt = (i.get("title") or "").strip()
        _full = _strip_md(i.get("summary_full") or "").strip().lstrip("，,、；;。 ")
        if summ in ("", "-") or summ == _tt or _tt.startswith(summ) or summ.startswith(_tt):
            summ = ""
        elif _full and len(_full) > len(summ) + 5:
            # ★2026-10-06 (Chao: 摘要被截断, 要点击能看到原文): 折叠态给前 ~100 字, 点开看 B 站平台自带简介全文。
            #   口径不变: 这是平台简介, 不是视频口播原文; 正文仍未读。
            _short = summ[:100].rstrip("，,、；;。 ")
            summ = (f'<details class="rpl-more"><summary><span class="rpl-sum">{_esc(_short)}…</span>'
                    f'<span class="rpl-open">展开简介全文（{len(_full)} 字）</span></summary>'
                    f'<div class="rpl-full">{_esc(_full)}</div>'
                    f'<div class="rpl-fullnote">以上为 B 站平台自带的视频简介，不是视频口播原文；正文未读，解读是否忠实原报告未核验。</div></details>')
        else:
            summ = f'<div class="rpl-sum">{_esc(summ)}</div>'
        return (f'<tr><td class="rpl-d">{_esc(i.get("date", ""))}</td>'
                f'<td><div class="rpl-t">{_esc(_strip_md(i.get("title", "")))}</div>{summ}</td>'
                f'<td class="rpl-s">{links}</td></tr>')

    blocks = []
    for name, v in sorted(orgs.items(), key=lambda kv: (-sum(1 for i in kv[1].get("items", []) if i.get("type") == "report"), kv[0])):
        items = v.get("items") or []
        rep = [i for i in items if i.get("type") == "report"]
        itv = [i for i in items if i.get("type") == "interview"]
        head = (f'<div class="rpl-h"><b>{_esc(name)}</b><span class="rpl-org">{_esc(v.get("org", ""))}</span>'
                f'<span class="rpl-n">报告解读 {len(rep)} 条' + (f' · 访谈 {len(itv)} 条' if itv else '') + '</span></div>')
        if rep:
            body = ('<table class="rpl-tb"><thead><tr><th>发布日</th><th>解读标题 / 平台简介</th><th>来源</th></tr></thead><tbody>'
                    + "".join(row(i, name) for i in rep) + '</tbody></table>')
        else:
            body = '<p class="rpl-none">近 6 个月未检索到报告类解读（公开信息有限，不代表该机构没有报告）。</p>'
        if itv:
            body += ('<details class="rpl-dt"><summary>相关访谈 / 对话 / 配音 ' + str(len(itv)) + ' 条（不是报告内容，仅供参考）</summary>'
                     '<table class="rpl-tb"><tbody>' + "".join(row(i, name) for i in itv) + '</tbody></table></details>')
        blocks.append(f'<div class="rpl-g">{head}{body}</div>')
    return f"""
<div class="rpl-wrap">
  <p class="rpl-note"><b>口径：</b>收录「机构或个人研究报告被第三方公开解读」的线索：只要解读的是报告里的内容就收录，不要求原报告付费；
    <b>只记标题、日期、解读者、链接和平台自带简介，不转载原文，也不写我们自己的推断</b>。正文未读，解读是否忠实原报告未核验。
    当前渠道：{chan}；微信公众号条目只有标题与平台自带摘要，正文未读；其链接是搜狗搜索的中转链接，点开可能先要输入验证码，打不开时可在微信里搜标题；Reddit 未接入。更新 {gen}。共 {n_rep} 条报告解读、{n_itv} 条访谈。</p>
  {''.join(blocks)}
</div>
"""


def _gs_tech_html(o):
    """金银短线图: 每个标的一张图 = 价格(收盘线+SMA20/50/200) + 上方 RSI(14); 默认近 90 个交易日, 可切 60/130/250;
    悬停读数(收/MA/RSI/距各均线%), 每图下一行事实状态。内联 SVG, 数据一次性嵌入 JS。"""
    import json as _json
    if not o or o.get("status") == "error" or not o.get("items"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">金银短线图同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    items = o["items"]
    groups = []
    for it in items:
        if it["grp"] not in groups:
            groups.append(it["grp"])
    def status_line(it):
        c, m20, m50, m200, r = it["c"][-1], it["ma20"][-1], it["ma50"][-1], it["ma200"][-1], it["rsi"][-1]
        def rel(m, n):
            if m is None: return f"{n}日线缺"
            return f"{'站上' if c >= m else '跌破'}{n}日线({(c / m - 1) * 100:+.1f}%)"
        rz = "超买区" if r is not None and r >= 70 else ("超卖区" if r is not None and r <= 30 else "中性区")
        prev = it["c"][-2]
        return f"{it['d'][-1]} 收 {c:g}（日 {(c / prev - 1) * 100:+.2f}%）｜{rel(m20, 20)}、{rel(m50, 50)}、{rel(m200, 200)}｜RSI {r:.1f}（{rz}）"
    cards = ""
    for gi, g in enumerate(groups):
        cards += f'<div class="gst-grp">{_esc(g)}</div><div class="gst-grid">'
        for it in [x for x in items if x["grp"] == g]:
            sid = it["sym"].replace("=", "_").replace(".", "_")
            tag = '<span class="gst-tag">缓存</span>' if it.get("src") == "cache" else ""
            cards += (f'<div class="gst-card"><div class="gst-hd"><b>{_esc(it["name"])}</b><span class="gst-sym">{_esc(it["sym"])}</span>{tag}</div>'
                      f'<div class="gst-pin" id="gst-pin-{sid}">鼠标移到图上查看当日读数</div>'
                      f'<svg class="gst-svg" id="gst-svg-{sid}" viewBox="0 0 560 300" preserveAspectRatio="none"></svg>'
                      f'<div class="gst-st">{_esc(status_line(it))}</div><div class="gst-nt">{_esc(it["note"])}</div></div>')
        cards += '</div>'
    data = _json.dumps({it["sym"]: {k: it[k] for k in ("d", "c", "ma20", "ma50", "ma200", "rsi")} for it in items}, separators=(",", ":"))
    ids = _json.dumps({it["sym"]: it["sym"].replace("=", "_").replace(".", "_") for it in items})
    js = """<script>(function(){var D=__DATA__,ID=__IDS__,W=560,H=300,ML=4,MR=46,PT=6,PH=190,GAP=14,RT=PT+PH+GAP,RH=H-RT-16;var win=90;
function fmt(v){if(v==null)return '—';var a=Math.abs(v);return v.toFixed(a>=1000?0:(a>=100?1:(a>=10?2:3)))}
function build(sym){var d=D[sym],id=ID[sym],svg=document.getElementById('gst-svg-'+id);var n=d.d.length,a=Math.max(0,n-win);
var c=d.c.slice(a),m20=d.ma20.slice(a),m50=d.ma50.slice(a),m200=d.ma200.slice(a),rs=d.rsi.slice(a),dt=d.d.slice(a),k=c.length;
var vals=c.concat(m20,m50,m200).filter(function(x){return x!=null});var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);var pad=(hi-lo)*0.06||1;lo-=pad;hi+=pad;
var X=function(i){return ML+(W-ML-MR)*i/Math.max(k-1,1)},Y=function(v){return PT+PH*(1-(v-lo)/(hi-lo))},YR=function(v){return RT+RH*(1-v/100)};
function pl(arr,Yf,col,sw,dash){var p='';for(var i=0;i<arr.length;i++){if(arr[i]==null)continue;p+=(p?' ':'')+X(i).toFixed(1)+','+Yf(arr[i]).toFixed(1)}return p?'<polyline points="'+p+'" fill="none" stroke="'+col+'" stroke-width="'+sw+'"'+(dash?' stroke-dasharray="'+dash+'"':'')+' stroke-linejoin="round"/>':''}
var g='';for(var t=0;t<=4;t++){var v=lo+(hi-lo)*t/4,y=Y(v);g+='<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+y.toFixed(1)+'" y2="'+y.toFixed(1)+'" stroke="#ece7dc"/><text x="'+(W-MR+4)+'" y="'+(y+3).toFixed(1)+'" font-size="10" fill="#6b5a2a">'+fmt(v)+'</text>'}
[30,50,70].forEach(function(v){g+='<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+YR(v).toFixed(1)+'" y2="'+YR(v).toFixed(1)+'" stroke="'+(v==50?'#e6e1d6':'#d9a0a0')+'" stroke-dasharray="'+(v==50?'':'3 3')+'"/><text x="'+(W-MR+4)+'" y="'+(YR(v)+3).toFixed(1)+'" font-size="9" fill="#a8a095">'+v+'</text>'});
var step=Math.max(1,Math.round(k/6));for(var i=0;i<k;i+=step){g+='<text x="'+X(i).toFixed(1)+'" y="'+(H-3)+'" font-size="9" fill="#8a837a" text-anchor="'+(i==0?'start':'middle')+'">'+(i==0?dt[i].slice(2):dt[i].slice(5))+'</text>'}
g+='<text x="'+ML+'" y="'+(RT-3)+'" font-size="9" fill="#8a837a">RSI(14)</text>';
var ln=pl(m200,Y,'#7a5c8a',1.3)+pl(m50,Y,'#3f7d5a',1.3)+pl(m20,Y,'#d08a2c',1.3)+pl(c,Y,'#1f2a44',1.9)+pl(rs,YR,'#b0493a',1.4);
svg.innerHTML=g+ln+'<line class="gst-hl" x1="0" x2="0" y1="'+PT+'" y2="'+(RT+RH)+'" stroke="#555" stroke-dasharray="3 3" visibility="hidden"/>';
svg.onmousemove=function(e){var b=svg.getBoundingClientRect();var x=(e.clientX-b.left)/b.width*W;var i=Math.round((x-ML)/(W-ML-MR)*(k-1));if(i<0||i>=k)return;var px=ML+(W-ML-MR)*i/Math.max(k-1,1);var hl=svg.querySelector('.gst-hl');hl.setAttribute('x1',px);hl.setAttribute('x2',px);hl.setAttribute('visibility','visible');
function dv(m){return m==null?'—':((c[i]/m-1)*100).toFixed(1)+'%'}
document.getElementById('gst-pin-'+id).textContent=dt[i]+'　收 '+fmt(c[i])+'｜MA20 '+fmt(m20[i])+'('+dv(m20[i])+') MA50 '+fmt(m50[i])+'('+dv(m50[i])+') MA200 '+fmt(m200[i])+'('+dv(m200[i])+')｜RSI '+(rs[i]==null?'—':rs[i].toFixed(1))};
svg.onmouseleave=function(){var hl=svg.querySelector('.gst-hl');hl.setAttribute('visibility','hidden')};}
function all(){Object.keys(D).forEach(build)}
document.querySelectorAll('.gst-win button').forEach(function(b){b.addEventListener('click',function(){win=+b.dataset.w;document.querySelectorAll('.gst-win button').forEach(function(x){x.classList.toggle('on',x===b)});all()})});
all()})();</script>""".replace("__DATA__", data).replace("__IDS__", ids)
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:4]))}</p>' if warn_l else ""
    return f"""
<style>.gst-grp{{font-size:12px;color:#6b5a2a;margin:10px 0 6px;letter-spacing:.5px}}.gst-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}@media(max-width:900px){{.gst-grid{{grid-template-columns:1fr}}}}
.gst-card{{background:#fff;border:1px solid #e6e1d6;border-radius:8px;padding:8px 10px}}.gst-hd{{display:flex;gap:8px;align-items:baseline;font-size:13px}}.gst-sym{{font-size:11px;color:#8a837a}}.gst-tag{{font-size:10px;background:#f3e3c6;color:#8a5a14;border-radius:3px;padding:0 4px}}
.gst-pin{{font-size:11px;color:#2b2b2b;background:#faf7f0;border:1px solid #efe9db;border-radius:5px;padding:3px 6px;margin:4px 0;min-height:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.gst-svg{{width:100%;height:230px;display:block;cursor:crosshair}}
.gst-st{{font-size:11px;color:#3a362f;margin-top:2px}}.gst-nt{{font-size:10px;color:#9a948a;margin-top:1px}}.gst-win{{display:flex;gap:6px;align-items:center;font-size:12px;margin:0 0 6px}}.gst-win button{{border:1px solid #d8d1c2;background:#fff;border-radius:4px;padding:2px 9px;cursor:pointer;font-size:12px}}.gst-win button.on{{background:#1f2a44;color:#fff;border-color:#1f2a44}}
.gst-lg{{font-size:11px;color:#5a554c;margin:2px 0 4px}}.gst-lg i{{display:inline-block;width:14px;height:3px;margin:0 4px 0 10px;vertical-align:middle}}</style>
{warn}
<div class="sfc-note"><b>读图：</b>每张图上半部是<b>收盘价</b>与 <b>20/50/200 日均线</b>（简单平均），下半部是 <b>RSI(14)</b>（Wilder 口径，70/30 为超买/超卖参考线，不是买卖信号）。默认看近 90 个交易日，右上角可切换窗口；均线与 RSI 在全部历史上计算，窗口只是截取，所以左端不会缺线。
 <b>口径：</b>金银期货为 COMEX <b>连续合约</b>（换月时有价格跳点），不是现货价；GLD/SLV/GDX 等为美元 ETF；中国侧为 A 股与深交所 ETF（人民币）。<b>时间：</b>美股收盘在北京时间次日清晨，中国收盘在当日 15:00；11:00 日更任务读到的是<b>最近一个已收盘交易日</b>。<b>2026-10-09 GDXJ 的 RSI 与 StockCharts 截图核对一致（45.74）。</b></div>
<div class="gst-win">窗口：<button data-w="45">45 日</button><button data-w="90" class="on">90 日</button><button data-w="130">130 日</button><button data-w="250">250 日</button>
<span class="gst-lg"><i style="background:#1f2a44"></i>收盘<i style="background:#d08a2c"></i>MA20<i style="background:#3f7d5a"></i>MA50<i style="background:#7a5c8a"></i>MA200<i style="background:#b0493a"></i>RSI</span></div>
{cards}{js}
<div class="sfc-foot">数据：Yahoo Finance 日线；指标由本看板自行计算。仅陈述价格与指标相对位置，不构成买卖建议。</div>
"""



def _ur_tech_html(o):
    """铀短线图(克隆自金银, 前缀 urt-): 每个标的一张图 = 价格(收盘线+SMA20/50/200) + 上方 RSI(14); 默认近 90 个交易日, 可切 60/130/250;
    悬停读数(收/MA/RSI/距各均线%), 每图下一行事实状态。内联 SVG, 数据一次性嵌入 JS。"""
    import json as _json
    if not o or o.get("status") == "error" or not o.get("items"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">铀短线图同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    items = o["items"]
    groups = []
    for it in items:
        if it["grp"] not in groups:
            groups.append(it["grp"])
    def status_line(it):
        c, m20, m50, m200, r = it["c"][-1], it["ma20"][-1], it["ma50"][-1], it["ma200"][-1], it["rsi"][-1]
        def rel(m, n):
            if m is None: return f"{n}日线缺"
            return f"{'站上' if c >= m else '跌破'}{n}日线({(c / m - 1) * 100:+.1f}%)"
        rz = "超买区" if r is not None and r >= 70 else ("超卖区" if r is not None and r <= 30 else "中性区")
        prev = it["c"][-2]
        return f"{it['d'][-1]} 收 {c:g}（日 {(c / prev - 1) * 100:+.2f}%）｜{rel(m20, 20)}、{rel(m50, 50)}、{rel(m200, 200)}｜RSI {r:.1f}（{rz}）"
    cards = ""
    for gi, g in enumerate(groups):
        cards += f'<div class="urt-grp">{_esc(g)}</div><div class="urt-grid">'
        for it in [x for x in items if x["grp"] == g]:
            sid = it["sym"].replace("=", "_").replace(".", "_")
            tag = '<span class="urt-tag">缓存</span>' if it.get("src") == "cache" else ""
            cards += (f'<div class="urt-card"><div class="urt-hd"><b>{_esc(it["name"])}</b><span class="urt-sym">{_esc(it["sym"])}</span>{tag}</div>'
                      f'<div class="urt-pin" id="urt-pin-{sid}">鼠标移到图上查看当日读数</div>'
                      f'<svg class="urt-svg" id="urt-svg-{sid}" viewBox="0 0 560 300" preserveAspectRatio="none"></svg>'
                      f'<div class="urt-st">{_esc(status_line(it))}</div><div class="urt-nt">{_esc(it["note"])}</div></div>')
        cards += '</div>'
    data = _json.dumps({it["sym"]: {k: it[k] for k in ("d", "c", "ma20", "ma50", "ma200", "rsi")} for it in items}, separators=(",", ":"))
    ids = _json.dumps({it["sym"]: it["sym"].replace("=", "_").replace(".", "_") for it in items})
    js = """<script>(function(){var D=__DATA__,ID=__IDS__,W=560,H=300,ML=4,MR=46,PT=6,PH=190,GAP=14,RT=PT+PH+GAP,RH=H-RT-16;var win=90;
function fmt(v){if(v==null)return '—';var a=Math.abs(v);return v.toFixed(a>=1000?0:(a>=100?1:(a>=10?2:3)))}
function build(sym){var d=D[sym],id=ID[sym],svg=document.getElementById('urt-svg-'+id);var n=d.d.length,a=Math.max(0,n-win);
var c=d.c.slice(a),m20=d.ma20.slice(a),m50=d.ma50.slice(a),m200=d.ma200.slice(a),rs=d.rsi.slice(a),dt=d.d.slice(a),k=c.length;
var vals=c.concat(m20,m50,m200).filter(function(x){return x!=null});var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);var pad=(hi-lo)*0.06||1;lo-=pad;hi+=pad;
var X=function(i){return ML+(W-ML-MR)*i/Math.max(k-1,1)},Y=function(v){return PT+PH*(1-(v-lo)/(hi-lo))},YR=function(v){return RT+RH*(1-v/100)};
function pl(arr,Yf,col,sw,dash){var p='';for(var i=0;i<arr.length;i++){if(arr[i]==null)continue;p+=(p?' ':'')+X(i).toFixed(1)+','+Yf(arr[i]).toFixed(1)}return p?'<polyline points="'+p+'" fill="none" stroke="'+col+'" stroke-width="'+sw+'"'+(dash?' stroke-dasharray="'+dash+'"':'')+' stroke-linejoin="round"/>':''}
var g='';for(var t=0;t<=4;t++){var v=lo+(hi-lo)*t/4,y=Y(v);g+='<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+y.toFixed(1)+'" y2="'+y.toFixed(1)+'" stroke="#ece7dc"/><text x="'+(W-MR+4)+'" y="'+(y+3).toFixed(1)+'" font-size="10" fill="#6b5a2a">'+fmt(v)+'</text>'}
[30,50,70].forEach(function(v){g+='<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+YR(v).toFixed(1)+'" y2="'+YR(v).toFixed(1)+'" stroke="'+(v==50?'#e6e1d6':'#d9a0a0')+'" stroke-dasharray="'+(v==50?'':'3 3')+'"/><text x="'+(W-MR+4)+'" y="'+(YR(v)+3).toFixed(1)+'" font-size="9" fill="#a8a095">'+v+'</text>'});
var step=Math.max(1,Math.round(k/6));for(var i=0;i<k;i+=step){g+='<text x="'+X(i).toFixed(1)+'" y="'+(H-3)+'" font-size="9" fill="#8a837a" text-anchor="'+(i==0?'start':'middle')+'">'+(i==0?dt[i].slice(2):dt[i].slice(5))+'</text>'}
g+='<text x="'+ML+'" y="'+(RT-3)+'" font-size="9" fill="#8a837a">RSI(14)</text>';
var ln=pl(m200,Y,'#7a5c8a',1.3)+pl(m50,Y,'#3f7d5a',1.3)+pl(m20,Y,'#d08a2c',1.3)+pl(c,Y,'#1f2a44',1.9)+pl(rs,YR,'#b0493a',1.4);
svg.innerHTML=g+ln+'<line class="urt-hl" x1="0" x2="0" y1="'+PT+'" y2="'+(RT+RH)+'" stroke="#555" stroke-dasharray="3 3" visibility="hidden"/>';
svg.onmousemove=function(e){var b=svg.getBoundingClientRect();var x=(e.clientX-b.left)/b.width*W;var i=Math.round((x-ML)/(W-ML-MR)*(k-1));if(i<0||i>=k)return;var px=ML+(W-ML-MR)*i/Math.max(k-1,1);var hl=svg.querySelector('.urt-hl');hl.setAttribute('x1',px);hl.setAttribute('x2',px);hl.setAttribute('visibility','visible');
function dv(m){return m==null?'—':((c[i]/m-1)*100).toFixed(1)+'%'}
document.getElementById('urt-pin-'+id).textContent=dt[i]+'　收 '+fmt(c[i])+'｜MA20 '+fmt(m20[i])+'('+dv(m20[i])+') MA50 '+fmt(m50[i])+'('+dv(m50[i])+') MA200 '+fmt(m200[i])+'('+dv(m200[i])+')｜RSI '+(rs[i]==null?'—':rs[i].toFixed(1))};
svg.onmouseleave=function(){var hl=svg.querySelector('.urt-hl');hl.setAttribute('visibility','hidden')};}
function all(){Object.keys(D).forEach(build)}
document.querySelectorAll('.urt-win button').forEach(function(b){b.addEventListener('click',function(){win=+b.dataset.w;document.querySelectorAll('.urt-win button').forEach(function(x){x.classList.toggle('on',x===b)});all()})});
all()})();</script>""".replace("__DATA__", data).replace("__IDS__", ids)
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:4]))}</p>' if warn_l else ""
    return f"""
<style>.urt-grp{{font-size:12px;color:#6b5a2a;margin:10px 0 6px;letter-spacing:.5px}}.urt-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}@media(max-width:900px){{.urt-grid{{grid-template-columns:1fr}}}}
.urt-card{{background:#fff;border:1px solid #e6e1d6;border-radius:8px;padding:8px 10px}}.urt-hd{{display:flex;gap:8px;align-items:baseline;font-size:13px}}.urt-sym{{font-size:11px;color:#8a837a}}.urt-tag{{font-size:10px;background:#f3e3c6;color:#8a5a14;border-radius:3px;padding:0 4px}}
.urt-pin{{font-size:11px;color:#2b2b2b;background:#faf7f0;border:1px solid #efe9db;border-radius:5px;padding:3px 6px;margin:4px 0;min-height:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.urt-svg{{width:100%;height:230px;display:block;cursor:crosshair}}
.urt-st{{font-size:11px;color:#3a362f;margin-top:2px}}.urt-nt{{font-size:10px;color:#9a948a;margin-top:1px}}.urt-win{{display:flex;gap:6px;align-items:center;font-size:12px;margin:0 0 6px}}.urt-win button{{border:1px solid #d8d1c2;background:#fff;border-radius:4px;padding:2px 9px;cursor:pointer;font-size:12px}}.urt-win button.on{{background:#1f2a44;color:#fff;border-color:#1f2a44}}
.urt-lg{{font-size:11px;color:#5a554c;margin:2px 0 4px}}.urt-lg i{{display:inline-block;width:14px;height:3px;margin:0 4px 0 10px;vertical-align:middle}}</style>
{warn}
<div class="sfc-note"><b>读图：</b>每张图上半部是<b>收盘价</b>与 <b>20/50/200 日均线</b>（简单平均），下半部是 <b>RSI(14)</b>（Wilder 口径，70/30 为超买/超卖参考线，不是买卖信号）。默认看近 90 个交易日，右上角可切换窗口；均线与 RSI 在全部历史上计算，窗口只是截取，所以左端不会缺线。
 <b>口径：</b>铀<b>现货(U3O8)没有免费可靠的日线</b>，这里用两只<b>实物铀信托</b>（SPUT 美股 OTC 价、Yellow Cake 伦敦价）作代理，它们是二级市场价，与现货之间有溢价或折价，<b>不等于铀价</b>。URA/URNM/NLR 为美元 ETF；矿企按各自上市地计价（美元、澳元、港元，Kazatomprom 为伦敦 GDR 美元价）。<b>时间：</b>各市场收盘时刻不同，同一天的收盘不在同一时点。</div>
<div class="urt-win">窗口：<button data-w="45">45 日</button><button data-w="90" class="on">90 日</button><button data-w="130">130 日</button><button data-w="250">250 日</button>
<span class="urt-lg"><i style="background:#1f2a44"></i>收盘<i style="background:#d08a2c"></i>MA20<i style="background:#3f7d5a"></i>MA50<i style="background:#7a5c8a"></i>MA200<i style="background:#b0493a"></i>RSI</span></div>
{cards}{js}
<div class="sfc-foot">数据：Yahoo Finance 日线；指标由本看板自行计算。仅陈述价格与指标相对位置，不构成买卖建议。</div>
"""

def _cn_cap_svg(series, w=940, h=250, unit="", colors=None, stacked=False, dec=0, ylab=""):
    """通用 A 股资金面折线/堆叠柱。series: [(名称, [(日期, 值), ...])]; 每点/每柱 悬停 data-tip。
    stacked=True: 按日期对齐画堆叠柱(季频存量); 否则折线(日频)。"""
    colors = colors or ["#6b8fb5", "#7fa085", "#b58a6a", "#9a7ca8"]
    series = [(n, [(d, v) for d, v in pts if v is not None]) for n, pts in series]
    series = [(n, pts) for n, pts in series if pts]
    if not series:
        return ""
    ml, mr, mt, mb = 62, 14, 24, 44
    pw, ph = w - ml - mr, h - mt - mb
    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    if stacked:
        dates = sorted({d for _, pts in series for d, _ in pts})
        m = {n: dict(pts) for n, pts in series}
        tot = [sum(m[n].get(d, 0) for n, _ in series) for d in dates]
        top = max(tot) * 1.1 or 1
        Y = lambda v: mt + ph - ph * v / top
        step = pw / len(dates)
        bw = step * 0.62
        for k in range(5):
            tv = top * k / 4
            yy = Y(tv)
            p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" stroke="#2a2f3a" stroke-dasharray="3 3"/>')
            p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10" fill="#8b93a7">{tv:,.{dec}f}</text>')
        for i, d in enumerate(dates):
            cx = ml + step * i + step / 2
            acc = 0
            for j, (n, _) in enumerate(series):
                v = m[n].get(d)
                if v is None:
                    continue
                y1, y0 = Y(acc + v), Y(acc)
                acc += v
                tip = f'{d}｜{n} {v:,.{dec}f}{unit}（合计 {tot[i]:,.{dec}f}{unit}）'
                p.append(f'<rect class="tip-hit" x="{cx-bw/2:.1f}" y="{y1:.1f}" width="{bw:.1f}" '
                         f'height="{max(y0-y1, 0.5):.1f}" fill="{colors[j % len(colors)]}" opacity="0.85" data-tip="{_esc(tip)}"/>')
            if i % max(1, len(dates) // 10) == 0 or i == len(dates) - 1:
                p.append(f'<text x="{cx:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" font-size="9" fill="#7c8496">{_esc(d[2:7])}</text>')
    else:
        allv = [v for _, pts in series for _, v in pts]
        lo, hi = min(allv), max(allv)
        pad = (hi - lo) * 0.12 or 1
        lo -= pad
        hi += pad
        dates = sorted({d for _, pts in series for d, _ in pts})
        idx = {d: i for i, d in enumerate(dates)}
        X = lambda d: ml + pw * idx[d] / max(len(dates) - 1, 1)
        Y = lambda v: mt + ph - ph * (v - lo) / (hi - lo)
        for k in range(5):
            tv = lo + (hi - lo) * k / 4
            yy = Y(tv)
            p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" stroke="#2a2f3a" stroke-dasharray="3 3"/>')
            p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10" fill="#8b93a7">{tv:,.{dec}f}</text>')
        if lo < 0 < hi:
            p.append(f'<line x1="{ml}" y1="{Y(0):.1f}" x2="{ml+pw}" y2="{Y(0):.1f}" stroke="#8b93a7" opacity=".7"/>')
        for j, (n, pts) in enumerate(series):
            c = colors[j % len(colors)]
            pl = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in pts)
            p.append(f'<polyline points="{pl}" fill="none" stroke="{c}" stroke-width="1.6"/>')
            stp = max(1, len(pts) // 260)
            hit = pts[::stp]
            if hit[-1] != pts[-1]:
                hit.append(pts[-1])
            for d, v in hit:
                tip = f"{d}｜{n} {v:,.{dec}f}{unit}"
                p.append(f'<circle class="tip-hit" cx="{X(d):.1f}" cy="{Y(v):.1f}" r="5" fill="transparent" data-tip="{_esc(tip)}"/>')
        for i in range(0, len(dates), max(1, len(dates) // 9)):
            p.append(f'<text x="{X(dates[i]):.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" font-size="9" fill="#7c8496">{_esc(dates[i][2:7])}</text>')
    lx = ml
    for j, (n, _) in enumerate(series):
        p.append(f'<rect x="{lx}" y="{h-18}" width="10" height="10" fill="{colors[j % len(colors)]}"/>'
                 f'<text x="{lx+14}" y="{h-9}" font-size="9.5" fill="#8b93a7">{_esc(n)}</text>')
        lx += 26 + len(n) * 11
    p.append(f'<text x="{ml}" y="{mt-5}" font-size="10" fill="#8b93a7">{_esc(ylab)}</text></svg>')
    return "".join(p)


def _cn_capital_html(o, cl, hk_hold=None):
    """A 股资金面: ①国家队直接持股(季频) ②北向持股市值(季频快照) ③南向净买入累计(日频)
    ④⑤ 复用宽基 ETF 份额 / 两融余额(来自 cn_liq)。口径坑全部写在页面上, 不替「超级平准/超级外资」背书。"""
    if not o or o.get("status") == "error":
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">A 股资金面数据同步中{(chr(0xff1a) + _esc(err)) if err else ""}。</p>'
    h = []
    warn = o.get("warnings") or []
    if warn:
        h.append(f'<p class="sgr-warn">⚠ {_esc("；".join(warn[:3]))}</p>')
    h.append('<div class="sfc-note"><b>先读口径：</b>本板块全部来自交易所/东方财富披露库的<b>真实披露数据</b>，没有任何推算。'
             '行情软件里的「超级平准持仓占比」「超级外资累计净买入」是软件自定义口径，<b>公开资料查不到定义，'
             '本板块不复刻、也不等同于它们</b>。</div>')
    # ① 国家队
    hq = o.get("holders_q") or {}
    qs = sorted(hq)[-24:]
    names = ["汇金投资", "汇金资管", "证金"]
    if qs:
        h.append('<div class="part-title" style="font-size:14px;margin-top:10px">① 国家队直接持股市值 · 季末'
                 '<span class="freq-badge freq-quarterly">季度更新</span></div>')
        last = qs[-1]
        lv = hq[last]
        tot = sum(v["cap_yi"] for v in lv.values())
        h.append(f'<p class="oil-meta">三家合计 <b>{tot/1e4:.2f} 万亿元</b>（{last} 十大流通股东披露口径）。'
                 f'汇金投资只直接持有 {lv.get("汇金投资", {}).get("n", 0)} 只，以四大行为主，是这条线的绝对主体，'
                 '季度间变化主要来自股价而非买卖。</p>')
        ser = [(nm, [(q, hq[q][nm]["cap_yi"] / 1e4 if nm in hq[q] else None) for q in qs]) for nm in names]
        h.append(_cn_cap_svg(ser, stacked=True, unit=" 万亿元", dec=2, ylab="万亿元"))
        hs = o.get("holders_stocks") or {}
        if len(qs) >= 3 and all(q in hs for q in qs[-3:]):
            base = qs[-2]
            basket = {c for c, v in hs[base].items() if "证金" in v or "汇金资管" in v}
            row = []
            for q in qs[-4:]:
                if q not in hs:
                    continue
                sh = {c: hs[q].get(c, {}).get("证金", 0) + hs[q].get(c, {}).get("汇金资管", 0) for c in basket}
                row.append((q, sum(sh.values()) / 1e8, sum(1 for v in sh.values() if v > 0)))
            if len(row) >= 2:
                cells = "；".join(f"{q} {t:,.0f} 亿股（{n}/{len(basket)} 只有记录）" for q, t, n in row)
                h.append('<p class="oil-meta" style="border-left:3px solid #c9a961;padding-left:9px">'
                         '<b>读图提示：证金/汇金资管的「只数」逐季骤降，不能读成撤退。</b>'
                         f'这是十大流通股东披露——掉出前十名就不再出现。以 {base} 时证金+汇金资管在列的 {len(basket)} 只股票为固定篮子，'
                         f'合并两家股数（持股会在两家之间转移）：{cells}。'
                         '最新一期「有记录只数」下降，可能是掉出前十、也可能是真减持，<b>这份数据区分不了，所以不据此下撤退结论</b>。'
                         '另：汇金通过 ETF 的持仓不在本数据内（ETF 持有人仅半年报/年报披露前十大）。</p>')
    # ② 北向
    nq = o.get("north_q") or {}
    if nq:
        h.append('<div class="part-title" style="font-size:14px;margin-top:14px">② 北向（外资）持股市值 · 季末快照'
                 '<span class="freq-badge freq-quarterly">季度更新</span></div>')
        ks = sorted(nq)
        lk = ks[-1]
        h.append(f'<p class="oil-meta"><b>北向日度净买入已于 2024-08-16 起停止披露</b>（交易所只剩日成交额，净买入字段为空），'
                 f'所以外资只能看季度存量：{lk} 持股 <b>{nq[lk]["cap_yi"]/1e4:.2f} 万亿元</b>，占 A 股流通市值 <b>{nq[lk]["ratio_pct"]:.2f}%</b>。'
                 f'接口只给最近几期，本看板每次运行把拿到的期次存进本地档案，<b>历史从现在开始逐季积累，目前只有 {len(ks)} 个点</b>。'
                 '持股市值含价格涨跌，不等于净买入。</p>')
        h.append(_cn_cap_svg([("北向持股市值", [(k, nq[k]["cap_yi"] / 1e4) for k in ks])],
                             stacked=True, unit=" 万亿元", dec=2, ylab="万亿元", h=210))
    # ③ 南向
    sd = o.get("south_d") or {}
    if sd:
        h.append('<div class="part-title" style="font-size:14px;margin-top:14px">③ 南向资金净买入累计 · 港股通'
                 '<span class="freq-badge freq-daily">每日更新</span></div>')
        ds = sorted(sd)
        cutoff = (datetime.date.fromisoformat(ds[-1]) - datetime.timedelta(days=365 * 3)).isoformat()
        acc = 0.0
        c3 = []
        for d in ds:
            if d >= cutoff:
                acc += sd[d][0]
                c3.append((d, acc / 1e6))
        hsi = [(d, sd[d][1]) for d in ds if d >= cutoff and sd[d][1]]
        last5 = sum(sd[d][0] for d in ds[-5:]) / 100
        last20 = sum(sd[d][0] for d in ds[-20:]) / 100
        yt = sum(sd[d][0] for d in ds if d[:4] == ds[-1][:4]) / 100
        h.append(f'<p class="oil-meta"><b>方向要看清：南向是内地资金买港股，不是外资</b>（H 股一侧最完整的跨境资金数据）。'
                 f'截至 {ds[-1]}：近 5 日净买入 <b>{last5:,.0f} 亿港元</b>，近 20 日 <b>{last20:,.0f} 亿港元</b>，今年以来 <b>{yt:,.0f} 亿港元</b>。'
                 '下图为近 3 年累计（起点归零，单位万亿港元）及同期恒生指数；数据 2014-11-17 起日频完整。</p>')
        h.append(_cn_cap_svg([("南向近3年累计净买入", c3)], unit=" 万亿港元", dec=2, ylab="万亿港元", colors=["#6b8fb5"], h=220))
        h.append(_cn_cap_svg([("恒生指数收盘", hsi)], unit="", dec=0, ylab="恒指", colors=["#b58a6a"], h=190))
        hh = (hk_hold or {}).get("d") or {}
        if len(hh) >= 20:
            hk = sorted(hh)
            lastd = hk[-1]
            cap_now = hh[lastd][0] / 1e4
            top10 = hh[lastd][2]
            # 与恒指对齐比较起点: 持股存量与恒指同期涨幅 → 估算「价格效应」占多少(只描述, 不下结论)
            d0 = hk[0]
            hsi_map = {d: sd[d][1] for d in sd if sd[d][1]}
            note = ""
            if d0 in hsi_map and lastd in hsi_map:
                note = (f'同期恒指 {hsi_map[d0]:,.0f} → {hsi_map[lastd]:,.0f}（{(hsi_map[lastd] / hsi_map[d0] - 1) * 100:+.0f}%），'
                        f'港股通持股市值 {hh[d0][0] / 1e4:.2f} → {cap_now:.2f} 万亿港元（{(hh[lastd][0] / hh[d0][0] - 1) * 100:+.0f}%）。')
            h.append(f'<p class="oil-meta"><b>南向持股存量（港股通在港股持有的总市值）</b>：{lastd} 为 <b>{cap_now:.2f} 万亿港元</b>，'
                     f'共 {hh[lastd][1]} 只，前十大合计占 {top10}%。{note}'
                     f'<b>注意：这是存量，包含港股价格涨跌，不等于净买入</b>（净买入见上方累计线）。'
                     f'数据 {hk[0]} 起日频（接口只存约两年）；港股通两个通道返回同一份持股，已只取一个通道，没有重复计算。</p>')
            h.append(_cn_cap_svg([("南向持股市值", [(d, hh[d][0] / 1e4) for d in hk])], unit=" 万亿港元", dec=2,
                                 ylab="万亿港元", colors=["#7fa085"], h=210))
    # ④⑤ 复用
    cl = cl or {}
    etf = (cl.get("etf") or {}).get("series") or {}
    mgr = cl.get("margin") or []
    if etf or mgr:
        h.append('<div class="part-title" style="font-size:14px;margin-top:14px">④ 宽基 ETF 份额 · ⑤ 两融余额'
                 '<span class="freq-badge freq-daily">每日更新</span></div>')
        h.append('<p class="oil-meta">这两张是日频代理指标，频率与上方季频数据不同。<b>注意：代理指标，不等同于国家队持仓。</b>'
                 '④ 宽基 ETF 份额：三只份额各自以首日为 100 的指数化走势，2026 年的大幅下降是已用公开报道逐点核对过的真实赎回'
                 '（沪深300ETF 2025-12-31 888.30 亿份 → 2026-08-10 248.61 亿份），不是数据故障。'
                 '⑤ 两融余额：沪深两融合计余额，单位万亿元；纵轴出现负数刻度只是画图留白，余额本身不会为负。</p>')
        if etf:
            h.append(_etf_share_svg(etf, (cl.get("etf") or {}).get("names") or {}))
        if mgr:
            h.append(f'<p class="oil-meta">⑤ 两融余额（万亿元）· {mgr[0]["date"]} ~ {mgr[-1]["date"]} · 日频</p>')
            h.append(_cn_line_svg(mgr, "v", unit="", color="#c9a961", dec=3))
    h.append('<div class="sfc-foot">数据：东方财富披露库（十大流通股东、沪深港通）、上交所 ETF 规模表。仅陈述披露数据，不构成投资建议。</div>')
    return "".join(h)


def _fed_gold_oil_html(o):
    """联邦基金利率(左轴 线性 %) + 金价(美元/盎司) + WTI 油价(美元/桶)(右轴 共用对数美元轴), 月度 1970 起。内联 SVG + 悬停读数 + 开关。"""
    import json as _json, math as _m
    if not o or o.get("status") == "error" or len(o.get("m", [])) < 600:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">利率、金价、油价同步中{((chr(0xff1a) + _esc(err)) if err else "")}。</p>'
    M, FF, G, O = o["m"], o["ff"], o["gold"], o["oil"]; n = len(M)
    W, Hh, ML, MR, MT, MB = 1140, 430, 48, 56, 14, 26
    X = lambda i: ML + (W - ML - MR) * i / (n - 1)
    YL = lambda v: MT + (Hh - MT - MB) * (1 - v / 20.0)                 # 左轴 0~20%
    lo, hi = 2.0, 8000.0
    YR = lambda v: MT + (Hh - MT - MB) * (1 - (_m.log10(v) - _m.log10(lo)) / (_m.log10(hi) - _m.log10(lo)))
    g = ""
    for v in (0, 5, 10, 15, 20):
        g += f'<line x1="{ML}" x2="{W-MR}" y1="{YL(v):.1f}" y2="{YL(v):.1f}" stroke="#ece7dc"/><text x="{ML-5}" y="{YL(v)+3:.1f}" text-anchor="end" font-size="10" fill="#b0493a">{v}%</text>'
    for v in (2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        major = v in (10, 100, 1000)
        g += f'<text x="{W-MR+5}" y="{YR(v)+3:.1f}" font-size="{10 if major else 9}" fill="#6b5a2a">${v:,}</text>' + (f'<line x1="{W-MR}" x2="{W-MR+3}" y1="{YR(v):.1f}" y2="{YR(v):.1f}" stroke="#a8761a"/>')
    for yr in range(1970, 2030, 5):
        i = next((j for j, x in enumerate(M) if x >= f"{yr}-01"), None)
        if i is not None:
            g += f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{MT}" y2="{Hh-MB}" stroke="#f1ede3"/><text x="{X(i):.1f}" y="{Hh-MB+14}" text-anchor="middle" font-size="10" fill="#8a837a">{yr}</text>'
    pl = lambda vals, Y, col, sw, idn: f'<polyline id="{idn}" points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round"/>'
    lines = pl(O, YR, "#1f3a68", 1.3, "fgo-l-oil") + pl(G, YR, "#c99a2e", 1.8, "fgo-l-gold") + pl(FF, YL, "#b0493a", 1.8, "fgo-l-ff")
    # 数据派生的极值标注(不写原因, 只标日期与数值)
    ipk = max(range(n), key=lambda i: FF[i]); igk = max(range(n), key=lambda i: G[i]); iok = max(range(n), key=lambda i: O[i])
    def mark(i, Y, v, col, txt, dy, dx=0, anchor="middle"):
        return (f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.2" fill="{col}"/>'
                f'<text x="{X(i)+dx:.1f}" y="{Y(v)+dy:.1f}" text-anchor="{anchor}" font-size="11" fill="{col}" stroke="#fff" stroke-width="3" paint-order="stroke">{txt}</text>')
    marks = (mark(ipk, YL, FF[ipk], "#b0493a", f"利率峰值 {FF[ipk]:.1f}%（{M[ipk]}）", -8, dx=70)
             + mark(igk, YR, G[igk], "#8a6a14", f"金价高点 ${G[igk]:,.0f}（{M[igk]}）", -8, dx=-6, anchor="end")
             + mark(iok, YR, O[iok], "#1f3a68", f"油价高点 ${O[iok]:,.0f}（{M[iok]}）", -9))
    data = _json.dumps({"m": M, "ff": FF, "g": G, "o": O}, separators=(",", ":"))
    script = """<script>(function(){var D=__DATA__,W=__W__,ML=__ML__,MR=__MR__,n=D.m.length;var pin=document.getElementById('fgo-pin');var sv=document.getElementById('fgo-svg');var hl=document.getElementById('fgo-hl');
function f(v,k){return v==null?'—':v.toFixed(k)}
sv.addEventListener('mousemove',function(e){var s=sv.getBoundingClientRect();var x=(e.clientX-s.left)/s.width*W;var i=Math.round((x-ML)/(W-ML-MR)*(n-1));if(i<0||i>=n)return;var px=ML+(W-ML-MR)*i/(n-1);hl.setAttribute('x1',px);hl.setAttribute('x2',px);hl.setAttribute('visibility','visible');
pin.textContent=D.m[i]+'　联邦基金利率 '+f(D.ff[i],2)+'%　｜　金价 $'+f(D.g[i],0)+'/盎司　｜　WTI 油价 $'+f(D.o[i],2)+'/桶　｜　金油比 '+f(D.g[i]/D.o[i],1)});
['ff','gold','oil'].forEach(function(k){var c=document.getElementById('fgo-c-'+k);var l=document.getElementById('fgo-l-'+k);c.addEventListener('change',function(){l.setAttribute('visibility',c.checked?'visible':'hidden')})})})();</script>""".replace("__DATA__", data).replace("__W__", str(W)).replace("__ML__", str(ML)).replace("__MR__", str(MR))
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:3]))}</p>' if warn_l else ""
    srcs = "；".join(sorted(set(o.get("src", {}).values())))
    return f"""
<style>.fgo-box{{background:#fff;border:1px solid #e6e1d6;border-radius:8px;padding:10px 12px}}.fgo-svg{{width:100%;height:auto;display:block;cursor:crosshair}}
.fgo-ctl{{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#3a362f;margin:0 0 8px}}.fgo-ctl label{{cursor:pointer}}.fgo-ctl i{{display:inline-block;width:16px;height:3px;margin-right:5px;vertical-align:middle}}
.fgo-pin{{font-size:12px;color:#2b2b2b;background:#faf7f0;border:1px solid #e6e1d6;border-radius:6px;padding:6px 10px;margin-bottom:8px;min-height:18px}}</style>
{warn}
<div class="sfc-note"><b>口径说明：</b>左轴是<b>联邦基金有效利率</b>（月均，线性，%）；右轴是<b>对数轴</b>，<b>金价（美元/盎司）和 WTI 原油（美元/桶）共用这一根轴</b>，两者单位不同，只是都以美元计价、放在同一把尺子上比较涨跌幅度。
  金价为世界银行月均价（与本看板「金油比」「股指÷黄金」同一底表）；油价为 FRED 的 WTI 现货月均价，<b>1973 年前为官方管制标价，不是市场价</b>。{(' 最新未发布月份用日度数据补：' + _esc(srcs) + '。') if srcs else ''}</div>
<div class="fgo-box"><div class="fgo-ctl"><label><input type="checkbox" id="fgo-c-ff" checked><i style="background:#b0493a"></i>联邦基金利率（左轴）</label><label><input type="checkbox" id="fgo-c-gold" checked><i style="background:#c99a2e"></i>金价（右轴·对数）</label><label><input type="checkbox" id="fgo-c-oil" checked><i style="background:#1f3a68"></i>WTI 油价（右轴·对数）</label></div>
<div class="fgo-pin" id="fgo-pin">鼠标移到图上，可看到该月的利率、金价、油价和金油比。</div>
<svg viewBox="0 0 {W} {Hh}" class="fgo-svg" id="fgo-svg" role="img" aria-label="联邦基金利率与金价油价">{g}{lines}{marks}<line id="fgo-hl" x1="0" x2="0" y1="{MT}" y2="{Hh-MB}" stroke="#555" stroke-dasharray="3 3" visibility="hidden"/></svg></div>
{script}
<div class="sfc-foot">数据：FRED（FEDFUNDS、DFF、WTISPLC、DCOILWTICO）、datahub gold-prices（世界银行 Pink Sheet）、Yahoo Finance（GC=F，仅补最新月）。图上只标注数据本身的极值，不附原因解读。</div>
"""


def _gold_vol_html(o):
    """黄金波动率(周线): 价格 + 5 条简单均线 + GVZ / 布林带宽度(40,80) / ATR(14) 四个副图。纯内联 SVG + 少量 JS(悬停读数)。"""
    import json as _json
    w = (o or {}).get("w") or {}
    if not w or len(w.get("d", [])) < 300 or o.get("status") == "error":
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">黄金波动率同步中{((chr(0xff1a) + _esc(err)) if err else "")}。</p>'
    d0 = next((i for i, x in enumerate(w["d"]) if x >= "2011-01-01"), 0)
    sl = lambda L: L[d0:]
    D_ = sl(w["d"]); n = len(D_)
    c = sl(w["c"]); hi_ = sl(w["h"]); lo_ = sl(w["l"])
    ma = {k: sl(v) for k, v in w["ma"].items()}
    panels = [("GVZ", sl(w["gvz"]), "GVZ（黄金波动率指数）", 0), ("BBW40", sl(w["bbw40"]), "布林带宽度(40,2)", 1),
              ("BBW80", sl(w["bbw80"]), "布林带宽度(80,2)", 1), ("ATR", sl(w["atr"]), "ATR(14)", 0)]
    W, ML, MR = 1140, 52, 14
    COLS = {"82": "#1f2d4d", "105": "#8a2d3b", "127": "#2f7d4f", "148": "#a23b8a", "170": "#8d7bc4"}
    X = lambda i: ML + (W - ML - MR) * i / (n - 1)
    def lines(vals, Y, col, sw=1.2):
        seg, cur = [], []
        for i, v in enumerate(vals):
            if v is None:
                if cur: seg.append(cur); cur = []
            else: cur.append(f"{X(i):.1f},{Y(v):.1f}")
        if cur: seg.append(cur)
        return "".join(f'<polyline points="{" ".join(p)}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round"/>' for p in seg if len(p) > 1)
    def yticks(lo, hi, Y, fmt, k=5):
        import math as _m
        raw = (hi - lo) / k; mag = 10 ** _m.floor(_m.log10(raw)); st = min((x * mag for x in (1, 2, 2.5, 5, 10)), key=lambda x: abs(x - raw))
        v = _m.floor(lo / st + 1) * st; g = ""
        while v < hi:
            g += f'<line x1="{ML}" x2="{W-MR}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#ece7dc"/><text x="{ML-4}" y="{Y(v)+3:.1f}" text-anchor="end" font-size="9" fill="#8a837a">{fmt(v)}</text>'
            v += st
        return g
    def xticks(top, bot):
        g = ""
        for yr in range(2011, 2027):
            i = next((j for j, x in enumerate(D_) if x >= f"{yr}-01-01"), None)
            if i is not None: g += f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{top}" y2="{bot}" stroke="#f1ede3"/>' + (f'<text x="{X(i):.1f}" y="{bot+12}" text-anchor="middle" font-size="9" fill="#8a837a">{yr}</text>' if yr % 2 == 1 or yr == 2026 else "")
        return g
    # 价格主图
    PH, PT, PB = 300, 12, 22
    allp = [v for v in hi_ if v] + [v for v in lo_ if v] + [v for L in ma.values() for v in L if v]
    plo, phi = min(allp) * 0.97, max(allp) * 1.03
    YP = lambda v: PT + (PH - PT - PB) * (1 - (v - plo) / (phi - plo))
    price_svg = yticks(plo, phi, YP, lambda v: f"{v:,.0f}") + xticks(PT, PH - PB)
    price_svg += lines(c, YP, "#1c1c1c", 1.5)
    for k in ("82", "105", "127", "148", "170"): price_svg += lines(ma[k], YP, COLS[k], 1.1)
    leg = '<span class="gv-lg"><i style="background:#1c1c1c"></i>收盘价</span>' + "".join(f'<span class="gv-lg"><i style="background:{COLS[k]}"></i>{k} 周均线</span>' for k in ("82", "105", "127", "148", "170"))
    out = [f'<div class="gv-box"><div class="gv-ttl">黄金（COMEX 期货，周线）与 5 条简单均线</div><svg viewBox="0 0 {W} {PH}" class="gv-svg" id="gv-p0">{price_svg}<line class="gv-hl" x1="0" x2="0" y1="{PT}" y2="{PH-PB}" stroke="#b0493a" stroke-dasharray="3 3" visibility="hidden"/></svg><div class="gv-leg">{leg}</div></div>']
    SH, ST, SB = 120, 8, 18
    for idx, (key, vals, title, dec) in enumerate(panels):
        vv = [v for v in vals if v is not None]
        lo, hi = 0 if key in ("GVZ", "ATR") else min(vv) * 0.9, max(vv) * 1.08
        Y = (lambda lo, hi: (lambda v: ST + (SH - ST - SB) * (1 - (v - lo) / (hi - lo))))(lo, hi)
        g = yticks(lo, hi, Y, (lambda v: f"{v:,.0f}") if dec == 0 else (lambda v: f"{v:.0f}"), 4) + xticks(ST, SH - SB) + lines(vals, Y, "#1c1c1c", 1.3)
        last = next((v for v in reversed(vals) if v is not None), None)
        mx = max(vv); imx = vals.index(mx)
        out.append(f'<div class="gv-box"><div class="gv-ttl">{title}　<span class="gv-now">最新 {last:,.2f}</span>　<span class="gv-sub">区间峰值 {mx:,.1f}（{D_[imx]}）</span></div>'
                   f'<svg viewBox="0 0 {W} {SH}" class="gv-svg" id="gv-p{idx+1}">{g}<line class="gv-hl" x1="0" x2="0" y1="{ST}" y2="{SH-SB}" stroke="#b0493a" stroke-dasharray="3 3" visibility="hidden"/></svg></div>')
    data = {"d": D_, "c": c, "ma": ma, "gvz": panels[0][1], "b40": panels[1][1], "b80": panels[2][1], "atr": panels[3][1]}
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = """<script>(function(){var D=__DATA__,W=__W__,ML=__ML__,MR=__MR__,n=D.d.length;
var pin=document.getElementById('gv-pin');function f(v,k){return v==null?'—':v.toFixed(k)}
function show(e){var s=e.currentTarget.getBoundingClientRect();var x=(e.clientX-s.left)/s.width*W;var i=Math.round((x-ML)/(W-ML-MR)*(n-1));if(i<0||i>=n)return;
var px=ML+(W-ML-MR)*i/(n-1);for(var k=0;k<5;k++){var l=document.querySelector('#gv-p'+k+' .gv-hl');if(l){l.setAttribute('x1',px);l.setAttribute('x2',px);l.setAttribute('visibility','visible')}}
pin.textContent=D.d[i]+'（周）　收盘 '+f(D.c[i],1)+'　MA82 '+f(D.ma['82'][i],0)+'　MA105 '+f(D.ma['105'][i],0)+'　MA127 '+f(D.ma['127'][i],0)+'　MA148 '+f(D.ma['148'][i],0)+'　MA170 '+f(D.ma['170'][i],0)+'　｜　GVZ '+f(D.gvz[i],2)+'　BB宽度(40) '+f(D.b40[i],1)+'　BB宽度(80) '+f(D.b80[i],1)+'　ATR(14) '+f(D.atr[i],1)}
for(var k=0;k<5;k++){var sv=document.getElementById('gv-p'+k);if(sv)sv.addEventListener('mousemove',show)}})();</script>""".replace("__DATA__", js).replace("__W__", str(W)).replace("__ML__", str(ML)).replace("__MR__", str(MR))
    last_bar = w.get("last_bar", D_[-1])
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:3]))}</p>' if warn_l else ""
    return f"""
<style>.gv-box{{background:#fff;border:1px solid #e6e1d6;border-radius:8px;padding:10px 12px;margin-bottom:10px}}.gv-ttl{{font-size:13px;font-weight:600;color:#2b2b2b;margin-bottom:4px}}
.gv-now{{font-weight:600;color:#b0493a}}.gv-sub{{font-size:11px;font-weight:400;color:#8a837a}}.gv-svg{{width:100%;height:auto;display:block;cursor:crosshair}}
.gv-leg{{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#5b564e;margin-top:4px}}.gv-lg i{{display:inline-block;width:14px;height:3px;margin-right:5px;vertical-align:middle}}
.gv-pin{{font-size:12px;color:#2b2b2b;background:#faf7f0;border:1px solid #e6e1d6;border-radius:6px;padding:6px 10px;margin-bottom:10px;min-height:18px}}</style>
{warn}
<div class="sfc-note"><b>口径说明：</b>价格取 Yahoo 的 <b>COMEX 黄金期货（GC=F）周线</b>，不是现货；均线为<b>简单均线</b>（周期 82/105/127/148/170 周）；布林带宽度＝(上轨−下轨)÷中轨×100，ATR 用 Wilder 平滑；
  <b>GVZ</b> 为 CBOE 黄金波动率指数（FRED 官方，日度取每周最后值）。我拿同一周的参考读数对过：GVZ 完全一致，均线整体比现货口径高约 0.5%，布林带宽度差 1~3%，ATR 同量级（期货与现货有基差）。本周最新一根为 {last_bar}（未收完的周线按当日价计）。</div>
<div class="gv-pin" id="gv-pin">鼠标移到任一图上，可同时看到该周的价格、5 条均线和 4 个指标读数。</div>
{"".join(out)}{script}
<div class="sfc-foot">数据：Yahoo Finance（GC=F 周线）、FRED GVZCLS。均线周期是原作者所选，本看板照用，不作评价；不含主观画线与走势设想。</div>
"""


def _analog_corr_html(o):
    """金银「类比路径」+ GDX÷SPY。历史年份价格路径按【从当年 1/28 起的日历天数偏移】叠到 2026 年起点上,
    并按比例缩放到 2026-01-28 起点价(原图 y 轴量级证实做了缩放, 图上未写; 本看板口径写明)。纯 SVG 内联, 无外链。"""
    import json as _json
    if not o or o.get("status") == "error" or not (o.get("gold") or {}).get("2026") or not (o.get("silver") or {}).get("2026"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">类比路径同步中{((chr(0xff1a) + _esc(err)) if err else "")}。</p>'
    W, Hh, ML, MR, MT, MB = 560, 300, 46, 12, 14, 34
    COL = {"2026": "#1c1c1c", "2006": "#b0493a", "2008": "#1f3a68", "2011": "#c0643c", "1973": "#7a8f5a", "1974": "#6aa8c8"}
    def chart(metal, title, order, unit):
        ser = o[metal]
        def _pk(pts):
            w = [p for p in pts if p[0] <= 120]
            return max(w, key=lambda p: p[1])
        pk26 = _pk(ser["2026"]["pts"])
        lines = {}
        for lab in order:
            if lab not in ser: continue
            if lab == "2026":
                lines[lab] = [(d, v) for d, v in ser[lab]["pts"]]
            else:
                pk = _pk(ser[lab]["pts"]); k = pk26[1] / pk[1]
                lines[lab] = [(d - pk[0] + pk26[0], v * k) for d, v in ser[lab]["pts"] if d >= pk[0]]
        allv = [v for L in lines.values() for _, v in L]
        lo, hi = min(allv), max(allv); pad = (hi - lo) * 0.06; lo -= pad; hi += pad
        xmax = max(d for L in lines.values() for d, _ in L)
        X = lambda d: ML + (W - ML - MR) * d / xmax
        Y = lambda v: MT + (Hh - MT - MB) * (1 - (v - lo) / (hi - lo))
        g = []
        import math as _m
        _raw = (hi - lo) / 6.0
        _mag = 10 ** _m.floor(_m.log10(_raw))
        step = min((c * _mag for c in (1, 2, 2.5, 5, 10)), key=lambda x: abs(x - _raw))   # 约 6 档的"好看"步长
        v0 = _m.floor(lo / step + 1) * step
        while v0 < hi:
            g.append(f'<line x1="{ML}" x2="{W-MR}" y1="{Y(v0):.1f}" y2="{Y(v0):.1f}" stroke="#e6e1d6"/><text x="{ML-4}" y="{Y(v0)+3:.1f}" text-anchor="end" font-size="9" fill="#8a837a">{unit}{v0:,.0f}</text>')
            v0 += step
        for m in range(0, int(xmax) + 1, 60):
            g.append(f'<line x1="{X(m):.1f}" x2="{X(m):.1f}" y1="{MT}" y2="{Hh-MB}" stroke="#f0ece2"/><text x="{X(m):.1f}" y="{Hh-MB+13}" text-anchor="middle" font-size="9" fill="#8a837a">+{m}天</text>')
        paths = []
        for lab, L in lines.items():
            pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in L)
            paths.append(f'<polyline points="{pts}" fill="none" stroke="{COL[lab]}" stroke-width="{2.4 if lab == "2026" else 1.3}" stroke-linejoin="round"><title>{lab}</title></polyline>')
        leg = "".join(f'<span class="ac-lg"><i style="background:{COL[l]}"></i>{l}{"（实际）" if l == "2026" else "（类比·已缩放）"}</span>' for l in order if l in lines)
        last26 = ser["2026"]["last_date"]
        return (f'<div class="ac-box"><div class="ac-ttl">{title}</div>'
                f'<svg viewBox="0 0 {W} {Hh}" class="ac-svg" role="img" aria-label="{title}">{"".join(g)}{"".join(paths)}</svg>'
                f'<div class="ac-leg">{leg}</div><div class="ac-sub">2026 线截至 {last26}；各线以「当年 1 月底起 120 天内的最高收盘」对齐 2026 年高点，横轴＝距 2026-01-28 的天数。</div></div>')
    gold = chart("gold", "金：重大突破后的回调（2026 与 2006、2008 类比）", ["2006", "2008", "2026"], "$")
    silver = chart("silver", "银：回调（2026 与 2008、2011 类比）", ["2008", "2011", "2026"], "$")
    # GDX÷SPY
    gs = o.get("gdx_spy") or {}
    gsvg = ""
    if len(gs.get("d", [])) > 500:
        d, v = gs["d"], gs["v"]
        W2, H2 = 1140, 260
        lo, hi = 0, max(v) * 1.05
        t0 = __import__("datetime").date.fromisoformat(d[0]).toordinal(); t1 = __import__("datetime").date.fromisoformat(d[-1]).toordinal()
        X2 = lambda ds: ML + (W2 - ML - MR) * (__import__("datetime").date.fromisoformat(ds).toordinal() - t0) / (t1 - t0)
        Y2 = lambda x: MT + (H2 - MT - MB) * (1 - (x - lo) / (hi - lo))
        step = max(1, len(d) // 600)
        pts = " ".join(f"{X2(d[i]):.1f},{Y2(v[i]):.1f}" for i in range(0, len(d), step))
        gg = "".join(f'<line x1="{ML}" x2="{W2-MR}" y1="{Y2(y):.1f}" y2="{Y2(y):.1f}" stroke="#e6e1d6"/><text x="{ML-4}" y="{Y2(y)+3:.1f}" text-anchor="end" font-size="9" fill="#8a837a">{y:.2f}</text>' for y in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6) if y < hi)
        for yr in range(2006, 2027, 2):
            ds = f"{yr}-01-02"
            if ds >= d[0]:
                gg += f'<text x="{X2(ds):.1f}" y="{H2-MB+13}" text-anchor="middle" font-size="9" fill="#8a837a">{yr}</text>'
        gsvg = (f'<div class="ac-box ac-wide"><div class="ac-ttl">金矿股相对大盘：GDX ÷ SPY（日度，2006 年 5 月起）</div>'
                f'<svg viewBox="0 0 {W2} {H2}" class="ac-svg" role="img" aria-label="GDX÷SPY">{gg}<polyline points="{pts}" fill="none" stroke="#1c1c1c" stroke-width="1.4"><title>GDX/SPY</title></polyline></svg>'
                f'<div class="ac-sub">最新 {d[-1]}：{v[-1]:.3f}（2011-09 附近高点约 0.52）。</div></div>')
    m73 = o.get("gold_1973_monthly") or []
    note73 = ""
    if m73:
        note73 = (f'<p class="ac-note">1973 年的金价只有<b>月度</b>数据（datahub 公开数据集，1973-01 {m73[0][1]:g} 美元 → 1973-12 {m73[-1][1]:g} 美元），'
                  f'画成日度路径会失真，所以<b>金图未画 1973</b>；1974 年金银均无公开日度数据，银图未画 1974。</p>')
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:3]))}</p>' if warn_l else ""
    _w = lambda m: max([p for p in o[m]["2026"]["pts"] if p[0] <= 120], key=lambda p: p[1])[1]
    _gp, _sp = _w("gold"), _w("silver")
    return f"""
<style>.ac-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.ac-box{{background:#fff;border:1px solid #e6e1d6;border-radius:8px;padding:10px 12px}}.ac-wide{{margin-top:14px}}
.ac-ttl{{font-size:13px;font-weight:600;color:#2b2b2b;margin-bottom:4px}}.ac-svg{{width:100%;height:auto;display:block}}.ac-leg{{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#5b564e;margin-top:4px}}
.ac-lg i{{display:inline-block;width:14px;height:3px;margin-right:5px;vertical-align:middle}}.ac-sub{{font-size:11px;color:#8a837a;margin-top:4px}}.ac-note{{font-size:12px;color:#5b564e;margin:10px 0 0;line-height:1.7}}
@media(max-width:760px){{.ac-grid{{grid-template-columns:1fr}}}}</style>
{warn}
<div class="sfc-note"><b>口径说明：</b>价格取 Yahoo 的 COMEX 黄金（GC=F）、白银（SI=F）连续合约日收盘价，不是 LBMA 定盘价。历史年份路径的对齐方式：取该年 1 月底起 120 天内的<b>最高收盘价</b>作为高点，把高点<b>对齐到 2026 年高点日</b>，并<b>按比例缩放到 2026 年高点价</b>（金 {_gp:,.0f} 美元、银 {_sp:,.1f} 美元），所以历史线读的是<b>走势形状和回调幅度的类比，不是当年的真实价格</b>。
  这个对齐方式是我按原图里圈出的低点位置<b>反推</b>出来的，只用金 2008、银 2008 两条线粗略对过（低点出现的天数接近，价格有几个百分点差距），其余线未逐条核对；原图作者没有公开算法，图上低点位置也是估读。</div>
<div class="ac-grid">{gold}{silver}</div>{note73}{gsvg}
<div class="sfc-foot">数据：Yahoo Finance（GC=F、SI=F、GDX、SPY）；1973 月度金价 datahub gold-prices。类比不代表预测。</div>
"""


def _silver_curve_html(o):
    """白银期货曲线价差: Yahoo COMEX 各月合约收盘价 - 最近月合约, 美元/盎司与百分比, 对比按 3M 国债利率估算的持有成本。
    非 EFP、非 CME 官方结算价, 图上显眼标注。页内 JS 绘制, 容器高度固定, 切换只换 SVG 内容。"""
    import json as _json
    rows = (o or {}).get("rows") or []
    if len(rows) < 30 or not (o or {}).get("contracts"):
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">白银期货曲线同步中{((chr(0xff1a) + _esc(err)) if err else "")}。</p>'
    cons = [c["ym"] for c in o["contracts"]]
    data = {"c": cons, "d": [r["d"] for r in rows], "b": [r["b"] for r in rows], "r": [r["r"] for r in rows],
            "p": [[r["px"].get(c) for c in cons] for r in rows]}
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    t = o.get("today") or {}
    warn_l = list(o.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:3]))}</p>' if warn_l else ""
    chk = "".join(
        f'<label class="sfc-chk"><input type="checkbox" data-c="{_esc(c)}"{" checked" if c in (cons[2], cons[5], cons[8] if len(cons) > 8 else cons[-1]) else ""}>'
        f'<i style="background:{col}"></i>{_esc(c[:4])}年{int(c[5:])}月</label>'
        for c, col in zip(cons[1:], ["#8a837a", "#1f3a68", "#7a8f5a", "#b0493a", "#a8761a", "#5b4a8a", "#2b7a78", "#c0643c"]))
    return f"""
<div class="sfc-wrap" id="sfc">
  {warn}
  <div class="sfc-note"><b>口径说明：</b>这是 <b>COMEX 白银期货各月合约的收盘价差</b>（各月合约 − 基准合约），基准是<b>当前最近到期的合约（{_esc(t.get('base',''))}），全程固定不滚动</b>，数据来自 Yahoo，
    <b>不是 EFP 价差，也不是 CME 官方结算价</b>；EFP 是期货与现货之间的互换价差，免费渠道拿不到历史。两者方向相关，数值不可直接对比。</div>
  <div class="sfc-ctl">
    <span class="sfc-lab">时间段</span>
    <button type="button" class="sfc-r" data-n="22">1 个月</button><button type="button" class="sfc-r" data-n="63">3 个月</button>
    <button type="button" class="sfc-r" data-n="126">6 个月</button><button type="button" class="sfc-r on" data-n="0">全部</button>
    <span class="sfc-sep"></span>
    <span class="sfc-lab">单位</span>
    <button type="button" class="sfc-u on" data-u="usd">美元/盎司</button><button type="button" class="sfc-u" data-u="pct">百分比</button>
    <span class="sfc-sep"></span>
    <label class="sfc-chk"><input type="checkbox" id="sfc-carry" checked><i style="background:repeating-linear-gradient(90deg,#8a837a 0 5px,transparent 5px 8px)"></i>持有成本（与合约同色的虚线）</label>
  </div>
  <div class="sfc-ctl">{chk}</div>
  <div class="sfc-chart" id="sfc-chart"></div>
  <div class="sfc-pin" id="sfc-pin">悬停图上任意位置可看各合约当日价差。</div>
  <div class="sfc-tabbox"><table class="sfc-tab" id="sfc-tab"></table></div>
  <div class="sfc-foot">
    升水＝该月合约收盘价 − 基准合约收盘价（基准：{_esc(t.get('base',''))}合约；它到期后基准换成下一个月，历史按新基准整体重算）。注意：2026 年初该合约离到期还有 9 个月，那时的价差是「远月 − 10 月合约」，不是当时的「近月升水」。
    持有成本＝基准合约价 × 3 个月美国国债收益率 × 该合约与基准合约相隔月数 ÷ 12，是无套利时远月相对基准的理论升水上限的粗估（未含仓储、保险、交割费用），
    实际价差高出这条线才意味着市场愿意为远期实物多付钱。每日随 dashboard 更新；合约到期前几天流动性变薄，价差可能出现噪声。
  </div>
  <script type="application/json" id="sfc-data">{js}</script>
</div>"""


def _btc_gold_html(o):
    """比特币 ÷ 黄金(2010-08 起月度) + 全球货币供应 + 美国联邦债务 + 28 条事件标注。
    图由页内 JS 绘制(数据内嵌 JSON): 时间段切换只替换 SVG 内容、容器高度固定 → 不改变页面布局, 不会引起侧栏/右侧跳动。"""
    import json as _json
    ser = (o or {}).get("rows") or []
    if len(ser) < 24:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">比特币 ÷ 黄金同步中{(("：" + _esc(err)) if err else "")}。</p>'
    st = o["stats"]; td = o.get("today") or {}
    evs = sorted([e for e in (o.get("events") or []) if e.get("date") and e.get("event")], key=lambda z: z["date"])
    nf = (o.get("not_found") or [])
    ov = o.get("overlay") or {}
    data = {"r": [[x["m"], x["r"], x["btc"], x["gold"]] for x in ser],
            "m2": [[x["m"], x["v"], x.get("n")] for x in ov.get("m2", [])],
            "debt": [[x["m"], x["v"]] for x in ov.get("debt", [])],
            "ev": [{"d": e["date"], "t": e["event"], "x": e.get("detail", ""), "u": e.get("url", ""), "s": e.get("source", ""),
                    "c": e.get("confidence", ""), "p": e.get("btc_px")} for e in evs]}
    js = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    warn_l = list(o.get("warnings", [])) + list(ov.get("warnings", []))
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(warn_l[:3]))}</p>' if warn_l else ""
    nf_html = "；".join(f'{_esc(z["date"])} {_esc(z["note"])}' for z in nf)
    peak = o.get("btc_peak") or ("", 0)
    cur = td.get("ratio") or ser[-1]["r"]
    m2l = ov.get("m2", [{}])[-1] if ov.get("m2") else {}
    dl = ov.get("debt", [{}])[-1] if ov.get("debt") else {}
    return f"""
<div class="tfs-wrap btcg-wrap" id="btcg">
  {warn}
  <div class="sgr-stat">
    <span>今日 <b>{cur:.1f} 盎司</b><i>{_esc(td.get('date',''))} · BTC ${td.get('btc',0):,.0f} / 黄金 ${td.get('gold') or 0:,.0f}</i></span>
    <span>历史最高 <b>{st['max']:.1f}</b><i>{_esc(st['max_m'])} 月均（与当前相差 {cur/st['max']*100-100:+.0f}%）</i></span>
    <span>全球货币供应 <b>{m2l.get('v', 0):.1f} 万亿$</b><i>{_esc(m2l.get('m',''))} · 五大经济体 M2/M3 折美元</i></span>
    <span>美国联邦债务 <b>{dl.get('v', 0):.1f} 万亿$</b><i>{_esc(dl.get('m',''))} · FRED GFDEBTN（季度）</i></span>
  </div>
  <div class="btcg-ctl">
    <span class="btcg-lab">时间段</span>
    <button type="button" class="btcg-r" data-y="1">1 年</button><button type="button" class="btcg-r" data-y="3">3 年</button>
    <button type="button" class="btcg-r" data-y="5">5 年</button><button type="button" class="btcg-r" data-y="10">10 年</button>
    <button type="button" class="btcg-r on" data-y="0">全部</button>
    <span class="btcg-sep"></span>
    <label class="btcg-lab" lang="zh-CN">自选 <input type="month" id="btcg-from" min="2010-08" lang="zh-CN"> 至 <input type="month" id="btcg-to" lang="zh-CN"></label>
    <button type="button" id="btcg-go">应用</button>
    <span class="btcg-sep"></span>
    <span class="btcg-lab">曲线</span>
    <label class="btcg-chk"><input type="checkbox" data-s="r" checked><i style="background:#1f3a68"></i>比特币÷黄金（左轴）</label>
    <label class="btcg-chk"><input type="checkbox" data-s="m2" checked><i style="background:#2f6b4f"></i>全球货币供应（右轴）</label>
    <label class="btcg-chk"><input type="checkbox" data-s="debt" checked><i style="background:#b0493a"></i>美国联邦债务（右轴）</label>
    <label class="btcg-chk"><input type="checkbox" data-s="ev" checked><i style="background:#b07a5a;border-radius:50%"></i>事件标注</label>
  </div>
  <div class="btcg-chart" id="btcg-chart"></div>
  <div class="btcg-pin" id="btcg-pin">悬停图上任意位置可看横纵坐标，点击可锁定。</div>
  <div class="sgr-title">暴涨暴跌时点的事件（<span id="btcg-evn">{len(evs)}</span> 条，编号对应图上标记；随上方时间段联动）</div>
  <div class="btcg-legend"><i style="background:#2f6b4f"></i>多方来源或原文已核验 <i style="background:#b07a5a"></i>出处可读，部分数字未能逐字核对</div>
  <div class="btcg-tabbox"><table class="btcg-tab"><thead><tr><th>#</th><th>日期</th><th>事件与价格</th><th>当日 BTC</th><th>出处</th></tr></thead><tbody id="btcg-tb"></tbody></table></div>
  <div class="sgr-foot">
    三条线各用独立纵轴：比特币÷黄金为左轴（对数，1 个比特币＝多少盎司黄金）；全球货币供应与美国联邦债务共用右轴（万亿美元，线性）。
    比特币：blockchain.com 市场均价（美元，日度，2010-08-18 起首次有价），月内取均值；黄金：伦敦金月均价（与金油比、股金比同底表），当月用 COMEX 期货日收盘均值。<br>
    全球货币供应＝美国 M2、欧元区 M3、日本 M2、英国 M4、中国 M2 按当期汇率折美元的自行聚合值，不是任何机构的官方数字；早期国家不全（1996 年仅 2 国），悬停会显示覆盖国数。
    美国联邦债务＝FRED GFDEBTN（联邦债务总额，季度，取季度首月），最新到 {_esc(dl.get('m',''))}。<br>
    事件为「价格先行」：先从价格找出转折点与极端涨跌日，再联网检索当日新闻，每条出处都经 web_extract 独立读取核验；只陈述事件和价格变化，不下因果结论。
    未找到明确触发事件的异动日：{nf_html or "无"}。早期（2010–2013）比特币成交量极小、各交易所价差大，数值仅供参考。随 dashboard 每日更新，事件清单每周人工复核。
  </div>
  <script type="application/json" id="btcg-data">{js}</script>
</div>"""


def _us_freight_html(o):
    """美国货运: 铁路周度(AAR, 10 类商品 + 联运, 按钮筛选 + 周/4周均线切换) + 公路月度(ATA 吨位 / Cass 发货量)。"""
    import json as _json
    wk = ((o or {}).get("rail") or {}).get("weeks") or []
    if len(wk) < 20:
        err = "；".join((o or {}).get("warnings", [])[:2])
        return f'<p class="empty">美国货运数据同步中{("：" + _esc(err)) if err else ""}。</p>'
    ZH = {"Total Traffic": "铁路总运量", "Total Carloads": "车皮合计", "Intermodal": "联运(集装箱/拖车)",
          "Chemicals": "化工品", "Coal": "煤炭", "Farm Products excl. Grain, and Food": "农产品(除谷物)及食品",
          "Forest Products": "林产品", "Grain": "谷物", "Metallic Ores and Metals": "金属矿及金属",
          "Motor Vehicles and Parts": "汽车及零部件", "Nonmetallic Minerals": "非金属矿",
          "Petroleum and Petroleum Products": "石油及制品", "Other": "其他"}
    keys = list(ZH)
    rail = {"d": [x["d"] for x in wk], "s": {k: [x[k] for x in wk] for k in keys}}
    road = (o or {}).get("road") or {}
    data = _json.dumps({"rail": rail, "zh": ZH, "ata": road.get("ata", []), "cass": road.get("cass", []),
                        "diesel": (o or {}).get("diesel", []), "ppi_tl": road.get("ppi_tl", []), "cass_exp": road.get("cass_exp", [])},
                       ensure_ascii=False, separators=(",", ":"))
    sn = ((o or {}).get("sonar") or {}).get("rows") or []
    dsl = (o or {}).get("diesel") or []
    def _yoyd(s):
        if len(s) < 53: return "—"
        import datetime as _d2
        t = _d2.date.fromisoformat(s[-1]["d"]) - _d2.timedelta(days=364)
        b = next((x for x in s if abs((_d2.date.fromisoformat(x["d"]) - t).days) <= 3), None)
        return f"{(s[-1]['v']/b['v']-1)*100:+.1f}%" if b else "—"
    ppi = road.get("ppi_tl") or []
    sonar_html = ""
    if sn:
        z = sn[-1]
        sonar_html = f"""
  <div class="sgr-stat">
    <span>合同货拒载率 <b>{z['stri']:.2f}%</b><i>SONAR STRI · 抓取日 {z['d']}（OTRI {z['otri'] if z.get('otri') is not None else '—'}%）</i></span>
    <span>卡车现货运价 <b>${z['nti']:.2f}/英里</b><i>SONAR NTI（含燃油附加费）</i></span>
    <span>合同运价 <b>${z['vcrpm1']:.2f}/英里</b><i>SONAR VCRPM1（不含燃油）</i></span>
    <span>本站已积累 <b>{len(sn)} 天</b><i>公开页只有当日读数，逐日积累成序列</i></span>
  </div>"""
    btns = "".join(f'<button type="button" class="frt-b{" on" if k == "Total Traffic" else ""}" data-k="{_esc(k)}">{_esc(ZH[k])}</button>' for k in keys)
    L = wk[-1]
    import datetime as _d
    _t = _d.date.fromisoformat(L["d"]) - _d.timedelta(days=364)   # 去年同一周(差 52 周, 与 AAR 口径一致)
    prev = next((x for x in wk if abs((_d.date.fromisoformat(x["d"]) - _t).days) <= 3), None)
    yoy = lambda k: (f"{(L[k]/prev[k]-1)*100:+.1f}%" if prev and prev.get(k) else "—")
    ata = road.get("ata") or []; cass = road.get("cass") or []
    def myoy(s):
        if len(s) < 13: return "—"
        a, b = s[-1], next((x for x in s if x["m"] == f"{int(s[-1]['m'][:4])-1}{s[-1]['m'][4:]}"), None)
        return f"{(a['v']/b['v']-1)*100:+.1f}%" if b else "—"
    warn = f'<p class="sgr-warn">⚠ {_esc("；".join(o["warnings"][:2]))}</p>' if o.get("warnings") else ""
    return f"""
<div class="tfs-wrap frt-wrap">
  {warn}
  <div class="sgr-stat">
    <span>铁路总运量 <b>{L['Total Traffic']:,}</b><i>周截至 {L['d']} · 同比 {yoy('Total Traffic')}</i></span>
    <span>车皮 / 联运 <b>{L['Total Carloads']:,} / {L['Intermodal']:,}</b><i>同比 {yoy('Total Carloads')} / {yoy('Intermodal')}</i></span>
    <span>卡车吨位指数 <b>{ata[-1]['v'] if ata else '—'}</b><i>{ata[-1]['m'] if ata else ''} · 同比 {myoy(ata)}（ATA，2015=100）</i></span>
    <span>Cass 发货量 <b>{cass[-1]['v'] if cass else '—'}</b><i>{cass[-1]['m'] if cass else ''} · 同比 {myoy(cass)}（1990-01=1）</i></span>
  </div>
  <div class="sgr-title">铁路周度货运量（AAR，单位：车皮/联运单元）</div>
  <div class="frt-bar">{btns}</div>
  <div class="frt-bar frt-opt">
    <button type="button" class="frt-m on" data-m="raw">每周</button><button type="button" class="frt-m" data-m="ma4">4 周均线</button>
    <button type="button" class="frt-m" data-m="yoy">同比 %</button>
    <span class="frt-sep"></span>
    <button type="button" class="frt-r" data-r="1">1 年</button><button type="button" class="frt-r" data-r="3">3 年</button><button type="button" class="frt-r on" data-r="5">5 年</button>
  </div>
  <div class="frt-chart" id="frt-rail"></div>
  <div class="sgr-title">公路货运（月度指数）</div>
  <div class="frt-chart" id="frt-road"></div>
  <div class="sgr-title">公路运力与成本</div>
  <div class="sgr-stat">
    <span>柴油零售价 <b>${(dsl[-1]['v'] if dsl else 0):.3f}/加仑</b><i>{dsl[-1]['d'] if dsl else ''} · 同比 {_yoyd(dsl)}（EIA 周度）</i></span>
    <span>整车长途运价 PPI <b>{ppi[-1]['v'] if ppi else '—'}</b><i>{ppi[-1]['m'] if ppi else ''} · 同比 {myoy(ppi)}（2003-12=100）</i></span>
  </div>{sonar_html}
  <div class="frt-chart" id="frt-diesel"></div>
  <div class="frt-chart" id="frt-cost"></div>
  <div class="sgr-foot">
    铁路：美国铁路协会（AAR）每周三发布的 Weekly Rail Traffic 美国部分（不含 CPKC、CN、GMXT 在美业务），本站逐份解析 PDF，
    每份都校验「10 类之和＝车皮合计、车皮＋联运＝总运量」，不符即不入库（2024-04-06 那一周 AAR 网站上没有该期文件，周度图中前后两周直接相连，同比图中对应周留空）。点按钮切换品类（可多选对比），「同比」与去年同一周比较。
    公路：美国没有公开的全国卡车周度运量，只有月度指数——ATA 卡车吨位指数（美国卡车运输协会，经季调，约 2 个月滞后）与 Cass 发货量指数
    （按 Cass 处理的企业货运账单统计，未季调，含多种运输方式但以公路为主）。两者都是指数，不是吨数。运力与成本：柴油为美国能源信息署（EIA）全美柴油零售均价（每周一）；整车长途运价 PPI 为美国劳工统计局生产者价格指数（月度）；Cass 运费支出指数＝发货量×运价。拒载率、现货/合同运价来自 FreightWaves SONAR 公开展示页的当日读数——完整历史为付费数据，本站只能从 2026-10-01 起每个工作日抓一次逐日积累，页面被拦截的日子会缺。随 dashboard 每日检查更新。
  </div>
  <script type="application/json" id="frt-data">{data}</script>
</div>"""


def _ust_micro_line(items, W=880, H=150, PL=58, PR=10, PT=10, PB=22, color="#6b7f8a", unit=""):
    """通用小折线, items=[{d,v}]。"""
    if len(items) < 3:
        return ""
    vals = [p["v"] for p in items]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    iw, ih = W - PL - PR, H - PT - PB
    def X(i): return PL + iw * i / max(len(items) - 1, 1)
    def Y(v): return PT + ih * (1 - (v - lo) / rng)
    pts = " ".join(f"{X(i):.1f},{Y(p['v']):.1f}" for i, p in enumerate(items))
    grid = ""
    for k in range(4):
        v = lo + rng * k / 3
        y = Y(v)
        lab = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"
        grid += (f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" class="um-grid"/>'
                 f'<text x="{PL-6}" y="{y+3.5:.1f}" class="um-yt">{lab}</text>')
    xt = ""
    seen = set()
    for i, p in enumerate(items):
        yr = p["d"][:4]
        if yr not in seen and (i == 0 or i > 6):
            seen.add(yr)
            xt += f'<text x="{X(i):.1f}" y="{H-6}" class="um-xt">{yr}</text>'
    _fv = (lambda v: f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}")
    hits = _hover_bands([X(i) for i in range(len(items))],
                        [f'{_esc(p["d"])}||{_fv(p["v"])}{_esc(unit)}' for p in items],
                        PT, ih, PL, W - PR)
    return (f'<svg viewBox="0 0 {W} {H}" class="um-chart" preserveAspectRatio="xMidYMid meet">'
            f'{grid}<polyline points="{pts}" style="stroke:{color}" class="um-line"/>'
            f'<circle cx="{X(len(items)-1):.1f}" cy="{Y(vals[-1]):.1f}" r="3.6" '
            f'style="fill:{color}"/>{xt}{hits}</svg>')


def _ust_micro_html(m):
    """国债市场微观结构 —— MS Exhibit 3(交易成本) / Exhibit 4(成交量)。"""
    if not m or not str(m.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(m.get("errors", [])[:2])) if m and m.get("errors") else ""
        return f'<p class="empty">国债微观结构数据同步中{err}。</p>'

    vol = m.get("volume") or {}
    cost = m.get("cost") or {}
    bks = vol.get("buckets") or []
    tot = vol.get("total")

    # ── Exhibit 4: 成交量(真数据) ──
    rows = ""
    for b in bks:
        cls = "pos" if b["vs_avg"] > 0 else "neg"
        star = ' <span class="um-star">★ MS 2Y 对应桶</span>' if b.get("tag") else ""
        rows += (f'<tr><td class="um-n">{b["name"]}{star}</td>'
                 f'<td class="um-v">{b["latest"]:,.0f}</td>'
                 f'<td class="um-v">{b["avg_52w"]:,.0f}</td>'
                 f'<td class="um-v {cls}">{b["vs_avg"]:+.1f}%</td></tr>')
    tot_line = ""
    if tot:
        c = "pos" if tot["vs_avg"] > 0 else "neg"
        tot_line = (f'<tr class="um-tot"><td>{tot["name"]}</td>'
                    f'<td class="um-v">{tot["latest"]:,.0f}</td>'
                    f'<td class="um-v">{tot["avg_52w"]:,.0f}</td>'
                    f'<td class="um-v {c}">{tot["vs_avg"]:+.1f}%</td></tr>')

    # 主图用 2Y 桶
    two = next((b for b in bks if b.get("tag")), bks[0] if bks else None)
    chart2y = _ust_micro_line(two["series"], color="#6b7f8a", unit=" 百万美元") if two else ""

    # ── Exhibit 3: 交易成本(代理) ──
    cost_blocks = ""
    for c in cost.get("series", []):
        cost_blocks += (
            f'<div class="um-cost-one">'
            f'<div class="um-cost-h"><b>{c["name"]}</b>'
            f'<span class="um-cost-v">{c["latest"]:.2f}{c["unit"]}</span>'
            f'<span class="um-pct">3年分位 {c["pct_rank"]}%</span></div>'
            f'<div class="um-cost-d">{c["desc"]}　·　{c["latest_date"]}　·　'
            f'区间 {c["min"]:.2f} ~ {c["max"]:.2f}</div>'
            f'{_ust_micro_line(c["series"], H=130, color="#a08b6a", unit=c.get("unit", ""))}</div>')

    return f"""
<div class="um-wrap">
  <div class="um-sec">
    <div class="um-h">
      <span class="um-badge real">真数据</span>
      Exhibit 4 对口 · 一级交易商美债成交量（按剩余期限）
    </div>
    <div class="um-src">{vol.get("source","")}</div>
    <div class="um-caliber">⚠ <b>口径差异</b>：{vol.get("caliber_note","")}</div>
    <table class="um-table">
      <thead><tr><th>期限桶</th><th>最新周成交<br><i>百万美元</i></th>
        <th>52 周均值</th><th>偏离</th></tr></thead>
      <tbody>{rows}{tot_line}</tbody>
    </table>
    <div class="um-cap">≤2 年桶周度成交量走势（对应 MS Exhibit 4 的 2Y OTR）</div>
    {chart2y}
  </div>

  <div class="um-sec">
    <div class="um-h">
      <span class="um-badge proxy">代理指标</span>
      Exhibit 3 对口 · 交易成本压力
    </div>
    <div class="um-proxy">⚠ <b>这不是买卖价差本身</b>：{cost.get("proxy_note","")}
      <br><span class="um-excl">{cost.get("excluded_note","")}</span></div>
    {cost_blocks}
    <div class="um-src">{cost.get("source","")}</div>
  </div>
</div>"""



def _dxy_gold_html(dg):
    """美元指数 vs 黄金 双轴走势 + 已核实事件标注。"""
    if not dg or not str(dg.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(dg.get("errors", [])[:2])) if dg and dg.get("errors") else ""
        return f'<p class="empty">美元/黄金数据同步中{err}。</p>'
    ser = dg.get("series") or []
    if len(ser) < 20:
        return '<p class="empty">美元/黄金：数据点不足。</p>'

    evs = [e for e in (dg.get("events") or [])
           if e.get("confidence") in ("high", "medium") and e.get("on_chart")]
    evs.sort(key=lambda e: e["date"])

    W, H = 960, 340
    PL, PR, PT, PB = 58, 62, 44, 30
    iw, ih = W - PL - PR, H - PT - PB
    gs = [p["g"] for p in ser]; xs = [p["x"] for p in ser]
    glo, ghi = min(gs), max(gs); xlo, xhi = min(xs), max(xs)
    gr = (ghi - glo) or 1.0; xr = (xhi - xlo) or 1.0
    idx = {p["d"]: i for i, p in enumerate(ser)}

    def X(i): return PL + iw * i / max(len(ser) - 1, 1)
    def YG(v): return PT + ih * (1 - (v - glo) / gr)
    def YX(v): return PT + ih * (1 - (v - xlo) / xr)

    gold_pts = " ".join(f"{X(i):.1f},{YG(p['g']):.1f}" for i, p in enumerate(ser))
    dxy_pts  = " ".join(f"{X(i):.1f},{YX(p['x']):.1f}" for i, p in enumerate(ser))

    # 左轴(黄金) / 右轴(DXY)
    axis = ""
    for k in range(5):
        yv = glo + gr * k / 4
        y = YG(yv)
        axis += (f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" class="dxg-grid"/>'
                 f'<text x="{PL-7}" y="{y+3.5:.1f}" class="dxg-yl">{yv:,.0f}</text>')
        xv = xlo + xr * k / 4
        axis += (f'<text x="{W-PR+7}" y="{YX(xv)+3.5:.1f}" class="dxg-yr">{xv:.1f}</text>')
    # 月份刻度
    xt = ""; seen = set()
    for i, p in enumerate(ser):
        m = p["d"][:7]
        if m not in seen:
            seen.add(m)
            xt += f'<text x="{X(i):.1f}" y="{H-10}" class="dxg-xt">{p["d"][5:7]}月</text>'

    # ── 事件标记: 交替上下两层, 避免重叠 ──
    marks = ""; labels = ""
    lane = 0
    prev_x = -99
    for n, e in enumerate(evs, 1):
        i = idx.get(e["date"])
        if i is None: continue
        x = X(i)
        yg = YG(e.get("gold", ser[i]["g"]))
        # 密集时上下交替
        if x - prev_x < 34:
            lane = (lane + 1) % 3
        else:
            lane = 0
        prev_x = x
        ly = PT - 8 - lane * 12
        cls = "cal" if e.get("kind") == "calendar" else ("med" if e.get("confidence") == "medium" else "hi")
        marks += (f'<line x1="{x:.1f}" y1="{ly+4:.1f}" x2="{x:.1f}" y2="{yg:.1f}" class="dxg-vl {cls}"/>'
                  f'<circle cx="{x:.1f}" cy="{yg:.1f}" r="3.2" class="dxg-dot {cls}"/>')
        labels += (f'<text x="{x:.1f}" y="{ly:.1f}" class="dxg-num {cls}">{n}</text>')

    # ── 事件清单(编号对应图上标记) ──
    rows = ""
    for n, e in enumerate(evs, 1):
        cls = "cal" if e.get("kind") == "calendar" else ("med" if e.get("confidence") == "medium" else "hi")
        badge = ("日历" if e.get("kind") == "calendar"
                 else ("待核" if e.get("confidence") == "medium" else "已核"))
        chg = ""
        if e.get("gold_pct") is not None:
            gc = "up" if e["gold_pct"] > 0 else "down"
            dc = "up" if (e.get("dxy_pct") or 0) > 0 else "down"
            chg = (f'<span class="dxg-chg {gc}">金 {e["gold_pct"]:+.2f}%</span>'
                   f'<span class="dxg-chg {dc}">汇 {e.get("dxy_pct",0):+.2f}%</span>')
        link = (f'<a href="{e["url"]}" target="_blank" rel="noopener">{e.get("source","出处")}</a>'
                if e.get("url") else '<span class="dxg-nolink">无出处</span>')
        note = f'<div class="dxg-vn">⚠ {e["verify_note"]}</div>' if e.get("verify_note") else ""
        rows += (f'<tr><td class="dxg-i {cls}">{n}</td>'
                 f'<td class="dxg-d">{e["date"]}<span class="dxg-bg {cls}">{badge}</span></td>'
                 f'<td class="dxg-e"><b>{e.get("event","")}</b>{chg}'
                 f'<div class="dxg-dt">{e.get("detail","")}</div>{note}</td>'
                 f'<td class="dxg-s">{link}</td></tr>')

    unc = dg.get("uncovered") or []
    unc_line = ""
    if unc:
        unc_line = (f'<div class="dxg-unc">另有 <b>{len(unc)}</b> 个异动日未找到明确触发事件（'
                    + "、".join(u["d"] for u in unc[:8])
                    + ("…" if len(unc) > 8 else "") + '）—— 如实列出，不硬凑。</div>')

    stale = ""
    if dg.get("events_stale"):
        stale = (f'<div class="dxg-stale">⚠ 事件清单已 {dg.get("events_age_days","?")} 天未更新'
                 f'（应每周重新核实一次）</div>')

    g0, g1 = ser[0]["g"], ser[-1]["g"]
    x0, x1 = ser[0]["x"], ser[-1]["x"]
    return f"""
<div class="dxg-wrap">
  <div class="dxg-stat">
    <span>黄金 {dg["gold"]["sym"]}<b>{g1:,.2f}</b>
      <i>年初 {g0:,.0f} → {(g1/g0-1)*100:+.1f}%</i></span>
    <span>美元指数 {dg["dxy"]["sym"]}<b>{x1:.2f}</b>
      <i>年初 {x0:.2f} → {(x1/x0-1)*100:+.1f}%</i></span>
    <span>已标注事件<b>{len(evs)}</b><i>{dg["start"]} 至今</i></span>
    <span>异动日<b>{len(dg.get("anomalies") or [])}</b>
      <i>|日收益| ≥ {dg["sigma"]["th"]}σ</i></span>
  </div>

  <div class="dxg-legend">
    <span class="dxg-lg gold">— 黄金（左轴，美元/盎司）</span>
    <span class="dxg-lg dxy">— 美元指数（右轴）</span>
    <span class="dxg-lg hi">● 已核实事件</span>
    <span class="dxg-lg cal">● FOMC 日历</span>
  </div>

  <svg viewBox="0 0 {W} {H}" class="dxg-chart" preserveAspectRatio="xMidYMid meet">
    {axis}
    <polyline points="{gold_pts}" class="dxg-gold"/>
    <polyline points="{dxy_pts}" class="dxg-dxy"/>
    {marks}{labels}{xt}
    {_hover_bands([X(i) for i in range(len(ser))], [f"{_esc(p['d'])}||黄金 ${p['g']:,.2f}&lt;br&gt;美元指数 {p['x']:.2f}" for p in ser], PT, ih, PL, W - PR)}
  </svg>

  <div class="dxg-method">{dg.get("method_note","")}<br>{dg.get("cadence_note","")}</div>
  {stale}{unc_line}

  <details class="dxg-det" open>
    <summary>事件明细（{len(evs)} 条，编号对应图上标记）</summary>
    <table class="dxg-table"><tbody>{rows}</tbody></table>
  </details>
</div>"""



def _gold_etf_region_html(gf):
    """黄金 ETF 分地区周度资金流(WGC 官方) + 金价叠加。"""
    if not gf or not str(gf.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(gf.get("errors", [])[:2])) if gf and gf.get("errors") else ""
        return f'<p class="empty">WGC 黄金 ETF 资金流数据同步中{err}。</p>'
    wk = gf.get("weeks") or []
    if len(wk) < 8:
        return '<p class="empty">WGC 黄金 ETF 资金流：数据点不足。</p>'

    REG = ["北美", "欧洲", "亚洲", "其他"]
    COL = {"北美": "#7d94a8", "欧洲": "#9a8c6e", "亚洲": "#8d9c86", "其他": "#b0a49a"}
    W, H = 960, 320
    PL, PR, PT, PB = 54, 60, 22, 40
    iw, ih = W - PL - PR, H - PT - PB

    # 堆叠柱: 正负分别向上/向下堆
    lo = min(min(0, sum(r[k] for k in REG if r[k] < 0)) for r in wk)
    hi = max(max(0, sum(r[k] for k in REG if r[k] > 0)) for r in wk)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    def Y(v): return PT + ih * (1 - (v - lo) / (hi - lo))
    bw = iw / len(wk) * 0.66
    def X(i): return PL + iw * (i + 0.5) / len(wk)

    bars = ""
    for i, r in enumerate(wk):
        x = X(i) - bw / 2
        up = dn = 0.0
        for k in REG:
            v = r[k]
            if v >= 0:
                y0, y1 = Y(up + v), Y(up); up += v
            else:
                y0, y1 = Y(dn), Y(dn + v); dn += v
            h = abs(y1 - y0)
            if h < 0.35: continue
            bars += (f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}" fill="{COL[k]}" opacity=".9" '
                     f'data-tip="{_esc(r["d"])} · {k}||{v:+.2f} 吨（当周合计 {r["total"]:+.2f} 吨）"/>')

    # 金价折线(右轴)
    pxs = [r["px"] for r in wk if r["px"]]
    pline = ""
    if len(pxs) > 4:
        plo, phi = min(pxs), max(pxs)
        pr_ = (phi - plo) or 1
        def YP(v): return PT + ih * (1 - (v - plo) / pr_) * 0.92 + ih * 0.04
        pts = " ".join(f"{X(i):.1f},{YP(r['px']):.1f}" for i, r in enumerate(wk) if r["px"])
        pline = f'<polyline points="{pts}" class="gef-px"/>'
        pline += "".join(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{YP(r["px"]):.1f}" r="6" '
                         f'data-tip="{_esc(r["d"])} · 金价||${r["px"]:,.0f}/盎司"/>'
                         for i, r in enumerate(wk) if r["px"])
        for k in range(3):
            v = plo + pr_ * k / 2
            pline += f'<text x="{W-PR+6}" y="{YP(v)+3.5:.1f}" class="gef-yr">{v:,.0f}</text>'

    grid = f'<line x1="{PL}" y1="{Y(0):.1f}" x2="{W-PR}" y2="{Y(0):.1f}" class="gef-zero"/>'
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        grid += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="gef-grid"/>'
                 f'<text x="{PL-7}" y="{Y(v)+3.5:.1f}" class="gef-yl">{v:+.0f}</text>')
    xt = ""; seen = set()
    for i, r in enumerate(wk):
        m = r["d"][:7]
        if m not in seen:
            seen.add(m)
            xt += f'<text x="{X(i):.1f}" y="{H-14}" class="gef-xt">{r["d"][5:7]}月</text>'

    t = gf.get("totals") or {}
    def _cell(dd, lab):
        tv = dd.get("total", 0)
        cls = "in" if tv > 0 else "out"
        cells = "".join(f'<span class="gef-r"><i style="background:{COL[k]}"></i>'
                        f'{k} <b class="{"in" if dd.get(k,0)>0 else "out"}">{dd.get(k,0):+.1f}</b></span>'
                        for k in REG)
        return (f'<div class="gef-card"><div class="gef-lab">{lab}</div>'
                f'<div class="gef-tot {cls}">{tv:+.1f} <small>吨</small></div>'
                f'<div class="gef-rs">{cells}</div></div>')

    ex = gf.get("extremes") or {}
    rank = ""
    if ex.get("latest_rank_out"):
        rank = (f'最新一周在 {ex["n_all"]} 周历史中流出排名第 <b>{ex["latest_rank_out"]}</b>'
                f'（样本自 {ex.get("hist_start","")}）')
    worst = "、".join(f'{r["d"]} {r["total"]:.1f}t' for r in (ex.get("worst_all") or [])[:3])

    rows = "".join(
        f'<tr><td>{r["d"]}</td>'
        + "".join(f'<td class="{"in" if r[k]>0 else "out"}">{r[k]:+.2f}</td>' for k in REG)
        + f'<td class="gef-tt {"in" if r["total"]>0 else "out"}">{r["total"]:+.2f}</td>'
          f'<td class="gef-px-c">{r["px"]:,.0f}</td></tr>'
        for r in wk[::-1][:16])

    return f"""
<div class="gef-wrap">
  <div class="gef-src">
    数据源：<b>{gf.get("source","")}</b> —— 与市面上流传的 WGC「Gold ETF flows」图<b>同源</b>。
    实测复核：2026-06-12 = −24.7 吨、2026-06-26 = −38.2 吨，与公开图表标注逐字吻合。
    数据日 <b>{gf.get("as_of_data","")}</b>（WGC 每周更新）·
    <a href="{gf.get("source_url","")}" target="_blank" rel="noopener">官方页面</a>
  </div>

  <div class="gef-cards">
    {_cell(t.get("latest", {}), "最新一周")}
    {_cell(t.get("w4", {}), "近 4 周累计")}
    {_cell(t.get("w13", {}), "近 13 周累计")}
    {_cell(t.get("ytd", {}), "年初至今累计")}
  </div>

  <div class="gef-legend">
    {"".join(f'<span><i style="background:{COL[k]}"></i>{k}</span>' for k in REG)}
    <span><i class="gef-pxi"></i>金价（右轴，美元/盎司）</span>
  </div>

  <svg viewBox="0 0 {W} {H}" class="gef-chart" preserveAspectRatio="xMidYMid meet">
    {grid}{bars}{pline}{xt}
    <text x="{PL-7}" y="{PT-6}" class="gef-unit">吨</text>
  </svg>

  <div class="gef-ctx">{rank}　·　历史最大单周流出：{worst}</div>

  <div class="gef-silver">
    <b>为什么没有白银？</b>{gf.get("silver_note","")}
  </div>

  <details class="gef-det">
    <summary>近 16 周明细（吨）</summary>
    <table class="gef-table">
      <thead><tr><th>周</th>{"".join(f"<th>{k}</th>" for k in REG)}
        <th>合计</th><th>金价</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </details>
</div>"""



def _pm_optvol_html(pv):
    """贵金属期权: ATM IV 期限结构 + 25D 偏斜(CBOE 真数据)。"""
    if not pv or not str(pv.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(pv.get("errors", [])[:2])) if pv and pv.get("errors") else ""
        return f'<p class="empty">贵金属期权波动率数据同步中{err}。</p>'
    tks = pv.get("tickers") or {}
    if not tks:
        return '<p class="empty">贵金属期权：无可用数据。</p>'

    COL = {"GLD": "#b08a3e", "SLV": "#7d94a8", "IAU": "#8d9c86"}
    ORDER = [t for t in ("GLD", "SLV", "IAU") if t in tks]

    def _chart(field, title, unit, zero_line=False):
        W, H = 940, 290
        PL, PR, PT, PB = 58, 26, 26, 40
        iw, ih = W - PL - PR, H - PT - PB
        labs, vals = [], []
        for tk in ORDER:
            arr = tks[tk].get("term" if field == "atm" else "skew") or []
            for x in arr:
                if x.get(field) is not None:
                    vals.append(x[field])
                    if x["t"] not in labs:
                        labs.append(x["t"])
        if not vals or len(labs) < 2:
            return f'<p class="empty">{title}：数据不足。</p>'
        order = ["1M", "3M", "6M", "12M", "18M", "24M"]
        labs = [l for l in order if l in labs]
        lo, hi = min(vals), max(vals)
        if zero_line:
            lo, hi = min(lo, 0), max(hi, 0)
        pad = (hi - lo) * 0.14 or 1
        lo, hi = lo - pad, hi + pad

        def X(i): return PL + iw * i / max(len(labs) - 1, 1)
        def Y(v): return PT + ih * (1 - (v - lo) / (hi - lo))

        grid = ""
        for k in range(5):
            v = lo + (hi - lo) * k / 4
            grid += (f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" class="pv-grid"/>'
                     f'<text x="{PL-7}" y="{Y(v)+3.5:.1f}" class="pv-yl">{v:.1f}</text>')
        if zero_line and lo < 0 < hi:
            grid += f'<line x1="{PL}" y1="{Y(0):.1f}" x2="{W-PR}" y2="{Y(0):.1f}" class="pv-zero"/>'
        xt = "".join(f'<text x="{X(i):.1f}" y="{H-14}" class="pv-xt">{l}</text>'
                     for i, l in enumerate(labs))

        lines = ""
        for tk in ORDER:
            arr = tks[tk].get("term" if field == "atm" else "skew") or []
            m = {x["t"]: x.get(field) for x in arr if x.get(field) is not None}
            pts = [(X(i), Y(m[l])) for i, l in enumerate(labs) if l in m]
            if len(pts) < 2:
                continue
            path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            lines += f'<polyline points="{path}" class="pv-ln" stroke="{COL[tk]}"/>'
            for i, l in enumerate(labs):
                if l in m:
                    lines += (f'<circle cx="{X(i):.1f}" cy="{Y(m[l]):.1f}" r="3" fill="{COL[tk]}"/>'
                              f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(m[l]):.1f}" r="8" '
                              f'data-tip="{tk} · 期限 {l}||{m[l]:.2f} {unit}"/>')
        return f"""
  <div class="pv-block">
    <div class="pv-t">{title}</div>
    <svg viewBox="0 0 {W} {H}" class="pv-chart" preserveAspectRatio="xMidYMid meet">
      {grid}{lines}{xt}
      <text x="{PL-7}" y="{PT-8}" class="pv-unit">{unit}</text>
    </svg>
  </div>"""

    cards = ""
    for tk in ORDER:
        v = tks[tk]
        term = {x["t"]: x.get("atm") for x in (v.get("term") or [])}
        skew = {x["t"]: x.get("skew") for x in (v.get("skew") or [])}
        sh = v.get("shape") or "—"
        shc = "inv" if sh == "倒挂" else "nor"
        s12 = skew.get("12M")
        bias = ("偏多" if s12 is not None and s12 < 0 else
                "偏空" if s12 is not None else "—")
        bc = "bull" if bias == "偏多" else ("bear" if bias == "偏空" else "")
        dup = (f'<div class="pv-warn">⚠ {v["dup_note"]}</div>' if v.get("dup_note") else "")
        cards += (f'<div class="pv-card"><div class="pv-ct">'
                  f'<i style="background:{COL[tk]}"></i>{tk}'
                  f'<small>现价 {v.get("spot")}</small></div>'
                  f'<div class="pv-row"><span>1M ATM IV</span>'
                  f'<b>{term.get("1M","—")}%</b></div>'
                  f'<div class="pv-row"><span>12M ATM IV</span>'
                  f'<b>{term.get("12M","—")}%</b></div>'
                  f'<div class="pv-row"><span>期限结构</span>'
                  f'<b class="{shc}">{sh}</b></div>'
                  f'<div class="pv-row"><span>12M 25D 偏斜</span>'
                  f'<b class="{bc}">{s12 if s12 is not None else "—"}　{bias}</b></div>'
                  f'<div class="pv-sub">到期日 {v.get("n_exp")} · 合约 {v.get("n_contract")}</div>'
                  f'{dup}</div>')

    legend = "".join(f'<span><i style="background:{COL[t]}"></i>{t}</span>' for t in ORDER)

    return f"""
<div class="pv-wrap">
  <div class="pv-cards">{cards}</div>
  <div class="pv-legend">{legend}</div>

  {_chart("atm", "① ATM 隐含波动率 期限结构（近月 &gt; 远月 = 倒挂，市场预期近期震荡）", "%")}
  {_chart("skew", "② 25-Delta 偏斜：Put IV − Call IV（正值 = 看跌期权更贵 = 偏空）", "pt", True)}

  <div class="pv-method">{pv.get("method_note","")}</div>
  <div class="pv-hist">
    <b>历史说明：</b>{pv.get("hist_note","")}
    数据源：{pv.get("source","")}。
  </div>
</div>"""



def _comex_optpos_html(cx):
    """COMEX 期货期权持仓(Managed Money 方向) —— 注意这不是 IV。"""
    if not cx or not str(cx.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(cx.get("errors", [])[:2])) if cx and cx.get("errors") else ""
        return f'<p class="empty">COMEX 期货期权持仓数据同步中{err}。</p>'
    ms = cx.get("metals") or {}
    if not ms:
        return '<p class="empty">COMEX 期货期权持仓：无可用数据。</p>'

    COL = {"gold": "#b08a3e", "silver": "#7d94a8"}

    def _bars(key, v):
        """期权净多周度柱状图(正上负下, 零轴居中) + ★2026-10-06 叠加 COMEX 连续合约日线价格(右轴)。"""
        ser = v.get("series") or []
        ser = ser[-104:]
        vals = [x["net_opt"] for x in ser]
        if len(vals) < 4:
            return ""
        px_all = v.get("price") or []
        W, H = 940, 220
        PL, PR, PT, PB = 62, (64 if px_all else 16), 16, 30
        iw, ih = W - PL - PR, H - PT - PB
        lo, hi = min(vals + [0]), max(vals + [0])
        pad = (hi - lo) * 0.10 or 1
        lo, hi = lo - pad, hi + pad
        def Y(y): return PT + ih * (1 - (y - lo) / (hi - lo))
        bw = max(iw / len(ser) * 0.78, 1.2)
        y0 = Y(0)
        # ── 价格线: 只取柱图时间窗内的日线, 横坐标按「日期在 [首周, 末周] 里的位置」映射到与柱同一条时间轴 ──
        import datetime as _d
        def _dd(s): return _d.date.fromisoformat(s[:10])
        d0, d1 = _dd(ser[0]["d"]), _dd(ser[-1]["d"])
        span = max((d1 - d0).days, 1)
        def XD(s): return PL + iw * (0.5 / len(ser)) + (iw * (1 - 1.0 / len(ser))) * ((_dd(s) - d0).days / span)
        px = [(p[0], p[1]) for p in px_all if d0 <= _dd(p[0]) <= d1 + _d.timedelta(days=4)]
        PCOL = "#2f5d8a" if key == "silver" else "#7a4b12"
        price_svg = legend_px = ""
        if len(px) >= 10:
            pvals = [p[1] for p in px]
            plo, phi = min(pvals), max(pvals)
            pp = (phi - plo) * 0.08 or 1
            plo, phi = plo - pp, phi + pp
            def YP(v): return PT + ih * (1 - (v - plo) / (phi - plo))
            price_svg = ('<polyline fill="none" stroke="' + PCOL + '" stroke-width="1.5" opacity=".95" points="'
                         + " ".join(f"{XD(a):.1f},{YP(b):.1f}" for a, b in px) + '"/>')
            ax = ""
            for k in range(4):
                pv = plo + (phi - plo) * k / 3
                ax += f'<text x="{W-PR+6}" y="{YP(pv)+3.5:.1f}" class="cxo-yl" style="text-anchor:start;fill:{PCOL}">${pv:,.0f}</text>'
            price_svg += ax
            legend_px = (f'<span class="cxo-lg"><i style="background:{PCOL}"></i>COMEX {"白银 SI=F" if key=="silver" else "黄金 GC=F"} 收盘价（右轴 · 日线）</span>'
                         f'<span class="cxo-lg"><i style="background:{COL[key]}"></i>期权净多（左轴 · 周度柱，正=净多 / 负=净空）</span>')
        bars = ""
        for i, x in enumerate(ser):
            cx_ = PL + iw * (i + 0.5) / len(ser)
            yv = Y(x["net_opt"])
            top, h = (yv, y0 - yv) if x["net_opt"] >= 0 else (y0, yv - y0)
            fill = COL[key] if x["net_opt"] >= 0 else "#a3705f"
            bars += (f'<rect x="{cx_-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                     f'height="{max(h,0.6):.1f}" fill="{fill}" opacity=".82"/>')
        # 悬停: 每周一条命中带, 同时给出该周期权净多 + 当周价格(取不晚于该周周日的最近一个交易日收盘)
        tips = []
        pj = 0
        for x in ser:
            tp = f'{_esc(x["d"])}||期权净多 {x["net_opt"]:,} 张'
            if px:
                lim = _dd(x["d"])
                while pj + 1 < len(px) and _dd(px[pj + 1][0]) <= lim:
                    pj += 1
                if _dd(px[pj][0]) <= lim:
                    tp += f'<br>COMEX {"白银" if key=="silver" else "黄金"} ${px[pj][1]:,.2f}/oz（{_esc(px[pj][0])}）'
            tips.append(tp)
        hover = _hover_bands([PL + iw * (i + 0.5) / len(ser) for i in range(len(ser))], tips, PT, ih, PL, W - PR)
        grid = ""
        for k in range(4):
            gv = lo + (hi - lo) * k / 3
            grid += (f'<line x1="{PL}" y1="{Y(gv):.1f}" x2="{W-PR}" y2="{Y(gv):.1f}" class="cxo-g"/>'
                     f'<text x="{PL-6}" y="{Y(gv)+3.5:.1f}" class="cxo-yl">{gv:,.0f}</text>')
        zero = f'<line x1="{PL}" y1="{y0:.1f}" x2="{W-PR}" y2="{y0:.1f}" class="cxo-z"/>'
        xt = ""
        for i in (0, len(ser)//2, len(ser)-1):
            xt += (f'<text x="{PL + iw*(i+0.5)/len(ser):.1f}" y="{H-10}" '
                   f'class="cxo-xt">{ser[i]["d"]}</text>')
        pst = v.get("price_status")
        pnote = ""
        if px_all and pst == "缓存":
            pnote = '<div class="cxo-warn">⚠ 价格本次抓取失败，显示的是上次缓存（最新点见悬停）。</div>'
        elif not px_all:
            pnote = '<div class="cxo-warn">⚠ 价格未获取，本图暂不叠加价格线（持仓柱图不受影响）。</div>'
        return f"""
  <div class="cxo-block">
    <div class="cxo-t">{v.get("cn")} · Managed Money 期权净多（张，正=净多 / 负=净空）{('· 叠加 COMEX 价格' if price_svg else '')}</div>
    <div class="cxo-lgs">{legend_px}</div>
    <svg viewBox="0 0 {W} {H}" class="cxo-chart" preserveAspectRatio="xMidYMid meet">
      {grid}{zero}{bars}{price_svg}{xt}{hover}
    </svg>
    {pnote}
  </div>"""

    cards, charts = "", ""
    for key in ("gold", "silver"):
        v = ms.get(key)
        if not v:
            continue
        L = v["latest"]
        dcls = "bull" if v["dir"] == "净多" else ("bear" if v["dir"] == "净空" else "")
        warn = (f'<div class="cxo-warn">⚠ {v["caveat"]}</div>' if v.get("caveat") else "")
        cards += (f'<div class="cxo-card"><div class="cxo-ct">'
                  f'<i style="background:{COL[key]}"></i>{v["cn"]}'
                  f'<small>{L["d"]}</small></div>'
                  f'<div class="cxo-row"><span>MM 净多（期货）</span>'
                  f'<b>{L["net_fut"]:,} 张</b></div>'
                  f'<div class="cxo-row"><span>折合吨位</span>'
                  f'<b>{L["tonnes"]:,.1f} 吨</b></div>'
                  f'<div class="cxo-row"><span>期权部分净多</span>'
                  f'<b class="{dcls}">{L["net_opt"]:,} 张　{v["dir"]}</b></div>'
                  f'<div class="cxo-row"><span>近两年分位</span>'
                  f'<b>{v["pct"]}%</b></div>'
                  f'<div class="cxo-sub">样本 {v["n"]} 周 · 期权 OI 差为负 '
                  f'{v["neg_weeks"]} 周{"（口径成立）" if not v["neg_weeks"] else ""}</div>'
                  f'{warn}</div>')
        charts += _bars(key, v)

    return f"""
<div class="cxo-wrap">
  <div class="cxo-notiv"><b>这不是隐含波动率。</b>{cx.get("not_iv_note","")}</div>
  <div class="cxo-cards">{cards}</div>
  {charts}
  <div class="cxo-method">{cx.get("method_note","")} 数据源：{cx.get("source","")}。
    持仓为 CFTC 周度报告（每周五发布、数据截至周二），非日更。</div>
</div>"""



def _global_money_html(gm):
    """全球货币供应(五大经济体聚合) + 加速度。"""
    if not gm or not str(gm.get("status", "")).startswith("ok"):
        err = ("：" + "；".join(gm.get("errors", [])[:2])) if gm and gm.get("errors") else ""
        return f'<p class="empty">全球货币供应数据同步中{err}。</p>'
    ser = gm.get("series") or []
    if len(ser) < 24:
        return '<p class="empty">全球货币供应：样本不足。</p>'

    COL = {"US": "#b08a3e", "EZ": "#7d94a8", "CN": "#a3705f",
           "JP": "#8d9c86", "GB": "#9a8ba8"}
    NM = {"US": "美国 M2", "EZ": "欧元区 M3", "CN": "中国 M2",
          "JP": "日本 M2", "GB": "英国 M4"}
    ORDER = ["US", "EZ", "CN", "JP", "GB"]

    W, H = 940, 300
    PL, PR, PT, PB = 62, 18, 20, 34
    iw, ih = W - PL - PR, H - PT - PB
    n = len(ser)

    def X(i): return PL + iw * i / max(n - 1, 1)

    def xticks(fmt_y=True):
        out, seen = "", set()
        for i, r in enumerate(ser):
            y = r["m"][:4]
            if y in seen or int(y) % 4:
                continue
            seen.add(y)
            out += (f'<line x1="{X(i):.1f}" y1="{PT}" x2="{X(i):.1f}" y2="{PT+ih}" '
                    f'class="gms-vg"/>'
                    f'<text x="{X(i):.1f}" y="{H-12}" class="gms-xt">{y}</text>')
        return out

    # ── 图① 分国堆叠面积 ──
    tmax = max(r["total"] for r in ser)
    def Y1(v): return PT + ih * (1 - v / (tmax * 1.06))
    layers, base = "", [0.0] * n
    for cc in ORDER:
        top = []
        for i, r in enumerate(ser):
            base[i] += r["parts"].get(cc, 0.0)
            top.append(base[i])
        up = " ".join(f"{X(i):.1f},{Y1(v):.1f}" for i, v in enumerate(top))
        dn = " ".join(f"{X(i):.1f},{Y1(v):.1f}"
                      for i, v in reversed(list(enumerate(
                          [b - r["parts"].get(cc, 0.0) for b, r in zip(top, ser)]))))
        layers = (f'<polygon points="{up} {dn}" fill="{COL[cc]}" opacity=".78">'
                  f'<title>{NM[cc]}</title></polygon>') + layers
    g1 = ""
    for k in range(5):
        v = tmax * 1.06 * k / 4
        g1 += (f'<line x1="{PL}" y1="{Y1(v):.1f}" x2="{W-PR}" y2="{Y1(v):.1f}" class="gms-g"/>'
               f'<text x="{PL-6}" y="{Y1(v)+3.5:.1f}" class="gms-yl">{v:.0f}</text>')

    # ── 图② 同比 + 加速度 ──
    yy = [r["yoy"] for r in ser if r.get("yoy") is not None]
    aa = [r["accel"] for r in ser if r.get("accel") is not None]
    H2 = 260
    ih2 = H2 - PT - PB
    lo2 = min(yy + aa + [0]) * 1.1
    hi2 = max(yy + aa + [0]) * 1.1
    def Y2(v): return PT + ih2 * (1 - (v - lo2) / (hi2 - lo2))
    g2 = ""
    for k in range(5):
        v = lo2 + (hi2 - lo2) * k / 4
        g2 += (f'<line x1="{PL}" y1="{Y2(v):.1f}" x2="{W-PR}" y2="{Y2(v):.1f}" class="gms-g"/>'
               f'<text x="{PL-6}" y="{Y2(v)+3.5:.1f}" class="gms-yl">{v:.0f}</text>')
    g2 += f'<line x1="{PL}" y1="{Y2(0):.1f}" x2="{W-PR}" y2="{Y2(0):.1f}" class="gms-z"/>'
    # 加速度柱
    bars = ""
    bw = max(iw / n * 0.7, 0.8)
    y0 = Y2(0)
    for i, r in enumerate(ser):
        a = r.get("accel")
        if a is None:
            continue
        yv = Y2(a)
        top, hh = (yv, y0 - yv) if a >= 0 else (y0, yv - y0)
        fill = "#a3855f" if a >= 0 else "#8ba39a"
        bars += (f'<rect x="{X(i)-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                 f'height="{max(hh,0.5):.1f}" fill="{fill}" opacity=".62"/>')
    # 同比线
    pts = [(X(i), Y2(r["yoy"])) for i, r in enumerate(ser) if r.get("yoy") is not None]
    line = ('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) +
            '" class="gms-ln"/>') if len(pts) > 2 else ""

    xt2, seen2 = "", set()
    for i, r in enumerate(ser):
        y = r["m"][:4]
        if y in seen2 or int(y) % 4:
            continue
        seen2.add(y)
        xt2 += f'<text x="{X(i):.1f}" y="{H2-12}" class="gms-xt">{y}</text>'

    # hover 命中带(两图): ①合计+分国 ②同比+加速度
    def _f(v, fmt):
        return "—" if v is None else format(v, fmt)
    hits1 = _hover_bands(
        [X(i) for i in range(n)],
        [_esc(r["m"]) + "||" + f'合计 {r["total"]:,.1f} 万亿美元' + "".join(
            f'&lt;br&gt;{NM[c]} {r["parts"][c]:,.1f}' for c in ORDER if c in r["parts"])
         for r in ser], PT, ih, PL, W - PR)
    hits2 = _hover_bands(
        [X(i) for i in range(n)],
        [f'{_esc(r["m"])}||同比 {_f(r.get("yoy"), ".2f")}%&lt;br&gt;加速度 {_f(r.get("accel"), "+.2f")}'
         for r in ser], PT, ih2, PL, W - PR)

    # ── 覆盖度条 ──
    cov = ""
    for c in (gm.get("coverage") or []):
        cov += (f'<div class="gms-cov-row"><span class="gms-cov-p">'
                f'{c["from"]} ~ {c["to"]}</span>'
                f'<span class="gms-cov-n">{len(c["cty"])} 国</span>'
                f'<span class="gms-cov-c">{"、".join(NM.get(x,x) for x in c["cty"])}</span>'
                f'</div>')

    L = gm.get("latest") or ser[-1]
    acc = L.get("accel")
    acls = "up" if (acc is not None and acc > 0) else ("dn" if acc is not None else "")
    aword = ("放水提速" if (acc is not None and acc > 0)
             else "放水减速" if acc is not None else "—")

    cards = (f'<div class="gms-card"><div class="gms-k">五国合计</div>'
             f'<div class="gms-v">{L["total"]:,.1f}<small> 万亿美元</small></div>'
             f'<div class="gms-s">{L["m"]}</div></div>'
             f'<div class="gms-card"><div class="gms-k">同比增速</div>'
             f'<div class="gms-v">{L.get("yoy","—")}<small>%</small></div>'
             f'<div class="gms-s">较去年同月</div></div>'
             f'<div class="gms-card"><div class="gms-k">加速度</div>'
             f'<div class="gms-v {acls}">{f"{acc:+.2f}" if acc is not None else "—"}</div>'
             f'<div class="gms-s">{aword}</div></div>')

    parts = "".join(
        f'<div class="gms-p"><i style="background:{COL[c]}"></i>{NM[c]}'
        f'<b>{L["parts"].get(c,0):,.1f}</b></div>'
        for c in ORDER if c in L.get("parts", {}))

    tail = (f'<div class="gms-tail">⏳ {gm["tail_note"]}</div>'
            if gm.get("tail_note") else "")

    return f"""
<div class="gms-wrap">
  <div class="gms-caliber"><b>口径说明：</b>{gm.get("caliber_note","")}</div>
  <div class="gms-cards">{cards}</div>
  <div class="gms-parts">{parts}</div>
  {tail}

  <div class="gms-block">
    <div class="gms-t">① 五大经济体货币存量（折万亿美元，堆叠）</div>
    <svg viewBox="0 0 {W} {H}" class="gms-chart" preserveAspectRatio="xMidYMid meet">
      {g1}{xticks()}{layers}{hits1}
    </svg>
  </div>

  <div class="gms-block">
    <div class="gms-t">② 同比增速（线）与加速度（柱）——
      柱在零轴上方＝放水在提速，下方＝在减速</div>
    <svg viewBox="0 0 {W} {H2}" class="gms-chart" preserveAspectRatio="xMidYMid meet">
      {g2}{bars}{line}{xt2}{hits2}
    </svg>
  </div>

  <div class="gms-covbox"><div class="gms-covt">各时段实际覆盖国家</div>{cov}</div>
  <div class="gms-gap"><b>历史缺口：</b>{gm.get("gap_note","")}</div>
  <div class="gms-acc">{gm.get("accel_note","")}</div>
</div>"""


def generate(snap, checks, hit, gstats, overall, ai_reads=None, ai_conclusions=None,
             daily_notes=None, kol_changes=None, liquidity=None, cb_balance=None,
             holdings=None, custody=None, auctions=None, money_supply=None, m2_history=None,
             country_ust=None, tic_official_private=None, euro_ncb=None,
             kol_views=None, credit_impulse=None, custody_accel=None,
             stress_panels=None, ofr_fsi=None, maturing_treasury=None, bis_latest=None,
             bis_all=None, cb_swaps=None,
             oil_inventory=None, us_jp_yields=None, nikkei225=None, foreign_flow=None,
             iip_four=None, fiscal_news=None, hf_leverage=None, bis_gold_swaps=None,
             market_breadth=None, silver_bank_positions=None, comex_silver_issues_ref=None,
             gold_exports=None, us_yield_century=None, comex_issue_stop=None,
             comex_firms_top10=None,
             ad_line_real=None, gold_premium=None, silver_imports=None, fiscal_budget=None,
             basis_trade=None, comex_inventory=None, debt_gdp=None,
             corp_credit=None, cips=None, ai_fcf=None, ai_credit=None,
             cn_liq=None,
             liquidity_crisis=None, analog_corr=None, gold_vol=None, fed_gold_oil=None, cn_capital=None, cn_hk_hold=None, gs_tech=None, ur_tech=None, cot_mm=None, china_regime=None, wrs=None, stock_gold=None, spx_gold_long=None, ust_trio=None, jpy_carry=None, ai_cds=None, bbb_3y=None, mm_ratio=None, h8_deposits=None, hf_ust=None, tfp_sentiment=None, llm_token=None, ai_capex=None, gold_oil=None, btc_gold=None, silver_curve=None, report_leads=None, us_freight=None, ust_micro=None, dxy_gold=None, gold_etf_flows=None, pm_optvol=None, comex_optpos=None,
    global_money=None,
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
              <div class="mc-val">{fmt_val(ind, r)} {chg}{st_badge}{slabel_html}{_ind_fresh_badge(key, r)}</div>
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
                # ★2026-09-28: 原样拼接 → 指标说明里的 **粗体** 显示成字面星号(门禁报 6 处)。
                # 改 _esc_md: 先转义再渲染 **→<b>。实测 note/AI 解读里的 "<" 全是小于号(如 "<4.0")而非标签,
                # 转义后显示不变且更安全。
                html += f'<div class="interp-item"><span class="ii-sig">{lt}</span><b>{ind["name_zh"]}</b> <span class="ii-val">{fmt_val(ind, r)}</span><p>{_esc_md(read)}</p></div>'
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
              <div class="cot-cad">{_cot_cadence_note(r.get('as_of'))}</div>
            </div>"""
        return html

    overall_cls = {"🔴 减仓": "danger", "🟡 警戒": "warn", "🟢 平静": "calm"}.get(overall, "calm")
    generated = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    # ★2026-09-08: payload 只算一次, 同时给名录卡片一份「谁有多少条历史」索引,
    #   让卡片能挂钻取并显示真实条数(而不是再算一遍或写死)。
    _kol_hist_json = _kol_history_payload(kol_history)
    try:
        _kol_hist_index = {k: v.get("h") or []
                           for k, v in json.loads(_kol_hist_json).items()}
    except Exception:
        _kol_hist_index = {}

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
        kol_changes=_kol_multi_period_html(kol_changes, "changes"),
        kol_views=_kol_multi_period_html(kol_views, "views"),
        cycle_kol="",  # ★2026-08-22 Chao: 玄学/术数派已迁往 Forecast-Checker,
                       # 技术分析派归回常规 KOL 板块, 本独立 section 停用(不再渲染)。
                       # _cycle_kol_html 保留未删, 便于日后需要时恢复。
        kol_history_json=_kol_hist_json,
        liquidity=_liquidity_html(liquidity),
        cb_balance=_cb_balance_html(cb_balance, euro_ncb),
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
        comex_firms_top10=_comex_firms_top10_html(comex_firms_top10),
        fiscal_budget=_fiscal_budget_html(fiscal_budget),
        bis_section=_bis_section_html(bis_latest, "https://eco-volatility-checker.pages.dev/bis/", bis_all),
        cb_swaps=_cb_swaps_html(cb_swaps),
        kol_roster=_kol_roster_table_html(_kol_hist_index),
        country_ust=_country_ust_html(country_ust, tic_official_private),
        credit_impulse=_credit_impulse_html(credit_impulse),
        stress_panels=_stress_panels_html(stress_panels, ofr_fsi),
        liquidity_crisis_html=_liquidity_crisis_html(liquidity_crisis),
        cot_mm_html=_cot_mm_html(cot_mm),
        mm_ratio_html=_mm_ratio_html(mm_ratio),
        h8_deposits_html=_h8_deposits_html(h8_deposits),
        hf_ust_html=_hf_ust_html(hf_ust),
        china_regime_html=_china_regime_html(china_regime),
        wrs_html=_wrs_html(wrs),
        stock_gold_html=_stock_gold_html(stock_gold),
        spx_gold_long_html=_sgl_html(spx_gold_long),
        ust_yld_html=_ust_trio_html(ust_trio, 'yld'),
        ust_tpm_html=_ust_trio_html(ust_trio, 'tpm'),
        ust_agg_html=_ust_trio_html(ust_trio, 'agg'),
        ai_cds_html=_ai_cds_html(ai_cds, bbb_3y),
        jpy_facts_html=_jpy_carry_html(jpy_carry, 'facts'),
        jpy_cftc_html=_jpy_carry_html(jpy_carry, 'cftc'),
        jpy_spread_html=_jpy_carry_html(jpy_carry, 'spread'),
        jpy_kline_html=_jpy_carry_html(jpy_carry, 'kline'),
        tfp_sentiment_html=_tfp_sentiment_html(tfp_sentiment),
        llm_token_html=_llm_token_html(llm_token),
        ai_capex_html=_ai_capex_html(ai_capex),
        gold_oil_html=_gold_oil_html(gold_oil),
        btc_gold_html=_btc_gold_html(btc_gold),
        silver_curve_html=_silver_curve_html(silver_curve),
        analog_corr_html=_analog_corr_html(analog_corr),
        gold_vol_html=_gold_vol_html(gold_vol),
        fed_gold_oil_html=_fed_gold_oil_html(fed_gold_oil),
        gs_tech_html=_gs_tech_html(gs_tech),
        ur_tech_html=_ur_tech_html(ur_tech),
        cn_capital_html=_cn_capital_html(cn_capital, cn_liq, cn_hk_hold),
        report_leads_html=_report_leads_html(report_leads),
        us_freight_html=_us_freight_html(us_freight),
        ust_micro_html=_ust_micro_html(ust_micro),
        dxy_gold_html=_dxy_gold_html(dxy_gold),
        gold_etf_region_html=_gold_etf_region_html(gold_etf_flows),
        pm_optvol_html=_pm_optvol_html(pm_optvol),
        comex_optpos_html=_comex_optpos_html(comex_optpos),
        global_money_html=_global_money_html(global_money),
        basis_trade=_basis_trade_html(basis_trade),
        comex_inventory=_comex_inventory_html(comex_inventory),
        debt_gdp=_debt_gdp_html(debt_gdp),
        corp_credit=_corp_credit_html(corp_credit),
        cips=_cips_html(cips),
        cn_liq=_cn_liq_html(cn_liq),
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
            focus = _esc_md(k.get("focus") or "")   # ★_esc_md: 名册文本含 Markdown 粗体
            # 方向 / 言论: 有才显示, 没有明确标"待采集"
            if v:
                d = (v.get("direction") or "").strip() or "—"
                cls = {"强烈看多":"kv-bull2","看多":"kv-bull","分歧":"kv-mixed","中性":"kv-mixed",
                       "看空":"kv-bear","强烈看空":"kv-bear2","另类预言":"kv-mixed"}.get(d, "kv-mixed")
                body = _esc_md((v.get("comments") or "").strip()) or "—"
                tg = _esc(_tg_str(v.get("targets")))
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
                f'<div class="kol-item-head"><span class="kol-name">{_esc(_kol_disp(nm))}</span>{dir_html}</div>'
                f'<div class="cyc-meta">{rg}<span class="cyc-freq">{freq}更新</span>'
                f'<span class="cyc-school">{school}</span>{hint}</div>'
                f'<div class="kol-comment">{body}</div>{tg_html}{fc}'
                + (f'<div class="kol-standing">🏛 {_esc_md(inst)}</div>' if inst else "")
                + link + '</div>'
            )
        return (f'<div class="cyc-block"><div class="cyc-block-title">{title}'
                f'<span class="cyc-block-sub">{sub}</span></div>'
                f'<div class="kol-grid">{cards}</div></div>')

    body = _block("每日 / 每周预测", "更新节奏快，可做短周期对账", hi)
    body += _block("月度 / 不定期预测", "长周期与节气/节点式预测", lo)
    return head + body


def _tg_str(v):
    """targets 归一为字符串。

    ★2026-08-24 线上 build 崩溃根因: 深度重抓时部分子 agent 把 targets 写成了
      <b>数组</b>(如 ["黄金$6000","白银$120"]), 而三处渲染都直接 .strip() → AttributeError。
      上游数据形状不可控(人写/LLM 写/历史遗留混杂), 所以在<b>渲染层</b>做类型兜底:
      list/tuple → 顿号连接; None → 空串; 其它 → str()。
      不去改上游数据: 数组本身是合法表达, 改了反而丢结构。
    """
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "、".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def _kol_payload_key(prof_name, payload_keys):
    """★2026-09-08(Chao 问「全量名录怎么没有这个KOL的全部言论？」): 把名录卡片的
    人名解析成 kol_history payload 的 key, 供卡片挂 kol-drill 钻取。

    为什么需要解析而不能直接用: 名录卡片读 data/kol_profiles.json(125 人),
    历史 payload 的 key 来自名册 registry(129 人) —— 同一个人两边写法不同:
        卡片 Stanley Druckenmiller  ←→ 名册 S. Druckenmiller
        卡片 Ken Griffin            ←→ 名册 Ken Griffin（Citadel 创始人 / CEO）
        卡片 N. Gregory Mankiw      ←→ 名册 Greg Mankiw
    实测 125 人里 115 直接命中、7 人属这类写法差异、3 个是机构非自然人
    (Citi / UBS、Morgan Stanley、Foundation for the Study of Cycles)。
    不解析的话那 7 人点开会是空白。

    ★匹配方向沿用 AGENTS.md 记过的坑: 只认「主干相等 / 单方向包含 / 姓相同」,
    不做双向模糊 —— 否则「Goldman Sachs」这类机构后缀会抢先吃掉别人的行。
    """
    if not prof_name:
        return ""
    if prof_name in payload_keys:
        return prof_name

    def _base(s):
        s = re.sub(r'[（(].*', '', s or '')       # 去括号后缀
        s = re.sub(r'\b[A-Z]\.\s*', '', s)        # 去中间名缩写
        return re.sub(r'[^a-z]+', '', s.lower())

    def _last(s):
        s = re.sub(r'[（(].*', '', s or '').strip()
        parts = [w for w in re.split(r'\s+', s) if len(w) > 1]
        return parts[-1].lower() if parts else ''

    pb, pl = _base(prof_name), _last(prof_name)
    if not pb:
        return ""
    cands = []
    for k in payload_keys:
        kb, kl = _base(k), _last(k)
        if pb == kb:
            cands.append((0, len(k), k))
        elif pb in kb or kb in pb:
            cands.append((1, len(k), k))
        elif pl and pl == kl and len(pl) > 3:
            cands.append((2, len(k), k))
    cands.sort()
    return cands[0][2] if cands else ""


def _kol_history_payload(kol_history):
    """把 kol_full_history() 结果压成内嵌 JSON(供前端两层展开钻取)。
    结构精简: {kol: {"s": 背景介绍, "f": 关注领域,
                     "h": [[first,last,dir,comments,targets,source,detail,srcs],...]}}
    数组形式而非对象, 省掉每条重复的键名(2600+ 条能省约 40% 体积)。
    ★2026-08-22(Chao): 新增第 7 位 detail(100-300 字结构化深度摘要)与第 8 位 srcs
      (来源链接数组)。此前展开层复用同一个 comments, 导致「点开第二层和默认值没区别」。
    无历史数据返回 '{}' —— 前端据此禁用钻取, 绝不显示假数据。"""
    if not kol_history:
        return "{}"
    meta = _kol_meta()
    # ★2026-08-22: payload 只收名册在册的人。kol_full_history() 是直接扫
    #   data/kol/backfill/ 目录的, 不看名册 —— 从名册移出的人(如迁往
    #   Forecast-Checker 的玄学派)其 backfill 文件仍保留在磁盘(留痕不删),
    #   若不在此过滤, 他们的历史会继续内嵌进页面, 造成"卡片没了但数据还在"。
    _roster = set(meta.keys())
    # ★深度摘要索引: 从当日 kol_independent.json 取 detail/sources, 按 KOL 名匹配。
    #   只有「最新一条」记录能配到 detail(历史条目本来就没有深度摘要, 不伪造)。
    _deep = {}
    try:
        import os as _os
        _ip = _os.path.join(_os.path.dirname(__file__), "..", "data", "kol_independent.json")
        for _x in (json.load(open(_ip, encoding="utf-8")).get("all") or []):
            _n = (_x.get("kol") or "").strip()
            if _n and _x.get("detail"):
                _deep[_n] = {"d": _strip_md(_x.get("detail") or ""),
                             "src": [s for s in (_x.get("sources") or []) if s.get("url")][:4],
                             "date": _x.get("date") or ""}
    except Exception:
        _deep = {}
    out = {}
    for kol, recs in kol_history.items():
        if not recs:
            continue
        if _roster and kol not in _roster:
            continue
        m = meta.get(kol, {})
        dp = _deep.get(kol)
        rows = []
        for r in recs:
            last = r.get("last_date", "")
            # ★优先用该历史条目自带的 detail(2026-08-23 全量回填, 369 条 100% 覆盖);
            #   没有自带的, 才看是否匹配「今天深度抓取」那一条。两者都无则留空 ——
            #   绝不把某一天的摘要贴到别的日期上(那是伪造)。
            det = (r.get("detail") or "").strip()
            srcs = r.get("sources") or []
            if not det and dp and last and dp.get("date") and last >= dp["date"]:
                det, srcs = dp["d"], dp["src"]
            if not srcs and r.get("source"):
                srcs = [{"url": r.get("source")}]
            rows.append([r.get("first_date", ""), last,
                         r.get("direction", ""), _strip_md(r.get("comments", "")),
                         r.get("targets", ""), r.get("source", ""),
                         _strip_md(det), srcs[:4]])
        out[kol] = {"n": _kol_disp(kol), "s": _strip_md(m.get("standing", "")),
                    "f": _strip_md(m.get("focus", "")), "h": rows}
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


_KOL_SHORT_CACHE = None


def _kol_disp(name):
    """卡片可见标题用的短名。display_name 仍是全链路 join key(快照/backfill/payload),
    这里只换「显示」。★2026-09-25(Chao 问「KOL名字怎么这么长」): Notion「KOL / 机构」
    字段有 5 行只填了机构介绍(如「The Trends Research Institute（1980…）创办人兼董事」
    实为 Gerald Celente), 另有 29 人是「人名（长简介）」, 原样当标题。名册 short_name
    由 tools/add_kol_short_names.py 维护; 无 short_name 时退回括号前部分。"""
    global _KOL_SHORT_CACHE
    n = (name or "").strip()
    if _KOL_SHORT_CACHE is None:
        _KOL_SHORT_CACHE = {}
        try:
            import os as _os
            _rp = _os.path.join(_os.path.dirname(__file__), "..", "data", "kol_registry.json")
            for _k in json.load(open(_rp, encoding="utf-8")).get("kols", []):
                _d = (_k.get("display_name") or "").strip()
                if _d and _k.get("short_name"):
                    _KOL_SHORT_CACHE[_d] = _k["short_name"].strip()
        except Exception:
            pass
    if n in _KOL_SHORT_CACHE:
        return _KOL_SHORT_CACHE[n]
    return re.split(r"[（(]", n)[0].strip() or n


def _kol_standing_html(meta, kol):
    """渲染 KOL 背景介绍块(业界地位 + 关注领域)。无资料返回空串, 绝不编造。"""
    m = meta.get((kol or "").strip()) or {}
    standing = m.get("standing", "")
    if not standing:
        return ""
    return f'<div class="kol-standing">🏛 {_esc_md(standing)}</div>'


_PERIOD_LABEL = {"day": "本日", "week": "本周", "month": "本月"}


def _kol_period_tabs(group, active="week"):
    """本日/本周/本月 三档切换按钮(纯前端, 三份数据都已内嵌, 点击零请求)。"""
    btns = ""
    for p in ("day", "week", "month"):
        cls = "kp-btn on" if p == active else "kp-btn"
        btns += (f'<button type="button" class="{cls}" data-kp-group="{group}" '
                 f'data-kp="{p}">{_PERIOD_LABEL[p]}</button>')
    return f'<div class="kp-tabs" data-kp-tabs="{group}">{btns}</div>'


def _kol_changes_html(kol_changes, period="week"):
    """KOL 状态变化板块(模块化, 仿 13F 报告)。
    接收 kol_stance_changes_grouped() 的结果 {since,days,total,modules:[...]};
    向后兼容旧 list 结构(自动包一层"其他"模块)。
    每个 sector 一个彩色模块, 模块下列该模块转向的 KOL(主方向变化+言论+标的+日期)。
    period: day/week/month —— 只影响文案措辞, 数据由调用方按档位传入。"""
    _pl = _PERIOD_LABEL.get(period, "本周")
    # 空/无数据
    if not kol_changes:
        return f'<p class="empty">{_pl}暂无 KOL 主导方向变化（或快照尚在累积中）。</p>'
    # 兼容: 旧 list 结构 → 包成单模块
    if isinstance(kol_changes, list):
        kol_changes = {"since": "", "days": 0, "total": len(kol_changes),
                       "modules": [{"sector": "全部", "en": "", "color": "#8a8377", "changes": kol_changes}]}
    modules = kol_changes.get("modules", [])
    # ★2026-08-22: 独立 section 已停用, 不再从常规板块剔除任何 sector。
    #   (原为配合「周期与术数预测」独立板块做的去重; 现玄学派已迁走、
    #    技术分析派归回常规板块, 若继续过滤会把这 12 人挡在页面外。)
    #   但同样须按名册过滤掉已移出的人(快照可能早于名册变更)。
    _roster = set(_kol_meta().keys())
    if _roster:
        for m in modules:
            m["changes"] = [c for c in (m.get("changes") or []) if c.get("kol") in _roster]
        modules = [m for m in modules if m.get("changes")]
    _tot = sum(len(m.get("changes") or []) for m in modules)
    if not modules or _tot == 0:
        return f'<p class="empty">{_pl}暂无 KOL 主导方向变化（或快照尚在累积中）。</p>'

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
    if kol_changes.get("cumulative"):
        # ★月度=稳定度口径(非端点转向)。口径差异必须写在脸上, 避免与周/日混读。
        ns = kol_changes.get("n_stable", 0)
        nf = kol_changes.get("n_flip", 0)
        nsoft = kol_changes.get("n_soft", 0)
        head = (f'<div class="kol-overview">本月 KOL 立场稳定度（{_esc(since)} 以来全月逐日快照）：'
                f'<b>{nf}</b> 位跨多空反转、<b>{nsoft}</b> 位仅强度摆动、'
                f'<b>{ns}</b> 位全月稳定，共 <b>{total}</b> 位。'
                f'<span class="kol-ov-note">⚠️ 本档口径与本日/本周不同：'
                f'日/周看「首尾对比的转向」，本月看「整月待过几个阵营」。'
                f'月内多空来回者在首尾对比下会被抵消成「没变」，故本档改判稳定性。'
                f'「跨多空反转」才是真换边；「强度摆动」只是强烈看多↔看多这类档位漂移，'
                f'未离开原阵营；因标注精度不足，不声称具体转向次数</span></div>')
    else:
        head = (f'<div class="kol-overview">{_pl} KOL 状态变化（对比基准 <b>{_esc(since)}</b>）共 '
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
        _unit = "位" if kol_changes.get("cumulative") else "转向"
        cards = ""
        for ch in changes:
            pc = dir_cls.get(ch["prev_dir"], "n")
            nc = dir_cls.get(ch["new_dir"], "n")
            comment = (ch.get("comments") or "").strip()
            targets = _tg_str(ch.get("targets"))
            extra = ""
            if comment:
                extra += f'<div class="kol-cmt">{_esc_md(comment)}</div>'
            if targets:
                extra += f'<div class="kol-tgt">标的：{_esc(targets)}</div>'
            # Bug1 修复: 状态变化卡片补背景介绍(与"观点全景"板块口径一致, 均取名册 institution/bio)
            extra += _kol_standing_html(_meta, ch.get("kol", ""))
            # 月度稳定度口径: 卡片头显示 稳定/软摆动/跨多空 三级徽章 + 阵营 + 样本天数
            # ★2026-08-31 分三级(实测): 只分"稳定/反复"两级会把 Michael Saylor 这种
            #   强烈看多→看多 的细档漂移(掺个中性档)与真·多空反转混为一谈, 误导交易员。
            #   flip=True 才是真跨越多空(40人); 仅多↔中/空↔中 摆动(32人)单列一级。
            if ch.get("stable") is not None:
                if ch.get("stable"):
                    _sb = ('<span class="kol-arrow kol-flat">● 全月稳定</span>'
                           f'<span class="kol-date">{_esc(ch.get("camps",""))}阵营 · '
                           f'{ch.get("days_seen",0)}天样本</span>')
                elif ch.get("flip"):
                    _sb = ('<span class="kol-arrow kol-down">⇄ 跨多空反转</span>'
                           f'<span class="kol-date">跨 {_esc(ch.get("camps",""))} · '
                           f'{ch.get("days_seen",0)}天样本</span>')
                else:
                    _sb = ('<span class="kol-arrow kol-flat">～ 强度摆动</span>'
                           f'<span class="kol-date">未换阵营 {_esc(ch.get("camps",""))} · '
                           f'{ch.get("days_seen",0)}天样本</span>')
                _pathv = (ch.get("path") or "").strip()
                _path_html = (f'<div class="kol-shift">{_esc(_pathv)}</div>'
                              if _pathv else "")
                cards += f"""<div class="kol-item kol-drill" data-kol="{_esc(ch['kol'])}" tabindex="0" role="button">
                  <div class="kol-line"><b>{_esc(_kol_disp(ch['kol']))}</b> {_sb}</div>
                  {_path_html}
                  {extra}
                  <div class="kol-more">点击查看该 KOL 全部观点 →</div>
                </div>"""
                continue
            cards += f"""<div class="kol-item kol-drill" data-kol="{_esc(ch['kol'])}" tabindex="0" role="button">
              <div class="kol-line"><b>{_esc(_kol_disp(ch['kol']))}</b> {_shift_badge(ch['prev_dir'], ch['new_dir'])} <span class="kol-date">{_esc(ch['date'])}</span></div>
              <div class="kol-shift"><span class="kdir kdir-{pc}">{_esc(ch['prev_dir'])}</span> → <span class="kdir kdir-{nc}">{_esc(ch['new_dir'])}</span></div>
              {extra}
              <div class="kol-more">点击查看该 KOL 全部观点 →</div>
            </div>"""
        html += (
            f'<div class="h-module" style="border-color:{color}">'
            f'<div class="h-module-title" style="background:{color}">'
            f'<span class="h-mod-dot"></span>{_esc(sector)}<span class="h-mod-en">{_esc(en)}</span>'
            f'<span class="h-mod-n">{len(changes)} {_unit}</span></div>'
            f'<div class="kol-mod-inner">{cards}</div></div>'
        )
    return html


def _kol_views_html(views, period="week"):
    """KOL 观点板块(按模块, 每 KOL 一卡带多空方向)。
    接收 kol_weekly_views() 结果 {date,total,modules:[{sector,en,color,views:[...]}]}。
    这是'窗口内有意义的观点'全景(不只转向), 回答'上百个KOL不可能一周没话说'。
    period: day/week/month —— 只影响文案措辞, 数据由调用方按档位传入。"""
    _pl = _PERIOD_LABEL.get(period, "本周")
    if not views or not views.get("modules") or views.get("total", 0) == 0:
        return f'<p class="empty">{_pl}暂无 KOL 观点数据（快照未就绪）。</p>'
    # 方向 → 徽章色 + 文案(看多暖/看空冷, 与转向徽章一致的语义)
    dir_badge = {
        "强烈看多": ("kv-bull2", "强烈看多"), "看多": ("kv-bull", "看多"),
        "分歧": ("kv-mixed", "分歧"), "中性": ("kv-mixed", "中性"),
        "看空": ("kv-bear", "看空"), "强烈看空": ("kv-bear2", "强烈看空"),
    }
    date = views.get("date", "")
    total = views.get("total", 0)
    modules = views["modules"]
    # ★2026-08-22: 同上, 独立 section 停用后不再剔除。
    #   但必须按名册过滤: kol_weekly_views() 数据源是每日快照(抓取时的名册),
    #   名册变更后旧快照仍含已移出的人 → 不过滤会渲染出"卡片在但点开空白"。
    _roster = set(_kol_meta().keys())
    if _roster:
        for m in modules:
            m["views"] = [v for v in (m.get("views") or []) if v.get("kol") in _roster]
        modules = [m for m in modules if m.get("views")]
    total = sum(len(m.get("views") or []) for m in modules)
    if not modules or total == 0:
        return f'<p class="empty">{_pl}暂无 KOL 观点数据（快照未就绪）。</p>'
    # 加载 KOL 名册的业界地位/机构声誉, 按名字匹配渲染到卡片底部(与"状态变化"板块共用同一口径)
    _meta = _kol_meta()
    head = (f'<div class="kol-overview">{_pl} KOL 观点全景（截至 <b>{_esc(date)}</b>）：'
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
            targets = _tg_str(v.get("targets"))
            since = (v.get("since_date") or "").strip()
            is_new = v.get("is_new")
            # 首现日期标注: 本周内新转成→🆕 新观点; 否则→自 X 日持有(旧观点延续)
            since_html = ""
            if since:
                if is_new:
                    since_html = f'<span class="kol-since kol-since-new">🆕 {_pl}新观点</span>'
                else:
                    since_html = f'<span class="kol-since">自 {_esc(since)} 持此观点</span>'
            extra = ""
            if comment:
                extra += f'<div class="kol-cmt">{_esc_md(comment)}</div>'
            if targets:
                extra += f'<div class="kol-tgt">标的：{_esc(targets)}</div>'
            _standing = _kol_standing_html(_meta, v.get("kol", ""))
            if _standing:
                extra += _standing
            cards += f"""<div class="kol-item kol-drill" data-kol="{_esc(v['kol'])}" tabindex="0" role="button">
              <div class="kol-line"><b>{_esc(_kol_disp(v['kol']))}</b> <span class="kv-badge {bcls}">{_esc(btxt)}</span> {since_html}</div>
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


def _kol_multi_period_html(data_by_period, kind, active="week"):
    """把 本日/本周/本月 三份数据渲染成「按钮 + 三个 pane」结构。

    ★Chao 2026-08-31: 两个 KOL 板块顶部各加 本日/本周/本月 三档 filter。
      三份数据全部内嵌进 HTML, 前端点击只切 display, 零网络请求。
      data_by_period: {"day":..., "week":..., "month":...}; 缺档位则该 pane 显示未就绪。
      kind: "views" → 观点全景 / "changes" → 状态变化。
      ★向后兼容: 若传进来的不是 {day,week,month} 字典(旧调用直接传单份数据),
        则退化为只渲染一份, 不显示切换按钮。
    """
    render = _kol_views_html if kind == "views" else _kol_changes_html
    if not isinstance(data_by_period, dict) or not (
            {"day", "week", "month"} & set(data_by_period.keys())):
        return render(data_by_period, period="week")   # 旧调用: 单份数据
    group = f"kol-{kind}"
    panes = ""
    for p in ("day", "week", "month"):
        body = render(data_by_period.get(p), period=p)
        style = "" if p == active else ' style="display:none"'
        panes += (f'<div class="kp-pane" data-kp-group="{group}" '
                  f'data-kp-pane="{p}"{style}>{body}</div>')
    return _kol_period_tabs(group, active) + panes


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
        parts.append(f'<div class="liq-note"><b>关键变动</b><br>{_esc_md(notes["关键变动"]).replace(chr(10), "<br>")}</div>')
    if notes.get("AI短评"):
        parts.append(f'<div class="liq-note"><b>AI 短评</b><br>{_esc_md(notes["AI短评"]).replace(chr(10), "<br>")}</div>')
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
    # ★2026-10-07 接季频: 年频之后追加「最新季度」标签(如 2026-Q1/Q2), 与年频同一 x 轴顺序延伸
    q_labels = sorted({q for c in active.values() for q, _ in (c.get("net_q") or [])})
    all_years = all_years + [q for q in q_labels if q not in all_years]
    all_vals = [v for c in active.values() for _, v in c["net"]] + [v for c in active.values() for _, v in (c.get("net_q") or [])]
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
        # 季度标签一律显示(只有 1~2 个); 年份仍每隔 1 个标一个
        if i % 2 == 0 or i == n - 1 or "Q" in str(y):
            anchor = "start" if i == 0 else ("end" if i >= n - 1 else "middle")
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
            nq = [(q, v) for q, v in (c.get("net_q") or []) if q in yidx]
            if nq:
                # 虚线: 年频末点 → 各季度点(区别于实线年频; 季度点空心圆)
                seg = [f"{X(yidx[ly]):.1f},{Y(lv):.1f}"] + [f"{X(yidx[q]):.1f},{Y(v):.1f}" for q, v in nq]
                parts.append(f'<polyline points="{" ".join(seg)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-dasharray="5,4" stroke-linejoin="round"/>')
                for q, v in nq:
                    parts.append(f'<circle class="tip-hit" cx="{X(yidx[q]):.1f}" cy="{Y(v):.1f}" r="6" data-tip="{_esc(c["name"])} · {_esc(str(q))}（季频）||{v:+.1f}"/>')
                    parts.append(f'<circle cx="{X(yidx[q]):.1f}" cy="{Y(v):.1f}" r="3.2" fill="#fff" stroke="{color}" stroke-width="1.6"/>')
                ly, lv = nq[-1]
            parts.append(f'<circle cx="{X(yidx[ly]):.1f}" cy="{Y(lv):.1f}" r="3.4" fill="{color}"/>')
        parts.append(f'<line x1="{w-mr+8}" y1="{legend_y}" x2="{w-mr+24}" y2="{legend_y}" stroke="{color}" stroke-width="2.6"/>')
        parts.append(f'<text x="{w-mr+28}" y="{legend_y+4}" font-size="10" fill="{color}" font-weight="600">{c["flag"]}{_esc(c["name"])} {(c.get("q_net") if c.get("q_net") is not None else c["latest_net"]):+.1f}</text>')
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
    # ★2026-10-07 接季频: 用最新季度资产/负债(四国都有才用, 否则整图退回年频, 不混用不同期别)
    use_q = all(cd[k].get("q_assets") is not None and cd[k].get("q_liab") is not None for k in order)
    A = (lambda k: cd[k]["q_assets"]) if use_q else (lambda k: cd[k]["latest_assets"])
    L = (lambda k: cd[k]["q_liab"]) if use_q else (lambda k: cd[k]["latest_liab"])
    allv = [A(k) for k in order] + [L(k) for k in order]
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
        for off, val, col, lab in ((-bw*0.6, A(k), "#7fa085", "资产"),
                                   (bw*0.6, L(k), "#c0757d", "负债")):
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
        _q_ok = c.get("q_net") is not None and all(cs.get(x, {}).get("q_assets") is not None for x in ("US", "JP", "DE", "CN") if cs.get(x, {}).get("status") == "ok")
        net = c["q_net"] if _q_ok else c["latest_net"]
        _as = c["q_assets"] if _q_ok else c["latest_assets"]
        _li = c["q_liab"] if _q_ok else c["latest_liab"]
        col = "#2e9e5b" if net >= 0 else "#d64545"
        role = "净债权国" if net >= 0 else "净债务国"
        rows.append(f'<span style="color:{c["color"]};font-weight:600">{c["flag"]}{_esc(c["name"])}</span> '
                    f'资产${_as:.1f}T/负债${_li:.1f}T→'
                    f'净<b style="color:{col}">{net:+.1f}T</b>（{role}）')
    meta = " · ".join(rows)
    asof = iip.get("as_of", "")
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">四国对外净头寸 NIIP · 过去约十年（对外总资产 − 总负债 · $万亿）'
        f'<span class="chart-freq freq-w">🔵 年频为主 + 最新季频（虚线）· IMF</span></div>'
        f'{net_svg}'
        f'</div>'
        f'<div class="cust-chart-col cust-chart-full" style="margin-top:14px;">'
        f'<div class="cust-chart-title">最新{("季（" + _esc(iip.get("q_as_of", "")) + "，季频") if iip.get("q_as_of") and all(cs.get(x, {}).get("q_assets") is not None for x in ("US", "JP", "DE", "CN") if cs.get(x, {}).get("status") == "ok") else ("年（" + _esc(asof))}）· 四国对外总资产 vs 总负债（$万亿）</div>'
        f'{al_svg}'
        f'<div class="oil-meta">{meta}</div>'
        f'<div class="oil-src">数据源：{_esc(iip.get("source",""))}</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b><b>国际投资头寸(IIP)</b>是一国对外<b>金融资产与负债的存量</b>快照，'
        f'净头寸(NIIP=资产−负债)＝该国对世界其他地区的<b>净债权(正)或净债务(负)</b>：'
        f'<b>🇺🇸 美国</b>是全球最大<b>净债务国</b>(净头寸深度为负且持续恶化)——靠美元储备货币地位持续吸收外部资本；'
        f'<b>🇯🇵 日本 / 🇩🇪 德国 / 🇨🇳 中国</b>是主要<b>净债权国</b>(常年经常账户顺差累积对外资产)。'
        f'净债务国若外部融资条件收紧(利率↑/避险)会承压；净债权国则在全球动荡时资本回流本国、支撑本币。'
        f'是判断<b>全球资本流向与外部脆弱性</b>的结构性指标。<br>实线为年频(年末值)，虚线为晚于最新年末的季频点；同口径(IMF IIP 同一数据集，美国 2025-Q4 季频值与 2025 年频值一致)，IMF 官方公开数据。</div>'
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
        # ★2026-09-08 修(Chao 报「这张图没有每日更新啊」): 原标「🟢 每日」是<b>错的承诺</b>。
        #   WGC 官方方法论 PDF 原文: "We publish the data monthly, but the file contains
        #   daily data" / "Indian premium/discount data is calculated and reported weekly"
        #   —— 源头就是周更/月更, 只是文件内装日频序列。标成「每日」等于向读者承诺了
        #   数据源根本不提供的频率。改标官方真实口径 + 挂 weekly 档滞后徽章,
        #   断更时读者一眼可见(实测本次已断 25 天: 数据停 08-14, 今日 09-08)。
        f'<span class="chart-freq freq-w">🟡 周更/月更（WGC 官方口径）· World Gold Council goldhub</span>'
        f'{_stale_badge(gp.get("as_of", ""), "weekly", "黄金 premium")}</div>'
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
        recent = " → ".join(f'{q["date"][:7]} {q["tonnes"]}t' for q in monthly[-4:])
        mo_txt = (f' · 最新月度推算 <b>{m["tonnes"]}t</b>（{_esc(m["date"])}，GATA/Lambourne 从 BIS 月报推算；'
                  f'近几期：{_esc(recent)}）')
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
        f'仅呈现已核实公开真值，月度点由 cron 读 GATA 新披露只增补充，<b>绝不编造</b>。'
        f'{("<br><b>缺口：</b>" + _esc(bg.get("gaps_note"))) if bg.get("gaps_note") else ""}</div>'
        f'</div>'
    )


def _silver_net_price_svg(pts, px, W=1160, H=320):
    """白银做市商净持仓(左轴, 周度) + 白银价格(右轴, 日线) 双轴图。
    ★2026-09-25 Chao 要求叠加价格。悬停: 每个价格日一条命中带, 显示当日金价 +
    截至当日最近一期 COT 净持仓(注明截至日, 不插值)。"""
    import datetime as _dt
    PL, PR, PT, PB = 70, 64, 24, 34
    iw, ih = W - PL - PR, H - PT - PB
    d0 = min(pts[0]["date"], px[0][0]); d1 = max(pts[-1]["date"], px[-1][0])
    t0 = _dt.date.fromisoformat(d0).toordinal()
    span = max(1, _dt.date.fromisoformat(d1).toordinal() - t0)
    def X(d): return PL + iw * (_dt.date.fromisoformat(d).toordinal() - t0) / span
    nets = [p["comm_net"] for p in pts]
    nlo, nhi = min(nets + [0]), max(nets + [0])
    npad = (nhi - nlo) * 0.08 or 1; nlo, nhi = nlo - npad, nhi + npad
    pv = [v for _, v in px]
    plo, phi = min(pv), max(pv)
    ppad = (phi - plo) * 0.08 or 1; plo, phi = plo - ppad, phi + ppad
    def YN(v): return PT + ih * (1 - (v - nlo) / (nhi - nlo))
    def YP(v): return PT + ih * (1 - (v - plo) / (phi - plo))
    NC, PC = "#6b8fb5", "#8a8f98"
    p = [f'<svg viewBox="0 0 {W} {H}" class="sbp-chart" preserveAspectRatio="xMidYMid meet" '
         f'style="width:100%;height:auto;display:block" '
         f'font-family="-apple-system,PingFang SC,Helvetica,sans-serif">']
    for k in range(5):
        y = PT + ih * k / 4
        p.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{PL+iw}" y2="{y:.1f}" stroke="#d8d2c6" '
                 f'stroke-width="0.6" stroke-dasharray="2,3"/>')
        p.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" font-size="10" fill="{NC}" text-anchor="end">'
                 f'{nhi-(nhi-nlo)*k/4:,.0f}</text>')
        p.append(f'<text x="{PL+iw+8}" y="{y+3.5:.1f}" font-size="10" fill="{PC}" text-anchor="start">'
                 f'${phi-(phi-plo)*k/4:,.0f}</text>')
    if nlo < 0 < nhi:
        p.append(f'<line x1="{PL}" y1="{YN(0):.1f}" x2="{PL+iw}" y2="{YN(0):.1f}" stroke="#9a9184" stroke-width="0.9"/>')
        p.append(f'<text x="{PL+iw-4}" y="{YN(0)-4:.1f}" font-size="9.5" fill="#6f665a" text-anchor="end">净持仓 0</text>')
    # 净持仓: 零轴到曲线的面积 + 线
    npts = " ".join(f'{X(q["date"]):.1f},{YN(q["comm_net"]):.1f}' for q in pts)
    p.append(f'<polygon points="{X(pts[0]["date"]):.1f},{YN(0):.1f} {npts} '
             f'{X(pts[-1]["date"]):.1f},{YN(0):.1f}" fill="{NC}" opacity="0.12"/>')
    p.append(f'<polyline points="{npts}" fill="none" stroke="{NC}" stroke-width="1.6"/>')
    # 价格: 日线, 画上层
    p.append('<polyline points="' + " ".join(f'{X(d):.1f},{YP(v):.1f}' for d, v in px) +
             f'" fill="none" stroke="{PC}" stroke-width="1.3" opacity="0.95"/>')
    # 最新点
    p.append(f'<circle cx="{X(pts[-1]["date"]):.1f}" cy="{YN(nets[-1]):.1f}" r="3.4" fill="{NC}" stroke="#fff"/>')
    p.append(f'<circle cx="{X(px[-1][0]):.1f}" cy="{YP(pv[-1]):.1f}" r="3.4" fill="{PC}" stroke="#fff"/>')
    # x 轴年份
    seen = set()
    for d, _ in px:
        if d[:4] not in seen and d[5:7] == "01":
            seen.add(d[:4])
            p.append(f'<text x="{X(d):.1f}" y="{H-12}" font-size="10" fill="#8a8070" text-anchor="middle">{d[:4]}</text>')
    p.append(f'<text x="{PL-8}" y="{PT-9}" font-size="10" fill="{NC}" text-anchor="end">净持仓(合约)</text>')
    p.append(f'<text x="{PL+iw+8}" y="{PT-9}" font-size="10" fill="{PC}" text-anchor="start">白银 $/oz</text>')
    # 图例
    p.append(f'<rect x="{PL+4}" y="{PT-1}" width="380" height="18" rx="3" fill="#f4efe4" opacity="0.88"/>')
    p.append(f'<line x1="{PL+10}" y1="{PT+8}" x2="{PL+28}" y2="{PT+8}" stroke="{NC}" stroke-width="2.4"/>'
             f'<text x="{PL+32}" y="{PT+12}" font-size="10.5" fill="{NC}">做市商净持仓（左轴 · 周度）</text>'
             f'<line x1="{PL+190}" y1="{PT+8}" x2="{PL+208}" y2="{PT+8}" stroke="{PC}" stroke-width="2.4"/>'
             f'<text x="{PL+212}" y="{PT+12}" font-size="10.5" fill="{PC}">白银价格 SI=F（右轴 · 日线）</text>')
    # hover
    xs, tips, ci = [], [], -1
    for d, v in px:
        while ci + 1 < len(pts) and pts[ci + 1]["date"] <= d:
            ci += 1
        t = f'白银 ${v:,.2f}/oz'
        if ci >= 0:
            q = pts[ci]
            t += (f'<br>做市商净持仓 {q["comm_net"]:+,} 合约'
                  + (f'<br>（多 {q["comm_long"]:,} / 空 {q["comm_short"]:,}）'
                     if q.get("comm_long") is not None and q.get("comm_short") is not None else "")
                  + f'<br>持仓周度 · 截至 {q["date"]}')
        xs.append(X(d)); tips.append(f'{_esc(d)}||{_esc(t)}')
    p.append(_hover_bands(xs, tips, PT, ih, PL, PL + iw))
    p.append("</svg>")
    return "".join(p)


def _silver_bank_positions_html(sb):
    """白银做市商头寸 section: CFTC COT commercial 净持仓折线(净空区), 一手官方真数据。
    sb: fetch_silver_bank_positions()。绝不编造, 抓不到读缓存真值。"""
    if not sb or sb.get("status") in (None, "未获取") or not sb.get("points"):
        return '<p class="empty">白银做市商头寸(CFTC COT)数据未就绪（cron 每周更新）。</p>'
    pts = [p for p in sb["points"] if p.get("comm_net") is not None]
    if not pts:
        return '<p class="empty">白银做市商头寸(CFTC COT)数据未就绪。</p>'
    line_pts = [(p["date"], p["comm_net"]) for p in pts]
    # ★2026-09-25 叠加白银价格(右轴)。价格为日线, 裁到 COT 起点之后; 悬停同时显示两者(as-of)。
    px = [(d, v) for d, v in (sb.get("price") or []) if d >= pts[0]["date"]]
    if len(px) >= 20:
        svg = _silver_net_price_svg(pts, px)
    else:
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
    _px_line = ""
    if len(px) >= 20:
        _pxs = ('（价格源暂不可达，显示上次缓存）' if sb.get("price_status") == "缓存" else "")
        _px_line = (f' · 白银价格 <b style="color:#8a8f98">${px[-1][1]:,.2f}</b>/oz（{_esc(px[-1][0])}，'
                    f'{_esc(sb.get("price_source", ""))}）{_pxs}')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">白银做市商(bullion banks)净持仓 · CFTC COT commercial（合约 · 近10年）× 白银价格'
        f'<span class="chart-freq freq-w">{status_badge}</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(asof)}）：净持仓 <b style="color:#6b8fb5">{net:,}</b> 合约'
        f'（多 {lg:,} / 空 {sh:,} · OI {oi:,}） · 周环比 {dir_txt} · '
        f'历史最深净空 <b>{peak:,}</b>（{_esc(peakd)}）{_px_line}</div>'
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


def _cot_cadence_note(as_of):
    """COT 周频: 持仓日=周二, CFTC 通常周五发布(遇联邦假日顺延)。下一期日期由最近数据日推算, 不写死。
    ★2026-10-07 实测 CFTC Socrata 全表最新=09-29, 与本卡一致; 页面此前只写日期不写节奏, 读者会误以为没更新。"""
    try:
        d0 = datetime.date.fromisoformat(str(as_of)[:10])
    except Exception:
        return ""
    nxt_data = d0 + datetime.timedelta(days=7)
    nxt_pub = nxt_data + datetime.timedelta(days=3)
    late = ""
    if datetime.date.today() > nxt_pub + datetime.timedelta(days=2):
        late = ' <span class="stale-badge sb-amber">🟡 已超过预计发布日，请核对 CFTC 是否延迟</span>'
    return (f'周频 · 持仓日为周二、通常周五发布 · 本期持仓日 {d0.isoformat()} · '
            f'下一期持仓日 {nxt_data.isoformat()}，预计 {nxt_pub.isoformat()} 发布{late}')


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
    # ★2026-10-07 更正(Chao 复核全图时发现): 原写 latest/1000 却标「亿美元」, 实为「十亿美元」, 单位错 10 倍;
    #   且「约 460 吨」是【峰值季】(47.2B)的换算, 误挂在「最新季」后。现改: 最新季按 亿美元=百万美元/100 显示,
    #   吨数按「同一假设(金价约 $3200/oz, 与原批注一致)」分别给最新季与峰值季, 不再串用。
    latest_b = round(latest / 100, 1) if latest else None   # 百万美元 → 亿美元
    _oz_t = 32151.0
    _t_latest = round(latest * 1e6 / 3200.0 / _oz_t) if latest else None
    _t_peak = round(peak * 1e6 / 3200.0 / _oz_t) if peak else None
    # 460吨换算说明(用户图批注): 47B USD ÷ ~$3200/oz ÷ 32151 oz/t ≈ 460t 量级
    status_badge = ('🟡 缓存' if ge.get("status") == "缓存" else '🟢 每季 · FRED/BEA 官方')
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">美国黄金出口 · Nonmonetary Gold Exports（百万美元 · 季度 · 1999→今）'
        f'<span class="chart-freq freq-w">{status_badge}</span></div>'
        f'{svg}'
        f'<div class="oil-meta">最新（{_esc(latest_d)}）：<b style="color:#c9a94e">{latest:,.0f} 百万美元</b>{_srcslow_badge(latest_d, "季度", "2026-10-07", "FRED IEAXGG 官方 API 实测: 全序列最新观测=2026-04-01, FRED 最近一次更新 2026-09-24; 抓取链路完好")}'
        f'（≈ <b>{latest_b:,.0f} 亿美元</b>，按金价约 $3,200/盎司折算约 <b>{_t_latest} 吨</b>量级；峰值季约 {_t_peak} 吨） · '
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


def _comex_firms_top10_html(cf):
    """需求B(Chao 2026-08-22): 三金属 × top10 发货方/接货方 × 日/周/月/全期。

    cf: fetch_comex_issue_stop_firms()。排名按<b>总量</b>(非净额)。
    每个金属一块, 块内左右两栏(发货榜/接货榜), 顶部时间粒度 tab 切换。
    铂金交割极稀疏(常常整周无交割), 窗口内无数据时如实显示"该窗口无交割",
    绝不用其它窗口的数字充数。
    """
    if not cf or cf.get("status") != "ok" or not cf.get("metals"):
        return '<p class="empty">COMEX per-firm 交割明细未就绪（数据文件缺失，不编造）。</p>'

    CN = {"Gold": "黄金 Gold", "Silver": "白银 Silver", "Platinum": "铂金 Platinum"}
    wins = cf.get("windows", [])
    cov = cf.get("coverage", {})

    def _rank_list(rows, kind):
        """一栏榜单。kind: 'i'=发货(红) / 's'=接货(绿)。"""
        if not rows:
            return '<div class="tf-none">该窗口无交割记录</div>'
        mx = max(r["lots"] for r in rows) or 1
        col = "#d64545" if kind == "i" else "#2e9e5b"
        out = []
        for n, r in enumerate(rows, 1):
            w = r["lots"] / mx * 100
            tag = "" if r.get("is_bank") else '<span class="tf-nb">非银</span>'
            # ★2026-08-22(Chao): 主显<b>吨</b>便于直接口算, 手数放小字括号保留可追溯性
            t = r.get("tonnes")
            t_txt = f'{t:,.2f}' if isinstance(t, (int, float)) else "—"
            # ★账户类型徽章 C(客户盘)/H(自营盘)/U(未知) —— 按占比标注主导类型
            lots = r.get("lots") or 0
            c, hh, u = r.get("c", 0), r.get("h", 0), r.get("u", 0)
            if lots and (c or hh or u):
                parts = []
                if hh:
                    parts.append(f'<span class="tf-oh" title="House 自营盘 {hh:,} 手'
                                 f'（机构自有资金，代表其真实判断）">H {hh/lots*100:.0f}%</span>')
                if c:
                    parts.append(f'<span class="tf-oc" title="Customer 客户盘 {c:,} 手'
                                 f'（代客户清算，非该机构自身观点）">C {c/lots*100:.0f}%</span>')
                if u:
                    parts.append(f'<span class="tf-ou" title="账户类型未知 {u:,} 手'
                                 f'（Notion 增量段无 ORG 字段，不臆测归类）">? {u/lots*100:.0f}%</span>')
                org_html = '<span class="tf-org">' + "".join(parts) + "</span>"
            else:
                org_html = ""
            out.append(
                f'<div class="tf-row">'
                f'<span class="tf-rk">{n}</span>'
                f'<span class="tf-nm">{_esc(r["firm"])}{tag}{org_html}</span>'
                f'<span class="tf-bar"><i style="width:{w:.1f}%;background:{col}"></i></span>'
                f'<span class="tf-lot">{t_txt}<span class="tf-lots">({r["lots"]:,}手)</span></span>'
                f'<span class="tf-sh">{r["share"]:.1f}%</span>'
                f'</div>')
        return "".join(out)

    blocks = []
    for metal in ("Gold", "Silver", "Platinum"):
        per = cf["metals"].get(metal)
        if not per:
            continue
        slug = {"Gold": "au", "Silver": "ag", "Platinum": "pt"}[metal]
        tabs, panes = [], []
        for i, w in enumerate(wins):
            k = w["key"]
            d = per.get(k)
            if not d:
                continue
            act = " tf-on" if k == "m" else ""       # 默认「近一个月」
            rng = d.get("range", ["", ""])
            sub = (f'{rng[0]} → {rng[1]}（{d["days"]} 个交割日）'
                   if rng[0] != rng[1] else f'{rng[0]}（单日）')
            tabs.append(f'<button class="tf-tab{act}" data-tf="{slug}" '
                        f'data-k="{k}">{w["label"]}</button>')
            # ★窗口级 C/H 概览条: 一眼看出该窗口整体是客户盘还是自营盘主导
            def _org_bar(od, tot, lbl):
                if not tot or not od:
                    return ""
                c, hh, u = od.get("c", 0), od.get("h", 0), od.get("u", 0)
                seg = []
                for val, cls, nm in ((hh, "tfo-h", "H自营"), (c, "tfo-c", "C客户"), (u, "tfo-u", "?未知")):
                    if val:
                        seg.append(f'<i class="{cls}" style="width:{val/tot*100:.1f}%" '
                                   f'title="{nm} {val:,} 手（{val/tot*100:.1f}%）"></i>')
                return (f'<div class="tfo-row"><span class="tfo-lbl">{lbl}</span>'
                        f'<span class="tfo-bar">{"".join(seg)}</span>'
                        f'<span class="tfo-txt">H {hh/tot*100:.0f}% · C {c/tot*100:.0f}%'
                        + (f' · ? {u/tot*100:.0f}%' if u else "") + '</span></div>')

            org_html = (_org_bar(d.get("org_i"), d.get("total_i"), "交货")
                        + _org_bar(d.get("org_s"), d.get("total_s"), "接货"))
            panes.append(
                f'<div class="tf-pane{act}" data-tf="{slug}" data-k="{k}">'
                f'<div class="tf-sub">{sub} · 总交割 {d.get("total_i_t", 0):,.2f} 吨（{d["total_i"]:,} 手）</div>'
                f'{org_html}'
                f'<div class="tf-cols">'
                f'<div class="tf-col"><div class="tf-ct tf-ci">▲ Top10 交货方（Issued）</div>'
                f'{_rank_list(d["issuers"], "i")}</div>'
                f'<div class="tf-col"><div class="tf-ct tf-cs">▼ Top10 接货方（Stopped）</div>'
                f'{_rank_list(d["stoppers"], "s")}</div>'
                f'</div></div>')
        blocks.append(
            f'<div class="tf-metal"><div class="tf-mt">{CN[metal]}</div>'
            f'<div class="tf-tabs">{"".join(tabs)}</div>{"".join(panes)}</div>')

    return (
        f'<div class="cust-wrap"><div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">COMEX 交割前十名 · 金 / 银 / 铂'
        f'<span class="chart-freq freq-d">🟢 每日更新 · 数据截至 {_esc(cf.get("as_of",""))}</span></div>'
        f'{"".join(blocks)}'
        f'<div class="oil-src">数据源：{_esc(cf.get("source",""))} · '
        f'覆盖 {_esc(cov.get("start",""))} → {_esc(cov.get("end",""))}'
        f'（{cov.get("days","?")} 个交割日 = archive PDF {cov.get("archive_days","?")} + '
        f'Notion 增量 {cov.get("notion_days","?")}）· 单位：合约手数</div>'
        f'</div>'
        f'<div class="cust-how"><b>如何看：</b><b style="color:#d64545">交货方(Issued)</b>＝'
        f'开出交割通知、把实物交出去的一方；<b style="color:#2e9e5b">接货方(Stopped)</b>＝'
        f'接下通知、拿走实物的一方。二者总量恒等（每手交割必有一发一接）。<br>'
        f'<b>单位</b>：主数字为<b>吨</b>（便于与库存/产量口径直接对比），括号内为原始<b>合约手数</b>。'
        f'换算依据 CME 官方合约规格：黄金 100 oz/手、白银 5,000 oz/手、铂金 50 oz/手，'
        f'1 金衡盎司 = 31.1034768 克。<br>'
        f'<b>★账户类型 C / H（CME 原始 PDF 的 ORG 列）</b>：'
        f'<span class="tf-oh">H</span> = <b>House 自营盘</b>，机构用自有资金交割，'
        f'<b>代表该机构自己的真实判断</b>；'
        f'<span class="tf-oc">C</span> = <b>Customer 客户盘</b>，代客户清算，'
        f'背后是基金/实物商/散户，<b>不等于该机构的观点</b>。'
        f'同一家常同时有 C 与 H 两笔（如 Marex 同日 C 接 1 手、H 发 52 手）。'
        f'<b>读榜时应优先看 H 占比高的机构</b>——那才是机构在用自己的钱表态。'
        f'<span class="tf-ou">?</span> = 账户类型未知：'
        f'{_ch_gap_text(cf)}<br>'
        f'<b>排名口径</b>：按该窗口内<b>累计总量</b>排（非净额）——净额会让大进大出的做市商掉榜，'
        f'不符合「谁交货最多」的直觉。同一家可同时进两个榜（既发又接属正常做市行为）。<br>'
        f'<b>怎么用</b>：某家<b>持续霸榜接货方</b>＝在囤实物（看涨/逼空）；'
        f'<b>持续霸榜交货方</b>＝在放实物（压价/去库存）。<br>'
        f'<b>数据诚实说明</b>：archive 段为 CME 官方 PDF 的 per-firm 精确解析'
        f'（133/133 份全解析成功，席位加总与 PDF TOTAL 逐日自洽校验，0 处不符）；'
        f'近期段来自 Notion 每日交割明细增量。<b>铂金交割极稀疏</b>（常整周无交割），'
        f'短窗口内榜单为空属真实情况，不用其它窗口数字填充。</div>'
        f'{_comex_firms_who_html()}'
        f'</div>')


def _ch_gap_summary(cf=None):
    """从<b>原始 json 文件</b>实算「哪些日期没有 C/H 拆分」，供说明文字动态生成。

    ★2026-09-08(Chao 问「你不是已经有了 c h 了么，看看还有必要吗」): 页面上原本写死
    「{notion_days} 天的 Notion 增量段原始记录中没有 ORG 字段」——<b>这句话已经过时</b>。
    实测: archive 段(≤archive_end) 缺 0 天; Notion 段的缺口全部止于 2026-08-19,
    因为上游 cme_delivery_parser 在 8/21 改为输出「Advantage(C)发5」格式后, 解析器的
    兼容逻辑就一直正常工作(实测 8/26、8/28、9/02 的 i_c/s_c/i_h/s_h 都在)。
    写死 notion_days 会把「早就修好的历史缺口」说成「整段都没有」, 与今天上午黄金
    premium 那个假「每日更新」标签是同一类病: <b>说明文字与真实状态脱节</b>。

    ★★踩坑(同日): 第一版传 fetch_comex_issue_stop_firms() 的返回值进来, 结果渲染出
    「all ~ w 区间内 Gold 4 天」这种垃圾 —— 因为**那个返回值的 metals 已经是按窗口
    聚合过的**(键是 d/w/m/all), 不是逐日原始数据。逐日只存在于 json 文件里。
    故本函数直接读文件, 不接受聚合后的入参。

    返回 dict: {metal: {"n": 缺失天数, "first": 最早, "last": 最晚}}，无缺失则不含该 metal。
    """
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "data", "comex_issue_stop_firms.json")
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    out = {}
    for metal, days in (raw.get("metals") or {}).items():
        if not isinstance(days, dict):
            continue
        miss = []
        for d in sorted(days):
            # 只认 YYYY-MM-DD 形式的键，跳过任何聚合键
            if not (len(d) == 10 and d[4] == "-" and d[7] == "-"):
                continue
            firms = days[d]
            if not isinstance(firms, dict):
                continue
            has_ch = any(
                ("i_c" in v or "s_c" in v or "i_h" in v or "s_h" in v)
                for v in firms.values() if isinstance(v, dict))
            if not has_ch:
                miss.append(d)
        if miss:
            out[metal] = {"n": len(miss), "first": miss[0], "last": miss[-1]}
    return out


def _ch_gap_text(cf=None):
    """把 _ch_gap_summary 渲染成一句诚实的中文说明。"""
    gaps = _ch_gap_summary()
    if not gaps:
        return "目前<b>所有交割日均带精确 C/H</b>，无未知账户类型。"
    # 合并三金属的整体范围
    first = min(g["first"] for g in gaps.values())
    last = max(g["last"] for g in gaps.values())
    per = "、".join("%s %d 天" % (m, g["n"]) for m, g in gaps.items())
    return (f'<b>{_esc(first)} ~ {_esc(last)}</b> 区间内有部分交割日缺账户类型'
            f'（{_esc(per)}）——那段时期上游 Notion 增量记录尚未带出 CME 的 ORG 列，'
            f'如实标注为未知，<b>绝不臆测归到 C 或 H</b>；'
            f'<b>{_esc(last)} 之后已恢复精确 C/H</b>，archive PDF 段全程精确。')


def _comex_firms_who_html():
    """★2026-08-22(Chao): 「不同的机构代表哪些利益集团」——交割席位的阵营背景说明。

    ★纪律: 只写<b>本数据集中真实出现过的机构</b>(已核对归一后的 34 家名单), 不凑不编;
      阵营归类基于机构公开身份(LBMA 做市商资格 / 清算所 / FCM 经纪商等公开事实),
      对其交割动机的解读<b>明确标注为一般性行为逻辑, 不是对某家的指控</b>。
    """
    groups = [
        ("清算所自身", "#8a8578",
         ["CME"],
         "交易所清算机构的自有席位，<b>不是市场参与者</b>。出现在榜上多为交割流程的中转/代位，"
         "占比高不代表有人在大举交货 —— 读榜时应先把它排除再看真实机构排序。"),
        ("LBMA 核心做市商（美系）", "#7d6b8a",
         ["JP Morgan", "BofA", "Citi", "Goldman", "Morgan Stanley", "Wells Fargo"],
         "伦敦金银市场协会做市商与美国大行自营。<b>同时是最大的库房运营方与 COMEX 主力做市商</b>，"
         "既为客户代持也为自营账户操作，双向巨量收发属常态。其<b>净方向</b>（而非总量）"
         "才是判断压价 vs 囤货的关键信号。"),
        ("LBMA 做市商（欧系）", "#6b7d8a",
         ["HSBC", "Barclays", "Deutsche Bank", "BNP Paribas", "Std Chartered", "SG", "ABN AMRO"],
         "欧洲跨国行。HSBC 与 Std Chartered 在亚洲实物需求链上参与度高；"
         "BNP Paribas、Deutsche Bank 近年在贵金属交割端明显活跃。"
         "这一组的动向常与<b>亚洲/中东实物流向</b>相关。"),
        ("加拿大 / 日本 / 澳洲银行", "#6b8a7d",
         ["Scotia", "BMO", "RBC", "Mizuho", "Macquarie"],
         "Scotia（原 ScotiaMocatta）曾是全球最老的黄金交易行之一；BMO、RBC 为加系资源型银行；"
         "Mizuho 代表日系；Macquarie 是澳洲资源系投行。"
         "这一组常服务<b>矿业生产商的套保盘</b>，交货方向偏向生产端出货。"),
        ("非银 FCM / 自营商", "#a08a6b",
         ["StoneX", "Advantage", "Marex", "ADM", "Dorman", "PTG", "RJ O'Brien",
          "Interactive Brokers", "Wedbush", "Straits Financial", "Ironbeam",
          "Phillip", "Plus500", "Nanhua USA-HK"],
         "期货经纪商（FCM）与自营交易商，<b>多数是代客户清算</b>而非自有头寸。"
         "其席位背后可能是对冲基金、家族办公室、实物商或散户，"
         "<b>因此不能把它们的方向直接读成机构观点</b>——这是与 bullion bank 最大的区别。"
         "ADM 与 StoneX 亦有实物商品业务背景。"),
        ("对冲基金 / 其他", "#8a6b6b",
         ["Citadel"],
         "以自有资金参与的交易机构。在贵金属交割端出现频率低、量级小，"
         "偶发上榜多为特定策略的实物腿，不构成趋势信号。"),
    ]
    cards = []
    for name, color, firms, desc in groups:
        chips = "".join(f'<span class="fw-chip">{_esc(f)}</span>' for f in firms)
        cards.append(
            f'<div class="fw-grp">'
            f'<div class="fw-hd" style="border-left-color:{color}">'
            f'<b style="color:{color}">{name}</b>'
            f'<span class="fw-cnt">{len(firms)} 家</span></div>'
            f'<div class="fw-chips">{chips}</div>'
            f'<div class="fw-desc">{desc}</div>'
            f'</div>')
    return (
        f'<div class="cust-how fw-wrap">'
        f'<b>各机构代表哪些利益集团？</b>（按公开身份归类，覆盖本数据集出现过的全部机构）'
        f'<div class="fw-grid">{"".join(cards)}</div>'
        f'<div class="fw-note">★ 上表的<b>行为解读是一般性逻辑</b>，非对任何机构的指控。'
        f'交割席位反映的是<b>清算通道</b>，不等于最终受益人——'
        f'大行席位下既有自营也有代客，单看某日某家的方向容易过度解读，'
        f'应看<b>多窗口的持续性</b>（切换上方日/周/月/全期对比同一家的方向是否稳定）。'
        f'标<span class="tf-nb">非银</span>的机构尤其如此。</div>'
        f'</div>')


def _comex_issue_stop_html(cs):
    """图1: COMEX 做市商每周净 issue/stop 柱状图(金+银, 两口径)。cs: fetch_comex_issue_stop_weekly()。"""
    if not cs or cs.get("status") != "ok" or not (cs.get("gold") or cs.get("silver")):
        return '<p class="empty">COMEX 做市商周净 issue/stop 数据未就绪。</p>'

    def _week_done(week_monday):
        """该 ISO 周(周一日期)是否已过完: 周五已是过去(以今日东京日期)。"""
        import datetime as _d
        try:
            fri = _d.date.fromisoformat(week_monday) + _d.timedelta(days=4)
            _today = _d.datetime.now(_d.timezone(_d.timedelta(hours=9))).date()
            return _today > fri
        except Exception:
            return True

    def _bars_svg(rows, field, w=920, h=230):
        if not rows:
            return '<div class="cust-chart-na">无数据</div>'
        vals = [r[field] for r in rows if r.get(field) is not None]
        if not vals:
            return '<div class="cust-chart-na">该时间窗内没有可区分 House 的数据</div>'
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
            v = r[field]; x = X(i)
            if v is None:
                # ★Chao 2026-10-06 选 A: 该周全是「无 C/H 标记」数据 → 留白, 画一条浅灰细线占位, 悬停说明原因
                parts.append(f'<rect x="{x-bw/2:.1f}" y="{zero_y-3:.1f}" width="{bw:.1f}" height="6" fill="#d9d3c6" opacity="0.9" '
                             f'data-tip="{_esc(r["week"])}||无 House/Customer 区分，不进图（该周 {r.get("days", "?")} 个交割日的席位记录没有 C/H 标记）"/>')
                continue
            y = BY(v)
            col = "#d64545" if v > 0 else ("#2e9e5b" if v < 0 else "#8a8578")
            top = min(y, zero_y); ht = abs(y - zero_y)
            # ★2026-10-06 (Chao: 少了几天内容): 每周实际采到的交割日数写进悬停; 不足 5 天(且该周已过完)标「不完整」, 柱子加虚线描边。
            _nd = r.get("h_days") if r.get("h_days") is not None else r.get("days")
            _wk_done = _week_done(r["week"])
            _short = _nd is not None and _nd < 5 and _wk_done
            _cur = _nd is not None and not _wk_done
            _note = (f'（本周仅 {_nd}/5 个交割日有 House 记录，数值不完整）' if _short else
                     (f'（本周进行中，已有 {_nd} 个交割日）' if _cur else
                      (f'（{_nd} 个交割日）' if _nd is not None else '')))
            _st = ' stroke="#8a8578" stroke-width="1" stroke-dasharray="3,2"' if (_short or _cur) else ''
            parts.append(f'<rect x="{x-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{ht:.1f}" fill="{col}" opacity="{0.45 if (_short or _cur) else 0.82}"{_st} data-tip="{_esc(r["week"])}||{v:+.0f}{_esc(_note)}"/>')
        step = max(1, round(n/8)); prev=None
        for i in range(0, n, step):
            lbl = rows[i]["week"][:7]
            if lbl==prev: continue
            prev=lbl
            parts.append(f'<text x="{X(i):.1f}" y="{h-9}" font-size="8.5" fill="#8a8578" text-anchor="middle">{lbl}</text>')
        parts.append('</svg>')
        return "".join(parts)

    def _metal_block(metal_name, rows, slug):
        """★2026-08-22 需求A: 同一张图加时间窗口 filter(当周/过去一个月/过去三个月/全部)。
        数据一次性全量内嵌, 切换纯前端重绘, 不重新请求。窗口不足的诚实显示实际周数。"""
        if not rows:
            return f'<div class="cust-chart-na">{metal_name} 无数据</div>'
        _valued = [r for r in rows if r.get("core_net") is not None]
        if not _valued:
            return f'<div class="cust-chart-na">{metal_name} 暂无可区分 House 的数据</div>'
        latest = _valued[-1]
        cn = latest["core_net"]
        cdir = "净发货(交货/压价)" if cn > 0 else ("净接货(囤货/看涨)" if cn < 0 else "持平")

        import datetime as _dt
        try:
            _last = _dt.date.fromisoformat(rows[-1]["week"])
        except Exception:
            _last = None
        # (标签, 回看天数); None = 全部
        _wins = [("当周", 7), ("过去一个月", 30), ("过去三个月", 92), ("全部", None)]
        _views = []
        for _lbl, _days in _wins:
            if _days is None or _last is None:
                _sub = rows
            else:
                _cut = _last - _dt.timedelta(days=_days - 7)
                _sub = [r for r in rows
                        if _dt.date.fromisoformat(r["week"]) >= _cut] or rows[-1:]
            _views.append((_lbl, _sub))

        _tabs, _panes = [], []
        for _i, (_lbl, _sub) in enumerate(_views):
            _act = " cis-on" if _i == 2 else ""      # 默认「过去三个月」
            _tabs.append(
                f'<button class="cis-tab{_act}" data-cis="{slug}" data-idx="{_i}">'
                f'{_lbl}<span class="cis-n">{len(_sub)}周</span></button>')
            _panes.append(
                f'<div class="cis-pane{_act}" data-cis="{slug}" data-idx="{_i}">'
                f'{_bars_svg(_sub, "core_net")}'
                f'<div class="cust-chart-title" style="margin-top:8px;font-size:12px;color:#8a8578">'
                f'{metal_name} · 全投行(17家)对照</div>'
                f'{_bars_svg(_sub, "all_net")}</div>')

        return (
            f'<div style="margin-bottom:18px">'
            f'<div class="cust-chart-title">{metal_name} · 核心做市商每周净 issue/stop（合约）'
            f'<span class="chart-freq freq-d">最新周 {_esc(latest["week"])}：净 {cn:+d}（{cdir}）</span></div>'
            f'<div class="cis-tabs">{"".join(_tabs)}</div>'
            f'{"".join(_panes)}'
            f'</div>'
        )

    banks_core = "、".join(cs.get("banks_core", []))
    # 覆盖天数 = 各周实际采到的交割日数之和(取金银较大者); 原写法用 archive_pdfs_parsed(历史 PDF 数)会把增量日漏算
    _cov_days = max(sum((r.get("days") or 0) for r in (cs.get("silver") or [])),
                    sum((r.get("days") or 0) for r in (cs.get("gold") or [])))
    _short_wks = [r["week"] for r in (cs.get("silver") or []) if r.get("core_net") is not None and (r.get("h_days") if r.get("h_days") is not None else (r.get("days") or 5)) < 5 and _week_done(r["week"])]
    _blank_wks = [r["week"] for r in (cs.get("silver") or []) if r.get("blank")]
    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-chart-col cust-chart-full">'
        f'<div class="cust-chart-title">COMEX 做市商每周净 issue/stop · 金 + 银（{_esc(cs.get("data_range") or cs.get("archive_range",""))}，已覆盖 {_cov_days} 个交割日）'
        f'<span class="chart-freq freq-d">🟢 每日更新 · CME 交割报告</span></div>'
        f'{_metal_block("白银 Silver", cs.get("silver", []), "ag")}'
        f'{_metal_block("黄金 Gold", cs.get("gold", []), "au")}'
        f'<div class="oil-src">数据源：CME 每日 Issues &amp; Stops 交割报告（ScraperAPI/Jina/Wayback 三层兜底采集，x坐标精确解析）· '
        f'核心做市商(10家)：{_esc(banks_core)}'
        + (f'<br><b style="color:#8e3b30">⚠ 有 {len(_short_wks)} 周 House 记录不足 5 个交割日（虚线浅色柱）：</b>该日 House 当日可能确实为 0 笔，也可能上游采集只有库存没有交割明细；悬停可见实际天数。' if _short_wks else '')
        + (f'<br><b style="color:#8e3b30">留白 {len(_blank_wks)} 周（{_esc(_blank_wks[0])} → {_esc(_blank_wks[-1])}，浅灰细线）：</b>上游该段记录没有 C/H 标记，无法区分 House 与 Customer，按口径不进图，也不假装是 0。' if _blank_wks else '')
        + f'</div>'
        f'</div>'
        f'<div class="cust-how"><b>口径：</b>只统计 <b>House（自营）</b>席位；Customer（代客）不进图。<br><b>如何看：</b>每根柱=<b>该周大行(bullion banks)House 净 issue/stop</b>＝Σ发货−Σ接货：'
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
            f'<div class="fn-sum">{_esc_md(ev.get("summary",""))}</div>'
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
        f'2020 年 3 月「dash for cash」国债闪崩即源于此。敞口越高，一旦货币市场承压（见本页 SOFR−EFFR、'
        f'银行融资利差），去杠杆引发的<b>国债流动性踩踏</b>风险越大。<br>'
        f'⚠️ 数据源为 SEC Form PF，<b>季度更新且滞后发布</b>（非日频），是结构性中长期风险指标。</div>'
        f'</div>'
    )


def _cb_swaps_html(d):
    """★2026-08-24(Chao 点名遗失指标): 央行美元流动性互换板块。

    Chao:「我刚刚发现有一个指标我们好像遗失掉了，叫"央行货币互换"…
          你能不能看一下你是否可以把这个数据拿到，然后每天去爬取。」
    数据源 = 纽约联储官方 API(免费无 key)。<b>抓不到就显示未就绪, 绝不用旧值冒充。</b>
    """
    if not isinstance(d, dict) or d.get("status") not in ("ok", "empty"):
        msg = (d or {}).get("error") or "数据未就绪"
        return f'<div class="tf-none">央行货币互换：{_esc(str(msg))}（未就绪，不以旧值填充）</div>'
    if d.get("status") == "empty":
        return ('<div class="tf-none">央行货币互换：查询区间内<b>无任何互换操作</b>。'
                '这是<b>真实的零</b>——平静期本就接近零，不是抓取失败。</div>')

    wk = d.get("weekly") or []
    latest = d.get("latest_week_usd") or 0.0
    peak = d.get("peak_week_usd") or 1.0
    bycb = d.get("by_cb") or {}
    ops = d.get("ops") or []

    def _yi(v):
        return f"{v/1e8:,.2f}"

    # 周度柱状(近 52 周)
    show = wk[-52:]
    mx = max([w["usd"] for w in show] or [1.0]) or 1.0
    bars = "".join(
        f'<div class="cbs-b" style="height:{max(2, w["usd"]/mx*100):.1f}%" '
        f'title="{_esc(w["week"])} · {_yi(w["usd"])} 亿美元"></div>'
        for w in show)

    cb_rows = "".join(
        f'<div class="cbs-r"><span class="cbs-n">{_esc(k)}</span>'
        f'<span class="cbs-v">{_yi(v["usd"])} 亿</span>'
        f'<span class="cbs-c">{v["n"]} 笔</span></div>'
        for k, v in sorted(bycb.items(), key=lambda x: -x[1]["usd"]))

    op_rows = "".join(
        f'<tr><td class="cbs-d">{_esc(o["date"])}</td>'
        f'<td>{_esc(o["cb"])}</td>'
        f'<td class="cbs-num"><b>{_yi(o["usd"])}</b></td>'
        f'<td class="cbs-num">{_esc(str(o.get("term") or "—"))}天</td>'
        f'<td class="cbs-num">{_esc(str(o.get("rate") or "—"))}%</td></tr>'
        for o in ops[:12])

    return (
        f'<div class="kr-head">'
        f'<span class="kr-total">本周成交 <b>{_yi(latest)}</b> 亿美元</span>'
        f'<span class="kr-total">近一年峰值 <b>{_yi(peak)}</b> 亿</span>'
        f'<span class="kr-total">操作 <b>{d.get("n_ops", 0)}</b> 笔</span>'
        f'<span class="kr-total">截至 {_esc(str(d.get("as_of") or ""))}</span></div>'
        f'<div class="cust-how"><b>这是什么：</b>美联储与外国央行的<b>美元流动性互换</b>'
        f'（U.S. Dollar Liquidity Swap）—— 外国央行拿本币向 Fed 换美元，'
        f'再借给本辖区缺美元的银行，到期换回。<br>'
        f'<b>怎么看：</b>平静期接近零；<b>某国央行突然大额动用 = 该辖区银行在离岸市场借不到美元</b>，'
        f'是美元荒的直接温度计。2008 / 2020 危机期间曾冲到数千亿美元级别。'
        f'与 FIMA 回购便利（真 FIMA，常态≈0）、SOFR−EFFR 利差互为佐证——三者同时走高才是真紧张。<br>'
        f'<b>口径：</b>按 ISO 周汇总成交额；金额为原始美元数除以 1e8（亿美元）。'
        f'数据源 <a class="src-lnk" href="https://www.newyorkfed.org/markets/desk-operations/central-bank-liquidity-swap-operations" '
        f'target="_blank" rel="noopener">纽约联储官方</a>（每日更新，免费 API）。</div>'
        f'<div class="cbs-wrap"><div class="cbs-bars">{bars}</div>'
        f'<div class="cbs-axis"><span>{_esc(show[0]["week"]) if show else ""}</span>'
        f'<span>近 52 周成交额（柱高 = 当周金额）</span>'
        f'<span>{_esc(show[-1]["week"]) if show else ""}</span></div></div>'
        f'<div class="cbs-grid">{cb_rows}</div>'
        f'<table class="cbs-tb"><thead><tr><th>日期</th><th>对手央行</th>'
        f'<th>金额(亿$)</th><th>期限</th><th>利率</th></tr></thead>'
        f'<tbody>{op_rows}</tbody></table>')


def _kol_roster_table_html(hist_keys=None):
    """★2026-08-23(Chao): KOL 全量名录 —— 每人一张 Wiki 式档案卡, 放页面最底部备查。

    Chao 指定的 13 个维度(一个都不能少):
      姓名 / 编号 / 领域 / 在世年份 / 现任头衔 / 代表性成就 / 荣誉 /
      主要活动范围 / 观点 / 追踪价值 / 机构名称 / 书籍 / 代表性言论(仅当年)
    缺失处理(Chao 明确): 年龄查不到 → 标「未公开」;已故者 → <b>必须特别标出「已故」</b>。

    ★自动同步: 直接读 data/kol_registry.json 的 active 全量, <b>不写死人数</b>。
      名册由每日 cron 步骤 0 从 Notion「KOL List」单向镜像 ——
      Notion 侧新增 KOL, 次日自动多一张卡, 无需改代码。
    ★档案正文取自 data/kol_profiles.json(逐人联网检索撰写);
      该文件缺某人时, 卡片只显示名册已有字段并标「档案待补」, <b>绝不用模型猜写</b>。
    """
    import os as _os
    _dir = _os.path.dirname(__file__)
    try:
        reg = json.load(open(_os.path.join(_dir, "..", "data", "kol_registry.json"),
                             encoding="utf-8"))
    except Exception:
        return '<div class="tf-none">名册读取失败，本表跳过（绝不显示占位数据）</div>'
    ks = [k for k in reg.get("kols", []) if k.get("active")]
    if not ks:
        return '<div class="tf-none">名册为空</div>'

    prof = {}
    try:
        _pf = json.load(open(_os.path.join(_dir, "..", "data", "kol_profiles.json"),
                             encoding="utf-8"))
        for _x in (_pf.get("profiles") if isinstance(_pf, dict) else _pf) or []:
            if _x.get("id"):
                prof[_x["id"]] = _x
    except Exception:
        prof = {}

    def _num(k):
        for f in ("notion_list_num", "list_num", "notion_num"):
            v = k.get(f)
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str) and v.strip().isdigit():
                return int(v.strip())
        return 9999

    # 领域配色(莫兰迪同系, 10 类)
    PAL = ["#8ea1ad", "#c08a7d", "#9aa88f", "#b3a08c", "#8c93a8",
           "#a8998c", "#7d9c9c", "#b09a9a", "#93a396", "#a3969f"]
    doms = []
    for k in ks:
        d = k.get("domain") or "未分类"
        if d not in doms:
            doms.append(d)
    dcol = {d: PAL[i % len(PAL)] for i, d in enumerate(sorted(doms))}

    groups = {}
    for k in ks:
        groups.setdefault(k.get("domain") or "未分类", []).append(k)
    for g in groups.values():
        g.sort(key=lambda k: (_num(k), k.get("display_name") or ""))

    n_prof = sum(1 for k in ks if k.get("id") in prof)
    n_dead = sum(1 for k in ks if (prof.get(k.get("id")) or {}).get("deceased"))

    chips = "".join(
        f'<span class="kr-chip" style="border-color:{dcol[d]};color:{dcol[d]}">'
        f'{_esc(d)} <b>{len(g)}</b></span>'
        for d, g in sorted(groups.items(), key=lambda x: -len(x[1])))

    def _row(label, val, cls=""):
        if not val:
            return ""
        # ★_esc_md 而非 _esc: 档案正文里写的是 Markdown, HTML 不认 ** 会字面显示
        return (f'<div class="kp-r{cls}"><span class="kp-k">{label}</span>'
                f'<span class="kp-v">{_esc_md(val)}</span></div>')

    blocks = []
    for d, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        col = dcol[d]
        cards = []
        for k in g:
            p = prof.get(k.get("id")) or {}
            num = _num(k)
            num_txt = str(num) if num != 9999 else "—"
            life = p.get("lifespan") or "未公开"
            dead = bool(p.get("deceased"))
            dead_tag = '<span class="kp-dead">已故</span>' if dead else ""
            title = p.get("title") or k.get("institution") or ""
            inst = p.get("institution") or k.get("institution") or ""
            body = (
                _row("在世年份", life)
                + _row("现任头衔", title)
                + _row("机构名称", inst)
                + _row("代表性成就", p.get("achievements") or "")
                + _row("荣誉", p.get("honors") or "")
                + _row("书籍", p.get("books") or "")
                + _row("活动范围", p.get("scope") or "")
                + _row("观点", p.get("viewpoint") or k.get("focus") or "")
                + _row("追踪价值", p.get("track_value") or "")
                + _row("2026 代表言论", p.get("quote_2026") or "", " kp-q")
            )
            if not p:
                body += ('<div class="kp-todo">档案待补 —— 名册已收录，'
                         '但尚未逐人检索撰写完整档案（不猜写）</div>')
            # ★2026-09-08(Chao 问「全量名录怎么没有这个KOL的全部言论？」):
            #   卡片原先只显示 quote_2026 这一条, 而 kol_history payload 里
            #   平均每人有 27 条结构化言论(含 detail 论点/依据 + 来源链接),
            #   一直躺在页面 payload 里没接上。此处挂 kol-drill:
            #   点卡片 → 复用既有弹层按时间倒序看全部 N 条(含键盘可达性)。
            #   data-kol 必须用 payload 的 key(见 _kol_payload_key: 两边写法不同)。
            hk = _kol_payload_key(k.get("display_name") or "", hist_keys or ())
            nh = len((hist_keys or {}).get(hk) or ()) if isinstance(hist_keys, dict) else 0
            drill_cls, drill_attr, more = "", "", ""
            if hk:
                drill_cls = " kol-drill"
                drill_attr = (f' data-kol="{_esc(hk)}" tabindex="0" role="button"'
                              f' title="查看全部言论"')
                more = (f'<div class="kp-more">查看全部'
                        f'{f" {nh} 条" if nh else ""}言论 ›</div>')
            cards.append(
                f'<div class="kp-card{drill_cls}"{drill_attr} style="border-left-color:{col}">'
                f'<div class="kp-hd"><span class="kp-num">#{num_txt}</span>'
                f'<span class="kp-nm">{_esc(_kol_disp(k.get("display_name") or ""))}</span>'
                f'{dead_tag}</div>'
                f'{body}{more}</div>')
        blocks.append(
            f'<div class="kp-grp">'
            f'<div class="kp-gt" style="background:{col}">{_esc(d)}'
            f'<span class="kp-gn">{len(g)} 位</span></div>'
            f'<div class="kp-grid">{"".join(cards)}</div></div>')

    gap = ""
    if n_prof < len(ks):
        gap = (f'<div class="kr-gap">⚠ 档案完成度：<b>{n_prof}/{len(ks)}</b>。'
               f'未完成者卡片标「档案待补」，只显示名册已有字段 —— '
               f'<b>缺的信息一律留白，不用模型猜写</b>。</div>')

    return (
        f'<div class="kr-head"><span class="kr-total">在册 <b>{len(ks)}</b> 位</span>'
        f'<span class="kr-total">档案 <b>{n_prof}</b></span>'
        + (f'<span class="kr-total">已故 <b>{n_dead}</b></span>' if n_dead else "")
        + f'</div><div class="kr-chips">{chips}</div>'
        f'<div class="cust-how"><b>说明：</b>每人一张档案卡，含 13 个维度：'
        f'姓名 / 编号 / 领域 / 在世年份 / 现任头衔 / 代表性成就 / 荣誉 / 活动范围 / '
        f'观点 / 追踪价值 / 机构 / 书籍 / 当年代表性言论。按领域分色成组。<br>'
        f'<b>本表读名册 active 全量生成，不写死人数</b> —— 名册每日从 Notion「KOL List」'
        f'单向镜像，<b>Notion 侧新增一位，次日自动多一张卡</b>。<br>'
        f'<b>缺失口径</b>：年龄/生年查不到标「未公开」；'
        f'<b>已故者卡片右上角标红色「已故」徽章</b>；机构类条目非自然人，在世年份栏据实说明；'
        f'未写过书写「无公开著作」。<b>所有空缺一律留白或标注，绝不用模型猜写。</b></div>'
        f'{gap}{"".join(blocks)}')


def _bis_section_html(bis_latest, page_url, bis_all=None):
    """BIS(国际清算银行)报告 section。

    ★2026-08-22(Chao): 从「只显示最新一期」改为「过去 4 个季度可切换」——
    顶部一排 filter button(2026-06 / 2026-03 / 2025-12 / 2025-09), 点击切换要点。
    数据本来就已在 data/bis/reports.json 里(4 期各 6 条中文要点), 之前只是没渲染出来。

    bis_all:  bis_reports.load_reports() 的 reports 列表(按 date 降序)。传 None 时
              退回只渲染 bis_latest(向后兼容)。
    bis_latest: 最新一期(用于无 bis_all 时的兜底 / 决定默认选中项)。
    page_url: 独立页公开地址。
    只渲染 summary_status == 'ok' 且确有要点的期; pending 的不显示假内容。
    """
    # 归一成列表: 优先用全量, 否则退回单份
    reports = [r for r in (bis_all or []) if r.get("summary_status") == "ok" and r.get("summary")]
    if not reports and bis_latest and bis_latest.get("summary_status") == "ok" and bis_latest.get("summary"):
        reports = [bis_latest]
    # 按 date 降序(最新在左), 只取最近 4 期
    reports = sorted(reports, key=lambda r: r.get("date", ""), reverse=True)[:4]

    if not reports:
        return (
            f'<div class="card bis-card">'
            f'<div class="bis-na">最新 BIS 报告摘要待更新（daily cron 扫描中，抓不到不编造）。</div>'
            f'<div class="bis-how"><b>如何看：</b>BIS(国际清算银行)是"央行的央行"，其 Quarterly Review 每季'
            f'(3/6/9/12月)综述全球金融市场、银行体系、流动性、信用与系统性风险，是最权威的跨国央行视角。</div>'
            f'</div>')

    tabs, panes = [], []
    for i, r in enumerate(reports):
        act = " bis-on" if i == 0 else ""      # 默认最新一期
        date = r.get("date", "")
        # button 上只放年月(紧凑), 具体标题在 pane 里
        tabs.append(f'<button class="bis-tab{act}" data-bis="{i}">{_esc(date)}</button>')
        pdf = r.get("pdf_url", "")
        pdf_link = (f'　·　<a class="src-lnk" href="{_esc(pdf)}" target="_blank" rel="noopener">原文 PDF</a>'
                    if pdf else "")
        pts = "".join(f'<li>{_esc_md(p)}</li>' for p in r["summary"])
        panes.append(
            f'<div class="bis-pane{act}" data-bis="{i}">'
            f'<div class="bis-meta"><b>{_esc(r.get("title",""))}</b>'
            f'（{_esc(date)}）{pdf_link}</div>'
            f'<ul class="bis-pts">{pts}</ul>'
            f'</div>')

    span = (f'{_esc(reports[-1].get("date",""))} → {_esc(reports[0].get("date",""))}'
            if len(reports) > 1 else _esc(reports[0].get("date", "")))
    return (
        f'<div class="card bis-card">'
        f'<div class="bis-tabs">{"".join(tabs)}'
        f'<span class="bis-span">近 {len(reports)} 期 · {span}</span></div>'
        f'{"".join(panes)}'
        f'<div class="bis-how"><b>如何看：</b>BIS(国际清算银行)是"央行的央行"，其 Quarterly Review 每季'
        f'(3/6/9/12月)综述全球金融市场、银行体系、流动性、信用与系统性风险，是最权威的跨国央行视角。'
        f'上方按钮切换季度，可对比同一议题(如外汇结算风险、准备金充裕度、NBFI 流动性)在各季的表述变化。'
        f'点右上按钮查看全库报告。</div>'
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
    if not mt or not str(mt.get("status", "")).startswith("ok") or not mt.get("history_long"):
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


def _official_private_svg(off, priv, w=1050, h=230):
    """全球「外国官方 vs 外国私人」持有美债双线图。off/priv: [(YYYY-MM, $B),...] 升序。"""
    if not off or not priv or len(off) < 2:
        return '<div class="cust-chart-na">数据未就绪</div>'
    pad_l, pad_r, pad_t, pad_b = 58, 14, 16, 26
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    allv = [v for _, v in off] + [v for _, v in priv]
    vmin, vmax = min(allv), max(allv)
    span = (vmax - vmin) or 1.0
    vmin -= span * 0.08
    vmax += span * 0.08
    span = vmax - vmin
    n = len(off)

    def path(pts, color):
        d = []
        for i, (_, v) in enumerate(pts):
            x = pad_l + (iw * i / max(n - 1, 1))
            y = pad_t + ih - ih * (v - vmin) / span
            d.append(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}')
        return (f'<path d="{"".join(d)}" fill="none" stroke="{color}" '
                f'stroke-width="2.1" stroke-linejoin="round"/>')

    grid = []
    for f in (0, .25, .5, .75, 1):
        y = pad_t + ih - ih * f
        val = vmin + span * f
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                    f'stroke="#d8d0c3" stroke-width=".6" stroke-dasharray="2,3"/>')
        grid.append(f'<text x="{pad_l-6}" y="{y+3.5:.1f}" text-anchor="end" '
                    f'font-size="9.5" fill="#8a8377">{val:,.0f}</text>')
    xl = []
    for i in (0, n // 3, 2 * n // 3, n - 1):
        if 0 <= i < n:
            x = pad_l + (iw * i / max(n - 1, 1))
            xl.append(f'<text x="{x:.1f}" y="{h-8}" text-anchor="middle" '
                      f'font-size="9.5" fill="#8a8377">{off[i][0]}</text>')
    _pm = dict(priv)
    hits = _hover_bands(
        [pad_l + (iw * i / max(n - 1, 1)) for i in range(n)],
        [f'{_esc(d)}||外国官方 ${v:,.0f}B'
         + (f'&lt;br&gt;外国私人 ${_pm[d]:,.0f}B' if d in _pm else "")
         for d, v in off], pad_t, ih, pad_l, w - pad_r)
    return (f'<svg viewBox="0 0 {w} {h}" class="cu-svg" role="img">'
            f'{"".join(grid)}{path(priv, "#8f9bb3")}{path(off, "#c08a7d")}'
            f'{"".join(xl)}{hits}</svg>')


def _official_private_block(op):
    """全球 官方 vs 私人 持有美债。op: fetch_tic_official_vs_private()。

    ★这是 TIC 唯一的央行/非央行拆分, <b>只有全球总量, 没有分国</b>——
      Chao 2026-09-09 问「日本/美国央行和其他机构持有美债有没有区别」,
      答案是有且巨大, 但分国拆分美国财政部不公布(见函数 docstring)。
    """
    if not op or op.get("status") != "ok":
        st = (op or {}).get("status", "数据未就绪")
        return (f'<div class="cu-op"><div class="cu-op-title">全球 · 外国官方 vs 外国私人</div>'
                f'<div class="cust-chart-na">数据未就绪（{_esc(st)}）</div></div>')
    o_last, p_last = op["official_latest"], op["private_latest"]
    sh_f, sh_l = op["share_first"], op["share_latest"]
    od, pd_ = op["official_delta"], op["private_delta"]
    trend = "下降" if sh_l < sh_f else "上升"
    return (
        f'<div class="cu-op">'
        f'<div class="cu-op-title">🏛 全球 · 外国<b>官方</b>(央行/主权基金) vs 外国<b>私人</b> 持有美债'
        f'<span class="cu-op-sub">{_esc(op["first_month"])} → {_esc(op["latest_month"])} · $B · '
        f'TIC 唯一的央行/非央行拆分</span></div>'
        f'<div class="cu-op-kpis">'
        f'<div class="cu-op-kpi"><span class="k-lab">官方(央行)</span>'
        f'<span class="k-val" style="color:#c08a7d">{o_last:,.0f}B</span>'
        f'<span class="k-dlt {"r" if od < 0 else "g"}">{od:+,.0f}B</span></div>'
        f'<div class="cu-op-kpi"><span class="k-lab">私人</span>'
        f'<span class="k-val" style="color:#8f9bb3">{p_last:,.0f}B</span>'
        f'<span class="k-dlt {"r" if pd_ < 0 else "g"}">{pd_:+,.0f}B</span></div>'
        f'<div class="cu-op-kpi"><span class="k-lab">官方占比</span>'
        f'<span class="k-val">{sh_f:.1f}% → {sh_l:.1f}%</span>'
        f'<span class="k-dlt {"r" if sh_l < sh_f else "g"}">{sh_l-sh_f:+.1f}pp</span></div>'
        f'</div>'
        f'{_official_private_svg(op["official"], op["private"])}'
        f'<div class="cu-op-leg">'
        f'<span><i style="background:#c08a7d"></i>外国官方（央行 / 主权财富基金）</span>'
        f'<span><i style="background:#8f9bb3"></i>外国私人（银行 / 基金 / 保险 / 企业）</span>'
        f'</div>'
        f'<div class="cu-op-read"><b>怎么读：</b>官方占比从 {sh_f:.1f}% {trend}到 {sh_l:.1f}%'
        f'（{sh_l-sh_f:+.1f}pp）—— 全球央行净{"减持" if od < 0 else "增持"} '
        f'{abs(od):,.0f}B，私人净{"减持" if pd_ < 0 else "增持"} {abs(pd_):,.0f}B。'
        f'<b>边际买家已从官方部门转向私人部门</b>，意味着美债需求对价格/利差更敏感、'
        f'对储备管理政策的依赖下降。<b>注意：此拆分只有全球总量，'
        f'TIC 的 113 个国家/地区中没有任何一国带官方/私人拆分</b>——'
        f'「某国央行持有多少美债」美国财政部不公布，需看该国央行自己的资产负债表。</div>'
        f'</div>'
    )


def _prov_line(d):
    """单条序列的溯源行(Chao: 所有数据需可回溯源头 + 抓取路径)。"""
    pv = (d or {}).get("provenance") or {}
    if not pv:
        return ""
    mem = (d or {}).get("members") or []
    mem_s = ("，成员：" + "、".join(mem)) if len(mem) > 1 else ""
    return (
        f'<div class="cu-prov-row"><span class="cu-prov-nm">{_esc((d or {}).get("flag",""))} '
        f'{_esc((d or {}).get("name",""))}</span>'
        f'<span class="cu-prov-body">'
        f'当期：<a href="{_esc(pv.get("primary",""))}" target="_blank" rel="noopener">'
        f'{_esc(pv.get("primary","").rsplit("/",1)[-1])}</a> '
        f'（{_esc(pv.get("primary_desc",""))}）｜'
        f'长历史：<a href="{_esc(pv.get("history",""))}" target="_blank" rel="noopener">'
        f'{_esc(pv.get("history","").rsplit("/",1)[-1])}</a>｜'
        f'取值列：<code>{_esc(pv.get("column",""))}</code>｜'
        f'{_esc(pv.get("agg",""))}{_esc(mem_s)}'
        f'</span></div>'
    )


def _country_ust_html(cu, official_private=None):
    """日本 / 中国 / 欧元区(拆分) 持有美债 + 全球官方vs私人 + 2008长历史 + 溯源。

    ★2026-09-09 重写(Chao 以国债交易员视角提的三条要求):
      ① 欧盟不再拢成一个数 —— 拆「托管中心(比卢爱)」与「真实需求国(德法意荷西芬)」,
         两组驱动逻辑相反: 前者是第三国资金借道 Euroclear/Clearstream,
         后者才是欧洲机构的真实配置(美欧利差与对冲成本驱动)。
         实测拆开后 真实需求 +139.4% > 托管 +96.1%, 这个结构差异在合计里被完全抹掉。
      ② 新增全球「官方 vs 私人」——「分央行和私人部门两个数据」。
      ③ 每条序列附溯源(URL/表名/列名/成员国)。
    """
    _keys = ("Japan", "China", "EU")
    _eu_split = ("EU_CUSTODY", "EU_REAL")
    if not cu or all(cu.get(k, {}).get("status") != "ok" for k in _keys):
        return '<p class="empty">日本 / 中国 / 欧盟 持有美债数据未就绪。</p>'
    src = next((cu[k].get("source") for k in _keys if cu.get(k, {}).get("status") == "ok"),
               "US Treasury TIC")

    # ── 2008 长历史多国折线 ──
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

    # ── 欧元区拆分行 ──
    eu_split_block = ""
    if any(cu.get(k, {}).get("status") == "ok" for k in _eu_split):
        cus, real = cu.get("EU_CUSTODY", {}), cu.get("EU_REAL", {})
        ratio = ""
        try:
            tot = cus["latest"][1] + real["latest"][1]
            ratio = (f'托管中心占欧元区合计 <b>{100*cus["latest"][1]/tot:.1f}%</b>，'
                     f'真实需求国 <b>{100*real["latest"][1]/tot:.1f}%</b>')
        except Exception:
            ratio = ""
        eu_split_block = (
            f'<div class="cu-eusplit">'
            f'<div class="cu-eusplit-title">🔍 欧元区拆分 · 托管中心 vs 真实需求国'
            f'<span class="cu-eusplit-sub">同为 TIC 口径，但持有人性质完全不同 —— '
            f'合计数会抹掉这个结构差异</span></div>'
            f'<div class="cust-charts cust-charts-2">'
            f'{_country_ust_col(cus)}'
            f'{_country_ust_col(real)}'
            f'</div>'
            f'<div class="cu-eusplit-read"><b>交易员视角：</b>'
            f'<b>托管中心</b>＝比利时(Euroclear)／卢森堡(Clearstream)／爱尔兰。'
            f'卢森堡持仓约为其 GDP 的 <b>4.3 倍</b>，比利时约 <b>0.67 倍</b> —— '
            f'经济体量根本撑不起这个规模，说明大部分是<b>第三国资金借道寄存</b>'
            f'（2014 年比利时持仓暴涨被普遍认为是中国借道 Euroclear）。'
            f'这一组的变化要与中国持仓<b>反向对读</b>：中国降、托管升，很可能是同一笔钱换了保管箱，'
            f'而非真实抛售。<br>'
            f'<b>真实需求国</b>＝德/法/意/荷/西/芬，持仓量级与经济体量匹配，'
            f'反映欧洲保险／养老金／基金的<b>真实配置行为</b>，主要由美欧利差'
            f'（10Y 美债 − 德债，扣汇率对冲成本后的净收益）驱动。'
            f'{ratio}。<br>'
            f'<b>⚠️ 与下方各国央行资产负债表不是包含关系：</b>这里统计的是所有外国持有人'
            f'（保险／养老金／基金／企业），欧元区各国央行几乎不持有美债'
            f'（实测德国央行「对非欧元区外币债权」仅 €0.004B，外汇储备已大部分上缴 ECB 统一管理）。'
            f'</div></div>'
        )

    # ── 全球 官方 vs 私人 ──
    op_block = _official_private_block(official_private)

    # ── 溯源 ──
    prov_rows = "".join(_prov_line(cu.get(k)) for k in
                        ("Japan", "China", "EU", "EU_CUSTODY", "EU_REAL")
                        if (cu.get(k) or {}).get("provenance"))
    op_prov = ""
    if official_private and official_private.get("status") == "ok":
        op_prov = (
            f'<div class="cu-prov-row"><span class="cu-prov-nm">🏛 全球官方/私人</span>'
            f'<span class="cu-prov-body">'
            f'<a href="https://ticdata.treasury.gov/Publish/slt_table3.txt" '
            f'target="_blank" rel="noopener">slt_table3.txt</a>'
            f'（TIC Table 3 内两行全球汇总）｜'
            f'行名：<code>Of Which: Foreign Official</code>(码 99990) / '
            f'<code>Of Which: Foreign Non-Official</code>(码 99991)｜'
            f'取值列：<code>for_treas_pos(第4列)</code>｜无分国拆分'
            f'</span></div>')
    prov_block = (
        f'<div class="cu-prov">'
        f'<div class="cu-prov-title">🔗 数据溯源 · 每条序列的来源与抓取路径</div>'
        f'{prov_rows}{op_prov}'
        f'<div class="cu-prov-note">★ TIC 为<b>托管口径</b>：统计证券登记在哪国托管账户，'
        f'不是最终受益人。美国财政部原文：“…cannot attribute holdings of U.S. securities '
        f'with complete accuracy … if a U.S. Treasury security purchased by a foreign resident '
        f'is held in a custodial account in a third country, the true ownership of the security '
        f'will not be reflected in the data.”（'
        f'<a href="https://home.treasury.gov/system/files/136/Press-notice-TIC-for-Oct-2024.pdf" '
        f'target="_blank" rel="noopener">TIC 月度新闻稿</a>）</div>'
        f'</div>'
    )

    return (
        f'<div class="cust-wrap">'
        f'<div class="cust-charts cust-charts-3">'
        f'{_country_ust_col(cu.get("Japan"))}'
        f'{_country_ust_col(cu.get("China"))}'
        f'{_country_ust_col(cu.get("EU"))}'
        f'</div>'
        f'{eu_split_block}'
        f'{op_block}'
        f'<div class="cust-how"><b>如何看：</b>美国财政部 TIC 口径下各国/地区持有的美债总额'
        f'（含官方＋私人，月度，滞后约 2 个月）。'
        f'<b>日本</b>是最大单一持有国，近10年高位震荡；'
        f'<b>中国</b>近10年持续系统性减持，是去美元化／中美博弈的结构性信号；'
        f'<b>欧元区合计</b>为 9 国加总（TIC 无欧盟合计行），'
        f'已在上方按<b>托管中心／真实需求国</b>拆开——两者信号含义相反，不可混看。'
        f'数据源：{_linkify_sources(src)}。</div>'
        f'{long_block}'
        f'{prov_block}'
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
        f'口径为 BIS credit-to-GDP ratio 的二阶差分（美/中/欧/日统一口径、国际可比），<b>季度序列、BIS 汇编发布滞后约 3 季</b>（as of {_esc(asof)[:7]}）{_srcslow_badge(asof, "季度", "2026-10-07", "FRED QUSPAM770A/QCNPAM770A 等四国序列官方 API 实测: 最新观测均=2025-10-01, FRED 06-15 才更新; 抓取链路完好", extra="BIS 汇编发布滞后约 3 季")}。'
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
        "carry": ("<b>怎么看：</b>carry = 各期限国债收益率 − 隔夜融资成本（美债用 SOFR，日债用 TONAR），即"
                  "<b>回购融资买入并持有现券的净收益(bp)</b>。carry 为正且宽 = 持券吃息差有肉、头寸稳；"
                  "<b>carry 收窄甚至转负(倒挂)= 借钱持债反而亏损 = 强平动机爆发</b>。"
                  "短端(2Y/1M)对融资成本最敏感，最先转负。实线=美债(−SOFR)，虚线=日债(−TONAR)。"
                  "<br><b>⚠️ 口径说明(2026-08-22 修正)：</b>本图是<b>现券持有 carry（单腿）</b>，"
                  "<b>不是</b>对冲基金的「期现基差套利(cash-futures basis trade)」。后者是<b>双腿</b>："
                  "回购融资买入 CTD 现券 + 同时卖空对应国债期货，收益 = "
                  "<b>隐含回购利率(IRR) − 实际回购利率</b>，其中 IRR =［(发票价格 − 债券脏价) / 债券脏价］×(年天数 / 距交割天数)，"
                  "发票价格 = 期货价 × 转换因子 + 交割日应计利息（依据 Fed FEDS Notes 2024-03-08、"
                  "ScienceDirect《Hedge funds and the Treasury cash-futures basis trade》）。"
                  "两者关键差异：真 basis trade 的<b>久期风险被期货腿对冲掉</b>，本图的现券 carry <b>仍暴露久期风险</b>。"
                  "真 net basis 需 CME 期货结算价 + 转换因子 + CTD 判定（商业授权/反爬），本项目免费源不可得，"
                  "<b>故只做现券 carry 并如实标注，绝不冒充 basis trade</b>。"
                  "<br><b>怎么用：</b>任一期限 carry 跌破 0(<span style=\"color:#d64545\">红区</span>)= 🔴 该期限持券头寸开始亏损，"
                  "叠加融资触顶就是去杠杆的直接扳机——这与真 basis trade 的强平压力<b>同向</b>（融资成本是两者共同的分母），"
                  "故仍是有效的预警代理。日债近端 carry 转负正是 TONAR 融资倒挂预警(对应表6)。"),
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
            tip = (f'{m["ticker"]}·{m["name"]}'
                   f'{("（" + m["zh"] + "）") if m.get("zh") and m["zh"] != m["name"] else ""}'
                   f'｜FY{(m.get("fy") or "")[:7]}'
                   f'｜经营现金流 {m["ocf"]/1e9:,.1f}B｜资本开支 '
                   f'{m["capex"]/1e9:,.1f}B｜自由现金流 {v:+,.1f}B')
            p.append(f'<rect x="{cx-bw/2:.1f}" y="{ytop:.1f}" width="{bw:.1f}" '
                     f'height="{max(hh,0.6):.1f}" fill="{fill}" opacity="0.88" '
                     f'data-tip="{_esc(tip)}"/>')
            lv = f'{v:+,.0f}' if abs(v) >= 1 else f'{v:+,.1f}'
            ly = (ytop - 3) if v >= 0 else (ytop + hh + 9)
            p.append(f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                     f'font-size="8.5" fill="#aab3c5">{lv}</text>')
        p.append(f'<text x="{cx:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="10" fill="#c8cee0">{_esc(m["ticker"])}</text>')
        # ★中文名 (Chao 2026-08-25): 放 ticker 与财年之间。
        #   字号 8 且比 ticker 暗一档, 保证 ticker 仍是第一视觉层级。
        zh = m.get("zh")
        if zh:
            p.append(f'<text x="{cx:.1f}" y="{mt+ph+24.5:.1f}" '
                     f'text-anchor="middle" font-size="8" fill="#98a1b3">'
                     f'{_esc(zh)}</text>')
        fy = (m.get("fy") or "")[:7]
        if fy:
            p.append(f'<text x="{cx:.1f}" y="{mt+ph+35:.1f}" '
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
        tip = (f'{r["ticker"]}·{r["name"]}'
               f'{("（" + r["zh"] + "）") if r.get("zh") and r["zh"] != r["name"] else ""}'
               f'｜FY{(r.get("fy") or "")[:7]}'
               f'｜净债务/EBITDA {r["leverage"]:+,.2f}x'
               f'｜利息保障 {r["coverage"]:,.1f}x'
               f'｜净债务 {nd/1e9:+,.1f}B｜EBITDA {r["ebitda"]/1e9:,.1f}B')
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{col}" '
                 f'opacity="0.85" stroke="#11141a" stroke-width="1" '
                 f'data-tip="{_esc(tip)}"/>')
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
                     f'height="{hh:.1f}" fill="{fill}" opacity="{op}" rx="2" '
                     f'data-tip="{_esc(tip)}"/>')

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
                             f'fill="#fff" stroke="#dc2626" stroke-width="2" '
                             f'data-tip="{_esc(f"{ym}｜日均 {v:,.0f} 亿元")}"/>')
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
                     f'rx="2" data-tip='
                     f'"{_esc(f"{y_} 年｜金额 {a:,.0f} 亿元（{a/10000:.1f} 万亿）｜笔数 {c:,}{yoy}")}"/>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{mt+ph+14}" '
                     f'text-anchor="middle" font-size="10" fill="#6b7280">'
                     f'{y_}</text>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="#9ca3af" stroke-width="1.2"/>')
    parts.append("</svg>")
    return "".join(parts)


def _cn_liq_html(cl):
    """中国流动性四图 + 多周期变动表。cl: fetch_china_liquidity()。

    布局（Chao 2026-08-25 定稿）：
      变动表  周/月/半年 三口径同屏对比（他要「同一时间的变动情况」）
      图1 OMO 逆回购分品种柱状 · 日频
      图2 DR007 折线 · 日频
      图3 MLF 月度操作柱状 · 事件频
      图4 SFISF 股市托底工具 · 事件频（<b>替换原 PSL</b>）

    ★ PSL 已下架（Chao：「已经是过时的了」）—— 工具本身在清退，官网停更 448 天。
    ★ SFISF = 券商/基金/险资拿股票资产抵押换国债，钱只能投股市 → 最直接的官方托市工具。
    ★ 每个子图都标<b>更新频率</b>（Chao 明确要求），避免把事件频当日频读。
    """
    if not cl or cl.get("status") != "ok":
        err = (cl or {}).get("error") or ""
        return (f'<p class="empty">中国流动性数据未就绪'
                f'{("（" + _esc(err) + "）") if err else ""}。</p>')

    omo, dr, mlf, sf = cl["omo"], cl["dr007"], cl["mlf"], cl.get("sfisf") or []
    dl = cl.get("deltas") or {}
    h = []

    # ── 概览行 ──
    bits = []
    if omo:
        last = omo[-1]
        seg = []
        if last.get("on") is not None:
            seg.append(f'隔夜 {last["on"]:,.0f}亿')
        if last.get("d7") is not None:
            seg.append(f'7天 {last["d7"]:,.0f}亿')
        rt = f'@{last["rate"]}%' if last.get("rate") is not None else ""
        bits.append(f'逆回购（{last["date"]}）<b>{"＋".join(seg) or "—"}</b>{rt}')
    if dr:
        bits.append(f'DR007 <b>{dr[-1]["v"]:.4f}%</b>')
    if mlf:
        bits.append(f'MLF（{mlf[-1]["date"]}）<b>{mlf[-1]["v"]:,.0f}亿</b>')
    if sf:
        bits.append(f'SFISF 累计 <b>{sum(x["v"] for x in sf):,.0f}亿</b>')
    h.append('<div class="oil-meta">' + ' · '.join(bits) + '</div>')

    # ── 多周期变动表 ──
    h.append(_cn_delta_table(dl, sf))

    # ── 图1 OMO ──
    h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
             '① 公开市场逆回购 · 分品种投放'
             '<span class="freq-badge freq-daily">每日更新</span></div>')
    h.append(_cn_omo_svg(omo[-130:]))
    h.append(f'<p class="cips-note">口径：PBoC《公开市场业务交易公告》当日<b>执行量</b>（非计划上限）。'
             f'2026-06 起新增「隔夜」品种，与 7 天期分列——只看总量会掩盖品种结构变化。'
             f'净投放需当日到期量，PBoC 不公开，故不展示净额、不估算。'
             f'历史覆盖 {len(omo)} 个交易日'
             f'（{omo[0]["date"] if omo else "-"} 起）。</p>')

    # ── 图2 DR007 ──
    if dr:
        h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
                 '② DR007 · 存款类机构质押式回购利率（短期资金<b>价格</b>）'
                 '<span class="freq-badge freq-daily">每日更新</span></div>')
        h.append(_cn_line_svg(dr, "v", unit="%", color="#c17d6a", dec=4))
        h.append(f'<p class="cips-note">口径：CFETS（中国货币网）FDR007，'
                 f'即<b>存款类机构</b>质押式回购加权利率。'
                 f'★注意与 FR007 区别：后者是<b>全市场</b>（含非银），'
                 f'资金面紧张时两者能差几十 bp，取错口径结论会反。'
                 f'量（逆回购投放）与价（DR007）要合看：投放大而 DR007 仍上行 = 资金面真紧。'
                 f'历史覆盖 {len(dr)} 个交易日（{dr[0]["date"]} 起）。</p>')

    # ── 图3 MLF ──
    if mlf:
        h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
                 '③ MLF 中期借贷便利 · 月度操作量'
                 '<span class="freq-badge freq-monthly">月度 · 每月一次招标</span></div>')
        h.append(_cn_bar_svg(mlf, "v", unit="亿元", color="#6b8fb5"))
        h.append(f'<p class="cips-note">口径：PBoC《中期借贷便利招标公告》，1 年期。'
                 f'★<b>历史长度受官方披露限制</b>：PBoC 该栏目 2025-01 才创建，'
                 f'目前可得 {len(mlf)} 个月（{mlf[0]["date"][:7]} 起）。'
                 f'2024 年的 MLF 公告在官网、Wayback 存档、公开数据接口均未检索到，'
                 f'按项目铁律不用二手估算值填充。</p>')

    # ── 图4 SFISF（替换 PSL）──
    h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
             '④ SFISF 互换便利 · <b>股市托底工具</b>'
             '<span class="freq-badge freq-monthly">事件驱动 · 央行启用时发布</span></div>')
    h.append(_cn_sfisf_html(sf))

    # ── 图5 A股两融余额（Chao 2026-08-25 指定）──
    # 定位：SFISF 停发独立公告后，用<b>日频</b>杠杆资金活跃度回答「钱在进还是在退」。
    # 这是<b>代理指标不是 SFISF 本身</b> —— 标题与说明必须写清，避免口径混淆。
    mgr = (cl.get("margin") or [])
    if mgr:
        h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
                 '⑤ A股两融余额 · <b>杠杆资金日频代理</b>'
                 '<span class="freq-badge freq-daily">每日更新</span></div>')
        _lo, _hi = mgr[0], mgr[-1]
        h.append(f'<p class="oil-meta">融资融券余额反映场内杠杆资金的进退，'
                 f'是<b>日频</b>指标 —— SFISF 已停发独立公告（季度/年度口径），'
                 f'看短期资金动向要靠这条。'
                 f'<b>注意：这是代理指标，不等于 SFISF 本身。</b>'
                 f'覆盖 {_lo["date"]} ~ {_hi["date"]}，共 {len(mgr)} 个交易日。</p>')
        h.append(_cn_line_svg(mgr, "v", unit="万亿", color="#c9a961", dec=3))

    # ── 图6 宽基 ETF 份额（Chao 2026-08-25，B 方案）──
    # ★ 看份额不看规模：规模=净值×份额会被指数涨跌污染，份额才是真申购/赎回。
    etf = cl.get("etf") or {}
    ser = etf.get("series") or {}
    if ser:
        h.append('<div class="part-title" style="font-size:14px;margin-top:12px">'
                 '⑥ 宽基 ETF 份额 · <b>真金白银进出</b>'
                 '<span class="freq-badge freq-daily">每日更新</span></div>')
        _n = min(len(s) for s in ser.values())
        h.append(f'<p class="oil-meta">'
                 f'<b>只看份额，不看规模或价格</b> —— 规模=净值×份额会被指数涨跌污染'
                 f'（指数涨 10%、份额没动，规模也涨 10%，看着像资金流入其实没有）。'
                 f'<b>份额增加 = 真有人申购</b>，减少 = 赎回撤离。'
                 f'SFISF 抵押品明确包含股票 ETF 与沪深300 成分股，机构拿到钱进场首选宽基，'
                 f'所以这三只的份额变化能侧面反映「国家队在不在场」。'
                 f'数据源：上交所官方每日 ETF 规模表。'
                 f'{f"覆盖约 {_n} 个交易日。" if _n else ""}'
                 f'<b>注意：代理指标，不等于 SFISF 本身。</b></p>')
        # ★ 2026 年这条曲线断崖式下行是<b>真实事件</b>不是数据故障，必须写明，
        #   否则读图的人第一反应是"抓错了"。已用公开报道逐点交叉验证：
        #   我们的 2025-12-31=888.30 / 2026-01-21=719.78 / 2026-01-27=575.33 /
        #   2026-08-10=248.61，与媒体披露数字<b>完全一致</b>。
        h.append('<p class="oil-meta" style="border-left:3px solid #c9a961;'
                 'padding-left:9px;color:#c9a961">'
                 '<b>读图提示：2026 年的断崖是真实事件，不是数据故障。</b>'
                 '沪深300ETF 份额自 2026-01-15 起连续单边下滑，'
                 '由 2025 年末的 888 亿份降至当前约 238 亿份（−73%）。'
                 '公开报道确认为<b>「国家队」（中央汇金系）大额赎回</b>：'
                 '一季度单该基金即赎回约 500 亿份，同期易方达、华夏等头部宽基同步缩水。'
                 '数值已与公开披露逐点交叉核对一致（2025-12-31 = 888.30 亿份、'
                 '2026-01-27 = 575.33 亿份、2026-08-10 = 248.61 亿份）。</p>')
        h.append(_etf_share_svg(ser, etf.get("names") or {}))
        h.append(_etf_delta_table(dl.get("etf") or {}, etf.get("names") or {}))

    return "".join(h)


def _etf_share_svg(series, names, w=940, h=250):
    """三只宽基 ETF 份额同图。

    ★ 归一化到「首日=100」再画：三只量级差 5 倍（300ETF 238 亿份 vs 500ETF 49 亿份），
      直接画绝对值会让小的那条压成一条直线，看不出变化。
      归一化后比较的是<b>各自的相对增减</b>，这正是我们要看的「进出方向」。
    """
    codes = [c for c in ("510300", "510050", "510500") if series.get(c)]
    if not codes:
        return ""
    cols = {"510300": "#6b8fb5", "510050": "#7fa085", "510500": "#b58a6a"}
    norm = {}
    for c in codes:
        s = series[c]
        base = s[0]["v"] or 1
        norm[c] = [{"date": x["date"], "v": x["v"] / base * 100, "raw": x["v"]}
                   for x in s]
    allv = [p["v"] for c in codes for p in norm[c]]
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1
    ml, mr, mt, mb = 62, 14, 16, 46
    pw, ph = w - ml - mr, h - mt - mb
    n = max(len(norm[c]) for c in codes)

    def Y(v):
        return mt + ph - ph * (v - lo) / span

    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for k in range(5):
        tv = lo + span * k / 4
        yy = Y(tv)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.1f}</text>')
    # 100 基准线（首日水平），越过=净申购，跌破=净赎回
    if lo < 100 < hi:
        y100 = Y(100)
        p.append(f'<line x1="{ml}" y1="{y100:.1f}" x2="{ml+pw}" y2="{y100:.1f}" '
                 f'stroke="#8b93a7" stroke-width="1" stroke-dasharray="5 4" opacity="0.7"/>')
        p.append(f'<text x="{ml+pw-2}" y="{y100-4:.1f}" text-anchor="end" '
                 f'font-size="9" fill="#8b93a7">首日基准 100（上方=净申购）</text>')
    p.append(f'<text x="{ml-52}" y="{mt-2}" font-size="10" fill="#8b93a7">指数化</text>')
    for c in codes:
        s = norm[c]
        m = len(s)

        def X(i, _m=m):
            return ml + pw * i / max(_m - 1, 1)
        pts = " ".join(f'{X(i):.1f},{Y(x["v"]):.1f}' for i, x in enumerate(s))
        p.append(f'<polyline points="{pts}" fill="none" stroke="{cols[c]}" '
                 f'stroke-width="1.8"/>')
        for i, x in enumerate(s):
            _tip = (f'{names.get(c, c)} · {x["date"]}｜'
                    f'{x["raw"]:,.2f} 亿份（指数 {x["v"]:.1f}）')
            p.append(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(x["v"]):.1f}" '
                     f'r="6" fill="transparent" data-tip="{_esc(_tip)}"/>')
    s0 = norm[codes[0]]
    stepl = max(1, len(s0) // 8)
    for i in range(0, len(s0), stepl):
        xx = ml + pw * i / max(len(s0) - 1, 1)
        p.append(f'<text x="{xx:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#7c8496">{_esc(s0[i]["date"][5:])}</text>')
    lx = ml
    for c in codes:
        nm = names.get(c, c)
        p.append(f'<rect x="{lx}" y="{h-18}" width="10" height="10" '
                 f'fill="{cols[c]}" opacity="0.9"/>')
        p.append(f'<text x="{lx+14}" y="{h-9}" font-size="9.5" '
                 f'fill="#8b93a7">{_esc(nm)}</text>')
        lx += 26 + len(nm) * 11
    p.append("</svg>")
    return "".join(p)


def _etf_delta_table(dl_etf, names):
    """ETF 份额变动表：亿份 + 百分比。份额是存量 → 点位对比。"""
    if not dl_etf:
        return ""
    h = ['<table style="width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0">'
         '<tr style="color:#8b93a7;text-align:left">'
         '<th style="padding:5px 8px;font-weight:500">ETF</th>'
         '<th style="padding:5px 8px;font-weight:500">最新份额</th>'
         '<th style="padding:5px 8px;font-weight:500">近 1 周</th>'
         '<th style="padding:5px 8px;font-weight:500">近 1 月</th>'
         '<th style="padding:5px 8px;font-weight:500">近半年</th></tr>']
    for code in ("510300", "510050", "510500"):
        d = dl_etf.get(code) or {}
        a, b, c = d.get("7d"), d.get("30d"), d.get("180d")
        if not any((a, b, c)):
            continue
        cur = (a or b or c)["cur"]
        h.append(f'<tr style="border-top:1px solid #23272f">'
                 f'<td style="padding:6px 8px;color:#c8cee0">{_esc(names.get(code, code))}</td>'
                 f'<td style="padding:6px 8px"><b>{cur:,.2f} 亿份</b></td>'
                 f'<td style="padding:6px 8px">{_fmt_delta(a, " 亿份", dec=2)}</td>'
                 f'<td style="padding:6px 8px">{_fmt_delta(b, " 亿份", dec=2)}</td>'
                 f'<td style="padding:6px 8px">{_fmt_delta(c, " 亿份", dec=2)}</td></tr>')
    h.append("</table>")
    return "".join(h) if len(h) > 2 else ""


def _fmt_delta(d, unit="", pct_first=False, dec=2):
    """变动单元格：绝对值 + 百分比，涨红跌绿（中国市场习惯）。"""
    if not d:
        return '<span style="color:#6b7280">—</span>'
    dv, pc = d.get("delta"), d.get("pct")
    col = "#e05c5c" if (dv or 0) > 0 else ("#39c07c" if (dv or 0) < 0 else "#8b93a7")
    a = f'{dv:+,.{dec}f}{unit}'
    b = f'（{pc:+.1f}%）' if pc is not None else ""
    if pct_first and pc is not None:
        a, b = f'{pc:+.1f}%', f'（{dv:+,.{dec}f}{unit}）'
    return f'<span style="color:{col}">{a}<span style="font-size:11px">{b}</span></span>'


def _cn_delta_table(dl, sf):
    """周 / 月 / 半年 三口径变动对比表。

    ★ 流量与存量分开算（口径不同，混用会得出荒谬结论）：
      - DR007 是<b>价格点位</b> → 比最新 vs N 天前的点位
      - OMO 是<b>流量</b> → 比本区间投放总额 vs 上一区间总额
        （若对 OMO 也用点位法，会出现"较上周 -100%"，其实只是当天没操作）
    """
    rows = []
    d7, d30, d180 = (dl.get("dr007") or {}).get("7d"), \
                    (dl.get("dr007") or {}).get("30d"), \
                    (dl.get("dr007") or {}).get("180d")
    if any((d7, d30, d180)):
        cur = (d7 or d30 or d180)["cur"]
        rows.append(("DR007 资金价格", f'{cur:.4f}%', "点位对比",
                     _fmt_delta(d7, "pp", dec=4), _fmt_delta(d30, "pp", dec=4),
                     _fmt_delta(d180, "pp", dec=4)))
    o = dl.get("omo") or {}
    o7, o30, o180 = o.get("7d"), o.get("30d"), o.get("180d")
    if any((o7, o30, o180)):
        cur = f'{o7["cur"]:,.0f}亿' if o7 else "—"
        rows.append(("逆回购投放（区间合计）", cur, "区间总额对比",
                     _fmt_delta(o7, "亿", dec=0), _fmt_delta(o30, "亿", dec=0),
                     _fmt_delta(o180, "亿", dec=0)))
    m = dl.get("mlf") or {}
    m30, m90, m180 = m.get("30d"), m.get("90d"), m.get("180d")
    if any((m30, m90, m180)):
        cur = (m30 or m90 or m180)["cur"]
        rows.append(("MLF 月度操作", f'{cur:,.0f}亿', "操作量对比",
                     _fmt_delta(m30, "亿", dec=0), _fmt_delta(m90, "亿", dec=0),
                     _fmt_delta(m180, "亿", dec=0)))
    # ★ MLF 净投放（Chao 2026-08-25 要求）：投放量看不出真实流动性影响，
    #   投放 5000 亿而到期 6000 亿实为净回笼。到期量 = 12 个月前操作量（MLF 全为 1 年期）。
    mn = dl.get("mlf_net") or {}
    n30, n90, n180 = mn.get("30d"), mn.get("90d"), mn.get("180d")
    if any((n30, n90, n180)):
        cur = (n30 or n90 or n180)["cur"]
        col = "#e05c5c" if cur > 0 else ("#39c07c" if cur < 0 else "#8b93a7")
        lab = "净投放" if cur > 0 else ("净回笼" if cur < 0 else "持平")
        rows.append(("MLF <b>净投放</b>（投放−到期）",
                     f'<span style="color:{col}">{cur:+,.0f}亿（{lab}）</span>',
                     "净额对比",
                     _fmt_delta(n30, "亿", dec=0), _fmt_delta(n90, "亿", dec=0),
                     _fmt_delta(n180, "亿", dec=0)))
    # ★ A股两融余额（Chao 2026-08-25 指定）：SFISF 停发独立公告后的<b>日频</b>杠杆资金代理。
    #   存量指标 → 比点位差，不做区间求和。数据一直在 B2，此前从未渲染。
    mg = dl.get("margin") or {}
    g7, g30, g180 = mg.get("7d"), mg.get("30d"), mg.get("180d")
    if any((g7, g30, g180)):
        cur = (g7 or g30 or g180)["cur"]
        rows.append(("A股两融余额", f'{cur:,.4f}万亿', "杠杆资金·点位对比",
                     _fmt_delta(g7, "万亿", dec=4), _fmt_delta(g30, "万亿", dec=4),
                     _fmt_delta(g180, "万亿", dec=4)))
    if not rows:
        return ""
    h = ['<div class="part-title" style="font-size:14px;margin-top:10px">'
         '各指标同期变动 · 周 / 月 / 半年</div>',
         '<table class="cn-liq-tbl" style="width:100%;border-collapse:collapse;'
         'font-size:12.5px;margin:6px 0 4px">',
         '<tr style="color:#8b93a7;text-align:left">'
         '<th style="padding:5px 8px;font-weight:500">指标</th>'
         '<th style="padding:5px 8px;font-weight:500">最新</th>'
         '<th style="padding:5px 8px;font-weight:500">口径</th>'
         '<th style="padding:5px 8px;font-weight:500">近 1 周</th>'
         '<th style="padding:5px 8px;font-weight:500">近 1 月</th>'
         '<th style="padding:5px 8px;font-weight:500">近半年</th></tr>']
    for name, cur, kind, a, b, c in rows:
        # name/cur 允许内嵌 <b>/<span>（净投放行要染色），故不 _esc；
        # 内容均为本函数自造的常量或数字格式化结果，无外部输入，安全。
        h.append(f'<tr style="border-top:1px solid #23272f">'
                 f'<td style="padding:6px 8px;color:#c8cee0">{name}</td>'
                 f'<td style="padding:6px 8px"><b>{cur}</b></td>'
                 f'<td style="padding:6px 8px;color:#7c8496;font-size:11px">{_esc(kind)}</td>'
                 f'<td style="padding:6px 8px">{a}</td>'
                 f'<td style="padding:6px 8px">{b}</td>'
                 f'<td style="padding:6px 8px">{c}</td></tr>')
    h.append('</table>')
    h.append('<p class="cips-note">口径说明：DR007 是<b>价格</b>，比的是点位差（单位 pp）；'
             '逆回购是<b>流量</b>，比的是区间投放<b>总额</b>（本区间 vs 紧邻的上一等长区间）——'
             '两者不能用同一种算法，否则会出现「逆回购较上周 −100%」这种假信号'
             '（实际只是当天恰好没有操作）。MLF 为月频，「近 1 周」无意义故不计算。'
             '涨红跌绿，遵循中国市场习惯。</p>')
    return "".join(h)


def _cn_sfisf_html(sf):
    """SFISF 股市托底工具。

    ★ Chao 的用途是「短期看有没有剧增，观察托底股市」。
      当前官方只披露过 2 次操作（2024-10 / 2025-01），此后 600 天无新操作 ——
      <b>「没有剧增」本身就是答案</b>，必须显式说出来，而不是留个空图让人以为抓挂了。
    """
    if not sf:
        return ('<p class="empty">SFISF 暂无操作记录。'
                'PBoC 官网「证券、基金、保险公司互换便利」栏目未见公告。</p>')
    import datetime as _dt
    total = sum(x["v"] for x in sf)
    last = sf[-1]
    try:
        gap = (_dt.date.today() - _dt.date.fromisoformat(last["date"])).days
    except Exception:
        gap = None
    quiet = gap is not None and gap > 180

    h = [f'<div class="oil-meta">累计操作 <b>{len(sf)}</b> 次 · '
         f'合计 <b>{total:,.0f} 亿元</b> · '
         f'最近一次 <b>{last["date"]}</b>'
         f'{f"（距今 <b>{gap}</b> 天）" if gap is not None else ""}</div>']

    # 判定语——直接回答「有没有剧增」
    # ★ 2026-08-25 口径订正：不能说「未启用」。2025-05-07 央行公告已将 SFISF(5000亿)
    #   与股票回购增持再贷款(3000亿)<b>合并为 8000 亿总额度统一使用</b>，此后不再单独
    #   发布 SFISF 操作公告 —— 所以空窗期的准确含义是「无独立公告」，而非「央行没操作」。
    #   交叉印证：中证协 2026-04 披露「截至 2025 年末累计操作 1050 亿」，与本表 500+550
    #   完全一致，说明官网 2 条即为独立公告全量；同期货币政策委员会例会已不再提及该工具。
    if quiet:
        h.append(f'<div class="oil-meta" style="color:#c9a961">'
                 f'当前状态：<b>已无独立公告 {gap} 天</b>。'
                 f'2025-05-07 起央行将 SFISF 与股票回购增持再贷款'
                 f'<b>合并为 8000 亿元总额度统一使用</b>，此后不再单独披露 SFISF 操作，'
                 f'因此空窗<b>不等于「央行未操作」</b>，只能确认<b>没有新的独立公告</b>。'
                 f'若恢复单独公告，本板块次日自动反映。</div>')
    else:
        h.append('<div class="oil-meta" style="color:#e05c5c">'
                 '当前状态：<b>近期有独立公告操作</b> —— 需关注是否为托市信号。</div>')

    h.append('<table style="width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0">'
             '<tr style="color:#8b93a7;text-align:left">'
             '<th style="padding:5px 8px;font-weight:500">操作日</th>'
             '<th style="padding:5px 8px;font-weight:500">轮次</th>'
             '<th style="padding:5px 8px;font-weight:500">操作金额</th>'
             '<th style="padding:5px 8px;font-weight:500">中标费率</th></tr>')
    for i, x in enumerate(sf):
        rb = f'{x["rate_bp"]:.0f} bp' if x.get("rate_bp") is not None else "—"
        h.append(f'<tr style="border-top:1px solid #23272f">'
                 f'<td style="padding:6px 8px;color:#c8cee0">{_esc(x["date"])}</td>'
                 f'<td style="padding:6px 8px;color:#7c8496">第 {i+1} 次</td>'
                 f'<td style="padding:6px 8px"><b>{x["v"]:,.0f} 亿元</b></td>'
                 f'<td style="padding:6px 8px">{rb}</td></tr>')
    h.append('</table>')

    # 费率趋势解读（只在有 2 次以上时才说）
    rates = [x for x in sf if x.get("rate_bp") is not None]
    if len(rates) >= 2:
        a, b = rates[0]["rate_bp"], rates[-1]["rate_bp"]
        if b < a:
            h.append(f'<div class="oil-meta">中标费率 <b>{a:.0f}bp → {b:.0f}bp</b>：'
                     f'机构使用该工具的成本下降，等于央行<b>降低了入场门槛</b>，'
                     f'属宽松取向。费率与金额需合看——金额不变而费率大降同样是信号。</div>')

    h.append(f'<p class="cips-note">工具说明：SFISF（Securities, Funds and Insurance '
             f'companies Swap Facility）为央行 2024-10 创设，允许券商/基金/保险以'
             f'债券、股票 ETF、沪深300 成分股作抵押，从央行换入国债、央票等高流动性资产，'
             f'<b>换得资金只能投向股市</b>——是最直接的官方股市稳定工具，'
             f'首期额度 5,000 亿元。<br>'
             f'★<b>数据可得性</b>：本表为 PBoC 官网《SFISF 操作结果公告》全量'
             f'（专属栏目、上级聚合页、多种分页写法均已核查）。'
             f'该工具<b>按需启用、非定期发布</b>，因此没有「日频/月频」的更新节奏——'
             f'空窗期不代表抓取失败，而代表央行未动用。'
             f'本板块每日检查栏目，一有新公告即入库。</p>')
    return "".join(h)


def _cn_omo_svg(rows, w=940, h=250):
    """OMO 分品种堆叠柱状。隔夜/7天/其他三色。"""
    if not rows:
        return ""
    def tot(r):
        return sum(r.get(k) or 0 for k in ("on", "d7", "other"))
    vmax = max([tot(r) for r in rows] + [1])
    ml, mr, mt, mb = 62, 14, 16, 46
    pw, ph = w - ml - mr, h - mt - mb
    top = _nice_top(vmax * 1.08, 4)
    n = len(rows)
    step = pw / n
    bw = max(step * 0.7, 1.2)
    cols = {"on": "#7fa085", "d7": "#6b8fb5", "other": "#b58a6a"}
    labs = {"on": "隔夜", "d7": "7天", "other": "其他期限"}
    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for k in range(5):
        tv = top * k / 4
        yy = mt + ph - ph * tv / top
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.0f}</text>')
    p.append(f'<text x="{ml-52}" y="{mt-2}" font-size="10" fill="#8b93a7">亿元</text>')
    for i, r in enumerate(rows):
        x = ml + step * i + (step - bw) / 2
        acc = 0.0
        tip = [f'{r["date"]}']
        for k in ("on", "d7", "other"):
            v = r.get(k)
            if not v:
                continue
            hh = ph * v / top
            y = mt + ph - ph * acc / top - hh
            p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{max(hh,0.6):.1f}" fill="{cols[k]}" opacity="0.88"/>')
            acc += v
            tip.append(f'{labs[k]} {v:,.0f}亿')
        if r.get("rate") is not None:
            tip.append(f'利率 {r["rate"]}%')
        p.append(f'<rect x="{x:.1f}" y="{mt}" width="{bw:.1f}" height="{ph}" '
                 f'fill="transparent" data-tip="{_esc("｜".join(tip))}"/>')
    stepl = max(1, n // 8)
    for i in range(0, n, stepl):
        x = ml + step * (i + 0.5)
        p.append(f'<text x="{x:.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#7c8496">{_esc(rows[i]["date"][5:])}</text>')
    lx = ml
    for k in ("on", "d7", "other"):
        p.append(f'<rect x="{lx}" y="{h-18}" width="10" height="10" '
                 f'fill="{cols[k]}" opacity="0.88"/>')
        p.append(f'<text x="{lx+14}" y="{h-9}" font-size="9.5" '
                 f'fill="#8b93a7">{labs[k]}</text>')
        lx += 24 + len(labs[k]) * 11
    p.append("</svg>")
    return "".join(p)


def _cn_line_svg(rows, key, unit="", color="#6b8fb5", w=940, h=210, dec=2):
    """通用日频折线。"""
    vs = [r[key] for r in rows if r.get(key) is not None]
    if not vs:
        return ""
    ml, mr, mt, mb = 62, 14, 16, 40
    pw, ph = w - ml - mr, h - mt - mb
    lo, hi = min(vs), max(vs)
    pad = (hi - lo) * 0.15 or (abs(hi) * 0.02 or 0.01)
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1
    n = len(rows)
    def X(i):
        return ml + pw * i / max(n - 1, 1)
    def Y(v):
        return mt + ph - ph * (v - lo) / span
    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for k in range(5):
        tv = lo + span * k / 4
        yy = Y(tv)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.{dec}f}</text>')
    pts = " ".join(f'{X(i):.1f},{Y(r[key]):.1f}'
                   for i, r in enumerate(rows) if r.get(key) is not None)
    p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
             f'stroke-width="1.8"/>')
    for i, r in enumerate(rows):
        if r.get(key) is None:
            continue
        _tip = f'{r["date"]}｜{r[key]:,.{dec}f}{unit}'
        # ★ 规范 knowledge/frontend/data-dashboard-publishing.md §3「全图 hover tooltip」：
        #   折线整条无法逐点 hover → 每点叠透明 tip-hit 圈 + data-tip，走全站事件委托。
        #   不要用 SVG 原生 <title>（需悬停 1-2 秒才弹系统提示，样式也不统一）。
        p.append(f'<circle class="tip-hit" cx="{X(i):.1f}" cy="{Y(r[key]):.1f}" r="7" '
                 f'fill="transparent" data-tip="{_esc(_tip)}"/>')
    stepl = max(1, n // 8)
    for i in range(0, n, stepl):
        p.append(f'<text x="{X(i):.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#7c8496">{_esc(rows[i]["date"][5:])}</text>')
    p.append(f'<text x="{ml-52}" y="{mt-2}" font-size="10" '
             f'fill="#8b93a7">{_esc(unit)}</text>')
    p.append("</svg>")
    return "".join(p)


def _cn_bar_svg(rows, key, unit="", color="#6b8fb5", w=940, h=230):
    """通用月频柱状（点少，柱宽，标日期）。"""
    vs = [r[key] for r in rows if r.get(key) is not None]
    if not vs:
        return ""
    ml, mr, mt, mb = 62, 14, 20, 48
    pw, ph = w - ml - mr, h - mt - mb
    top = _nice_top(max(vs) * 1.12, 4)
    n = len(rows)
    step = pw / n
    bw = step * 0.6
    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for k in range(5):
        tv = top * k / 4
        yy = mt + ph - ph * tv / top
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.0f}</text>')
    p.append(f'<text x="{ml-52}" y="{mt-4}" font-size="10" fill="#8b93a7">{_esc(unit)}</text>')
    for i, r in enumerate(rows):
        v = r.get(key)
        if v is None:
            continue
        hh = ph * v / top
        x = ml + step * (i + 0.5) - bw / 2
        y = mt + ph - hh
        _tip = f'{r["date"]}｜{v:,.0f}{unit}'
        # MLF 图另带到期量与净投放（rows 里若有 matured/net 就一并显示）
        if r.get("matured") is not None:
            _tip += f'｜到期 {r["matured"]:,.0f}{unit}'
        if r.get("net") is not None:
            _lab = "净投放" if r["net"] > 0 else ("净回笼" if r["net"] < 0 else "持平")
            _tip += f'｜{_lab} {r["net"]:+,.0f}{unit}'
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                 f'height="{max(hh,0.6):.1f}" fill="{color}" opacity="0.88" '
                 f'data-tip="{_esc(_tip)}"/>')
        p.append(f'<text x="{ml+step*(i+0.5):.1f}" y="{y-4:.1f}" '
                 f'text-anchor="middle" font-size="8.5" fill="#aab3c5">'
                 f'{v:,.0f}</text>')
        p.append(f'<text x="{ml+step*(i+0.5):.1f}" y="{mt+ph+14:.1f}" '
                 f'text-anchor="middle" font-size="8.5" fill="#7c8496">'
                 f'{_esc(r["date"][2:7])}</text>')
    p.append("</svg>")
    return "".join(p)


def _cn_area_svg(rows, key, unit="", color="#a8646e", w=940, h=230):
    """存量退坡面积图（PSL 专用）。峰值与末值打标。"""
    vs = [r[key] for r in rows if r.get(key) is not None]
    if not vs:
        return ""
    ml, mr, mt, mb = 66, 14, 22, 46
    pw, ph = w - ml - mr, h - mt - mb
    top = _nice_top(max(vs) * 1.10, 4)
    n = len(rows)
    def X(i):
        return ml + pw * i / max(n - 1, 1)
    def Y(v):
        return mt + ph - ph * v / top
    p = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for k in range(5):
        tv = top * k / 4
        yy = Y(tv)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="#2a2f3a" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{ml-7}" y="{yy+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#8b93a7">{tv:,.0f}</text>')
    p.append(f'<text x="{ml-56}" y="{mt-4}" font-size="10" fill="#8b93a7">{_esc(unit)}</text>')
    line = " ".join(f'{X(i):.1f},{Y(r[key]):.1f}' for i, r in enumerate(rows))
    p.append(f'<polygon points="{ml},{mt+ph} {line} {ml+pw},{mt+ph}" '
             f'fill="{color}" opacity="0.18"/>')
    p.append(f'<polyline points="{line}" fill="none" stroke="{color}" '
             f'stroke-width="2"/>')
    peak_i = max(range(n), key=lambda i: rows[i][key])
    for i, r in enumerate(rows):
        _tip = f'{r["date"]}｜余额 {r[key]:,.0f}{unit}'
        if r.get("net") is not None:
            _tip += f'｜当月净额 {r["net"]:+,.0f}亿'
        p.append(f'<circle cx="{X(i):.1f}" cy="{Y(r[key]):.1f}" r="6" '
                 f'fill="transparent" data-tip="{_esc(_tip)}"/>')
    for i, tag in ((peak_i, "峰值"), (n - 1, "最新")):
        p.append(f'<circle cx="{X(i):.1f}" cy="{Y(rows[i][key]):.1f}" r="3.5" '
                 f'fill="{color}"/>')
        anc = "start" if i == peak_i and i < n - 1 else "end"
        dx = 6 if anc == "start" else -6
        p.append(f'<text x="{X(i)+dx:.1f}" y="{Y(rows[i][key])-8:.1f}" '
                 f'text-anchor="{anc}" font-size="9.5" fill="#c8cee0">'
                 f'{tag} {rows[i][key]:,.0f}</text>')
    stepl = max(1, n // 8)
    for i in range(0, n, stepl):
        p.append(f'<text x="{X(i):.1f}" y="{mt+ph+14:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#7c8496">{_esc(rows[i]["date"][2:7])}</text>')
    p.append("</svg>")
    return "".join(p)


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
    ohtml = (f'<div class="cc-osec"><div class="dg-sub">真实未偿总额（Fed Z.1 · 季度）'
             f'<span class="cc-oscope">全市场口径 · 非分评级</span></div>'
             f'<div class="cc-ogrid">{"".join(ocards)}</div>'
             f'<div class="cc-onote"><b>为什么这里没有 AAA/BBB/CCC 各自的总量？</b>'
             f'「按评级拆分的未偿余额」属 ICE / Bloomberg 指数成分数据，'
             f'<b>商业授权、无免费源</b>。已实测确认：SIFMA 公开统计（US Fixed Income Securities）'
             f'的 Corporates 亦<b>只有单一合计</b>（最新 1Q26 约 $11.74T），同样不分评级；'
             f'FRED 上带 TRIV 后缀的分评级序列是<b>总回报指数</b>（随价格波动的指数点位），'
             f'<b>不是</b>债券余额，用它冒充总量会得出完全错误的量级。'
             f'故本节总量只给<b>能验证的全市场口径</b>，分评级层面只提供收益率与 OAS。</div>'
             f'</div>') if ocards else ""

    return (
        f'<div class="cc-wrap">'
        f'<div class="dg-head">🏦 美国公司债 · 分评级 收益率 / 利差 / 总额'
        f'<span class="dg-asof">as of {_esc(asof)}{badge}</span></div>'
        f'{table}{divergence}{pct_html}'
        f'{ohtml}'
        f'<div class="dg-sub">期权调整利差 OAS 走势（近 3 年 · 纯信用风险溢价）</div>'
        f'{_corp_credit_svg(rs, "oas_series", unit=" %")}'
        f'<div class="dg-sub">有效收益率走势（近 3 年 · 含无风险利率）</div>'
        f'{_corp_credit_svg(rs, "yield_series", unit=" %")}'
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
    if not ci or not str(ci.get("status", "")).startswith("ok") or not ci.get("panels"):
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


def _ncb_spark(series, color="#8a9bb0", w=250, h=52):
    """五国央行总资产迷你走势线。series: [(YYYY-MM, val),...] 升序。"""
    if not series or len(series) < 2:
        return ""
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(series)
    pts = []
    for i, (_, v) in enumerate(series):
        x = 2 + (w - 4) * i / (n - 1)
        y = h - 4 - (h - 10) * (v - lo) / span
        pts.append(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}')
    return (f'<svg viewBox="0 0 {w} {h}" class="ncb-spark" preserveAspectRatio="none" '
            f'role="img"><path d="{"".join(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linejoin="round"/></svg>')


def _euro_ncb_html(ncb):
    """欧元区五国央行(德/意/荷/西/芬)资产负债表总资产子表。

    ★2026-09-09 新增(Chao 要求)。**必须与上方 Eurosystem 卡片、
      以及 TIC 持有美债表区分清楚**, 三者口径完全不同:
        - Eurosystem 卡片 = ECB 本部 + 20 家成员国央行的<b>合并</b>表
        - 本表 = 五国央行<b>各自</b>的总资产(可横向比较, 也能看出谁占大头)
        - TIC「德国持有美债 107.8B」= 德国<b>所有</b>外国持有人(保险/养老金/基金),
          与德国央行无关 —— 实测德国央行「对非欧元区外币债权」仅 €0.004B。
    """
    if not ncb:
        return ""
    ok = {k: v for k, v in ncb.items() if v.get("status") == "ok"}
    if not ok:
        sts = "、".join(f'{v.get("name","")}: {v.get("status","")}'
                       for v in ncb.values())
        return (f'<div class="ncb-wrap"><div class="ncb-title">欧元区五国央行 · 资产负债表总资产</div>'
                f'<div class="cust-chart-na">数据未就绪（{_esc(sts)}）</div></div>')

    unit = next(iter(ok.values())).get("unit", "$B")
    tot = sum(v["latest"][1] for v in ok.values())
    rows = []
    for cc, v in sorted(ok.items(), key=lambda z: -z[1]["latest"][1]):
        m, val = v["latest"]
        d, dp = v.get("delta"), v.get("delta_pct")
        up = (d is not None and d >= 0)
        cls = "g" if up else "r"
        arrow = "▲" if up else "▼"
        share = 100 * val / tot if tot else 0
        rows.append(
            f'<div class="ncb-row">'
            f'<span class="ncb-flag">{_esc(v.get("flag",""))}</span>'
            f'<span class="ncb-nm">{_esc(v.get("name",""))}</span>'
            f'<span class="ncb-val">{val:,.0f}<i>{_esc(unit)}</i></span>'
            f'<span class="ncb-share">{share:.1f}%</span>'
            f'<span class="ncb-spark-wrap">{_ncb_spark(v["series"])}</span>'
            f'<span class="ncb-dlt {cls}">{arrow} {d:+,.0f} ({dp:+.1f}%)</span>'
            f'<span class="ncb-asof">{_esc(m)}</span>'
            f'</div>')
    span_txt = ""
    f0 = next(iter(ok.values())).get("first")
    l0 = next(iter(ok.values())).get("latest")
    if f0 and l0:
        span_txt = f'{f0[0]} → {l0[0]}'

    return (
        f'<div class="ncb-wrap">'
        f'<div class="ncb-title">🏦 欧元区五国央行 · 各自资产负债表总资产'
        f'<span class="ncb-sub">德/意/荷/西/芬 · {_esc(span_txt)} · {_esc(unit)} · '
        f'变动为区间首末对比 · 与上方 Eurosystem 合并表<b>不是同一口径</b></span></div>'
        f'<div class="ncb-head">'
        f'<span class="ncb-flag"></span><span class="ncb-nm">央行</span>'
        f'<span class="ncb-val">总资产</span><span class="ncb-share">占五国</span>'
        f'<span class="ncb-spark-wrap">走势</span>'
        f'<span class="ncb-dlt">区间变动</span><span class="ncb-asof">数据月</span>'
        f'</div>'
        f'{"".join(rows)}'
        f'<div class="ncb-read"><b>怎么读：</b>这五家是欧元区里 TIC 当期表未单列的成员国'
        f'（德/意/荷/西/芬 在 Table 5 里被归入 All Other，故此前欧盟数据被迫退回年度存档表）。'
        f'此处给出它们央行<b>自己</b>的资产负债表规模，可横向比较谁在扩表／缩表。<br>'
        f'<b>⚠️ 三个口径务必分清：</b>'
        f'①上方 <b>Eurosystem</b> 卡片＝ECB 本部 ＋ 20 家成员国央行的<b>合并</b>表；'
        f'②本表＝五国央行<b>各自</b>的表；'
        f'③「持有美债」板块里的德国 / 法国等＝该国<b>所有外国持有人</b>'
        f'（保险／养老金／基金／企业），<b>与央行无关</b> —— '
        f'实测德国央行「对非欧元区外币债权」仅 <b>€0.004B</b>，'
        f'欧元区各国央行几乎不持有美债（外汇储备已大部分上缴 ECB 统一管理）。</div>'
        f'<div class="cu-prov" style="margin-top:12px">'
        f'<div class="cu-prov-title">🔗 数据溯源</div>'
        f'<div class="cu-prov-row"><span class="cu-prov-nm">五国央行总资产</span>'
        f'<span class="cu-prov-body">'
        f'<a href="https://data.ecb.europa.eu/data/datasets/BSI" target="_blank" '
        f'rel="noopener">ECB Data Portal · BSI 数据集</a>｜'
        f'序列 key：<code>BSI/M.{{国家码}}.N.N.T00.A.1.Z5.0000.Z01.E</code>'
        f'（国家码 DE/IT/NL/ES/FI）｜'
        f'官方标题：<code>Total assets of the NCB, Stocks</code>｜'
        f'原始单位百万欧元，按 FRED <code>DEXUSEU</code> 当日汇率折 $B'
        f'</span></div>'
        f'<div class="cu-prov-row"><span class="cu-prov-nm">Eurosystem 合并表</span>'
        f'<span class="cu-prov-body">'
        f'<a href="https://data.ecb.europa.eu/data/datasets/ILM" target="_blank" '
        f'rel="noopener">ECB Data Portal · ILM 数据集</a>｜'
        f'序列 key：<code>ILM/W.U2.C.*</code>（U2＝欧元区整体，C＝Eurosystem）｜周度'
        f'</span></div>'
        f'<div class="cu-prov-note">★ ECB BSI 的 NCB 部门只提供 <code>T00 总资产</code> 与 '
        f'<code>L40 发行债务证券</code> 两个科目，<b>没有黄金／证券等分项</b>。'
        f'德国的详细分项可另走 Bundesbank API（<code>BBBK11.D.TTA032</code> 等，'
        f'实测总资产 €2,271B／黄金 €381B），但五国口径将不一致，故此处统一只做总资产。'
        f'意/荷/西/芬 四国各自的 API 端点格式互不相同且实测不可直接取数，'
        f'故统一走 ECB 口径以保证可横向比较。</div>'
        f'</div>'
        f'</div>'
    )


def _cb_balance_html(cb, euro_ncb=None):
    """底部央行资产负债表板块(US/JP/CN/Eurosystem), 2x2 布局 + 欧元区五国央行子表。
    统一当天汇率折 $B 横向可比。

    ★2026-09-09: ECB 卡片已改名 Eurosystem —— 原名「欧洲央行 ECB」是错的,
      数据源 ILM/W.U2.C 是 ECB 本部 + 20 家成员国央行的合并表(实测 €5,912B),
      而德国央行一家就 €2,271B。见 external_data.fetch_ecb_balance_sheet docstring。
    """
    if not cb:
        return '<p class="empty">央行资产负债表数据未就绪。</p>'
    fx = cb.get("_fx")
    order = ["US", "JP", "CN", "ECB"]
    cards = "".join(_cb_one_view(cb.get(cc, {}), fx=fx) for cc in order if cc in cb)
    if not cards:
        return '<p class="empty">央行资产负债表数据未就绪。</p>'
    return cards + _euro_ncb_html(euro_ncb)


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
    /* 莫兰迪色板 (低饱和灰调)
       ★2026-09-07 Chao: "底色再暗一点，太凉了" → 整体降明度 + 加暖。
       原 bg #e8e4dd / card #f2efe9 偏冷灰且过亮；现往赭土暖调压一档，
       仍保持莫兰迪低饱和(不是深色主题)，文字对比度同步加深保证可读。 */
    --bg: #ddd6ca;          /* 暖赭灰(原 #e8e4dd，压暗+加暖) */
    --card: #eae4d9;        /* 暖米白(原 #f2efe9) */
    --card2: #dcd4c6;       /* 浅陶土(原 #e3ddd3) */
    --border: #c2b8a6;      /* 灰褐边(原 #cdc6ba，随底色加深) */
    --text: #423d34;        /* 深咖灰(原 #4a463f，略加深保对比) */
    --muted: #7d7568;       /* 灰褐(原 #8a8377) */
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
  /* 本日/本周/本月 三档 filter(Chao 2026-08-31) */
  .kp-tabs {{ display: flex; gap: 6px; margin: 0 0 12px; flex-wrap: wrap; }}
  .kp-btn {{ font-size: 12px; font-weight: 600; color: var(--muted); background: var(--card);
             border: 1px solid var(--border); padding: 5px 16px; border-radius: 6px;
             cursor: pointer; font-family: inherit; transition: all .15s; }}
  .kp-btn:hover {{ border-color: var(--dust-blue); color: var(--ink); }}
  .kp-btn.on {{ background: var(--dust-blue); border-color: var(--dust-blue); color: #fff; }}
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
  /* ★2026-09-08: 名录卡片的「查看全部 N 条言论」入口 */
  .kp-more {{ margin-top:8px; padding-top:7px; border-top:1px dashed var(--border);
             font-size:11.5px; color:var(--dust-blue); font-weight:600;
             opacity:.75; transition:opacity .15s; }}
  .kp-card.kol-drill:hover .kp-more {{ opacity:1; }}
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
  .sb-gray  {{ color: #6b6f78; background: rgba(120,125,135,.12); border: 1px solid rgba(120,125,135,.30); }}
  .sb-slow  {{ color: #4a5b78; background: rgba(74,91,120,.10); border: 1px solid rgba(74,91,120,.28); }}
  .cot-cad  {{ margin-top: 8px; font-size: 11px; color: var(--muted); line-height: 1.5; }}
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
  /* ★2026-09-09 欧元区拆分 / 官方vs私人 / 溯源(Chao 交易员视角改版) */
  .cu-eusplit {{ margin: 18px 0 4px; padding: 14px 16px 12px; background: #efe9dd;
    border: 1px solid #d8d0c3; border-radius: 10px; }}
  .cu-eusplit-title {{ font-size: 14.5px; font-weight: 700; color: #4a443c; margin-bottom: 4px; }}
  .cu-eusplit-sub {{ display: block; font-size: 11.5px; font-weight: 400; color: #8a8377; margin-top: 2px; }}
  .cu-eusplit-read {{ margin-top: 10px; font-size: 12.5px; line-height: 1.85; color: #5c554b;
    padding-top: 10px; border-top: 1px dashed #d8d0c3; }}
  .cu-op {{ margin: 18px 0 4px; padding: 14px 16px 12px; background: #eae4d9;
    border: 1px solid #d8d0c3; border-radius: 10px; }}
  .cu-op-title {{ font-size: 14.5px; font-weight: 700; color: #4a443c; }}
  .cu-op-sub {{ display: block; font-size: 11.5px; font-weight: 400; color: #8a8377; margin-top: 2px; }}
  .cu-op-kpis {{ display: flex; gap: 26px; flex-wrap: wrap; margin: 10px 0 6px; }}
  .cu-op-kpi {{ display: flex; flex-direction: column; gap: 1px; }}
  .cu-op-kpi .k-lab {{ font-size: 11px; color: #8a8377; }}
  .cu-op-kpi .k-val {{ font-size: 18px; font-weight: 700; color: #4a443c; }}
  .cu-op-kpi .k-dlt {{ font-size: 11.5px; }}
  .cu-op-kpi .k-dlt.r {{ color: #b5695c; }}
  .cu-op-kpi .k-dlt.g {{ color: #6f8a6b; }}
  .cu-op-leg {{ display: flex; gap: 20px; flex-wrap: wrap; font-size: 11.5px;
    color: #6b655c; margin: 4px 0 2px; }}
  .cu-op-leg i {{ display: inline-block; width: 18px; height: 3px; border-radius: 2px;
    margin-right: 5px; vertical-align: middle; }}
  .cu-op-read {{ margin-top: 8px; font-size: 12.5px; line-height: 1.85; color: #5c554b;
    padding-top: 9px; border-top: 1px dashed #d8d0c3; }}
  .cu-prov {{ margin: 16px 0 2px; padding: 12px 14px; background: #f2efe9;
    border: 1px dashed #cfc6b8; border-radius: 9px; }}
  .cu-prov-title {{ font-size: 13px; font-weight: 700; color: #4a443c; margin-bottom: 7px; }}
  .cu-prov-row {{ display: flex; gap: 10px; padding: 5px 0; font-size: 11.5px;
    line-height: 1.7; border-top: 1px solid #e6e0d4; }}
  .cu-prov-row:first-of-type {{ border-top: none; }}
  .cu-prov-nm {{ flex: 0 0 148px; font-weight: 600; color: #5c554b; }}
  .cu-prov-body {{ flex: 1; color: #7a736a; word-break: break-word; }}
  .cu-prov-body code {{ background: #e6e0d4; padding: 1px 5px; border-radius: 3px;
    font-size: 10.5px; color: #5c554b; }}
  .cu-prov-body a {{ color: #6b8fb5; text-decoration: none; border-bottom: 1px dotted #6b8fb5; }}
  .cu-prov-note {{ margin-top: 8px; padding-top: 8px; border-top: 1px solid #e6e0d4;
    font-size: 11px; line-height: 1.75; color: #8a8377; }}
  /* ★2026-09-09 欧元区五国央行子表 */
  .ncb-wrap {{ grid-column: 1 / -1; margin-top: 14px; padding: 14px 16px 12px;
    background: #efe9dd; border: 1px solid #d8d0c3; border-radius: 10px; }}

.lqc-chart{{width:100%;height:auto;display:block;margin:10px 0 6px}}
.lqc-leg{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:#6f665a;margin-bottom:10px}}
.lqc-leg span{{display:inline-flex;align-items:center;gap:5px}}
.lqc-leg i{{width:14px;height:3px;border-radius:2px;display:inline-block}}
.lqc-cards{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}}
.lqc-c{{flex:1 1 200px;background:#eae4d9;border-radius:9px;padding:11px 13px}}
.lqc-k{{font-size:12px;color:#7d7466;margin-bottom:3px}}
.lqc-v{{font-size:21px;font-weight:650;color:#3b352c;letter-spacing:-.3px}}
.lqc-v.good{{color:#3f6b52}}.lqc-v.warn{{color:#c9a227}}.lqc-v.bad{{color:#b5533c}}
.lqc-s{{font-size:11.5px;color:#8a8070;margin-top:3px;line-height:1.45}}
.lqc-hint{{font-size:12px;color:#7d7466;line-height:1.6;margin:6px 0 10px}}
.lqc-det{{margin-top:9px;font-size:12.5px}}
.lqc-det summary{{cursor:pointer;color:#6b6253;padding:5px 0}}
.lqc-tb{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}}
.lqc-tb th{{text-align:left;color:#7d7466;font-weight:600;padding:5px 8px;
  border-bottom:1px solid #d8d2c6}}
.lqc-tb td{{padding:5px 8px;border-bottom:1px solid #e6e0d5}}
.lqc-d{{color:#6b6253;white-space:nowrap}}
.lqc-tag{{font-size:11px;padding:1.5px 7px;border-radius:9px;white-space:nowrap}}
.lqc-tag.pm{{background:#e8dcc9;color:#7a5c3c}}
.lqc-tag.eq{{background:#dbe0ea;color:#465575}}
.lqc-tag.both{{background:#efd6d2;color:#8e3b30}}
.lqc-prov{{margin:6px 0 0 0;padding-left:18px;color:#6f665a;line-height:1.75;font-size:12px}}

/* ── 中国模式断代 ── */
.crs-wrap{{margin:8px 0 4px}}
.crs-verdict{{padding:14px 18px;border-radius:10px;margin-bottom:14px;border-left:4px solid}}
.crs-cached{{background:#f4e9e6;border-left:3px solid #a3705f;padding:9px 12px;border-radius:5px;font-size:11.5px;color:#7a5f52;line-height:1.8;margin-bottom:10px}}
.crs-cached b{{color:#8e3b30}}
.crs-verdict.bad{{background:#f4e9e6;border-color:#a3705f}}
.crs-verdict.warn{{background:#f3efe2;border-color:#b09a5f}}
.crs-verdict.ok{{background:#e9efe8;border-color:#6f8f6a}}
.crs-verdict-t{{font-size:17px;font-weight:600;color:#3d3a36;margin-bottom:6px}}
.crs-verdict-s{{font-size:13px;color:#5f5a54;line-height:1.75}}
.crs-intro{{font-size:13px;color:#5f5a54;line-height:1.85;margin:10px 0 16px}}
.crs-table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:6px}}
.crs-table th{{text-align:left;padding:7px 10px;color:#7a736b;font-weight:500;border-bottom:1px solid #ddd6ca;font-size:12px}}
.crs-table td{{padding:7px 10px;border-bottom:1px solid #eee9e0}}
.crs-grp td{{background:#f0ebe1;font-weight:600;color:#4a453f;font-size:12px;letter-spacing:.4px}}
.crs-n{{color:#4a453f}}
.crs-v{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;text-align:right;width:92px}}
.crs-v.neg{{color:#a3705f}}
.crs-v.pos{{color:#5f7f5a}}
.crs-b{{color:#8d857b;font-size:12px;width:80px}}
.crs-pk{{color:#8d857b;font-size:12px}}
.crs-note{{font-size:12px;color:#8d857b;margin:6px 0 18px}}
.crs-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(184px,1fr));gap:11px;margin-bottom:16px}}
.crs-card{{background:#eae4d9;border-radius:9px;padding:11px 13px}}
.crs-card-n{{font-size:12px;color:#6b645c;margin-bottom:5px}}
.crs-card-v{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:21px;font-weight:600;color:#3d3a36}}
.crs-u{{font-size:12px;margin-left:2px;color:#7a736b}}
.crs-card-m{{font-size:11px;color:#8d857b;margin-top:4px}}
.crs-card-r{{font-size:11px;color:#9a938a;margin-top:3px}}
.crs-mom{{margin-left:5px;font-family:ui-monospace,monospace}}
.crs-mom.neg{{color:#a3705f}}
.crs-mom.pos{{color:#5f7f5a}}
.crs-det{{margin:10px 0;font-size:13px}}
.crs-det summary{{cursor:pointer;color:#6b645c;padding:6px 0}}
.crs-una li,.crs-src li{{margin:8px 0;line-height:1.7}}
.crs-why{{font-size:12px;color:#8d857b;line-height:1.75;margin-top:4px}}
.crs-err{{background:#f4e9e6;border-left:3px solid #a3705f;padding:9px 12px;font-size:12px;color:#7a5f52;border-radius:5px;margin-top:10px}}

/* ── WRS Walmart 衰退信号 ── */
.tfs-wrap{{margin:6px 0}}
.tfs-grid{{stroke:#eceae5;stroke-width:1}}
.tfs-zero{{stroke:#9fc5e8;stroke-width:1;stroke-dasharray:4 3}}
.tfs-yl{{font-size:10px;fill:#8a837a;text-anchor:end}}
.tfs-yr{{font-size:10px;fill:#5b8fc0;text-anchor:start}}
.tfs-xt{{font-size:10px;fill:#8a837a;text-anchor:middle}}
.tfs-legend{{font-size:11px;color:#6b645a;margin:6px 0 2px;display:flex;gap:14px;flex-wrap:wrap;align-items:center}}
.tfs-legend i{{display:inline-block;width:18px;height:0;border-top:2px solid;margin-right:4px;vertical-align:middle}}
.tfs-legend .l1{{border-color:#1f3a68}}.tfs-legend .l2{{border-color:#5b9bd5}}.tfs-legend .l3{{border-color:#9fc5e8;border-top-style:dashed}}
.sgr-wrap{{margin:6px 0}}
.sgr-title{{font-size:15px;font-weight:700;color:#4a443c;margin:14px 0 6px}}
.sgr-stat{{display:flex;gap:22px;flex-wrap:wrap;font-size:12px;color:#6b645a;margin-bottom:4px}}
.sgr-stat b{{font-size:15px;color:#3d372f;margin:0 3px}}.sgr-stat i{{font-style:normal;color:#9a9288;font-size:11px}}
.frt-bar{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}}
.frt-bar button{{font-size:11.5px;padding:3px 9px;border:1px solid #cfc7ba;background:#f6f2ec;color:#5a534a;border-radius:12px;cursor:pointer}}
.frt-bar button.on{{background:#1f3a68;border-color:#1f3a68;color:#fff}}
.frt-opt{{margin-top:2px}} .frt-sep{{width:14px}}
.frt-chart{{min-height:120px}}
.sgr-chart{{width:100%;height:auto;display:block}}
.sgr-grid{{stroke:#eceae5;stroke-width:1}}
.sgr-med{{stroke:#a8a29a;stroke-width:1;stroke-dasharray:4 3}}
.sgr-medt{{font-size:10px;fill:#8a837a}}
.sgr-yt{{font-size:10px;fill:#8a837a;text-anchor:end}}
.sgr-xt{{font-size:10px;fill:#8a837a;text-anchor:middle}}
.sgr-lab{{font-size:10px;fill:#4a443c}}
.rpl-wrap{{margin:6px 0}}
.rpl-note{{font-size:12px;color:#6b5a3a;background:#faf3df;border:1px solid #ecdca8;border-radius:6px;padding:8px 11px;margin:2px 6px 10px;line-height:1.65}}
.rpl-g{{margin:0 6px 14px;border:1px solid #e3ddd0;border-radius:8px;background:#fffdf8;padding:8px 10px}}
.rpl-h{{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:6px}}
.rpl-h b{{font-size:14px;color:#2e2a24}}
.rpl-org{{font-size:11.5px;color:#7a7266}}
.rpl-n{{font-size:11.5px;color:#8a5a2a;margin-left:auto}}
.rpl-tb{{width:100%;border-collapse:collapse;font-size:12px}}
.rpl-tb th{{text-align:left;font-weight:600;color:#7a7266;padding:4px 6px;border-bottom:1px solid #e3ddd0}}
.rpl-tb td{{padding:5px 6px;border-bottom:1px solid #f0ebe0;vertical-align:top}}
.rpl-d{{white-space:nowrap;color:#5a534a;width:78px}}
.rpl-t{{color:#2e2a24;line-height:1.5}}
.rpl-sum{{color:#7a7266;font-size:11.5px;margin-top:2px;line-height:1.5}}
.rpl-more{{margin-top:2px}}
.rpl-more>summary{{cursor:pointer;list-style:none;display:block}}
.rpl-more>summary::-webkit-details-marker{{display:none}}
.rpl-more .rpl-sum{{display:inline;margin-top:0}}
.rpl-open{{display:inline-block;margin-left:6px;font-size:11px;color:#8a5a2a;border-bottom:1px dashed #b98c5a;white-space:nowrap}}
.rpl-more[open] .rpl-open{{display:none}}
.rpl-full{{color:#4a443b;font-size:12px;line-height:1.65;margin-top:4px;padding:6px 8px;background:#f6f1e6;border-radius:4px;white-space:pre-wrap;word-break:break-word;max-height:280px;overflow-y:auto}}
.rpl-fullnote{{font-size:10.5px;color:#9a9185;margin-top:3px}}
.rpl-s{{width:210px;font-size:11.5px}}
.rpl-s a{{color:#1f3a68;text-decoration:none;margin-right:2px}}
.rpl-s a:hover{{text-decoration:underline}}
.rpl-pf{{color:#7d7566;font-size:10.5px;margin:0 8px 0 3px}}
.rpl-none{{font-size:12px;color:#8a8478;margin:2px 0 4px}}
.rpl-dt{{margin-top:6px;font-size:12px;color:#5f584c}}
.rpl-dt summary{{cursor:pointer;user-select:none}}
.sfc-note{{font-size:12px;color:#6b5a3a;background:#faf3df;border:1px solid #ecdca8;border-radius:6px;padding:7px 10px;margin:2px 6px 8px;line-height:1.6}}
.sfc-ctl{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 6px 6px;min-height:28px}}
.sfc-ctl button{{font-size:11.5px;padding:3px 9px;border:1px solid #cfc7ba;background:#f6f2ec;color:#5a534a;border-radius:12px;cursor:pointer}}
.sfc-ctl button.on{{background:#1f3a68;border-color:#1f3a68;color:#fff}}
.sfc-lab{{font-size:11.5px;color:#8a837a}}.sfc-sep{{width:12px}}
.sfc-chk{{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#5a534a;cursor:pointer;user-select:none}}
.sfc-chk i{{display:inline-block;width:14px;height:3px;border-radius:2px}}
.sfc-chart{{height:320px;margin:0 6px}}.sfc-chart svg{{width:100%;height:320px;display:block}}
.sfc-pin{{height:38px;margin:2px 6px 6px;padding:6px 10px;box-sizing:border-box;font-size:12px;color:#4a443c;background:#f6f2ec;border-radius:6px;overflow:hidden;line-height:1.5}}
.sfc-tabbox{{height:300px;overflow-y:auto;margin:0 6px;border-top:1px solid #eceae5}}
.sfc-tab{{width:100%;border-collapse:collapse;font-size:12px}}.sfc-tab th{{position:sticky;top:0;background:#fbfaf7;text-align:right;padding:5px 8px;color:#8a837a;font-weight:500;border-bottom:1px solid #eceae5}}
.sfc-tab th:first-child,.sfc-tab td:first-child{{text-align:left}}.sfc-tab td{{text-align:right;padding:4px 8px;border-bottom:1px solid #f1eee8;color:#4a443c}}
.sfc-foot{{font-size:11.5px;color:#8a837a;line-height:1.7;margin:8px 6px 2px}}
.sfc-g{{stroke:#eceae5;stroke-width:1}}.sfc-yt{{font-size:10px;fill:#8a837a;text-anchor:end}}.sfc-xt{{font-size:10px;fill:#8a837a;text-anchor:middle}}
.sgz-ctl{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0 8px;min-height:30px;padding:0 6px}}.sgz-p,.sgz-st{{padding:0 6px;box-sizing:border-box}}
.sgz-ctl button{{font-size:11.5px;padding:3px 9px;border:1px solid #cfc7ba;background:#f6f2ec;color:#5a534a;border-radius:12px;cursor:pointer}}
.sgz-ctl button.on{{background:#1f3a68;border-color:#1f3a68;color:#fff}}
.sgz-lab{{font-size:11.5px;color:#8a837a}}.sgz-sep{{width:12px}}
.sgz-ctl input[type=month]{{font-size:11.5px;padding:2px 4px;border:1px solid #cfc7ba;border-radius:6px;background:#fbfaf7;color:#4a443c;width:118px}}
.sgz-chk{{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#5a534a;cursor:pointer;user-select:none}}
.sgz-chk i{{display:inline-block;width:14px;height:3px;border-radius:2px}}
#sgz-panels{{height:640px;contain:layout paint;overflow:hidden}}
.sgz-p{{height:300px}}.sgz-p svg{{width:100%;height:230px;display:block}}
.sgz-st{{display:flex;gap:22px;flex-wrap:wrap;font-size:12px;color:#6b645a;height:34px;overflow:hidden}}
.sgz-st b{{font-size:15px;color:#3d372f;margin:0 3px}}.sgz-st i{{font-style:normal;color:#9a9288;font-size:11px}}
.aic-row{{display:flex;gap:12px;flex-wrap:wrap}}.aic-card{{flex:1;min-width:150px;background:#faf7f0;padding:10px 12px;border-radius:4px}}.aic-n{{font-size:12px;color:#6b645a}}.aic-v{{font-size:26px;font-weight:600;color:#3d372f;line-height:1.3}}.aic-v small{{font-size:12px;font-weight:400;color:#8a837a}}.aic-d{{font-size:11px;color:#8a837a}}.aic-d i{{font-style:normal;margin-left:6px}}.aic-svg .sgr-yt,.aic-svg .sgr-xt{{font-size:11.5px;fill:#5a534a}}.aic-tab{{width:100%;border-collapse:collapse;font-size:12px}}.aic-tab th{{text-align:left;color:#6b645a;border-bottom:1px solid #d9d3c8;padding:4px 6px}}.aic-tab td{{border-bottom:1px dashed #e6e0d4;padding:4px 6px;color:#3d372f;vertical-align:top}}
.jpy-facts{{list-style:none;margin:6px 0 8px;padding:0}}.jpy-facts li{{padding:6px 2px;border-bottom:1px dashed #e0d9cc;font-size:13.5px;line-height:1.7;color:#3d372f}}.jpy-facts li b{{display:inline-block;min-width:44px;color:#6b645a;font-weight:600}}
.sgr-foot{{font-size:11px;color:#8a837a;margin-top:10px;line-height:1.6}}
.sgr-warn{{font-size:12px;color:#8e3b30;margin:0 0 6px}}
.btcg-n{{font-size:9px;font-weight:700;text-anchor:middle}}
.btcg-ctl{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0 6px;min-height:30px}}
.btcg-ctl button{{font-size:11.5px;padding:3px 9px;border:1px solid #cfc7ba;background:#f6f2ec;color:#5a534a;border-radius:12px;cursor:pointer}}
.btcg-ctl button.on{{background:#1f3a68;border-color:#1f3a68;color:#fff}}
.btcg-lab{{font-size:11.5px;color:#8a837a}}.btcg-sep{{width:12px}}
.btcg-ctl input[type=month]{{font-size:11.5px;padding:2px 4px;border:1px solid #cfc7ba;border-radius:6px;background:#fbfaf7;color:#4a443c;width:118px}}
.btcg-chk{{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#5a534a;cursor:pointer;user-select:none}}
.btcg-chk i{{display:inline-block;width:14px;height:3px;border-radius:2px}}
.btcg-chart{{height:380px;position:relative;contain:layout paint}}
.btcg-chart svg{{width:100%;height:100%;display:block}}
.btcg-pin{{height:38px;line-height:19px;font-size:12px;color:#6b645a;background:#f6f2ec;border-radius:6px;padding:0 10px;margin:4px 0 6px;overflow:hidden;display:flex;align-items:center}}
.btcg-pin b{{color:#3d372f}}
.btcg-tabbox{{height:360px;overflow-y:auto;overscroll-behavior:contain;border-top:1px solid #eceae5}}.btcg-tab thead th{{position:sticky;top:0;background:#fbfaf7}}
.btcg-legend{{font-size:11px;color:#8a837a;margin:2px 0 6px}}.btcg-legend i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 10px;vertical-align:-1px}}
.btcg-tab{{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}}
.btcg-tab th{{text-align:left;color:#8a837a;font-weight:600;padding:4px 6px;border-bottom:1px solid #e5e1da}}
.btcg-tab td{{padding:6px;border-bottom:1px solid #f0ede7;vertical-align:top;color:#4a443c}}
.btcg-no{{font-weight:700;width:26px}}.btcg-tab td:nth-child(2){{white-space:nowrap;width:84px}}.btcg-tab td:nth-child(4){{white-space:nowrap}}.btcg-wrap{{padding:0 6px}}.btcg-d{{color:#8a837a;font-size:11px}}.btcg-tab a{{color:#1f3a68;text-decoration:none}}

.wrs-wrap{{margin:6px 0}}
.wrs-head{{margin-bottom:10px}}
.wrs-title{{font-size:15px;font-weight:700;color:#4a443c;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.wrs-lvl{{font-size:11px;font-weight:600;padding:2px 9px;border-radius:9px}}
.wrs-lvl.red{{background:#efd6d2;color:#8e3b30}}
.wrs-lvl.amber{{background:#f0e6cc;color:#87652a}}
.wrs-lvl.green{{background:#dde7dc;color:#41613c}}
.wrs-formula{{font-size:12px;color:#7a736b;margin-top:5px}}
.wrs-proxy{{background:#f3efe2;border-left:3px solid #b09a5f;padding:10px 13px;border-radius:5px;
  font-size:12px;color:#6b5f45;line-height:1.85;margin:10px 0 12px}}
.wrs-stat{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:10px}}
.wrs-stat span{{flex:1 1 168px;background:#eae4d9;border-radius:8px;padding:9px 12px;
  font-size:12px;color:#6b645c;display:flex;flex-direction:column;gap:2px}}
.wrs-stat b{{font-size:17px;color:#3d3a36;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.wrs-stat i{{font-style:normal;font-size:11px;color:#9a938a}}
.wrs-stat .up{{color:#a3705f}}
.wrs-stat .down{{color:#5f7f5a}}
.wrs-chart{{width:100%;height:auto;display:block;margin:4px 0}}
.wrs-grid{{stroke:#ddd6ca;stroke-width:.7}}
.wrs-line{{fill:none;stroke:#8a6f5c;stroke-width:1.7}}
.wrs-now{{fill:#8e3b30}}
.wrs-peak{{fill:none;stroke:#8a6f5c;stroke-width:1.6}}
.wrs-ytick{{font-size:10px;fill:#8d857b;text-anchor:end;font-family:ui-monospace,monospace}}
.wrs-xtick{{font-size:10px;fill:#9a938a;text-anchor:middle}}
.wrs-foot{{font-size:11.5px;color:#8d857b;line-height:1.8;margin-top:6px}}

/* ── 国债微观结构 Exhibit 3/4 ── */
.um-wrap{{margin:6px 0}}
.um-sec{{margin-bottom:22px}}
.um-h{{font-size:14.5px;font-weight:700;color:#4a443c;display:flex;align-items:center;
  gap:9px;flex-wrap:wrap;margin-bottom:5px}}
.um-badge{{font-size:10.5px;font-weight:600;padding:2px 9px;border-radius:9px;letter-spacing:.3px}}
.um-badge.real{{background:#dde7dc;color:#41613c}}
.um-badge.proxy{{background:#f0e6cc;color:#87652a}}
.um-src{{font-size:11.5px;color:#9a938a;margin-bottom:8px}}
.um-caliber{{background:#f3efe2;border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px;
  font-size:12px;color:#6b5f45;line-height:1.8;margin-bottom:11px}}
.um-proxy{{background:#f4ece4;border-left:3px solid #a3855f;padding:10px 13px;border-radius:5px;
  font-size:12px;color:#6b5a45;line-height:1.85;margin-bottom:12px}}
.um-excl{{color:#8d857b;font-size:11.5px}}
.um-table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:8px}}
.um-table th{{text-align:right;padding:6px 10px;color:#7a736b;font-weight:500;font-size:11.5px;
  border-bottom:1px solid #ddd6ca}}
.um-table th:first-child{{text-align:left}}
.um-table th i{{font-style:normal;font-size:10px;color:#9a938a}}
.um-table td{{padding:6px 10px;border-bottom:1px solid #eee9e0}}
.um-n{{color:#4a453f}}
.um-v{{text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.um-v.pos{{color:#5f7f5a}}
.um-v.neg{{color:#a3705f}}
.um-tot td{{background:#f0ebe1;font-weight:600}}
.um-star{{font-size:10.5px;color:#87652a;background:#f0e6cc;padding:1px 7px;border-radius:8px;margin-left:6px}}
.um-cap{{font-size:11.5px;color:#8d857b;margin:10px 0 2px}}
.um-chart{{width:100%;height:auto;display:block}}
.um-grid{{stroke:#e2dcd1;stroke-width:.7}}
.um-line{{fill:none;stroke-width:1.6}}
.um-yt{{font-size:9.5px;fill:#9a938a;text-anchor:end;font-family:ui-monospace,monospace}}
.um-xt{{font-size:9.5px;fill:#9a938a;text-anchor:middle}}
.um-cost-one{{margin-bottom:16px}}
.um-cost-h{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;font-size:13px;color:#4a453f}}
.um-cost-v{{font-family:ui-monospace,monospace;font-size:17px;font-weight:600;color:#3d3a36}}
.um-pct{{font-size:11px;color:#87652a;background:#f0e6cc;padding:1px 8px;border-radius:8px}}
.um-cost-d{{font-size:11.5px;color:#8d857b;margin:3px 0 4px}}

/* ── 美元指数 vs 黄金 + 事件标注 ── */
.dxg-wrap{{margin:6px 0}}
.dxg-stat{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:10px}}
.dxg-stat span{{flex:1 1 172px;background:#eae4d9;border-radius:8px;padding:9px 12px;
  font-size:12px;color:#6b645c;display:flex;flex-direction:column;gap:2px}}
.dxg-stat b{{font-size:18px;color:#3d3a36;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.dxg-stat i{{font-style:normal;font-size:11px;color:#9a938a}}
.dxg-legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;margin-bottom:4px}}
.dxg-lg.gold{{color:#b08a3e}}
.dxg-lg.dxy{{color:#5b7d94}}
.dxg-lg.hi{{color:#8e3b30}}
.dxg-lg.cal{{color:#5f7f5a}}
.dxg-chart{{width:100%;height:auto;display:block}}
.dxg-grid{{stroke:#e2dcd1;stroke-width:.7}}
.dxg-gold{{fill:none;stroke:#b08a3e;stroke-width:1.8}}
.dxg-dxy{{fill:none;stroke:#5b7d94;stroke-width:1.5}}
.dxg-yl{{font-size:9.5px;fill:#b08a3e;text-anchor:end;font-family:ui-monospace,monospace}}
.dxg-yr{{font-size:9.5px;fill:#5b7d94;text-anchor:start;font-family:ui-monospace,monospace}}
.dxg-xt{{font-size:9.5px;fill:#9a938a;text-anchor:middle}}
.dxg-vl{{stroke-width:.8;stroke-dasharray:2.5 2.5;opacity:.55}}
.dxg-vl.hi{{stroke:#8e3b30}}
.dxg-vl.cal{{stroke:#5f7f5a}}
.dxg-vl.med{{stroke:#a3855f}}
.dxg-dot.hi{{fill:#8e3b30}}
.dxg-dot.cal{{fill:#5f7f5a}}
.dxg-dot.med{{fill:#a3855f}}
.dxg-num{{font-size:9px;text-anchor:middle;font-weight:700}}
.dxg-num.hi{{fill:#8e3b30}}
.dxg-num.cal{{fill:#5f7f5a}}
.dxg-num.med{{fill:#a3855f}}
.dxg-method{{font-size:11.5px;color:#8d857b;line-height:1.85;margin:10px 0 6px;
  background:#f3efe2;border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px}}
.dxg-stale{{background:#f4e9e6;border-left:3px solid #a3705f;padding:8px 12px;
  font-size:12px;color:#7a5f52;border-radius:5px;margin-bottom:8px}}
.dxg-unc{{font-size:11.5px;color:#8d857b;margin-bottom:8px;line-height:1.8}}
.dxg-det{{margin-top:8px;font-size:13px}}
.dxg-det summary{{cursor:pointer;color:#6b645c;padding:6px 0}}
.dxg-table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:4px}}
.dxg-table td{{padding:8px 9px;border-bottom:1px solid #eee9e0;vertical-align:top}}
.dxg-i{{width:24px;font-weight:700;font-family:ui-monospace,monospace;text-align:right}}
.dxg-i.hi{{color:#8e3b30}}
.dxg-i.cal{{color:#5f7f5a}}
.dxg-i.med{{color:#a3855f}}
.dxg-d{{width:104px;color:#6b645c;font-family:ui-monospace,monospace;font-size:11.5px}}
.dxg-bg{{display:block;margin-top:3px;font-size:10px;padding:1px 6px;border-radius:7px;
  width:fit-content;font-family:system-ui,sans-serif}}
.dxg-bg.hi{{background:#dde7dc;color:#41613c}}
.dxg-bg.cal{{background:#dbe4ea;color:#3f5a6b}}
.dxg-bg.med{{background:#f0e6cc;color:#87652a}}
.dxg-e b{{color:#3d3a36}}
.dxg-chg{{margin-left:8px;font-size:11px;font-family:ui-monospace,monospace}}
.dxg-chg.up{{color:#5f7f5a}}
.dxg-chg.down{{color:#a3705f}}
.dxg-dt{{color:#7a736b;line-height:1.75;margin-top:3px;font-size:11.5px}}
.dxg-vn{{color:#8e3b30;font-size:11px;margin-top:3px}}
.dxg-s{{width:96px;font-size:11.5px}}
.dxg-s a{{color:#5b7d94}}
.dxg-nolink{{color:#b3aba0}}

/* ── 黄金 ETF 分地区资金流 (WGC) ── */
.gef-wrap{{margin:6px 0}}
.gef-src{{font-size:11.5px;color:#7a736b;line-height:1.85;background:#eef1ea;
  border-left:3px solid #8d9c86;padding:9px 12px;border-radius:5px;margin-bottom:10px}}
.gef-src a{{color:#5b7d94}}
.gef-cards{{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:10px}}
.gef-card{{flex:1 1 202px;background:#eae4d9;border-radius:8px;padding:9px 12px}}
.gef-lab{{font-size:11.5px;color:#8d857b;margin-bottom:2px}}
.gef-tot{{font-size:20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-bottom:5px}}
.gef-tot small{{font-size:11px;color:#9a938a}}
.gef-tot.in,.gef-table td.in,.gef-r b.in{{color:#5f7f5a}}
.gef-tot.out,.gef-table td.out,.gef-r b.out{{color:#a3705f}}
.gef-rs{{display:flex;flex-direction:column;gap:2px}}
.gef-r{{font-size:11px;color:#7a736b;display:flex;align-items:center;gap:5px}}
.gef-r i{{width:8px;height:8px;border-radius:2px;display:inline-block;flex:none}}
.gef-r b{{font-family:ui-monospace,monospace;margin-left:auto}}
.gef-legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:#6b645c;margin-bottom:4px}}
.gef-legend span{{display:flex;align-items:center;gap:5px}}
.gef-legend i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.gef-pxi{{background:#b08a3e;height:2px!important;width:16px!important;border-radius:0!important}}
.gef-chart{{width:100%;height:auto;display:block}}
.gef-grid{{stroke:#e2dcd1;stroke-width:.7}}
.gef-zero{{stroke:#b3aba0;stroke-width:1.1}}
.gef-px{{fill:none;stroke:#b08a3e;stroke-width:1.7}}
.gef-yl{{font-size:9.5px;fill:#8d857b;text-anchor:end;font-family:ui-monospace,monospace}}
.gef-yr{{font-size:9.5px;fill:#b08a3e;text-anchor:start;font-family:ui-monospace,monospace}}
.gef-xt{{font-size:9.5px;fill:#9a938a;text-anchor:middle}}
.gef-unit{{font-size:10px;fill:#9a938a;text-anchor:end}}
.gef-ctx{{font-size:11.5px;color:#8d857b;margin:8px 0;line-height:1.8}}
.gef-silver{{font-size:11.5px;color:#7a5f52;line-height:1.85;background:#f4efe6;
  border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px;margin:8px 0}}
.gef-silver b{{color:#6b5340}}
.gef-det{{margin-top:8px;font-size:13px}}
.gef-det summary{{cursor:pointer;color:#6b645c;padding:6px 0}}
.gef-table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}}
.gef-table th{{text-align:right;padding:6px 8px;border-bottom:1px solid #ded7cb;
  color:#8d857b;font-weight:600;font-size:11px}}
.gef-table th:first-child,.gef-table td:first-child{{text-align:left}}
.gef-table td{{text-align:right;padding:5px 8px;border-bottom:1px solid #eee9e0;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.gef-tt{{font-weight:700}}
.gef-px-c{{color:#b08a3e}}

/* ── 贵金属期权波动率(ATM IV 期限结构 + 25D 偏斜) ── */
.pv-wrap{{margin:6px 0}}
.pv-cards{{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:10px}}
.pv-card{{flex:1 1 210px;background:#eae4d9;border-radius:8px;padding:10px 12px}}
.pv-ct{{display:flex;align-items:center;gap:6px;font-weight:600;color:#3d3a36;
  font-size:13px;margin-bottom:6px}}
.pv-ct i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.pv-ct small{{margin-left:auto;font-weight:400;color:#9a938a;font-size:11px}}
.pv-row{{display:flex;justify-content:space-between;font-size:11.5px;color:#7a736b;
  padding:2px 0}}
.pv-row b{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#3d3a36}}
.pv-row b.inv{{color:#a3705f}}
.pv-row b.nor{{color:#5f7f5a}}
.pv-row b.bull{{color:#5f7f5a}}
.pv-row b.bear{{color:#a3705f}}
.pv-sub{{font-size:10.5px;color:#9a938a;margin-top:5px;
  border-top:1px solid #ded7cb;padding-top:4px}}
.pv-warn{{font-size:10.5px;color:#8e3b30;margin-top:3px}}
.pv-legend{{display:flex;gap:14px;font-size:11.5px;color:#6b645c;margin-bottom:2px}}
.pv-legend span{{display:flex;align-items:center;gap:5px}}
.pv-legend i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.pv-block{{margin:10px 0}}
.pv-t{{font-size:12px;color:#6b645c;margin-bottom:2px}}
.pv-chart{{width:100%;height:auto;display:block}}
.pv-grid{{stroke:#e2dcd1;stroke-width:.7}}
.pv-zero{{stroke:#b3aba0;stroke-width:1.1;stroke-dasharray:3 3}}
.pv-ln{{fill:none;stroke-width:1.9}}
.pv-yl{{font-size:9.5px;fill:#8d857b;text-anchor:end;font-family:ui-monospace,monospace}}
.pv-xt{{font-size:10.5px;fill:#6b645c;text-anchor:middle}}
.pv-unit{{font-size:10px;fill:#9a938a;text-anchor:end}}
.pv-method{{font-size:11.5px;color:#8d857b;line-height:1.85;margin-top:8px;
  background:#f3efe2;border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px}}
.pv-hist{{font-size:11.5px;color:#7a5f52;line-height:1.85;margin-top:8px;
  background:#f4efe6;border-left:3px solid #a3855f;padding:9px 12px;border-radius:5px}}
.pv-hist b{{color:#6b5340}}

.mmr-one{{margin:14px 0 22px}}.mmr-t{{font-weight:600;font-size:14px;color:#3d372f;margin:4px 0 8px}}.mmr-ex{{font-size:11px;color:#8a837a;font-weight:400;margin-left:8px}}.mmr-stat{{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 8px}}.mmr-stat span{{flex:1;min-width:170px;background:#faf7f0;padding:8px 11px 12px;border-radius:4px}}.mmr-stat i{{display:block;font-style:normal;font-size:11.5px;color:#6b645a}}.mmr-stat b{{font-size:20px;color:#3d372f;font-weight:600}}.mmr-stat em{{display:block;font-style:normal;font-size:11px;color:#8a837a;margin-top:2px}}.mmr-ctl{{margin:4px 0 6px;font-size:12px}}.mmr-lab{{color:#6b645a;margin-right:6px}}.mmr-b,.mmr-r{{border:1px solid #d9d3c8;background:#fff;color:#3d372f;font-size:12px;padding:2px 10px;border-radius:3px;cursor:pointer;margin-right:4px}}.mmr-on{{background:#3d372f;color:#fff;border-color:#3d372f}}.mmr-chart{{width:100%;display:block}}
.h8-ban{{background:#f6e8b8;border-radius:4px;padding:9px 13px;margin:8px 0;font-size:13px;line-height:1.7;color:#3d372f}}.h8-u{{display:block;font-size:11px;color:#6b645a;margin-top:2px}}.h8-stat{{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 8px}}.h8-stat span{{flex:1;min-width:190px;background:#faf7f0;padding:8px 11px 11px;border-radius:4px}}.h8-stat i{{display:block;font-style:normal;font-size:11.5px;color:#6b645a}}.h8-stat b{{font-size:20px;color:#3d372f;font-weight:600}}.h8-stat em{{display:block;font-style:normal;font-size:11px;color:#8a837a;margin-top:2px}}.h8-ctl{{margin:4px 0 6px;font-size:12px}}.h8-lab{{color:#6b645a;margin-right:6px}}.h8-b,.h8-r{{border:1px solid #d9d3c8;background:#fff;color:#3d372f;font-size:12px;padding:2px 10px;border-radius:3px;cursor:pointer;margin-right:4px}}.h8-on{{background:#3d372f;color:#fff;border-color:#3d372f}}.h8-chart{{width:100%;display:block}}.h8-tab{{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}}.h8-tab th{{background:#efe9dd;color:#4a443c;padding:4px 6px;border:1px solid #e0d9cb;text-align:center}}.h8-tab td{{padding:4px 7px;border:1px solid #ece6d9;color:#3d372f}}.h8-tab td.r{{text-align:right;font-variant-numeric:tabular-nums}}.h8-m2{{font-size:12px;color:#4a443c;margin-top:6px}}
.hf-stat{{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0}}.hf-stat span{{flex:1 1 0;min-width:150px;background:#faf7f0;padding:8px 11px 11px;border-radius:4px}}.hf-stat i{{display:block;font-style:normal;font-size:11.5px;color:#6b645a}}.hf-stat b{{font-size:20px;color:#3d372f;font-weight:600}}.hf-stat em{{display:block;font-style:normal;font-size:11px;color:#8a837a;margin-top:2px}}.hf-chart{{width:100%;display:block}}.hf-tab{{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}}.hf-tab th{{background:#efe9dd;color:#4a443c;padding:4px 7px;border:1px solid #e0d9cb;text-align:right}}.hf-tab th:first-child{{text-align:left;white-space:nowrap}}.hf-tab td{{padding:4px 7px;border:1px solid #ece6d9;color:#3d372f}}.hf-tab td.r{{text-align:right;font-variant-numeric:tabular-nums}}.hf-u{{font-size:11px;color:#8a837a;margin-top:4px}}
/* ── COMEX 期货期权持仓 ── */
.cxo-wrap{{margin:6px 0}}
.cxo-notiv{{font-size:11.5px;color:#7a5f52;line-height:1.85;margin-bottom:10px;
  background:#f4efe6;border-left:3px solid #a3855f;padding:9px 12px;border-radius:5px}}
.cxo-notiv b{{color:#8e3b30}}
.cxo-cards{{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:10px}}
.cxo-card{{flex:1 1 260px;background:#eae4d9;border-radius:8px;padding:10px 12px}}
.cxo-ct{{display:flex;align-items:center;gap:6px;font-weight:600;color:#3d3a36;
  font-size:13px;margin-bottom:6px}}
.cxo-ct i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.cxo-ct small{{margin-left:auto;font-weight:400;color:#9a938a;font-size:11px}}
.cxo-row{{display:flex;justify-content:space-between;font-size:11.5px;color:#7a736b;padding:2px 0}}
.cxo-row b{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#3d3a36}}
.cxo-row b.bull{{color:#5f7f5a}}
.cxo-row b.bear{{color:#a3705f}}
.cxo-sub{{font-size:10.5px;color:#9a938a;margin-top:5px;border-top:1px solid #ded7cb;padding-top:4px}}
.cxo-warn{{font-size:10.5px;color:#8e3b30;margin-top:3px}}
.cxo-block{{margin:10px 0}}
.cxo-t{{font-size:12px;color:#6b645c;margin-bottom:2px}}
.cxo-lgs{{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:11px;color:#6b645c;margin:2px 0 4px}}
.cxo-lg i{{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}}
.cxo-chart{{width:100%;height:auto;display:block}}
.cxo-g{{stroke:#e2dcd1;stroke-width:.7}}
.cxo-z{{stroke:#b3aba0;stroke-width:1.1}}
.cxo-yl{{font-size:9.5px;fill:#8d857b;text-anchor:end;font-family:ui-monospace,monospace}}
.cxo-xt{{font-size:10px;fill:#6b645c;text-anchor:middle}}
.cxo-method{{font-size:11.5px;color:#8d857b;line-height:1.85;margin-top:8px;
  background:#f3efe2;border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px}}

/* ── 全球货币供应 ── */
.gms-wrap{{margin:6px 0}}
.gms-caliber{{font-size:11.5px;color:#7a5f52;line-height:1.85;margin-bottom:10px;
  background:#f4efe6;border-left:3px solid #a3855f;padding:9px 12px;border-radius:5px}}
.gms-caliber b{{color:#8e3b30}}
.gms-cards{{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:8px}}
.gms-card{{flex:1 1 170px;background:#eae4d9;border-radius:8px;padding:10px 12px}}
.gms-k{{font-size:11px;color:#8d857b;margin-bottom:3px}}
.gms-v{{font-size:20px;font-weight:600;color:#3d3a36;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.gms-v small{{font-size:11px;font-weight:400;color:#9a938a;margin-left:3px}}
.gms-v.up{{color:#8e3b30}}
.gms-v.dn{{color:#5f7f5a}}
.gms-s{{font-size:10.5px;color:#9a938a;margin-top:2px}}
.gms-parts{{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:#6b645c;
  margin-bottom:8px}}
.gms-p{{display:flex;align-items:center;gap:5px}}
.gms-p i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.gms-p b{{font-family:ui-monospace,monospace;color:#3d3a36;margin-left:2px}}
.gms-tail{{font-size:11px;color:#7a5f52;background:#f4e9e6;border-left:3px solid #a3705f;
  padding:7px 11px;border-radius:5px;margin-bottom:8px;line-height:1.8}}
.gms-block{{margin:10px 0}}
.gms-t{{font-size:12px;color:#6b645c;margin-bottom:2px;line-height:1.7}}
.gms-chart{{width:100%;height:auto;display:block}}
.gms-g{{stroke:#e2dcd1;stroke-width:.7}}
.gms-vg{{stroke:#ece6dc;stroke-width:.6}}
.gms-z{{stroke:#b3aba0;stroke-width:1.1}}
.gms-ln{{fill:none;stroke:#8e3b30;stroke-width:1.8}}
.gms-yl{{font-size:9.5px;fill:#8d857b;text-anchor:end;font-family:ui-monospace,monospace}}
.gms-xt{{font-size:10px;fill:#6b645c;text-anchor:middle}}
.gms-covbox{{background:#f3efe2;border-radius:6px;padding:9px 12px;margin-top:10px}}
.gms-covt{{font-size:11.5px;color:#6b645c;margin-bottom:5px;font-weight:600}}
.gms-cov-row{{display:flex;gap:10px;font-size:11px;color:#7a736b;padding:2px 0;
  align-items:baseline}}
.gms-cov-p{{font-family:ui-monospace,monospace;color:#3d3a36;min-width:140px}}
.gms-cov-n{{color:#8e3b30;min-width:38px}}
.gms-cov-c{{color:#8d857b}}
.gms-gap{{font-size:11.5px;color:#7a5f52;line-height:1.85;margin-top:8px;
  background:#f4efe6;border-left:3px solid #a3855f;padding:9px 12px;border-radius:5px}}
.gms-gap b{{color:#8e3b30}}
.gms-acc{{font-size:11.5px;color:#8d857b;line-height:1.85;margin-top:8px;
  background:#f3efe2;border-left:3px solid #b09a5f;padding:9px 12px;border-radius:5px}}

  .cmm-chart {{ width: 100%; height: auto; display: block; margin: 4px 0 2px; }}
  .cmm-one {{ margin: 16px 0 20px; }}
  .cmm-t {{ font-size: 14.5px; font-weight: 700; color: #4a443c; margin-bottom: 7px;
    display: flex; align-items: center; gap: 8px; }}
  .cmm-ex {{ font-size: 10.5px; font-weight: 600; color: #7a6f5d; background: #e6dfd2;
    padding: 2px 8px; border-radius: 9px; letter-spacing: .02em; }}
  .cmm-stat {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 6px; }}
  .cmm-stat span {{ flex: 1 1 190px; background: #eae4d9; border-radius: 8px;
    padding: 8px 11px; display: flex; flex-direction: column; gap: 1px; }}
  .cmm-stat i {{ font-style: normal; font-size: 11.5px; color: #7d7466; }}
  .cmm-stat b {{ font-size: 17px; font-weight: 650; color: #3b352c; letter-spacing: -.2px; }}
  .cmm-stat em {{ font-style: normal; font-size: 11px; color: #8a8070; line-height: 1.45; }}
  .cmm-leg {{ display: flex; flex-wrap: wrap; gap: 15px; font-size: 12px;
    color: #6f665a; margin: 4px 0 2px; }}
  .cmm-leg span {{ display: inline-flex; align-items: center; gap: 5px; }}
  .cmm-leg i {{ width: 14px; height: 3px; border-radius: 2px; display: inline-block; }}
  .ncb-title {{ font-size: 14.5px; font-weight: 700; color: #4a443c; margin-bottom: 9px; }}
  .ncb-sub {{ display: block; font-size: 11.5px; font-weight: 400; color: #8a8377; margin-top: 3px; }}
  .ncb-head, .ncb-row {{ display: grid;
    grid-template-columns: 26px minmax(150px,1.4fr) 108px 62px minmax(120px,1fr) 132px 74px;
    align-items: center; gap: 8px; padding: 6px 2px; font-size: 12.5px; }}
  .ncb-head {{ font-size: 10.5px; color: #8a8377; border-bottom: 1px solid #d8d0c3;
    padding-bottom: 5px; }}
  .ncb-row {{ border-bottom: 1px solid #e6e0d4; }}
  .ncb-row:last-of-type {{ border-bottom: none; }}
  .ncb-nm {{ color: #4a443c; font-weight: 600; }}
  .ncb-val {{ text-align: right; font-weight: 700; font-size: 15px; color: #4a443c; }}
  .ncb-val i {{ font-style: normal; font-size: 10px; color: #8a8377; margin-left: 2px; }}
  .ncb-share {{ text-align: right; font-size: 11.5px; color: #8a8377; }}
  .ncb-spark-wrap {{ display: block; height: 30px; }}
  .ncb-spark {{ width: 100%; height: 30px; display: block; }}
  .ncb-dlt {{ text-align: right; font-size: 11.5px; }}
  .ncb-dlt.g {{ color: #6f8a6b; }}
  .ncb-dlt.r {{ color: #b5695c; }}
  .ncb-asof {{ text-align: right; font-size: 10.5px; color: #8a8377; }}
  .ncb-read {{ margin-top: 10px; padding-top: 9px; border-top: 1px dashed #d8d0c3;
    font-size: 12.5px; line-height: 1.85; color: #5c554b; }}
  @media (max-width: 860px) {{
    .ncb-head {{ display: none; }}
    .ncb-row {{ grid-template-columns: 24px 1fr 96px; row-gap: 2px; }}
    .ncb-spark-wrap, .ncb-share {{ display: none; }}
  }}
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
  /* 多行 tooltip(流动性危机图: 四条线数值 + 当天事件说明) —— 仅内容含 <br> 时启用, 不影响其他图 */
  #chart-tip.multi {{ white-space: normal; max-width: 380px; font-weight: 400; }}
  #chart-tip.multi .tip-v {{ font-weight: 500; font-size: 12px; line-height: 1.55; }}
  #chart-tip .tip-d {{ color: #c9c2b2; font-size: 11px; }}
  #chart-tip .tip-v {{ font-weight: 700; font-size: 13px; }}
  /* 数据元素 hover 视觉反馈 */
  [data-tip] {{ cursor: crosshair; }}
  rect[data-tip]:hover {{ opacity: 1 !important; filter: brightness(1.12); }}
  circle.tip-hit {{ fill: transparent; stroke: none; }}
  circle.tip-hit:hover {{ fill: rgba(192,138,125,0.18); }}
  /* ★2026-08-22 需求A: COMEX issue/stop 图的时间窗口 filter(当周/月/三月/全部) */
  .cis-tabs {{ display: flex; gap: 6px; margin: 6px 0 8px; flex-wrap: wrap; }}
  .cis-tab {{
    font: 600 11.5px/1 -apple-system,PingFang SC,sans-serif;
    padding: 5px 11px; border-radius: 5px; cursor: pointer;
    border: 1px solid var(--border); background: var(--card); color: var(--muted);
    transition: all .12s;
  }}
  .cis-tab:hover {{ border-color: var(--clay); color: #8a3a2c; }}
  .cis-tab.cis-on {{ background: var(--clay); border-color: var(--clay); color: #fff; }}
  .cis-n {{ font-size: 9.5px; opacity: .72; margin-left: 5px; font-weight: 500; }}
  .cis-pane {{ display: none; }}
  .cis-pane.cis-on {{ display: block; }}
  /* ★2026-08-22 需求B: COMEX 三金属 top10 交货/接货方榜单 */
  .tf-metal {{ margin: 0 0 22px; }}
  .tf-mt {{ font-size: 13.5px; font-weight: 700; color: var(--ink); margin-bottom: 6px; }}
  .tf-tabs {{ display: flex; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }}
  .tf-tab {{
    font: 600 11px/1 -apple-system,PingFang SC,sans-serif; padding: 4px 10px;
    border-radius: 5px; cursor: pointer; border: 1px solid var(--border);
    background: var(--card); color: var(--muted); transition: all .12s;
  }}
  .tf-tab:hover {{ border-color: var(--clay); color: #8a3a2c; }}
  .tf-tab.tf-on {{ background: var(--clay); border-color: var(--clay); color: #fff; }}
  .tf-pane {{ display: none; }}
  .tf-pane.tf-on {{ display: block; }}
  .tf-sub {{ font-size: 10.5px; color: var(--muted); margin-bottom: 7px; }}
  .tf-cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  @media (max-width: 860px) {{ .tf-cols {{ grid-template-columns: 1fr; }} }}
  .tf-ct {{ font-size: 11.5px; font-weight: 700; margin-bottom: 5px; padding-bottom: 3px;
            border-bottom: 1px solid var(--border); }}
  .tf-ci {{ color: #d64545; }}
  .tf-cs {{ color: #2e9e5b; }}
  .tf-row {{ display: grid; grid-template-columns: 18px 132px 1fr 58px 42px;
             align-items: center; gap: 6px; padding: 2.5px 0; font-size: 11px; }}
  .tf-rk {{ color: var(--muted); font-size: 10px; text-align: right; }}
  .tf-nm {{ color: var(--ink); font-weight: 600; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap; }}
  .tf-nb {{ font-size: 8.5px; color: var(--muted); border: 1px solid var(--border);
            border-radius: 3px; padding: 0 3px; margin-left: 4px; font-weight: 500; }}
  .tf-bar {{ background: rgba(0,0,0,0.045); border-radius: 2px; height: 9px;
             display: block; overflow: hidden; }}
  .tf-bar i {{ display: block; height: 100%; opacity: .8; border-radius: 2px; }}
  .tf-lot {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--ink); }}
  .tf-sh {{ text-align: right; font-size: 10px; color: var(--muted);
            font-variant-numeric: tabular-nums; }}
  .tf-none {{ font-size: 11px; color: var(--muted); padding: 10px 0; font-style: italic; }}
  /* ★2026-08-22 BIS 季度切换 filter(近 4 期 Quarterly Review) */
  .bis-tabs {{ display: flex; gap: 6px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }}
  .bis-tab {{
    font: 600 11.5px/1 var(--mono),-apple-system,PingFang SC,sans-serif;
    padding: 5px 12px; border-radius: 5px; cursor: pointer;
    border: 1px solid var(--border); background: var(--card); color: var(--muted);
    transition: all .12s;
  }}
  .bis-tab:hover {{ border-color: var(--dust-blue); color: var(--text); }}
  .bis-tab.bis-on {{ background: var(--dust-blue); border-color: var(--dust-blue); color: #fff; }}
  .bis-span {{ font-size: 10px; color: var(--muted); margin-left: 4px; }}
  .bis-pane {{ display: none; }}
  .bis-pane.bis-on {{ display: block; }}
  /* ★2026-08-22 COMEX 交割席位 阵营背景说明 */
  .tf-lots {{ font-size: 9.5px; color: var(--muted); margin-left: 3px; font-weight: 400; }}
  .fw-wrap {{ margin-top: 10px; }}
  .fw-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
              gap: 10px; margin: 10px 0 8px; }}
  .fw-grp {{ background: rgba(140,155,175,.06); border-radius: 6px; padding: 9px 11px; }}
  .fw-hd {{ display: flex; align-items: center; gap: 6px; border-left: 3px solid var(--dust-blue);
            padding-left: 7px; margin-bottom: 6px; font-size: 12px; }}
  .fw-cnt {{ margin-left: auto; font-size: 9.5px; color: var(--muted); font-family: var(--mono); }}
  .fw-chips {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }}
  .fw-chip {{ font-family: var(--mono); font-size: 9.5px; background: var(--card);
              border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; color: var(--text); }}
  .fw-desc {{ font-size: 11px; line-height: 1.65; color: var(--muted); }}
  .fw-note {{ font-size: 10.5px; line-height: 1.6; color: var(--muted);
              border-top: 1px dashed var(--border); padding-top: 7px; }}
  .cc-oscope {{ font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 6px; }}
  .cc-onote {{ font-size: 10.5px; line-height: 1.65; color: var(--muted);
               background: rgba(140,155,175,.07); border-radius: 5px;
               padding: 8px 10px; margin-top: 8px; }}
  /* ★2026-08-22 COMEX 账户类型 C(客户)/H(自营)/U(未知) */
  .tf-org {{ display: inline-flex; gap: 3px; margin-left: 5px; vertical-align: middle; }}
  .tf-oh, .tf-oc, .tf-ou {{ font-family: var(--mono); font-size: 8.5px; font-weight: 700;
    padding: 0 3px; border-radius: 2px; line-height: 1.5; cursor: help; }}
  .tf-oh {{ background: rgba(122,90,140,.20); color: #7d5a8c; }}
  .tf-oc {{ background: rgba(140,155,175,.20); color: #6b7d8a; }}
  .tf-ou {{ background: rgba(160,150,130,.18); color: #8a8578; }}
  .tfo-row {{ display: flex; align-items: center; gap: 6px; margin: 3px 0; font-size: 10px; }}
  .tfo-lbl {{ width: 26px; color: var(--muted); flex: none; }}
  .tfo-bar {{ flex: 1; height: 7px; border-radius: 3px; overflow: hidden;
              display: flex; background: rgba(140,155,175,.10); }}
  .tfo-bar i {{ display: block; height: 100%; }}
  .tfo-h {{ background: #7d5a8c; }}
  .tfo-c {{ background: #8fa3b5; }}
  .tfo-u {{ background: #c4bcae; }}
  .tfo-txt {{ font-family: var(--mono); font-size: 9.5px; color: var(--muted);
              width: 130px; text-align: right; flex: none; }}
  /* ★2026-08-22 KOL 深度摘要(展开层四段式) */
  .kd-deep {{ margin-bottom: 6px; }}
  .kd-seg {{ display: flex; gap: 8px; margin-bottom: 5px; line-height: 1.75; }}
  .kd-seg-k {{ flex: none; width: 62px; font-size: 11px; font-weight: 700;
               color: var(--dust-blue); text-align: right; }}
  .kd-seg-k::before {{ content: "▸ "; }}
  .kd-seg-v {{ flex: 1; font-size: 11.5px; color: var(--text); }}
  .kd-deep-badge {{ flex: none; font-size: 8.5px; font-weight: 700; margin-left: 5px;
                    background: rgba(122,90,140,.18); color: #7d5a8c;
                    border-radius: 2px; padding: 0 3px; line-height: 1.6; }}
  /* ★2026-08-23 KOL 全量名录档案卡(13 维度, 按领域分色) */
  .kr-head {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 6px; }}
  .kr-total {{ font-size: 12px; color: var(--text); }}
  .kr-total b {{ font-family: var(--mono); font-size: 15px; color: var(--dust-rose); }}
  .kr-chips {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 9px; }}
  .kr-chip {{ font-size: 10px; padding: 1px 7px; border: 1px solid; border-radius: 9px; }}
  .kr-chip b {{ font-family: var(--mono); }}
  .kr-gap {{ font-size: 11px; color: #8a6d3b; background: rgba(200,170,110,.13);
             border-radius: 5px; padding: 7px 10px; margin: 8px 0; }}
  .kp-grp {{ margin-top: 16px; }}
  .kp-gt {{ color: #fff; font-size: 12.5px; font-weight: 700; padding: 5px 11px;
            border-radius: 5px 5px 0 0; display: flex; justify-content: space-between; }}
  .kp-gn {{ font-family: var(--mono); font-weight: 400; opacity: .85; }}
  .kp-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
              gap: 9px; padding: 9px; background: rgba(140,155,175,.06);
              border-radius: 0 0 5px 5px; }}
  .kp-card {{ background: var(--card); border-radius: 5px; padding: 9px 11px;
              border-left: 3px solid; box-shadow: 0 1px 2px rgba(0,0,0,.05); }}
  .kp-hd {{ display: flex; align-items: baseline; gap: 6px; margin-bottom: 6px;
            padding-bottom: 5px; border-bottom: 1px dashed var(--border); }}
  .kp-num {{ font-family: var(--mono); font-size: 10px; color: var(--muted); }}
  .kp-nm {{ font-size: 13px; font-weight: 700; color: var(--text); flex: 1; }}
  .kp-dead {{ font-size: 9px; font-weight: 700; color: #fff; background: #b0574f;
              border-radius: 3px; padding: 1px 5px; }}
  .kp-r {{ display: flex; gap: 6px; font-size: 10.5px; line-height: 1.6; margin-bottom: 3px; }}
  .kp-k {{ flex: none; width: 62px; color: var(--muted); text-align: right; }}
  .kp-v {{ flex: 1; color: var(--text); }}
  .kp-q {{ margin-top: 5px; padding-top: 5px; border-top: 1px dashed var(--border); }}
  .kp-q .kp-v {{ font-style: italic; color: #6b5f52; }}
  .kp-todo {{ font-size: 10px; color: var(--muted); font-style: italic;
              background: rgba(140,155,175,.10); border-radius: 4px;
              padding: 5px 7px; margin-top: 5px; }}
  /* ★2026-08-24 央行货币互换 */
  .cbs-wrap {{ margin: 10px 0; }}
  .cbs-bars {{ display: flex; align-items: flex-end; gap: 2px; height: 96px;
               background: rgba(140,155,175,.06); border-radius: 5px; padding: 6px 8px; }}
  .cbs-b {{ flex: 1; min-width: 3px; background: linear-gradient(180deg,#8ea1ad,#6b8494);
            border-radius: 2px 2px 0 0; }}
  .cbs-b:hover {{ background: var(--dust-rose); }}
  .cbs-axis {{ display: flex; justify-content: space-between; font-size: 9.5px;
               color: var(--muted); margin-top: 4px; font-family: var(--mono); }}
  .cbs-grid {{ display: grid; grid-template-columns: repeat(auto-fill,minmax(200px,1fr));
               gap: 6px; margin: 10px 0; }}
  .cbs-r {{ display: flex; align-items: baseline; gap: 6px; font-size: 11px;
            background: rgba(140,155,175,.08); border-radius: 4px; padding: 5px 9px; }}
  .cbs-n {{ flex: 1; color: var(--text); }}
  .cbs-v {{ font-family: var(--mono); font-weight: 700; color: var(--dust-rose); }}
  .cbs-c {{ font-size: 9.5px; color: var(--muted); }}
  .cbs-tb {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 8px; }}
  .cbs-tb th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 10px;
                border-bottom: 1px solid var(--border); padding: 4px 6px; }}
  .cbs-tb td {{ padding: 4px 6px; border-bottom: 1px dashed var(--border); }}
  .cbs-d {{ font-family: var(--mono); color: var(--muted); }}
  .cbs-num {{ font-family: var(--mono); text-align: right; }}
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
  <div class="part-title part-title-flex"><span><span class="part-num">＋</span>本周 KOL 观点全景 · 按模块 (多空方向卡片)</span><span class="freq-badge freq-daily" style="margin-left:0">每日更新</span><a class="kol-dash-btn" href="https://chao-kol-dashboard.pages.dev/" target="_blank" rel="noopener">📊 打开 KOL Dashboard →</a></div>
  <div class="card">{kol_views}</div>

  <!-- ═══ 附一：本周 KOL 状态变化(模块化, Eco 独立每日快照周对比) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>本周 KOL 状态变化 · 按模块 (态度转向 call-out)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{kol_changes}</div>

  <!-- ═══ 附一·二：周期与术数预测派 —— 2026-08-22 Chao 决定停用 ═══
       玄学/术数/占星派已迁往 Forecast-Checker 项目;
       技术分析/周期理论派归回上方常规 KOL 板块。整段不再渲染。
  <div class="part-title" id="sec-cycle-kol"><span class="part-num">＋</span>周期与术数预测 · 独立板块 (周期理论 / 金融占星 / 易经术数)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{cycle_kol}</div>
  -->

  <!-- ═══ 附五：KOL 全量名录档案卡(Chao 2026-08-23 要求, 13 维度) ═══ -->
  <!-- ★2026-08-31(Chao「按 menu 顺序改」)：原在页面最底部(DOM #48)，但属「KOL 观点」组，
       与组内其余 section(#9-11) 相隔 37 个 section → 滚到底时高亮突然窜回菜单顶部。
       现紧随 KOL 板块，使 DOM 顺序 === 菜单顺序。
       ⚠ 必须放在上面 cycle_kol 注释块【之外】，否则整段不渲染。 -->
  <div class="part-title" id="sec-kol-roster"><span class="part-num">＋</span>KOL 全量名录 · 13 维度档案卡 (编号/领域/在世/头衔/成就/荣誉/书籍/当年言论 · 名册镜像 Notion·新增自动入表)<span class="freq-badge freq-daily">随名册更新</span></div>
  <div class="card">{kol_roster}</div>

  <!-- ═══ 附二：流动性要点(联动 Economic Dashboard) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>流动性要点 · 央行/国债<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card liq-wrap">{liquidity}</div>

  <!-- ═══ 附三：四大央行资产负债表 (US/JP/CN/ECB, 2x2) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>四大央行资产负债表 · 每日更新 (US/JP/CN/Eurosystem · 2x2 + 欧元区五国央行 · 当天汇率统一折$B)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="bs-grid">{cb_balance}</div>

  <!-- ═══ 附三·一半：BIS 国际清算银行报告 (央行的央行 · 摘要+独立页) ═══ -->
  <div class="part-title part-title-flex"><span><span class="part-num">＋</span>BIS 国际清算银行报告 · 最新要点 (Quarterly Review 季度综述)</span><span class="freq-badge freq-quarterly" style="margin-left:0">每季度更新</span><a class="kol-dash-btn" href="https://eco-volatility-checker.pages.dev/bis/" target="_blank" rel="noopener">📄 查看 BIS 报告全库 →</a></div>
  {bis_section}

  <!-- ═══ 附三·二：三国货币供应量 M0/M1/M2 (央行资负表的延伸: 从"央行造多少底钱"到"社会流通多少钱") ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国货币供应量 M0 / M1 / M2 · 月度 (央行资负表下延: 社会实际流通的钱)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{money_supply}</div>

  <!-- ═══ 附三·二·二：三国 M2 十年历史折线 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>三国 M2 十年走势 · 折线 ($B 当天汇率统一折算 · 放水力度长期对比)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{m2_history}</div>

  <!-- ═══ 附三·A3b：中国央行流动性四图 (OMO/DR007/MLF/SFISF/两融) ═══ -->
  <!-- ★2026-08-31(Chao「按 menu 顺序改」)：本 section 原在 CIPS 之后(DOM #21)，
       但它属「流动性与央行」组，夹在「债务与信用」组中间 → 滚动时高亮回跳。
       现移到 M2 之后、与其余央行流动性 section 相邻，使 DOM 顺序 === 菜单顺序。 -->
  <div class="part-title" id="sec-cn-liq"><span class="part-num">＋</span>中国央行流动性 · 逆回购 / DR007 / MLF / SFISF / 两融 (三层融资渠道 + 股市托底 + 杠杆资金)<span class="freq-badge freq-daily">逆回购·DR007·两融 每日 · MLF 月度 · SFISF 事件驱动</span></div>
  <div class="card">{cn_liq}</div>

  <!-- ═══ 央行美元流动性互换(Chao 2026-08-24 点名遗失指标) ═══ -->
  <!-- ━━━ A 股资金面(国家队持股/北向/南向/ETF份额/两融) ━━━ -->
  <div class="part-title" id="sec-cn-capital"><span class="part-num">＋</span>A 股资金面 · 国家队持股 / 北向 / 南向 / ETF 份额 / 两融 (真实披露数据 · 不含软件自定义口径)<span class="freq-badge freq-daily">日更 + 季更</span></div>
  <div class="card">{cn_capital_html}</div>
  <!-- ★2026-08-31：原在页面最底部(DOM #47)，同属「流动性与央行」组 → 一并前移。 -->
  <div class="part-title" id="sec-cb-swaps"><span class="part-num">＋</span>央行货币互换 · 美元流动性互换 (Fed↔外国央行 · 离岸美元荒温度计)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{cb_swaps}</div>

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
  <!-- ━━━ 美债三图: 2Y/10Y/30Y · 期限溢价+MOVE+10Y · 彭博美综指 ETF 代理 (Chao 2026-10-16) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>美债 2年/10年/30年收益率 · 2019 年至今 (周度)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{ust_yld_html}</div>
  <div class="part-title"><span class="part-num">＋</span>美债期限溢价 + MOVE + 10年收益率 · 近 2 年<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{ust_tpm_html}</div>
  <div class="part-title"><span class="part-num">＋</span>美国综合债券指数 · ETF 代理 (AGG / BND · 近 2 年 · 日度)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{ust_agg_html}</div>
  <!-- ━━━ 国债微观结构: MS Exhibit 3/4 对口 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>国债市场微观结构 · 成交量与交易成本 (对齐 Morgan Stanley Exhibit 3/4 · 成交量为 NY Fed 官方真数据 · 价差为代理)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{ust_micro_html}</div>
  <!-- ═══ 附三·二B：基差套利去杠杆预警 ═══ -->
  <div class="part-title"><span class="part-num">＋</span>基差套利去杠杆预警 · 美债/日债 (SOFR 倒挂 + 持券 Carry + 波动触发 · 强平潮尾部风险 · 每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <!-- ━━━ 每日流动性危机监测(SOFR−EFFR + BBB/HY OAS + 闪崩标注) ━━━ -->
  {liquidity_crisis_html}
  <!-- ━━━ AI 债务 CDS 快照 (Chao 2026-10-18): Oracle/CoreWeave/SoftBank 单名 CDS, 新闻转引, 离散点不连线 ━━━ -->
  <div class="part-title" id="sec-ai-cds"><span class="part-num">＋</span>AI 债务 CDS 快照 · 甲骨文 / CoreWeave / 软银 (5 年期单名 · 新闻转引)<span class="freq-badge freq-daily">有报道才记</span></div>
  <div class="card">{ai_cds_html}</div>
  {cot_mm_html}
  {mm_ratio_html}
  <!-- ━━━ 中国模式断代监控(旧引擎停摆 / 新引擎接续) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>中国模式断代监控 · 旧引擎停摆与新引擎接续 (NBS 官方分项 + 东财宏观 · 对照 Perkins 2025-12 判据)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{china_regime_html}</div>
  <!-- ━━━ WRS · Walmart 衰退信号(分母 ETF 代理, 已标注) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>WRS · Walmart 衰退信号 (Walmart ÷ 奢侈品指数 · Jim Paulsen 口径 · 分母用 ETF 代理)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{wrs_html}</div>
  <!-- ━━━ 金银短线图(12 标的 · 价格+MA20/50/200+RSI14) ━━━ -->
  <div class="part-title" id="sec-gs-tech"><span class="part-num">＋</span>金银短线图 · 12 标的 (收盘 + 20/50/200 日线 + RSI14 · 日线)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{gs_tech_html}</div>
  <!-- ━━━ 金银类比路径 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>金银回调 · 历史类比路径 (金 2006/2008 · 银 2008/2011 · GDX÷SPY · 日度)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{analog_corr_html}</div>
  <!-- ━━━ 黄金波动率 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>黄金波动率 · GVZ / 布林带宽度 / ATR (COMEX 周线 · 2011 起)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{gold_vol_html}</div>
  <!-- ━━━ 联邦基金利率 × 金价 × 油价 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>联邦基金利率 × 金价 × 油价 (1970 起 · 月度 · 右轴对数)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{fed_gold_oil_html}</div>
  <!-- ━━━ 金油比 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>金油比 · 黄金 ÷ WTI 原油 (1971 起 · 月度 · 对数轴)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{gold_oil_html}</div>
  <!-- ━━━ 比特币 ÷ 黄金 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>比特币 ÷ 黄金 · 暴涨暴跌与事件 (2010 起 · 月度 · 对数轴)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{btc_gold_html}</div>
  <!-- ━━━ 道指/标普 ÷ 黄金 50 年比值 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>股指 ÷ 黄金 · 50 年比值 (道指÷金价 · 标普500÷金价 · 月度对数坐标 · 1976 年至今)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{stock_gold_html}</div>
  <div class="card"><div class="sgr-title" style="margin:0 0 4px">延长到 1929 年 · 标普÷黄金 · 均线与回撤（自制复现 StockCharts 公开图）</div>{spx_gold_long_html}</div>
  <!-- ━━━ 美元指数 vs 黄金 + 年初至今大事件标注 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>美元指数 vs 黄金 · 年初至今大事件标注 (双轴叠加 · 事件由价格异动反查并逐条核实出处)<span class="freq-badge freq-daily">价格每日 · 事件每周</span></div>
  <div class="card">{dxy_gold_html}</div>
  <!-- ━━━ 白银期货曲线价差 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>白银期货 · 各月合约价差 (COMEX · 日度 · 对比持有成本)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{silver_curve_html}</div>
  <!-- ━━━ COMEX 期货期权持仓(非 IV) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>COMEX 期货期权持仓 (金/银 · Managed Money 方向，非隐含波动率)<span class="freq-badge freq-weekly">持仓周更</span></div>
  <div class="card">{comex_optpos_html}</div>
  <!-- ═══ 附三·十二D：白银做市商头寸(CFTC COT, 一手) ═══ -->
  <div class="part-title" id="sec-silver-bank-positions"><span class="part-num">＋</span>白银做市商头寸 · CFTC COT commercial 净持仓 (做市商接货 vs 压价·一手真数据)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{silver_bank_positions}</div>
  <!-- ═══ 附三·十二E：COMEX 白银 issues/stops 静态参考(Michael Lynch) ═══ -->
  <div class="part-title" id="sec-comex-silver-issues"><span class="part-num">＋</span>COMEX 白银 投行累计 issues/stops · 静态参考 (Michael Lynch @DtDS_WSS·CME封禁无法自动更新)<span class="freq-badge" style="background:#e8e2d5;color:#8a6d3b">静态参考</span></div>
  <div class="card">{comex_silver_issues_ref}</div>
  <!-- ═══ 附三·十二F：COMEX 做市商每周净 issue/stop 柱状图(金+银, 一手) ═══ -->
  <div class="part-title" id="sec-comex-issue-stop"><span class="part-num">＋</span>COMEX 做市商每周净 issue/stop · 金+银 (一手·仅 House 自营·大行发货vs接货·每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{comex_issue_stop}</div>
  <!-- ═══ 附三·十二G：COMEX 交割前十名 金/银/铂 per-firm (需求B, Chao 2026-08-22) ═══ -->
  <div class="part-title" id="sec-comex-firms-top10"><span class="part-num">＋</span>COMEX 交割前十名 · 金/银/铂 (top10 交货方 vs 接货方·日/周/月切换·每日更新)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{comex_firms_top10}</div>
  <!-- ━━━ 贵金属 ETF 期权波动率: ATM IV 期限结构 + 25D 偏斜 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>贵金属 ETF 期权波动率 (GLD/SLV/IAU · ATM IV 期限结构 + 25D 偏斜)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{pm_optvol_html}</div>
  <!-- ━━━ 黄金 ETF 分地区资金流 (WGC 官方) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>黄金 ETF 分地区资金流 (北美/欧洲/亚洲/其他 · 世界黄金协会官方周度吨数)<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{gold_etf_region_html}</div>
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
  <div class="part-title" id="sec-gold-premium"><span class="part-num">＋</span>印度 &amp; 中国黄金 Domestic Premium/Discount (亚洲实物黄金需求风向标·WGC 真数据)<span class="freq-badge freq-weekly">周更/月更</span></div>
  <div class="card">{gold_premium}</div>
  <!-- ═══ 附三·十二B1b：印度白银月度进口 (UN Comtrade) ═══ -->
  <div class="part-title" id="sec-silver-imports"><span class="part-num">＋</span>印度白银月度进口 · Silver Bullion Imports (全球最大白银进口国·实物需求风向标·UN Comtrade 免费月度)<span class="freq-badge freq-monthly">每月更新</span></div>
  <div class="card">{silver_imports}</div>
  <!-- ━━━ 铀短线图(14 标的 · 价格+MA20/50/200+RSI14) ━━━ -->
  <div class="part-title" id="sec-ur-tech"><span class="part-num">＋</span>铀与铀矿企 · 14 标的 (收盘 + 20/50/200 日线 + RSI14 · 日线)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{ur_tech_html}</div>

  <!-- ━━━ 机构报告被公开解读(线索表) ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>机构研究报告 · 被公开解读的线索 (按机构 · 近 6 个月 · 正文未读)<span class="freq-badge freq-daily">日更</span></div>
  <div class="card">{report_leads_html}</div>
  <!-- ━━━ 密歇根信心 vs 全要素生产率相对趋势 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>消费者信心 vs 全要素生产率 (密歇根信心 · TFP 相对趋势 · 复刻 BofA Chart 10 · 1978 年至今)<span class="freq-badge freq-daily">每日检查</span></div>
  <div class="card">{tfp_sentiment_html}</div>
  <!-- ━━━ 美国货运 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>美国货运 · 铁路周度 (AAR 10 类商品 + 联运) 与公路月度 (ATA / Cass)<span class="freq-badge freq-daily">每周更新</span></div>
  <div class="card">{us_freight_html}</div>
  <!-- ━━━ 中美 AI 资本开支 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>中美 AI 投资 · 科技巨头资本开支 (美国五家 vs 阿里/腾讯/百度 · 季度 + 美国数据中心建设月度)<span class="freq-badge freq-daily">每日检查</span></div>
  <div class="card">{ai_capex_html}</div>
  <!-- ━━━ LLM Token 支出指数 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>AI 算力价格 · LLM Token 支出指数 (Silicon Data SDLLMTK · 美元/百万 token · 全市场/闭源/开源)<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{llm_token_html}</div>
  <!-- ━━━ 全球货币供应(五大经济体聚合) + 加速度 ━━━ -->
  <div class="part-title"><span class="part-num">＋</span>全球货币供应与放水加速度 (美/欧/日/英/中 · 30 年)<span class="freq-badge freq-monthly">月度更新</span></div>
  <div class="card">{global_money_html}</div>
  <div class="card">{h8_deposits_html}</div>
  <div class="card">{hf_ust_html}</div>
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
  <!-- ━━━ 日元套息 (Chao 2026-10-18): 每日事实 + CFTC 日元净头寸 + 美日利差 vs USDJPY + USDJPY 周K/均线/已实现波动率 ━━━ -->
  <div class="part-title" id="sec-jpy-carry"><span class="part-num">＋</span>日元套息 · 每日事实<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{jpy_facts_html}</div>
  <div class="part-title"><span class="part-num">＋</span>日元期货 CFTC 净头寸 · 非商业与杠杆基金 · 近 3 年<span class="freq-badge freq-weekly">每周更新</span></div>
  <div class="card">{jpy_cftc_html}</div>
  <div class="part-title"><span class="part-num">＋</span>美日 10年利差 vs 美元/日元 · 近 2 年<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{jpy_spread_html}</div>
  <div class="part-title"><span class="part-num">＋</span>美元/日元周K线 · 均线与已实现波动率<span class="freq-badge freq-daily">每日更新</span></div>
  <div class="card">{jpy_kline_html}</div>
  <!-- ═══ 附三·八B：美国国债收益率百年周期(4线, 1934→今) ═══ -->
  <div class="part-title" id="sec-us-yield-century"><span class="part-num">＋</span>美国国债收益率百年周期 · Fed Funds/3M/10Y/30Y (40年长周期·1940大底/1980大顶/2020大底)<span class="freq-badge freq-quarterly">每季更新</span></div>
  <div class="card">{us_yield_century}</div>
  <!-- ═══ 附三·六：日本 / 中国 分国别持有美债 (TIC, 近10年) ═══ -->
  <div class="part-title"><span class="part-num">＋</span>日本 / 中国 / 欧元区 持有美债 · 央行 vs 私人 · 近10年 + 2008长历史 (TIC 分国别口径)<span class="freq-badge freq-monthly">每月更新 · 滞后约2月 · 三方同频</span></div>
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
  // ★2026-08-25(Chao 报「左边目录和右边 chart 又开始跳动」)：根因是本行以前抓的是
  // <b>全部</b> .part-title —— 但 .part-title 这个类同时被两种东西用：
  //   ① 顶级 section 标题（模板里写死，带 <span class="part-num">＋</span>）  46 个
  //   ② <b>图内小标题</b>（_cn_liq_html / AI 信用维度等函数内生成，无 part-num）  6 个
  // ②本不该进导航。它们不匹配任何 GROUPS 关键词 → 全掉进「其他」，
  // 而「其他」按"首个成员 DOM 位置"排序会插在页面中部，于是向下滚动时
  // 高亮在「其他」和真实分组之间来回窜 —— 这就是"跳动"。
  // 修法：只认带 .part-num 的顶级标题。图内小标题不再参与导航与 scrollspy。
  var titles = Array.prototype.slice.call(document.querySelectorAll('.part-title'))
                    .filter(function(t) {{ return t.querySelector('.part-num'); }});
  var box = document.getElementById('sidenav-links');
  if (!titles.length || !box) return;

  // ★2026-08-22(Chao): 左侧菜单顺序必须与右侧内容 DOM 顺序<b>完全一致</b>。
  // 旧实现按 GROUPS 数组的固定顺序渲染分组, 与页面实际排布脱节 ——
  // 往下 browse 时高亮会在分组间来回跳(实测 3 次向上跳跃), 且 7 个 section
  // 未命中任何关键词掉进「其他」, 而「其他」渲染在最底部 → 读到页面中部
  // 高亮突然窜到菜单最下面。
  // 现在改为: 分组按其<b>首个成员在 DOM 中的位置</b>排序(首次出现即建组),
  // 组内成员也按 DOM 顺序 → 菜单自上而下 === 页面自上而下。
  // 「机构与政要持仓」由 Chao 指定固定放最后(在「其他」之下), 用 pinLast 标记。
  var GROUPS = [
    // ★2026-10-10(Chao「按这个顺序」): 黄金白银 21 板块连成一段, 置于首位以优先命中
    {{ name: '黄金白银', match: ['对冲基金多空比','金银短线','金银回调','黄金波动率','联邦基金利率','金油比','比特币 ÷ 黄金','股指 ÷ 黄金','美元指数 vs 黄金','白银期货','COMEX 期货期权持仓','白银做市商','COMEX 白银','做市商每周净','COMEX 交割前十名','贵金属 ETF 期权','黄金 ETF 分地区','COMEX & 上海贵金属库存','自营黄金掉期','美国黄金出口','印度 & 中国黄金','印度白银月度进口'] }},
    {{ name: '铀', match: ['铀与铀矿企'] }},
    {{ name: '核心风险扫描', match: ['指标卡片','警报统计','逐条','综合结论','卖出触发','今日最需关注','A/D 腾落线','市场广度'] }},
    // ★2026-08-25(Chao)：KOL 全量名录原先未命中任何关键词 → 掉进「其他」，
    // 但它本质就是 KOL 板块的一部分，归入本组。
    {{ name: 'KOL 观点', match: ['KOL 观点全景','KOL 状态变化','周期与术数预测','KOL 全量名录'] }},
    // ★2026-08-25(Chao)：「中国央行流动性」与「央行货币互换」原先都掉进「其他」，
    // 但两者本质都是央行流动性观测 —— 一个是 PBoC 的逆回购/DR007/MLF/SFISF，
    // 一个是 Fed 与外国央行的美元互换额度。均归入本组。
    {{ name: '流动性与央行', match: ['对冲基金常用注册地','美国银行存款','A 股资金面','流动性要点','央行资产负债表','国际清算银行','三国货币供应','全球货币供应','M2 十年','Credit Impulse','信贷脉冲','中国央行流动性','央行货币互换','美元流动性互换'] }},
    {{ name: '债务与信用', match: ['政府债务','世界前十大经济体','公司债','OAS 利差','AI 债务 CDS','CIPS','跨境人民币','AI 产业链','自由现金流','信用维度'] }},
    {{ name: '国债流动性观测', match: ['WRS','国债市场收益率','日元套息','日元期货 CFTC','美日 10年利差','美元/日元周K线','美债 2年/10年/30年','美债期限溢价','美国综合债券指数','国债市场微观结构','中国模式断代监控','市场压力','基差套利去杠杆预警','SOFR 倒挂','国债拍卖','托管美债','再融资墙','1年内到期','持有美债','分国别','10年/30年国债收益率','美日 10','国际投资头寸','IIP','净头寸','对冲基金美债杠杆','回购借款','百年周期'] }},
    {{ name: '能源与大宗', match: ['石油库存','能源安全','Cushing','SPR','Brent','COMEX & 上海','贵金属库存','ETF 资金流','白银做市商','COMEX 白银','投行累计','做市商每周净','issue/stop','COMEX 交割前十名','交货方','自营黄金掉期','黄金出口','Nonmonetary','黄金 Domestic Premium','Premium/Discount','白银月度进口','Silver Bullion'] }},
    {{ name: '实体、AI 与研报', match: ['机构研究报告','消费者信心','美国货运','中美 AI 投资','AI 算力价格'] }},
    {{ name: '财政政策', match: ['美日财政政策事件','债务上限','补正预算','国债发行','年度财政花费','财政花费','政府总支出'] }},
    {{ name: '日本市场', match: ['日经225','外资净买入','日本市场'] }},
    {{ name: '机构与政要持仓', match: ['机构持仓','13F','Trump'], pinLast: true }}
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
  var seq = [];     // ★2026-10-06: DOM 顺序下的 {{a, idx, hint}}; 菜单严格按它渲染, 保证 菜单顺序 === 页面顺序
  titles.forEach(function(t, i) {{
    // ★保留已有的语义 id（模板里写死的 sec-cn-liq / sec-cips 等）。
    // 旧实现无条件 t.id = 'sec-' + i，会把语义 id 冲掉 → 外部链接/书签锚点全失效。
    var id = t.id || ('sec-' + i);
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
    seq.push({{ a: a, idx: i, hint: g }});
    links[i] = a;
  }});

  // ★★2026-10-06(Chao「还是有跳动感」): 旧实现把同组成员(哪怕相距几十屏)合并成一个菜单组,
  //   而 scrollspy 用的是 DOM 序号 → 菜单顺序≠页面顺序, 3 处位置倒退
  //   (美元指数 vs 黄金 / 全球货币供应与放水加速度 / 国债市场微观结构 被关键词硬塞进远处的组)。
  //   根治: 菜单严格按 DOM 顺序渲染; 分组仅作「相邻 section 的小标题」:
  //   连续同组 → 一个标题; 同组但被别组隔开 → 分成两段各带标题; 关键词无命中 → 并入相邻段。
  //   以后新增 section 无论关键词命不命中, 都不可能再让菜单顺序与页面顺序不一致。
  var NONE = GROUPS.length;
  var eff = seq.map(function(x) {{ return x.hint; }});
  for (var k = 0; k < eff.length; k++) {{
    if (eff[k] !== NONE) continue;
    var pv = null, nx = null, j;
    for (j = k - 1; j >= 0; j--) {{ if (seq[j].hint !== NONE) {{ pv = seq[j].hint; break; }} }}
    for (j = k + 1; j < eff.length; j++) {{ if (seq[j].hint !== NONE) {{ nx = seq[j].hint; break; }} }}
    eff[k] = (pv !== null) ? pv : (nx !== null ? nx : NONE);
  }}
  // 孤立离群: 夹在同一组两侧、自己命中另一组、且只有 1 项 → 归入两侧那一组(菜单更连贯, 页面顺序不变)
  for (var q = 1; q < eff.length - 1; q++) {{
    if (eff[q] !== eff[q - 1] && eff[q - 1] === eff[q + 1] && eff[q - 1] !== NONE) {{ eff[q] = eff[q - 1]; }}
  }}
  var runs = [];
  seq.forEach(function(x, n) {{
    var gi = eff[n], last = runs[runs.length - 1];
    if (last && last.gIdx === gi) last.items.push(x); else runs.push({{ gIdx: gi, items: [x] }});
  }});
  // pinLast(机构与政要持仓): 保持 Chao 的「放最后」→ 仅当它在页面里本来就靠后时才有意义;
  // 若 pinLast 的段不在末尾, 不改菜单顺序(否则又与页面脱节), 只在日志里提示。
  function renderRun(run, seen) {{
    var wrap = document.createElement('div');
    wrap.className = 'sn-group';
    var hdr = document.createElement('div');
    hdr.className = 'sn-group-hdr';
    var nm = (run.gIdx < GROUPS.length) ? GROUPS[run.gIdx].name : '其他';
    hdr.innerHTML = '<span class="sn-caret">▾</span>' + nm + (seen[run.gIdx] ? '（续）' : '') + '<span class="sn-cnt">' + run.items.length + '</span>';
    seen[run.gIdx] = true;
    var list = document.createElement('div');
    list.className = 'sn-group-list';
    run.items.forEach(function(it) {{ list.appendChild(it.a); }});
    hdr.addEventListener('click', function() {{ wrap.classList.toggle('sn-collapsed'); }});
    wrap.appendChild(hdr);
    wrap.appendChild(list);
    box.appendChild(wrap);
  }}
  var _seen = {{}};
  runs.forEach(function(r) {{ renderRun(r, _seen); }});
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
    if (v.indexOf('<br>') >= 0) tip.classList.add('multi'); else tip.classList.remove('multi');
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
    // r = [first, last, direction, comments, targets, source, detail, srcs]
    var first = r[0] || '', last = r[1] || '', dir = r[2] || '', cmt = r[3] || '';
    var tgt = r[4] || '', src = r[5] || '', det = r[6] || '', srcs = r[7] || [];
    // 日期区间: 同一言论连续多日持有 → 显示 "起 ~ 止"; 单日 → 只显一个日期
    var dateTxt = (first && last && first !== last) ? (first + ' ~ ' + last) : (last || first);
    var kv = '';
    if (dir) kv += '<span class="kd-kv-i">方向：<b>' + esc(dir) + '</b></span>';
    if (tgt) kv += (kv ? ' · ' : '') + '标的：' + esc(tgt);
    if (first && last && first !== last) {{
      kv += (kv ? ' · ' : '') + '该观点连续见于 ' + esc(first) + ' 至 ' + esc(last);
    }}
    // ★2026-08-22(Chao): 展开层优先显示 detail(100-300字结构化深度摘要)。
    //   detail 用「▸ 小标题：内容」四段式, 按 \n 拆成多行渲染。
    //   没有 detail 的历史条目仍退回 comments —— 不伪造。
    var body;
    if (det) {{
      var segs = det.split('\\n').filter(function(s) {{ return s.trim(); }});
      body = '<div class="kd-deep">' + segs.map(function(s) {{
        s = s.trim();
        var mm = s.match(/^▸\\s*([^：:]{{2,12}})[：:]([\\s\\S]*)$/);
        return mm
          ? '<div class="kd-seg"><span class="kd-seg-k">' + esc(mm[1]) + '</span>'
            + '<span class="kd-seg-v">' + esc(mm[2].trim()) + '</span></div>'
          : '<div class="kd-seg"><span class="kd-seg-v">' + esc(s) + '</span></div>';
      }}).join('') + '</div>';
    }} else {{
      body = '<div class="kd-full">' + esc(cmt) + '</div>';
    }}
    // 来源: 优先用深度抓取带回的多条链接, 否则退回单条 source
    var srcHtml;
    if (srcs && srcs.length) {{
      srcHtml = '<div class="kd-kv">原文出处：' + srcs.map(function(s) {{
        var t = (s.title || s.url || '').slice(0, 46);
        return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">'
             + esc(t) + (s.date ? ' (' + esc(s.date) + ')' : '') + '</a>';
      }}).join(' · ') + '</div>';
    }} else if (src) {{
      srcHtml = '<div class="kd-kv">原文出处：<a href="' + esc(src) + '" target="_blank" rel="noopener">' + esc(src) + '</a></div>';
    }} else {{
      srcHtml = '<div class="kd-kv">出处：每日快照汇总（无单条原文链接）</div>';
    }}
    return '<div class="kd-row" data-i="' + idx + '">' +
             '<div class="kd-row-hd">' +
               '<span class="kd-date">' + esc(dateTxt) + '</span>' +
               (dir ? '<span class="kd-date">[' + esc(dir) + ']</span>' : '') +
               '<span class="kd-one">' + esc(cmt) + '</span>' +
               (det ? '<span class="kd-deep-badge" title="含深度摘要">详</span>' : '') +
               '<span class="kd-caret">▸</span>' +
             '</div>' +
             '<div class="kd-detail">' +
               body +
               (kv ? '<div class="kd-kv">' + kv + '</div>' : '') +
               srcHtml +
             '</div>' +
           '</div>';
  }}

  function open(kol) {{
    var d = DATA[kol];
    elName.textContent = (d && d.n) ? d.n : kol;
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
    // 本日/本周/本月 三档切换(Chao 2026-08-31): 三份数据已内嵌, 只切 display
    var kp = ev.target.closest ? ev.target.closest('.kp-btn') : null;
    if (kp) {{
      var grp = kp.getAttribute('data-kp-group');
      var sel = kp.getAttribute('data-kp');
      var i, btns = document.querySelectorAll('.kp-btn[data-kp-group="' + grp + '"]');
      for (i = 0; i < btns.length; i++) {{
        if (btns[i].getAttribute('data-kp') === sel) btns[i].classList.add('on');
        else btns[i].classList.remove('on');
      }}
      var panes = document.querySelectorAll('.kp-pane[data-kp-group="' + grp + '"]');
      for (i = 0; i < panes.length; i++) {{
        panes[i].style.display =
          (panes[i].getAttribute('data-kp-pane') === sel) ? '' : 'none';
      }}
      return;
    }}
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

/* ★2026-08-22 需求A: COMEX issue/stop 时间窗口 filter。
   数据全量已内嵌为多个 .cis-pane, 点击 tab 只切 display, 不重新请求。
   data-cis 区分金属(au/ag), data-idx 区分窗口, 两者组合定位唯一 pane。 */
(function() {{
  var tabs = document.querySelectorAll('.cis-tab');
  if (!tabs.length) return;
  for (var i = 0; i < tabs.length; i++) {{
    tabs[i].addEventListener('click', function() {{
      var slug = this.getAttribute('data-cis');
      var idx  = this.getAttribute('data-idx');
      // 同一金属的 tab 与 pane 一起切换, 不影响另一金属
      var sibTabs = document.querySelectorAll('.cis-tab[data-cis="' + slug + '"]');
      for (var a = 0; a < sibTabs.length; a++) sibTabs[a].classList.remove('cis-on');
      this.classList.add('cis-on');
      var panes = document.querySelectorAll('.cis-pane[data-cis="' + slug + '"]');
      for (var b = 0; b < panes.length; b++) {{
        panes[b].classList.toggle('cis-on', panes[b].getAttribute('data-idx') === idx);
      }}
    }});
  }}
}})();

/* ★2026-08-22 需求B: COMEX top10 榜单的时间粒度切换(日/周/月/全期)。
   data-tf 区分金属(au/ag/pt), data-k 区分窗口。三个金属各自独立切换。 */
(function() {{
  var tabs = document.querySelectorAll('.tf-tab');
  if (!tabs.length) return;
  for (var i = 0; i < tabs.length; i++) {{
    tabs[i].addEventListener('click', function() {{
      var slug = this.getAttribute('data-tf');
      var k    = this.getAttribute('data-k');
      var sibTabs = document.querySelectorAll('.tf-tab[data-tf="' + slug + '"]');
      for (var a = 0; a < sibTabs.length; a++) sibTabs[a].classList.remove('tf-on');
      this.classList.add('tf-on');
      var panes = document.querySelectorAll('.tf-pane[data-tf="' + slug + '"]');
      for (var b = 0; b < panes.length; b++) {{
        panes[b].classList.toggle('tf-on', panes[b].getAttribute('data-k') === k);
      }}
    }});
  }}
}})();

/* ★2026-08-22 BIS 季度切换(近 4 期 Quarterly Review)。
   4 期要点已全部内嵌为 .bis-pane, 点 button 只切 display。 */
(function() {{
  var tabs = document.querySelectorAll('.bis-tab');
  if (!tabs.length) return;
  for (var i = 0; i < tabs.length; i++) {{
    tabs[i].addEventListener('click', function() {{
      var k = this.getAttribute('data-bis');
      var all = document.querySelectorAll('.bis-tab');
      for (var a = 0; a < all.length; a++) all[a].classList.remove('bis-on');
      this.classList.add('bis-on');
      var panes = document.querySelectorAll('.bis-pane');
      for (var b = 0; b < panes.length; b++) {{
        panes[b].classList.toggle('bis-on', panes[b].getAttribute('data-bis') === k);
      }}
    }});
  }}
}})();
</script>

<script>
(function(){{
  var el=document.getElementById('frt-data'); if(!el) return;
  var D=JSON.parse(el.textContent), R=D.rail, ZH=D.zh;
  var COL=['#1f3a68','#b0613e','#6f8f5a','#8a6fa5','#c79a3b','#4a90a4','#a05a7a','#7a7a7a'];
  var NS='http://www.w3.org/2000/svg';
  var st={{keys:['Total Traffic'],mode:'raw',yrs:5}};
  function esc(t){{return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}}
  function fmt(v,m){{return v==null?'—':(m==='yoy'?(v>0?'+':'')+v.toFixed(1)+'%':Math.round(v).toLocaleString());}}
  function series(k){{
    var v=R.s[k], d=R.d, out=[];
    for(var i=0;i<v.length;i++){{
      var y=v[i];
      if(st.mode==='ma4'){{ if(i<3){{y=null;}} else {{y=(v[i]+v[i-1]+v[i-2]+v[i-3])/4;}} }}
      else if(st.mode==='yoy'){{
        var t=new Date(d[i]).getTime()-364*864e5, j=-1;
        for(var q=i-1;q>=0;q--){{ if(Math.abs(new Date(d[q]).getTime()-t)<=3*864e5){{j=q;break;}} if(new Date(d[q]).getTime()<t-7*864e5) break; }}
        y=(j>=0&&v[j])?(v[i]/v[j]-1)*100:null;
      }}
      out.push(y);
    }}
    return out;
  }}
  function draw(box,xs,lines,opts){{
    var W=900,H=opts.h||280,PL=56,PR=16,PT=12,PB=24,iw=W-PL-PR,ih=H-PT-PB,n=xs.length;
    var lo=Infinity,hi=-Infinity;
    lines.forEach(function(L){{L.v.forEach(function(y){{if(y!=null){{lo=Math.min(lo,y);hi=Math.max(hi,y);}}}});}});
    if(!isFinite(lo)){{box.innerHTML='<p class="empty">无数据</p>';return;}}
    if(opts.zero){{lo=Math.min(lo,0);hi=Math.max(hi,0);}}
    var span=(hi-lo)||1, raw=span/4, mag=Math.pow(10,Math.floor(Math.log10(raw))), nr=raw/mag;
    var step=(nr<=1?1:nr<=2?2:nr<=2.5?2.5:nr<=5?5:10)*mag;
    lo=Math.floor(lo/step)*step; hi=Math.ceil(hi/step)*step;
    function X(i){{return PL+iw*i/Math.max(n-1,1);}} function Y(y){{return PT+ih*(1-(y-lo)/(hi-lo));}}
    var h='<svg viewBox="0 0 '+W+' '+H+'" class="sgr-chart" preserveAspectRatio="xMidYMid meet">';
    for(var yv=lo;yv<=hi+step/2;yv+=step){{h+='<line x1="'+PL+'" y1="'+Y(yv).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(yv).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(Y(yv)+3.5).toFixed(1)+'" class="sgr-yt">'+esc(opts.fy(yv))+'</text>';}}
    if(opts.zero&&lo<0&&hi>0) h+='<line x1="'+PL+'" y1="'+Y(0).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(0).toFixed(1)+'" stroke="#8a837a" stroke-width="1"/>';
    var lastY='';
    for(var i=0;i<n;i++){{var yr=xs[i].slice(0,4); if(yr!==lastY&&xs[i].slice(5,7)==='01'){{ h+='<text x="'+X(i).toFixed(1)+'" y="'+(H-6)+'" class="sgr-xt">'+yr+'</text>'; }} lastY=yr;}}
    lines.forEach(function(L,li){{
      var p='',pen=false;
      L.v.forEach(function(y,i){{ if(y==null){{pen=false;return;}} p+=(pen?' L':' M')+X(i).toFixed(1)+','+Y(y).toFixed(1); pen=true; }});
      h+='<path d="'+p+'" fill="none" stroke="'+COL[li%COL.length]+'" stroke-width="'+(li===0?1.8:1.4)+'"/>';
    }});
    for(var i2=0;i2<n;i2++){{
      var l=i2>0?(X(i2-1)+X(i2))/2:PL, r=i2<n-1?(X(i2)+X(i2+1))/2:W-PR;
      var tip=esc((opts.monthly?'':'周截至 ')+xs[i2])+'||'+lines.map(function(L){{return esc(L.name+' '+opts.ft(L.v[i2]));}}).join('<br>');
      h+='<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(r-l,0.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-tip="'+tip+'"/>';
    }}
    h+='</svg>';
    var leg='<div class="tfs-legend">'+lines.map(function(L,li){{return '<i style="border-color:'+COL[li%COL.length]+'"></i>'+esc(L.name);}}).join('')+'</div>';
    box.innerHTML=leg+h;
  }}
  function renderRail(){{
    var cut=new Date(R.d[R.d.length-1]); cut.setFullYear(cut.getFullYear()-st.yrs);
    var i0=0; while(i0<R.d.length&&new Date(R.d[i0])<cut) i0++;
    var xs=R.d.slice(i0);
    var lines=st.keys.map(function(k){{return {{name:ZH[k],v:series(k).slice(i0)}};}});
    draw(document.getElementById('frt-rail'),xs,lines,{{h:290,zero:st.mode==='yoy',
      fy:function(v){{return st.mode==='yoy'?v.toFixed(0)+'%':(Math.abs(v)>=1000?Math.round(v/1000)+'k':v.toFixed(0));}},
      ft:function(v){{return fmt(v,st.mode);}}}});
  }}
  function renderRoad(){{
    var ms={{}}; (D.ata||[]).forEach(function(x){{ms[x.m]=1;}}); (D.cass||[]).forEach(function(x){{ms[x.m]=1;}});
    var xs=Object.keys(ms).sort(); if(!xs.length) return;
    function pick(a,base){{var m={{}};a.forEach(function(x){{m[x.m]=x.v;}}); var b=m[base]; return xs.map(function(k){{return (m[k]!=null&&b)?m[k]/b*100:null;}});}}
    var base=xs[0];
    var lines=[{{name:'ATA 卡车吨位（'+base+'=100）',v:pick(D.ata||[],base)}},{{name:'Cass 发货量（'+base+'=100）',v:pick(D.cass||[],base)}}];
    var raw={{a:{{}},c:{{}}}}; (D.ata||[]).forEach(function(x){{raw.a[x.m]=x.v;}}); (D.cass||[]).forEach(function(x){{raw.c[x.m]=x.v;}});
    draw(document.getElementById('frt-road'),xs,lines,{{h:220,monthly:true,
      fy:function(v){{return v.toFixed(0);}}, ft:function(v){{return v==null?'—（未发布）':v.toFixed(1);}}}});
  }}
  function bind(sel,fn){{Array.prototype.forEach.call(document.querySelectorAll(sel),function(b){{b.addEventListener('click',function(){{fn(b);renderRail();}});}});}}
  bind('.frt-b',function(b){{
    var k=b.getAttribute('data-k'), i=st.keys.indexOf(k);
    if(i>=0){{ if(st.keys.length>1){{st.keys.splice(i,1);b.classList.remove('on');}} }}
    else {{ if(st.keys.length>=8){{return;}} st.keys.push(k); b.classList.add('on'); }}
  }});
  bind('.frt-m',function(b){{document.querySelectorAll('.frt-m').forEach(function(x){{x.classList.remove('on');}});b.classList.add('on');st.mode=b.getAttribute('data-m');}});
  bind('.frt-r',function(b){{document.querySelectorAll('.frt-r').forEach(function(x){{x.classList.remove('on');}});b.classList.add('on');st.yrs=+b.getAttribute('data-r');}});
  function renderCost(){{
    var ds=D.diesel||[]; if(ds.length){{
      var c=new Date(ds[ds.length-1].d); c.setFullYear(c.getFullYear()-5);
      var xs=[],v=[]; ds.forEach(function(x){{ if(new Date(x.d)>=c){{xs.push(x.d);v.push(x.v);}} }});
      draw(document.getElementById('frt-diesel'),xs,[{{name:'柴油零售价（美元/加仑）',v:v}}],{{h:200,
        fy:function(y){{return '$'+y.toFixed(1);}}, ft:function(y){{return y==null?'—':'$'+y.toFixed(3);}}}});
    }}
    var ms={{}}; [D.ppi_tl,D.cass_exp,D.cass].forEach(function(a){{(a||[]).forEach(function(x){{ms[x.m]=1;}});}});
    var xs2=Object.keys(ms).sort(); if(!xs2.length) return; var base=xs2[0];
    function pick(a){{var m={{}};(a||[]).forEach(function(x){{m[x.m]=x.v;}}); var b=m[base]; return xs2.map(function(k){{return (m[k]!=null&&b)?m[k]/b*100:null;}});}}
    draw(document.getElementById('frt-cost'),xs2,[
      {{name:'整车长途运价 PPI（'+base+'=100）',v:pick(D.ppi_tl)}},
      {{name:'Cass 运费支出（'+base+'=100）',v:pick(D.cass_exp)}},
      {{name:'Cass 发货量（'+base+'=100）',v:pick(D.cass)}}],{{h:220,monthly:true,
      fy:function(y){{return y.toFixed(0);}}, ft:function(y){{return y==null?'—（未发布）':y.toFixed(1);}}}});
  }}
  renderRail(); renderRoad(); renderCost();
}})();



/* ── 白银期货曲线价差 (固定容器高度, 重绘只换 SVG 内容) ── */
(function() {{
  var el = document.getElementById('sfc-data'); if (!el) return;
  var D = JSON.parse(el.textContent), C = D.c, N = D.d.length;
  var COL = ['#8a837a','#1f3a68','#7a8f5a','#b0493a','#a8761a','#5b4a8a','#2b7a78','#c0643c'];
  var st = {{n: 0, u: 'usd', carry: 1, on: {{}}}};
  Array.prototype.forEach.call(document.querySelectorAll('.sfc-chk input[data-c]'), function(c) {{ st.on[c.getAttribute('data-c')] = c.checked; }});
  var W = 900, H = 320, PL = 54, PR = 16, PT = 12, PB = 26, iw = W-PL-PR, ih = H-PT-PB, box = document.getElementById('sfc-chart');
  function months(c) {{ return (+c.slice(0,4))*12 + (+c.slice(5,7)) - ((+C[0].slice(0,4))*12 + (+C[0].slice(5,7))); }}
  function sp(i, j) {{ var v = D.p[i][j]; if (v == null) return null; return st.u === 'usd' ? v - D.b[i] : (v / D.b[i] - 1) * 100; }}
  function cr(i, j) {{ if (D.r[i] == null) return null; var c = D.b[i] * D.r[i] * months(C[j]) / 12; return st.u === 'usd' ? c : c / D.b[i] * 100; }}
  function fmt(v) {{ return v == null ? '—' : (st.u === 'usd' ? v.toFixed(3) : v.toFixed(2) + '%'); }}
  function draw() {{
    var i0 = st.n ? Math.max(0, N - st.n) : 0, n = N - i0, series = [], all = [];
    C.forEach(function(c, j) {{ if (j === 0 || !st.on[c]) return;
      var pts = [], cp = []; for (var i = i0; i < N; i++) {{ pts.push(sp(i, j)); cp.push(cr(i, j)); }}
      series.push({{j: j, c: c, pts: pts, cp: cp}}); pts.forEach(function(v) {{ if (v != null) all.push(v); }});
      if (st.carry) cp.forEach(function(v) {{ if (v != null) all.push(v); }}); }});
    if (!series.length) {{ box.innerHTML = '<div style="padding:60px;text-align:center;color:#8a837a">请至少勾选一个合约</div>'; return; }}
    var mn = Math.min(0, Math.min.apply(null, all)), mx = Math.max.apply(null, all), pad = (mx - mn) * 0.08 || 0.1; mn -= (mn < 0 ? pad : 0); mx += pad;
    var X = function(k) {{ return PL + iw * k / Math.max(n-1, 1); }}, Y = function(v) {{ return PT + ih * (1 - (v - mn) / (mx - mn)); }};
    var g = '', tk = 5; for (var t = 0; t <= tk; t++) {{ var v = mn + (mx - mn) * t / tk; g += '<line x1="'+PL+'" y1="'+Y(v).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(v).toFixed(1)+'" class="sfc-g"/><text x="'+(PL-6)+'" y="'+(Y(v)+3.5).toFixed(1)+'" class="sfc-yt">'+(st.u === 'usd' ? v.toFixed(2) : v.toFixed(1)+'%')+'</text>'; }}
    g += '<text x="'+PL+'" y="'+(PT-1)+'" class="sfc-yt" style="text-anchor:start">'+(st.u === 'usd' ? '美元/盎司（相对基准合约的升水）' : '%（相对基准合约的升水）')+'</text>';
    var step = Math.max(1, Math.round(n / 7)); for (var k = 0; k < n; k += step) g += '<text x="'+X(k).toFixed(1)+'" y="'+(H-8)+'" class="sfc-xt">'+D.d[i0+k].slice(2)+'</text>';
    series.forEach(function(s) {{ var col = COL[(s.j-1) % COL.length], p = '', cp = '';
      s.pts.forEach(function(v, k) {{ if (v != null) p += X(k).toFixed(1)+','+Y(v).toFixed(1)+' '; }});
      if (st.carry) s.cp.forEach(function(v, k) {{ if (v != null) cp += X(k).toFixed(1)+','+Y(v).toFixed(1)+' '; }});
      g += '<polyline points="'+p+'" fill="none" stroke="'+col+'" stroke-width="1.7"/>';
      if (cp) g += '<polyline points="'+cp+'" fill="none" stroke="'+col+'" stroke-width="1.4" stroke-dasharray="6 4" opacity=".85"/>'; }});
    g += '<rect id="sfc-hit" x="'+PL+'" y="'+PT+'" width="'+iw+'" height="'+ih+'" fill="transparent"/><line id="sfc-cur" x1="0" y1="'+PT+'" x2="0" y2="'+(PT+ih)+'" stroke="#8a837a" stroke-dasharray="3 3" style="display:none"/>';
    box.innerHTML = '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'+g+'</svg>';
    var hit = document.getElementById('sfc-hit'), cur = document.getElementById('sfc-cur'), pin = document.getElementById('sfc-pin'), svg = box.firstChild;
    function at(ev) {{ var r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * W; var k = Math.round((x - PL) / iw * (n-1)); return Math.max(0, Math.min(n-1, k)); }}
    function show(k) {{ var i = i0 + k; cur.setAttribute('x1', X(k)); cur.setAttribute('x2', X(k)); cur.style.display = '';
      pin.innerHTML = '<b>'+D.d[i]+'</b> 基准合约 $'+D.b[i].toFixed(2)+(D.r[i] != null ? ' · 3M利率 '+(D.r[i]*100).toFixed(2)+'%' : '')+' | '+series.map(function(s) {{ return C[s.j].slice(2,4)+'年'+(+C[s.j].slice(5))+'月 <b style="color:'+COL[(s.j-1)%COL.length]+'">'+fmt(sp(i, s.j))+'</b>'; }}).join(' · '); }}
    hit.addEventListener('mousemove', function(ev) {{ show(at(ev)); }});
    hit.addEventListener('mouseleave', function() {{ cur.style.display = 'none'; pin.textContent = '悬停图上任意位置可看各合约当日价差。'; }});
  }}
  function table() {{
    var i = N - 1, ip = Math.max(0, N - 22), h = '<tr><th>合约（'+D.d[i]+'）</th><th>收盘价</th><th>升水($)</th><th>升水(%)</th><th>持有成本($)</th><th>超出成本($)</th><th>一个月前（'+D.d[ip].slice(5)+'）升水($)</th><th>变化($)</th></tr>';
    C.forEach(function(c, j) {{ if (j === 0) return; var u = D.p[i][j] - D.b[i], uc = D.r[i] != null ? D.b[i]*D.r[i]*months(c)/12 : null, up = D.p[ip][j] != null ? D.p[ip][j] - D.b[ip] : null;
      h += '<tr><td>'+c.slice(0,4)+'年'+(+c.slice(5))+'月</td><td>'+D.p[i][j].toFixed(3)+'</td><td>'+u.toFixed(3)+'</td><td>'+(u/D.b[i]*100).toFixed(2)+'%</td><td>'+(uc == null ? '—' : uc.toFixed(3))+'</td><td>'+(uc == null ? '—' : (u-uc >= 0 ? '+' : '')+(u-uc).toFixed(3))+'</td><td>'+(up == null ? '—' : up.toFixed(3))+'</td><td>'+(up == null ? '—' : (u-up >= 0 ? '+' : '')+(u-up).toFixed(3))+'</td></tr>'; }});
    document.getElementById('sfc-tab').innerHTML = h;
  }}
  Array.prototype.forEach.call(document.querySelectorAll('.sfc-r'), function(b) {{ b.addEventListener('click', function() {{
    Array.prototype.forEach.call(document.querySelectorAll('.sfc-r'), function(x) {{ x.classList.remove('on'); }}); b.classList.add('on'); st.n = +b.getAttribute('data-n'); draw(); }}); }});
  Array.prototype.forEach.call(document.querySelectorAll('.sfc-u'), function(b) {{ b.addEventListener('click', function() {{
    Array.prototype.forEach.call(document.querySelectorAll('.sfc-u'), function(x) {{ x.classList.remove('on'); }}); b.classList.add('on'); st.u = b.getAttribute('data-u'); draw(); }}); }});
  Array.prototype.forEach.call(document.querySelectorAll('.sfc-chk input[data-c]'), function(c) {{ c.addEventListener('change', function() {{ st.on[c.getAttribute('data-c')] = c.checked; draw(); }}); }});
  document.getElementById('sfc-carry').addEventListener('change', function(e) {{ st.carry = e.target.checked ? 1 : 0; draw(); }});
  draw(); table();
}})();
/* ── 股指÷黄金: 时间段选取 (固定容器高度, 重绘只换 SVG 内容, 统计量按区间重算) ── */
(function() {{
  var el = document.getElementById('sgz-data'); if (!el) return;
  var D = JSON.parse(el.textContent), R = D.r, box = document.getElementById('sgz-panels');
  var W = 900, H = 230, PL = 48, PR = 16, PT = 12, PB = 24, iw = W - PL - PR, ih = H - PT - PB;
  var KEYS = {{dg: {{i: 4, name: '道琼斯工业指数 ÷ 黄金', col: '#4a6fa5', ticks: [1,2,5,10,20,50], d: 1, idx: 1, idxn: '道指'}},
               sg: {{i: 5, name: '标普 500 ÷ 黄金', col: '#7a8f5a', ticks: [0.1,0.2,0.5,1,2,5], d: 2, idx: 2, idxn: '标普'}}}};
  var st = {{from: R[0][0], to: R[R.length-1][0], show: {{dg: 1, sg: 1}}}};
  function mAdd(m, k) {{ var y = +m.slice(0,4), mo = +m.slice(5,7) - 1 + k; y += Math.floor(mo/12); mo = ((mo%12)+12)%12; return y + '-' + ('0'+(mo+1)).slice(-2); }}
  function fmt(v, d) {{ return v.toFixed(d); }}
  function f0(v) {{ return Math.round(v).toLocaleString('en-US'); }}
  function median(a) {{ var b = a.slice().sort(function(x,y){{return x-y;}}), n = b.length; return n % 2 ? b[(n-1)/2] : (b[n/2-1] + b[n/2]) / 2; }}
  function panel(key) {{
    var K = KEYS[key], rows = R.filter(function(r) {{ return r[0] >= st.from && r[0] <= st.to; }});
    if (rows.length < 2) rows = R.slice(-2);
    var n = rows.length, vals = rows.map(function(r) {{ return r[K.i]; }});
    var X = function(i) {{ return PL + iw * i / Math.max(n-1, 1); }};
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    var lo = Math.log10(mn / 1.25), hi = Math.log10(mx * 1.25);
    var Y = function(v) {{ return PT + ih * (1 - (Math.log10(v) - lo) / (hi - lo)); }};
    var med = median(vals), cur = (key === 'dg' ? D.td.dg : D.td.sg);
    var pct = Math.round(vals.filter(function(v) {{ return v <= cur; }}).length / n * 1000) / 10;
    var imx = vals.indexOf(mx), imn = vals.indexOf(mn);
    var g = '';
    // 纵轴刻度: 区间内所有 1/2/5 × 10^k, 避免短区间没有刻度
    var ts = []; for (var e = Math.floor(lo) - 1; e <= Math.ceil(hi); e++) [1,1.5,2,3,4,5,7].forEach(function(m) {{ ts.push(m * Math.pow(10, e)); }});
    var lastY = -99; ts.sort(function(a,b){{return b-a;}});
    ts.forEach(function(t) {{ if (!(t >= mn/1.25 && t <= mx*1.25)) return; if (Math.abs(Y(t) - lastY) < 22) return; lastY = Y(t); g += '<line x1="'+PL+'" y1="'+Y(t).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(t).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(Y(t)+3.5).toFixed(1)+'" class="sgr-yt">'+(+t.toPrecision(2))+'</text>'; }});
    g += '<line x1="'+PL+'" y1="'+Y(med).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(med).toFixed(1)+'" class="sgr-med"/><text x="'+(W-PR-4)+'" y="'+(Y(med)-4).toFixed(1)+'" class="sgr-medt" style="text-anchor:end">所选区间中位数 '+fmt(med, K.d)+'</text>';
    var span = n, step = span > 240 ? 60 : span > 120 ? 24 : span > 48 ? 12 : span > 18 ? 6 : 3, xt = '';
    rows.forEach(function(r, i) {{ var mo = +r[0].slice(5,7) - 1, y = +r[0].slice(0,4);
      var ok = step >= 12 ? (mo === 0 && y % (step/12) === 0) : (mo % step === 0);
      if (ok) xt += '<text x="'+X(i).toFixed(1)+'" y="'+(H-6)+'" class="sgr-xt">'+(step >= 12 ? y : r[0])+'</text>'; }});
    var pts = vals.map(function(v, i) {{ return X(i).toFixed(1)+','+Y(v).toFixed(1); }}).join(' ');
    var marks = '';
    [[imx, '峰值'], [imn, '谷底']].forEach(function(a) {{ var i = a[0], right = X(i) < W - 150;
      marks += '<circle cx="'+X(i).toFixed(1)+'" cy="'+Y(vals[i]).toFixed(1)+'" r="3" fill="'+K.col+'"/><text x="'+(right ? X(i)+7 : X(i)-7).toFixed(1)+'" y="'+(Y(vals[i])+4).toFixed(1)+'" class="sgr-lab" style="text-anchor:'+(right?'start':'end')+'">'+rows[i][0]+' '+fmt(vals[i], K.d)+'</text>'; }});
    marks += '<circle cx="'+X(n-1).toFixed(1)+'" cy="'+Y(cur).toFixed(1)+'" r="3.8" fill="'+K.col+'" stroke="#fff" stroke-width="1.2"/>';
    var bands = '';
    rows.forEach(function(r, i) {{ var l = i ? (X(i-1)+X(i))/2 : PL, rr = i < n-1 ? (X(i)+X(i+1))/2 : W-PR;
      var gl = r[6] ? 'COMEX 期金当月均' : '伦敦金月均';
      var tip = r[0]+'||'+K.name+' '+fmt(r[K.i], K.d)+'<br>'+K.idxn+' '+f0(r[K.idx])+' ÷ 金价 $'+f0(r[3])+'（'+gl+'）';
      bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(rr-l,.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-tip="'+tip+'"/>'; }});
    var today = key === 'dg' ? [D.td.dg, D.td.dgd] : [D.td.sg, D.td.sgd];
    var stat = '<div class="sgz-st"><span>今日 <b>'+fmt(today[0], K.d)+'</b><i>'+today[1]+' 收盘</i></span>'
      +'<span>区间分位 <b>'+pct+'%</b><i>'+rows[0][0]+' 至 '+rows[n-1][0]+' 共 '+n+' 个月</i></span>'
      +'<span>区间峰值 <b>'+fmt(mx, K.d)+'</b><i>'+rows[imx][0]+'</i></span><span>区间谷底 <b>'+fmt(mn, K.d)+'</b><i>'+rows[imn][0]+'</i></span></div>';
    return '<div class="sgz-p"><div class="sgr-title">'+K.name+'</div>'+stat+'<svg viewBox="0 0 '+W+' '+H+'" class="sgr-chart" preserveAspectRatio="xMidYMid meet">'+g+'<polyline points="'+pts+'" fill="none" stroke="'+K.col+'" stroke-width="1.5"/>'+marks+xt+bands+'</svg></div>';
  }}
  function render() {{ var h = ''; ['dg','sg'].forEach(function(k) {{ if (st.show[k]) h += panel(k); }}); box.innerHTML = h; }}
  function setRange(f, t) {{ st.from = f; st.to = t; render(); }}
  var LAST = R[R.length-1][0], FIRST = R[0][0];
  Array.prototype.forEach.call(document.querySelectorAll('.sgz-r'), function(b) {{ b.addEventListener('click', function() {{
    Array.prototype.forEach.call(document.querySelectorAll('.sgz-r'), function(x) {{ x.classList.remove('on'); }}); b.classList.add('on');
    var y = +b.getAttribute('data-y'); setRange(y ? (mAdd(LAST, -12*y) < FIRST ? FIRST : mAdd(LAST, -12*y)) : FIRST, LAST);
    document.getElementById('sgz-from').value = ''; document.getElementById('sgz-to').value = ''; }}); }});
  document.getElementById('sgz-go').addEventListener('click', function() {{
    var f = document.getElementById('sgz-from').value || FIRST, t = document.getElementById('sgz-to').value || LAST;
    if (f > t) {{ var x = f; f = t; t = x; }} if (f < FIRST) f = FIRST; if (t > LAST) t = LAST;
    Array.prototype.forEach.call(document.querySelectorAll('.sgz-r'), function(x) {{ x.classList.remove('on'); }}); setRange(f, t); }});
  Array.prototype.forEach.call(document.querySelectorAll('.sgz-chk input'), function(c) {{ c.addEventListener('change', function() {{
    var k = c.getAttribute('data-s'); st.show[k] = c.checked ? 1 : 0; if (!st.show.dg && !st.show.sg) {{ st.show[k] = 1; c.checked = true; }} render(); }}); }});
  render();
}})();
/* ── 标普÷黄金 1929 起长历史: 均线 + 跌破标记 + 回撤 (独立 IIFE, 前缀 sgl-) ── */
(function() {{
  var el = document.getElementById('sgl-data'); if (!el) return;
  var D = JSON.parse(el.textContent), R = D.r, box = document.getElementById('sgl-box');
  var W = 900, H = 330, PL = 48, PR = 16, PT = 14, PB = 26, iw = W - PL - PR, ih = H - PT - PB;
  var st = {{from: R[0][0], ma: 1, ev: 1}};
  function mAdd(m, k) {{ var y = +m.slice(0,4), mo = +m.slice(5,7) - 1 + k; y += Math.floor(mo/12); mo = ((mo%12)+12)%12; return y + '-' + ('0'+(mo+1)).slice(-2); }}
  function f0(v) {{ return Math.round(v).toLocaleString('en-US'); }}
  function render() {{
    var rows = R.filter(function(r) {{ return r[0] >= st.from; }}), n = rows.length;
    if (n < 2) rows = R.slice(-2), n = 2;
    var vals = []; rows.forEach(function(r) {{ vals.push(r[1]); if (st.ma) {{ if (r[4] != null) vals.push(r[4]); if (r[5] != null) vals.push(r[5]); }} }});
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    var lo = Math.log10(mn / 1.2), hi = Math.log10(mx * 1.2);
    var X = function(i) {{ return PL + iw * i / (n - 1); }};
    var Y = function(v) {{ return PT + ih * (1 - (Math.log10(v) - lo) / (hi - lo)); }};
    var g = '';
    // 固定官价期灰带 1934-02 ~ 1971-08
    var a = -1, b = -1; rows.forEach(function(r, i) {{ if (r[0] >= '1934-02' && a < 0) a = i; if (r[0] <= '1971-08') b = i; }});
    if (a >= 0 && b >= a) g += '<rect x="'+X(a).toFixed(1)+'" y="'+PT+'" width="'+Math.max(X(b)-X(a),1).toFixed(1)+'" height="'+ih+'" fill="#d9d3c8" opacity=".45"/><text x="'+((X(a)+X(b))/2).toFixed(1)+'" y="'+(PT+11)+'" class="sgr-xt" style="text-anchor:middle">黄金固定官价期</text>';
    var lastY = -99, ts = []; for (var e = Math.floor(lo) - 1; e <= Math.ceil(hi); e++) [1,1.5,2,3,5,7].forEach(function(m) {{ ts.push(m * Math.pow(10, e)); }});
    ts.sort(function(x,y) {{ return y-x; }});
    ts.forEach(function(t) {{ if (!(t >= mn/1.2 && t <= mx*1.2)) return; if (Math.abs(Y(t) - lastY) < 20) return; lastY = Y(t);
      g += '<line x1="'+PL+'" y1="'+Y(t).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(t).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(Y(t)+3.5).toFixed(1)+'" class="sgr-yt">'+(t >= 1 ? +t.toFixed(1) : +t.toFixed(2))+'</text>'; }});
    var step = n > 600 ? 120 : n > 240 ? 60 : 24, xt = '';
    rows.forEach(function(r, i) {{ var mo = +r[0].slice(5,7) - 1, y = +r[0].slice(0,4); if (mo === 0 && y % (step/12) === 0) xt += '<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" class="sgr-xt">'+y+'</text>'; }});
    function line(idx, col, w, dash) {{ var p = []; rows.forEach(function(r, i) {{ if (r[idx] != null) p.push(X(i).toFixed(1)+','+Y(r[idx]).toFixed(1)); }});
      return p.length > 1 ? '<polyline points="'+p.join(' ')+'" fill="none" stroke="'+col+'" stroke-width="'+w+'"'+(dash ? ' stroke-dasharray="'+dash+'"' : '')+' stroke-linejoin="round"/>' : ''; }}
    if (st.ma) {{ g += line(5, '#8a4b2f', 1.3, '5 3') + line(4, '#c0793a', 1.3, ''); }}
    g += line(1, '#1f3a68', 1.8, '');
    var marks = '';
    if (st.ev) D.ev.forEach(function(m) {{ var i = -1; rows.forEach(function(r, k) {{ if (r[0] === m) i = k; }}); if (i < 0) return;
      marks += '<line x1="'+X(i).toFixed(1)+'" y1="'+PT+'" x2="'+X(i).toFixed(1)+'" y2="'+(PT+ih)+'" stroke="#b0493a" stroke-width="1" stroke-dasharray="3 3"/><circle cx="'+X(i).toFixed(1)+'" cy="'+Y(rows[i][1]).toFixed(1)+'" r="4" fill="#b0493a" stroke="#fff" stroke-width="1.2"/><text x="'+(X(i) > W - 150 ? X(i)-6 : X(i)+6).toFixed(1)+'" y="'+(PT+24)+'" class="sgr-lab" style="fill:#b0493a;text-anchor:'+(X(i) > W - 150 ? 'end' : 'start')+'">'+m+' 跌破两线</text>'; }});
    var cur = rows[n-1];
    marks += '<circle cx="'+X(n-1).toFixed(1)+'" cy="'+Y(cur[1]).toFixed(1)+'" r="3.8" fill="#1f3a68" stroke="#fff" stroke-width="1.2"/>';
    var bands = '';
    rows.forEach(function(r, i) {{ var l = i ? (X(i-1)+X(i))/2 : PL, rr = i < n-1 ? (X(i)+X(i+1))/2 : W-PR;
      var official = r[0] >= '1934-02' && r[0] <= '1971-08' ? '<br>（该月黄金为固定官价，比值≈指数本身）' : '';
      var tip = r[0]+'||标普÷黄金 '+r[1].toFixed(r[1] >= 1 ? 2 : 3)+(r[4] != null ? '<br>MA40月 '+r[4].toFixed(2) : '')+(r[5] != null ? ' · MA78月 '+r[5].toFixed(2) : '')+'<br>标普 '+f0(r[2])+' ÷ 金价 $'+f0(r[3])+official;
      bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(rr-l,.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-tip="'+tip+'"/>'; }});
    var below = cur[4] != null && cur[5] != null && cur[1] < cur[4] && cur[1] < cur[5];
    var stat = '<div class="sgz-st"><span>最新 <b>'+cur[1].toFixed(3)+'</b><i>'+cur[0]+'（当月未走完）</i></span>'
      +'<span>MA40月 <b>'+(cur[4] != null ? cur[4].toFixed(3) : '—')+'</b><i>MA78月 '+(cur[5] != null ? cur[5].toFixed(3) : '—')+'</i></span>'
      +'<span>位置 <b>'+(below ? '同时低于两线' : '未同时低于两线')+'</b><i>已连续 '+D.streak+' 个月</i></span></div>';
    var dd = '<div class="sgz-st">'+D.dd.map(function(d) {{ return '<span>'+d.label+' 标普回撤 <b>'+d.pct+'%</b><i>'+d.peak_m+' → '+d.trough_m+'（月均值口径）</i></span>'; }}).join('')+'</div>';
    box.innerHTML = '<div class="sgz-p" style="height:auto"><div class="sgr-title">标普 500 ÷ 黄金（1929 起，对数）</div>'+stat+'<svg viewBox="0 0 '+W+' '+H+'" class="sgr-chart" style="height:290px" preserveAspectRatio="xMidYMid meet">'+g+xt+marks+bands+'</svg>'+dd+'</div>';
  }}
  var LAST = R[R.length-1][0], FIRST = R[0][0];
  Array.prototype.forEach.call(document.querySelectorAll('.sgl-r'), function(b) {{ b.addEventListener('click', function() {{
    Array.prototype.forEach.call(document.querySelectorAll('.sgl-r'), function(x) {{ x.classList.remove('on'); }}); b.classList.add('on');
    var y = +b.getAttribute('data-y'); var f = y ? mAdd(LAST, -12*y) : FIRST; st.from = f < FIRST ? FIRST : f; render(); }}); }});
  document.getElementById('sgl-ma').addEventListener('change', function(e) {{ st.ma = e.target.checked ? 1 : 0; render(); }});
  document.getElementById('sgl-ev').addEventListener('change', function(e) {{ st.ev = e.target.checked ? 1 : 0; render(); }});
  render();
}})();
/* ── 美债三图: 2Y/10Y/30Y · 期限溢价+MOVE+10Y · AGG/BND 代理 (独立 IIFE, 前缀 ust-; 悬停显示日期+各线数值) ── */
(function() {{
  function build(which, spec) {{
    var el = document.getElementById('ust-' + which + '-data'); if (!el) return;
    var D = JSON.parse(el.textContent), box = document.getElementById('ust-' + which + '-box');
    var W = 900, H = 300, PL = 46, PR = spec.right ? 46 : 16, PT = 14, PB = 26, iw = W - PL - PR, ih = H - PT - PB;
    var dates = []; var mapS = spec.series.map(function(s) {{ var m = {{}}; (D[s.key] || []).forEach(function(p) {{ m[p[0]] = p[1]; if (dates.indexOf(p[0]) < 0) dates.push(p[0]); }}); return m; }});
    dates.sort(); var n = dates.length; if (n < 2) {{ box.innerHTML = '<p class="empty">数据点不足</p>'; return; }}
    var X = function(i) {{ return PL + iw * i / (n - 1); }};
    function range(side) {{ var a = [];
      spec.series.forEach(function(s, k) {{ if (s.axis !== side) return; dates.forEach(function(d) {{ var v = mapS[k][d]; if (v != null) a.push(v); }}); }});
      if (!a.length) return null; var lo = Math.min.apply(null, a), hi = Math.max.apply(null, a), pad = (hi - lo) * 0.08 || 1;
      if (spec.zero && side === 'L') lo = Math.min(0, lo); else lo -= pad; hi += pad; return [lo, hi]; }}
    var RL = range('L'), RR = range('R');
    var YL = function(v) {{ return PT + ih * (1 - (v - RL[0]) / (RL[1] - RL[0])); }};
    var YR = RR ? function(v) {{ return PT + ih * (1 - (v - RR[0]) / (RR[1] - RR[0])); }} : null;
    function nice(lo, hi, k) {{ var step = (hi - lo) / k, p = Math.pow(10, Math.floor(Math.log10(step))), f = step / p; var st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, a = []; for (var v = Math.ceil(lo / st) * st; v <= hi; v += st) a.push(v); return a; }}
    var g = '';
    (spec.bands || []).forEach(function(b) {{ var a = -1, z = -1; dates.forEach(function(d, i) {{ if (d >= b[0] && a < 0) a = i; if (d <= b[1]) z = i; }});
      if (a >= 0 && z > a) g += '<rect x="'+X(a).toFixed(1)+'" y="'+PT+'" width="'+(X(z)-X(a)).toFixed(1)+'" height="'+ih+'" fill="#d9d3c8" opacity=".5"/><text x="'+((X(a)+X(z))/2).toFixed(1)+'" y="'+(PT+11)+'" class="sgr-xt" style="text-anchor:middle">'+b[2]+'</text>'; }});
    nice(RL[0], RL[1], 5).forEach(function(v) {{ g += '<line x1="'+PL+'" y1="'+YL(v).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+YL(v).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(YL(v)+3.5).toFixed(1)+'" class="sgr-yt">'+(+v.toFixed(spec.dl))+'</text>'; }});
    if (RR) {{ var gl = nice(RL[0], RL[1], 5); gl.forEach(function(v) {{ var f = (v - RL[0]) / (RL[1] - RL[0]), rv = RR[0] + f * (RR[1] - RR[0]); g += '<text x="'+(W-PR+6)+'" y="'+(YL(v)+3.5).toFixed(1)+'" class="sgr-yt" style="text-anchor:start;fill:'+spec.rc+'">'+Math.round(rv)+'</text>'; }}); }}
    g += '<text x="'+(PL-6)+'" y="10" class="sgr-yt">'+spec.ul+'</text>' + (RR ? '<text x="'+(W-PR+6)+'" y="10" class="sgr-yt" style="text-anchor:start;fill:'+spec.rc+'">'+spec.ur+'</text>' : '');
    var step = n > 300 ? 52 : n > 120 ? 26 : n > 60 ? 13 : 5, xt = '', lastYr = '';
    dates.forEach(function(d, i) {{ var y = d.slice(0,4), m = d.slice(5,7); var tick = n > 300 ? (m === '01' && y !== lastYr) : (m === '01' || m === '04' || m === '07' || m === '10') && (d.slice(0,7) !== lastYr);
      if (tick) {{ lastYr = n > 300 ? y : d.slice(0,7); xt += '<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" class="sgr-xt">'+(n > 300 ? y : d.slice(2,7))+'</text>'; }} }});
    spec.series.forEach(function(s, k) {{ var Y = s.axis === 'R' ? YR : YL, p = [];
      dates.forEach(function(d, i) {{ var v = mapS[k][d]; if (v != null) p.push(X(i).toFixed(1)+','+Y(v).toFixed(1)); }});
      if (p.length > 1) g += '<polyline points="'+p.join(' ')+'" fill="none" stroke="'+s.col+'" stroke-width="'+(s.w || 1.6)+'"'+(s.dash ? ' stroke-dasharray="5 3"' : '')+' stroke-linejoin="round"/>'; }});
    var bands = '';
    dates.forEach(function(d, i) {{ var l = i ? (X(i-1)+X(i))/2 : PL, r = i < n-1 ? (X(i)+X(i+1))/2 : W-PR;
      var tip = d + '||' + spec.series.map(function(s, k) {{ var v = mapS[k][d]; if (v == null) {{ var best = null; Object.keys(mapS[k]).forEach(function(dd) {{ if (dd <= d && (best == null || dd > best)) best = dd; }}); return s.name + ' ' + (best ? (+mapS[k][best].toFixed(s.d)) + '（' + best + '）' : '—'); }} return s.name + ' ' + (+v.toFixed(s.d)) + (s.unit || ''); }}).join('<br>');
      bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(r-l,.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-tip="'+tip+'"/>'; }});
    var leg = '<div class="sgz-st">' + spec.series.map(function(s) {{ var L = D.last && D.last[s.lk], PX = D.px && D.px[s.lk]; return '<span><i style="display:inline-block;width:14px;height:3px;background:'+s.col+';margin-right:5px;vertical-align:middle"></i>'+s.name+' <b>'+(L ? (+L.v.toFixed(s.d)) + (s.unit || '') : '—')+'</b><i>'+(L ? L.d : '')+(PX ? '（实际价格 $'+PX.v+'）' : '')+'</i></span>'; }}).join('') + (D.d0 ? '<span><i style="font-style:normal">起点日 '+D.d0+'</i></span>' : '') + '</div>';
    box.innerHTML = '<div class="sgz-p" style="height:auto"><div class="sgr-title">'+spec.title+'</div>'+leg+'<svg viewBox="0 0 '+W+' '+H+'" class="sgr-chart" style="height:270px" preserveAspectRatio="xMidYMid meet">'+g+xt+bands+'</svg></div>';
  }}
  build('yld', {{title: '美国 2 年 / 10 年 / 30 年国债收益率（2019 年至今 · 周度）', ul: '收益率 %', dl: 1, zero: true, bands: [['2020-02-14', '2020-04-30', '2020 衰退']],
    series: [{{key: 'y2', lk: 'y2', name: '2 年', col: '#2f8a6a', axis: 'L', d: 2, unit: '%'}}, {{key: 'y10', lk: 'y10', name: '10 年', col: '#1f3a68', axis: 'L', d: 2, unit: '%'}}, {{key: 'y30', lk: 'y30', name: '30 年', col: '#b0493a', axis: 'L', d: 2, unit: '%'}}]}});
  build('tpm', {{title: '10 年期限溢价 · MOVE 波动率 · 10 年收益率（近 2 年 · 周度）', ul: '% (期限溢价/10Y)', ur: 'MOVE 指数', rc: '#b0493a', right: true, dl: 1,
    series: [{{key: 'tp', lk: 'tp', name: '10Y 期限溢价(ACM)', col: '#2f8a8a', axis: 'L', d: 2, unit: '%'}}, {{key: 'y10', lk: 'y10', name: '10Y 收益率', col: '#c0a030', axis: 'L', d: 2, unit: '%'}}, {{key: 'move', lk: 'move', name: 'MOVE', col: '#b0493a', axis: 'R', d: 1, dash: true}}]}});
  build('agg', {{title: '彭博美综指的 ETF 代理 · AGG 与 BND（起点=100 的相对值 · 近 2 年 · 日度）', ul: '相对值(起点=100)', dl: 0,
    series: [{{key: 'agg', lk: 'agg', name: 'AGG', col: '#6a4c93', axis: 'L', d: 2, w: 2}}, {{key: 'bnd', lk: 'bnd', name: 'BND', col: '#e0a030', axis: 'L', d: 2, w: 1.2, dash: true}}]}});
}})();
/* ── 日元套息: CFTC 净头寸 · 美日利差 vs USDJPY · USDJPY 周K+均线+已实现波动率 (独立 IIFE, 前缀 jpy-; 悬停显示日期+各线数值) ── */
(function() {{
  function get(w) {{ var e = document.getElementById('jpy-' + w + '-data'); return e ? [JSON.parse(e.textContent), document.getElementById('jpy-' + w + '-box')] : null; }}
  function nice(lo, hi, k) {{ var step = (hi - lo) / k, p = Math.pow(10, Math.floor(Math.log10(step))), f = step / p, st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, a = []; for (var v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) a.push(v); return a; }}
  function xticks(dates, X, H) {{ var t = '', last = ''; dates.forEach(function(d, i) {{ var m = d.slice(5,7), q = d.slice(0,4) + m; if ((m === '01' || m === '04' || m === '07' || m === '10') && q !== last) {{ last = q; t += '<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" class="sgr-xt">'+d.slice(2,7)+'</text>'; }} }}); return t; }}
  function legend(items) {{ return '<div class="sgz-st">' + items.map(function(s) {{ return '<span><i style="display:inline-block;width:14px;height:3px;background:'+s.col+';margin-right:5px;vertical-align:middle"></i>'+s.name+' <b>'+s.val+'</b><i>'+s.d+'</i></span>'; }}).join('') + '</div>'; }}
  /* 通用折线/柱 */
  function line(box, title, spec) {{
    var D = spec.D, W = 900, H = spec.h || 300, PL = 54, PR = spec.right ? 54 : 16, PT = 14, PB = 26, iw = W - PL - PR, ih = H - PT - PB;
    var dates = [], maps = spec.series.map(function(s) {{ var m = {{}}; (D[s.key] || []).forEach(function(p) {{ m[p[0]] = p[1]; if (dates.indexOf(p[0]) < 0) dates.push(p[0]); }}); return m; }});
    dates.sort(); var n = dates.length; if (n < 2) {{ box.innerHTML = '<p class="empty">数据点不足</p>'; return; }}
    var X = function(i) {{ return PL + iw * i / (n - 1); }};
    function rng(side) {{ var a = []; spec.series.forEach(function(s, k) {{ if (s.axis !== side) return; dates.forEach(function(d) {{ var v = maps[k][d]; if (v != null) a.push(v); }}); }}); if (!a.length) return null; var lo = Math.min.apply(null, a), hi = Math.max.apply(null, a), pad = (hi - lo) * 0.08 || 1; if (spec.bar && side === 'L') {{ lo = Math.min(lo, 0); hi = Math.max(hi, 0); }} return [lo - (spec.bar && side === 'L' ? 0 : pad), hi + (spec.bar && side === 'L' ? pad : pad)]; }}
    var RL = rng('L'), RR = rng('R');
    var YL = function(v) {{ return PT + ih * (1 - (v - RL[0]) / (RL[1] - RL[0])); }};
    var YR = RR ? function(v) {{ var f = (v - RR[0]) / (RR[1] - RR[0]); return PT + ih * (spec.flipR ? f : 1 - f); }} : null;
    var g = '';
    var gl = nice(RL[0], RL[1], 5);
    gl.forEach(function(v) {{ g += '<line x1="'+PL+'" y1="'+YL(v).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+YL(v).toFixed(1)+'" class="sgr-grid"'+(spec.bar && Math.abs(v) < (RL[1]-RL[0])*1e-6 ? ' style="stroke:#3d372f;stroke-width:1.4"' : '')+'/><text x="'+(PL-6)+'" y="'+(YL(v)+3.5).toFixed(1)+'" class="sgr-yt">'+(+v.toFixed(spec.dl))+'</text>'; }});
    if (RR) gl.forEach(function(v) {{ var f = (v - RL[0]) / (RL[1] - RL[0]), rv = spec.flipR ? RR[1] - f * (RR[1] - RR[0]) : RR[0] + f * (RR[1] - RR[0]); g += '<text x="'+(W-PR+6)+'" y="'+(YL(v)+3.5).toFixed(1)+'" class="sgr-yt" style="text-anchor:start;fill:'+spec.rc+'">'+(+rv.toFixed(spec.dr || 0))+'</text>'; }});
    g += '<text x="'+(PL-6)+'" y="10" class="sgr-yt">'+spec.ul+'</text>' + (RR ? '<text x="'+(W-PR+6)+'" y="10" class="sgr-yt" style="text-anchor:start;fill:'+spec.rc+'">'+spec.ur+'</text>' : '');
    spec.series.forEach(function(s, k) {{
      var Y = s.axis === 'R' ? YR : YL;
      if (spec.bar && s.bar) {{ var bw = Math.max(iw / n * (s.bw || 0.8), 1.2), y0 = YL(0); dates.forEach(function(d, i) {{ var v = maps[k][d]; if (v == null) return; var y = YL(v); g += '<rect x="'+(X(i)-bw/2+(s.off||0)).toFixed(1)+'" y="'+Math.min(y,y0).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(Math.abs(y-y0),.6).toFixed(1)+'" fill="'+(s.colNeg && v < 0 ? s.colNeg : s.col)+'" opacity="'+(s.op||1)+'"/>'; }}); return; }}
      var p = []; dates.forEach(function(d, i) {{ var v = maps[k][d]; if (v != null) p.push(X(i).toFixed(1)+','+Y(v).toFixed(1)); }});
      if (p.length > 1) g += '<polyline points="'+p.join(' ')+'" fill="none" stroke="'+s.col+'" stroke-width="'+(s.w || 1.6)+'"'+(s.dash ? ' stroke-dasharray="5 3"' : '')+' stroke-linejoin="round"/>'; }});
    var bands = '';
    dates.forEach(function(d, i) {{ var l = i ? (X(i-1)+X(i))/2 : PL, r = i < n-1 ? (X(i)+X(i+1))/2 : W-PR;
      var tip = d + '||' + spec.series.map(function(s, k) {{ var v = maps[k][d]; if (v == null) return s.name + ' —'; return s.name + ' ' + (spec.fmt ? spec.fmt(v) : (+v.toFixed(s.d))) + (s.unit || ''); }}).join('<br>');
      bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(r-l,.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-tip="'+tip+'"/>'; }});
    var lg = legend(spec.series.map(function(s) {{ var L = spec.last[s.lk]; return {{col: s.col, name: s.name, val: L ? (spec.lfmt ? spec.lfmt(L.v) : (+L.v.toFixed(s.d))) + (s.unit || '') : '—', d: L ? L.d : ''}}; }}));
    box.innerHTML = '<div class="sgz-p" style="height:auto"><div class="sgr-title">'+title+'</div>'+lg+'<svg viewBox="0 0 '+W+' '+H+'" class="sgr-chart" style="height:'+(H-30)+'px" preserveAspectRatio="xMidYMid meet">'+g+xticks(dates, X, H)+bands+'</svg></div>';
  }}
  var a = get('cftc'); if (a) line(a[1], '日元期货 CFTC 净头寸（近 3 年 · 周度 · 手）', {{D: a[0], bar: true, dl: 0, ul: '手', last: a[0].last, lfmt: function(v) {{ return (v > 0 ? '+' : '') + Math.round(v); }}, fmt: function(v) {{ return (v > 0 ? '+' : '') + Math.round(v); }},
    series: [{{key: 'noncomm', lk: 'noncomm', name: '非商业净头寸', col: '#2f6f9f', colNeg: '#c0553a', axis: 'L', bar: true, bw: 0.8, unit: ' 手'}}, {{key: 'lev', lk: 'lev', name: '杠杆基金净头寸', col: '#e0a030', axis: 'L', w: 1.8, d: 0, unit: ' 手'}}]}});
  var b = get('spread'); if (b) line(b[1], '美日 10 年利差 vs 美元/日元（近 2 年 · 周度；右轴反转：向上＝日元走强）', {{D: b[0], right: true, flipR: true, dl: 1, dr: 0, ul: '利差（百分点）', ur: '美元/日元（反转）', rc: '#b0493a', last: b[0].last,
    series: [{{key: 'spread', lk: 'spread', name: '美日10Y利差', col: '#2f6f9f', axis: 'L', d: 2, unit: ' 个百分点', w: 2}}, {{key: 'usdjpy', lk: 'usdjpy', name: '美元/日元', col: '#b0493a', axis: 'R', d: 2, w: 1.6}}]}});
  var c = get('kline'); if (c) {{
    var K = c[0].kl, box = c[1], W = 900, H1 = 280, H2 = 110, PL = 54, PR = 16, PT = 14, PB = 4, iw = W - PL - PR, n = K.length;
    var X = function(i) {{ return PL + iw * (i + 0.5) / n; }}, lo = 1e9, hi = -1e9;
    K.forEach(function(k) {{ lo = Math.min(lo, k.l); hi = Math.max(hi, k.h); [k.ma5, k.ma10, k.ma20, k.ma30].forEach(function(m) {{ if (m != null) {{ lo = Math.min(lo, m); hi = Math.max(hi, m); }} }}); }});
    var pad = (hi - lo) * 0.05; lo -= pad; hi += pad; var ih1 = H1 - PT - PB, Y = function(v) {{ return PT + ih1 * (1 - (v - lo) / (hi - lo)); }}, g = '', bw = Math.max(iw / n * 0.62, 1.4);
    nice(lo, hi, 6).forEach(function(v) {{ g += '<line x1="'+PL+'" y1="'+Y(v).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(v).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(Y(v)+3.5).toFixed(1)+'" class="sgr-yt">'+Math.round(v)+'</text>'; }});
    g += '<line x1="'+PL+'" y1="'+Y(160).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Y(160).toFixed(1)+'" stroke="#b0493a" stroke-width="1" stroke-dasharray="3 4" opacity=".7"/><text x="'+(W-PR-2)+'" y="'+(Y(160)-3).toFixed(1)+'" class="sgr-xt" style="text-anchor:end;fill:#b0493a">160</text>';
    K.forEach(function(k, i) {{ var up = k.c >= k.o, col = up ? '#c0553a' : '#2f8a6a'; g += '<line x1="'+X(i).toFixed(1)+'" y1="'+Y(k.h).toFixed(1)+'" x2="'+X(i).toFixed(1)+'" y2="'+Y(k.l).toFixed(1)+'" stroke="'+col+'" stroke-width="1"/><rect x="'+(X(i)-bw/2).toFixed(1)+'" y="'+Math.min(Y(k.o),Y(k.c)).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(Math.abs(Y(k.o)-Y(k.c)),.8).toFixed(1)+'" fill="'+col+'"/>'; }});
    var MA = [['ma5','#6a4c93','MA5'],['ma10','#2f6f9f','MA10'],['ma20','#e0a030','MA20'],['ma30','#555','MA30']];
    MA.forEach(function(m) {{ var p = []; K.forEach(function(k, i) {{ if (k[m[0]] != null) p.push(X(i).toFixed(1)+','+Y(k[m[0]]).toFixed(1)); }}); if (p.length > 1) g += '<polyline points="'+p.join(' ')+'" fill="none" stroke="'+m[1]+'" stroke-width="1.3"/>'; }});
    var bands = ''; K.forEach(function(k, i) {{ var l = PL + iw * i / n, tip = k.d + '（周）||开 '+k.o+' 高 '+k.h+' 低 '+k.l+' 收 '+k.c+'<br>' + MA.map(function(m) {{ return m[2] + ' ' + (k[m[0]] == null ? '—' : k[m[0]]); }}).join(' · ');
      bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+(iw/n).toFixed(2)+'" height="'+ih1+'" fill="transparent" data-tip="'+tip+'"/>'; }});
    var xt = '', lastq = ''; K.forEach(function(k, i) {{ var m = k.d.slice(5,7), q = k.d.slice(0,4)+m; if ((m === '01' || m === '04' || m === '07' || m === '10') && q !== lastq) {{ lastq = q; xt += '<text x="'+X(i).toFixed(1)+'" y="'+(H1+2)+'" class="sgr-xt" style="dominant-baseline:hanging">'+k.d.slice(2,7)+'</text>'; }} }});
    var RV = c[0].rv, rvmap = {{}}; RV.forEach(function(p) {{ rvmap[p[0]] = p[1]; }});
    var rv = RV.map(function(p) {{ return p[1]; }}), rlo = 0, rhi = Math.max.apply(null, rv) * 1.1, ih2 = H2 - 18, YV = function(v) {{ return 6 + ih2 * (1 - (v - rlo) / (rhi - rlo)); }}, g2 = '';
    nice(rlo, rhi, 3).forEach(function(v) {{ g2 += '<line x1="'+PL+'" y1="'+YV(v).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+YV(v).toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(YV(v)+3.5).toFixed(1)+'" class="sgr-yt">'+(+v.toFixed(0))+'</text>'; }});
    var rn = RV.length, XR = function(i) {{ return PL + iw * i / (rn - 1); }}, pp = RV.map(function(p, i) {{ return XR(i).toFixed(1)+','+YV(p[1]).toFixed(1); }});
    var lq2 = ''; RV.forEach(function(p, i) {{ var m = p[0].slice(5,7), q = p[0].slice(0,4)+m; if ((m === '01' || m === '04' || m === '07' || m === '10') && q !== lq2) {{ lq2 = q; g2 += '<text x="'+XR(i).toFixed(1)+'" y="'+(H2+8)+'" class="sgr-xt">'+p[0].slice(2,7)+'</text>'; }} }});
    g2 += '<polyline points="'+pp.join(' ')+'" fill="none" stroke="#1f7a7a" stroke-width="1.8"/>';
    var b2 = ''; RV.forEach(function(p, i) {{ var l = i ? (XR(i-1)+XR(i))/2 : PL, r = i < rn-1 ? (XR(i)+XR(i+1))/2 : W-PR; b2 += '<rect x="'+l.toFixed(1)+'" y="6" width="'+Math.max(r-l,.6).toFixed(2)+'" height="'+ih2+'" fill="transparent" data-tip="'+p[0]+'||20日已实现波动率 '+p[1]+'%（年化）"/>'; }});
    var L = c[0].last, lk = K[K.length-1];
    var lg = legend([{{col:'#c0553a',name:'美元/日元 收',val:lk.c,d:lk.d}},{{col:'#6a4c93',name:'MA5',val:lk.ma5,d:''}},{{col:'#2f6f9f',name:'MA10',val:lk.ma10,d:''}},{{col:'#e0a030',name:'MA20',val:lk.ma20,d:''}},{{col:'#555',name:'MA30',val:lk.ma30,d:''}},{{col:'#1f7a7a',name:'20日已实现波动率(年化)',val:(c[0].last_rv||{{}}).v+'%',d:(c[0].last_rv||{{}}).d}}]);
    box.innerHTML = '<div class="sgz-p" style="height:auto"><div class="sgr-title">美元/日元周 K 线 + MA5/10/20/30 周 + 20 日已实现波动率（近 2.5 年）</div>'+lg+'<svg viewBox="0 0 '+W+' '+(H1+16)+'" class="sgr-chart" style="height:'+(H1-10)+'px" preserveAspectRatio="xMidYMid meet">'+g+xt+bands+'</svg>'
      +'<div class="sgr-title" style="margin-top:2px;font-size:12px;color:#6b645a">20 日已实现波动率（年化 %，代理；不是隐含波动率）</div><svg viewBox="0 0 '+W+' '+(H2+14)+'" class="sgr-chart" style="height:'+(H2+4)+'px" preserveAspectRatio="xMidYMid meet">'+g2+b2+'</svg></div>';
  }}
}})();
/* ── 比特币 ÷ 黄金: 时间段 + 三条线 + 事件 (固定容器高度, 重绘只换 SVG 内容, 不触发布局位移) ── */
(function() {{
  var el = document.getElementById('btcg-data'); if (!el) return;
  var D = JSON.parse(el.textContent);
  var box = document.getElementById('btcg-chart'), pin = document.getElementById('btcg-pin');
  var W = 900, H = 380, PL = 54, PR = 54, PT = 16, PB = 28, iw = W - PL - PR, ih = H - PT - PB;
  var COL = {{r:'#1f3a68', m2:'#2f6b4f', debt:'#b0493a'}};
  var st = {{from: D.r[0][0], to: D.r[D.r.length-1][0], show: {{r:1, m2:1, debt:1, ev:1}}}};
  var pinned = null;
  function mAdd(m, k) {{ var y = +m.slice(0,4), mo = +m.slice(5,7) - 1 + k; y += Math.floor(mo/12); mo = ((mo%12)+12)%12; return y + '-' + ('0'+(mo+1)).slice(-2); }}
  function allMonths() {{ var a = [], m = D.r[0][0], e = D.r[D.r.length-1][0]; while (m <= e) {{ a.push(m); m = mAdd(m, 1); }} return a; }}
  var MONTHS = allMonths();
  function lerpSeries(arr, vi) {{ var m = {{}}; arr.forEach(function(x){{ m[x[0]] = x[vi]; }}); return m; }}
  var mapR = lerpSeries(D.r, 1), mapBtc = lerpSeries(D.r, 2), mapGold = lerpSeries(D.r, 3), mapM2 = lerpSeries(D.m2, 1), mapN = lerpSeries(D.m2, 2), mapDebt = lerpSeries(D.debt, 1);
  function fmt(v, d) {{ return v == null ? '—' : v.toLocaleString('en-US', {{maximumFractionDigits: d}}); }}
  function render() {{
    var ms = MONTHS.filter(function(m) {{ return m >= st.from && m <= st.to; }});
    if (ms.length < 2) ms = MONTHS.slice(-2);
    var n = ms.length, X = function(i) {{ return PL + iw * i / (n - 1); }};
    // 左轴(对数): 比特币÷黄金, 范围随所选区间自适应
    var rv = ms.map(function(m) {{ return mapR[m]; }}).filter(function(v) {{ return v > 0; }});
    var lo = Math.log10(Math.min.apply(null, rv)) - 0.15, hi = Math.log10(Math.max.apply(null, rv)) + 0.15;
    var YL = function(v) {{ return PT + ih * (1 - (Math.log10(v) - lo) / (hi - lo)); }};
    // 右轴(线性): 货币供应 + 联邦债务, 取所选区间内两线最大值
    var rr = [];
    ms.forEach(function(m) {{ if (st.show.m2 && mapM2[m] != null) rr.push(mapM2[m]); if (st.show.debt && mapDebt[m] != null) rr.push(mapDebt[m]); }});
    var rmax = rr.length ? Math.max.apply(null, rr) * 1.06 : 1, rmin = 0;
    var YR = function(v) {{ return PT + ih * (1 - (v - rmin) / (rmax - rmin)); }};
    var g = '';
    var ticksL = []; for (var e = Math.ceil(lo); e <= Math.floor(hi); e++) ticksL.push(Math.pow(10, e));
    ticksL.forEach(function(v) {{ var y = YL(v); g += '<line x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y.toFixed(1)+'" class="sgr-grid"/><text x="'+(PL-6)+'" y="'+(y+3.5).toFixed(1)+'" class="sgr-yt" fill="'+COL.r+'">'+(v>=1?v:v.toPrecision(1))+'</text>'; }});
    var nt = 5; for (var k = 0; k <= nt; k++) {{ var v = rmin + (rmax - rmin) * k / nt, y = YR(v); g += '<text x="'+(W-PR+6)+'" y="'+(y+3.5).toFixed(1)+'" class="sgr-yt" style="text-anchor:start" fill="'+COL.m2+'">'+v.toFixed(v<10?1:0)+'</text>'; }}
    g += '<text x="'+(PL-6)+'" y="10" class="sgr-yt" fill="'+COL.r+'">盎司/比特币</text><text x="'+(W-PR+6)+'" y="10" class="sgr-yt" style="text-anchor:start" fill="'+COL.m2+'">万亿美元</text>';
    var span = ms.length, step = span > 120 ? 24 : span > 60 ? 12 : span > 24 ? 6 : 3, xt = '';
    ms.forEach(function(m, i) {{ var mo = +m.slice(5,7) - 1; if (mo % (step >= 12 ? 12 : step) === 0 && (step < 12 || mo === 0) && (step >= 12 ? (+m.slice(0,4)) % (step/12) === 0 : true)) xt += '<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" class="sgr-xt">'+(step >= 12 ? m.slice(0,4) : m)+'</text>'; }});
    function line(map, Y, color, w) {{ var pts = [], seg = ''; ms.forEach(function(m, i) {{ var v = map[m]; if (v != null && v > 0) pts.push(X(i).toFixed(1)+','+Y(v).toFixed(1)); else if (pts.length) {{ seg += '<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+color+'" stroke-width="'+w+'"/>'; pts = []; }} }}); if (pts.length) seg += '<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+color+'" stroke-width="'+w+'"/>'; return seg; }}
    var body = '';
    if (st.show.m2) body += line(mapM2, YR, COL.m2, 1.6);
    if (st.show.debt) {{ // 联邦债务是季度点, 用阶梯连线避免被误读成月度
      var pts = []; ms.forEach(function(m, i) {{ var v = mapDebt[m]; if (v != null) pts.push(X(i).toFixed(1)+','+YR(v).toFixed(1)); }});
      if (pts.length) {{ body += '<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+COL.debt+'" stroke-width="1.6" stroke-dasharray="5,3"/>';
        ms.forEach(function(m, i) {{ if (mapDebt[m] != null) body += '<circle cx="'+X(i).toFixed(1)+'" cy="'+YR(mapDebt[m]).toFixed(1)+'" r="1.8" fill="'+COL.debt+'"/>'; }}); }}
    }}
    if (st.show.r) body += line(mapR, YL, COL.r, 1.9);
    // 事件标记: 落在所选区间内, 逐个检测间距错开
    var marks = '', placed = [], evIn = [], idx = {{}}; ms.forEach(function(m, i) {{ idx[m] = i; }});
    D.ev.forEach(function(e, k) {{ var m = e.d.slice(0,7); if (idx[m] == null) return; e._k = k + 1; evIn.push(e);
      if (!st.show.ev || !st.show.r) return;
      var i = idx[m], cx = X(i), cy = YL(mapR[m]), off = null;
      for (var step2 = 0; step2 < 9 && off == null; step2++) {{ [-1, 1].forEach(function(sg) {{ if (off != null) return; var c = sg * (12 + step2 * 10), ty = cy + c;
          if (ty >= PT + 6 && ty <= H - PB - 4 && !placed.some(function(p) {{ return Math.hypot(cx - p[0], ty - p[1]) < 14; }})) off = c; }}); }}
      if (off == null) off = -12; placed.push([cx, cy + off]);
      var col = e.c === 'high' ? '#2f6b4f' : '#b07a5a';
      marks += '<line x1="'+cx.toFixed(1)+'" y1="'+cy.toFixed(1)+'" x2="'+cx.toFixed(1)+'" y2="'+(cy+off+(off<0?5:-5)).toFixed(1)+'" stroke="'+col+'" stroke-width=".6" opacity=".6"/>'
            +'<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="2.6" fill="'+col+'"/>'
            +'<circle cx="'+cx.toFixed(1)+'" cy="'+(cy+off-3).toFixed(1)+'" r="6.2" fill="#fbfaf7" stroke="'+col+'" stroke-width=".7"/>'
            +'<text x="'+cx.toFixed(1)+'" y="'+(cy+off).toFixed(1)+'" class="btcg-n" fill="'+col+'">'+e._k+'</text>'; }});
    // 锁定线 + 命中带(每月一条, 悬停/点击共用)
    var pinLine = '', bands = '';
    if (pinned && idx[pinned] != null) pinLine = '<line x1="'+X(idx[pinned]).toFixed(1)+'" y1="'+PT+'" x2="'+X(idx[pinned]).toFixed(1)+'" y2="'+(H-PB)+'" stroke="#8a837a" stroke-width="1" stroke-dasharray="3,3"/>';
    ms.forEach(function(m, i) {{ var l = i ? (X(i-1)+X(i))/2 : PL, r = i < n-1 ? (X(i)+X(i+1))/2 : W-PR; bands += '<rect x="'+l.toFixed(1)+'" y="'+PT+'" width="'+Math.max(r-l,.6).toFixed(2)+'" height="'+ih+'" fill="transparent" data-m="'+m+'"/>'; }});
    box.innerHTML = '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'+g+xt+body+marks+pinLine+bands+'</svg>';
    // 事件表: 固定 tbody, 只替换行
    var rows = ''; evIn.forEach(function(e) {{ var col = e.c === 'high' ? '#2f6b4f' : '#b07a5a', px = e.p ? '$' + (e.p >= 100 ? fmt(e.p, 0) : fmt(e.p, 2)) : '—';
      rows += '<tr><td class="btcg-no" style="color:'+col+'">'+e._k+'</td><td>'+e.d+'</td><td><b>'+esc(e.t)+'</b><br><span class="btcg-d">'+esc(e.x)+'</span></td><td>'+px+'</td><td><a href="'+esc(e.u)+'" target="_blank" rel="noopener">'+esc(e.s||'出处')+'</a></td></tr>'; }});
    document.getElementById('btcg-tb').innerHTML = rows || '<tr><td colspan="5" style="color:#8a837a;padding:14px">所选时间段内没有已核验的事件。</td></tr>';
    document.getElementById('btcg-evn').textContent = evIn.length;
  }}
  function esc(t) {{ return String(t == null ? '' : t).replace(/[&<>"]/g, function(c) {{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]; }}); }}
  function info(m) {{
    var evs = D.ev.filter(function(e) {{ return e.d.slice(0,7) === m; }});
    var h = '<div><b>'+m+'</b>　1 比特币 ≈ <b>'+fmt(mapR[m], mapR[m] < 1 ? 4 : 2)+'</b> 盎司黄金（BTC $'+fmt(mapBtc[m], mapBtc[m] < 100 ? 2 : 0)+' · 黄金 $'+fmt(mapGold[m], 0)+'）</div>';
    h += '<div>全球货币供应 <b>'+fmt(mapM2[m], 1)+'</b> 万亿$'+(mapN[m] ? '（覆盖 '+mapN[m]+' 国）' : '')+'　美国联邦债务 <b>'+(mapDebt[m] != null ? fmt(mapDebt[m], 1) + '</b> 万亿$' : '—</b>（季度，非本月）')+(evs.length ? '　▸ '+esc(evs[0].d+' '+evs[0].t) : '')+'</div>';
    pin.innerHTML = h;
  }}
  function monthAt(ev) {{ var t = ev.target.closest ? ev.target.closest('rect[data-m]') : null; return t ? t.getAttribute('data-m') : null; }}
  box.addEventListener('mousemove', function(ev) {{ if (pinned) return; var m = monthAt(ev); if (m) info(m); }});
  box.addEventListener('mouseleave', function() {{ if (!pinned) pin.textContent = '悬停图上任意位置可看横纵坐标，点击可锁定。'; }});
  box.addEventListener('click', function(ev) {{ var m = monthAt(ev); if (!m) return; pinned = (pinned === m) ? null : m; if (pinned) info(pinned); else pin.textContent = '已取消锁定。悬停图上任意位置可看横纵坐标，点击可锁定。'; render(); }});
  function setRange(from, to) {{ st.from = from; st.to = to; pinned = null; render(); }}
  Array.prototype.forEach.call(document.querySelectorAll('.btcg-r'), function(b) {{ b.addEventListener('click', function() {{
    Array.prototype.forEach.call(document.querySelectorAll('.btcg-r'), function(x) {{ x.classList.remove('on'); }}); b.classList.add('on');
    var y = +b.getAttribute('data-y'), last = MONTHS[MONTHS.length-1]; setRange(y ? mAdd(last, -12*y) : MONTHS[0], last);
    document.getElementById('btcg-from').value = ''; document.getElementById('btcg-to').value = ''; }}); }});
  document.getElementById('btcg-go').addEventListener('click', function() {{
    var f = document.getElementById('btcg-from').value || MONTHS[0], t = document.getElementById('btcg-to').value || MONTHS[MONTHS.length-1];
    if (f > t) {{ var x = f; f = t; t = x; }} if (f < MONTHS[0]) f = MONTHS[0]; if (t > MONTHS[MONTHS.length-1]) t = MONTHS[MONTHS.length-1];
    Array.prototype.forEach.call(document.querySelectorAll('.btcg-r'), function(x) {{ x.classList.remove('on'); }}); setRange(f, t); }});
  Array.prototype.forEach.call(document.querySelectorAll('.btcg-chk input'), function(c) {{ c.addEventListener('change', function() {{ st.show[c.getAttribute('data-s')] = c.checked ? 1 : 0; render(); }}); }});
  render();
}})();
</script>
</body>
</html>"""
