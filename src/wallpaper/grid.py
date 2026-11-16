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


# ---------------------------------------------------------------------------
# Year Calendar ("Days" layout), measured from thelifecalendar.com's
# /days render at 1320x2868: 15 columns, 62 px pitch, 37 px dots, first dot
# centre (226, 834); caption "<n>d left · <p>%" in Inter 33 px, -1 px
# tracking, orange count + grey percentage, baseline 2438.
YEAR_REF = dict(cols=15, pitch=62, dot=37, left=195, top=803, caption_baseline=2438,
                caption_size=33, tracking=-1, dot_gap=14)
INTER_PATH = FONT_PATH.with_name("Inter-Regular.ttf")


def year_stats(today: date) -> tuple[int, int, int, int]:
    """(index of today, days in year, days left after today, percent done)."""
    start = date(today.year, 1, 1)
    n_days = (date(today.year + 1, 1, 1) - start).days
    idx = (today - start).days
    left = n_days - idx - 1
    pct = (idx + 1) * 100 // n_days
    return idx, n_days, left, pct


def render_year_overlay(
    size: tuple[int, int],
    today: date,
    style: GridStyle = GridStyle(),
    scale: float = 1.0,
    caption_baseline: float | None = None,
    shadow: bool = False,
) -> Image.Image:
    """Transparent RGBA layer with the year-in-days grid and caption.

    scale shrinks the whole block (dots, pitch, caption) around the centre
    line; caption_baseline (fraction of height) moves the block vertically
    with the caption baseline as the anchor. Defaults reproduce the
    reference render exactly.
    """
    W, H = size
    k = W / REF_W * scale
    R = YEAR_REF
    pitch = R["pitch"] * k
    dot = max(3, round(R["dot"] * k))
    r_lo = (dot - 1) // 2
    r_hi = dot - 1 - r_lo
    base = (caption_baseline * H) if caption_baseline is not None else R["caption_baseline"] * H / REF_H
    top = base - (R["caption_baseline"] - R["top"]) * k
    left = W / 2 - R["cols"] * pitch / 2

    idx_today, n_days, left_days, pct = year_stats(today)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(n_days):
        r, c = divmod(i, R["cols"])
        cx = int(left + c * pitch + pitch / 2)
        cy = int(top + r * pitch + pitch / 2)
        fill = style.lived if i < idx_today else style.current if i == idx_today else style.future
        d.ellipse((cx - r_lo, cy - r_lo, cx + r_hi, cy + r_hi), fill=fill)

    if style.show_caption:
        f = ImageFont.truetype(str(INTER_PATH), round(R["caption_size"] * k))
        tr = R["tracking"] * k
        gap = R["dot_gap"] * k
        a, b = f"{left_days}d left", f"{pct}%"
        wid = lambda s: sum(f.getlength(ch) + tr for ch in s) - tr  # noqa: E731
        x = W / 2 - (wid(a) + 2 * gap + f.getlength("·") + wid(b)) / 2 + k

        def run(x, s, fill):
            for ch in s:
                d.text((x, base), ch, font=f, fill=fill, anchor="ls")
                x += f.getlength(ch) + tr
            return x - tr

        x = run(x, a, style.current) + gap
        x = run(x, "·", style.caption) + gap
        run(x, b, style.caption)

    if shadow:
        from PIL import ImageFilter
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(max(2, dot * 0.35)))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh.putalpha(alpha.point(lambda v: v * 95 // 255))
        layer = Image.alpha_composite(sh, layer)
    return layer
