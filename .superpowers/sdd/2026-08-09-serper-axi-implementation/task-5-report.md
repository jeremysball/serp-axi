# Task 5 Report: CLI dispatcher and flag parser

## Status

DONE

## What was done

- Wrote the failing tests first in `src/cli.test.ts` (TDD red), verified they fail with `Cannot find module './cli.ts'`.
- Implemented `src/cli.ts` with:
  - `FlagType`, `FlagSpec`, `ParsedFlags`, `parseFlags` — `--name value` string flags, `--name` boolean flags, `--help`/`-h` detection, usage-error on unknown flag or missing value (`SerperAxiError` kind `"usage"`).
  - `CliCommand`, `RunCliOptions`, `runCli` — home view (AXI-encoded, `~`-collapsed `bin`), top-level help, `--version`, unknown-command rejection (exit 2), per-command help on `--help` (no dispatch), command dispatch with structured error rendering and `exitCodeForError`.
- Used `.ts` import specifiers (`./errors.ts`, `./output.ts`) in both files per the known Node 26 no-rewrite issue; no tsconfig changes needed.

## Verification

- `node --test src/cli.test.ts`: 8/8 tests pass.
- `npx tsc --noEmit`: no errors.

## Commits

- `feat: add CLI dispatcher, flag parser, home view, and help rendering`

## Concerns

- `parseFlags` treats any `--`-prefixed token after a value-flag as a missing value (values cannot start with `--`); fine for Serper use cases but worth noting for later tasks.
- `runCli` catches only errors during `command.run`; a non-Error throw (e.g. a string) would hit `(error as Error).message` and yield `undefined` — the brief's code does the same, so left verbatim.
