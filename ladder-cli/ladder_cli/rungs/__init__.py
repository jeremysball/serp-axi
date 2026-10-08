"""Rung registry and the verdict rules every rung shares.

A rung reports what it saw; this module decides what that means. Verdicts are
``ok``, ``dead``, and ``blocked``, the same three words as the spike ledger so
fixture rows stay comparable. ``error`` is rung-local: it means the rung itself
malfunctioned, which is never allowed to leave the child as a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol as TypingProtocol

# Dependency order. Phase 3 adds camoufox, zendriver_cf, zendriver_headed_cf;
# Phase 4 adds whisper for audio challenges.
RUNGS: tuple[str, ...] = ("http",)


class RungVerdict(Enum):
    OK = "ok"
    DEAD = "dead"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class RungResult:
    verdict: RungVerdict
    title: str = ""
    text: str = ""
    status: int | None = None
    reason: str = ""


class RungModule(TypingProtocol):
    def fetch(self, url: str) -> dict[str, Any]: ...

    def judge(self, page: dict[str, Any]) -> RungResult: ...


# Imported last: each rung module imports RungResult and RungVerdict from here,
# so binding the submodules before those names exist would start a cycle.
from . import http  # noqa: E402

MODULES: dict[str, RungModule] = {"http": http}


def fetch(rung: str, url: str) -> dict[str, Any]:
    return MODULES[rung].fetch(url)


def judge(rung: str, page: dict[str, Any]) -> RungResult:
    return MODULES[rung].judge(page)


def network_verdict(message: str) -> RungVerdict:
    """Map a child that produced no record at all.

    A DNS or TLS failure on rung 1 is final: no browser revives a domain that
    does not resolve, so it reads ``dead``. Anything else is the rung
    malfunctioning, which climbs rather than being reported to the caller.
    """
    if http.DEAD_NET.search(message):
        return RungVerdict.DEAD
    return RungVerdict.ERROR
