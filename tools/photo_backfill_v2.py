#!/usr/bin/env python3
"""v2 photo backfill for vehicles still missing photo_url.

Improvements over v1 (photo_backfill_full.py):
  1. base_min()/base_forms(): improved base-name normalization — strips
     /trop /U2 /Jabo style suffixes, -class, #NNN, G.41F, US block numbers
     (-25, -60-VE), Japanese variant words (otsu/hei/tei/ko/kai), TD suffix,
     quoted nicknames (incl. Unicode quotes).
  2. Variant-base reuse uses base_forms() so e.g. "Bf 109 F-4/trop" reuses the
     in-game photo of "Bf 109 F-4".
  3. Commons cascade: base forms + progressive shortening of trailing variant
     tokens (Mk IIb, mod. 22, Model 11, Type 5, -III, ...) + curated alias map
     for game-name vs real-world-name mismatches (M18 GMC -> M18 Hellcat).
  4. Naval names: strips nationality descriptors, prefixes (SMS/HMS/USS/
     HNLMS/JDS/IJN/ITS/ARA), trailing ship-type words; acceptance requires a
     ship-word in the file title.
  5. Animal-word guard for tanks (Panther/Tiger/Wiesel/Ratel/...): title must
     also contain a tank-ish word, so we never attach an animal photo.
  6. Unicode-folding norm so "Yūshio" matches "Yushio".

Safety: same strict philosophy — a candidate file is accepted only if its
title contains the (alias) vehicle name. Results go to
/tmp/photo_backfill_v2.json {id: {photo_url, photo_source, title, query}}.
Nothing is written to vehicles.json here; merge separately with
tools/merge_backfill_v2.py.

Run: /home/hatch/workspace/war-thunder-mobile-bot/.venv/bin/python tools/photo_backfill_v2.py
"""
import asyncio
import json
import re
import sys
import unicodedata
import urllib.parse as _up

sys.path.insert(0, "/home/hatch/workspace/war-thunder-mobile-bot")
from bot import vehicles as veh

OUT = "/tmp/photo_backfill_v2.json"

_QUOTES = "'\u2018\u2019\"\u201c\u201d\u00ab\u00bb"


def unorm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[\s_\-./'\"\u2018\u2019\u201c\u201d\u00ab\u00bb]+", "", s.lower())


def base_min(name: str, keep_quoted: bool = False) -> str:
    """Conservative base name: parens/quotes/-class/#NNN/G.41F/TD stripped."""
    s = name or ""
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)          # (Canada), (premium), (M-105R)
    qpat = "[" + _QUOTES + "]"
    if keep_quoted:
        s = re.sub(qpat, "", s)  # quoted name is the essence: drop marks only
    else:
        qsec = re.sub(r"\s*" + qpat + r"[^" + _QUOTES + r"]*" + qpat + r"\s*",
                      " ", s)
        # quoted nicknames; if the whole name was quoted keep the content
        s = qsec if qsec.strip() else re.sub(qpat, "", s)
    s = re.sub(r"(?i)-class\s*$", "", s)          # Type VII-class
    s = re.sub(r"\s*#\d+\s*$", "", s)             # Leopard I #457
    s = re.sub(r"\s+G\.\d+\w*\s*$", "", s)        # Meteor G.41F
    s = re.sub(r"(?i)\s+td\s*$", "", s)           # Challenger 3 TD
    return " ".join(s.split()).strip()


def strip_slash(s: str) -> str:
    return re.sub(r"\s*/\S+\s*$", "", s).strip()  # /trop /U2 /Jabo /70


def strip_block(s: str) -> str:
    return re.sub(r"-\d{2,}(-[A-Z]{2})?\s*$", "", s).strip()  # -25, -60-VE


def strip_jp(s: str) -> str:
    return re.sub(r"(?i)\s+(otsu|hei|tei|ko|kai)\s*$", "", s).strip()


def base_forms(name: str) -> list:
    """Ordered base-name forms: full first, then progressively stripped."""
    b = base_min(name)
    forms = [b]
    for fn in (strip_slash, strip_block, strip_jp):
        s = fn(b)
        if s and s != b and s not in forms and len(s) >= 3:
            forms.append(s)
    return forms


_VARIANT_TAIL = re.compile(
    r"(?i)\s+(mk\.?\s*\S+|mod\.?\s*\S+|model\s*\S+|type\s*\S+|mv-5|lu)\s*$")


def shortenings(b: str) -> list:
    """Progressively strip trailing variant tokens: 'I-16 type 18' -> 'I-16'."""
    out, cur = [], b
    for _ in range(3):
        m = _VARIANT_TAIL.search(cur)
        if m:
            cur = cur[:m.start()].strip()
        else:
            m2 = re.search(r"-[IVX]+\s*$", cur)
            if not m2:
                break
            cur = cur[:m2.start()].strip()
        if len(cur) < 4 or " " not in cur:
            break
        if cur not in out:
            out.append(cur)
    return out


# game-name (unorm'd base form) -> real-world name candidates
_ALIASES = {
    # tanks: game name vs real name
    "m18gmc": ["M18 Hellcat"],
    "m4a5": ["Ram tank"],
    "m4a3e2": ["Sherman Jumbo"],
    "m4a3e2w": ["Sherman Jumbo"],
    "ipm1": ["M1 Abrams"],
    "m109a1": ["M109 howitzer"],
    "m48a2ga2": ["M48 Patton"],
    "mkpzm47g": ["M47 Patton"],
    "m60a2": ["M60A2 Starship"],
    "t32e1": ["T32 heavy tank"],
    "leclercs2": ["Char Leclerc"],
    "amx30b2brenus": ["AMX-30"],
    "amx13dca40": ["AMX-13 DCA"],
    "amx50survasse": ["AMX-50 Surbaisse", "AMX-50"],
    "amx50foch": ["AMX-50 Foch", "AMX-50"],
    "arietepso": ["C1 Ariete"],
    "arietewar": ["C1 Ariete"],
    "of40mk2a": ["OF-40"],
    "centauroi120": ["B1 Centauro"],
    "centauroi105r": ["B1 Centauro"],
    "centaurorgo": ["B1 Centauro"],
    "vcc8060": ["Dardo IFV"],
    "r3t106fa": ["R3 T106"],
    "begleitpanzer57": ["Begleitpanzer"],
    "bfwjagdpantherg1": ["Jagdpanther"],
    "ru251": ["Spaehpanzer Ru 251", "Ru 251"],
    "ersatzm10": ["Panther tank"],
    "turmiii": ["Panther tank"],
    "pantherg": ["Panther tank"],
    "panther": ["Panther tank"],
    "tigere": ["Tiger I"],
    "kwic756": ["KV-1"],
    "pzbegwgvip": ["Tiger (P)"],
    "pzivj": ["PzKpfw IV Ausf J", "PzKfw IV"],
    "merkavamk3b": ["Merkava Mk III", "Merkava 3"],
    "merkavamk3c": ["Merkava Mk III", "Merkava 3"],
    "vk4501": ["Tiger (P)"],
    "leopard2a4m": ["Leopard 2"],
    "leopard2k": ["Leopard 2"],
    "leoparda1a1": ["Leopard 1"],
    "leopardi": ["Leopard 1"],
    "tam2ip": ["TAM tank"],
    "wiesel1a2": ["Wiesel AWC"],
    "wiesel1a4": ["Wiesel AWC"],
    "bkan1c": ["Bandkanon 1"],
    "strf9040bill": ["Strf 9040", "CV90"],
    "strf9040c": ["Strf 9040", "CV90"],
    "strf9040b": ["Strf 9040", "CV90"],
    "strv105": ["Centurion tank"],
    "strv122a": ["Stridsvagn 122"],
    "strv103c": ["Stridsvagn 103"],
    "cv90120t": ["CV90120"],
    "magach6r": ["Magach"],
    "shotkalgimel": ["Sho't Kal"],
    "namertsrikhon": ["Namer APC"],
    "olifantmk2": ["Olifant tank"],
    "ratelzt3a2": ["Ratel IFV"],
    "challenger3": ["Challenger 3"],
    "challengermk2": ["Challenger 2"],
    "chihalg": ["Type 97 Chi-Ha"],
    "chitolate": ["Type 4 Chi-To"],
    "type60sprg": ["Type 60 SPRG"],
    "type75sph": ["Type 75 SPH"],
    "ztz99ii": ["ZTZ-99", "Type 99 tank"],
    "ztz99iii": ["ZTZ-99", "Type 99 tank"],
    "ztz96a": ["ZTZ-96", "Type 96 tank"],
    "ztz59d1": ["Type 59 tank"],
    "zbd04a": ["ZBD-04"],
    "plz83": ["PLZ-83"],
    "plz83130": ["PLZ-83"],
    "ptl02": ["PTL-02"],
    "wz305": ["WZ305"],
    "pgz04a": ["PGZ-04"],
    "aft09": ["AFT-09"],
    "t3485gai": ["T-34-85"],
    "t34100": ["T-34-100", "T-34"],
    "t34estz": ["T-34"],
    "t34stz": ["T-34"],
    "t55amd1": ["T-55"],
    "t72b3a": ["T-72"],
    "t80um2": ["T-80"],
    "su85m": ["SU-85"],
    "btr152d": ["BTR-152"],
    "zsu234": ["ZSU-23-4 Shilka"],
    "zsu234v": ["ZSU-23-4 Shilka"],
    "m5359": ["Praga M53/59", "M53/59"],
    "centurionmk5avre": ["Centurion AVRE"],
    "vickersmk7": ["Vickers Mk 7"],
    "sidam25": ["SIDAM 25"],
    # aircraft: game name vs real name
    "a7he1": ["Heinkel He 112"],
    "ki200": ["Mitsubishi J8M"],
    "hagirisa5m4": ["Mitsubishi A5M"],
    "golovachevsyak9i": ["Yak-9"],
    "yer2lu": ["Yer-2"],
    "yer2": ["Yer-2"],
    "mb5": ["Martin-Baker MB 5"],
    "firecrest": ["Blackburn Firecrest"],
    "chesapeakemki": ["Vultee Vengeance"],
    "brigandb1": ["Bristol Brigand"],
    "attackerfb1": ["Supermarine Attacker"],
    "nimrodmkii": ["Hawker Nimrod"],
    "lincolnb mkii": ["Avro Lincoln"],
    "shackletonmrmk2": ["Avro Shackleton"],
    "vampirefb5": ["de Havilland Vampire"],
    "thunderboltmki": ["P-47 Thunderbolt"],
    "typhoonmkib": ["Hawker Typhoon"],
    "wellingtonmkic": ["Vickers Wellington"],
    "wellingtonmkx": ["Vickers Wellington"],
    "halifaxbmkiii a": ["Handley Page Halifax"],
    "hudsonmkv": ["Lockheed Hudson"],
    "lancasterbmkiii": ["Avro Lancaster"],
    "mosquitobmkxvi": ["de Havilland Mosquito"],
    "beaufightermkvic": ["Bristol Beaufighter"],
    "beaufightermk21": ["Bristol Beaufighter"],
    "beaufightermkx": ["Bristol Beaufighter"],
    "martletmkiv": ["Grumman Martlet"],
    "seafirefmkxvii": ["Supermarine Seafire"],
    "seafirelfmkiii": ["Supermarine Seafire"],
    "fireflyfrm kv": ["Fairey Firefly"],
    "seahurricanemkic": ["Hawker Sea Hurricane"],
    "hurricanemkiib": ["Hawker Hurricane"],
    "seameteorfmk3": ["Gloster Meteor"],
    "meteorfmk4": ["Gloster Meteor"],
    "meteorfmk3": ["Gloster Meteor"],
    "meteorfmk8": ["Gloster Meteor"],
    "spitfirefmkix": ["Supermarine Spitfire"],
    "spitfiremkiib": ["Supermarine Spitfire"],
    "spitfirefmkxvi": ["Supermarine Spitfire"],
    "spitfirefmkxvic": ["Supermarine Spitfire"],
    "spitfirefmk24": ["Supermarine Spitfire"],
    "spitfiremk22": ["Supermarine Spitfire"],
    "spitfiremkvb": ["Supermarine Spitfire"],
    "bf109f4": ["Messerschmitt Bf 109"],
    "fw190a5": ["Focke-Wulf Fw 190"],
    "fw190b12": ["Focke-Wulf Fw 190"],
    "fw90a5": ["Focke-Wulf Fw 190"],
    "me262a1a": ["Messerschmitt Me 262"],
    "me262a2": ["Messerschmitt Me 262"],
    "me262c2b": ["Messerschmitt Me 262"],
    "me410a1": ["Messerschmitt Me 410"],
    "bf110c6": ["Messerschmitt Bf 110"],
    "do217m1": ["Dornier Do 217"],
    "do335a1": ["Dornier Do 335"],
    "ju188a2": ["Junkers Ju 188"],
    "ju288c": ["Junkers Ju 288"],
    "ju87a2": ["Junkers Ju 87"],
    "ju87d3": ["Junkers Ju 87"],
    "he51b1": ["Heinkel He 51"],
    "he51c1": ["Heinkel He 51"],
    "hs129b2": ["Henschel Hs 129"],
    "ta152c3": ["Focke-Wulf Ta 152"],
    "ta152h1": ["Focke-Wulf Ta 152"],
    "fw200c1": ["Focke-Wulf Fw 200"],
    "a20g": ["Douglas A-20 Havoc"],
    "a26b": ["Douglas A-26 Invader"],
    "b17g": ["Boeing B-17"],
    "b24d": ["Consolidated B-24"],
    "f84b": ["Republic F-84"],
    "f4u1e": ["Vought F4U Corsair"],
    "p40e": ["Curtiss P-40"],
    "p40e1": ["Curtiss P-40"],
    "p40f": ["Curtiss P-40"],
    "p47m": ["Republic P-47"],
    "i15m22": ["Polikarpov I-15"],
    "i153m62": ["Polikarpov I-153"],
    "i16type5": ["Polikarpov I-16"],
    "i16type10": ["Polikarpov I-16"],
    "i16type18": ["Polikarpov I-16"],
    "la7b": ["Lavochkin La-7"],
    "lagg3": ["LaGG-3"],
    "tu2s": ["Tupolev Tu-2"],
    "yak9ut": ["Yakovlev Yak-9"],
    "db3b": ["Ilyushin DB-3"],
    "su2mv5": ["Sukhoi Su-2"],
    "su2": ["Sukhoi Su-2"],
    # naval core-name fixes (typos / transliteration / NATO names)
    "sovetskijsoyuz": ["Sovetsky Soyuz"],
    "tenessee": ["Tennessee"],
    "penescola": ["Pensacola"],
    "takatsuk": ["Takatsuki"],
    "korenaer": ["Kortenaer"],
    "pr613": ["Whiskey class"],
    "pr641": ["Foxtrot class"],
}
_ALIASES = {unorm(k): v for k, v in _ALIASES.items()}

_EXTRA_SKIP = ("cobi", "lego", "carcinoma", "tumor", "tumour", "cancer",
                "histology", "medical", "disease", "syndrome")

_ANIMAL_WORDS = ("panther", "tiger", "leopard", "jaguar", "puma", "wiesel",
                 "ratel", "olifant", "namer", "fuchs", "luchs", "marder",
                 "wespe", "hummel", "nashorn", "elefant", "maus", "dingo",
                 "grille", "bison", "buffel", "coelian")
_TANK_WORDS = ("tank", "panzer", "char", "carro", "strv", "stridsvagn", "mbt",
               "ifv", "apc", "artillery", "howitzer", "armoured", "armored",
               "self-propelled", "tank destroyer", "spaa", "spaag", "army",
               "military", "bundeswehr", "blindado", "blindo", "kampfwagen")
_SHIP_WORDS = ("ship", "frigate", "destroyer", "submarine", "cruiser",
               "battleship", "battlecruiser", "carrier", "boat", "schiff",
               "boot", "u-boot", "uboat", "kreuzer", "fregatte", "zerstoerer",
               "zerstörer", "cacciatorpediniere", "fregata", "incrociatore",
               "sommergibile", "acorazado", "destructor", "croiseur",
               "cuirasse", "sous-marin", "kreyser", "esminec",
               "linienschiff", "schlachtschiff",
               "hms", "uss", "ijn", "sms", "hnlms", "jds", "ara")


def naval_core(name: str, keep_quoted: bool = False) -> str:
    s = base_min(name, keep_quoted=keep_quoted)
    s = re.sub(r"(?i)^\s*(german|french|italian|japanese|british|american|"
               r"russian|soviet|dutch|argentine)\s+(missile\s+|nuclear(-powered)?\s+)?"
               r"(submarine|frigate|destroyer|cruiser|battleship|carrier|ship|boat|"
               r"dreadnought)(?:\s+|$)", "", s)
    s = re.sub(r"(?i)^\s*(battleship|dreadnought|line cruiser|light cruiser|"
               r"heavy cruiser|armored cruiser|cruiser)(?:\s+|$)", "", s)
    s = re.sub(r"(?i)^\s*(sms|hms|uss|hnlms|jds|ijn|its|ara|orp)\s+", "", s)
    s = re.sub(r"(?i)^\s*ss-\d+\s+", "", s)
    s = re.sub(r"(?i)^\s*z\s?\d+\s+", "", s)
    s = re.sub(r"(?i)^\s*u-\d+\s+", "", s)
    s = re.sub(r"(?i)^type\s+(?=pr\.)", "", s)
    s = re.sub(r"(?i)\s+((heavy|light|armored|armoured|guided)\s+)?"
               r"(nuclear(-powered)?\s+)?(missile\s+)?(patrol\s+)?(\S+-class\s+)?"
               r"(frigate|destroyer|cruiser|submarine|battleship|battlecruiser|"
               r"carrier|ship|boat|dreadnought)(\s+class)?\s*$", "", s)
    return " ".join(s.split()).strip()


def commons_candidates(name: str, branch: str) -> list:
    """Ordered (query, must_contain, animal_guard) triples for Commons."""
    out = []
    seen = set()

    def add(query, must, animal=False):
        key = (unorm(query), unorm(must))
        if not query or not must or len(unorm(must)) < 3 or key in seen:
            return
        seen.add(key)
        q = query + (" tank" if animal and branch == "tank" else "")
        out.append((q, must, animal))

    if branch == "naval":
        core = naval_core(name)
        cores = [core]
        if len(unorm(core)) < 3:
            # quoted name was the essence (e.g. light cruiser "Maxim Gorky")
            cores.append(naval_core(name, keep_quoted=True))
        extra = re.sub(r"(?i)^u-\d+\s+", "", core).strip()
        if extra and extra != core:
            cores.append(extra)
        for c in cores:
            add(c, c)
            for al in _ALIASES.get(unorm(c), []):
                add(al, al)
        return out

    for b in base_forms(name):
        for c in [b] + shortenings(b):
            au = unorm(c)
            animal = any(au == a or au.startswith(a) for a in _ANIMAL_WORDS)
            add(c, c, animal)
            for al in _ALIASES.get(unorm(c), []):
                alu = unorm(al)
                add(al, al, any(alu == a or alu.startswith(a)
                               for a in _ANIMAL_WORDS))
    return out


async def commons_search(query: str):
    q = _up.quote(query)
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           f"&generator=search&gsrsearch={q}%20filetype:bitmap&gsrnamespace=6"
           "&gsrlimit=8&prop=pageimages&pithumbsize=800")
    raw = await asyncio.to_thread(veh._api_download, url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return list(((data.get("query") or {}).get("pages") or {}).values())


async def commons_photo_v2(name: str, branch: str):
    wrong_words = veh._COMMONS_WRONG_BRANCH.get(branch, ())
    for query, must, animal in commons_candidates(name, branch):
        if len(unorm(must)) < 3:
            continue
        try:
            pages = await commons_search(query)
        except Exception:
            continue
        for p in pages:
            title = (p.get("title") or "")
            tl = title.lower()
            if any(k in tl for k in veh._COMMONS_SKIP):
                continue
            if any(k in tl for k in _EXTRA_SKIP):
                continue
            tnu = unorm(title)
            mnu = unorm(must)
            # must occur without being a numeric prefix of a longer
            # designation (Su-2 vs Su-20, T-34 vs T-3485)
            ok = False
            start = 0
            while True:
                idx = tnu.find(mnu, start)
                if idx < 0:
                    break
                nxt = tnu[idx + len(mnu):idx + len(mnu) + 1]
                if not nxt.isdigit():
                    ok = True
                    break
                start = idx + 1
            if not ok:
                continue
            if any(w in tl for w in wrong_words):
                continue
            if branch == "naval":
                has_ship = any(re.search(r"\b" + re.escape(w) + r"\b", tl)
                               for w in _SHIP_WORDS)
                if not has_ship:
                    continue
                # a "missile" hit without any vessel word is a weapon, not a ship
                if "missile" in tl and not any(
                        re.search(r"\b" + re.escape(w) + r"\b", tl) for w in
                        ("frigate", "destroyer", "cruiser", "submarine",
                         "battleship", "battlecruiser", "carrier", "hms",
                         "uss", "ijn", "sms", "hnlms", "jds", "ara")):
                    continue
            if animal and branch == "tank":
                if not any(w in tl for w in _TANK_WORDS):
                    continue
            thumb = (p.get("thumbnail") or {}).get("source")
            if thumb:
                return thumb.split("?")[0], title, query
        await asyncio.sleep(0.4)
    return None


def variant_base_photo_v2(v: dict, vehicles: list):
    """Reuse in-game photo of the base model (improved base-name matching)."""
    forms = [f for f in base_forms(v.get("name", "")) if f != v.get("name")]
    if not forms:
        return None
    for base in forms:
        base_n = unorm(base)
        best = None
        for cand in vehicles:
            if cand["id"] == v["id"]:
                continue
            if unorm(base_min(cand.get("name", ""))) != base_n:
                continue
            if not cand.get("photo_url") or cand.get("photo_source") == "commons":
                continue  # only reuse real in-game photos, not fallbacks
            if cand.get("branch") == v.get("branch"):
                return cand["photo_url"]
            best = best or cand["photo_url"]
    return best


async def main():
    vehicles = veh.get_vehicles()
    targets = [v for v in vehicles if not v.get("photo_url")]
    print(f"v2 backfill targets: {len(targets)}", flush=True)
    results = {}
    stats = {"wiki": 0, "variant": 0, "commons": 0}
    for i, v in enumerate(targets):
        photo = None
        src = None
        title = ""
        query = ""
        try:
            if v.get("wiki_url"):
                html = await asyncio.to_thread(veh._wiki_download, v["wiki_url"])
                if html:
                    p = veh._extract_photo(html)
                    if p:
                        photo, src = p, "wiki"
            if not photo:
                bp = variant_base_photo_v2(v, vehicles)
                if bp:
                    photo, src = bp, "variant"
            if not photo:
                r = await commons_photo_v2(v.get("name", ""), v.get("branch", ""))
                if r:
                    photo, title, query = r
                    src = "commons"
            if photo:
                results[v["id"]] = {"photo_url": photo, "photo_source": src,
                                    "title": title, "query": query,
                                    "name": v["name"]}
                stats[src] += 1
        except Exception as e:
            print(f"  ERR {v['name']}: {e}", flush=True)
        if (i + 1) % 25 == 0:
            print(f"  progress {i+1}/{len(targets)} hits={len(results)} "
                  f"{stats}", flush=True)
    json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"DONE: {len(results)}/{len(targets)} {stats} -> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
