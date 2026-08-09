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

---

# Task 4 Fix Report (review round 1)

## Status: DONE

## Findings addressed

- **Finding 1 (unmapped-status fallback):** dropped the raw 300-char body
  excerpt from the error message; now uses only `parsed.message ?? "no
  details"`. No raw HTTP body can reach stdout via this branch.
- **Finding 2 (success-path `response.json()`):** wrapped in a try/catch
  that throws a `SerperAxiError` (`runtime`, "Serper returned a non-JSON
  response (<status>)") instead of leaking a raw `SyntaxError`.

## Tests added (`src/serper.test.ts`)

- Unmapped status (400) with a JSON body containing `message`: asserts the
  thrown `SerperAxiError.message` matches `/400/` and `/Bad request/` and
  does NOT contain the raw JSON body text.
- 200 response with a non-JSON body: asserts a `SerperAxiError` (kind
  `runtime`) is thrown, not a raw `SyntaxError`.

## Verification

- `node --test src/serper.test.ts` (9 tests, 7 original + 2 new) — output:

```
✔ searchSerper on an unmapped status uses the parsed message and not the raw body (0.904298ms)
✔ searchSerper wraps a non-JSON 200 body as a runtime error, not a SyntaxError (0.908663ms)
ℹ tests 9
ℹ suites 0
ℹ pass 9
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 169.573883
```

- `npm run typecheck` — clean (no output beyond the `tsc --noEmit` banner).

## Commit

`b0f5177 fix: stop SerperAxiError leaking raw HTTP bodies and raw SyntaxErrors`
