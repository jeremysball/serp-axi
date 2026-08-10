import { test } from "node:test";
import assert from "node:assert/strict";
import { runUpdate } from "./update.ts";
import { SerperAxiError } from "../errors.ts";

test("runUpdate reports a local install with the upgrade path, no registry call", () => {
  const output = runUpdate([]);
  assert.equal(output.status, "local install; no registry to check");
  assert.equal(output.upgrade, "git pull && npm run build && npm install -g .");
});

test("runUpdate rejects an unknown flag with a usage error", () => {
  assert.throws(
    () => runUpdate(["--bogus"]),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /unknown flag --bogus/);
      return true;
    },
  );
});

test("runUpdate rejects an extra positional with a usage error", () => {
  assert.throws(
    () => runUpdate(["extra"]),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /unexpected argument "extra"/);
      return true;
    },
  );
});
