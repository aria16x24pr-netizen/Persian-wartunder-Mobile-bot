#!/usr/bin/env python3
"""Re-extract stats with max-logic (strongest wins) for already-enriched vehicles.

Only updates the stats field; never touches photo_url.
Writes progress to /tmp/stats_refresh.log.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/home/hatch/workspace/war-thunder-mobile-bot")
from bot import vehicles as veh


async def main():
    vs = veh.get_vehicles()
    targets = [v for v in vs if v.get("wiki_url") and v.get("stats")]
    print(f"refreshing stats for {len(targets)} vehicles", flush=True)
    updated = 0
    for i, v in enumerate(targets):
        try:
            html = await asyncio.to_thread(veh._wiki_download, v["wiki_url"])
            if html:
                new_stats = veh._extract_stats(html)
                if new_stats:
                    old = dict(v.get("stats") or {})
                    merged = dict(old)
                    merged.update(new_stats)
                    if merged != old:
                        v["stats"] = merged
                        updated += 1
        except Exception as e:
            print(f"  {v['name']}: {e}", flush=True)
        if (i + 1) % 20 == 0:
            print(f"  progress {i+1}/{len(targets)} updated={updated}", flush=True)
            await asyncio.to_thread(veh.save_vehicles)
    await asyncio.to_thread(veh.save_vehicles)
    print(f"DONE: updated {updated}/{len(targets)}", flush=True)


asyncio.run(main())
