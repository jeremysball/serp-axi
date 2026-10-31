"""Rung 1's caller-jar round trip and fresh-identity retry, against fakes.

The jar and the retry are rung 1's answer to the stateful defences the browser
rungs already face through their profile dirs: cookies earned by one request
ride on the next, and a walled answer gets a second, freshly-built identity
before the climb spends browser time. Nothing here touches the network; the
fakes stand in for primp the same way the judge fixtures stand in for pages.
"""

from __future__ import annotations

import dataclasses
import io
import json
from http.cookiejar import HTTPONLY_ATTR, MozillaCookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from ladder_cli.rungs import RungContext, http
from ladder_cli import cli


@pytest.fixture
def cookie_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Cookie", "")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/final")
            else:
                self.send_response(200)
                if self.path == "/set":
                    self.send_header("Set-Cookie", "fresh=earned; Path=/private; Secure; HttpOnly; SameSite=Lax")
                    self.send_header("Set-Cookie", "session=earned; Path=/")
            self.end_headers()
            self.wfile.write(article_html().encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_real_http_replay_enforces_secure_path_and_expiry(cookie_server, tmp_path):
    base, seen = cookie_server
    path = tmp_path / "scope.jar"
    path.write_text("# Netscape HTTP Cookie File\n"
                    "127.0.0.1\tFALSE\t/\tFALSE\t\tallowed\tyes\n"
                    "127.0.0.1\tFALSE\t/\tTRUE\t\tsecure\tsecret\n"
                    "127.0.0.1\tFALSE\t/private\tFALSE\t\tprivate\tsecret\n"
                    "127.0.0.1\tFALSE\t/\tFALSE\t1\texpired\tsecret\n")

    page = http.fetch(base + "/public", RungContext(jar_in=path))

    assert seen == [("/public", "allowed=yes")]
    assert page["title"] == "An article"


def test_real_resident_and_rung_child_use_http_jar_without_touching_browser_jar(cookie_server, tmp_path, make_request):
    base, seen = cookie_server
    session = tmp_path / "session.txt"
    session.write_text("# Netscape HTTP Cookie File\n"
                       "127.0.0.1\tFALSE\t/\tFALSE\t\tallowed\tyes\n")
    browser = tmp_path / "browser.json"
    original = '{"cookies": [{"name": "cf_clearance", "value": "browser-only"}]}'
    browser.write_text(original)
    request = make_request(url=base + "/set", rungCeiling=1,
                           jarIn=str(browser), jarOut=str(browser),
                           httpJarIn=str(session), httpJarOut=str(session))
    stdout = io.StringIO()

    assert cli.main([], stdin=[json.dumps(dataclasses.asdict(request))], stdout=stdout) == 0

    ready, response = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert ready == {"ready": True, "protocol": 3}
    assert response["verdict"] == "ok"
    assert response["rungReached"] == 1
    assert response["title"] == "An article"
    assert seen == [("/set", "allowed=yes")]
    saved = MozillaCookieJar(str(session))
    saved.load(ignore_discard=True)
    assert {cookie.name for cookie in saved} == {"allowed", "fresh", "session"}
    assert browser.read_text() == original


def test_real_redirect_does_not_forward_host_only_cookies(cookie_server, tmp_path):
    base, seen = cookie_server
    path = tmp_path / "redirect.jar"
    path.write_text("# Netscape HTTP Cookie File\n"
                    "127.0.0.1\tFALSE\t/\tFALSE\t\tsid\tprivate\n")

    page = http.fetch(base + "/redirect", RungContext(jar_in=path))

    assert seen == [("/redirect", "sid=private"), ("/final", "")]
    assert page["title"] == "An article"


def test_real_cookie_save_keeps_response_attributes_and_unvisited_paths(cookie_server, tmp_path):
    base, seen = cookie_server
    path = tmp_path / "persist.jar"
    path.write_text("# Netscape HTTP Cookie File\n"
                    "127.0.0.1\tFALSE\t/unvisited\tTRUE\t\tkept\tprivate\n")

    http.fetch(base + "/set", RungContext(jar_in=path, jar_out=path))

    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True)
    cookies = {cookie.name: cookie for cookie in jar}
    assert cookies["session"].value == "earned"
    assert cookies["fresh"].secure is True
    assert cookies["fresh"].path == "/private"
    assert cookies["fresh"].has_nonstandard_attr(HTTPONLY_ATTR)
    assert cookies["kept"].path == "/unvisited"
    assert cookies["kept"].secure is True


class FakeResponse:
    def __init__(self, status_code: int, text: str, url: str = "https://example.com/x"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = {}


class FakeClient:
    """A primp client double: scripted answers, recorded cookie calls."""

    def __init__(self, responses: list[FakeResponse], cookies: dict[str, str] | None = None):
        self.responses = list(responses)
        self.request_calls = []
        self._cookies = dict(cookies or {})

    def get(self, url: str, headers: dict[str, str] | None = None, *, follow_redirects=False) -> FakeResponse:
        self.request_calls.append((url, headers))
        response = self.responses.pop(0)
        if self._cookies:
            response.headers["Set-Cookie"] = "\n".join(f"{name}={value}; Path=/" for name, value in self._cookies.items())
        return response


def wall_html() -> str:
    body = "Join LinkedIn. Email and a password of six characters, agree and join, or sign in."
    return f"<html><head><title>Sign Up | LinkedIn</title></head><body><p>{body}</p></body></html>"


def article_html() -> str:
    body = "An article opening. " + ("content " * 130)
    return f"<html><head><title>An article</title></head><body><p>{body}</p></body></html>"


def write_jar(path, entries: list[tuple[str, str, str]]) -> None:
    # Netscape field order: domain, subdomains-allowed, path, secure, expires, name, value.
    # cookielib asserts the subdomain flag agrees with a leading dot on the domain.
    lines = ["# Netscape HTTP Cookie File"]
    for domain, name, value in entries:
        subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        lines.append(f"{domain}\t{subdomains}\t/\tFALSE\t\t{name}\t{value}")
    path.write_text("\n".join(lines) + "\n")


def test_a_walled_200_is_retried_on_a_fresh_client(monkeypatch) -> None:
    built: list[FakeClient] = []
    # One script per client build: the first identity answers with the wall,
    # the fresh second identity carries the page.
    scripts = iter([[FakeResponse(200, wall_html())], [FakeResponse(200, article_html())]])

    def factory() -> FakeClient:
        client = FakeClient(next(scripts))
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    page = http.fetch("https://example.com/x")

    assert page["title"] == "An article", "a walled 200 must not be returned as the page"
    assert len(built) == 2, "the retry must build a second client, not reuse the first"


def test_a_clean_first_fetch_builds_exactly_one_client(monkeypatch) -> None:
    built: list[FakeClient] = []

    def factory() -> FakeClient:
        client = FakeClient([FakeResponse(200, article_html())])
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    http.fetch("https://example.com/x")

    assert len(built) == 1, "a passing first identity must not be retried"


@pytest.mark.parametrize("body_length", [280, 413])
def test_a_page_rejected_by_the_judge_gets_the_http_retry(monkeypatch, body_length) -> None:
    title = "A title long enough to mask a short body"
    html = f"<title>{title}</title><p>{'x' * body_length}</p>"
    first = http.extract_html(html, 200, "https://example.com/x")
    assert http.judge(first).verdict is http.RungVerdict.BLOCKED
    clients = iter([
        FakeClient([FakeResponse(200, html)]),
        FakeClient([FakeResponse(200, article_html())]),
    ])
    monkeypatch.setattr(http, "_client", lambda: next(clients))

    page = http.fetch("https://example.com/x")

    assert page["title"] == "An article"
    assert http.judge(page).verdict is http.RungVerdict.OK


def test_a_failed_cookie_metadata_read_reports_the_error_and_preserves_the_jar(monkeypatch, tmp_path) -> None:
    jar_out = tmp_path / "out.jar"
    write_jar(jar_out, [("example.com", "sid", "earned")])
    original = jar_out.read_bytes()

    class BrokenHeaders(dict):
        def items(self):
            raise RuntimeError("cookie store unavailable")

    response = FakeResponse(200, article_html())
    response.headers = BrokenHeaders()
    monkeypatch.setattr(http, "_client", lambda: FakeClient([response]))

    with pytest.raises(RuntimeError, match="cookie store unavailable"):
        http.fetch("https://example.com/x", RungContext(jar_out=jar_out))
    assert jar_out.read_bytes() == original


def test_an_error_status_is_not_retried(monkeypatch) -> None:
    built: list[FakeClient] = []

    def factory() -> FakeClient:
        client = FakeClient([FakeResponse(403, "nope")])
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    page = http.fetch("https://example.com/x")

    assert page["status"] == 403
    assert len(built) == 1, "a status answer is the page's own verdict, not a wall to retry"


def test_the_callers_jar_rides_on_every_attempt(monkeypatch, tmp_path) -> None:
    jar_in = tmp_path / "in.jar"
    write_jar(jar_in, [("example.com", "sid", "warm")])
    built: list[FakeClient] = []
    scripts = iter([[FakeResponse(200, wall_html())], [FakeResponse(200, article_html())]])

    def factory() -> FakeClient:
        client = FakeClient(next(scripts))
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    http.fetch("https://example.com/x", RungContext(jar_in=jar_in))

    assert [calls for client in built for calls in client.request_calls] == [
        ("https://example.com/x", {"Cookie": "sid=warm"}),
        ("https://example.com/x", {"Cookie": "sid=warm"}),
    ], "the caller's jar is deliberate state: both identities ride it"


def test_an_absent_jar_file_is_a_cold_start_not_an_error(monkeypatch, tmp_path) -> None:
    built: list[FakeClient] = []

    def factory() -> FakeClient:
        client = FakeClient([FakeResponse(200, article_html())])
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    page = http.fetch("https://example.com/x", RungContext(jar_in=tmp_path / "missing.jar"))

    assert page["title"] == "An article"
    assert built[0].request_calls == [("https://example.com/x", {})]


def test_fresh_cookies_merge_back_and_other_hosts_survive(monkeypatch, tmp_path) -> None:
    jar_out = tmp_path / "out.jar"
    write_jar(jar_out, [("other.example", "keep", "1")])

    def factory() -> FakeClient:
        return FakeClient([FakeResponse(200, article_html())], cookies={"sid": "fresh"})

    monkeypatch.setattr(http, "_client", factory)

    http.fetch("https://example.com/x", RungContext(jar_out=jar_out))

    loaded = MozillaCookieJar(str(jar_out))
    loaded.load(ignore_discard=True, ignore_expires=True)
    by_name = {cookie.name: cookie for cookie in loaded}
    assert by_name["sid"].value == "fresh", "the session's own cookies land in the jar"
    assert by_name["sid"].domain == "example.com"
    assert by_name["keep"].value == "1", "another host's cookies are not the retry's to drop"
