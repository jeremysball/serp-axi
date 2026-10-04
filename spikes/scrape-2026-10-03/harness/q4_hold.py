"""Spike (throwaway): Q4, jittered press-and-hold against PerimeterX on zillow.

Uses the 2026-10-02 stealth_new variant on purpose, because it is the one that drew the PX
challenge; the fingerprint-clean browsers were never challenged. Prints one JSON record.
Run under `timeout -s KILL 110`.
"""

import json
import random
import re
import shutil
import time

from patchright.sync_api import sync_playwright

URL = "https://www.zillow.com/homes/for_sale/"
PROF = "profiles/q4_stealth_new"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
PX = re.compile(r"press & hold|access to this page has been denied", re.I)


def body(page):
    return f"{page.title()}\n{page.inner_text('body', timeout=10000)[:2000]}"


def main():
    rng = random.Random()
    rec = {"t0": time.strftime("%H:%M:%S")}
    shutil.rmtree(PROF, ignore_errors=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROF, headless=True, channel="chromium", user_agent=UA,
                                                    args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, wait_until="commit", timeout=30000)
        page.wait_for_timeout(7000)
        text = body(page)
        rec["challenged"] = bool(PX.search(text))
        if rec["challenged"]:
            box = None
            for _ in range(10):  # the hold button renders late
                el = page.locator("#px-captcha")
                if el.count() and (box := el.bounding_box()):
                    break
                page.wait_for_timeout(1000)
            rec["box"] = box
            if box:
                x = box["x"] + box["width"] / 2 + rng.uniform(-15, 15)
                y = box["y"] + box["height"] / 2 + rng.uniform(-5, 5)
                # approach along a few jittered waypoints instead of teleporting
                sx, sy = rng.uniform(100, 400), rng.uniform(100, 300)
                for i in range(1, 16):
                    page.mouse.move(sx + (x - sx) * i / 15 + rng.uniform(-3, 3), sy + (y - sy) * i / 15 + rng.uniform(-3, 3))
                    page.wait_for_timeout(rng.randint(15, 45))
                page.screenshot(path="q4_before.png")
                page.mouse.down()
                shot_at = time.monotonic() + 5
                hold_ms = rng.randint(9000, 12000)
                end = time.monotonic() + hold_ms / 1000
                while time.monotonic() < end:  # tiny tremor while holding
                    page.mouse.move(x + rng.uniform(-1.5, 1.5), y + rng.uniform(-1.5, 1.5))
                    if shot_at and time.monotonic() > shot_at:
                        page.screenshot(path="q4_mid.png")
                        shot_at = None
                    page.wait_for_timeout(rng.randint(80, 200))
                page.mouse.up()
                rec["hold_ms"] = hold_ms
                page.wait_for_timeout(8000)
                text = body(page)
        rec["final_title"] = page.title()[:80]
        rec["still_px"] = bool(PX.search(text))
        rec["chars"] = len(text)
        rec["cookies"] = sorted({c["name"] for c in ctx.cookies() if c["name"].startswith("_px")})
        ctx.close()
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
