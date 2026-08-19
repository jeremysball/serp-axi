import { test } from "node:test";
import assert from "node:assert/strict";
import { runUpdate } from "./update.ts";
import { SerpAxiError } from "../errors.ts";

test("runUpdate reports a local install with the upgrade path, no registry call", () => {
  const output = runUpdate([]);
  assert.equal(output.status, "no live version check; run the upgrade command below");
  assert.equal(output.upgrade, "npm install -g serp-axi@latest");
});

test("runUpdate rejects an unknown flag with a usage error", () => {
  assert.throws(
    () => runUpdate(["--bogus"]),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
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
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /unexpected argument "extra"/);
      return true;
    },
  );
});
