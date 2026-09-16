"""Record the demo take in README.md.

Drives the real SPA with Playwright and lets Chrome record the page. Nothing
under src/ is touched: the only injection is a visible cursor, which exists for
the camera and not for the app.

The API behind the page is the repo's own ?mock=1 fixture layer (static/dev-mock.js),
so the run is paced instead of instant and the Review queue carries a conflict with
an identity witness rationale. That makes the take reproducible and offline, and it
is why the README says the clip is demo data rather than a live download.

Needs `pip install playwright` and a Chrome on PATH.

    .venv/bin/python -m muzik.web --demo --port 8791 &
    python3 docs/media/record-demo.py out/

Then cut the dead air out of the raw webm and build the GIF. The take that
shipped was trimmed at both ends and had one stall removed from the middle. It
plays at recorded speed: the dwells in the script are the pacing, and speeding
them up made the whole thing read as a machine driving the UI.

    ffmpeg -i out/*.webm -filter_complex \\
      "[0:v]trim=4.0:27.0,setpts=PTS-STARTPTS[g1];\\
       [0:v]trim=45.2:57.8,setpts=PTS-STARTPTS[g2];\\
       [g1][g2]concat=n=2:v=1[cat];\\
       [cat]fps=12,scale=720:-1:flags=lanczos,split[s0][s1];\\
       [s0]palettegen=max_colors=128:stats_mode=diff[p];\\
       [s1][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \\
      -loop 0 docs/media/clean-muzik-demo.gif
"""

import os
import sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get("MUZIK_DEMO_URL", "http://127.0.0.1:8791") + "/?mock=1"
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else "docs/media/raw"
W, H = 1280, 800

CURSOR = """
(() => {
  const dot = document.createElement('div');
  dot.id = '__cam_cursor';
  dot.style.cssText = [
    'position:fixed','left:0','top:0','width:22px','height:22px',
    'margin:-11px 0 0 -11px','border-radius:50%','pointer-events:none',
    'z-index:2147483647','background:rgba(255,255,255,.92)',
    'box-shadow:0 0 0 2px rgba(0,0,0,.55), 0 0 18px 4px rgba(255,255,255,.35)',
    'transition:transform .1s ease','opacity:0'
  ].join(';');
  const add = () => document.body && document.body.appendChild(dot);
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', add) : add();
  addEventListener('mousemove', (e) => {
    dot.style.opacity = '1';
    dot.style.left = e.clientX + 'px';
    dot.style.top = e.clientY + 'px';
  }, true);
  addEventListener('mousedown', () => { dot.style.transform = 'scale(.6)'; }, true);
  addEventListener('mouseup', () => { dot.style.transform = 'scale(1)'; }, true);
})();
"""


def glide(page, selector, steps=24):
    """Walk the pointer to an element's centre so the click reads on camera."""
    box = page.locator(selector).first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)
    page.wait_for_timeout(220)


def tap(page, selector):
    # Scroll first, then walk the pointer over. Clicking a row the viewport has
    # not settled on cost 16 seconds of dead air in the first take.
    target = page.locator(selector).first
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    glide(page, selector)
    target.click()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", args=["--force-color-profile=srgb", "--font-render-hinting=none"])
    ctx = browser.new_context(
        viewport={"width": W, "height": H},
        device_scale_factor=1,
        record_video_dir=OUTDIR,
        record_video_size={"width": W, "height": H},
        reduced_motion="no-preference",
    )
    ctx.add_init_script(CURSOR)
    page = ctx.new_page()

    # --- 1. the shell, at rest -------------------------------------------
    page.goto(BASE + "#/run", wait_until="networkidle")
    page.wait_for_selector(".run-form")
    page.mouse.move(W * 0.62, H * 0.55, steps=2)
    page.wait_for_timeout(2600)

    # --- 2. paste a Source ------------------------------------------------
    glide(page, "#src-url")
    page.locator("#src-url").click()
    page.wait_for_timeout(300)
    page.locator("#src-url").type(
        "https://www.youtube.com/playlist?list=PLliked-august", delay=55
    )
    page.wait_for_timeout(700)

    # --- 3. it is a playlist, so say so ----------------------------------
    tap(page, "label.switch[for='opt-playlist']")
    page.wait_for_timeout(900)

    # --- 4. run it --------------------------------------------------------
    tap(page, "form.run-form button[type='submit']")
    page.wait_for_timeout(1200)

    # --- 5. watch the batch (mock paces ~1.4s a Track, 5 Tracks) ---------
    page.mouse.move(W * 0.5, H * 0.72, steps=18)
    page.wait_for_selector("text=Done", timeout=25000)
    page.wait_for_timeout(2400)

    # --- 6. the finished board --------------------------------------------
    page.mouse.wheel(0, 260)
    page.wait_for_timeout(1800)
    page.mouse.wheel(0, -260)
    page.wait_for_timeout(600)

    # --- 7. clear the Review queue ----------------------------------------
    tap(page, "nav.nav a[data-route='review']")
    page.wait_for_selector(".review-list")
    page.wait_for_timeout(1600)

    # the conflict: fingerprint against Source, with the witness's rationale
    tap(page, ".review-list li:nth-child(2) .ri-head")
    page.wait_for_timeout(1400)
    page.mouse.wheel(0, 300)
    page.wait_for_timeout(3200)
    page.mouse.wheel(0, 240)
    page.wait_for_timeout(2600)

    # rule on it
    tap(page, ".review-list li.open .d-accept")
    page.wait_for_timeout(2400)

    # --- 8. settings -------------------------------------------------------
    tap(page, "nav.nav a[data-route='settings']")
    page.wait_for_timeout(1800)
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(1600)

    # --- 9. rest on the crest ---------------------------------------------
    tap(page, "nav.nav a[data-route='run']")
    page.mouse.move(W * 0.7, H * 0.5, steps=20)
    page.wait_for_timeout(2200)

    video = page.video.path()
    ctx.close()
    browser.close()
    print(video)
