"""notion_writer.py — 幂等 upsert + 写后读回验证。

复用 Economic-Dashboard 模式：
  - 去重键 = 日期(每日一行) / COT 用 metal+date
  - query 已存在则 PATCH，否则 create
  - 写后 re-query 确认真值落地(API 自报不算证据)
时区：JST。
"""
import time
import requests
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config as c

API = "https://api.notion.com/v1"
HDR = {
    "Authorization": "Bearer " + c.NOTION_TOKEN,
    "Notion-Version": c.NOTION_VERSION,
    "Content-Type": "application/json",
}


def _req(method, path, payload=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.request(method, API + path, headers=HDR,
                                 json=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return r.status_code, r.json() if r.text else {}
        except Exception as e:
            if attempt == retries - 1:
                return None, {"error": str(e)}
            time.sleep(1.5 * (attempt + 1))
    return None, {}


def prop_title(v):
    return {"title": [{"text": {"content": str(v)}}]}

def prop_num(v):
    return {"number": (None if v is None else float(v))}

def prop_text(v):
    return {"rich_text": [{"text": {"content": str(v)[:2000]}}]} if v is not None else {"rich_text": []}

def prop_select(v):
    return {"select": ({"name": str(v)} if v else None)}

def prop_date(v):
    return {"date": ({"start": v} if v else None)}


def query_by_title(db_id, title_value):
    """按 title 精确匹配查行，返回 page_id 或 None。"""
    st, body = _req("POST", f"/databases/{db_id}/query",
                    {"filter": {"property": "Date", "title": {"equals": str(title_value)}},
                     "page_size": 1})
    if st == 200 and body.get("results"):
        return body["results"][0]["id"]
    return None


def upsert(db_id, title_value, props):
    """幂等 upsert：存在则 patch，否则 create。返回 page_id 或 None。"""
    props = dict(props)
    props["Date"] = prop_title(title_value)
    pid = query_by_title(db_id, title_value)
    if pid:
        st, body = _req("PATCH", f"/pages/{pid}", {"properties": props})
    else:
        st, body = _req("POST", "/pages",
                        {"parent": {"database_id": db_id}, "properties": props})
        pid = body.get("id")
    if st not in (200, 201):
        print(f"[notion] upsert FAIL {st}: {str(body)[:200]}")
        return None
    return pid


def read_back(db_id, title_value, field):
    """读回验证：re-query 该行确认某数值字段真值。"""
    pid = query_by_title(db_id, title_value)
    if not pid:
        return None
    st, body = _req("GET", f"/pages/{pid}")
    if st == 200:
        p = body.get("properties", {}).get(field, {})
        return p.get("number")
    return None
