#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把【周期/玄学/术数派金融预测者】写入 KOL 名册。

新增 sector = "Cycles & Esoteric Forecasting"(domain="周期与术数预测"),
在 dashboard 里单独成 section。

铁律: 所有 url / channel_id 均来自子代理实访验证; 拿不到的一律留空,不编造。
去重: 按 display_name 归一化(小写去空格)与现有名册比对, 已存在则跳过并打印。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data", "kol_registry.json")

SECTOR = "Cycles & Esoteric Forecasting"
DOMAIN = "周期与术数预测"

# ── 西方/英文圈(子代理实访验证, verified=true) ──────────────────────────
WESTERN = [
    ("Martin Armstrong", "马丁·阿姆斯特朗", "长周期模型（ECM 8.6年周期 / Socrates AI）",
     "https://www.armstrongeconomics.com/", "",
     "daily", "股指/黄金/利率/美元/地缘政治/主权债",
     "ECM 8.6年周期模型创始人，博客近乎每日更新且历史文章公开可回溯；曾因藐视法庭入狱11年，争议极大，Socrates 为付费黑箱模型，无独立第三方审计的绩效记录。"),
    ("Raymond A. Merriman", "雷蒙德·梅里曼", "金融占星（geocosmic 地象周期）+ 18周主周期",
     "https://www.mmacycles.com/", "",
     "weekly", "黄金/白银/道指/比特币/铜/农产品/美债",
     "从业50年以上，注册 CTA（商品交易顾问），MMA Cycles Report 自1982年连续发行；官网公开 Scorecard 列出带具体价位与止损的历史推荐，属该派系中少数愿意留下可复盘书面记录者。"),
    ("Charles Nenner", "查尔斯·内纳", "周期理论（专有周期算法 + 战争周期）",
     "https://charlesnenner.com/", "",
     "weekly", "股指/黄金/白银/原油/美债/德债/美元/比特币",
     "1997–2008 任职高盛（伦敦/纽约）自营与交易台周期研究；历史命中率无公开第三方验证，媒体访谈中的战争周期大预测常年偏早。"),
    ("Robert Prechter / Elliott Wave International", "罗伯特·普莱切特 / 艾略特波浪国际", "艾略特波浪（社会情绪学 Socionomics）",
     "https://www.elliottwave.com/", "UC4H-JhWsulgYjgziL5md1gw",
     "daily", "股指/利率/美元/黄金白银/原油/加密货币/全球市场",
     "全球最大独立预测机构，1987年崩盘前成名之作；但长期超级熊市论调（Conquer the Crash 系列）多轮落空，是波浪派最有名也最被质疑的招牌。"),
    ("Harry S. Dent Jr.", "哈里·丹特", "人口周期 / 消费支出波（Spending Wave）",
     "https://harrydent.com/", "UCDkLCChDIvIKLaxIAqkhjuQ",
     "weekly", "美股指数/房地产/债券/通缩情景",
     "哈佛 MBA、前贝恩顾问，《The Great Boom Ahead》(1992) 成功押注90年代大牛市；此后道指崩至3800等极端崩盘预言反复落空，是可复盘性最强但错误率也最高的样本。"),
    ("Neil Howe", "尼尔·豪", "世代长周期（Strauss–Howe 第四转折 / 约80年 Saeculum）",
     "https://www.fourthturning.com/", "",
     "monthly", "宏观政治风险/社会周期/资产配置大格局",
     "历史学家兼人口学家，Hedgeye Risk Management 人口研究董事总经理，《The Fourth Turning》(1997) 提出的危机窗口被广泛引用；属定性长周期框架，无逐笔可回测的市场调用记录。"),
    ("Eric Hadik", "埃里克·哈迪克", "周期理论（40年周期 / Hadik's Cycle Progression / 17年周期）",
     "https://www.insiidetracktrading.com/", "",
     "weekly", "黄金白银/天然气/利率/美元/股指/比特币",
     "1994年创办 INSIIDE Track，官网设 Cycles In Action 专栏逐案列出发布时点与目标，可对照原始出版物复盘；同时把周期用于疾病、火山、战争预测，玄学色彩浓。"),
    ("Andrew Pancholi", "安德鲁·潘乔利", "Gann/数学周期（Market Timing Report、PFO 直方图）",
     "https://markettimingreport.com/", "",
     "monthly", "标普500/原油/黄金/美元指数/EURUSD/比特币",
     "周期基金会（FSC）董事会成员，《Zero Hour》合著者；月报每期回顾上一期表现，官网公开多年 track record（自述可核，未经第三方审计）。"),
    ("Foundation for the Study of Cycles", "周期研究基金会", "周期理论学术机构（1941年创立）",
     "https://cycles.org/", "UClPmOWEi49CnLBWgl_ju7xw",
     "weekly", "股指/大宗商品/BDI/太阳黑子与市场/41个月周期",
     "美国501(c)(3)非营利研究机构，85年历史，是整个周期派的学术枢纽；Market Cycles Report 直播每周更新，适合作为派系聚合源订阅。"),
    ("Tom McClellan", "汤姆·麦克莱伦", "周期/市场广度（McClellan Oscillator、总统四年周期、太阳黑子周期）",
     "https://www.mcoscillator.com/", "",
     "daily", "美股指数/市场广度/高收益债/原油/利率",
     "McClellan 指标家族第二代，西点军校工程背景；免费 Chart In Focus 专栏长期公开归档、每篇带图带日期，是本组可复盘性最好、最接近主流技术分析的一位。"),
    ("Glenn Neely", "格伦·尼利", "艾略特波浪（NEoWave 规则化波浪理论）",
     "https://www.neowave.com/", "",
     "weekly", "标普500/黄金/美债T-Notes/欧元/比特币",
     "《Mastering Elliott Wave》(1990) 作者，40年从业；自述25年内被 Timer Digest 评为 Top 10 Timer 逾100次；发布过预测至2060年的超长周期图，属波浪派中方法论最系统化的分支。"),
    ("Avi Gilburt", "阿维·吉尔伯特", "艾略特波浪（Fibonacci Pinball 框架）",
     "https://www.elliottwavetrader.net/", "",
     "daily", "标普500/贵金属与矿业股/美元/加密/REITs/银行股",
     "23人分析师团队的付费社区，Seeking Alpha 长期高产作者——公开文章带时间戳，是英文圈波浪派中少数可用第三方平台逐篇复盘的账号。"),
    ("Peter Goodburn / WaveTrack International", "彼得·古德伯恩 / 波浪轨迹国际", "艾略特波浪 + 周期分析（Inflation-Pop 长周期论）",
     "https://www.wavetrack.com/", "",
     "daily", "美元指数/美10年期收益率/原油/黄金白银/全球股指",
     "从业40+年，受 CME Group 赞助在 Bloomberg Precious Metals Forum 演讲；官网每日发布带具体点位与波浪标注的跨资产评论，历史年度三视频展望可逐年回溯。"),
    ("David Hickson / Sentient Trader", "大卫·希克森 / Sentient Trader", "Hurst 周期理论（J.M. Hurst 嵌套周期、FLD 策略）",
     "https://sentienttrader.com/", "",
     "weekly", "美元/黄金/原油/铜/USDJPY/EURUSD/标普E-mini/日经",
     "Hurst 周期方法最主要的软件化推广者，30年交易经验；姊妹站 hurstcycles.com 定期发布带日期的多市场宏观周期展望，可逐条对照回测。"),
    ("Bo Polny", "波·波尔尼", "圣经周期 / 玄学择时（Seven Seals 时间模型）",
     "https://www.youtube.com/channel/UCUi58MXaCXTukyYmlCgeI9w", "UCUi58MXaCXTukyYmlCgeI9w",
     "weekly", "黄金/白银/比特币/美元崩溃叙事",
     "极端玄学派代表（频道名 God's Analyst of TIME，约15万订阅），官网列出大量带具体日期的末日/财富转移预言——可信度低，但作为散户情绪与极端叙事的高信号强度指标值得追踪，且其预言全部带日期、极易复盘。"),
]

# ── 中文圈术数派(本人亲验: YouTube 站内搜索取 channel_id, 再拉 /videos 确认近期确在做金融预测) ──
# 每条的 channel_id 与 handle 均由 curl 实拉页面取得; 更新时间为验证当日(2026-08-20)观察值。
CHINESE = [
    ("吳昌燁 · 太一研究院", "Wu Changye / Fengshui Wu", "奇门遁甲（周度盘势 + 月度大局）",
     "https://www.youtube.com/@wuchangye", "UCyzQhRHrH1rDQjEf4j0pEUw",
     "weekly", "美股/比特币/A股/黄金/港股/美元指数/原油",
     "用户点名追踪对象。台湾奇门遁甲研究者，逐周发布带明确日期区间的盘势预测（如「丙申月 8/24-8/29」），另有月度大局与半年展望；标的覆盖面在中文术数派中最全，且视频标题即含方向判断，可逐期复盘。验证日最新更新距今 6 小时。"),
    ("六爻佔卦之狼眼看世界", "Wolf in Canada", "周易六爻占卦（周卦制）",
     "https://www.youtube.com/@wolfincanada", "UCa3RhiQrvfzurtWsNjtP2pg",
     "weekly", "SPY/QQQ/BTC/ETH/黄金/白银/个股",
     "北美中文六爻频道，以「周卦」编号连续发布（验证时已至周卦29），自述「今天起卦，明天验证」并做先断后验；标的明确到 ETF 与贵金属，是中文术数派中复盘纪律最强的账号之一。验证日最新更新距今 2 天。"),
    ("小夏易經視角", "Xiaoxia Yijing", "易经卦象（天山遁、坎为水等卦象解盘）",
     "https://www.youtube.com/@xiaoxia523", "UCJY3w1r6qsy8pbBGlY3ST7Q",
     "weekly", "美股/纳指/半导体个股/A股",
     "以具体卦象（天山遁、坎为水变水地比等）解读美股周走势与产业逻辑，并结合 CPI/联储纪要等真实宏观日程；曾公开发布「我認錯復盤」检讨错误卦象，罕见地留下负面复盘记录。验证日最新更新距今 3 天。"),
    ("秋潤金融玄學 / 秋润易道", "Qiurun Financial Metaphysics", "八字 + 六爻 + 文王卦",
     "https://www.youtube.com/@qiurunyidao", "UC5QVNI2GdakaWPU-9ZXc--Q",
     "biweekly", "存储芯片股/美联储政策/原油/地缘冲突/SpaceX",
     "以「金融玄學」为栏目名，每期针对单一命题起卦（如「美联储会加息吗」「存储股票近期走势」），标题带明确日期编号便于回溯；中英双频道运营（英文站 @panstud，channel UCVFTHBy7W3qQWC1mLo_oWbA）。验证日最新更新距今 2 周。"),
    ("易經交易攻守道", "EZ Money", "易经思维 + 期指交易（台股结算日）",
     "https://www.youtube.com/@ezmoney945", "UCuCBcj5Z0V_JYmq23QYh9Ww",
     "daily", "台股期指/美股/AI 板块",
     "近乎每日更新（验证日最新距今 2 小时），聚焦台指期结算与短线方向，把易经框架用于交易节奏而非命理断事；在本组中更新频率最高、最贴近实盘。"),
    ("丙午易说天下", "Bingwu Yishuo", "八字命理 + 卦象（宏观命题）",
     "https://www.youtube.com/@bingwuyixue", "UCL_CTPQPdgMVUHqXWO1QM1A",
     "monthly", "美联储政策/比特币/国际油价/投资人物命理",
     "以八字与卦象推演宏观命题（美联储加息、油价三月走势、比特币年底目标位），并做投资人物（如芒格）命理解析；给出的目标位常带具体数字，可量化复盘。验证日最新更新距今 1 个月。"),
    ("天遁财局", "Tiandun Caiju", "奇门遁甲（节气局：小满局/立夏局/谷雨局）",
     "https://www.youtube.com/channel/UCtpNGKepybdLOs1z6mYZFuw", "UCtpNGKepybdLOs1z6mYZFuw",
     "monthly", "纳指/黄金/比特币",
     "按二十四节气起「财局」，每期给出纳指/黄金/BTC 的关键行情节点与日期区间；亦有奇门视角复盘索罗斯等经典战役。更新随节气，验证日最新距今 2 个月。"),
    ("JingHongNews 景宏资讯", "JingHong News / 中岛经济研究社", "奇门遁甲（中长期走势推演）",
     "https://www.youtube.com/@JingHongNews", "UCKQWNHMXenXIbNULzKrpJrQ",
     "monthly", "黄金/原油WTI/比特币/半导体个股/政治事件",
     "以「中岛经济研究社」名义发布奇门遁甲的中长期（半年至数年）走势推演，标的含黄金、WTI、Circle 等个股及政治事件时点；订阅规模小，但预测周期长、命题具体，适合做长周期对账样本。验证日最新更新距今 1 个月。"),
]


def norm(s):
    return re.sub(r"[\s·/、,，.．]+", "", (s or "").lower())


def build(rows, region):
    out = []
    for (name, alt, school, url, ch, cadence, focus, note) in rows:
        pid = re.sub(r"[^a-z0-9]+", "_", norm(name))[:40].strip("_") or norm(alt)[:40]
        rec = {
            "id": pid,
            "display_name": name,
            "notion_select_name": name,
            "domain": DOMAIN,
            "sector": SECTOR,
            "detail_sector": school,
            "kol_or_ib": "KOL",
            "institution": note,
            "bio": note,
            "focus": focus,
            "x_handle": "",
            "search_terms": [name] + ([alt] if alt else []),
            "active": True,
            "added_date": "2026-08-20",
            "forecast_school": school,
            "forecast_region": region,
            "forecast_cadence": cadence,
            "source_url": url,
            "youtube_channel_id": ch,
            "_source_note": "2026-08-20 新增: 周期/术数派金融预测者, URL 经实访验证",
        }
        out.append(rec)
    return out


def main():
    reg = json.load(open(REG, encoding="utf-8"))
    kols = reg["kols"]
    existing = {norm(k.get("display_name")) for k in kols}
    existing |= {norm(t) for k in kols for t in (k.get("search_terms") or [])}

    new = build(WESTERN, "西方") + build(CHINESE, "中文")
    added, skipped = [], []
    for rec in new:
        keys = {norm(rec["display_name"])} | {norm(t) for t in rec["search_terms"]}
        if keys & existing:
            skipped.append(rec["display_name"])
            continue
        kols.append(rec)
        existing |= keys
        added.append(rec["display_name"])

    reg["_count"] = len(kols)
    reg["_last_updated"] = "2026-08-20"
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"新增 {len(added)} 人, 跳过(重复) {len(skipped)} 人, 名册总数 {len(kols)}")
    for n in added:
        print("  + " + n)
    for n in skipped:
        print("  = 已存在, 跳过: " + n)


if __name__ == "__main__":
    main()
