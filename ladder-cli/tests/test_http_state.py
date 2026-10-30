"""Rung 1's caller-jar round trip and fresh-identity retry, against fakes.

The jar and the retry are rung 1's answer to the stateful defences the browser
rungs already face through their profile dirs: cookies earned by one request
ride on the next, and a walled answer gets a second, freshly-built identity
before the climb spends browser time. Nothing here touches the network; the
fakes stand in for primp the same way the judge fixtures stand in for pages.
"""

from __future__ import annotations

from http.cookiejar import MozillaCookieJar

from ladder_cli.rungs import http


class FakeResponse:
    def __init__(self, status_code: int, text: str, url: str = "https://example.com/x"):
        self.status_code = status_code
        self.text = text
        self.url = url


class FakeClient:
    """A primp client double: scripted answers, recorded cookie calls."""

    def __init__(self, responses: list[FakeResponse], cookies: dict[str, str] | None = None):
        self.responses = list(responses)
        self.set_calls: list[tuple[str, dict[str, str]]] = []
        self._cookies = dict(cookies or {})

    def get(self, url: str, headers: dict[str, str] | None = None) -> FakeResponse:
        return self.responses.pop(0)

    def set_cookies(self, url: str, cookies: dict[str, str]) -> None:
        self.set_calls.append((url, dict(cookies)))

    def get_cookies(self, url: str) -> dict[str, str]:
        return dict(self._cookies)


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
        lines.append(f"{domain}\t{subdomains}\t/\tFALSE\t0\t{name}\t{value}")
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

    http.fetch("https://example.com/x", jar_in=str(jar_in))

    assert [calls for client in built for calls in client.set_calls] == [
        ("https://example.com/x", {"sid": "warm"}),
        ("https://example.com/x", {"sid": "warm"}),
    ], "the caller's jar is deliberate state: both identities ride it"


def test_an_absent_jar_file_is_a_cold_start_not_an_error(monkeypatch, tmp_path) -> None:
    built: list[FakeClient] = []

    def factory() -> FakeClient:
        client = FakeClient([FakeResponse(200, article_html())])
        built.append(client)
        return client

    monkeypatch.setattr(http, "_client", factory)

    page = http.fetch("https://example.com/x", jar_in=str(tmp_path / "missing.jar"))

    assert page["title"] == "An article"
    assert built[0].set_calls == [], "no jar written yet means no cookies to send"


def test_fresh_cookies_merge_back_and_other_hosts_survive(monkeypatch, tmp_path) -> None:
    jar_out = tmp_path / "out.jar"
    write_jar(jar_out, [("other.example", "keep", "1")])

    def factory() -> FakeClient:
        return FakeClient([FakeResponse(200, article_html())], cookies={"sid": "fresh"})

    monkeypatch.setattr(http, "_client", factory)

    http.fetch("https://example.com/x", jar_out=str(jar_out))

    loaded = MozillaCookieJar(str(jar_out))
    loaded.load(ignore_discard=True, ignore_expires=True)
    by_name = {cookie.name: cookie for cookie in loaded}
    assert by_name["sid"].value == "fresh", "the session's own cookies land in the jar"
    assert by_name["sid"].domain == "example.com"
    assert by_name["keep"].value == "1", "another host's cookies are not the retry's to drop"
