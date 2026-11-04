"""Shared fixtures. Nothing here reaches the network."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder_cli.protocol import LadderRequest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))


@pytest.fixture
def make_request():
    """A request carrying the documented defaults, per TDD section 1.2."""

    def build(**overrides: object) -> LadderRequest:
        fields: dict[str, object] = {
            "protocol": 3,
            "url": "https://example.com/article",
            "tabState": "fresh",
            "cookieState": "cold",
            "cacheState": "cold",
            "fingerprintState": "rotate",
            "rungCeiling": 5,
            "profile": None,
            "jarIn": None,
            "jarOut": None,
            "httpJarIn": None,
            "httpJarOut": None,
        }
        fields.update(overrides)
        return LadderRequest.parse(fields)

    return build


class Recorder(list):
    """A call log that reads as a sequence, so a fixture asserts what a rung asked."""

    def __call__(self, entry):
        self.append(entry)
        return entry

    def names(self) -> list[str]:
        return [entry[0] for entry in self]


def reaped_pid() -> int:
    """A pid that belonged to a real process which has exited and been reaped.

    Linux hands pids out in increasing order and reuses one only after the counter
    wraps `pid_max`, so a pid freed a moment ago stays free for the length of a
    test. This checks that instead of trusting it, with a bare `os.kill` and not
    `procfs.probe`, so the tests that assert `probe` calls such a pid gone are not
    checking it against itself.
    """
    for _ in range(5):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        try:
            os.kill(child.pid, 0)
        except ProcessLookupError:
            return child.pid
    pytest.fail("a pid stayed taken after the process that held it was reaped, five times running")


def unreaped_child(*, own_group: bool = True) -> subprocess.Popen:
    """A child that has exited and not been reaped: a zombie, by default alone in a group of its own.

    The caller reaps it with `.wait()`. `os.waitid(..., WNOWAIT)` waits for the exit
    without collecting it, which is what leaves the zombie.
    """
    child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=own_group)
    os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
    return child


def write_fake_stat(root: Path, pid: int, state: str, pgrp: int, comm: str = "name") -> None:
    """One `/proc/<pid>/stat` under `root`, in the shape a real kernel writes.

    Twelve fields rather than the six `read_stat` reads, so a test that builds a
    process table feeds the parser the line it gets in production.
    """
    (root / str(pid)).mkdir()
    (root / str(pid) / "stat").write_text(f"{pid} ({comm}) {state} 1 {pgrp} {pgrp} 0 -1 4194560 0 0 0 0\n")


def inject_module(monkeypatch, name: str, module):
    """Bind a fake library where the rung's deferred import will find it.

    The browser rungs import their tool inside ``fetch`` rather than at module
    scope, so a test replaces it the same way. One helper owns the injection
    because every browser-rung test needed it, and a second copy of a
    monkeypatch is how a rung silently stops being tested at all.
    """
    monkeypatch.setitem(sys.modules, name, module)
    parent, _, child = name.rpartition(".")
    if parent:
        monkeypatch.setitem(sys.modules, parent, types.SimpleNamespace(**{child: module}))
