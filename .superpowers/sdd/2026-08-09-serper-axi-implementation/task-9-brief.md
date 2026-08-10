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

