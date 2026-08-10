import { test } from "node:test";
import assert from "node:assert/strict";
import { runSearch } from "./search.ts";
import { SerperAxiError } from "../errors.ts";

async function withApiKey<T>(value: string | undefined, fn: () => Promise<T>): Promise<T> {
  const original = process.env.SERPER_API_KEY;
  if (value === undefined) delete process.env.SERPER_API_KEY;
  else process.env.SERPER_API_KEY = value;
  try {
    return await fn();
  } finally {
    if (original === undefined) delete process.env.SERPER_API_KEY;
    else process.env.SERPER_API_KEY = original;
  }
}

function fetchWithOrganic(organic: unknown[]): typeof fetch {
  return (async () => new Response(JSON.stringify({ organic }), { status: 200 })) as typeof fetch;
}

test("runSearch rejects an empty query before any network call", async () => {
  await withApiKey("test-key", async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runSearch([], fetchImpl), SerperAxiError);
    assert.equal(called, false);
  });
});

test("runSearch rejects --num outside 1..100", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runSearch(["q", "--num", "0"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runSearch rejects an unknown --fields value", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runSearch(["q", "--fields", "bogus"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerperAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runSearch applies defaults and truncates a long snippet", async () => {
  await withApiKey("test-key", async () => {
    const longSnippet = "x".repeat(250);
    const fetchImpl = fetchWithOrganic([{ position: 1, title: "t", link: "https://x", snippet: longSnippet }]);
    const output = await runSearch(["hello world"], fetchImpl);
    assert.equal(output.count, 1);
    const results = output.results as Array<Record<string, unknown>>;
    assert.equal((results[0].snippet as string).length, 200);
  });
});

test("runSearch includes an extra --fields value in the output rows", async () => {
  await withApiKey("test-key", async () => {
    const fetchImpl = fetchWithOrganic([
      { position: 1, title: "t", link: "https://x", snippet: "s", date: "2026-01-01" },
    ]);
    const output = await runSearch(["q", "--fields", "date"], fetchImpl);
    const results = output.results as Array<Record<string, unknown>>;
    assert.equal(results[0].date, "2026-01-01");
  });
});

test("runSearch reports a definitive zero-result state", async () => {
  await withApiKey("test-key", async () => {
    const fetchImpl = fetchWithOrganic([]);
    const output = await runSearch(["nothing here"], fetchImpl);
    assert.equal(output.count, 0);
    assert.match(output.results as string, /0 results found for query "nothing here"/);
  });
});

test("runSearch requires SERPER_API_KEY before any network call", async () => {
  await withApiKey(undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runSearch(["hi"], fetchImpl), SerperAxiError);
    assert.equal(called, false);
  });
});
