"""Pixel-compare our year grid with thelifecalendar.com's /days render.

usage: python tests/compare_year.py REF.png TODAY(YYYY-MM-DD)
"""
import sys
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wallpaper.grid import render_year_overlay  # noqa: E402

ref = Image.open(sys.argv[1]).convert("RGB")
bg = Image.new("RGBA", ref.size, (26, 26, 26, 255))
ours = Image.alpha_composite(bg, render_year_overlay(ref.size, date.fromisoformat(sys.argv[2]))).convert("RGB")
a, b = np.asarray(ref).astype(int), np.asarray(ours).astype(int)
diff = np.abs(a - b).sum(2) > 30
print(f"grid: {diff[:2380].sum()} px differ; caption: {diff[2380:].sum()} px differ")
Image.fromarray(np.hstack([a[2380:2460, 500:820], b[2380:2460, 500:820]]).astype("uint8")).resize((1280, 160)).save(Path(sys.argv[1]).with_suffix(".cap.png"))
