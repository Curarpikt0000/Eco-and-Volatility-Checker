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
    "custody":    ENV.get("DB_CUSTODY", ""),        # DB-6 外国官方托管美债(周度)
    "auctions":   ENV.get("DB_AUCTIONS", ""),       # DB-7 美国国债拍卖(每次一行)
    "money_supply": ENV.get("DB_MONEY_SUPPLY", ""),  # DB-8 货币供应量 M0/M1/M2(月度,每国一行)
    "stress":     ENV.get("DB_STRESS", ""),        # DB-9 国债市场压力四联图最新值(as-of时序)
    "ofr":        ENV.get("DB_OFR", ""),           # DB-10 OFR 金融压力指数(as-of时序)
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
     "note": "【是什么】芝加哥期权交易所VIX指数，用标普500未来30天期权价格反推出的隐含波动率，俗称『恐慌指数』。它不预测涨跌方向，只衡量市场预期未来一个月的颠簸程度。【怎么看】低=市场自满、认为岁月静好，往往是风险积累期；高=恐慌已经发生，反而常在底部附近。所以对本系统这类顶部预警而言，真正危险的是【太低】——低波动会诱使杠杆堆积，一旦反转就是踩踏。VIX有均值回归特性，长期趋近18-20。【怎么用】<13=自满区，风险悄悄累积；>20进入警戒；>25=恐慌/系统性压力。别看单日数值，看是否从低位持续抬升——从12升到18的过程比停在25更值得警惕。【注意】阈值静态，不随市场结构调整。VIX低不等于安全，只等于『大家都觉得安全』。"},

    {"key": "fear_greed", "name_zh": "CNN 恐惧与贪婪指数", "name_en": "CNN Fear & Greed",
     "group": "short", "source": "web", "url": "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
     "unit": "0-100", "direction": "high_bad", "warn": 75, "trigger": 80,
     "note": "【是什么】CNN恐惧与贪婪指数，0-100分。由7个子指标合成（股价动量、涨跌家数、垃圾债需求、市场波动、看跌看涨期权比、避险需求、股价强度），是情绪的综合温度计。【怎么看】这是反向指标：分数越高说明市场越贪婪，越接近情绪顶部。极度贪婪时人人满仓、无人恐惧，往下的燃料反而耗尽了。【怎么用】>75=极度贪婪🟡；>80=过热🔴。★关键不是绝对值而是【拐点】：从高位（>75）回落跌破50，是本系统7项卖出触发之一——情绪由盛转衰的那一刻比情绪最高点更有交易意义。【注意】情绪指标波动快、噪音大，单日跳动别当信号，看趋势。"},

    {"key": "aaii_bull_bear", "name_zh": "AAII 散户多空差", "name_en": "AAII Bull-Bear Spread",
     "group": "short", "source": "web", "url": "https://www.aaii.com/sentimentsurvey",
     "unit": "%", "direction": "high_bad", "warn": 20, "trigger": 30,
     "note": "【是什么】美国散户投资者协会（AAII）每周问卷，问会员未来6个月看多还是看空，本指标=看多比例−看空比例。纯散户样本，不含机构。【怎么看】典型反向指标。散户历来在顶部最乐观、底部最悲观，所以多空差冲高说明『该买的人都买了』，接盘力量枯竭。【怎么用】>20%=偏乐观🟡；>30%=散户极度乐观🔴（反向卖出信号）。负值（看空多于看多）反而常出现在阶段底部。【注意】①这是【问卷说的】不是【实际仓位】，嘴上看多手上未必买，要配合『AAII家庭股票配置』那张卡看真实仓位。②周频更新，别指望它抓短线。"},

    {"key": "put_call", "name_zh": "CBOE 权益 Put/Call 比", "name_en": "CBOE Equity Put/Call",
     "group": "short", "source": "web", "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/",
     "unit": "比率", "direction": "low_bad", "warn": 0.55, "trigger": 0.45,
     "note": "【是什么】CBOE权益类看跌/看涨期权成交比。分子是买跌（put）的量，分母是买涨（call）的量，反映交易者真金白银下注的方向偏好。【怎么看】★方向与其他指标相反，这里是【越低越危险】。比值低=买涨的远多于买跌的=市场极度自满、没人买保险；比值高=大家在抢购下跌保护=恐慌，反而常见于底部。【怎么用】<0.55=偏自满🟡；<0.45=极度乐观🔴，回调风险高。正常区间大致0.6-0.9。持续低位比单日低点更有意义。【注意】期权数据受到期日、指数期权、零日期权（0DTE）影响，近年0DTE占比大增使绝对水平整体下移，跨十年比较要谨慎。"},

    {"key": "bofa_fms_cash", "name_zh": "BofA FMS 现金水平", "name_en": "BofA FMS Cash %",
     "group": "short", "source": "search", "url": "",
     "unit": "%", "direction": "low_bad", "warn": 4.5, "trigger": 4.0,
     "note": "【是什么】美银美林每月全球基金经理调查（FMS），统计受访机构组合里的现金占比。样本是真正管钱的机构，代表『聪明钱』的防御姿态。【怎么看】★越低越危险。现金少=机构已满仓、没有子弹再买；现金多=机构在避险、场外有钱等着进场。这是经典反向指标，美银自己有条著名的『现金水平交易法则』就基于此。【怎么用】<4.5%=偏满仓🟡；<4.0%=满仓贪婪/过热🔴（反向卖出信号）；>5%=避险恐慌，反而是反向买入信号。【注意】①月度更新，滞后性强，只能定基调不能抓时点。②本卡是NAAIM主动仓位指数的替代——NAAIM已于2026-08-01转付费停更，本系统不再采集，绝不编数。"},

    {"key": "sofr_iorb", "name_zh": "SOFR − IORB 利差", "name_en": "SOFR minus IORB Spread",
     "group": "short", "source": "derived", "unit": "bps", "direction": "high_bad",
     "warn": 7, "trigger": 17,
     "status_labels": {"green": "正常", "yellow": "心绞痛", "red": "心肌梗塞"},
     "note": "【是什么】SOFR（担保隔夜融资利率，银行间拿国债作抵押借隔夜钱的真实成本）减去IORB（美联储付给银行准备金的利率），差额×100换成bps。IORB本该是利率走廊的上沿，正常时银行不会用比它更贵的价格去外面借钱。【怎么看】SOFR冲破IORB意味着银行宁可在市场上出高价也要借到钱——说明准备金稀缺、回购市场承压。这是货币市场压力最核心的实时体温计，也是流动性危机最早亮的灯之一。【怎么用】≤0=正常🟢；7-17bps=心绞痛🟡（流动性趋紧）；>17bps=心肌梗塞🔴（钱荒，参照2019年9月回购危机，当时SOFR一度飙升数百bps）。【注意】季末、月末、缴税日会有技术性冲高，隔天回落属正常，要看是否【连续多日】维持高位才算真压力。"},

    {"key": "margin_cost", "name_zh": "股票杠杆融资成本", "name_en": "Equity Margin Funding Cost",
     "group": "short", "source": "fred", "fred_id": "DPRIME", "unit": "%",
     "direction": "high_bad", "warn": 7.0, "trigger": 8.0,
     "note": "【是什么】用美国最优贷款利率（FRED DPRIME）代理券商保证金贷款成本——券商的融资利率多挂钩broker call rate / prime rate。即：加杠杆炒股要付多少利息。【怎么看】融资成本高会从两头挤压杠杆：新杠杆不划算、老杠杆持仓成本上升。当前市场约1.4-1.5万亿美元保证金债务，抵押品大量是高波动AI股，一旦价格下跌+利息高企，容易触发强平连锁。历史上高融资成本常伴随市场顶部。【怎么用】≥7.0%=偏高🟡；≥8.0%=高企🔴。本卡看【成本】，规模要配合『FINRA保证金负债』那张卡一起看——成本高+负债高同时出现，才是杠杆见顶的完整信号。【注意】这是代理指标，各券商实际费率按账户规模分层，散户实付通常高于prime。"},

    {"key": "bank_funding_stress", "name_zh": "银行融资压力 (CP−Tbill)", "name_en": "Bank Funding Stress (CP−Tbill)",
     "group": "short", "source": "derived", "unit": "bps", "direction": "high_bad",
     "warn": 20, "trigger": 40,
     "status_labels": {"green": "宽松", "yellow": "趋紧", "red": "承压"},
     "note": "【是什么】市场无抵押借钱给银行3个月的利率(3M金融商业票据DCPF3M)，减去借给美国政府同期限的利率(3M国库券DTB3)，差额×100换成bps。两者期限相同，唯一区别是借款人是谁——所以差额就是市场对银行体系的『信任溢价』。CP=Commercial Paper商业票据，银行发的短期无担保借条，不押任何抵押品，纯靠信用。【怎么看】数字越小越好。利差小=市场认为借给银行和借给美国政府差不多安全；利差走阔=市场开始要额外补偿才肯借给银行。这是资金用脚投票的真实价格，不是情绪问卷。传导链：银行融资变贵→收缩对交易商/对冲基金的杠杆供给→被迫平仓→资产下跌→追加保证金→再平仓，市场从『减震模式』转『放大模式』。2008雷曼前夜这类利差冲到300bps以上。【怎么用】<20bps=宽松🟢；20-40bps=趋紧🟡；>40bps=承压🔴。配合短端利率SOFR一起看：利差走阔+短端上行=短期卖出信号；单独一天跳动别当信号，看是否连续数日抬升。【注意】①这是swap spread的替代品——更标准的银行压力指标是利率互换减国债，但FRED的DSWP2/10已于2016停更、OFR的swap曲线要付费，故用同样衡量『银行无担保融资信用溢价』的CP−Tbill代替。②方向相反易看错：swap spread承压时是『缩窄』，本指标承压时是『走阔』。"},


    # ═══════════ 🟡 中期指标 (周-月级别，判断趋势转折) ═══════════
    {"key": "margin_debt", "name_zh": "FINRA 保证金负债", "name_en": "FINRA Margin Debt",
     "group": "mid", "source": "web", "url": "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics",
     "unit": "十亿$", "direction": "high_bad", "warn": None, "trigger": None,
     "note": "【是什么】FINRA每月公布的全市场保证金负债总额，即投资者向券商借钱买股票的存量规模。这是杠杆的绝对水位，非情绪问卷而是真实借据。【怎么看】杠杆是市场的燃料也是炸药。上涨期融资盘推波助澜，一旦下跌，追加保证金会强制平仓，卖压自我强化。所以真正的风险信号不是余额高，而是【余额见顶回落】——那说明去杠杆已经开始，往往同步于市场顶部。【怎么用】本卡无固定阈值，看两件事：年增率、月度增减方向。★连续3个月下降=本系统7项卖出触发之一。【注意】月度数据，公布滞后约3-4周，只能确认趋势不能抓拐点。"},

    {"key": "margin_gdp", "name_zh": "保证金负债 / GDP", "name_en": "Margin Debt / GDP",
     "group": "mid", "source": "derived", "unit": "%", "direction": "high_bad",
     "warn": 3.0, "trigger": 3.5,
     "note": "【是什么】保证金负债 ÷ 名义GDP（FRED GDP）。把杠杆的绝对金额放到经济体量里做标准化。【怎么看】单看保证金负债的绝对值会被通胀和经济增长自然推高，十年前的1万亿和今天的1万亿不是一回事。除以GDP后才能跨周期比较，回答『相对于经济规模，市场的杠杆是不是历史极端』。【怎么用】>3.0%=杠杆偏高🟡；>3.5%=历史高位🔴，预示杠杆过度。历史上2000、2007、2021三个顶部区域该比值都冲到相对高位。【注意】①GDP季度更新，分母变动慢，短期波动几乎全来自分子。②派生指标，依赖margin_debt，后者缺数时本卡同步失效。"},

    {"key": "ipo_count", "name_zh": "Renaissance IPO 发行量", "name_en": "Renaissance IPO Count",
     "group": "mid", "source": "web", "url": "https://www.renaissancecapital.com/IPO-Center/Stats",
     "unit": "宗/季", "direction": "high_bad", "warn": None, "trigger": None,
     "note": "【是什么】Renaissance Capital统计的当季IPO发行宗数与募资总额，衡量一级市场发行热度。【怎么看】IPO是典型的顺周期供给。市场狂热时企业与承销商争相上市套现，因为估值最高、最好卖；市场冷时IPO窗口直接关闭。所以IPO井喷本身就是【情绪顶部的结构性特征】——它同时意味着二级市场的资金正被大量新股供给分流。【怎么看数】本卡无固定阈值，重点看环比井喷与质量下沉（亏损企业占比上升、上市首日暴涨），两者同现时警惕性最高。【注意】季度频率，滞后明显，属于确认性指标而非领先指标。"},

    {"key": "insider", "name_zh": "内部人买卖比", "name_en": "Insider Buy/Sell Ratio",
     "group": "mid", "source": "web", "url": "https://www.gurufocus.com/economic_indicators/4359/insider-buysell-ratio",
     "unit": "比率", "direction": "low_bad", "warn": 0.25, "trigger": 0.17,
     "note": "【是什么】上市公司内部人（高管、董事、大股东）的买入/卖出比。内部人交易须向SEC申报，本卡统计其买卖笔数或金额之比。【怎么看】★越低越危险。内部人最了解自家公司真实经营状况，他们集体减持而少有买入，说明最懂行的人认为价格已经贵了。这是少有的『信息优势方用真金白银投票』的指标，噪音低于任何情绪问卷。【怎么用】<0.25=偏空🟡；<0.17=明确看空🔴，是本系统7项卖出触发之一。【注意】内部人卖出有多种非看空原因（行权到期、税务规划、分散风险、预设的10b5-1自动卖出计划），所以【买入】比【卖出】的信息含量更高——内部人买入几乎只有一个理由：他觉得便宜。"},

    {"key": "bofa_bull_bear", "name_zh": "美银牛熊指标", "name_en": "BofA Bull & Bear",
     "group": "mid", "source": "search", "unit": "0-10", "direction": "high_bad",
     "warn": 7.0, "trigger": 8.0,
     "note": "【是什么】美银美林牛熊指标，0-10分制。综合对冲基金仓位、共同基金资金流、市场宽度、债券与股票的资金流向等多项硬数据合成，衡量全球资金的风险偏好极值。【怎么看】反向指标，且美银历史回测显示其在极值区的反转胜率较高。>8触发美银自己的『卖出信号』，<2触发『买入信号』。它比散户问卷更硬，因为成分多为实际资金流而非态度调查。【怎么用】>7.0=偏贪婪🟡；>8.0=极度贪婪🔴（卖出信号）；<2=极度恐慌（买入信号）。【注意】★本指标无稳定免费数据源，靠每周web_search从公开报道中交叉核实，搜不到时如实留空标『未找到』，绝不沿用旧值也绝不估算。"},

    {"key": "hy_oas", "name_zh": "高收益债利差", "name_en": "ICE BofA HY OAS",
     "group": "mid", "source": "fred", "fred_id": "BAMLH0A0HYM2", "unit": "%",
     "direction": "high_bad", "warn": 4.0, "trigger": 4.5,
     "note": "【是什么】ICE BofA美国高收益债期权调整利差（OAS）。即垃圾级企业债相对同期限美国国债要多付的利息，单位是百分点。【怎么看】这是信用市场的风险定价。利差收窄=投资者愿意为一点点额外收益承担垃圾债风险，风险偏好极高；利差扩张=资金撤离风险资产、要求更高补偿。★信用市场通常【领先】股市——债券投资者更保守，垃圾债利差往往在股指见顶前就开始走阔。【怎么用】>4.0%=信用趋紧🟡；>4.5%=信用市场警报🔴，是7项卖出触发之一。历史极端：2008年冲破20%，2020年3月约11%。【注意】看变化速率比看绝对水平更重要——快速走阔100bps比慢慢停在高位更危险。"},

    {"key": "ad_line", "name_zh": "NYSE 腾落线背离", "name_en": "NYSE A/D Line Divergence",
     "group": "mid", "source": "search", "unit": "布尔", "direction": "high_bad",
     "warn": None, "trigger": None,
     "note": "【是什么】纽交所腾落线（Advance/Decline Line）背离判断，布尔值（是/否）。A/D线=每日上涨家数减下跌家数的累计值，衡量上涨的【广度】。【怎么看】健康的牛市应该是普涨，指数与A/D线同步创新高。如果标普创了新高、A/D线却没跟上，说明指数是被少数大权重股（如AI七巨头）拉起来的，大多数股票已在下跌——这叫顶背离，是典型的牛市末期结构。【怎么用】出现背离=🔴，是本系统7项卖出触发之一。背离通常持续数周至数月才兑现，是【预警】不是【择时】。【注意】★本指标无固定免费数据源，由web_search每日交叉验证判断，证据不足时留空标『未找到』，绝不主观臆断。"},

    # ═══════════ 🔴 长期指标 (月-年级别，判断结构性周期顶) ═══════════
    {"key": "buffett", "name_zh": "巴菲特指标", "name_en": "Buffett Indicator",
     "group": "long", "source": "web", "url": "https://www.currentmarketvaluation.com/models/buffett-indicator.php",
     "unit": "%", "direction": "high_bad", "warn": 150, "trigger": 180,
     "note": "【是什么】巴菲特指标 = 美国股市总市值 ÷ 名义GDP。巴菲特2001年称其为『任何时点衡量估值水平的最佳单一指标』。【怎么看】把股市规模放到实体经济里比。股票的长期回报终究来自企业盈利，而企业盈利无法长期脱离GDP增长。比值远高于100%意味着市场price in的未来，已经超出经济能兑现的范围。【怎么用】>150%=显著高估🟡；>180%=极端泡沫区🔴。历史参照：2000年互联网顶部约140-150%，2007年约105%，近年已长期高于历史区间。【注意】①分子含大量海外收入的跨国公司，分母只算美国GDP，全球化使该比值存在系统性上移，跨50年比较要打折扣。②GDP季度更新，允许周/月度频率。"},

    {"key": "cape", "name_zh": "席勒 CAPE (PE10)", "name_en": "Shiller CAPE",
     "group": "long", "source": "web", "url": "https://www.multpl.com/shiller-pe",
     "unit": "倍", "direction": "high_bad", "warn": 30, "trigger": 35,
     "note": "【是什么】席勒周期调整市盈率（CAPE / PE10）= 股价 ÷ 过去10年经通胀调整的平均盈利。诺奖得主Robert Shiller提出。【怎么看】普通PE用当期盈利，会在经济顶部（盈利最高）显得便宜、在衰退期（盈利崩塌）显得极贵，恰好给出错误信号。用10年平均盈利平滑掉周期，才能看清真实估值。CAPE对未来10年期回报有较强解释力，但对未来1年几乎没有预测力。【怎么用】>30=历史高估🟡；>35=接近2000/2021级泡沫🔴。历史极值：1929年约33，2000年约44，2009年低点约13。【注意】★这是【长期估值】指标不是择时工具——CAPE可以在高位停留数年，用它做卖出时点会持续踏空。允许月度更新。"},

    {"key": "yield_curve", "name_zh": "10Y-2Y 收益率曲线", "name_en": "10Y-2Y Yield Curve",
     "group": "long", "source": "fred", "fred_id": "T10Y2Y", "unit": "%",
     "direction": "low_bad", "warn": 0.2, "trigger": 0.0,
     "note": "【是什么】美国10年期国债收益率 减 2年期国债收益率，单位百分点。正常情况下借得越久利率越高，曲线向上倾斜。【怎么看】★这张卡最容易被误读。倒挂（<0）本身是衰退的经典领先信号，但真正的危险时刻是【倒挂之后重新转正】。历史上多次衰退都不是在倒挂最深时开始，而是在曲线由负转正、即所谓bull steepening（短端因降息预期快速下行）之后不久到来。【怎么用】<0.2%=接近倒挂🟡；<0=倒挂🔴。★读法：倒挂=衰退在路上（可能还有1-2年）；由倒挂转正=衰退临近（数月级）。【注意】领先时间跨度大（历史上6-24个月不等），不能当择时信号用。"},

    {"key": "lei", "name_zh": "Conference Board 领先指数", "name_en": "Conference Board LEI",
     "group": "long", "source": "web", "url": "https://www.conference-board.org/topics/us-leading-indicators",
     "unit": "指数/6M%", "direction": "low_bad", "warn": -2.0, "trigger": -4.0,
     "note": "【是什么】世界大型企业研究会（Conference Board）领先经济指数，由10个领先성分合成（新增订单、初请失业金、建筑许可、股价、利差、消费者预期等），本卡看其6个月变化率。【怎么看】★方向与多数卡相反，这里是【越低越危险】。成分全部选自历史上早于经济周期见顶/见底的变量，所以LEI的6个月变化率转负并持续下探，是实体经济即将走弱的领先证据。【怎么用】<-2.0%=转弱🟡；<-4.0%=历史强烈预示衰退🔴。★注意区分：这是【经济】指标不是【市场】指标，经济衰退与股市见顶不同步，股市通常提前反应。【注意】月度更新且会修订，允许月度频率；单月波动别当信号，看6个月斜率。"},

    {"key": "aaii_alloc", "name_zh": "AAII 家庭股票配置", "name_en": "AAII Stock Allocation",
     "group": "long", "source": "web", "url": "https://www.aaii.com/assetallocationsurvey",
     "unit": "%", "direction": "high_bad", "warn": 68, "trigger": 71,
     "note": "【是什么】AAII每月调查会员的资产配置，本卡取【股票仓位占比】。★与『AAII散户多空差』的区别：那张问的是【怎么想】，这张问的是【实际怎么放钱】。【怎么看】仓位是比态度更硬的证据。散户股票仓位冲到历史极值，意味着可动用的增量资金已经耗尽——没有子弹的多头无法再推高市场。这是标准反向指标。【怎么用】>68%=仓位偏高🟡；>71%=历史仓位极值🔴（反向信号）。历史参照：2000年3月互联网顶部区曾达约77%的峰值水平。【注意】①样本是AAII会员（偏年长、偏富裕的自主投资者），不能代表全体散户。②月度更新，慢变量，用于判断风险位置而非交易时点。"},
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
