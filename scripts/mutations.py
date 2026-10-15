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
        old='    "zendriver_headed_cf": headed,' + chr(10) + '    "whisper": whisper,' + chr(10) + "}",
        new='    "zendriver_headed_cf": headed,' + chr(10) + "}",
        test="tests/test_escalation.py::test_every_rung_in_the_climb_is_reachable",
        why="A rung in RUNGS with no module is a dead step: the climb reaches for nothing.",
    ),
    Belief(
        name="the climb starts cheap and only reaches for a browser when it must",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf", "whisper")',
        new='RUNGS: tuple[str, ...] = ("camoufox", "http", "zendriver_cf", "zendriver_headed_cf", "whisper")',
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
    # ---- rung 5's model is a resource of the process, not of one fetch ----
    Belief(
        name="the laziness counter reports what actually happened",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="    return _loads",
        new="    return 1",
        test="tests/test_rungs_whisper.py::test_importing_the_module_loads_nothing",
        why="A counter that lies makes the zero-load claim unfalsifiable at a glance.",
    ),
    Belief(
        name="the model is built once per resident child's life",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="    if _model is None:",
        new="    if True:",
        test="tests/test_rungs_whisper.py::test_the_model_is_built_once_per_cli_life_not_once_per_fetch",
        why="Rebuilding per fetch re-pays the construction the rung exists to avoid.",
    ),
    Belief(
        name="the model cache holds the model it built",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="        _model = model",
        new="        _model = None",
        test="tests/test_rungs_whisper.py::test_the_model_is_built_once_across_fetches_in_the_resident_child",
        why="Discarding it means every fetch rebuilds while the counter still says one.",
    ),
    Belief(
        name="rung 5 runs in the resident child, never the killable subprocess",
        path=LADDER / "ladder_cli/cli.py",
        old='    if rung != "whisper":',
        new="    if True:",
        test="tests/test_rungs_whisper.py::test_rung_five_is_never_sent_to_the_killable_subprocess",
        why="A subprocess is a fresh interpreter per fetch, so the model dies with it.",
    ),
    Belief(
        name="the model is the measured base.en",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old='MODEL_NAME = "base.en"',
        new='MODEL_NAME = "tiny.en"',
        test="tests/test_rungs_whisper.py::test_the_construction_carries_the_measured_arguments",
        why="A constant ported from a measured run is a claim about that run.",
    ),
    Belief(
        name="transcription uses the measured beam size",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="load().transcribe(path, language=LANGUAGE, beam_size=BEAM_SIZE)",
        new="load().transcribe(path, language=LANGUAGE)",
        test="tests/test_rungs_whisper.py::test_transcription_carries_the_measured_arguments",
        why="q5_audio.py:47 pinned beam_size=5; dropping it is a silent decode change.",
    ),
    Belief(
        name="an answer is sanitised to words and digits",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old='    return re.sub(r"[^a-z0-9 ]", "", transcript.lower()).strip()',
        new="    return transcript.lower().strip()",
        test="tests/test_rungs_whisper.py::test_the_answer_is_the_measured_sanitised_form_of_the_transcript",
        why="The challenge field wants only the words and digits it asked for.",
    ),
    Belief(
        name="the three-round budget is a ceiling",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="list(clips)[:MAX_ROUNDS]",
        new="list(clips)",
        test="tests/test_rungs_whisper.py::test_the_measured_loop_stops_at_three_clips_no_matter_how_many_are_offered",
        why="q5_audio.py:42 stopped at three; answering a fourth is a different run.",
    ),
    # ---- the cookie jar is filtered, on both sides ----
    Belief(
        name="only the four defence cookies travel",
        path=LADDER / "ladder_cli/state/jars.py",
        old='KEEP: tuple[str, ...] = ("cf_clearance", "_px3", "_pxhd", "datadome")',
        new='KEEP: tuple[str, ...] = ("cf_clearance", "_px3", "_pxhd")',
        test="tests/test_jars.py::test_only_the_defence_cookies_the_spike_kept_are_kept",
        why="solver_probe.py:27 named four; a browsing cookie has no business here.",
    ),
    Belief(
        name="a cookie's scope stops at a label boundary",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    return scope == base or scope.endswith("." + base)',
        new="    return scope.endswith(base)",
        test="tests/test_jars.py::test_the_domain_match_stops_at_a_label_boundary",
        why='"evil-example.com".endswith("example.com") is true: lookalikes get in.',
    ),
    Belief(
        name="the browser rungs agree on a verdict",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="judge = browser_judge",
        new='judge = lambda page: browser_judge({"title": "", "text": "", "status": 404})',
        test="tests/test_fixture_replay.py::test_the_browser_rungs_apply_one_set_of_rules",
        why="A page judged twice must not read differently because it climbed twice.",
    ),
    Belief(
        name="the filter refuses a URL it cannot scope rather than crashing",
        path=LADDER / "ladder_cli/state/jars.py",
        old=(
            '    if "://" not in url:' + chr(10)
            + "        return None" + chr(10)
            + "    return urlparse(url).hostname"
        ),
        new='    return url.split("/")[2]',
        test="tests/test_jars.py::test_a_url_the_filter_cannot_scope_is_rejected_rather_than_crashed",
        why="A raw string split raises IndexError on a scheme-less URL and keeps :port in the scope.",
    ),
    Belief(
        name="a multi-label public suffix is not the base domain",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES:',
        new="    if False:",
        test="tests/test_jars.py::test_a_multi_label_public_suffix_is_not_treated_as_the_base_domain",
        why="Two labels turns www.bbc.co.uk into co.uk and lets every .co.uk sibling through.",
    ),
    Belief(
        name="loading a jar re-applies the filter rather than trusting the file",
        path=LADDER / "ladder_cli/state/jars.py",
        old="    return filter_cookies(cookies, url)",
        new="    return cookies",
        test="tests/test_jars.py::test_loading_a_jar_re_applies_the_filter_rather_than_trusting_the_file",
        why="A jar is data on disk and anything can widen one by hand.",
    ),
    Belief(
        name="a killed browser's profile locks are all cleared",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    "SingletonSocket",' + chr(10) + ")",
        new='    "SingletonSocket",' + chr(10) + '    "never-existed",' + chr(10) + ")",
        test="tests/test_jars.py::test_a_killed_browser_leaves_no_lock_behind_for_the_next_launch",
        why="The test pins the measured five names; a sixth must not pass as five.",
    ),
    Belief(
        name="the jar is named after the profile it belongs to",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    return profile_dir / f"{name}.cookies.dat"',
        new='    return profile_dir / f"{name}.jar"',
        test="tests/test_jars.py::test_the_jar_path_is_named_after_the_profile",
        why="solver_probe.py:86 named it <name>.cookies.dat; the name is the contract.",
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
