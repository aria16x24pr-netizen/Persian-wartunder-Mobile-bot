"""Background backfill: real-world photos from Wikimedia Commons.

Writes results to a SEPARATE file (no race with the running bot).
Merge into vehicles.json afterwards with a brief bot stop.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace/war-thunder-mobile-bot"))
from bot import vehicles as veh

LIVE = os.path.expanduser("~/workspace/war-thunder-mobile-bot/data/vehicles.json")
OUT = "/tmp/commons_backfill.json"


def load_done() -> dict:
    try:
        return json.load(open(OUT))
    except Exception:
        return {}


async def main() -> None:
    done = load_done()
    vs = veh.get_vehicles()
    targets = [v for v in vs if not v.get("photo_url") and v["id"] not in done]
    print(f"targets: {len(targets)} (already done: {len(done)})", flush=True)
    for i, v in enumerate(targets):
        try:
            # 1) reuse base model's in-game photo for variants
            photo = veh._variant_base_photo(v)
            # 2) strict Commons fallback
            if not photo:
                photo = await veh._commons_photo(v.get("name", ""), v.get("branch", ""))
        except Exception as e:
            print(f"ERR {v['id']}: {e}", flush=True)
            photo = None
        done[v["id"]] = photo  # None = tried, no hit (don't retry)
        if (i + 1) % 10 == 0:
            json.dump(done, open(OUT, "w"))
            hits = sum(1 for x in done.values() if x)
            print(f"progress {i+1}/{len(targets)} hits={hits}", flush=True)
        await asyncio.sleep(1.5)
    json.dump(done, open(OUT, "w"))
    hits = sum(1 for x in done.values() if x)
    print(f"DONE total={len(done)} hits={hits}", flush=True)


asyncio.run(main())
