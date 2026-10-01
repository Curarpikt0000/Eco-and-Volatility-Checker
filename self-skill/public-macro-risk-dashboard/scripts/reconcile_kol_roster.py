#!/usr/bin/env python3
"""Reconcile the KOL roster across its three live sources and print an honest report.

Answers "在 track 的 KOL 是多少人?" from artifacts, never from docs prose.

  1. Notion "KOL List" DB  -> the SSOT
  2. data/kol_registry.json -> the GitHub mirror the collector reads
  3. newest data/kol/daily/*.json -> who was actually crawled last run

Usage (from the project root, e.g. ~/Projects/Eco-and-Volatility-Checker):
    .venv/bin/python scripts/reconcile_kol_roster.py
    .venv/bin/python scripts/reconcile_kol_roster.py --also ~/Projects/Economy-KOL-to-Notion

Requires NOTION_TOKEN in ./.env (flat KEY=value). Read-only: makes no writes anywhere.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

KOL_LIST_DB = "35947eb5-fd3c-800d-b852-cef31f9de6a5"
NOTION_VERSION = "2022-06-28"


def load_env(root: Path) -> dict:
    env = {}
    p = root / ".env"
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def norm(s: str) -> str:
    """Strip institution suffixes + whitespace. Without this a 124-vs-124 match
    reports ~25 phantom mismatches (Notion titles carry '（… 前 Goldman Sachs MD）')."""
    return re.sub(r"\s+", "", re.sub(r"[（(].*?[)）]", "", s or "")).lower()


def fetch_notion(token: str, db: str = KOL_LIST_DB) -> list[str]:
    import requests  # local import so the script degrades gracefully without network deps

    hdr = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{db}/query", headers=hdr, json=body, timeout=60
        )
        d = r.json()
        if "results" not in d:
            raise SystemExit(f"Notion query failed: {d}")
        rows += d["results"]
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    if not rows:
        return []
    # The title property here is "KOL / 机构", NOT "Name". Never hardcode "Name".
    props = rows[0]["properties"]
    title_key = next((k for k, v in props.items() if v["type"] == "title"), None)
    if title_key is None:
        raise SystemExit(f"no title property found; props={list(props)}")
    out = []
    for r in rows:
        p = r["properties"].get(title_key, {})
        out.append("".join(t["plain_text"] for t in p.get("title", [])).strip())
    return [n for n in out if n]


def read_registry(root: Path) -> list[str]:
    d = json.loads((root / "data" / "kol_registry.json").read_text())
    kols = d["kols"] if isinstance(d, dict) else d
    return [k["display_name"].strip() for k in kols if k.get("active", True)]


def read_latest_snapshot(root: Path):
    files = sorted(glob.glob(str(root / "data" / "kol" / "daily" / "*.json")))
    if not files:
        return None, [], Counter()
    f = files[-1]
    snap = json.loads(Path(f).read_text())
    kols = snap["kols"] if isinstance(snap, dict) else snap
    names = [s["kol"].strip() for s in kols]
    dirs = Counter(s.get("direction", "") for s in kols)
    return Path(f).name, names, dirs


def diff(a: list[str], b: list[str]):
    an = {norm(x): x for x in a}
    bn = {norm(x): x for x in b}
    return [an[k] for k in an if k not in bn], [bn[k] for k in bn if k not in an]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="project root (default: cwd)")
    ap.add_argument("--also", action="append", default=[],
                    help="sibling project root(s) mirroring the same SSOT")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    env = load_env(root)
    token = env.get("NOTION_TOKEN") or os.environ.get("NOTION_TOKEN")

    reg = read_registry(root)
    print(f"[2] local registry (active) : {len(reg)}   ({root/'data/kol_registry.json'})")

    notion = []
    if token:
        notion = fetch_notion(token)
        print(f"[1] Notion KOL List (SSOT) : {len(notion)} rows, {len(set(notion))} unique")
        only_n, only_l = diff(notion, reg)
        if not only_n and not only_l:
            print("    -> SSOT vs registry: 0 差异 (after stripping institution suffixes)")
        else:
            print(f"    -> Notion only ({len(only_n)}): {sorted(only_n)}")
            print(f"    -> local  only ({len(only_l)}): {sorted(only_l)}")
    else:
        print("[1] Notion KOL List        : SKIPPED (no NOTION_TOKEN in .env)")

    fname, snap, dirs = read_latest_snapshot(root)
    if fname:
        print(f"[3] latest snapshot {fname}: {len(snap)} crawled")
        miss, extra = diff(reg, snap)
        if miss:
            print(f"    -> 名册有/快照无 ({len(miss)}): {sorted(miss)}")
        if extra:
            print(f"    -> 快照有/名册无 ({len(extra)}): {sorted(extra)}")
        if miss or extra:
            print("    NOTE: a lag of one cron run is NORMAL when the roster sync landed after")
            print("          the last crawl. Check sync commit time vs snapshot mtime before")
            print("          calling this breakage. Do NOT patch the snapshot by hand.")
        print(f"    directions: {dict(dirs)}")

    for other in args.also:
        o = Path(other).expanduser().resolve()
        try:
            oreg = read_registry(o)
            print(f"[sibling] {o.name}: {len(oreg)} active"
                  + ("  <-- DRIFT vs SSOT" if notion and len(oreg) != len(notion) else ""))
        except Exception as e:  # noqa: BLE001
            print(f"[sibling] {o.name}: unreadable ({e})")

    print("\nReport the SSOT number as the answer; report [3] separately as "
          "'what the dashboard currently shows'. Never quote AGENTS.md/README counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
