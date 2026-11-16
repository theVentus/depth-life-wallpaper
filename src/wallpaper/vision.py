"""Foreground segmentation, iOS Depth Effect checks and clock-overlap cropping.

iOS gives no feedback on whether Depth Effect engaged, so everything is
decided here: a photo is only accepted if, after cropping, its subject's
apex tucks under the bottom of the lock-screen clock numerals and the
heuristics below (which mirror what makes Apple's on-device segmentation
fail) all pass.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from scipy import ndimage

from .device import Device


@dataclass
class Verdict:
    ok: bool
    reason: str
    crop: tuple[int, int, int, int] | None = None  # source-px box (l, t, r, b)
    metrics: dict = field(default_factory=dict)


_session = None


def segment(img: Image.Image) -> np.ndarray:
    """Return a float32 alpha matte in [0, 1] at the image's resolution."""
    global _session
    from rembg import new_session, remove

    if _session is None:
        _session = new_session(os.environ.get("REMBG_MODEL", "isnet-general-use"))
    work = img.convert("RGB")
    long_side = max(work.size)
    if long_side > 1280:  # model runs at 1024 internally; no gain from feeding more
        s = 1280 / long_side
        work = work.resize((round(work.width * s), round(work.height * s)), Image.LANCZOS)
    matte = remove(work, session=_session, only_mask=True)
    if matte.size != img.size:
        matte = matte.resize(img.size, Image.BILINEAR)
    return np.asarray(matte, dtype=np.float32) / 255.0


def _apex(mask: np.ndarray, x0: int, x1: int, min_px: int) -> int | None:
    """Topmost row whose solid subject pixels inside [x0, x1) reach min_px."""
    counts = mask[:, x0:x1].sum(axis=1)
    rows = np.flatnonzero(counts >= min_px)
    return int(rows[0]) if rows.size else None


def evaluate(img: Image.Image, matte: np.ndarray, dev: Device, cfg: dict) -> Verdict:
    W_src, H_src = img.size
    out_w, out_h = dev.width, dev.height
    aspect = out_w / out_h
    target = cfg["apex_target"]
    lo_apex = dev.clock_bottom - cfg["max_clock_cover"] * dev.clock_h
    hi_apex = dev.clock_bottom - cfg["min_clock_cover"] * dev.clock_h

    solid = matte > 0.5
    # Remove hair/branch-thin bits before finding the apex: Apple's matte
    # ignores them too, so they must not decide where the clock goes.
    open_r = max(2, round(min(W_src, H_src) * 0.004))
    core = ndimage.binary_opening(solid, structure=np.ones((open_r * 2 + 1,) * 2))
    if core.mean() < 0.01:
        return Verdict(False, "no clear subject")

    min_ch = int(np.ceil(out_h / cfg["max_upscale"]))
    max_ch = int(min(H_src, W_src / aspect))
    if max_ch < min_ch:
        return Verdict(False, f"too small ({W_src}x{H_src}) for {out_w}x{out_h} at <= {cfg['max_upscale']}x upscale")

    min_px_src = max(4, round(W_src * 0.006))
    apex_src = _apex(core, 0, W_src, min_px_src)
    band = core[apex_src: apex_src + max(4, round(H_src * 0.04))]
    ys, xs = np.nonzero(band)
    apex_x = float(xs.mean())

    last_reason = "no crop places the subject under the clock"
    ch = max_ch
    while ch >= min_ch:
        cw = round(ch * aspect)
        left = int(np.clip(round(apex_x - cw / 2), 0, W_src - cw))
        top = round(apex_src - target * ch)
        if top < 0 or top + ch > H_src:
            # Zooming in (smaller crop) moves both edges toward the apex.
            last_reason = "not enough room above the subject" if top < 0 else "crop would run off the bottom"
            ch -= max(8, round(ch * 0.03))
            continue
        v = _check_crop(img, solid, core, (left, top, left + cw, top + ch), dev, cfg, lo_apex, hi_apex)
        if v.ok:
            return v
        last_reason = v.reason
        if not v.metrics.get("zoom_may_help"):
            return v
        ch -= max(8, round(ch * 0.03))
    return Verdict(False, last_reason)


def _check_crop(img, solid, core, box, dev: Device, cfg, lo_apex, hi_apex) -> Verdict:
    l, t, r, b = box
    ch, cw = b - t, r - l
    s_mask = solid[t:b, l:r]
    c_mask = core[t:b, l:r]
    m = {"scale": round(dev.height / ch, 3)}

    area = float(s_mask.mean())
    m["area"] = round(area, 3)
    if area < cfg["min_area"]:
        return Verdict(False, f"subject too small ({area:.0%})", metrics={**m, "zoom_may_help": True})
    if area > cfg["max_area"]:
        return Verdict(False, f"subject too large ({area:.0%})", metrics=m)

    cx0, cx1 = round(dev.clock_x0 * cw), round(dev.clock_x1 * cw)
    apex = _apex(c_mask, cx0, cx1, max(3, round(cw * 0.01)))
    if apex is None:
        return Verdict(False, "subject not under the clock horizontally", metrics=m)
    apex_f = apex / ch
    m["apex"] = round(apex_f, 4)
    if not (lo_apex <= apex_f <= hi_apex):
        return Verdict(False, f"apex at {apex_f:.1%}, needs {lo_apex:.1%}-{hi_apex:.1%}", metrics=m)

    # Anything of the subject poking above the clock elsewhere (outside the
    # numerals' span) is fine for iOS, but it must not cover the date line.
    date_top = round(dev.date_top * ch)
    if c_mask[:date_top].any():
        return Verdict(False, "subject reaches the date/status area", metrics=m)

    # Fragmentation just below the apex: many separate pieces or lots of
    # thin structure removed by the opening -> Apple's Vision matte breaks.
    band_h = max(6, round(ch * cfg["frag_band"]))
    band_s = s_mask[apex: apex + band_h, cx0:cx1]
    band_c = c_mask[apex: apex + band_h, cx0:cx1]
    lab, n = ndimage.label(band_s)
    if n:
        sizes = np.bincount(lab.ravel())[1:]
        big = int((sizes >= band_s.size * 0.002).sum())
    else:
        big = 0
    thin = 1.0 - (band_c.sum() / max(1, band_s.sum()))
    m.update(frag_pieces=big, thin_ratio=round(float(thin), 3))
    if big > cfg["max_frag_pieces"]:
        return Verdict(False, f"fragmented outline under clock ({big} pieces)", metrics=m)
    if thin > cfg["max_thin_ratio"]:
        return Verdict(False, f"wispy outline under clock ({thin:.0%} thin)", metrics=m)

    # Background clutter behind the clock: Apple segments on-device and fails
    # on busy backgrounds; it also hurts clock legibility.
    crop_small = img.crop(box).convert("L").resize((cw // 4 or 1, ch // 4 or 1), Image.BILINEAR)
    g = np.asarray(crop_small, dtype=np.float32) / 255.0
    sm = np.asarray(Image.fromarray(s_mask.astype(np.uint8) * 255).resize(crop_small.size, Image.NEAREST)) > 0
    y0, y1 = round(dev.clock_top * g.shape[0]), round(dev.clock_bottom * g.shape[0])
    x0, x1 = round(dev.clock_x0 * g.shape[1]), round(dev.clock_x1 * g.shape[1])
    zone, zone_fg = g[y0:y1, x0:x1], sm[y0:y1, x0:x1]
    bgpx = zone[~zone_fg]
    if bgpx.size < zone.size * 0.4:
        return Verdict(False, "subject covers too much of the clock", metrics=m)
    gx = ndimage.sobel(zone, axis=1)
    gy = ndimage.sobel(zone, axis=0)
    edges = np.hypot(gx, gy)[~ndimage.binary_dilation(zone_fg, iterations=2)]
    std, edge = float(bgpx.std()), float(edges.mean()) if edges.size else 0.0
    m.update(clock_bg_std=round(std, 3), clock_bg_edges=round(edge, 3))
    if std > cfg["max_clock_bg_std"]:
        return Verdict(False, f"busy background behind clock (std {std:.2f})", metrics=m)
    if edge > cfg["max_clock_bg_edges"]:
        return Verdict(False, f"cluttered background behind clock (edges {edge:.2f})", metrics=m)

    return Verdict(True, "ok", crop=box, metrics=m)
