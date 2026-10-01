# no_agent 同步类 cron：成功静默 + 自己的产物自己提交（2026-09-29，hermes-line-daily-sync）

## Chao 偏好（再次确认）
同步/备份类 cron 每天发「新增 N 行」= 刷屏。问「这个 cron 做啥、还要不要」时给三选项：
A 保留但成功静默（推荐）/ B 全停（暂停可恢复，不删表不删文件）/ C 原样。他选 A。
回答时先一句话说清：它做什么、下游有没有人读（本例：看板/日报都不读，只是 Notion 备份）。

## 改法
- 成功分支不 echo；行数追加到本地日志（scratch/<job>.log）备查。失败/解析失败/有错误照常输出。
- 周/月频的同组 job 不算刷屏，默认不动，问一句即可。

## 顺带发现的坑：路径排除把自己的产物排成了「别人的」
日报提交脚本 daily_commit_push.sh 按路径排除 `data/hermes_line/HDB_*.json`（当初以为是别的 agent 的），
且 90 分钟 mtime 窗口也赶不上 13:30 的 job → 这批文件 9/12 起再没进 git。
**「别人的文件」判定要查血缘（谁的脚本写的），不能凭目录名。** 修法 = 由产出它的 job 自己提交：
```bash
if [ -n "$(git status --porcelain -uall -- data/hermes_line/)" ]; then
  git add -- data/hermes_line/HDB_*.json && git commit -q -m "..." -- data/hermes_line/ || { echo 告警; exit 1; }
  PUSH_OUT=$(git push -q origin HEAD 2>&1)   # ★必须捕获: 远端提示走 stderr 会混进 cron 输出→成功也发消息
  git fetch -q origin
  [ "$(git rev-parse HEAD)" = "$(git rev-parse @{u})" ] || { echo 告警; echo "$PUSH_OUT"|tail -5; exit 1; }
fi
```
`commit -- <path>` 的 pathspec 保证不卷入工作区其他未提交改动。

## 验证配方（临时 bare repo，不碰真仓库）
`git init --bare remote.git && git clone remote.git w`；用假 `.venv/bin/python` 打印固定 JSON/退出码；
sed 把脚本里的真仓库路径换成临时目录；逐一跑：成功有新行（期望空输出+已 push+其他文件未被带入）/
成功无改动（不造空 commit）/ 有错误 / ingest 失败 / push 失败（set-url 到不存在路径）。
首轮就是靠「成功有新行」用例抓到 push 提示泄漏到 stdout。
