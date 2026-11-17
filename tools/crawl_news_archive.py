#!/usr/bin/env python3
"""Crawl the full wtmobile.com news archive (all pages).

Outputs data/news_archive.json: [{id, title, date, url, tag}]
Run in background; safe to re-run (dedupes by URL).
"""
import json
import os
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (WTM-Bot-Archive/1.0)"}
BASE = "https://wtmobile.com/en/news"
OUT = os.path.expanduser("~/workspace/war-thunder-mobile-bot/data/news_archive.json")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")


def parse_page(html: str) -> list[dict]:
    items = []
    # article cards link to /en/news/<id or slug>
    for m in re.finditer(
        r'<a[^>]+href="(/en/news/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
    ):
        url, inner = m.group(1), m.group(2)
        if url == "/en/news" or "?" in url:
            continue
        txt = " ".join(re.sub(r"<[^>]+>", " ", inner).split())
        if len(txt) < 10:
            continue
        # title is usually the longest text chunk; date like "15 October 2026"
        dm = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", txt)
        date = dm.group(1) if dm else ""
        title = txt.replace(date, "").strip(" -|")
        # tag from nearby label
        tag = ""
        for t in ("Tanks", "Aviation", "Fleet", "Ships"):
            if t.lower() in txt.lower()[:120]:
                tag = t.lower()
                break
        items.append({
            "id": url.rstrip("/").split("/")[-1],
            "title": title[:200],
            "date": date,
            "url": "https://wtmobile.com" + url,
            "tag": tag,
        })
    return items


def main() -> None:
    try:
        archive = json.load(open(OUT))
    except Exception:
        archive = []
    seen_urls = {a["url"] for a in archive}
    # discover last page
    html1 = fetch(BASE)
    pages = {int(p) for p in re.findall(r"/en/news\?page=(\d+)", html1)}
    last = max(pages) if pages else 1
    print(f"pages: 1..{last}, have {len(archive)}", flush=True)
    for p in range(1, last + 1):
        try:
            html = html1 if p == 1 else fetch(f"{BASE}?page={p}")
            new = 0
            for it in parse_page(html):
                if it["url"] not in seen_urls:
                    seen_urls.add(it["url"])
                    archive.append(it)
                    new += 1
            print(f"page {p}: +{new} (total {len(archive)})", flush=True)
        except Exception as e:
            print(f"page {p} FAILED: {e}", flush=True)
        time.sleep(1.5)
    json.dump(archive, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"DONE: {len(archive)} articles", flush=True)


main()
