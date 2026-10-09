"""Escalation order and the per-rung kill budget.

Both are properties of the ladder rather than of any one rung, so they are
asserted here against the registry every rung must be in and against the one
budget the parent enforces.
"""

from __future__ import annotations

import pytest

from ladder_cli import cli
from ladder_cli.rungs import MODULES, RUNGS


def test_the_climb_starts_cheap_and_only_reaches_for_a_browser_when_it_must() -> None:
    # ladder.py:15 `RUNGS = ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]`
    assert RUNGS == ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")


def test_rung_one_is_still_the_only_free_rung() -> None:
    """The 80-in-100 case pays rung 1's cost alone (04-tdd 1.4)."""
    assert RUNGS[0] == "http"
    assert len(RUNGS) == 4


def test_every_rung_in_the_climb_is_reachable() -> None:
    assert set(MODULES) == set(RUNGS), "a rung in the climb with no module is a dead step"


def test_each_module_speaks_the_rung_protocol() -> None:
    for name, module in MODULES.items():
        assert callable(getattr(module, "fetch", None)), f"{name} cannot fetch"
        assert callable(getattr(module, "judge", None)), f"{name} cannot judge"


def test_every_rung_is_killed_by_the_same_measured_budget() -> None:
    # ladder.py:182 `p.communicate(timeout=90)` then `os.killpg(p.pid, signal.SIGKILL)`
    assert cli.DEFAULT_RUNG_TIMEOUT_S == 90.0


@pytest.mark.parametrize("rung", RUNGS)
def test_no_rung_carries_its_own_budget(rung: str) -> None:
    """One deadline, one owner: the parent enforces it, so a rung cannot drift.

    LADDER_RUNG_TIMEOUT_S used to give the child a second owner of the same
    deadline and no test ever exercised it (f2cf1cd removed it).
    """
    module = MODULES[rung]
    assert not hasattr(module, "TIMEOUT_S"), f"{rung} re-owns a budget the parent enforces"
    assert not hasattr(module, "RUNG_TIMEOUT_S"), f"{rung} re-owns a budget the parent enforces"