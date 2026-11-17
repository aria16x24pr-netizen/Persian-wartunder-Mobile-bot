#!/usr/bin/env python3
"""One-off staging enrichment for the vehicle database (research run 2026-10-16).

Reads data/vehicles.json (READ-ONLY), fetches photo + game stats from the
WTM wiki for every record that has a wiki_url and is not yet enriched, using
the bot's own extraction functions, and writes the result to
data/vehicles.staging-enriched.json. The live file is NEVER touched here;
delivery swaps it in with a bot restart.

Also assigns wiki_url for 11 variant records whose base vehicle has a wiki
page (verified to exist via the MediaWiki API on 2026-10-16).
"""
import copy
import json
import sys
import time

sys.path.insert(0, "/home/hatch/workspace/war-thunder-mobile-bot")
from bot import vehicles as veh  # noqa: E402

# variant record id -> base wiki page title (page verified to exist)
RECOVERED = {
    "is-2-china-tank-china": "IS-2",
    "isu-152-china-tank-china": "ISU-152",
    "kv-2-zis-6-tank-ussr": "KV-2",
    "m10-gmc-quest-before-tech-tree-update-tank-usa": "M10 GMC",
    "m18-gmc-china-tank-china": "M18 GMC",
    "m24-china-tank-china": "M24",
    "m4a2-ussr-tank-ussr": "M4A2",
    "m4a5-canada-premium-tank-usa": "M4A5",
    "t26e5-event-tank-usa": "T26E5",
    "t28-event-tank-usa": "T28",
    "tiger-ii-sla-16-tank-germany": "Tiger II",
}
WIKI = "https://wtmobile.fandom.com/wiki/"

SRC = "/home/hatch/workspace/war-thunder-mobile-bot/data/vehicles.json"
DST = "/home/hatch/workspace/war-thunder-mobile-bot/data/vehicles.staging-enriched.json"

with open(SRC, encoding="utf-8") as f:
    records = json.load(f)
by_id = {r["id"]: r for r in records}

recovered = 0
for vid, title in RECOVERED.items():
    r = by_id.get(vid)
    if r and not r.get("wiki_url"):
        r["wiki_url"] = WIKI + title.replace(" ", "_")
        recovered += 1

todo = [r for r in records if r.get("wiki_url") and not r.get("enriched")]
print(f"records={len(records)} recovered_urls={recovered} to_enrich={len(todo)}", flush=True)

done = failed = 0
for r in todo:
    try:
        html = veh._wiki_download(r["wiki_url"])
        if html:
            photo = veh._extract_photo(html)
            if photo:
                r["photo_url"] = photo
            stats = veh._extract_stats(html)
            if stats:
                merged = dict(r.get("stats") or {})
                merged.update(stats)
                r["stats"] = merged
            done += 1
        else:
            failed += 1
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"FAILED {r['id']}: {e}", flush=True)
    r["enriched"] = True
    time.sleep(2)  # be gentle with the wiki, same as the bot's fill job
    if (done + failed) % 25 == 0:
        print(f"progress {done+failed}/{len(todo)}", flush=True)

with open(DST, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False)

photos = sum(1 for r in records if r.get("photo_url"))
stats = sum(1 for r in records if r.get("stats"))
enriched = sum(1 for r in records if r.get("enriched"))
print(f"STAGING DONE: enriched={enriched}/800 photos={photos} stats={stats} "
      f"ok={done} failed={failed} -> {DST}", flush=True)
