"""BIS (国际清算银行) 报告抓取 + 存储。

★数据源(免费公开, 无需key):
  1) BIS Quarterly Review(季度评论) —— 主力, 命名规律 r_qtYYMM.pdf(3/6/9/12月发),
     确定性可下载, 可精确 backfill 过去一年。
  2) BIS Bulletin(短文, 月度信号) —— 列表页 JS 渲染, 脚本难抓, 交由 daily cron
     agent 模式(web_extract/browser)动态发现最新几篇, 写入同一 store。

★存储: data/bis/reports.json (单一文件, 统一化, 避免散落 —— 遵循 handover.md §7 存储一致性原则)
  结构: {"updated": "YYYY-MM-DD", "reports": [ {报告条目}, ... ] }
  每条报告:
    {
      "id": "qr_2606",                    # 唯一键(qr_=Quarterly, bull_=Bulletin)
      "kind": "quarterly" | "bulletin",
      "title": "BIS Quarterly Review, June 2026",
      "date": "2026-06",                  # 发布年月
      "pdf_url": "https://www.bis.org/publ/qtrpdf/r_qt2606.pdf",
      "page_url": "https://www.bis.org/publ/quarterly.htm",  # 人读入口
      "summary": ["要点1", "要点2", ...],  # LLM 提炼(agent 模式填), 抓不到=[] 标 pending
      "summary_status": "ok" | "pending",  # pending=待 agent 摘要, 绝不编造
    }

★纪律: 摘要拿不到留空标 pending, 绝不编要点/日期/URL(遵循项目铁律)。
"""
import os
import json
import requests
from datetime import datetime

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bis", "reports.json")
QR_PDF_TMPL = "https://www.bis.org/publ/qtrpdf/r_qt{ym}.pdf"   # ym = YYMM, 如 2606
QR_PAGE = "https://www.bis.org/publ/quarterly.htm"
UA = {"User-Agent": "Mozilla/5.0 (EcoVolChecker research)"}


def _load_store():
    if os.path.exists(DATA_PATH):
        try:
            return json.load(open(DATA_PATH))
        except Exception:
            pass
    return {"updated": None, "reports": []}


def _save_store(store):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    store["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
    # 按 date 降序(最新在前), 稳定排序
    store["reports"] = sorted(
        store["reports"], key=lambda r: (r.get("date", ""), r.get("id", "")), reverse=True
    )
    json.dump(store, open(DATA_PATH, "w"), ensure_ascii=False, indent=1)


def _quarterly_months_back(n_quarters=5):
    """返回过去 n 个季度的 (YYMM, 年月标签, 月名) 列表(含当前应发的最近一期)。
    BIS Quarterly 在 3/6/9/12 月发。取当前日期往回推最近 n 个季度锚点。"""
    now = datetime.utcnow()
    # 找当前/最近的季度发布月(3,6,9,12)
    qmonths = [3, 6, 9, 12]
    out = []
    y, m = now.year, now.month
    # 定位 <= 当前月的最近一个季度月
    cur = max([q for q in qmonths if q <= m], default=None)
    if cur is None:
        y -= 1
        cur = 12
    idx = qmonths.index(cur)
    yy, ii = y, idx
    for _ in range(n_quarters):
        mm = qmonths[ii]
        out.append((f"{yy % 100:02d}{mm:02d}", f"{yy}-{mm:02d}", mm))
        ii -= 1
        if ii < 0:
            ii = 3
            yy -= 1
    return out


def _month_name(m):
    return ["", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"][m]


def discover_quarterly(n_quarters=5):
    """确定性发现过去 n 个季度的 Quarterly Review PDF(HTTP 200 才算存在)。
    返回新报告条目 list(summary 留 pending, 待 agent 填)。"""
    found = []
    for ym, date_label, mm in _quarterly_months_back(n_quarters):
        url = QR_PDF_TMPL.format(ym=ym)
        try:
            r = requests.head(url, headers=UA, timeout=20, allow_redirects=True)
            if r.status_code != 200:
                # 有些 HEAD 被拒, 再试 GET range
                r = requests.get(url, headers={**UA, "Range": "bytes=0-1"}, timeout=20)
            ok = r.status_code in (200, 206)
        except Exception:
            ok = False
        if ok:
            year = 2000 + int(ym[:2])
            found.append({
                "id": f"qr_{ym}",
                "kind": "quarterly",
                "title": f"BIS Quarterly Review, {_month_name(mm)} {year}",
                "date": date_label,
                "pdf_url": url,
                "page_url": QR_PAGE,
                "summary": [],
                "summary_status": "pending",
            })
    return found


def sync_quarterly(n_quarters=5):
    """把发现到的 Quarterly Review 合并进 store(幂等: 已存在的 id 不覆盖已有摘要)。
    返回 (新增数, store)。"""
    store = _load_store()
    existing = {r["id"]: r for r in store["reports"]}
    added = 0
    for rep in discover_quarterly(n_quarters):
        if rep["id"] not in existing:
            store["reports"].append(rep)
            added += 1
        # 已存在: 保留原摘要(不覆盖 agent 已填的内容)
    _save_store(store)
    return added, store


def upsert_summary(report_id, summary_points, kind=None, title=None, date=None,
                   pdf_url=None, page_url=None):
    """由 agent 模式调用: 给某报告写入/更新摘要要点。若 report_id 不存在则新建(用于 Bulletin)。
    summary_points: list[str]。空 list => 保持 pending。"""
    store = _load_store()
    existing = {r["id"]: r for r in store["reports"]}
    if report_id in existing:
        rep = existing[report_id]
        if summary_points:
            rep["summary"] = summary_points
            rep["summary_status"] = "ok"
    else:
        rep = {
            "id": report_id,
            "kind": kind or ("bulletin" if report_id.startswith("bull_") else "quarterly"),
            "title": title or report_id,
            "date": date or "",
            "pdf_url": pdf_url or "",
            "page_url": page_url or "",
            "summary": summary_points or [],
            "summary_status": "ok" if summary_points else "pending",
        }
        store["reports"].append(rep)
    _save_store(store)
    return rep


def latest_report(kind=None):
    """返回最新一份报告(可按 kind 过滤)。用于 dashboard section 摘要。"""
    store = _load_store()
    reps = store["reports"]
    if kind:
        reps = [r for r in reps if r.get("kind") == kind]
    return reps[0] if reps else None


def all_reports():
    """返回全部报告(降序), 用于独立页 docs/bis/index.html。"""
    return _load_store()["reports"]


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_standalone_page(out_path=None):
    """生成独立页 docs/bis/index.html: 过去一年全部 BIS 报告要点卡片(莫兰迪配色, 与主 dashboard 一致)。
    返回写入路径。"""
    if out_path is None:
        out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "bis", "index.html")
    reps = all_reports()
    cards = []
    for r in reps:
        pts = r.get("summary", [])
        if pts and r.get("summary_status") == "ok":
            pts_html = "<ul class='pts'>" + "".join(f"<li>{_esc(p)}</li>" for p in pts) + "</ul>"
        else:
            pts_html = "<div class='pending'>摘要待更新（daily cron 扫描中，抓不到不编造）。</div>"
        pdf = r.get("pdf_url", "")
        pdf_link = (f"<a class='pdf' href='{_esc(pdf)}' target='_blank' rel='noopener'>原文 PDF ↗</a>"
                    if pdf else "")
        kind_label = {"quarterly": "Quarterly Review", "bulletin": "Bulletin"}.get(r.get("kind"), r.get("kind", ""))
        cards.append(
            f"<div class='rep-card'>"
            f"<div class='rep-head'><span class='rep-kind'>{_esc(kind_label)}</span>"
            f"<span class='rep-date'>{_esc(r.get('date',''))}</span></div>"
            f"<div class='rep-title'>{_esc(r.get('title',''))}</div>"
            f"{pts_html}"
            f"<div class='rep-foot'>{pdf_link}</div>"
            f"</div>"
        )
    cards_html = "\n".join(cards) if cards else "<p class='empty'>暂无 BIS 报告数据。</p>"
    updated = _load_store().get("updated", "")
    n = len(reps)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BIS 国际清算银行报告全库 · Eco & Volatility Checker</title>
<style>
  :root {{ --bg:#e8e3d8; --card:#f2eee5; --card2:#ebe6da; --ink:#3a3833; --muted:#8a8578;
           --line:#d4cdbe; --dust-blue:#6b7a8f; --accent:#7d8a6a; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
          font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; line-height:1.7; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 28px 18px 60px; }}
  .top {{ margin-bottom: 22px; }}
  .top h1 {{ font-size: 22px; margin: 0 0 6px; color: var(--ink); }}
  .top .sub {{ font-size: 13px; color: var(--muted); }}
  .top a.back {{ font-size: 12px; color:#fff; background:var(--dust-blue); padding:6px 14px;
                 border-radius:6px; text-decoration:none; display:inline-block; margin-top:10px; }}
  .rep-card {{ background: var(--card); border:1px solid var(--line); border-radius:10px;
               padding: 16px 18px; margin-bottom: 16px; }}
  .rep-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }}
  .rep-kind {{ font-size:11px; font-weight:600; color:#fff; background:var(--accent);
               padding:2px 9px; border-radius:5px; }}
  .rep-date {{ font-size:12px; color:var(--muted); }}
  .rep-title {{ font-size:15px; font-weight:700; color:var(--ink); margin-bottom:8px; }}
  .pts {{ margin:8px 0 10px; padding-left:20px; }}
  .pts li {{ margin-bottom:7px; font-size:13.5px; color:var(--ink); }}
  .pending {{ font-size:13px; color:var(--muted); padding:6px 0; }}
  .rep-foot {{ border-top:1px dashed var(--line); padding-top:8px; }}
  .pdf {{ font-size:12px; color:var(--dust-blue); text-decoration:none; }}
  .pdf:hover {{ text-decoration:underline; }}
  .empty {{ color:var(--muted); }}
  .foot {{ margin-top:24px; font-size:11px; color:var(--muted); text-align:center; }}
</style></head>
<body><div class="wrap">
  <div class="top">
    <h1>📄 BIS 国际清算银行报告全库</h1>
    <div class="sub">过去一年 {n} 份 · Quarterly Review 季度综述（3/6/9/12 月发） · 要点由文档实文提炼，不编造 · 更新 {_esc(updated)}</div>
    <a class="back" href="../index.html">← 返回 Eco &amp; Volatility Checker</a>
  </div>
  {cards_html}
  <div class="foot">数据源：<a class="pdf" href="https://www.bis.org/publ/quarterly.htm" target="_blank" rel="noopener">BIS Quarterly Review 官方页</a> · Bank for International Settlements。要点摘要基于报告实文，抓不到标"待更新"绝不编造。</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    open(out_path, "w", encoding="utf-8").write(html)
    return out_path


if __name__ == "__main__":
    print("=== BIS Quarterly Review 发现(过去5季度) ===")
    added, store = sync_quarterly(5)
    print(f"新增 {added} 份, store 共 {len(store['reports'])} 份报告")
    for r in store["reports"]:
        st = r["summary_status"]
        print(f"  [{r['kind']:9}] {r['date']} | {r['title']} | 摘要:{st} | {r['pdf_url']}")
