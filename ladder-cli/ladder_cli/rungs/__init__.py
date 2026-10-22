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

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol as TypingProtocol

# Dependency order. Rung 5 is the rung-4 fallback, so it comes last.
RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf", "whisper")

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


@dataclass(frozen=True)
class RungContext:
    """The per-request state a rung needs beyond the URL.

    Only the two jar paths today. They live here rather than on a module global
    because a rung's fetch is per request and the resident child answers many
    requests over its life: a global would leak one caller's jar into the next
    caller's fetch.

    ``jar_in`` is loaded into the first browser rung that runs, and ``jar_out``
    is written from that browser before it stops. Rung 1 has no cookie jar, so a
    climb that rung 1 answers writes nothing; that is the honest outcome, not a
    silent failure.
    """

    jar_in: Path | None = None
    jar_out: Path | None = None


class RungModule(TypingProtocol):
    def fetch(self, url: str, ctx: RungContext | None = None) -> dict[str, Any]: ...

    def judge(self, page: dict[str, Any]) -> RungResult: ...


def normalize_page_text(text: str | None) -> str:
    """Collapse runs of blank lines and strip, the shape the run recorded.

    ladder.py:114 `re.sub(r"\\n\\s*\\n+", "\\n\\n", text or "").strip()` ran in
    the rung child before the record was written, so the 800-character floor and
    the 600-character challenge window were both measured against the collapsed
    string. Skipping it moves both thresholds onto text the run never saw: a
    page held open by whitespace padding reads as ``ok`` where the run read
    ``thin``, and a marker pushed past character 600 of padding reads as no
    marker at all.
    """
    return re.sub(r"\n\s*\n+", "\n\n", text or "").strip()


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
from . import camoufox, headed, whisper, zendriver  # noqa: E402

MODULES: dict[str, RungModule] = {
    "http": http,
    "camoufox": camoufox,
    "zendriver_cf": zendriver,
    "zendriver_headed_cf": headed,
    "whisper": whisper,
}


def fetch(rung: str, url: str, ctx: RungContext | None = None) -> dict[str, Any]:
    return MODULES[rung].fetch(url, ctx)


def judge(rung: str, page: dict[str, Any]) -> RungResult:
    return MODULES[rung].judge(page)


def network_verdict(message: str, rung: str) -> RungVerdict:
    """Map a child that produced no record at all.

    A DNS or TLS failure on rung 1 is final: no browser revives a domain that
    does not resolve, so it reads ``dead``. Every other rung reads such a
    failure as itself having malfunctioned, which climbs rather than being
    reported to the caller.

    The scoping is not decoration. The spike gates the same mapping on the rung
    (ladder.py:192, ``v = "dead" if rung == "http" and DEAD_NET.search(err)
    else "error"``) and this function is the reason it has to take one: a
    browser rung that cannot resolve is a browser rung that failed, not a page
    that is gone, and reading it as ``dead`` would stop the climb on the one
    signal that says to keep going.
    """
    if rung == "http" and http.DEAD_NET.search(message):
        return RungVerdict.DEAD
    return RungVerdict.ERROR
