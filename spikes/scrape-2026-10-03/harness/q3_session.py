"""Spike: Q3 control. Solve indeed once, then revisit in the SAME browser after 60s and after a fresh tab."""
import asyncio, json, os, re, time
import zendriver as zd
U = "https://www.indeed.com/q-software-engineer-jobs.html"
CH = re.compile(r"just a moment", re.I)

async def state(tab):
    await asyncio.sleep(6)
    return (await tab.evaluate("document.title")) or ""

async def main():
    b = await zd.start(headless=True, browser_executable_path="/usr/bin/chromium")
    out = []
    try:
        tab = await b.get(U)
        await asyncio.sleep(6)
        try:
            await tab.verify_cf(click_delay=3, timeout=20)
        except Exception as ex:
            out.append({"solve_exc": type(ex).__name__})
        await asyncio.sleep(4)
        out.append({"step": "after_solve", "title": (await tab.evaluate("document.title"))[:50]})
        ck = [c for c in await b.cookies.get_all() if c.name == "cf_clearance"]
        out.append({"cf_clearance": [{"domain": c.domain, "expires": c.expires, "secure": c.secure,
                                      "same_site": str(c.same_site), "partition": str(getattr(c, "partition_key", None))} for c in ck]})
        await asyncio.sleep(60)
        tab2 = await b.get(U, new_tab=True)
        out.append({"step": "same_browser_new_tab_+60s", "title": (await state(tab2))[:50]})
        await b.cookies.save("profiles/q3_session.dat")
    finally:
        await b.stop()
    b2 = await zd.start(headless=True, browser_executable_path="/usr/bin/chromium")
    try:
        await b2.cookies.load("profiles/q3_session.dat")
        ck = [c.name for c in await b2.cookies.get_all() if c.name == "cf_clearance"]
        out.append({"restart_loaded": ck})
        t = await b2.get(U)
        out.append({"step": "restart_+jar", "title": (await state(t))[:50]})
    finally:
        await b2.stop()
    print(json.dumps(out, indent=1))

asyncio.run(main())
