import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
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
  return createAppOptions("file:///home/user/.local/bin/serp-axi", { homeDir: "/home/user" });
}

test("standard checks and prepublish include the named mutation gate", () => {
  const { scripts } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.match(scripts.check, /(?:^|&&)\s*npm run test:mutations\s*(?:&&|$)/);
  assert.match(scripts.prepublishOnly, /^npm run check\s*&&/);
});

test("live providers require explicit opt-in as well as credentials", () => {
  for (const [file, optIn] of [
    ["serper.live.test.ts", "SERP_AXI_LIVE_SERPER"],
    ["brightdata.live.test.ts", "SERP_AXI_LIVE_BRIGHTDATA"],
    ["brightdata.scrape.live.test.ts", "SERP_AXI_LIVE_BRIGHTDATA"],
    ["kagi.live.test.ts", "SERP_AXI_LIVE_KAGI"],
  ]) {
    const source = `globalThis.fetch = async () => { throw new Error('LIVE_FETCH_ATTEMPT'); }; await import(${JSON.stringify(new URL(file, import.meta.url).href)});`;
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      SERPER_API_KEY: "test-only", BRIGHTDATA_API_KEY: "test-only", KAGI_SESSION_TOKEN: "test-only",
      SERP_AXI_LIVE_SERPER: "0", SERP_AXI_LIVE_BRIGHTDATA: "0", SERP_AXI_LIVE_KAGI: "0",
    };
    delete env.NODE_TEST_CONTEXT;
    const args = ["--test-reporter=tap", "--input-type=module", "--eval", source];
    const enabled = spawnSync(process.execPath, args, {
      env: { ...env, [optIn]: "1" }, encoding: "utf8", timeout: 10_000,
    });
    assert.equal(enabled.error, undefined, file);
    assert.notEqual(enabled.status, 0, `${file}: positive control must attempt fetch`);
    assert.match(enabled.stdout + enabled.stderr, /LIVE_FETCH_ATTEMPT/, file);
    const disabled = spawnSync(process.execPath, args, {
      env, encoding: "utf8", timeout: 10_000,
    });
    assert.equal(disabled.error, undefined, file);
    assert.equal(disabled.status, 0, `${file}: credentials alone must not activate live tests\n${disabled.stdout}${disabled.stderr}`);
    assert.match(disabled.stdout, /# SKIP/, file);
  }
});

test("no-args home view includes bin, description, and every command", async () => {
  const stdout = fakeStdout();
  const code = await runCli([], { ...testOptions(), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.bin, "~/.local/bin/serp-axi");
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
  assert.equal(decoded.status, "no live version check; run the upgrade command below");
});

test("search --help prints the command's help without making a network call", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["search", "--help"], { ...testOptions(), stdout });
  assert.equal(code, 0);
  assert.match(stdout.output, /serp-axi search/);
});

test("scrape --help documents profile bundles above config in ladder precedence", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["scrape", "--help"], { ...testOptions(), stdout });
  assert.equal(code, 0);
  assert.match(stdout.output, /flag > env > profile > config > default/);
});

test("scrape --help marks unimplemented ladder state controls as reserved", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["scrape", "--help"], { ...testOptions(), stdout });
  assert.equal(code, 0);
  for (const flag of ["tab-state", "cache-state", "fingerprint-state"]) {
    assert.match(stdout.output, new RegExp(`--${flag}[^\\n]*reserved; not yet applied`));
  }
});
