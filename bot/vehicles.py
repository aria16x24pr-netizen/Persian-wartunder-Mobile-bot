"""Vehicle database browser for the WTM Telegram bot.

Button-first, Persian UX: branch → nation → rank/type → paginated list → card.
Search is text-initiated from the vehicle menu.
"""
from __future__ import annotations

import json
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BRANCHES = ("tank", "aircraft", "naval")

BRANCH_FA = {"tank": "🎖 تانک", "aircraft": "✈️ هوایی", "naval": "🚢 دریایی"}
BRANCH_EN = {"tank": "🎖 Tanks", "aircraft": "✈️ Aircraft", "naval": "🚢 Ships"}

NATIONS = {
    "tank": ["USA", "Germany", "USSR", "China", "Japan", "Sweden", "France", "Israel", "Great Britain"],
    "aircraft": ["USA", "Germany", "USSR", "Japan", "Great Britain"],
    "naval": ["USA", "Germany", "USSR", "Japan", "Great Britain", "France", "Netherlands", "Italy"],
}

NATION_FA = {
    "USA": "🇺🇸 آمریکا",
    "Germany": "🇩🇪 آلمان",
    "USSR": "🇷🇺 شوروی",
    "China": "🇨🇳 چین",
    "Japan": "🇯🇵 ژاپن",
    "Great Britain": "🇬🇧 بریتانیا",
    "Sweden": "🇸🇪 سوئد",
    "France": "🇫🇷 فرانسه",
    "Israel": "🇮🇱 اسرائیل",
    "Netherlands": "🇳🇱 هلند",
    "Italy": "🇮🇹 ایتالیا",
}

NATION_CODE = {"USA": "us", "Germany": "de", "USSR": "su", "China": "cn",
               "Japan": "jp", "Great Britain": "gb", "Sweden": "se",
               "France": "fr", "Israel": "il", "Netherlands": "nl",
               "Italy": "it"}
CODE_NATION = {v: k for k, v in NATION_CODE.items()}
BRANCH_CODE = {"tank": "t", "aircraft": "a", "naval": "s"}
CODE_BRANCH = {v: k for k, v in BRANCH_CODE.items()}

TYPE_FA = {
    "light": "سبک", "medium": "متوسط", "heavy": "سنگین",
    "spg": "توپ خودکششی", "spaa": "ضدهوایی",
    "fighter": "جنگنده", "bomber": "بمب‌افکن", "strike": "تهاجمی",
    "destroyer": "ناوشکن", "cruiser": "رزمناو", "battlecruiser": "رزم‌ناو",
    "battleship": "نبردناو", "submarine": "زیردریایی",
}

FLAG_BADGE = {
    "premium": "🌟 پریمیوم", "platinum": "💠 پلاتینیوم", "event": "🎫 ایونت",
    "blueprint": "📜 بلوپرینت", "quest": "🗺 کوئست",
}

STAT_FA = {
    "caliber_mm": ("کالیبر", "میلی‌متر"),
    "penetration_mm": ("نفوذ", "میلی‌متر"),
    "reload_s": ("بارگذاری مجدد", "ثانیه"),
    "turret_rotation_deg_s": ("چرخش برجک", "درجه/ثانیه"),
    "max_speed_kmh": ("حداکثر سرعت", "کم/ساعت"),
    "reverse_speed_kmh": ("سرعت دنده عقب", "کم/ساعت"),
    "specific_power_hp_t": ("توان ویژه", "اسب‌بخار/تن"),
    "horsepower_hp": ("قدرت موتور", "اسب‌بخار"),
    "mass_t": ("وزن", "تن"),
    "crew": ("خدمه", "نفر"),
    "armament_main": ("جنگ‌افزار اصلی", ""),
    "armament_secondary": ("جنگ‌افزار دوم", ""),
}

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV"]

PAGE_SIZE = 8

STR = {
    "fa": {
        "menu_title": "🚗 دیتابیس وسیله‌ها\nیه شاخه رو انتخاب کن:",
        "nation_title": "کشور رو انتخاب کن:",
        "mode_title": "می‌خوای بر اساس چی بگردی؟",
        "by_rank": "🔢 بر اساس رنک",
        "by_type": "🗂 بر اساس نوع",
        "rank_title": "رنک رو انتخاب کن:",
        "type_title": "نوع رو انتخاب کن:",
        "back": "🔙 بازگشت",
        "prev": "◀ قبلی",
        "next": "بعدی ▶",
        "search_btn": "🔍 جست‌وجوی اسم",
        "search_ask": "🔍 اسم وسیله رو بنویس (انگلیسی یا فارسی):\nمثال: T-34 یا تی-۳۴",
        "search_none": "چیزی پیدا نشد. یه اسم دیگه امتحان کن.",
        "search_results": "🔍 نتایج جست‌وجو:",
        "wiki_btn": "🔗 صفحه ویکی",
        "count": "تعداد: {n} وسیله",
    },
    "en": {
        "menu_title": "🚗 Vehicle database\nPick a branch:",
        "nation_title": "Pick a nation:",
        "mode_title": "Browse by:",
        "by_rank": "🔢 By rank",
        "by_type": "🗂 By type",
        "rank_title": "Pick a rank:",
        "type_title": "Pick a type:",
        "back": "🔙 Back",
        "prev": "◀ Prev",
        "next": "Next ▶",
        "search_btn": "🔍 Search by name",
        "search_ask": "🔍 Type the vehicle name (English or Persian):",
        "search_none": "Nothing found. Try another name.",
        "search_results": "🔍 Search results:",
        "wiki_btn": "🔗 Wiki page",
        "count": "{n} vehicles",
    },
}


def load_vehicles(path: str):
    with open(path, encoding="utf-8") as f:
        vehicles = json.load(f)
    by_id = {v["id"]: v for v in vehicles}
    return vehicles, by_id


def _branch_label(branch: str, lang: str) -> str:
    return (BRANCH_FA if lang == "fa" else BRANCH_EN)[branch]


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    s = STR[lang]
    rows = [
        [InlineKeyboardButton(_branch_label(b, lang), callback_data=f"v:b:{BRANCH_CODE[b]}")]
        for b in BRANCHES
    ]
    rows.append([InlineKeyboardButton(s["search_btn"], callback_data="v:s")])
    return InlineKeyboardMarkup(rows)


def nation_kb(branch: str, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(NATION_FA[n], callback_data=f"v:n:{BRANCH_CODE[branch]}:{NATION_CODE[n]}")]
        for n in NATIONS[branch]
    ]
    rows.append([InlineKeyboardButton(STR[lang]["back"], callback_data="v:menu")])
    return InlineKeyboardMarkup(rows)


def mode_kb(branch: str, nation: str, lang: str) -> InlineKeyboardMarkup:
    s = STR[lang]
    bc, nc = BRANCH_CODE[branch], NATION_CODE[nation]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(s["by_rank"], callback_data=f"v:mr:{bc}:{nc}")],
        [InlineKeyboardButton(s["by_type"], callback_data=f"v:mt:{bc}:{nc}")],
        [InlineKeyboardButton(s["back"], callback_data=f"v:b:{bc}")],
    ])


def rank_kb(vehicles, branch: str, nation: str, lang: str) -> InlineKeyboardMarkup:
    s = STR[lang]
    bc, nc = BRANCH_CODE[branch], NATION_CODE[nation]
    ranks = sorted({v["rank"] for v in vehicles
                    if v["branch"] == branch and v["nation"] == nation and v["rank"]})
    rows = []
    row = []
    for r in ranks:
        row.append(InlineKeyboardButton(f"رنک {ROMAN[r-1]}" if lang == "fa" else f"Rank {ROMAN[r-1]}",
                                        callback_data=f"v:lr:{bc}:{nc}:{r}:0"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(s["back"], callback_data=f"v:n:{bc}:{nc}")])
    return InlineKeyboardMarkup(rows)


def type_kb(vehicles, branch: str, nation: str, lang: str) -> InlineKeyboardMarkup:
    s = STR[lang]
    bc, nc = BRANCH_CODE[branch], NATION_CODE[nation]
    types = sorted({v["type"] for v in vehicles
                    if v["branch"] == branch and v["nation"] == nation and v["type"]})
    rows = [[InlineKeyboardButton(TYPE_FA.get(t, t), callback_data=f"v:lt:{bc}:{nc}:{t}:0")]
            for t in types]
    rows.append([InlineKeyboardButton(s["back"], callback_data=f"v:n:{bc}:{nc}")])
    return InlineKeyboardMarkup(rows)


def _filtered(vehicles, branch, nation, kind, value):
    out = [v for v in vehicles
           if v["branch"] == branch and v["nation"] == nation
           and (v["rank"] == value if kind == "rank" else v["type"] == value)]
    out.sort(key=lambda v: (v["rank"] or 0, v["name"]))
    return out


def list_kb(vehicles, branch: str, nation: str, kind: str, value, page: int,
            lang: str) -> tuple[InlineKeyboardMarkup, int, int]:
    """Returns (keyboard, page, total_pages)."""
    s = STR[lang]
    bc, nc = BRANCH_CODE[branch], NATION_CODE[nation]
    items = _filtered(vehicles, branch, nation, kind, value)
    total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    tag = f"v:l{kind[0]}:{bc}:{nc}:{value}"
    rows = [[InlineKeyboardButton(v["name"], callback_data=f"v:c:{v['id']}")]
            for v in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(s["prev"], callback_data=f"{tag}:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(s["next"], callback_data=f"{tag}:{page+1}"))
    if nav:
        rows.append(nav)
    back_to = f"v:mr:{bc}:{nc}" if kind == "rank" else f"v:mt:{bc}:{nc}"
    rows.append([InlineKeyboardButton(s["back"], callback_data=back_to)])
    return InlineKeyboardMarkup(rows), page, total_pages


def _norm(q: str) -> str:
    q = q.lower().strip()
    q = q.replace("‌", "")  # ZWNJ
    q = q.replace("ی", "").replace("ي", "")
    q = re.sub(r"[\s\-_./]+", "", q)
    return q


def search(vehicles, query: str, limit: int = 8):
    nq = _norm(query)
    if not nq:
        return []
    scored = []
    for v in vehicles:
        nn = _norm(v["name"])
        nf = _norm(v.get("fa_name") or "")
        if nn.startswith(nq) or nf.startswith(nq):
            scored.append((0, v))
        elif nq in nn or nq in nf:
            scored.append((1, v))
    scored.sort(key=lambda t: (t[0], len(t[1]["name"])))
    return [v for _, v in scored[:limit]]


def card_text(v: dict, lang: str) -> str:
    icon = {"tank": "🎖", "aircraft": "✈️", "naval": "🚢"}[v["branch"]]
    lines = [f"{icon} <b>{v['name']}</b>"]
    if v.get("fa_name"):
        lines.append(v["fa_name"])
    badges = [FLAG_BADGE[f] for f in v.get("flags", []) if f in FLAG_BADGE]
    if badges:
        lines.append(" ".join(badges))
    rank_s = ROMAN[v["rank"] - 1] if v.get("rank") else "?"
    lines.append(f"\n{NATION_FA.get(v['nation'], v['nation'])} · "
                 f"{_branch_label(v['branch'], lang)} · "
                 f"{'رنک' if lang == 'fa' else 'Rank'} {rank_s} · "
                 f"{TYPE_FA.get(v.get('type'), v.get('type') or '?')}")
    stats = v.get("stats")
    if stats:
        lines.append(f"\n📊 {'آمار' if lang == 'fa' else 'Stats'}:")
        for k, val in stats.items():
            if val is None or k == "shell_types":
                continue
            disp = int(val) if isinstance(val, float) and val.is_integer() else val
            if k in STAT_FA:
                label, unit = STAT_FA[k]
                lines.append(f"• {label}: {disp} {unit}".rstrip())
            else:
                lines.append(f"• {k}: {disp}")
        shells = stats.get("shell_types")
        if shells:
            if lang == "fa":
                shells = shells.replace(" and ", "، ").replace(",", "،")
            lines.append(f"• 🎯 {'گلوله‌ها' if lang == 'fa' else 'Shells'}: {shells}")
    if v.get("fa_blurb"):
        lines.append(f"\n📝 {v['fa_blurb']}")
    return "\n".join(lines)


def card_kb(v: dict, lang: str, back_cb: str) -> InlineKeyboardMarkup:
    s = STR[lang]
    # NOTE: no wiki button by design — the card itself carries photo + game info.
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(s["back"], callback_data=back_cb)]]
    )


# ---------- store + wiki enrichment (photo & game stats) ----------

import asyncio as _asyncio
import html as _html
import os as _os
import subprocess as _subprocess
import threading as _threading

VEHICLES_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(__file__)), "data", "vehicles.json"
)

_vehicles: list | None = None
_by_id: dict | None = None
_store_lock = _threading.Lock()


def get_vehicles() -> list:
    global _vehicles, _by_id
    if _vehicles is None:
        with open(VEHICLES_PATH, encoding="utf-8") as f:
            _vehicles = json.load(f)
        _by_id = {v["id"]: v for v in _vehicles}
    return _vehicles


def get_vehicle(vid: str) -> dict | None:
    get_vehicles()
    return (_by_id or {}).get(vid)


def reload_vehicles() -> int:
    """Reload vehicles.json from disk. Returns entry count."""
    global _vehicles, _by_id
    with _store_lock:
        with open(VEHICLES_PATH, encoding="utf-8") as f:
            _vehicles = json.load(f)
        _by_id = {v["id"]: v for v in _vehicles}
    return len(_vehicles)


def save_vehicles() -> None:
    with _store_lock:
        if _vehicles is None:
            return
        tmp = VEHICLES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_vehicles, f, ensure_ascii=False)
        _os.replace(tmp, VEHICLES_PATH)


def _wiki_download(url: str) -> str | None:
    try:
        out = _subprocess.run(
            ["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", url],
            capture_output=True,
            timeout=30,
        )
        if out.returncode == 0 and len(out.stdout) > 5000:
            return out.stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass
    return None


def _api_download(url: str) -> str | None:
    """Like _wiki_download but without the 5KB minimum (for JSON APIs)."""
    try:
        out = _subprocess.run(
            ["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", url],
            capture_output=True,
            timeout=30,
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass
    return None


def _extract_photo(html: str) -> str | None:
    for m in re.finditer(
        r"https://static\.wikia\.nocookie\.net/wtmobile/images/[^\"'\s]+", html
    ):
        u = m.group(0)
        low = u.lower()
        if "site-background" in low or "site-logo" in low:
            continue
        return u.split("/revision/latest")[0] + "/revision/latest"
    return None


_STAT_LABEL_MAP = [
    ("caliber", "caliber_mm", True),
    ("penetration", "penetration_mm", True),
    ("reload", "reload_s", True),
    ("turret rotation", "turret_rotation_deg_s", True),
    ("forward speed", "max_speed_kmh", True),
    ("reverse speed", "reverse_speed_kmh", True),
    ("power/weight", "specific_power_hp_t", True),
    ("horsepower", "horsepower_hp", True),
    ("mass", "mass_t", True),
    ("crew", "crew", True),
    ("main armament", "armament_main", False),
    ("secondary armament", "armament_secondary", False),
    ("shell types", "shell_types", False),
]


def _parse_num(v: str) -> float | None:
    """Parse a number that may use ',' as decimal separator ('61,02 t')."""
    m = re.search(r"[\d.,]+", v.strip())
    if not m:
        return None
    s = m.group(0)
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = parts[0] + "." + parts[1]  # decimal comma
        else:
            s = s.replace(",", "")  # thousand separator
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_stats(html: str) -> dict:
    stats: dict = {}
    for label, val in re.findall(
        r'data-source="[^"]+"[^>]*>.*?<h3[^>]*>(.*?)</h3>'
        r'.*?<div class="pi-data-value[^"]*">(.*?)</div>',
        html,
        re.DOTALL,
    ):
        lab = _html.unescape(re.sub(r"<[^>]+>", "", label)).strip().lower()
        v = _html.unescape(re.sub(r"<[^>]+>", " ", val)).strip()
        v = " ".join(v.split())
        if not v:
            continue
        for kw, key, numeric in _STAT_LABEL_MAP:
            if kw in lab:
                if numeric:
                    num = _parse_num(v)
                    if num is None:
                        break
                    # strongest wins: max for most stats, min for reload (faster = better)
                    if key not in stats:
                        stats[key] = num
                    elif key == "reload_s":
                        stats[key] = min(stats[key], num)
                    else:
                        stats[key] = max(stats[key], num)
                else:
                    if key not in stats:
                        stats[key] = v[:120]
                break
    return stats


_COMMONS_SKIP = ("crest", "insignia", "badge", "logo", "patch", "seal",
                   "flag", "emblem", "coat of arms", "map ", "diagram")

# words that strongly indicate a wrong vehicle branch in a Commons title
_COMMONS_WRONG_BRANCH = {
    "tank": ("aircraft", "airplane", "air plane", "fighter", "bomber",
             "helicopter", "air force", "ship", "submarine", "destroyer",
             "cruiser", "battleship", "carrier"),
    "aircraft": ("tank", "ship", "submarine", "destroyer", "cruiser",
                 "battleship", "carrier"),
    "naval": ("tank", "aircraft", "airplane", "fighter", "bomber",
              "helicopter", "air force"),
}


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def _base_name(name: str) -> str:
    """Strip variant suffixes: 'IS-2 'Revenge'' -> 'IS-2', 'M4A4 (event)' -> 'M4A4'."""
    s = re.sub(r"\s*\(.*?\)\s*", " ", name)
    s = re.sub(r"\s*'[^']*'\s*", " ", s)
    s = re.sub(r"\s*\"[^\"]*\"\s*", " ", s)
    return " ".join(s.split()).strip()


def _commons_queries(name: str, branch: str) -> list[str]:
    """Search query variants for the Commons fallback (most specific first)."""
    clean = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    if not clean:
        return []
    # NOTE: do NOT append branch qualifier ("tank"/"aircraft"/"ship") —
    # it excludes valid files whose titles lack the qualifier.
    # Wrong-branch protection comes from _COMMONS_WRONG_BRANCH title filtering.
    cands = [clean]
    if "/" in clean:
        cands.append(clean.split("/")[0].strip())
    no_class = re.sub(r"-class$", "", clean, flags=re.I).strip()
    if no_class != clean:
        cands.append(no_class)
    toks = clean.split()
    if len(toks) > 2:
        cands.append(" ".join(toks[:2]))
    seen: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.append(c)
    return seen


async def _commons_photo(name: str, branch: str = "") -> str | None:
    """Real-world photo fallback via Wikimedia Commons (no wiki image).

    STRICT: only accepts files whose title actually contains the vehicle
    name. A wrong photo is worse than no photo.
    """
    try:
        import urllib.parse as _up

        base = _base_name(name)
        if not base:
            return None
        base_n = _norm(base)
        # skip absurdly short base names that would match everything
        if len(base_n) < 3:
            return None
        wrong_words = _COMMONS_WRONG_BRANCH.get(branch, ())
        for query in _commons_queries(name, branch):
            q = _up.quote(query)
            url = (
                "https://commons.wikimedia.org/w/api.php?action=query&format=json"
                f"&generator=search&gsrsearch={q}%20filetype:bitmap&gsrnamespace=6"
                "&gsrlimit=8&prop=pageimages&pithumbsize=800"
            )
            raw = await _asyncio.to_thread(_api_download, url)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            pages = (data.get("query") or {}).get("pages") or {}
            cands = []
            for p in pages.values():
                title = (p.get("title") or "").lower()
                if any(k in title for k in _COMMONS_SKIP):
                    continue
                if base_n not in _norm(title):
                    continue  # title doesn't mention this vehicle -> reject
                if any(w in title for w in wrong_words):
                    continue  # obviously wrong branch -> reject
                thumb = (p.get("thumbnail") or {}).get("source")
                if thumb:
                    cands.append(thumb.split("?")[0])
            if cands:
                return cands[0]
    except Exception:
        pass
    return None


def _variant_base_photo(v: dict) -> str | None:
    """Reuse the in-game photo of the base model for variant vehicles.

    e.g. "IS-2 'Revenge'" -> photo of "IS-2". Prefers same branch.
    """
    base = _base_name(v.get("name", ""))
    if not base or base == v.get("name"):
        return None
    base_n = _norm(base)
    best = None
    for cand in get_vehicles():
        if cand["id"] == v["id"]:
            continue
        if _norm(_base_name(cand.get("name", ""))) != base_n:
            continue
        if not cand.get("photo_url") or cand.get("photo_source") == "commons":
            continue  # only reuse real in-game photos, not fallbacks
        if cand.get("branch") == v.get("branch"):
            return cand["photo_url"]
        best = best or cand["photo_url"]
    return best


async def enrich_vehicle(v: dict) -> dict:
    """Fill photo_url + stats (once per vehicle).

    Photo fallback chain: in-game wiki image -> other wiki images ->
    real-world photo from Wikimedia Commons.
    """
    if v.get("enriched"):
        return v
    wiki_url = v.get("wiki_url")
    if wiki_url:
        html = await _asyncio.to_thread(_wiki_download, wiki_url)
        if html:
            photo = _extract_photo(html)
            if photo:
                v["photo_url"] = photo
            stats = _extract_stats(html)
            if stats:
                merged = dict(v.get("stats") or {})
                merged.update(stats)
                v["stats"] = merged
    if not v.get("photo_url"):
        # variant (e.g. "IS-2 'Revenge'") -> reuse the base model's in-game photo
        base_photo = _variant_base_photo(v)
        if base_photo:
            v["photo_url"] = base_photo
            v["photo_source"] = "variant"
    if not v.get("photo_url"):
        photo = await _commons_photo(v.get("name", ""), v.get("branch", ""))
        if photo:
            v["photo_url"] = photo
            v["photo_source"] = "commons"
    v["enriched"] = True
    await _asyncio.to_thread(save_vehicles)
    return v


def db_stats() -> dict:
    vs = get_vehicles()
    return {
        "total": len(vs),
        "tanks": sum(1 for v in vs if v.get("branch") == "tank"),
        "aircraft": sum(1 for v in vs if v.get("branch") == "aircraft"),
        "naval": sum(1 for v in vs if v.get("branch") == "naval"),
        "photos": sum(1 for v in vs if v.get("photo_url")),
        "stats": sum(1 for v in vs if v.get("stats")),
        "enriched": sum(1 for v in vs if v.get("enriched")),
    }
