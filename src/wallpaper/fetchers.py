"""Candidate photo sources, landscapes only: Unsplash and Pexels searches,
Wikimedia Commons Featured Pictures, and (dormant) the EarthPorn family on Reddit."""
from __future__ import annotations

import html
import io
import logging
import os
import random
from dataclasses import dataclass
from datetime import date

import requests
from PIL import Image

log = logging.getLogger(__name__)
UA = "depth-life-wallpaper/1.0 (personal daily-wallpaper bot; one photo per day; https://github.com)"
Image.MAX_IMAGE_PIXELS = 120_000_000

# Keep it EarthPorn-style: drop anything tagged/described as people, animals,
# abstract art or man-made close-ups.
BANNED_TAGS = {"person", "people", "man", "woman", "girl", "boy", "human", "portrait", "selfie",
               "animal", "dog", "cat", "bird", "wildlife", "abstract", "texture", "pattern", "art",
               "illustration", "3d", "render", "flower", "macro", "food", "car", "interior"}
BANNED_WORDS = {"person", "people", "man", "men", "woman", "women", "girl", "boy", "child", "children",
                "portrait", "portraits", "dog", "dogs", "cat", "cats", "bird", "birds", "animal", "animals",
                "insect", "insects", "flower", "flowers", "macro", "abstract",
                "illustration", "render", "couple", "hiker", "silhouette of a"}


@dataclass
class Candidate:
    key: str            # "unsplash:<id>" / "reddit:<id>" for dedup
    source: str
    image_url: str
    width: int
    height: int
    page_url: str
    title: str = ""
    author: str = ""
    author_url: str = ""
    score: float = 0.0
    download_location: str = ""  # Unsplash API guideline: ping on use
    local_path: str = ""          # inbox / --local files

    def download(self) -> Image.Image:
        import time
        for attempt in range(3):
            r = requests.get(self.image_url, headers={"User-Agent": UA}, timeout=60)
            if r.status_code != 429:
                break
            time.sleep(10 * (attempt + 1))  # be polite to rate-limited hosts
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img = img.convert("RGB")
        return img

    def mark_used(self) -> None:
        key = os.environ.get("UNSPLASH_ACCESS_KEY")
        if self.download_location and key:
            try:
                requests.get(self.download_location, params={"client_id": key}, timeout=20)
            except requests.RequestException:
                pass


def _big_enough(w: int, h: int, min_h: int, min_w: int) -> bool:
    return h >= min_h and w >= min_w


def unsplash(cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        log.warning("UNSPLASH_ACCESS_KEY not set; skipping Unsplash")
        return []
    out: list[Candidate] = []
    queries = list(cfg["queries"])
    n = cfg.get("queries_per_run", len(queries))
    start = (date.today().toordinal() * n) % len(queries)  # rotate through the list day by day
    todays = (queries[start:] + queries[:start])[:n]
    for q in todays:
        for page in range(1, cfg.get("pages", 2) + 1):
            try:
                r = requests.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": q, "orientation": "portrait", "order_by": "relevant",
                            "content_filter": "high", "per_page": 30, "page": page},
                    headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
                    timeout=30,
                )
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("unsplash '%s' p%d: %s", q, page, e)
                break
            for p in r.json().get("results", []):
                if p.get("promoted_at") is None and p.get("likes", 0) < cfg.get("min_likes", 20):
                    continue
                if any(t.get("title") in BANNED_TAGS for t in p.get("tags", [])):
                    continue
                desc = f"{p.get('alt_description') or ''} {p.get('description') or ''}".lower()
                if any(f" {w} " in f" {desc} " for w in BANNED_WORDS):
                    continue
                w, h = p["width"], p["height"]
                if not _big_enough(w, h, min_h, min_w):
                    continue
                # Ask imgix for a 3600px-tall JPEG: plenty for 2868 output.
                url = p["urls"]["raw"] + "&fm=jpg&q=90&fit=max&h=3600"
                s = 3600 / h if h > 3600 else 1.0
                out.append(Candidate(
                    key=f"unsplash:{p['id']}", source=f"unsplash/{q}", image_url=url,
                    width=round(w * s), height=round(h * s),
                    page_url=p["links"]["html"], title=p.get("alt_description") or "",
                    author=p["user"]["name"], author_url=p["user"]["links"]["html"],
                    score=float(p.get("likes", 0)), download_location=p["links"]["download_location"],
                ))
    return out


def _reddit_session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if cid and secret:
        try:
            t = s.post("https://www.reddit.com/api/v1/access_token",
                       data={"grant_type": "client_credentials"}, auth=(cid, secret), timeout=20)
            t.raise_for_status()
            s.headers["Authorization"] = f"Bearer {t.json()['access_token']}"
            return s, "https://oauth.reddit.com"
        except requests.RequestException as e:
            log.warning("reddit oauth failed, falling back to public JSON: %s", e)
    return s, "https://www.reddit.com"


def reddit(cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    if not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
        return []  # Reddit blocks anonymous/server access; dormant without approved keys
    s, base = _reddit_session()
    out: list[Candidate] = []
    for sub in cfg["subreddits"]:
        suffix = "" if "oauth" in base else ".json"
        try:
            r = s.get(f"{base}/r/{sub}/{cfg.get('sort', 'hot')}{suffix}", params={"limit": cfg.get("limit", 50), "raw_json": 1}, timeout=30)
            r.raise_for_status()
            listing = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("reddit r/%s: %s (on GitHub Actions set REDDIT_CLIENT_ID/SECRET)", sub, e)
            continue
        for ch in listing.get("data", {}).get("children", []):
            d = ch["data"]
            if d.get("over_18") or d.get("stickied") or d.get("is_video"):
                continue
            url = d.get("url_overridden_by_dest") or d.get("url", "")
            if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                src = d["preview"]["images"][0]["source"]
                w, h = int(src["width"]), int(src["height"])
            except (KeyError, IndexError):
                continue
            if not _big_enough(w, h, min_h, min_w):
                continue
            out.append(Candidate(
                key=f"reddit:{d['id']}", source=f"reddit/r/{sub}", image_url=html.unescape(url),
                width=w, height=h, page_url="https://www.reddit.com" + d["permalink"],
                title=d.get("title", ""), author=f"u/{d.get('author', '')}",
                author_url=f"https://www.reddit.com/user/{d.get('author', '')}", score=float(d.get("score", 0)),
            ))
    return out


def _todays(items: list, n: int) -> list:
    """Rotate through a list n items per day so the pool keeps changing."""
    if not items:
        return []
    start = (date.today().toordinal() * n) % len(items)
    return (items[start:] + items[:start])[:n]


def _clean_text(text: str) -> bool:
    t = f" {text.lower()} "
    return not any(f" {w} " in t for w in BANNED_WORDS)


def pexels(cfg: dict, queries: list[str], min_h: int, min_w: int) -> list[Candidate]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        log.info("PEXELS_API_KEY not set; skipping Pexels")
        return []
    out: list[Candidate] = []
    for q in _todays(queries, cfg.get("queries_per_run", 6)):
        try:
            r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=30,
                             params={"query": q, "orientation": "portrait", "size": "large", "per_page": 40})
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("pexels '%s': %s", q, e)
            continue
        for p in r.json().get("photos", []):
            w, h = p["width"], p["height"]
            if not _big_enough(w, h, min_h, min_w) or not _clean_text(p.get("alt") or ""):
                continue
            # Pexels serves resized copies via query params; ~3600 tall is plenty.
            url = p["src"]["original"] + "?auto=compress&cs=tinysrgb&fit=crop&h=3600"
            s = min(1.0, 3600 / h)
            out.append(Candidate(
                key=f"pexels:{p['id']}", source=f"pexels/{q}", image_url=url,
                width=round(w * s), height=round(h * s), page_url=p["url"], title=p.get("alt") or "",
                author=p.get("photographer", ""), author_url=p.get("photographer_url", ""),
            ))
    return out


# Wikimedia only serves (and doesn't rate-limit) thumbnails at these widths.
COMMONS_WIDTHS = (960, 1280, 1920, 3840)


def _commons_thumb(url: str, w: int, h: int, min_h: int) -> tuple[str, int, int]:
    """Smallest standard-width thumbnail that is still tall enough."""
    from urllib.parse import quote
    for tw in COMMONS_WIDTHS:
        th = round(h * tw / w)
        if th >= min_h and tw < w:
            head, name = url.rsplit("/", 1)
            thumb = head.replace("/wikipedia/commons/", "/wikipedia/commons/thumb/", 1) + f"/{name}/{tw}px-{name}"
            return thumb, tw, th
    return url, w, h


def wikimedia(cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    """Commons Featured Pictures by category: community-curated, no key."""
    out: list[Candidate] = []
    for cat in _todays(cfg["categories"], cfg.get("categories_per_run", 2)):
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent": UA}, timeout=30, params={
                "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:{cat}",
                "gcmtype": "file", "gcmlimit": 500, "gcmsort": "timestamp", "gcmdir": "desc",
                "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                "iiextmetadatafilter": "Artist|ObjectName|Categories"})
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", {}).values()
        except (requests.RequestException, ValueError) as e:
            log.warning("wikimedia %s: %s", cat, e)
            continue
        for p in pages:
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("mime") != "image/jpeg" or ii.get("size", 0) > cfg.get("max_bytes", 30_000_000):
                continue
            w, h = ii.get("width", 0), ii.get("height", 0)
            meta = ii.get("extmetadata", {})
            text = " ".join([p["title"], meta.get("ObjectName", {}).get("value", ""),
                             meta.get("Categories", {}).get("value", "").replace("|", " ")])
            if not _big_enough(w, h, min_h, min_w) or not _clean_text(text.replace("_", " ")):
                continue
            import re
            artist = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
            url, tw, th = _commons_thumb(ii["url"], w, h, min_h)
            out.append(Candidate(
                key=f"wikimedia:{p['pageid']}", source=f"wikimedia/{cat}", image_url=url,
                width=tw, height=th, page_url=ii.get("descriptionurl", ""),
                title=p["title"].split(":", 1)[-1].rsplit(".", 1)[0].replace("_", " "), author=artist[:80],
            ))
    random.shuffle(out)  # no popularity signal; featured status is the quality bar
    return out


def gather(cfg: dict, min_h: int, min_w: int, seen: set[str]) -> list[Candidate]:
    cands = (unsplash(cfg["unsplash"], min_h, min_w)
             + pexels(cfg.get("pexels", {}), cfg["unsplash"]["queries"], min_h, min_w)
             + wikimedia(cfg["wikimedia"], min_h, min_w)
             + reddit(cfg["reddit"], min_h, min_w))
    fresh = {c.key: c for c in cands if c.key not in seen}
    ranked = sorted(fresh.values(), key=lambda c: c.score, reverse=True)
    # Keep popularity order but interleave sources so one feed can't hog the budget.
    by_src: dict[str, list[Candidate]] = {}
    for c in ranked:
        by_src.setdefault(c.source.split("/")[0], []).append(c)
    mixed: list[Candidate] = []
    while any(by_src.values()):
        for lst in by_src.values():
            if lst:
                mixed.append(lst.pop(0))
    # A little shuffle inside the top band so it isn't the same order every day.
    head = mixed[: cfg.get("shuffle_top", 0)]
    random.shuffle(head)
    return head + mixed[len(head):]
