"""report_writer.py — 每日/周报的丰富内容写入。

1. write_daily_page_content: 往 Eco 每日报告 DB 的当天 page 内部写丰富 blocks
   (6部分骨架 + 分领域分析 + KOL变化 + 流动性要点)
2. write_github_copy: GitHub 每日副本 reports/<date>.md + data/daily/<date>.json
3. write_weekly: 周报 DB 一行 + GitHub reports/weekly/<week>.md

Notion block children API 追加。绝不编数字。时区 JST。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from notion_writer import _req, query_by_title

ROOT = os.path.join(os.path.dirname(__file__), "..")


# ─────────── Notion block helpers ───────────
def _h2(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text[:100]}}]}}


def _h3(text):
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text[:100]}}]}}


def _p(text):
    # Notion 单 rich_text 上限 2000 字符
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": str(text)[:1990]}}]}}


def _bullet(text):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(text)[:1990]}}]}}


def _callout(text, emoji="📊"):
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [{"type": "text", "text": {"content": str(text)[:1990]}}],
                        "icon": {"emoji": emoji}}}


def _divider():
    return {"object": "block", "type": "divider", "divider": {}}


def _clear_page_blocks(page_id):
    """删除 page 现有子 block(避免重复堆积)。"""
    st, b = _req("GET", f"/blocks/{page_id}/children?page_size=100")
    if st == 200:
        for blk in b.get("results", []):
            _req("DELETE", f"/blocks/{blk['id']}")


def write_daily_page_content(date_str, payload):
    """往每日报告 DB 当天 page 内部写丰富内容。
    payload: {
      overall, hit, sell_threshold_reached,
      sector_analysis: 分领域分析长文(str, 500-1000字),
      part2_stats: {short:(s,t),mid,long},
      part3_reads: {指标名: 解读},
      part4_conclusions: {short,mid,long},
      part5_triggers: [(cond,thr,desc,state),...],
      part6_focus: str,
      kol_changes: [dict],
      liquidity_notes: str,
      dashboard_url: str,
    }
    """
    db = c.NOTION_DB["report"]
    pid = query_by_title(db, date_str)
    if not pid:
        return None
    _clear_page_blocks(pid)

    blocks = []
    ov = payload.get("overall", "")
    hit = payload.get("hit", 0)
    blocks.append(_callout(f"综合信号 {ov} · 卖出触发 {hit}/7 · " +
                           ("⚠️ 已达分批卖出阈值" if payload.get("sell_threshold_reached") else "未达分批卖出阈值"),
                           "🔴" if hit >= 3 else ("🟡" if hit >= 1 else "🟢")))

    # 分领域分析长文(500-1000字)
    if payload.get("sector_analysis"):
        blocks.append(_h2("📈 分领域指标分析（状态变化重点）"))
        for para in payload["sector_analysis"].split("\n\n"):
            if para.strip():
                blocks.append(_p(para.strip()))

    # 第2部分 警报统计
    blocks.append(_h2("② 警报统计速览"))
    st = payload.get("part2_stats", {})
    for g, lbl in [("short", "短期"), ("mid", "中期"), ("long", "长期")]:
        if g in st:
            s, t = st[g]
            blocks.append(_bullet(f"{lbl}信号：{s} / {t} 未警报"))

    # 第3部分 逐条解读
    if payload.get("part3_reads"):
        blocks.append(_h2("③ 逐条简短解读"))
        for name, read in payload["part3_reads"].items():
            blocks.append(_bullet(f"{name}：{read}"))

    # 第4部分 短中长结论
    if payload.get("part4_conclusions"):
        blocks.append(_h2("④ 短中长期综合结论"))
        cc = payload["part4_conclusions"]
        blocks.append(_h3("短期（1-3 个月）"))
        blocks.append(_p(cc.get("short", "")))
        blocks.append(_h3("中期（3-12 个月）"))
        blocks.append(_p(cc.get("mid", "")))
        blocks.append(_h3("长期（1-3 年+）"))
        blocks.append(_p(cc.get("long", "")))

    # 第5部分 卖出触发
    if payload.get("part5_triggers"):
        blocks.append(_h2("⑤ 卖出触发状态追踪"))
        for cond, thr, desc, state in payload["part5_triggers"]:
            mark = {"✅": "✅已触发", "⚠️": "⚠️接近", "❌": "❌未触发"}.get(state, state)
            blocks.append(_bullet(f"{mark} · {cond}（阈值 {thr}）当前 {desc}"))
        blocks.append(_p(f"今日共 {hit}/7 触发。" +
                        ("已达「开始分批卖出」阈值（≥3）。" if hit >= 3 else "未达分批卖出阈值（需 ≥3）。")))

    # 第6部分 今日焦点
    if payload.get("part6_focus"):
        blocks.append(_h2("⑥ 今日最需关注的一条信号"))
        blocks.append(_callout(payload["part6_focus"], "🎯"))

    # KOL 状态变化
    if payload.get("kol_changes"):
        blocks.append(_h2("＋ 当日 KOL 状态变化（Eco 独立数据源）"))
        for ch in payload["kol_changes"][:15]:
            line = f"{ch['kol']}（{ch.get('sector','')}）：{ch.get('prev_dir','')} → {ch.get('new_dir','')}"
            if ch.get("comments"):
                line += f" — {ch['comments'][:200]}"
            blocks.append(_bullet(line))

    # 流动性要点
    if payload.get("liquidity_notes"):
        blocks.append(_h2("＋ 流动性要点（联动 Economic Dashboard）"))
        for para in payload["liquidity_notes"].split("\n"):
            if para.strip():
                blocks.append(_bullet(para.strip()))

    # 三大央行资产负债表摘要
    if payload.get("cb_balance_notes"):
        blocks.append(_h2("＋ 三大央行资产负债表（US/JP/CN · 带环比）"))
        for para in payload["cb_balance_notes"].split("\n"):
            if para.strip():
                blocks.append(_bullet(para.strip()))

    # 机构持仓 13F + Trump 要点
    if payload.get("holdings_notes"):
        blocks.append(_h2("＋ 机构持仓追踪（13F + Trump · 对比上期）"))
        for para in payload["holdings_notes"].split("\n"):
            if para.strip():
                blocks.append(_bullet(para.strip()))

    # dashboard 链接
    if payload.get("dashboard_url"):
        blocks.append(_divider())
        blocks.append(_p(f"📊 完整 dashboard: {payload['dashboard_url']}"))

    # 分批写入(Notion 一次最多 100 blocks)
    for i in range(0, len(blocks), 90):
        _req("PATCH", f"/blocks/{pid}/children", {"children": blocks[i:i + 90]})
    return pid


# ─────────── GitHub 每日副本 ───────────
def write_github_copy(date_str, md_content, json_data):
    """写 reports/<date>.md + data/daily/<date>.json。"""
    rdir = os.path.join(ROOT, "reports")
    ddir = os.path.join(ROOT, "data", "daily")
    os.makedirs(rdir, exist_ok=True)
    os.makedirs(ddir, exist_ok=True)
    open(os.path.join(rdir, f"{date_str}.md"), "w", encoding="utf-8").write(md_content)
    json.dump(json_data, open(os.path.join(ddir, f"{date_str}.json"), "w"),
              ensure_ascii=False, indent=2, default=str)
    # 也更新 reports/latest.md
    open(os.path.join(rdir, "latest.md"), "w", encoding="utf-8").write(md_content)
    return True


# ─────────── 周报 ───────────
def write_weekly(week_label, payload):
    """写周报 DB 一行 + GitHub reports/weekly/<week>.md。"""
    import notion_writer as nw
    db = c.NOTION_DB["weekly"]
    props = {
        "Week": nw.prop_title(week_label),
        "周期": nw.prop_text(payload.get("period", "")),
        "综合信号": nw.prop_select(payload.get("overall", "")),
        "周内最高触发数": nw.prop_num(payload.get("max_hit")),
        "周内红灯指标": nw.prop_text(payload.get("red_indicators", "")),
        "状态变化汇总": nw.prop_text(payload.get("status_changes", "")),
        "KOL周内转向": nw.prop_text(payload.get("kol_shifts", "")),
        "流动性周综述": nw.prop_text(payload.get("liquidity_summary", "")),
        "周综合结论": nw.prop_text(payload.get("conclusion", "")),
    }
    pid = nw.upsert(db, week_label, props)
    # GitHub 副本
    if payload.get("md"):
        wdir = os.path.join(ROOT, "reports", "weekly")
        os.makedirs(wdir, exist_ok=True)
        open(os.path.join(wdir, f"{week_label}.md"), "w", encoding="utf-8").write(payload["md"])
    return pid
