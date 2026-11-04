"""Handshake, NDJSON loop, and dispatch for the resident ladder CLI.

The parent (serp-axi) holds one of these children open across scrapes: we print
a single ready line before reading anything, answer one JSON request per line,
and go quiet when the parent closes stdin. No sockets, no ports, no supervisor
beyond the parent holding our handle.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Iterable, Sequence

from . import procfs, stopping
from .protocol import PROTOCOL, LadderRequest, LadderResponse, ProtocolError
from .rungs import RUNGS, RungContext, RungResult, RungVerdict, fetch, judge, network_verdict

# One budget, owned by the code that enforces it: a rung is stopped at 90s.
# It used to be overridable from the environment, which made two owners of one
# deadline (the parent already bounds the whole request) and a tunable no test
# ever exercised. Tests now inject `timeout_s` instead of exporting an env var.
DEFAULT_RUNG_TIMEOUT_S = 90.0


def _cap_args(ctx: RungContext | None) -> list[str]:
    """The child's byte cap, omitted when the request did not set one."""
    if ctx is None or ctx.max_response_bytes is None:
        return []
    return ["--max-bytes", str(ctx.max_response_bytes)]


def _jar_args(ctx: RungContext | None) -> list[str]:
    """The child's jar flags, omitted when the request carries no jar."""
    if ctx is None:
        return []
    args: list[str] = []
    if ctx.jar_in is not None:
        args += ["--jar-in", str(ctx.jar_in)]
    if ctx.jar_out is not None:
        args += ["--jar-out", str(ctx.jar_out)]
    return args


def _context_from(args: Sequence[str]) -> RungContext:
    """Read the cap and jar flags the parent appended to the child's argv."""
    jar_in: Path | None = None
    jar_out: Path | None = None
    max_response_bytes: int | None = None
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--max-bytes" and index + 1 < len(args):
            max_response_bytes = int(args[index + 1])
            index += 2
            continue
        if flag in ("--jar-in", "--jar-out") and index + 1 < len(args):
            value = args[index + 1]
            if flag == "--jar-in":
                jar_in = Path(value)
            else:
                jar_out = Path(value)
            index += 2
            continue
        index += 1
    return RungContext(jar_in=jar_in, jar_out=jar_out, max_response_bytes=max_response_bytes)


def _signal_group(group: int, sig: int) -> None:
    """Send `sig` to every process in the group. A group already gone is the goal, not an error."""
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        pass


def _reap(process: subprocess.Popen) -> None:
    """Collect the leader and close its pipes, without waiting on anything outside the group.

    `communicate()` reads until both pipes reach EOF, and a descendant that left
    the group (`setsid`, a double fork) and inherited them holds them open for as
    long as it lives, which the group's SIGKILL cannot end. So the read gets
    `PIPE_DRAIN_S` and no more: past it the leader is killed and reaped, and the
    pipes are closed here, so a straggler outside the group cannot hang the
    resident CLI. What the stopped rung printed is not used, so none of it is lost.

    The wait after that SIGKILL is bounded too (`KILL_WAIT_S`): a leader in
    uninterruptible sleep ignores SIGKILL until its call returns, and an
    unbounded `wait()` would hold the resident CLI for as long as the mount stays
    stalled. It raises instead, so a leader that cannot be reaped is reported
    rather than silently left behind.
    """
    try:
        process.communicate(timeout=stopping.PIPE_DRAIN_S)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=stopping.KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"rung (pid {process.pid}) did not exit within {stopping.KILL_WAIT_S:g}s of SIGKILL"
            ) from None
        finally:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


def _stop_group(process: subprocess.Popen, *, leader_reaped: bool = False) -> None:
    """Stop a rung and everything it started, and reap it.

    The group is asked to stop with SIGTERM first, because SIGKILL gives nothing
    in it the chance to clean up, and Xvfb leaves its lock file behind on one.
    Whatever is still running when the grace period ends is killed. The group is
    waited on, not just the child: the child dying closes the pipes, which says
    nothing about a display server that is still removing its lock.

    The order, the grace period and the kill that survives an exception mid-stop
    are `stopping.stop_with_grace`, shared with the display stop. What is
    particular to a group is here: it has no wait, so "gone" is a poll of /proc,
    and the kill is followed by its own bounded wait and a raise. The reaping is
    in a `finally` of its own for the same reason the kill is in one: the child
    must not be left unreaped by whatever interrupted the stop.

    The last SIGKILL, which covers a member the /proc scans missed, is sent only
    while the leader is unreaped, because only an unreaped leader keeps the group
    id from being handed to an unrelated process. The budget/exception path
    reaches here with the leader unreaped. The normal-exit path (`leader_reaped`)
    has already had it reaped by `communicate`, so it kills only what the grace
    period did not stop, and a live member found a moment ago is the only thing
    that held the id.
    """
    group = process.pid

    def wait_gone(seconds: float) -> bool:
        # The leader is not reaped in here, on purpose. A pid stays allocated while
        # its process is an unreaped zombie, so the group id cannot be handed to
        # anything else until `_reap` below reaps it, and a signal to the group can
        # only reach this group (pinned against the real kernel by
        # `test_an_unreaped_leader_keeps_its_pid_and_group_id_allocated`). A zombie
        # is not "running" to `group_is_running`, so leaving it unreaped does not
        # hold the wait up.
        #
        # A scan of /proc is the expensive question, so it is asked at most every
        # 0.2s; between scans the cheap `killpg(group, 0)` says whether the group
        # still exists at all. A zombie-only group still answers that signal, so a
        # cheap "gone" is the only early answer it gives. One scan is made at the
        # deadline, so a group that went at the last moment is not called running.
        deadline = time.monotonic() + seconds
        next_scan = 0.0
        while True:
            now = time.monotonic()
            if now >= next_scan or now >= deadline:
                if not procfs.group_is_running(group):
                    return True
                next_scan = now + 0.2
            else:
                try:
                    os.killpg(group, 0)
                except ProcessLookupError:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def kill() -> None:
        _signal_group(group, signal.SIGKILL)
        if not wait_gone(stopping.KILL_WAIT_S):
            raise RuntimeError(
                f"rung group {group} did not stop within {stopping.KILL_WAIT_S:g}s of SIGKILL"
            )

    try:
        # `always_kill` is the H2 answer: a /proc scan is not atomic, so a child
        # forked and gone again between its reads is in no listing, and "nothing
        # is running" can still be wrong. One SIGKILL inside the shared routine's
        # `finally` settles it, and is safe while the leader is unreaped, which is
        # what keeps the group id from being anyone else's. It is not after the
        # routine: a SIGTERM landing in that window must not skip it (review
        # findings F19, F20 and F21). When the leader was already reaped there is
        # no such guarantee, so `leader_reaped` turns it off and only a group that
        # outlasted the grace period is killed.
        stopping.stop_with_grace(
            term=lambda: _signal_group(group, signal.SIGTERM),
            wait_gone=wait_gone,
            kill=kill,
            always_kill=not leader_reaped,
        )
    finally:
        _reap(process)


def run_rung_isolated(
    rung: str,
    url: str,
    timeout_s: float | None = None,
    argv: Sequence[str] | None = None,
    ctx: RungContext | None = None,
) -> RungResult:
    """Run one rung as a subprocess under a hard time budget.

    A subprocess is what makes the budget enforceable: it is the thing that can
    be stopped (see ``_stop_group``). The child is started in its own session so
    the stop reaches whatever it spawned underneath it, matching ladder.py:180.

    The cap and jar flags are part of the child's argv because both are per
    request and the child's own arguments are how one request's settings reach
    it. A custom ``argv`` is a complete command (the tests use one to fake a
    child), so it is passed through untouched.
    """
    budget = DEFAULT_RUNG_TIMEOUT_S if timeout_s is None else timeout_s
    command = (
        list(argv)
        if argv is not None
        else [
            sys.executable,
            "-m",
            "ladder_cli",
            "--rung",
            rung,
            url,
            *_cap_args(ctx),
            *_jar_args(ctx),
        ]
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = process.communicate(timeout=budget)
    except BaseException as error:
        _stop_group(process)
        if isinstance(error, subprocess.TimeoutExpired):
            return RungResult(RungVerdict.ERROR, reason=f"rung {rung} exceeded its {budget:g}s budget")
        raise

    # A rung that exits without raising has already been reaped by `communicate`,
    # so nothing ran the graceful group stop. A child killed by a signal (the OOM
    # killer, a SIGKILL, a native crash) cannot run its own cleanup, and an Xvfb it
    # started would keep its display lock for the life of the machine. A live
    # process still in the group proves the group id is still ours, so stop it.
    # When nothing is left there, no signal is sent: the leader has been reaped and
    # its number could otherwise belong to an unrelated group.
    if procfs.has_running_member(process.pid):
        _stop_group(process, leader_reaped=True)

    # Split on LF only, never str.splitlines(): U+2028 LINE SEPARATOR is legal
    # inside a JSON string, and splitlines() treats it as a line break. A page
    # with that character in its text would otherwise be cut mid-string and
    # read as a rung that produced no record at all.
    lines = [line for line in (out or "").split("\n") if line.startswith("{")]
    if lines:
        try:
            page = json.loads(lines[-1])
        except json.JSONDecodeError:
            page = None
        if isinstance(page, dict) and "text" in page:
            return judge(rung, page)

    message = _rung_error_line(err)
    verdict = network_verdict(message, rung)
    if verdict is RungVerdict.DEAD:
        return RungResult(verdict, reason=f"network: {message}")
    return RungResult(verdict, reason=message)


# The child writes exactly one of these, but stderr carries other things too: a
# traceback from a library, a deprecation notice, a SIGKILL note. Taking the
# last line therefore assumes nothing noisier arrived after it, while taking
# the last line *shaped like an exception* does not.
_RUNG_ERROR_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exit|Interrupt|Timeout|Exception|Halt): (?P<detail>.*)$")


def _rung_error_line(stderr: str) -> str:
    """Pull the child's own error line out of whatever it printed."""
    for line in reversed((stderr or "").splitlines()):
        match = _RUNG_ERROR_LINE.match(line.strip())
        if match:
            return match.group("detail")[:160]
    return ((stderr or "").strip().splitlines() or ["?"])[-1][:160]


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _response(verdict: str, rung_reached: int, result: RungResult, started: float) -> LadderResponse:
    return LadderResponse(
        verdict=verdict,
        rungReached=rung_reached,
        title=result.title,
        text=result.text,
        engines=[],
        elapsedMs=_elapsed_ms(started),
        warning=result.reason or None,
        links=result.links,
    )


def dispatch(request: LadderRequest, *, runner=None) -> LadderResponse:
    """Climb the ladder for one request.

    Two verdicts end the climb early and the rest keep going: ``ok`` because the
    page arrived, ``dead`` because a stronger rung cannot revive a domain that
    does not resolve or a page that says it is parked (ladder.py:196). A blown
    budget and a rung that malfunctioned both mean try the next one.

    Running out of rungs is reported as ``blocked`` (the page defended itself)
    or as ``error`` when the last rung could not answer at all. Both are honest
    about the outcome, and they differ in the only part the caller can act on.

    The runner defaults by lookup rather than by argument value so a test can
    replace ``run_rung_isolated`` on this module.
    """
    if runner is None:
        runner = run_rung_isolated
    started = time.monotonic()
    rung_reached = 0
    last: RungResult | None = None

    for index, rung in enumerate(RUNGS[: request.rungCeiling]):
        rung_reached = index + 1
        # Each rung gets its own jar pair and no other's: rung 1 the caller's
        # full-session Netscape jars, the zendriver rungs the filtered browser
        # JSON jars, Camoufox neither. The formats are never converted.
        ctx: RungContext | None = None
        if rung == "http":
            # Always a context: the byte cap matters even on a cold request with
            # no jar, and rung 1 is the rung that reads the page itself.
            ctx = RungContext(
                jar_in=Path(request.httpJarIn) if request.httpJarIn is not None else None,
                jar_out=Path(request.httpJarOut) if request.httpJarOut is not None else None,
                max_response_bytes=request.maxResponseBytes,
            )
        elif rung in ("zendriver_cf", "zendriver_headed_cf") and (request.jarIn is not None or request.jarOut is not None):
            ctx = RungContext(
                jar_in=Path(request.jarIn) if request.jarIn is not None else None,
                jar_out=Path(request.jarOut) if request.jarOut is not None else None,
            )
        last = runner(rung, request.url, ctx=ctx)
        if last.verdict is RungVerdict.OK and not last.text.strip():
            # Asserted by both sides; converting rather than crashing keeps the
            # resident child alive across a bad response.
            last = RungResult(
                RungVerdict.BLOCKED,
                last.title,
                last.text,
                last.status,
                "rung reported ok with no text",
            )
        if last.verdict is RungVerdict.OK:
            return _response("ok", rung_reached, last, started)
        if last.verdict is RungVerdict.DEAD:
            return _response("dead", rung_reached, last, started)

    if last is None:
        return LadderResponse(
            verdict="blocked",
            rungReached=0,
            title="",
            text="",
            engines=[],
            elapsedMs=_elapsed_ms(started),
            warning=f"no rungs available at a ceiling of {request.rungCeiling}",
        )
    if last.verdict is RungVerdict.ERROR:
        return _response("error", rung_reached, last, started)
    return _response("blocked", rung_reached, last, started)


def _run_rung_child(rung: str, url: str, stdout: IO[str], stderr: IO[str], ctx: RungContext | None = None) -> int:
    try:
        page = fetch(rung, url, ctx)
    except Exception as error:  # noqa: BLE001 - the parent maps the message, not the type
        print(f"{type(error).__name__}: {error}", file=stderr, flush=True)
        return 1
    stdout.write(json.dumps(page, ensure_ascii=False) + "\n")
    stdout.flush()
    return 0


def _write(stdout: IO[str], payload: str) -> None:
    stdout.write(payload + "\n")
    stdout.flush()


def _refusal(reason: str) -> LadderResponse:
    return LadderResponse(
        verdict="blocked",
        rungReached=0,
        title="",
        text="",
        engines=[],
        elapsedMs=0,
        warning=reason,
    )


def _terminate(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Iterable[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    if len(args) >= 3 and args[0] == "--rung":
        return _run_rung_child(args[1], args[2], stdout, stderr, _context_from(args[3:]))

    # Readiness is announced before the first read, so no caller ever sleeps a
    # fixed interval and hopes. Anything the parent writes before this line is
    # not possible, since we have not read anything yet.
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        _write(stdout, json.dumps({"ready": True, "protocol": PROTOCOL}))

        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                response = dispatch(LadderRequest.parse(json.loads(line)))
            except ProtocolError as error:
                response = _refusal(str(error))
            except Exception as error:  # noqa: BLE001 - a failed request, never a hang
                response = _refusal(f"{type(error).__name__}: {error}")
            _write(stdout, response.encode())
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
