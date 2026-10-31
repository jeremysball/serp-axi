"""Rung 4 (headed Chromium under Xvfb) against the measured constants.

Rung 4 is rung 3 with the head taken off and a virtual display in front of it,
so this file asserts the headed half owns only what the spike actually varied:
the display. The page work is rung 3's, which is asserted through the call
rather than through shared names, so a rung 4 that quietly reimplemented the
climb would fail here even if it reused every constant.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ladder_cli.rungs import RungVerdict, headed, zendriver


class FakeProcess:
    def __init__(self, exit_code: int | None = None, stderr: bytes = b"") -> None:
        self.killed = False
        self.waited = False
        self.exit_code = exit_code
        self.stderr = _Reader(stderr)
        self.argv: list[str] = []

    def kill(self) -> None:
        self.killed = True

    def wait(self, *args: object) -> None:
        self.waited = True

    def poll(self) -> int | None:
        return self.exit_code


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


def test_rung_four_is_the_headed_variant() -> None:
    # ladder.py:82 `headless=not headed` with headed True
    assert headed.HEADLESS is False
    assert headed.launch_options()["headless"] is False


def test_rung_four_changes_only_the_head() -> None:
    base, variant = zendriver.launch_options(), headed.launch_options()
    assert variant.keys() == base.keys()
    assert [key for key in base if base[key] != variant[key]] == ["headless"]


def test_the_spike_slot_formula_is_only_a_search_start() -> None:
    # ladder.py:105 `disp = f":{200 + os.getpid() % 500}"` names a *preferred*
    # slot. One resident CLI holds several rungs open at once (04-tdd 1.8), and
    # two pids congruent mod 500 would both be handed a display the other owns.
    assert headed.display_for_pid(0) == ":200"
    assert headed.display_for_pid(1234) == f":{200 + 1234 % 500}"
    assert headed.display_for_pid(501) == ":201"


def test_the_virtual_display_command_carries_the_measured_geometry() -> None:
    assert headed.xvfb_command(200) == ["Xvfb", ":200", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"]
    assert headed.XVFB_SCREEN == "1920x1080x24"


def test_the_display_is_not_exposed_to_the_network() -> None:
    # `-nolisten tcp` is a safety property, not a tuning number
    argv = headed.xvfb_command(200)
    assert argv[argv.index("-nolisten") + 1] == "tcp"


def test_the_display_is_given_time_to_come_up_before_the_browser_starts() -> None:
    # ladder.py:109 `time.sleep(1.5)`
    assert headed.XVFB_SETTLE_S == 1.5


def test_a_taken_display_is_stepped_over_rather_than_stolen() -> None:
    """A dead display reads as a browser failure, which is nobody's fault but ours."""
    taken = {200, 201}
    original = headed.display_is_free

    def fake_free(number: int) -> bool:
        return number not in taken

    headed.display_is_free = fake_free
    try:
        assert headed.free_display(":201") == 202
        assert headed.free_display(":200") == 202
    finally:
        headed.display_is_free = original


def test_the_call_site_asks_for_a_free_slot_rather_than_taking_the_pids_own(monkeypatch) -> None:
    """`free_display` is only useful if the thing that spawns Xvfb calls it.

    Testing the helper alone leaves this open: a rung that hard-codes the pid's
    slot again passes a direct `free_display` test while handing two concurrent
    climbs the same display. So the slot is read back out of the Xvfb argv.
    """
    seen: dict = {}
    process = FakeProcess()

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        process.argv = list(argv)
        return process

    monkeypatch.setattr(headed.subprocess, "Popen", fake_popen)
    # The pid's own slot is the one the spike would have used, and it is taken.
    monkeypatch.setattr(headed, "display_is_free", lambda number: number != _own_slot())
    monkeypatch.setattr(headed, "_await_display", lambda number, proc: None)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(zendriver, "climb", lambda url, options: {"title": "", "text": "", "status": None})

    with headed.display("https://example.com/", headed.launch_options()):
        seen["slot"] = int(process.argv[1].lstrip(":"))

    assert seen["slot"] != _own_slot(), "the spawn took the pid's slot even though it was taken"
    assert seen["slot"] >= headed.XVFB_DISPLAY_LOW


def _own_slot() -> int:
    return int(headed.display_for_pid(__import__("os").getpid()).lstrip(":"))


def test_the_search_wraps_once_rather_than_running_past_the_measurable_range() -> None:
    assert headed.XVFB_DISPLAY_LOW <= 200 <= headed.XVFB_DISPLAY_HIGH
    original = headed.display_is_free
    headed.display_is_free = lambda number: number < 299
    try:
        assert headed.free_display(":299") == 200, "wraps to the bottom rather than exhausting"
    finally:
        headed.display_is_free = original


def test_a_rung_four_page_is_judged_by_the_browser_rules() -> None:
    result = headed.judge({"title": "Gone", "text": "nope", "status": 404})
    assert result.verdict is RungVerdict.DEAD


def test_the_display_is_still_given_the_measured_settle_before_the_lock_is_polled(monkeypatch, tmp_path) -> None:
    """ladder.py:109's `time.sleep(1.5)` is the floor, not the whole answer.

    The readiness poll turns it into a floor, which is the point of the poll;
    removing the settle and jumping straight to polling would skip the measured
    wait and win nothing, since a lock that has not appeared yet has not appeared.
    """
    slept: list[float] = []
    monkeypatch.setattr(headed, "Path", lambda path: tmp_path / Path(path).name)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: FakeProcess())
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.05)

    with pytest.raises(RuntimeError, match="never wrote its lock"):
        headed.fetch("https://example.com/")

    assert slept[0] == headed.XVFB_SETTLE_S, "the measured settle is spent before polling"


def test_a_display_that_never_lock_fails_after_the_measured_readiness_window(monkeypatch, tmp_path) -> None:
    """Silence is not readiness: a display with no lock is a dead display.

    The spike's fixed 1.5s sleep stays the floor (XVFB_SETTLE_S) but cannot tell
    a slow display from a dead one, so the lock settles the question. The
    readiness window is shortened rather than the clock faked, so the wait being
    bounded is part of what is tested.
    """
    process = FakeProcess()
    monkeypatch.setattr(headed, "Path", lambda path: tmp_path / Path(path).name)
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: process)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.25)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(zendriver, "climb", _boom)

    with pytest.raises(RuntimeError, match="never wrote its lock"):
        headed.fetch("https://example.com/")


def _boom(url: str, options: dict) -> dict:
    raise AssertionError("the climb must not start against a display that died")


def test_rung_four_is_registered_under_its_wire_name() -> None:
    from ladder_cli.rungs import MODULES, RUNGS

    assert "zendriver_headed_cf" in RUNGS
    assert MODULES["zendriver_headed_cf"] is headed


def test_the_judge_is_the_wrapped_rungs_not_a_restatement() -> None:
    """A wrapper that re-declares its delegate's method can drift from it."""
    assert headed.judge is zendriver.judge


def test_a_display_that_dies_before_the_climb_fails_loudly(monkeypatch) -> None:
    """A fixed sleep cannot tell a slow display from a dead one."""
    process = FakeProcess(exit_code=1, stderr=b"_XSERVTransSocketCreateListener: failed")
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: process)
    monkeypatch.setattr(headed, "_await_display", headed._await_display)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(zendriver, "climb", _boom)

    with pytest.raises(RuntimeError, match="exited immediately"):
        headed.fetch("https://example.com/")


def test_the_display_is_torn_down_and_restored_even_when_the_climb_fails(monkeypatch) -> None:
    process = FakeProcess()
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: process)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(headed, "_await_display", lambda number, proc: None)
    monkeypatch.setenv("DISPLAY", "kept-for-the-next-caller")
    monkeypatch.setattr(zendriver, "climb", _boom)

    with pytest.raises(AssertionError):
        headed.fetch("https://example.com/")

    assert process.killed, "the display is torn down"
    assert process.waited, "and reaped, so it is not left as an unreaped child"
    assert os.environ["DISPLAY"] == "kept-for-the-next-caller", "the caller's display is restored"


def test_the_display_is_reaped_on_success_too(monkeypatch) -> None:
    process = FakeProcess()
    seen: dict = {}

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        process.argv = list(argv)
        return process

    monkeypatch.setattr(headed.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(headed, "_await_display", lambda number, proc: None)
    monkeypatch.delenv("DISPLAY", raising=False)

    def fake_climb(url: str, options: dict) -> dict:
        seen["url"] = url
        seen["options"] = options
        seen["display"] = os.environ.get("DISPLAY")
        return {"title": "Recorded", "text": "body", "status": None}

    monkeypatch.setattr(zendriver, "climb", fake_climb)

    result = headed.fetch("https://example.com/")

    assert result == {"title": "Recorded", "text": "body", "status": None}
    assert seen["url"] == "https://example.com/"
    assert seen["options"] == headed.launch_options()
    assert seen["display"] == f":{free_slot(process.argv)}", "the climb sees the display it was given"
    assert process.killed and process.waited
    assert "DISPLAY" not in os.environ, "nothing is left advertising a killed display"


def free_slot(argv: list[str]) -> int:
    """Pull the slot back out of the argv the helper passed to Xvfb."""
    return int(argv[1].lstrip(":"))


def test_the_turnstile_click_is_not_restated() -> None:
    """Rung 4 routes through rung 3's climb, so it declares no click of its own.

    A `cf_options` here would be a second owner of one click and the two halves
    could drift without any test noticing.
    """
    assert not hasattr(headed, "cf_options")
    assert not hasattr(headed, "CF_CLICK_DELAY_S")
    assert not hasattr(headed, "verify_cf")
