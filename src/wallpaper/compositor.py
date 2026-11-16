"""Background -> Life Calendar grid -> foreground subject, exported as RGB JPEG."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .device import Device
from .grid import GridStyle, render_grid_overlay, render_year_overlay


def make_layers(img: Image.Image, matte: np.ndarray, box, dev: Device) -> tuple[Image.Image, Image.Image]:
    """Crop/resize the photo and its matte to the device; return (bg RGB, fg RGBA)."""
    size = (dev.width, dev.height)
    bg = img.crop(box).resize(size, Image.LANCZOS)
    a = Image.fromarray((matte * 255).astype(np.uint8)).crop(box).resize(size, Image.BILINEAR)
    fg = bg.convert("RGBA")
    fg.putalpha(a)
    return bg, fg


def composite(bg: Image.Image, fg: Image.Image, birth: date, today: date, lifespan: int, style: GridStyle,
              grid_cfg: dict | None = None) -> Image.Image:
    g = grid_cfg or {}
    canvas = bg.convert("RGBA")
    if g.get("view", "year") == "year":
        overlay = render_year_overlay(canvas.size, today, style, scale=g.get("scale", 1.0),
                                      caption_baseline=g.get("caption_baseline"), shadow=g.get("shadow", False))
    else:
        overlay = render_grid_overlay(canvas.size, birth, today, lifespan, style)
    if g.get("layer", "front") == "behind":
        # photo -> grid -> subject cutout: the subject hides part of the grid
        canvas = Image.alpha_composite(canvas, overlay)
        canvas = Image.alpha_composite(canvas, fg)
    else:
        # photo -> grid: grid always fully visible; it sits well below the
        # clock, so iOS's own subject/clock layering is unaffected
        canvas = Image.alpha_composite(canvas, overlay)
    # iOS only offers Depth Effect on real photos: flat RGB JPEG, no alpha.
    return canvas.convert("RGB")


def save_jpeg(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=93, subsampling=0, optimize=True, progressive=False)


def debug_preview(final: Image.Image, dev: Device, note: str = "") -> Image.Image:
    """Final image with the clock box and apex band drawn on, for tuning."""
    im = final.copy()
    d = ImageDraw.Draw(im)
    W, H = im.size
    d.rectangle((dev.clock_x0 * W, dev.clock_top * H, dev.clock_x1 * W, dev.clock_bottom * H), outline=(0, 255, 255), width=4)
    d.text((dev.clock_x0 * W + 10, dev.clock_top * H + 10), "12:34", fill=(0, 255, 255), font_size=int(dev.clock_h * H * 0.8))
    if note:
        d.text((30, H - 80), note, fill=(255, 255, 0), font_size=36)
    return im.resize((W // 2, H // 2))
