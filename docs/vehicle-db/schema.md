# War Thunder Mobile — Vehicle Database: schema & feature design (draft)

## Data source evaluation (checked 2026-10-16)
- `https://wtmobile.fandom.com/wiki/War_Thunder_Mobile_Wiki` — community wiki, dedicated to WTM.
- Country pages list EVERY vehicle per rank & type with flags (premium/platinum/event/blueprint/quest).
  - Tanks: USA, Germany, USSR, China, Japan — ranks I–XIV, types: Light/Medium/Heavy/SPG/SPAA.
  - Aircraft: USA, Germany, USSR, Japan, Great Britain — types: Fighters/Bombers/Strike aircraft.
  - Naval: USA, Germany, USSR, Japan, Great Britain — ranks I–VI.
- Individual vehicle pages have stat blocks on RICH pages (e.g. T-28E: caliber, penetration, reload, turret rotation, max/reverse speed, specific power, mass, crew). Coverage is UNEVEN — some pages are stubs (e.g. ZTZ96 has only one line).
- Decision: roster (name/branch/nation/rank/type/flags/url) scraped fully; stats collected only where a stat block exists; Persian blurbs written by us (never copy wiki prose).

## Record schema (vehicles.json)
```json
{
  "id": "t34-1940-ussr",
  "name": "T-34 (1940)",
  "fa_name": "تی-۳۴ (۱۹۴۰)",
  "branch": "tank | aircraft | naval",
  "nation": "USSR",
  "rank": 1,
  "type": "medium",
  "flags": ["premium" | "platinum" | "event" | "blueprint" | "quest"],
  "stats": {
    "caliber_mm": 76.2,
    "penetration_mm": 67,
    "reload_s": 5,
    "turret_rotation_deg_s": 15,
    "max_speed_kmh": 35,
    "reverse_speed_kmh": 5,
    "specific_power_hp_t": 17,
    "mass_t": 29,
    "crew": 6
  },
  "wiki_url": "https://wtmobile.fandom.com/wiki/...",
  "fa_blurb": "…",
  "verified_at": "2026-10-16"
}
```
Aircraft/naval stat keys differ (speed, armament, crew…); store whatever stat block exists, same key names where possible.

## Bot UX (proposed, Persian, button-first — no typing)
1. Main menu button: 🚗 «دیتابیس وسیله‌ها»
2. Branch → nation → browse by rank OR by type → paginated list (10/page, Prev/Next)
3. Vehicle card: name + fa_name, badges (🌟 premium / 🎫 event / 📜 blueprint), stats table, fa_blurb, link to wiki page.
4. Search: text input, fuzzy match on name (Persian + English aliases); top 5 results as buttons.
5. Admin: /admin → «🔄 به‌روزرسانی دیتابیس» reloads vehicles.json without restart.

## Data pipeline
- `tools/scrape_roster.py`: fetches the 15 country pages (gentle: 2s delay, UA set, ETag cache), emits vehicles.json skeleton. Rerun monthly / after major updates.
- `tools/fill_stats.py`: visits rich vehicle pages, extracts stat blocks (regex on "Stats:" sections), fills `stats` where found; logs stubs for manual review.
- Manual review step before each release; user gets a diff summary (new/changed vehicles).

## Effort notes
- Full roster ≈ 600–900 vehicles across 3 branches; one-time scrape is cheap, stats are the long tail.
- Ship stats per-rank first (fewer ships), tanks biggest.
- Persian fa_name transliteration: keep well-known names (آبرامز، تی-۷۲-style) consistent with community usage.
