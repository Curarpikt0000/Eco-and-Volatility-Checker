"""FRED API fetcher — 最可靠的源。VIX / HY OAS / 收益率曲线 / TIPS / DXY 等。"""
import requests
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as c

BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_latest(fred_id):
    """取某 FRED series 的最新非空值。返回 (value, as_of) 或 (None, None)。带重试。"""
    import time
    params = {"series_id": fred_id, "api_key": c.FRED_API_KEY,
              "file_type": "json", "sort_order": "desc", "limit": 20}
    for attempt in range(3):
        try:
            r = requests.get(BASE, params=params, timeout=25)
            obs = r.json().get("observations", [])
            for o in obs:  # 跳过 "." 空值
                if o["value"] not in (".", "", None):
                    return float(o["value"]), o["date"]
            return None, None
        except Exception:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None, None


def fetch_fred_history(fred_id, start="2025-01-01"):
    """取某 FRED series 从 start 至今的完整历史。返回 [(date, value), ...] 升序。"""
    params = {"series_id": fred_id, "api_key": c.FRED_API_KEY,
              "file_type": "json", "sort_order": "asc",
              "observation_start": start}
    out = []
    try:
        r = requests.get(BASE, params=params, timeout=40)
        for o in r.json().get("observations", []):
            if o["value"] not in (".", "", None):
                out.append((o["date"], float(o["value"])))
    except Exception:
        pass
    return out


def fetch(indicator):
    """标准接口：给一个 INDICATORS 条目，返回统一结果 dict。"""
    v, d = fetch_fred_latest(indicator["fred_id"])
    if v is None:
        return {"key": indicator["key"], "value": None, "as_of": None,
                "status": "未找到"}
    return {"key": indicator["key"], "value": v, "as_of": d, "status": "ok"}
