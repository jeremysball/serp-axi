"""What /proc and `kill(pid, 0)` say about a process, asked through one module.

Three callers used to carry their own copy of these two questions (the rung
group check, the profile lock cleanup and the display lock check), and the
copies had already drifted once: one of them forgot that `os.kill` raises
OverflowError for a pid past a pid_t. These tests are the one place the answers
are pinned; the callers' own tests check what each does with them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ladder_cli import procfs


def _fake_stat(root: Path, pid: int, state: str, pgrp: int, comm: str = "name") -> None:
    (root / str(pid)).mkdir()
    (root / str(pid) / "stat").write_text(f"{pid} ({comm}) {state} 1 {pgrp} {pgrp} 0 -1 4194560 0 0 0 0\n")


def test_read_stat_takes_the_state_and_group_after_the_last_parenthesis(monkeypatch, tmp_path) -> None:
    """The comm field is a process name, so it can hold spaces and parentheses of its own."""
    monkeypatch.setattr(procfs, "PROC", tmp_path)
    _fake_stat(tmp_path, 321, "Z", 77, comm="a (b) c d")

    assert procfs.read_stat(321) == procfs.Stat(state="Z", pgrp=77)


def test_read_stat_agrees_with_the_kernel_about_this_process() -> None:
    stat = procfs.read_stat(os.getpid())

    assert stat.state in "RSD"
    assert stat.pgrp == os.getpgid(0)


def test_read_stat_says_a_missing_process_is_gone_with_an_oserror(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(procfs, "PROC", tmp_path)

    with pytest.raises(FileNotFoundError):
        procfs.read_stat(999_999)


def test_read_stat_rejects_a_stat_it_cannot_parse_with_a_valueerror(monkeypatch, tmp_path) -> None:
    """Callers catch (OSError, ValueError); a bare IndexError would slip through both."""
    monkeypatch.setattr(procfs, "PROC", tmp_path)
    (tmp_path / "555").mkdir()
    (tmp_path / "555" / "stat").write_text("no closing parenthesis here")

    with pytest.raises(ValueError, match="stat"):
        procfs.read_stat(555)


def test_probe_a_running_process_exists() -> None:
    assert procfs.probe(os.getpid()) is procfs.Liveness.EXISTS


def test_probe_a_reaped_process_is_gone() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()

    assert procfs.probe(child.pid) is procfs.Liveness.GONE


def test_probe_a_zombie_still_exists() -> None:
    """`kill(pid, 0)` succeeds on a zombie; telling it apart is the caller's choice, not the probe's."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)

        assert procfs.probe(child.pid) is procfs.Liveness.EXISTS
    finally:
        child.wait()


@pytest.mark.parametrize("pid", [2**31, 10**20])
def test_probe_a_pid_too_large_to_ask_about_is_unknown(pid: int) -> None:
    """`os.kill` raises OverflowError, not a lookup error, past what fits a pid_t."""
    assert procfs.probe(pid) is procfs.Liveness.UNKNOWN


@pytest.mark.skipif(os.getuid() == 0, reason="root may signal PID 1")
def test_probe_a_process_we_may_not_signal_is_unknown() -> None:
    """PID 1 exists and is not ours: that is an answer we cannot get, not an answer of "dead"."""
    assert procfs.probe(1) is procfs.Liveness.UNKNOWN
