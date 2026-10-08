"""Rung 1: a site API where one exists, otherwise primp with browser impersonation.

Every constant here is carried across from the measured run at
``spikes/sample100-2026-10-03/ladder.py`` and cited at its use, so the numbers
stay attached to the evidence that produced them. ``ladder.py`` is deliberately
not imported: it is the executable statement of what was measured, not a
dependency.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from . import RungResult, RungVerdict

# ladder.py:16
CHALLENGE = re.compile(
    r"just a moment|attention required|checking your browser|press & hold|verify you are human|"
    r"prove your humanity|robot or human|access denied|blocked by network security|"
    r"enable javascript and cookies",
    re.I,
)
# ladder.py:19
JS_SHELL = re.compile(r"\bloading(\.\.\.|…| the )", re.I)
# ladder.py:130: any TLS failure is dead; plain-http fallback is an open item (BAL-40).
# The spike maps a timeout here too, which would let a blown budget read as "the
# page is gone" and stop the climb dead. A timeout is our machinery failing
# rather than the page, so it is deliberately absent and reads as an error.
DEAD_NET = re.compile(
    r"DNSError|dns error|failed to lookup|Name or service not known|ConnectError|Connection refused|"
    r"connection reset|certificate|tls handshake|received corrupt message|ERR_SSL|"
    r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION",
    re.I,
)
# ladder.py:133: rung-1 text beyond the title; below this only a browser can say what the page is
SHELL_FLOOR = 300
# ladder.py:134: gone, or Cloudflare saying the origin is down
DEAD_STATUS = {404, 410, 521, 522, 523, 525, 526, 530}
# ladder.py:125: the thin floor below which the spike's regex baseline refuses to call a page ok
THIN_CHARS = 800
# ladder.py:59
USER_AGENT = "serp-axi-research/0.1"


def api_url(url: str) -> str | None:
    """Prefer a site's own API over its HTML when the URL is a known discussion page."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("reddit.com") and "/comments/" in parsed.path:
        return "https://www.reddit.com" + parsed.path.rstrip("/") + ".json?limit=200"
    if parsed.netloc == "news.ycombinator.com" and "id=" in parsed.query:
        item = urllib.parse.parse_qs(parsed.query)["id"][0]
        return f"https://hn.algolia.com/api/v1/items/{item}"
    return None


def flatten_api(url: str, data: Any) -> str:
    """Depth-first gather of readable post bodies from a discussion API payload.

    ladder.py:65 strips tags by substituting a single space, which leaves double
    spaces behind, and formats author and score unconditionally (lines 38-39),
    so a node with neither prints the string "None". Both are cosmetic rather
    than measured, so they are cleaned here instead of carried across.
    """
    pieces: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("title", "selftext", "body", "text"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()
                    who = node.get("author")
                    points = node.get("score") if node.get("score") is not None else node.get("points")
                    head = " ".join(str(part) for part in (who, points) if part is not None and part != "")
                    pieces.append(f"[{head}] {cleaned}" if head else cleaned)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(data)
    return "\n\n".join(pieces)


def _client() -> Any:
    # ladder.py:49: "random" can pick a profile this primp build rejects
    # (BuilderError chrome_133), so retry before falling back to chrome.
    #
    # primp is imported here, not at module scope: it is a browser tool, and the
    # resident child owes its ready line before it touches one (04-tdd 1.4).
    # Importing it at the top spends the handshake budget on a library the first
    # request may not even need.
    import primp

    for _ in range(5):
        try:
            return primp.Client(impersonate="random", impersonate_os="random", follow_redirects=True, timeout=30)
        except Exception as error:  # noqa: BLE001 - the retry key is a message match
            if "Invalid impersonate" not in str(error):
                raise
    return primp.Client(impersonate="chrome", follow_redirects=True, timeout=30)


def fetch(url: str) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise.

    Nothing verdict-shaped is decided here: the caller judges, so one page
    representation feeds one set of rules regardless of how it was fetched.
    """
    api = api_url(url)
    response = _client().get(api or url, headers={"User-Agent": USER_AGENT} if api else None)
    status = response.status_code

    if api and status == 200:
        return {"title": "api", "text": flatten_api(url, response.json()), "status": status}

    html = response.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = (title_match.group(1) if title_match else "") or ""
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"[ \t]+", " ", body)
    return {"title": title.strip(), "text": body, "status": status}


def judge(page: dict[str, Any]) -> RungResult:
    """Turn one fetched page into a verdict.

    Deterministic status and marker rules only; the spike's classifier step
    comes back in Phase 5 alongside its threshold fixtures, so this never
    guesses where the spike would have asked.

    A bot check is read before the shell floor, the reverse of the spike's
    ``judge`` order, because a challenge is a known reason and a shell is an
    unknown one: calling a short challenge page "thin" would let a defence pass
    off as merely content-thin.
    """
    status = page.get("status")
    title = page.get("title") or ""
    text = page.get("text") or ""

    if title == "api":
        return RungResult(RungVerdict.OK, title, text, status, "site api")
    if status in DEAD_STATUS:
        return RungResult(RungVerdict.DEAD, title, text, status, f"status {status}")
    if isinstance(status, int) and status >= 400:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"status {status}")
    if CHALLENGE.search(f"{title} {text[:600]}"):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "challenge marker")
    if len(text.replace(title, "", 1).strip()) < SHELL_FLOOR:
        return RungResult(
            RungVerdict.BLOCKED,
            title,
            text,
            status,
            f"{len(text)} chars, under rung-1 floor",
        )
    if JS_SHELL.search(text):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "js shell (loading marker)")
    if len(text) < THIN_CHARS:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"{len(text)} chars")
    return RungResult(RungVerdict.OK, title, text, status, f"{len(text)} chars")
