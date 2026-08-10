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

---

## Fix Report (review verdict: Needs fixes — plan-error, raw error leak on stdout)

### Finding

The `catch` block in `runCli` (src/cli.ts) wrote the raw thrown error's message
straight to stdout when the error was not a `SerperAxiError`, violating the
Global Constraint "never a stack trace, raw HTTP body, or dependency name" on
stdout; additionally `(error as Error).message` is `undefined` for non-`Error`
throws, which TOON encodes as `error: null`.

### Fix

Sanitized the non-`SerperAxiError` path in the `catch` block: a generic
`error: "unexpected error"` / `help: "see stderr for details"` pair is written
to stdout, and the real detail (`error.message`, or `String(error)` for
non-`Error` throws) is written to stderr via `process.stderr.write`.

### Verification

Test command: `node --test src/cli.test.ts`

Output:

```
✔ parseFlags collects positionals and string flags (0.2...ms)
✔ parseFlags rejects an unknown flag with a usage error (0.2...ms)
✔ parseFlags rejects a value-flag with a missing value (0.1...ms)
✔ runCli with no args renders the home view (0.4...ms)
✔ runCli rejects an unknown command with exit 2 (0.5...ms)
✔ runCli dispatches to a matching command and renders its output (0.5...ms)
✔ runCli surfaces a SerperAxiError as a structured error with the right exit code (0.6...ms)
✔ runCli prints a command's help text on --help without dispatching (0.2...ms)
✔ runCli sanitizes a non-SerperAxiError throw so raw detail never reaches stdout (0.9...ms)
ℹ tests 9
ℹ suites 0
ℹ pass 9
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ duration_ms 130.618148
```

Typecheck command: `npm run typecheck` — clean (no errors).

### Commits

- `265e433 fix: sanitize non-SerperAxiError output to stop raw error detail leaking to stdout`
