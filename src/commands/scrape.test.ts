import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runScrape } from "./scrape.ts";
import { SerpAxiError } from "../errors.ts";
import { INCLUDE_MARKUP_ENV } from "../scrape-output.ts";

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

// The env these process.env-driven tests hand to runScrape: what withBrightData
// set, minus the one setting a developer's shell might export. Paired with an
// empty config so no test reads the machine's real config file.
function hermeticEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  delete env[INCLUDE_MARKUP_ENV];
  return env;
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
      hermeticEnv(),
      {},
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
    const output = await runScrape(
      ["https://example.com/$HOME/test", "--provider", "brightdata"],
      fetchImpl,
      hermeticEnv(),
      {},
    );
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
      hermeticEnv(),
      {},
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
    const output = await runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl, hermeticEnv(), {});
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
    await runScrape(["https://example.com", "--provider", "brightdata", "--full"], fetchImpl, hermeticEnv(), {});
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
    await runScrape(["https://example.com", "--provider", "brightdata"], fetchImpl, hermeticEnv(), {});
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

// One behavioural assertion per provider that the shared path is the one in force:
// a record only a provider-specific shortcut could leave alone is shaped here.
const HTML_DOCUMENT = "<!doctype html><html><head><title>T</title></head><body>x</body></html>";

test("runScrape Serper omits a title that is a whole HTML document unless the flag or env keeps it", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ text: "plain page text", metadata: { title: HTML_DOCUMENT } }))) as typeof fetch;
  const env = { SERPER_API_KEY: "k" };

  const stripped = await runScrape(["https://example.com/a"], fetchImpl, env, {});
  assert.equal(Object.hasOwn(stripped, "title"), false);
  assert.deepEqual(stripped.markupOmitted, ["title"]);
  assert.equal(stripped.text, "plain page text");

  const viaFlag = await runScrape(["https://example.com/a", "--include-markup"], fetchImpl, env, {});
  assert.equal(viaFlag.title, HTML_DOCUMENT);
  const viaEnv = await runScrape(["https://example.com/a"], fetchImpl, { ...env, SERP_AXI_INCLUDE_MARKUP: "1" }, {});
  assert.equal(viaEnv.title, HTML_DOCUMENT);
});

test("runScrape --ladder omits a title that is a whole HTML document unless the flag or env keeps it", async () => {
  await withLadderStub("html-title", async () => {
    const fetchImpl = (async () => new Response("{}")) as typeof fetch;

    const stripped = await runScrape(["https://example.com/a", "--ladder"], fetchImpl, hermeticEnv(), {});
    assert.equal(Object.hasOwn(stripped, "title"), false);
    assert.deepEqual(stripped.markupOmitted, ["title"]);
    assert.equal(stripped.text, "plain body");

    const viaFlag = await runScrape(["https://example.com/a", "--ladder", "--include-markup"], fetchImpl, hermeticEnv(), {});
    assert.equal(viaFlag.title, HTML_DOCUMENT);
    const viaEnv = await runScrape(
      ["https://example.com/a", "--ladder"],
      fetchImpl,
      { ...hermeticEnv(), SERP_AXI_INCLUDE_MARKUP: "1" },
      {},
    );
    assert.equal(viaEnv.title, HTML_DOCUMENT);
  });
});

test("runScrape Bright Data rerun hint repeats the flags that shaped the record", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ url: "https://example.org/", markdown: "m".repeat(2000) }))) as typeof fetch;
  const helpFor = async (extra: string[], env: NodeJS.ProcessEnv = {}) =>
    brightDataResults(
      await runScrape(["https://example.org/", "--provider", "brightdata", ...extra], fetchImpl, { ...BRIGHT_DATA_ENV, ...env }, {}),
    )[0].help;
  const rerun = (flags: string) =>
    `Run \`serp-axi scrape 'https://example.org/' --provider brightdata${flags} --full\` to see up to 50000 characters (2000 total)`;

  assert.equal(await helpFor([]), rerun(""));
  assert.equal(await helpFor(["--dataset-id", "gd_x"]), rerun(" --dataset-id 'gd_x'"));
  assert.equal(await helpFor(["--include-markup"]), rerun(" --include-markup"));
  assert.equal(await helpFor([], { SERP_AXI_INCLUDE_MARKUP: "1" }), rerun(" --include-markup"));
  assert.equal(await helpFor(["--dataset-id", "gd_x", "--include-markup"]), rerun(" --dataset-id 'gd_x' --include-markup"));
});

test("runScrape --ladder rerun hint repeats the axis flags that were passed", async () => {
  await withLadderStub("ok", async () => {
    const url = `https://example.com/${"a".repeat(2000)}`;
    const fetchImpl = (async () => new Response("{}")) as typeof fetch;

    const output = await runScrape(
      [url, "--ladder", "--rung-ceiling", "2", "--tab-state", "same", "--include-markup"],
      fetchImpl,
      hermeticEnv(),
      {},
    );

    assert.match(
      output.help as string,
      new RegExp(`^Run \`serp-axi scrape '${url}' --ladder --tab-state 'same' --rung-ceiling '2' --include-markup --full\``),
    );
  });
});

test("runScrape Bright Data leaves a long url whole and unmarked", async () => {
  const url = `https://example.org/${"a".repeat(2500)}`;
  const fetchImpl = (async () => new Response(JSON.stringify({ url, markdown: "m" }))) as typeof fetch;

  const output = await runScrape([url, "--provider", "brightdata"], fetchImpl, { ...BRIGHT_DATA_ENV }, {});
  const result = brightDataResults(output)[0];

  assert.equal(result.url, url);
  assert.equal(Object.hasOwn(result, "urlTruncatedFrom"), false);
});

test("runScrape's extra-URL usage hint lists every flag the command takes", async () => {
  await assert.rejects(
    () =>
      runScrape(
        ["https://example.com/a", "https://example.com/b"],
        (async () => new Response("{}")) as typeof fetch,
        { SERPER_API_KEY: "k" },
        {},
      ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.help, /\[--full\] \[--include-markup\]/);
      return true;
    },
  );
});

// --- when the config file is read -------------------------------------------
// A config file that is not JSON. Any run that opens it fails with a "not valid
// JSON" usage error, so a test can tell "read the config" from "never looked".

async function withBrokenConfig(fn: (xdgConfigHome: string) => Promise<void>): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "serp-axi-config-"));
  try {
    mkdirSync(path.join(dir, "serp-axi"));
    writeFileSync(path.join(dir, "serp-axi", "config.json"), "{ not json");
    await fn(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("runScrape checks its input before it opens the config file", async () => {
  await withBrokenConfig(async (xdg) => {
    const fetchImpl = (async () => new Response("{}")) as typeof fetch;
    const keys: Record<string, string> = { SERPER_API_KEY: "k", BRIGHTDATA_API_KEY: "k" };
    const withoutKey = (name: string) => {
      const { [name]: _dropped, ...rest } = keys;
      return rest;
    };
    const cases: Array<{ name: string; args: string[]; env: NodeJS.ProcessEnv; expect: RegExp }> = [
      { name: "Serper, bad URL", args: ["not a url"], env: keys, expect: /is not a valid URL/ },
      { name: "Serper, no URL", args: [], env: keys, expect: /requires a URL/ },
      { name: "Serper, no key", args: ["https://example.com"], env: withoutKey("SERPER_API_KEY"), expect: /SERPER_API_KEY is not set/ },
      { name: "Bright Data, bad URL", args: ["not a url", "--provider", "brightdata"], env: keys, expect: /is not a valid URL/ },
      { name: "Bright Data, no URL", args: ["--provider", "brightdata"], env: keys, expect: /at least one URL/ },
      {
        name: "Bright Data, no key",
        args: ["https://example.com", "--provider", "brightdata"],
        env: withoutKey("BRIGHTDATA_API_KEY"),
        expect: /BRIGHTDATA_API_KEY is not set/,
      },
      { name: "ladder, bad URL", args: ["not a url", "--ladder"], env: keys, expect: /is not a valid URL/ },
      { name: "ladder, no URL", args: ["--ladder"], env: keys, expect: /requires a URL/ },
    ];
    for (const { name, args, env, expect } of cases) {
      await assert.rejects(() => runScrape(args, fetchImpl, { ...env, XDG_CONFIG_HOME: xdg }), expect, name);
    }
  });
});

test("runScrape opens the config file for Bright Data only once its input is valid", async () => {
  await withBrokenConfig(async (xdg) => {
    const fetchImpl = (async () => new Response(JSON.stringify({ url: "https://example.org/", markdown: "m" }))) as typeof fetch;
    await assert.rejects(
      () =>
        runScrape(["https://example.org/", "--provider", "brightdata"], fetchImpl, { ...BRIGHT_DATA_ENV, XDG_CONFIG_HOME: xdg }),
      /config file .* is not valid JSON/,
    );
  });
});

test("runScrape consults config includeMarkup for Bright Data and for no other path", async () => {
  const invalid = { includeMarkup: "yes" };
  const serperFetch = (async () =>
    new Response(JSON.stringify({ text: "plain page text", metadata: { title: "T" } }))) as typeof fetch;

  const serper = await runScrape(["https://example.com/a"], serperFetch, { SERPER_API_KEY: "k" }, invalid);
  assert.equal(serper.text, "plain page text");

  await withLadderStub("ok", async () => {
    const ladder = await runScrape(
      ["https://example.com/a", "--ladder"],
      (async () => new Response("{}")) as typeof fetch,
      hermeticEnv(),
      invalid,
    );
    assert.equal(ladder.verdict, "ok");
  });

  await assert.rejects(() => scrapeFixture([], {}, invalid), /includeMarkup must be a JSON boolean/);
});

test("runScrape --ladder reads the config file once, from the injected env", async () => {
  await withBrokenConfig(async (xdg) => {
    await withLadderStub("ok", async () => {
      await assert.rejects(
        () =>
          runScrape(
            ["https://example.com/a", "--ladder"],
            (async () => new Response("{}")) as typeof fetch,
            { ...hermeticEnv(), XDG_CONFIG_HOME: xdg },
          ),
        /config file .* is not valid JSON/,
      );
    });
  });
});
