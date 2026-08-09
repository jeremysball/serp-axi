import { test } from "node:test";
import assert from "node:assert/strict";
import { searchSerper, scrapeSerper } from "./serper.ts";
import { SerperAxiError } from "./errors.ts";

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

test("searchSerper on an unmapped status uses the parsed message and not the raw body", async () => {
  const rawBody = JSON.stringify({ message: "Bad request", statusCode: 400 });
  const fetchImpl = (async () => new Response(rawBody, { status: 400 })) as typeof fetch;
  await assert.rejects(
    () => searchSerper("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /400/);
      assert.match(error.message, /Bad request/);
      assert.doesNotMatch(error.message, /\{"message"/);
      return true;
    },
  );
});

test("searchSerper wraps a non-JSON 200 body as a runtime error, not a SyntaxError", async () => {
  const fetchImpl = (async () => new Response("<html>not json</html>", { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchSerper("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /non-JSON/);
      return true;
    },
  );
});
