# Task 8 Report: `update` command

## Status

DONE

## Summary

Implemented the `update` command for `serper-axi`: a local-only command that
reports the upgrade path (`git pull && npm run build && npm install -g .`)
and notes that the project is not published to the npm registry, so there is
no version to check remotely. Followed the brief's TDD steps: wrote the
failing test, verified it failed, wrote the implementation, verified it
passed, then committed.

## Files

- Created: `src/commands/update.ts` — `runUpdate(): AxiOutput` and
  `updateCommand: CliCommand` (name `"update"`), consuming `CliCommand` from
  `../cli.ts` and `AxiOutput` from `../output.ts`.
- Created: `src/commands/update.test.ts` — single test asserting the
  `status` and `upgrade` fields of `runUpdate()`.

## Deviations from the brief

- Import specifiers use `.ts` instead of the brief's `.js`
  (`from "../cli.ts"`, `from "../output.ts"`, `from "./update.ts"`), per the
  project-wide convention required by the known Node 26.5.1 import-specifier
  issue. All other code is verbatim from the brief.

## Verification

- `node --test src/commands/update.test.ts` (before implementation):
  FAIL, 1/1 — `ERR_MODULE_NOT_FOUND` for `./update.ts` (expected).
- `node --test src/commands/update.test.ts` (after implementation):
  PASS, 1/1.
- `npm test` (full suite): PASS, 52/52.
- `npm run typecheck`: PASS (no errors).

## Commit

- Hash: `4b76576`
- Message: `feat: add update command`
- Files: `src/commands/update.ts`, `src/commands/update.test.ts` (2 files,
  32 insertions). Note: git emitted a non-fatal warning about
  `.git/packed-refs.lock` on a read-only file system, but the commit was
  created successfully and is present in the log.
