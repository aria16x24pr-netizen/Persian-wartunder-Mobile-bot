# WTM Vehicle Roster — manifest (extracted 2026-10-16)

Source: https://wtmobile.fandom.com/wiki/War_Thunder_Mobile_Wiki (community wiki).
Method: wiki's MediaWiki API (wikitext of the 15 country pages + link-existence check). All 15 pages loaded, 0 failed.

## Counts
- Tanks: USA 123, Germany 91, USSR 71, China 43, Japan 43 → 371
- Aircraft: USA 62, Germany 59, USSR 58, Japan 51, Great Britain 51 → 281
- Naval: USA 32, Germany 30, USSR 33, Japan 27, Great Britain 28 → 150
- TOTAL: 802 entries (one known wiki-side duplicate: "IJN Mikuma" listed twice under Japan Naval Rank II — dedupe on import)

## Country pages
- Tanks: USA, Germany, USSR, China, Japan (ranks I–XIV)
- Aircraft: USA, Germany, USSR, Japan, Great Britain (ranks I–IX)
- Naval: USA, Germany, USSR, Japan, Great Britain (ranks I–VII)

## Per-row fields (as extracted)
name, branch (tank|aircraft|naval), country, rank ("Rank I".."Rank XIV"), type (see map below),
flags subset of [premium, platinum, event, blueprint, quest], wiki_url (set only if the vehicle page exists; null otherwise)

Tags that did NOT normalize (kept inside name, flags=[]): "(promo)", "(obtainable until tech tree update)", "TTD (?)".
Treat "(obtainable until tech tree update)" as legacy/quest-era entries — keep them, they are still real vehicles.

## Type normalization (for the bot)
- "Light tanks"→light, "Medium tanks"→medium, "Heavy tanks"→heavy, "SPGs"→spg, "SPAAs"→spaa
- "Fighters"→fighter, "Bombers"→bomber, "Strike aircraft"→strike
- "Destroyers"→destroyer, "Cruisers"→cruiser, "Battleships"→battleship, "Battlecruisers"→battlecruiser, "Submarines"→submarine

## Rank normalization
"Rank I"→1 … "Rank XIV"→14 (roman numeral parse).

## Known quirks
- Piped links: display name may differ from page title (e.g. "M4A3 (76) W"→page "M4A1 (76) W"; "Calliope"→"Calliope(tank)"). wiki_url always points at the real page.
- Misspelled wiki page: "Spitfire F Mk IX" → page "Spitifre F Mk IX" (use wiki_url, don't guess).
- Coverage of individual vehicle pages is UNEVEN: some have full stat blocks (caliber/penetration/reload/speed…), some are stubs (e.g. ZTZ96 = one line). Stats = v2 work; the roster alone powers browse+search v1.

## Refresh procedure (for the main agent, monthly or after big updates)
1. Fetch the 15 country pages via MediaWiki API (action=parse, prop=wikitext), 2s delay between calls.
2. Parse rank/type headings and bullet lists; extract name + parenthetical flags; resolve link targets; check page existence (red links → wiki_url=null).
3. Normalize with the maps above; dedupe exact duplicates; diff against vehicles.json (report new/removed/changed).
4. Manual review of the diff before shipping to the bot.

## Files in this folder
- schema.md — record schema + bot UX design
- vehicles.sample.json — 2 fully verified entries with stat blocks + Persian blurbs (my own words)
- roster-manifest.md — this file
