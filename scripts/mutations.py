#!/usr/bin/env python3
"""A named mutation gate: what the suite believes, and how each belief could fail.

A green suite only says the tests that exist still pass. It says nothing about
whether those tests would notice the thing they are supposed to notice. This
script is the mechanical answer to that gap, and it is deliberately not a
generic mutation tool.

A generic sweep reports surviving MUTANTS. This reports surviving BELIEFS. Every
entry below is one sentence this codebase holds to be true, paired with the
smallest edit that makes it false and the tests that must go red when it is.
A belief held from more than one side lists every one of them, and each is run
alone against the mutant: the belief is killed only if all of them go red. If a
belief survives, at least one listed test is hollow: it agrees with the code
rather than with the claim, and the report names which.

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
    """One sentence the suite claims to hold, plus the edit that falsifies it.

    `tests` is every test that claims to notice this edit, and each one is run on
    its own against the mutant: the belief is killed only if all of them go red.
    One edit is sometimes guarded from more than one side (the wait, the kill,
    the order), and a belief that stopped at the first red test would let the
    others rot into agreeing with the code. Two beliefs with the same edit are a
    mistake for the same reason, so `main` refuses the pair and the second test
    is listed here instead.
    """

    name: str
    path: Path
    old: str
    new: str
    tests: tuple[str, ...]
    why: str


BELIEFS: list[Belief] = [
    # ---- the climb is one ordered ladder under one budget ----
    Belief(
        name="every rung in the climb is reachable",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='    "zendriver_headed_cf": headed,',
        new='',
        tests=("tests/test_escalation.py::test_every_rung_in_the_climb_is_reachable",),
        why="A rung in RUNGS with no module is a dead step: the climb reaches for nothing.",
    ),
    Belief(
        name="the climb starts cheap and only reaches for a browser when it must",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='RUNGS: tuple[str, ...] = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")',
        new='RUNGS: tuple[str, ...] = ("camoufox", "http", "zendriver_cf", "zendriver_headed_cf")',
        tests=("tests/test_escalation.py::test_the_climb_starts_cheap_and_only_reaches_for_a_browser_when_it_must",),
        why="The 80-in-100 case pays rung 1's cost alone, so a browser first is the wrong order.",
    ),
    Belief(
        name="every rung is killed by the same measured budget",
        path=LADDER / "ladder_cli/cli.py",
        old="DEFAULT_RUNG_TIMEOUT_S = 90.0",
        new="DEFAULT_RUNG_TIMEOUT_S = 1.0",
        tests=("tests/test_escalation.py::test_every_rung_is_killed_by_the_same_measured_budget",),
        why="90s is the measured budget. A different number is a claim with no measurement behind it.",
    ),
    Belief(
        name="no rung carries its own budget",
        path=LADDER / "ladder_cli/cli.py",
        old="    budget = DEFAULT_RUNG_TIMEOUT_S if timeout_s is None else timeout_s",
        new='    budget = 5.0 if rung == "http" else (DEFAULT_RUNG_TIMEOUT_S if timeout_s is None else timeout_s)',
        tests=("tests/test_escalation.py::test_no_rung_carries_its_own_budget",),
        why="One deadline, one owner. A per-rung budget gives one deadline two owners.",
    ),
    # ---- unwired audio helpers cache only within their own process ----
    Belief(
        name="audio helper imports do not construct a model",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="_model: Any | None = None",
        new="_model: Any | None = object()",
        tests=("tests/test_rungs_whisper.py::test_importing_the_module_loads_nothing",),
        why="Importing optional audio helpers must leave the model unloaded.",
    ),
    Belief(
        name="the audio helper reuses its model within one process",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="    if _model is None:",
        new="    if True:",
        tests=("tests/test_rungs_whisper.py::test_the_helper_reuses_one_model_within_its_process",),
        why="Repeated helper calls should not reconstruct their model.",
    ),
    Belief(
        name="the model cache holds the model it built",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="        _model = _build(device=DEVICE, compute_type=COMPUTE_TYPE)",
        new="        _build(device=DEVICE, compute_type=COMPUTE_TYPE)",
        tests=("tests/test_rungs_whisper.py::test_the_helper_reuses_one_model_within_its_process",),
        why="Discarding the constructed model makes the next helper call rebuild it.",
    ),
    Belief(
        name="ceiling five stops at the last implemented rung",
        path=LADDER / "ladder_cli/rungs/__init__.py",
        old='"zendriver_headed_cf")',
        new='"zendriver_headed_cf", "whisper")',
        tests=("tests/test_escalation.py::test_ceiling_five_stops_at_the_last_implemented_rung",),
        why="An unwired audio helper must not become a duplicate browser attempt.",
    ),
    Belief(
        name="the model is the measured base.en",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old='MODEL_NAME = "base.en"',
        new='MODEL_NAME = "tiny.en"',
        tests=("tests/test_rungs_whisper.py::test_the_construction_carries_the_measured_arguments",),
        why="A constant ported from a measured run is a claim about that run.",
    ),
    Belief(
        name="transcription uses the measured beam size",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="load().transcribe(path, language=LANGUAGE, beam_size=BEAM_SIZE)",
        new="load().transcribe(path, language=LANGUAGE)",
        tests=("tests/test_rungs_whisper.py::test_transcription_carries_the_measured_arguments",),
        why="q5_audio.py:47 pinned beam_size=5; dropping it is a silent decode change.",
    ),
    Belief(
        name="an answer is sanitised to words and digits",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old='    return re.sub(r"[^a-z0-9 ]", "", transcript.lower()).strip()',
        new="    return transcript.lower().strip()",
        tests=("tests/test_rungs_whisper.py::test_the_answer_is_the_measured_sanitised_form_of_the_transcript",),
        why="The challenge field wants only the words and digits it asked for.",
    ),
    Belief(
        name="the three-round budget is a ceiling",
        path=LADDER / "ladder_cli/rungs/whisper.py",
        old="islice(clips, MAX_ROUNDS)",
        new="list(clips)",
        tests=("tests/test_rungs_whisper.py::test_the_measured_loop_stops_at_three_clips_no_matter_how_many_are_offered",),
        why="q5_audio.py:42 stopped at three; answering a fourth is a different run.",
    ),
    # ---- the cookie jar is filtered, on both sides ----
    Belief(
        name="only the four defence cookies travel",
        path=LADDER / "ladder_cli/state/jars.py",
        old='KEEP: tuple[str, ...] = ("cf_clearance", "_px3", "_pxhd", "datadome")',
        new='KEEP: tuple[str, ...] = ("cf_clearance", "_px3", "_pxhd")',
        tests=("tests/test_jars.py::test_only_the_defence_cookies_the_spike_kept_are_kept",),
        why="solver_probe.py:27 named four; a browsing cookie has no business here.",
    ),
    Belief(
        name="a cookie's scope stops at a label boundary",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    return scope == base or scope.endswith("." + base)',
        new="    return scope.endswith(base)",
        tests=("tests/test_jars.py::test_the_domain_match_stops_at_a_label_boundary",),
        why='"evil-example.com".endswith("example.com") is true: lookalikes get in.',
    ),
    Belief(
        name="the browser rungs agree on a verdict",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="judge = zendriver.judge",
        new='judge = lambda page: zendriver.judge({"title": "", "text": "", "status": 404})',
        tests=("tests/test_fixture_replay.py::test_the_browser_rungs_apply_one_set_of_rules",),
        why="A page judged twice must not read differently because it climbed twice.",
    ),
    Belief(
        name="the browser opens the exact profile already leased",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old='        return asyncio.run(_fetch(url, {**options, "user_data_dir": str(profile)}, ctx))',
        new='        return asyncio.run(_fetch(url, {**options, "user_data_dir": str(prepare_profile(headed=not options["headless"]))}, ctx))',
        tests=("tests/test_rungs_zendriver.py::test_browser_launch_uses_the_exact_profile_already_leased",),
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
        tests=("tests/test_jars.py::test_a_url_the_filter_cannot_scope_is_rejected_rather_than_crashed",),
        why="A raw string split raises IndexError on a scheme-less URL and keeps :port in the scope.",
    ),
    Belief(
        name="a multi-label public suffix is not the base domain",
        path=LADDER / "ladder_cli/state/jars.py",
        old="    return extracted.top_domain_under_public_suffix",
        new='    return ".".join(host.split(".")[-2:])',
        tests=("tests/test_jars.py::test_a_multi_label_public_suffix_is_not_treated_as_the_base_domain",),
        why="Two labels turns www.bbc.co.uk into co.uk and lets every .co.uk sibling through.",
    ),
    Belief(
        name="loading a jar re-applies the filter rather than trusting the file",
        path=LADDER / "ladder_cli/state/jars.py",
        old="    return filter_cookies(cookies, url)",
        new="    return cookies",
        tests=("tests/test_jars.py::test_loading_a_jar_re_applies_the_filter_rather_than_trusting_the_file",),
        why="A jar is data on disk and anything can widen one by hand.",
    ),
    Belief(
        name="a killed browser's profile locks are all cleared",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    "SingletonSocket",' + chr(10) + ")",
        new='    "SingletonSocket",' + chr(10) + '    "never-existed",' + chr(10) + ")",
        tests=("tests/test_jars.py::test_a_killed_browser_leaves_no_lock_behind_for_the_next_launch",),
        why="The test pins the measured five names; a sixth must not pass as five.",
    ),
    Belief(
        name="the jar is named after the profile and says which format it holds",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    return profile_dir / f"{name}.cookies.json"',
        new='    return profile_dir / f"{name}.cookies.dat"',
        tests=("tests/test_jars.py::test_the_jar_path_is_named_after_the_profile_and_says_json",),
        why="zendriver's .cookies.dat is a pickle; this module writes JSON under its own name.",
    ),
    # ---- the request's jars reach the browser ----
    Belief(
        name="the request's jar paths become the runner's context",
        path=LADDER / "ladder_cli/cli.py",
        old='        jar_in=Path(request.jarIn) if request.jarIn is not None else None,',
        new='        jar_in=None,',
        tests=("tests/test_cli.py::test_the_requests_jar_paths_reach_the_runner",),
        why="The parent sent jarIn/jarOut and dispatch dropped both on the floor.",
    ),
    Belief(
        name="an isolated child is told the jars on its command line",
        path=LADDER / "ladder_cli/cli.py",
        old='        args += ["--jar-in", str(ctx.jar_in)]',
        new="        args += []",
        tests=("tests/test_cli.py::test_an_isolated_child_is_told_the_jars_on_its_command_line",),
        why="A subprocess cannot see the parent's memory; argv is the handoff.",
    ),
    Belief(
        name="a killed browser's locks are cleared on the launch path",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="        jars.clear_locks(profile)",
        new="        pass",
        tests=("tests/test_rungs_zendriver.py::test_a_stale_profile_lock_is_cleared_before_the_browser_starts",),
        why="clear_locks was tested on its own and called by nothing, so launches still stalled.",
    ),
    Belief(
        name="a carried jar is loaded before the page is fetched",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="            await browser.cookies.set_all([_cookie_param(cookie) for cookie in carried])",
        new="            pass",
        tests=("tests/test_rungs_zendriver.py::test_the_carried_jar_is_loaded_before_the_page_and_earned_cookies_saved_before_stop",),
        why="A jar loaded after the page arrives replays nothing.",
    ),
    Belief(
        name="cookies earned by the fetch are saved before the browser stops",
        path=LADDER / "ladder_cli/rungs/zendriver.py",
        old="            jars.save(ctx.jar_out, (_jar_cookie(cookie) for cookie in earned), url)",
        new="            pass",
        tests=("tests/test_rungs_zendriver.py::test_the_carried_jar_is_loaded_before_the_page_and_earned_cookies_saved_before_stop",),
        why="Chrome flushes cookies lazily and stop() kills it first, which is why the jar exists.",
    ),
    # ---- rung 4 gives its virtual display back ----
    Belief(
        name="a display slot whose server is dead is free again",
        path=LADDER / "ladder_cli/procfs.py",
        old="    except ProcessLookupError:\n        return Liveness.GONE\n",
        new="    except ProcessLookupError:\n        return Liveness.EXISTS\n",
        tests=("tests/test_rungs_headed.py::test_a_slot_is_free_once_the_server_that_locked_it_is_gone",),
        why="A lock left by a killed Xvfb takes its slot for good, and 500 headed fetches later rung 4 finds no display.",
    ),
    Belief(
        name="a display lock that does not name a pid is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old=(
            "    try:\n"
            "        owner, pid = _read_lock(lock)\n"
            "    except FileNotFoundError:\n"
            "        return _LockState.FREE\n"
            "    except (OSError, ValueError):\n"
            "        return _LockState.HELD\n"
        ),
        new=(
            "    try:\n"
            "        owner, pid = _read_lock(lock)\n"
            "    except FileNotFoundError:\n"
            "        return _LockState.FREE\n"
            "    except (OSError, ValueError):\n"
            "        return _LockState.FREE\n"
        ),
        tests=("tests/test_rungs_headed.py::test_a_lock_that_does_not_name_a_pid_is_treated_as_held",),
        why="Claiming a slot needs proof its server is dead; a lock we cannot read could be a live server mid-write.",
    ),
    Belief(
        name="a display is asked to stop before it is killed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    stopping.stop_with_grace(term=process.terminate, wait_gone=wait_gone, kill=kill)\n",
        new="    stopping.stop_with_grace(term=process.kill, wait_gone=wait_gone, kill=kill)\n",
        # A fake process, not the real-Xvfb test: this gate runs under a read-only
        # bwrap root where Xvfb cannot write /tmp/.X<n>-lock, so a real server
        # never comes up. The real-server version runs in the ordinary suite.
        tests=(
            "tests/test_rungs_headed.py::test_the_display_is_reaped_on_success_too",
            "tests/test_rungs_headed.py::test_a_server_that_exits_on_sigterm_is_not_killed",
        ),
        why="Xvfb removes its own lock and socket on SIGTERM; SIGKILL leaves both behind on every fetch.",
    ),
    Belief(
        name="a display that ignores the request to stop is killed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        process.kill()\n        try:\n            process.wait(timeout=stopping.KILL_WAIT_S)\n",
        new="        try:\n            process.wait(timeout=stopping.KILL_WAIT_S)\n",
        tests=("tests/test_rungs_headed.py::test_a_display_that_ignores_sigterm_is_killed_after_the_grace_period",),
        why="Asking first must not leave a wedged Xvfb running, or the fetch returns with a display still held.",
    ),
    Belief(
        name="the display's stderr pipe is closed even when the stop raises",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="                if process.stderr is not None:\n                    process.stderr.close()\n",
        new="                if False:\n                    process.stderr.close()\n",
        tests=("tests/test_rungs_headed.py::test_the_stderr_pipe_is_closed_even_when_the_display_could_not_be_reaped",),
        why="`_stop_display` raises for a server that survives SIGKILL, and a close that comes after it leaks the pipe once per unkillable server in a resident CLI.",
    ),
    Belief(
        name="a reclaim that puts a lock back does not replace one written since",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    except FileExistsError:\n        # Another server wrote its own lock while this one was moved.",
        new="    except FileNotFoundError:\n        # Another server wrote its own lock while this one was moved.",
        tests=("tests/test_rungs_headed.py::test_a_lock_written_while_the_reclaim_holds_the_old_one_aside_is_not_replaced",),
        why="Review finding F02: the lock written since is the live server's, and a put-back by rename would delete it.",
    ),
    Belief(
        name="a display stop that fails is a note on the page's error, not its replacement",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old=(
            "                    if in_flight is None:\n"
            "                        raise\n"
            '                    in_flight.add_note(f"the display stop also failed: {stop_failure}")\n'
        ),
        new="                    raise\n",
        tests=("tests/test_rungs_headed.py::test_a_failing_display_stop_does_not_replace_the_pages_error",),
        why="Review finding F05: the page's failure explains the rung; a stop that also failed is context on it.",
    ),
    Belief(
        name="a display stop that fails with no page error is the error",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="                    if in_flight is None:\n                        raise\n",
        new="                    if False:\n                        raise\n",
        tests=("tests/test_rungs_headed.py::test_a_failing_display_stop_is_the_error_when_the_page_succeeded",),
        why="Review finding F05: with no page failure there is nothing to attach a note to, and the unkillable server has to be reported.",
    ),
    Belief(
        name="an interrupt during the display stop is not folded into the page's error",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="                except Exception as stop_failure:\n",
        new="                except BaseException as stop_failure:\n",
        tests=("tests/test_rungs_headed.py::test_an_interrupt_during_the_display_stop_is_not_swallowed",),
        why="A KeyboardInterrupt or SystemExit during the stop is the operator's; folding it into a note would hand back the page error and swallow the interrupt.",
    ),
    Belief(
        name="the wait after SIGKILL is bounded, and reads its own named bound",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            process.wait(timeout=stopping.KILL_WAIT_S)\n        except subprocess.TimeoutExpired:\n            raise RuntimeError(",
        new="            process.wait(timeout=5.0)\n        except subprocess.TimeoutExpired:\n            raise RuntimeError(",
        tests=("tests/test_rungs_headed.py::test_the_kill_is_followed_by_a_bounded_wait_that_names_the_server_it_could_not_reap",),
        why="Review findings F13 and F25: a server in uninterruptible sleep ignores SIGKILL, and the wait after it is a different question from the SIGTERM grace, so it has its own bound.",
    ),
    Belief(
        name="a server that will not die after SIGKILL is raised, not swallowed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        except subprocess.TimeoutExpired:\n            raise RuntimeError(\n",
        new="        except subprocess.TimeoutExpired:\n            return\n            raise RuntimeError(\n",
        tests=("tests/test_rungs_headed.py::test_the_kill_is_followed_by_a_bounded_wait_that_names_the_server_it_could_not_reap",),
        why="Review finding F13: the bounded wait is only better than the unbounded one if its failure is reported.",
    ),
    Belief(
        name="a display lock whose owner cannot be asked about is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old=(
            "    try:\n"
            "        state = procfs.read_stat(pid).state\n"
            "    except (OSError, ValueError):\n"
            "        return _LockState.HELD  # it exited mid-read, or /proc cannot say: not proof either way\n"
        ),
        new=(
            "    try:\n"
            "        state = procfs.read_stat(pid).state\n"
            "    except (OSError, ValueError):\n"
            "        return _LockState.FREE\n"
        ),
        tests=("tests/test_rungs_headed.py::test_a_lock_naming_a_pid_too_large_to_probe_is_treated_as_held",),
        why="Only a pid that is shown to be gone frees a slot; one whose stat cannot be read (too large for a pid_t, or a /proc that does not cover it) is not shown to be anything.",
    ),
    Belief(
        name="a display lock longer than Xvfb writes is not read as a pid",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        text = os.read(fd, LOCK_MAX_BYTES + 1)\n",
        new="        text = os.read(fd, LOCK_MAX_BYTES)\n",
        tests=("tests/test_rungs_headed.py::test_a_lock_longer_than_xvfb_writes_is_treated_as_held",),
        why="A read capped at the bound cannot tell a file of exactly that length from a longer one, so the number at the front of a longer file passed for a server's pid.",
    ),
    Belief(
        name="a display lock another user owns is treated as held",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    if owner != os.getuid():\n        return _LockState.HELD\n",
        new="    if False:\n        return _LockState.HELD\n",
        tests=(
            "tests/test_rungs_headed.py::test_a_lock_we_could_not_remove_is_treated_as_held",
            "tests/test_rungs_headed.py::test_only_a_zombies_lock_is_reclaimed",
        ),
        why="/tmp is sticky, so a lock we do not own is one nothing of ours can clear; its slot is not ours to take, and it is never reclaimed.",
    ),
    Belief(
        name="an absent display lock is not a held one",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    except FileNotFoundError:\n        return _LockState.FREE\n",
        new="    except FileNotFoundError:\n        return _LockState.HELD\n",
        tests=(
            "tests/test_rungs_headed.py::test_a_socket_file_with_no_lock_holds_its_slot_only_while_something_listens_on_it",
            "tests/test_rungs_headed.py::test_a_lock_that_vanishes_mid_check_falls_back_to_the_socket",
        ),
        why="An absent lock says nothing about the socket; folding it into 'unreadable' would read every slot without a lock as taken.",
    ),
    Belief(
        name="a display is ready only when its lock names the server we started",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        return _read_lock(lock)[1] == pid\n",
        new="        return _read_lock(lock)[1] > 0\n",
        tests=("tests/test_rungs_headed.py::test_readiness_waits_for_the_lock_the_new_server_wrote_not_a_stale_one",),
        why="A slot reclaimed from a dead server still holds the old pid; reading that as ready starts the browser early.",
    ),
    Belief(
        name="reading a display lock never blocks on a FIFO",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW",
        new="os.O_RDONLY | os.O_NOFOLLOW",
        tests=("tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[fifo]",),
        why="/tmp is shared; opening a FIFO for reading blocks until a writer shows up, which would hang the slot search for good.",
    ),
    Belief(
        name="a display lock that is a symlink is not followed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW",
        new="os.O_RDONLY | os.O_NONBLOCK",
        tests=("tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[symlink]",),
        why="A link is read as whatever it points at, so a planted one could name any dead pid and free a slot that is not ours.",
    ),
    Belief(
        name="a display lock that is not a regular file is not read as a lock",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="        if not stat.S_ISREG(status.st_mode):\n",
        new="        if False:\n",
        tests=("tests/test_rungs_headed.py::test_a_lock_that_is_not_a_plain_file_is_held_and_never_waited_on[fifo-holding-a-dead-pid]",),
        why="Xvfb writes a regular file; a FIFO that happens to hold a dead pid is not evidence that a server died.",
    ),
    Belief(
        name="both stops wait for the one grace period, read when the stop runs",
        path=LADDER / "ladder_cli/stopping.py",
        old="        gone = wait_gone(STOP_GRACE_S)\n",
        new="        gone = wait_gone(5.0)\n",
        tests=(
            "tests/test_stopping.py::test_the_grace_period_is_read_when_the_stop_runs_and_is_not_a_parameter",
            "tests/test_rungs_headed.py::test_the_display_waits_for_the_one_grace_period_the_group_stop_uses",
        ),
        why="Two constants for one wait drift apart (review findings F09 and F10); `stopping.STOP_GRACE_S` is the one home and a copy of its value cannot follow a change to it.",
    ),
    Belief(
        name="the display stop goes through the shared stop routine",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    stopping.stop_with_grace(term=process.terminate, wait_gone=wait_gone, kill=kill)\n",
        new="    process.terminate()\n    if not wait_gone(stopping.STOP_GRACE_S):\n        kill()\n",
        tests=("tests/test_rungs_headed.py::test_the_display_and_the_rung_group_are_stopped_by_the_one_routine",),
        why="Review findings G8 and H9: a second copy of the TERM-then-KILL loop is how the display lost the group's kill-in-a-finally.",
    ),
    Belief(
        name="the rung group stop goes through the shared stop routine",
        path=LADDER / "ladder_cli/cli.py",
        old=(
            "        stopping.stop_with_grace(\n"
            "            term=lambda: _signal_group(group, signal.SIGTERM),\n"
            "            wait_gone=wait_gone,\n"
            "            kill=kill,\n"
            "            always_kill=not leader_reaped,\n"
            "        )\n"
        ),
        new=(
            "        _signal_group(group, signal.SIGTERM)\n"
            "        if not wait_gone(stopping.STOP_GRACE_S):\n"
            "            kill()\n"
        ),
        tests=("tests/test_rungs_headed.py::test_the_display_and_the_rung_group_are_stopped_by_the_one_routine",),
        why="Review findings G8 and H9, from the group's side.",
    ),
    Belief(
        name="a SIGTERM landing while something is stopping still kills it",
        path=LADDER / "ladder_cli/stopping.py",
        old="    finally:\n        if not gone or always_kill:\n            kill()\n",
        new="    except ProcessLookupError:\n        pass\n    else:\n        if not gone or always_kill:\n            kill()\n",
        # One edit, three sides: the routine on its own, the display through it, and
        # a real rung group through it. Two beliefs with the same edit would be
        # reported as one, so the other tests are listed here and each must go red.
        tests=(
            "tests/test_stopping.py::test_a_sigterm_that_lands_in_the_wait_still_kills_and_still_surfaces",
            "tests/test_rungs_headed.py::test_a_sigterm_that_lands_while_the_display_is_stopping_still_kills_it",
            "tests/test_cli.py::test_a_second_sigterm_while_the_group_is_stopping_still_kills_what_ignored_the_first",
        ),
        why="`main` turns SIGTERM into SystemExit, which can land in the wait; the kill must not depend on the wait finishing (review finding H9).",
    ),
    Belief(
        name="the request to stop is inside the try that holds the kill",
        path=LADDER / "ladder_cli/stopping.py",
        old="    try:\n        term()\n        gone = wait_gone(STOP_GRACE_S)\n",
        new="    term()\n    try:\n        gone = wait_gone(STOP_GRACE_S)\n",
        tests=(
            "tests/test_stopping.py::test_a_sigterm_that_lands_in_the_request_to_stop_still_kills_and_still_surfaces",
            "tests/test_cli.py::test_a_sigterm_that_lands_before_the_group_was_asked_to_stop_still_kills_it",
        ),
        why="`main` turns SIGTERM into SystemExit, which can surface in the first request; outside the try, nothing is left to send the SIGKILL.",
    ),
    Belief(
        name="the shared stop asks before it waits",
        path=LADDER / "ladder_cli/stopping.py",
        old="        term()\n        gone = wait_gone(STOP_GRACE_S)\n",
        new="        gone = wait_gone(STOP_GRACE_S)\n        term()\n",
        tests=("tests/test_stopping.py::test_a_target_that_stops_when_asked_is_never_killed",),
        why="Waiting out the grace period before asking stops nothing and kills everything that would have stopped on request.",
    ),
    # ---- a slot is free when nothing answers on it, whatever its lock says ----
    Belief(
        name="a dead lock beside a live listener does not free the slot",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="    return not _accepts_connections(number)\n",
        new="    return True\n",
        tests=("tests/test_rungs_headed.py::test_a_dead_lock_beside_a_live_listener_does_not_free_the_slot",),
        why="A stale lock says its own server is gone, not that nobody else is listening; a real Xvfb on such a slot exits 'server already running' (review finding G6).",
    ),
    Belief(
        name="an early exit on a slot that is taken is a collision whatever Xvfb said",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            if not display_is_free(number):\n                raise _DisplayCollision(",
        new="            if False:\n                raise _DisplayCollision(",
        tests=("tests/test_rungs_headed.py::test_an_early_exit_is_a_collision_when_the_slot_is_taken_and_a_failure_when_it_is_not",),
        why="Review finding F29: the slot is asked, not Xvfb's words; a lost race for one slot must try the next, not fail the rung with 499 free.",
    ),
    Belief(
        name="an early exit on a slot that is free is a failure whatever Xvfb said",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            if not display_is_free(number):\n                raise _DisplayCollision(",
        new="            if True:\n                raise _DisplayCollision(",
        tests=("tests/test_rungs_headed.py::test_an_early_exit_is_a_collision_when_the_slot_is_taken_and_a_failure_when_it_is_not",),
        why="The other half of the pair: an Xvfb that cannot start on an empty slot is broken, and retrying another slot would loop over a fault that is not the slot's.",
    ),
    # ---- a display is ready when it answers, not when its lock appears ----
    Belief(
        name="a display is not ready until a connect to its socket succeeds",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            if _accepts_connections(number, timeout_s=max(0.0, min(1.0, deadline - time.monotonic()))):\n                return\n",
        new="            if True:\n                return\n",
        tests=("tests/test_rungs_headed.py::test_readiness_waits_for_a_socket_that_answers_not_just_the_lock",),
        why="Xvfb writes its lock before it binds its socket (39 of 200 real starts); a browser pointed at it in that gap cannot connect (review finding G4).",
    ),
    Belief(
        name="a display that only listens on the abstract socket is ready",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old='    for address in (path, "\\0" + path):\n',
        new="    for address in (path,):\n",
        tests=("tests/test_rungs_headed.py::test_readiness_accepts_a_display_that_only_listens_on_the_abstract_socket",),
        why="Xvfb tolerates a /tmp/.X11-unix it cannot write and serves on the abstract socket alone; requiring the file would break that working setup.",
    ),
    # ---- a display slot held by a zombie is reclaimed, and only a zombie's ----
    Belief(
        name="only a zombie's display lock is reclaimed",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old=(
            "    if _lock_state(aside) is _LockState.ZOMBIE:\n"
            "        aside.unlink(missing_ok=True)\n"
            "        return\n"
        ),
        new="    aside.unlink(missing_ok=True)\n    return\n",
        tests=("tests/test_rungs_headed.py::test_a_lock_that_is_replaced_while_it_is_being_reclaimed_is_put_back",),
        why="Review finding F02: a running server's lock is a live server and another user's is not ours; the re-check after the move is what decides, so deleting anything moved takes a slot out from under a working Xvfb.",
    ),
    Belief(
        name="the slot search reclaims a zombie's lock before it asks if the slot is free",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            _reclaim_zombie_lock(candidate, state)\n",
        new="            pass\n",
        tests=("tests/test_rungs_headed.py::test_the_slot_search_reclaims_a_zombies_lock_and_offers_the_slot",),
        why="Real Xvfb refuses a lock that names a zombie (rc 1, measured 2026-11-03), so without the call every such slot is lost for as long as the zombie is.",
    ),
    Belief(
        name="Xvfb stays in the rung's process group",
        path=LADDER / "ladder_cli/rungs/headed.py",
        old="            xvfb_command(number),\n            stdout=subprocess.DEVNULL,\n            stderr=subprocess.PIPE,\n",
        new="            xvfb_command(number),\n            stdout=subprocess.DEVNULL,\n            stderr=subprocess.PIPE,\n            start_new_session=True,\n",
        tests=("tests/test_rungs_headed.py::test_xvfb_is_started_in_the_rungs_own_process_group",),
        why="Review finding F36: the group's SIGTERM and SIGKILL are what reach an Xvfb the display's own stop never got to; a session of its own puts it out of their reach.",
    ),
    # ---- a rung that blows its budget is stopped, not just removed ----
    Belief(
        name="a rung's process group is asked to stop before it is killed",
        path=LADDER / "ladder_cli/cli.py",
        old="            term=lambda: _signal_group(group, signal.SIGTERM),\n",
        new="            term=lambda: _signal_group(group, signal.SIGKILL),\n",
        tests=("tests/test_cli.py::test_a_rung_killed_on_its_budget_has_its_group_asked_to_stop_first",),
        why="Xvfb leaves its lock file behind on SIGKILL, so every rung 4 timeout burned a display slot for good.",
    ),
    Belief(
        name="a rung is not done until everything it started has stopped",
        path=LADDER / "ladder_cli/cli.py",
        old="            if not procfs.group_is_running(group):\n",
        new="            if process.poll() is not None:\n",
        tests=("tests/test_cli.py::test_a_rung_is_not_done_until_what_it_started_has_finished_stopping",),
        why="The rung's own process dying says nothing about a display server still removing its lock.",
    ),
    Belief(
        name="a rung group that ignores the request to stop is killed on the way out of an interrupted stop",
        path=LADDER / "ladder_cli/cli.py",
        old="        _signal_group(group, signal.SIGKILL)\n        if not wait_gone(stopping.KILL_WAIT_S):\n",
        new="        _signal_group(group, signal.SIGTERM)\n        if not wait_gone(stopping.KILL_WAIT_S):\n",
        tests=(
            "tests/test_cli.py::test_a_second_sigterm_while_the_group_is_stopping_still_kills_what_ignored_the_first",
            "tests/test_cli.py::test_a_member_the_scans_missed_is_killed_before_the_group_is_called_stopped",
        ),
        why="Asking first must not let a rung that will not stop outlive a stop that was cut short; on that path nothing after the routine runs.",
    ),
    Belief(
        name="the group stop's last SIGKILL belongs to the shared routine",
        path=LADDER / "ladder_cli/stopping.py",
        old="        if not gone or always_kill:\n            kill()\n",
        new="        if not gone:\n            kill()\n",
        tests=(
            "tests/test_stopping.py::test_always_kill_sends_one_kill_even_when_the_wait_said_gone[gone]",
            "tests/test_cli.py::test_a_member_the_scans_missed_is_killed_before_the_group_is_called_stopped",
        ),
        why="Review findings F19 and F20: the missed-member SIGKILL used to sit after the routine, where a SIGTERM in the gap skipped it; now the routine sends it once, in its `finally`.",
    ),
    Belief(
        name="a member the scans missed is killed before the group is called stopped",
        path=LADDER / "ladder_cli/cli.py",
        old="            always_kill=not leader_reaped,\n",
        new="            always_kill=False,\n",
        tests=("tests/test_cli.py::test_a_member_the_scans_missed_is_killed_before_the_group_is_called_stopped",),
        why="A fork that lands between two /proc reads is in no listing, and calling the group stopped then leaves it running (review finding H2); the last SIGKILL is the only thing that does not depend on the listing.",
    ),
    Belief(
        name="a reaped leader's emptied group is not sent a last SIGKILL",
        path=LADDER / "ladder_cli/cli.py",
        old="            always_kill=not leader_reaped,\n",
        new="            always_kill=True,\n",
        tests=("tests/test_cli.py::test_a_reaped_leaders_emptied_group_is_not_sent_a_last_sigkill",),
        why="Only an unreaped leader keeps the group id from being handed to an unrelated process. On the normal-exit path `communicate` has already reaped it, so a SIGKILL sent to the emptied group could hit someone else's.",
    ),
    Belief(
        name="a rung that dies on a signal has what it started stopped",
        path=LADDER / "ladder_cli/cli.py",
        old="    if procfs.has_running_member(process.pid):\n        _stop_group(process, leader_reaped=True)\n",
        new="    if False:\n        _stop_group(process, leader_reaped=True)\n",
        tests=("tests/test_cli.py::test_a_rung_that_dies_on_a_signal_has_what_it_started_stopped",),
        why="Review finding F23: a child killed by OOM or a crash cannot run its own cleanup, so the group stop must also run on the path where `communicate` returns normally.",
    ),
    Belief(
        name="a group that survives SIGKILL is reported, not called stopped",
        path=LADDER / "ladder_cli/cli.py",
        old="        if not wait_gone(stopping.KILL_WAIT_S):\n            raise RuntimeError(",
        new="        if False:\n            raise RuntimeError(",
        tests=("tests/test_cli.py::test_a_group_member_that_survives_sigkill_is_reported_not_called_stopped[survives-SIGKILL]",),
        why="Review finding F22: a member in uninterruptible sleep ignores SIGKILL, and the candidate must not hand the next request a profile or display still held.",
    ),
    Belief(
        name="the cheap group check runs often while the /proc scan stays rare",
        path=LADDER / "ladder_cli/cli.py",
        old="                next_scan = now + 0.2\n",
        new="                next_scan = now\n",
        tests=("tests/test_cli.py::test_a_stubborn_group_is_scanned_for_members_only_a_few_times_a_second",),
        why="Review finding F31: a full process-table scan every 20 ms for the grace period is thousands of file reads per stop; `killpg` answers the cheap question.",
    ),
    Belief(
        name="a reap that has waited the drain period gives up on the pipes",
        path=LADDER / "ladder_cli/cli.py",
        old="        process.communicate(timeout=stopping.PIPE_DRAIN_S)\n",
        new="        process.communicate()\n",
        tests=(
            "tests/test_cli.py::test_reap_reads_for_the_drain_period_and_only_then_kills_and_closes_the_pipes[pipes-held-open]",
            "tests/test_cli.py::test_reap_does_not_hang_on_a_straggler_outside_the_group_that_holds_the_pipes",
        ),
        why="A descendant that left the group and inherited the pipes holds them open as long as it lives; an unbounded read hangs the resident CLI on it.",
    ),
    Belief(
        name="a reap that gave up closes the pipes it was reading",
        path=LADDER / "ladder_cli/cli.py",
        old="            for pipe in (process.stdout, process.stderr):\n                if pipe is not None:\n                    pipe.close()\n",
        new="            pass\n",
        tests=(
            "tests/test_cli.py::test_reap_reads_for_the_drain_period_and_only_then_kills_and_closes_the_pipes[pipes-held-open]",
            "tests/test_cli.py::test_reap_does_not_hang_on_a_straggler_outside_the_group_that_holds_the_pipes",
        ),
        why="Killing the leader does not close the read ends held in this process; left open they are a descriptor leak per timed-out rung in a CLI that stays resident.",
    ),
    Belief(
        name="a reap that cannot collect the leader does not wait without a limit",
        path=LADDER / "ladder_cli/cli.py",
        old="            process.wait(timeout=stopping.KILL_WAIT_S)\n",
        new="            process.wait()\n",
        tests=(
            "tests/test_cli.py::test_reap_reads_for_the_drain_period_and_only_then_kills_and_closes_the_pipes[pipes-held-open]",
            "tests/test_cli.py::test_a_leader_that_survives_sigkill_is_reported_not_waited_on_forever",
        ),
        why="Review finding F01: a leader in uninterruptible sleep ignores SIGKILL, and the unbounded `wait()` that followed held the resident CLI forever.",
    ),
    # ---- what the kernel says about a group, asked in one place ----
    Belief(
        name="a zombie left in a stopped group is not waited on",
        path=LADDER / "ladder_cli/procfs.py",
        old="    return has_running_member(group)\n",
        new="    return True\n",
        tests=(
            "tests/test_cli.py::test_a_stopped_group_whose_orphan_nobody_reaps_is_not_waited_on_for_the_whole_grace_period",
            "tests/test_procfs.py::test_a_group_holding_only_a_zombie_is_not_running_though_killpg_still_finds_it",
        ),
        why="Under a PID 1 that never waits, an orphaned grandchild is a zombie for good; counting it makes every stop spend the whole grace period.",
    ),
    Belief(
        name="a zombie in the group does not count as running",
        path=LADDER / "ladder_cli/procfs.py",
        old='        if stat.pgrp == group and stat.state != "Z":\n',
        new="        if stat.pgrp == group:\n",
        tests=(
            "tests/test_cli.py::test_a_stopped_group_whose_orphan_nobody_reaps_is_not_waited_on_for_the_whole_grace_period",
            "tests/test_procfs.py::test_a_running_process_in_the_group_keeps_it_running_and_a_zombie_does_not",
        ),
        why="Same cost as the belief above, reached through the scan itself: a zombie is the stop's answer, not a reason to wait.",
    ),
    Belief(
        name="a group member whose state cannot be read is asked about its group directly",
        path=LADDER / "ladder_cli/procfs.py",
        old="                if os.getpgid(pid) == group:\n                    return True\n",
        new="                pass\n",
        tests=(
            "tests/test_procfs.py::test_a_group_member_whose_state_cannot_be_read_is_not_taken_for_gone",
            "tests/test_procfs.py::test_only_an_exit_reads_as_gone_and_any_other_failed_read_asks_the_kernel[unparseable]",
            "tests/test_procfs.py::test_only_an_exit_reads_as_gone_and_any_other_failed_read_asks_the_kernel[refused]",
        ),
        why="An unreadable stat is not an exit; counting it as gone lets a hidepid mount or a malformed line skip the SIGKILL.",
    ),
    Belief(
        name="a stat read that fails with ProcessLookupError is an exit",
        path=LADDER / "ladder_cli/procfs.py",
        old="        except (FileNotFoundError, ProcessLookupError):\n            continue  # it exited between the listing and the read\n",
        new="        except FileNotFoundError:\n            continue  # it exited between the listing and the read\n",
        tests=("tests/test_procfs.py::test_only_an_exit_reads_as_gone_and_any_other_failed_read_asks_the_kernel[reaped-behind-an-open-file]",),
        why="Reading a stat through a handle opened before the process was reaped raises ProcessLookupError, not FileNotFoundError (measured 2026-11-03); the arm is reachable, and without it an exit reads as an unreadable stat.",
    ),
    Belief(
        name="a /proc that cannot be listed leaves the group counted as running",
        path=LADDER / "ladder_cli/procfs.py",
        old="    except OSError:\n        return True\n    classified = False\n",
        new="    except ValueError:\n        return True\n    classified = False\n",
        tests=("tests/test_procfs.py::test_a_group_is_taken_to_be_running_when_proc_cannot_be_listed",),
        why="`iterdir` raising turned a stop on a host without /proc into a crash with the rung still running.",
    ),
    Belief(
        name="a /proc with nothing classifiable leaves the group counted as running",
        path=LADDER / "ladder_cli/procfs.py",
        old="    return not classified\n",
        new="    return False\n",
        tests=("tests/test_procfs.py::test_a_group_is_taken_to_be_running_when_nothing_in_proc_could_be_classified",),
        why="`killpg` already said something is in the group; a scan that read nothing has not shown it gone.",
    ),
    # ---- what the kernel says about a process, asked in one place ----
    Belief(
        name="the stat line is read after the last parenthesis",
        path=LADDER / "ladder_cli/procfs.py",
        old='text.rsplit(")", 1)[1]',
        new='text.split(")", 1)[1]',
        tests=("tests/test_procfs.py::test_read_stat_takes_the_state_and_group_after_the_last_parenthesis",),
        why="The comm field is a process name and can hold a `)`; splitting at the first one reads the wrong fields.",
    ),
    Belief(
        name="a pid too large to probe is unknown, not a crash",
        path=LADDER / "ladder_cli/procfs.py",
        old="    except (PermissionError, OverflowError):\n        return Liveness.UNKNOWN\n",
        new="    except PermissionError:\n        return Liveness.UNKNOWN\n",
        tests=("tests/test_procfs.py::test_probe_a_pid_too_large_to_ask_about_is_unknown[2147483648]",),
        why="os.kill raises OverflowError past a pid_t; one planted lock would crash every caller that asks.",
    ),
    # ---- a profile lock whose owner cannot be probed is refused, not a crash ----
    Belief(
        name="a profile lock whose owner cannot be asked about is refused with a reason",
        path=LADDER / "ladder_cli/state/jars.py",
        old=(
            "    except (FileNotFoundError, ProcessLookupError):\n"
            "        if procfs.probe(pid) is not procfs.Liveness.GONE:\n"
            "            raise RuntimeError(f\"profile lock owner cannot be checked: {lock}\") from None\n"
            "        state = \"Z\"  # signal 0 says it is gone: the proof the lock needs\n"
        ),
        new="    except (FileNotFoundError, ProcessLookupError):\n        state = \"Z\"\n",
        tests=(
            "tests/test_jars.py::test_cleanup_reports_an_owner_pid_too_large_to_probe_and_keeps_the_lock",
            "tests/test_jars.py::test_a_missing_proc_entry_for_a_live_owner_is_refused_not_cleared",
        ),
        why="A missing stat entry can mean /proc does not cover a live owner as well as an exit; only signal 0 saying GONE is the proof that clears the lock.",
    ),
    Belief(
        name="a profile lock whose owner has exited but is not reaped is cleared",
        path=LADDER / "ladder_cli/state/jars.py",
        old='    if state != "Z":\n',
        new="    if True:\n",
        tests=("tests/test_jars.py::test_cleanup_distinguishes_a_zombie_owner_from_a_running_owner",),
        why="A zombie exists to signal 0 but is gone; refusing its lock strands the profile until something reaps it.",
    ),
    Belief(
        name="pytest moves its temp tree off a TMPDIR too long for a test's socket",
        path=LADDER / "tests/conftest.py",
        old='"/.X11-unix/X301") <= 107:',
        new='"/.X11-unix/X301") <= 108:',
        tests=("tests/test_socket_budget.py::test_conftest_moves_pytest_exactly_when_the_socket_would_not_fit",),
        why="A socket path is capped at 107 bytes; one byte of slack in either direction either breaks the display tests on a long XDG TMPDIR or moves every run off a TMPDIR that fits.",
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


def _short_temp_root() -> str:
    """A temp root that leaves room for a test's unix socket.

    AF_UNIX caps a whole socket path at 107 bytes. A scratch project is
    `<root>/serp-axi-mutation-XXXXXXXX/ladder-cli`, and the tests run with
    `--basetemp=<that>/bt` + a 30-character test name with its numeric suffix
    (31) + `.X11-unix/X301`, which leaves the root 30 bytes. Pytest resolves its
    base directory through symlinks, so the root is measured where it leads. An
    inherited TMPDIR (an XDG state directory, for instance) can spend more than
    that before pytest's own layout is even added; /tmp is the conventional short
    root for those, and stays the fallback.
    """
    inherited = tempfile.gettempdir()
    layout = len("/serp-axi-mutation-XXXXXXXX") + len("/bt") + len("/") + 31 + len("/.X11-unix/X301")
    if len(os.fspath(Path(inherited).resolve())) + layout <= 107:
        return inherited
    tmp = Path("/tmp")
    if tmp.is_dir() and os.access(tmp, os.W_OK):
        return os.fspath(tmp)
    return inherited


@contextmanager
def _scratch_project():
    # Callers give pytest a short base directory (`run_tests` passes --basetemp):
    # a test that binds a unix socket under its tmp_path has 107 bytes for the
    # whole path, and this directory's name plus pytest's default layout under
    # TMPDIR used up all of them for the longest test names.
    with tempfile.TemporaryDirectory(prefix="serp-axi-mutation-", dir=_short_temp_root()) as temporary:
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
            sandbox + wrapper + PYTEST + [f"--basetemp={project.parent / 'bt'}", selector], cwd=project,
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


def _table_problems(beliefs: list[Belief]) -> list[str]:
    """Mistakes in the table itself, found before any test runs.

    A belief with no test can never be killed or survive, so it would be counted
    as nothing at all. Two beliefs with the same edit are one claim written twice
    under different names: both would be "killed" by whichever tests exist, and
    the gate's count would say two things were held where one was. A test listed
    twice in one belief collapses to one entry in the outcomes and would be
    reported as if both sides had been run.
    """
    problems = []
    seen: dict[tuple[Path, str, str], str] = {}
    names: set[str] = set()
    for belief in beliefs:
        if not belief.tests:
            problems.append(f"[{belief.name}] lists no tests")
        if len(set(belief.tests)) != len(belief.tests):
            problems.append(f"[{belief.name}] lists the same test twice")
        if belief.name in names:
            problems.append(f"[{belief.name}] is named twice")
        names.add(belief.name)
        key = (belief.path, belief.old, belief.new)
        if key in seen:
            problems.append(f"[{belief.name}] is the same edit as [{seen[key]}]; list its test there instead")
        seen.setdefault(key, belief.name)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("match", nargs="?", help="only beliefs whose name contains this")
    parser.add_argument("--list", action="store_true", help="print beliefs and exit")
    args = parser.parse_args()

    problems = _table_problems(BELIEFS)
    if problems:
        for problem in problems:
            print(f"BAD TABLE: {problem}", file=sys.stderr)
        return 2

    chosen = [b for b in BELIEFS if not args.match or args.match in b.name]
    if args.list:
        for belief in chosen:
            print(f"- {belief.name}")
            for test in belief.tests:
                print(f"    test: {test}")
            print(f"    why:  {belief.why}")
        return 0

    if not chosen:
        print("no beliefs matched", file=sys.stderr)
        return 2

    survived: list[tuple[Belief, list[str]]] = []
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

        not_clean = [(t, *_baseline(t)) for t in belief.tests]
        not_clean = [(t, base, last) for t, base, last in not_clean if base != "pass"]
        if not_clean:
            # The belief cannot demonstrate anything: a test of it is already red
            # on clean code, or matches no test at all. Counting that as a kill
            # would have the gate certifying itself.
            test, base, last = not_clean[0]
            print(f"INVALID   [{belief.name}]: {test} is {base} on clean code ({last})")
            invalid.append(belief)
            continue

        outcomes: dict[str, tuple[str, str]] = {}
        with _scratch_project() as project:
            target = project / belief.path.relative_to(LADDER)
            target.write_text(original.replace(belief.old, belief.new, 1))
            for test in belief.tests:
                outcomes[test] = run_tests(test, project)

        errored = [(t, last) for t, (outcome, last) in outcomes.items() if outcome == "error"]
        hollow = [t for t, (outcome, _) in outcomes.items() if outcome == "pass"]
        if errored:
            invalid.append(belief)
            test, last = errored[0]
            print(f"INVALID   [{belief.name}]: mutant test could not run: {test} ({last})")
        elif hollow:
            survived.append((belief, hollow))
            print(f"SURVIVED  [{belief.name}] -> {outcomes[hollow[0]][1]}")
            for test in hollow:
                print(f"          hollow test: {test}")
            print(f"          consequence: {belief.why}")
        else:
            killed += 1
            print(f"killed    [{belief.name}]" + (f" by all {len(belief.tests)} tests" if len(belief.tests) > 1 else ""))

    print()
    print(f"{killed}/{len(chosen)} beliefs killed")
    if survived:
        print(f"\n{len(survived)} hollow belief(s): the suite does not hold these.")
        for belief, hollow in survived:
            print(f"  - {belief.name} ({len(hollow)} of {len(belief.tests)} tests stayed green)")
    if invalid:
        print(f"\n{len(invalid)} stale entr(ies): the code moved and the claim did not.")
        for belief in invalid:
            print(f"  - {belief.name}")

    return 1 if (survived or invalid) else 0


if __name__ == "__main__":
    sys.exit(main())
