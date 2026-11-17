#!/usr/bin/env python3
"""Merge /tmp/photo_backfill_v2.json results into data/vehicles.json.

Single atomic write (tmp + os.replace). The running bot keeps its in-memory
cache; an admin must tap the admin-panel "db:reload" button afterwards
(callback db:reload -> veh.reload_vehicles()) for cards to show new photos.

Usage: .venv/bin/python tools/merge_backfill_v2.py [--apply]
Default is dry-run (prints what WOULD change). --apply writes.
"""
import json
import os
import sys

BASE = "/home/hatch/workspace/war-thunder-mobile-bot"
LIVE = os.path.join(BASE, "data/vehicles.json")
RES = "/tmp/photo_backfill_v2.json"


def main():
    apply = "--apply" in sys.argv
    vehicles = json.load(open(LIVE, encoding="utf-8"))
    results = json.load(open(RES, encoding="utf-8"))
    by_id = {v["id"]: v for v in vehicles}
    changed = 0
    skipped = 0
    for vid, r in results.items():
        v = by_id.get(vid)
        if v is None:
            print(f"  WARN unknown id {vid}")
            continue
        if v.get("photo_url"):
            skipped += 1
            continue
        v["photo_url"] = r["photo_url"]
        v["photo_source"] = r["photo_source"]
        v["enriched"] = True
        changed += 1
    with_photo = sum(1 for v in vehicles if v.get("photo_url"))
    print(f"vehicles: {len(vehicles)} | with photo after merge: {with_photo} "
          f"({with_photo/len(vehicles):.1%}) | changed: {changed} | skipped: {skipped}")
    if apply and changed:
        tmp = LIVE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(vehicles, f, ensure_ascii=False)
        os.replace(tmp, LIVE)
        print(f"APPLIED -> {LIVE}")
    elif not apply:
        print("dry-run: pass --apply to write")


main()
