// Runs the unit tests with every setting the CLI reads from the shell set to a
// value no test wants, so a test that reads the developer's environment fails
// here instead of only on a machine that happens to export something.
//
// Belief: no test depends on the shell it runs in. A test hands the code its own
// env and config, or it clears what it needs. Passing on a clean shell proves
// nothing about that, because a clean shell has none of these variables set.
//
// The names come from the source, not from a list kept here: every
// SERP_AXI_*, SERPER_*, BRIGHTDATA_* and KAGI_* token in a non-test module under
// src/. A setting added tomorrow is poisoned tomorrow. A setting under a new
// prefix is not found; add the prefix below when a provider brings one.
//
// The poison is an absolute path that does not exist. A path variable then fails
// loudly instead of creating a file in the working directory, a number or URL
// variable fails to parse, and a key or token is a value that is wrong but present.
//
// usage: node scripts/hostile-env.mjs [-- <node --test arguments>]
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PREFIXES = ["SERP_AXI_", "SERPER_", "BRIGHTDATA_", "KAGI_"];
const POISON = "/nonexistent/serp-axi-hostile-env";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.join(root, "src");

function* sourceFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* sourceFiles(full);
    else if (entry.name.endsWith(".ts") && !entry.name.endsWith(".test.ts")) yield full;
  }
}

const tokenPattern = new RegExp(`\\b(?:${PREFIXES.join("|")})[A-Z0-9_]+\\b`, "g");
const names = new Set();
for (const file of sourceFiles(src)) {
  for (const match of readFileSync(file, "utf8").matchAll(tokenPattern)) {
    // A prefix on its own ("SERP_AXI_") is a comment about the family, not a variable.
    if (!match[0].endsWith("_")) names.add(match[0]);
  }
}

if (names.size === 0) {
  console.error(`hostile-env: found no ${PREFIXES.join("/")} names under src/, so there is nothing to poison.`);
  console.error("The scan or the prefixes are wrong; refusing to report a clean run.");
  process.exit(2);
}

const env = { ...process.env };
for (const name of names) env[name] = POISON;

const extra = process.argv.slice(2).filter((arg) => arg !== "--");
const args = ["--test", ...(extra.length > 0 ? extra : ["src/**/*.test.ts"])];

console.error(`hostile-env: ${names.size} settings poisoned: ${[...names].sort().join(" ")}`);
const result = spawnSync(process.execPath, args, { cwd: root, env, stdio: "inherit" });

if (result.status !== 0) {
  console.error("\nhostile-env: a test failed with the shell's settings poisoned.");
  console.error("Belief broken: no test depends on the shell it runs in. The failing test read a");
  console.error("setting from process.env, or the machine's config file, that it did not set itself.");
  console.error("Hand it its own env and config ({} for none), or clear the variable it needs.");
}
process.exit(result.status ?? 1);
