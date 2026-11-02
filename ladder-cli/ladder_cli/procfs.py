"""What the kernel says about a process, asked in one place.

Three callers need the same two answers: the rung stop (is anything in the group
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

    The caller keeps its own check for a pid at or below zero: `kill(0, 0)` and
    `kill(-1, 0)` mean the caller's own group and everyone, not a process.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return Liveness.GONE
    except (PermissionError, OverflowError):
        return Liveness.UNKNOWN
    return Liveness.EXISTS
