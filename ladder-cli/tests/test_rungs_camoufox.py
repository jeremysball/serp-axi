"""Rung 2 (Camoufox) against the constants the measured run recorded.

The browser is never launched here. What is testable without a browser is the
configuration the launch is built from, the sequence of what is asked of the
page, and the verdict rules applied to what comes back, so all three are
asserted and the launch itself stays a thin wrapper.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from ladder_cli.rungs import camoufox


def test_the_launch_carries_the_measured_fingerprint_settings() -> None:
    # ladder.py:71 `Camoufox(headless=True, humanize=True)`
    assert camoufox.launch_options() == {"headless": True, "humanize": True}
    assert camoufox.HEADLESS is True
    assert camoufox.HUMANIZE is True


def test_the_navigation_and_settle_budgets_are_the_measured_ones() -> None:
    # ladder.py:73 `p.goto(url, wait_until="domcontentloaded", timeout=30000)`
    assert camoufox.GOTO_TIMEOUT_MS == 30000
    # ladder.py:74 `p.wait_for_timeout(12000)`
    assert camoufox.SETTLE_MS == 12000


def test_rung_two_is_registered_under_its_wire_name() -> None:
    from ladder_cli.rungs import MODULES, RUNGS

    assert "camoufox" in RUNGS
    assert MODULES["camoufox"] is camoufox


def test_the_measured_navigation_and_settle_are_what_fetch_actually_uses(monkeypatch) -> None:
    """The constants are only worth having if fetch applies them.

    Asserted as the call sequence, so dropping the settle or widening the
    navigation budget fails here rather than passing as a still-true comment.
    """
    calls: list = []

    class FakeResponse:
        status = 200

    class FakePage:
        def goto(self, url: str, **kwargs: object) -> FakeResponse:
            calls.append(("goto", url, kwargs))
            return FakeResponse()

        def wait_for_timeout(self, ms: int) -> None:
            calls.append(("wait", ms))

        def evaluate(self, expression: str) -> tuple[str, str]:
            calls.append(("evaluate", expression))
            return ("Title", "body text")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            calls.append(("new_page",))
            return FakePage()

    class FakeCamoufox:
        def __init__(self, **kwargs: object) -> None:
            calls.append(("launch", kwargs))

        def __enter__(self) -> FakeBrowser:
            calls.append(("enter",))
            return FakeBrowser()

        def __exit__(self, *exc: object) -> None:
            calls.append(("exit",))

    fake_sync_api = SimpleNamespace(Camoufox=FakeCamoufox)
    monkeypatch.setitem(sys.modules, "camoufox", SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync_api)

    page = camoufox.fetch("https://example.com/")

    assert page == {"title": "Title", "text": "body text", "status": 200}
    assert calls == [
        ("launch", {"headless": True, "humanize": True}),
        ("enter",),
        ("new_page",),
        ("goto", "https://example.com/", {"wait_until": "domcontentloaded", "timeout": 30000}),
        ("wait", 12000),
        ("evaluate", camoufox.STRIP_JS),
        ("exit",),
    ]


def test_a_navigation_that_returns_no_response_leaves_the_status_unknown(monkeypatch) -> None:
    """zendriver reports no status; Camoufox only does when it got one."""

    class FakePage:
        def goto(self, url: str, **kwargs: object) -> None:
            return None

        def wait_for_timeout(self, ms: int) -> None: ...

        def evaluate(self, expression: str) -> tuple[str, str]:
            return ("Title", "body text")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

    class FakeCamoufox:
        def __init__(self, **kwargs: object) -> None: ...

        def __enter__(self) -> FakeBrowser:
            return FakeBrowser()

        def __exit__(self, *exc: object) -> None: ...

    fake_sync_api = SimpleNamespace(Camoufox=FakeCamoufox)
    monkeypatch.setitem(sys.modules, "camoufox", SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync_api)

    assert camoufox.fetch("https://example.com/") == {"title": "Title", "text": "body text", "status": None}


def test_the_browser_is_closed_even_when_the_page_raises(monkeypatch) -> None:
    """A leaked Camoufox holds a patched Firefox until the process exits."""
    state = {"closed": False}

    class FakePage:
        def goto(self, url: str, **kwargs: object) -> None:
            raise RuntimeError("navigation failed")

        def wait_for_timeout(self, ms: int) -> None: ...

        def evaluate(self, expression: str) -> tuple[str, str]:
            return ("", "")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

    class FakeCamoufox:
        def __init__(self, **kwargs: object) -> None: ...

        def __enter__(self) -> FakeBrowser:
            return FakeBrowser()

        def __exit__(self, *exc: object) -> None:
            state["closed"] = True

    fake_sync_api = SimpleNamespace(Camoufox=FakeCamoufox)
    monkeypatch.setitem(sys.modules, "camoufox", SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync_api)

    try:
        camoufox.fetch("https://example.com/")
    except RuntimeError:
        pass
    assert state["closed"] is True