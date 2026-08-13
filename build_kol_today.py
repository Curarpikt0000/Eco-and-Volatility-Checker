import json, sys
from datetime import datetime, timedelta

TODAY = (datetime.utcnow()+timedelta(hours=9)).strftime('%Y-%m-%d')
reg = json.load(open('data/kol_registry.json'))
kols = [k for k in reg['kols'] if k.get('active', True)]

# 今日 web_search 真值判定 (id -> (direction, comments, targets))
# 方向枚举: 强烈看多/看多/分歧/中性/看空/强烈看空/未找到
V = {
 'jim_curry': ('分歧', '周期分析:金四年大周期2月见顶后回落,监测154日"秘密周期"回归,关注拐点', '金'),
 'james_turk': ('强烈看多', '贵金属界元老,2026年度金银估值与目标坚定看多,长期看空法币', '金/银'),
 'jordan_roy-byrne': ('看多', '金处长期牛市,回调休整为买点,"下一波涨势将很猛";金跌破200日线是第二次上车机会', '金/矿股'),
 'jesse_colombo': ('强烈看多', '银仍处长期牛市,1月以来回调只是健康喘息非新熊,目标$300-500', '银'),
 'larry_lepard': ('强烈看多', '比特币处"地板价"应买入,金长期看多,债务货币贬值主线', 'BTC/金'),
 'frank_giustra': ('看多', '这不是金的最终顶,铜供应紧缺须涨价(电气化+AI需求),商品超级周期', '金/铜'),
 'bob_haberkorn': ('看多', 'StoneX:金技术动能强,场外资金回流,Fed加息概率降利好', '金'),
 'marc_chandler': ('中性', 'Bannockburn:美元/日元宏观策略分析,7月CPI符合预期市场淡定,无强烈方向', '外汇'),
 'david_meger': ('看多', 'High Ridge Futures:金看多,能源价格回落+Fed加息概率降支撑', '金'),
 'dan_loeb': ('看多', 'Third Point Q2 +7.7%,看好AI基建,Amazon为第一重仓', 'AI/科技股'),
 'todd_bubba_horowitz': ('强烈看空', 'BubbaTrading:股市或崩40-60%,金看$6000,通胀失控;对股强烈看空', '金(多)/股(空)'),
 'ronny_stoeferle': ('强烈看多', 'In Gold We Trust:"金现在极度便宜",长期强烈看多', '金'),
 'massimiliano_castelli': ('看多', 'UBS:央行持续增持黄金+FX储备多元化(去美元化),看多金', '金'),
 'timothy_arcuri': ('看多', 'UBS半导体:Micron/Entegris/Intel买入评级,AI芯片需求强', '半导体'),
 'jeff_currie': ('强烈看多', 'Carlyle/Abaxx:商品超级周期,油市"tank bottoms"供应临界,AI需求驱动', '商品/油'),
 'andy_schectman': ('强烈看多', 'Miles Franklin:银或40X重估,实物市场紧张,BRICS用金逼美元重置', '金/银'),
 'jeff_snider': ('看空', 'Eurodollar Univ:信用/流动性风险回归,行为在信用事件前已改变,谨慎', '风险资产(空)'),
 'bill_gross': ('分歧', '债王:股市涨势有失速风险,估值蒙阴影但无崩盘,需新支撑', '股(谨慎)'),
 'kyle_bass': ('分歧', 'Hayman:看空中国经济,押注美国制造/Divergent,地缘冲突关联', '中国(空)/美国制造(多)'),
 'james_grant': ('看多', "Grant's:金反映91年货币贬值趋势,债务上升利好金", '金'),
 'lacy_hunt': ('看空', '★重大转向:Hoisington结束30年债牛,转看空长债/看涨收益率(通胀+财政)', '长债(空)'),
 'michael_saylor': ('强烈看多', 'Strategy:长期强烈看多比特币($7M愿景),Q2曾减持3588BTC补股息', 'BTC'),
 'ray_kurzweil': ('中性', 'AI奇点2029/2045长期乐观,非市场方向判断', '科技(长期乐观)'),
 'dan_ives': ('看多', 'Wedbush:科技/AI还有~15%上涨空间,"AI交易仍在第3局"', 'AI/科技股'),
 'doomberg': ('分歧', '油战后或崩至$25-30,但铀/核能/结构性商品看多;SPR创1983新低', '油(空)/铀商品(多)'),
 'eric_nuttall': ('看多', 'Ninepoint:能源市场太自满,油气仍看多但精选个股', '油气股'),
 'chris_vermeulen': ('看多', 'Technical Traders:大盘坚定看多,但金矿技术性熊市/金突破可能失败', '股(多)/金(分歧)'),
 'ag_thorson': ('强烈看多', '7月已见中年大底,矿股要跑赢,矿股已涨~30%;长期金$10000银$300', '金/银/矿股'),
 'vince_lanci': ('看多', 'Kontrarian:10月前对金不极度看多,耐心为主,PM回暖,看涨收益率曲线陡化', '金银(谨慎多)'),
 'gareth_soloway': ('分歧', 'Verified Investing:金两情景($5000突破vs回落$3500),BTC临突破', '金/BTC(分歧)'),
 'jay_martin': ('看多', 'Cambridge House:商品长期看多框架,多数人金银配置不足', '商品/金银'),
 'bob_moriarty': ('看多', '321gold:金银崩后看多,"保护好自己"', '金/银'),
 'adrian_day': ('看多', 'Adrian Day AM:金股情绪"50年最差"(逆向看多),看好金矿/特许权', '金矿'),
 'jeff_clark': ('看多', 'GoldSilver:金处早中期牛市,金股大幅跑赢其他资产', '金/银/矿股'),
 'rick_rule': ('看多', 'Rule Investment:结构性看多金银铀铜,欢迎金属回调,预期波动继续', '金银铀铜'),
 'keith_weiner': ('看多', 'Monetary Metals:金驱动因素完好无损,看多', '金/银'),
 'peter_krauth': ('看多', '银关键拐点,需求强供应少(太阳能/EV/电子),"银可翻倍"', '银'),
 'craig_hemke': ('强烈看多', 'TF Metals:金$5000+银翻倍,坚定看多,"烟花开始了"', '金/银'),
 'robert_kiyosaki': ('看多', '崩盘预警,看多金银BTC石油房产(硬资产),看空股/法币', '金银BTC(多)/股(空)'),
 'david_garofalo': ('看多', 'Gold Royalty:$5150金价基准,记录业绩,看多', '金'),
 'willem_middelkoop': ('强烈看多', '"大重置"已发生,中国逢跌就买,金已替代美债成储备,去美元化', '金'),
 'matthew_piepenburg': ('强烈看多', 'Von Greyerz:2026各资产"Uh-Oh"信号,金价终将飙升,7信号1金向', '金'),
 'alasdair_macleod': ('强烈看多', 'Goldmoney:"99%银投资者将震惊",中国或大动作,看多金银', '金/银'),
 'stephen_leeb': ('看多', 'Leeb Capital:中国储备巨量黄金,石油美元衰亡,金回归货币核心', '金/商品'),
 'daniel_oliver': ('看多', 'Myrmikan:结构性看空市场(债务/私人信用崩),但看多金矿', '金矿(多)/风险(空)'),
 's_druckenmiller': ('中性', 'Duquesne:组合Natera/Insmed生物科技+LYB,无单一强烈方向', '生物科技'),
 'jeffrey_gundlach': ('分歧', 'DoubleLine:债市押注Fed 9月加息应对通胀,强调债券/非美/黄金', '债/非美/金(多),股(谨慎)'),
 'michael_hartnett': ('看空', 'BofA:泡沫警报,私人客户股票配置创纪录66%/现金创新低,建议25/25/25/25四分散', '股(逆向卖出信号)'),
 'ted_oakley': ('看空', 'Oxbow:警告市场或40%回调,防御,寻被忽视个股中的便宜货', '股(空)'),
 'peter_schiff': ('强烈看多', '"崩盘已来",金看$11400,看空美元/BTC,强烈看多金银,2026美国式危机', '金银(多)/美元BTC(空)'),
 'james_rickards': ('强烈看多', '金$10000银$200,央行抛美元囤真钱', '金/银'),
 'ray_dalio': ('看空', '债务危机"心脏病发",货币秩序崩溃,金融重置,看空美元/风险,看多黄金硬资产', '美元/风险(空),金(多)'),
}

# 读上次
try:
    prev = json.load(open('data/kol_independent.json'))
    prev_map = {x['kol']: x.get('direction','未找到') for x in prev.get('all',[])}
except Exception:
    prev_map = {}

all_rows = []
changes = []
found = 0
for k in kols:
    kid = k['id']
    name = k['display_name']
    sector = k.get('detail_sector') or k.get('sector') or ''
    if kid in V:
        d, c, t = V[kid]
        found += 1
    else:
        d, c, t = '未找到', '', ''
    row = {'kol': name, 'sector': sector, 'direction': d, 'comments': c, 'targets': t, 'date': TODAY}
    all_rows.append(row)
    pd = prev_map.get(name, '未找到')
    if d != '未找到' and pd != '未找到' and d != pd:
        changes.append({'kol': name, 'sector': sector, 'prev_dir': pd, 'new_dir': d,
                        'date': TODAY, 'comments': c, 'targets': t})

out = {'date': TODAY, 'all': all_rows, 'changes': changes}
json.dump(out, open('data/kol_independent.json','w'), ensure_ascii=False, indent=2)
print(f'total={len(all_rows)} found={found} notfound={len(all_rows)-found} changes={len(changes)}')
for ch in changes:
    print('CHANGE:', ch['kol'], ch['prev_dir'], '->', ch['new_dir'])
