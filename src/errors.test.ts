import { test } from "node:test";
import assert from "node:assert/strict";
import { SerperAxiError, exitCodeForError } from "./errors.ts";

test("SerperAxiError carries message, kind, and help", () => {
  const error = new SerperAxiError("bad input", "usage", "fix it like this");
  assert.equal(error.message, "bad input");
  assert.equal(error.kind, "usage");
  assert.equal(error.help, "fix it like this");
  assert.equal(error.name, "SerperAxiError");
});

test("exitCodeForError returns 2 for a usage error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "usage", "h")), 2);
});

test("exitCodeForError returns 1 for a runtime error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "runtime", "h")), 1);
});

test("exitCodeForError returns 1 for a non-SerperAxiError", () => {
  assert.equal(exitCodeForError(new Error("boom")), 1);
});
