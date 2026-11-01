import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
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
        [
          JSON.stringify({ url: "https://example.com", markdown: longText }),
          JSON.stringify({ url: "https://example.com/1", markdown: "short" }),
        ].join("\n"),
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
        JSON.stringify({
          url: "https://example.com/$HOME/test",
          markdown: "m".repeat(2000),
          markdownTruncatedFrom: 9999,
          content: "c".repeat(2000),
        }),
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
      return new Response("");
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
      return new Response("");
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
      return new Response("");
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
      return new Response(JSON.stringify({ url: "https://example.com", markdown: "x" }));
    }) as typeof fetch;
    await runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl);
    assert.deepEqual((capturedBody as { input: unknown }).input, [{ url: "https://example.com" }]);
  });
});

async function withLadderStub<T>(mode: string, fn: () => Promise<T>): Promise<T> {
  const binKey = "SERP_AXI_LADDER_BIN";
  const modeKey = "LADDER_STUB_MODE";
  const originalBin = process.env[binKey];
  const originalMode = process.env[modeKey];
  process.env[binKey] = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "..",
    "fixtures",
    "ladder-stub-bin.sh",
  );
  process.env[modeKey] = mode;
  try {
    return await fn();
  } finally {
    if (originalBin === undefined) delete process.env[binKey];
    else process.env[binKey] = originalBin;
    if (originalMode === undefined) delete process.env[modeKey];
    else process.env[modeKey] = originalMode;
  }
}

test("runScrape --ladder returns rung text with no API key", async () => {
  await withLadderStub("ok", async () => {
    const output = await runScrape(
      ["https://example.com/article", "--ladder"],
      (async () => new Response("{}")) as typeof fetch,
    );
    assert.equal(output.verdict, "ok");
    assert.equal(output.rungReached, 1);
    assert.deepEqual(output.links, [{ url: "https://example.com/linked", text: "Linked" }]);
    assert.match(output.text as string, /example\.com\/article/);
  });
});

test("runScrape --ladder maps a blocked verdict to a typed runtime error", async () => {
  await withLadderStub("blocked", async () => {
    await assert.rejects(
      runScrape(["https://example.com/article", "--ladder"], (async () => new Response("{}")) as typeof fetch),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.equal(error.kind, "runtime");
        assert.match(error.message, /verdict: blocked/);
        return true;
      },
    );
  });
});

test("runScrape --ladder rejects --provider and multiple URLs", async () => {
  await withLadderStub("ok", async () => {
    await assert.rejects(
      runScrape(
        ["https://example.com/a", "--ladder", "--provider", "serper"],
        (async () => new Response("{}")) as typeof fetch,
      ),
      /--provider does not apply with --ladder/,
    );
    await assert.rejects(
      runScrape(
        ["https://example.com/a", "https://example.com/b", "--ladder"],
        (async () => new Response("{}")) as typeof fetch,
      ),
      /exactly one URL/,
    );
  });
});

test("runScrape rejects a ladder axis flag without --ladder instead of ignoring it", async () => {
  await assert.rejects(
    runScrape(
      ["https://example.com/article", "--tab-state", "same"],
      (async () => new Response("{}")) as typeof fetch,
    ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /--tab-state only applies with --ladder/);
      return true;
    },
  );
});

test("runScrape --ladder forwards the resolved axes onto the wire", async () => {
  await withLadderStub("echo-request", async () => {
    const output = await runScrape(
      ["https://example.com/article", "--ladder", "--tab-state", "same", "--rung-ceiling", "2",
        "--jar-in", "browser.json", "--http-jar-in", "session.in", "--http-jar-out", "session.out"],
      (async () => new Response("{}")) as typeof fetch,
    );
    const sent = JSON.parse(output.text as string) as Record<string, unknown>;
    assert.equal(sent.url, "https://example.com/article");
    assert.equal(sent.protocol, 3);
    assert.equal(sent.tabState, "same");
    assert.equal(sent.rungCeiling, 2);
    assert.equal(sent.jarIn, "browser.json");
    assert.equal(sent.jarOut, null);
    assert.equal(sent.httpJarIn, "session.in");
    assert.equal(sent.httpJarOut, "session.out");
  });
});

test("runScrape --ladder rejects an invalid axis value as a usage error", async () => {
  await assert.rejects(
    runScrape(
      ["https://example.com/article", "--ladder", "--rung-ceiling", "9"],
      (async () => new Response("{}")) as typeof fetch,
    ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /rung-ceiling "9"/);
      return true;
    },
  );
});

// --- markup stripping -------------------------------------------------------
// Settings are injected (env, config) so none of these touch process.env or
// the machine's real config file.

const FIXTURE_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const BRIGHT_DATA_ENV = { BRIGHTDATA_API_KEY: "test-key" };

function fixtureRecord(): Record<string, unknown> {
  const firstLine = readFileSync(path.join(FIXTURE_DIR, "brightdata-scrape.ndjson"), "utf8").split("\n")[0];
  return JSON.parse(firstLine) as Record<string, unknown>;
}

function brightDataResults(output: Record<string, unknown>): Array<Record<string, unknown>> {
  return output.results as Array<Record<string, unknown>>;
}

async function scrapeFixture(extraArgs: string[], env: NodeJS.ProcessEnv = {}, config: Record<string, unknown> = {}) {
  const fetchImpl = (async () => new Response(JSON.stringify(fixtureRecord()))) as typeof fetch;
  return runScrape(
    ["https://example.org/", "--provider", "brightdata", ...extraArgs],
    fetchImpl,
    { ...BRIGHT_DATA_ENV, ...env },
    config,
  );
}

test("runScrape Bright Data omits a real record's page_html by default and names it", async () => {
  const output = await scrapeFixture([]);
  const result = brightDataResults(output)[0];

  assert.deepEqual(result.markupOmitted, ["page_html"]);
  assert.equal(Object.hasOwn(result, "page_html"), false);
  assert.match(result.markdown as string, /^# Example Domain/);
  assert.match(result.html2text as string, /^EXAMPLE DOMAIN/);
  assert.match(result.help as string, /--provider brightdata --include-markup/);
});

test("runScrape Bright Data --include-markup keeps page_html and reports no omission", async () => {
  const output = await scrapeFixture(["--include-markup"]);
  const result = brightDataResults(output)[0];

  assert.match(result.page_html as string, /^<!doctype html>/);
  assert.equal(Object.hasOwn(result, "markupOmitted"), false);
});

test("runScrape reads SERP_AXI_INCLUDE_MARKUP, and the flag beats it", async () => {
  const kept = brightDataResults(await scrapeFixture([], { SERP_AXI_INCLUDE_MARKUP: "1" }))[0];
  const stripped = brightDataResults(await scrapeFixture([], { SERP_AXI_INCLUDE_MARKUP: "0" }))[0];
  const flagged = brightDataResults(await scrapeFixture(["--include-markup"], { SERP_AXI_INCLUDE_MARKUP: "0" }))[0];

  assert.deepEqual(stripped.markupOmitted, ["page_html"]);
  assert.equal(typeof kept.page_html, "string");
  assert.equal(typeof flagged.page_html, "string");
});

test("runScrape reads includeMarkup from config, and env beats it", async () => {
  const kept = brightDataResults(await scrapeFixture([], {}, { includeMarkup: true }))[0];
  const stripped = brightDataResults(await scrapeFixture([], { SERP_AXI_INCLUDE_MARKUP: "false" }, { includeMarkup: true }))[0];

  assert.equal(typeof kept.page_html, "string");
  assert.deepEqual(stripped.markupOmitted, ["page_html"]);
});

test("runScrape rejects a bad SERP_AXI_INCLUDE_MARKUP before any network call", async () => {
  let called = false;
  const fetchImpl = (async () => {
    called = true;
    return new Response("{}");
  }) as typeof fetch;
  await assert.rejects(
    () => runScrape(["https://example.com"], fetchImpl, { SERPER_API_KEY: "k", SERP_AXI_INCLUDE_MARKUP: "maybe" }, {}),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /SERP_AXI_INCLUDE_MARKUP/);
      return true;
    },
  );
  assert.equal(called, false);
});

test("runScrape Serper accepts --include-markup and returns the same record", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ text: "plain page text", metadata: { title: "T" } }))) as typeof fetch;
  const env = { SERPER_API_KEY: "k" };

  const plain = await runScrape(["https://example.com/a"], fetchImpl, env, {});
  const flagged = await runScrape(["https://example.com/a", "--include-markup"], fetchImpl, env, {});

  assert.equal(plain.text, "plain page text");
  assert.deepEqual(flagged, plain);
});

test("runScrape Serper help gives a quoted, runnable rerun command with the total", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ text: "y".repeat(2000), metadata: {} }))) as typeof fetch;

  const plain = await runScrape(["https://example.com/big"], fetchImpl, { SERPER_API_KEY: "k" }, {});
  const flagged = await runScrape(["https://example.com/big", "--include-markup"], fetchImpl, { SERPER_API_KEY: "k" }, {});

  assert.equal(plain.help, "Run `serp-axi scrape 'https://example.com/big' --full` to see up to 50000 characters (2000 total)");
  assert.equal(
    flagged.help,
    "Run `serp-axi scrape 'https://example.com/big' --include-markup --full` to see up to 50000 characters (2000 total)",
  );
});

test("runScrape --ladder accepts --include-markup and returns the same record", async () => {
  await withLadderStub("ok", async () => {
    const fetchImpl = (async () => new Response("{}")) as typeof fetch;
    const plain = await runScrape(["https://example.com/article", "--ladder"], fetchImpl, process.env, {});
    const flagged = await runScrape(["https://example.com/article", "--ladder", "--include-markup"], fetchImpl, process.env, {});

    assert.equal(plain.verdict, "ok");
    assert.deepEqual(flagged, plain);
  });
});

test("runScrape --ladder truncates through the shared path with a quoted, runnable rerun command", async () => {
  await withLadderStub("ok", async () => {
    const url = `https://example.com/${"a".repeat(2000)}`;
    const output = await runScrape([url, "--ladder"], (async () => new Response("{}")) as typeof fetch, process.env, {});

    assert.equal((output.text as string).length, 1200);
    assert.equal(output.truncatedFrom, `body for ${url}`.length);
    assert.match(output.help as string, new RegExp(`^Run \`serp-axi scrape '${url}' --ladder --full\``));
  });
});

test("scrape.ts routes every provider through shapeScrapeRecord and never truncates on its own", () => {
  const source = readFileSync(fileURLToPath(new URL("./scrape.ts", import.meta.url)), "utf8");

  assert.match(source, /shapeScrapeRecord\(/);
  assert.doesNotMatch(source, /\btruncate\(/);
  assert.doesNotMatch(source, /\bFULL_LIMIT\b\s*=/);
});
