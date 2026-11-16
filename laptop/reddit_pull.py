"""Once-a-day Reddit pull for the wallpaper inbox (runs on your laptop).

Opens the EarthPorn-family "hot" pages in Microsoft Edge (your own
connection, a dedicated browser profile kept in laptop/.browser-profile),
saves tall high-res images into ../inbox/, then commits and pushes them so
the cloud run picks them up. If Reddit shows a CAPTCHA, a login wall or a
block page, it stops for the day; it never tries to get around one.

First time: python laptop/reddit_pull.py --login   (sign in to Reddit in the window, then close it)
Daily:      python laptop/reddit_pull.py [--max-new 6] [--no-push]
"""
from __future__ import annotations

import argparse
import io
import json
import random
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INBOX = ROOT / "inbox"
STATE = HERE / "pulled.json"           # ids already saved, so nothing repeats
PROFILE = HERE / ".browser-profile"    # never committed (see .gitignore)
SUBS = ["EarthPorn", "SkyPorn", "WaterPorn", "AutumnPorn", "WinterPorn", "DesertPorn"]
MIN_W, MIN_H = 1150, 2500              # enough for 1320x2868 at <=1.15x upscale
BLOCK_MARKERS = ("captcha", "blocked", "whoa there", "prove you're human", "log in to continue")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ids": [], "last_run": None}


def posts_from_page(page, sub: str) -> list[dict] | None:
    page.goto(f"https://old.reddit.com/r/{sub}/hot/", wait_until="domcontentloaded", timeout=45000)
    text = (page.title() + " " + page.inner_text("body")[:2000]).lower()
    if "/login" in page.url:
        return "login"
    if any(m in text for m in BLOCK_MARKERS) or not page.query_selector("#siteTable"):
        return None
    return page.eval_on_selector_all(
        "#siteTable > .thing.link:not(.stickied):not(.promoted)",
        """els => els.map(e => ({id: e.dataset.fullname, url: e.dataset.url,
             title: (e.querySelector('a.title')||{}).textContent || '',
             permalink: e.dataset.permalink, score: +e.dataset.score || 0,
             nsfw: e.classList.contains('over18')}))""",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new", type=int, default=6, help="images to save per run")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--login", action="store_true", help="open Reddit so you can sign in once")
    ap.add_argument("--force", action="store_true", help="run even if it already ran today")
    args = ap.parse_args()

    state = load_state()
    if args.login:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=False, no_viewport=True)
            pg = ctx.new_page(); pg.goto("https://old.reddit.com/login/")
            print("Sign in to Reddit in the Edge window, then close the window.")
            pg.wait_for_event("close", timeout=0)
            ctx.close()
        return 0
    if state.get("last_run") == date.today().isoformat() and not args.force:
        print("already ran today")
        return 0
    seen = set(state["ids"])
    INBOX.mkdir(exist_ok=True)

    from playwright.sync_api import sync_playwright

    saved: list[Path] = []
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), channel="msedge", headless=False, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for sub in random.sample(SUBS, len(SUBS)):
            if len(saved) >= args.max_new:
                break
            posts = posts_from_page(page, sub)
            if posts == "login":
                print("Not signed in to Reddit - run: python laptop/reddit_pull.py --login")
                break
            if posts is None:
                print(f"r/{sub}: Reddit showed a block/CAPTCHA/login page - stopping for today")
                break
            posts.sort(key=lambda p: p["score"], reverse=True)
            for p in posts:
                if len(saved) >= args.max_new:
                    break
                url = (p.get("url") or "").split("?")[0]
                if p["nsfw"] or p["id"] in seen or not url.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                seen.add(p["id"])
                r = ctx.request.get(url, timeout=60000)
                if not r.ok:
                    continue
                try:
                    im = Image.open(io.BytesIO(r.body()))
                    w, h = im.size
                except OSError:
                    continue
                if w < MIN_W or h < MIN_H or h < w * 1.1:
                    continue  # too small, or landscape-oriented (would need a heavy crop)
                out = INBOX / f"reddit_{sub}_{p['id'].split('_')[-1]}.jpg"
                # ~1.5 MB JPEG at 3200 px tall: plenty for 2868 output, light on the repo.
                im = im.convert("RGB")
                if im.height > 3200:
                    im = im.resize((round(im.width * 3200 / im.height), 3200), Image.LANCZOS)
                im.save(out, "JPEG", quality=88, optimize=True)
                (out.with_suffix(".json")).write_text(json.dumps(
                    {"source": f"reddit/r/{sub}", "title": p["title"].strip(),
                     "page_url": "https://www.reddit.com" + (p.get("permalink") or "")}, indent=1), encoding="utf-8")
                saved.append(out)
                print(f"saved {out.name} ({w}x{h}) - {p['title'][:60]}")
            time.sleep(random.uniform(3, 8))  # browse like a person, not a crawler
        ctx.close()

    state["ids"] = list(seen)[-5000:]
    state["last_run"] = date.today().isoformat()
    STATE.write_text(json.dumps(state), encoding="utf-8")
    print(f"{len(saved)} new image(s) in inbox/")

    if not args.no_push and (ROOT / ".git").exists() and any(INBOX.glob("reddit_*.jpg")):
        push_inbox_branch()
    return 0


def git(*a: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=cwd, check=check, capture_output=True, text=True)


def push_inbox_branch() -> None:
    """Merge local inbox/reddit_* into the remote `inbox` branch as ONE orphan
    commit (force-replaced each time), so photos never pile up in git history.
    The cloud run removes photos it has tried from that branch."""
    import shutil
    import tempfile

    remote = git("remote", "get-url", "origin", cwd=ROOT).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        git("init", "-q", "-b", "inbox", cwd=work)
        git("remote", "add", "origin", remote, cwd=work)
        sha = git("ls-remote", "--heads", "origin", "inbox", cwd=work).stdout.split("\t")[0].strip()
        if sha:
            git("fetch", "-q", "--depth", "1", "origin", "inbox", cwd=work)
            git("checkout", "-q", "FETCH_HEAD", "--", ".", cwd=work)
        mine = sorted(INBOX.glob("reddit_*.jpg"))
        for f in mine:
            shutil.copy2(f, work / f.name)
            if f.with_suffix(".json").exists():
                shutil.copy2(f.with_suffix(".json"), work / f.with_suffix(".json").name)
        git("add", "-A", cwd=work)
        git("-c", "user.name=reddit-pull", "-c", "user.email=reddit-pull@localhost",
            "commit", "-q", "--allow-empty", "-m", f"inbox {date.today()}", cwd=work)
        lease = f"--force-with-lease=inbox:{sha}" if sha else "--force-with-lease=inbox:"
        r = git("push", "-q", lease, "origin", "HEAD:inbox", cwd=work, check=False)
    if r.returncode == 0:
        for f in mine:  # handed over to the cloud; keep the laptop folder empty
            f.unlink(missing_ok=True)
            f.with_suffix(".json").unlink(missing_ok=True)
        print(f"pushed {len(mine)} photo(s) to the inbox branch")
    else:
        print("push failed - photos stay in inbox/ and go up next run:", r.stderr.strip()[:200])


if __name__ == "__main__":
    sys.exit(main())
