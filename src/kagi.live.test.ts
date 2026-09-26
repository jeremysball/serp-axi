import { test } from "node:test";
import assert from "node:assert/strict";
import { searchKagi } from "./kagi.ts";

const token = process.env.KAGI_SESSION_TOKEN;

test("searchKagi returns real organic results from the live SERP", { skip: !token }, async () => {
  const response = await searchKagi(token as string, { q: "openai", gl: "us", hl: "en", num: 3 });
  assert.equal(response.organic.length, 3);
  for (const result of response.organic) {
    assert.ok(typeof result.title === "string" && result.title.length > 0);
    assert.match(result.link, /^https?:\/\//);
  }
});

test("searchKagi rejects a bad session token against the live SERP", { skip: !token }, async () => {
  // An invalid token gets a 200 sign-in page rather than a 401, so the
  // no-results path is what actually fires here.
  await assert.rejects(() => searchKagi("invalid-token-serp-axi-test", { q: "test", gl: "us", hl: "en", num: 1 }));
});
