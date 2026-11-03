import test, { after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Tests for the ast-grep rules in `.ast-grep/rules/`, and for the packaging rule
 * that sits beside them. A guard that cannot fire is decoration, so every rule is
 * run here against code it must catch, code it must leave alone, and the bypass.
 *
 * The scans run the command from package.json's `guard` script, not a copy of it,
 * so a change to the script (a dropped `--error=unused-suppression`) changes what
 * these tests see. The binary is the one `.mise.toml` pins; a missing one fails
 * the run instead of skipping it.
 */

const REPO = fileURLToPath(new URL("../", import.meta.url));

interface Hit {
  ruleId: string;
  severity: string;
  file: string;
  /** 1-based, as an editor shows it. ast-grep reports 0-based. */
  line: number;
}

function guardCommand(): [string, string[]] {
  const pkg = JSON.parse(readFileSync(path.join(REPO, "package.json"), "utf8")) as { scripts: Record<string, string> };
  const [bin, subcommand, ...args] = pkg.scripts.guard.split(/\s+/);
  assert.equal(bin, "ast-grep", "package.json `guard` runs ast-grep");
  assert.equal(subcommand, "scan", "package.json `guard` is an `ast-grep scan`");
  return [bin, [subcommand, ...args]];
}

function runGuard(cwd: string): { status: number | null; hits: Hit[] } {
  const [bin, args] = guardCommand();
  const result = spawnSync(bin, [...args, "--json=stream"], { cwd, encoding: "utf8" });
  if (result.error) {
    throw new Error(`could not run ${bin}: ${result.error.message}. Run \`mise install\`; .mise.toml pins ast-grep.`);
  }
  assert.ok(result.status === 0 || result.status === 1, `ast-grep failed to run (status ${result.status}): ${result.stderr}`);
  const hits = result.stdout
    .split("\n")
    .filter((line) => line.startsWith("{"))
    .map((line) => {
      const hit = JSON.parse(line) as { ruleId: string; severity: string; file: string; range: { start: { line: number } } };
      return { ruleId: hit.ruleId, severity: hit.severity, file: hit.file, line: hit.range.start.line + 1 };
    });
  return { status: result.status, hits };
}

const scratch: string[] = [];
after(() => {
  for (const dir of scratch) rmSync(dir, { recursive: true, force: true });
});

/** A throwaway project with the real rules and the given source files. */
function scaffold(files: Record<string, string>): string {
  const dir = mkdtempSync(path.join(os.tmpdir(), "serp-axi-guards-"));
  scratch.push(dir);
  cpSync(path.join(REPO, "sgconfig.yml"), path.join(dir, "sgconfig.yml"));
  cpSync(path.join(REPO, ".ast-grep"), path.join(dir, ".ast-grep"), { recursive: true });
  for (const [name, source] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    writeFileSync(path.join(dir, name), source);
  }
  return dir;
}

// Shapes each rule must catch. [name, rule that must fire, 1-based line, source]
const FIRES: Array<[string, string, number, string]> = [
  ["a bare .text()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.text();\n}\n"],
  ["a bare .json()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.json();\n}\n"],
  ["a bare .arrayBuffer()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.arrayBuffer();\n}\n"],
  ["a bare .blob()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.blob();\n}\n"],
  ["a bare .formData()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.formData();\n}\n"],
  ["a bare .bytes()", "unbounded-response-read", 2, "export async function f(r: Response) {\n  return await r.bytes();\n}\n"],
  ["an optional-chained read", "unbounded-response-read", 2, "export async function f(r?: Response) {\n  return await r?.text();\n}\n"],
  ["a read on a fetch result", "unbounded-response-read", 1, "export const f = async (u: string) => (await fetch(u)).json();\n"],
  ["a read inside a then callback", "unbounded-response-read", 1, "export const f = (u: string) => fetch(u).then((r) => r.text());\n"],
  ["a read swallowed by .catch", "unbounded-response-read", 2, 'export async function f(r: Response) {\n  return await r.text().catch(() => "");\n}\n'],
  ["a for-await loop over the body", "response-body-stream-access", 2, "export async function f(r: Response) {\n  for await (const chunk of r.body!) void chunk;\n}\n"],
  ["getReader on the body", "response-body-stream-access", 1, "export const f = (r: Response) => r.body?.getReader();\n"],
  ["the body passed to another function", "response-body-stream-access", 2, "declare function consume(s: unknown): void;\nexport const f = (r: Response) => consume(r.body);\n"],
  ["an optional-chained body", "response-body-stream-access", 1, "export const f = (r?: Response) => r?.body;\n"],
  ["a static import of node:https", "raw-transport-import", 1, 'import https from "node:https";\nexport default https;\n'],
  ["a static import of bare http", "raw-transport-import", 1, 'import http from "http";\nexport default http;\n'],
  ["a static import of node:http2", "raw-transport-import", 1, 'import { connect } from "node:http2";\nexport default connect;\n'],
  ["a static import of undici", "raw-transport-import", 1, 'import { request } from "undici";\nexport default request;\n'],
  ["a static import from an undici subpath", "raw-transport-import", 1, 'import { Agent } from "undici/lib/dispatcher";\nexport default Agent;\n'],
  ["a dynamic import of node:https", "raw-transport-import", 1, 'export const load = () => import("node:https");\n'],
  ["a require of node:http", "raw-transport-import", 2, 'declare function require(name: string): unknown;\nexport const http = require("node:http");\n'],
];

// Code that looks close to a violation and is not one. [name, path, source]
const SILENT: Array<[string, string, string]> = [
  [
    "src/body.ts, the one module that reads a body",
    "src/body.ts",
    "export async function read(response: Response) {\n  const reader = response.body!.getReader();\n  void reader;\n  return await response.text();\n}\n",
  ],
  ["a test file", "src/x.test.ts", "export const f = async (r: Response) => [await r.text(), r.body];\n"],
  ["a test file in a subdirectory", "src/commands/y.test.ts", "export const f = async (r: Response) => r.json();\n"],
  ["a test file that imports node:http", "src/z.test.ts", 'import http from "node:http";\nexport default http;\n'],
  ["node:net, which scrape.ts needs for isIP", "src/net.ts", 'import { isIP } from "node:net";\nexport const f = isIP;\n'],
  ["a property named text that is not called", "src/prop.ts", "export const f = (r: { text: string }) => r.text;\n"],
  ["JSON.parse and a constructed Response", "src/parse.ts", "export const f = (s: string) => [JSON.parse(s), new Response(s)];\n"],
  ["a request body in an options object", "src/req.ts", 'export const init = { method: "POST", body: JSON.stringify({}) };\n'],
  ["a transport name inside a string", "src/word.ts", 'export const note = "import http from node:https";\n'],
  ["an import of a module whose name starts with http", "src/lookalike.ts", 'import x from "http-status-codes";\nexport default x;\n'],
];

// The bypass. [name, path, source, rule ids expected to still fire, whether unused-suppression fires]
const BYPASS: Array<[string, string, string, string[], boolean]> = [
  [
    "a directive on the line above hides the hit",
    "src/bypass-above.ts",
    "declare const o: { text(): string };\n// ast-grep-ignore: unbounded-response-read (o is a plain object, not a Response)\nexport const a = o.text();\n",
    [],
    false,
  ],
  [
    "a directive at the end of the line hides the hit",
    "src/bypass-trailing.ts",
    "declare const o: { text(): string };\nexport const a = o.text(); // ast-grep-ignore: unbounded-response-read (plain object)\n",
    [],
    false,
  ],
  [
    "a directive for a different rule does not hide the hit",
    "src/bypass-wrong-id.ts",
    "declare const r: Response;\n// ast-grep-ignore: response-body-stream-access (wrong rule for this line)\nexport const a = r.text();\n",
    ["unbounded-response-read"],
    true,
  ],
  [
    "a directive with nothing under it is reported as unused",
    "src/bypass-stale.ts",
    "// ast-grep-ignore: unbounded-response-read (nothing here reads a response)\nexport const a = 1 + 1;\n",
    [],
    true,
  ],
];

const project = (() => {
  let cached: { dir: string; hits: Hit[] } | undefined;
  return () => {
    if (cached === undefined) {
      const files: Record<string, string> = {};
      FIRES.forEach(([, , , source], index) => (files[`src/fires-${index}.ts`] = source));
      for (const [, file, source] of SILENT) files[file] = source;
      for (const [, file, source] of BYPASS) files[file] = source;
      const dir = scaffold(files);
      cached = { dir, hits: runGuard(dir).hits };
    }
    return cached;
  };
})();

const hitsIn = (file: string): Hit[] => project().hits.filter((hit) => hit.file === file);

FIRES.forEach(([name, rule, line], index) => {
  test(`${rule} fires on ${name}`, () => {
    const hits = hitsIn(`src/fires-${index}.ts`);
    assert.deepEqual(
      hits.map((hit) => [hit.ruleId, hit.line, hit.severity]),
      [[rule, line, "error"]],
      "exactly one hit, from the expected rule, at the expected line, at error severity",
    );
  });
});

for (const [name, file] of SILENT) {
  test(`the rules stay silent on ${name}`, () => {
    assert.deepEqual(hitsIn(file), []);
  });
}

for (const [name, file, , stillFires, unused] of BYPASS) {
  test(`bypass: ${name}`, () => {
    const hits = hitsIn(file);
    assert.deepEqual(
      hits.filter((hit) => hit.ruleId !== "unused-suppression").map((hit) => hit.ruleId),
      stillFires,
    );
    const stale = hits.filter((hit) => hit.ruleId === "unused-suppression");
    assert.equal(stale.length > 0, unused, "an unused directive is reported");
    for (const hit of stale) assert.equal(hit.severity, "error", "an unused directive fails the build, not just notes it");
  });
}

test("every rule file has a case above that makes it fire", () => {
  const rulesDir = path.join(REPO, ".ast-grep", "rules");
  const ids = readdirSync(rulesDir)
    .filter((name) => name.endsWith(".yml"))
    .map((name) => /^id: (\S+)/m.exec(readFileSync(path.join(rulesDir, name), "utf8"))?.[1]);
  assert.ok(ids.length >= 3, "the rules directory is not empty");
  const covered = new Set(FIRES.map(([, rule]) => rule));
  for (const id of ids) {
    assert.ok(id !== undefined, "every rule file starts its rule with an `id:` line");
    assert.ok(covered.has(id), `rule ${id} has no FIRES case, so nothing proves it can fire`);
  }
});

test("a bypass names its reason, so it states the belief it overrides", () => {
  const bypassLine = /ast-grep-ignore: [a-z-]+(, [a-z-]+)* \(\S.*\)\s*$/;
  const srcDir = path.join(REPO, "src");
  const sources = readdirSync(srcDir, { recursive: true, encoding: "utf8" }).filter((name) => name.endsWith(".ts"));
  let seen = 0;
  for (const name of sources) {
    // This file quotes bypasses on purpose, some of them without a reason.
    if (name === "guards.test.ts") continue;
    for (const line of readFileSync(path.join(srcDir, name), "utf8").split("\n")) {
      if (!line.includes("ast-grep-ignore")) continue;
      seen += 1;
      assert.match(line, bypassLine, `${name}: a bypass needs "<rule-id> (<reason>)"; got: ${line.trim()}`);
    }
  }
  assert.ok(seen >= 1, "src/brightdata.ts carries the envelope bypass; if it is gone, drop this floor");
});

test("the real src tree passes every guard", () => {
  const { status, hits } = runGuard(REPO);
  assert.deepEqual(hits, [], "no hits in the real tree");
  assert.equal(status, 0);
});

// Packaging. `files` ships dist/ minus test files, so a helper that only tests
// import would ship unless it is excluded by name. live.ts did before this rule.
test("a module that only tests import is left out of the package", () => {
  const srcDir = path.join(REPO, "src");
  const all = readdirSync(srcDir, { recursive: true, encoding: "utf8" })
    .filter((name) => name.endsWith(".ts"))
    .map((name) => name.split(path.sep).join("/"));
  const importers = new Map<string, string[]>();
  for (const importer of all) {
    const source = readFileSync(path.join(srcDir, importer), "utf8");
    for (const match of source.matchAll(/(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+\.ts)["']/g)) {
      const target = path.posix.normalize(path.posix.join(path.posix.dirname(importer), match[1]));
      importers.set(target, [...(importers.get(target) ?? []), importer]);
    }
  }
  const testOnly = all.filter((name) => {
    if (name.endsWith(".test.ts")) return false;
    const users = importers.get(name) ?? [];
    return users.length > 0 && users.every((user) => user.endsWith(".test.ts"));
  });
  assert.ok(testOnly.includes("live.ts") && testOnly.includes("fixtures.ts"), `the finder sees the known helpers; found ${testOnly.join(", ")}`);

  const pkg = JSON.parse(readFileSync(path.join(REPO, "package.json"), "utf8")) as { files: string[] };
  for (const name of testOnly) {
    const entry = `!dist/${name.replace(/\.ts$/, ".js")}`;
    assert.ok(pkg.files.includes(entry), `src/${name} is imported only by tests but package.json "files" does not exclude ${entry}`);
  }
});
