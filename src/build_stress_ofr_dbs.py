"""build_stress_ofr_dbs.py — 增量建 DB_STRESS + DB_OFR 两个新 Notion DB(幂等)。
只追加这两个 db_id 到 .env, 不动其他已有 DB(避免 build_notion_dbs.py 覆盖问题)。
存最新一期读数(as-of时序); 完整3年序列在 GitHub data/stress/。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import build_notion_dbs as b


def _num():
    return {"number": {"format": "number"}}


def build():
    ids = {}
    # DB-9 国债市场压力四联图最新值
    props_stress = {
        "Date": {"title": {}},
        "MOVE指数": _num(),
        "10年收益率": _num(),
        "2年收益率": _num(),
        "10年期限溢价": _num(),
        "IG企业债OAS": _num(),
        "10Y2Y曲线利差": _num(),
        "HY_OAS": _num(),
        "数据源": {"rich_text": {}},
    }
    ids["stress"] = b.create_db("Eco Volatility · 国债市场压力(四联图)", props_stress)

    # DB-10 OFR 金融压力指数
    props_ofr = {
        "Date": {"title": {}},
        "OFR_FSI总指数": _num(),
        "信用": _num(),
        "融资": _num(),
        "安全资产": _num(),
        "波动性": _num(),
        "数据源": {"rich_text": {}},
    }
    ids["ofr"] = b.create_db("Eco Volatility · OFR金融压力指数", props_ofr)

    # 追加写 .env(只追加缺失的键, 不动其他)
    envp = os.path.join(os.path.dirname(__file__), "..", ".env")
    existing = ""
    if os.path.exists(envp):
        existing = open(envp).read()
    to_add = []
    if ids.get("stress") and "DB_STRESS=" not in existing:
        to_add.append(f"DB_STRESS={ids['stress']}\n")
    if ids.get("ofr") and "DB_OFR=" not in existing:
        to_add.append(f"DB_OFR={ids['ofr']}\n")
    if to_add:
        with open(envp, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.writelines(to_add)
        print(f"[.env] 已追加: {[l.strip() for l in to_add]}")
    else:
        print("[.env] 无需追加(已存在或建库失败)")
    print("ids:", ids)
    return ids


if __name__ == "__main__":
    build()
