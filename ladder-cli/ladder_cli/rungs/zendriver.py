"""Rung 3: zendriver, a CDP client that clicks through Turnstile.

Every constant is carried across from the measured run at
``spikes/sample100-2026-10-03/ladder.py`` and cited at its use. Rung 4 is this
same fetch with the head taken off, so the click configuration is declared here
once and the headed half borrows it rather than restating it.

zendriver reports no status at all, which is the run's behaviour rather than an
oversight (ladder.py:91 returns ``None`` for it): a defence at this rung is read
from the page, not from a code.
"""

from __future__ import annotations

import asyncio
import fcntl
from pathlib import Path
from typing import Any

from ..state import jars, profiles
from . import LINKS_JS, STRIP_JS, RungContext, RungResult, browser_judge, normalize_page_text

# ladder.py:15 rung name `zendriver_cf`
HEADLESS = True
# ladder.py:82 `browser_connection_max_tries=80` (H11: a browser slow to accept
# the connection is not a reason to give up on the page)
BROWSER_CONNECT_MAX_TRIES = 80
# ladder.py:87 `tab.verify_cf(click_delay=3, timeout=20)`
CF_CLICK_DELAY_S = 3
CF_TIMEOUT_S = 20
# ladder.py:84 and ladder.py:89 `await tab.sleep(6)`
SETTLE_S = 6
# ladder.py:91 (H12): zendriver evaluates the expression and hands back an
# uncalled arrow function as ``{}``, so the extraction has to be wrapped in a
# call. Playwright calls it for you; here it is called explicitly.
TEXT_EXPRESSION = f"({STRIP_JS})()"
LINKS_EXPRESSION = f"({LINKS_JS})()"


def launch_options() -> dict[str, Any]:
    """The measured launch configuration.

    One declaration per rung, and the only one ``fetch`` reads: headed-ness is
    derived from it below rather than passed alongside it, so a rung cannot
    declare one head and launch another.
    """
    return {"headless": HEADLESS, "browser_connection_max_tries": BROWSER_CONNECT_MAX_TRIES}


def cf_options() -> dict[str, Any]:
    """The measured Turnstile click. Shared with rung 4, not restated there."""
    return {"click_delay": CF_CLICK_DELAY_S, "timeout": CF_TIMEOUT_S}


def fetch(url: str, ctx: RungContext | None = None) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise."""
    return climb(url, launch_options(), ctx)


def prepare_profile(headed: bool) -> Path:
    """Select and warm the profile this head uses."""
    return profiles.warm(profiles.zendriver_dir(profiles.root(), headed=headed))


def climb(url: str, options: dict[str, Any], ctx: RungContext | None = None) -> dict[str, Any]:
    """The fetch rungs 3 and 4 share; only the launch options differ.

    Public because rung 4 is this same climb with a different head, and a
    sibling reaching for a private name would be the two halves drifting apart
    under cover of a name that says "not yours".
    """
    profile = prepare_profile(headed=not options["headless"])
    with (profile / ".ladder.lock").open("a") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BlockingIOError(f"profile is already in use: {profile}; wait for the other ladder request to finish") from error
        jars.clear_locks(profile)
        return asyncio.run(_fetch(url, {**options, "user_data_dir": str(profile)}, ctx))


def _jar_cookie(cookie: Any) -> jars.Cookie:
    """A browser cookie as the jar's own record, keeping what replay needs."""
    same_site = getattr(cookie, "same_site", None)
    return jars.Cookie(
        name=cookie.name,
        domain=cookie.domain,
        value=cookie.value,
        expires=getattr(cookie, "expires", None),
        secure=bool(getattr(cookie, "secure", False)),
        same_site=getattr(same_site, "value", same_site),
        path=getattr(cookie, "path", "/") or "/",
        http_only=bool(getattr(cookie, "http_only", False)),
    )


def _cookie_param(cookie: jars.Cookie) -> Any:
    """A jar record as a CDP ``CookieParam``, the shape ``set_all`` sends.

    Deferred like every other zendriver touch so importing this module does not
    require the browser extra. A jar field the CDP type cannot represent is
    raised rather than dropped: a silently narrowed cookie is a replay that
    looks like it ran and did not.
    """
    from zendriver.cdp.network import CookieParam, CookieSameSite, TimeSinceEpoch

    fields: dict[str, Any] = {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "secure": cookie.secure,
        "http_only": cookie.http_only,
    }
    if cookie.expires is not None:
        fields["expires"] = TimeSinceEpoch(cookie.expires)
    if cookie.same_site is not None:
        fields["same_site"] = CookieSameSite(cookie.same_site)
    return CookieParam(**fields)


async def _fetch(url: str, options: dict[str, Any], ctx: RungContext | None = None) -> dict[str, Any]:
    carried = jars.load(ctx.jar_in, url) if ctx is not None and ctx.jar_in is not None else []
    import zendriver

    browser = await zendriver.start(**options)
    try:
        if carried:
            await browser.cookies.set_all([_cookie_param(cookie) for cookie in carried])
        tab = await browser.get(url)
        await tab.sleep(SETTLE_S)
        try:
            await tab.verify_cf(**cf_options())
        except Exception:  # noqa: BLE001 - no Turnstile is not a failed fetch
            pass
        await tab.sleep(SETTLE_S)
        title, text = await tab.evaluate(TEXT_EXPRESSION)
        links = await tab.evaluate(LINKS_EXPRESSION)
        if ctx is not None and ctx.jar_out is not None:
            # Before stop(): Chrome flushes cookies lazily and stop() kills it
            # first (solver_probe.py:85), which is why the jar exists at all.
            earned = await browser.cookies.get_all()
            jars.save(ctx.jar_out, (_jar_cookie(cookie) for cookie in earned), url)
        return {
            "title": title or "",
            "text": normalize_page_text(text),
            "status": None,
            "links": links,
        }
    finally:
        await browser.stop()


# One binding, not three restatements; see camoufox.judge.
judge = browser_judge
