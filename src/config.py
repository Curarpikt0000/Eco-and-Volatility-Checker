"""
config.py — Eco and Volatility Checker 单一事实来源 (SSOT)

17 项宏观风险指标 + 金银 COT 的完整定义：
  - 数据源类型与地址
  - Notion DB 字段名 / 单位
  - 警戒阈值 (基于历史经验，静态，不随情绪调整)
  - 信号灯规则 (🟢 正常 / 🟡 警戒 / 🔴 触发)
  - 7 项硬性卖出触发条件

改指标 = 只改本文件 + 对应 fetcher；其它文件不动。
时区：一律 Asia/Tokyo (JST)。
"""
import os

# ─────────────────────── 密钥 (从 .env 读，绝不硬编码) ───────────────────────
def _load_env():
    env = {}
    p = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = _load_env()
FRED_API_KEY = ENV.get("FRED_API_KEY", "")
NOTION_TOKEN = ENV.get("NOTION_TOKEN", "")
NOTION_VERSION = ENV.get("NOTION_VERSION", "2022-06-28")
TG_BOT_TOKEN = ENV.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = ENV.get("TG_CHAT_ID", "")
TG_THREAD_ID = ENV.get("TG_THREAD_ID", "")

# ─────────────────────── Notion 目标 ───────────────────────
NOTION_PARENT_PAGE = "3b947eb5fd3c80ea9b06d41704af3b05"
# 三个 DB 的 id 在建库后写回本文件 (build_notion_dbs.py 生成)
NOTION_DB = {
    "indicators": ENV.get("DB_INDICATORS", ""),   # DB-1 每日 17 指标时序
    "cot":        ENV.get("DB_COT", ""),          # DB-2 金银 COT 时序
    "report":     ENV.get("DB_REPORT", ""),       # DB-3 每日扫描报告
    "weekly":     ENV.get("DB_WEEKLY", ""),        # DB-4 周报
    "holdings":   ENV.get("DB_HOLDINGS", ""),       # DB-5 机构持仓(13F)+Trump
}

# ─────────────────────── 信号方向 ───────────────────────
# "high_bad": 值越高越危险 (VIX高/杠杆高/估值高) → 超上阈值触发
# "low_bad":  值越低越危险 (LEI下滑/收益率曲线倒挂/内部人买少) → 跌破下阈值触发
# "band":     区间型 (Fear&Greed 过高=贪婪危险)

# ─────────────────────── 17 指标定义 ───────────────────────
# key: 内部唯一键
# name_zh: 中文名 | name_en: 英文名
# group: short(短期) / mid(中期) / long(长期)
# source: fred / web / derived / search
# fred_id: FRED series id (source=fred 时)
# url: 抓取地址 (source=web 时)
# unit: 单位
# direction: high_bad / low_bad
# warn / trigger: 警戒阈值 / 触发阈值 (信号灯用)
# note: 历史经验说明

INDICATORS = [
    # ═══════════ 🟢 短期指标 (天-周级别，判断过热回调) ═══════════
    {"key": "vix", "name_zh": "VIX 波动率指数", "name_en": "CBOE VIX",
     "group": "short", "source": "fred", "fred_id": "VIXCLS", "unit": "点",
     "direction": "high_bad", "warn": 20, "trigger": 25,
     "note": "VIX<13 = 自满区；>25 = 恐慌/系统性压力。阈值静态，不随市场结构调整。"},

    {"key": "fear_greed", "name_zh": "CNN 恐惧与贪婪指数", "name_en": "CNN Fear & Greed",
     "group": "short", "source": "web", "url": "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
     "unit": "0-100", "direction": "high_bad", "warn": 75, "trigger": 80,
     "note": ">75 极度贪婪 = 过热，从高位(>75)回落到<50 是卖出触发信号之一。"},

    {"key": "aaii_bull_bear", "name_zh": "AAII 散户多空差", "name_en": "AAII Bull-Bear Spread",
     "group": "short", "source": "web", "url": "https://www.aaii.com/sentimentsurvey",
     "unit": "%", "direction": "high_bad", "warn": 20, "trigger": 30,
     "note": "多空差(Bull%-Bear%)>30% = 散户极度乐观(反向信号)。"},

    {"key": "put_call", "name_zh": "CBOE 权益 Put/Call 比", "name_en": "CBOE Equity Put/Call",
     "group": "short", "source": "web", "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/",
     "unit": "比率", "direction": "low_bad", "warn": 0.55, "trigger": 0.45,
     "note": "越低越自满(买权多)。<0.45 = 极度乐观，回调风险高。"},

    {"key": "bofa_fms_cash", "name_zh": "BofA FMS 现金水平", "name_en": "BofA FMS Cash %",
     "group": "short", "source": "search", "url": "",
     "unit": "%", "direction": "low_bad", "warn": 4.5, "trigger": 4.0,
     "note": "全球基金经理现金占比(BofA月度调查)。替代已停更的NAAIM主动仓位。现金<4%=满仓贪婪/过热(反向卖出信号),>5%=避险恐慌(反向买入)。"},

    # ═══════════ 🟡 中期指标 (周-月级别，判断趋势转折) ═══════════
    {"key": "margin_debt", "name_zh": "FINRA 保证金负债", "name_en": "FINRA Margin Debt",
     "group": "mid", "source": "web", "url": "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics",
     "unit": "十亿$", "direction": "high_bad", "warn": None, "trigger": None,
     "note": "月度。关注年增率 + 月增方向。连续3个月下降 = 卖出触发信号之一。"},

    {"key": "margin_gdp", "name_zh": "保证金负债 / GDP", "name_en": "Margin Debt / GDP",
     "group": "mid", "source": "derived", "unit": "%", "direction": "high_bad",
     "warn": 3.0, "trigger": 3.5,
     "note": "派生：margin_debt / 名义GDP(FRED GDP)。历史高位 >3% 预示杠杆过高。"},

    {"key": "ipo_count", "name_zh": "Renaissance IPO 发行量", "name_en": "Renaissance IPO Count",
     "group": "mid", "source": "web", "url": "https://www.renaissancecapital.com/IPO-Center/Stats",
     "unit": "宗/季", "direction": "high_bad", "warn": None, "trigger": None,
     "note": "当季数量+募资总额。IPO 井喷 = 市场情绪顶部特征。"},

    {"key": "insider", "name_zh": "内部人买卖比", "name_en": "Insider Buy/Sell Ratio",
     "group": "mid", "source": "web", "url": "https://www.gurufocus.com/economic_indicators/4359/insider-buysell-ratio",
     "unit": "比率", "direction": "low_bad", "warn": 0.25, "trigger": 0.17,
     "note": "内部人越卖越少买 = 看空。<0.17 = 卖出触发信号之一。"},

    {"key": "bofa_bull_bear", "name_zh": "美银牛熊指标", "name_en": "BofA Bull & Bear",
     "group": "mid", "source": "search", "unit": "0-10", "direction": "high_bad",
     "warn": 7.0, "trigger": 8.0,
     "note": "无固定源，web_search 每周搜。>8.0 = 极度贪婪(卖出信号)，<2 = 极度恐慌(买入)。"},

    {"key": "hy_oas", "name_zh": "高收益债利差", "name_en": "ICE BofA HY OAS",
     "group": "mid", "source": "fred", "fred_id": "BAMLH0A0HYM2", "unit": "%",
     "direction": "high_bad", "warn": 4.0, "trigger": 4.5,
     "note": "信用利差扩张 = 风险偏好收缩。>4.5% = 信用市场警报(卖出信号之一)。"},

    {"key": "ad_line", "name_zh": "NYSE 腾落线背离", "name_en": "NYSE A/D Line Divergence",
     "group": "mid", "source": "search", "unit": "布尔", "direction": "high_bad",
     "warn": None, "trigger": None,
     "note": "S&P创新高但A/D不创新高 = 顶背离(卖出信号之一)。web_search 判断。"},

    # ═══════════ 🔴 长期指标 (月-年级别，判断结构性周期顶) ═══════════
    {"key": "buffett", "name_zh": "巴菲特指标", "name_en": "Buffett Indicator",
     "group": "long", "source": "web", "url": "https://www.currentmarketvaluation.com/models/buffett-indicator.php",
     "unit": "%", "direction": "high_bad", "warn": 150, "trigger": 180,
     "note": "总市值/GDP。>150% 显著高估，>180% 极端泡沫区。允许周/月度数据。"},

    {"key": "cape", "name_zh": "席勒 CAPE (PE10)", "name_en": "Shiller CAPE",
     "group": "long", "source": "web", "url": "https://www.multpl.com/shiller-pe",
     "unit": "倍", "direction": "high_bad", "warn": 30, "trigger": 35,
     "note": "周期调整市盈率。>30 历史高估，>35 接近2000/2021级泡沫。允许月度。"},

    {"key": "yield_curve", "name_zh": "10Y-2Y 收益率曲线", "name_en": "10Y-2Y Yield Curve",
     "group": "long", "source": "fred", "fred_id": "T10Y2Y", "unit": "%",
     "direction": "low_bad", "warn": 0.2, "trigger": 0.0,
     "note": "倒挂(<0)历史预示衰退；由倒挂转正(bull steepening)常是衰退临近信号。"},

    {"key": "lei", "name_zh": "Conference Board 领先指数", "name_en": "Conference Board LEI",
     "group": "long", "source": "web", "url": "https://www.conference-board.org/topics/us-leading-indicators",
     "unit": "指数/6M%", "direction": "low_bad", "warn": -2.0, "trigger": -4.0,
     "note": "领先经济指数。6个月变化率 <-4% 历史强烈预示衰退。允许月度。"},

    {"key": "aaii_alloc", "name_zh": "AAII 家庭股票配置", "name_en": "AAII Stock Allocation",
     "group": "long", "source": "web", "url": "https://www.aaii.com/assetallocationsurvey",
     "unit": "%", "direction": "high_bad", "warn": 68, "trigger": 71,
     "note": "家庭股票仓位%。历史 >70% 是仓位极值(2000年峰值区)，反向信号。"},
]

# ─────────────────────── 金银 COT (CFTC) ───────────────────────
# CFTC Socrata Legacy futures-only 报告，周五发布(上周二数据)
COT_SOURCE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
# 精确匹配主力合约(排除 MICRO)
COT_MARKETS = {
    "gold":   "GOLD - COMMODITY EXCHANGE INC.",
    "silver": "SILVER - COMMODITY EXCHANGE INC.",
}
# 重点：commercial(商业套保) 持仓突然增加 → 通常是聪明钱见顶/见底信号
COT_FIELDS = {
    "open_interest": "open_interest_all",
    "comm_long": "comm_positions_long_all",
    "comm_short": "comm_positions_short_all",
    "noncomm_long": "noncomm_positions_long_all",
    "noncomm_short": "noncomm_positions_short_all",
}
# commercial 净持仓周环比突增阈值 (绝对合约数)，触发关注
COT_COMM_SURGE_THRESHOLD = 15000

# ─────────────────────── 7 项硬性卖出触发条件 ───────────────────────
# 同时触发 3+ 项 = 开始分批卖出
SELL_TRIGGERS = [
    {"key": "vix",            "cond": "VIX 突破并站稳 > 25",           "check": "vix_gt_25"},
    {"key": "margin_debt",    "cond": "Margin Debt 连续 3 个月下降",   "check": "margin_3m_down"},
    {"key": "hy_oas",         "cond": "HY Spread 扩张 > 4.5%",         "check": "hy_gt_45"},
    {"key": "fear_greed",     "cond": "Fear&Greed 从 >75 回落到 <50",  "check": "fg_high_to_low"},
    {"key": "ad_line",        "cond": "A/D Line 顶背离",               "check": "ad_divergence"},
    {"key": "bofa_bull_bear", "cond": "BofA Bull&Bear > 8.0",         "check": "bofa_gt_8"},
    {"key": "insider",        "cond": "Insider Buy/Sell < 0.17",       "check": "insider_lt_017"},
]
SELL_START_THRESHOLD = 3  # 同时触发 >= 3 项 → 开始分批卖出

# ─────────────────────── 增强版 (每周一额外拉) ───────────────────────
WEEKLY_EXTRA = [
    {"key": "fwd_pe", "name_zh": "标普500前瞻本益比", "name_en": "S&P 500 Forward P/E",
     "source": "search", "unit": "倍"},
    {"key": "tips_10y", "name_zh": "10年期TIPS实质殖利率", "name_en": "10Y TIPS Real Yield",
     "source": "fred", "fred_id": "DFII10", "unit": "%"},
    {"key": "dxy", "name_zh": "美元指数DXY", "name_en": "US Dollar Index",
     "source": "fred", "fred_id": "DTWEXBGS", "unit": "指数"},
    {"key": "gold_spx", "name_zh": "Gold/S&P500 比值", "name_en": "Gold/SPX Ratio",
     "source": "derived", "unit": "比率"},
]

# ─────────────────────── 组标签 ───────────────────────
GROUP_LABEL = {"short": "🟢 短期 (天-周)", "mid": "🟡 中期 (周-月)", "long": "🔴 长期 (月-年)"}
GROUP_COUNT = {"short": 5, "mid": 7, "long": 5}

def indicators_by_group(g):
    return [i for i in INDICATORS if i["group"] == g]
