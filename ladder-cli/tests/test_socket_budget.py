"""The 107-byte unix-socket budget the Python tests and the mutation gate keep to.

The display tests bind a socket at `<tmp_path>/.X11-unix/X<n>`, and AF_UNIX
accepts a path of at most 107 bytes. Two places move their temporary tree to
`/tmp` when an inherited TMPDIR would leave no room: pytest's own tree
(`conftest.pytest_configure`) and the mutation gate's scratch project
(`scripts/mutations._short_temp_root`). These tests ask the kernel, not the
arithmetic, whether each one keeps its promise.

A test here that creates a directory under `/tmp` runs in the ordinary suite
only. The mutation gate's sandbox (`bwrap --ro-bind / /`) mounts `/tmp` read-only:
`tempfile.mkdtemp(dir="/tmp")` fails there with EROFS (checked by running it
under that command), which the gate would count as a false kill. The gate lists
only `test_conftest_moves_pytest_exactly_when_the_socket_would_not_fit`, which
touches nothing outside its own temporary tree.
"""

from __future__ import annotations

import getpass
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from conftest import pytest_configure

LADDER = Path(__file__).resolve().parents[1]
SOCKET_TEST = "tests/test_rungs_headed.py::test_readiness_waits_for_a_socket_that_answers_not_just_the_lock"
LIMIT = 107


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(LADDER.parent / "scripts"))
    import mutations

    return mutations


def _bind(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(os.fspath(path))


def test_the_kernel_takes_a_socket_path_of_107_bytes_and_refuses_108(tmp_path) -> None:
    """The limit every other number in this file is counted against."""
    stem = len(os.fspath(tmp_path)) + 1
    assert stem < LIMIT - 8, "precondition: tmp_path leaves room for a name"
    fits = tmp_path / ("n" * (LIMIT - stem))
    too_long = tmp_path / ("n" * (LIMIT + 1 - stem))
    assert (len(os.fspath(fits)), len(os.fspath(too_long))) == (LIMIT, LIMIT + 1)

    _bind(fits)
    with pytest.raises(OSError, match="path too long"):
        _bind(too_long)


def _kept(gate, monkeypatch, root: Path) -> bool:
    monkeypatch.setattr(tempfile, "gettempdir", lambda: os.fspath(root))
    return gate._short_temp_root() == os.fspath(root)


def test_the_gate_keeps_the_longest_tmpdir_that_still_fits_a_socket_and_moves_a_longer_one(gate, monkeypatch) -> None:
    """The gate's scratch root is the inherited TMPDIR exactly while the longest test socket fits under it.

    Found by asking `_short_temp_root` about roots of growing length, then
    binding a real socket at the path the gate and pytest would build under the
    longest root it kept: `<root>/serp-axi-mutation-XXXXXXXX/bt/<name30>0/.X11-unix/X301`.
    """
    base = Path(tempfile.mkdtemp(prefix="gate-root-", dir="/tmp"))
    try:
        candidates = [base / ("r" * pad) for pad in range(1, LIMIT - len(os.fspath(base)))]
        kept = [root for root in candidates if _kept(gate, monkeypatch, root)]
        assert kept and len(kept) < len(candidates), "precondition: some roots are kept and some are moved"
        longest = kept[-1]
        assert kept == candidates[: len(kept)], "every root shorter than the longest kept one is kept too"
        assert not _kept(gate, monkeypatch, candidates[len(kept)])
        assert gate._short_temp_root() == "/tmp"

        monkeypatch.setattr(tempfile, "gettempdir", lambda: os.fspath(longest))
        longest.mkdir()
        with gate._scratch_project() as project:
            tests_tmp = project.parent / "bt" / ("t" * 31)
            _bind(tests_tmp / ".X11-unix" / "X301")
            assert len(os.fspath(tests_tmp / ".X11-unix" / "X301")) <= LIMIT
            with pytest.raises(OSError, match="path too long"):
                _bind(project.parent / "bt" / ("t" * 32) / ".X11-unix" / "X301")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_gate_measures_a_symlinked_tmpdir_by_where_it_leads(gate, monkeypatch) -> None:
    """A short TMPDIR that is a symlink to a long path puts the gate's sockets at the long path, because pytest resolves it."""
    base = Path(tempfile.mkdtemp(prefix="gl-", dir="/tmp"))
    try:
        long_target = base / ("t" * 70)
        long_target.mkdir()
        short_link = base / "link"
        short_link.symlink_to(long_target)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: os.fspath(short_link))

        assert gate._short_temp_root() == "/tmp"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _pytest_on_a_socket_test(tmpdir: Path, *options: str) -> subprocess.CompletedProcess:
    env = {name: value for name, value in os.environ.items() if name not in ("PYTEST_ADDOPTS", "PYTEST_DEBUG_TEMPROOT")}
    env["TMPDIR"] = os.fspath(tmpdir)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *options, SOCKET_TEST]
    return subprocess.run(command, cwd=LADDER, env=env, capture_output=True, text=True, timeout=120)


def _configure(monkeypatch, tmpdir: Path, basetemp: str | None = None, real: bool = False) -> tuple[types.SimpleNamespace, list]:
    """Run conftest's `pytest_configure` as pytest would, with `tmpdir` as the system temporary directory.

    `mkdtemp` is a stub unless `real`, so that deciding whether to move creates nothing under `/tmp`.
    """
    cleanups: list = []
    config = types.SimpleNamespace(option=types.SimpleNamespace(basetemp=basetemp), add_cleanup=cleanups.append)
    with monkeypatch.context() as patched:
        patched.setattr(tempfile, "gettempdir", lambda: os.fspath(tmpdir))
        if not real:
            patched.setattr(tempfile, "mkdtemp", lambda prefix, dir: "/stub/" + prefix)
        pytest_configure(config)
    return config, cleanups


def _moved(monkeypatch, tmpdir: Path) -> bool:
    config, _ = _configure(monkeypatch, tmpdir)
    return config.option.basetemp is not None


def test_conftest_moves_pytest_exactly_when_the_socket_would_not_fit(monkeypatch) -> None:
    """A TMPDIR is kept while `<tmpdir>/pytest-of-<user>/pytest-<N>/<name31>/.X11-unix/X301` fits in 107 bytes, and moved at one byte more.

    The room is counted here from the layout pytest builds (checked for real by
    the next test), not by calling the code under test.
    """
    monkeypatch.setattr(getpass, "getuser", lambda: "alice")
    tail = "/pytest-of-alice/pytest-999999/" + "x" * 31 + "/.X11-unix/X301"
    room = LIMIT - len(tail)
    assert room > 10, "precondition: the layout leaves room for a TMPDIR"

    assert _moved(monkeypatch, Path("/" + "r" * (room - 1))) is False
    assert _moved(monkeypatch, Path("/" + "r" * room)) is True

def test_pytest_moves_its_tree_to_tmp_when_a_long_tmpdir_would_not_fit_a_socket(tmp_path, monkeypatch) -> None:
    """The same socket test, run with a TMPDIR that is too long, passes only because pytest moved its tree."""
    long_tmpdir = tmp_path / ("t" * 70)
    long_tmpdir.mkdir()
    explicit = _pytest_on_a_socket_test(long_tmpdir, f"--basetemp={long_tmpdir / 'bt'}")
    assert explicit.returncode != 0, "precondition: this TMPDIR really is too long for the socket test"
    assert "path too long" in explicit.stdout, explicit.stdout[-2000:]

    moved = _pytest_on_a_socket_test(long_tmpdir)
    assert moved.returncode == 0, moved.stdout[-2000:] + moved.stderr[-2000:]
    assert "1 passed" in moved.stdout
    assert not (long_tmpdir / f"pytest-of-{getpass.getuser()}").exists(), "pytest used the long TMPDIR anyway"


def test_pytest_keeps_the_longest_tmpdir_that_fits_even_after_many_runs_and_moves_a_longer_one(tmp_path, monkeypatch) -> None:
    """Pytest numbers its run directories without bound (`pytest-10`, `pytest-123`), so the fit is counted with room for that.

    The longest TMPDIR conftest keeps is found by asking it about roots of
    growing length. Pytest is then run there with its newest run directory at
    `pytest-999998`, so the next one is `pytest-999999`, the widest number the
    budget covers, and the socket test has to bind under it.
    """
    base = Path(tempfile.mkdtemp(prefix="sb-", dir="/tmp"))
    try:
        candidates = [base / ("r" * pad) for pad in range(1, LIMIT - len(os.fspath(base)))]
        kept = [root for root in candidates if not _moved(monkeypatch, root)]
        assert kept and len(kept) < len(candidates), "precondition: some roots are kept and some are moved"
        assert kept == candidates[: len(kept)], "every root shorter than the longest kept one is kept too"
        longest, one_more = kept[-1], candidates[len(kept)]

        config, cleanups = _configure(monkeypatch, one_more, real=True)
        try:
            assert Path(config.option.basetemp).parent == Path("/tmp")
            assert Path(config.option.basetemp).name.startswith("serp-axi-pytest-")
        finally:
            for cleanup in cleanups:
                cleanup()
        assert not Path(config.option.basetemp).exists(), "the cleanup removes the directory it made"

        user_dir = longest / f"pytest-of-{getpass.getuser()}"
        (user_dir / "pytest-999998").mkdir(parents=True, mode=0o700)
        result = _pytest_on_a_socket_test(longest)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert (user_dir / "pytest-999999").is_dir(), "precondition: pytest used the TMPDIR it was kept at"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_an_explicit_basetemp_is_left_alone(tmp_path, monkeypatch) -> None:
    """The gate passes `--basetemp`, and a user's own wins too, however long the TMPDIR is."""
    long_tmpdir = tmp_path / ("t" * 70)
    config, cleanups = _configure(monkeypatch, long_tmpdir, basetemp="/somewhere/else")

    assert config.option.basetemp == "/somewhere/else"
    assert cleanups == []


def test_a_missing_user_name_does_not_stop_pytest_starting(tmp_path, monkeypatch) -> None:
    """Pytest itself falls back to `unknown`; the size estimate has to as well, or one container breaks every run."""
    def no_user() -> str:
        raise KeyError("getpwuid(): uid not found: 4242")

    monkeypatch.setattr(getpass, "getuser", no_user)
    long_tmpdir = tmp_path / ("t" * 70)

    assert _moved(monkeypatch, long_tmpdir) is True


def test_a_tmpdir_that_is_a_short_symlink_to_a_long_path_is_measured_by_where_it_leads(tmp_path, monkeypatch) -> None:
    """Pytest resolves the temporary directory before it builds under it, and the socket path is the resolved one."""
    long_target = tmp_path / ("t" * 70)
    long_target.mkdir()
    short_link = Path(tempfile.mkdtemp(prefix="sl-", dir="/tmp")) / "link"
    try:
        short_link.symlink_to(long_target)
        assert len(os.fspath(short_link)) < 40, "precondition: the link itself is short"
        assert _moved(monkeypatch, short_link) is True

        result = _pytest_on_a_socket_test(short_link)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert not (long_target / f"pytest-of-{getpass.getuser()}").exists(), "pytest used the long path anyway"
    finally:
        shutil.rmtree(short_link.parent, ignore_errors=True)
