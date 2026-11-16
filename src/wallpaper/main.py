"""Daily run: pick a photo iOS will layer behind the clock, add the Life Calendar, publish.

python -m wallpaper.main --site site [--local DIR] [--debug DIR] [--grid-only]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import tomllib
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from . import fetchers, vision
from .compositor import composite, debug_preview, make_layers, save_jpeg
from .device import DEVICES
from .grid import GridStyle

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("wallpaper")


def load_history(p: Path) -> list[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def local_candidates(folder: Path) -> list[fetchers.Candidate]:
    out = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            try:
                with Image.open(f) as im:
                    w, h = im.size
            except OSError:
                log.warning("skip unreadable %s", f.name)
                continue
            out.append(fetchers.Candidate(key=f"local:{f.name}", source="local", image_url=f.as_uri(),
                                          width=w, height=h, page_url=str(f), title=f.stem))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--site", default=str(ROOT / "site"), help="output folder published to GitHub Pages")
    ap.add_argument("--history", default=str(ROOT / "data" / "history.json"))
    ap.add_argument("--local", help="use images from this folder instead of the web (testing)")
    ap.add_argument("--debug", help="write annotated previews of every candidate here")
    ap.add_argument("--grid-only", action="store_true", help="re-render today's grid on the last accepted photo")
    ap.add_argument("--birth-date", default=os.environ.get("BIRTH_DATE"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    if not args.birth_date:
        log.error("BIRTH_DATE is not set (repo secret or --birth-date YYYY-MM-DD)")
        return 2
    birth = date.fromisoformat(args.birth_date.strip())
    today = datetime.now(ZoneInfo(cfg["timezone"])).date()
    dev = DEVICES[cfg["device"]]
    style = GridStyle(show_caption=cfg["grid"].get("show_caption", True))
    lifespan = int(cfg["lifespan_years"])
    sel = cfg["selection"]

    site = Path(args.site)
    layers = site / "layers"
    hist_path = Path(args.history)
    history = load_history(hist_path)
    debug = Path(args.debug) if args.debug else None
    if debug:
        debug.mkdir(parents=True, exist_ok=True)

    accepted = None
    if not args.grid_only:
        min_h = int(dev.height / sel["max_upscale"]) + 1
        min_w = int(min_h * dev.width / dev.height) + 1
        seen = {h["key"] for h in history}
        if args.local:
            cands = local_candidates(Path(args.local))
        else:
            # Photos you drop into inbox/ (e.g. saved from r/EarthPorn via the
            # GitHub app) are tried first, then the web sources.
            inbox = ROOT / "inbox"
            cands = [c for c in (local_candidates(inbox) if inbox.is_dir() else []) if c.key not in seen]
            cands += fetchers.gather(cfg["sources"], min_h, min_w, seen)
        log.info("%d fresh candidates", len(cands))
        tried = 0
        for c in cands:
            if tried >= sel["max_candidates"]:
                break
            tried += 1
            t0 = time.time()
            try:
                img = Image.open(Path(c.page_url)).convert("RGB") if c.source == "local" else c.download()
            except Exception as e:  # noqa: BLE001 - any bad download just skips
                log.warning("skip %s: download failed (%s)", c.key, e)
                continue
            matte = vision.segment(img)
            v = vision.evaluate(img, matte, dev, sel)
            log.info("%s %s [%s] %s %.1fs", "ACCEPT" if v.ok else "reject", c.key, c.source, v.reason if not v.ok else v.metrics, time.time() - t0)
            if debug:
                name = c.key.replace(":", "_").replace("/", "_")
                if v.ok:
                    bg, fg = make_layers(img, matte, v.crop, dev)
                    debug_preview(composite(bg, fg, birth, today, lifespan, style), dev, "ACCEPT").save(debug / f"{name}.jpg")
                else:
                    red = Image.new("RGB", img.size, (255, 0, 0))
                    tint = Image.fromarray((matte * 110).astype("uint8"))
                    th = Image.composite(red, img, tint); th.thumbnail((600, 1200))
                    th.save(debug / f"{name}__{v.reason[:40].replace(' ', '_').replace('/', '-')}.jpg")
            if v.ok:
                accepted = (c, img, matte, v)
                break
            if not args.local:
                history.append({"key": c.key, "date": today.isoformat(), "used": False, "reason": v.reason})
                if c.source == "local":
                    log.warning("inbox photo %s rejected: %s", c.title, v.reason)

    if accepted:
        c, img, matte, v = accepted
        bg, fg = make_layers(img, matte, v.crop, dev)
        layers.mkdir(parents=True, exist_ok=True)
        save_jpeg(bg, layers / "bg.jpg")
        fg.save(layers / "fg.png", optimize=True)
        meta = {k: getattr(c, k) for k in ("key", "source", "page_url", "title", "author", "author_url")}
        meta.update(date=today.isoformat(), metrics=v.metrics)
        (layers / "photo.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if not args.local:
            c.mark_used()
            history.append({"key": c.key, "date": today.isoformat(), "used": True})
    elif (layers / "bg.jpg").exists() and (layers / "fg.png").exists():
        log.warning("no new photo passed today; re-using the last one with today's grid")
    else:
        log.error("no photo passed and there is no previous photo to fall back on")
        return 1

    bg = Image.open(layers / "bg.jpg").convert("RGB")
    fg = Image.open(layers / "fg.png").convert("RGBA")
    final = composite(bg, fg, birth, today, lifespan, style)
    save_jpeg(final, site / "wallpaper.jpg")
    photo = json.loads((layers / "photo.json").read_text(encoding="utf-8"))
    (site / "status.json").write_text(json.dumps({"rendered": datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds"),
                                                  "new_photo_today": bool(accepted), "photo": photo}, indent=2), encoding="utf-8")
    _write_index(site, photo)
    if not args.local:
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_path.write_text(json.dumps(history[-3000:], indent=1), encoding="utf-8")
    log.info("wrote %s", site / "wallpaper.jpg")
    return 0


def _write_index(site: Path, photo: dict) -> None:
    from html import escape as e
    (site / ".nojekyll").write_text("", encoding="utf-8")
    (site / "index.html").write_text(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Today's wallpaper</title><style>body{{background:#1a1a1a;color:#aaa;font:15px system-ui;margin:16px;text-align:center}}img{{max-width:min(420px,100%);border-radius:24px}}a{{color:#ddd}}</style>
<img src="wallpaper.jpg" alt="today's wallpaper"><p>Photo: <a href="{e(photo.get('page_url',''))}">{e(photo.get('title','') or 'source')}</a>
by <a href="{e(photo.get('author_url',''))}">{e(photo.get('author',''))}</a> via {e(photo.get('source',''))} &middot; {e(photo.get('date',''))}</p>
""", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
