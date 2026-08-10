# Final Review Fix Report

Date: 2026-08-09

## Status

DONE

## Summary

Fixed all four findings from the final whole-branch review of `serper-axi`.
Each fix is a small, independent, single-file change (plus its test file), and
all four were mandated by the human to override the plan's literal text. The
full check suite (`npm run check`) passes with 60/60 tests.

## Changes

### Finding 1 — `update` command silently accepts unknown flags/arguments (Critical)

**File:** `src/commands/update.ts`

`runUpdate` now accepts `args: string[]` and calls `parseFlags(args, {}, "update")`.
If `parseFlags` returns any positionals, a usage `SerperAxiError` is thrown naming
them, reusing the same shape `scrape.ts` uses for its extra-positionals check
(`unexpected argument "extra" for \`update\`` with `usage: serper-axi update` help).
Unknown flags are rejected by `parseFlags` itself (now via the hardened
own-property check from Finding 2). `updateCommand.run` is now
`(args) => runUpdate(args)`.

**Tests** (`src/commands/update.test.ts`):
- Existing test updated to call `runUpdate([])`; still asserts the status/upgrade fields.
- New: `runUpdate(["--bogus"])` rejects with a usage `SerperAxiError` mentioning `unknown flag --bogus`.
- New: `runUpdate(["extra"])` rejects with a usage `SerperAxiError` mentioning `unexpected argument "extra"`.

### Finding 2 — flag-name check uses `in`, so it matches inherited `Object.prototype` names (Important)

**File:** `src/cli.ts`

`parseFlags` now uses `!Object.hasOwn(spec, name)` instead of `!(name in spec)`,
so inherited names like `constructor`, `toString`, `valueOf`, and
`hasOwnProperty` are rejected as unknown flags instead of resolving to inherited
function values.

**Tests** (`src/cli.test.ts`):
- New: `parseFlags(["--constructor"], {}, "update")` rejects with a usage
  `SerperAxiError` mentioning `unknown flag --constructor`.

### Finding 3 — truncated search snippets exceed the stated 200-character limit by 3 (Important)

**File:** `src/commands/search.ts`

`runSearch` now calls `truncate(r.snippet, SNIPPET_LIMIT - 3)` instead of
`truncate(r.snippet, SNIPPET_LIMIT)`, so a truncated snippet's final rendered
length (text + `...` suffix) is exactly 200 characters, never 203. The
`snippetInfo.truncated ? \`${snippetInfo.text}...\` : snippetInfo.text`
structure is unchanged.

**Tests** (`src/commands/search.test.ts`):
- Existing snippet-length assertion updated from 203 to 200.

### Finding 4 — network-error message included in user-facing output without a length bound (Important)

**File:** `src/serper.ts`

Added a `boundedDetail` helper that caps a message at 200 characters, appending
`...` when truncated. The network-error catch block now interpolates
`boundedDetail((cause as Error).message)` instead of the raw unbounded message,
so user-facing output stays a clean, structured `error:`/`help:` pair.

**Tests** (`src/serper.test.ts`):
- New: a fetchImpl rejecting with an `Error` carrying a 5000-character `message`
  produces a `SerperAxiError` whose message is bounded (ends with `...`, does not
  contain the full 5000-character payload).

## Verification

Command: `npm run check` (typecheck + full test suite)

Result: 0 failures — **60 tests passed** (60 pass, 0 fail, 0 skipped).

## Commits

- `c28f05a` — `fix: reject unknown update args, harden flag parsing, cap snippet and error-message length`
