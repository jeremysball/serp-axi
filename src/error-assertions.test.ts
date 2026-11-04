import test from "node:test";
import assert from "node:assert/strict";
import { runtimeError, serpAxiError, usageError } from "./error-assertions.ts";
import { SerpAxiError, type SerpAxiErrorKind } from "./errors.ts";

function make(message: string, kind: SerpAxiErrorKind): SerpAxiError {
  return new SerpAxiError(message, kind, "a help line");
}

// The helper is the one place that decides whether an error "matches", so it is
// tested on both sides: the error it must accept, then each way it must refuse.

test("serpAxiError accepts a SerpAxiError of the named kind whose message matches", () => {
  const error = make("the cap is too small", "usage");
  assert.equal(serpAxiError("usage", /too small/)(error), true);
  assert.equal(usageError(/too small/)(error), true);
  assert.equal(runtimeError(/too small/)(make("the cap is too small", "runtime")), true);
});

test("serpAxiError refuses an error of the other kind", () => {
  // `actual` and `expected` are the kind found and the kind asked for. The message of a
  // strict-equal failure names both kinds, so a regex on it could not tell them apart.
  assert.throws(() => usageError(/too small/)(make("the cap is too small", "runtime")), {
    name: "AssertionError",
    actual: "runtime",
    expected: "usage",
  });
  assert.throws(() => runtimeError(/too small/)(make("the cap is too small", "usage")), {
    name: "AssertionError",
    actual: "usage",
    expected: "runtime",
  });
});

test("serpAxiError refuses a message the pattern does not match", () => {
  assert.throws(() => usageError(/too large/)(make("the cap is too small", "usage")));
});

test("serpAxiError refuses a value that is not a SerpAxiError", () => {
  assert.throws(() => usageError(/too small/)(new Error("the cap is too small")), /expected a SerpAxiError/);
  assert.throws(() => usageError(/too small/)("the cap is too small"), /expected a SerpAxiError/);
});
