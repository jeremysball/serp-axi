import { test } from "node:test";
import assert from "node:assert/strict";
import { scrapeBrightData } from "./brightdata.ts";
import { SerpAxiError } from "./errors.ts";

function fakeFetch(status: number, body: unknown): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
}

test("scrapeBrightData posts a batch of URLs with the requested character limit", async () => {
  let capturedUrl: string | undefined;
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    capturedUrl = url;
    capturedInit = init;
    return new Response(JSON.stringify([{ url: "https://example.com", markdown: "hi" }]), { status: 200 });
  }) as typeof fetch;

  const result = await scrapeBrightData(
    "key",
    "gd_m6gjtfmeh43we6cqc",
    ["https://example.com", "https://example.com/1"],
    1200,
    fetchImpl,
  );

  assert.equal(
    capturedUrl,
    "https://api.brightdata.com/datasets/v3/scrape?dataset_id=gd_m6gjtfmeh43we6cqc&notify=false&include_errors=true",
  );
  assert.equal((capturedInit?.headers as Record<string, string>).Authorization, "Bearer key");
  const body = JSON.parse(capturedInit?.body as string);
  assert.deepEqual(body.input, [{ url: "https://example.com" }, { url: "https://example.com/1" }]);
  assert.equal(body.limit_per_input, 1200);
  assert.equal(result.length, 1);
});

test("scrapeBrightData passes the full character limit through to Bright Data", async () => {
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (_url: string, init?: RequestInit) => {
    capturedInit = init;
    return new Response(JSON.stringify([]), { status: 200 });
  }) as typeof fetch;

  await scrapeBrightData("key", "gd_x", ["https://example.com"], 50000, fetchImpl);
  assert.equal(JSON.parse(capturedInit?.body as string).limit_per_input, 50000);
});

test("scrapeBrightData maps authentication failures and preserves a bounded detail", async () => {
  const fetchImpl = fakeFetch(401, { message: "API key expired" });
  await assert.rejects(
    () => scrapeBrightData("bad", "gd_x", ["https://example.com"], 1200, fetchImpl),
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
    () => scrapeBrightData("key", "gd_missing", ["https://example.com"], 1200, fakeFetch(404, {})),
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
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], 1200, fakeFetch(429, {})),
    (error: unknown) => error instanceof SerpAxiError && /rate-limited/.test(error.message),
  );
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], 1200, fakeFetch(502, {})),
    (error: unknown) => error instanceof SerpAxiError && /upstream failure/.test(error.message),
  );
});

test("scrapeBrightData rejects non-JSON and non-array successful responses", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], 1200, (async () => new Response("not json")) as typeof fetch),
    (error: unknown) => error instanceof SerpAxiError && /non-JSON/.test(error.message),
  );
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], 1200, fakeFetch(200, { not: "an array" })),
    (error: unknown) => error instanceof SerpAxiError && /array of records/.test(error.message),
  );
});

test("scrapeBrightData rejects non-object records", async () => {
  await assert.rejects(
    () => scrapeBrightData("key", "gd_x", ["https://example.com"], 1200, fakeFetch(200, [{ url: "https://example.com" }, null])),
    (error: unknown) => error instanceof SerpAxiError && /invalid record shape/.test(error.message),
  );
});
