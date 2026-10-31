"""Escalation order and the per-rung kill budget.

Both are properties of the ladder rather than of any one rung, so they are
asserted here against the registry every rung must be in and against the one
budget the parent enforces.
"""

from __future__ import annotations

import pathlib
import json
import os
import select
import signal
import socket
import subprocess
from dataclasses import asdict
import sys
import time

import pytest

from ladder_cli import cli
from ladder_cli.rungs import MODULES, RUNGS, RungVerdict


def test_the_climb_starts_cheap_and_only_reaches_for_a_browser_when_it_must() -> None:
    # ladder.py:15 `RUNGS = ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]`.
    assert RUNGS == ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")


def test_ceiling_five_stops_at_the_last_implemented_rung(make_request, monkeypatch) -> None:
    from ladder_cli.rungs import RungResult, headed

    seen = []
    duplicate_fetches = []

    def headed_fetch(url, ctx=None):
        duplicate_fetches.append(url)
        return {"title": "challenge", "text": "captcha", "status": 403}

    monkeypatch.setattr(headed, "fetch", headed_fetch)

    def runner(rung, url, ctx=None):
        seen.append(rung)
        return RungResult(RungVerdict.BLOCKED, reason="challenge")

    response = cli.dispatch(make_request(rungCeiling=5), runner=runner)
    assert seen == ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]
    assert duplicate_fetches == []
    assert response.rungReached == 4
    assert response.verdict == "blocked"


def test_rung_one_is_still_the_only_free_rung() -> None:
    """The 80-in-100 case pays rung 1's cost alone (04-tdd 1.4)."""
    assert RUNGS[0] == "http"


def test_reserved_axes_do_not_change_the_rung_context(make_request):
    from ladder_cli.rungs import RungResult

    calls = []

    def runner(rung, url, ctx=None):
        calls.append((rung, url, ctx))
        return RungResult(RungVerdict.OK, text="content")

    defaults = cli.dispatch(make_request(), runner=runner)
    reserved = cli.dispatch(make_request(tabState="same", cacheState="warm", fingerprintState="stable"), runner=runner)
    assert defaults.verdict == reserved.verdict == "ok"
    assert defaults.text == reserved.text == "content"
    assert calls == [("http", "https://example.com/article", None)] * 2


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

    assert result.verdict is RungVerdict.ERROR, f"a hung {rung} must be killed, not answered"
    assert "exceeded its" in result.reason and "budget" in result.reason
    assert time.monotonic() - started < 5, "the kill must not wait for the child"


def test_terminating_the_resident_reaps_its_active_rung(tmp_path, make_request) -> None:
    address = str(tmp_path / "rung.sock")
    child = (
        "import os, signal, socket; "
        "peer = socket.socket(socket.AF_UNIX); "
        f"peer.connect({address!r}); peer.sendall(str(os.getpid()).encode()); "
        "signal.pause()"
    )
    supervisor = (
        "import sys; from ladder_cli import cli; "
        "run = cli.run_rung_isolated; "
        f"cli.run_rung_isolated = lambda *a, **kw: run(*a, **kw, argv=[sys.executable, '-c', {child!r}]); "
        "cli.main()"
    )
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(address)
        listener.listen(1)
        listener.settimeout(10)
        process = subprocess.Popen(
            [sys.executable, "-c", supervisor], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        rung_pid = None
        try:
            assert json.loads(process.stdout.readline())["ready"] is True
            process.stdin.write(json.dumps(asdict(make_request())) + "\n")
            process.stdin.flush()
            with listener.accept()[0] as peer:
                peer.settimeout(5)
                rung_pid = int(peer.recv(32))
                assert os.getsid(rung_pid) == rung_pid
                process.terminate()
                process.wait(timeout=5)
                readable, _, _ = select.select([peer], [], [], 2)
                assert readable, "terminating the resident left its rung running"
                assert peer.recv(1) == b""
        finally:
            if rung_pid is not None:
                try:
                    os.killpg(rung_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
