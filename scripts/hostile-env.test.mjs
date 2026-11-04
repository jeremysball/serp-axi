import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO = fileURLToPath(new URL("../", import.meta.url));
const SCRIPT = path.join(REPO, "scripts", "hostile-env.mjs");
const CONFIG = pathToFileURL(path.join(REPO, "src", "config.ts")).href;
const LIVE = pathToFileURL(path.join(REPO, "src", "live.ts")).href;

function probe(source) {
  const dir = mkdtempSync(path.join(tmpdir(), "serp-axi-hostile-probe-"));
  const file = path.join(dir, "probe.test.mjs");
  writeFileSync(file, source);
  return { dir, file };
}

function run(args, env) {
  const childEnv = { ...env };
  // The outer `node --test` sets this; a child runner that inherits it skips its files.
  delete childEnv.NODE_TEST_CONTEXT;
  return spawnSync(process.execPath, args, { cwd: REPO, env: childEnv, encoding: "utf8", timeout: 60_000 });
}

test("the gated run gives the child no config file from the parent's HOME", () => {
  const { dir, file } = probe(`
import test from "node:test";
import assert from "node:assert/strict";
import { loadStoredConfig } from ${JSON.stringify(CONFIG)};
test("config is not inherited", () => {
  assert.equal(loadStoredConfig(process.env.HOME ?? "", process.env).maxResponseBytes, undefined);
});
`);
  const home = mkdtempSync(path.join(tmpdir(), "serp-axi-hostile-home-"));
  const configDir = path.join(home, "serp-axi");
  mkdirSync(configDir, { recursive: true });
  writeFileSync(path.join(configDir, "config.json"), JSON.stringify({ maxResponseBytes: 1000 }));
  const env = { ...process.env, HOME: home, XDG_CONFIG_HOME: home };
  try {
    // Positive control: without the gate the probe reads the parent's config and fails.
    const direct = run(["--test", file], env);
    assert.notEqual(direct.status, 0, `the probe must see the parent's config without the gate\n${direct.stdout}${direct.stderr}`);

    const gated = run([SCRIPT, "--", file], env);
    assert.equal(gated.status, 0, `the gated run must hide the parent's config\n${gated.stdout}${gated.stderr}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(home, { recursive: true, force: true });
  }
});

test("the hostile gate and the test helper share one prefix list", () => {
  for (const file of ["scripts/hostile-env.mjs", "src/searxng.test.ts"]) {
    const source = readFileSync(path.join(REPO, file), "utf8");
    assert.match(source, /env-prefixes\.mjs/, `${file} imports the shared prefix list`);
    assert.doesNotMatch(source, /\[\s*"SERP_AXI_",\s*"SERPER_"/, `${file} does not keep its own copy of the list`);
  }
});

test("a live opt-in exported in the parent shell is poisoned in the gated run", () => {
  const { dir, file } = probe(`
import test from "node:test";
import assert from "node:assert/strict";
import { liveSkip } from ${JSON.stringify(LIVE)};
test("live opt-in is not inherited", () => {
  assert.equal(liveSkip("SERP_AXI_LIVE_SERPER", process.env.SERPER_API_KEY), true);
});
`);
  const env = { ...process.env, SERP_AXI_LIVE_SERPER: "1", SERPER_API_KEY: "test-only" };
  try {
    // Positive control: the probe runs live without the gate.
    const direct = run(["--test", file], env);
    assert.notEqual(direct.status, 0, `the probe must run live without the gate\n${direct.stdout}${direct.stderr}`);

    const gated = run([SCRIPT, "--", file], env);
    assert.equal(gated.status, 0, `the gated run must skip the live test\n${gated.stdout}${gated.stderr}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the poisoned run selects the test files that can reach the shell, directly or through an import, and no others", () => {
  // A throwaway tree, so the answer does not move when a real test file changes.
  const root = mkdtempSync(path.join(tmpdir(), "serp-axi-hostile-tree-"));
  try {
    mkdirSync(path.join(root, "scripts"));
    mkdirSync(path.join(root, "src"));
    for (const name of ["hostile-env.mjs", "env-prefixes.mjs"]) {
      copyFileSync(path.join(REPO, "scripts", name), path.join(root, "scripts", name));
    }
    const write = (name, body) => writeFileSync(path.join(root, "src", name), body);
    write("reader.ts", "export const key = process.env.SERP_AXI_PROBE_KEY;\n");
    write("middle.ts", 'import { key } from "./reader.ts";\nexport const again = key;\n');
    write("direct.test.ts", 'import test from "node:test";\ntest("names the shell", () => { void process.env; });\n');
    write(
      "transitive.test.ts",
      'import test from "node:test";\nimport { again } from "./middle.ts";\ntest("reaches the shell through middle.ts", () => { void again; });\n',
    );
    write("unrelated.test.ts", 'import test from "node:test";\ntest("cannot see the shell", () => {});\n');

    const result = run([path.join(root, "scripts", "hostile-env.mjs")], process.env);
    assert.equal(result.status, 0, `the gated run over the throwaway tree failed\n${result.stdout}${result.stderr}`);
    const line = result.stderr.split("\n").find((l) => l.includes("shell-sensitive test files:"));
    assert.ok(line, `the script did not report the files it selected\n${result.stderr}`);
    const selected = line.split("shell-sensitive test files:")[1].trim().split(" ").sort();
    assert.deepEqual(selected, ["src/direct.test.ts", "src/transitive.test.ts"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
