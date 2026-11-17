#!/usr/bin/env python3
"""Full photo backfill for ALL vehicles without photos.

Priority:
1. Wiki in-game photo (if wiki_url exists)
2. Variant base photo (reuse base model's photo)
3. Wikimedia Commons real-world photo (strict matching)

Writes directly to vehicles.json with periodic saves.
Logs to /tmp/photo_backfill_full.log
"""
import asyncio
import json
import sys

sys.path.insert(0, "/home/hatch/workspace/war-thunder-mobile-bot")
from bot import vehicles as veh


async def main():
    vs = veh.get_vehicles()
    targets = [v for v in vs if not v.get("photo_url")]
    print(f"backfilling photos for {len(targets)} vehicles", flush=True)
    
    done = 0
    for i, v in enumerate(targets):
        try:
            # 1. wiki in-game photo (if wiki_url)
            if v.get("wiki_url"):
                html = await asyncio.to_thread(veh._wiki_download, v["wiki_url"])
                if html:
                    photo = veh._extract_photo(html)
                    if photo:
                        v["photo_url"] = photo
                        v["photo_source"] = "wiki"
            # 2. variant base photo
            if not v.get("photo_url"):
                base_photo = veh._variant_base_photo(v)
                if base_photo:
                    v["photo_url"] = base_photo
                    v["photo_source"] = "variant"
            # 3. Commons real-world photo (use BASE name for variants)
            if not v.get("photo_url"):
                base_name = veh._base_name(v["name"])
                photo = await veh._commons_photo(base_name, v["branch"])
                if not photo and base_name != v["name"]:
                    photo = await veh._commons_photo(v["name"], v["branch"])
                if photo:
                    v["photo_url"] = photo
                    v["photo_source"] = "commons"
            v["enriched"] = True
            if v.get("photo_url"):
                done += 1
        except Exception as e:
            print(f"  {v['name']}: {e}", flush=True)
        
        if (i + 1) % 25 == 0:
            print(f"  progress {i+1}/{len(targets)} with_photo={done}", flush=True)
            await asyncio.to_thread(veh.save_vehicles)
    
    await asyncio.to_thread(veh.save_vehicles)
    print(f"DONE: {done}/{len(targets)} got photos", flush=True)


asyncio.run(main())
