"""The one SIGTERM-wait-SIGKILL routine both stops share."""

from __future__ import annotations

import pytest

from ladder_cli import stopping
from ladder_cli.stopping import stop_with_grace


def _recorder():
    events: list[object] = []

    def term() -> None:
        events.append("term")

    def kill() -> None:
        events.append("kill")

    return events, term, kill


def test_a_target_that_stops_when_asked_is_never_killed(monkeypatch) -> None:
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 2.5)
    events, term, kill = _recorder()

    def wait_gone(seconds: float) -> bool:
        events.append(("wait", seconds))
        return True

    stop_with_grace(term=term, wait_gone=wait_gone, kill=kill)

    # the positive half of the pair: it was asked, and waited on for the grace period
    assert events == ["term", ("wait", 2.5)]
    assert "kill" not in events


def test_a_target_that_does_not_stop_is_asked_then_waited_on_then_killed_in_that_order(monkeypatch) -> None:
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.75)
    events, term, kill = _recorder()

    def wait_gone(seconds: float) -> bool:
        events.append(("wait", seconds))
        return False

    stop_with_grace(term=term, wait_gone=wait_gone, kill=kill)

    assert events == ["term", ("wait", 0.75), "kill"]


def test_a_sigterm_that_lands_in_the_wait_still_kills_and_still_surfaces() -> None:
    """`main` turns SIGTERM into SystemExit, which can surface in the wait."""
    events, term, kill = _recorder()

    def wait_gone(seconds: float) -> bool:
        raise SystemExit(128 + 15)

    with pytest.raises(SystemExit):
        stop_with_grace(term=term, wait_gone=wait_gone, kill=kill)

    assert events == ["term", "kill"]


def test_a_sigterm_that_lands_in_the_request_to_stop_still_kills_and_still_surfaces() -> None:
    """The request itself can be the call that is interrupted: nothing was sent, the kill is still owed."""
    events: list[object] = []

    def term() -> None:
        raise SystemExit(128 + 15)

    def wait_gone(seconds: float) -> bool:
        events.append("wait")
        return True

    with pytest.raises(SystemExit):
        stop_with_grace(term=term, wait_gone=wait_gone, kill=lambda: events.append("kill"))

    assert events == ["kill"], "no wait ran after the interrupted request, and the kill was still sent"


def test_a_failing_request_to_stop_is_not_swallowed() -> None:
    def term() -> None:
        raise PermissionError("not ours to signal")

    with pytest.raises(PermissionError):
        stop_with_grace(term=term, wait_gone=lambda seconds: True, kill=lambda: None)


def test_the_grace_period_is_read_when_the_stop_runs_and_is_not_a_parameter(monkeypatch) -> None:
    """One home for the number: a stop that took its own would be a second constant to drift."""
    import inspect

    assert "grace_s" not in inspect.signature(stop_with_grace).parameters
    seen: list[float] = []

    monkeypatch.setattr(stopping, "STOP_GRACE_S", 1.5)
    stop_with_grace(term=lambda: None, wait_gone=lambda seconds: seen.append(seconds) or True, kill=lambda: None)
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 9.25)
    stop_with_grace(term=lambda: None, wait_gone=lambda seconds: seen.append(seconds) or True, kill=lambda: None)

    assert seen == [1.5, 9.25]
