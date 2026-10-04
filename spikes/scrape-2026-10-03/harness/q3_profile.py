"""Spike: Q3 without the jar. Solve glassdoor, revisit same browser +60s, close gracefully, relaunch same profile."""
import asyncio, json, os, shutil, sqlite3, time
import zendriver as zd
from zendriver import cdp
import sys
U = sys.argv[1] if len(sys.argv) > 1 else "https://www.glassdoor.com/Reviews/index.htm"
PROF = os.path.abspath("profiles/q3_profile")

async def title(tab, wait=8):
    await asyncio.sleep(wait)
    return ((await tab.evaluate("document.title")) or "")[:50]

async def main():
    shutil.rmtree(PROF, ignore_errors=True)
    out = []
    b = await zd.start(headless=True, user_data_dir=PROF, browser_executable_path="/usr/bin/chromium")
    tab = await b.get(U)
    await asyncio.sleep(6)
    try:
        await tab.verify_cf(click_delay=3, timeout=20)
    except Exception as ex:
        out.append({"solve_exc": str(ex)[:60]})
    out.append({"step": "after_solve", "title": await title(tab, 5), "at": time.strftime("%H:%M:%S")})
    await asyncio.sleep(60)
    await tab.get(U)
    out.append({"step": "same_tab_+60s", "title": await title(tab)})
    tab2 = await b.get(U, new_tab=True)
    out.append({"new_tab_cookie": [c.name for c in await b.cookies.get_all() if c.name == "cf_clearance"]})
    out.append({"step": "same_browser_+60s", "title": await title(tab2)})
    proc = b._process
    await b.connection.send(cdp.browser.close())  # graceful: Chrome flushes its cookie store
    for _ in range(30):
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.5)
    out.append({"graceful_exit": proc.returncode})
    db = os.path.join(PROF, "Default", "Cookies")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out.append({"on_disk": con.execute("select host_key, name, top_frame_site_key from cookies where name='cf_clearance'").fetchall()})
    con.close()
    try:
        await b.stop()
    except Exception:
        pass
    await asyncio.sleep(3)
    b2 = await zd.start(headless=True, user_data_dir=PROF, browser_executable_path="/usr/bin/chromium")
    try:
        out.append({"restart_cookie": [c.name for c in await b2.cookies.get_all() if c.name == "cf_clearance"]})
        t = await b2.get(U)
        out.append({"step": "restart_same_profile", "title": await title(t), "at": time.strftime("%H:%M:%S")})
    finally:
        await b2.stop()
    print(json.dumps(out))

asyncio.run(main())
