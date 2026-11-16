"""Life Calendar grid, matching the thelifecalendar.com design.

Geometry and colours were measured from that service's own render at
1320x2868 (iPhone 16/17 Pro Max): 4,680 weeks (90 years x 52) laid out in
55 columns on a 21 px pitch with 13 px dots, grid top at y=737, caption
"<pct>% to <lifespan>" in Inter Regular #888888 under the grid.
Other device widths scale proportionally from that reference.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REF_W, REF_H = 1320, 2868
REF = dict(cols=55, pitch=21, dot=13, grid_top=737 - 10.5, caption_baseline=2579, caption_size=30)

FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "NotoSans-Regular.ttf"


@dataclass(frozen=True)
class GridStyle:
    # Future dots and caption are white with alpha: on the reference #1A1A1A
    # background they come out exactly #404040 / #888888, and over a photo
    # they lighten whatever is behind them instead of punching grey holes.
    lived: tuple[int, int, int, int] = (255, 255, 255, 255)
    future: tuple[int, int, int, int] = (255, 255, 255, 42)
    current: tuple[int, int, int, int] = (245, 107, 63, 255)
    caption: tuple[int, int, int, int] = (255, 255, 255, 122)
    show_caption: bool = True


def life_stats(birth: date, today: date, lifespan_years: int) -> tuple[int, int, float]:
    days = (today - birth).days
    # Calendar weeks, Monday-aligned (matches thelifecalendar.com): the dot
    # advances every Monday rather than on your birth weekday.
    monday = lambda d: d.toordinal() - d.weekday()  # noqa: E731
    weeks_lived = max(0, (monday(today) - monday(birth)) // 7)
    total_weeks = lifespan_years * 52
    pct = max(0.0, min(100.0, days / (lifespan_years * 365.25) * 100))
    return weeks_lived, total_weeks, pct


def render_grid_overlay(
    size: tuple[int, int],
    birth: date,
    today: date,
    lifespan_years: int = 90,
    style: GridStyle = GridStyle(),
) -> Image.Image:
    """Transparent RGBA layer holding only the dots and caption."""
    W, H = size
    k = W / REF_W
    cols = REF["cols"]
    pitch = REF["pitch"] * k
    dot = max(3, round(REF["dot"] * k))
    r_lo = (dot - 1) // 2
    r_hi = dot - 1 - r_lo
    grid_w = cols * pitch
    left = (W - grid_w) / 2
    top = REF["grid_top"] * (H / REF_H)

    weeks_lived, total, pct = life_stats(birth, today, lifespan_years)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rows = 0
    for i in range(total):
        r, c = divmod(i, cols)
        rows = r + 1
        cx = int(left + c * pitch + pitch / 2)
        cy = int(top + r * pitch + pitch / 2)
        if i < weeks_lived:
            fill = style.lived
        elif i == weeks_lived:
            fill = style.current
        else:
            fill = style.future
        d.ellipse((cx - r_lo, cy - r_lo, cx + r_hi, cy + r_hi), fill=fill)

    if style.show_caption:
        font = ImageFont.truetype(str(FONT_PATH), round(REF["caption_size"] * k))
        baseline = top + rows * pitch + (REF["caption_baseline"] - (REF["grid_top"] + 86 * REF["pitch"])) * k
        d.text((W / 2, baseline), f"{pct:.1f}% to {lifespan_years}", font=font, fill=style.caption, anchor="ms")
    return layer
