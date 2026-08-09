# Task 2 Report: `SerperAxiError` and exit-code mapping

## Status: DONE_WITH_CONCERNS

## What was done

- Created `src/errors.ts` — `SerperAxiError` (extends `Error`, `name` set to `"SerperAxiError"`, readonly `kind: "usage" | "runtime"`,
  readonly `help: string`) and `exitCodeForError(error: unknown): number` (2 for usage, 1 for runtime or any non-`SerperAxiError`).
  Implementation is verbatim from the brief.
- Created `src/errors.test.ts` — the brief's 4 tests, verbatim except the import specifier (see deviation below).
- Updated `tsconfig.json` — added `allowImportingTsExtensions` and `rewriteRelativeImportExtensions` (see deviation below).

## Verification (real execution)

- Step 2 (failing tests): `node --test src/errors.test.ts` failed as expected — `ERR_MODULE_NOT_FOUND` for `./errors.js`.
- Step 4 (passing tests): `node --test src/errors.test.ts` → 4/4 pass.
- `npm run typecheck` → clean.
- `npm run build` → emits `dist/errors.js` and `dist/errors.test.js` with `.js` specifiers (rewritten by tsc).
- `node dist/errors.test.js` → 4/4 pass (built output runs for real).
- `npm run check` → typecheck + tests, all green.

## Deviation from the brief (the concern)

The brief's test file imports `from "./errors.js"`. On Node 26.5.1 (the pinned runtime) that specifier cannot resolve: Node 26.0.0
removed `--experimental-transform-types`, and with it the `.js` → `.ts` specifier rewriting (Node docs, "Modules: TypeScript",
v26.x: "file extensions are mandatory in import statements … `import './file.ts'`, not `import './file'`"). Verified empirically:
`import { x } from "./b.js"` fails with `ERR_MODULE_NOT_FOUND` even with `--experimental-strip-types`, while `"./b.ts"` works.

Fix applied:
- `src/errors.test.ts` imports `from "./errors.ts"` (the only change to the brief's test content).
- `tsconfig.json` gains `allowImportingTsExtensions: true` (tsc accepts `.ts` specifiers) and
  `rewriteRelativeImportExtensions: true` (tsc rewrites them to `.js` in emitted `dist/` output, so the built CLI and its
  `dist/bin/serper-axi.js` entrypoint keep working under NodeNext ESM).

This keeps the plan's architecture intact: tests run `.ts` directly via Node's native type stripping, and `npm run build` still
produces runnable `.js` output. Later tasks' briefs use the same `./x.js` specifier pattern (e.g. `./output.js`, `./serper.js`,
`./errors.js` in Task 3+); they will need the same `.ts`-specifier treatment, which the tsconfig change now supports.

## Commit

- `feat: add SerperAxiError and exit-code mapping` (includes the tsconfig change; `src/errors.ts`, `src/errors.test.ts`,
  `tsconfig.json`).
