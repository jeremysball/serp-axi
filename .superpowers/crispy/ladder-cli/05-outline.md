# Outline: resident ladder CLI

Each phase is a vertical slice ending in a sensor going green. Order is
dependency order; every phase merges to main behind a ferried review before
the next starts.

# Phase 1: TypeScript lifecycle against a stub child

Testable result: `src/ladder.test.ts` green — spawn-once, ready-wait, queued
second scrape, idle teardown, ok/dead/blocked mapping, stderr-tail errors,
pre-ready-exit failure. No Python exists yet; the stub is a 20-line node
script replaying canned NDJSON.

Files touched: `src/ladder.ts` (new), `src/ladder.test.ts` (new),
`src/commands/scrape.ts` (`--ladder` flag wired to `fetchViaLadder`,
serper stays the scrape default).

Checks: `npm run check` green; mutation pass on the ready-wait and
verdict-mapping lines.

# Phase 2: Python skeleton, full request schema, rung 1

Testable result: a real `ladder-cli` answers a rung-1 URL end to end through
`fetchViaLadder`: handshake, NDJSON loop, `primp` fetch, `ok` response with
the `protocol: 1` field, and a 90s-budget timeout path exercised by test.

The parent half lands in the same phase, because §2.3's dataclass rejects
unknown fields: nine-field request schema, `protocol: 1` in both directions,
axis resolution (flags > env > config > default) with `--profile` and jar
expansion, sibling-of-package binary resolution, and the §1.3 honest-empty
rule. A parent that still sends bare `{url}` cannot coexist with the child.

Files touched: `ladder-cli/pyproject.toml` (pinned deps),
`ladder-cli/cli.py`, `ladder-cli/rungs/http.py`, `ladder-cli/tests/`
(skeleton + rung-1 tests), `src/ladder.ts` (request building, protocol check,
honest-empty, binary resolution: sibling-of-package, `SERP_AXI_LADDER_BIN`
override, missing-binary error), `src/commands/scrape.ts` (axis flags),
`src/ladder.test.ts` (the three approval sensors).

Checks: `npm run check` green; `pytest` green; one live rung-1 fetch by hand,
never in CI.

# Phase 3: Browser rungs 2–4

Testable result: Camoufox, zendriver+CF-click, and headed-Chromium rungs port
with the spike's measured constants (timeouts, `humanize=True`, allowlist
site), each with unit tests on recorded fixtures. Escalation order and the
90s SIGKILL budget asserted per rung.

Files touched: `ladder-cli/rungs/camoufox.py`,
`ladder-cli/rungs/zendriver.py`, `ladder-cli/rungs/headed.py`,
`ladder-cli/state/profiles.py`, `ladder-cli/tests/` (rung fixtures).

Checks: `pytest` green; fixture replay of a rung-2 and rung-3 URL from the
spike rows.

# Phase 4: Rung 5, and the jar state modules

Corrected premise. The first draft of this phase claimed that
`spikes/scrape-2026-10-03/harness/q5_audio.py:44` rebuilt `WhisperModel` per URL
and that a module memo fixed it. That claim is false and the cited line does not
support it: `drive()` already spawns `--one` in a fresh subprocess per try
(`q5_audio.py:74`), and `one()` builds the model once and reuses it across the
three audio rounds. A per-process memo therefore reproduces the spike's own
behaviour instead of improving on it. What is actually missing is amortization
across fetches, which the per-rung subprocess model prevents
(`ladder-cli/ladder_cli/cli.py:43` runs `python -m ladder_cli --rung <rung>`, so
the module global dies with every fetch).

Testable result:

- The Whisper model constructs once per resident child's life, across fetches.
  A startup test asserts zero model loads before first audio need, and a
  two-fetch test asserts exactly one construction in total. This is achieved by
  running rung 5 inside the resident child instead of in a per-rung SIGKILL
  subprocess; see the budget note.
- `jarIn` and `jarOut` are routed end to end (request to rung to jar file) and
  round-trip through the Python state module.
- README documents the ladder flags, and every documented flag is exercised by a
  test, so a flag that silently does nothing fails the suite.

Budget note. The SIGKILL budget exists to bound a browser launch or a hung
network fetch. Rung 5 does neither: no browser, no fetch, only the transcription
of a clip already on disk. It runs in the resident child so its model survives
across fetches, and carries its own soft deadline. The uniform 90s kill stays on
rungs 1 to 4.

Defects this phase must fix, each with a test that goes red first:

1. `base_domain` returns the last two labels, so `www.bbc.co.uk` yields `co.uk`
   and a `.co.uk` sibling's defence cookies pass the filter. The scope must stop
   at the registrable domain under multi-label public suffixes. This is the same
   class of bug as the lookalike fix already made, one label further out.
2. `keeps()` derives the host with `url.split("/")[2]`, which raises `IndexError`
   on a scheme-less URL and keeps a `:port` in the scope. `LadderRequest.parse`
   accepts any non-empty string.
3. The jar is written as JSON under `<name>.cookies.dat`, the exact filename
   zendriver's `cookies.save/load` writes its own format to
   (`solver_probe.py:86,89,113`). Either the format or the name changes, and the
   choice is recorded at the code with its reason.
4. `answer_rounds` materializes the whole clip iterable with `list(clips)` before
   capping at `MAX_ROUNDS`, draining a lazy producer past the three-round budget.
   The ceiling is correct and stays; the eager materialization goes.
5. `clear_locks` is written and tested but called from no production path, so the
   H4 stale-lock stall is still live. Wire it into the profile launch path, where
   `solver_probe.py:122` ran it before every launch.
6. `cli.dispatch` reads only `rungCeiling` and `url` and silently drops `jarIn`
   and `jarOut`, while the README documents those flags as working.
7. `test_all_three_browser_rungs_apply_one_set_of_rules` sweeps `MODULES.values()`,
   now five modules including `http` and `whisper`, while its name and docstring
   say three.

Axis resolution, `--profile` expansion, and the six-axis orthogonality pairs
moved to Phase 2 (ruling 1 at §2): they are request building, not rung
behaviour, and cannot ship after the dataclass that validates them.

Files touched: `ladder-cli/rungs/whisper.py`, `ladder-cli/state/jars.py`,
`ladder-cli/ladder_cli/cli.py` (rung 5 in the resident child, jar routing),
`README.md` (ladder flags documented).

Checks: `npm run check` green; `pytest` green; the q3_restart jar-replay
expectation encoded (replay alone stays `blocked`: want 4 still unmet, by test);
mutation check in which every defect listed above has a test that goes red.

Verification discipline. Findings are verified against source, not settled by a
model vote. Every cited constant names `file:line` and the cited line is checked
to actually contain it; a citation that does not resolve is a failure, not a
footnote. This replaces the decision-model verifier, which on this phase refuted
five true findings including the central one above and returns no reasoning to
audit.

Out of scope, stated rather than implied: the browser half of the audio solve
(clicking the audio button and typing the answer back, `q5_audio.py:28-48`) has
no recorded fixture and is not written. Rung 5 reports an audio challenge as
`blocked` rather than answering it.

# Phase 5: Regression lock-in and docs

Testable result: `final.jsonl` verdicts and `q6_rows.jsonl` classifier
thresholds replay bit-for-bit; the suite fails if `flywheel.md` is missing
or shorter than recorded; README and `using-serp-axi` skill document the
ladder path with every claim verified against the build.

Files touched: `ladder-cli/tests/test_regression.py`,
`spikes/scrape-2026-10-03/flywheel.md` (entry count recorded),
`README.md`, skill repo `using-serp-axi/SKILL.md`.

Checks: full `npm run check` + `pytest` green; docs-claim audit (one quote
per claim with `file:line`).
