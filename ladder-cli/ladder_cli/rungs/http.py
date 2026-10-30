"""Rung 1: a site API where one exists, otherwise primp with browser impersonation.

Every constant here is carried across from the measured run at
``spikes/sample100-2026-10-03/ladder.py`` and cited at its use, so the numbers
stay attached to the evidence that produced them. ``ladder.py`` is deliberately
not imported: it is the executable statement of what was measured, not a
dependency.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import Cookie, MozillaCookieJar
from typing import Any

from . import RungResult, RungVerdict, normalize_links

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


class _AnchorParser(HTMLParser):
    """Collect anchors and their text without pulling in an HTML dependency.

    ``convert_charrefs`` is on by default, so ``&amp;`` in an href arrives as a
    literal ``&`` and the parent can use the URL as-is. Anchors may contain
    nested inline tags, which is why text is gathered from every data node until
    the closing ``a``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def _flush(self) -> None:
        if self._href is not None:
            self.links.append({"url": self._href, "text": "".join(self._text)})
        self._href = None
        self._text = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._flush()
        href = dict(attrs).get("href")
        if href:
            self._href = href

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._flush()


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


def extract_html(html: str, status: int | None, final_url: str) -> dict[str, Any]:
    """Turn raw HTML into the page shape every rung reports.

    Entity decoding happens after tag stripping, so an escaped ``&lt;script&gt;``
    in prose stays text instead of becoming a tag that is then removed. Source
    whitespace is layout, not content, and is collapsed so the character floors
    measure prose rather than indentation.
    """
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = (title_match.group(1) if title_match else "") or ""
    parser = _AnchorParser()
    parser.feed(html)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = unescape(body)
    body = re.sub(r"\s+", " ", body).strip()
    return {
        "title": title.strip(),
        "text": body,
        "status": status,
        "links": normalize_links(parser.links, final_url),
    }


def _load_jar_cookies(jar_in: str, url: str) -> dict[str, str]:
    """Cookies the caller's jar holds for this URL's host, as primp wants them.

    A jar the caller named but never wrote (a cold start on the first request of
    a sequence) is an empty read, not an error: the file appears on the save of
    that same first request.
    """
    jar = MozillaCookieJar(jar_in)
    if not os.path.exists(jar_in):
        return {}
    jar.load(ignore_discard=True, ignore_expires=True)
    host = urllib.parse.urlparse(url).hostname or ""
    matching: dict[str, str] = {}
    for cookie in jar:
        domain = (cookie.domain or "").lstrip(".")
        if domain and (host == domain or host.endswith("." + domain)) and cookie.value is not None:
            matching[cookie.name] = cookie.value
    return matching


def _save_jar_cookies(jar_out: str, url: str, cookies: dict[str, str]) -> None:
    """Merge this host's fresh cookies into the caller's jar, keeping other hosts.

    Entries are keyed by exact stored domain, so a rewrite replaces only the
    host this request visited and leaves every other site's cookies untouched.
    """
    jar = MozillaCookieJar(jar_out)
    kept: list[Cookie] = []
    if os.path.exists(jar_out):
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
            host = urllib.parse.urlparse(url).hostname or ""
            kept = [c for c in jar if c.domain.lstrip(".") != host]
        except OSError:
            kept = []
    jar.clear()
    for cookie in kept:
        jar.set_cookie(cookie)
    domain = urllib.parse.urlparse(url).hostname or ""
    for name, value in cookies.items():
        jar.set_cookie(
            Cookie(
                0,
                name,
                value,
                None,
                False,
                domain,
                False,
                domain.startswith("."),
                "/",
                True,
                False,
                None,
                False,
                None,
                None,
                {},
            )
        )
    jar.save(ignore_discard=True, ignore_expires=True)


def _walled(page: dict[str, Any]) -> bool:
    """Whether a 200 answer is a defence page rather than the requested content.

    The two shapes the parity measurements kept producing: a challenge marker,
    or a body below the rung-1 shell floor (LinkedIn's signup wall renders 413
    characters at status 200). Both are cheap local reads on the extracted page.
    """
    text = page.get("text") or ""
    title = page.get("title") or ""
    return bool(CHALLENGE.search(f"{title} {text[:600]}")) or len(text) < SHELL_FLOOR


def fetch(url: str, *, jar_in: str | None = None, jar_out: str | None = None) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise.

    Nothing verdict-shaped is decided here: the caller judges, so one page
    representation feeds one set of rules regardless of how it was fetched.

    Two capabilities the 2026-10-30 parity measurements against an unblocker
    service isolated as the HTTP-level gap (findings: warmup and TLS were both
    present; rotation and the retry loop were not):

    - a caller-provided Netscape jar rides on the request and its fresh cookies
      are merged back, so a caller can warm a session across requests the way
      the browser rungs' profile dirs already do; and
    - a walled 200 answer is retried once on a freshly built client, so the
      second identity is not the first one's TLS fingerprint or its response
      cookies - the caller's jar still rides on the retry.
    """
    api = api_url(url)
    jar_cookies = _load_jar_cookies(jar_in, url) if jar_in else {}
    page: dict[str, Any] = {}
    client: Any = None
    final_url = url
    for attempt in (1, 2):
        # A fresh client per attempt is the point, not waste: primp draws a new
        # impersonation each build, so the retry arrives as a different browser.
        client = _client()
        if jar_cookies:
            client.set_cookies(url, jar_cookies)
        response = client.get(api or url, headers={"User-Agent": USER_AGENT} if api else None)
        status = response.status_code

        if api and status == 200:
            page = {"title": "api", "text": flatten_api(url, response.json()), "status": status, "links": []}
            final_url = str(getattr(response, "url", "") or url)
            break

        final_url = str(getattr(response, "url", "") or url)
        page = extract_html(response.text, status, final_url)
        if attempt == 1 and status == 200 and _walled(page):
            continue
        break

    if jar_out and client is not None:
        try:
            fresh = client.get_cookies(final_url)
        except Exception:  # noqa: BLE001 - a cookie read must not discard a fetched page
            fresh = {}
        if isinstance(fresh, dict):
            _save_jar_cookies(jar_out, final_url, fresh)
    return page


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
    links = page.get("links") or []

    if title == "api":
        return RungResult(RungVerdict.OK, title, text, status, "site api")
    if status in DEAD_STATUS:
        return RungResult(RungVerdict.DEAD, title, text, status, f"status {status}", links=links)
    if isinstance(status, int) and status >= 400:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"status {status}", links=links)
    if CHALLENGE.search(f"{title} {text[:600]}"):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "challenge marker", links=links)
    if len(text.replace(title, "", 1).strip()) < SHELL_FLOOR:
        return RungResult(
            RungVerdict.BLOCKED,
            title,
            text,
            status,
            f"{len(text)} chars, under rung-1 floor",
            links=links,
        )
    if JS_SHELL.search(text):
        return RungResult(RungVerdict.BLOCKED, title, text, status, "js shell (loading marker)", links=links)
    if len(text) < THIN_CHARS:
        return RungResult(RungVerdict.BLOCKED, title, text, status, f"{len(text)} chars", links=links)
    return RungResult(RungVerdict.OK, title, text, status, f"{len(text)} chars", links=links)
