"""Escalation order and the per-rung kill budget.

Both are properties of the ladder rather than of any one rung, so they are
asserted here against the registry every rung must be in and against the one
budget the parent enforces.
"""

from __future__ import annotations

import pathlib
import sys
import time

import pytest

from ladder_cli import cli
from ladder_cli.rungs import MODULES, RUNGS, RungVerdict


def test_the_climb_starts_cheap_and_only_reaches_for_a_browser_when_it_must() -> None:
    # ladder.py:15 `RUNGS = ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]`.
    # One more than the spike: 04-tdd 1.4 puts Whisper in the ladder as the
    # rung-4 fallback, which the measured run kept as a separate harness.
    assert RUNGS == ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf", "whisper")
    assert len(RUNGS) == 5, "rungCeiling 5 must have a rung 5 to stop at"


def test_rung_one_is_still_the_only_free_rung() -> None:
    """The 80-in-100 case pays rung 1's cost alone (04-tdd 1.4)."""
    assert RUNGS[0] == "http"


def test_every_python_file_ends_with_a_newline() -> None:
    """A pre-existing file's missing trailing newline is a regression, not a style nit.

    Every file this CLI shipped with ends in one; a hunk that strips it shows up
    in the diff as a `\\ No newline at end of file` line and nothing fails.
    """
    package = pathlib.Path(cli.__file__).resolve().parent
    tests = package.parent / "tests"
    checked = 0
    for root in (package, tests):
        for path in sorted(root.rglob("*.py")):
            checked += 1
            assert path.read_bytes().endswith(b"\n"), f"{path.relative_to(package.parent)} lost its trailing newline"
    assert checked > 10, f"only {checked} files found; the walk is not covering the package"


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
    """One deadline, one owner, proven by killing the rung rather than by naming it.

    A name blacklist cannot catch the regression this guards: a rung that
    re-introduced its own kill budget under a fresh name would pass one. What is
    actually being asserted is that the *parent's* budget reaches every rung,
    which is observable: hand each rung a child that never speaks and confirm
    the parent kills it and reports the budget.

    LADDER_RUNG_TIMEOUT_S was exactly this defect: a second owner of one
    deadline, with no test that ever exercised it (f2cf1cd removed it).
    """
    # Moon-era timeout is scaled so the test does not wait on the real budget.
    started = time.monotonic()
    result = cli.run_rung_isolated(
        rung,
        "https://example.com/",
        timeout_s=0.3,
        argv=[sys.executable, "-c", "import time; time.sleep(120)"],
    )

    assert result.verdict is RungVerdict.BLOCKED, f"a hung {rung} must be killed, not answered"
    assert "exceeded its" in result.reason and "budget" in result.reason
    assert time.monotonic() - started < 5, "the kill must not wait for the child"
