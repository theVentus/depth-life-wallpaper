# Depth Life Wallpaper

A new iPhone Lock Screen every morning: a popular photo whose subject iOS
can layer **over the clock** (Depth Effect), with the
[Life Calendar](https://thelifecalendar.com) week grid sandwiched between
the photo and the subject.

Everything runs on GitHub (Actions + Pages). The phone runs a two-action
Shortcut. No computer is involved after setup.

```
GitHub Actions (02:30 IST daily)
  fetch photos ────────── inbox/ drop folder → Unsplash landscape searches → (Reddit EarthPorn family, if keys)
  segment subject ─────── BiRefNet (rembg)
  depth checks ────────── subject apex tucks under the clock numerals,
                          8–65% subject area, clean outline, calm clock background
  crop ────────────────── apex at 22.5% of height, ≤1.15× upscale
  compose ─────────────── photo → Life Calendar grid → subject cutout → RGB JPEG
  publish ─────────────── gh-pages → https://<user>.github.io/<repo>/wallpaper.jpg
iPhone Shortcut (06:00 daily)
  Get Contents of URL → Set Wallpaper Photo (Lock Screen)
```

Photos that iOS wouldn't layer are discarded and the next candidate is
tried. If nothing passes on a given day, yesterday's photo is reused with
today's grid, so the wallpaper still updates.

## The grid

The grid reproduces thelifecalendar.com's life calendar. Geometry and
colours were measured from its own render and checked pixel-for-pixel
(`tests/compare_reference.py`):

- 90 years × 52 weeks = 4,680 dots, in 55 columns on a 21 px pitch, 13 px dots
- lived weeks white, future weeks faint white, the current week orange `#F56B3F`
- weeks are counted Monday to Monday, so the dot moves on each Monday
- caption: `NN.N% to 90` (Noto Sans)

## One-time setup

1. **Secrets** (repo → Settings → Secrets and variables → Actions):
   - `BIRTH_DATE`: `YYYY-MM-DD`
   - `UNSPLASH_ACCESS_KEY`: from a free app at <https://unsplash.com/oauth/applications>
   - `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (optional): only if Reddit
     approves an API app for you. Reddit has blocked anonymous access since
     2026 and requires approval for new apps, so Reddit stays off without
     these.
2. **Pages**: Settings → Pages → Deploy from branch → `gh-pages` / root.
   The branch appears after the first run.
3. **First run**: Actions → Daily wallpaper → Run workflow.

## iPhone setup

1. Lock Screen: long-press → **+** → Photos → pick any photo → Add. This is the
   slot the automation will overwrite. Keep the clock at its default size
   (don't stretch it) and add **no widgets below the clock**. Either one
   turns Depth Effect off.
2. Shortcuts → Automation → **+** → Time of Day → 06:00, Daily →
   **Run Immediately**, Notify When Run off → New Blank Automation:
   1. **Get Contents of URL**: `https://<user>.github.io/<repo>/wallpaper.jpg`
   2. **Set Wallpaper Photo**: Lock Screen. Tap the arrow and turn off
      **Show Preview** and **Crop to Subject**.
3. Run it once by hand, then long-press the Lock Screen → Customize and
   check that Depth Effect is on (⋯ menu).

## Adding your own photos

Saw a great r/EarthPorn shot? Save it on your phone, then in the GitHub app
open the repo → `inbox/` → upload it. The next run tries inbox photos before
anything else, with the same depth checks. Each photo is tried once; the
Actions log says if one was rejected and why.

## Tuning

All thresholds are in `config.toml`: device, timezone, lifespan, photo
topics and subreddits, and the depth checks. Edit it on github.com and the
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
Unsplash and Reddit; each day's credit is on the Pages index and in
`status.json`. Fonts: Noto Sans (OFL).
