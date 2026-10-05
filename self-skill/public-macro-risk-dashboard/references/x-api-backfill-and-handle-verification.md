# X(Twitter) 官方 API 回填 KOL 言论 + 账号核对(2026-10 实测)

抓取层优先用官方 API;网页抓取(Chrome 隧道)只当兜底。Gromen 3 个月: 网页约 55 分钟+补读 125 次,API 不到 1 分钟且更完整(多找回 9 条、纠正 22 条截断)。

## 计费/接口事实(docs.x.com + 实测)
- 按量计费: 读帖 $0.005/条, 读用户 $0.01/个, 同资源同 UTC 日去重。search/all 在按量账号可用; 时间线 100/页; users/by 批量 100/次。
- 余额挂「开发者账号/项目」不是应用。`GET /2/usage/tweets`(Bearer)返回 project_id/project_usage,用它判断几个 token 是否同项目,别靠控制台页面猜。
- 402=token 有效但项目余额 0; 401=token 已被再生成/应用删除(别误记成「有效但没钱」)。
- Chao 自述 $20 是 X 注册时赠送,同一台电脑三个账号只一个拿到 → 不要建议再开新号拿钱(可能触发风控); 预算=已有余额。
- token 只写 .env 新变量(X_BEARER_TOKEN_2/3...),经环境变量传值、不回显,写前 git check-ignore .env。聊天里出现过的 token 建议事后再生成。

## 必踩的 API 坑(Gromen 对账里栽过)
1. 长推文 `text` 被截断,必须优先取 `note_tweet.text`。
2. text 含 HTML 实体(&amp;): 入库前 html.unescape。
3. 仅链接/媒体或「引用转推且无评论」的帖 text 为空: 不能静默丢,单列 quote_only 保留链接+被引用 ID。
4. 分页边界重复返回 1 条(每页多付 $0.005): 按 id 去重落盘; 账本按返回条数记账更接近真实扣费。
5. `counts/all` 不可信: -is:reply/-is:retweet 不生效(4 种查询同一数),且低估约 3 倍(估 73 实拉 213)。不要用它估价。
6. 无按长度过滤的 operator; `-lang:und`/关键词预排除实测会误删真言论且只省几美分 → 不上。真省钱=不重拉(since_id 增量+post_id 账本)+缩范围。
7. 各人发帖量差 14 倍(3 个月 15~262 条): 单人样本不能外推 48 人成本,用区间并先小样。

## 封装与护栏(Eco-and-Volatility-Checker tools/x_backfill/xapi.py)
- 请求前按官方价预估,账本累计超 HARD_CAP 抛 BudgetExceeded; 402 也抛。
- 每页立即落盘(实测栽过: 内存里拉完才写,预算闸中途拦住导致 $1.44 付了没拿到)。per-query 熔断(默认 $4)。★写了≠有效: 动大额前先设极小上限(如 $0.03)实测真会拦。
- 推文原文/原始 JSON/账号简介属第三方内容: .gitignore 掉,公开仓库只放 ID+日期+链接+中文翻译。已推送历史里原文仍在,清除需 force push(破坏性,须 Chao 明确说)。先问公开边界再 commit,别先 commit 再讨论。

## 账号核对(名册 x_handle 全空)
- X 网页 People 搜索对约 37% 人名失灵(返回热门推荐: 特朗普/BBC),含 Dalio/Gromen → 结果必须过门禁,「搜不到」≠「没账号」,先拿必存在的对照组验。
- 猜账号后用 users/by 批量核对,先估价给 Chao 批再花。
- 门禁(对着 48 个已知答案调参有过拟合风险 → 无认证的一律进人审表):
  - 机构词里剔除名册英文名的姓/名(否则同名路人靠 'Hunt' 自己背书: Lacy Hunt→@Atlanta_Newz 钓鱼爱好者)。
  - 通用词(china/group/capital/macro…)不算机构词; 要求≥2 个强词或 1 个≥6 字母强词。
  - BAD 简介词补 commentary/tribute/festival/poetry/literary/satire/fan(诗人文学节号 @EigseMHartnett、模仿号 @ArunSFan 靠这些挡住)。
  - 认证号+粉丝≥1万+姓名双命中 可免机构词; 低粉丝(<5000)verified 逐个看简介(灵媒 29 粉丝=疑似模仿号)。

## 增量翻译复用门禁
- 旧译文复用只查数字/标签/@ 查不出「原文被截断后变长」(译文停在截断处、数字都在)。★记录译文所翻的 src,复用前要求新旧原文(去 URL/空白)逐字相同,否则重翻; 再全量独立复核 src==当前原文。
- 抽样验证必含最极端样本(被截断的、变短的、新增的)。

## 二模型分工(Chao 2026-10-04 授权)
我不能中途切模型。要「Opus 评审方案、Sonnet 执行」: 经 localhost:8800 代理调 claude-opus-5-5,事实全用实测值打包。坑: 长提示+小 max_tokens 时返回 choices=null(输出被 thinking 吃光),调大 max_tokens(实测 30000 OK)并在提示里限字数。Opus 结论要拿真实数据离线验证再采纳(其预过滤建议实测全不值得上)。
