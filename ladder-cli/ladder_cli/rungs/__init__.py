"""Rung registry and the verdict rules every rung shares.

A rung reports what it saw; this module decides what that means. Verdicts are
``ok``, ``dead``, and ``blocked``, the same three words as the spike ledger so
fixture rows stay comparable, plus ``error``, which says the rung itself
malfunctioned rather than answering about the page. ``error`` climbs, because a
rung that broke is not a reason to give up on the page, so it only reaches the
caller once every rung above it has failed to answer as well.

Two rules live here because every rung needs them and none should own them:
the text extraction a browser rung runs in the page, and the verdict rules the
browser rungs share. Rung 1 has its own judge, because it is the only rung
looking at raw HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol as TypingProtocol

# Dependency order. Phase 4 adds whisper for audio challenges.
RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")

# ladder.py:18. Drop the elements that are not the page, then read what is left.
# Camoufox's Playwright calls it for you; zendriver has to be handed a call
# (ladder.py:91, H12), so each rung wraps it as its library expects.
STRIP_JS = (
    "() => { document.querySelectorAll('script,style,noscript')"
    ".forEach(e => e.remove()); return [document.title, document.body.innerText] }"
)


class RungVerdict(Enum):
    OK = "ok"
    DEAD = "dead"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class RungResult:
    verdict: RungVerdict
    title: str = ""
    text: str = ""
    status: int | None = None
    reason: str = ""


class RungModule(TypingProtocol):
    def fetch(self, url: str) -> dict[str, Any]: ...

    def judge(self, page: dict[str, Any]) -> RungResult: ...


def browser_judge(page: dict[str, Any]) -> RungResult:
    """The verdict rules every browser rung shares.

    Rung 1 judges raw HTML, so it suspects a client-side shell and refuses a
    page too thin to be a page. A browser has already run the page's JavaScript
    by the time it reports, which retires both suspicions and leaves the rest.
    These are the measured run's rules (ladder.py:118 ``verdict``) with its two
    rung-1-only branches left out, which is why the same shell reads ``ok``
    here and ``blocked`` on rung 1.
    """
    status = page.get("status")
    title = page.get("title") or ""
    text = page.get("text") or ""

    if status in http.DEAD_STATUS:
        return RungResult(RungVerdict.DEAD, title, text, status, f"status {status}")
    if isinstance(status, int) and status >= 400:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"status {status}")
    if http.CHALLENGE.search(f"{title} {text[:600]}"):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "challenge marker")
    if len(text) < http.THIN_CHARS:
        return RungResult(
            RungVerdict.BLOCKED,
            title,
            text,
            status,
            f"{len(text)} chars, under the measured floor",
        )
    return RungResult(RungVerdict.OK, title, text, status, f"{len(text)} chars")


# Imported last: each rung module imports RungResult, RungVerdict, STRIP_JS and
# browser_judge from here, so binding the submodules before those names exist
# would start a cycle. ``http`` comes first because browser_judge reads the
# page-shape vocabulary it owns.
from . import http  # noqa: E402
from . import camoufox, headed, zendriver  # noqa: E402

MODULES: dict[str, RungModule] = {
    "http": http,
    "camoufox": camoufox,
    "zendriver_cf": zendriver,
    "zendriver_headed_cf": headed,
}


def fetch(rung: str, url: str) -> dict[str, Any]:
    return MODULES[rung].fetch(url)


def judge(rung: str, page: dict[str, Any]) -> RungResult:
    return MODULES[rung].judge(page)


def network_verdict(message: str) -> RungVerdict:
    """Map a child that produced no record at all.

    A DNS or TLS failure on rung 1 is final: no browser revives a domain that
    does not resolve, so it reads ``dead``. A timeout is deliberately absent
    from that set, because our budget firing is not the page's doing. Anything
    else is the rung malfunctioning, which climbs rather than being reported to
    the caller.
    """
    if http.DEAD_NET.search(message):
        return RungVerdict.DEAD
    return RungVerdict.ERROR