"""Rung 4 (headed Chromium under Xvfb) against the measured constants.

Rung 4 is rung 3 with the head taken off and a virtual display in front of it,
so this file asserts the headed half owns only what the spike actually varied:
the display. The page work is rung 3's, which is asserted through the call
rather than through shared names, so a rung 4 that quietly reimplemented the
climb would fail here even if it reused every constant.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from conftest import reaped_pid, unreaped_child
from ladder_cli import cli, procfs, stopping
from ladder_cli.rungs import RungVerdict, headed, zendriver

# The pid a FakeProcess reports. No lock in these tests names it unless the test says so.
FAKE_SERVER_PID = 4242


class FakeProcess:
    def __init__(
        self,
        exit_code: int | None = None,
        stderr: bytes = b"",
        ignores_terminate: bool = False,
        ignores_kill: bool = False,
    ) -> None:
        self.terminated = False
        self.killed = False
        self.waited = False
        self.ignores_terminate = ignores_terminate
        self.ignores_kill = ignores_kill
        self.exit_code = exit_code
        self.stderr = _Reader(stderr)
        self.argv: list[str] = []
        self.pid = FAKE_SERVER_PID
        self.wait_timeouts: list[float | None] = []

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> None:
        self.wait_timeouts.append(timeout)
        # A server that shrugs off SIGTERM only stops waiting on SIGKILL, and one in
        # uninterruptible sleep does not stop for that either, until the call returns.
        if self.ignores_kill and timeout is not None:
            raise subprocess.TimeoutExpired("Xvfb", timeout)
        if self.ignores_terminate and not self.killed and timeout is not None:
            raise subprocess.TimeoutExpired("Xvfb", timeout)
        self.waited = True

    def poll(self) -> int | None:
        return self.exit_code


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.closed = False

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        self.closed = True


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


def test_an_xvfb_collision_after_the_free_check_retries_another_display(monkeypatch) -> None:
    number = headed.free_display(headed.display_for_pid(os.getpid()))
    owner = subprocess.Popen(headed.xvfb_command(number), stderr=subprocess.PIPE)
    popen = subprocess.Popen
    attempts = []

    def record_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        attempts.append(process)
        return process

    try:
        headed._await_display(number, owner)
        monkeypatch.setattr(headed.subprocess, "Popen", record_process)
        monkeypatch.setattr(headed, "display_for_pid", lambda pid: f":{number}")
        # The first check lies, which is the race: it said free and a server got there
        # first. Every later question is answered by the slot itself.
        real_free, asked = headed.display_is_free, []

        def lie_once(candidate: int) -> bool:
            asked.append(candidate)
            return True if len(asked) == 1 else real_free(candidate)

        monkeypatch.setattr(headed, "display_is_free", lie_once)
        monkeypatch.setattr(zendriver, "climb", lambda *args: {"display": os.environ["DISPLAY"]})

        with headed.display("https://example.com/", headed.launch_options()) as page:
            assert page["display"] != f":{number}"
            assert Path(f"/tmp/.X{page['display'][1:]}-lock").exists()
            assert owner.poll() is None
        assert len(attempts) >= 2
        assert all(process.poll() is not None and process.stderr.closed for process in attempts)
    finally:
        # SIGTERM, not kill: the server removes its own lock, which a kill would leave behind
        owner.terminate()
        owner.wait(timeout=10)
        owner.stderr.close()


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
    monkeypatch.setattr(zendriver, "climb", lambda url, options, ctx=None: {"title": "", "text": "", "status": None})

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
    _x11_files_under(monkeypatch, tmp_path)
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
    _x11_files_under(monkeypatch, tmp_path)
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: process)
    monkeypatch.setattr(headed, "display_is_free", lambda number: True)
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.25)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(zendriver, "climb", _boom)

    with pytest.raises(RuntimeError, match="never wrote its lock"):
        headed.fetch("https://example.com/")


def _boom(url: str, options: dict, ctx=None) -> dict:
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

    assert process.terminated, "the display is torn down"
    assert not process.killed, "with SIGTERM, which lets Xvfb remove its own lock"
    assert process.waited, "and reaped, so it is not left as an unreaped child"
    assert process.stderr.closed, "the Xvfb stderr pipe is closed when the climb fails"
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

    def fake_climb(url: str, options: dict, ctx=None) -> dict:
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
    assert process.terminated and process.waited
    assert not process.killed, "a display that stops when asked is not killed"
    assert process.stderr.closed, "the Xvfb stderr pipe is closed after a successful climb"
    assert "DISPLAY" not in os.environ, "nothing is left advertising a killed display"


def free_slot(argv: list[str]) -> int:
    """Pull the slot back out of the argv the helper passed to Xvfb."""
    return int(argv[1].lstrip(":"))


def _x11_files_under(monkeypatch, tmp_path: Path) -> None:
    """Point the lock and socket paths at tmp_path: `.X<n>-lock` and `.X11-unix/X<n>`, as under /tmp."""
    monkeypatch.setattr(headed, "X11_ROOT", tmp_path)
    (tmp_path / ".X11-unix").mkdir(exist_ok=True)


def _socket_in(tmp_path: Path, number: int) -> Path:
    return tmp_path / ".X11-unix" / f"X{number}"


@contextlib.contextmanager
def _listening(address: str | bytes):
    """A unix socket listening at `address`, a path or an abstract name starting with NUL."""
    import socket as socket_module

    server = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        server.bind(address)
        server.listen(4)
        yield
    finally:
        server.close()


def test_a_slot_is_free_once_the_server_that_locked_it_is_gone(monkeypatch, tmp_path) -> None:
    """A SIGKILL, a crash or a reboot leaves the lock behind; Xvfb reclaims such a slot itself.

    So a lock only counts while the pid written in it is alive. Checking that
    the file exists, which this used to do, burns a slot per dead server.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X300-lock").write_text(f"{os.getpid():>10}\n")
    (tmp_path / ".X301-lock").write_text(f"{reaped_pid():>10}\n")

    assert headed.display_is_free(300) is False, "a lock held by a live process is respected"
    assert headed.display_is_free(301) is True, "a lock left by a dead process is not"


def test_a_dead_lock_beside_a_live_listener_does_not_free_the_slot(monkeypatch, tmp_path) -> None:
    """Review finding G6: the lock was trusted over the socket.

    A stale lock of ours says the server that wrote it is gone, which says nothing
    about a different server now listening on the same slot. A real Xvfb on such a
    slot exits "server already running", so the search must not offer it.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X310-lock").write_text(f"{reaped_pid():>10}\n")
    (tmp_path / ".X311-lock").write_text(f"{reaped_pid():>10}\n")

    assert headed.display_is_free(311) is True, "a dead lock with nothing listening is still free"
    with _listening("\0" + os.fspath(_socket_in(tmp_path, 310))):
        assert headed.display_is_free(310) is False, "a dead lock beside a listener is not"
    with _listening(os.fspath(_socket_in(tmp_path, 310))):
        assert headed.display_is_free(310) is False, "nor is one beside a listener on the socket file"


def test_a_listener_with_no_lock_at_all_holds_its_slot(monkeypatch, tmp_path) -> None:
    """The abstract address leaves no file, so the old `exists()` check could not see it."""
    _x11_files_under(monkeypatch, tmp_path)
    assert headed.display_is_free(312) is True, "precondition: nothing at the slot"

    with _listening("\0" + os.fspath(_socket_in(tmp_path, 312))):
        assert headed.display_is_free(312) is False


def test_an_early_exit_is_a_collision_when_the_slot_is_taken_and_a_failure_when_it_is_not(monkeypatch, tmp_path) -> None:
    """Review finding F29: the collision was read off Xvfb's words, which a version or wrapper changes.

    A real Xvfb printed "server already running" for a dead lock beside a live
    listener and "Server is already active" for a live lock (2026-11-03), and a
    third wording would have turned a lost race for one slot into a failed rung
    with 499 free. So the slot is asked, the way the search asked it: taken is a
    collision, whatever Xvfb said, and free is a failure, whatever it said.
    """
    _x11_files_under(monkeypatch, tmp_path)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    words = b"some wording no version of Xvfb has printed\n"
    (tmp_path / ".X316-lock").write_text(f"{os.getpid():>10}\n")

    with pytest.raises(headed._DisplayCollision):
        headed._await_display(316, FakeProcess(exit_code=1, stderr=words))

    with pytest.raises(RuntimeError, match="exited immediately") as raised:
        headed._await_display(317, FakeProcess(exit_code=1, stderr=b"(EE) no screens found\n"))
    assert not isinstance(raised.value, headed._DisplayCollision), "an exit on a free slot is still a failure"


def test_a_lock_that_does_not_name_a_pid_is_treated_as_held(monkeypatch, tmp_path) -> None:
    """Free needs proof the server is dead; a lock we cannot read proves nothing."""
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X302-lock").write_text("not a pid\n")
    (tmp_path / ".X303-lock").write_text("")

    assert headed.display_is_free(302) is False
    assert headed.display_is_free(303) is False
    assert headed.display_is_free(304) is True, "with no lock and no socket the slot is free"


def test_a_socket_file_with_no_lock_holds_its_slot_only_while_something_listens_on_it(monkeypatch, tmp_path) -> None:
    """Review finding F03: a bare socket file used to hold the slot, so each stale one cost a slot for good.

    A real Xvfb started over such a file and removed it on SIGTERM (2026-11-03),
    so it is the listener that holds a slot, not the file.
    """
    _x11_files_under(monkeypatch, tmp_path)
    _socket_in(tmp_path, 305).write_text("")  # a file, as a server killed with -9 leaves

    assert headed.display_is_free(305) is True, "a file nothing answers on is not a server"
    with _listening(os.fspath(_socket_in(tmp_path, 306))):
        assert headed.display_is_free(306) is False, "paired: the same layout with a listener on it is held"


def test_a_slot_that_cannot_be_asked_is_not_offered(monkeypatch, tmp_path) -> None:
    """Free needs proof; a connect that fails for a reason other than "nothing there" proves nothing."""
    _x11_files_under(monkeypatch, tmp_path)
    assert headed.display_is_free(307) is True, "precondition: with nothing there, the slot is free"

    def cannot_say(number: int, timeout_s: float = 1.0) -> bool:
        raise TimeoutError("timed out")

    monkeypatch.setattr(headed, "_accepts_connections", cannot_say)

    assert headed.display_is_free(307) is False


class _ConnectRaises:
    """A socket whose connect fails the way a test names; the rest of the interface is a no-op."""

    error: OSError

    def __init__(self, *args: object) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def settimeout(self, seconds: float) -> None:
        pass

    def connect(self, address: object) -> None:
        raise self.error


@pytest.mark.parametrize(
    ("error", "answer"),
    [
        (FileNotFoundError(2, "No such file or directory"), False),
        (ConnectionRefusedError(111, "Connection refused"), False),
        (TimeoutError("timed out"), "raises"),
        (PermissionError(13, "Permission denied"), "raises"),
    ],
    ids=["no-socket", "refused", "timed-out", "denied"],
)
def test_only_nothing_there_reads_as_not_listening(monkeypatch, error, answer) -> None:
    """Review finding F30: any OSError counted as "not listening", so a timeout on a full backlog freed a busy slot."""
    monkeypatch.setattr(headed.socket, "socket", type("S", (_ConnectRaises,), {"error": error}))

    if answer == "raises":
        with pytest.raises(type(error)):
            headed._accepts_connections(5)
    else:
        assert headed._accepts_connections(5) is answer


def test_a_lock_naming_a_pid_too_large_to_probe_is_treated_as_held(monkeypatch, tmp_path) -> None:
    """`os.kill` raises OverflowError, not ProcessLookupError, past what fits a pid_t.

    That is a lock whose owner cannot be shown dead, and the answer for those is
    "held", not a crash out of the display search.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X307-lock").write_text(f"{2**31:>10}\n")
    (tmp_path / ".X308-lock").write_text(f"{10**20:>10}\n")

    assert headed.display_is_free(307) is False
    assert headed.display_is_free(308) is False


def test_a_lock_longer_than_xvfb_writes_is_treated_as_held(monkeypatch, tmp_path) -> None:
    """Review finding: a bounded read of 64 bytes took the number at the front of a longer file.

    Xvfb writes `"%10d\\n"`, which is eleven bytes (read off a real server's
    lock). A file past the read bound is not one it wrote, so the number at its
    front names no server, and a dead pid there used to free a slot whose lock
    was somebody else's file. Right-aligned in ten columns, then a newline,
    then 100 spaces and text: the first 64 bytes parse as a dead pid.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X317-lock").write_text(f"{reaped_pid():>10}\n" + " " * 100 + "garbage")
    (tmp_path / ".X318-lock").write_text(f"{reaped_pid():>10}\n")

    assert headed.display_is_free(317) is False, "a lock past what Xvfb writes is not read as a pid"
    assert headed.display_is_free(318) is True, "the same pid in the file Xvfb writes is a dead server's"


def test_a_lock_whose_server_we_may_not_signal_is_treated_as_held(monkeypatch, tmp_path) -> None:
    """PermissionError from `os.kill` means the pid exists and belongs to someone else."""
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X309-lock").write_text(f"{reaped_pid():>10}\n")

    def refuse(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(headed.os, "kill", refuse)

    assert headed.display_is_free(309) is False


def test_a_lock_that_vanishes_mid_check_falls_back_to_the_socket(monkeypatch, tmp_path) -> None:
    """A server shutting down removes its lock while its socket may still be there.

    The lock is read once, and a read that finds it gone settles the slot from the
    socket. The stand-in is the read raising FileNotFoundError for a lock that is
    on disk, which is what a removal between the open and anything before it looks like.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X310-lock").write_text(f"{os.getpid():>10}\n")
    (tmp_path / ".X311-lock").write_text(f"{os.getpid():>10}\n")

    def vanished(lock: Path) -> tuple[int, int]:
        raise FileNotFoundError(2, "No such file or directory", os.fspath(lock))

    monkeypatch.setattr(headed, "_read_lock", vanished)

    with _listening(os.fspath(_socket_in(tmp_path, 310))):
        assert headed.display_is_free(310) is False, "the socket still answers, so the slot is not free"
    assert headed.display_is_free(311) is True, "paired: with nothing answering it is"


def test_a_lock_we_could_not_remove_is_treated_as_held(monkeypatch, tmp_path) -> None:
    """/tmp is sticky: a dead server's lock left by another user is not ours to unlink.

    Xvfb would have to start over it by removing it, which is the one thing it
    cannot do there, so the slot is not ours to take. A uid mismatch is faked
    because a test cannot create a file owned by someone else.
    """
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X312-lock").write_text(f"{reaped_pid():>10}\n")
    assert headed.display_is_free(312) is True, "precondition: the same lock is free to its own user"

    someone_else = os.getuid() + 1
    monkeypatch.setattr(headed.os, "getuid", lambda: someone_else)

    assert headed.display_is_free(312) is False


def _returns_within(seconds: float, call, unblock):
    """Run `call` on a thread, so a hang is a failed assertion instead of a stuck suite.

    `unblock` is run if the call is still going after `seconds`, to let the
    thread finish; the caller asserts on the returned `(finished, value)`.
    """
    outcome: list = []
    thread = threading.Thread(target=lambda: outcome.append(call()), daemon=True)
    thread.start()
    thread.join(seconds)
    finished = not thread.is_alive()
    if not finished:
        unblock()
        thread.join(5)
    return finished, outcome[0] if outcome else None


@pytest.fixture
def cleanup():
    """Closes whatever a test opened, even when it fails."""
    with contextlib.ExitStack() as stack:
        yield stack


def _lock_that_is_not_a_plain_file(kind: str, tmp_path: Path, cleanup: contextlib.ExitStack) -> Path:
    """`.X316-lock` as a FIFO, a symlink to a dead server's lock, or a directory.

    "fifo-holding-a-dead-pid" is a FIFO with a dead server's pid already written
    into it, which reads without blocking and parses as a number: only the
    check that the lock is a regular file tells it from a real leftover.
    """
    lock = tmp_path / ".X316-lock"
    if kind in ("fifo", "fifo-holding-a-dead-pid"):
        os.mkfifo(lock)
        if kind == "fifo-holding-a-dead-pid":
            held_open = os.open(lock, os.O_RDWR)
            cleanup.callback(os.close, held_open)
            os.write(held_open, f"{reaped_pid():>10}\n".encode())
    elif kind == "symlink":
        target = tmp_path / "elsewhere"
        target.write_text(f"{reaped_pid():>10}\n")
        lock.symlink_to(target)
    else:
        lock.mkdir()
    return lock


@pytest.mark.parametrize("kind", ["fifo", "fifo-holding-a-dead-pid", "symlink", "directory"])
def test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on(monkeypatch, tmp_path, cleanup, kind) -> None:
    """Review finding: `/tmp` is shared, so what sits at the lock path is not ours to trust.

    Another user can leave a FIFO there, and opening one for reading blocks until
    something writes to it, which would hang the display search for good. A symlink
    is read as whatever it points at. Neither is something Xvfb wrote, so neither
    says its server is dead, and neither may be waited on.
    """
    _x11_files_under(monkeypatch, tmp_path)
    lock = _lock_that_is_not_a_plain_file(kind, tmp_path, cleanup)

    finished, free = _returns_within(
        2.0,
        lambda: headed.display_is_free(316),
        # opens the other end, which lets a reader that was stuck on a FIFO through
        unblock=lambda: os.close(os.open(lock, os.O_WRONLY | os.O_NONBLOCK)),
    )

    assert finished, f"display_is_free blocked on a {kind} at the lock path"
    assert free is False, f"a {kind} at the lock path was read as a dead server's lock"


def test_readiness_does_not_wait_on_a_fifo_at_the_lock_path(monkeypatch, tmp_path, cleanup) -> None:
    """`_await_display` reads the same file, so it has the same hang to avoid."""
    _x11_files_under(monkeypatch, tmp_path)
    lock = _lock_that_is_not_a_plain_file("fifo", tmp_path, cleanup)

    finished, named = _returns_within(
        2.0,
        lambda: headed._lock_names(lock, FAKE_SERVER_PID),
        unblock=lambda: os.close(os.open(lock, os.O_WRONLY | os.O_NONBLOCK)),
    )

    assert finished, "_lock_names blocked on a FIFO"
    assert named is False


def test_readiness_waits_for_the_lock_the_new_server_wrote_not_a_stale_one(monkeypatch, tmp_path) -> None:
    """A slot reclaimed from a dead server still has the old pid in its lock until Xvfb rewrites it.

    `exists()` is true for that file the whole time, so it said "ready" to a
    server that had not yet written anything.
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.2)
    # this test is about which lock counts; whether the socket answers is the next one's
    monkeypatch.setattr(headed, "_accepts_connections", lambda number, timeout_s=1.0: True)
    (tmp_path / ".X313-lock").write_text(f"{reaped_pid():>10}\n")

    with pytest.raises(RuntimeError, match="never wrote its lock"):
        headed._await_display(313, process)

    (tmp_path / ".X313-lock").write_text(f"{process.pid:>10}\n")
    headed._await_display(313, process)


def test_readiness_waits_for_a_socket_that_answers_not_just_the_lock(monkeypatch, tmp_path) -> None:
    """Review finding G4: Xvfb writes its lock before it binds its socket.

    A real Xvfb shows the lock first in a share of starts (the measurement is in
    docs/things-that-look-like-bugs.md). The lock naming our pid is the only thing
    the wait used to ask, so a browser pointed at the display in that gap would
    fail to connect.
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.2)
    (tmp_path / ".X314-lock").write_text(f"{process.pid:>10}\n")

    with pytest.raises(RuntimeError, match="wrote its lock but never accepted a connection"):
        headed._await_display(314, process)

    with _listening(os.fspath(_socket_in(tmp_path, 314))):
        headed._await_display(314, process)


def test_the_readiness_connect_is_held_to_the_time_left_and_never_past_a_second(monkeypatch, tmp_path) -> None:
    """Review finding F25: a slot that never answers could run the wait past its own deadline.

    The connect is given the smaller of a second and what is left. The clock is a
    stand-in that is read three ways in turn: the start (deadline 110.0), then per
    pass the loop check and the time left. Pass one has 0.25 seconds left, pass two
    has ten, and the third loop check is past the deadline.
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X326-lock").write_text(f"{process.pid:>10}\n")
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    now = iter([100.0, 100.0, 109.75, 100.0, 100.0, 110.5])
    monkeypatch.setattr(headed.time, "monotonic", lambda: next(now))
    timeouts: list[float] = []

    def never_answers(number: int, timeout_s: float = 1.0) -> bool:
        timeouts.append(timeout_s)
        return False

    monkeypatch.setattr(headed, "_accepts_connections", never_answers)

    with pytest.raises(RuntimeError, match="wrote its lock but never accepted a connection"):
        headed._await_display(326, process)

    assert timeouts == [0.25, 1.0], "the time left when it was less than a second, a second when it was more"


def test_a_probe_that_cannot_say_is_asked_again_until_the_deadline(monkeypatch, tmp_path) -> None:
    """Review finding F30 on the wait: a connect that fails for a reason other than "nothing there" is not an answer.

    The first ask raises, the second succeeds, and the wait returns instead of
    failing on the first or giving up on the slot.
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    (tmp_path / ".X327-lock").write_text(f"{process.pid:>10}\n")
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    answers = iter([TimeoutError("timed out"), True])

    def flaky(number: int, timeout_s: float = 1.0) -> bool:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(headed, "_accepts_connections", flaky)

    headed._await_display(327, process)

    assert next(answers, "drained") == "drained", "both answers were asked for"


def test_a_lock_that_named_the_server_once_is_not_read_again(monkeypatch, tmp_path) -> None:
    """Once the lock names this server it cannot name another while the server runs, so the wait stops reading it.

    Paired with the test above that a lock naming someone else is read every
    pass: here the file is rewritten to a stranger's pid after the first read and
    the wait still finishes.
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    lock = tmp_path / ".X328-lock"
    lock.write_text(f"{process.pid:>10}\n")
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    asked = []

    def answers_the_second_time(number: int, timeout_s: float = 1.0) -> bool:
        asked.append(number)
        lock.write_text(f"{process.pid + 1:>10}\n")
        return len(asked) == 2

    monkeypatch.setattr(headed, "_accepts_connections", answers_the_second_time)

    headed._await_display(328, process)

    assert asked == [328, 328], "it kept asking the socket after the lock changed, without needing the lock to still name it"


def test_readiness_accepts_a_display_that_only_listens_on_the_abstract_socket(monkeypatch, tmp_path) -> None:
    """Xvfb tolerates a /tmp/.X11-unix it cannot write to and serves on the abstract socket alone.

    Checked against a real Xvfb on 2026-11-03 with the directory bound read-only:
    no file socket, a connect to the abstract one succeeded. Requiring the file
    would have turned that working setup into "never accepted a connection".
    """
    process = FakeProcess()
    _x11_files_under(monkeypatch, tmp_path)
    monkeypatch.setattr(headed.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(headed, "XVFB_READY_TIMEOUT_S", 0.2)
    (tmp_path / ".X315-lock").write_text(f"{process.pid:>10}\n")
    assert not (_socket_in(tmp_path, 315)).exists(), "precondition: there is no socket file"

    with _listening("\0" + os.fspath(_socket_in(tmp_path, 315))):
        headed._await_display(315, process)


def _remove_own_leftovers(number: int, server_pid: int, root: Path = Path("/tmp")) -> None:
    """Delete what a test server left on its slot, unless the lock says it is not ours.

    The slot came from `free_display`, but another process can take it between
    that and this cleanup. If the lock names anyone else, or is gone, the lock and
    socket are theirs or already cleaned up: a server that stopped when asked
    removes both itself, and one that was killed leaves the lock, so a missing
    lock never means a leftover of ours. Deleting the socket then would hand a
    server that took the slot in the meantime a dead display.

    The lock is read the way the code under test reads it (`headed._read_lock`),
    so a FIFO or a symlink another user left at that path is not waited on or
    followed. One window stays: a stranger who replaces the lock between the read
    and the unlink loses it. Closing that needs the check and the removal to be
    one step, which a file system does not offer without renaming a file that
    is not ours; two syscalls on a slot `free_display` had just found free is the
    residue, and it is why this is test cleanup and not a library function.
    """
    lock = root / f".X{number}-lock"
    try:
        owner = headed._read_lock(lock)[1]
    except (OSError, ValueError):
        return
    if owner != server_pid:
        return
    lock.unlink(missing_ok=True)
    (root / ".X11-unix" / f"X{number}").unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("lock_text", "removes_files"),
    [
        (f"{FAKE_SERVER_PID:>10}\n", True),  # ours: a server that was killed leaves exactly this
        (f"{FAKE_SERVER_PID + 1:>10}\n", False),  # a stranger took the slot
        ("not a pid", False),
        (None, False),  # no lock: a clean stop removed both, so there is nothing of ours
    ],
)
def test_test_cleanup_removes_a_slot_only_when_its_lock_still_names_our_server(tmp_path, lock_text, removes_files) -> None:
    """The cleanup of the real-Xvfb tests must not delete a server that took the slot after ours.

    The case that matters is no lock at all: a socket beside it belongs to
    whoever started since, and removing it hands that server a dead display.
    """
    (tmp_path / ".X11-unix").mkdir()
    socket_path = tmp_path / ".X11-unix" / "X315"
    socket_path.write_text("")
    lock = tmp_path / ".X315-lock"
    if lock_text is not None:
        lock.write_text(lock_text)

    _remove_own_leftovers(315, FAKE_SERVER_PID, root=tmp_path)

    assert not socket_path.exists() if removes_files else socket_path.exists()
    assert not lock.exists() if removes_files else lock.exists() == (lock_text is not None)


def test_test_cleanup_does_not_wait_on_a_fifo_at_the_lock_path(tmp_path, cleanup) -> None:
    """Review finding: the cleanup read the lock with `read_text`, which blocks on a FIFO.

    A hung cleanup holds the whole suite, and it ran in a `finally` after the
    test had already failed, which is when the reason for the failure matters most.
    """
    (tmp_path / ".X11-unix").mkdir()
    socket_path = tmp_path / ".X11-unix" / "X319"
    socket_path.write_text("")
    lock = tmp_path / ".X319-lock"
    os.mkfifo(lock)

    finished, _ = _returns_within(
        2.0,
        lambda: _remove_own_leftovers(319, FAKE_SERVER_PID, root=tmp_path),
        unblock=lambda: os.close(os.open(lock, os.O_WRONLY | os.O_NONBLOCK)),
    )

    assert finished, "the cleanup blocked on a FIFO at the lock path"
    assert lock.exists() and socket_path.exists(), "what is not a lock of ours is left alone"


def test_test_cleanup_does_not_follow_a_symlink_at_the_lock_path(tmp_path) -> None:
    """A link to a file holding our server's pid is not our lock: the link is not Xvfb's."""
    (tmp_path / ".X11-unix").mkdir()
    socket_path = tmp_path / ".X11-unix" / "X320"
    socket_path.write_text("")
    target = tmp_path / "elsewhere"
    target.write_text(f"{FAKE_SERVER_PID:>10}\n")
    lock = tmp_path / ".X320-lock"
    lock.symlink_to(target)

    _remove_own_leftovers(320, FAKE_SERVER_PID, root=tmp_path)

    assert lock.is_symlink(), "the link was removed"
    assert socket_path.exists(), "the socket beside a link that is not our lock was removed"


@contextlib.contextmanager
def _real_servers(number: int):
    """Start real Xvfb servers on a slot the test found free, and clean up whatever they leave.

    Yields `start()`, which launches one more. Afterwards every server is killed if
    it is still up, reaped, its stderr pipe closed, and the lock and socket it owned
    removed, so a failed assertion in the middle of a test leaves no display behind.
    """
    servers: list[subprocess.Popen] = []

    def start() -> subprocess.Popen:
        server = subprocess.Popen(headed.xvfb_command(number), stderr=subprocess.PIPE)
        servers.append(server)
        return server

    try:
        yield start
    finally:
        for server in servers:
            if server.poll() is None:
                server.kill()
            server.wait(timeout=10)
            if server.stderr is not None:
                server.stderr.close()
            _remove_own_leftovers(number, server.pid)


def test_a_slot_whose_real_xvfb_was_killed_can_be_started_over() -> None:
    """The finding itself: `display_is_free` said False with no Xvfb alive.

    Run against a real Xvfb because the claim in `_lock_is_held` is about what
    Xvfb does: it starts over the lock a SIGKILL leaves, instead of failing on
    it. A fake cannot say that, and without it freeing the slot would be a
    guess that sends the next fetch to a display that never comes up.
    """
    number = headed.free_display(headed.display_for_pid(os.getpid()))
    lock, socket = Path(f"/tmp/.X{number}-lock"), Path(f"/tmp/.X11-unix/X{number}")
    with _real_servers(number) as start:
        first = start()
        headed._await_display(number, first)
        assert headed.display_is_free(number) is False, "a running server holds its slot"
        first.kill()
        first.wait(timeout=10)
        assert lock.exists(), "precondition: SIGKILL leaves the lock behind"
        assert headed.display_is_free(number) is True

        second = start()
        headed._await_display(number, second)
        assert int(lock.read_text().strip()) == second.pid, "the replacement owns the lock it started over"
        assert headed.display_is_free(number) is False
        headed._stop_display(second)
        assert not lock.exists(), "and removes it when stopped"
        assert not socket.exists()


def _lock_naming(number: int, pid: int) -> Path:
    """Write `/tmp/.X<n>-lock` the way Xvfb does, for a slot the test found free."""
    lock = Path(f"/tmp/.X{number}-lock")
    lock.write_text(f"{pid:>10}\n")
    return lock


def test_a_lock_naming_a_zombie_is_held_until_it_is_reclaimed_and_then_the_real_server_starts(monkeypatch) -> None:
    """Review finding F02: a server killed and orphaned to a PID 1 that never waits leaves a lock that nothing removes.

    Measured against a real Xvfb on 2026-11-03: over a lock naming a zombie it
    exits 1, "Server is already active for display ... remove /tmp/.X<n>-lock",
    where over a lock naming a reaped pid it starts. So the search removes such a
    lock and then offers the slot, and this runs the real server over the result.
    """
    number = headed.free_display(headed.display_for_pid(os.getpid()))
    zombie = unreaped_child()
    lock = _lock_naming(number, zombie.pid)
    try:
        with _real_servers(number) as start:
            assert procfs.read_stat(zombie.pid).state == "Z", "precondition: the owner is a zombie, not gone"
            assert headed.display_is_free(number) is False, "precondition: until reclaimed, the zombie's lock holds the slot"

            assert headed.free_display(f":{number}") == number, "the search reclaims it and offers the same slot"
            assert not lock.exists()

            server = start()
            headed._await_display(number, server)
            assert int(lock.read_text().strip()) == server.pid
            headed._stop_display(server)
            assert not lock.exists(), "and the server it started removes its own lock when stopped"
    finally:
        zombie.wait()
        if lock.exists() and lock.read_text().strip() == str(zombie.pid):
            lock.unlink()


def test_only_a_zombies_lock_is_reclaimed(monkeypatch, tmp_path) -> None:
    """The three locks the reclaim must leave alone, beside the one it removes.

    A running owner is a live server; a reaped owner is `display_is_free`'s to call
    free, since Xvfb starts over it; and a lock another user wrote is not ours to
    unlink. Each of the three is paired with the zombie whose lock goes.
    """
    _x11_files_under(monkeypatch, tmp_path)
    zombie = unreaped_child()
    try:
        for number, pid in ((320, os.getpid()), (321, reaped_pid()), (322, zombie.pid)):
            (tmp_path / f".X{number}-lock").write_text(f"{pid:>10}\n")

        for number in (320, 321, 322):
            headed._reclaim_zombie_lock(number)

        assert (tmp_path / ".X320-lock").exists(), "a running server's lock stays"
        assert (tmp_path / ".X321-lock").exists(), "a reaped owner's lock stays; Xvfb starts over it"
        assert not (tmp_path / ".X322-lock").exists(), "a zombie's lock goes"

        (tmp_path / ".X323-lock").write_text(f"{zombie.pid:>10}\n")
        real_read = headed._read_lock

        def another_users_lock(lock: Path) -> tuple[int, int]:
            owner, pid = real_read(lock)
            return owner + 1, pid

        monkeypatch.setattr(headed, "_read_lock", another_users_lock)
        headed._reclaim_zombie_lock(323)
        assert (tmp_path / ".X323-lock").exists(), "a zombie's lock written by another user stays"
    finally:
        zombie.wait()


def test_the_slot_search_reclaims_a_zombies_lock_and_offers_the_slot(monkeypatch, tmp_path) -> None:
    """`free_display` is where the reclaim is called from, and nothing else here calls it that way.

    The real-server test above runs the same path, but it needs `/tmp/.X*-lock`
    to be writable, so it cannot run where the mutation gate runs the suite.
    This one does the same through a directory the test owns.
    """
    _x11_files_under(monkeypatch, tmp_path)
    zombie = unreaped_child()
    try:
        lock = tmp_path / ".X330-lock"
        lock.write_text(f"{zombie.pid:>10}\n")
        assert headed.display_is_free(330) is False, "precondition: until reclaimed, a zombie's lock holds the slot"

        assert headed.free_display(":330") == 330
        assert not lock.exists()
    finally:
        zombie.wait()


def test_a_lock_that_goes_away_while_it_is_being_reclaimed_is_not_an_error(monkeypatch, tmp_path) -> None:
    """Review finding F02's race: the zombie is reaped, or the lock removed, between the read and the unlink."""
    _x11_files_under(monkeypatch, tmp_path)

    headed._reclaim_zombie_lock(324)  # no lock at all

    zombie = unreaped_child()
    try:
        (tmp_path / ".X325-lock").write_text(f"{zombie.pid:>10}\n")
        real_unlink = Path.unlink

        def racing_unlink(path: Path, missing_ok: bool = False) -> None:
            real_unlink(path)  # the other party got there first ...
            real_unlink(path, missing_ok=missing_ok)  # ... so ours finds nothing

        monkeypatch.setattr(Path, "unlink", racing_unlink)
        headed._reclaim_zombie_lock(325)
    finally:
        zombie.wait()
    assert not (tmp_path / ".X325-lock").exists()


def test_a_real_xvfb_starts_over_a_socket_file_left_by_a_killed_server() -> None:
    """Review finding F03, against the real server: the file alone does not hold a slot.

    A killed server leaves its socket file. `display_is_free` used to call that
    held, so each one used a slot for good. A real Xvfb starts over it, writes its
    own lock, and on SIGTERM removes both (measured 2026-11-03), so the slot is free.
    """
    import socket as socket_module

    number = headed.free_display(headed.display_for_pid(os.getpid()))
    path = headed.socket_path(number)
    stale = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        with _real_servers(number) as start:
            stale.bind(os.fspath(path))
            stale.close()  # a bound socket closed without unlink leaves the file, as a SIGKILL does
            assert path.exists() and not headed.lock_path(number).exists(), "precondition: a file and no lock"
            assert headed.display_is_free(number) is True

            server = start()
            headed._await_display(number, server)
            assert headed.display_is_free(number) is False, "paired: with the real server up, the same slot is held"
            headed._stop_display(server)
            assert not path.exists() and not headed.lock_path(number).exists()
    finally:
        stale.close()
        path.unlink(missing_ok=True)


def test_a_rung_killed_on_its_budget_leaves_no_display_lock_behind(tmp_path) -> None:
    """Review finding: the timeout path SIGKILLed the whole group, Xvfb included.

    `run_rung_isolated` is the real one, with a stand-in child that only starts
    a real Xvfb and hangs, so the budget expires with a display up. Nothing here
    depends on the rest of the rung.
    """
    from ladder_cli import cli

    number = headed.free_display(headed.display_for_pid(os.getpid()))
    lock, socket = Path(f"/tmp/.X{number}-lock"), Path(f"/tmp/.X11-unix/X{number}")
    marker = tmp_path / "up"
    child = (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "marker, number = Path(sys.argv[1]), sys.argv[2]\n"
        "server = subprocess.Popen(sys.argv[3:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "lock = Path(f'/tmp/.X{number}-lock')\n"
        "while True:\n"
        "    try:\n"
        "        if int(lock.read_text().strip()) == server.pid:\n"
        "            break\n"
        "    except (FileNotFoundError, ValueError):\n"
        "        pass\n"
        "    time.sleep(0.01)\n"
        "marker.write_text(str(server.pid))\n"
        "time.sleep(60)\n"
    )
    server_pid = None
    try:
        result = cli.run_rung_isolated(
            "headed",
            "https://example.com/",
            timeout_s=2.0,
            argv=[sys.executable, "-c", child, str(marker), str(number), *headed.xvfb_command(number)],
        )
        assert marker.exists(), "precondition: the display was up before the budget ran out"
        server_pid = int(marker.read_text())
        assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
        assert not lock.exists(), "the display lock outlived the rung that was killed"
        assert not socket.exists(), "and so did its socket"
    finally:
        if server_pid is not None:
            _remove_own_leftovers(number, server_pid)


def test_a_real_display_leaves_no_lock_behind_when_it_is_torn_down(monkeypatch) -> None:
    """The lock is Xvfb's to remove, and SIGKILL denies it the chance.

    Killing the server on every exit left one lock per headed fetch until the
    500 slots ran out, at which point rung 4 failed with "no free Xvfb display".
    """
    seen: dict = {}

    def climb(url: str, options: dict, ctx=None) -> dict:
        number = os.environ["DISPLAY"].lstrip(":")
        seen["lock"] = Path(f"/tmp/.X{number}-lock")
        seen["socket"] = Path(f"/tmp/.X11-unix/X{number}")
        seen["lock_while_up"] = seen["lock"].exists()
        return {"title": "", "text": "", "status": None}

    monkeypatch.setattr(zendriver, "climb", climb)

    headed.fetch("https://example.com/")

    assert seen["lock_while_up"], "the display has a lock while it is up"
    assert not seen["lock"].exists(), "and none once it has been torn down"
    assert not seen["socket"].exists(), "nor a socket"


def _fetch_with(monkeypatch, process: FakeProcess) -> None:
    """Run a fetch whose Xvfb is `process`, with the display search and the readiness wait out of the way."""
    monkeypatch.setattr(headed.subprocess, "Popen", lambda argv, **kw: process)
    monkeypatch.setattr(headed, "free_display", lambda preferred: 305)
    monkeypatch.setattr(headed, "_await_display", lambda number, proc: None)
    monkeypatch.setattr(zendriver, "climb", lambda url, options, ctx=None: {"title": "", "text": "", "status": None})
    headed.fetch("https://example.com/")


def test_a_display_that_ignores_sigterm_is_killed_after_the_grace_period(monkeypatch) -> None:
    """Asking first must not mean waiting forever on a server that will not stop."""
    process = FakeProcess(ignores_terminate=True)
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.01)

    _fetch_with(monkeypatch, process)

    assert process.terminated, "it is asked to stop first"
    assert process.killed, "and killed when it does not"
    assert process.waited, "and reaped either way"


def test_the_display_waits_for_the_one_grace_period_the_group_stop_uses(monkeypatch) -> None:
    """Review findings F09 and F10: the grace period has one home, and a stop reads it when it runs.

    The old check compared three module attributes with `==`, which holds for any
    three copies of 5.0. This one sets the single constant and watches what each
    wait is given, so a stop that kept a number of its own would not see it.
    """
    assert not hasattr(headed, "STOP_GRACE_S"), "the display stop has no grace period of its own"
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 7.25)
    process = FakeProcess()

    _fetch_with(monkeypatch, process)

    assert process.wait_timeouts == [7.25]


def test_the_kill_is_followed_by_a_bounded_wait_that_names_the_server_it_could_not_reap(monkeypatch) -> None:
    """Review finding F13: an unbounded wait after SIGKILL held the rung's result for as long as the server stayed in D state.

    A server that ignores SIGTERM and is still there after SIGKILL is raised,
    not waited on, and the message names the pid and the period.
    """
    process = FakeProcess(ignores_terminate=True, ignores_kill=True)
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.5)
    monkeypatch.setattr(stopping, "KILL_WAIT_S", 0.5)

    with pytest.raises(RuntimeError, match=rf"Xvfb \(pid {FAKE_SERVER_PID}\) did not exit within 0\.5s of SIGKILL"):
        headed._stop_display(process)

    assert process.killed
    assert process.wait_timeouts == [0.5, 0.5], "the wait for SIGTERM, then the bounded wait for SIGKILL"
    assert all(timeout is not None for timeout in process.wait_timeouts), "no wait is without a limit"


def test_the_stderr_pipe_is_closed_even_when_the_display_could_not_be_reaped(monkeypatch) -> None:
    """The stop raises for a server that survives SIGKILL; the pipe it was reading must still be closed.

    Two descriptors per display leak into the resident CLI otherwise, one for each
    rung 4 that met an unkillable server.
    """
    process = FakeProcess(ignores_terminate=True, ignores_kill=True)
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.01)

    with pytest.raises(RuntimeError, match="did not exit within"):
        _fetch_with(monkeypatch, process)

    assert process.killed, "precondition: the stop reached the kill and raised from it"
    assert process.stderr.closed, "the pipe was left open by the raise"


def test_a_server_that_exits_on_sigterm_is_not_killed() -> None:
    """The pair for the two kill tests: a server that stops when asked keeps its lock cleanup, so no SIGKILL."""
    process = FakeProcess()

    headed._stop_display(process)

    assert process.terminated and process.waited
    assert not process.killed, "SIGKILL denies Xvfb the chance to remove its lock"


def test_xvfb_is_started_in_the_rungs_own_process_group(monkeypatch) -> None:
    """Review finding F36: the stop path leans on Xvfb being in the rung's group, so the spawn is pinned.

    The rung runs in a group of its own, and the group's SIGTERM and SIGKILL are
    what reach an Xvfb that the display's own stop never got to. A
    `start_new_session` here would put it in a group of its own, out of their reach.
    """
    seen: dict[str, Any] = {}

    def popen(argv, **kwargs):
        seen.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(headed.subprocess, "Popen", popen)
    monkeypatch.setattr(headed, "free_display", lambda preferred: 305)
    monkeypatch.setattr(headed, "_await_display", lambda number, proc: None)
    monkeypatch.setattr(zendriver, "climb", lambda url, options, ctx=None: {"title": "", "text": "", "status": None})

    headed.fetch("https://example.com/")

    assert seen, "precondition: Xvfb was spawned"
    assert not seen.get("start_new_session"), "Xvfb must stay in the rung's group"
    assert "process_group" not in seen and "preexec_fn" not in seen, "and no other way of leaving it"


def test_a_sigterm_that_lands_while_the_display_is_stopping_still_kills_it() -> None:
    """Review finding H9: only the group stop kept its SIGKILL when SIGTERM landed mid-stop.

    `main` turns SIGTERM into SystemExit, which can surface in the display's wait.
    The display stop used to send the kill after the wait, so that SystemExit left
    an Xvfb that ignored the first request running, with its lock held. The stop is
    now the routine the group stop uses, so the kill is in a `finally`.
    """

    class Interrupted(FakeProcess):
        def wait(self, timeout: float | None = None) -> None:
            if not self.killed and timeout is not None:
                raise SystemExit(128 + 15)
            super().wait(timeout)

    process = Interrupted()

    with pytest.raises(SystemExit):
        headed._stop_display(process)

    assert process.terminated, "it was asked to stop before the interruption"
    assert process.killed, "and killed anyway, since the wait did not end with it gone"
    assert process.waited, "and reaped, so it is not left as an unreaped child"


def test_the_display_and_the_rung_group_are_stopped_by_the_one_routine(monkeypatch) -> None:
    """Review findings G8 and H9: two TERM-then-KILL loops that could drift apart.

    Both stops are checked from their own side: each hands the shared routine its
    callbacks, and the routine is the only thing that orders the request and the
    kill. A stop that went back to carrying its own loop would not reach the
    stand-in. The routine takes no grace period, so neither call can pass one.
    """
    calls: list[dict[str, Any]] = []

    def standin(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(stopping, "stop_with_grace", standin)

    headed._stop_display(FakeProcess())
    group_process = subprocess.Popen(
        [sys.executable, "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        cli._stop_group(group_process)
    finally:
        # The stand-in stopped nothing, and the child is a real one.
        group_process.kill()
        group_process.communicate()

    assert len(calls) == 2, "each stop went through the shared routine once"
    for call in calls:
        assert {"term", "wait_gone", "kill"} <= set(call)
    assert calls[1]["always_kill"] is True, "the group's missed-member kill is the routine's, not a line after it"


def test_the_turnstile_click_is_not_restated() -> None:
    """Rung 4 routes through rung 3's climb, so it declares no click of its own.

    A `cf_options` here would be a second owner of one click and the two halves
    could drift without any test noticing.
    """
    assert not hasattr(headed, "cf_options")
    assert not hasattr(headed, "CF_CLICK_DELAY_S")
    assert not hasattr(headed, "verify_cf")
