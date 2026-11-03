"""Ask something to stop, give it a grace period, and kill what did not.

Two things in this CLI are stopped on a deadline: a rung's process group
(`cli._stop_group`) and the display server a headed rung starts
(`headed._stop_display`). Each used to carry its own SIGTERM-wait-SIGKILL loop,
and only the group's put the SIGKILL in a `finally`, so a SIGTERM that `main`
turned into SystemExit during the display's wait left the server running. The
order, the grace period handed in and the kill that cannot be skipped live here
once; what differs between the two (how to signal, and how to tell it is gone)
stays with each caller as a callback.

This module imports nothing from the package, so any module can import it.
"""

from __future__ import annotations

from typing import Callable


def stop_with_grace(
    *,
    term: Callable[[], None],
    wait_gone: Callable[[float], bool],
    kill: Callable[[], None],
    grace_s: float,
) -> None:
    """Send `term`, wait up to `grace_s` seconds for the target to be gone, else `kill`.

    `wait_gone(seconds)` returns True once the target is gone and False if
    `seconds` ran out first. It is the one place the two callers differ: a
    `Popen` can be waited on and returns the instant it exits, while a process
    group has no wait and is polled.

    `kill` runs in a `finally`, so it runs whether `wait_gone` said the target was
    still there, or `term` or `wait_gone` raised. `main` turns SIGTERM into
    SystemExit, which can surface in either, and a SystemExit that skipped the
    kill would leave behind the very thing that ignored the first request. `term`
    is inside the `try` for that reason: a SystemExit out of it is a stop that has
    sent nothing, and the kill is still owed. The exception then propagates.

    `grace_s` has no default so that a caller cannot pass a number of its own by
    leaving it out: both read `rungs.STOP_GRACE_S`.
    """
    gone = False
    try:
        term()
        gone = wait_gone(grace_s)
    finally:
        if not gone:
            kill()
