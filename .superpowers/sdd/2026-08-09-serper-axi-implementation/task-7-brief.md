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

