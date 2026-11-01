import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { runSearch } from "./search.ts";
import { SerpAxiError } from "../errors.ts";

// runSearch takes the env and the stored config as arguments, so these tests
// hand it both and never touch process.env or the machine's real config file.
// `{}` for the config means "no stored config"; leaving it unset would make
// runSearch read the developer's own file when the provider is searxng.
const SERPER_ENV: NodeJS.ProcessEnv = { SERPER_API_KEY: "test-key" };
const BRIGHT_DATA_ENV: NodeJS.ProcessEnv = { BRIGHTDATA_API_KEY: "bd-key" };
const NO_CONFIG = {};

function fetchWithOrganic(organic: unknown[]): typeof fetch {
  return (async () => new Response(JSON.stringify({ organic }), { status: 200 })) as typeof fetch;
}

function fetchWithBrightDataOrganic(organic: unknown[]): typeof fetch {
  return (async () =>
    new Response(
      JSON.stringify({ status_code: 200, headers: {}, body: JSON.stringify({ organic }) }),
      { status: 200 },
    )) as typeof fetch;
}

function bodyCapturingBrightDataFetch(captured: { body?: string }): typeof fetch {
  return (async (_url: string, init?: RequestInit) => {
    captured.body = init?.body as string;
    return new Response(
      JSON.stringify({ status_code: 200, headers: {}, body: JSON.stringify({ organic: [] }) }),
      { status: 200 },
    );
  }) as typeof fetch;
}

// Sets process.env keys for the length of fn, then puts them back. Only the
// tests that prove runSearch ignores process.env use it: they set a value that
// differs from the one they inject, so a read of the global shows up as a
// wrong answer rather than a coincidence.
async function withProcessEnv<T>(poison: Record<string, string>, fn: () => Promise<T>): Promise<T> {
  const originals = Object.keys(poison).map((name) => [name, process.env[name]] as const);
  Object.assign(process.env, poison);
  try {
    return await fn();
  } finally {
    for (const [name, value] of originals) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

function countingFetch(): { fetchImpl: typeof fetch; calls: () => number } {
  let called = 0;
  const fetchImpl = (async () => {
    called++;
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  return { fetchImpl, calls: () => called };
}

test("runSearch rejects an empty query before any network call", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch([], fetchImpl, SERPER_ENV, NO_CONFIG), SerpAxiError);
  assert.equal(calls(), 0);
});

test("runSearch rejects --num outside 1..100", async () => {
  await assert.rejects(
    () => runSearch(["q", "--num", "0"], (async () => new Response("{}")) as typeof fetch, SERPER_ENV, NO_CONFIG),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runSearch rejects an unknown --fields value", async () => {
  await assert.rejects(
    () => runSearch(["q", "--fields", "bogus"], (async () => new Response("{}")) as typeof fetch, SERPER_ENV, NO_CONFIG),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runSearch applies defaults and truncates a long snippet", async () => {
  const longSnippet = "x".repeat(250);
  const fetchImpl = fetchWithOrganic([{ position: 1, title: "t", link: "https://x", snippet: longSnippet }]);
  const output = await runSearch(["hello world", "--provider", "serper"], fetchImpl, SERPER_ENV, NO_CONFIG);
  assert.equal(output.count, 1);
  const results = output.results as Array<Record<string, unknown>>;
  assert.equal((results[0].snippet as string).length, 200);
});

test("runSearch includes an extra --fields value in the output rows", async () => {
  const fetchImpl = fetchWithOrganic([
    { position: 1, title: "t", link: "https://x", snippet: "s", date: "2026-01-01" },
  ]);
  const output = await runSearch(["q", "--provider", "serper", "--fields", "date"], fetchImpl, SERPER_ENV, NO_CONFIG);
  const results = output.results as Array<Record<string, unknown>>;
  assert.equal(results[0].date, "2026-01-01");
});

test("runSearch reports a definitive zero-result state", async () => {
  const fetchImpl = fetchWithOrganic([]);
  const output = await runSearch(["nothing here", "--provider", "serper"], fetchImpl, SERPER_ENV, NO_CONFIG);
  assert.equal(output.count, 0);
  assert.match(output.results as string, /0 results found for query "nothing here"/);
});

test("runSearch requires SERPER_API_KEY before any network call", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch(["hi", "--provider", "serper"], fetchImpl, {}, NO_CONFIG), SerpAxiError);
  assert.equal(calls(), 0);
});

test("runSearch rejects an unknown --provider value", async () => {
  await assert.rejects(
    () => runSearch(["q", "--provider", "bogus"], (async () => new Response("{}")) as typeof fetch, SERPER_ENV, NO_CONFIG),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runSearch rejects --fields combined with --provider brightdata", async () => {
  await assert.rejects(
    () =>
      runSearch(
        ["q", "--provider", "brightdata", "--fields", "date"],
        (async () => new Response("{}")) as typeof fetch,
        BRIGHT_DATA_ENV,
        NO_CONFIG,
      ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runSearch requires BRIGHTDATA_API_KEY before any network call when --provider brightdata", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(
    () => runSearch(["hi", "--provider", "brightdata"], fetchImpl, {}, NO_CONFIG),
    SerpAxiError,
  );
  assert.equal(calls(), 0);
});

test("runSearch dispatches to Bright Data with the default zone when --provider brightdata", async () => {
  const captured: { body?: string } = {};
  const fetchImpl = (async (_url: string, init?: RequestInit) => {
    captured.body = init?.body as string;
    return new Response(
      JSON.stringify({
        status_code: 200,
        headers: {},
        body: JSON.stringify({ organic: [{ rank: 1, title: "t", link: "https://x", description: "s" }] }),
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  const output = await runSearch(["hello world", "--provider", "brightdata"], fetchImpl, BRIGHT_DATA_ENV, NO_CONFIG);
  assert.equal(output.count, 1);
  assert.equal(JSON.parse(captured.body as string).zone, "serp_api1");
});

test("runSearch honors BRIGHTDATA_ZONE when --provider brightdata", async () => {
  const captured: { body?: string } = {};
  await runSearch(
    ["hello world", "--provider", "brightdata"],
    bodyCapturingBrightDataFetch(captured),
    { ...BRIGHT_DATA_ENV, BRIGHTDATA_ZONE: "custom_zone" },
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "custom_zone");
});

test("runSearch honors --zone when --provider brightdata", async () => {
  const captured: { body?: string } = {};
  await runSearch(
    ["hello world", "--provider", "brightdata", "--zone", "flag_zone"],
    bodyCapturingBrightDataFetch(captured),
    BRIGHT_DATA_ENV,
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "flag_zone");
});

test("runSearch prefers --zone over BRIGHTDATA_ZONE when both are set", async () => {
  const captured: { body?: string } = {};
  await runSearch(
    ["hello world", "--provider", "brightdata", "--zone", "flag_zone"],
    bodyCapturingBrightDataFetch(captured),
    { ...BRIGHT_DATA_ENV, BRIGHTDATA_ZONE: "env_zone" },
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "flag_zone");
});

test("runSearch reports a definitive zero-result state via --provider brightdata", async () => {
  const fetchImpl = fetchWithBrightDataOrganic([]);
  const output = await runSearch(["nothing here", "--provider", "brightdata"], fetchImpl, BRIGHT_DATA_ENV, NO_CONFIG);
  assert.equal(output.count, 0);
  assert.match(output.results as string, /0 results found for query "nothing here"/);
});

// Everything below proves runSearch reads the env and config it is handed and
// not the process's own. Each test sets process.env to a value that differs
// from the injected one, so reading the global gives a different answer.

test("runSearch reads the Serper key from the env it is handed, not process.env", async () => {
  await withProcessEnv({ SERPER_API_KEY: "from-process" }, async () => {
    const { fetchImpl, calls } = countingFetch();
    await assert.rejects(
      () => runSearch(["hi", "--provider", "serper"], fetchImpl, {}, NO_CONFIG),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.match(error.message, /SERPER_API_KEY is not set/);
        return true;
      },
    );
    assert.equal(calls(), 0);

    let sentKey: string | undefined;
    const keyedFetch = (async (_url: string, init?: RequestInit) => {
      sentKey = (init?.headers as Record<string, string>)["X-API-KEY"];
      return new Response(JSON.stringify({ organic: [] }), { status: 200 });
    }) as typeof fetch;
    await runSearch(["hi", "--provider", "serper"], keyedFetch, { SERPER_API_KEY: "injected" }, NO_CONFIG);
    assert.equal(sentKey, "injected");
  });
});

test("runSearch reads the Bright Data key and zone from the env it is handed, not process.env", async () => {
  await withProcessEnv({ BRIGHTDATA_API_KEY: "from-process", BRIGHTDATA_ZONE: "process_zone" }, async () => {
    const { fetchImpl, calls } = countingFetch();
    await assert.rejects(
      () => runSearch(["hi", "--provider", "brightdata"], fetchImpl, {}, NO_CONFIG),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.match(error.message, /BRIGHTDATA_API_KEY is not set/);
        return true;
      },
    );
    assert.equal(calls(), 0);

    const withZone: { body?: string } = {};
    await runSearch(
      ["hi", "--provider", "brightdata"],
      bodyCapturingBrightDataFetch(withZone),
      { ...BRIGHT_DATA_ENV, BRIGHTDATA_ZONE: "injected_zone" },
      NO_CONFIG,
    );
    assert.equal(JSON.parse(withZone.body as string).zone, "injected_zone");

    const withoutZone: { body?: string } = {};
    await runSearch(["hi", "--provider", "brightdata"], bodyCapturingBrightDataFetch(withoutZone), BRIGHT_DATA_ENV, NO_CONFIG);
    assert.equal(JSON.parse(withoutZone.body as string).zone, "serp_api1");
  });
});

test("runSearch reads the Kagi token from the env it is handed, not process.env", async () => {
  await withProcessEnv({ KAGI_SESSION_TOKEN: "from-process" }, async () => {
    const { fetchImpl, calls } = countingFetch();
    await assert.rejects(
      () => runSearch(["hi", "--provider", "kagi"], fetchImpl, {}, NO_CONFIG),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError);
        assert.match(error.message, /KAGI_SESSION_TOKEN is not set/);
        return true;
      },
    );
    assert.equal(calls(), 0);
  });
});

function recordingSearxngFetch(urls: string[]): typeof fetch {
  return (async (url: unknown) => {
    urls.push(String(url));
    return new Response(JSON.stringify({ results: [] }), { status: 200 });
  }) as typeof fetch;
}

test("runSearch resolves searxng settings from the env and config it is handed, not process.env", async () => {
  await withProcessEnv(
    { SERP_AXI_SEARXNG_URL: "http://process.local", SERP_AXI_SEARXNG_ENGINES: "process-e" },
    async () => {
      const urls: string[] = [];
      const fetchImpl = recordingSearxngFetch(urls);
      const config = { searxngUrl: "http://config.local", searxngEngines: ["cfg-e"] };

      await runSearch(["q", "--provider", "searxng"], fetchImpl, {}, config);
      const fromConfig = new URL(urls[0]);
      assert.equal(fromConfig.host, "config.local");
      assert.equal(fromConfig.searchParams.get("engines"), "cfg-e");

      await runSearch(["q", "--provider", "searxng"], fetchImpl, { SERP_AXI_SEARXNG_URL: "http://env.local" }, config);
      const fromEnv = new URL(urls[1]);
      assert.equal(fromEnv.host, "env.local");
      assert.equal(fromEnv.searchParams.get("engines"), "cfg-e");
    },
  );
});

test("runSearch opens the config file only when it is not handed a config", async (t) => {
  const xdg = mkdtempSync(path.join(tmpdir(), "serp-axi-search-config-"));
  t.after(() => rmSync(xdg, { recursive: true, force: true }));
  mkdirSync(path.join(xdg, "serp-axi"));
  writeFileSync(path.join(xdg, "serp-axi", "config.json"), "{not json");
  const env = { XDG_CONFIG_HOME: xdg };

  // Control: with no config handed in, the broken file is read and rejected.
  const urls: string[] = [];
  await assert.rejects(
    () => runSearch(["q", "--provider", "searxng"], recordingSearxngFetch(urls), env),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /not valid JSON/);
      return true;
    },
  );
  assert.equal(urls.length, 0);

  // With a config handed in, the same broken file is never opened.
  await runSearch(
    ["q", "--provider", "searxng"],
    recordingSearxngFetch(urls),
    env,
    { searxngUrl: "http://config.local" },
  );
  assert.equal(urls.length, 1);
  assert.equal(new URL(urls[0]).host, "config.local");
});

test("runSearch finds the config file through the env it is handed, not process.env", async (t) => {
  const real = mkdtempSync(path.join(tmpdir(), "serp-axi-search-real-"));
  const decoy = mkdtempSync(path.join(tmpdir(), "serp-axi-search-decoy-"));
  t.after(() => {
    rmSync(real, { recursive: true, force: true });
    rmSync(decoy, { recursive: true, force: true });
  });
  mkdirSync(path.join(real, "serp-axi"));
  writeFileSync(path.join(real, "serp-axi", "config.json"), JSON.stringify({ searxngUrl: "http://file.local" }));

  await withProcessEnv({ XDG_CONFIG_HOME: decoy }, async () => {
    const urls: string[] = [];
    await runSearch(["q", "--provider", "searxng"], recordingSearxngFetch(urls), { XDG_CONFIG_HOME: real });
    assert.equal(new URL(urls[0]).host, "file.local");
  });
});
