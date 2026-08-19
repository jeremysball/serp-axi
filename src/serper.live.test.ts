import { test } from "node:test";
import assert from "node:assert/strict";
import { searchSerper, scrapeSerper } from "./serper.ts";

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
    () => searchSerper("invalid-key-serp-axi-test", { q: "test", gl: "us", hl: "en", num: 1 }),
    (error: unknown) => {
      assert.match((error as Error).message, /403/);
      return true;
    },
  );
});
