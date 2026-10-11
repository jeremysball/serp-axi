"""Warmed browser profiles.

A profile is warmed once and reused for the CLI's whole life (04-tdd 1.5), so
the layout has one owner. The names are carried from the measured run, which
kept one user-data directory per headed-ness (ladder.py:82), not one per
request.

One directory per *named* profile is not here on purpose. A rung is handed a
URL and nothing else (``fetch(url)``), so it cannot tell which ``--profile``
the caller asked for; that split belongs where the request is known, and
putting a half of it here would leave a layout nothing reads.
"""

from __future__ import annotations

from pathlib import Path

# ladder.py:213 `os.makedirs("profiles", exist_ok=True)`. Made absolute at the
# use below, exactly as the spike's `os.path.abspath(f"profiles/...")` was:
# the rung child inherits whatever CWD launched the CLI, and a relative
# user-data-dir is resolved by the browser against *its* CWD, which can differ.
#
# There is deliberately no environment variable here. 04-tdd 1.2 resolves
# where a store lives in TypeScript before the request is built, "so the CLI
# never reads env or config itself". A second knob here would make this the
# second owner of one decision, which is the same shape as the
# LADDER_RUNG_TIMEOUT_S second budget f2cf1cd removed.
DEFAULT_ROOT = "profiles"


def root() -> Path:
    """Where warmed profiles live for this CLI's life.

    Absolute, per the spike's ``os.path.abspath`` (ladder.py:82), so the path a
    rung warms and the path the browser resolves as its user-data-dir are the
    same directory rather than two opinions about where the CLI was launched.
    """
    return Path(DEFAULT_ROOT).resolve()


def zendriver_dir(base: Path, *, headed: bool) -> Path:
    """The measured zendriver profile layout.

    ladder.py:82 `user_data_dir=os.path.abspath(f"profiles/zd{'_headed' if headed else ''}")`.
    Headed and headless are separate profiles because they are separate
    browsers: sharing one would let a headed run's fingerprints and cookies
    leak into a headless run and make the two rungs look alike to a defence.
    """
    return base / ("zd_headed" if headed else "zd")


def warm(path: Path) -> Path:
    """Create a profile directory if it is absent, and pass it through if not.

    Idempotent on purpose. Warming an already-warm profile must not clear what
    it holds, or the second request loses the cookies the first one earned and
    pays its cold start again.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
