import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Beliefs the hook states in its own header: it runs the guards through
// package.json's `guard` script, so the hook and CI cannot enforce different
// rule sets; and a missing tsc skips the typecheck but not the guards.
//
// The hook runs in a throwaway project with no node_modules (so no tsc) and a
// stand-in `ast-grep` first on PATH. The stand-in prints its arguments, which
// shows what command the hook ran, and exits with the status the case needs.

const HOOK = fileURLToPath(new URL("../.githooks/pre-commit", import.meta.url));
const GUARD_COMMAND = "ast-grep scan --taken-from-package-json src";

function cleanEnv(extra = {}) {
  // Variables git sets inside a hook would point the throwaway repo at this one.
  const env = { ...process.env, ...extra };
  for (const name of Object.keys(env)) if (name.startsWith("GIT_")) delete env[name];
  return env;
}

function stagedProject(astGrepExit) {
  const dir = mkdtempSync(path.join(tmpdir(), "serp-axi-hook-probe-"));
  const bin = path.join(dir, "bin");
  const project = path.join(dir, "project");
  mkdirSync(bin);
  mkdirSync(path.join(project, "src"), { recursive: true });
  writeFileSync(path.join(bin, "ast-grep"), `#!/bin/sh\necho "STAND-IN $*"\nexit ${astGrepExit}\n`);
  chmodSync(path.join(bin, "ast-grep"), 0o755);
  writeFileSync(
    path.join(project, "package.json"),
    JSON.stringify({ name: "hook-probe", version: "1.0.0", private: true, scripts: { guard: GUARD_COMMAND } }),
  );
  writeFileSync(path.join(project, "src", "a.ts"), "export const a = 1;\n");
  for (const args of [["init", "-q"], ["add", "-A"]]) {
    const done = spawnSync("git", args, { cwd: project, env: cleanEnv(), encoding: "utf8" });
    assert.equal(done.status, 0, `git ${args.join(" ")} failed\n${done.stderr}`);
  }
  return { dir, project, bin };
}

function runHook({ project, bin }) {
  const env = cleanEnv({ PATH: `${bin}${path.delimiter}${process.env.PATH}` });
  const done = spawnSync("sh", [HOOK], { cwd: project, env, encoding: "utf8", timeout: 60_000 });
  return { status: done.status, output: `${done.stdout}${done.stderr}` };
}

test("a failing guard blocks the commit, run as package.json's guard script, with typescript absent", () => {
  const probe = stagedProject(1);
  try {
    const { status, output } = runHook(probe);
    assert.match(output, /typescript is not installed/, `the probe must have no tsc\n${output}`);
    assert.match(output, /STAND-IN scan --taken-from-package-json src/, `the hook did not run the package.json guard\n${output}`);
    assert.equal(status, 1, `a failing guard must block the commit\n${output}`);
  } finally {
    rmSync(probe.dir, { recursive: true, force: true });
  }
});

test("a passing guard lets the same commit through", () => {
  const probe = stagedProject(0);
  try {
    const { status, output } = runHook(probe);
    assert.match(output, /STAND-IN scan --taken-from-package-json src/, `the guard must have run\n${output}`);
    assert.equal(status, 0, `a passing guard must not block the commit\n${output}`);
  } finally {
    rmSync(probe.dir, { recursive: true, force: true });
  }
});
