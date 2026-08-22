"""期次(vintage)存档 —— 让「只有最新一期」的数据源积累出历史，供 dashboard 做 filter button。

★2026-08-22 (Chao 需求): IMF 债务/GDP 与 美国公司债 这类板块, fetcher 每次都是
  **实时抓 API、不落盘**, 所以磁盘上没有任何历史 vintage —— 想做「上一期 / 上上期」
  的切换按钮时无米下锅。本模块建立通用存档层:
     每次 build 时把当期结果快照存一份 → 攒够 2 期, dashboard 自动出 filter。

★重要纪律(与项目铁律一致):
  - **绝不为了凑按钮而编造历史期次**。今天首次启用时只有 1 期 = 只显示 1 期、不出按钮,
    下次数据源更新才有第 2 个按钮。诚实优先于好看。
  - 只在数据 status == "ok" 时存档; 抓失败(未找到/异常)一律不存, 避免空壳期次污染历史。
  - 同一 period_key 重复存 = 覆盖(幂等), 因为同一期数据被修订属正常(如 IMF 修订历史值)。

存储: data/vintages/<dataset>/<period_key>.json
  dataset   : "debt_gdp" | "corp_credit" | ...
  period_key: 该期的自然标识, 决定「多久算一期」——
              IMF WEO 一年发两次 → period_key = vintage 标签(如 "2026-04")或 as_of_year
              公司债日频 → 用**月度** period_key(如 "2026-08"), 否则一年 365 个按钮没法看

索引: data/vintages/<dataset>/_index.json
  {"dataset":..., "updated":..., "periods":[{"key","label","saved_at","as_of","note"}...]}
  periods 按 key 降序(最新在前)。
"""
import os
import json
import glob
from datetime import datetime

_BASE = os.path.join(os.path.dirname(__file__), "..", "data", "vintages")


def _ds_dir(dataset):
    return os.path.join(_BASE, dataset)


def _index_path(dataset):
    return os.path.join(_ds_dir(dataset), "_index.json")


def _load_index(dataset):
    p = _index_path(dataset)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {"dataset": dataset, "updated": None, "periods": []}


def _save_index(dataset, idx):
    os.makedirs(_ds_dir(dataset), exist_ok=True)
    idx["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
    idx["periods"] = sorted(idx["periods"], key=lambda x: x.get("key", ""), reverse=True)
    json.dump(idx, open(_index_path(dataset), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def save_vintage(dataset, period_key, payload, label=None, note=None, max_keep=8):
    """存一期快照。返回 (saved: bool, reason: str)。

    payload: fetcher 的完整返回 dict。**必须 status == "ok" 才存**。
    period_key: 期次键(如 "2026-08"); 同键覆盖。
    max_keep: 最多保留期数(超出删最旧), 防止无限膨胀。
    """
    if not isinstance(payload, dict):
        return False, "payload 非 dict"
    if payload.get("status") != "ok":
        return False, f"status={payload.get('status')} 非 ok, 不存档(避免空壳期次)"
    if not period_key:
        return False, "period_key 为空"

    os.makedirs(_ds_dir(dataset), exist_ok=True)
    fp = os.path.join(_ds_dir(dataset), f"{period_key}.json")
    existed = os.path.exists(fp)
    json.dump(payload, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    idx = _load_index(dataset)
    idx["periods"] = [p for p in idx["periods"] if p.get("key") != period_key]
    idx["periods"].append({
        "key": period_key,
        "label": label or period_key,
        "saved_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "as_of": payload.get("as_of") or payload.get("as_of_year") or payload.get("vintage"),
        "note": note,
    })
    # 超额裁剪(删最旧的文件 + 索引项)
    idx["periods"] = sorted(idx["periods"], key=lambda x: x.get("key", ""), reverse=True)
    for drop in idx["periods"][max_keep:]:
        dp = os.path.join(_ds_dir(dataset), f"{drop['key']}.json")
        if os.path.exists(dp):
            try:
                os.remove(dp)
            except Exception:
                pass
    idx["periods"] = idx["periods"][:max_keep]
    _save_index(dataset, idx)
    return True, ("覆盖同期" if existed else "新增期次")


def load_vintages(dataset, limit=4):
    """读最近 limit 期(降序, 最新在前)。返回 [{key,label,as_of,payload}...]。

    ★只返回磁盘上真实存在的期次 —— 没有就是没有, 绝不补空位。
    """
    idx = _load_index(dataset)
    out = []
    for p in idx.get("periods", [])[:limit]:
        fp = os.path.join(_ds_dir(dataset), f"{p['key']}.json")
        if not os.path.exists(fp):
            continue
        try:
            payload = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        out.append({"key": p["key"], "label": p.get("label") or p["key"],
                    "as_of": p.get("as_of"), "saved_at": p.get("saved_at"),
                    "payload": payload})
    return out


def vintage_count(dataset):
    """当前已积累的真实期数(用于判断够不够出 filter)。"""
    return len([p for p in _load_index(dataset).get("periods", [])
                if os.path.exists(os.path.join(_ds_dir(dataset), f"{p['key']}.json"))])


# ── 各数据集的 period_key 规则(集中在此, 避免散落) ──

def period_key_debt_gdp(payload):
    """IMF WEO 一年发布两次(约 4 月 / 10 月)。

    ★period_key 用**发布期**(vintage)而非实绩年 —— 实绩年一年内不变(如 2025),
      两次发布会撞成同一个 key、第二次覆盖第一次, 永远攒不出第 2 个按钮。
      发布期规则: 当前月 <=9 → 当年 H1(4月版); >=10 → 当年 H2(10月版)。
      标签里再带上实绩年, 便于人读(如 "2026-H1 · 实绩2025")。
    """
    v = payload.get("vintage")
    if v:
        return str(v)[:7]
    now = datetime.utcnow()
    half = "H1" if now.month <= 9 else "H2"
    return f"{now.year}-{half}"


def label_debt_gdp(payload, key):
    y = payload.get("as_of_year")
    return f"IMF {key}" + (f" · 实绩{y}" if y else "")


def period_key_corp_credit(payload):
    """公司债是日频 —— 按**月**存一期, 否则一年 365 个按钮。
    用数据自身 as_of 的年月(不是今天), 保证数据滞后时期次仍准确。"""
    a = payload.get("as_of")
    if a and len(str(a)) >= 7:
        return str(a)[:7]
    return datetime.utcnow().strftime("%Y-%m")
