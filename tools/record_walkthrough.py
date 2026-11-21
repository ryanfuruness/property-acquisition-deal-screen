"""Record the README walkthrough GIF from the built demo site.

Serves site/ under the GitHub Pages project path, drives Chrome with Playwright through
the main story (inbox -> deal -> cited figure -> discrepancy -> underwriting), and
assembles the frames into assets/walkthrough.gif with ffmpeg.

    python tools/record_walkthrough.py [--deal d03-sorrel-jvc] [--width 1280]

Starts on the deal inbox (not the landing page), records at 1280x800 and writes the GIF at full
width so the text stays readable. Run tools/build_site_data.py afterwards so the site picks up the
new duration.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "property-acquisition-deal-screen"
SIZE = {"width": 1280, "height": 800}
FPS = 10


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


class Recorder:
    def __init__(self, page, frames: Path):
        self.page, self.frames, self.n = page, frames, 0

    def hold(self, seconds: float) -> None:
        """Capture one frame and repeat it for the hold time."""
        path = self.frames / f"{self.n:05d}.png"
        self.page.screenshot(path=str(path))
        self.n += 1
        for _ in range(max(0, int(seconds * FPS) - 1)):
            shutil.copy(path, self.frames / f"{self.n:05d}.png")
            self.n += 1

    def settle(self, ms: int = 400) -> None:
        self.page.wait_for_timeout(ms)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deal", default="d03-sorrel-jvc")
    ap.add_argument("--width", type=int, default=1280, help="output width in pixels (1280 = no scaling)")
    ap.add_argument("--out", default=str(ROOT / "assets" / "walkthrough.gif"))
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / PROJECT).symlink_to(ROOT / "site")
        server, port = serve(tmp)
        base = f"http://127.0.0.1:{port}/{PROJECT}/"
        frames = tmp / "frames"
        frames.mkdir()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
            page = browser.new_page(viewport=SIZE, device_scale_factor=1, color_scheme="light")
            rec = Recorder(page, frames)

            # 1. The inbox: the analyst's Monday queue.
            page.goto(base + "#/inbox")
            rec.settle(1000)
            rec.hold(4.0)

            # 2. Open the deal from its row.
            page.click(f"tr[data-href='#/deal/{args.deal}'] .name a")
            rec.settle(1200)
            rec.hold(4.0)

            # 3. Click memo figures: the walk-away price, then a figure from the broker's documents.
            for fact in ("uw.walk_away_price_aed", "om.annual_rent_stated", "rr.in_place_rent_aed", "deal.asking_price_aed"):
                c = page.locator(f'.memo .cite[data-fact="{fact}"]').first
                if c.count() and c.is_visible():
                    c.scroll_into_view_if_needed()
                    c.click()
                    rec.settle(900)
                    rec.hold(3.5)

            # 4. Discrepancies: open a source, then override one with a reason.
            page.click("#tab-discrepancies")
            rec.settle(800)
            rec.hold(3.0)
            src = page.locator(".src .btn").first
            if src.count():
                src.click()
                rec.settle(900)
                rec.hold(3.5)
            ov = page.locator("[data-decide='info_requested']").first
            if ov.count():
                ov.click()
                rec.settle(300)
                page.keyboard.type("Asked the broker for the Ejari export and vacancy list", delay=25)
                rec.hold(1.5)
                page.locator("[data-save]").first.click()
                rec.settle(400)
                rec.hold(2.5)

            # 5. Underwriting: unlevered returns first, then the walk-away price on the house view.
            page.click("#tab-underwriting")
            rec.settle(900)
            rec.hold(3.5)
            wa = page.locator("#walk-away")
            if wa.count():
                wa.scroll_into_view_if_needed()
                page.mouse.wheel(0, -60)
                rec.settle(500)
                rec.hold(4.0)
            browser.close()
        server.shutdown()

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        palette = tmp / "palette.png"
        scale = f"fps={FPS},scale={args.width}:-1:flags=lanczos"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                        "-vf", f"{scale},palettegen=stats_mode=diff", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                        "-i", str(palette), "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        str(out)], check=True)
        print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {rec.n / FPS:.0f} s)")


if __name__ == "__main__":
    main()
