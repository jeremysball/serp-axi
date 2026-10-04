"""Spike (throwaway): run each (variant, target) in its own subprocess with a hard wall-clock kill.

Usage: xvfb-run -a .venv/bin/python scrape_driver.py <variant>...
Child mode: scrape_driver.py --one <variant> <COLD|FP|url>
"""

import json
import os
import re
import signal
import subprocess
import sys
import time

from scrape_probe import FINGERPRINT_URL, URLS, classify, launch

HARD_KILL_S = 75


def one(variant, target):
    if variant.startswith(("patchright", "stealth")):
        from patchright.sync_api import sync_playwright
    else:
        from playwright.sync_api import sync_playwright
    rec = {"variant": variant, "target": target}
    with sync_playwright() as pw:
        t0 = time.monotonic()
        browser, ctx, _ = launch(variant, pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("about:blank")
        rec["cold_start_ms"] = int((time.monotonic() - t0) * 1000)
        if target == "FP":
            # bot.sannysoft.com hangs every variant here; read the main tells directly instead
            page.goto("https://example.com", wait_until="load", timeout=30000)
            rec["fingerprint"] = page.evaluate(
                """() => ({webdriver: navigator.webdriver, ua: navigator.userAgent,
                     plugins: navigator.plugins.length, languages: navigator.languages,
                     chrome_obj: typeof window.chrome})"""
            )
        elif target != "COLD":
            t1 = time.monotonic()
            resp = page.goto(target, wait_until="commit", timeout=30000)
            page.wait_for_timeout(6000)  # let challenges / SPAs settle
            title = page.title()
            text = page.inner_text("body", timeout=10000)
            verdict, why = classify(resp.status if resp else None, title, text)
            rec.update(status=resp.status if resp else None, title=title[:120], chars=len(text),
                       verdict=verdict, why=why, head=re.sub(r"\s+", " ", text[:240]),
                       ms=int((time.monotonic() - t1) * 1000))
        ctx.close()
        if browser:
            browser.close()
    print(json.dumps(rec))


def drive(variants):
    failures = 0
    for v in variants:
        out = open(f"./scrape_{v}{os.environ.get('SUFFIX', '')}.jsonl", "w")
        for target in ["COLD", "FP", *URLS]:
            p = subprocess.Popen([sys.executable, __file__, "--one", v, target], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=HARD_KILL_S)
                lines = [l for l in stdout.splitlines() if l.startswith("{")]
                if p.returncode == 0 and lines:
                    rec = json.loads(lines[-1])
                else:
                    err = (stderr.strip().splitlines() or ["no stderr"])[-1]
                    rec = {"variant": v, "target": target, "verdict": "error", "why": err[:200]}
                    failures += 1
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)  # take the browser down with the child
                p.communicate()
                rec = {"variant": v, "target": target, "verdict": "hang", "why": f">{HARD_KILL_S}s, killed"}
                failures += 1
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(v, rec.get("verdict", "-"), target, "|", rec.get("why", ""), "|", rec.get("cold_start_ms", ""),
                  "|", rec.get("fingerprint", ""), flush=True)
    print("DRIVER DONE failures:", failures, flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--one":
        one(sys.argv[2], sys.argv[3])
    else:
        drive(sys.argv[1:])
