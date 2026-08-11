"""build_notion_dbs.py — 在目标页建 3 个 inline DB(幂等)，把 db_id 写回 .env。

DB-1 indicators: 每日 17 指标时序(一日一行，每指标一列 + 信号灯)
DB-2 cot: 金银 COT 时序(metal+date 一行)
DB-3 report: 每日扫描报告(结论文本 + 触发计数)
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from notion_writer import _req

PARENT = c.NOTION_PARENT_PAGE


def _num_prop():
    return {"number": {"format": "number"}}


def find_existing_db(title):
    """在父页子块里找同名 child_database，返回 id 或 None(幂等)。"""
    st, body = _req("GET", f"/blocks/{PARENT}/children?page_size=100")
    if st == 200:
        for b in body.get("results", []):
            if b.get("type") == "child_database":
                t = b.get("child_database", {}).get("title", "")
                if t == title:
                    return b["id"]
    return None


def create_db(title, properties):
    existing = find_existing_db(title)
    if existing:
        print(f"[db] '{title}' 已存在: {existing}")
        return existing
    payload = {
        "parent": {"type": "page_id", "page_id": PARENT},
        "is_inline": True,
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    st, body = _req("POST", "/databases", payload)
    if st == 200:
        print(f"[db] '{title}' 建成: {body['id']}")
        return body["id"]
    print(f"[db] '{title}' 建库失败 {st}: {str(body)[:200]}")
    return None


def build():
    ids = {}

    # ── DB-1 indicators ──
    props1 = {"Date": {"title": {}}}
    for ind in c.INDICATORS:
        props1[ind["name_en"]] = _num_prop()
        props1[ind["name_en"] + " 信号"] = {"select": {"options": [
            {"name": "🟢", "color": "green"},
            {"name": "🟡", "color": "yellow"},
            {"name": "🔴", "color": "red"},
            {"name": "⚪", "color": "gray"},
        ]}}
    props1["触发计数"] = _num_prop()
    ids["indicators"] = create_db("Eco Volatility · 每日指标", props1)

    # ── DB-2 cot ──
    props2 = {
        "Date": {"title": {}},  # 格式 "gold 2026-08-04"
        "Metal": {"select": {"options": [{"name": "gold", "color": "yellow"},
                                          {"name": "silver", "color": "gray"}]}},
        "Report Date": {"date": {}},
        "Open Interest": _num_prop(),
        "Comm Long": _num_prop(),
        "Comm Short": _num_prop(),
        "Comm Net": _num_prop(),
        "Comm Net WoW": _num_prop(),
        "Comm Long WoW": _num_prop(),
        "Comm Short WoW": _num_prop(),
        "NonComm Net": _num_prop(),
        "Surge": {"select": {"options": [{"name": "⚠️突增", "color": "red"},
                                          {"name": "正常", "color": "default"}]}},
    }
    ids["cot"] = create_db("Eco Volatility · 金银 COT", props2)

    # ── DB-3 report ──
    props3 = {
        "Date": {"title": {}},
        "综合信号": {"select": {"options": [
            {"name": "🟢 平静", "color": "green"},
            {"name": "🟡 警戒", "color": "yellow"},
            {"name": "🔴 减仓", "color": "red"},
        ]}},
        "卖出触发数": _num_prop(),
        "短期警报": {"rich_text": {}},
        "中期警报": {"rich_text": {}},
        "长期警报": {"rich_text": {}},
        "综合结论": {"rich_text": {}},
        "今日焦点": {"rich_text": {}},
    }
    ids["report"] = create_db("Eco Volatility · 每日报告", props3)

    # 写回 .env
    envp = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = [l for l in open(envp)] if os.path.exists(envp) else []
    lines = [l for l in lines if not l.startswith(("DB_INDICATORS=", "DB_COT=", "DB_REPORT="))]
    lines.append(f"DB_INDICATORS={ids['indicators']}\n")
    lines.append(f"DB_COT={ids['cot']}\n")
    lines.append(f"DB_REPORT={ids['report']}\n")
    open(envp, "w").writelines(lines)
    print("\n[.env] 已写回 db ids:", json.dumps(ids, indent=2))
    return ids


if __name__ == "__main__":
    build()
