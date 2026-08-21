import { test } from "node:test";
import assert from "node:assert/strict";
import { runScrape } from "./scrape.ts";
import { SerpAxiError } from "../errors.ts";

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

test("runScrape rejects a missing URL before any network call", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(() => runScrape([], (async () => new Response("{}")) as typeof fetch), SerpAxiError);
  });
});

test("runScrape rejects a non-http(s) scheme", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["file:///etc/passwd"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects a loopback host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://127.0.0.1/secret"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects a private-range host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://192.168.1.5/"], (async () => new Response("{}")) as typeof fetch),
      SerpAxiError,
    );
  });
});

test("runScrape rejects any loopback /8 host, not just 127.0.0.1", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://127.0.0.2/"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects an IPv4-mapped IPv6 loopback host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://[::ffff:127.0.0.1]/"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects an IPv4-mapped IPv6 private-range host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://[::ffff:192.168.1.5]/"], (async () => new Response("{}")) as typeof fetch),
      SerpAxiError,
    );
  });
});

test("runScrape rejects a link-local host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://169.254.1.1/"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects a unique-local IPv6 host", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["http://[fc00::1]/"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape rejects extra positional arguments before any network call", async () => {
  await withApiKey("test-key", async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(
      () => runScrape(["https://example.com", "garbage"], fetchImpl),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        assert.match(error.message, /garbage/);
        return true;
      },
    );
    assert.equal(called, false);
  });
});

test("runScrape requires SERPER_API_KEY before any network call", async () => {
  await withApiKey(undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await assert.rejects(() => runScrape(["https://example.com"], fetchImpl), SerpAxiError);
    assert.equal(called, false);
  });
});

test("runScrape truncates to the default 1200-character limit", async () => {
  await withApiKey("test-key", async () => {
    const longText = "y".repeat(2000);
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ text: longText, metadata: { title: "Big Page" } }), { status: 200 })) as typeof fetch;
    const output = await runScrape(["https://example.com/big"], fetchImpl);
    assert.equal((output.text as string).length, 1200);
    assert.equal(output.title, "Big Page");
    assert.equal(output.truncatedFrom, 2000);
    assert.match(output.help as string, /--full/);
  });
});

test("runScrape --full raises the limit to 50000 characters", async () => {
  await withApiKey("test-key", async () => {
    const longText = "z".repeat(2000);
    const fetchImpl = (async () => new Response(JSON.stringify({ text: longText, metadata: {} }), { status: 200 })) as typeof fetch;
    const output = await runScrape(["https://example.com/big", "--full"], fetchImpl);
    assert.equal((output.text as string).length, 2000);
    assert.equal(output.truncatedFrom, undefined);
    assert.equal(output.title, undefined);
  });
});

async function withBrightData<T>(
  apiKey: string | undefined,
  datasetId: string | undefined,
  fn: () => Promise<T>,
): Promise<T> {
  const originalKey = process.env.BRIGHTDATA_API_KEY;
  const originalDataset = process.env.BRIGHTDATA_DATASET_ID;
  if (apiKey === undefined) delete process.env.BRIGHTDATA_API_KEY;
  else process.env.BRIGHTDATA_API_KEY = apiKey;
  if (datasetId === undefined) delete process.env.BRIGHTDATA_DATASET_ID;
  else process.env.BRIGHTDATA_DATASET_ID = datasetId;
  try {
    return await fn();
  } finally {
    if (originalKey === undefined) delete process.env.BRIGHTDATA_API_KEY;
    else process.env.BRIGHTDATA_API_KEY = originalKey;
    if (originalDataset === undefined) delete process.env.BRIGHTDATA_DATASET_ID;
    else process.env.BRIGHTDATA_DATASET_ID = originalDataset;
  }
}

test("runScrape rejects an unknown provider", async () => {
  await assert.rejects(
    () => runScrape(["https://example.com", "--provider", "yahoo"], (async () => new Response("[]")) as typeof fetch),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runScrape rejects --dataset-id with the default Serper provider", async () => {
  await withApiKey("test-key", async () => {
    await assert.rejects(
      () => runScrape(["https://example.com", "--dataset-id", "gd_x"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "usage");
        return true;
      },
    );
  });
});

test("runScrape requires a URL for Bright Data before any network call", async () => {
  await withBrightData("test-key", undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("[]");
    }) as typeof fetch;
    await assert.rejects(() => runScrape(["--provider", "brightdata"], fetchImpl), SerpAxiError);
    assert.equal(called, false);
  });
});

test("runScrape requires BRIGHTDATA_API_KEY before any network call", async () => {
  await withBrightData(undefined, undefined, async () => {
    let called = false;
    const fetchImpl = (async () => {
      called = true;
      return new Response("[]");
    }) as typeof fetch;
    await assert.rejects(
      () => runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl),
      SerpAxiError,
    );
    assert.equal(called, false);
  });
});

test("runScrape Bright Data batches URLs, applies the default dataset, and truncates fields", async () => {
  await withBrightData("test-key", undefined, async () => {
    let capturedUrl: string | undefined;
    let capturedBody: unknown;
    const longText = "m".repeat(2000);
    const fetchImpl = (async (url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedBody = JSON.parse(init?.body as string);
      return new Response(
        JSON.stringify([
          { url: "https://example.com", markdown: longText },
          { url: "https://example.com/1", markdown: "short" },
        ]),
        { status: 200 },
      );
    }) as typeof fetch;

    const output = await runScrape(
      ["https://example.com", "https://example.com/1", "--provider", "brightdata"],
      fetchImpl,
    );

    assert.match(capturedUrl as string, /dataset_id=gd_m6gjtfmeh43we6cqc/);
    assert.deepEqual((capturedBody as { input: unknown }).input, [
      { url: "https://example.com" },
      { url: "https://example.com/1" },
    ]);
    assert.equal(output.provider, "brightdata");
    assert.equal(output.datasetId, "gd_m6gjtfmeh43we6cqc");
    const results = output.results as Array<Record<string, unknown>>;
    assert.equal(results.length, 2);
    assert.equal((results[0].markdown as string).length, 1200);
    assert.equal(results[0].markdownTruncatedFrom, 2000);
    assert.match(results[0].help as string, /--provider brightdata --full/);
    assert.equal(results[1].markdown, "short");
    assert.equal(results[1].markdownTruncatedFrom, undefined);
  });
});

test("runScrape Bright Data preserves upstream truncation markers and quotes help URLs", async () => {
  await withBrightData("test-key", undefined, async () => {
    const fetchImpl = (async () =>
      new Response(
        JSON.stringify([
          {
            url: "https://example.com/$HOME/test",
            markdown: "m".repeat(2000),
            markdownTruncatedFrom: 9999,
            content: "c".repeat(2000),
          },
        ]),
      )) as typeof fetch;
    const output = await runScrape(["https://example.com/$HOME/test", "--provider", "brightdata"], fetchImpl);
    const result = (output.results as Array<Record<string, unknown>>)[0];

    assert.equal(result.markdownTruncatedFrom, 9999);
    assert.equal(result.contentTruncatedFrom, 2000);
    assert.match(result.help as string, /scrape 'https:\/\/example\.com\/\$HOME\/test' --provider brightdata --full/);
  });
});

test("runScrape Bright Data prefers --dataset-id over BRIGHTDATA_DATASET_ID", async () => {
  await withBrightData("test-key", "gd_from_env", async () => {
    let capturedUrl: string | undefined;
    const fetchImpl = (async (url: string) => {
      capturedUrl = url;
      return new Response("[]");
    }) as typeof fetch;
    const output = await runScrape(
      ["https://example.com", "--provider", "brightdata", "--dataset-id", "gd_from_flag"],
      fetchImpl,
    );
    assert.match(capturedUrl as string, /dataset_id=gd_from_flag/);
    assert.equal(output.datasetId, "gd_from_flag");
  });
});

test("runScrape Bright Data uses BRIGHTDATA_DATASET_ID when no flag is given", async () => {
  await withBrightData("test-key", "gd_from_env", async () => {
    let capturedUrl: string | undefined;
    const fetchImpl = (async (url: string) => {
      capturedUrl = url;
      return new Response("[]");
    }) as typeof fetch;
    const output = await runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl);
    assert.match(capturedUrl as string, /dataset_id=gd_from_env/);
    assert.equal(output.datasetId, "gd_from_env");
  });
});

test("runScrape Bright Data passes the full limit to the provider", async () => {
  await withBrightData("test-key", undefined, async () => {
    let capturedBody: unknown;
    const fetchImpl = (async (_url: string, init?: RequestInit) => {
      capturedBody = JSON.parse(init?.body as string);
      return new Response("[]");
    }) as typeof fetch;
    await runScrape(["https://example.com", "--provider", "brightdata", "--full"], fetchImpl);
    assert.equal((capturedBody as { limit_per_input: number }).limit_per_input, 50000);
  });
});

test("runScrape Bright Data preserves a bare-origin URL without adding a slash", async () => {
  await withBrightData("test-key", undefined, async () => {
    let capturedBody: unknown;
    const fetchImpl = (async (_url: string, init?: RequestInit) => {
      capturedBody = JSON.parse(init?.body as string);
      return new Response(JSON.stringify([{ url: "https://example.com", markdown: "x" }]));
    }) as typeof fetch;
    await runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl);
    assert.deepEqual((capturedBody as { input: unknown }).input, [{ url: "https://example.com" }]);
  });
});
