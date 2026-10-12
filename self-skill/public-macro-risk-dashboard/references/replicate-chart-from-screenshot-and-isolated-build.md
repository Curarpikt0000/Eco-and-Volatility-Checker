# 用户发图说「这个图你能做吗」：逐线核数据源 → 诚实版 → 隔离整站构建验证
（2026-10-09 实测：霍尔木兹四线图、金银类比路径图、ETF 隐含配置图、黄金波动率图，共 4 张）

## 1. 先逐线审计，不要笼统答「能/不能」
一张图常由多条线拼成，每条线来源不同。用 vision 逐项转录（标题/图例/轴/Source/标注，看不清写「看不清」），然后**每条线单独**找源并实测，输出一张表：线 | 公开来源 | 实测拿到几天 | 口径是否一致。
- 付费源（Bloomberg / LSEG / Kpler 日度 / ICI 官网 403）= **做不了，页面上写「付费数据，无公开来源」，绝不用别的数据冒充、绝不照着截图描点造数据。**
- 图上没有 Source 脚注时，先说「我读到的只有标题/图例/轴」，不要替作者补来源。
- 图上数字疑似笔误要点出（"$895 Trillion" 按 24 万亿×3.7% 应为 Billion），不照抄。
- 手画元素（阻力线、预测虚线、圈、方框）= 作者主观判断，不画，页面脚注写明。
- 回复末给「诚实版」方案并问是否同意；对齐方式等口径写出来让用户确认。

## 2. 反推对齐口径要拿图上标注对账，并如实写「只核了几条」
类比路径图（历史年份叠到 2026 日历轴）：
- 第一版「各线起点=1/28、缩放到起点价」**和原图对不上**（2006 金线缩放后冲到 6,747，原图最高 6,000）。
- 改成「取当年 1 月底起 120 天内最高收盘 → 对齐 2026 高点日 → 缩放到 2026 高点价」后，金 2008/银 2008 的低点天数与原图圈位一致（241 vs ~240 天，价差 2~3%）。
- 只核了 2 条线就在页面写「只用金 2008、银 2008 粗略对过，其余未逐条核对」，不夸大。
- 缩放后历史线读的是形状不是真实价格——口径说明里写明。月度数据（1973 datahub）不画成日线，写说明。

## 3. 用图上读数对账公式（区分 SMA/EMA 的好办法）
黄金波动率图：图上给了 2026-10-02 的 MA/BBW/ATR/GVZ 读数。
- 5 条均线偏差**全部一致 +0.5%** → 类型是 SMA，偏差来自期货 vs 现货基差；EMA 偏差 -0.4%~+8.8% 逐级拉大 → 排除。
- GVZ（FRED GVZCLS）与图完全一致；BB 宽度差 1~3%；ATR 同量级（Wilder 231 / 简单 207 夹着图 220.68）。
- 页面口径说明写「价格取 Yahoo COMEX 期货非现货」并把对账偏差原样写出。
- Yahoo 周线最后一根是周五（未收完），倒数第二根是周六标记日，间隔≠7 天——页面注明，别当 bug 修。

## 4. 接线范式（照白银期货曲线板块）
`external_data.fetch_xxx(cache_path=None)`（在线失败回退缓存、缓存也无则 status=error，绝不用空覆盖旧值）→ `dashboard._xxx_html(o)`（空/error 退「同步中」）→ `generate(..., xxx=None)` 形参 + 变量 + 板块 `<div class="part-title"><span class="part-num">＋</span>…` → `build_dashboard.py` 里 try/except 取数 + 传参。菜单由 `.part-title` 自动生成，不用改菜单。`generate()` 有 5 个必填形参(snap/checks/hit/gstats/overall)，用空 dict 调会 `KeyError: 'results'`——整页验证必须走真实构建，不要用占位参数调 generate。

## 5. 隔离整站构建（会写生产 Notion，必须隔离）
```
ISO=/tmp/eco_iso_x; mkdir -p $ISO/docs; cp -r src data → $ISO; rm $ISO/.env $ISO/data/kol_store.sqlite; rm -rf data/x_backfill data/web_watch data/tech_watch
# 把 write_stress_panels_notion / write_ofr_notion 改成 `return None`
硬检查(任一失败 exit): .env 不存在 | 'ISO: 隔离构建禁写 Notion' 计数==2 | 新函数名在隔离 src 里
```
- 脚本必须 `write_file` 成 .sh 再 `bash` 跑，长 heredoc 内联会被解析器 hardline 拦（exit -1，非操作本身错）。
- 后台 `terminal(background=True, notify_on_complete=True)` 跑 `build_dashboard.py`（约 8 分钟）；读日志首几行确认路径是 `/tmp/eco_iso_*`（不是生产目录）；完成后看 `BUILD_EXIT=` 行与末行门禁，不信通知措辞。
- 验收：①日志里新板块那行 status=ok ②**两页 `.part-title` 标题集合 diff：生产有新页无=0，新页有生产无=只多这一个**（41→42）③无头 Chromium：JS 零异常、菜单含新板块、SVG 数量、420px 窄屏不横向溢出 ④自己看截图（vision）再回 DOM 复核 ⑤生产 docs/index.html mtime 不变。
- 无头 Chromium 用 `~/.cdp-venv/bin/python`（有 websocket 包；项目 .venv 没有），启动须加 `--remote-allow-origins=*`，否则 WS 握手 403。
- 不手动发布；等 11:00 cron；次日用 `curl` 读回线上页面确认新板块出现。

## 6. 本轮踩过的小坑
- `/tmp` 被清后 `/tmp/bak_rl` 不存在：`cp a b && python … ` 链在第一步断掉，**后面的改写根本没执行**，却容易误以为改了。备份前先 `mkdir -p`，并事后 `grep -c` 新函数名确认真写入。
- 用 `sed -i` 删含 `os.remove` 的行会把 `for` 循环体删空 → IndentationError。改脚本用 `write_file` 重写，不用 sed 局部删。
- 补丁脚本里混进「新旧相同」的无意义替换会让 `assert count==1` 失败；断言在写盘之前，所以文件没被改坏，去掉该行重跑即可。
- 纵轴刻度用 `10**(len(str(int(range)))-1)/2` 在 range≈1700 时只给 3 档；改成目标约 6 档的「好看步长」（1/2/2.5/5/10×10^k 选最近）。
