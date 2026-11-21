"""Record the README walkthrough GIF from the built demo site.

Serves site/ under the GitHub Pages project path, drives Chrome with Playwright through
the main story (inbox -> deal -> cited figure -> discrepancy -> underwriting), and
assembles the frames into assets/walkthrough.gif with ffmpeg.

    python tools/record_walkthrough.py [--deal d03-sorrel-jvc]
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

            page.goto(base + "#/")
            rec.settle(900)
            rec.hold(3.0)

            page.click("a.btn[href='#/inbox']")
            rec.settle()
            rec.hold(3.5)

            page.goto(base + f"#/deal/{args.deal}/memo")
            rec.settle(900)
            rec.hold(3.5)

            cites = page.locator("#tabpanel .cite")
            for i in range(min(2, cites.count())):
                cites.nth(i).click()
                rec.settle(700)
                rec.hold(3.0)

            page.click("#tab-discrepancies")
            rec.settle(700)
            rec.hold(2.5)
            decide = page.locator("[data-decide]").first
            if decide.count():
                decide.click()
                rec.settle(400)
                rec.hold(2.0)
            source = page.get_by_role("button", name="Show cells").first
            if source.count():
                source.click()
                rec.settle(700)
                rec.hold(3.0)

            page.click("#tab-underwriting")
            rec.settle(700)
            rec.hold(3.0)
            page.mouse.wheel(0, 600)
            rec.settle(500)
            rec.hold(3.0)
            browser.close()
        server.shutdown()

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        palette = tmp / "palette.png"
        scale = "fps=10,scale=1024:-1:flags=lanczos"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                        "-vf", f"{scale},palettegen=stats_mode=diff", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                        "-i", str(palette), "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        str(out)], check=True)
        print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {rec.n / FPS:.0f} s)")


if __name__ == "__main__":
    main()
