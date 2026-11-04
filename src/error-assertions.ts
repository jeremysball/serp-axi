import assert from "node:assert/strict";
import { SerpAxiError, type SerpAxiErrorKind } from "./errors.ts";

/**
 * The one assertion for a `SerpAxiError` in a test: the type, the kind, and a
 * pattern the message must match. Test-only: nothing outside a `*.test.ts` file
 * imports it, as with `fixtures.ts`, and the packaging test keeps it out of
 * `dist`. A change to the error contract then fails every test that relies on
 * the old shape instead of leaving a copy behind to pass.
 */
export function serpAxiError(kind: SerpAxiErrorKind, pattern: RegExp) {
  return (error: unknown) => {
    assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
    assert.equal(error.kind, kind);
    assert.match(error.message, pattern);
    return true;
  };
}

export function usageError(pattern: RegExp) {
  return serpAxiError("usage", pattern);
}

export function runtimeError(pattern: RegExp) {
  return serpAxiError("runtime", pattern);
}
