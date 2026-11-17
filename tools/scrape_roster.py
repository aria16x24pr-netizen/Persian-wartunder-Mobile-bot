#!/usr/bin/env python3
"""Extract the full War Thunder Mobile vehicle roster from wtmobile.fandom.com.

Method (verified 2026-10-16): fetch the 15 country pages via the MediaWiki API
(action=parse, prop=wikitext), parse rank/type headings + bullet lists, resolve
link targets, and check page existence against list=allpages. Emits
data/vehicles.json — one record per vehicle.

Rerun monthly or after major game updates; diff against the previous file to
spot additions/removals.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://wtmobile.fandom.com/api.php"
UA = {"User-Agent": "WTM-Bot-Roster/1.0 (research use; gentle scraping)"}
WIKI = "https://wtmobile.fandom.com/wiki/"

PAGES = [
    ("tank", "USA", "USA"),
    ("tank", "Germany", "Germany"),
    ("tank", "USSR", "USSR"),
    ("tank", "China", "China"),
    ("tank", "Japan", "Japan"),
    ("aircraft", "USA", "USA (Aircraft Tree)"),
    ("aircraft", "Germany", "Germany (Aircraft Tree)"),
    ("aircraft", "USSR", "USSR (Aircraft Tree)"),
    ("aircraft", "Japan", "Japan (Aircraft Tree)"),
    ("aircraft", "Great Britain", "Great Britain (Aircraft Tree)"),
    ("naval", "USA", "USA (Naval Tree)"),
    ("naval", "Germany", "Germany (Naval Tree)"),
    ("naval", "USSR", "USSR (Naval Tree)"),
    ("naval", "Japan", "Japan (Naval Tree)"),
    ("naval", "Great Britain", "Great Britain (Naval Tree)"),
]

FLAG_WORDS = {"premium", "platinum", "event", "blueprint", "quest"}
# parentheticals that are NOT flags — kept inside the display name
NON_FLAG_HINTS = {"promo", "obtainable until tech tree update", "ttd (?)"}

TYPE_MAP = [
    ("battlecruiser", "battlecruiser"),
    ("light", "light"),
    ("medium", "medium"),
    ("heavy", "heavy"),
    ("spaa", "spaa"),
    ("anti-air", "spaa"),
    ("spg", "spg"),
    ("tank destroyer", "spg"),
    ("assault gun", "spg"),
    ("fighter", "fighter"),
    ("bomber", "bomber"),
    ("strike", "strike"),
    ("attack", "strike"),
    ("destroyer", "destroyer"),
    ("cruiser", "cruiser"),
    ("battleship", "battleship"),
    ("submarine", "submarine"),
]

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
         "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14}

TR = {
    "A": "ا", "B": "ب", "C": "ک", "D": "د", "E": "ا", "F": "ف", "G": "گ",
    "H": "ه", "I": "ی", "J": "ج", "K": "ک", "L": "ل", "M": "م", "N": "ن",
    "O": "و", "P": "پ", "Q": "ک", "R": "ر", "S": "س", "T": "ت", "U": "و",
    "V": "و", "W": "و", "X": "کس", "Y": "ی", "Z": "ز",
    "a": "ا", "b": "ب", "c": "ک", "d": "د", "e": "ه", "f": "ف", "g": "گ",
    "h": "ه", "i": "ی", "j": "ج", "k": "ک", "l": "ل", "m": "م", "n": "ن",
    "o": "و", "p": "پ", "q": "ک", "r": "ر", "s": "س", "t": "ت", "u": "و",
    "v": "و", "w": "و", "x": "کس", "y": "ی", "z": "ز",
    "0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴", "5": "۵", "6": "۶",
    "7": "۷", "8": "۸", "9": "۹",
    "-": "-", "/": "/", " ": " ", ".": ".", "(": "(", ")": ")",
    "'": "’", "’": "’", "&": "و", "+": "+", ":": ":", ",": "،",
}


def transliterate(name: str) -> str:
    # leading single letter like "T-34" is pronounced "تی-۳۴" in Persian
    name = re.sub(r"^([A-Za-z])(?=[-\s])", lambda m: m.group(1) + "ی", name)
    out = []
    for ch in name:
        out.append(TR.get(ch, ch))
    s = "".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fa_display_name(name: str) -> str:
    """Transliterate the base name; keep parenthetical tags in Latin."""
    m = re.match(r"^([^(]+?)(\s*\(.*\))?$", name)
    if not m:
        return transliterate(name)
    head = transliterate(m.group(1).strip())
    tail = m.group(2) or ""
    return (head + tail).strip()


def api(params: dict):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{API}?{qs}", headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def get_wikitext(title: str) -> str:
    d = api({"action": "parse", "page": title, "prop": "wikitext", "format": "json"})
    return d["parse"]["wikitext"]["*"]


def all_existing_titles() -> set:
    titles = set()
    cont = None
    while True:
        p = {"action": "query", "list": "allpages", "apnamespace": 0,
             "aplimit": 500, "format": "json"}
        if cont:
            p["apcontinue"] = cont
        d = api(p)
        for pg in d["query"]["allpages"]:
            titles.add(pg["title"])
        if "continue" in d:
            cont = d["continue"]["apcontinue"]
            time.sleep(1)
        else:
            break
    return titles


def clean_heading(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^=+\s*|\s*=+$", "", s)          # heading marks
    s = re.sub(r"</?u>", "", s)
    s = re.sub(r"</?big>", "", s)
    s = s.replace("'''", "").replace("''", "")
    return s.strip()


def parse_page(branch: str, nation: str, wikitext: str, existing: set) -> list:
    rows = []
    rank = None
    vtype = None
    for raw in wikitext.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.search(r"[Rr]ank\s+([IVX]+)\b", clean_heading(line))
        if m and not line.startswith("*"):
            rank = ROMAN.get(m.group(1).upper())
            continue
        if not line.startswith("*"):
            low = clean_heading(line).lower()
            if low and "rank" not in low:
                for needle, norm in TYPE_MAP:
                    if needle in low:
                        vtype = norm
                        break
            continue
        # bullet → vehicle entry
        body = line.lstrip("*").strip()
        if not body:
            continue  # stray empty bullet
        link_m = re.match(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]\s*(.*)$", body)
        if link_m:
            target = link_m.group(1).strip()
            display = (link_m.group(2) or target).strip()
            rest = link_m.group(3).strip()
        else:
            pm = re.match(r"^([^(]+?)\s*((?:\([^)]*\)\s*)*)$", body)
            if pm:
                display, rest = pm.group(1).strip(), pm.group(2).strip()
            else:
                display, rest = body, ""
            target = display
        flags = []
        kept_parens = []
        for par in re.findall(r"\(([^)]*)\)", rest):
            w = par.strip().lower()
            if w in FLAG_WORDS:
                flags.append(w)
            else:
                kept_parens.append(par.strip())
        name = display
        if kept_parens:
            name = f"{display} ({') ('.join(kept_parens)})"
        target_norm = target.replace("_", " ")
        wiki_url = None
        if target_norm in existing:
            wiki_url = WIKI + urllib.parse.quote(target.replace(" ", "_"))
        rows.append({
            "branch": branch,
            "nation": nation,
            "rank": rank,
            "type": vtype,
            "name": name,
            "target": target_norm,
            "flags": sorted(set(flags)),
            "wiki_url": wiki_url,
        })
    return rows


def slugify(name: str, branch: str, nation: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return f"{s[:40].strip('-')}-{branch}-{nation.lower().replace(' ', '')}"


def main() -> None:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/vehicles.json"
    print("fetching existing titles…", flush=True)
    existing = all_existing_titles()
    print(f"  {len(existing)} pages", flush=True)
    all_rows = []
    for i, (branch, nation, title) in enumerate(PAGES):
        print(f"[{i+1}/15] {title}…", flush=True)
        wt = get_wikitext(title)
        rows = parse_page(branch, nation, wt, existing)
        print(f"  → {len(rows)} entries", flush=True)
        all_rows.extend(rows)
        time.sleep(2)
    # dedupe exact (branch, nation, name) — keep first
    seen = set()
    uniq = []
    for r in all_rows:
        key = (r["branch"], r["nation"], r["name"])
        if key in seen:
            print(f"  dedupe: {r['name']} ({r['branch']}/{r['nation']})", flush=True)
            continue
        seen.add(key)
        uniq.append(r)
    # finalize records
    used_ids = set()
    records = []
    for r in uniq:
        vid = slugify(r["name"], r["branch"], r["nation"])
        n = 2
        while vid in used_ids:
            vid = f"{slugify(r['name'], r['branch'], r['nation'])}-{n}"
            n += 1
        used_ids.add(vid)
        records.append({
            "id": vid,
            "name": r["name"],
            "fa_name": fa_display_name(r["name"]),
            "fa_name_auto": True,
            "branch": r["branch"],
            "nation": r["nation"],
            "rank": r["rank"],
            "type": r["type"],
            "flags": r["flags"],
            "stats": None,
            "wiki_url": r["wiki_url"],
            "fa_blurb": None,
            "verified_at": time.strftime("%Y-%m-%d"),
        })
    # merge verified sample records (stats + hand-written blurbs)
    try:
        with open("docs/vehicle-db/vehicles.sample.json", encoding="utf-8") as f:
            samples = json.load(f)
        by_name = {(s["branch"], s["nation"], s["name"]): s for s in samples}
        for rec in records:
            s = by_name.get((rec["branch"], rec["nation"], rec["name"]))
            if s:
                rec["stats"] = s.get("stats")
                rec["fa_blurb"] = s.get("fa_blurb")
                rec["fa_name"] = s.get("fa_name", rec["fa_name"])
                rec["fa_name_auto"] = False
        print(f"merged {len(samples)} verified sample records", flush=True)
    except FileNotFoundError:
        pass
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
    # summary
    from collections import Counter
    c = Counter((r["branch"], r["nation"]) for r in records)
    print("---- summary ----")
    for (b, n), k in sorted(c.items()):
        print(f"  {b:8s} {n:14s} {k}")
    print(f"TOTAL: {len(records)}")
    missing_rank = sum(1 for r in records if not r["rank"])
    missing_type = sum(1 for r in records if not r["type"])
    print(f"missing rank: {missing_rank}, missing type: {missing_type}")


if __name__ == "__main__":
    main()
