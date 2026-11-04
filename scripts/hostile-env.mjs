// Runs the shell-sensitive unit tests with every setting the CLI reads from the
// shell set to a value no test wants, so a test that reads the developer's
// environment fails here instead of only on a machine that happens to export
// something.
//
// Belief: no test depends on the shell it runs in. A test hands the code its own
// env and config, or it clears what it needs. Passing on a clean shell proves
// nothing about that, because a clean shell has none of these variables set.
//
// The names come from the source, not from a list kept here: every
// SERP_AXI_*, SERPER_*, BRIGHTDATA_* and KAGI_* token in a module under src/ that
// ships, plus the *.live.test.ts opt-ins, which by design exist only in tests. A
// setting added tomorrow is poisoned tomorrow. A setting under a new prefix is not
// found; add the prefix to scripts/env-prefixes.mjs when a provider brings one.
//
// The run is narrowed to the test files that can see the shell: a file that names
// process.env itself, or that imports (directly or through another module) a
// module that does. The full suite already ran clean in `npm test`; running it
// again with the poison on adds nothing for a file that cannot read the
// environment, and re-running the real-socket and ast-grep suites costs seconds
// for no extra coverage.
//
// The child also gets an empty HOME and XDG_CONFIG_HOME, so a test that omits its
// config argument cannot read the developer's real ~/.config/serp-axi/config.json.
//
// The poison is an absolute path that does not exist. A path variable then fails
// loudly instead of creating a file in the working directory, a number or URL
// variable fails to parse, and a key or token is a value that is wrong but present.
//
// usage: node scripts/hostile-env.mjs [-- <node --test arguments>]
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PREFIXES } from "./env-prefixes.mjs";

const POISON = "/nonexistent/serp-axi-hostile-env";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.join(root, "src");

function* sourceFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* sourceFiles(full);
    else if (entry.name.endsWith(".ts")) yield full;
  }
}

const files = [...sourceFiles(src)];
const sources = new Map(files.map((file) => [file, readFileSync(file, "utf8")]));

const tokenPattern = new RegExp(`\\b(?:${PREFIXES.join("|")})[A-Z0-9_]+\\b`, "g");
const names = new Set();
for (const [file, source] of sources) {
  const isTest = file.endsWith(".test.ts");
  if (isTest && !file.endsWith(".live.test.ts")) continue;
  for (const match of source.matchAll(tokenPattern)) {
    // A prefix on its own ("SERP_AXI_") is a comment about the family, not a variable.
    if (!match[0].endsWith("_")) names.add(match[0]);
  }
}

if (names.size === 0) {
  console.error(`hostile-env: found no ${PREFIXES.join("/")} names under src/, so there is nothing to poison.`);
  console.error("The scan or the prefixes are wrong; refusing to report a clean run.");
  process.exit(2);
}

const envRead = /\bprocess\.env\b/;
const envReaders = new Set(
  [...sources].filter(([file, source]) => !file.endsWith(".test.ts") && envRead.test(source)).map(([file]) => file),
);

function importsOf(file) {
  const deps = [];
  for (const match of (sources.get(file) ?? "").matchAll(/(?:from|import)\s*\(?\s*["'](\.[^"']+)["']/g)) {
    const target = path.resolve(path.dirname(file), match[1]);
    if (sources.has(target)) deps.push(target);
    else if (sources.has(`${target}.ts`)) deps.push(`${target}.ts`);
  }
  return deps;
}

function reachesEnvReader(file, seen = new Set()) {
  if (seen.has(file)) return false;
  seen.add(file);
  if (envReaders.has(file)) return true;
  return importsOf(file).some((dep) => reachesEnvReader(dep, seen));
}

const sensitive = files
  .filter((file) => file.endsWith(".test.ts") && (envRead.test(sources.get(file)) || reachesEnvReader(file)))
  .map((file) => path.relative(root, file))
  .sort();

if (sensitive.length === 0) {
  console.error("hostile-env: found no test file that can read the shell, so there is nothing to run poisoned.");
  console.error("The scan or the import graph is wrong; refusing to report a clean run.");
  process.exit(2);
}

const emptyHome = mkdtempSync(path.join(os.tmpdir(), "serp-axi-hostile-home-"));
const env = { ...process.env, HOME: emptyHome, XDG_CONFIG_HOME: emptyHome };
for (const name of names) env[name] = POISON;

const extra = process.argv.slice(2).filter((arg) => arg !== "--");
const args = ["--test", ...(extra.length > 0 ? extra : sensitive)];

console.error(`hostile-env: ${names.size} settings poisoned: ${[...names].sort().join(" ")}`);
console.error(`hostile-env: ${sensitive.length} shell-sensitive test files: ${sensitive.join(" ")}`);
let result;
try {
  result = spawnSync(process.execPath, args, { cwd: root, env, stdio: "inherit" });
} finally {
  rmSync(emptyHome, { recursive: true, force: true });
}

if (result.status !== 0) {
  console.error("\nhostile-env: a test failed with the shell's settings poisoned.");
  console.error("Belief broken: no test depends on the shell it runs in. The failing test read a");
  console.error("setting from process.env, or the machine's config file, that it did not set itself.");
  console.error("Hand it its own env and config ({} for none), or clear the variable it needs.");
}
process.exit(result.status ?? 1);
