"""Daily run: pick a photo iOS will layer behind the clock, add the Life Calendar, publish.

python -m wallpaper.main --site site [--local DIR] [--debug DIR] [--grid-only]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import sys
import time
import tomllib
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
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
    """Image files in a folder; an optional <name>.json sidecar (written by
    laptop/reddit_pull.py) supplies source/title/page_url for the credit."""
    out = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        try:
            with Image.open(f) as im:
                w, h = im.size
        except OSError:
            log.warning("skip unreadable %s", f.name)
            continue
        meta = {}
        side = f.with_suffix(".json")
        if side.exists():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        out.append(fetchers.Candidate(
            key=f"local:{f.name}", source=meta.get("source", "local"), image_url=f.as_uri(),
            width=w, height=h, page_url=meta.get("page_url", ""), title=meta.get("title", f.stem),
            author=meta.get("author", ""), local_path=str(f)))
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
    if not args.birth_date and cfg["grid"].get("view", "year") == "life":
        log.error("BIRTH_DATE is not set (repo secret or --birth-date YYYY-MM-DD); needed for the life view")
        return 2
    birth = date.fromisoformat(args.birth_date.strip()) if args.birth_date else date(2000, 1, 1)
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

    pool = cfg["pool"]
    N = int(pool["size"])
    dark_luma = float(pool["dark_luma"])
    max_bright = N - math.ceil(N * pool["min_dark_share"])
    space_cap = round(N * pool["space_share"])
    land_cap = N - space_cap

    accepted: list[dict] = []
    if not args.grid_only:
        min_h = int(dev.height / sel["max_upscale"]) + 1
        min_w = int(min_h * dev.width / dev.height) + 1
        seen = {h["key"] for h in history}
        if args.local:
            cands = local_candidates(Path(args.local))
        else:
            # Photos you upload to inbox/ are tried first, then the web sources.
            inbox = ROOT / "inbox"
            cands = [c for c in (local_candidates(inbox) if inbox.is_dir() else []) if c.key not in seen]
            cands += fetchers.gather(cfg["sources"], min_h, min_w, seen, dark_luma)
        log.info("%d fresh candidates; pool %d (<= %d bright, ~%d space)", len(cands), N, max_bright, space_cap)
        consumed: list[Path] = []
        deferred: list = []  # skipped only because their kind was full; tried if the pool is short
        t_start = time.time()
        tried = [0]

        def norm_title(t: str) -> str:
            return re.sub(r"[^a-z]+", " ", (t or "").lower()).strip()[:40]

        def redundant(c) -> bool:
            """Max 2 picks per search feed, and no near-duplicate titles."""
            same_feed = sum(1 for a in accepted if a["c"].source == c.source)
            dup = c.title and any(norm_title(a["c"].title) == norm_title(c.title) for a in accepted)
            return same_feed >= pool.get("max_per_feed", 2) or bool(dup)

        def kind_full(c) -> bool:
            n = sum(1 for a in accepted if a["c"].kind == c.kind)
            return n >= (space_cap if c.kind == fetchers.SPACE else land_cap)

        def try_one(c) -> None:
            tried[0] += 1
            t0 = time.time()
            try:
                img = Image.open(c.local_path).convert("RGB") if c.local_path else c.download()
            except Exception as e:  # noqa: BLE001 - any bad download just skips
                log.warning("skip %s: download failed (%s)", c.key, e)
                return
            if c.local_path and not args.local:
                consumed.append(Path(c.local_path))
            if img.height < min_h or img.width < min_w:  # cheap check before the slow model
                log.info("reject %s [%s] too small (%dx%d)", c.key, c.source, img.width, img.height)
                if not args.local:
                    history.append({"key": c.key, "date": today.isoformat(), "used": False, "reason": "too small"})
                return
            matte = vision.segment(img)
            v = vision.evaluate(img, matte, dev, sel)
            luma = None
            if v.ok:
                bg, fg = make_layers(img, matte, v.crop, dev)
                luma = float(np.asarray(bg.convert("L"), dtype=np.float32).mean() / 255)
                n_bright = sum(1 for a in accepted if a["luma"] > dark_luma)
                if luma > dark_luma and n_bright >= max_bright:
                    v = vision.Verdict(False, f"too bright for today's dark quota ({luma:.2f})")
            log.info("%s %s [%s] %s %.1fs", "ACCEPT" if v.ok else "reject", c.key, c.source,
                     ({**v.metrics, "luma": round(luma, 3)} if v.ok else v.reason), time.time() - t0)
            if debug:
                name = c.key.replace(":", "_").replace("/", "_")[:80]
                if v.ok:
                    debug_preview(composite(bg, fg, birth, today, lifespan, style, cfg["grid"]), dev,
                                  f"ACCEPT {c.kind} luma {luma:.2f}").save(debug / f"{name}.jpg")
                else:
                    red = Image.new("RGB", img.size, (255, 0, 0))
                    th = Image.composite(red, img, Image.fromarray((matte * 110).astype("uint8")))
                    th.thumbnail((600, 1200))
                    th.save(debug / f"{name}__{re.sub(r'[^A-Za-z0-9.]+', '_', v.reason)[:40]}.jpg")
            if v.ok:
                accepted.append({"c": c, "bg": bg, "fg": fg, "v": v, "luma": luma})
            elif not args.local and not v.reason.startswith("too bright for today"):
                history.append({"key": c.key, "date": today.isoformat(), "used": False, "reason": v.reason})

        def out_of_budget() -> bool:
            return (len(accepted) >= N or tried[0] >= sel["max_candidates"]
                    or time.time() - t_start > sel.get("time_budget_min", 35) * 60)

        for c in cands:
            if out_of_budget():
                break
            if redundant(c):
                continue
            if kind_full(c):
                deferred.append(c)
                continue
            try_one(c)
        for c in deferred:  # e.g. not enough landscapes passed: let the other kind fill in
            if out_of_budget():
                break
            if not redundant(c):
                try_one(c)
        log.info("accepted %d/%d after %d tries in %.0fs", len(accepted), N, tried[0], time.time() - t_start)
        for p in consumed:  # inbox photos are tried once (used or rejected)
            p.unlink(missing_ok=True)
            p.with_suffix(".json").unlink(missing_ok=True)

    # ---- assemble the pool: today's picks first, then yesterday's to top up
    slots: list[dict] = []
    new_layers = site / "layers_new"
    shutil.rmtree(new_layers, ignore_errors=True)
    for a in accepted:
        c, v = a["c"], a["v"]
        d = new_layers / f"{len(slots) + 1}"
        d.mkdir(parents=True)
        save_jpeg(a["bg"], d / "bg.jpg")
        if cfg["grid"].get("layer", "front") == "behind":
            a["fg"].save(d / "fg.png", optimize=True)
        meta = {k: getattr(c, k) for k in ("key", "source", "kind", "page_url", "title", "author", "author_url")}
        meta.update(date=today.isoformat(), luma=round(a["luma"], 3), metrics=v.metrics)
        (d / "photo.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        slots.append(meta)
        if not args.local:
            c.mark_used()
            history.append({"key": c.key, "date": today.isoformat(), "used": True})
    def load_meta(od: Path) -> dict:
        pj = od / "photo.json"
        return json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {"key": od.name}

    old_dirs = [p for p in layers.glob("*") if (p / "bg.jpg").exists()]
    if (layers / "bg.jpg").exists():  # pre-pool single-photo layout
        old_dirs.append(layers)
    old_dirs.sort(key=lambda p: load_meta(p).get("luma", 0.5))  # top up with the darkest first
    have = {s["key"] for s in slots}
    titles = {re.sub(r"[^a-z]+", " ", (s.get("title") or "").lower()).strip()[:40] for s in slots}
    n_bright = sum(1 for s in slots if s.get("luma", 0) > dark_luma)
    for od in old_dirs:
        if len(slots) >= N:
            break
        meta = load_meta(od)
        t = re.sub(r"[^a-z]+", " ", (meta.get("title") or "").lower()).strip()[:40]
        bright = meta.get("luma", 0) > dark_luma
        kind = meta.get("kind") or fetchers.LANDSCAPE
        title = meta.get("title") or ""
        if (meta.get("key") in have or (t and t in titles) or (bright and n_bright >= max_bright)
                or not fetchers._clean(title, kind) or not fetchers.nasa_ok(title)):
            continue  # carried-over slots pass today's filters too
        n_bright += bright
        titles.add(t)
        d = new_layers / f"{len(slots) + 1}"
        d.mkdir(parents=True)
        for f in ("bg.jpg", "fg.png", "photo.json"):
            if (od / f).exists():
                shutil.copy2(od / f, d / f)
        slots.append(meta)
        have.add(meta.get("key"))
    if not slots:
        log.error("no photo passed and there is no previous pool to fall back on")
        return 1
    shutil.rmtree(layers, ignore_errors=True)
    new_layers.rename(layers)

    # ---- render: w/1.jpg .. w/N.jpg (repeats if the pool is still short)
    wdir = site / "w"
    shutil.rmtree(wdir, ignore_errors=True)
    wdir.mkdir(parents=True)
    for i in range(N):
        d = layers / f"{i % len(slots) + 1}"
        bg = Image.open(d / "bg.jpg").convert("RGB")
        fg = Image.open(d / "fg.png").convert("RGBA") if (d / "fg.png").exists() else Image.new("RGBA", bg.size)
        save_jpeg(composite(bg, fg, birth, today, lifespan, style, cfg["grid"]), wdir / f"{i + 1}.jpg")
    shutil.copy2(wdir / "1.jpg", site / "wallpaper.jpg")  # the fixed URL keeps working
    (site / "status.json").write_text(json.dumps({
        "rendered": datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds"),
        "new_today": len(accepted), "pool_size": N, "photos": slots}, indent=2), encoding="utf-8")
    _write_index(site, slots, N)
    if not args.local:
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_path.write_text(json.dumps(history[-4000:], indent=1), encoding="utf-8")
    log.info("wrote %d wallpapers (%d new today) to %s", N, len(accepted), wdir)
    return 0


def _write_index(site: Path, slots: list[dict], n: int) -> None:
    from html import escape as e
    (site / ".nojekyll").write_text("", encoding="utf-8")
    cards = "".join(
        f'<figure><img src="w/{i + 1}.jpg" loading=lazy><figcaption>{i + 1}. <a href="{e(s.get("page_url", ""))}">'
        f'{e((s.get("title") or "source")[:60])}</a><br>{e(s.get("author", ""))} · {e(s.get("source", ""))}</figcaption></figure>'
        for i, s in enumerate(slots[:n]))
    (site / "index.html").write_text(
        '<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
        '<title>Wallpaper pool</title><style>body{background:#111;color:#999;font:13px system-ui;margin:16px}'
        'main{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}'
        'img{width:100%;border-radius:14px}a{color:#ddd}</style><main>' + cards + '</main>\n', encoding="utf-8")

if __name__ == "__main__":
    sys.exit(main())
