import { test } from "node:test";
import assert from "node:assert/strict";
import { searchBrightData } from "./brightdata.ts";
import { SerpAxiError } from "./errors.ts";

function envelope(statusCode: number, body: unknown): string {
  return JSON.stringify({ status_code: statusCode, headers: {}, body: JSON.stringify(body) });
}

test("searchBrightData posts to the Bright Data endpoint with the default zone and returns organic results", async () => {
  let capturedUrl: string | undefined;
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    capturedUrl = url;
    capturedInit = init;
    return new Response(
      envelope(200, { organic: [{ rank: 1, title: "t", link: "https://x", description: "s" }] }),
      { status: 200 },
    );
  }) as typeof fetch;

  const result = await searchBrightData("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl);

  assert.equal(capturedUrl, "https://api.brightdata.com/request");
  assert.equal((capturedInit?.headers as Record<string, string>).Authorization, "Bearer key");
  const sentBody = JSON.parse(capturedInit?.body as string);
  assert.equal(sentBody.zone, "serp_api1");
  assert.equal(sentBody.format, "json");
  assert.equal(sentBody.data_format, "parsed");
  assert.match(sentBody.url, /^https:\/\/www\.google\.com\/search\?/);
  assert.match(sentBody.url, /q=hi/);
  assert.match(sentBody.url, /num=5/);
  assert.deepEqual(result.organic, [{ position: 1, title: "t", link: "https://x", snippet: "s" }]);
});

test("searchBrightData accepts a custom zone", async () => {
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (_url: string, init?: RequestInit) => {
    capturedInit = init;
    return new Response(envelope(200, { organic: [] }), { status: 200 });
  }) as typeof fetch;

  await searchBrightData("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl, "custom_zone");

  assert.equal(JSON.parse(capturedInit?.body as string).zone, "custom_zone");
});

test("searchBrightData maps a missing description to an empty snippet", async () => {
  const fetchImpl = (async () =>
    new Response(envelope(200, { organic: [{ rank: 1, title: "t", link: "https://x" }] }), {
      status: 200,
    })) as typeof fetch;

  const result = await searchBrightData("key", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl);

  assert.equal(result.organic[0].snippet, "");
});

test("searchBrightData throws a runtime error on a 401 (plain-text body)", async () => {
  const fetchImpl = (async () => new Response("Invalid token", { status: 401 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("bad", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /401/);
      return true;
    },
  );
});

test("searchBrightData throws a runtime error on a 400 (plain-text body)", async () => {
  const fetchImpl = (async () =>
    new Response('zone "nonexistent_zone_xyz" not found', { status: 400 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /400/);
      assert.match(error.message, /not found/);
      return true;
    },
  );
});

test("searchBrightData throws a runtime error on 429", async () => {
  const fetchImpl = (async () => new Response("rate limited", { status: 429 })) as typeof fetch;
  await assert.rejects(() => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerpAxiError);
});

test("searchBrightData throws a runtime error on 500", async () => {
  const fetchImpl = (async () => new Response("boom", { status: 500 })) as typeof fetch;
  await assert.rejects(() => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerpAxiError);
});

test("searchBrightData throws a runtime error when the envelope's own status_code is not 200", async () => {
  const fetchImpl = (async () => new Response(envelope(429, { organic: [] }), { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /429/);
      return true;
    },
  );
});

test("searchBrightData wraps a network failure as a runtime error", async () => {
  const fetchImpl = (async () => {
    throw new Error("getaddrinfo ENOTFOUND");
  }) as typeof fetch;
  await assert.rejects(() => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl), SerpAxiError);
});

test("searchBrightData wraps a non-JSON 200 body as a runtime error, not a SyntaxError", async () => {
  const fetchImpl = (async () => new Response("<html>not json</html>", { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /non-JSON/);
      return true;
    },
  );
});

test("searchBrightData wraps an unparseable envelope body string as a runtime error", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ status_code: 200, headers: {}, body: "not json" }), {
      status: 200,
    })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("k", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /not valid JSON/);
      return true;
    },
  );
});
