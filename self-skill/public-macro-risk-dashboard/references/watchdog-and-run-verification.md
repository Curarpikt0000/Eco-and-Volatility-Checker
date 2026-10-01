# 「今天到底跑了没有」与守护脚本自身的可靠性

Chao 高频问句:**「今天的任务跑了没有?」「今天的发了吗?」**
这两个问题看似简单,但用错判据会当场答错——本文件是这类问题的标准作业。
配套:`dashboard-data-integrity-audit.md`(产物层体检)、`shared-repo-cron-collision.md`(多写者)。

---

## 一、判据铁律:**产物是真值,cron 元数据不是**

2026-09-04 实例,我差点答错:

| 信号源 | 显示 | 真相 |
|---|---|---|
| `cron/jobs.json` 的 `last_run_at` | 停在 **9/3** | ❌ 元数据回写滞后 |
| `next_run_at` | 跳到 **9/7**(周一) | ❌ 看着像「今天被跳过」 |
| **产物 `data/snapshots/2026-09-04.json`** | 存在,20 项指标 | ✅ |
| **dashboard 生成戳** | `2026-09-04 11:18 JST` | ✅ |
| **`git log`** | `daily 2026-09-04 @11:21` | ✅ |

**结论:日报正常跑完并已 push。** 我只看 cron 字段就险些报「今天被跳过」。

### 标准判定顺序(自上而下,先看产物)
```bash
# ① 今日产物在不在(最硬)
ls -l data/snapshots/$(date +%F).json
# ② 产物内部时间戳(防止是昨天的文件被 touch)
grep -oE 'id="update-time">[^<]*' docs/index.html | head -1
# ③ git 有没有今天的自动提交
git log --oneline -3 --date=format:'%m-%d %H:%M' --format='%h %ad %s'
# ④ 最后才看 cron 元数据(仅用于「下次何时跑」)
```

**推论**:`status=unknown` / `FAILED` / 元数据滞后 **都 ≠ 零产出**。
超时的任务产物常常是完整的。凭状态标签下结论必错——**查库/查文件/查 git**。

### 反向也成立:排程没到点 ≠ 没跑
问「今天的发了吗」时先 `date` 看现在几点,再对 cron 表达式。主日报 `0 11 * * 1-5`,
上午 10:00 问就是**还没到点**,直接说「11:00 才跑,不用管」,别去查一圈然后含糊其辞。

---

## 二、守护脚本的设计红线:**检查器必须比被检查对象更可靠**

2026-09-04 踩到的真事,教训比故障本身值钱:

三个 state.db 守护脚本(health check / auto snapshot / emergency swap)全都硬依赖
`/usr/bin/sqlite3` 这个**外部二进制**。当该二进制在环境层被移除后:

- `health_check` 把「**工具没了**」当成「**数据库坏了**」,连续报 BAD,
  **并真的推送了一条假的「state.db 损坏」告警**——而库实测 `quick_check=ok`、25,903 sessions 完好。
- `auto_snapshot` rc=127 连败 3 次,24 小时快照覆盖出现空洞,**且无人察觉**。

### 规则
1. **依赖要选最不容易消失的那一层**:`stdlib` > 语言包 > 系统包 > 手动安装。
   同样是查 SQLite 完整性,`python3 -c "import sqlite3"` 随 python 发行,比 apt 装的 CLI 稳得多。
2. **必须区分「工具不可用」与「目标损坏」**,并给出不同的退出语义。
   把两者混成一个 BAD,等于把监控变成假告警源——**假告警比没有告警更坏**,
   它会训练用户忽略所有告警(狼来了),真出事时反而没人信。
3. 检查器**抛异常时要能自证**:让探测脚本输出 `PYERR: <类型>: <原因>`,
   调用方据此区分「连库都打不开」和「库打开了但校验不过」。
4. **抽成共用探针**,别让同一个脆弱依赖散落在 3~4 个脚本里(本次要改 4 处才改干净)。

可复用探针骨架(替代对 CLI 的依赖):
```python
#!/usr/bin/env python3
"""sqlite_check.py <db> [quick|integrity] [depth] → 打印 'ok' / 问题 / 'PYERR: ...'"""
import sqlite3, sys
try:
    c = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True, timeout=50)  # 只读不抢锁
    for row in c.execute("PRAGMA quick_check(3);").fetchall()[:5]:
        print(row[0])
    c.close()
except Exception as e:
    print("PYERR: %s: %s" % (type(e).__name__, e))   # 与「数据损坏」区分对待
```
备份同理:用 `Connection.backup()`(同样是 SQLite backup API,WAL 安全)替代 `sqlite3 .backup`。

### 修完必须做的两件事
- **实跑三条链路**,不能只改代码:`health_check` 报 ok → 假 marker 被清除 →
  告警桥推送「恢复」通知。只改不跑 = 不知道假告警有没有解除。
- **主动向 Chao 认错**:「昨天 18:22 那条 state.db 损坏告警是假的,是我装的东西误报的」。
  诚实优先于讨好;告警可信度一旦受损,必须显式修复,不能让它悄悄过去。

---

## 三、多 agent 并发写同一 repo:提交隔离

本机多个项目 cron / 其他 agent 会同时改同一个 repo(实测撞到:`data/hermes_line/HDB_*.json`
是另一个 cron 13:32 写的;ChaoWiki 的 `log.md`、`pipelines/forecast-checker/*` 是
Forecast-Checker agent 几分钟前写的)。

- **绝不 `git add -A` / `git add -u`**。只 `git add` 自己明确改过的文件。
- 提交前 `git status --porcelain` + 比 mtime,认出「别人刚写的」。
- 暂存区隔离的自检:`M ` (第一列 M)=已暂存是我的;` M`(空格开头)=未暂存是别人的。
- push 后再 `git status` 复核一次,确认别人的改动**原样还在工作区**。
- 共享 wiki 的 `log.md` 常被占用;写不进就把内容放进自己拥有的 knowledge 页,别硬抢。

---

## 四、回答这类问题的表述规范

- **先给结论**(「跑了,今天零失败」/「没发,原因是 X」),再给证据表。
- 把**「还没到点」和「跑失败了」严格分开**说,别混成一句「暂无数据」。
- 报告失败时**同时给恢复证据**(例:昨天失败的 7 个今天分别几点恢复的),
  否则 Chao 无法判断是否已自愈。
- 自己引入的问题(假告警、临时修复会失效)**主动挑明,并说明失效时点**
  ——「明天 11:00 cron 一跑又会变空」是决策相关信息,不是压力。
