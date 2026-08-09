# serper-axi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `serper-axi`, an AXI-compliant CLI that runs Serper (Google Search API) search queries and page scrapes for agents, per
`.superpowers/specs/2026-08-09-serper-axi-design.md` (revision 3).

**Architecture:** A standalone TypeScript package (ESM, Node ≥26) with a hand-rolled CLI dispatcher (`src/cli.ts`), a direct HTTPS client
against Serper (`src/serper.ts`, no MCP/subprocess), and three commands (`search`, `scrape`, `update`) wired together in `src/app.ts` and
run from `src/bin/serper-axi.ts`. Every module is unit-tested with Node's built-in test runner (`node --test`) executing `.ts` files
directly via Node 26's native type stripping — no test-only compiler in the loop.

**Tech Stack:** TypeScript 7.0.2, Node.js ≥26 (pinned via `.mise.toml`), `@toon-format/toon` 2.3.1 (sole runtime dependency),
`@types/node` 26.2.0 (dev only), Node's built-in `node:test` module.

## Global Constraints

- Node pinned via `.mise.toml` to `26.5.1`; `package.json` `engines.node` is `>=26`.
- Sole runtime dependency: `@toon-format/toon`, pinned to exact version `2.3.1`. No `axi-sdk-js`, no other runtime dependency (spec
  revision 3).
- Never hardcode an absolute path (`/home/...`, a specific username/hostname) into source, scripts, or config.
- Every failure surfaces on **stdout** as a structured `error:`/`help:` TOON pair — never a stack trace, raw HTTP body, or dependency
  name. **stderr** carries diagnostics only, never data.
- Exit codes: `0` success (including a zero-result search and the no-op `update`), `1` runtime error, `2` usage error.
- No interactive prompts anywhere; every operation is completable from flags alone.
- Unknown flags and unknown positional arguments are rejected by name, exit code `2`, before any network call, listing that
  subcommand's valid flags inline.
- `SERPER_API_KEY` is checked before any network call in every command that needs it; it is never written to any file.
- Search defaults: `--region us --lang en --num 10`. `--num` must be an integer in `1..100`. Snippets in the default schema are
  truncated to 200 characters. `--fields` accepts only `date` and `sitelinks`.
- Scrape rejects non-`http`/`https` schemes and loopback/private-range hosts before any network call. Text is truncated to 1200
  characters by default; `--full` raises the ceiling to 50,000 characters.
- serper-axi never fabricates a search "total results" figure — the API doesn't return one.
- Commit messages: Conventional Commits (`type(scope): description`, imperative mood). Never a `Co-Authored-By` trailer.
- Search tool: `fd` for files, `rg` for text. Never `find`/`grep`.

---

## File Structure

```
serper-axi/
  package.json
  tsconfig.json
  .mise.toml
  .gitignore
  src/
    errors.ts             <- SerperAxiError, exitCodeForError
    errors.test.ts
    output.ts              <- encodeOutput, collapseHomeDirectory, truncate
    output.test.ts
    serper.ts               <- searchSerper(), scrapeSerper() — direct HTTPS client
    serper.test.ts           <- mocked-fetch tests
    serper.live.test.ts       <- live-API tests, skipped without SERPER_API_KEY
    cli.ts                     <- parseFlags(), runCli() dispatch/home/help
    cli.test.ts
    app.ts                      <- createAppOptions(): wires commands into RunCliOptions
    app.test.ts                  <- end-to-end dispatch through runCli
    commands/
      search.ts                   <- runSearch(), searchCommand
      search.test.ts
      scrape.ts                     <- runScrape(), scrapeCommand
      scrape.test.ts
      update.ts                      <- runUpdate(), updateCommand
      update.test.ts
    bin/
      serper-axi.ts                   <- entrypoint: calls runCli(), process.exit()
  SKILL.md                               <- hand-written discovery doc
  .taskferry.toml                          <- verification gate, added in Task 11
```

Test files are colocated next to the module they test (`foo.ts` / `foo.test.ts`), matching the pattern already used in this account's
`taskferry` repo. `node --test "src/**/*.test.ts"` discovers all of them recursively (verified: Node 26.5.1's test runner glob-expands
`**` and picks up nested directories).

---

### Task 1: Repo scaffold

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `.mise.toml`
- Create: `.gitignore`

**Interfaces:**
- Produces: the `npm run build`, `npm run typecheck`, `npm test`, and `npm run check` scripts every later task relies on.

- [ ] **Step 1: Write `package.json`**

```json
{
  "name": "serper-axi",
  "version": "0.1.0",
  "private": true,
  "description": "AXI-compliant CLI for Serper (Google Search API) search and page-scrape queries",
  "type": "module",
  "bin": {
    "serper-axi": "dist/bin/serper-axi.js"
  },
  "engines": {
    "node": ">=26"
  },
  "scripts": {
    "build": "tsc",
    "typecheck": "tsc --noEmit",
    "test": "node --test \"src/**/*.test.ts\"",
    "check": "npm run typecheck && npm test"
  },
  "dependencies": {
    "@toon-format/toon": "2.3.1"
  },
  "devDependencies": {
    "typescript": "7.0.2",
    "@types/node": "26.2.0"
  }
}
```

- [ ] **Step 2: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2023",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "lib": ["ES2023"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "types": ["node"]
  },
  "include": ["src/**/*.ts"],
  "exclude": ["dist", "node_modules"]
}
```

- [ ] **Step 3: Write `.mise.toml`**

```toml
[tools]
node = "26.5.1"
```

- [ ] **Step 4: Verify `.gitignore` already covers the package's build artifacts**

`.gitignore` was created at repo root before this plan's worktree existed (it needed to ignore `.worktrees/` before any worktree
was created). Read it and confirm it already contains `node_modules/` and `dist/` alongside `.worktrees/`:

```
.worktrees/
node_modules/
dist/
```

If either package line is missing, add it — but never remove the `.worktrees/` line: this file is shared with `main` through the
eventual merge, and dropping that line would stop `main` from ignoring future worktrees.

- [ ] **Step 5: Install dependencies and verify exact pinned versions landed**

Run: `npm install`

Then verify:

```bash
npm ls @toon-format/toon typescript @types/node
```

Expected: `@toon-format/toon@2.3.1`, `typescript@7.0.2`, `@types/node@26.2.0`, no errors, no "invalid" markers.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json tsconfig.json .mise.toml .gitignore
git commit -m "chore: scaffold serper-axi package"
```

---

### Task 2: `SerperAxiError` and exit-code mapping

**Files:**
- Create: `src/errors.ts`
- Test: `src/errors.test.ts`

**Interfaces:**
- Produces: `SerperAxiError` (class, extends `Error`, fields `message: string`, `kind: "usage" | "runtime"`, `help: string`) and
  `exitCodeForError(error: unknown): number` (returns `2` for a `SerperAxiError` with `kind: "usage"`, `1` for `kind: "runtime"` or any
  other thrown value).

- [ ] **Step 1: Write the failing tests**

```typescript
// src/errors.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { SerperAxiError, exitCodeForError } from "./errors.js";

test("SerperAxiError carries message, kind, and help", () => {
  const error = new SerperAxiError("bad input", "usage", "fix it like this");
  assert.equal(error.message, "bad input");
  assert.equal(error.kind, "usage");
  assert.equal(error.help, "fix it like this");
  assert.equal(error.name, "SerperAxiError");
});

test("exitCodeForError returns 2 for a usage error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "usage", "h")), 2);
});

test("exitCodeForError returns 1 for a runtime error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "runtime", "h")), 1);
});

test("exitCodeForError returns 1 for a non-SerperAxiError", () => {
  assert.equal(exitCodeForError(new Error("boom")), 1);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/errors.test.ts`
Expected: FAIL — `Cannot find module './errors.js'` (file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```typescript
// src/errors.ts
export type SerperAxiErrorKind = "usage" | "runtime";

export class SerperAxiError extends Error {
  readonly kind: SerperAxiErrorKind;
  readonly help: string;

  constructor(message: string, kind: SerperAxiErrorKind, help: string) {
    super(message);
    this.name = "SerperAxiError";
    this.kind = kind;
    this.help = help;
  }
}

export function exitCodeForError(error: unknown): number {
  if (error instanceof SerperAxiError) {
    return error.kind === "usage" ? 2 : 1;
  }
  return 1;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/errors.test.ts`
Expected: PASS, 4/4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/errors.ts src/errors.test.ts
git commit -m "feat: add SerperAxiError and exit-code mapping"
```

---

### Task 3: TOON output helpers

**Files:**
- Create: `src/output.ts`
- Test: `src/output.test.ts`

**Interfaces:**
- Consumes: `encode` from `@toon-format/toon`.
- Produces: `AxiOutput = Record<string, unknown>`; `encodeOutput(output: AxiOutput): string` (TOON text, always ending in exactly one
  `\n`); `collapseHomeDirectory(path: string, homeDir: string): string`; `truncate(text: string, limit: number): { text: string;
  truncated: boolean; totalChars: number }`.

- [ ] **Step 1: Write the failing tests**

```typescript
// src/output.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeOutput, collapseHomeDirectory, truncate } from "./output.js";

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
  assert.equal(collapseHomeDirectory("/home/user/.local/bin/serper-axi", "/home/user"), "~/.local/bin/serper-axi");
});

test("collapseHomeDirectory leaves a non-home path untouched", () => {
  assert.equal(collapseHomeDirectory("/usr/local/bin/serper-axi", "/home/user"), "/usr/local/bin/serper-axi");
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/output.test.ts`
Expected: FAIL — `Cannot find module './output.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/output.ts
import { encode } from "@toon-format/toon";

export type AxiOutput = Record<string, unknown>;

export function encodeOutput(output: AxiOutput): string {
  const text = encode(output);
  return text.endsWith("\n") ? text : `${text}\n`;
}

export function collapseHomeDirectory(path: string, homeDir: string): string {
  if (homeDir.length > 0 && path.startsWith(homeDir)) {
    return `~${path.slice(homeDir.length)}`;
  }
  return path;
}

export interface Truncated {
  text: string;
  truncated: boolean;
  totalChars: number;
}

export function truncate(text: string, limit: number): Truncated {
  const totalChars = text.length;
  if (totalChars <= limit) {
    return { text, truncated: false, totalChars };
  }
  return { text: text.slice(0, limit), truncated: true, totalChars };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/output.test.ts`
Expected: PASS, 6/6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/output.ts src/output.test.ts
git commit -m "feat: add TOON output, home-path collapse, and truncation helpers"
```

---

### Task 4: Serper HTTPS client

**Files:**
- Create: `src/serper.ts`
- Test: `src/serper.test.ts` (mocked `fetch`)
- Test: `src/serper.live.test.ts` (live API, skipped without `SERPER_API_KEY`)

**Interfaces:**
- Consumes: `SerperAxiError` from `./errors.js`.
- Produces: `SearchParams { q: string; gl: string; hl: string; num: number }`; `OrganicResult { position: number; title: string; link:
  string; snippet: string; date?: string; sitelinks?: unknown }`; `SearchResponse { organic: OrganicResult[] }`; `ScrapeResponse { text:
  string; metadata: { title?: string; [key: string]: unknown } }`; `searchSerper(apiKey: string, params: SearchParams, fetchImpl?: typeof
  fetch): Promise<SearchResponse>`; `scrapeSerper(apiKey: string, url: string, fetchImpl?: typeof fetch): Promise<ScrapeResponse>`. Both
  default `fetchImpl` to the global `fetch` and throw `SerperAxiError` (`kind: "runtime"`) on any HTTP or network failure.

- [ ] **Step 1: Write the failing mocked-fetch tests**

```typescript
// src/serper.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { searchSerper, scrapeSerper } from "./serper.js";
import { SerperAxiError } from "./errors.js";

function fakeFetch(status: number, body: unknown): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
}

test("searchSerper posts to the search endpoint and returns organic results", async () => {
  let capturedUrl: string | undefined;
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    capturedUrl = url;
    capturedInit = init;
    return new Response(
      JSON.stringify({ organic: [{ position: 1, title: "t", link: "https://x", snippet: "s" }] }),
      { status: 200 },
    );
  }) as typeof fetch;

  const result = await searchSerper("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl);

  assert.equal(capturedUrl, "https://google.serper.dev/search");
  assert.equal((capturedInit?.headers as Record<string, string>)["X-API-KEY"], "key");
  assert.equal(JSON.parse(capturedInit?.body as string).num, 5);
  assert.equal(result.organic.length, 1);
});

test("searchSerper throws a runtime error on 403", async () => {
  const fetchImpl = fakeFetch(403, { message: "Unauthorized.", statusCode: 403 });
  await assert.rejects(
    () => searchSerper("bad", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /403/);
      return true;
    },
  );
});

test("searchSerper throws a runtime error on 429", async () => {
  const fetchImpl = fakeFetch(429, { message: "Too Many Requests", statusCode: 429 });
  await assert.rejects(() => searchSerper("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerperAxiError);
});

test("searchSerper throws a runtime error on 500", async () => {
  const fetchImpl = fakeFetch(500, { message: "Internal Server Error", statusCode: 500 });
  await assert.rejects(() => searchSerper("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerperAxiError);
});

test("scrapeSerper posts to the scrape endpoint and returns text", async () => {
  let capturedUrl: string | undefined;
  const fetchImpl = (async (url: string) => {
    capturedUrl = url;
    return new Response(JSON.stringify({ text: "hello", metadata: { title: "Hello Page" } }), { status: 200 });
  }) as typeof fetch;

  const result = await scrapeSerper("key", "https://example.com", fetchImpl);

  assert.equal(capturedUrl, "https://scrape.serper.dev");
  assert.equal(result.text, "hello");
  assert.equal(result.metadata.title, "Hello Page");
});

test("scrapeSerper throws a runtime error on 404", async () => {
  const fetchImpl = fakeFetch(404, { message: "Page not found.", statusCode: 404 });
  await assert.rejects(
    () => scrapeSerper("key", "https://example.com/missing", fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.match(error.message, /404/);
      return true;
    },
  );
});

test("searchSerper wraps a network failure as a runtime error", async () => {
  const fetchImpl = (async () => {
    throw new Error("getaddrinfo ENOTFOUND");
  }) as typeof fetch;
  await assert.rejects(() => searchSerper("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerperAxiError);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/serper.test.ts`
Expected: FAIL — `Cannot find module './serper.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/serper.ts
import { SerperAxiError } from "./errors.js";

export interface SearchParams {
  q: string;
  gl: string;
  hl: string;
  num: number;
}

export interface OrganicResult {
  position: number;
  title: string;
  link: string;
  snippet: string;
  date?: string;
  sitelinks?: unknown;
}

export interface SearchResponse {
  organic: OrganicResult[];
}

export interface ScrapeResponse {
  text: string;
  metadata: { title?: string; [key: string]: unknown };
}

interface SerperErrorBody {
  message?: string;
  statusCode?: number;
}

async function serperRequest(url: string, apiKey: string, body: unknown, fetchImpl: typeof fetch): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: {
        "X-API-KEY": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new SerperAxiError(
      `network error calling Serper: ${(cause as Error).message}`,
      "runtime",
      "check network connectivity and retry",
    );
  }

  if (response.ok) {
    return response.json();
  }

  let parsed: SerperErrorBody = {};
  try {
    parsed = (await response.json()) as SerperErrorBody;
  } catch {
    // body wasn't JSON; fall through with an empty parsed body
  }

  if (response.status === 403) {
    throw new SerperAxiError(
      "Serper rejected the API key (403)",
      "runtime",
      "check that SERPER_API_KEY is set to a valid key",
    );
  }
  if (response.status === 429) {
    throw new SerperAxiError("Serper rate-limited this request (429)", "runtime", "wait and retry later");
  }
  if (response.status === 404) {
    throw new SerperAxiError(
      "Serper could not find the requested page (404)",
      "runtime",
      "verify the URL is correct and reachable",
    );
  }
  if (response.status >= 500) {
    throw new SerperAxiError(`Serper had an upstream failure (${response.status})`, "runtime", "retry later");
  }

  const excerpt = JSON.stringify(parsed).slice(0, 300);
  throw new SerperAxiError(
    `Serper returned an unexpected status ${response.status}: ${excerpt}`,
    "runtime",
    "this is not a status serper-axi maps explicitly; report it if it persists",
  );
}

export async function searchSerper(
  apiKey: string,
  params: SearchParams,
  fetchImpl: typeof fetch = fetch,
): Promise<SearchResponse> {
  const body = await serperRequest(
    "https://google.serper.dev/search",
    apiKey,
    { q: params.q, gl: params.gl, hl: params.hl, num: params.num },
    fetchImpl,
  );
  return body as SearchResponse;
}

export async function scrapeSerper(
  apiKey: string,
  url: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ScrapeResponse> {
  const body = await serperRequest("https://scrape.serper.dev", apiKey, { url }, fetchImpl);
  return body as ScrapeResponse;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/serper.test.ts`
Expected: PASS, 7/7 tests.

- [ ] **Step 5: Write the live-API test file**

```typescript
// src/serper.live.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { searchSerper, scrapeSerper } from "./serper.js";

const apiKey = process.env.SERPER_API_KEY;

test("searchSerper returns real organic results from the live API", { skip: !apiKey }, async () => {
  const response = await searchSerper(apiKey as string, { q: "openai", gl: "us", hl: "en", num: 3 });
  assert.ok(Array.isArray(response.organic));
  assert.ok(response.organic.length > 0);
  assert.ok(typeof response.organic[0].title === "string");
});

test("scrapeSerper returns real page text from the live API", { skip: !apiKey }, async () => {
  const response = await scrapeSerper(apiKey as string, "https://example.com");
  assert.ok(typeof response.text === "string");
  assert.ok(response.text.length > 0);
});

test("searchSerper surfaces a 403 for a bad key against the live API", { skip: !apiKey }, async () => {
  await assert.rejects(
    () => searchSerper("invalid-key-serper-axi-test", { q: "test", gl: "us", hl: "en", num: 1 }),
    (error: unknown) => {
      assert.match((error as Error).message, /403/);
      return true;
    },
  );
});
```

- [ ] **Step 6: Run the live test file and confirm it skips cleanly without a key, and passes with one**

Run: `env -u SERPER_API_KEY node --test src/serper.live.test.ts`
Expected: 3/3 tests reported `skipped`, 0 failures.

Run: `node --test src/serper.live.test.ts` (with `SERPER_API_KEY` set in the environment)
Expected: PASS, 3/3 tests, exercising the real Serper API.

- [ ] **Step 7: Commit**

```bash
git add src/serper.ts src/serper.test.ts src/serper.live.test.ts
git commit -m "feat: add direct HTTPS client for Serper search and scrape"
```

---

### Task 5: CLI dispatcher and flag parser

**Files:**
- Create: `src/cli.ts`
- Test: `src/cli.test.ts`

**Interfaces:**
- Consumes: `SerperAxiError`, `exitCodeForError` from `./errors.js`; `encodeOutput`, `collapseHomeDirectory`, `AxiOutput` from
  `./output.js`.
- Produces: `FlagType = "string" | "boolean"`; `FlagSpec = Record<string, FlagType>`; `ParsedFlags { positionals: string[]; flags:
  Record<string, string | boolean>; helpRequested: boolean }`; `parseFlags(args: string[], spec: FlagSpec, commandName: string):
  ParsedFlags` (throws `SerperAxiError` with `kind: "usage"` on an unknown flag or a missing value); `CliCommand { name: string; help:
  string; run: (args: string[]) => Promise<AxiOutput | string> | AxiOutput | string }`; `RunCliOptions { description: string; version:
  string; execPath: string; homeDir: string; commands: CliCommand[]; stdout: { write: (chunk: string) => unknown } }`; `runCli(argv:
  string[], options: RunCliOptions): Promise<number>`.

- [ ] **Step 1: Write the failing tests**

```typescript
// src/cli.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { decode } from "@toon-format/toon";
import { parseFlags, runCli, type CliCommand, type RunCliOptions } from "./cli.js";
import { SerperAxiError } from "./errors.js";

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

function baseOptions(commands: CliCommand[]): Omit<RunCliOptions, "stdout"> {
  return {
    description: "test tool",
    version: "0.0.1",
    execPath: "/home/user/.local/bin/serper-axi",
    homeDir: "/home/user",
    commands,
  };
}

test("parseFlags collects positionals and string flags", () => {
  const parsed = parseFlags(["query words", "--region", "uk"], { region: "string" }, "search");
  assert.deepEqual(parsed.positionals, ["query words"]);
  assert.equal(parsed.flags.region, "uk");
  assert.equal(parsed.helpRequested, false);
});

test("parseFlags rejects an unknown flag with a usage error", () => {
  assert.throws(
    () => parseFlags(["--stat", "closed"], { state: "string" }, "list"),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /unknown flag --stat/);
      assert.match(error.help, /--state/);
      return true;
    },
  );
});

test("parseFlags rejects a value-flag with a missing value", () => {
  assert.throws(
    () => parseFlags(["--region"], { region: "string" }, "search"),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runCli with no args renders the home view", async () => {
  const stdout = fakeStdout();
  const code = await runCli([], { ...baseOptions([]), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.bin, "~/.local/bin/serper-axi");
  assert.equal(decoded.description, "test tool");
});

test("runCli rejects an unknown command with exit 2", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["bogus"], { ...baseOptions([]), stdout });
  assert.equal(code, 2);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.match(decoded.error as string, /unknown command `bogus`/);
});

test("runCli dispatches to a matching command and renders its output", async () => {
  const command: CliCommand = {
    name: "echo",
    help: "echo help text",
    run: (args) => ({ heard: args.join(" ") }),
  };
  const stdout = fakeStdout();
  const code = await runCli(["echo", "hi", "there"], { ...baseOptions([command]), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.heard, "hi there");
});

test("runCli surfaces a SerperAxiError as a structured error with the right exit code", async () => {
  const command: CliCommand = {
    name: "boom",
    help: "boom help text",
    run: () => {
      throw new SerperAxiError("something is unset", "runtime", "set the thing");
    },
  };
  const stdout = fakeStdout();
  const code = await runCli(["boom"], { ...baseOptions([command]), stdout });
  assert.equal(code, 1);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.error, "something is unset");
  assert.equal(decoded.help, "set the thing");
});

test("runCli prints a command's help text on --help without dispatching", async () => {
  let ran = false;
  const command: CliCommand = {
    name: "echo",
    help: "echo help text",
    run: () => {
      ran = true;
      return {};
    },
  };
  const stdout = fakeStdout();
  const code = await runCli(["echo", "--help"], { ...baseOptions([command]), stdout });
  assert.equal(code, 0);
  assert.equal(ran, false);
  assert.match(stdout.output, /echo help text/);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/cli.test.ts`
Expected: FAIL — `Cannot find module './cli.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/cli.ts
import { SerperAxiError, exitCodeForError } from "./errors.js";
import { encodeOutput, collapseHomeDirectory, type AxiOutput } from "./output.js";

export type FlagType = "string" | "boolean";
export type FlagSpec = Record<string, FlagType>;

export interface ParsedFlags {
  positionals: string[];
  flags: Record<string, string | boolean>;
  helpRequested: boolean;
}

export function parseFlags(args: string[], spec: FlagSpec, commandName: string): ParsedFlags {
  const positionals: string[] = [];
  const flags: Record<string, string | boolean> = {};
  let helpRequested = false;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") {
      helpRequested = true;
      continue;
    }
    if (arg.startsWith("--")) {
      const name = arg.slice(2);
      if (!(name in spec)) {
        throw new SerperAxiError(
          `unknown flag --${name} for \`${commandName}\``,
          "usage",
          `valid flags for \`${commandName}\`: ${Object.keys(spec)
            .map((f) => `--${f}`)
            .join(", ")} (--help always allowed)`,
        );
      }
      if (spec[name] === "boolean") {
        flags[name] = true;
        continue;
      }
      const value = args[i + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new SerperAxiError(`--${name} requires a value`, "usage", `example: --${name} <value>`);
      }
      flags[name] = value;
      i++;
      continue;
    }
    positionals.push(arg);
  }

  return { positionals, flags, helpRequested };
}

export interface CliCommand {
  name: string;
  help: string;
  run: (args: string[]) => Promise<AxiOutput | string> | AxiOutput | string;
}

export interface RunCliOptions {
  description: string;
  version: string;
  execPath: string;
  homeDir: string;
  commands: CliCommand[];
  stdout: { write: (chunk: string) => unknown };
}

function homeHeader(options: RunCliOptions): AxiOutput {
  return {
    bin: collapseHomeDirectory(options.execPath, options.homeDir),
    description: options.description,
  };
}

function renderHome(options: RunCliOptions): AxiOutput {
  return {
    ...homeHeader(options),
    commands: options.commands.map((c) => c.name),
    help: options.commands.map((c) => `Run \`serper-axi ${c.name} --help\` for details`),
  };
}

function renderTopLevelHelp(options: RunCliOptions): string {
  const lines = [
    options.description,
    "",
    "Commands:",
    ...options.commands.map((c) => `  ${c.name}`),
    "",
    "Run `serper-axi <command> --help` for a command's flags.",
  ];
  return `${lines.join("\n")}\n`;
}

export async function runCli(argv: string[], options: RunCliOptions): Promise<number> {
  if (argv.length === 0) {
    options.stdout.write(encodeOutput(renderHome(options)));
    return 0;
  }

  if (argv[0] === "--help" || argv[0] === "-h") {
    options.stdout.write(renderTopLevelHelp(options));
    return 0;
  }

  if (argv[0] === "--version" || argv[0] === "-v") {
    options.stdout.write(`${options.version}\n`);
    return 0;
  }

  const [commandName, ...rest] = argv;
  const command = options.commands.find((c) => c.name === commandName);

  if (!command) {
    const output: AxiOutput = {
      error: `unknown command \`${commandName}\``,
      help: `valid commands: ${options.commands.map((c) => c.name).join(", ")}`,
    };
    options.stdout.write(encodeOutput(output));
    return 2;
  }

  if (rest.includes("--help") || rest.includes("-h")) {
    options.stdout.write(command.help.endsWith("\n") ? command.help : `${command.help}\n`);
    return 0;
  }

  try {
    const result = await command.run(rest);
    options.stdout.write(typeof result === "string" ? result : encodeOutput(result));
    return 0;
  } catch (error) {
    const message = error instanceof SerperAxiError ? error.message : (error as Error).message;
    const help = error instanceof SerperAxiError ? error.help : undefined;
    const output: AxiOutput = { error: message };
    if (help) output.help = help;
    options.stdout.write(encodeOutput(output));
    return exitCodeForError(error);
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/cli.test.ts`
Expected: PASS, 8/8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/cli.ts src/cli.test.ts
git commit -m "feat: add CLI dispatcher, flag parser, home view, and help rendering"
```

---

### Task 6: `search` command

**Files:**
- Create: `src/commands/search.ts`
- Test: `src/commands/search.test.ts`

**Interfaces:**
- Consumes: `parseFlags`, `FlagSpec`, `CliCommand` from `../cli.js`; `SerperAxiError` from `../errors.js`; `truncate`, `AxiOutput` from
  `../output.js`; `searchSerper`, `SearchParams` from `../serper.js`.
- Produces: `runSearch(args: string[], fetchImpl?: typeof fetch): Promise<AxiOutput>`; `searchCommand: CliCommand` (name `"search"`).

- [ ] **Step 1: Write the failing tests**

```typescript
// src/commands/search.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { runSearch } from "./search.js";
import { SerperAxiError } from "../errors.js";

async function withApiKey<T>(value: string | undefined, fn: () => Promise<T>): Promise<T> {
  const original = process.env.SERPER_API_KEY;
  if (value === undefined) delete process.env.SERPER_API_KEY;
  else process.env.SERPER_API_KEY = value;
  try {
    return await fn();
  } finally {
    if (original === undefined) delete process.env.SERPER_API_KEY;
    else process.env.SERPER_API_KEY = original;
  }
}

function fetchWithOrganic(organic: unknown[]): typeof fetch {
  return (async () => new Response(JSON.stringify({ organic }), { status: 200 })) as typeof fetch;
}

test("runSearch rejects an empty query before any network call", async () => {
  await withApiKey("test-key", async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runSearch([], fetchImpl), SerperAxiError);
    assert.equal(called, false);
  });
});

test("runSearch rejects --num outside 1..100", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runSearch(["q", "--num", "0"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runSearch rejects an unknown --fields value", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runSearch(["q", "--fields", "bogus"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runSearch applies defaults and truncates a long snippet", async () => {
  await withApiKey("test-key", async () => {
    const longSnippet = "x".repeat(250);
    const fetchImpl = fetchWithOrganic([{ position: 1, title: "t", link: "https://x", snippet: longSnippet }]);
    const output = await runSearch(["hello world"], fetchImpl);
    assert.equal(output.count, 1);
    const results = output.results as Array<Record<string, unknown>>;
    assert.equal((results[0].snippet as string).length, 203);
  });
});

test("runSearch includes an extra --fields value in the output rows", async () => {
  await withApiKey("test-key", async () => {
    const fetchImpl = fetchWithOrganic([
      { position: 1, title: "t", link: "https://x", snippet: "s", date: "2026-01-01" },
    ]);
    const output = await runSearch(["q", "--fields", "date"], fetchImpl);
    const results = output.results as Array<Record<string, unknown>>;
    assert.equal(results[0].date, "2026-01-01");
  });
});

test("runSearch reports a definitive zero-result state", async () => {
  await withApiKey("test-key", async () => {
    const fetchImpl = fetchWithOrganic([]);
    const output = await runSearch(["nothing here"], fetchImpl);
    assert.equal(output.count, 0);
    assert.match(output.results as string, /0 results found for query "nothing here"/);
  });
});

test("runSearch requires SERPER_API_KEY before any network call", async () => {
  await withApiKey(undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runSearch(["hi"], fetchImpl), SerperAxiError);
    assert.equal(called, false);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/commands/search.test.ts`
Expected: FAIL — `Cannot find module './search.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/commands/search.ts
import { parseFlags, type CliCommand, type FlagSpec } from "../cli.js";
import { SerperAxiError } from "../errors.js";
import { truncate, type AxiOutput } from "../output.js";
import { searchSerper, type SearchParams } from "../serper.js";

const SEARCH_FLAGS: FlagSpec = {
  region: "string",
  lang: "string",
  num: "string",
  fields: "string",
};

const ALLOWED_EXTRA_FIELDS = ["date", "sitelinks"];
const SNIPPET_LIMIT = 200;

const SEARCH_HELP = `serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>]

Run a Serper (Google Search API) query.

Flags:
  --region <cc>      Two-letter region code (maps to Serper's gl). Default: us
  --lang <code>       Language code (maps to Serper's hl). Default: en
  --num <n>            Number of results, 1-100. Default: 10
  --fields <a,b,c>      Extra fields to include beyond the default schema.
                          Accepted: date, sitelinks

Examples:
  serper-axi search "site:example.com pricing"
  serper-axi search "climate policy" --region uk --lang en --num 20
  serper-axi search "conference talks" --fields date,sitelinks`;

function parseNum(raw: string | undefined): number {
  if (raw === undefined) return 10;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 100) {
    throw new SerperAxiError(`--num must be an integer in 1..100, got "${raw}"`, "usage", "example: --num 20");
  }
  return value;
}

function parseRegionOrLang(raw: string | undefined, flagName: string, fallback: string): string {
  const value = raw ?? fallback;
  if (!/^[a-z]+$/.test(value)) {
    throw new SerperAxiError(
      `--${flagName} must be non-empty lowercase ASCII, got "${value}"`,
      "usage",
      `example: --${flagName} ${fallback}`,
    );
  }
  return value;
}

function parseFields(raw: string | undefined): string[] {
  if (raw === undefined) return [];
  const fields = raw
    .split(",")
    .map((f) => f.trim())
    .filter((f) => f.length > 0);
  for (const field of fields) {
    if (!ALLOWED_EXTRA_FIELDS.includes(field)) {
      throw new SerperAxiError(
        `unknown field "${field}" for --fields`,
        "usage",
        `accepted fields: ${ALLOWED_EXTRA_FIELDS.join(", ")}`,
      );
    }
  }
  return fields;
}

export async function runSearch(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SEARCH_FLAGS, "search");

  const query = positionals.join(" ").trim();
  if (query.length === 0) {
    throw new SerperAxiError("search requires a query", "usage", 'example: serper-axi search "<query>"');
  }

  const num = parseNum(flags.num as string | undefined);
  const region = parseRegionOrLang(flags.region as string | undefined, "region", "us");
  const lang = parseRegionOrLang(flags.lang as string | undefined, "lang", "en");
  const extraFields = parseFields(flags.fields as string | undefined);

  const apiKey = process.env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerperAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  const params: SearchParams = { q: query, gl: region, hl: lang, num };
  const response = await searchSerper(apiKey, params, fetchImpl);

  const results = response.organic.map((r) => {
    const snippetInfo = truncate(r.snippet, SNIPPET_LIMIT);
    const row: Record<string, unknown> = {
      position: r.position,
      title: r.title,
      link: r.link,
      snippet: snippetInfo.truncated ? `${snippetInfo.text}...` : snippetInfo.text,
    };
    for (const field of extraFields) {
      row[field] = (r as Record<string, unknown>)[field];
    }
    return row;
  });

  if (results.length === 0) {
    return {
      count: 0,
      results: `0 results found for query "${query}"`,
      help: "try a different query, or broaden --region/--lang",
    };
  }

  return {
    count: results.length,
    results,
    help: 'Run `serper-axi scrape "<link>"` to read a result in full',
  };
}

export const searchCommand: CliCommand = {
  name: "search",
  help: SEARCH_HELP,
  run: (args) => runSearch(args),
};
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/commands/search.test.ts`
Expected: PASS, 7/7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/commands/search.ts src/commands/search.test.ts
git commit -m "feat: add search command"
```

---

### Task 7: `scrape` command

**Files:**
- Create: `src/commands/scrape.ts`
- Test: `src/commands/scrape.test.ts`

**Interfaces:**
- Consumes: `parseFlags`, `FlagSpec`, `CliCommand` from `../cli.js`; `SerperAxiError` from `../errors.js`; `truncate`, `AxiOutput` from
  `../output.js`; `scrapeSerper` from `../serper.js`.
- Produces: `runScrape(args: string[], fetchImpl?: typeof fetch): Promise<AxiOutput>`; `scrapeCommand: CliCommand` (name `"scrape"`).

- [ ] **Step 1: Write the failing tests**

```typescript
// src/commands/scrape.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { runScrape } from "./scrape.js";
import { SerperAxiError } from "../errors.js";

async function withApiKey<T>(value: string | undefined, fn: () => Promise<T>): Promise<T> {
  const original = process.env.SERPER_API_KEY;
  if (value === undefined) delete process.env.SERPER_API_KEY;
  else process.env.SERPER_API_KEY = value;
  try {
    return await fn();
  } finally {
    if (original === undefined) delete process.env.SERPER_API_KEY;
    else process.env.SERPER_API_KEY = original;
  }
}

test("runScrape rejects a missing URL before any network call", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(() => runScrape([], (async () => new Response("{}")) as typeof fetch), SerperAxiError);
  });
});

test("runScrape rejects a non-http(s) scheme", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["file:///etc/passwd"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects a loopback host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://127.0.0.1/secret"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects a private-range host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://192.168.1.5/"], (async () => new Response("{}")) as typeof fetch),
      SerperAxiError,
    );
  });
});

test("runScrape requires SERPER_API_KEY before any network call", async () => {
  await withApiKey(undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runScrape(["https://example.com"], fetchImpl), SerperAxiError);
    assert.equal(called, false);
  });
});

test("runScrape truncates to the default 1200-character limit", async () => {
  await withApiKey("test-key", async () => {
    const longText = "y".repeat(2000);
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ text: longText, metadata: { title: "Big Page" } }), { status: 200 })) as typeof fetch;
    const output = await runScrape(["https://example.com/big"], fetchImpl);
    assert.equal((output.text as string).length, 1200);
    assert.equal(output.title, "Big Page");
    assert.equal(output.truncatedFrom, 2000);
    assert.match(output.help as string, /--full/);
  });
});

test("runScrape --full raises the limit to 50000 characters", async () => {
  await withApiKey("test-key", async () => {
    const longText = "z".repeat(2000);
    const fetchImpl = (async () => new Response(JSON.stringify({ text: longText, metadata: {} }), { status: 200 })) as typeof fetch;
    const output = await runScrape(["https://example.com/big", "--full"], fetchImpl);
    assert.equal((output.text as string).length, 2000);
    assert.equal(output.truncatedFrom, undefined);
    assert.equal(output.title, undefined);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/commands/scrape.test.ts`
Expected: FAIL — `Cannot find module './scrape.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/commands/scrape.ts
import { parseFlags, type CliCommand, type FlagSpec } from "../cli.js";
import { SerperAxiError } from "../errors.js";
import { truncate, type AxiOutput } from "../output.js";
import { scrapeSerper } from "../serper.js";

const SCRAPE_FLAGS: FlagSpec = {
  full: "boolean",
};

const DEFAULT_LIMIT = 1200;
const FULL_LIMIT = 50000;

const SCRAPE_HELP = `serper-axi scrape <url> [--full]

Fetch and extract readable text from a web page via Serper.

Flags:
  --full   Return up to 50,000 characters instead of the default 1,200.

Examples:
  serper-axi scrape https://example.com/article
  serper-axi scrape https://example.com/article --full`;

const PRIVATE_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);

function validateUrl(raw: string): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SerperAxiError(`"${raw}" is not a valid URL`, "usage", "example: serper-axi scrape https://example.com/article");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SerperAxiError(
      `scrape only accepts http/https URLs, got "${url.protocol}"`,
      "usage",
      "example: serper-axi scrape https://example.com/article",
    );
  }
  const hostname = url.hostname.toLowerCase();
  if (
    PRIVATE_HOSTS.has(hostname) ||
    hostname.startsWith("10.") ||
    hostname.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname)
  ) {
    throw new SerperAxiError(
      `"${hostname}" is a loopback or private-range host`,
      "usage",
      "scrape only accepts publicly reachable URLs",
    );
  }
  return url;
}

export async function runScrape(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SCRAPE_FLAGS, "scrape");

  const raw = positionals[0];
  if (!raw) {
    throw new SerperAxiError("scrape requires a URL", "usage", "example: serper-axi scrape https://example.com/article");
  }
  const url = validateUrl(raw);

  const apiKey = process.env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerperAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  const response = await scrapeSerper(apiKey, url.toString(), fetchImpl);
  const limit = flags.full ? FULL_LIMIT : DEFAULT_LIMIT;
  const info = truncate(response.text, limit);

  const output: AxiOutput = { url: url.toString() };
  if (response.metadata.title) {
    output.title = response.metadata.title;
  }
  output.text = info.text;
  if (info.truncated) {
    output.truncatedFrom = info.totalChars;
    output.help = flags.full
      ? `content is capped at ${FULL_LIMIT} characters even with --full`
      : `Run \`serper-axi scrape ${url.toString()} --full\` to see up to ${FULL_LIMIT} characters (${info.totalChars} total)`;
  }
  return output;
}

export const scrapeCommand: CliCommand = {
  name: "scrape",
  help: SCRAPE_HELP,
  run: (args) => runScrape(args),
};
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/commands/scrape.test.ts`
Expected: PASS, 7/7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/commands/scrape.ts src/commands/scrape.test.ts
git commit -m "feat: add scrape command"
```

---

### Task 8: `update` command

**Files:**
- Create: `src/commands/update.ts`
- Test: `src/commands/update.test.ts`

**Interfaces:**
- Consumes: `CliCommand` from `../cli.js`; `AxiOutput` from `../output.js`.
- Produces: `runUpdate(): AxiOutput`; `updateCommand: CliCommand` (name `"update"`).

- [ ] **Step 1: Write the failing test**

```typescript
// src/commands/update.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { runUpdate } from "./update.js";

test("runUpdate reports a local install with the upgrade path, no registry call", () => {
  const output = runUpdate();
  assert.equal(output.status, "local install; no registry to check");
  assert.equal(output.upgrade, "git pull && npm run build && npm install -g .");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test src/commands/update.test.ts`
Expected: FAIL — `Cannot find module './update.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/commands/update.ts
import type { CliCommand } from "../cli.js";
import type { AxiOutput } from "../output.js";

const UPDATE_HELP = `serper-axi update

Report the local install's upgrade path. serper-axi is not published to the
npm registry, so there is no version to check remotely.

Examples:
  serper-axi update`;

export function runUpdate(): AxiOutput {
  return {
    status: "local install; no registry to check",
    upgrade: "git pull && npm run build && npm install -g .",
  };
}

export const updateCommand: CliCommand = {
  name: "update",
  help: UPDATE_HELP,
  run: () => runUpdate(),
};
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test src/commands/update.test.ts`
Expected: PASS, 1/1 test.

- [ ] **Step 5: Commit**

```bash
git add src/commands/update.ts src/commands/update.test.ts
git commit -m "feat: add update command"
```

---

### Task 9: App wiring and entrypoint

**Files:**
- Create: `src/app.ts`
- Test: `src/app.test.ts`
- Create: `src/bin/serper-axi.ts`

**Interfaces:**
- Consumes: `RunCliOptions`, `runCli` from `./cli.js`; `searchCommand` from `./commands/search.js`; `scrapeCommand` from
  `./commands/scrape.js`; `updateCommand` from `./commands/update.js`.
- Produces: `createAppOptions(execUrl: string, overrides?: { homeDir?: string }): Omit<RunCliOptions, "stdout">`.

- [ ] **Step 1: Write the failing tests**

```typescript
// src/app.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { decode } from "@toon-format/toon";
import { runCli } from "./cli.js";
import { createAppOptions } from "./app.js";

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/app.test.ts`
Expected: FAIL — `Cannot find module './app.js'`.

- [ ] **Step 3: Write `src/app.ts`**

```typescript
// src/app.ts
import os from "node:os";
import { fileURLToPath } from "node:url";
import type { RunCliOptions } from "./cli.js";
import { searchCommand } from "./commands/search.js";
import { scrapeCommand } from "./commands/scrape.js";
import { updateCommand } from "./commands/update.js";

export const VERSION = "0.1.0";

export function createAppOptions(
  execUrl: string,
  overrides: { homeDir?: string } = {},
): Omit<RunCliOptions, "stdout"> {
  return {
    description: "Run Serper (Google Search API) queries and page scrapes",
    version: VERSION,
    execPath: fileURLToPath(execUrl),
    homeDir: overrides.homeDir ?? os.homedir(),
    commands: [searchCommand, scrapeCommand, updateCommand],
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/app.test.ts`
Expected: PASS, 4/4 tests.

- [ ] **Step 5: Write `src/bin/serper-axi.ts`**

```typescript
#!/usr/bin/env node
// src/bin/serper-axi.ts
import { runCli } from "../cli.js";
import { createAppOptions } from "../app.js";

const exitCode = await runCli(process.argv.slice(2), {
  ...createAppOptions(import.meta.url),
  stdout: process.stdout,
});

process.exit(exitCode);
```

- [ ] **Step 6: Build and smoke-test the compiled entrypoint directly (not a global install)**

Run: `npm run build`
Expected: exits 0, `dist/bin/serper-axi.js` exists.

Run: `node dist/bin/serper-axi.js`
Expected: exit code `0`, TOON home view printed with `bin:` ending in `dist/bin/serper-axi.js` and `commands: search,scrape,update` (or
the equivalent tabular/array TOON rendering).

Run: `node dist/bin/serper-axi.js bogus`
Expected: exit code `2`, structured `error: unknown command \`bogus\`` on stdout.

Run: `echo $?` after each, to confirm the exit codes above.

- [ ] **Step 7: Commit**

```bash
git add src/app.ts src/app.test.ts src/bin/serper-axi.ts
git commit -m "feat: wire commands into the CLI entrypoint"
```

---

### Task 10: `SKILL.md`

**Files:**
- Create: `SKILL.md`

**Interfaces:**
- None — static documentation. Must stay consistent with the real `--help` output produced by Task 6/7's `SEARCH_HELP`/`SCRAPE_HELP`
  text (defaults, flags, limits).

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: using-serper-axi
description: Use when an agent needs to run a live web search or scrape a specific page's text via Serper (Google Search API) — search results with title/link/snippet, or a page's readable text extracted from its URL.
---

# serper-axi

`serper-axi` is a CLI that runs Serper (Google Search API) queries and page
scrapes for agents. It requires `SERPER_API_KEY` to be set in the
environment and the package installed locally (this tool is not published to
npm — install via `git pull && npm run build && npm install -g .` in its
repo).

## Search

```
serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>]
```

Defaults: `--region us --lang en --num 10`. Results include `position`,
`title`, `link`, and a 200-character `snippet`. Pass `--fields date,sitelinks`
to include either of those two extra fields when present.

## Scrape

```
serper-axi scrape <url> [--full]
```

Fetches a page's readable text (from Serper's scrape endpoint), truncated to
1,200 characters by default. `--full` returns up to 50,000 characters.

## Notes

- `SERPER_API_KEY` must be exported in the environment before running either
  command; serper-axi checks for it before making any network call.
- Both commands reject invalid input (bad `--num`, non-http(s) scrape URLs,
  loopback/private hosts) with exit code 2, before any network call.
- Run `serper-axi <command> --help` for the full flag reference.
```

- [ ] **Step 2: Verify parity against the real CLI's help output**

Run: `node dist/bin/serper-axi.js search --help`
Run: `node dist/bin/serper-axi.js scrape --help`

Confirm by inspection that every default and limit `SKILL.md` states (`--region us`, `--lang en`, `--num 10`, 200-character snippet,
1200/50000-character scrape limits, accepted `--fields` values `date`/`sitelinks`) matches what these two commands actually print.
Fix `SKILL.md` if anything drifted.

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: add SKILL.md discovery doc for serper-axi"
```

---

### Task 11: Taskferry verification gate

**Files:**
- Create: `.taskferry.toml`

**Interfaces:**
- None — repo administration, not application code.

- [ ] **Step 1: Run `taskferry init` at the repo root**

Run: `taskferry init`

`init` detects `package.json`'s `check` script (added in Task 1) and either writes it directly (interactive TTY) or writes a commented
fill-in template (non-interactive). Confirm which happened by reading the file.

- [ ] **Step 2: Ensure the `check` command is live, not commented out**

Open `.taskferry.toml`. If the `check` line is commented out (`# check = "..."`), uncomment it and set it explicitly:

```toml
check = "npm run check"
```

- [ ] **Step 3: Verify the gate actually runs the check command**

Run: `npm run check`
Expected: exits 0 (typecheck clean, full test suite passing — live tests skip without `SERPER_API_KEY`, or pass with it set).

- [ ] **Step 4: Commit**

```bash
git add .taskferry.toml
git commit -m "chore: enable taskferry verification gate"
```

---

## Post-plan note on install verification

Every task above verifies behavior by running the built CLI directly (`node dist/bin/serper-axi.js ...`), never via a global
`npm install -g .`, to avoid mutating the implementer's global npm prefix during automated execution. Once the plan is fully executed,
a human (not an automated task step) should run `npm install -g .` once from the repo root and confirm `serper-axi` resolves on `PATH`,
per the spec's "Install" line.
