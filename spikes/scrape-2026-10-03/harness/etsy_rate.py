"""How fast can headed Chromium hit Etsy search? One browser, one tab, shrinking gaps; stop at the first block.

Usage: timeout -k 10 900 .venv/bin/python etsy_rate.py <out.jsonl> [--fresh]
Each fetch: navigate, poll until the results page is real (title "<Query> - Etsy", >3000 chars) or 25s pass.
"""
import asyncio, json, os, re, subprocess, sys, tempfile, time

GAPS = [30, 15, 8, 4, 2, 0]
PER_GAP = 6
NAV_S, EVAL_S, SETTLE_S, FETCH_S, STOP_S = 20, 5, 25, 40, 15  # timeouts, seconds
WORDS = ("mug lamp candle poster blanket ring necklace sticker tote planter scarf wallet print journal "
         "coaster apron pillow hat bookmark keychain earrings bracelet vase quilt calendar puzzle "
         "ornament soap tumbler shirt bag frame sign clock rug basket socks").split()
CHALLENGE = re.compile(r"just a moment|verify you are human|robot or human|captcha|access denied|"
                       r"blocked|unusual activity|slide right", re.I)


def verdict(q, title, text):
    if CHALLENGE.search(f"{title}\n{text[:1500]}"):
        return "blocked"
    if title.lower().startswith(q) and "etsy" in title.lower() and len(text) > 3000:
        return "ok"
    return "pending"


async def main(out_path, fresh):
    import zendriver as zd
    prof = tempfile.mkdtemp(prefix="etsy-rate-") if fresh else os.path.abspath("profiles/zendriver_headed")
    for n in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try: os.unlink(os.path.join(prof, n))
        except FileNotFoundError: pass
    for attempt in range(3):  # run 2 failed to connect once right after a killed browser; retry, capped
        try:
            browser = await asyncio.wait_for(
                zd.start(headless=False, user_data_dir=prof, browser_executable_path="/usr/bin/chromium",
                         browser_connection_max_tries=80), 30)  # H11: default 2.5s connect budget
            break
        except Exception as ex:
            print("start attempt", attempt + 1, "failed:", type(ex).__name__, flush=True)
            await asyncio.sleep(3)
    else:
        raise SystemExit("browser never started")
    tab, i, t_start = None, 0, time.monotonic()
    try:
        with open(out_path, "a") as out:
            for gap in GAPS:
                for k in range(30 if gap == 0 else PER_GAP):  # sustained burst at gap 0
                    q = WORDS[i % len(WORDS)]; i += 1
                    url = f"https://www.etsy.com/search?q={q}" + (f"&page={i // len(WORDS) + 1}" if i > len(WORDS) else "")
                    t0 = time.monotonic()
                    seen = {"title": "", "text": ""}

                    async def fetch():
                        nonlocal tab
                        # H10: fetch 36 hung 15 min inside an un-timed CDP call; every await is now capped
                        if tab is None:
                            tab = await asyncio.wait_for(browser.get(url), NAV_S)
                        else:
                            await asyncio.wait_for(tab.get(url), NAV_S)
                        while time.monotonic() - t0 < SETTLE_S:
                            await asyncio.sleep(0.5)
                            try:
                                seen["title"] = await asyncio.wait_for(tab.evaluate("document.title"), EVAL_S) or ""
                                seen["text"] = await asyncio.wait_for(
                                    tab.evaluate("document.body ? document.body.innerText : ''"), EVAL_S) or ""
                            except Exception:
                                continue
                            v = verdict(q, seen["title"], seen["text"])
                            if v != "pending":
                                return v
                        return "thin"

                    try:
                        v = await asyncio.wait_for(fetch(), FETCH_S)
                    except asyncio.TimeoutError:
                        v = "hang"
                    title, text = seen["title"], seen["text"]
                    rec = {"gap_s": gap, "n": i, "q": q, "verdict": v, "fetch_s": round(time.monotonic() - t0, 2),
                           "t_s": round(time.monotonic() - t_start, 1), "title": title[:80], "chars": len(text),
                           "final_url": tab.url if tab else None, "head": re.sub(r"\s+", " ", text[:200]), "fresh": fresh,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                    out.write(json.dumps(rec) + "\n"); out.flush()
                    print(gap, i, q, v, rec["fetch_s"], rec["title"][:40], flush=True)
                    if v != "ok":
                        print("STOP at gap", gap, flush=True)
                        return
                    await asyncio.sleep(gap)
        print("DONE all gaps", flush=True)
    finally:
        try:
            await asyncio.wait_for(browser.stop(), STOP_S)
        except Exception:
            proc = getattr(browser, "_process", None)  # stop() hung: kill Chromium directly
            if proc: proc.kill()


if __name__ == "__main__":
    disp = f":{200 + os.getpid() % 500}"
    x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = disp
    time.sleep(1.5)
    try:
        asyncio.run(main(sys.argv[1], "--fresh" in sys.argv))
    finally:
        x.kill()
