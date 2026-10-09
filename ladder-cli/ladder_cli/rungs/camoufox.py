"""Rung 2: Camoufox, a patched Firefox that answers where rung 1 was refused.

Every constant is carried across from the measured run at
``spikes/sample100-2026-10-03/ladder.py`` and cited at its use. Camoufox is a
patched build doing its own fingerprint work, so its launch is a distinct
declaration rather than a variant of rung 3's.

There is no warmed profile to keep here. The measured run passed no
``user_data_dir`` to ``Camoufox`` (ladder.py:71), which builds and tears down
its own browser per fetch; only the zendriver rungs persisted a profile, so
``state/profiles`` owns those and nothing else.
"""

from __future__ import annotations

from typing import Any

from . import STRIP_JS, RungResult, browser_judge

# ladder.py:71 `Camoufox(headless=True, humanize=True)`: `humanize` is the
# build's own human-like input shaping, and it is the point of reaching for
# Camoufox rather than a stock browser.
HEADLESS = True
HUMANIZE = True
# ladder.py:73 `p.goto(url, wait_until="domcontentloaded", timeout=30000)`
WAIT_UNTIL = "domcontentloaded"
GOTO_TIMEOUT_MS = 30000
# ladder.py:74 `p.wait_for_timeout(12000)`: the page is given time to run its
# own scripts before anything is read off it.
SETTLE_MS = 12000


def launch_options() -> dict[str, Any]:
    """The measured launch configuration, in one place so a test can read it."""
    return {"headless": HEADLESS, "humanize": HUMANIZE}


def fetch(url: str) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise.

    The browser is built here rather than at import: it is a browser tool, and
    the resident child owes its ready line before it touches one (04-tdd 1.4).
    """
    from camoufox.sync_api import Camoufox

    with Camoufox(**launch_options()) as browser:
        page = browser.new_page()
        response = page.goto(url, wait_until=WAIT_UNTIL, timeout=GOTO_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        title, text = page.evaluate(STRIP_JS)
        return {
            "title": title or "",
            "text": text or "",
            "status": response.status if response else None,
        }


def judge(page: dict[str, Any]) -> RungResult:
    return browser_judge(page)