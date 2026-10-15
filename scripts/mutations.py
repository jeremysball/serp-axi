#!/usr/bin/env python3
"""A named mutation gate: what the suite believes, and how each belief could fail.

A green suite only says the tests that exist still pass. It says nothing about
whether those tests would notice the thing they are supposed to notice. This
script is the mechanical answer to that gap, and it is deliberately not a
generic mutation tool.

A generic sweep reports surviving MUTANTS. This reports surviving BELIEFS. Every
entry below is one sentence this codebase holds to be true, paired with the
smallest edit that makes it false and the exact test that must go red when it
is. If a belief survives, that test is hollow: it agrees with the code rather
than with the claim.

That distinction is the whole point. When this file caught a real defect, the
report read "no rung carries its own budget SURVIVED", which names a false thing
the suite was willing to tolerate. A mutant id would have said "m_4 survived"
and told nobody what to think.

Usage:
    python3 scripts/mutations.py            # run every belief
    python3 scripts/mutations.py --list     # print the beliefs, change nothing
    python3 scripts/mutations.py only-frag  # run beliefs whose name matches

Exit status is non-zero if any belief survives, so this can gate CI.

Adding a belief is the act of writing down a claim. If you cannot name the
sentence and the test that should fail when it is false, the suite does not yet
hold that belief and pretending otherwise is the failure this file exists to
prevent.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LADDER = ROOT / "ladder-cli"
PYTEST = ["uv", "run", "--frozen", "--extra", "test", "pytest", "-q"]


@dataclass(frozen=True)
class Belief:
    """One sentence the suite claims to hold, plus the edit that falsifies it."""

    name: str
    path: Path
    old: str
    new: str
    test: str
    why: str


BELIEFS: list[Belief] = [
    # ---- the climb is one ordered ladder under one budget ----
    Belief(
        name="every rung in the climb is reachable",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")',
        new='RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf")',
        test="tests/test_escalation.py::test_every_rung_in_the_climb_is_reachable",
        why="A rung dropped from RUNGS is unreachable, so the climb silently loses a step.",
    ),
    Belief(
        name="the climb starts cheap and only reaches for a browser when it must",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")',
        new='RUNGS: tuple[str, ...] = ("camoufox", "http", "zendriver_cf", "zendriver_headed_cf")',
        test="tests/test_escalation.py::test_the_climb_starts_cheap_and_only_reaches_for_a_browser_when_it_must",
        why="The 80-in-100 case pays rung 1's cost alone, so a browser first is the wrong order.",
    ),
    Belief(
        name="every rung is killed by the same measured budget",
        path=LADDER / "ladder_cli/cli.py",
        old="DEFAULT_RUNG_TIMEOUT_S = 90.0",
        new="DEFAULT_RUNG_TIMEOUT_S = 1.0",
        test="tests/test_escalation.py::test_every_rung_is_killed_by_the_same_measured_budget",
        why="90s is the measured budget. A different number is a claim with no measurement behind it.",
    ),
    Belief(
        name="no rung carries its own budget",
        path=LADDER / "ladder_cli/cli.py",
        old="    budget = DEFAULT_RUNG_TIMEOUT_S if timeout_s is None else timeout_s",
        new='    budget = 5.0 if rung == "http" else DEFAULT_RUNG_TIMEOUT_S',
        test="tests/test_escalation.py::test_no_rung_carries_its_own_budget",
        why="One deadline, one owner. A per-rung budget gives one deadline two owners.",
    ),
]


def _forget_imports() -> None:
    """Drop every compiled cache before a run.

    Python invalidates bytecode by source mtime AND size. A mutant that preserves
    byte length (base.en to tiny.en) written inside the same timestamp tick leaves
    the stale .pyc valid, so pytest imports the OLD module and the belief reports
    SURVIVED even though its test would have caught it. That false confidence is
    worse than no gate at all, so caches are cleared every run and bytecode is
    never written back.
    """
    for cache in LADDER.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def run_tests(selector: str) -> tuple[str, str]:
    """Return (outcome, last_line) where outcome is pass, fail, or error.

    The verdict comes from pytest's exit code, not the last output line. A
    changed summary format or a traceback tail can omit the word "failed" and
    turn a real kill into a false SURVIVED, which is the safe-direction lie this
    gate exists to prevent. Exit 5 means no tests were collected, so the selector
    matches nothing; that is an invalid entry and never a kill.
    """
    _forget_imports()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        PYTEST + [selector], cwd=LADDER, capture_output=True, text=True, timeout=600, env=env
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    last = tail[-1] if tail else "(no output)"
    if proc.returncode == 0:
        return "pass", last
    if proc.returncode == 1:
        # The only code that means "these tests ran and failed".
        return "fail", last
    # 4 is a usage error (a test id that matches nothing) and 5 is no tests
    # collected. Both mean the belief cannot demonstrate anything. A typo'd id
    # returning "fail" would count as a kill and have the gate certify itself.
    return "error", last


_BASELINE: dict[str, tuple[str, str]] = {}


def _baseline(selector: str) -> tuple[str, str]:
    """The belief's own test on unmutated code, cached per selector.

    Without this a belief whose test is already red, or whose id is a typo,
    counts as a kill: the mutation "broke" a test that was already broken. That
    lets the gate certify itself, so every belief must first prove its test
    passes on clean code.
    """
    if selector not in _BASELINE:
        _BASELINE[selector] = run_tests(selector)
    return _BASELINE[selector]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("match", nargs="?", help="only beliefs whose name contains this")
    parser.add_argument("--list", action="store_true", help="print beliefs and exit")
    args = parser.parse_args()

    chosen = [b for b in BELIEFS if not args.match or args.match in b.name]
    if args.list:
        for belief in chosen:
            print(f"- {belief.name}\n    test: {belief.test}\n    why:  {belief.why}")
        return 0

    if not chosen:
        print("no beliefs matched", file=sys.stderr)
        return 2

    survived: list[Belief] = []
    invalid: list[Belief] = []
    killed = 0

    for belief in chosen:
        original = belief.path.read_text()
        hits = original.count(belief.old)
        if hits != 1:
            # A belief that can no longer be applied is itself a failure: the code
            # moved and nobody updated the claim, so this entry is now fiction.
            print(f"INVALID   [{belief.name}]: pattern found {hits}x in {belief.path.name}")
            invalid.append(belief)
            continue

        base, base_last = _baseline(belief.test)
        if base != "pass":
            # The belief cannot demonstrate anything: its test is already red on
            # clean code, or matches no test at all. Counting that as a kill would
            # have the gate certifying itself.
            print(f"INVALID   [{belief.name}]: its test is {base} on clean code ({base_last})")
            invalid.append(belief)
            continue

        belief.path.write_text(original.replace(belief.old, belief.new, 1))
        try:
            outcome, last = run_tests(belief.test)
        finally:
            belief.path.write_text(original)

        if outcome == "fail":
            killed += 1
            print(f"killed    [{belief.name}]")
        else:
            survived.append(belief)
            print(f"SURVIVED  [{belief.name}] -> {last}")
            print(f"          hollow test: {belief.test}")
            print(f"          consequence: {belief.why}")

    print()
    print(f"{killed}/{len(chosen)} beliefs killed")
    if survived:
        print(f"\n{len(survived)} hollow test(s): the suite does not hold these beliefs.")
        for belief in survived:
            print(f"  - {belief.name}")
    if invalid:
        print(f"\n{len(invalid)} stale entr(ies): the code moved and the claim did not.")
        for belief in invalid:
            print(f"  - {belief.name}")

    return 1 if (survived or invalid) else 0


if __name__ == "__main__":
    sys.exit(main())
