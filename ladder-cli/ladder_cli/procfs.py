"""What the kernel says about a process, asked in one place.

Three callers need the same answers: the rung stop (is anything in the group
still running), the profile lock cleanup (is the owner still running) and the
display lock check (is the server still there). Each used to carry its own copy
of the `/proc/<pid>/stat` parse and of the `os.kill(pid, 0)` classification, and
the copies had already drifted once, when one learned that `os.kill` raises
OverflowError for a pid past a pid_t and another did not.

What each caller does with a zombie is not decided here. A zombie "exists" to
`probe`; the display lock check counts that as held, since Xvfb does too, and the
profile lock cleanup reads `read_stat` to tell it from a running owner.

This module imports nothing from the package, so any module can import it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# A name another module or a test can point at a fake tree, which is the only way
# to exercise a /proc that cannot be listed or a stat that cannot be read.
PROC = Path("/proc")


@dataclass(frozen=True)
class Stat:
    """The two fields of `/proc/<pid>/stat` the callers use."""

    state: str
    pgrp: int


class Liveness(Enum):
    GONE = "gone"  # no such process
    EXISTS = "exists"  # a process with that pid is there; a zombie counts
    UNKNOWN = "unknown"  # it cannot be asked about: someone else's, or a pid past what a pid_t holds


def read_stat(pid: int) -> Stat:
    """The state and process group of `pid`, from `/proc/<pid>/stat`.

    The line is `pid (comm) state ppid pgrp ...`. The comm field is a process
    name, so it can hold spaces and parentheses of its own; the fields that
    follow are taken after its last `)`.

    Raises OSError when the file cannot be read (FileNotFoundError when the
    process has exited) and ValueError when what it holds is not a stat line.
    """
    text = (PROC / str(pid) / "stat").read_text()
    try:
        fields = text.rsplit(")", 1)[1].split()
        return Stat(state=fields[0], pgrp=int(fields[2]))
    except (IndexError, ValueError) as error:
        raise ValueError(f"{PROC / str(pid) / 'stat'} is not a stat line: {text[:80]!r}") from error


def probe(pid: int) -> Liveness:
    """Whether a process with this pid exists, by signal 0, which sends nothing.

    A pid at or below zero is not a process: `kill(0, 0)` and `kill(-1, 0)` mean
    the caller's own group and everyone, and both succeed. They are UNKNOWN here,
    so a lock file that holds `0` or `-1` cannot read as a live owner by way of a
    caller that forgot to check.
    """
    if pid <= 0:
        return Liveness.UNKNOWN
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return Liveness.GONE
    except (PermissionError, OverflowError):
        return Liveness.UNKNOWN
    return Liveness.EXISTS


def has_running_member(group: int) -> bool:
    """One pass over /proc: whether a process in the group is running, which a zombie is not.

    A process that is not readable is not taken for gone. Only an exit says "gone"
    (FileNotFoundError, or ProcessLookupError, which is what reading a stat file
    raises once the process behind an already-open file has been reaped; or
    `getpgid` raising ProcessLookupError; the kernel behavior is checked by
    `test_an_open_stat_file_raises_process_lookup_error_after_its_process_is_reaped`);
    any other reason a stat cannot be
    read, such as a `hidepid` mount or a stat line that does not parse, falls
    back to `getpgid`, which asks the kernel for the group without needing the
    read to succeed. If that says the process is in this group, it counts as
    running, because it cannot be shown to be a zombie. If `getpgid` cannot
    answer either (EPERM), the process gets no vote.

    If /proc cannot be listed at all, or nothing in it could be classified, the
    answer is True: the caller already knows something is in the group, and with
    no way to look closer that stays the answer, so the grace period decides,
    not a crash and not an early "stopped".
    """
    try:
        entries = [entry for entry in PROC.iterdir() if entry.name.isdigit()]
    except OSError:
        return True
    classified = False
    for entry in entries:
        pid = int(entry.name)
        try:
            stat = read_stat(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue  # it exited between the listing and the read
        except (OSError, ValueError):
            try:
                if os.getpgid(pid) == group:
                    return True
            except OSError:
                continue  # ProcessLookupError: it exited; anything else: no answer, so no vote
            classified = True
            continue
        classified = True
        if stat.pgrp == group and stat.state != "Z":
            return True
    return not classified


def group_is_running(group: int) -> bool:
    """Whether anything in the process group is running.

    `killpg(group, 0)` also succeeds while an unreaped zombie is in the group. A
    rung's grandchild orphaned to a PID 1 that never waits stays one for good,
    which made every stop spend its whole grace period on a group with nothing
    running in it. So a group the kernel still knows is read through
    `has_running_member`, which tells a zombie from a running process.
    """
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return has_running_member(group)
