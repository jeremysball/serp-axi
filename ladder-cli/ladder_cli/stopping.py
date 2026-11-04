"""Ask something to stop, give it a grace period, and kill what did not.

Two things in this CLI are stopped on a deadline: a rung's process group
(`cli._stop_group`) and the display server a headed rung starts
(`headed._stop_display`). Each used to carry its own SIGTERM-wait-SIGKILL loop,
and only the group's put the SIGKILL in a `finally`, so a SIGTERM that `main`
turned into SystemExit during the display's wait left the server running. The
order, the grace period and the kill that cannot be skipped live here once; what
differs between the two (how to signal, and how to tell it is gone) stays with
each caller as a callback.

This module imports nothing from the package, so any module can import it.
"""

from __future__ import annotations

from typing import Callable

# How long anything this CLI stops (a rung's process group, the display server it
# started) gets after SIGTERM to clean up before it is SIGKILLed. A bound for one
# that does not stop when asked, not a measured stop time. It lives here, the one
# module both stops go through, and `stop_with_grace` reads it when it runs, so
# there is no second copy to drift and a test that sets `stopping.STOP_GRACE_S`
# changes both stops.
STOP_GRACE_S = 5.0

# How long `cli._reap` keeps reading a stopped rung's pipes after the stop. Not
# `STOP_GRACE_S`: a descendant outside the group can hold the pipes open, which
# is a different question from how long the group gets to answer SIGTERM, and
# tuning one must not silently retune the other. A separate named bound, not a
# second copy of the number: 5.0 is today's value, not a value it has to share.
PIPE_DRAIN_S = 5.0

# How long a target that survived SIGKILL gets to finish dying before the stop
# raises. A process in uninterruptible sleep ignores SIGKILL until its call
# returns. Separate from `STOP_GRACE_S` for the same reason as `PIPE_DRAIN_S`:
# it measures a different thing.
KILL_WAIT_S = 5.0


def stop_with_grace(
    *,
    term: Callable[[], None],
    wait_gone: Callable[[float], bool],
    kill: Callable[[], None],
    always_kill: bool = False,
) -> None:
    """Send `term`, wait up to `STOP_GRACE_S` seconds for the target to be gone, else `kill`.

    `wait_gone(seconds)` returns True once the target is gone and False if
    `seconds` ran out first. It is the one place the two callers differ: a
    `Popen` can be waited on and returns the instant it exits, while a process
    group has no wait and is polled.

    `kill` runs in a `finally`, so it runs whether `wait_gone` said the target was
    still there, or `term` or `wait_gone` raised. A `SystemExit` that `main`'s
    SIGTERM handler raises can surface in either, but only in the resident loop:
    `main` installs that handler for the loop and returns before it for a
    `--rung` child, where a SIGTERM takes the default action and ends the process
    wherever it is (pinned by
    `test_a_rung_child_takes_sigterm_as_the_default_action_not_via_the_resident_handler`).
    So in a rung child the `finally` guards any other exception
    during the wait (a failing `/proc` read, a `KeyboardInterrupt`), and the
    process ending on SIGTERM is covered by the display server sharing the rung's
    process group, which gets the group's SIGTERM and SIGKILL itself (see
    `headed.display`).

    `always_kill` asks for `kill` even when `wait_gone` said the target was gone.
    The group stop needs that: one `/proc` scan is not atomic, so "nothing
    running" can miss a child forked and gone again between two reads. The
    leader is not reaped until after this routine returns, so the group id is
    still ours and a SIGKILL to an empty group does nothing.

    The grace period is not a parameter: a caller that could pass its own number
    is a second constant for the two stops to disagree on. `STOP_GRACE_S` is read
    here, when the stop runs, so changing it changes both.
    """
    gone = False
    try:
        term()
        gone = wait_gone(STOP_GRACE_S)
    finally:
        if not gone or always_kill:
            kill()
