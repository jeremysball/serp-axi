import { test } from "node:test";
import assert from "node:assert/strict";
import { scrapeBrightData } from "./brightdata.ts";

const apiKey = process.env.BRIGHTDATA_API_KEY;

test("scrapeBrightData returns real records from the live API", { skip: !apiKey }, async () => {
  const results = await scrapeBrightData(apiKey as string, "gd_m6gjtfmeh43we6cqc", ["https://example.com"], 1200);
  assert.ok(Array.isArray(results));
  assert.ok(results.length > 0);
});
