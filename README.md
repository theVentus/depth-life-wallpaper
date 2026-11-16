# Depth Life Wallpaper

A fresh iPhone Lock Screen every time the Shortcut runs: mostly dark,
EarthPorn-style landscapes and space imagery (real and artistic renders)
whose subject iOS can layer **over the clock** (Depth Effect), with the
[Life Calendar](https://thelifecalendar.com) year grid on top.

Everything runs on GitHub (Actions + Pages). The phone runs a two-action
Shortcut. No computer is involved after setup.

```
GitHub Actions (02:30 IST daily)
  fetch photos ────────── inbox/ → Unsplash · Pexels · Wikimedia · NASA (landscapes ~70%, space ~30%)
  segment subject ─────── BiRefNet (rembg)
  depth checks ────────── subject apex tucks under the clock numerals,
                          8–65% subject area, clean outline, calm clock background
  crop ────────────────── apex at 22.5% of height, ≤1.15× upscale
  compose ─────────────── photo → year grid (front, lower half) → RGB JPEG
  pool ────────────────── 8 wallpapers, at least 75% dark → gh-pages/w/1.jpg … w/8.jpg
iPhone Shortcut (any time it runs)
  Random Number 1–8 → Get Contents of URL (…/w/N.jpg) → Set Wallpaper Photo
```

Photos that iOS wouldn't layer are discarded and the next candidate is
tried. If fewer than 8 pass on a given night, the pool is topped up with
yesterday's photos, re-rendered with today's grid.

## The grid

thelifecalendar.com's **Year Calendar** ("Days" layout), reproduced from
its own render and checked pixel-for-pixel (`tests/compare_year.py`):

- 365 dots (366 in leap years) in 15 columns: past days white, today
  orange `#F56B3F`, future days faint
- caption `44d left · 87%` (Inter), with the count in orange
- drawn **in front of** the photo, scaled to 0.68 and anchored low (caption
  at 86% of the height), so it is always fully visible and stays clear of
  the clock and the peak behind it. Change `[grid]` in `config.toml` to
  adjust: `scale = 1.0` is their exact size, and `view = "life"` switches to
  the 90-year weeks grid.

## One-time setup

Nothing is required: pushing to `main` starts the first run, and Wikimedia
Commons needs no key. Optional extras (repo → Settings → Secrets and
variables → Actions):

- `UNSPLASH_ACCESS_KEY`: free app at <https://unsplash.com/oauth/applications>
- `PEXELS_API_KEY`: free at <https://www.pexels.com/api/>
- `BIRTH_DATE` (`YYYY-MM-DD`): only for `view = "life"`

GitHub Pages is optional too. The phone reads the image straight from the
`gh-pages` branch. If you turn Pages on (Settings → Pages → `gh-pages`), you
also get a small credits page at `https://<user>.github.io/<repo>/`.

## iPhone setup

1. Lock Screen: long-press → **+** → Photos → any photo → Add. Keep the
   clock at its default size and add **no widgets below the clock**.
2. Shortcuts → Automation → **+** → Time of Day → 06:00, Daily →
   **Run Immediately**, Notify When Run off → New Blank Automation:
   1. **Random Number**: Minimum 1, Maximum 8
   2. **Get Contents of URL**:
      `https://raw.githubusercontent.com/<user>/<repo>/gh-pages/w/` + the
      **Random Number** variable + `.jpg`
   3. **Set Wallpaper Photo**: Lock Screen. Turn off **Show Preview** and
      **Crop to Subject**.
3. Run it whenever you want a different wallpaper: each run picks one of
   today's 8 at random. Add more Time of Day automations if you want it to
   change through the day.

## Photo sources

No people, animals, flowers or close-ups. Landscapes also exclude
abstract art; space allows artistic renders.

| Source | Key | Landscapes | Space |
|---|---|---|---|
| `inbox/` | none | your uploads, tried first | – |
| Unsplash | `UNSPLASH_ACCESS_KEY` | night / moody peak searches | planets, moon, launches, space art |
| Pexels | `PEXELS_API_KEY` | same searches | same searches |
| Wikimedia Commons | none | Featured Pictures: landscapes, mountains, volcanoes, glaciers, coasts | Featured Pictures: astronomy, the Moon, planets |
| NASA Image Library | none | – | mission imagery and artist's concepts |
| Reddit | approved keys only | dormant | – |

Darkness: Unsplash and Pexels report each photo's average colour, so very
bright photos are dropped before downloading. Every accepted crop is then
measured, and at least 75% of the pool must fall below `dark_luma`.

## Tuning

All thresholds are in `config.toml`: device, timezone, grid placement, photo
searches and categories, and the depth checks. Edit it on github.com and the
next run picks it up. To refresh only the grid, use Run workflow with
"grid only" ticked.

Local preview (optional):

```
pip install -r requirements.txt
cd src && python -m wallpaper.main --birth-date 2001-05-19 --site ../site --debug ../debug
```

`debug/` gets a preview of every accepted candidate (with the clock box
drawn on) and a thumbnail of every rejected one, named by the reason it
was rejected.

## Credits

Grid design: thelifecalendar.com by @luismbat and @joao_batalha. Photos:
Unsplash, Pexels, Wikimedia Commons and NASA (credited per photo in
`status.json` and on the Pages index). Fonts: Inter and Noto Sans (OFL).
