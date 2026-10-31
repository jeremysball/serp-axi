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
import urllib.parse
from dataclasses import dataclass, field
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
# Anchors are read from the live DOM, not from the stripped text. ``a.href``
# resolves relative URLs the same way a click would, so the parent gets links it
# can follow without re-resolving them against the final page URL.
LINKS_JS = (
    "() => Array.from(document.querySelectorAll('a[href]'))"
    ".map(a => ({ url: a.href, text: (a.innerText || a.textContent || '').trim() }))"
)
# A page can carry thousands of anchors, most of them navigation chrome. The
# cap keeps one response bounded without hiding the links a caller came for.
MAX_LINKS = 200
MAX_LINK_TEXT = 200


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
    links: list[dict[str, str]] = field(default_factory=list)


class RungModule(TypingProtocol):
    def fetch(self, url: str) -> dict[str, Any]: ...

    def judge(self, page: dict[str, Any]) -> RungResult: ...


def normalize_page_text(text: str | None) -> str:
    """Collapse whitespace noise while keeping paragraph breaks.

    ladder.py:114 `re.sub(r"\\n\\s*\\n+", "\\n\\n", text or "").strip()` ran in
    the rung child before the record was written, so the 800-character floor and
    the 600-character challenge window were both measured against the collapsed
    string. Skipping it moves both thresholds onto text the run never saw: a
    page held open by whitespace padding reads as ``ok`` where the run read
    ``thin``, and a marker pushed past character 600 of padding reads as no
    marker at all.

    ``innerText`` preserves the page's visual line breaks, including lines that
    are only indentation from the source. Trimming each line and collapsing
    repeated blank runs removes that noise without flattening real paragraphs.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize_links(entries: Any, base_url: str | None = None) -> list[dict[str, str]]:
    """Dedupe, absolutize, and bound the anchors a rung reports.

    Rung 1 reads raw ``href`` values, which may be relative, so ``base_url`` is
    the final URL after redirects. Browser rungs already hand back absolute
    ``a.href`` values and pass no base. Non-navigational schemes are dropped
    rather than reported as links the caller cannot fetch.
    """
    if not isinstance(entries, list):
        return []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_url = entry.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            continue
        url = raw_url.strip()
        if base_url:
            url = urllib.parse.urljoin(base_url, url)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        raw_text = entry.get("text")
        text = re.sub(r"\s+", " ", raw_text).strip()[:MAX_LINK_TEXT] if isinstance(raw_text, str) else ""
        links.append({"url": url, "text": text})
        if len(links) >= MAX_LINKS:
            break
    return links


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
    links = normalize_links(page.get("links"))

    if status in http.DEAD_STATUS:
        return RungResult(RungVerdict.DEAD, title, text, status, f"status {status}", links=links)
    if isinstance(status, int) and status >= 400:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"status {status}", links=links)
    if http.CHALLENGE.search(f"{title} {text[:600]}"):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "challenge marker", links=links)
    if len(text) < http.THIN_CHARS:
        return RungResult(
            RungVerdict.BLOCKED,
            title,
            text,
            status,
            f"{len(text)} chars, under the measured floor",
            links=links,
        )
    return RungResult(RungVerdict.OK, title, text, status, f"{len(text)} chars", links=links)


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
