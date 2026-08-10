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

