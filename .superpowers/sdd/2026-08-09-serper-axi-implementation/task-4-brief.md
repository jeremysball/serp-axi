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

