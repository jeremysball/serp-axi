"""Rung 3 (zendriver + Turnstile click) against the measured constants.

Same rule as rung 2: the CDP browser is never started here, so the launch
configuration and the verdict rules are what gets pinned to the spike's
numbers.
"""

from __future__ import annotations

import pytest

from conftest import inject_module
from ladder_cli.rungs import RungVerdict, zendriver
from ladder_cli.state import profiles


def test_rung_three_runs_headless() -> None:
    # ladder.py:82 `zd.start(headless=not headed, ...)` with headed False
    assert zendriver.HEADLESS is True
    assert zendriver.launch_options()["headless"] is True


def test_the_launch_retries_the_connection_the_measured_number_of_times() -> None:
    # ladder.py:82 `browser_connection_max_tries=80` (H11)
    assert zendriver.BROWSER_CONNECT_MAX_TRIES == 80
    assert zendriver.launch_options() == {
        "headless": True,
        "browser_connection_max_tries": 80,
    }


def test_the_turnstile_click_carries_the_measured_delay_and_timeout() -> None:
    # ladder.py:87 `tab.verify_cf(click_delay=3, timeout=20)`
    assert zendriver.cf_options() == {"click_delay": 3, "timeout": 20}
    assert zendriver.CF_CLICK_DELAY_S == 3
    assert zendriver.CF_TIMEOUT_S == 20


def test_the_page_is_given_the_measured_settle_before_and_after_the_click() -> None:
    # ladder.py:84 and ladder.py:89 `await tab.sleep(6)`
    assert zendriver.SETTLE_S == 6


def test_the_text_expression_is_called_not_merely_evaluated() -> None:
    # ladder.py:91 (H12): zendriver returns an uncalled arrow function as {},
    # so the extraction expression has to be wrapped in a call.
    assert zendriver.TEXT_EXPRESSION == f"({zendriver.STRIP_JS})()"


def test_a_rung_three_page_is_judged_by_the_browser_rules() -> None:
    result = zendriver.judge({"title": "An article", "text": "content " * 200, "status": None})
    assert result.verdict is RungVerdict.OK
    assert result.status is None


def test_rung_three_is_registered_under_its_wire_name() -> None:
    from ladder_cli.rungs import MODULES, RUNGS

    assert "zendriver_cf" in RUNGS
    assert MODULES["zendriver_cf"] is zendriver


def test_fetch_climbs_with_its_own_declared_options(monkeypatch) -> None:
    """The launch options are what fetch uses, not a description of it.

    A configuration nothing reads is a claim no test can hold up: this pins the
    two together so they cannot be edited apart.
    """
    seen: dict = {}

    def fake_climb(url: str, options: dict, ctx=None) -> dict:
        seen["climb"] = (url, options)
        return {"title": "Recorded", "text": "body", "status": None}

    monkeypatch.setattr(zendriver, "climb", fake_climb)

    result = zendriver.fetch("https://example.com/")

    assert seen["climb"] == ("https://example.com/", zendriver.launch_options())
    assert result == {"title": "Recorded", "text": "body", "status": None}


def test_the_measured_call_sequence_is_honoured(tmp_path, monkeypatch) -> None:
    """The run slept before *and* after the Turnstile click (ladder.py:84, :89).

    Both settles are load-bearing and neither is a constant a config check could
    catch being dropped, so the sequence is asserted as a sequence. A single
    settle would change what the run saw and no other test would notice.
    """
    calls: list = []

    class FakeTab:
        async def sleep(self, seconds: float) -> None:
            calls.append(("sleep", seconds))

        async def verify_cf(self, **kwargs: object) -> None:
            calls.append(("verify_cf", kwargs))

        async def evaluate(self, expression: str):
            calls.append(("evaluate", expression))
            if expression == zendriver.LINKS_EXPRESSION:
                return [{"url": "https://example.com/", "text": "Home"}]
            return ("Title", "Body text.\n" + "\n" * 900)

    class FakeBrowser:
        async def get(self, url: str) -> FakeTab:
            calls.append(("get", url))
            return FakeTab()

        async def stop(self) -> None:
            calls.append(("stop",))

    class FakeZendriver:
        @staticmethod
        async def start(**kwargs: object) -> FakeBrowser:
            calls.append(("start", kwargs))
            return FakeBrowser()

    inject_module(monkeypatch, "zendriver", FakeZendriver)
    monkeypatch.chdir(tmp_path)

    page = zendriver.fetch("https://example.com/")

    assert page == {
        "title": "Title",
        "text": "Body text.",
        "status": None,
        "links": [{"url": "https://example.com/", "text": "Home"}],
    }, "blanks collapsed, as ladder.py:114 did"
    assert calls == [
        ("start", {"user_data_dir": str(tmp_path / "serp-axi" / "profiles" / "zd"), **zendriver.launch_options()}),
        ("get", "https://example.com/"),
        ("sleep", 6),
        ("verify_cf", {"click_delay": 3, "timeout": 20}),
        ("sleep", 6),
        ("evaluate", zendriver.TEXT_EXPRESSION),
        ("evaluate", zendriver.LINKS_EXPRESSION),
        ("stop",),
    ], "a settle is missing on one side of the click"


def test_the_headless_profile_is_the_one_warmed_not_the_headed_one(tmp_path, monkeypatch) -> None:
    """Rung 3 must not spend rung 4's profile: they are separate browsers."""
    seen: dict = {}

    class FakeBrowser:
        async def get(self, url: str):
            seen["profile"] = sorted(p.name for p in (tmp_path / "serp-axi" / "profiles").iterdir())

            class Tab:
                async def sleep(self, seconds: float) -> None: ...
                async def verify_cf(self, **kwargs: object) -> None: ...
                async def evaluate(self, expression: str):
                    if expression == zendriver.LINKS_EXPRESSION:
                        return []
                    return ("Title", "body text")

            return Tab()

        async def stop(self) -> None: ...

    class FakeZendriver:
        @staticmethod
        async def start(**kwargs: object) -> FakeBrowser:
            seen["dir"] = kwargs["user_data_dir"]
            return FakeBrowser()

    inject_module(monkeypatch, "zendriver", FakeZendriver)
    monkeypatch.chdir(tmp_path)

    zendriver.fetch("https://example.com/")

    assert seen["dir"] == str(tmp_path / "serp-axi" / "profiles" / "zd")
    assert seen["profile"] == ["zd"]


def test_a_stale_profile_lock_is_cleared_before_the_browser_starts(tmp_path, monkeypatch) -> None:
    """H4: a SIGKILLed browser leaves a lock the next launch stalls on.

    `jars.clear_locks` was tested on its own and called by nothing, which is a
    helper passing while the launch path it was written for still hangs. This
    calls the launch path's own preparation, so the wiring is what is asserted.
    """
    monkeypatch.chdir(tmp_path)
    profile = profiles.zendriver_dir(profiles.root(), headed=False)
    profile.mkdir(parents=True)
    import socket
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    (profile / "SingletonLock").symlink_to(f"{socket.gethostname()}-{child.pid}")
    assert (profile / "SingletonLock").is_symlink()

    async def fetch(url, options, ctx=None):
        assert options["user_data_dir"] == str(profile)
        assert not (profile / "SingletonLock").is_symlink()
        return {"title": "page", "text": "body", "status": None}

    monkeypatch.setattr(zendriver, "_fetch", fetch)
    page = zendriver.climb("https://example.com/", {"headless": True})

    assert page == {"title": "page", "text": "body", "status": None}
    assert not (profile / "SingletonLock").is_symlink()


def test_shared_profile_launches_are_exclusive(tmp_path, monkeypatch) -> None:
    import fcntl
    import pytest

    monkeypatch.chdir(tmp_path)
    calls = []

    async def fetch(url, options, ctx=None):
        calls.append(url)
        return {"title": "page", "text": "body", "status": None}

    monkeypatch.setattr(zendriver, "_fetch", fetch)
    assert zendriver.climb("https://example.com/", {"headless": True})["title"] == "page"
    assert calls == ["https://example.com/"]
    profile = profiles.zendriver_dir(profiles.root(), headed=False)
    profile.mkdir(parents=True, exist_ok=True)
    with (profile / ".ladder.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError, match="profile is already in use"):
            zendriver.climb("https://other.example/", {"headless": True})
    assert calls == ["https://example.com/"]


@pytest.mark.parametrize("headless", [True, False])
def test_browser_launch_uses_the_exact_profile_already_leased(tmp_path, monkeypatch, headless) -> None:
    import fcntl

    resolved = []
    launched = []

    def profile_dir(base, *, headed):
        path = base / f"{'headed' if headed else 'headless'}-{len(resolved)}"
        resolved.append(path)
        return path

    class Tab:
        async def sleep(self, seconds): ...
        async def verify_cf(self, **kwargs): ...
        async def evaluate(self, expression):
            if expression == zendriver.LINKS_EXPRESSION:
                return []
            return ("Title", "body text")

    class Browser:
        async def get(self, url):
            return Tab()

        async def stop(self): ...

    class Zendriver:
        @staticmethod
        async def start(**options):
            launched.append(options["user_data_dir"])
            assert options["user_data_dir"] == str(resolved[0]), "browser must use the leased directory"
            with (resolved[0] / ".ladder.lock").open("a") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return Browser()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(profiles, "zendriver_dir", profile_dir)
    inject_module(monkeypatch, "zendriver", Zendriver)

    page = zendriver.climb("https://example.com/", {"headless": headless})

    assert page == {"title": "Title", "text": "body text", "status": None, "links": []}
    assert launched == [str(tmp_path / "serp-axi" / "profiles" / f"{'headless' if headless else 'headed'}-0")]
    assert len(resolved) == 1, "profile selection has one owner per launch"


@pytest.mark.parametrize("headless", [True, False])
def test_invalid_jar_is_rejected_before_browser_start(tmp_path, monkeypatch, headless):
    from ladder_cli.rungs import RungContext
    from ladder_cli.state import jars

    started = []

    class Tab:
        async def sleep(self, seconds): ...
        async def verify_cf(self, **kwargs): ...
        async def evaluate(self, expression):
            if expression == zendriver.LINKS_EXPRESSION:
                return []
            return ("Title", "body")

    class Browser:
        async def get(self, url):
            return Tab()
        async def stop(self): ...

    class Zendriver:
        @staticmethod
        async def start(**options):
            started.append(options)
            return Browser()

    monkeypatch.chdir(tmp_path)
    inject_module(monkeypatch, "zendriver", Zendriver)
    path = tmp_path / "input.json"
    jars.save(path, [], "https://example.com/")
    options = {"headless": headless}
    page = zendriver.climb("https://example.com/", options, RungContext(jar_in=path))
    assert page == {"title": "Title", "text": "body", "status": None, "links": []}
    assert len(started) == 1
    path.write_text('{"cookies": 1}')

    with pytest.raises(ValueError, match="invalid cookie jar"):
        zendriver.climb("https://example.com/", options, RungContext(jar_in=path))
    assert len(started) == 1, "corrupt input must not launch another browser"


def test_failed_jar_export_reports_the_error_and_stops_the_browser(tmp_path, monkeypatch):
    from ladder_cli.rungs import RungContext

    calls = []

    class Tab:
        async def sleep(self, seconds): ...
        async def verify_cf(self, **kwargs): ...
        async def evaluate(self, expression):
            if expression == zendriver.LINKS_EXPRESSION:
                calls.append("links")
                return []
            calls.append("extract")
            return ("Title", "body")

    class Browser:
        @property
        def cookies(self):
            return self
        async def get_all(self):
            return []
        async def get(self, url):
            return Tab()
        async def stop(self):
            calls.append("stop")

    class Zendriver:
        @staticmethod
        async def start(**options):
            calls.append("start")
            return Browser()

    monkeypatch.chdir(tmp_path)
    inject_module(monkeypatch, "zendriver", Zendriver)
    output = tmp_path / "directory-not-a-jar"
    output.mkdir()
    with pytest.raises(OSError):
        zendriver.fetch("https://example.com/", RungContext(jar_out=output))
    assert calls == ["start", "extract", "links", "stop"]


def test_the_carried_jar_is_loaded_before_the_page_and_earned_cookies_saved_before_stop(
    tmp_path,
    monkeypatch,
) -> None:
    """`jarIn`/`jarOut` were sent by the parent and read by no rung.

    The order matters on both ends: a jar loaded after the page arrives replays
    nothing, and cookies read after `stop()` are the lazy-flush loss the jar
    exists to prevent (solver_probe.py:85).
    """
    from types import SimpleNamespace

    from ladder_cli.rungs import RungContext
    from ladder_cli.state import jars

    calls: list = []
    sent: list = []

    class FakeCookie:
        name = "cf_clearance"
        domain = ".example.com"
        value = "earned"
        expires = 1735689600.0
        secure = True
        same_site = "Lax"
        path = "/"
        http_only = True

    class FakeCookies:
        async def set_all(self, params: list) -> None:
            calls.append("set_all")
            sent.extend(params)

        async def get_all(self) -> list:
            calls.append("get_all")
            browsing = SimpleNamespace(name="sessionid", domain=".example.com", value="browsing")
            return [FakeCookie(), browsing]

    class FakeBrowser:
        cookies = FakeCookies()

        async def get(self, url: str):
            calls.append("get")

            class Tab:
                async def sleep(self, seconds: float) -> None: ...
                async def verify_cf(self, **kwargs: object) -> None: ...
                async def evaluate(self, expression: str) -> tuple[str, str]:
                    return ("Title", "body text")

            return Tab()

        async def stop(self) -> None:
            calls.append("stop")

    class FakeZendriver:
        @staticmethod
        async def start(**kwargs: object) -> FakeBrowser:
            return FakeBrowser()

    class FakeCookieParam(dict):
        def __init__(self, **fields: object) -> None:
            super().__init__(**fields)

    class FakeSameSite:
        def __init__(self, value: str) -> None:
            self.value = value

    class FakeTime(float):
        pass

    inject_module(monkeypatch, "zendriver", FakeZendriver)
    inject_module(
        monkeypatch,
        "zendriver.cdp.network",
        SimpleNamespace(CookieParam=FakeCookieParam, CookieSameSite=FakeSameSite, TimeSinceEpoch=FakeTime),
    )
    monkeypatch.chdir(tmp_path)

    jar_in = tmp_path / "in.cookies.json"
    jar_out = tmp_path / "out.cookies.json"
    jars.save(
        jar_in,
        [
            jars.Cookie(
                name="cf_clearance",
                domain=".example.com",
                value="carried",
                secure=True,
                same_site="Strict",
                path="/account",
                http_only=True,
            )
        ],
        "https://example.com/",
    )

    zendriver.fetch(
        "https://example.com/",
        RungContext(jar_in=jar_in, jar_out=jar_out),
    )

    assert calls == ["set_all", "get", "get_all", "stop"], "load, fetch, save, then stop"
    assert sent[0]["name"] == "cf_clearance"
    assert sent[0]["value"] == "carried"
    assert sent[0]["path"] == "/account"
    assert sent[0]["http_only"] is True
    assert sent[0]["same_site"].value == "Strict"
    saved = jars.load(jar_out, "https://example.com/")
    assert [cookie.value for cookie in saved] == ["earned"]
    assert saved[0].path == "/" and saved[0].http_only is True
