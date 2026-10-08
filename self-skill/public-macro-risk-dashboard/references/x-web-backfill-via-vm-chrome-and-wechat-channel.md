# X 网页回填 / VM 专用 Chrome / 微信渠道（2026-10-07 实战）

## 不要占用 Chao 正在用的 Chrome
Chao 明确要求 background、不阻碍他正常使用。实测：经他 Mac 隧道 9333 用 `Target.createTarget(background=True)` 建的标签，`document.visibilityState` 仍是 visible（他所有标签都读 visible，分不出前后台）→ 不能自称「后台」。改走 **VM 专用无头 Chrome**：`tools/x_backfill/x_vm_chrome.py start|status|stop`（profile ~/.cache/x-vm-chrome 权限700，CDP 端口 9444，cookie 由 Chao 提供的文件经 Storage.setCookies 注入，不打印值、不入库）。`cdp_probe/x_day/x_backfill_6m` 用环境变量 `CDP_HOST`/`CDP_PORT` 切换（默认 localhost:9333）。启动用 `CDP_PORT=9444`，**不要设 CDP_HOST**（显示层会把 127.0.0.1 之类改写成占位串，传进去连不上，曾导致启动即停）。

## cookie 纪律
Chao 把 cookie 文件贴进聊天时：先说明风险与「删消息+X 退出登录」；他明确选方案并再次提供后才用，只读文件、不回显；用完问是否删除缓存副本（`~/.hermes/cache/documents/doc_*x.com_json_*`，删前核哈希、删后全盘找副本）。

## 回填执行器
`x_plan_6m.py` 生成每账号缺口区间；`x_backfill_6m.py [handle…]` 顺序跑，断点续跑，通道检查重试3次，连续3天失败自停。样板 Rory_Johnston 151 天用时 70.7 分（比预计 50 长），去重后 792 条、无验证页、无 capped。
- since:/until: 按 UTC 切且边界宽松：960 条里 813 条时间戳日期≠所在日文件，168 条同帖多日出现。入库必须按帖 created_at 取日期并按 id 去重，不能按文件名数帖。
- 漏抓率未验证（API 估 91 天 1755 条 vs 网页换算约 477）：放开其余账号前先对高产日做二分窗口重抓。

## 微信（搜狗）渠道
`src/report_leads_wechat.py` 独立产出 data/report_leads_wechat.json（不碰线上），复用 report_leads 门禁；开跑前用「黄金」做对照组。2026-10-07 实测限流已解除，10 家 48 条；0 条的家抽样确认是真没搜到（窗口内空或纯噪声），非门禁错杀。搜狗 link 中转会落验证码页，页脚须如实提示。微信无公开搜索 API；小红书无公开 API，走已登录浏览器（opencli 需 Browser Bridge 扩展，本机未连；CDP 搜索页可读标题/作者/日期）。
