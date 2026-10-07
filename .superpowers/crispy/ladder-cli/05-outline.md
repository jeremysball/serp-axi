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

Testable result: Whisper constructs once per CLI life (startup test asserts
zero model loads before first audio need); `jarIn`/`jarOut` round-trip through
the Python state module; README documents the ladder flags.

Axis resolution, `--profile` expansion, and the six-axis orthogonality pairs
moved to Phase 2 (ruling 1 at §2): they are request building, not rung
behaviour, and cannot ship after the dataclass that validates them.

Files touched: `ladder-cli/rungs/whisper.py`, `ladder-cli/state/jars.py`,
`README.md` (ladder flags documented).

Checks: `npm run check` green; `pytest` green; the q3_restart jar-replay
expectation encoded (replay alone stays `blocked`: want 4 still unmet, by
test).

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
