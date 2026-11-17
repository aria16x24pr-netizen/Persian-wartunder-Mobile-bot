"""English -> Persian translation via MyMemory (free, no key), with disk cache.

Each article is translated once and cached forever, so the daily quota
is only spent on genuinely new content.
"""
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "translations.json"
)
_cache: dict | None = None

# Circuit breaker: when the translation backend is down, fail fast instead of
# hanging every request on timeouts.
_degraded_until: float = 0.0
_fail_streak: int = 0
_DEGRADED_COOLDOWN = 300  # seconds


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save() -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False)


def _key(text: str) -> str:
    return hashlib.sha1(("en>" + text).encode("utf-8")).hexdigest()


def _mymemory(text: str) -> str | None:
    global _fail_streak, _degraded_until
    url = (
        "https://api.mymemory.translated.net/get?q="
        + urllib.parse.quote(text)
        + "&langpair=en|fa"
    )
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            break
        except Exception:
            log.warning("translation request failed (attempt %d)", attempt + 1)
            time.sleep(1)
    else:
        _note_failure()
        return None
    rd = data.get("responseData") or {}
    out = (rd.get("translatedText") or "").strip()
    status = str(data.get("responseStatus", ""))
    if not out or status != "200" or "MYMEMORY WARNING" in out.upper():
        _note_failure()
        return None
    # service sometimes echoes the source back -> treat as failure
    if out.strip().lower() == text.strip().lower():
        _note_failure()
        return None
    _fail_streak = 0
    return out


def _note_failure() -> None:
    global _fail_streak, _degraded_until
    _fail_streak += 1
    if _fail_streak >= 4:
        _degraded_until = time.time() + _DEGRADED_COOLDOWN
        _fail_streak = 0
        log.warning("translation backend degraded, cooling down %ds", _DEGRADED_COOLDOWN)


def _chunks(text: str, limit: int = 450) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    parts, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 > limit and cur:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        parts.append(cur)
    return parts or [text]


def translate_to_fa(text: str) -> tuple[str, bool]:
    """Translate English text to Persian.

    Returns (text, fully_translated). Failed chunks fall back to English so the
    caller never hangs or ends up empty-handed; when the backend is degraded
    we skip the network entirely and return English immediately.
    """
    text = " ".join(text.split())
    if not text:
        return "", True
    # skip if already Persian/Arabic script heavy
    if sum("\u0600" <= c <= "\u06FF" for c in text) > len(text) * 0.5:
        return text, True
    if time.time() < _degraded_until:
        return text, False
    cache = _load()
    out_parts = []
    full = True
    for chunk in _chunks(text):
        k = _key(chunk)
        if k in cache:
            out_parts.append(cache[k])
            continue
        fa = _mymemory(chunk)
        time.sleep(0.6)  # be gentle with the free quota
        if fa is None:
            full = False
            out_parts.append(chunk)  # English fallback for this chunk
            continue
        cache[k] = fa
        out_parts.append(fa)
    _save()
    return " ".join(out_parts), full
