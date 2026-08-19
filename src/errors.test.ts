import { test } from "node:test";
import assert from "node:assert/strict";
import { SerpAxiError, exitCodeForError } from "./errors.ts";

test("SerpAxiError carries message, kind, and help", () => {
  const error = new SerpAxiError("bad input", "usage", "fix it like this");
  assert.equal(error.message, "bad input");
  assert.equal(error.kind, "usage");
  assert.equal(error.help, "fix it like this");
  assert.equal(error.name, "SerpAxiError");
});

test("exitCodeForError returns 2 for a usage error", () => {
  assert.equal(exitCodeForError(new SerpAxiError("m", "usage", "h")), 2);
});

test("exitCodeForError returns 1 for a runtime error", () => {
  assert.equal(exitCodeForError(new SerpAxiError("m", "runtime", "h")), 1);
});

test("exitCodeForError returns 1 for a non-SerpAxiError", () => {
  assert.equal(exitCodeForError(new Error("boom")), 1);
});
