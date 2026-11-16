"""Candidate photo sources: Unsplash landscape searches and the EarthPorn family on Reddit."""
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
UA = "depth-life-wallpaper/1.0 (personal wallpaper bot)"
Image.MAX_IMAGE_PIXELS = 120_000_000

# Keep it EarthPorn-style: drop anything tagged/described as people, animals,
# abstract art or man-made close-ups.
BANNED_TAGS = {"person", "people", "man", "woman", "girl", "boy", "human", "portrait", "selfie",
               "animal", "dog", "cat", "bird", "wildlife", "abstract", "texture", "pattern", "art",
               "illustration", "3d", "render", "flower", "macro", "food", "car", "interior"}
BANNED_WORDS = {"person", "people", "man", "woman", "girl", "boy", "dog", "cat", "bird", "abstract",
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
        r = requests.get(self.image_url, headers={"User-Agent": UA}, timeout=60)
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


def gather(cfg: dict, min_h: int, min_w: int, seen: set[str]) -> list[Candidate]:
    cands = unsplash(cfg["unsplash"], min_h, min_w) + reddit(cfg["reddit"], min_h, min_w)
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
