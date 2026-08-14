"""build_money_supply_db.py — 建 DB_MONEY_SUPPLY(inline, 幂等), 写回 .env。

三国货币供应量 M0/M1/M2(+日本 M3) 月度时序。每国一行, 'Country' 作 title 幂等。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config as c  # noqa: E402
from build_notion_dbs import create_db, _num_prop  # noqa: E402


def main():
    props = {
        "Country": {"title": {}},  # "国家 as_of" 作幂等 key
        "国家": {"select": {"options": [
            {"name": "美国 Fed", "color": "blue"},
            {"name": "日本 BoJ", "color": "red"},
            {"name": "中国 PBoC", "color": "yellow"},
        ]}},
        "口径日期": {"rich_text": {}},
        "单位": {"select": {"options": [
            {"name": "$B", "color": "blue"},
            {"name": "万亿円", "color": "red"},
            {"name": "万亿元", "color": "yellow"},
        ]}},
        "M0/基础货币": _num_prop(),
        "M1": _num_prop(),
        "M2": _num_prop(),
        "M3": _num_prop(),
        "来源": {"rich_text": {}},
    }
    db_id = create_db("Eco Volatility · 货币供应量 M0/M1/M2", props)
    print(f"[db] DB_MONEY_SUPPLY = {db_id}")

    # 写回 .env(幂等: 已有则跳过)
    envp = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = []
    if os.path.exists(envp):
        with open(envp) as f:
            lines = f.read().splitlines()
    if not any(ln.startswith("DB_MONEY_SUPPLY=") for ln in lines):
        lines.append(f"DB_MONEY_SUPPLY={db_id}")
        with open(envp, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"[env] 已写入 DB_MONEY_SUPPLY 到 {envp}")
    else:
        print("[env] DB_MONEY_SUPPLY 已在 .env, 跳过")
    return db_id


if __name__ == "__main__":
    main()
