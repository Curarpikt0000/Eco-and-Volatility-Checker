# Data Dictionary — Eco and Volatility Checker

本目录存放数据快照。每个数据文件必须在此登记：

| 文件 | 来源 | Query / 抓取方式 | 口径 | 拉取日期(JST) |
|---|---|---|---|---|
| _（示例）_ | | | | |

## 规则
- 未来分析优先复用已有数据，取不到再重取（省 Presto / API）
- 数据只进 Uber 内部 GitHub，绝不进个人 repo
- 单文件 >500M 直接裁剪或忽略
