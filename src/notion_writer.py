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


def query_by_title(db_id, title_value, title_field="Date"):
    """按 title 精确匹配查行，返回 page_id 或 None。"""
    st, body = _req("POST", f"/databases/{db_id}/query",
                    {"filter": {"property": title_field, "title": {"equals": str(title_value)}},
                     "page_size": 1})
    if st == 200 and body.get("results"):
        return body["results"][0]["id"]
    return None


def _is_empty_prop(p):
    """判断一个 property 值是否为空(不应覆盖已有真值)。"""
    if not isinstance(p, dict):
        return False
    if "number" in p:
        return p["number"] is None
    if "select" in p:
        return p["select"] is None
    if "date" in p:
        return p["date"] is None
    if "rich_text" in p:
        return len(p["rich_text"]) == 0
    return False


def upsert(db_id, title_value, props, title_field="Date", skip_none=True):
    """幂等 upsert：存在则 patch，否则 create。返回 page_id 或 None。
    title_field: title 属性名(默认 Date, 持仓 DB 用 机构-期)。
    skip_none: PATCH 已有行时剔除空值字段(number=None/select=None/rich_text=[]),
      避免用"抓不到"覆盖 Notion 里已有的真值(BofA=9.7 类回归的根因防护)。新建行不剔除。"""
    props = dict(props)
    props[title_field] = prop_title(title_value)
    pid = query_by_title(db_id, title_value, title_field)
    if pid:
        patch_props = props
        if skip_none:
            # 剔除空值字段(但 title 永远保留)，不覆盖已有真值
            patch_props = {k: v for k, v in props.items()
                           if k == title_field or not _is_empty_prop(v)}
        st, body = _req("PATCH", f"/pages/{pid}", {"properties": patch_props})
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
