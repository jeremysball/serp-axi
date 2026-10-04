"""Spike (throwaway): scrape A/B across browser variants. Logs every fetch to JSONL.

Run under xvfb-run so the headed variants have a display.
"""

import json
import re
import shutil
import sys
import time

URLS = [
    "https://www.reddit.com/r/linux/",
    "https://stackoverflow.com/questions/231767",
    "https://medium.com/@karpathy/software-2-0-a64152b37c35",
    "https://www.npmjs.com/package/playwright",
    "https://www.g2.com/products/slack/reviews",
    "https://www.indeed.com/q-software-engineer-jobs.html",
    "https://www.glassdoor.com/Reviews/index.htm",
    "https://www.zillow.com/homes/for_sale/",
    "https://www.walmart.com/ip/5253396052",
    "https://www.etsy.com/search?q=mug",
    "https://www.nytimes.com/section/technology",
    "https://www.bloomberg.com/technology",
    "https://www.ticketmaster.com/",
    "https://www.linkedin.com/jobs/",
    "https://x.com/github",
    "https://nowsecure.nl/",
]
FINGERPRINT_URL = "https://bot.sannysoft.com/"

import os as _os
if _os.environ.get("URLSET"):
    URLS = [u["url"] for u in json.load(open(_os.environ["URLSET"]))]

BLOCK_MARKERS = re.compile(
    r"just a moment|attention required|verify you are human|are you a robot|robot or human|"
    r"captcha|access denied|pardon our interruption|unusual traffic|request blocked|"
    r"blocked|enable javascript and cookies|checking your browser|px-captcha|datadome|"
    r"you've been blocked|press & hold|security check",
    re.I,
)


def classify(status, title, text):
    hay = f"{title}\n{text[:4000]}"
    m = BLOCK_MARKERS.search(hay)
    if status and status >= 400:
        return "blocked", f"http {status}" + (f" + '{m.group(0)}'" if m else "")
    if m and len(text) < 3000:
        return "blocked", f"marker '{m.group(0)}', short page"
    if len(text) < 300:
        return "thin", f"{len(text)} chars"
    return "ok", f"{len(text)} chars" + (f", marker '{m.group(0)}' in long page" if m else "")


def launch(variant, pw):
    prof = f"./profiles/{variant}"
    if variant == "headless_shell":
        b = pw.chromium.launch(headless=True)
        return b, b.new_context(), None
    if variant == "headless_new":
        b = pw.chromium.launch(headless=True, channel="chromium")
        return b, b.new_context(), None
    if variant in ("persistent_headed", "patchright_headed"):
        ctx = pw.chromium.launch_persistent_context(prof, headless=False, no_viewport=True)
        return None, ctx, prof
    if variant in ("persistent_new", "patchright_new"):
        # headed Chrome stalls after connecting to Xvfb on this box; full-Chrome new headless instead
        ctx = pw.chromium.launch_persistent_context(prof, headless=True, channel="chromium")
        return None, ctx, prof
    if variant == "stealth_new":
        # L1/L5: drop the HeadlessChrome UA token and the webdriver flag
        ctx = pw.chromium.launch_persistent_context(
            prof, headless=True, channel="chromium",
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        )
        return None, ctx, prof
    raise ValueError(variant)


def run(variant):
    if variant.startswith("patchright"):
        from patchright.sync_api import sync_playwright
    else:
        from playwright.sync_api import sync_playwright
    out = open(f"./scrape_{variant}.jsonl", "w")
    with sync_playwright() as pw:
        t0 = time.monotonic()
        browser, ctx, _ = launch(variant, pw)
        page = ctx.new_page()
        page.goto("about:blank")
        cold_ms = int((time.monotonic() - t0) * 1000)
        out.write(json.dumps({"variant": variant, "cold_start_ms": cold_ms}) + "\n")
        print(variant, "cold_start_ms", cold_ms, flush=True)

        try:
            page.goto(FINGERPRINT_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            fp = page.evaluate(
            """() => ({webdriver: navigator.webdriver, ua: navigator.userAgent,
                 failed: [...document.querySelectorAll('td.failed')].map(td => td.parentElement.cells[0].innerText.trim())})"""
            )
        except Exception as ex:
            fp = {"webdriver": None, "failed": None, "err": f"{type(ex).__name__}: {str(ex)[:160]}"}
        out.write(json.dumps({"variant": variant, "fingerprint": fp}) + "\n")
        print(variant, "fingerprint webdriver=", fp["webdriver"], "failed=", fp["failed"], flush=True)

        for url in URLS:
            t1 = time.monotonic()
            status, title, text, err = None, "", "", None
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status = resp.status if resp else None
                page.wait_for_timeout(4000)  # let challenges / SPAs settle
                title = page.title()
                text = page.inner_text("body")
            except Exception as ex:
                err = f"{type(ex).__name__}: {str(ex)[:160]}"
            verdict, why = ("error", err) if err else classify(status, title, text)
            rec = {"variant": variant, "url": url, "status": status, "title": title[:120],
                   "chars": len(text), "verdict": verdict, "why": why,
                   "head": re.sub(r"\s+", " ", text[:240]), "ms": int((time.monotonic() - t1) * 1000)}
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(variant, verdict, url, "|", why, "|", title[:60], flush=True)
        ctx.close()
        if browser:
            browser.close()


if __name__ == "__main__":
    shutil.rmtree("./profiles", ignore_errors=True)
    failed = []
    for v in sys.argv[1:]:
        try:
            run(v)
        except Exception as ex:
            print(v, "VARIANT CRASHED", type(ex).__name__, str(ex)[:200], flush=True)
            failed.append(v)
    sys.exit(1 if failed else 0)
