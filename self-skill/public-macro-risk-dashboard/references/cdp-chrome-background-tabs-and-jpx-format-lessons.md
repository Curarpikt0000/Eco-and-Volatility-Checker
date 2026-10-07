# CDP 借 Chao Chrome 读网页 + 静默停更两条教训 (2026-10-07)

## 1. 借 Chao 的 Chrome(隧道 9333)读 X/小红书: 不可能真「后台」
- Chao 明确要求「background 去跑,不要阻碍我 chrome 正常使用」。
- 实测: Target.createTarget(background=True) 新建的标签 document.visibilityState=visible|focus=true;
  他 Chrome 里所有已开标签在 CDP 里也全是 visible,读数分不出前后台 → 不得向他宣称「已是后台」。
- /json/new 会开前台标签(x_day.py 旧写法),用完靠 /json/close 关;一闪而过会打断他。
- 可用方案(让他选,别自己定): 甲=VM 上独立无头 Chrome + 他手动登录一次(经 ssh -L 转调试端口,密码/cookie 不进聊天);
  乙=约定夜间时段他不碰那个 Chrome 再跑;丙=等 X API 充值走 API。
- 他再次把含 auth_token/ct0 的 cookie JSON 直接发进聊天: 一律不读不用,提醒删消息+X 退出登录(token 有效到 2027),
  Drive/X 走手动登录或 scp,不走聊天。上传文件副本在 ~/.hermes/cache/documents/,问他是否删。
- 杀进程只用精确 PID(pgrep→kill),不要 pkill -f。
- x_day.py 旧版写死 sys.path /tmp 找 cdp_probe, /tmp 被清会 ImportError → 已改为脚本同目录。

## 2. 「fetcher 不报错+缓存每天重写+日报标 ok」= 静默停更
- 案例: 日本外资周流停在 09-11。JPX 自 2026-09 第 3 周起把发布格式从存档页 stock_val_1_YYMMWW.xls
  (海外投资家差引 col6)换成 index 页 stock_1_w_YYYYMMDD_YYYYMMDD.xlsx(横向多投资者块,海外投資家差引 col21,
  Prime 金额行=「プライム」行的下一行 Value)。旧解析器只扫存档页→抓不到新周,但不报错。
- 修法: 并入新路径 + 自洽校验(买−卖==差引±2,不符丢弃) + 用不经函数的独立读法对账 + 旧点 0 丢失/0 变值。
- 单位核对看 PDF 页眉「千円 1,000 yen」,不是靠量级猜。
- 通用: 任何「0 条/没更新」先拿对照组(必有结果的查询/已知有新数据的源)走同一通道,再下结论。
