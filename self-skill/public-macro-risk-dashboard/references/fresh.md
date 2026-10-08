# 数据新鲜度核查与回填实战教训 (2026-10-06/07)

## 1. 「日报 ok」≠「数据是活的」——三种静默停更
- **上游站自己停更**: GLD/SLV 读 comex-inventory-charts.pages.dev, 末日停 09-16, 页面照常渲染+ok, 20 天无人发现。生产 cron 在 Mac(路径写死 /Users/...), VM 看不到。解法: 脚本入库 tools/comex_inv/(路径参数化 INV_BASE), fetch_comex_inventory 本地自产→外站→缓存, 回落写进 note 不静默。
- **解析器被上游改版甩下**: 日本外资周流停 09-11。JPX 自 9 月第 3 周改发 stock_1_w_YYYYMMDD_YYYYMMDD.xlsx(仅 index 页, 海外投資家差引在 col21), 旧解析器只扫存档页 stock_val_1_*.xls。fetcher 不报错, 缓存文件每天重写但内容不变。**判据看「内容最大日期」不是 mtime**。修复后: 独立读原表重算对账 + 买−卖==差引自洽 + PDF 页眉读单位(千円)。
- **读取早于写入**: 周净 issue/stop 生产文件 11:04 生成, Notion 当天行 12:30 才写, 展示永远落后一天。

## 2. 审计更新频率的顺序
1. 先跑已有 tools/freshness_audit.py(40 fetcher, 带频率+容忍天数), 在**隔离副本**跑(rsync 排除 .git/.venv/docs; notion_writer.upsert 与 _req 非查询 POST/PATCH 改空操作)——整站 fetch 会写生产 Notion。
2. STALE 不直接采信, 逐个回官方源核最新观测(FRED API)。实测: 黄金出口(官方最新 2026-04-01)、信贷脉冲(4 国均 2025-10-01)是源头本来就慢。
3. INTERNAL_MISMATCH 先查是否**未来日期**(拍卖日历/互换到期日/年末标记)。
4. NO_DATE ≠ 没数据(日期可能在元组 ('2026-07', 值) 里)。
5. 静态 HTML 里板块 id(sec-0/sec-5)是 JS 运行时分配, 源码找不到; 静态审计用 .part-title 切块, 或无头 Chrome --dump-dom + 探针。

## 3. COT 节奏
数据日=周二, 发布=周五。周三看到「9/29 周」就是最新, 下一期 10-09。核对: Socrata max(report_date_as_yyyy_mm_dd) 全表 + 对照商品(原油)+ 另一数据集(6dca-aqww / 72hh-3qpy), 四口径同值才下结论。展示层应写「周频·周二数据周五发布·下一期 X」。

## 4. 徽章措辞陷阱
同板块同时出现「🟢 每季」和「🟡 滞后 189 天」相互矛盾(源头季度、_stale_badge 阈值不匹配)。只对**已回官方核实**的源改灰色「⏳ 源头季度更新, 最新 X(已是官方最新)」; 未核实的不写该断言(TIC 旧教训)。

## 5. 菜单 scrollspy 与页面顺序
根因: 同组成员相距数十屏被合并成一个菜单组, 用 DOM 序号 → 菜单倒退。修法: 严格按 DOM 顺序渲染, 同组被隔开标「(续)」。验证: 无头 Chrome 探针取 64 板块 y, 断言倒退次数==0(集合为空不算数)。

## 6. X 网页回填(VM 专用 Chrome)
- 用 Chao Mac Chrome 隧道(9333)开标签会弹前台打扰他; Target.createTarget(background=True) 实测仍 visible|focus=true(该 Chrome 所有标签都报 visible, 读数分不出前后台)。**别承诺「后台不打扰」**。
- 改用 VM 专用无头 Chrome(tools/x_backfill/x_vm_chrome.py: 独立 profile 700, localhost:9444, cookie 由用户提供文件经 Storage.setCookies 注入, 不打印值, 用后删文件)。Chao 贴 cookie 到聊天: 不读内容、只比哈希、提醒删消息+X 退出登录; 他明确选「甲」并再次提供时按授权用, 用完按「删除」精确删文件并复验。
- x_day.py 原写死 sys.path /tmp 找 cdp_probe, /tmp 被清即 ImportError → 已入库。端口主机用环境变量 CDP_PORT/CDP_HOST。**传 CDP_HOST=127.0.0.1 会被显示层改写成占位串导致连不上——不传, 默认 localhost**。tunnel_ok 加 3 次重试。
- since:/until: 按 UTC 切窗, 同帖出现在多个日文件(Rory 151 天: 960 条→去重 792, 813 条时间戳日≠文件日)。入库按帖时间戳取日期+id 去重; 网页漏抓率无法独立验证, 不得称「完整」。151 天≈70 分钟。

## 7. 报告线索渠道
搜狗微信: 免登录 requests 可用, 只给标题+摘要+时间戳, 链接是 weixin.sogou.com/link 中转, 点开常落验证码页(已在页脚写明)。0 条先抽样被丢条目再下结论(Gromen/Pozsar 窗口内真无结果, Zulauf 全噪声)。小红书: opencli 需浏览器扩展; 经 CDP 打开 search_result 页无需登录弹窗能读卡片, 中文译名「格罗门」全噪声, 英文名才有相关条。微信/小红书均无公开检索 API。
