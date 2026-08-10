import { test } from "node:test";
import assert from "node:assert/strict";
import { decode } from "@toon-format/toon";
import { runCli } from "./cli.ts";
import { createAppOptions } from "./app.ts";

function fakeStdout() {
  let buffer = "";
  return {
    write: (chunk: string) => {
      buffer += chunk;
      return true;
    },
    get output() {
      return buffer;
    },
  };
}

function testOptions() {
  return createAppOptions("file:///home/user/.local/bin/serper-axi", { homeDir: "/home/user" });
}

test("no-args home view includes bin, description, and every command", async () => {
  const stdout = fakeStdout();
  const code = await runCli([], { ...testOptions(), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.bin, "~/.local/bin/serper-axi");
  assert.deepEqual(decoded.commands, ["search", "scrape", "update"]);
});

test("unknown command exits 2 with a structured error", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["bogus"], { ...testOptions(), stdout });
  assert.equal(code, 2);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.match(decoded.error as string, /unknown command/);
});

test("update command dispatches end to end through runCli", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["update"], { ...testOptions(), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.status, "local install; no registry to check");
});

test("search --help prints the command's help without making a network call", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["search", "--help"], { ...testOptions(), stdout });
  assert.equal(code, 0);
  assert.match(stdout.output, /serper-axi search/);
});
