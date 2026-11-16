# Depth Life Wallpaper

A new iPhone Lock Screen every morning: an EarthPorn-style landscape whose
peak iOS can layer **over the clock** (Depth Effect), with the
[Life Calendar](https://thelifecalendar.com) year grid on top.

Everything runs on GitHub (Actions + Pages). The phone runs a two-action
Shortcut. No computer is involved after setup.

```
GitHub Actions (02:30 IST daily)
  fetch photos ────────── inbox/ (your uploads) → Unsplash · Pexels · Wikimedia Commons landscapes
  segment subject ─────── BiRefNet (rembg)
  depth checks ────────── subject apex tucks under the clock numerals,
                          8–65% subject area, clean outline, calm clock background
  crop ────────────────── apex at 22.5% of height, ≤1.15× upscale
  compose ─────────────── photo → year grid (front, lower half) → RGB JPEG
  publish ─────────────── gh-pages → https://<user>.github.io/<repo>/wallpaper.jpg
iPhone Shortcut (06:00 daily)
  Get Contents of URL → Set Wallpaper Photo (Lock Screen)
```

Photos that iOS wouldn't layer are discarded and the next candidate is
tried. If nothing passes on a given day, yesterday's photo is reused with
today's grid, so the wallpaper still updates.

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

1. **Secrets** (repo → Settings → Secrets and variables → Actions):
   - `BIRTH_DATE`: `YYYY-MM-DD` (only needed for the life/weeks view)
   - `UNSPLASH_ACCESS_KEY`: from a free app at <https://unsplash.com/oauth/applications>
   - `PEXELS_API_KEY` (optional): free at <https://www.pexels.com/api/>
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

## Photo sources

All of these run in the cloud and return landscapes only: no people,
animals, abstract or macro shots.

| Source | Key | What it pulls |
|---|---|---|
| `inbox/` | none | photos you upload with the GitHub app (e.g. saved from r/EarthPorn); tried first, once each |
| Unsplash | `UNSPLASH_ACCESS_KEY` | landscape searches (peaks, volcanoes, sea stacks, lone trees…), relevance-ranked |
| Pexels | `PEXELS_API_KEY` (free, instant: <https://www.pexels.com/api/>) | the same landscape searches |
| Wikimedia Commons | none | Featured Pictures of landscapes, mountains, rock formations and volcanoes (community-curated) |
| Reddit | `REDDIT_CLIENT_ID/SECRET` | dormant: Reddit blocks servers and requires approval for new API apps |

Sources without a key are skipped silently. Wikimedia needs no key, so
there is always a supply.

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
Unsplash, Pexels and Wikimedia Commons (credited per photo); each day's credit is on the Pages index and in
`status.json`. Fonts: Inter and Noto Sans (OFL).
