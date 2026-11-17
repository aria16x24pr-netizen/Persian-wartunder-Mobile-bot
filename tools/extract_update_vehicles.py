#!/usr/bin/env python3
"""Extract new vehicles from official WTM major-update articles.

Parses the 'New vehicles' sections (Tanks/Ships/Aviation) from wtmobile.com
news articles, extracting vehicle names, ranks, types, and platoon nations.
Outputs a JSON list for diffing against the DB roster.
"""
import json
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (WTM-Bot-Roster/1.0)"}

# nation hints from vehicle/platoon names
NATION_HINTS = [
    ("swed", "Sweden"), ("strv", "Sweden"), ("pvrbv", "Sweden"), ("veak", "Sweden"),
    ("ikv", "Sweden"), ("udesh", "Sweden"), ("savoie", "France"), ("amx", "France"),
    ("leclerc", "France"), ("ariete", "Italy"), ("centauro", "Italy"), ("of-40", "Italy"),
    ("challenger", "Great Britain"), ("chieftain", "Great Britain"), ("centurion", "Great Britain"),
    ("conqueror", "Great Britain"), ("tiger", "Germany"), ("panther", "Germany"),
    ("leopard", "Germany"), ("maus", "Germany"), ("panzer", "Germany"), ("wiesel", "Germany"),
    ("ostwind", "Germany"), ("kugel", "Germany"), ("hetzer", "Germany"), ("jagd", "Germany"),
    ("stug", "Germany"), ("marder", "Germany"), ("sherman", "USA"), ("m4", "USA"),
    ("m10", "USA"), ("m18", "USA"), ("m24", "USA"), ("m26", "USA"), ("m46", "USA"),
    ("m47", "USA"), ("m48", "USA"), ("m60", "USA"), ("m103", "USA"), ("m551", "USA"),
    ("t29", "USA"), ("t30", "USA"), ("t34", "USA"), ("t54e", "USA"), ("t58", "USA"),
    ("t92", "USA"), ("t114", "USA"), ("abrams", "USA"), ("m1a", "USA"), ("m1128", "USA"),
    ("m163", "USA"), ("m247", "USA"), ("m3", "USA"), ("m5", "USA"), ("m7", "USA"),
    ("m8", "USA"), ("m12", "USA"), ("m19", "USA"), ("m41", "USA"), ("m42", "USA"),
    ("t-34", "USSR"), ("t-54", "USSR"), ("t-55", "USSR"), ("t-62", "USSR"), ("t-64", "USSR"),
    ("t-72", "USSR"), ("t-80", "USSR"), ("t-90", "USSR"), ("is-1", "USSR"), ("is-2", "USSR"),
    ("is-3", "USSR"), ("is-4", "USSR"), ("is-6", "USSR"), ("is-7", "USSR"), ("kv-1", "USSR"),
    ("kv-2", "USSR"), ("kv-85", "USSR"), ("su-", "USSR"), ("isu-", "USSR"), ("object", "USSR"),
    ("bmp", "USSR"), ("bmd", "USSR"), ("btr-", "USSR"), ("zsu", "USSR"), ("shilka", "USSR"),
    ("pt-76", "USSR"), ("2s", "USSR"), ("t-10", "USSR"), ("t-44", "USSR"),
    ("ztz", "China"), ("wz-", "China"), ("type 59", "China"), ("type 62", "China"),
    ("type 63", "China"), ("type 69", "China"), ("type 79", "China"), ("type 96", "China"),
    ("type 99", "China"), ("pgz", "China"), ("plz", "China"), ("ptl", "China"),
    ("ztl", "China"), ("zbd", "China"), ("zsl", "China"),
    ("chi-", "Japan"), ("st-a", "Japan"), ("stb", "Japan"), ("type 74", "Japan"),
    ("type 87", "Japan"), ("type 89", "Japan"), ("type 90", "Japan"), ("type 10", "Japan"),
    ("type 16", "Japan"), ("ho-", "Japan"), ("ka-mi", "Japan"), ("ke-ni", "Japan"),
    # ships
    ("hms", "Great Britain"), ("hmt", "Great Britain"),
    ("uss", "USA"),
    ("ijn", "Japan"), ("jds", "Japan"),
    ("kronshtadt", "USSR"), ("chapayev", "USSR"), ("sverdlov", "USSR"),
    ("vampire", "Great Britain"), ("vanguard", "Great Britain"),
    ("des moines", "USA"), ("bismarck", "Germany"), ("prinz", "Germany"),
    ("kongo", "Japan"), ("yamato", "Japan"), ("mikuma", "Japan"),
    # new nations / patterns
    ("magach", "Israel"), ("sho't kal", "Israel"), ("hovet", "Israel"),
    ("la fayette", "France"), ("surcouf", "France"),
    ("hnlms", "Netherlands"),
    ("niedersachsen", "Germany"), ("baden-württemberg", "Germany"),
    ("sachsen", "Germany"), ("brandenburg", "Germany"), ("emden", "Germany"),
    ("köln", "Germany"), ("derfflinger", "Germany"), ("type 212", "Germany"),
    ("u-305", "Germany"), ("type vii", "Germany"),
    ("british", "Great Britain"), ("type 45", "Great Britain"),
    ("invincible", "Great Britain"),
    ("soviet", "USSR"), ("pr. 971", "USSR"), ("pr. 11540", "USSR"),
    ("pr. 1144", "USSR"), ("pr. 11661", "USSR"), ("pr. 61m", "USSR"),
    ("pr. 11352", "USSR"), ("pr.885", "USSR"), ("pr.956", "USSR"),
    ("pr. 1155", "USSR"), ("groznyy", "USSR"), ("maxim gorky", "USSR"),
    ("german", "Germany"),
    ("ram ii", "Great Britain"), ("mig-15", "USSR"), ("meteor", "Great Britain"),
]


def guess_nation(name: str) -> str | None:
    n = name.lower()
    for hint, nation in NATION_HINTS:
        if hint in n:
            return nation
    return None


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")


def _clean_html(html: str) -> str:
    """Strip Vue comments and normalize for parsing."""
    html = re.sub(r"<!--\[?-->", "", html)
    html = re.sub(r"<!--\]?-->", "", html)
    return html


def parse_vehicles(html: str) -> list[dict]:
    """Extract vehicles from the 'New vehicles' section."""
    out = []
    html = _clean_html(html)
    i = html.find("New vehicles")
    if i < 0:
        return out
    seg = html[i:i + 40000]
    # split into subsections by h2
    parts = re.split(r"<h[23][^>]*>", seg)
    for part in parts[1:]:
        head_text = " ".join(re.sub(r"<[^>]+>", " ", part[:500]).split())
        m = re.match(r"\s*(Tanks|Ships|Aviation|Aircraft|Ground Vehicles|Naval)", head_text)
        if not m:
            continue
        section = m.group(1).lower()
        if "tank" in section or "ground" in section:
            branch = "tank"
        elif "ship" in section or "naval" in section:
            branch = "naval"
        else:
            branch = "aircraft"
        body = part[:15000]
        # platoon blocks: heading with "NAME Platoon (Rank X)" followed by <ul><li>...
        # handles nested spans: extract text content of <p>...</p> blocks
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.DOTALL):
            ptxt = " ".join(re.sub(r"<[^>]+>", " ", pm.group(1)).split()).strip()
            rm = re.match(
                r"(.{3,80}?)\s*(?:Platoon)?\s*\(\s*Rank\s+([IVX\d]+)\s*\)\s*(\(can be received.*?\))?\s*$",
                ptxt,
            )
            if not rm:
                rm = re.match(
                    r"Platoon\s+(.{3,60}?)\s*\(\s*Rank\s+([IVX\d]+)\s*\)\s*$",
                    ptxt,
                )
            if not rm:
                continue
            platoon = rm.group(1).strip()
            rank_roman = rm.group(2).strip().upper()
            # find the following <ul>
            tail = body[pm.end():pm.end() + 3000]
            um = re.search(r"<ul[^>]*>(.*?)</ul>", tail, re.DOTALL)
            vehicles = []
            if um:
                for li in re.findall(r"<li[^>]*>(.*?)</li>", um.group(1), re.DOTALL):
                    nm = _latin(" ".join(re.sub(r"<[^>]+>", " ", li).split()).strip())
                    nm = re.sub(r"\s*\(Rank.*$", "", nm).strip()
                    if nm and len(nm) < 60:
                        vehicles.append(nm)
            if not vehicles:
                # single vehicle in the platoon line itself
                nm = re.sub(r"\s*Premium\s*", "", platoon).strip()
                if nm and "platoon" not in nm.lower():
                    vehicles = [nm]
            is_premium = "premium" in platoon.lower() or "premium" in body[pm.start()-200:pm.start()].lower()
            try:
                rank = _roman(rank_roman)
            except Exception:
                rank = None
            for v in vehicles:
                out.append({
                    "name": v,
                    "branch": branch,
                    "rank": rank,
                    "premium": is_premium,
                    "nation_guess": guess_nation(v) or guess_nation(platoon),
                    "platoon": platoon,
                })
        # Format B: bullet paragraphs "• M47 Patton II (MT Rank VI)"
        # or "• M4A4 (SA50) (Premium MT Rank III)"
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.DOTALL):
            ptxt = " ".join(re.sub(r"<[^>]+>", " ", pm.group(1)).split()).strip()
            if not ptxt.startswith("•"):
                continue
            bm = re.match(
                r"•\s*(.+?)\s*\(\s*(?:(Premium)\s+)?([A-Za-z/]+)?\s*Rank\s+([IVX\d]+)\s*\)",
                ptxt,
            )
            if not bm:
                continue
            nm = _unescape(_latin(bm.group(1).strip()))
            is_premium = bool(bm.group(2))
            vtype = (bm.group(3) or "").upper()
            try:
                rank = _roman(bm.group(4).upper())
            except Exception:
                rank = None
            if nm and len(nm) < 60 and not any(o["name"] == nm and o["branch"] == branch for o in out):
                out.append({
                    "name": nm, "branch": branch, "rank": rank,
                    "premium": is_premium, "vtype": vtype,
                    "nation_guess": guess_nation(nm), "platoon": "",
                })
        # Format C: "• Calliope (Rank II premium MT)" (premium after rank)
        # or naval "• Poltava (level 14 premium battleship)"
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.DOTALL):
            ptxt = " ".join(re.sub(r"<[^>]+>", " ", pm.group(1)).split()).strip()
            if not ptxt.startswith("•"):
                continue
            cm = re.match(
                r"•\s*(.+?)\s*\(\s*Rank\s+([IVX\d]+)\s+(premium\s+)?([A-Za-z/]+)\s*\)",
                ptxt,
            )
            rank, is_premium, vtype = None, False, ""
            nm = None
            if cm:
                nm = _latin(cm.group(1).strip())
                is_premium = bool(cm.group(3))
                vtype = cm.group(4).upper()
                try:
                    rank = _roman(cm.group(2).upper())
                except Exception:
                    rank = None
            else:
                lm = re.match(
                    r"•\s*(.+?)\s*\(\s*level\s+(\d+)\s+(premium\s+)?([A-Za-z]+)\s*\)",
                    ptxt,
                )
                if lm:
                    nm = _unescape(_latin(lm.group(1).strip()))
                    is_premium = bool(lm.group(3))
                    vtype = lm.group(4).upper()
            if nm and len(nm) < 60 and not any(o["name"] == nm and o["branch"] == branch for o in out):
                out.append({
                    "name": nm, "branch": branch, "rank": rank,
                    "premium": is_premium, "vtype": vtype,
                    "nation_guess": guess_nation(nm), "platoon": "",
                })
        # standalone ship lines: <li>Type Name (Rank X)</li>
        if branch == "naval":
            for li in re.findall(r"<li[^>]*>(.*?)</li>", body, re.DOTALL):
                txt = " ".join(re.sub(r"<[^>]+>", " ", li).split()).strip()
                m2 = re.match(r"(.*?)\s*\(\s*Rank\s+([IVX\d]+)\s*\)", txt)
                if m2:
                    nm = m2.group(1).strip()
                    nm = re.sub(r"^(Premium|Submarine|Battleship|Cruiser|Destroyer|Battlecruiser|Submarine)\s+",
                                "", nm, flags=re.I).strip()
                    nm = re.sub(r"^(Premium|Submarine|Battleship|Cruiser|Destroyer|Battlecruiser|Submarine)\s+",
                                "", nm, flags=re.I).strip()
                    try:
                        rank = _roman(m2.group(2).upper())
                    except Exception:
                        rank = None
                    if nm and not any(o["name"] == nm for o in out):
                        out.append({
                            "name": nm, "branch": "naval", "rank": rank,
                            "premium": "premium" in txt.lower(),
                            "nation_guess": guess_nation(nm), "platoon": "",
                        })
    return out


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


def _latin(s: str) -> str:
    """Replace Cyrillic lookalikes with Latin (Т-54 -> T-54)."""
    return (
        s.replace("Т", "T").replace("т", "t")
        .replace("А", "A").replace("а", "a")
        .replace("В", "B").replace("Е", "E").replace("е", "e")
        .replace("К", "K").replace("М", "M").replace("м", "m")
        .replace("Н", "H").replace("О", "O").replace("о", "o")
        .replace("Р", "P").replace("р", "p").replace("С", "C").replace("с", "c")
        .replace("Х", "X").replace("х", "x").replace("І", "I").replace("і", "i")
    )


def _roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10}
    total, prev = 0, 0
    for ch in reversed(s):
        cur = vals[ch]
        total += -cur if cur < prev else cur
        prev = cur
    return total


if __name__ == "__main__":
    urls = sys.argv[1:]
    all_v = []
    for u in urls:
        try:
            html = fetch(u)
            vs = parse_vehicles(html)
            print(f"{u[-40:]}: {len(vs)} vehicles", file=sys.stderr)
            all_v.extend(vs)
        except Exception as e:
            print(f"FAIL {u}: {e}", file=sys.stderr)
    # dedupe
    seen, dedup = set(), []
    for v in all_v:
        k = (v["name"].lower(), v["branch"])
        if k not in seen:
            seen.add(k)
            dedup.append(v)
    json.dump(dedup, open("/tmp/update_vehicles.json", "w"), ensure_ascii=False, indent=1)
    print(f"total unique: {len(dedup)}")
