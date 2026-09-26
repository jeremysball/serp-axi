import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { SerpAxiError } from "./errors.ts";
import { parseKagiHtml, searchKagi } from "./kagi.ts";

const FIXTURE = readFileSync(fileURLToPath(new URL("./fixtures/kagi-html-search.html", import.meta.url)), "utf8");

const PARAMS = { q: "rust async runtime", gl: "us", hl: "en", num: 10 };

function stubFetch(body: string, init: { status?: number } = {}): typeof fetch {
  return (async () => new Response(body, { status: init.status ?? 200 })) as unknown as typeof fetch;
}

test("parseKagiHtml extracts every organic result from a real SERP", () => {
  const results = parseKagiHtml(FIXTURE);

  assert.equal(results.length, 13);
  assert.deepEqual(results.map((r) => r.position), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]);
  assert.equal(results[2]?.title, "Tokio - An asynchronous Rust runtime");
  assert.equal(results[2]?.link, "https://tokio.rs/");
});

test("parseKagiHtml finds a snippet for every result", () => {
  // Regression: the description class is written `class="_0_DESC __sri-desc"`,
  // so a selector anchored to the start of the class attribute silently lost
  // the snippet on 7 of these 13 results while still returning titles.
  const empty = parseKagiHtml(FIXTURE).filter((r) => r.snippet.length === 0);
  assert.deepEqual(empty, []);
});

test("parseKagiHtml strips nested markup and decodes entities in snippets", () => {
  for (const result of parseKagiHtml(FIXTURE)) {
    assert.doesNotMatch(result.snippet, /<[a-z/]/i, `snippet kept markup: ${result.snippet}`);
    assert.doesNotMatch(result.snippet, /&(amp|lt|gt|quot|#\d+);/, `snippet kept an entity: ${result.snippet}`);
  }
});

test("parseKagiHtml drops the Summarize UI control from snippets", () => {
  // The control is an <a> nested inside the description div, so plain
  // tag-stripping leaves its label glued to the end of every snippet.
  for (const result of parseKagiHtml(FIXTURE)) {
    assert.doesNotMatch(result.snippet, /Summarize$/, `snippet kept the control: ${result.snippet}`);
  }
});

test("parseKagiHtml finds blocks regardless of where _0_SRI sits in the class list", () => {
  // Kagi currently writes `class="_0_SRI _ext_ub_r search-result "`, so a
  // prefix-anchored selector passes today and breaks on any class reorder.
  const html =
    '<div class="search-result _0_SRI x">' +
    '<a class="__sri_title_link a" title="Example" href="https://example.com/"></a>' +
    '<div class="_0_DESC __sri-desc">a snippet</div></div>';

  assert.deepEqual(parseKagiHtml(html), [
    { position: 1, title: "Example", link: "https://example.com/", snippet: "a snippet" },
  ]);
});

test("parseKagiHtml returns nothing for a page with no result blocks", () => {
  assert.deepEqual(parseKagiHtml("<html><body>Sign in to continue</body></html>"), []);
});

test("searchKagi sends the session token as a cookie", async () => {
  let seenUrl = "";
  let seenCookie: string | null = null;
  const fetchImpl = (async (url: string, init: RequestInit) => {
    seenUrl = url;
    seenCookie = (init.headers as Record<string, string>).Cookie ?? null;
    return new Response(FIXTURE, { status: 200 });
  }) as unknown as typeof fetch;

  await searchKagi("tok123", PARAMS, fetchImpl);

  assert.equal(seenUrl, "https://kagi.com/html/search?q=rust+async+runtime");
  assert.equal(seenCookie, "kagi_session=tok123");
});

test("searchKagi caps results at --num", async () => {
  const response = await searchKagi("tok", { ...PARAMS, num: 3 }, stubFetch(FIXTURE));
  assert.equal(response.organic.length, 3);
});

test("searchKagi returns every result when num exceeds what Kagi gave back", async () => {
  const response = await searchKagi("tok", { ...PARAMS, num: 50 }, stubFetch(FIXTURE));
  assert.equal(response.organic.length, 13);
});

test("searchKagi maps a rejected token to a runtime error naming the token", async () => {
  await assert.rejects(
    () => searchKagi("bad", PARAMS, stubFetch("denied", { status: 401 })),
    (error: SerpAxiError) => {
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /rejected the session token \(401\)/);
      assert.match(error.help, /expired/);
      return true;
    },
  );
});

test("searchKagi maps rate limiting and upstream failures", async () => {
  await assert.rejects(
    () => searchKagi("tok", PARAMS, stubFetch("slow down", { status: 429 })),
    /rate-limited this request \(429\)/,
  );
  await assert.rejects(
    () => searchKagi("tok", PARAMS, stubFetch("boom", { status: 503 })),
    /upstream failure \(503\)/,
  );
});

test("searchKagi treats a 200 with no results as a likely expired token", async () => {
  // Kagi answers an expired session with a sign-in page and HTTP 200, so an
  // empty parse is the only signal that the token stopped working.
  await assert.rejects(
    () => searchKagi("tok", PARAMS, stubFetch("<html><body>Sign in</body></html>")),
    (error: SerpAxiError) => {
      assert.equal(error.kind, "runtime");
      assert.match(error.help, /session token has likely expired/);
      return true;
    },
  );
});

test("searchKagi wraps a network failure as a runtime error", async () => {
  const fetchImpl = (async () => {
    throw new Error("getaddrinfo ENOTFOUND kagi.com");
  }) as unknown as typeof fetch;

  await assert.rejects(() => searchKagi("tok", PARAMS, fetchImpl), /network error calling Kagi/);
});

test("the committed fixture carries no session token", () => {
  // The raw /html/search response embeds the live session token in its
  // opensearch link. This fixture is scrubbed; keep it that way.
  assert.doesNotMatch(FIXTURE, /opensearch\.xml\/[A-Za-z0-9_-]{20,}/);
});
