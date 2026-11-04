"""Shared fixtures. Nothing here reaches the network."""

from __future__ import annotations

import getpass
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder_cli.protocol import LadderRequest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))


def pytest_configure(config):
    """Keep pytest's temporary tree short enough for the unix-socket tests.

    A test's `tmp_path` holds a socket under `.X11-unix/`, and AF_UNIX caps the
    whole path at 107 bytes. Pytest's default layout
    (`$TMPDIR/pytest-of-<user>/pytest-N/<name30>`) spends most of that, so a
    TMPDIR inherited from an XDG state directory leaves no room and the socket
    tests fail with "AF_UNIX path too long" on clean code. An explicit
    `--basetemp` (the mutation gate's) wins; otherwise fall back to /tmp only
    when the default would not fit.

    The estimate follows what pytest will build: it resolves the temporary
    directory through symlinks, names the user `unknown` when the platform has
    none, numbers its runs without bound (`pytest-7`, `pytest-1234`; six digits
    are budgeted here), and truncates a test's directory to 30 characters plus
    a numeric suffix (31 here).
    """
    if config.option.basetemp is not None:
        return
    try:
        user = getpass.getuser()
    except (ImportError, OSError, KeyError):
        user = "unknown"
    default = Path(tempfile.gettempdir()).resolve() / f"pytest-of-{user}" / ("pytest-" + "9" * 6) / ("x" * 31)
    if len(os.fspath(default)) + len("/.X11-unix/X301") <= 107:
        return
    short = tempfile.mkdtemp(prefix="serp-axi-pytest-", dir="/tmp")
    config.add_cleanup(lambda: shutil.rmtree(short, ignore_errors=True))
    config.option.basetemp = short


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


def sleeper_in_its_own_group() -> subprocess.Popen:
    """A live process alone in a group of its own, for the group checks to find."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)


def kill_group(group: int | subprocess.Popen | None) -> None:
    """SIGKILL what is left of a group a test started, and reap its leader.

    A test's cleanup runs in a `finally` after the assertion it was guarding, and
    a group that has already gone raises from `killpg`: that error would replace
    the assertion's failure with a cleanup failure. Both the sleeper tests and
    the CLI tests stopped carrying their own copy to get that.
    """
    if group is None:
        return
    pid = group.pid if isinstance(group, subprocess.Popen) else group
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if isinstance(group, subprocess.Popen):
        group.wait()
    else:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


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
