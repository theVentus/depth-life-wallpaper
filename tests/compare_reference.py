"""Pixel-compare our grid with a thelifecalendar.com render.

usage: python tests/compare_reference.py REF.png BIRTH(YYYY-MM-DD) TODAY(YYYY-MM-DD)
"""
import sys
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wallpaper.grid import render_grid_overlay  # noqa: E402

ref = Image.open(sys.argv[1]).convert("RGB")
birth, today = date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3])
bg = Image.new("RGBA", ref.size, (26, 26, 26, 255))
ours = Image.alpha_composite(bg, render_grid_overlay(ref.size, birth, today)).convert("RGB")
out = Path(sys.argv[1]).with_suffix(".ours.png")
ours.save(out)

a, b = np.asarray(ref).astype(int), np.asarray(ours).astype(int)
diff = np.abs(a - b).sum(2)
H = a.shape[0]
grid_rows = diff[: int(H * 0.885)]
cap_rows = diff[int(H * 0.885):]
print(f"grid area: {np.count_nonzero(grid_rows > 30)} px differ (of {grid_rows.size})")
print(f"caption area: {np.count_nonzero(cap_rows > 30)} px differ, max {cap_rows.max()}")
Image.fromarray((np.clip(diff, 0, 255)).astype("uint8")).save(Path(sys.argv[1]).with_suffix(".diff.png"))
print("wrote", out)
