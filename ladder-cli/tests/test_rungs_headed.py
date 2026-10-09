"""Rung 4 (headed Chromium under Xvfb) against the measured constants.

Rung 4 is rung 3 with the head taken off and a virtual display in front of it,
so this file asserts the headed half owns only what the spike actually varied:
the display. The page work is rung 3's, which is asserted through the call
rather than through shared names, so a rung 4 that quietly reimplemented the
climb would fail here even if it reused every constant.
"""

from __future__ import annotations

import os

import pytest

from ladder_cli.rungs import RungVerdict, headed, zendriver


class FakeProcess:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_rung_four_is_the_headed_variant() -> None:
    # ladder.py:82 `headless=not headed` with headed True
    assert headed.HEADLESS is False
    assert headed.launch_options()["headless"] is False


def test_rung_four_changes_only_the_head() -> None:
    base, variant = zendriver.launch_options(), headed.launch_options()
    assert variant.keys() == base.keys()
    assert [key for key in base if base[key] != variant[key]] == ["headless"]


def test_the_display_is_picked_from_the_pid_the_measured_way() -> None:
    # ladder.py:105 `disp = f":{200 + os.getpid() % 500}"`
    assert headed.display_for_pid(1234) == f":{200 + 1234 % 500}"
    assert headed.display_for_pid(0) == ":200"
    assert headed.display_for_pid(501) == ":201"


def test_the_virtual_display_command_carries_the_measured_geometry() -> None:
    # ladder.py:106 `["Xvfb", disp, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"]`
    assert headed.xvfb_command(":200") == ["Xvfb", ":200", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"]
    assert headed.XVFB_SCREEN == "1920x1080x24"


def test_the_display_is_not_exposed_to_the_network() -> None:
    # `-nolisten tcp` is a safety property, not a tuning number
    argv = headed.xvfb_command(":200")
    assert argv[argv.index("-nolisten") + 1] == "tcp"


def test_the_display_is_given_time_to_come_up_before_the_browser_starts() -> None:
    # ladder.py:109 `time.sleep(1.5)`
    assert headed.XVFB_SETTLE_S == 1.5


def test_a_rung_four_page_is_judged_by_the_browser_rules() -> None:
    result = headed.judge({"title": "Gone", "text": "nope", "status": 404})
    assert result.verdict is RungVerdict.DEAD


def test_rung_four_is_registered_under_its_wire_name() -> None:
    from ladder_cli.rungs import MODULES, RUNGS

    assert "zendriver_headed_cf" in RUNGS
    assert MODULES["zendriver_headed_cf"] is headed


def test_rung_four_brings_up_a_display_and_climbs_with_rung_threes_fetch(monkeypatch) -> None:
    started: dict = {}
    process = FakeProcess()

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        started["xvfb"] = list(argv)
        return process

    def fake_climb(url: str, options: dict) -> dict:
        started["climb"] = (url, options)
        return {"title": "Recorded", "text": "body", "status": None}

    monkeypatch.setenv("DISPLAY", "unset")
    monkeypatch.setattr(headed.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: started.setdefault("slept", seconds))
    monkeypatch.setattr(zendriver, "climb", fake_climb)

    result = headed.fetch("https://example.com/")

    assert started["climb"] == ("https://example.com/", headed.launch_options())
    assert started["xvfb"] == headed.xvfb_command(headed.display_for_pid(os.getpid()))
    assert started["slept"] == headed.XVFB_SETTLE_S
    assert os.environ["DISPLAY"] == headed.display_for_pid(os.getpid())
    assert process.killed, "the display is torn down when the climb ends"
    assert result == {"title": "Recorded", "text": "body", "status": None}


def test_the_display_is_torn_down_even_when_the_climb_fails(monkeypatch) -> None:
    """A leaked Xvfb holds a display number until the machine is rebooted."""
    process = FakeProcess()
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kwargs: process)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)

    def boom(url: str, options: dict) -> dict:
        raise RuntimeError("browser went away")

    monkeypatch.setattr(zendriver, "climb", boom)

    with pytest.raises(RuntimeError):
        headed.fetch("https://example.com/")
    assert process.killed


def test_the_turnstile_click_is_not_restated() -> None:
    """Rung 4 routes through rung 3's climb, so it declares no click of its own.

    A `cf_options` here would be a second owner of one click and the two halves
    could drift without any test noticing.
    """
    assert not hasattr(headed, "cf_options")
    assert not hasattr(headed, "CF_CLICK_DELAY_S")
    assert not hasattr(headed, "verify_cf")