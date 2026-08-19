import { test } from "node:test";
import assert from "node:assert/strict";
import { searchBrightData } from "./brightdata.ts";

const apiKey = process.env.BRIGHTDATA_API_KEY;

test("searchBrightData returns real organic results from the live API", { skip: !apiKey }, async () => {
  const response = await searchBrightData(apiKey as string, { q: "openai", gl: "us", hl: "en", num: 3 });
  assert.ok(Array.isArray(response.organic));
  assert.ok(response.organic.length > 0);
  assert.ok(typeof response.organic[0].title === "string");
});

test("searchBrightData surfaces a 401 for a bad key against the live API", { skip: !apiKey }, async () => {
  await assert.rejects(
    () => searchBrightData("invalid-key-serp-axi-test", { q: "test", gl: "us", hl: "en", num: 1 }),
    (error: unknown) => {
      assert.match((error as Error).message, /401/);
      return true;
    },
  );
});
