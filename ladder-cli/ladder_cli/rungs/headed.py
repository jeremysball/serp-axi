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
from pathlib import Path
from typing import Any

from .. import procfs
from ..stopping import stop_with_grace
from . import STOP_GRACE_S, RungContext, RungResult, zendriver

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
# What a lock may hold before it is not one Xvfb wrote. Xvfb writes `"%10d\n"`,
# eleven bytes (read off a real server's lock, 2026-11-02). The bound is looser
# than that on purpose: it is there to refuse a file with more in it, not to
# pin the format.
LOCK_MAX_BYTES = 64


# What Xvfb prints when another server holds the slot. The first is the lock
# (a live pid in it), the second the socket (something already listening, which
# a dead lock does not show). Both are the slot being taken, not Xvfb being broken.
XVFB_COLLISION_MESSAGES = ("Server is already active for display", "server already running")


class _DisplayCollision(RuntimeError):
    pass


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


def _lock_is_held(lock: Path) -> bool:
    """Whether the server named in an Xvfb lock file is still there.

    The lock holds the server's pid. Xvfb itself starts over a lock whose pid is
    gone (tested against a real server), so a leftover from a SIGKILL, a crash
    or a reboot does not take the slot. Anything that cannot be read as a
    live-or-dead pid counts as held: claiming a slot needs proof the server is
    dead, not the absence of proof. That includes a lock another user owns,
    since /tmp is sticky and Xvfb could not remove it to start over, a lock that
    is not a regular file, and a pid too large to probe at all (`os.kill` raises
    OverflowError for those).

    Raises FileNotFoundError when there is no lock, so the caller decides what
    an absent lock means with one read rather than a stat and a read.
    """
    try:
        owner, pid = _read_lock(lock)
    except FileNotFoundError:
        raise
    except (OSError, ValueError):
        return True
    if owner != os.getuid() or pid <= 0:
        return True
    # A zombie counts as held: it still occupies the pid, and Xvfb treats a lock
    # whose pid answers signal 0 as active.
    return procfs.probe(pid) is not procfs.Liveness.GONE


def display_is_free(number: int) -> bool:
    """Xvfb's own lock, which is what a second server on the slot would fail on.

    A lock only counts while its server is alive; a socket with no lock at all
    still counts, since nothing says whose it is. A slot whose lock says free is
    asked one more question: does anything answer on its socket. A dead lock
    beside a live listener is another server's slot (review finding G6), and
    Xvfb refuses it ("server already running", exit 1, checked against a real
    server on 2026-11-03 with a stand-in listener on the abstract address), so
    claiming it only buys a failed start.
    """
    try:
        if _lock_is_held(Path(f"/tmp/.X{number}-lock")):
            return False
    except FileNotFoundError:
        if Path(f"/tmp/.X11-unix/X{number}").exists():
            return False
    return not _accepts_connections(number)


def free_display(preferred: str) -> int:
    """The first free slot at or after the preferred one, wrapping once.

    The spike's slot formula can collide; this keeps it as the start of a
    search rather than a claim, so two concurrent headed fetches get two
    displays instead of one dead one.
    """
    low, high = XVFB_DISPLAY_LOW, XVFB_DISPLAY_HIGH
    start = int(preferred.lstrip(":"))
    for offset in range(high - low + 1):
        candidate = low + (start - low + offset) % (high - low + 1)
        if display_is_free(candidate):
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
    for _ in range(XVFB_DISPLAY_HIGH - XVFB_DISPLAY_LOW + 1):
        number = free_display(preferred)
        process = subprocess.Popen(
            xvfb_command(number),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            try:
                _await_display(number, process)
            except _DisplayCollision:
                preferred = f":{number + 1}"
                continue
            os.environ["DISPLAY"] = f":{number}"
            yield zendriver.climb(url, options, ctx)
            return
        finally:
            if previous is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = previous
            _stop_display(process)
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
    exits, and the kill is followed by the wait that reaps it.
    """

    def wait_gone(seconds: float) -> bool:
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return False
        return True

    def kill() -> None:
        process.kill()
        process.wait()

    stop_with_grace(term=process.terminate, wait_gone=wait_gone, kill=kill, grace_s=STOP_GRACE_S)


def _lock_names(lock: Path, pid: int) -> bool:
    """Whether the lock file currently holds this pid. Unreadable counts as no."""
    try:
        return _read_lock(lock)[1] == pid
    except (OSError, ValueError):
        return False


def _accepts_connections(number: int) -> bool:
    """Whether something answers a connect on the display's socket.

    The lock is written before the server binds its socket, so a lock naming our
    pid does not mean a client can connect yet. Measured against a real Xvfb on
    2026-11-03: of 200 starts, 39 showed the lock before the socket, by 0.012 to
    0.071 ms on an idle machine. A connect that succeeds is the proof, and both
    addresses are tried because Xvfb listens on the socket file and on the Linux
    abstract socket of the same name, and where it cannot create the file (a
    read-only or foreign `/tmp/.X11-unix`, which it tolerates) only the abstract
    one exists. The connection is closed without a word; the server drops a
    client that never sends its setup request.
    """
    path = os.fspath(Path(f"/tmp/.X11-unix/X{number}"))
    for address in (path, "\0" + path):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            try:
                probe.connect(address)
            except OSError:
                continue
            return True
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
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = (process.stderr.read() if process.stderr else b"").decode(errors="replace").strip()
            if any(message in stderr for message in XVFB_COLLISION_MESSAGES):
                raise _DisplayCollision(f"Xvfb :{number} was claimed by another server")
            raise RuntimeError(f"Xvfb :{number} exited immediately: {stderr or process.returncode}")
        if _lock_names(Path(f"/tmp/.X{number}-lock"), process.pid):
            locked = True
            if _accepts_connections(number):
                return
        time.sleep(0.05)
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
