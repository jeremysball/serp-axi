"""Rung 4: rung 3 with a virtual display in front of it.

Some defences look for a real display before they believe a browser. This rung
is zendriver's fetch with the head taken off and an Xvfb screen behind it, so
nothing about how a page is handled is restated here. What it owns is only what
the measured run varied to get a headed browser: the display.
"""

from __future__ import annotations

import contextlib
import os
import socket
import stat
import subprocess
import time
from collections.abc import Iterator
from enum import Enum
from pathlib import Path
from typing import Any

from .. import procfs, stopping
from . import RungContext, RungResult, zendriver

# ladder.py:82 `headless=not headed` with headed True
HEADLESS = False
# ladder.py:106 `["Xvfb", disp, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"]`
XVFB_SCREEN = "1920x1080x24"
# `-nolisten tcp` is a safety property rather than a tuning number: the display
# exists for one local browser and must not be reachable over the network.
XVFB_BASE = ("Xvfb", "-screen", "0", XVFB_SCREEN, "-nolisten", "tcp")
# ladder.py:109 `time.sleep(1.5)`, the display's own cold start
XVFB_SETTLE_S = 1.5
# The spike picked `:200 + pid % 500`, which is a *starting* point, not a
# reservation. One resident CLI can hold several rungs open at once (04-tdd 1.8),
# and two pids congruent mod 500 would both be handed a slot the other owns.
XVFB_DISPLAY_LOW = 200
XVFB_DISPLAY_HIGH = 699
XVFB_READY_TIMEOUT_S = 10.0
# Where Xvfb keeps a display's files: the lock `.X<n>-lock` here, the socket
# `X<n>` under `.X11-unix/` in it. A name, not a literal at each use, so every
# reader derives the same two paths and a test can point them at a scratch directory.
X11_ROOT = Path("/tmp")
# What a lock may hold before it is not one Xvfb wrote. Xvfb writes `"%10d\n"`,
# eleven bytes (read off a real server's lock, 2026-11-02). The bound is looser
# than that on purpose: it is there to refuse a file with more in it, not to
# pin the format.
LOCK_MAX_BYTES = 64


class _DisplayCollision(RuntimeError):
    pass


class _DisplayRetry(RuntimeError):
    """The server exited at once, but the slot is free again: try it once more."""


class _LockState(Enum):
    """What an Xvfb lock says about the slot it names, in one read."""

    FREE = "free"  # no lock, or one whose owner is gone
    ZOMBIE = "zombie"  # ours, and its owner is a zombie
    HELD = "held"  # live, foreign, unreadable, or not provably either


def lock_path(number: int) -> Path:
    """The lock file Xvfb writes for display `number`, and removes on a clean stop."""
    return X11_ROOT / f".X{number}-lock"


def socket_path(number: int) -> Path:
    """The unix socket Xvfb listens on for display `number`."""
    return X11_ROOT / ".X11-unix" / f"X{number}"


def display_for_pid(pid: int) -> str:
    """ladder.py:105 `disp = f":{200 + os.getpid() % 500}"`, as a search start."""
    return f":{XVFB_DISPLAY_LOW + pid % (XVFB_DISPLAY_HIGH - XVFB_DISPLAY_LOW + 1)}"


def _read_lock(lock: Path) -> tuple[int, int]:
    """The owning uid and the pid inside an Xvfb lock, read without ever blocking.

    /tmp is shared, so what sits at the lock path is not necessarily what Xvfb
    wrote. A plain `open` of a FIFO there blocks until something writes to it,
    which would hang the display search for good, and it follows a symlink to
    whatever that points at. This opens non-blocking and without following a
    link, and accepts only a regular file; anything else raises OSError, which
    both callers read as "not a lock we can vouch for". A missing lock raises
    FileNotFoundError. A file that does not hold a number raises ValueError, and
    so does one longer than `LOCK_MAX_BYTES`: Xvfb writes the pid as `%10d\\n`,
    eleven bytes, so a longer file is not one it wrote, and reading only its
    first bytes would take the number at its front for a server's pid.
    """
    fd = os.open(lock, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode):
            raise OSError(f"{lock} is not a regular file")
        text = os.read(fd, LOCK_MAX_BYTES + 1)
        if len(text) > LOCK_MAX_BYTES:
            raise ValueError(f"{lock} is longer than the {LOCK_MAX_BYTES} bytes a lock may hold")
        return status.st_uid, int(text.strip())
    finally:
        os.close(fd)


def _lock_state(lock: Path) -> _LockState:
    """Classify the server named in an Xvfb lock file, reading the lock once.

    The lock holds the server's pid. Xvfb itself starts over a lock whose pid is
    gone (tested against a real server), so a leftover from a SIGKILL, a crash
    or a reboot does not take the slot. Anything that cannot be read as a
    live-or-dead pid counts as held: claiming a slot needs proof the server is
    dead, not the absence of proof. That includes a lock another user owns,
    since /tmp is sticky and Xvfb could not remove it to start over, a lock that
    is not a regular file, and a pid too large to probe at all (`os.kill` raises
    OverflowError for those).

    The owner is checked before `/proc` is read, so a foreign user's lock costs
    neither a stat read nor a signal. A zombie is the one liveness answer that is
    returned as its own state: it is held for `display_is_free`, and reclaimable
    for `free_display`.
    """
    try:
        owner, pid = _read_lock(lock)
    except FileNotFoundError:
        return _LockState.FREE
    except (OSError, ValueError):
        return _LockState.HELD
    if owner != os.getuid():
        return _LockState.HELD
    # A zombie exists to `probe` and still occupies the pid; Xvfb treats a lock
    # whose pid answers signal 0 as active (checked against a real server on
    # 2026-11-03: it exits 1, "Server is already active for display"). A pid at or
    # below zero is UNKNOWN to `probe`, so a lock holding `0` is held too.
    if procfs.probe(pid) is procfs.Liveness.GONE:
        return _LockState.FREE
    try:
        state = procfs.read_stat(pid).state
    except (OSError, ValueError):
        return _LockState.HELD  # it exited mid-read, or /proc cannot say: not proof either way
    return _LockState.ZOMBIE if state == "Z" else _LockState.HELD


def _reclaim_zombie_lock(number: int, state: _LockState | None = None) -> None:
    """Remove the lock of a server that has died and was never reaped.

    Xvfb starts over a lock whose pid is gone, but not over one whose pid is a
    zombie, and a zombie nobody reaps stays one: this CLI is PID 1's grandchild
    in a container whose PID 1 never waits, and an Xvfb it had to SIGKILL after
    its rung child was killed too is orphaned to that PID 1. Nothing else would
    ever remove such a lock, and each one would take a slot for good. Only a lock
    of ours naming a process that is a zombie is removed; anything else, a
    running server included, is left alone.

    The lock is moved aside and re-classified under the name only this process
    knows before it is unlinked. A read followed by an unlink of the original
    path could delete a lock another server wrote between the two syscalls; a
    lock that turns out not to be the zombie is put back instead.
    """
    lock = lock_path(number)
    if state is None:
        state = _lock_state(lock)
    if state is not _LockState.ZOMBIE:
        return
    aside = lock.with_name(f"{lock.name}.{os.getpid()}.{time.monotonic_ns()}.reclaim")
    try:
        os.rename(lock, aside)
    except FileNotFoundError:
        return
    if _lock_state(aside) is _LockState.ZOMBIE:
        aside.unlink(missing_ok=True)
        return
    try:
        os.link(aside, lock)  # put it back without replacing a lock written since
    except FileExistsError:
        # Another server wrote its own lock while this one was moved. Keep that
        # one and leave this file under its private name rather than delete a
        # lock that is not ours.
        return
    except OSError:
        # A directory or something else that hard links refuse still goes back.
        os.rename(aside, lock)
        return
    aside.unlink(missing_ok=True)


def display_is_free(number: int) -> bool:
    """Whether a second server on the slot would start: Xvfb's own lock, then its socket.

    A lock only counts while its server is alive. Whatever the lock says, the
    socket is asked one more question: does anything answer on it. A dead lock
    beside a live listener is another server's slot (review finding G6), and
    Xvfb refuses it ("server already running", exit 1, checked against a real
    server on 2026-11-03 with a stand-in listener on the abstract address), so
    claiming it only buys a failed start. A socket file with nothing listening
    and no lock is not a server: Xvfb starts over it (same day, a real server
    came up over such a file and removed it on SIGTERM), so it does not hold the
    slot either, and enough of them would have used up the 500 slots.

    A connect that fails for a reason other than "nothing is there" cannot say
    whether the slot is free, so the OSError is raised rather than reported as a
    taken slot: the caller names the local failure instead of saying all 500
    slots are busy.
    """
    if _lock_state(lock_path(number)) is not _LockState.FREE:
        return False
    return not _accepts_connections(number)


def free_display(preferred: str) -> int:
    """The first free slot at or after the preferred one, wrapping once.

    The spike's slot formula can collide; this keeps it as the start of a
    search rather than a claim, so two concurrent headed fetches get two
    displays instead of one dead one. Each candidate's lock is classified once;
    only a zombie's is re-read, to confirm it is still that zombie before the
    lock is moved aside.
    """
    low, high = XVFB_DISPLAY_LOW, XVFB_DISPLAY_HIGH
    start = int(preferred.lstrip(":"))
    for offset in range(high - low + 1):
        candidate = low + (start - low + offset) % (high - low + 1)
        state = _lock_state(lock_path(candidate))
        if state is _LockState.ZOMBIE:
            _reclaim_zombie_lock(candidate, state)
            state = _lock_state(lock_path(candidate))
        if state is _LockState.FREE and not _accepts_connections(candidate):
            return candidate
    raise RuntimeError(f"no free Xvfb display between :{low} and :{high}")


def xvfb_command(number: int) -> list[str]:
    """The measured Xvfb invocation with its display slot filled in."""
    return ["Xvfb", f":{number}", "-screen", "0", XVFB_SCREEN, "-nolisten", "tcp"]


@contextlib.contextmanager
def display(url: str, options: dict[str, Any], ctx: RungContext | None = None) -> Iterator[dict[str, Any]]:
    """Bring up a private display, and take it down again afterwards.

    Xvfb is spawned, given the measured settle, and *checked* before the
    browser is pointed at it: a display that never came up otherwise reads as a
    generic browser failure. ``DISPLAY`` is restored on the way out, because a
    process that keeps advertising a display it has already killed hands every
    later library in the same process a dead one.
    """
    previous = os.environ.get("DISPLAY")
    preferred = display_for_pid(os.getpid())
    retried: set[int] = set()
    for _ in range(XVFB_DISPLAY_HIGH - XVFB_DISPLAY_LOW + 1):
        number = free_display(preferred)
        # No `start_new_session`: Xvfb stays in this process's group. A rung is run
        # in a group of its own (`cli.run_rung_isolated`), so a stop of the rung
        # reaches the display server with the group's SIGTERM, which lets it remove
        # its lock, and with the group's SIGKILL when it will not.
        process = subprocess.Popen(
            xvfb_command(number),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # The error this attempt is leaving with, taken from the `except` below and
        # not from `sys.exc_info()`: that one also reports an exception the caller
        # is handling around this `with`, which would be blamed for a stop failure.
        in_flight: BaseException | None = None
        try:
            try:
                _await_display(number, process)
            except _DisplayCollision:
                preferred = f":{number + 1}"
                continue
            except _DisplayRetry as failure:
                # The slot is free again, so either the server that won it has
                # gone or ours is broken. One more try on the same slot tells
                # those apart; a second immediate exit reports the real error.
                if number in retried:
                    raise RuntimeError(str(failure)) from failure
                retried.add(number)
                preferred = f":{number}"
                continue
            os.environ["DISPLAY"] = f":{number}"
            yield zendriver.climb(url, options, ctx)
            return
        except BaseException as failure:
            in_flight = failure
            raise
        finally:
            if previous is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = previous
            try:
                try:
                    _stop_display(process)
                except Exception as stop_failure:
                    # A page that failed is the failure to report; a stop that
                    # also failed is a note on it. The note keeps the page error's
                    # own `__cause__`, and the failure stays an `Exception` so a
                    # KeyboardInterrupt or SystemExit during the stop is not
                    # swallowed. With no page error the stop failure is the error.
                    if in_flight is None:
                        raise
                    in_flight.add_note(f"the display stop also failed: {stop_failure}")
            finally:
                # `_stop_display` raises for a server that survives SIGKILL; the pipe
                # it was reading is closed either way.
                if process.stderr is not None:
                    process.stderr.close()
    raise RuntimeError("all Xvfb display allocations collided")


def _stop_display(process: subprocess.Popen) -> None:
    """Ask Xvfb to stop, so it removes its own lock and socket, and reap it.

    SIGKILL gives it no chance to, and every kill left one lock behind until
    the 500 slots ran out. The kill stays as the answer to a server that has
    not stopped within the grace period.

    The order and the kill are `stopping.stop_with_grace`, shared with the rung
    group's stop, so a SIGTERM that `main` turns into SystemExit during the wait
    still kills the server. What is particular to a display is here: it is a
    child with a handle, so "gone" is `Popen.wait`, which returns the instant it
    exits, and the kill is followed by the wait that reaps it. That wait is
    bounded by `KILL_WAIT_S`, not the SIGTERM grace: a server in uninterruptible
    sleep (a `/tmp` on a stalled mount, where it removes its lock) ignores
    SIGKILL until the call returns, and waiting without a limit would hold the
    rung's result for as long. It raises instead, so the failure is reported
    rather than the rung hanging.
    """

    def wait_gone(seconds: float) -> bool:
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return False
        return True

    def kill() -> None:
        process.kill()
        try:
            process.wait(timeout=stopping.KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Xvfb (pid {process.pid}) did not exit within {stopping.KILL_WAIT_S:g}s of SIGKILL"
            ) from None

    stopping.stop_with_grace(term=process.terminate, wait_gone=wait_gone, kill=kill)


def _lock_names(lock: Path, pid: int) -> bool:
    """Whether the lock file currently holds this pid. Unreadable counts as no."""
    try:
        return _read_lock(lock)[1] == pid
    except (OSError, ValueError):
        return False


def _accepts_connections(number: int, timeout_s: float = 1.0) -> bool:
    """Whether something answers a connect on the display's socket.

    The lock is written before the server binds its socket, so a lock naming our
    pid does not mean a client can connect yet (the measurement is in
    docs/things-that-look-like-bugs.md, "Rung 4 treats a display as ready…").
    A connect that succeeds is the proof, and both
    addresses are tried because Xvfb listens on the socket file and on the Linux
    abstract socket of the same name, and where it cannot create the file (a
    read-only or foreign `/tmp/.X11-unix`, which it tolerates) only the abstract
    one exists. The connection is closed without a word; the server drops a
    client that never sends its setup request.

    Only "nothing is there" answers False: no such socket file, or one that
    refuses the connection (a file left behind, or an abstract name nobody
    holds). A failure on one address is tried on the other before it is raised,
    because the file and the abstract socket are the same display: a permission
    error on a file another user left must not hide an abstract socket that
    answers. If neither address answers but one failed for a reason other than
    "nothing is there" (a connect that timed out on a full backlog, a
    permission error) that OSError is raised, because it does not say the slot
    is empty and a caller that read it as empty would hand out a slot that is
    in use.
    """
    path = os.fspath(socket_path(number))
    unknown: OSError | None = None
    for address in (path, "\0" + path):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(timeout_s)
            try:
                probe.connect(address)
            except (FileNotFoundError, ConnectionRefusedError):
                continue
            except OSError as error:
                unknown = unknown or error
                continue
            return True
    if unknown is not None:
        raise unknown
    return False


def _await_display(number: int, process: subprocess.Popen) -> None:
    """Wait for the lock the server itself writes and a socket that answers, or fail with its reason.

    A fixed sleep is what the spike did and it stays the floor, but a fixed
    sleep alone cannot tell a slow display from a dead one. The lock has to name
    this server: a slot reclaimed from a dead one still holds the old pid until
    the new server rewrites it, and that file is not evidence of anything. The
    lock is also written before the socket is bound, so it is not enough on its
    own either: the display is ready when a connect to it succeeds.
    """
    deadline = time.monotonic() + XVFB_READY_TIMEOUT_S
    time.sleep(XVFB_SETTLE_S)
    locked = False
    polls = 0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = (process.stderr.read() if process.stderr else b"").decode(errors="replace").strip()
            # Whether another server holds the slot is asked of the slot, the way
            # the search asked it, and not read off the words Xvfb printed: those
            # change between versions and wrappers, and a miss turned a lost race
            # for one slot into a failed rung with 499 free.
            if not display_is_free(number):
                raise _DisplayCollision(f"Xvfb :{number} was claimed by another server")
            # The slot is free now, so the server that beat us may already have
            # gone: asking the slot again cannot tell that from a broken Xvfb.
            # Trying the free slot once more can, without reading its words.
            raise _DisplayRetry(f"Xvfb :{number} exited immediately: {stderr or process.returncode}")
        # A lock that names this server cannot name anything else while it runs, so
        # it is read until it does and not again.
        locked = locked or _lock_names(lock_path(number), process.pid)
        if locked:
            # The connect is held to the time left, or a slot that never answers
            # could run the wait past its own deadline. A failure it cannot
            # explain is raised: after the deadline the server would be blamed
            # for a local problem (a full backlog, an unwritable socket).
            if _accepts_connections(number, timeout_s=max(0.0, min(1.0, deadline - time.monotonic()))):
                return
        # A ready display answers within milliseconds; after the first second
        # there is no point opening the lock and two sockets 20 times a second.
        polls += 1
        time.sleep(0.05 if polls <= 20 else 0.25)
    if locked:
        raise RuntimeError(f"Xvfb :{number} wrote its lock but never accepted a connection within {XVFB_READY_TIMEOUT_S:g}s")
    raise RuntimeError(f"Xvfb :{number} never wrote its lock within {XVFB_READY_TIMEOUT_S:g}s")


def launch_options() -> dict[str, Any]:
    """Rung 4 is rung 3 with the head taken off, and changes nothing else."""
    return {**zendriver.launch_options(), "headless": HEADLESS}


def fetch(url: str, ctx: RungContext | None = None) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise."""
    with display(url, launch_options(), ctx) as page:
        return page


# Rung 4 shares the wrapped rung's judge, exactly as it shares its climb: a
# trampoline here would re-state what its delegate already says.
judge = zendriver.judge
