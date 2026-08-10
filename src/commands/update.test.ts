import { test } from "node:test";
import assert from "node:assert/strict";
import { runUpdate } from "./update.ts";

test("runUpdate reports a local install with the upgrade path, no registry call", () => {
  const output = runUpdate();
  assert.equal(output.status, "local install; no registry to check");
  assert.equal(output.upgrade, "git pull && npm run build && npm install -g .");
});
