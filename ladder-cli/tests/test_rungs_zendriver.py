"""Rung 3 (zendriver + Turnstile click) against the measured constants.

Same rule as rung 2: the CDP browser is never started here, so the launch
configuration and the verdict rules are what gets pinned to the spike's
numbers.
"""

from __future__ import annotations

import sys

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

    def fake_climb(url: str, options: dict) -> dict:
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

        async def evaluate(self, expression: str) -> tuple[str, str]:
            calls.append(("evaluate", expression))
            return ("Title", "body text")

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

    monkeypatch.setitem(sys.modules, "zendriver", FakeZendriver)
    monkeypatch.setenv(profiles.ROOT_ENV, str(tmp_path))

    page = zendriver.fetch("https://example.com/")

    assert page == {"title": "Title", "text": "body text", "status": None}
    assert calls == [
        ("start", {"user_data_dir": str(tmp_path / "zd"), **zendriver.launch_options()}),
        ("get", "https://example.com/"),
        ("sleep", 6),
        ("verify_cf", {"click_delay": 3, "timeout": 20}),
        ("sleep", 6),
        ("evaluate", zendriver.TEXT_EXPRESSION),
        ("stop",),
    ], "a settle is missing on one side of the click"


def test_the_headless_profile_is_the_one_warmed_not_the_headed_one(tmp_path, monkeypatch) -> None:
    """Rung 3 must not spend rung 4's profile: they are separate browsers."""
    seen: dict = {}

    class FakeBrowser:
        async def get(self, url: str):
            seen["profile"] = sorted(p.name for p in (tmp_path).iterdir())

            class Tab:
                async def sleep(self, seconds: float) -> None: ...
                async def verify_cf(self, **kwargs: object) -> None: ...
                async def evaluate(self, expression: str) -> tuple[str, str]:
                    return ("Title", "body text")

            return Tab()

        async def stop(self) -> None: ...

    class FakeZendriver:
        @staticmethod
        async def start(**kwargs: object) -> FakeBrowser:
            seen["dir"] = kwargs["user_data_dir"]
            return FakeBrowser()

    monkeypatch.setitem(sys.modules, "zendriver", FakeZendriver)
    monkeypatch.setenv(profiles.ROOT_ENV, str(tmp_path))

    zendriver.fetch("https://example.com/")

    assert seen["dir"] == str(tmp_path / "zd")
    assert seen["profile"] == ["zd"]