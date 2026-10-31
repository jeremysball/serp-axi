"""Rung 1: a site API where one exists, otherwise primp with browser impersonation.

Every constant here is carried across from the measured run at
``spikes/sample100-2026-10-03/ladder.py`` and cited at its use, so the numbers
stay attached to the evidence that produced them. ``ladder.py`` is deliberately
not imported: it is the executable statement of what was measured, not a
dependency.
"""

from __future__ import annotations

import copy
import os
import re
import tempfile
import urllib.parse
from email.message import Message
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import DefaultCookiePolicy, HTTPONLY_ATTR, MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.request import Request

from . import RungContext, RungResult, RungVerdict, normalize_links

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
            return primp.Client(impersonate="random", impersonate_os="random", cookie_store=False, follow_redirects=False, timeout=30)
        except Exception as error:  # noqa: BLE001 - the retry key is a message match
            if "Invalid impersonate" not in str(error):
                raise
    return primp.Client(impersonate="chrome", cookie_store=False, follow_redirects=False, timeout=30)


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


def _load_jar_cookies(path: str | None) -> MozillaCookieJar:
    """Load complete Netscape records, enforcing host-only cookies on replay."""
    jar = MozillaCookieJar(path, policy=DefaultCookiePolicy(
        strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain,
    ))
    if path:
        try:
            jar.load(ignore_discard=True)
        except FileNotFoundError:
            pass
    return jar


def _save_jar_cookies(jar_out: str, jar: MozillaCookieJar) -> None:
    """Atomically persist full cookie records, never a name/value projection."""
    target = Path(jar_out).resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        for cookie in jar:
            if cookie.has_nonstandard_attr("HttpOnly"):
                cookie.set_nonstandard_attr(HTTPONLY_ATTR, cookie.get_nonstandard_attr("HttpOnly"))
        jar.save(str(temporary), ignore_discard=True)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _request(client: Any, url: str, jar: MozillaCookieJar, saved: MozillaCookieJar, *, api: bool) -> Any:
    for redirect in range(21):
        request = Request(url, headers={"User-Agent": USER_AGENT} if api else {})
        jar.add_cookie_header(request)
        response = client.get(url, headers=dict(request.header_items()), follow_redirects=False)
        headers = Message()
        for key, value in response.headers.items():
            for line in value.split("\n"):
                headers.add_header(key, line)

        class CookieResponse:
            def info(self):
                return headers

        jar.extract_cookies(CookieResponse(), request)
        saved.extract_cookies(CookieResponse(), request)
        location = headers.get("Location")
        if response.status_code not in (301, 302, 303, 307, 308) or not location:
            return response
        if redirect == 20:
            raise RuntimeError("HTTP redirect limit exceeded")
        url = urllib.parse.urljoin(url, location)
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ValueError("HTTP redirect must use http or https")


def _walled(page: dict[str, Any]) -> bool:
    """Use the judge's blocked-page rules to decide whether to retry a 200."""
    return judge(page).verdict is RungVerdict.BLOCKED


def fetch(url: str, ctx: RungContext | None = None) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status", "links"}``, or raise.

    Nothing verdict-shaped is decided here: the caller judges, so one page
    representation feeds one set of rules regardless of how it was fetched.

    ``ctx`` carries rung 1's own jar pair: the caller's full-session Netscape
    cookies, loaded before the request and saved after it. They are not the
    browser JSON jars, and the two formats are never converted into one another.

    Caller-provided Netscape cookies retain their scope through requests and
    redirects. Response cookies are saved with their domain, path, Secure,
    expiry and HttpOnly attributes. Netscape files cannot represent SameSite.

    A blocked 200 answer gets one retry with a fresh client and the original
    caller cookies. Random impersonation may choose the same profile again;
    a fresh client does not guarantee a different TLS fingerprint or address.
    """
    api = api_url(url)
    jar_in = str(ctx.jar_in) if ctx is not None and ctx.jar_in is not None else None
    jar_out = str(ctx.jar_out) if ctx is not None and ctx.jar_out is not None else None
    jar_cookies = _load_jar_cookies(jar_in)
    output_cookies = _load_jar_cookies(jar_out)
    for cookie in jar_cookies:
        output_cookies.set_cookie(copy.copy(cookie))
    page: dict[str, Any] = {}
    client: Any = None
    final_url = url
    for attempt in (1, 2):
        client = _client()
        carried, saved = _load_jar_cookies(None), _load_jar_cookies(None)
        for source, target in ((jar_cookies, carried), (output_cookies, saved)):
            for cookie in source:
                target.set_cookie(copy.deepcopy(cookie))
        response = _request(client, api or url, carried, saved, api=bool(api))
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
        _save_jar_cookies(jar_out, saved)
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
