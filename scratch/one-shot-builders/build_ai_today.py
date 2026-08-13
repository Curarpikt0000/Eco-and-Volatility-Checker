import json
from datetime import datetime, timedelta

TODAY = (datetime.utcnow()+timedelta(hours=9)).strftime('%Y-%m-%d')
snap = json.load(open(f'data/snapshots/{TODAY}.json'))
R = snap['results']
def v(k): return R.get(k,{}).get('value')

reads = {
 'vix': f"VIX {v('vix')} 低位,市场无恐慌,与9.7的BofA牛熊表极致乐观互相印证——安逸即风险。",
 'fear_greed': f"CNN F&G {v('fear_greed')} 处贪婪区,情绪偏热但未极端,短期动能仍在多方。",
 'aaii_bull_bear': "AAII 多空持平(bull≈bear),散户分歧加大,较前期乐观有所收敛。",
 'put_call': f"股票 Put/Call {v('put_call')} 偏低(call重),期权端偏多、防护不足,回撤时缺缓冲。",
 'bofa_fms_cash': f"BofA基金经理现金 {v('bofa_fms_cash')}% 逼近历史新低,机构满仓+低现金=典型晚周期拥挤,🔴。",
 'sofr_iorb': f"SOFR-IORB {v('sofr_iorb')}bp 为负,货币市场无压力,回购利率平稳。",
 'margin_debt': f"融资余额 ${v('margin_debt')}B(6月),YoY约+49%创天量,杠杆快速累积。",
 'margin_gdp': f"融资/GDP {v('margin_gdp')}% 处历史高位🔴,系统杠杆偏高、去杠杆一旦启动放大跌幅。",
 'ipo_count': f"年内IPO {int(v('ipo_count'))} 家,一级市场活跃,风险偏好高。",
 'insider': f"内部人买卖比 {v('insider')} 远低于长期均值0.39,高管不看好自家股票,🟢转谨慎信号。",
 'bofa_bull_bear': f"BofA Bull&Bear {v('bofa_bull_bear')} 远超8.0卖出线🔴,2021以来最高,极度乐观=逆向减仓信号。",
 'hy_oas': f"高收益利差 {v('hy_oas')}% 极窄,信用市场零担忧,风险定价过度乐观。",
 'ad_line': "NYSE A/D 背离(广度未跟随指数),上涨集中于少数权重股,内部走弱。",
 'buffett': f"巴菲特指标 {v('buffett')}% 处极端高估区🔴,总市值/GDP远超历史。",
 'cape': f"Shiller CAPE {v('cape')} 逼近历史峰值🔴,长期回报预期被显著压缩。",
 'yield_curve': f"10Y-2Y {v('yield_curve')} 已转正陡峭化,衰退担忧缓解但需警惕熊陡(通胀/财政驱动)。",
 'lei': "OECD领先指标口径回升,短期经济动能未失速(注:Conference Board LEI 6月-0.2%,H1 -0.3%,仍偏弱)。",
 'aaii_alloc': f"AAII股票配置 {v('aaii_alloc')}% 连续74个月高于均值61.5%🟡,散户长期重仓股票。",
}

notes = {
 'vix': "低波动+高乐观,警惕突发波动率跳升。",
 'fear_greed': "贪婪区,顺势但设好止损。",
 'aaii_bull_bear': "散户分歧收敛,情绪见顶迹象。",
 'put_call': "对冲不足,回撤缺垫。",
 'bofa_fms_cash': "现金创新低,晚周期拥挤,🔴。",
 'sofr_iorb': "货币市场平稳。",
 'margin_debt': "杠杆天量,脆弱。",
 'margin_gdp': "系统杠杆高位🔴。",
 'ipo_count': "一级火热,风险偏好高。",
 'insider': "高管谨慎,不买自家股。",
 'bofa_bull_bear': "9.7超卖出线,逆向减仓🔴。",
 'hy_oas': "信用零担忧,定价过乐观。",
 'ad_line': "广度背离,内部走弱。",
 'buffett': "极端高估🔴。",
 'cape': "估值近峰值🔴。",
 'yield_curve': "转正陡化,防熊陡。",
 'lei': "短期动能未失速。",
 'aaii_alloc': "散户长期重仓🟡。",
}

conclusions = {
 'short': "短期(周):综合🟡警戒,卖出触发1/7未达分批门槛。VIX低/F&G贪婪/put-call偏多显示动能仍在多方,可持有但降杠杆——融资余额天量+对冲不足,一旦波动率跳升缺缓冲。动作:不新增杠杆多头,持仓设硬止损,留5-10%现金应对突发。关注今晚30Y美债拍卖($250亿)与Fed准备金读数(已连续低于$3T,流动性缓冲薄)。",
 'mid': "中期(月):估值+情绪+杠杆三重红灯——BofA Bull&Bear 9.7(2021来最高)、基金经理现金3.2%(近历史低)、CAPE 42.3、巴菲特指标214%、融资/GDP 4.63%,均处极端区。这是典型晚周期拥挤格局。动作:分批再平衡,把高估值成长仓位部分换成现金/短债/黄金,机构已在做(Oxbow Q2加仓黄金ETF +13.8%)。Lacy Hunt结束30年债牛转看空长债,提示长端利率风险,久期敞口宜缩短。",
 'long': "长期(季+):结构上估值处历史极值区,长期回报预期被压缩;去美元化(外国央行减持美债、金替代储备)与AI资本开支超级周期并存。动作:维持黄金/贵金属战略配置(KOL贵金属阵营几乎一致强烈看多,央行持续增持),控制美股总敞口在舒适区,分散至非美/实物资产。不追高、保留干火药,等7项卖出触发累积到≥3再启动系统性分批减仓。",
}

focus = "今日焦点:情绪与估值指标集体亮红灯(BofA Bull&Bear 9.7创2021新高、基金经理现金3.2%近史低、CAPE 42/巴菲特214%),但触发计数仅1/7未达分批门槛——'贵而未崩'的晚周期拥挤。机构用脚投票:10家巨头(桥水/索罗斯/Appaloosa/杜肯/Tiger/Coatue等)Q1不约而同新建台积电(AI芯片超级共识),而唯一有Q2报告的Oxbow加仓黄金ETF+13.8%、清仓美银——从科技拥挤向黄金/能源实物悄悄挪仓。今晚30Y美债拍卖是流动性试金石。"

sector_analysis = (
"【波动率与情绪】VIX 15.28、CNN贪婪62、股票Put/Call 0.61(call重)——市场安逸到几乎没有对冲。最刺眼的是BofA Bull&Bear指标9.7,不仅远超8.0卖出线,更是2021年以来最高读数,叠加BofA基金经理现金占比降至3.2%(逼近历史新低),构成教科书式的'满仓+低现金+零恐慌'晚周期拥挤。这类组合历史上并不精确择时,但一旦有催化剂,回撤的斜率会很陡。散户端AAII多空转为持平,较前期的一边倒乐观已开始收敛,是情绪见顶的早期迹象。\n\n"
"【杠杆与信用】融资余额6月$1.502万亿、同比约+49%创天量,融资/GDP 4.63%处历史高位🔴——系统性杠杆是本轮最大的隐性风险,去杠杆一旦启动会放大跌幅。与之呼应,高收益利差仅2.72%极窄,信用市场对风险几乎零定价。内部人买卖比0.285远低于长期均值0.39,公司高管在用真金白银表达对自家股价的谨慎。货币市场层面SOFR-IORB为负、无压力,但Fed准备金已连续多日低于$3万亿、ON RRP归零级,流动性缓冲很薄,今晚30Y拍卖($250亿)与准备金读数是关键观察点。\n\n"
"【估值与周期】Shiller CAPE 42.3、巴菲特指标214%,双双处历史极端高估区🔴,长期回报预期被显著压缩。收益率曲线10Y-2Y转正至0.48并陡峭化,衰退担忧缓解,但要警惕的是'熊陡'——由通胀黏性与财政赤字驱动的长端利率上行。这正是Lacy Hunt本期的重大转向:Hoisington结束长达30年的债券多头,改为看空长债、看涨收益率,提示久期敞口需要缩短。\n\n"
"【贵金属与COT】金银COT commercial持仓(8/04口径)维持结构。KOL贵金属阵营几乎一边倒:Turk/Colombo/Craig Hemke/Schiff/Rickards/Piepenburg/Middelkoop/Alasdair Macleod等多位强烈看多,目标从金$10000到银$300不等,核心逻辑是去美元化+央行增持+债务货币化。7月被多位分析师(AG Thorson/Jesse Colombo)判定为中年大底,矿股已反弹约30%。分歧点在短期:Vince Lanci 10月前不极度看多,Chris Vermeulen认为金矿技术性仍偏弱、金突破可能失败。\n\n"
"【KOL情绪(独立全量覆盖)】本次自主web_search覆盖91位KOL,成功取得50位真值判定(后端间歇性限流致41位暂标'未找到',非数据缺失,将由后续cron补真值,绝不编造)。方向分布明显偏向'硬资产多头+风险资产谨慎':贵金属阵营强烈看多占多数;宏观阵营(Dalio/Schiff/Hartnett/Ted Oakley/David Hunter类)警示泡沫与债务风险、偏防御。最值得记的方向变化是Lacy Hunt结束30年债牛(看多长债→看空);Michael Hartnett维持泡沫警报并给出25/25/25/25四分散的post-bubble打法;Ted Oakley警告市场或40%回调。科技多头(Dan Ives/Cathie Wood/Timothy Arcuri)仍看AI还有上行空间,但Chamath警告AI支出将冲击盈利。\n\n"
"【央行流动性与资产负债表】Fed(8/05)总资产$6.749万亿,国债周增+103亿、准备金+88亿但仍低于$3万亿,FIMA海外回购周降-168亿(连续两周负,海外美元需求缓解);ON RRP -35.95%近归零。BoJ(7/31)总资产较上期+0.77%,JGB续增,经常项目存款+1.48%;日债10Y 2.815%仍远超2.5%红线、YCC退出风险'高'为核心风险,日债熊陡直接利好银行净息差。PBoC(7月)资产负债表环比持平。风控总分🟡紧张,日债🔴。\n\n"
"【机构持仓动向(13F)】本期最大看点:唯一披露Q2(2026-06-30,8/07备案)的Oxbow Advisors(Ted Oakley)加仓iShares黄金信托+13.8%、Vanguard指数+8.2%,新建Noble Corp(海上钻井)/Kimbell(能源特许权)/Idex,清仓美国银行(BAC)——一个从科技向黄金+能源实物挪仓的清晰信号,与其公开的'40%回调'警告一致。其余机构仍是Q1(3/31)快照,但共识极强:桥水/索罗斯/Appaloosa/杜肯/Tiger/Coatue/Whale Rock/Third Point/花旗/千禧等至少10家不约而同新建台积电(TSM)——AI芯片是当前最拥挤的机构共识。Berkshire新建Chevron/Chubb、清仓Amazon/Mastercard(继续防御+能源);Scion(Q3'25旧报)持PLTR/NVDA。政要端:佩洛西5/29大额买入INTC($1-5M)+UBER;Crenshaw 6/1卖出GOOG/AMZN/AAPL/META、买油ETF USOU;Tuberville减持科技(卖MSFT/AAPL/GOOGL/ORCL/PEP)。政要与Oxbow方向一致:从大盘科技向能源/价值轮动。"
)

out = {'reads': reads, 'notes': notes, 'conclusions': conclusions, 'focus': focus, 'sector_analysis': sector_analysis}
json.dump(out, open(f'data/ai_analysis_{TODAY}.json','w'), ensure_ascii=False, indent=2)
print('written', f'data/ai_analysis_{TODAY}.json', 'sector_len', len(sector_analysis))
