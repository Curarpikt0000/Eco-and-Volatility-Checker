"""build_holdings_db.py — 在父页最下建「Eco Volatility · 机构持仓(13F)」DB(幂等)，db_id 写回 .env。

一行 = 一个机构的一期 13F 报告。字段:
  机构-期(title) / KOL / 基金 / 报告期 / 上期 / 总市值($B) / 持仓数 /
  TOP持仓+变动(文本) / 新建仓(文本) / 清仓(文本) / 数据源
Trump 单独一行(数据源=公开披露PFD, 由 cron agent 填)。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import config as c
from notion_writer import _req

PARENT = c.NOTION_PARENT_PAGE
TITLE = "Eco Volatility · 机构持仓(13F)"


def find_existing_db(title):
    st, body = _req("GET", f"/blocks/{PARENT}/children?page_size=100")
    if st == 200:
        for b in body.get("results", []):
            if b.get("type") == "child_database":
                if b.get("child_database", {}).get("title", "") == title:
                    return b["id"]
    return None


def build():
    existing = find_existing_db(TITLE)
    if existing:
        print(f"[db] '{TITLE}' 已存在: {existing}")
        db_id = existing
    else:
        props = {
            "机构-期": {"title": {}},          # 如 "Berkshire Hathaway 2026-03-31"
            "KOL": {"rich_text": {}},
            "基金": {"rich_text": {}},
            "报告期": {"date": {}},
            "上期": {"rich_text": {}},
            "总市值_B": {"number": {"format": "number"}},
            "持仓数": {"number": {"format": "number"}},
            "TOP持仓与变动": {"rich_text": {}},
            "新建仓": {"rich_text": {}},
            "清仓": {"rich_text": {}},
            "数据源": {"select": {"options": [
                {"name": "SEC 13F", "color": "blue"},
                {"name": "公开披露PFD", "color": "orange"},
            ]}},
        }
        payload = {
            "parent": {"type": "page_id", "page_id": PARENT},
            "is_inline": True,
            "title": [{"type": "text", "text": {"content": TITLE}}],
            "properties": props,
        }
        st, body = _req("POST", "/databases", payload)
        if st != 200:
            print(f"[db] 建库失败 {st}: {str(body)[:300]}")
            return None
        db_id = body["id"]
        print(f"[db] '{TITLE}' 建成: {db_id}")

    # 写回 .env
    envp = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = [l for l in open(envp)] if os.path.exists(envp) else []
    lines = [l for l in lines if not l.startswith("DB_HOLDINGS=")]
    lines.append(f"DB_HOLDINGS={db_id}\n")
    open(envp, "w").writelines(lines)
    print(f"[.env] DB_HOLDINGS={db_id}")
    return db_id


if __name__ == "__main__":
    build()
