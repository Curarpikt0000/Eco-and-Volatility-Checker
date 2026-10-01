#!/bin/bash
# 单批 KOL 深度摘要子agent runner
# usage: run_batch.sh <batchN> <DATE>
set -e
cd <PROJECT_ROOT>
BATCH="$1"
DATE="$2"
BFILE="scratch/kol_deep_${DATE}/batches/${BATCH}.json"
OUTDIR="scratch/kol_deep_${DATE}/out"
mkdir -p "$OUTDIR"

PROMPT=$(cat <<EOF
你是 KOL 深度摘要子agent。工作目录 <PROJECT_ROOT>。
读名单文件 ${BFILE}（JSON 数组，每项含 id/name/sector/search_terms）。
对**每一个** KOL：
1) web_search 最多3次: "<name> latest market view 2026" / "<name> outlook gold stocks 2026" / "<name> interview 2026"（search_terms 非空则优先用第一个别名）。
2) 搜到有价值来源(文章/访谈/YouTube/报告)时用 web_extract 抓1-2个最相关 URL 拿正文，写出带细节的摘要(带数字/点位/时间窗口)。抓不到就跳过，不死磕。
3) 产出结构化摘要，**每人搜完立即单独落盘** 到 ${OUTDIR}/<id>.json，不要攒到最后。用 write_file 工具落盘。

落盘格式(单文件, 一个KOL一个json, 文件名用该KOL的id):
{"kol":"<name>","id":"<id>","sector":"<sector>","direction":"看多|看空|中性|未找到","targets":"","comments":"40字以内一句话","detail":"四段式","detail_status":"ok|thin|none","sources":[{"title":"","url":"","date":""}],"date":"${DATE}"}

detail 硬性格式(100-300中文字, 四段, 每段以「▸ 」开头, \\n 分隔):
▸ 核心论点：...
▸ 关键依据：...(尽量带具体数字)
▸ 时间与位置：...(点位/目标价/时间窗口, 没有写「未给出具体点位」)
▸ 标的与操作：...(涉及资产, 买/卖/观望)

铁律【绝不编造】: 只有一两句公开信息 → detail 如实写「公开信息有限, 仅检索到: <原文要点>」+ detail_status="thin"；完全搜不到 → direction="未找到", detail="", detail_status="none"。宁可标 thin/none 也不许凑字数。
comments 必写(卡片折叠显示)；detail 必写(卡片展开显示)；绝不能只写 comments 不写 detail。
处理完所有人后回复一行: DONE ${BATCH} 落盘N个。
EOF
)

hermes -z "$PROMPT" --provider custom -m claude-opus-4-8 2>&1
