"""Per-user profiles: WTM username/display name, onboarding state, news prefs."""
import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")

NEWS_TAGS = ("tanks", "aircraft", "ships")


@dataclass
class Profile:
    wtm_username: str | None = None
    display_name: str | None = None
    onboarded: bool = False
    news: dict = field(default_factory=lambda: {t: True for t in NEWS_TAGS})


_profiles: dict | None = None


def _load_all() -> dict:
    global _profiles
    if _profiles is None:
        try:
            with open(PROFILES_FILE, encoding="utf-8") as f:
                _profiles = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _profiles = {}
    return _profiles


def _save_all() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(_load_all(), f, ensure_ascii=False, indent=1)


def get_profile(user_id: int) -> Profile:
    d = _load_all().get(str(user_id), {})
    news = {t: True for t in NEWS_TAGS}
    news.update({k: bool(v) for k, v in (d.get("news") or {}).items() if k in NEWS_TAGS})
    return Profile(
        wtm_username=d.get("wtm_username"),
        display_name=d.get("display_name"),
        onboarded=bool(d.get("onboarded", False)),
        news=news,
    )


def save_profile(user_id: int, profile: Profile) -> None:
    _load_all()[str(user_id)] = {
        "wtm_username": profile.wtm_username,
        "display_name": profile.display_name,
        "onboarded": profile.onboarded,
        "news": profile.news,
    }
    _save_all()


def profile_exists(user_id: int) -> bool:
    return str(user_id) in _load_all()
