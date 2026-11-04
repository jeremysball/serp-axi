"""What /proc and `kill(pid, 0)` say about a process, asked through one module.

Three callers used to carry their own copy of these two questions (the rung
group check, the profile lock cleanup and the display lock check), and the
copies had already drifted once: one of them forgot that `os.kill` raises
OverflowError for a pid past a pid_t. These tests are the one place the answers
are pinned; the callers' own tests check what each does with them.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import reaped_pid, unreaped_child, write_fake_stat
from ladder_cli import procfs


def test_read_stat_takes_the_state_and_group_after_the_last_parenthesis(monkeypatch, tmp_path) -> None:
    """The comm field is a process name, so it can hold spaces and parentheses of its own."""
    monkeypatch.setattr(procfs, "PROC", tmp_path)
    write_fake_stat(tmp_path, 321, "Z", 77, comm="a (b) c d")

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
    assert procfs.probe(reaped_pid()) is procfs.Liveness.GONE


def test_probe_a_zombie_still_exists() -> None:
    """`kill(pid, 0)` succeeds on a zombie; telling it apart is the caller's choice, not the probe's."""
    child = unreaped_child(own_group=False)
    try:
        assert procfs.probe(child.pid) is procfs.Liveness.EXISTS
    finally:
        child.wait()


@pytest.mark.parametrize("pid", [2**31, 10**20])
def test_probe_a_pid_too_large_to_ask_about_is_unknown(pid: int) -> None:
    """`os.kill` raises OverflowError, not a lookup error, past what fits a pid_t."""
    assert procfs.probe(pid) is procfs.Liveness.UNKNOWN


def _may_signal_pid_1() -> bool:
    """Root may, and so may a user who owns PID 1: a user namespace or a bwrap sandbox, where PID 1 is ours."""
    try:
        os.kill(1, 0)
    except (PermissionError, ProcessLookupError):
        return False
    return True


@pytest.mark.skipif(_may_signal_pid_1(), reason="this user may signal PID 1, so it is not a process we may not signal")
def test_probe_a_process_we_may_not_signal_is_unknown() -> None:
    """PID 1 exists and is not ours: that is an answer we cannot get, not an answer of "dead"."""
    assert procfs.probe(1) is procfs.Liveness.UNKNOWN


def test_probe_reads_a_refused_signal_as_unknown_not_as_gone(monkeypatch) -> None:
    """The same mapping with the refusal stood in for, so it is checked where PID 1 is ours too."""

    def refuse(pid: int, sig: int) -> None:
        raise PermissionError(pid, "Operation not permitted")

    monkeypatch.setattr(procfs.os, "kill", refuse)

    assert procfs.probe(4321) is procfs.Liveness.UNKNOWN


@pytest.mark.parametrize("pid", [0, -1])
def test_probe_a_pid_that_is_not_a_process_is_unknown(pid: int) -> None:
    """`kill(0, 0)` is the caller's own group and `kill(-1, 0)` is everyone: both succeed.

    A lock file holding `0` would otherwise read as a live owner, or as a server
    to wait out. Paired with the running process above: this one answers EXISTS.
    """
    assert procfs.probe(os.getpid()) is procfs.Liveness.EXISTS, "precondition: signal 0 does succeed for a real pid"
    assert procfs.probe(pid) is procfs.Liveness.UNKNOWN


def _fake_proc(root: Path, entries: dict[int, tuple[str, int] | None]) -> None:
    """A /proc under `root`: pid -> (state, group), or None for a stat file that cannot be read.

    Reading a directory raises IsADirectoryError, which is an OSError that is
    neither "no such file" nor "no such process": the unreadable case without
    needing a user the test does not have.
    """
    for pid, entry in entries.items():
        if entry is None:
            (root / str(pid) / "stat").mkdir(parents=True)
        else:
            write_fake_stat(root, pid, *entry)


def _sleeper_in_its_own_group() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)


def _stop_sleeper(child: subprocess.Popen) -> None:
    os.killpg(child.pid, signal.SIGKILL)
    child.wait()


def test_a_running_process_in_the_group_keeps_it_running_and_a_zombie_does_not() -> None:
    """The pair that tells the two apart, on the real /proc: same call, one group each."""
    runner = _sleeper_in_its_own_group()
    zombie = unreaped_child()
    try:
        os.killpg(zombie.pid, 0)  # precondition: the kernel still lists the zombie's group

        assert procfs.has_running_member(runner.pid) is True
        assert procfs.has_running_member(zombie.pid) is False
    finally:
        _stop_sleeper(runner)
        zombie.wait()


def test_a_group_is_running_while_it_has_a_member_and_not_once_it_is_gone() -> None:
    child = _sleeper_in_its_own_group()
    try:
        assert procfs.group_is_running(child.pid) is True, "precondition: a running member"
    finally:
        _stop_sleeper(child)

    assert procfs.group_is_running(child.pid) is False


def test_a_group_holding_only_a_zombie_is_not_running_though_killpg_still_finds_it() -> None:
    """The case `killpg(group, 0)` alone gets wrong: a rung's orphan under a PID 1 that never waits."""
    zombie = unreaped_child()
    try:
        os.killpg(zombie.pid, 0)  # precondition: signal 0 succeeds on the zombie's group

        assert procfs.group_is_running(zombie.pid) is False
    finally:
        zombie.wait()


def test_a_group_is_taken_to_be_running_when_proc_cannot_be_listed(monkeypatch, tmp_path) -> None:
    """Review finding: `iterdir()` raised, so a stop on a host without /proc crashed instead of waiting.

    `killpg(group, 0)` has already said something is in the group; with no way
    to look closer that stays the answer, and the grace period then decides.
    """
    child = _sleeper_in_its_own_group()
    try:
        monkeypatch.setattr(procfs, "PROC", tmp_path / "no-such-proc")

        assert procfs.group_is_running(child.pid) is True
        assert procfs.has_running_member(child.pid) is True
    finally:
        _stop_sleeper(child)


def test_a_group_member_whose_state_cannot_be_read_is_not_taken_for_gone(monkeypatch, tmp_path) -> None:
    """Review finding: any OSError on the read counted as "it exited", so SIGKILL could be skipped.

    A process that cannot be read cannot be shown to be a zombie, so if its
    group is ours it counts as running. Its group comes from `getpgid`, which
    does not need the read to succeed.
    """
    child = _sleeper_in_its_own_group()
    try:
        _fake_proc(tmp_path, {child.pid: None})
        monkeypatch.setattr(procfs, "PROC", tmp_path)

        assert procfs.has_running_member(child.pid) is True
    finally:
        _stop_sleeper(child)


def test_an_unreadable_process_in_another_group_does_not_keep_a_group_running(monkeypatch, tmp_path) -> None:
    """The other half of the one above: `hidepid=1` hides other users' processes, and they are not ours."""
    gone = reaped_pid()
    _fake_proc(tmp_path, {os.getpid(): None, 1: ("S", 1)})
    monkeypatch.setattr(procfs, "PROC", tmp_path)

    assert procfs.has_running_member(gone) is False


def test_a_group_is_taken_to_be_running_when_nothing_in_proc_could_be_classified(monkeypatch, tmp_path) -> None:
    """A scan that read nothing has not shown the group gone.

    The listing works but every entry in it is either empty or unreadable and
    already exited, so no process was ever classified as in the group or out of
    it. `killpg` said something is there, so the answer stays "running".
    """
    gone = reaped_pid()
    empty = tmp_path / "empty"
    empty.mkdir()
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    _fake_proc(unreadable, {gone: None})

    for root in (empty, unreadable):
        monkeypatch.setattr(procfs, "PROC", root)
        assert procfs.has_running_member(gone) is True, root.name


@pytest.mark.parametrize(
    ("error", "running"),
    [
        (ProcessLookupError(3, "No such process"), False),
        (FileNotFoundError(2, "No such file"), False),
        (ValueError("not a stat line"), True),
        (PermissionError(13, "Permission denied"), True),
    ],
    ids=["reaped-behind-an-open-file", "exited-before-the-read", "unparseable", "refused"],
)
def test_only_an_exit_reads_as_gone_and_any_other_failed_read_asks_the_kernel(monkeypatch, tmp_path, error, running) -> None:
    """What a failed read of one member's stat means, each kind of failure in turn.

    Reading a stat through a handle opened before the process was reaped raises
    ProcessLookupError, not FileNotFoundError (measured on 2026-11-03), so that
    arm is reachable and it means "exited". An unparseable or refused read
    cannot show the member is a zombie, so `getpgid` is asked and, answering
    "this group", it counts as running. A second member, a zombie, makes the scan
    classify something, so the only difference between the rows is the first
    member's failure.
    """
    group = 4_000_001
    for pid in (11, 12):
        (tmp_path / str(pid)).mkdir()
    monkeypatch.setattr(procfs, "PROC", tmp_path)

    def read_stat(pid: int) -> procfs.Stat:
        if pid == 11:
            raise error
        return procfs.Stat(state="Z", pgrp=group)

    monkeypatch.setattr(procfs, "read_stat", read_stat)
    monkeypatch.setattr(procfs.os, "getpgid", lambda pid: group)

    assert procfs.has_running_member(group) is running
