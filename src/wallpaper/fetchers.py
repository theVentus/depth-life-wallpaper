"""Candidate photo sources, two kinds:

- landscape: EarthPorn-style scenery (Unsplash/Pexels searches, Wikimedia
  Commons Featured Pictures, dormant Reddit)
- space: real imagery and artistic renders (NASA Image Library incl.
  artist's concepts, Commons astronomy Featured Pictures, Unsplash/Pexels
  space searches)

Every candidate carries an optional brightness estimate (from the source's
average colour) so dark photos can be preferred before anything is
downloaded.
"""
from __future__ import annotations

import html
import io
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date

import requests
from PIL import Image

log = logging.getLogger(__name__)
UA = "depth-life-wallpaper/1.0 (personal daily-wallpaper bot; https://github.com/theVentus/depth-life-wallpaper)"
Image.MAX_IMAGE_PIXELS = 160_000_000

LANDSCAPE, SPACE = "landscape", "space"

# No people, animals or close-ups anywhere. Landscapes additionally exclude
# art/renders; space keeps them (artistic renders are wanted there).
BANNED_COMMON = {"person", "people", "man", "men", "woman", "women", "girl", "boy", "child", "children",
                 "portrait", "portraits", "selfie", "couple", "hiker", "dog", "dogs", "cat", "cats", "bird",
                 "birds", "animal", "animals", "wildlife", "insect", "insects", "flower", "flowers", "macro",
                 "food", "car", "interior", "silhouette of a", "crowd", "crowds", "spectators", "guests",
                 "visitors", "students", "employees", "team", "attendees", "workers", "engineers",
                 "technicians", "astronaut", "astronauts", "crew", "patch", "logo", "ceremony", "event",
                 "media", "press", "officials", "administrator", "family", "families", "public"}
BANNED_LANDSCAPE = BANNED_COMMON | {"abstract", "illustration", "render", "art", "3d", "texture", "pattern"}


def _clean(text: str, kind: str) -> bool:
    t = f" {re.sub(r'[^a-z0-9 ]', ' ', text.lower())} "
    banned = BANNED_LANDSCAPE if kind == LANDSCAPE else BANNED_COMMON
    return not any(f" {w} " in t for w in banned)


def _hex_luma(hex_color: str | None) -> float | None:
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255
    except (AttributeError, ValueError):
        return None


@dataclass
class Candidate:
    key: str            # "<source>:<id>" for dedup
    source: str
    image_url: str
    width: int          # 0 = unknown until downloaded
    height: int
    page_url: str
    kind: str = LANDSCAPE
    title: str = ""
    author: str = ""
    author_url: str = ""
    score: float = 0.0
    est_luma: float | None = None  # 0 (black) .. 1 (white), from the source's average colour
    download_location: str = ""    # Unsplash API guideline: ping on use
    local_path: str = ""           # inbox / --local files

    def download(self) -> Image.Image:
        for attempt in range(3):
            r = requests.get(self.image_url, headers={"User-Agent": UA}, timeout=90)
            if r.status_code != 429:
                break
            time.sleep(10 * (attempt + 1))  # be polite to rate-limited hosts
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")

    def mark_used(self) -> None:
        key = os.environ.get("UNSPLASH_ACCESS_KEY")
        if self.download_location and key:
            try:
                requests.get(self.download_location, params={"client_id": key}, timeout=20)
            except requests.RequestException:
                pass


def _big_enough(w: int, h: int, min_h: int, min_w: int) -> bool:
    return h >= min_h and w >= min_w


def _todays(items: list, n: int) -> list:
    """Rotate through a list n items per day so the pool keeps changing."""
    if not items:
        return []
    start = (date.today().toordinal() * n) % len(items)
    return (items[start:] + items[:start])[:n]


# --------------------------------------------------------------- Unsplash
def unsplash(queries: list[str], kind: str, cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return []
    out: list[Candidate] = []
    for q in _todays(queries, cfg.get("queries_per_run", 6)):
        for page in range(1, cfg.get("pages", 1) + 1):
            try:
                r = requests.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": q, "orientation": "portrait", "order_by": "relevant",
                            "content_filter": "high", "per_page": 30, "page": page},
                    headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"}, timeout=30)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("unsplash '%s' p%d: %s", q, page, e)
                break
            for p in r.json().get("results", []):
                if p.get("likes", 0) < cfg.get("min_likes", 20):
                    continue
                tags = " ".join(t.get("title", "") for t in p.get("tags", []))
                if not _clean(f"{p.get('alt_description') or ''} {p.get('description') or ''} {tags}", kind):
                    continue
                w, h = p["width"], p["height"]
                if not _big_enough(w, h, min_h, min_w):
                    continue
                s = min(1.0, 3600 / h)
                out.append(Candidate(
                    key=f"unsplash:{p['id']}", source=f"unsplash/{q}", kind=kind,
                    image_url=p["urls"]["raw"] + "&fm=jpg&q=90&fit=max&h=3600",
                    width=round(w * s), height=round(h * s), page_url=p["links"]["html"],
                    title=p.get("alt_description") or "", author=p["user"]["name"],
                    author_url=p["user"]["links"]["html"], score=float(p.get("likes", 0)),
                    est_luma=_hex_luma(p.get("color")), download_location=p["links"]["download_location"]))
    return out


# ----------------------------------------------------------------- Pexels
def pexels(queries: list[str], kind: str, cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
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
            if not _big_enough(w, h, min_h, min_w) or not _clean(p.get("alt") or "", kind):
                continue
            s = min(1.0, 3600 / h)
            out.append(Candidate(
                key=f"pexels:{p['id']}", source=f"pexels/{q}", kind=kind,
                image_url=p["src"]["original"] + "?auto=compress&cs=tinysrgb&fit=crop&h=3600",
                width=round(w * s), height=round(h * s), page_url=p["url"], title=p.get("alt") or "",
                author=p.get("photographer", ""), author_url=p.get("photographer_url", ""),
                est_luma=_hex_luma(p.get("avg_color"))))
    return out


# ------------------------------------------------------- Wikimedia Commons
def wikimedia(categories: list[str], kind: str, cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    """Commons Featured Pictures by category: community-curated, no key."""
    out: list[Candidate] = []
    for cat in _todays(categories, cfg.get("categories_per_run", 3)):
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent": UA}, timeout=30, params={
                "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:{cat}",
                "gcmtype": "file", "gcmlimit": 500, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                "iiurlheight": 3000,  # API rounds to a standard thumbnail size and returns a valid URL
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
                             meta.get("Categories", {}).get("value", "").replace("|", " ")]).replace("_", " ")
            if not _big_enough(w, h, min_h, min_w) or not _clean(text, kind):
                continue
            artist = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
            # Commons serves thumbnails at most 3840 px wide, whatever the API
            # reports; wide panoramas would arrive too short, so use originals.
            tw = min(ii.get("thumbwidth", w), 3840)
            th = round(h * tw / w)
            url = ii.get("thumburl", ii["url"])
            if th < min_h:
                url, tw, th = ii["url"], w, h
            out.append(Candidate(
                key=f"wikimedia:{p['pageid']}", source=f"wikimedia/{cat}", kind=kind, image_url=url,
                width=tw, height=th, page_url=ii.get("descriptionurl", ""),
                title=p["title"].split(":", 1)[-1].rsplit(".", 1)[0].replace("_", " "), author=artist[:80]))
    random.shuffle(out)  # no popularity signal; featured status is the quality bar
    return out


# ------------------------------------------------------ NASA Image Library
def nasa(queries: list[str], cfg: dict) -> list[Candidate]:
    """images.nasa.gov: real mission imagery and artist's concepts, no key.
    Sizes aren't in the search results; undersized ones fail the crop check."""
    out: list[Candidate] = []
    for q in _todays(queries, cfg.get("queries_per_run", 4)):
        try:
            r = requests.get("https://images-api.nasa.gov/search", headers={"User-Agent": UA}, timeout=30,
                             params={"q": q, "media_type": "image", "page_size": 60})
            r.raise_for_status()
            items = r.json()["collection"]["items"]
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("nasa '%s': %s", q, e)
            continue
        for it in items:
            d = (it.get("data") or [{}])[0]
            nid = d.get("nasa_id")
            text = f"{d.get('title', '')} {' '.join(d.get('keywords', []) or [])} {(d.get('description') or '')[:300]}"
            if not nid or not _clean(text, SPACE):
                continue
            # The library is mostly press/event photos; keep the imagery feeds:
            # JPL Photojournal (planets, artist's concepts), ISS Earth views, launches.
            kw = text.lower()
            if not (nid.startswith("PIA") or nid.lower().startswith("iss")
                    or (nid.startswith("KSC") and "launch" in kw) or "artist" in kw):
                continue
            if any(w in kw for w in ("3-d", "3d ", "anaglyph", "stereo", "diagram", "chart", "graphic", "test",
                                     " lab", "laboratory", "clean room", "cleanroom", "assembly", "facility",
                                     "hardware", "installed", "engineering", "mockup", "prototype")):
                continue
            if "artist" in kw and not any(w in kw for w in ("planet", "exoplanet", "moon", "star", "galaxy", "nebula")):
                continue  # artist's concepts of spacecraft crop badly; keep worlds and skies
            out.append(Candidate(
                key=f"nasa:{nid}", source=f"nasa/{q}", kind=SPACE, width=0, height=0,
                image_url=f"https://images-assets.nasa.gov/image/{nid}/{nid}~orig.jpg",
                page_url=f"https://images.nasa.gov/details/{nid}", title=d.get("title", ""),
                author=d.get("photographer") or d.get("secondary_creator") or d.get("center") or "NASA"))
    random.shuffle(out)
    return out


# ------------------------------------------------- Reddit (dormant, keys only)
def reddit(cfg: dict, min_h: int, min_w: int) -> list[Candidate]:
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return []  # Reddit blocks anonymous/server access; dormant without approved keys
    s = requests.Session()
    s.headers["User-Agent"] = UA
    try:
        t = s.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                   auth=(cid, secret), timeout=20)
        t.raise_for_status()
        s.headers["Authorization"] = f"Bearer {t.json()['access_token']}"
    except requests.RequestException as e:
        log.warning("reddit oauth failed: %s", e)
        return []
    out: list[Candidate] = []
    for sub in cfg["subreddits"]:
        try:
            r = s.get(f"https://oauth.reddit.com/r/{sub}/{cfg.get('sort', 'hot')}",
                      params={"limit": cfg.get("limit", 50), "raw_json": 1}, timeout=30)
            r.raise_for_status()
            listing = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("reddit r/%s: %s", sub, e)
            continue
        for ch in listing.get("data", {}).get("children", []):
            d = ch["data"]
            url = d.get("url_overridden_by_dest") or d.get("url", "")
            if d.get("over_18") or d.get("stickied") or not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                src = d["preview"]["images"][0]["source"]
                w, h = int(src["width"]), int(src["height"])
            except (KeyError, IndexError):
                continue
            if _big_enough(w, h, min_h, min_w):
                out.append(Candidate(
                    key=f"reddit:{d['id']}", source=f"reddit/r/{sub}", image_url=html.unescape(url),
                    width=w, height=h, page_url="https://www.reddit.com" + d["permalink"], title=d.get("title", ""),
                    author=f"u/{d.get('author', '')}", score=float(d.get("score", 0))))
    return out


# ------------------------------------------------------------------ gather
def gather(cfg: dict, min_h: int, min_w: int, seen: set[str], dark_luma: float) -> list[Candidate]:
    L, S = cfg["landscape"], cfg["space"]
    cands = (unsplash(L["queries"], LANDSCAPE, cfg.get("unsplash", {}), min_h, min_w)
             + unsplash(S["queries"], SPACE, cfg.get("unsplash", {}), min_h, min_w)
             + pexels(L["queries"], LANDSCAPE, cfg.get("pexels", {}), min_h, min_w)
             + pexels(S["queries"], SPACE, cfg.get("pexels", {}), min_h, min_w)
             + wikimedia(L["wikimedia_categories"], LANDSCAPE, cfg.get("wikimedia", {}), min_h, min_w)
             + wikimedia(S["wikimedia_categories"], SPACE, cfg.get("wikimedia", {}), min_h, min_w)
             + nasa(S["nasa_queries"], cfg.get("nasa", {}))
             + reddit(cfg["reddit"], min_h, min_w))
    max_est = cfg.get("max_est_luma", 0.62)
    fresh = {c.key: c for c in cands if c.key not in seen and (c.est_luma is None or c.est_luma <= max_est)}
    # Within each feed: known-dark first, then by popularity.
    rank = lambda c: (not (c.est_luma is not None and c.est_luma <= dark_luma), -c.score)  # noqa: E731
    groups: dict[str, list[Candidate]] = {}
    for c in sorted(fresh.values(), key=rank):
        groups.setdefault(f"{c.kind}/{c.source.split('/')[0]}", []).append(c)
    log.info("candidates per feed: %s", {k: len(v) for k, v in groups.items()})
    mixed: list[Candidate] = []
    while any(groups.values()):  # round-robin so no single feed hogs the budget
        for lst in groups.values():
            if lst:
                mixed.append(lst.pop(0))
    return mixed
