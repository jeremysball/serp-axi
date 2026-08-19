import { test } from "node:test";
import assert from "node:assert/strict";
import { searchBrightData } from "./brightdata.ts";
import { SerpAxiError } from "./errors.ts";

// Regression coverage for the code-review fixes to brightdata.ts's status
// mapping: outer HTTP 400/404 previously fell through to the generic
// "unexpected status" branch despite the code's own comment documenting a
// 400 "zone not found" response, and the envelope's inner status_code
// collapsed 429/5xx into the same generic message as the outer branch
// already avoids. Kept separate from brightdata.test.ts, which covers the
// original happy-path/401/429/500 behavior.

function envelope(statusCode: number, body: unknown): string {
  return JSON.stringify({ status_code: statusCode, headers: {}, body: JSON.stringify(body) });
}

test("searchBrightData gives a targeted hint on an outer 400 (bad zone)", async () => {
  const fetchImpl = (async () =>
    new Response('zone "typo_zone" not found', { status: 400 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /400/);
      assert.match(error.message, /not found/);
      assert.match(error.help, /BRIGHTDATA_ZONE|--zone/);
      return true;
    },
  );
});

test("searchBrightData gives a targeted hint on an outer 404", async () => {
  const fetchImpl = (async () => new Response("not found", { status: 404 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "hi", gl: "us", hl: "en", num: 5 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /404/);
      assert.match(error.help, /BRIGHTDATA_ZONE|--zone/);
      return true;
    },
  );
});

test("searchBrightData gives a rate-limit-specific message on an inner envelope 429", async () => {
  const fetchImpl = (async () => new Response(envelope(429, { organic: [] }), { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /rate-limited/);
      assert.match(error.message, /429/);
      return true;
    },
  );
});

test("searchBrightData gives an upstream-failure-specific message on an inner envelope 5xx", async () => {
  const fetchImpl = (async () => new Response(envelope(503, { organic: [] }), { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /upstream failure/);
      assert.match(error.message, /503/);
      return true;
    },
  );
});

test("searchBrightData still uses the generic message for an unmapped inner envelope status", async () => {
  const fetchImpl = (async () => new Response(envelope(302, { organic: [] }), { status: 200 })) as typeof fetch;
  await assert.rejects(
    () => searchBrightData("key", { q: "q", gl: "us", hl: "en", num: 1 }, fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /unexpected status 302/);
      return true;
    },
  );
});
