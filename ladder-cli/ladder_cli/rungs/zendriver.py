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
from typing import Any

from . import STRIP_JS, RungResult, browser_judge

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


def fetch(url: str) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise."""
    return climb(url, launch_options())


def climb(url: str, options: dict[str, Any]) -> dict[str, Any]:
    """The fetch rungs 3 and 4 share; only the launch options differ.

    Public because rung 4 is this same climb with a different head, and a
    sibling reaching for a private name would be the two halves drifting apart
    under cover of a name that says "not yours".
    """
    return asyncio.run(_fetch(url, options))


async def _fetch(url: str, options: dict[str, Any]) -> dict[str, Any]:
    import zendriver

    from ..state import profiles

    headed = not options["headless"]
    # ladder.py:82 `user_data_dir=os.path.abspath(f"profiles/zd{'_headed' if headed else ''}")`.
    # Warmed once and reused for the CLI's whole life, so the second request on a
    # profile does not pay the first one's cold start.
    user_data_dir = profiles.warm(profiles.zendriver_dir(profiles.root(), headed=headed))
    browser = await zendriver.start(user_data_dir=str(user_data_dir), **options)
    try:
        tab = await browser.get(url)
        await tab.sleep(SETTLE_S)
        try:
            await tab.verify_cf(**cf_options())
        except Exception:  # noqa: BLE001 - no Turnstile is not a failed fetch
            pass
        await tab.sleep(SETTLE_S)
        title, text = await tab.evaluate(TEXT_EXPRESSION)
        return {"title": title or "", "text": text or "", "status": None}
    finally:
        await browser.stop()


def judge(page: dict[str, Any]) -> RungResult:
    return browser_judge(page)