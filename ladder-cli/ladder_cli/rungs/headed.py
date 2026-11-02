"""Rung 4: rung 3 with a virtual display in front of it.

Some defences look for a real display before they believe a browser. This rung
is zendriver's fetch with the head taken off and an Xvfb screen behind it, so
nothing about how a page is handled is restated here. What it owns is only what
the measured run varied to get a headed browser: the display.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
# How long Xvfb gets after SIGTERM to remove its lock before it is killed. It
# exits in milliseconds when asked; this only bounds a server that is wedged.
XVFB_STOP_TIMEOUT_S = 5.0


class _DisplayCollision(RuntimeError):
    pass


def display_for_pid(pid: int) -> str:
    """ladder.py:105 `disp = f":{200 + os.getpid() % 500}"`, as a search start."""
    return f":{XVFB_DISPLAY_LOW + pid % (XVFB_DISPLAY_HIGH - XVFB_DISPLAY_LOW + 1)}"


def _lock_is_held(lock: Path) -> bool:
    """Whether the server named in an Xvfb lock file is still there.

    The lock holds the server's pid. Xvfb itself starts over a lock whose pid is
    gone, so a leftover from a SIGKILL, a crash or a reboot does not take the
    slot. Anything that cannot be read as a live-or-dead pid counts as held:
    claiming a slot needs proof the server is dead, not the absence of proof.
    """
    try:
        pid = int(lock.read_text().strip())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def display_is_free(number: int) -> bool:
    """Xvfb's own lock, which is what a second server on the slot would fail on.

    A lock only counts while its server is alive; a socket with no lock at all
    still counts, since nothing says whose it is.
    """
    lock = Path(f"/tmp/.X{number}-lock")
    if lock.exists():
        return not _lock_is_held(lock)
    return not Path(f"/tmp/.X11-unix/X{number}").exists()


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
    """
    process.terminate()
    try:
        process.wait(timeout=XVFB_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _await_display(number: int, process: subprocess.Popen) -> None:
    """Wait for the lock the server itself writes, or fail with its reason.

    A fixed sleep is what the spike did and it stays the floor, but a fixed
    sleep alone cannot tell a slow display from a dead one.
    """
    deadline = time.monotonic() + XVFB_READY_TIMEOUT_S
    time.sleep(XVFB_SETTLE_S)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = (process.stderr.read() if process.stderr else b"").decode(errors="replace").strip()
            if "Server is already active for display" in stderr:
                raise _DisplayCollision(f"Xvfb :{number} was claimed by another server")
            raise RuntimeError(f"Xvfb :{number} exited immediately: {stderr or process.returncode}")
        if Path(f"/tmp/.X{number}-lock").exists():
            return
        time.sleep(0.05)
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
