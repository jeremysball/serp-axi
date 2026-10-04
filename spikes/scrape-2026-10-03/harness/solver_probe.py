"""Spike (throwaway): challenge-solver probes. One (variant, url) per subprocess, SIGKILL at 75s.

Usage:   .venv/bin/python solver_probe.py <out.jsonl> <variant> [url...]   (default: hostile 16)
Child:   solver_probe.py --one <variant> <url>
Variants: camoufox (headless), camoufox_virtual (Xvfb), zendriver (new headless Chromium),\nzendriver_headed (headed Chromium on Xvfb), plus _cf variants that click the CF checkbox
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "spike-2026-10-02"))
from scrape_probe import URLS, classify  # noqa: E402

HARD_KILL_S = 75
SETTLE_S = 25  # Q1 falsifier window is 20s; give 5s of slack for load
PROFILES = os.environ.get("PROBE_PROFILES") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
CHALLENGE = re.compile(r"just a moment|attention required|checking your browser|press & hold|"
                       r"verify you are human|prove your humanity|robot or human", re.I)


KEEP = ("cf_clearance", "_px3", "_pxhd", "datadome")


def site_cookies(names_domains, url):
    # H3: the persistent profile holds every site's cookies; keep only the target's
    host = re.sub(r"^www\.", "", url.split("/")[2])
    base = ".".join(host.split(".")[-2:])
    return sorted({n for n, d in names_domains if n in KEEP and d.lstrip(".").endswith(base)})


def clear_locks(profile):
    # H4: a SIGKILLed browser leaves its profile lock behind; the next launch stalls on it
    for name in ("lock", ".parentlock", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.unlink(os.path.join(profile, name))
        except FileNotFoundError:
            pass


def snapshot(title, text):
    return {"title": title[:120], "chars": len(text), "head": re.sub(r"\s+", " ", text[:240])}


def run_camoufox(variant, url):
    from camoufox.sync_api import Camoufox
    headless = "virtual" if variant == "camoufox_virtual" else True
    timeline, rec = [], {}
    with Camoufox(headless=headless, persistent_context=True,
                  user_data_dir=os.path.join(PROFILES, variant), humanize=True) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        t0 = time.monotonic()
        resp = page.goto(url, wait_until="commit", timeout=30000)
        rec["status"] = resp.status if resp else None
        title = text = ""
        while time.monotonic() - t0 < SETTLE_S:
            page.wait_for_timeout(2500)
            try:
                title, text = page.title(), page.inner_text("body", timeout=5000)
            except Exception as ex:  # navigation mid-read after a challenge clears
                timeline.append({"t": round(time.monotonic() - t0, 1), "err": type(ex).__name__})
                continue
            timeline.append({"t": round(time.monotonic() - t0, 1), "title": title[:60], "chars": len(text)})
            if not CHALLENGE.search(f"{title}\n{text[:2000]}") and len(text) > 300:
                break
        rec.update(snapshot(title, text))
        rec["cookies"] = site_cookies([(c["name"], c["domain"]) for c in ctx.cookies()], url)
        rec["final_url"] = page.url
    rec["timeline"] = timeline
    return rec


async def run_zendriver_async(url, solve=False, headed=False):
    import zendriver as zd
    timeline, rec = [], {}
    name = ("zendriver_headed" if headed else "zendriver") + ("_cf" if solve else "")
    browser = await zd.start(headless=not headed, user_data_dir=os.path.join(PROFILES, name),
                             browser_executable_path="/usr/bin/chromium",
                             browser_connection_max_tries=80)  # H11: default 10x0.25s = 2.5s is too short for a 300 MB profile
    # H5: Chrome writes cookies lazily and stop() kills it first, so carry them in a jar file
    jar = os.path.join(PROFILES, name + ".cookies.dat")
    try:
        if os.path.exists(jar):
            await browser.cookies.load(jar)
            rec["jar_loaded"] = True
        t0 = time.monotonic()
        tab = await browser.get(url)
        title = text = ""
        while time.monotonic() - t0 < (SETTLE_S + 20 if solve else SETTLE_S):  # room for the 20s solve
            await asyncio.sleep(2.5)
            title = await tab.evaluate("document.title") or ""
            text = await tab.evaluate("document.body ? document.body.innerText : ''") or ""
            timeline.append({"t": round(time.monotonic() - t0, 1), "title": title[:60], "chars": len(text)})
            if not CHALLENGE.search(f"{title}\n{text[:2000]}") and len(text) > 300:
                break
            if solve and not rec.get("solve") and time.monotonic() - t0 > 6:
                # Q2: hand the still-challenged page to zendriver's own Turnstile clicker
                try:
                    await tab.verify_cf(click_delay=3, timeout=20)
                    rec["solve"] = "verify_cf returned"
                except Exception as ex:
                    rec["solve"] = f"{type(ex).__name__}: {str(ex)[:120]}"
        rec.update(snapshot(title, text))
        rec["status"] = None  # zendriver tab.get does not surface the response status
        cookies = await browser.cookies.get_all()
        rec["cookies"] = site_cookies([(c.name, c.domain) for c in cookies], url)
        rec["final_url"] = tab.url
        await browser.cookies.save(jar)
    finally:
        await browser.stop()
    rec["timeline"] = timeline
    return rec


def one(variant, url):
    t0 = time.monotonic()
    clear_locks(os.path.join(PROFILES, variant))
    if variant.startswith("camoufox"):
        rec = run_camoufox(variant, url)
    elif variant in ("zendriver", "zendriver_cf"):
        rec = asyncio.run(run_zendriver_async(url, solve=variant == "zendriver_cf"))
    elif variant in ("zendriver_headed", "zendriver_headed_cf"):
        # Q0: real headed Chromium on a private Xvfb; killpg on timeout takes Xvfb down too
        display = f":{200 + os.getpid() % 500}"
        xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ["DISPLAY"] = display
        time.sleep(1.5)
        try:
            rec = asyncio.run(run_zendriver_async(url, solve=variant.endswith("_cf"), headed=True))
        finally:
            xvfb.kill()
    else:
        raise ValueError(variant)
    rec["first_status"] = rec.pop("status", None)
    if CHALLENGE.search(rec["title"] + rec["head"]):
        verdict, why = "blocked", "challenge marker still present at end"
    elif rec["chars"] < 300:
        verdict, why = "thin", f"{rec['chars']} chars"
    else:
        verdict, why = "ok", f"{rec['chars']} chars, first_status={rec['first_status']}"
    rec.update(variant=variant, url=url, verdict=verdict, why=why, ms=int((time.monotonic() - t0) * 1000))
    print(json.dumps(rec))


def drive(out_path, variant, urls):
    failures = 0
    with open(out_path, "a") as out:
        for url in urls:
            p = subprocess.Popen([sys.executable, __file__, "--one", variant, url], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=HARD_KILL_S)
                lines = [l for l in stdout.splitlines() if l.startswith("{")]
                if p.returncode == 0 and lines:
                    rec = json.loads(lines[-1])
                else:
                    rec = {"variant": variant, "url": url, "verdict": "error",
                           "why": (stderr.strip().splitlines() or ["no stderr"])[-1][:200]}
                    failures += 1
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
                rec = {"variant": variant, "url": url, "verdict": "hang", "why": f">{HARD_KILL_S}s, killed"}
                failures += 1
            rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(variant, rec["verdict"], url, "|", rec.get("why"), "|", rec.get("title", "")[:50],
                  "|", rec.get("cookies", ""), flush=True)
    print("DRIVER DONE failures:", failures, flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--one":
        one(sys.argv[2], sys.argv[3])
    else:
        drive(sys.argv[1], sys.argv[2], sys.argv[3:] or URLS)
