# Task 9 Report: App wiring and entrypoint

## Status

DONE

## Summary

Wired the three existing commands (`search`, `scrape`, `update`) into the CLI app options via a new `createAppOptions(execUrl, overrides)` factory in `src/app.ts`, and added the real entrypoint script `src/bin/serper-axi.ts`. Followed the brief's TDD sequence: wrote `src/app.test.ts` first, verified it failed with `ERR_MODULE_NOT_FOUND` (Cannot find module './app'), then implemented `src/app.ts` and verified 4/4 tests pass. Built with `npm run build` and smoke-tested the compiled entrypoint `node dist/bin/serper-axi.js` directly (home view exit 0, unknown command exit 2). Full `npm run check` (typecheck + all 56 tests) passes. Committed as `feat: wire commands into the CLI entrypoint`.

## Files

- Created: `src/app.test.ts` (4 tests, from brief verbatim)
- Created: `src/app.ts` (`VERSION = "0.1.0"`, `createAppOptions(execUrl, overrides?)` returning `Omit<RunCliOptions, "stdout">`)
- Created: `src/bin/serper-axi.ts` (shebang entrypoint calling `runCli(process.argv.slice(2), { ...createAppOptions(import.meta.url), stdout: process.stdout })`)
- Modified: none (no other files changed)

## Deviations from the brief

- **Import specifiers use `.ts`, not `.js`** (`./cli.ts`, `./app.ts`, `./commands/search.ts`, etc.) in all three new files. This is the project-wide convention mandated for this build due to a known Node 26.5.1 import-specifier issue; `tsc`'s rewrite of specifiers is disabled by `allowImportingTsExtensions`/`rewriteRelativeImportExtensions` in the tsconfig (verified: `dist` output contains `.js` specifiers and runs fine under Node).
- No other deviations; all code, tests, commands, and the commit message are otherwise verbatim from the brief.

## Verification

### Step 2 — failing tests (before implementation)

```
node --test src/app.test.ts
Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../src/app.ts' imported from .../src/app.test.ts
✖ src/app.test.ts (162.805686ms)   — 1 fail / 0 pass
EXIT=1
```

### Step 4 — tests pass (after `src/app.ts`)

```
node --test src/app.test.ts
✔ no-args home view includes bin, description, and every command
✔ unknown command exits 2 with a structured error
✔ update command dispatches end to end through runCli
✔ search --help prints the command's help without making a network call
ℹ tests 4 / pass 4 / fail 0
EXIT=0
```

### Step 6 — build and smoke test

```
npm run build
> tsc
BUILD_EXIT=0
dist/bin/serper-axi.js exists
```

```
node dist/bin/serper-axi.js ; echo $?
bin: /workspace/serper-axi/.worktrees/serper-axi-impl/dist/bin/serper-axi.js
description: Run Serper (Google Search API) queries and page scrapes
commands[3]: search,scrape,update
help[3]: Run `serper-axi search --help` for details,Run `serper-axi scrape --help` for details,Run `serper-axi update --help` for details
EXIT=0
```

```
node dist/bin/serper-axi.js bogus ; echo $?
error: unknown command `bogus`
help: "valid commands: search, scrape, update"
EXIT=2
```

Matches the brief: exit 0 with home view whose `bin:` ends in `dist/bin/serper-axi.js` and commands `search,scrape,update`; exit 2 with `error: unknown command` for `bogus`. (No absolute path is hardcoded anywhere in source; the build path appearing in the smoke-test output is the sandbox's own `dist/bin/serper-axi.js`, which is expected.)

### Full check

```
npm run check
(tsc --noEmit && node --test "src/**/*.test.ts")
ℹ tests 56 / pass 56 / fail 0
CHECK_EXIT=0
```

## Commit

- Hash: `9f9711f`
- Message: `feat: wire commands into the CLI entrypoint`
- Files: `src/app.ts`, `src/app.test.ts`, `src/bin/serper-axi.ts` (3 files, 86 insertions)

Note: git printed a benign warning `Unable to create '.../.git/packed-refs.lock': Read-only file system` while creating the commit, but the commit itself succeeded (verified via `git log`), so no action was taken.
