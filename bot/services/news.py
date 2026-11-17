"""News provider: official War Thunder Mobile news page (wtmobile.com).

Polite single-page polling; articles link back to the official site.
Uses stdlib urllib (via a thread) since it handles the runtime proxy reliably.
"""
import asyncio
import html as htmlmod
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

BASE = "https://wtmobile.com"
NEWS_URL = BASE + "/en/news"

# Server-rendered news cards have the `news-card` class
# (this skips the "See more" button which links to the same article).
CARD_RE = re.compile(
    r'<a href="(/en/news/\d+)"[^>]*news-card[^>]*>.*?<h2[^>]*><!--\[-->([^<]*)<!--\]--></h2>'
    r".*?<p[^>]*><!--\[-->([^<]*)<!--\]--></p>\s*<time[^>]*>([^<]*)</time>",
    re.DOTALL,
)

# user keyword -> site tag filter (verified against wtmobile.com)
TAG_MAP = {
    "tank": "tanks",
    "tanks": "tanks",
    "تانک": "tanks",
    "air": "aircraft",
    "aircraft": "aircraft",
    "airplane": "aircraft",
    "هواپیما": "aircraft",
    "ship": "ships",
    "ships": "ships",
    "کشتی": "ships",
    "ناو": "ships",
}


@dataclass
class Article:
    id: str
    title: str
    tag: str
    date: str
    url: str


def _download(url: str, start: int | None = None, end: int | None = None) -> str:
    """Download a URL, optionally via HTTP Range.

    wtmobile.com pages are ~440KB and the egress proxy intermittently truncates
    large responses for urllib, so we fetch only the byte window holding the
    content, using curl which proved far more reliable here than urllib.
    Falls back to a full download when no range is given.
    """
    cmd = ["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", url]
    if start is not None and end is not None:
        cmd += ["-r", f"{start}-{end}"]
    last: str = "unknown"
    for attempt in range(3):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=30)
            if out.returncode == 0 and len(out.stdout) > 10000:
                return out.stdout.decode("utf-8", errors="ignore")
            last = f"rc={out.returncode} size={len(out.stdout)}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        log.warning("download failed (attempt %d/3): %s [%s]", attempt + 1, url, last)
    raise RuntimeError(f"download failed: {url} [{last}]")


# Byte windows (verified 2026-10-15): the news grid sits ~300-360KB into the
# list page; article bodies start ~324KB into article pages.
LIST_RANGE = (280000, 400000)
ARTICLE_RANGE = (315000, 425000)


async def _fetch_ranged(url: str, window: tuple[int, int]) -> str:
    try:
        return await asyncio.to_thread(_download, url, window[0], window[1])
    except Exception:
        log.warning("ranged fetch failed, trying full download: %s", url)
        return await asyncio.to_thread(_download, url)


async def _fetch_full(url: str) -> str:
    """Download wider windows for archive articles (full downloads truncate).

    Article images can appear anywhere; fetch two windows and concatenate.
    """
    early = await asyncio.to_thread(_download, url, 200000, 330000)
    late = await asyncio.to_thread(_download, url, 315000, 450000)
    return early + late


def _download_bytes(url: str, max_size: int = 15_000_000) -> bytes | None:
    """Download raw bytes (for photos/videos). Returns None on failure."""
    try:
        out = subprocess.run(
            [
                "curl", "-sL", "--max-time", "40", "--max-filesize", str(max_size),
                "-A", "Mozilla/5.0", url,
            ],
            capture_output=True,
            timeout=45,
        )
        if out.returncode == 0 and len(out.stdout) > 1000:
            return out.stdout
    except Exception:
        pass
    log.warning("media download failed: %s", url[:80])
    return None


def _clean(raw: str) -> str:
    text = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmlmod.unescape(text)
    return " ".join(text.split())


@dataclass
class FullArticle:
    id: str
    title: str
    tag: str
    date: str
    url: str
    description: str
    hero_image: str | None
    blocks: list = field(default_factory=list)  # ("h3"|"p", text) | ("img", url) | ("video", mp4url) | ("yt", watchurl)


async def fetch_article(url: str, full_page: bool = False) -> FullArticle | None:
    """Download one article page and extract title, body blocks and images."""
    try:
        if full_page:
            html = await _fetch_full(url)
        else:
            html = await _fetch_ranged(url, ARTICLE_RANGE)
    except Exception:
        log.exception("article fetch failed: %s", url)
        return None

    main_m = re.search(r"<main.*?</main>", html, re.DOTALL)
    # Ranged fetches may start mid-document; the window is already scoped to
    # the content area, so fall back to the whole chunk when <main> is absent.
    main = main_m.group(0) if main_m else html

    title_m = re.search(r"<h2[^>]*><!--\[-->([^<]*)<!--\]--></h2>", main)
    title = _clean(title_m.group(1)) if title_m else ""
    date_m = re.search(r"<time[^>]*>([^<]*)</time>", main)
    date = _clean(date_m.group(1)) if date_m else ""
    tag_m = re.search(r'<a href="/en/news\?tag=[^"]*"[^>]*><!--\[-->([^<]*)<!--\]--></a>', main)
    tag = _clean(tag_m.group(1)) if tag_m else ""

    # hero image: first big banner picture
    hero = None
    hm = re.search(r'<img[^>]+src="(https://patchnotes\.cdn\.gaijin\.net/[^"]+?)"', main)
    if hm and not hm.group(1).lower().endswith(".svg"):
        hero = hm.group(1)
    if not hero:
        # fallback: OpenGraph image (main article image, in <head>)
        og = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if not og:
            og = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html)
        if og:
            url = og.group(1)
            if (url.startswith("https://")
                and not url.lower().endswith(".svg")
                and "logo" not in url.lower()):
                hero = url

    # body starts at the content <div id ...>; walk blocks in document order
    body_html = main
    div_id = main.find("<div id")
    if div_id != -1:
        body_html = main[div_id:]

    blocks: list = []
    seen_imgs: set = set()
    seen_vids: set = set()
    for m in re.finditer(
        r"<h3[^>]*>(.*?)</h3>|<p[^>]*>(.*?)</p>|<img[^>]+src=\"([^\"]+)\""
        r"|<video[^>]*(?:src=\"([^\"]+)\")?[^>]*>(.*?)</video>"
        r"|<iframe[^>]+src=\"([^\"]+)\"",
        body_html,
        re.DOTALL,
    ):
        h3, p, img, vid_src, vid_inner, iframe_src = m.groups()
        if h3 is not None:
            t = _clean(h3)
            if t:
                blocks.append(("h3", t))
        elif p is not None:
            t = _clean(p)
            if t and len(t) > 2:
                blocks.append(("p", t))
        elif img is not None:
            if (
                "patchnotes.cdn.gaijin.net" in img
                and not img.lower().endswith(".svg")
                and "logo" not in img.lower()
                and "qrcode" not in img.lower()
                and img not in seen_imgs
            ):
                seen_imgs.add(img)
                blocks.append(("img", img))
        elif vid_src is not None or vid_inner is not None:
            vsrc = vid_src
            if not vsrc and vid_inner:
                sm = re.search(r'<source[^>]+src="([^"]+)"', vid_inner)
                vsrc = sm.group(1) if sm else None
            if vsrc and vsrc not in seen_vids:
                seen_vids.add(vsrc)
                blocks.append(("video", vsrc))
        elif iframe_src is not None:
            ym = re.search(r"youtube\.com/embed/([\w-]{6,})", iframe_src)
            if ym:
                yid = ym.group(1)
                yurl = f"https://www.youtube.com/watch?v={yid}"
                if yurl not in seen_vids:
                    seen_vids.add(yurl)
                    blocks.append(("yt", yurl))

    art_id = url.rstrip("/").rsplit("/", 1)[-1]
    # description: first body paragraph (often the lede)
    description = next((t for k, t in blocks if k == "p"), "")
    return FullArticle(
        id=art_id,
        title=title,
        tag=tag,
        date=date,
        url=url,
        description=description,
        hero_image=hero,
        blocks=blocks,
    )


async def fetch_news(tag: str | None = None, limit: int = 5) -> list[Article]:
    """Return latest articles, newest first."""
    url = NEWS_URL + (f"?tag={tag}" if tag else "")
    try:
        html = await _fetch_ranged(url, LIST_RANGE)
    except Exception:
        log.exception("news fetch failed")
        return []

    articles: list[Article] = []
    for m in CARD_RE.finditer(html):
        path, title, tag_, date = m.groups()
        art_id = path.rsplit("/", 1)[-1]
        articles.append(
            Article(
                id=art_id,
                title=" ".join(title.split()),
                tag=" ".join(tag_.split()),
                date=date.strip(),
                url=BASE + path,
            )
        )
        if len(articles) >= limit:
            break
    return articles


# ---------- official Telegram channel as a second news source ----------
# The channel (t.me/WarThunderMobile) carries campaigns/offers that never appear
# as website articles (e.g. the ZTZ96A Tank Campaign). Its preview page is small
# (~160KB) and downloads reliably. Posts are newest-last in the HTML.

CHANNEL_URL = "https://t.me/s/WarThunderMobile"

_POST_SPLIT_RE = re.compile(r'<div class="tgme_widget_message_wrap[^"]*"')
_POST_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
_POST_DATE_RE = re.compile(r'datetime="([^"]+)"')
_POST_LINK_RE = re.compile(r'href="(https://t\.me/WarThunderMobile/(\d+))"')
_POST_PHOTO_RE = re.compile(r"background-image:url\('([^']+)'\)")
_POST_SITE_RE = re.compile(r'href="(https://wtmobile\.com/(?:en/)?news/(\d+))"')
_POST_VIDEO_RE = re.compile(r'tgme_widget_message_video_player')
_POST_DURATION_RE = re.compile(r'message_video_duration[^>]*>([^<]+)<')

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_site_date(s: str):
    """'15 October 2026' -> naive datetime (noon, for ordering)."""
    from datetime import datetime

    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s.strip())
    if not m:
        return datetime(2000, 1, 1)
    day, mon, year = m.groups()
    return datetime(int(year), _MONTHS.get(mon.lower(), 1), int(day), 12, 0)


@dataclass
class ChannelPost:
    id: str
    text: str
    date: str
    dt: object  # datetime, naive UTC
    url: str
    photo: str | None
    site_id: str | None  # linked wtmobile.com article id, if any
    has_video: bool = False
    video_duration: str | None = None


async def fetch_channel_posts(limit: int = 20) -> list[ChannelPost]:
    """Latest posts from the official Telegram channel, newest first."""
    from datetime import datetime, timezone

    try:
        html = await asyncio.to_thread(_download, CHANNEL_URL)
    except Exception:
        log.exception("channel fetch failed")
        return []
    posts: list[ChannelPost] = []
    for chunk in reversed(_POST_SPLIT_RE.split(html)[1:]):
        link = _POST_LINK_RE.search(chunk)
        if not link:
            continue
        post_url, post_id = link.group(1), link.group(2)
        t = _POST_TEXT_RE.search(chunk)
        text = ""
        if t:
            text = htmlmod.unescape(re.sub(r"<br\s*/?>", "\n", t.group(1)))
            text = " ".join(re.sub(r"<[^>]+>", "", text).split())
        if not text:
            continue
        d = _POST_DATE_RE.search(chunk)
        try:
            dt = (
                datetime.fromisoformat(d.group(1)).astimezone(timezone.utc).replace(tzinfo=None)
                if d
                else datetime(2000, 1, 1)
            )
        except Exception:
            dt = datetime(2000, 1, 1)
        photo = None
        for p in _POST_PHOTO_RE.findall(chunk):
            if "telesco.pe" in p or "cdn-telegram.org" in p:
                photo = p if p.startswith("http") else "https:" + p
                break
        site = _POST_SITE_RE.search(chunk)
        has_video = bool(_POST_VIDEO_RE.search(chunk))
        dur = _POST_DURATION_RE.search(chunk)
        posts.append(
            ChannelPost(
                id=post_id,
                text=text,
                date=dt.strftime("%d %B %Y"),
                dt=dt,
                url=post_url,
                photo=photo,
                site_id=site.group(2) if site else None,
                has_video=has_video,
                video_duration=dur.group(1).strip() if dur else None,
            )
        )
        if len(posts) >= limit:
            break
    return posts


# keyword -> site tag, for classifying channel posts
_CLASSIFY = [
    ("tanks", ("tank", "ztz", "leopard", "abrams", "t-72", "t-80", "armored", "armour", "ground vehicle", "tank campaign")),
    ("aircraft", ("aircraft", "airplane", "plane", "jet", "helicopter", "pilot", "air force", "aviation", "air campaign", "dogfight")),
    ("ships", ("ship", "naval", "fleet", "vessel", "boat", "submarine", "cruiser", "destroyer", "battleship", "ship campaign")),
]


def classify_channel(text: str) -> str | None:
    low = text.lower()
    for tag, words in _CLASSIFY:
        if any(w in low for w in words):
            return tag
    return None


@dataclass
class FeedItem:
    """Unified news item from either source, newest first."""

    id: str  # "site:<id>" or "ch:<id>"
    title: str
    date: str
    dt: object
    url: str
    photo: str | None
    tag: str | None  # tanks / aircraft / ships
    source: str  # "site" | "channel"
    text: str | None = None  # channel post full text
    has_video: bool = False
    video_duration: str | None = None


async def fetch_feed(tag: str | None = None, limit: int = 10) -> list[FeedItem]:
    """Merged website + channel feed, deduped, sorted newest-first."""
    site_articles = await fetch_news(tag=tag, limit=15)
    site_ids = {a.id for a in site_articles}
    items: list[FeedItem] = [
        FeedItem(
            id=f"site:{a.id}",
            title=a.title,
            date=a.date,
            dt=_parse_site_date(a.date),
            url=a.url,
            photo=None,
            tag=tag or a.tag,
            source="site",
        )
        for a in site_articles
    ]
    for p in await fetch_channel_posts(limit=20):
        if p.site_id and p.site_id in site_ids:
            continue  # richer website version already present
        first_line = p.text.split("\n")[0].strip()[:120] or "Channel post"
        items.append(
            FeedItem(
                id=f"ch:{p.id}",
                title=first_line,
                date=p.date,
                dt=p.dt,
                url=p.url,
                photo=p.photo,
                tag=classify_channel(p.text),
                source="channel",
                text=p.text,
                has_video=p.has_video,
                video_duration=p.video_duration,
            )
        )
    items.sort(key=lambda i: i.dt, reverse=True)
    if tag:
        items = [i for i in items if i.tag == tag]
    return items[:limit]


# ---------- news archive (all seasons) ----------

ARCHIVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "news_archive.json")

_archive_cache: list | None = None
_seasons_cache: list | None = None


def _load_archive() -> list:
    global _archive_cache
    if _archive_cache is None:
        try:
            _archive_cache = json.load(open(ARCHIVE_PATH, encoding="utf-8"))
        except Exception:
            _archive_cache = []
    return _archive_cache


def get_seasons() -> list:
    """Return [(version, date_str, start_dt, count)] newest first."""
    global _seasons_cache
    if _seasons_cache is not None:
        return _seasons_cache
    arch = _load_archive()
    seasons = []
    for a in arch:
        m = re.search(r"Season Update ([\d.]+)", a.get("title") or "", re.I)
        if m and "technical" not in (a.get("title") or "").lower():
            try:
                dt = datetime.strptime(a["date"].strip(), "%d %B %Y")
                seasons.append({"version": m.group(1), "date": a["date"], "dt": dt})
            except Exception:
                pass
    # dedupe by version, keep earliest date
    by_ver: dict = {}
    for s in seasons:
        v = s["version"]
        if v not in by_ver or s["dt"] < by_ver[v]["dt"]:
            by_ver[v] = s
    ordered = sorted(by_ver.values(), key=lambda s: s["dt"])
    # assign article counts
    result = []
    for idx, s in enumerate(ordered):
        start = s["dt"]
        end = ordered[idx + 1]["dt"] if idx + 1 < len(ordered) else datetime.now() + timedelta(days=365)
        count = sum(
            1 for a in arch
            if _archive_dt(a) and start <= _archive_dt(a) < end
        )
        result.append({
            "version": s["version"],
            "date": s["date"],
            "dt": start,
            "count": count,
        })
    result.reverse()  # newest first
    _seasons_cache = result
    return result


def _archive_dt(a: dict):
    try:
        return datetime.strptime(a["date"].strip(), "%d %B %Y")
    except Exception:
        return None


def get_season_articles(version: str) -> list:
    """Articles belonging to a season version, newest first."""
    seasons = get_seasons()
    s = next((x for x in seasons if x["version"] == version), None)
    if not s:
        return []
    ordered = sorted(seasons, key=lambda x: x["dt"])
    idx = next(i for i, x in enumerate(ordered) if x["version"] == version)
    start = ordered[idx]["dt"]
    end = ordered[idx + 1]["dt"] if idx + 1 < len(ordered) else datetime.now() + timedelta(days=365)
    arch = _load_archive()
    items = [a for a in arch if _archive_dt(a) and start <= _archive_dt(a) < end]
    items.sort(key=lambda a: _archive_dt(a), reverse=True)
    return items


def get_archive_article(article_id: str) -> dict | None:
    for a in _load_archive():
        if str(a.get("id")) == str(article_id):
            return a
    return None
