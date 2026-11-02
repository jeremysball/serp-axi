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

test("encodeOutput quotes a title starting with # so it cannot decode as a comment", () => {
  const text = encodeOutput({
    results: [{ position: 1, title: "#1 Rust runtimes" }],
  });
  assert.match(text, /1,"#1 Rust runtimes"/);
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

test("truncate never ends a cut in half of a surrogate pair", () => {
  const grin = "\u{1F600}";
  const text = `ab${grin}cd`;

  // Positive trigger: a cut on either side of the pair keeps or drops all of it.
  assert.equal(truncate(text, 4).text, `ab${grin}`);
  assert.equal(truncate(text, 2).text, "ab");

  // A cut between the two halves backs up one unit, so the text is one shorter than the limit.
  const split = truncate(text, 3);
  assert.equal(split.text, "ab");
  assert.equal(split.truncated, true);
  assert.equal(split.totalChars, 6);
  assert.doesNotMatch(split.text, /[\ud800-\udbff]$/);

  // A pair that is the whole first character leaves nothing at a limit of 1.
  assert.equal(truncate(`${grin}hello`, 1).text, "");
  assert.equal(truncate(`${grin}hello`, 2).text, grin);
});

test("truncate leaves a lone high surrogate that is already in the text alone", () => {
  // Only a cut that splits a pair backs up; a stray surrogate the page held is its own.
  assert.equal(truncate("ab\ud83dcd", 3).text, "ab\ud83d");
});
