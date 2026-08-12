"""institution_meta.py — 18 家机构 + 政要的元数据(模块分组 + 两句话介绍)。

Chao 需求(2026-08):
- 每个机构名下两句话: ①以什么投资类型知名 ②社会地位
- dashboard 按模块分组展示(颜色/线框分区)
- 政要(佩洛西/川普等)持仓披露单独一个板块(数据源=国会交易披露 STOCK Act, 非13F)

模块(module)决定 dashboard 分区颜色。desc_type/desc_status 是两句话介绍。
"""

# 模块显示配置(颜色用于 dashboard 分区)
MODULES = {
    "价值传奇": {"color": "#7a8c6f", "en": "Value / Legendary"},        # 鼠尾草绿
    "宏观对冲": {"color": "#8c7a6f", "en": "Macro / Hedge"},            # 陶土棕
    "科技成长": {"color": "#6f7d8c", "en": "Tech / Growth"},           # 尘蓝
    "价值宏观": {"color": "#9c8452", "en": "Value / Activist"},         # 芥末黄
    "量化多策略": {"color": "#8c6f80", "en": "Quant / Multi-strat"},    # 紫灰
    "贵金属/另类": {"color": "#a08a5c", "en": "Precious Metals / Alt"},  # 金褐
    "政要披露": {"color": "#b0746e", "en": "Political / STOCK Act"},    # 砖红
}

# 机构元数据: fund -> {module, desc_type, desc_status}
INST_META = {
    # ── 原有 9 家(KOL 所在机构) ──
    "Berkshire Hathaway": {
        "module": "价值传奇",
        "desc_type": "以长期价值投资与高集中度蓝筹持仓闻名，代表人物沃伦·巴菲特。",
        "desc_status": "全球最受关注的投资旗舰，其季度持仓被视为价值投资风向标。",
    },
    "Bridgewater Associates": {
        "module": "宏观对冲",
        "desc_type": "全球最大对冲基金，以「全天候」风险平价与宏观资产配置著称，创始人瑞·达利欧。",
        "desc_status": "机构资金的宏观标杆，持仓反映其对经济周期与去全球化的判断。",
    },
    "Scion Asset Mgmt": {
        "module": "价值宏观",
        "desc_type": "逆向价值+做空押注，掌门迈克尔·伯里(《大空头》原型)，仓位极集中且常带对冲。",
        "desc_status": "散户最爱围观的「末日博士」，一举一动被媒体放大解读。",
    },
    "Soros Fund Mgmt": {
        "module": "宏观对冲",
        "desc_type": "宏观投机与反身性理论的代名词，乔治·索罗斯的家族办公室。",
        "desc_status": "「击败英格兰银行的人」，全球宏观交易的传奇符号。",
    },
    "ARK Investment Mgmt": {
        "module": "科技成长",
        "desc_type": "颠覆式创新主题投资(AI/基因/电动车)，掌门凯茜·伍德，高波动高信念。",
        "desc_status": "散户科技成长信仰的旗帜，牛市宠儿、熊市争议焦点。",
    },
    "Pershing Square": {
        "module": "价值宏观",
        "desc_type": "集中式激进价值投资，比尔·阿克曼常公开维权、押注少数几只重仓股。",
        "desc_status": "华尔街最善用社交媒体发声的激进投资者之一，话题性极强。",
    },
    "Appaloosa": {
        "module": "宏观对冲",
        "desc_type": "困境证券与逆向宏观交易，大卫·泰珀以精准抄底(2009银行股)闻名。",
        "desc_status": "被誉为当代最会择时的对冲基金经理之一，发言常搅动市场。",
    },
    "Duquesne Family Office": {
        "module": "宏观对冲",
        "desc_type": "宏观交易大师斯坦利·德鲁肯米勒的家族办公室，从不亏损年份的传奇纪录。",
        "desc_status": "索罗斯的前军师，宏观交易界公认的「活着的传奇」。",
    },
    "Oxbow Advisors": {
        "module": "价值传奇",
        "desc_type": "高净值财富管理与保守价值配置，创始人泰德·奥克利，重防御与现金流。",
        "desc_status": "面向富裕家庭的稳健派，常在播客警示泡沫与债务风险。",
    },
    # ── 科技/成长股 ──
    "Tiger Global": {
        "module": "科技成长",
        "desc_type": "全球科技成长与一二级市场联动投资，蔡斯·科尔曼，重仓互联网/软件龙头。",
        "desc_status": "「老虎系」鼻祖之一，科技成长投资的机构标杆。",
    },
    "Coatue Management": {
        "module": "科技成长",
        "desc_type": "科技长短仓对冲，菲利普·拉丰专注 AI/半导体/平台型科技股。",
        "desc_status": "硅谷与华尔街之间的桥梁，AI 投资风向的重要观察窗口。",
    },
    "Whale Rock Capital": {
        "module": "科技成长",
        "desc_type": "纯科技成长对冲，亚历克斯·萨瑟多特重仓 SaaS/云计算/AI 敞口。",
        "desc_status": "低调但业绩凶悍的科技专注型基金，机构圈内认可度高。",
    },
    # ── 价值/激进 ──
    "Baupost Group": {
        "module": "价值宏观",
        "desc_type": "深度价值与特殊机会投资，塞斯·卡拉曼(《安全边际》作者)的逆向堡垒。",
        "desc_status": "价值投资界「教科书级」人物，其年度信被奉为必读。",
    },
    "Third Point": {
        "module": "价值宏观",
        "desc_type": "事件驱动+激进维权投资，丹·勒布善于介入公司治理推动变革。",
        "desc_status": "华尔街著名维权投资者，季度信文风犀利、市场关注度高。",
    },
    "Icahn Enterprises": {
        "module": "价值宏观",
        "desc_type": "激进维权投资的开山鼻祖，卡尔·伊坎以逼宫董事会、拆分套利闻名。",
        "desc_status": "「企业狙击手」传奇，数十年维权战绩塑造了现代激进投资。",
    },
    # ── 量化/多策略 ──
    "Renaissance Technologies": {
        "module": "量化多策略",
        "desc_type": "量化交易之王(大奖章基金)，创始人吉姆·西蒙斯，纯数学模型驱动。",
        "desc_status": "对冲基金史上最成功的量化机构，持仓极度分散、信号隐晦。",
    },
    "Citadel Advisors": {
        "module": "量化多策略",
        "desc_type": "多策略平台巨头，肯·格里芬旗下，做市+量化+基本面多引擎。",
        "desc_status": "全球最赚钱的对冲基金之一，格里芬为华尔街与政界重要人物。",
    },
    "Millennium Management": {
        "module": "量化多策略",
        "desc_type": "多经理平台(pod shop)代表，伊兹·英格兰德，数百团队分散押注。",
        "desc_status": "多策略平台模式的标杆，管理规模巨大、机构影响力强。",
    },
}

# ── 政要持仓披露(数据源=国会交易披露 STOCK Act / PFD, 非13F) ──
# 数据由 cron agent web_search/web_extract 从 Capitol Trades / Quiver / Unusual Whales 补
POLITICAL_FIGURES = [
    {"name": "Nancy Pelosi", "name_zh": "南希·佩洛西", "role": "前众议院议长(众议员)",
     "source": "国会交易披露(STOCK Act)", "desc": "其家族科技股交易(常经其夫)被市场高度追踪,散户跟单现象显著。"},
    {"name": "Donald Trump", "name_zh": "唐纳德·特朗普", "role": "美国总统",
     "source": "年度财务披露(PFD)", "desc": "个人资产以地产/品牌授权为主,近年涉加密与自有媒体股,披露颗粒度较粗。"},
    {"name": "Dan Crenshaw", "name_zh": "丹·克伦肖", "role": "众议员(德州)",
     "source": "国会交易披露(STOCK Act)", "desc": "较活跃的国会交易者之一,能源/国防股交易受关注。"},
    {"name": "Tommy Tuberville", "name_zh": "汤米·图伯维尔", "role": "参议员(阿拉巴马)",
     "source": "国会交易披露(STOCK Act)", "desc": "国会中交易最频繁的成员之一,农业/大宗/科技均有涉猎。"},
]


def meta_for(fund):
    """取某机构元数据, 缺则返回默认。"""
    return INST_META.get(fund, {"module": "其他", "desc_type": "", "desc_status": ""})


def module_color(module):
    return MODULES.get(module, {}).get("color", "#8a8a80")
