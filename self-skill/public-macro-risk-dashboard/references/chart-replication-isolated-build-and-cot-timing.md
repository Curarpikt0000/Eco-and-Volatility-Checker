# 截图复刻新图 + 隔离整站构建 + COT 发布时差(2026-10-09/10 实战沉淀)

## 1. 「Chao 发一张截图:这个图你能做么」的固定流程
1. `vision_analyze` 转录图上所有读数(最后价、均线值、指标值、来源水印)。**图片缓存会被清**(霍尔木兹原图 1 天后就没了),要用的数字/事件表当场落盘到 /tmp 或 data/。
2. 逐线探数据源并**对账**:拿图上读数 vs 自算值(均线类型靠偏差方向判:5 条都 +0.5% = SMA+期货/现货基差;EMA 排除)。对不上的不写、对上的写出偏差。
3. 「诚实版」口径:取不到的线不画并写原因(付费 Bloomberg/LSEG/Kpler/NCAGS);作者手画元素(阻力线/预测虚线/灰圈)不画;图上疑似笔误不照抄;历史对齐若是反推必须写在图下并说明只核了哪几条线;价格口径(Yahoo 期货 vs 现货定盘)必须写明。
4. 事件类(如袭击)**逐条找官方编号**(UKMTO 官网 403 但官方 PDF/JMIC 公告可读);原图日期查出是别的事(海盗/美军封锁/阿曼湾/红海)的不画,放进 excluded 清单并写理由;图上数字(如「AIS 峰值 61」)与官方逐日最大值(51)对不上就不写。
5. 联邦基金/金/油这类跨单位图:左轴线性利率,金油共用一根**对数美元轴**,口径说明里讲清「单位不同只是同用美元计价」;1973 年前 WTI 是管制标价要注明;最新未发布月用 DFF/DCOILWTICO/Yahoo 日度当月均值补并写明。FRED **没有 T30Y2Y**,30Y-2Y 用 DGS30−DGS2 自算(同日 10Y−2Y 自算与 T10Y2Y 逐日一致,证明口径可靠)。

## 2. 新板块接线范式
`fetch_*`(失败回退缓存、绝不空覆盖真值)→ `data/*_cache.json` → `_xxx_html` → `generate()` 加形参(+`generate` 返回 dict 里加 html 键 + 模板里加 `.part-title` 区块)→ `build_dashboard.py` 抓取+传参。**每步写完单独 `py_compile`,不与写入链式。**

## 3. 隔离整站构建(会写生产 Notion,必须隔离)
- `/tmp/iso_setup_*.sh`:复制 src+data → 删 `.env`/kol_store.sqlite/x_backfill/web_watch → 用 python 把 `write_stress_panels_notion`、`write_ofr_notion` 改成 `return None` → **硬检查**(`.env` 不存在、Notion 禁写标记出现 2 次、新函数在)任一失败就 exit。
- 后台构建 `background=true, notify_on_complete`;完成通知 exit 0 不可信,读日志末行 `BUILD_EXIT=`、日志写入路径都在隔离目录、产物内逐 `.part-title` 与生产页比对(「生产有新页无」必须为空)。
- 备份目录 `/tmp/bak_rl` 会被清:备份步骤单独确认(`&&` 链曾因此中断,三文件未改)。
- 本机命令解析器会拦「一条里塞多件事」(exit -1,hardline 提示):拆成单条,不重试同一条。

## 4. 浏览器验证(headless chromium + CDP)
- Chrome 路径 `~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`;必须加 `--remote-allow-origins=*`;python 用 `~/.cdp-venv/bin/python`(带 websocket,项目 .venv 没有)。
- 检查:JS 零异常、菜单含新板块、SVG/polyline 数、420px 窄屏不横向溢出、开关(checkbox)实测。
- **悬停测试必须按目标序号换算屏幕占比** `frac=(ML+(W-ML-MR)*i/(n-1))/W`;凭感觉放鼠标会读到别的月份(曾把 1971 放成 1986),别把测试误差当 bug。
- `vision_analyze` 看截图能抓到标注被线压住这类可读性问题(油价峰值标注 → 加白色描边 stroke+paint-order 并错开位置);数字只当估读,要用数据核。

## 5. COT「怎么还停在上周」= 发布时差,不是故障
- CFTC 周二持仓、周五美东 15:30 发布 = **周六 04:30 JST**;cron 周五 11:00 JST 抓的必然是上一期。判据:Socrata `https://publicreporting.cftc.gov/api/views/6dca-aqww.json` 的 `rowsUpdatedAt` + 数据集 `$order report_date DESC` 最新报告日;再看 git 远端提交链(排除「GitHub 任务坏了」)。
- `run.py` 的 `fetch_cot_all()` 随主流程写快照+Notion,**没有只抓 COT 的入口**;手补快照会被下次 cron 覆盖且需写补丁,收益小,默认等下一次 cron,别因此写生产。
- 合约单位以数据里的 `contract_units` 为准:黄金 100 金衡盎司/手、白银 5000;吨 = 手×单位×31.1035/1e6。OI 折吨是「纸面吨数」(多数不交割),不要与 COMEX 库存直接比;多空是单边口径,不能相加。Legacy「商业/非商业」≠ Managed Money。
- 解读「商业净空缩小」要拆四项(商业多/空、非商业多/空)+OI 变化:商业空头减少 ≠ 看多,同周投机多头可能在减、整体 OI 在缩仓。

## 6. 日报「X→Y」文字来源
日报里「10Y-2Y 0.45→0.47」「16bp→2bp」是 **cron agent 润色出来的**,`daily_brief.py` 只出 ↑↓→ 箭头与锚点值。要让每天带数值变化/解释,改点是 `daily_brief.py` 的 `anchors` 或 cron prompt(改 cron 需 Chao 批准);解释用指标 `note`,不让 agent 临场编。银行融资压力(CP−Tbill)这类利差单日跳动先查 DCPF3M/DTB3 原始日值再解释(16bp→2bp 实为 CP 当天先涨、国库券滞后的一次性噪音,平时 0~8bp)。
