"""Download a few tall Wikimedia Commons featured pictures for offline testing.

usage: python tests/fetch_test_photos.py OUT_DIR [N]
"""
import sys
from pathlib import Path

import requests

UA = "depth-life-wallpaper-test/1.0"
CATS = ["Featured pictures of mountains", "Featured pictures of landscapes", "Featured pictures of rock formations",
        "Featured pictures of trees", "Featured pictures of lighthouses", "Featured pictures of volcanoes"]
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
got = 0
for cat in CATS:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent": UA}, timeout=30, params={
        "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:{cat}",
        "gcmtype": "file", "gcmlimit": 200, "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlheight": 3600})
    pages = r.json().get("query", {}).get("pages", {}).values()
    tall = [p for p in pages if p.get("imageinfo") and p["imageinfo"][0]["mime"] == "image/jpeg"
            and p["imageinfo"][0]["height"] >= 2600 and p["imageinfo"][0]["height"] > 1.25 * p["imageinfo"][0]["width"]]
    for p in tall[: max(1, n // len(CATS))]:
        ii = p["imageinfo"][0]
        url = ii.get("thumburl") or ii["url"]
        name = out / (p["title"].split(":", 1)[1].replace(" ", "_")[:60])
        if not name.suffix.lower() in (".jpg", ".jpeg"):
            name = name.with_suffix(".jpg")
        name.write_bytes(requests.get(url, headers={"User-Agent": UA}, timeout=60).content)
        got += 1
        print(cat, "->", name.name, ii["width"], ii["height"])
print("downloaded", got)
