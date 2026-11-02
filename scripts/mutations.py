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
import tempfile
from contextlib import contextmanager
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
        old='    "zendriver_headed_cf": headed,',
        new='',
        test="tests/test_escalation.py::test_every_rung_in_the_climb_is_reachable",
        why="A rung in RUNGS with no module is a dead step: the climb reaches for nothing.",
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
        new='    budget = 5.0 if rung == "http" else (DEFAULT_RUNG_TIMEOUT_S if timeout_s is None else timeout_s)',
        test="tests/test_escalation.py::test_no_rung_carries_its_own_budget",
        why="One deadline, one owner. A per-rung budget gives one deadline two owners.",
    ),
    # ---- unwired audio helpers cache only within their own process ----
    Belief(
        name="audio helper imports do not construct a model",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="_model: Any | None = None",
        new="_model: Any | None = object()",
        test="tests/test_rungs_whisper.py::test_importing_the_module_loads_nothing",
        why="Importing optional audio helpers must leave the model unloaded.",
    ),
    Belief(
        name="the audio helper reuses its model within one process",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="    if _model is None:",
        new="    if True:",
        test="tests/test_rungs_whisper.py::test_the_helper_reuses_one_model_within_its_process",
        why="Repeated helper calls should not reconstruct their model.",
    ),
    Belief(
        name="the model cache holds the model it built",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="        _model = _build(device=DEVICE, compute_type=COMPUTE_TYPE)",
        new="        _build(device=DEVICE, compute_type=COMPUTE_TYPE)",
        test="tests/test_rungs_whisper.py::test_the_helper_reuses_one_model_within_its_process",
        why="Discarding the constructed model makes the next helper call rebuild it.",
    ),
    Belief(
        name="ceiling five stops at the last implemented rung",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='"zendriver_headed_cf")',
        new='"zendriver_headed_cf", "whisper")',
        test="tests/test_escalation.py::test_ceiling_five_stops_at_the_last_implemented_rung",
        why="An unwired audio helper must not become a duplicate browser attempt.",
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
        old="islice(clips, MAX_ROUNDS)",
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
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="judge = zendriver.judge",
        new='judge = lambda page: zendriver.judge({"title": "", "text": "", "status": 404})',
        test="tests/test_fixture_replay.py::test_the_browser_rungs_apply_one_set_of_rules",
        why="A page judged twice must not read differently because it climbed twice.",
    ),
    Belief(
        name="the browser opens the exact profile already leased",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old='        return asyncio.run(_fetch(url, {**options, "user_data_dir": str(profile)}, ctx))',
        new='        return asyncio.run(_fetch(url, {**options, "user_data_dir": str(prepare_profile(headed=not options["headless"]))}, ctx))',
        test="tests/test_rungs_zendriver.py::test_browser_launch_uses_the_exact_profile_already_leased",
        why="Selecting the profile again can move the browser away from the directory protected by the lease.",
    ),
    Belief(
        name="the filter refuses a URL it cannot scope rather than crashing",
        path=LADDER / "ladder_cli/state/jars.py",
        old=(
            '    if "://" not in url:' + chr(10)
            + "        return None" + chr(10)
            + "    try:" + chr(10)
            + "        return urlparse(url).hostname" + chr(10)
            + "    except ValueError:" + chr(10)
            + "        return None"
        ),
        new='    return url.split("/")[2]',
        test="tests/test_jars.py::test_a_url_the_filter_cannot_scope_is_rejected_rather_than_crashed",
        why="A raw string split raises IndexError on a scheme-less URL and keeps :port in the scope.",
    ),
    Belief(
        name="a multi-label public suffix is not the base domain",
        path=LADDER / "ladder_cli/state/jars.py",
        old="    return extracted.top_domain_under_public_suffix",
        new='    return ".".join(host.split(".")[-2:])',
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
        name="the jar is named after the profile and says which format it holds",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    return profile_dir / f"{name}.cookies.json"',
        new='    return profile_dir / f"{name}.cookies.dat"',
        test="tests/test_jars.py::test_the_jar_path_is_named_after_the_profile_and_says_json",
        why="zendriver's .cookies.dat is a pickle; this module writes JSON under its own name.",
    ),
    # ---- the request's jars reach the browser ----
    Belief(
        name="the request's jar paths become the runner's context",
        path=LADDER / "ladder_cli/cli.py",
        old='        jar_in=Path(request.jarIn) if request.jarIn is not None else None,',
        new='        jar_in=None,',
        test="tests/test_cli.py::test_the_requests_jar_paths_reach_the_runner",
        why="The parent sent jarIn/jarOut and dispatch dropped both on the floor.",
    ),
    Belief(
        name="an isolated child is told the jars on its command line",
        path=LADDER / "ladder_cli/cli.py",
        old='        args += ["--jar-in", str(ctx.jar_in)]',
        new="        args += []",
        test="tests/test_cli.py::test_an_isolated_child_is_told_the_jars_on_its_command_line",
        why="A subprocess cannot see the parent's memory; argv is the handoff.",
    ),
    Belief(
        name="a killed browser's locks are cleared on the launch path",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="        jars.clear_locks(profile)",
        new="        pass",
        test="tests/test_rungs_zendriver.py::test_a_stale_profile_lock_is_cleared_before_the_browser_starts",
        why="clear_locks was tested on its own and called by nothing, so launches still stalled.",
    ),
    Belief(
        name="a carried jar is loaded before the page is fetched",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="            await browser.cookies.set_all([_cookie_param(cookie) for cookie in carried])",
        new="            pass",
        test="tests/test_rungs_zendriver.py::test_the_carried_jar_is_loaded_before_the_page_and_earned_cookies_saved_before_stop",
        why="A jar loaded after the page arrives replays nothing.",
    ),
    Belief(
        name="cookies earned by the fetch are saved before the browser stops",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="            jars.save(ctx.jar_out, (_jar_cookie(cookie) for cookie in earned), url)",
        new="            pass",
        test="tests/test_rungs_zendriver.py::test_the_carried_jar_is_loaded_before_the_page_and_earned_cookies_saved_before_stop",
        why="Chrome flushes cookies lazily and stop() kills it first, which is why the jar exists.",
    ),
    # ---- rung 4 gives its virtual display back ----
    Belief(
        name="a display slot whose server is dead is free again",
        path=LADDER / "ladder_cli/procfs.py",
        old="    except ProcessLookupError:\n        return Liveness.GONE\n",
        new="    except ProcessLookupError:\n        return Liveness.EXISTS\n",
        test="tests/test_rungs_headed.py::test_a_slot_is_free_once_the_server_that_locked_it_is_gone",
        why="A lock left by a killed Xvfb takes its slot for good, and 500 headed fetches later rung 4 finds no display.",
    ),
    Belief(
        name="a display lock that does not name a pid is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    except (OSError, ValueError):\n        return True\n",
        new="    except (OSError, ValueError):\n        return False\n",
        test="tests/test_rungs_headed.py::test_a_lock_that_does_not_name_a_pid_is_treated_as_held",
        why="Claiming a slot needs proof its server is dead; a lock we cannot read could be a live server mid-write.",
    ),
    Belief(
        name="a display is asked to stop before it is killed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    process.terminate()\n    try:",
        new="    process.kill()\n    try:",
        # A fake process, not the real-Xvfb test: this gate runs under a read-only
        # bwrap root where Xvfb cannot write /tmp/.X<n>-lock, so a real server
        # never comes up. The real-server version runs in the ordinary suite.
        test="tests/test_rungs_headed.py::test_the_display_is_reaped_on_success_too",
        why="Xvfb removes its own lock and socket on SIGTERM; SIGKILL leaves both behind on every fetch.",
    ),
    Belief(
        name="a display that ignores the request to stop is killed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    except subprocess.TimeoutExpired:\n        process.kill()\n        process.wait()",
        new="    except subprocess.TimeoutExpired:\n        pass",
        test="tests/test_rungs_headed.py::test_a_display_that_ignores_sigterm_is_killed_after_the_grace_period",
        why="Asking first must not leave a wedged Xvfb running, or the fetch returns with a display still held.",
    ),
    Belief(
        name="a display lock whose owner cannot be asked about is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    return procfs.probe(pid) is not procfs.Liveness.GONE\n",
        new="    return procfs.probe(pid) is procfs.Liveness.EXISTS\n",
        test="tests/test_rungs_headed.py::test_a_lock_naming_a_pid_too_large_to_probe_is_treated_as_held",
        why="Only a pid that is shown to be gone frees a slot; one that cannot be asked about (too large for a pid_t, or someone else's) is not shown to be anything.",
    ),
    Belief(
        name="a display lock longer than Xvfb writes is not read as a pid",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        text = os.read(fd, LOCK_MAX_BYTES + 1)\n",
        new="        text = os.read(fd, LOCK_MAX_BYTES)\n",
        test="tests/test_rungs_headed.py::test_a_lock_longer_than_xvfb_writes_is_treated_as_held",
        why="A read capped at the bound cannot tell a file of exactly that length from a longer one, so the number at the front of a longer file passed for a server's pid.",
    ),
    Belief(
        name="a display lock another user owns is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    if owner != os.getuid() or pid <= 0:\n        return True\n",
        new="    if pid <= 0:\n        return True\n",
        test="tests/test_rungs_headed.py::test_a_lock_we_could_not_remove_is_treated_as_held",
        why="/tmp is sticky, so a lock we do not own is one nothing of ours can clear; its slot is not ours to take.",
    ),
    Belief(
        name="a display lock that vanishes mid-check falls back to the socket",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old='    except FileNotFoundError:\n        return not Path(f"/tmp/.X11-unix/X{number}").exists()\n',
        new="    except FileNotFoundError:\n        return True\n",
        test="tests/test_rungs_headed.py::test_a_lock_that_vanishes_mid_check_falls_back_to_the_socket",
        why="A lock removed between the check and the read says nothing about a socket that is still there.",
    ),
    Belief(
        name="a display is ready only when its lock names the server we started",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        return _read_lock(lock)[1] == pid\n",
        new="        return _read_lock(lock)[1] > 0\n",
        test="tests/test_rungs_headed.py::test_readiness_waits_for_the_lock_the_new_server_wrote_not_a_stale_one",
        why="A slot reclaimed from a dead server still holds the old pid; reading that as ready starts the browser early.",
    ),
    Belief(
        name="reading a display lock never blocks on a FIFO",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW",
        new="os.O_RDONLY | os.O_NOFOLLOW",
        test="tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[fifo]",
        why="/tmp is shared; opening a FIFO for reading blocks until a writer shows up, which would hang the slot search for good.",
    ),
    Belief(
        name="a display lock that is a symlink is not followed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW",
        new="os.O_RDONLY | os.O_NONBLOCK",
        test="tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[symlink]",
        why="A link is read as whatever it points at, so a planted one could name any dead pid and free a slot that is not ours.",
    ),
    Belief(
        name="a display lock that is not a regular file is not read as a lock",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        if not stat.S_ISREG(status.st_mode):\n",
        new="        if False:\n",
        test="tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[fifo-holding-a-dead-pid]",
        why="Xvfb writes a regular file; a FIFO that happens to hold a dead pid is not evidence that a server died.",
    ),
    Belief(
        name="both stops wait for the one shared grace period",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        process.wait(timeout=STOP_GRACE_S)",
        new="        process.wait(timeout=5.0)",
        test="tests/test_rungs_headed.py::test_the_display_and_the_rung_group_are_given_one_grace_period",
        why="Two constants for one wait drift apart; the comment on rungs.STOP_GRACE_S says there is only one.",
    ),
    # ---- a rung that blows its budget is stopped, not just removed ----
    Belief(
        name="a rung's process group is asked to stop before it is killed",
        path=LADDER / "ladder_cli/cli.py",
        old="            os.killpg(group, signal.SIGTERM)\n",
        new="            os.killpg(group, signal.SIGKILL)\n",
        test="tests/test_cli.py::test_a_rung_killed_on_its_budget_has_its_group_asked_to_stop_first",
        why="Xvfb leaves its lock file behind on SIGKILL, so every rung 4 timeout burned a display slot for good.",
    ),
    Belief(
        name="the first request to stop is inside the try that holds the kill",
        path=LADDER / "ladder_cli/cli.py",
        old=(
            "    try:\n        try:\n            os.killpg(group, signal.SIGTERM)\n"
            "        except ProcessLookupError:\n            pass\n"
            "        deadline = time.monotonic() + STOP_GRACE_S\n"
        ),
        new=(
            "    try:\n        os.killpg(group, signal.SIGTERM)\n"
            "    except ProcessLookupError:\n        pass\n"
            "    try:\n        deadline = time.monotonic() + STOP_GRACE_S\n"
        ),
        test="tests/test_cli.py::test_a_sigterm_that_lands_before_the_group_was_asked_to_stop_still_kills_it",
        why="`main` turns SIGTERM into SystemExit, which can surface in the first killpg; outside the try, nothing is left to send the SIGKILL.",
    ),
    Belief(
        name="a rung is not done until everything it started has stopped",
        path=LADDER / "ladder_cli/cli.py",
        old="            if not _group_exists(group):\n                stopped = True\n                break\n",
        new="            if process.poll() is not None:\n                stopped = True\n                break\n",
        test="tests/test_cli.py::test_a_rung_is_not_done_until_what_it_started_has_finished_stopping",
        why="The rung's own process dying says nothing about a display server still removing its lock.",
    ),
    Belief(
        name="a rung group that ignores the request to stop is killed",
        path=LADDER / "ladder_cli/cli.py",
        old="        if not stopped:\n            try:\n                os.killpg(group, signal.SIGKILL)\n",
        new="        if not stopped:\n            try:\n                os.killpg(group, signal.SIGTERM)\n",
        test="tests/test_cli.py::test_a_rung_that_ignores_the_request_to_stop_is_killed_after_the_grace_period",
        why="Asking first must not let a rung that will not stop hold the budget open indefinitely.",
    ),
    Belief(
        name="a second SIGTERM during the stop still kills what ignored the first",
        path=LADDER / "ladder_cli/cli.py",
        old="    finally:\n        if not stopped:\n",
        new="    except ProcessLookupError:\n        pass\n    else:\n        if not stopped:\n",
        test="tests/test_cli.py::test_a_second_sigterm_while_the_group_is_stopping_still_kills_what_ignored_the_first",
        why="`main` turns SIGTERM into SystemExit, which can land in the wait; the kill must not depend on the wait finishing.",
    ),
    Belief(
        name="a zombie left in a stopped group is not waited on",
        path=LADDER / "ladder_cli/cli.py",
        old="    return _has_live_member(group)\n",
        new="    return True\n",
        test="tests/test_cli.py::test_a_stopped_group_whose_orphan_nobody_reaps_is_not_waited_on_for_the_whole_grace_period",
        why="Under a PID 1 that never waits, an orphaned grandchild is a zombie for good; counting it makes every stop spend the whole grace period.",
    ),
    Belief(
        name="a zombie in the group does not count as running",
        path=LADDER / "ladder_cli/cli.py",
        old='        if stat.pgrp == group and stat.state != "Z":\n',
        new="        if stat.pgrp == group:\n",
        test="tests/test_cli.py::test_a_stopped_group_whose_orphan_nobody_reaps_is_not_waited_on_for_the_whole_grace_period",
        why="Same cost as the belief above, reached through the scan itself: a zombie is the stop's answer, not a reason to wait.",
    ),
    Belief(
        name="a group is not called stopped on one empty scan",
        path=LADDER / "ladder_cli/cli.py",
        old="    return _scan_for_live_member(group) or _scan_for_live_member(group)\n",
        new="    return _scan_for_live_member(group)\n",
        test="tests/test_cli.py::test_a_group_is_not_called_stopped_on_one_empty_scan_alone",
        why="A scan of /proc is not atomic: a child forked after the listing is missed, and calling the group stopped then skips the SIGKILL.",
    ),
    Belief(
        name="a group member whose state cannot be read is asked about its group directly",
        path=LADDER / "ladder_cli/cli.py",
        old="                if os.getpgid(pid) == group:\n                    return True\n",
        new="                pass\n",
        test="tests/test_cli.py::test_a_group_member_whose_state_cannot_be_read_is_not_taken_for_gone",
        why="An unreadable stat is not an exit; counting it as gone lets a hidepid mount or a malformed line skip the SIGKILL.",
    ),
    Belief(
        name="a /proc that cannot be listed leaves the group counted as running",
        path=LADDER / "ladder_cli/cli.py",
        old="    except OSError:\n        return True\n    classified = False\n",
        new="    except ValueError:\n        return True\n    classified = False\n",
        test="tests/test_cli.py::test_a_group_is_taken_to_be_running_when_proc_cannot_be_listed",
        why="`iterdir` raising turned a stop on a host without /proc into a crash with the rung still running.",
    ),
    Belief(
        name="a /proc with nothing classifiable leaves the group counted as running",
        path=LADDER / "ladder_cli/cli.py",
        old="    return not classified\n",
        new="    return False\n",
        test="tests/test_cli.py::test_a_group_is_taken_to_be_running_when_nothing_in_proc_could_be_classified",
        why="`killpg` already said something is in the group; a scan that read nothing has not shown it gone.",
    ),
    # ---- what the kernel says about a process, asked in one place ----
    Belief(
        name="the stat line is read after the last parenthesis",
        path=LADDER / "ladder_cli/procfs.py",
        old='text.rsplit(")", 1)[1]',
        new='text.split(")", 1)[1]',
        test="tests/test_procfs.py::test_read_stat_takes_the_state_and_group_after_the_last_parenthesis",
        why="The comm field is a process name and can hold a `)`; splitting at the first one reads the wrong fields.",
    ),
    Belief(
        name="a pid too large to probe is unknown, not a crash",
        path=LADDER / "ladder_cli/procfs.py",
        old="    except (PermissionError, OverflowError):\n        return Liveness.UNKNOWN\n",
        new="    except PermissionError:\n        return Liveness.UNKNOWN\n",
        test="tests/test_procfs.py::test_probe_a_pid_too_large_to_ask_about_is_unknown[2147483648]",
        why="os.kill raises OverflowError past a pid_t; one planted lock would crash every caller that asks.",
    ),
    # ---- a profile lock whose owner cannot be probed is refused, not a crash ----
    Belief(
        name="a profile lock whose owner cannot be asked about is refused with a reason",
        path=LADDER / "ladder_cli/state/jars.py",
        old="    if liveness is procfs.Liveness.UNKNOWN:\n",
        new="    if False:\n",
        test="tests/test_jars.py::test_cleanup_reports_an_owner_pid_too_large_to_probe_and_keeps_the_lock",
        why="Without the refusal an owner that cannot be checked falls through and its lock is cleared.",
    ),
    Belief(
        name="a profile lock whose owner has exited but is not reaped is cleared",
        path=LADDER / "ladder_cli/state/jars.py",
        old='        if state != "Z":\n',
        new="        if True:\n",
        test="tests/test_jars.py::test_cleanup_distinguishes_a_zombie_owner_from_a_running_owner",
        why="A zombie exists to signal 0 but is gone; refusing its lock strands the profile until something reaps it.",
    ),
]


def _forget_imports(project: Path) -> None:
    """Drop project source and test bytecode before a run.

    Python invalidates bytecode by source mtime AND size. A mutant that preserves
    byte length (base.en to tiny.en) written inside the same timestamp tick leaves
    the stale .pyc valid, so pytest imports the OLD module and the belief reports
    SURVIVED even though its test would have caught it. That false confidence is
    worse than no gate at all, so caches are cleared every run and bytecode is
    never written back.
    """
    for root in (project / "ladder_cli", project / "tests"):
        for cache in root.rglob("__pycache__"):
            shutil.rmtree(cache)


@contextmanager
def _scratch_project():
    with tempfile.TemporaryDirectory(prefix="serp-axi-mutation-") as temporary:
        project = Path(temporary) / "ladder-cli"
        shutil.copytree(
            LADDER, project,
            ignore=shutil.ignore_patterns(".venv", "profiles", "__pycache__", ".pytest_cache"),
        )
        yield project


def run_tests(selector: str, project: Path | None = None) -> tuple[str, str]:
    """Return (outcome, last_line) where outcome is pass, fail, or error.

    The verdict comes from pytest's exit code, not the last output line. A
    changed summary format or a traceback tail can omit the word "failed" and
    turn a real kill into a false SURVIVED, which is the safe-direction lie this
    gate exists to prevent. Exit 5 means no tests were collected, so the selector
    matches nothing; that is an invalid entry and never a kill.
    """
    if project is None:
        with _scratch_project() as scratch:
            return run_tests(selector, scratch)
    _forget_imports(project)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(project)
    environment = Path(env.get("UV_PROJECT_ENVIRONMENT", str(LADDER / ".venv")))
    env["UV_PROJECT_ENVIRONMENT"] = str((LADDER / environment).resolve())
    env["UV_NO_SYNC"] = "1"
    env["UV_OFFLINE"] = "1"
    for name, directory in {
        "HOME": "home", "TMPDIR": "tmp", "XDG_CACHE_HOME": "cache",
        "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state",
        "UV_CACHE_DIR": "cache/uv",
    }.items():
        location = project.parent / directory
        location.mkdir(parents=True, exist_ok=True)
        env[name] = str(location)
    sandbox = [
        "bwrap", "--ro-bind", "/", "/", "--bind", str(project.parent), str(project.parent),
        "--dev", "/dev", "--proc", "/proc", "--unshare-all", "--die-with-parent",
        "--new-session", "--cap-drop", "ALL", "--",
    ]
    status = project.parent / "pytest-status"
    status.unlink(missing_ok=True)
    wrapper = [
        sys.executable, "-c",
        "import subprocess, sys; from pathlib import Path; "
        "code = subprocess.run(sys.argv[2:]).returncode; "
        "Path(sys.argv[1]).write_text(str(code))",
        str(status),
    ]
    try:
        proc = subprocess.run(
            sandbox + wrapper + PYTEST + [selector], cwd=project,
            capture_output=True, text=True, timeout=600, env=env
        )
    except FileNotFoundError:
        return "error", "bwrap is unavailable; install Bubblewrap and enable unprivileged user namespaces"
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    last = tail[-1] if tail else "(no output)"
    if proc.returncode != 0 or not status.exists():
        return "error", f"sandbox/pytest startup failed; check Bubblewrap, user namespaces and the synced test extra: {last}"
    code = int(status.read_text())
    if code == 0:
        return "pass", last
    if code == 1:
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

        with _scratch_project() as project:
            target = project / belief.path.relative_to(LADDER)
            target.write_text(original.replace(belief.old, belief.new, 1))
            outcome, last = run_tests(belief.test, project)

        if outcome == "fail":
            killed += 1
            print(f"killed    [{belief.name}]")
        elif outcome == "error":
            invalid.append(belief)
            print(f"INVALID   [{belief.name}]: mutant test could not run ({last})")
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
