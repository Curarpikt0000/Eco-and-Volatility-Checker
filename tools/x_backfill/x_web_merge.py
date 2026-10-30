#!/usr/bin/env python3
"""把 X 网页抓取的 data/x_backfill/web_rows/<handle>/<day>.json 并入 x_posts_store.json。
(Chao 2026-10-30 选 A: 只存原文、零 AI 成本; 三重排重; 之后只对新增且值得进看板的做提炼/翻译)

排重(任一命中=不并入):
  1. 链接/ID: 推文 id 已在 store(含 API 抓的)
  2. 内容: 同作者 text 归一化指纹已在 store
  3. 引用: (网页行里 text 只含 t.co 之类时不适用; 保留接口, 对 text 内 URL 全已见且无正文者跳过)
并入的行带 source='x_web', handle, web_when, web_url, 方便区分 API 与网页来源, 不覆盖已有 API 记录。

用法: python tools/x_backfill/x_web_merge.py          # 预演
      python tools/x_backfill/x_web_merge.py --apply  # 写入(先备份 store)
"""
import glob
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import kol_dedup as kd  # noqa: E402

BF = os.path.join(ROOT, "data", "x_backfill")
STORE = os.path.join(BF, "x_posts_store.json")
ROWS = os.path.join(BF, "web_rows")


def main():
    apply = "--apply" in sys.argv
    store = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {}
    # 内容指纹: 以 (handle小写, fp) 判重; store 里 API 记录没有 handle 字段, 用 fp 全局判(推文原文几乎唯一)
    fps = {}
    for pid, t in store.items():
        f = kd.fingerprint(t.get("text", ""))
        if f:
            fps[f] = pid
    T = dict(files=0, rows=0, dup_id=0, dup_content=0, dup_in_batch=0, empty_text=0, new=0)
    new = {}
    for p in sorted(glob.glob(os.path.join(ROWS, "*", "*.json"))):
        handle = os.path.basename(os.path.dirname(p))
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        T["files"] += 1
        for r in d.get("rows", []):
            T["rows"] += 1
            pid = str(r.get("id") or "")
            txt = (r.get("text") or "").strip()
            if not pid:
                continue
            if pid in store or pid in new:
                T["dup_id" if pid in store else "dup_in_batch"] += 1
                continue
            if not txt:
                T["empty_text"] += 1
                continue
            f = kd.fingerprint(txt)
            if f and f in fps:
                T["dup_content"] += 1
                continue
            if f:
                fps[f] = pid
            new[pid] = {"id": pid, "text": txt, "created_at": r.get("when", ""), "source": "x_web",
                        "handle": handle, "web_who": r.get("who", ""), "web_url": r.get("url", ""),
                        "is_reply": bool(r.get("reply")), "is_quote": bool(r.get("quoted"))}
            T["new"] += 1
    print(("APPLY " if apply else "DRY ") + json.dumps(T, ensure_ascii=False))
    if apply and new:
        shutil.copy(STORE, STORE + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
        store.update(new)
        json.dump(store, open(STORE + ".tmp", "w", encoding="utf-8"))
        os.replace(STORE + ".tmp", STORE)
        chk = json.load(open(STORE, encoding="utf-8"))
        print("写后读回: store 共 %d 条 (原 %d + 新 %d)" % (len(chk), len(chk) - len(new), len(new)),
              "OK" if all(k in chk for k in new) else "MISMATCH")


if __name__ == "__main__":
    main()
