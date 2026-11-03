import { test } from "node:test";
import assert from "node:assert/strict";
import { scrapeBrightData } from "./brightdata.ts";
import { SerpAxiError } from "./errors.ts";
import { brightDataScrapeNdjson } from "./fixtures.ts";

const FIXTURE = brightDataScrapeNdjson();

function fakeFetch(status: number, body: string): typeof fetch {
  return (async () => new Response(body, { status })) as typeof fetch;
}

test("scrapeBrightData posts a batch of URLs and puts nothing else in the body", async () => {
  let capturedUrl: string | undefined;
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    capturedUrl = url;
    capturedInit = init;
    return new Response(JSON.stringify({ url: "https://example.com", markdown: "hi" }), { status: 200 });
  }) as typeof fetch;

  const result = await scrapeBrightData(
    "key",
    "gd_m6gjtfmeh43we6cqc",
    ["https://example.com", "https://example.com/1"],
    fetchImpl,
  );

  assert.equal(
    capturedUrl,
    "https://api.brightdata.com/datasets/v3/scrape?dataset_id=gd_m6gjtfmeh43we6cqc&notify=false&include_errors=true",
  );
  assert.equal((capturedInit?.headers as Record<string, string>).Authorization, "Bearer key");
  const body = JSON.parse(capturedInit?.body as string);
  assert.deepEqual(body.input, [{ url: "https://example.com" }, { url: "https://example.com/1" }]);
  // Bright Data documents `limit_per_input` as a record count for discovery
  // requests (docs/things-that-look-like-bugs.md), so a character cap must not
  // ride in it. The body is the inputs and nothing else.
  assert.deepEqual(Object.keys(body), ["input"]);
  assert.equal(result.length, 1);
});

test("scrapeBrightData parses the real NDJSON response shape from the live API", async () => {
  const fetchImpl = (async () => new Response(FIXTURE, { status: 200 })) as typeof fetch;

  const result = await scrapeBrightData("key", "gd_m6gjtfmeh43we6cqc", ["https://example.org", "https://example.com"], fetchImpl);

  assert.equal(result.length, 2);
  assert.equal(result[0].url, "https://example.org/");
  assert.equal(result[1].url, "https://example.com/");
  assert.equal(result[0].page_title, "Example Domain");
  assert.match(result[0].markdown as string, /Example Domain/);
  assert.deepEqual(result[0].input, { url: "https://example.org" });
});

test("scrapeBrightData maps authentication failures and preserves a bounded detail", async () => {
  const fetchImpl = fakeFetch(401, JSON.stringify({ message: "API key expired" }));
  await assert.rejects(
    () => scrapeBrightData("bad", "gd_x", ["https://example.com"], fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "runtime");
      assert.match(error.message, /401/);
      assert.match(error.message, /API key expired/);
      return true;
    },
  );
});

test("scrapeBrightData maps a missing dataset to an actionable error", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_missing", ["https://example.com"], fakeFetch(404, "{}")),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /gd_missing/);
      assert.match(error.help, /BRIGHTDATA_DATASET_ID/);
      return true;
    },
  );
});

test("scrapeBrightData maps rate limits and upstream failures", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], fakeFetch(429, "{}")),
    (error: unknown) => error instanceof SerpAxiError && /rate-limited/.test(error.message),
  );
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], fakeFetch(502, "{}")),
    (error: unknown) => error instanceof SerpAxiError && /upstream failure/.test(error.message),
  );
});

test("scrapeBrightData rejects non-JSON and non-object successful responses", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], (async () => new Response("not json")) as typeof fetch),
    (error: unknown) => error instanceof SerpAxiError && /non-JSON line/.test(error.message),
  );
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], fakeFetch(200, "not json")),
    (error: unknown) => error instanceof SerpAxiError && /non-JSON line/.test(error.message),
  );
});

test("scrapeBrightData rejects non-object records", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], fakeFetch(200, "null")),
    (error: unknown) => error instanceof SerpAxiError && /invalid record shape/.test(error.message),
  );
});
