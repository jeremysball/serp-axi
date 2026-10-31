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
`ladder-cli/ladder_cli/cli.py`, `ladder-cli/ladder_cli/rungs/http.py`, `ladder-cli/tests/`
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

Files touched: `ladder-cli/ladder_cli/rungs/camoufox.py`,
`ladder-cli/ladder_cli/rungs/zendriver.py`, `ladder-cli/ladder_cli/rungs/headed.py`,
`ladder-cli/tests/` (rung fixtures). Profile ownership lives in zendriver's
`climb` and `ladder-cli/ladder_cli/state/jars.py`, not a separate `profiles.py`.

Checks: `pytest` green; fixture replay of a rung-2 and rung-3 URL from the
spike rows.

# Phase 4: Rung 5, and the jar state modules

Approved scope correction: live rung 5 is deferred. The four registered live
rungs are HTTP, Camoufox, zendriver CF, and headed zendriver CF
(`ladder-cli/ladder_cli/rungs/__init__.py:24-25`). Ceiling 5 remains accepted
for protocol compatibility, but runs at most those four and reports actual
`rungReached: 4` on exhaustion. Do not fetch the headed page a second time
under an audio rung.

Corrected premise. The first draft claimed that
`spikes/scrape-2026-10-03/harness/q5_audio.py:44` rebuilt `WhisperModel` per URL
and that a module memo fixed it. That claim is false: `drive()` already
spawns `--one` in a fresh subprocess per try (`q5_audio.py:74`), and `one()`
builds the model once and reuses it across the three audio rounds. A
per-process memo reproduces that behavior. Cross-fetch amortization remains
undelivered because the isolated process dies after its fetch.

Testable result within the corrected scope:

- All live rungs use `run_rung_isolated` and the hard 90s subprocess budget,
  with process-group SIGKILL on timeout
  (`ladder-cli/ladder_cli/cli.py:62-103,178-180`). There is no inline soft
  SIGALRM route.
- Unwired audio helpers load lazily and cache only within their own process.
  `answer_rounds` uses `islice` to consume at most `MAX_ROUNDS` clips
  (`ladder-cli/ladder_cli/rungs/whisper.py:42-47,66-78`). They are not a live
  escalation step and deliver neither cross-fetch model reuse nor an
  end-to-end audio solve.
- `jarIn` and `jarOut` travel through per-request context and subprocess
  arguments. Only zendriver rungs 3 and 4 read and write jars; HTTP and
  Camoufox do neither. Zendriver loads before navigation and saves before
  browser shutdown (`ladder-cli/ladder_cli/rungs/zendriver.py:121-144`).
- JSON jars use `<name>.cookies.json` by convention. Explicit paths are used
  unchanged; callers must not target zendriver's `.cookies.dat` pickle files.
  Each zendriver rung loads the input and saves its own output; a later rung's
  save replaces the earlier one.
- Profile cleanup runs under a nonblocking exclusive `.ladder.lock` lease
  held across the browser fetch, including shutdown. Cleanup refuses live,
  foreign-host, unknown, and permission-uncheckable owners. Tests and
  examples use temporary fixture directories, never real browser profiles.
- README describes the delivered ladder flags and their limits; documented
  flags need tests that catch silently ignored behavior.

Safeguards and defect sensors:

1. Replace last-two-label domain scoping with pinned tldextract's bundled
   public/private suffix snapshot, with runtime network fetching disabled.
   Multi-label public suffixes and private suffixes delimit registrable
   domains; unknown suffixes remain host-scoped. Keep label-boundary checks
   so lookalike domains cannot pass.
2. Parse URL hostnames rather than using `url.split("/")[2]`. Ports and
   userinfo do not enter cookie scope; unscopable URLs admit no cookies.
3. Filter the defence-cookie allowlist on both jar read and write. Missing
   jars are cold starts; corrupt or unreadable jars raise instead of
   silently disappearing. Preserve `.cookies.json` filenames.
4. Keep lazy audio clip consumption bounded to three rounds without
   materializing the entire producer. A helper test establishes only helper
   behavior, not a browser audio solve.
5. Exercise dead-local-owner cleanup and refusal of every unverifiable or
   live owner. Verify lease contention fails without deleting profile
   locks, and hold the lease through cleanup, launch, fetch, and shutdown.
6. Exercise jar routing through dispatch, subprocess arguments, and the two
   zendriver browser paths. Assert HTTP and Camoufox do not read or write
   jars.
7. Scope browser-rule tests to the three browser modules, not all registry
   modules. Assert the live registry has four entries, ceiling 5 performs
   no fifth fetch, and exhaustion reports the actual rung reached.

Jar replay rescue remains unproven. Preserve the q3_restart expectation
that replay alone stays `blocked` (3/3 in the spike); round-trip tests do
not establish rescue. Same-tab and browser-residency goals remain deferred:
disk profiles and jars do not keep a browser or tab alive between isolated
rungs.

Axis resolution, `--profile` expansion, and the six-axis orthogonality pairs
moved to Phase 2 (ruling 1 at §2): they are request building, not rung
behaviour, and cannot ship after the dataclass that validates them.

Files touched: `ladder-cli/ladder_cli/cli.py`,
`ladder-cli/ladder_cli/rungs/__init__.py`,
`ladder-cli/ladder_cli/rungs/whisper.py`,
`ladder-cli/ladder_cli/rungs/zendriver.py`,
`ladder-cli/ladder_cli/rungs/headed.py`,
`ladder-cli/ladder_cli/state/jars.py`,
`ladder-cli/pyproject.toml`, `ladder-cli/tests/`,
`README.md` (flags and scope limits).

Gate status: review, integration, and live gates remain pending. Verification
runs are separate records, not design acceptance claims. Phase 4 is not
declared accepted or merged, and historical TDD approval flags do not
provide a fresh signoff.

Verification discipline. Findings are verified against source, not settled by a
model vote. Every cited constant names `file:line` and the cited line is checked
to actually contain it; a citation that does not resolve is a failure, not a
footnote. This replaces the decision-model verifier, which on this phase refuted
five true findings including the central one above and returns no reasoning to
audit.

Out of scope: live rung 5, cross-fetch model/browser residency, same-tab
continuity across isolated rungs, and browser/audio integration. The browser
half of the audio solve (clicking the audio button and typing the answer
back, `q5_audio.py:28-48`) has no recorded fixture and is not delivered.
Audio challenges remain subject to the four live rungs' verdicts; no audio
solver runs after rung 4.

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
