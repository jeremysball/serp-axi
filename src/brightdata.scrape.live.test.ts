import { test } from "node:test";
import assert from "node:assert/strict";
import { scrapeBrightData } from "./brightdata.ts";

const apiKey = process.env.BRIGHTDATA_API_KEY;

test("scrapeBrightData returns real records from the live API", { skip: !apiKey }, async () => {
  const results = await scrapeBrightData(
    apiKey as string,
    "gd_m6gjtfmeh43we6cqc",
    ["https://example.org", "https://example.com"],
    1200,
  );
  assert.equal(results.length, 2);
  const urls = results.map((r) => r.url).sort();
  assert.deepEqual(urls, ["https://example.com/", "https://example.org/"]);
  for (const record of results) {
    assert.match(record.markdown as string, /Example Domain/);
  }
});
