# Task 4 Report: Serper HTTPS client

## Status: DONE_WITH_CONCERNS

## What was built

- `src/serper.ts` — direct HTTPS client for Serper's search
  (`https://google.serper.dev/search`) and scrape
  (`https://scrape.serper.dev`) endpoints. Exposes `SearchParams`,
  `OrganicResult`, `SearchResponse`, `ScrapeResponse`, `searchSerper`, and
  `scrapeSerper`, matching the brief's interfaces. Both functions default
  `fetchImpl` to the global `fetch` and throw `SerperAxiError`
  (`kind: "runtime"`) on any HTTP or network failure. Status mapping: 403,
  429, 404, >=500 each get a specific message + help; any other non-OK
  status throws a generic runtime error carrying the parsed error body.
- `src/serper.test.ts` — 7 mocked-fetch tests from the brief (successful
  search, 403/429/500 for search, scrape success, 404 for scrape, network
  failure wrapping).
- `src/serper.live.test.ts` — 3 live-API tests from the brief, each skipped
  when `SERPER_API_KEY` is unset.

## Verification

- Step 2 (failing first): `node --test src/serper.test.ts` failed with
  `ERR_MODULE_NOT_FOUND` for `./serper.ts` as expected.
- Step 4 (passing): `node --test src/serper.test.ts` → 7/7 pass.
- Step 6 (live, unset): `env -u SERPER_API_KEY node --test
  src/serper.live.test.ts` → 3/3 reported `skipped`, 0 failures.
- `npm run typecheck` → clean.
- Full suite (`errors`, `output`, `serper`, `serper.live`) → 20/20 pass,
  0 fail.

## Concerns

- The key-present path (Step 6 second run) is **unverified in this
  environment**: no `SERPER_API_KEY` is available in the sandbox, so the
  real-API assertions and the bad-key 403 path were not exercised against
  the live Serper service. No result is fabricated for that path.
- Per the known Node 26 import-specifier issue, all relative imports in
  the new files use `.ts` extensions (`./errors.ts`, `./serper.ts`); the
  brief's `.js` specifiers were not used. `tsconfig.json` was already
  configured in Task 2 (`allowImportingTsExtensions` +
  `rewriteRelativeImportExtensions`), no further changes needed.

## Commit

`feat: add direct HTTPS client for Serper search and scrape`
