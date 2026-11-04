"""Handshake, dispatch, and the rung budget."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from ladder_cli import cli, procfs, stopping
from ladder_cli.rungs import RungResult, RungVerdict

from conftest import unreaped_child


# A rung that ignores SIGTERM and writes its pid to the file named in argv[1], so a
# test can tell a stop that asked and waited from one that also killed.
STUBBORN_RUNG = (
    "import os, signal, sys, time\n"
    "from pathlib import Path\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
    "time.sleep(15)\n"
)


def _stubborn_rung(ready) -> list[str]:
    return [sys.executable, "-c", STUBBORN_RUNG, str(ready)]


# A rung with a second process in its group. Both ignore SIGTERM. `_reap` kills the
# leader after the grace period whatever happened before it, so a test that only
# watches the leader cannot tell a group-wide SIGKILL from none at all; the member
# is what only the group-wide SIGKILL reaches. argv: leader pid file, member pid
# file, the member's program (the same one `_stubborn_rung` runs).
STUBBORN_LEADER = (
    "import os, signal, subprocess, sys, time\n"
    "from pathlib import Path\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]])\n"
    "while not Path(sys.argv[2]).exists():\n"
    "    time.sleep(0.01)\n"
    "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
    "time.sleep(15)\n"
)


def _stubborn_family(leader_ready, member_ready) -> list[str]:
    return [sys.executable, "-c", STUBBORN_LEADER, str(leader_ready), str(member_ready), STUBBORN_RUNG]


def _assert_member_was_killed(member_ready) -> None:
    """The member outlives its leader's death unless the whole group was sent SIGKILL.

    SIGKILL lands asynchronously, so the member gets a moment to finish exiting. It
    sleeps 15 seconds, so waiting two never lets a survivor pass for a casualty.
    """
    pid = int(member_ready.read_text())
    deadline = time.monotonic() + 2
    while True:
        try:
            running = procfs.read_stat(pid).state != "Z"
        except (FileNotFoundError, ProcessLookupError):
            running = False
        if not running:
            return
        if time.monotonic() > deadline:
            os.kill(pid, signal.SIGKILL)  # the test's own cleanup, not the code's
            raise AssertionError("the group's second member is still running: the SIGKILL did not reach the group")
        time.sleep(0.02)


def _kill_leftover_group(group: int | None) -> None:
    """The test's own cleanup after a failure left the child running, not the code's."""
    if group is None:
        return
    try:
        os.killpg(group, signal.SIGKILL)
        os.waitpid(group, 0)
    except (ProcessLookupError, ChildProcessError):
        pass


def sequence(*results: RungResult):
    """A runner that answers in order and records which rungs it was asked for."""
    queue = list(results)
    calls: list[str] = []
    jars: list[tuple[str | None, str | None]] = []

    def fake(rung: str, url: str, ctx=None) -> RungResult:
        calls.append(rung)
        jars.append((
            str(ctx.jar_in) if ctx is not None and ctx.jar_in is not None else None,
            str(ctx.jar_out) if ctx is not None and ctx.jar_out is not None else None,
        ))
        return queue.pop(0)

    fake.calls = calls
    fake.jars = jars
    return fake


def ok_result(text: str = "body " * 200) -> RungResult:
    return RungResult(RungVerdict.OK, title="An article", text=text, status=200, reason="enough text")


def refused(reason: str = "status 403") -> RungResult:
    return RungResult(RungVerdict.BLOCKED, status=403, reason=reason)


def payload(request) -> dict:
    return dataclasses.asdict(request)


def read_lines(stdout: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_the_ready_line_precedes_every_response_and_declares_the_protocol() -> None:
    stdout = io.StringIO()
    cli.main([], stdin=io.StringIO(""), stdout=stdout)
    assert read_lines(stdout) == [{"ready": True, "protocol": 3}]


def test_a_request_is_answered_with_a_versioned_response(make_request, monkeypatch) -> None:
    runner = sequence(ok_result("clear enough to read"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    lines = read_lines(stdout)
    assert lines[0]["ready"] is True
    response = lines[1]
    assert response["protocol"] == 3
    assert response["verdict"] == "ok"
    assert response["rungReached"] == 1
    assert response["text"] == "clear enough to read"
    assert runner.calls == ["http"]


def test_dead_ends_the_climb_before_a_stronger_rung_is_tried(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(RungResult(RungVerdict.DEAD, reason="status 404"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "dead"
    assert response.rungReached == 1
    assert runner.calls == ["http"], "a browser cannot revive a page that is gone"


def test_blocked_climbs_until_the_rungs_run_out(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(refused(), refused(), ok_result())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "ok"
    assert response.rungReached == 3
    assert runner.calls == ["http", "camoufox", "zendriver_cf"]


def test_exhausting_every_rung_reports_blocked_not_an_empty_success(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(refused("status 403"), refused("js shell"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "blocked"
    assert response.rungReached == 2
    assert response.warning == "js shell"


def test_the_rung_ceiling_caps_the_climb(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(refused())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request(rungCeiling=1))
    assert response.verdict == "blocked"
    assert response.rungReached == 1
    assert runner.calls == ["http"]


def test_a_rung_reporting_ok_with_no_text_is_refused_not_propagated(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(ok_result("   "), refused("enough text"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "blocked"
    assert runner.calls == ["http", "camoufox"], "the empty ok must climb, not satisfy the caller"


def test_a_refused_request_is_answered_and_the_loop_carries_on(make_request, monkeypatch) -> None:
    broken = payload(make_request())
    broken["protocol"] = 1
    stdin = io.StringIO(json.dumps(broken) + "\n" + json.dumps(payload(make_request())) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr(cli, "run_rung_isolated", sequence(ok_result()))

    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    lines = read_lines(stdout)
    assert lines[0]["ready"] is True
    assert lines[1]["verdict"] == "blocked"
    assert "protocol mismatch" in lines[1]["warning"]
    assert lines[2]["verdict"] == "ok", "one bad request must not take the resident child down"


def test_a_rung_that_blows_its_budget_is_killed() -> None:
    started = time.monotonic()
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=0.5,
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
    )
    elapsed = time.monotonic() - started
    assert elapsed < 20, f"the SIGKILL did not land; waited {elapsed}s"
    assert result.verdict is RungVerdict.ERROR
    assert "budget" in result.reason


def _rung_that_starts(member_code: str, *, quiet: bool = False) -> str:
    """A stand-in rung: start `member_code` in the rung's own group, wait for argv[2] to exist, then hang.

    The member is given argv[1] and argv[2]. `quiet` sends its stdio to /dev/null, as
    Xvfb's goes in the real rung, so the pipes closing says nothing about it.
    """
    stdio = ", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if quiet else ""
    return (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {member_code!r}, sys.argv[1], sys.argv[2]]{stdio})\n"
        "while not Path(sys.argv[2]).exists():\n"
        "    time.sleep(0.01)\n"
        "time.sleep(60)\n"
    )


_STOPS_ON_TERM = (
    "import signal, sys, time\n"
    "from pathlib import Path\n"
    "stopped, ready = Path(sys.argv[1]), Path(sys.argv[2])\n"
    "def stop(signum, frame):\n"
    "    stopped.write_text('asked')\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, stop)\n"
    "ready.write_text('ready')\n"
    "time.sleep(60)\n"
)


def test_a_rung_killed_on_its_budget_has_its_group_asked_to_stop_first(tmp_path) -> None:
    """Whatever the rung started (a display server, a browser) gets to clean up after itself.

    SIGKILL gives no process that chance, and Xvfb leaves its lock file behind
    on one. The stand-in child starts a grandchild in its group that records
    having been asked, then both hang until the budget expires.
    """
    stopped, ready = tmp_path / "stopped", tmp_path / "ready"
    child = _rung_that_starts(_STOPS_ON_TERM)

    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=2.0,
        argv=[sys.executable, "-c", child, str(stopped), str(ready)],
    )

    assert ready.exists(), "precondition: the grandchild was up before the budget ran out"
    assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
    assert stopped.exists(), "the group was killed outright, with no chance to stop itself"


_SLOW_TO_STOP = (
    "import signal, sys, time\n"
    "from pathlib import Path\n"
    "finished, ready = Path(sys.argv[1]), Path(sys.argv[2])\n"
    "def stop(signum, frame):\n"
    "    time.sleep(0.6)\n"
    "    finished.write_text('cleaned up')\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, stop)\n"
    "ready.write_text('ready')\n"
    "time.sleep(60)\n"
)


def test_a_rung_is_not_done_until_what_it_started_has_finished_stopping(tmp_path) -> None:
    """The rung itself dying is not the end of it: Xvfb outlives it while it removes its lock.

    The grandchild's output goes to /dev/null, as Xvfb's does in the real rung, so
    the pipes closing says nothing about it. Only waiting on the group does.
    """
    finished, ready = tmp_path / "finished", tmp_path / "ready"
    child = _rung_that_starts(_SLOW_TO_STOP, quiet=True)

    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=1.5,
        argv=[sys.executable, "-c", child, str(finished), str(ready)],
    )

    assert ready.exists(), "precondition: the grandchild was up before the budget ran out"
    assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
    assert finished.exists(), "the rung was reported stopped while its grandchild was still cleaning up"


def test_a_rung_that_ignores_the_request_to_stop_is_killed_after_the_grace_period(tmp_path, monkeypatch) -> None:
    """Asking first must not mean waiting forever on a rung that will not stop."""
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.3)
    ready = tmp_path / "ready"
    started = time.monotonic()

    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=1.5,
        argv=_stubborn_rung(ready),
    )

    assert ready.exists(), "precondition: the child was ignoring SIGTERM before the budget ran out"
    assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
    assert time.monotonic() - started < 10, "the kill did not land after the grace period"
    try:
        os.kill(int(ready.read_text()), 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("the rung that ignored SIGTERM is still running")


def test_a_second_sigterm_while_the_group_is_stopping_still_kills_what_ignored_the_first(tmp_path, monkeypatch) -> None:
    """`main` turns SIGTERM into SystemExit, so one can land inside the grace wait.

    Without a fallback that exits the wait with the SIGKILL still unsent, a rung
    that ignores SIGTERM outlives the CLI that was stopping it. The stand-in
    raises SystemExit from the wait's own sleep, which is where the handler's
    exception would surface.
    """
    ready = tmp_path / "ready"
    member = tmp_path / "member"

    def second_sigterm(seconds: float) -> None:
        raise SystemExit(128 + 15)

    group = None
    try:
        monkeypatch.setattr(cli.time, "sleep", second_sigterm)
        with pytest.raises(SystemExit):
            cli.run_rung_isolated(
                "http",
                "https://example.com/article",
                timeout_s=1.5,
                argv=_stubborn_family(ready, member),
            )
        monkeypatch.undo()
        assert ready.exists(), "precondition: the rung was ignoring SIGTERM before the budget ran out"
        group = int(ready.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(group, 0)
        # `_reap` kills the leader after the grace period even when the SIGKILL never
        # went out, so the leader alone cannot show it did. The member can.
        _assert_member_was_killed(member)
    finally:
        _kill_leftover_group(group)


def test_a_sigterm_that_lands_before_the_group_was_asked_to_stop_still_kills_it(tmp_path, monkeypatch) -> None:
    """Review finding: the first `killpg` sat outside the `try` that holds the kill.

    `main` turns SIGTERM into SystemExit, which can surface in that very call.
    Then nothing had been sent and nothing was left to send it, and a rung that
    ignores SIGTERM outlived the CLI that was stopping it. The stand-in raises
    from the first SIGTERM before it reaches the group, which is where the
    handler's exception would surface. The kill reaches the real group.
    """
    ready = tmp_path / "ready"
    member = tmp_path / "member"
    real_killpg = os.killpg

    def interrupted(group: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            raise SystemExit(128 + 15)
        real_killpg(group, sig)

    group = None
    try:
        monkeypatch.setattr(cli.os, "killpg", interrupted)
        with pytest.raises(SystemExit):
            cli.run_rung_isolated(
                "http",
                "https://example.com/article",
                timeout_s=1.5,
                argv=_stubborn_family(ready, member),
            )
        monkeypatch.undo()
        assert ready.exists(), "precondition: the rung was ignoring SIGTERM before the budget ran out"
        group = int(ready.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(group, 0)
        _assert_member_was_killed(member)  # same reason as the test above
    finally:
        _kill_leftover_group(group)


def test_a_member_the_scans_missed_is_killed_before_the_group_is_called_stopped(tmp_path, monkeypatch) -> None:
    """Review finding H2: two scans that find nothing running can still be wrong.

    A child forked and gone again between them is in neither listing. Here the
    scans are blind on purpose (stood in for by `procfs.has_running_member` saying
    nothing runs) while a real rung ignores SIGTERM, which is exactly what a missed member
    looks like to the wait. Only the last SIGKILL, sent while the leader is still
    unreaped, ends it. The rung has a second process in its group: `_reap` kills
    the leader after the grace period even with no SIGKILL, so the leader alone
    cannot show the signal went out. The member can.
    """
    monkeypatch.setattr(procfs, "has_running_member", lambda group: False)
    ready = tmp_path / "ready"
    member = tmp_path / "member"

    try:
        result = cli.run_rung_isolated(
            "http",
            "https://example.com/article",
            timeout_s=1.5,
            argv=_stubborn_family(ready, member),
        )

        assert ready.exists(), "precondition: the rung was ignoring SIGTERM before the budget ran out"
        assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
        with pytest.raises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)
        _assert_member_was_killed(member)
    finally:
        _kill_leftover_group(int(ready.read_text()) if ready.exists() else None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc and signals process groups, as the group check does")
def test_an_unreaped_leader_keeps_its_pid_and_group_id_allocated() -> None:
    """The kernel invariant `_stop_group` leans on when it sends its last SIGKILL.

    The comment above `wait_gone` says a pid stays allocated while its process is
    an unreaped zombie, so the group id cannot be handed to anything else until
    `_reap` runs. This checks that against a real child rather than a fake: while
    the leader is a zombie its pid and group are still there, and reaping it is
    what releases both.
    """
    leader = unreaped_child()
    try:
        assert procfs.read_stat(leader.pid).state == "Z", "precondition: the leader is an unreaped zombie"
        assert os.getpgid(leader.pid) == leader.pid, "the zombie still holds its group"
        os.killpg(leader.pid, 0)  # the group id is still ours, not another process's
    finally:
        leader.wait()

    with pytest.raises(ProcessLookupError):
        os.getpgid(leader.pid)
    with pytest.raises(ProcessLookupError):
        os.killpg(leader.pid, 0)


class _GroupLeader:
    """The leader side `_stop_group` needs once the signals are stubbed out."""

    pid = 4_000_000
    stdout = None
    stderr = None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "", ""


@pytest.mark.parametrize(("survives",), [(True,), (False,)], ids=["survives-SIGKILL", "stops-on-SIGKILL"])
def test_a_group_member_that_survives_sigkill_is_reported_not_called_stopped(monkeypatch, survives) -> None:
    """`_stop_display` raises for this; the group stop used to call it stopped.

    A member in uninterruptible sleep ignores SIGKILL until its call returns. The
    pair is the same stop with only the post-SIGKILL answer changed: one row still
    running (it must raise) and one row gone (it must return).
    """
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 0.01)
    monkeypatch.setattr(stopping, "KILL_WAIT_S", 0.01)
    monkeypatch.setattr(procfs, "group_is_running", lambda group: survives)
    sent: list[int] = []
    monkeypatch.setattr(cli, "_signal_group", lambda group, sig: sent.append(sig))

    if survives:
        with pytest.raises(RuntimeError, match="did not stop within"):
            cli._stop_group(_GroupLeader())  # type: ignore[arg-type]
    else:
        cli._stop_group(_GroupLeader())  # type: ignore[arg-type]

    assert sent.count(signal.SIGTERM) == 1, "precondition: the group was asked to stop"
    assert sent.count(signal.SIGKILL) == 1, "the one kill is sent either way, and only once"


class _Pipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _LeaderWhosePipesMayStayOpen:
    """The leader of a stopped rung: `communicate` either finishes or hits its timeout."""

    def __init__(self, pipes_held_open: bool, survives_kill: bool = False) -> None:
        self.pid = 4_000_002
        self.pipes_held_open = pipes_held_open
        self.survives_kill = survives_kill
        self.stdout = _Pipe()
        self.stderr = _Pipe()
        self.timeouts: list[float | None] = []
        self.wait_timeouts: list[float | None] = []
        self.killed = False
        self.waited = False

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.timeouts.append(timeout)
        if self.pipes_held_open:
            raise subprocess.TimeoutExpired("rung", timeout)
        return "", ""

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> None:
        self.waited = True
        self.wait_timeouts.append(timeout)
        if self.survives_kill and timeout is not None:
            raise subprocess.TimeoutExpired("rung", timeout)


@pytest.mark.parametrize("pipes_held_open", [True, False], ids=["pipes-held-open", "pipes-closed"])
def test_reap_reads_for_the_drain_period_and_only_then_kills_and_closes_the_pipes(monkeypatch, pipes_held_open) -> None:
    """The bounded read: the drain period comes from `stopping`, and a timeout is what triggers the fallback.

    The pair differs only in whether the read finishes. When it does, the leader
    is left alone; when it does not, the leader is killed and reaped and both
    pipes are closed by hand, because nothing else will.
    """
    monkeypatch.setattr(stopping, "PIPE_DRAIN_S", 2.5)
    monkeypatch.setattr(stopping, "KILL_WAIT_S", 1.25)
    leader = _LeaderWhosePipesMayStayOpen(pipes_held_open)

    cli._reap(leader)  # type: ignore[arg-type]

    assert leader.timeouts == [2.5], "the read was bounded by the pipe drain bound"
    assert leader.killed is pipes_held_open
    assert leader.waited is pipes_held_open
    assert leader.wait_timeouts == ([1.25] if pipes_held_open else [])
    assert leader.stdout.closed is pipes_held_open
    assert leader.stderr.closed is pipes_held_open


def test_a_leader_that_survives_sigkill_is_reported_not_waited_on_forever(monkeypatch) -> None:
    """A leader in uninterruptible sleep ignores SIGKILL; the reap must not hang on it.

    The pipes are closed on the way out too, which is why the kill and the raise
    live either side of the same `finally`.
    """
    monkeypatch.setattr(stopping, "PIPE_DRAIN_S", 0.25)
    monkeypatch.setattr(stopping, "KILL_WAIT_S", 0.5)
    leader = _LeaderWhosePipesMayStayOpen(pipes_held_open=True, survives_kill=True)

    with pytest.raises(RuntimeError, match=r"did not exit within 0\.5s of SIGKILL"):
        cli._reap(leader)  # type: ignore[arg-type]

    assert leader.killed, "precondition: the reap reached the kill"
    assert leader.wait_timeouts == [0.5], "the wait after SIGKILL is bounded too"
    assert leader.stdout.closed and leader.stderr.closed, "the raise did not leak the pipes"


def test_reap_does_not_hang_on_a_straggler_outside_the_group_that_holds_the_pipes(monkeypatch, tmp_path) -> None:
    """The same fallback on the real kernel: a process that left the group and kept the pipes.

    `setsid` takes the straggler out of the rung's group, so the group's SIGKILL
    cannot end it, and it inherited the rung's stdout and stderr, so `communicate`
    would wait for it to exit. The rung exits at once, so what is left to wait on
    is only the straggler's 30-second sleep.
    """
    monkeypatch.setattr(stopping, "PIPE_DRAIN_S", 0.5)
    pid_file = tmp_path / "straggler.pid"
    rung = (
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "straggler = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
        "Path(sys.argv[1]).write_text(str(straggler.pid))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", rung, str(pid_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    straggler = None
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() or not pid_file.read_text():
            assert time.monotonic() < deadline, "the rung never started its straggler"
            time.sleep(0.01)
        straggler = int(pid_file.read_text())
        started = time.monotonic()

        cli._reap(process)

        assert time.monotonic() - started < 10, "the reap waited for the straggler's own sleep"
        os.kill(straggler, 0)  # precondition: the straggler outlived the reap, so it really held the pipes
        assert process.returncode is not None, "the leader was reaped"
        assert process.stdout.closed and process.stderr.closed
    finally:
        if straggler is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(straggler, signal.SIGKILL)
        if process.returncode is None:
            process.kill()
            process.wait()
        for pipe in (process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()


def _rung_that_dies_on_a_signal_leaving_a_member(tmp_path):
    """The argv of a rung that SIGKILLs itself after starting one quiet child, and the file that child writes.

    The child sleeps 30 seconds with SIGTERM at its default action, so a group
    stop that reaches it ends it on the first signal.
    """
    member_file = tmp_path / "member"
    member_code = (
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    rung = (
        "import os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]],\n"
        "    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "while not Path(sys.argv[2]).exists():\n"
        "    time.sleep(0.01)\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    return [sys.executable, "-c", rung, member_code, str(member_file)], member_file


def test_a_rung_that_dies_on_a_signal_has_what_it_started_stopped(tmp_path) -> None:
    """A child killed by the OOM killer or a crash cannot run its own cleanup.

    `communicate` returns normally with the leader's signal return code, so this
    used to skip the group stop entirely and leave an Xvfb (here, a quiet child
    in the rung's group) holding its display lock for the life of the machine.
    """
    argv, member_file = _rung_that_dies_on_a_signal_leaving_a_member(tmp_path)

    result = cli.run_rung_isolated("http", "https://example.com/article", timeout_s=5, argv=argv)

    assert member_file.exists(), "precondition: the rung started a process in its group"
    assert result.verdict is RungVerdict.ERROR
    _assert_member_was_killed(member_file)


def test_a_reaped_leaders_emptied_group_is_not_sent_a_last_sigkill(monkeypatch, tmp_path) -> None:
    """Once `communicate` has reaped the leader, nothing holds the group id.

    The same rung as above, but the group stop is watched. The member ends on the
    SIGTERM, so the group is empty when the grace wait returns. The leader is
    already reaped, so its number may be someone else's by now, and a SIGKILL sent
    to it would hit that group. The unconditional last SIGKILL belongs to the
    budget path, where the leader is still a zombie holding the number.
    """
    sent: list[int] = []
    real_signal_group = cli._signal_group

    def spy(group: int, sig: int) -> None:
        sent.append(sig)
        real_signal_group(group, sig)

    monkeypatch.setattr(cli, "_signal_group", spy)
    argv, member_file = _rung_that_dies_on_a_signal_leaving_a_member(tmp_path)

    cli.run_rung_isolated("http", "https://example.com/article", timeout_s=5, argv=argv)

    assert sent[:1] == [signal.SIGTERM], "precondition: the group stop ran and asked the member to stop"
    _assert_member_was_killed(member_file)
    assert signal.SIGKILL not in sent


def test_a_stubborn_group_is_scanned_for_members_only_a_few_times_a_second(monkeypatch, tmp_path) -> None:
    """Review finding F31: the cheap question is asked often, the /proc scan rarely.

    A group that ignores SIGTERM used to cost a full process-table scan every
    20 ms for the whole grace period (about 50 a second). The cheap
    `killpg(group, 0)` is still asked that often, but the scan is bounded to one
    every 0.2 s; the last SIGKILL covers a member a slower scan missed.
    """
    monkeypatch.setattr(stopping, "STOP_GRACE_S", 1.0)
    monkeypatch.setattr(stopping, "KILL_WAIT_S", 0.5)
    calls: list[int] = []
    real = procfs.has_running_member

    def counting(group: int) -> bool:
        calls.append(group)
        return real(group)

    monkeypatch.setattr(procfs, "has_running_member", counting)
    ready = tmp_path / "ready"

    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=0.3,
        argv=_stubborn_rung(ready),
    )

    assert ready.exists(), "precondition: the group was still ignoring SIGTERM"
    assert result.verdict is RungVerdict.ERROR and "budget" in result.reason
    assert len(calls) >= 2, "precondition: the group was scanned while it ran"
    assert len(calls) <= 12, f"{len(calls)} full /proc scans in one stop; the cheap check was not used"


_ORPHANS_THE_GRANDCHILD_TO_A_PARENT_THAT_NEVER_REAPS = (
    "import ctypes, subprocess, sys, time\n"
    "from pathlib import Path\n"
    "from ladder_cli import cli, stopping\n"
    # What a container whose PID 1 never waits does: orphans stay zombies for good.
    "PR_SET_CHILD_SUBREAPER = 36\n"
    "if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:\n"
    "    sys.exit('could not become a subreaper')\n"
    "stopping.STOP_GRACE_S = 3.0\n"
    "ready = Path(sys.argv[1])\n"
    "rung = (\n"
    "    'import subprocess, sys, time\\n'\n"
    "    'from pathlib import Path\\n'\n"
    "    \"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\\n\"\n"
    "    'Path(sys.argv[1]).write_text(\"up\")\\n'\n"
    "    'time.sleep(60)\\n'\n"
    ")\n"
    "process = subprocess.Popen(\n"
    "    [sys.executable, '-c', rung, str(ready)],\n"
    "    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,\n"
    ")\n"
    "while not ready.exists():\n"
    "    time.sleep(0.01)\n"
    "started = time.monotonic()\n"
    "cli._stop_group(process)\n"
    "print(time.monotonic() - started)\n"
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc and uses prctl, as the rest of the group check does")
def test_a_stopped_group_whose_orphan_nobody_reaps_is_not_waited_on_for_the_whole_grace_period(tmp_path) -> None:
    """A zombie is dead; counting it as still running costs every timeout the full wait.

    `killpg(group, 0)` succeeds while an unreaped zombie is in the group. Under
    a PID 1 that never waits, the rung's orphaned grandchild is one for good,
    so the group is never seen to be gone and `_stop_group` always spent its
    whole grace period, then SIGKILLed the dead. Measured on the real kernel
    with a subreaper standing in for that PID 1.
    """
    result = subprocess.run(
        [sys.executable, "-c", _ORPHANS_THE_GRANDCHILD_TO_A_PARENT_THAT_NEVER_REAPS, str(tmp_path / "ready")],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    elapsed = float(result.stdout.strip().splitlines()[-1])
    assert elapsed < 2.0, f"waited {elapsed:.2f}s of a 3s grace period on a group with nothing left running"


def test_a_final_rung_timeout_is_an_error_not_a_defended_page(make_request) -> None:
    calls = []

    def runner(rung, url, ctx=None):
        calls.append(rung)
        return cli.run_rung_isolated(
            rung, url, timeout_s=0.3,
            argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        )

    response = cli.dispatch(make_request(rungCeiling=1), runner=runner)
    assert calls == ["http"]
    assert response.rungReached == 1
    assert response.verdict == "error"
    assert "budget" in response.warning


def test_a_child_record_comes_back_judged_by_the_rung_rules() -> None:
    page = json.dumps({"title": "An article", "text": "body " * 300, "status": 200})
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=20,
        argv=[sys.executable, "-c", f"print({page!r})"],
    )
    assert result.verdict is RungVerdict.OK
    assert result.status == 200


def test_a_dns_failure_on_the_first_rung_reads_dead() -> None:
    result = cli.run_rung_isolated(
        "http",
        "https://nonexistent.invalid",
        timeout_s=20,
        argv=[sys.executable, "-c", "import sys; print('DNSError: failed to lookup', file=sys.stderr); sys.exit(1)"],
    )
    assert result.verdict is RungVerdict.DEAD
    assert "network" in result.reason


def test_an_unexpected_rung_failure_climbs_and_only_surfaces_when_the_rungs_run_out(
    make_request,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    monkeypatch.setattr(cli, "run_rung_isolated", sequence(RungResult(RungVerdict.ERROR, reason="boom"), RungResult(RungVerdict.ERROR, reason="boom again")))

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    response = read_lines(stdout)[1]
    assert response["verdict"] == "error"
    assert response["rungReached"] == 2
    assert response["warning"]


def test_an_unexpected_rung_failure_reports_blocked_once_a_page_is_actually_defended(
    make_request,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(RungResult(RungVerdict.ERROR, reason="boom"), refused())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    assert read_lines(stdout)[1]["verdict"] == "blocked"


def test_a_timeout_reads_as_an_error_not_as_the_page_dying() -> None:
    # The spike mapped a timeout to `dead`, which stopped the climb on a blown
    # budget. A budget firing is our machinery, never the page, so it must climb.
    from ladder_cli.rungs import http as rung_http

    assert rung_http.DEAD_NET.search("TimeoutError") is None
    assert rung_http.DEAD_NET.search("timed out") is None
    assert rung_http.DEAD_NET.search("DNSError: failed to lookup")


def test_the_childs_error_line_is_picked_out_of_stderr_noise() -> None:
    # The child prints one `Type: message` line, but it is not the last thing on
    # stderr: a multi-line exception message, or a deprecation notice after it,
    # used to be mistaken for the error.
    stderr = (
        "/usr/lib/ladder_cli/http.py:9: DeprecationWarning: something newer\n"
        "Traceback (most recent call last):\n"
        '  File "x", line 1\n'
        "ValueError: the real reason\nsecond line of the same message\n"
    )
    assert cli._rung_error_line(stderr) == "the real reason"


def test_a_timeout_on_a_rung_is_reported_as_a_budget_not_as_a_network_death() -> None:
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=20,
        argv=[sys.executable, "-c", "import sys; print('TimeoutError: read timed out', file=sys.stderr); sys.exit(1)"],
    )
    assert result.verdict is RungVerdict.ERROR
    assert "timed out" in result.reason


def test_a_browser_tool_is_not_imported_before_anything_needs_it() -> None:
    # primp is a browser library and rung 1 is the only rung. Importing it at
    # module scope made the resident child owe its ready line before it had
    # touched a browser, so the import moved inside the client that uses it.
    assert "primp" not in sys.modules, "importing the ladder pulled in a browser tool it has not asked for"


def test_suffix_data_is_loaded_only_when_cookie_scoping_needs_it():
    process = subprocess.run([
        sys.executable, "-c",
        "import sys; from ladder_cli import cli; from ladder_cli.state import jars; "
        "before = 'tldextract' in sys.modules; "
        "assert jars.base_domain('www.example.com') == 'example.com'; "
        "assert 'tldextract' in sys.modules; "
        "assert not before, 'resident readiness eagerly imported cookie suffix support'",
    ], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr


def test_the_requests_jar_paths_reach_the_runner(make_request, monkeypatch) -> None:
    """The parent sent `jarIn`/`jarOut` and dispatch dropped them on the floor.

    README documented both flags as working while no rung read either field.
    This pins the first hop: the request's browser jar paths become the context
    the zendriver runner is given. HTTP runs its own jar pair instead.
    """
    from pathlib import Path

    from ladder_cli.rungs import RungContext

    seen: dict = {}

    def fake(rung: str, url: str, ctx=None) -> RungResult:
        seen["ctx"] = ctx
        return ok_result()

    monkeypatch.setattr(cli, "RUNGS", ("zendriver_cf",))

    cli.dispatch(make_request(jarIn="/work/in.cookies.json", jarOut="/work/out.cookies.json"), runner=fake)

    assert seen["ctx"] == RungContext(
        jar_in=Path("/work/in.cookies.json"),
        jar_out=Path("/work/out.cookies.json"),
    )


def test_an_isolated_child_is_told_the_jars_on_its_command_line(monkeypatch) -> None:
    """A subprocess cannot see the parent's memory; its argv is the handoff."""
    from pathlib import Path

    from ladder_cli.rungs import RungContext

    commands: list[list[str]] = []

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            commands.append(command)
            self.pid = 4242

        def communicate(self, timeout: float | None = None):
            return ('{"title": "T", "text": "body", "status": 200}\n', "")

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)

    cli.run_rung_isolated(
        "http",
        "https://example.com/",
        timeout_s=5,
        ctx=RungContext(jar_in=Path("/j/in.json"), jar_out=Path("/j/out.json")),
    )
    cli.run_rung_isolated("http", "https://example.com/", timeout_s=5)

    assert commands[0][-4:] == ["--jar-in", "/j/in.json", "--jar-out", "/j/out.json"]
    assert "--jar-in" not in commands[1], "no jar, no flags: the child's argv stays what it was"


def test_the_rung_child_reads_the_jar_flags_back_without_mistaking_them_for_the_url(monkeypatch) -> None:
    from pathlib import Path

    from ladder_cli.rungs import RungContext

    seen: dict = {}

    def fake_child(rung, url, stdout, stderr, ctx=None):
        seen["call"] = (rung, url, ctx)
        return 0

    monkeypatch.setattr(cli, "_run_rung_child", fake_child)

    cli.main(
        ["--rung", "http", "https://example.com/", "--jar-in", "/j/in.json", "--jar-out", "/j/out.json"],
        stdout=io.StringIO(),
    )

    assert seen["call"] == (
        "http",
        "https://example.com/",
        RungContext(jar_in=Path("/j/in.json"), jar_out=Path("/j/out.json")),
    )
def test_u2028_in_page_text_does_not_split_the_rung_record() -> None:
    # U+2028 LINE SEPARATOR is legal inside a JSON string but is a line break
    # to str.splitlines(). The regression is a page whose text contains it
    # reading as a rung that produced no record at all.
    script = (
        "import json; "
        "print(json.dumps({'title': 'T', 'status': 200, "
        "'text': 'before\\u2028' + 'word ' * 200}, ensure_ascii=False))"
    )
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=10,
        argv=[sys.executable, "-c", script],
    )
    assert result.verdict is RungVerdict.OK


def test_jar_paths_reach_the_runner_with_the_request(make_request, monkeypatch, tmp_path) -> None:
    runner = sequence(ok_result("clear enough to read"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    jar_in = tmp_path / "in.jar"
    jar_out = tmp_path / "out.jar"
    stdin = io.StringIO(json.dumps(payload(make_request(httpJarIn=str(jar_in), httpJarOut=str(jar_out)))) + "\n")
    stdout = io.StringIO()
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    assert runner.calls == ["http"]
    assert runner.jars == [(str(jar_in), str(jar_out))], "the request's jar paths are the runner's to pass on"


def test_the_child_command_carries_jar_flags(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from ladder_cli.rungs import RungContext

    jar = tmp_path / "session.jar"
    page = json.dumps({"title": "T", "text": "word " * 200, "status": 200})
    captured: dict[str, list[str]] = {}

    class FakeProcess:
        def __init__(self, command, **_kwargs):
            captured["command"] = list(command)
            self.pid = 4_000_003

        def communicate(self, timeout=None):
            return (page + "\n", "")

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)

    result = cli.run_rung_isolated(
        "http",
        "https://example.com/x",
        ctx=RungContext(jar_in=Path(jar), jar_out=Path(jar)),
    )

    assert result.verdict is RungVerdict.OK
    assert captured["command"][-4:] == ["--jar-in", str(jar), "--jar-out", str(jar)], (
        "the child's argv carries the rung's own jar pair under one flag spelling"
    )

    captured.clear()
    cli.run_rung_isolated("http", "https://example.com/x")
    assert "--jar-in" not in captured["command"], "a cold request spawns no jar flags"


def test_child_mode_parses_jar_flags(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from ladder_cli.rungs import RungContext

    seen: dict[str, object] = {}

    def fake_fetch(rung, url, ctx=None):
        seen.update(rung=rung, url=url, ctx=ctx)
        return {"title": "T", "text": "word " * 200, "status": 200, "links": []}

    monkeypatch.setattr(cli, "fetch", fake_fetch)

    jar_in = tmp_path / "in.jar"
    jar_out = tmp_path / "out.jar"
    code = cli.main(
        ["--rung", "http", "https://example.com/x", "--jar-in", str(jar_in), "--jar-out", str(jar_out)]
    )

    assert code == 0
    assert seen == {
        "rung": "http",
        "url": "https://example.com/x",
        "ctx": RungContext(jar_in=Path(jar_in), jar_out=Path(jar_out)),
    }


def test_a_rung_child_takes_sigterm_as_the_default_action_not_via_the_resident_handler() -> None:
    """The handler belongs to the resident loop, not the `--rung` branch.

    `stopping.stop_with_grace` leans on this: a SIGTERM that reaches a rung child
    ends the process instead of raising `SystemExit` inside the stop. A signal to
    a real child distinguishes the two by its exit status: the default action is
    death by SIGTERM (negative return code), while the installed handler would
    exit 143 after turning it into `SystemExit`.
    """
    script = (
        "import sys, time\n"
        "from ladder_cli import cli\n"
        "def slow(rung, url, ctx=None):\n"
        "    print('ready', flush=True)\n"
        "    time.sleep(60)\n"
        "cli.fetch = slow\n"
        "sys.exit(cli.main(['--rung', 'http', 'https://example.com/']))\n"
    )
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready", "precondition: the rung child was running"
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
        assert process.returncode == -signal.SIGTERM, (
            "a rung child installed the resident SIGTERM handler before its branch"
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


def test_each_rung_receives_only_its_own_jar_format(make_request):
    runner = sequence(refused(), refused(), refused(), ok_result())
    request = make_request(jarIn="browser.in.json", jarOut="browser.out.json",
                           httpJarIn="http.in.txt", httpJarOut="http.out.txt", rungCeiling=4)
    response = cli.dispatch(request, runner=runner)
    assert response.verdict == "ok"
    assert runner.calls == ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]
    assert runner.jars == [("http.in.txt", "http.out.txt"), (None, None),
                           ("browser.in.json", "browser.out.json"),
                           ("browser.in.json", "browser.out.json")]
