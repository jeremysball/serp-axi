import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeOutput, collapseHomeDirectory, truncate } from "./output.ts";

test("encodeOutput renders TOON with a trailing newline", () => {
  const text = encodeOutput({ count: 2 });
  assert.equal(text, "count: 2\n");
});

test("encodeOutput renders a tabular array", () => {
  const text = encodeOutput({
    results: [
      { position: 1, title: "a" },
      { position: 2, title: "b" },
    ],
  });
  assert.match(text, /results\[2\]\{position,title\}:/);
});

test("collapseHomeDirectory replaces a leading home path with ~", () => {
  assert.equal(collapseHomeDirectory("/home/user/.local/bin/serp-axi", "/home/user"), "~/.local/bin/serp-axi");
});

test("collapseHomeDirectory leaves a non-home path untouched", () => {
  assert.equal(collapseHomeDirectory("/usr/local/bin/serp-axi", "/home/user"), "/usr/local/bin/serp-axi");
});

test("truncate passes short text through unchanged", () => {
  const result = truncate("hello", 10);
  assert.deepEqual(result, { text: "hello", truncated: false, totalChars: 5 });
});

test("truncate cuts long text and reports the total length", () => {
  const result = truncate("hello world", 5);
  assert.equal(result.text, "hello");
  assert.equal(result.truncated, true);
  assert.equal(result.totalChars, 11);
});
