import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runSearch } from "./search.ts";
import { SerpAxiError } from "../errors.ts";

// runSearch takes the env and the stored config as arguments, so these tests
// hand it both. Most of them never touch process.env or the machine's real
// config file. The ones that prove runSearch ignores the process's own values
// set a different value in process.env first (withProcessEnv), and the
// config-file tests point XDG_CONFIG_HOME at a temp directory. `{}` for the
// config means "no stored config"; leaving it unset makes a searxng run read
// a config file from the env it was handed (see runSearch).
const SERPER_ENV: NodeJS.ProcessEnv = { SERPER_API_KEY: "test-key" };
const BRIGHT_DATA_ENV: NodeJS.ProcessEnv = { BRIGHTDATA_API_KEY: "bd-key" };
const NO_CONFIG = {};
const KAGI_FIXTURE = readFileSync(
  fileURLToPath(new URL("../fixtures/kagi-html-search.html", import.meta.url)),
  "utf8",
);

function fetchWithOrganic(organic: unknown[]): typeof fetch {
  return (async () => new Response(JSON.stringify({ organic }), { status: 200 })) as typeof fetch;
}

interface BrightDataCapture {
  body?: string;
  authorization?: string;
}

function capturingBrightDataFetch(captured: BrightDataCapture, organic: unknown[] = []): typeof fetch {
  return (async (_url: string, init?: RequestInit) => {
    captured.body = init?.body as string;
    captured.authorization = (init?.headers as Record<string, string>).Authorization;
    return new Response(
      JSON.stringify({ status_code: 200, headers: {}, body: JSON.stringify({ organic }) }),
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

function recordingSearxngFetch(urls: string[]): typeof fetch {
  return (async (url: unknown) => {
    urls.push(String(url));
    return new Response(JSON.stringify({ results: [] }), { status: 200 });
  }) as typeof fetch;
}

// Writes `contents` to <tmp>/serp-axi/config.json and returns <tmp>, ready to
// hand to runSearch as XDG_CONFIG_HOME. The directory goes when the test ends.
function configHome(t: TestContext, contents: string): string {
  const xdg = mkdtempSync(path.join(tmpdir(), "serp-axi-search-config-"));
  t.after(() => rmSync(xdg, { recursive: true, force: true }));
  mkdirSync(path.join(xdg, "serp-axi"));
  writeFileSync(path.join(xdg, "serp-axi", "config.json"), contents);
  return xdg;
}

function isUsageError(error: unknown): boolean {
  assert.ok(error instanceof SerpAxiError);
  assert.equal(error.kind, "usage");
  return true;
}

// With an empty env the named provider must fail on its missing credential
// before it makes a request.
async function assertMissingCredential(provider: string, message: RegExp): Promise<void> {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(
    () => runSearch(["hi", "--provider", provider], fetchImpl, {}, NO_CONFIG),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, message);
      return true;
    },
  );
  assert.equal(calls(), 0);
}

test("runSearch rejects an empty query before any network call", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch([], fetchImpl, {}, NO_CONFIG), SerpAxiError);
  assert.equal(calls(), 0);
});

test("runSearch rejects --num outside 1..100", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch(["q", "--num", "0"], fetchImpl, {}, NO_CONFIG), isUsageError);
  assert.equal(calls(), 0);
});

test("runSearch rejects an unknown --fields value", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch(["q", "--fields", "bogus"], fetchImpl, {}, NO_CONFIG), isUsageError);
  assert.equal(calls(), 0);
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

test("runSearch rejects an unknown --provider value", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(() => runSearch(["q", "--provider", "bogus"], fetchImpl, {}, NO_CONFIG), isUsageError);
  assert.equal(calls(), 0);
});

test("runSearch rejects --fields combined with --provider brightdata", async () => {
  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(
    () => runSearch(["q", "--provider", "brightdata", "--fields", "date"], fetchImpl, {}, NO_CONFIG),
    isUsageError,
  );
  assert.equal(calls(), 0);
});

test("runSearch dispatches to Bright Data with the default zone when --provider brightdata", async () => {
  const captured: BrightDataCapture = {};
  const fetchImpl = capturingBrightDataFetch(captured, [
    { rank: 1, title: "t", link: "https://x", description: "s" },
  ]);
  const output = await runSearch(["hello world", "--provider", "brightdata"], fetchImpl, BRIGHT_DATA_ENV, NO_CONFIG);
  assert.equal(output.count, 1);
  assert.equal(JSON.parse(captured.body as string).zone, "serp_api1");
});

test("runSearch honors BRIGHTDATA_ZONE when --provider brightdata", async () => {
  const captured: BrightDataCapture = {};
  await runSearch(
    ["hello world", "--provider", "brightdata"],
    capturingBrightDataFetch(captured),
    { ...BRIGHT_DATA_ENV, BRIGHTDATA_ZONE: "custom_zone" },
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "custom_zone");
});

test("runSearch honors --zone when --provider brightdata", async () => {
  const captured: BrightDataCapture = {};
  await runSearch(
    ["hello world", "--provider", "brightdata", "--zone", "flag_zone"],
    capturingBrightDataFetch(captured),
    BRIGHT_DATA_ENV,
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "flag_zone");
});

test("runSearch prefers --zone over BRIGHTDATA_ZONE when both are set", async () => {
  const captured: BrightDataCapture = {};
  await runSearch(
    ["hello world", "--provider", "brightdata", "--zone", "flag_zone"],
    capturingBrightDataFetch(captured),
    { ...BRIGHT_DATA_ENV, BRIGHTDATA_ZONE: "env_zone" },
    NO_CONFIG,
  );
  assert.equal(JSON.parse(captured.body as string).zone, "flag_zone");
});

test("runSearch reports a definitive zero-result state via --provider brightdata", async () => {
  const output = await runSearch(
    ["nothing here", "--provider", "brightdata"],
    capturingBrightDataFetch({}),
    BRIGHT_DATA_ENV,
    NO_CONFIG,
  );
  assert.equal(output.count, 0);
  assert.match(output.results as string, /0 results found for query "nothing here"/);
});

// Everything below proves runSearch reads the env and config it is handed and
// not the process's own. Each test sets process.env to a value that differs
// from the injected one, so reading the global gives a different answer.

test("runSearch reads the Serper key from the env it is handed, not process.env", async () => {
  await withProcessEnv({ SERPER_API_KEY: "from-process" }, async () => {
    await assertMissingCredential("serper", /SERPER_API_KEY is not set/);

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
    await assertMissingCredential("brightdata", /BRIGHTDATA_API_KEY is not set/);

    const withZone: BrightDataCapture = {};
    await runSearch(
      ["hi", "--provider", "brightdata"],
      capturingBrightDataFetch(withZone),
      { BRIGHTDATA_API_KEY: "injected-key", BRIGHTDATA_ZONE: "injected_zone" },
      NO_CONFIG,
    );
    assert.equal(withZone.authorization, "Bearer injected-key");
    assert.equal(JSON.parse(withZone.body as string).zone, "injected_zone");

    // No zone in the handed env: the default applies, not the process's zone.
    const withoutZone: BrightDataCapture = {};
    await runSearch(["hi", "--provider", "brightdata"], capturingBrightDataFetch(withoutZone), BRIGHT_DATA_ENV, NO_CONFIG);
    assert.equal(JSON.parse(withoutZone.body as string).zone, "serp_api1");
  });
});

test("runSearch reads the Kagi token from the env it is handed, not process.env", async () => {
  await withProcessEnv({ KAGI_SESSION_TOKEN: "from-process" }, async () => {
    await assertMissingCredential("kagi", /KAGI_SESSION_TOKEN is not set/);

    let sentCookie: string | undefined;
    const cookieFetch = (async (_url: string, init?: RequestInit) => {
      sentCookie = (init?.headers as Record<string, string>).Cookie;
      return new Response(KAGI_FIXTURE, { status: 200 });
    }) as typeof fetch;
    const output = await runSearch(["hi", "--provider", "kagi"], cookieFetch, { KAGI_SESSION_TOKEN: "injected" }, NO_CONFIG);
    assert.equal(sentCookie, "kagi_session=injected");
    assert.ok((output.count as number) > 0);
  });
});

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

test("runSearch reads the searxng timeout from the env it is handed, not process.env", async () => {
  // The searxng timeout is validated when it is resolved, so a bad value in
  // one place and a good value in the other tells the two sources apart.
  await withProcessEnv({ SERP_AXI_SEARCH_TIMEOUT_MS: "5000" }, async () => {
    const { fetchImpl, calls } = countingFetch();
    await assert.rejects(
      () => runSearch(["q", "--provider", "searxng"], fetchImpl, { SERP_AXI_SEARCH_TIMEOUT_MS: "bogus" }, NO_CONFIG),
      (error: unknown) => {
        assert.ok(isUsageError(error));
        assert.match((error as SerpAxiError).message, /SERP_AXI_SEARCH_TIMEOUT_MS/);
        return true;
      },
    );
    assert.equal(calls(), 0);
  });

  await withProcessEnv({ SERP_AXI_SEARCH_TIMEOUT_MS: "bogus" }, async () => {
    const urls: string[] = [];
    await runSearch(
      ["q", "--provider", "searxng"],
      recordingSearxngFetch(urls),
      { SERP_AXI_SEARCH_TIMEOUT_MS: "5000" },
      NO_CONFIG,
    );
    assert.equal(urls.length, 1);
  });
});

test("runSearch opens the config file only when it is not handed a config", async (t) => {
  const env = { XDG_CONFIG_HOME: configHome(t, "{not json") };

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

test("runSearch opens the config file for searxng and for no other provider", async (t) => {
  const env = { ...SERPER_ENV, XDG_CONFIG_HOME: configHome(t, "{not json") };

  // Control: the same env and broken file stop a searxng run.
  await assert.rejects(
    () => runSearch(["q", "--provider", "searxng"], recordingSearxngFetch([]), env),
    /not valid JSON/,
  );

  const output = await runSearch(["q", "--provider", "serper"], fetchWithOrganic([]), env);
  assert.equal(output.count, 0);
});

test("runSearch checks its flags before it opens the config file", async (t) => {
  const env = { XDG_CONFIG_HOME: configHome(t, "{not json") };

  // Control: without the bad flag, the broken file is what stops the run.
  await assert.rejects(
    () => runSearch(["q", "--provider", "searxng"], recordingSearxngFetch([]), env),
    /not valid JSON/,
  );

  const { fetchImpl, calls } = countingFetch();
  await assert.rejects(
    () => runSearch(["q", "--provider", "searxng", "--num", "0"], fetchImpl, env),
    (error: unknown) => {
      assert.ok(isUsageError(error));
      assert.match((error as SerpAxiError).message, /--num/);
      return true;
    },
  );
  assert.equal(calls(), 0);
});

test("runSearch finds the config file through the env it is handed, not process.env", async (t) => {
  const real = configHome(t, JSON.stringify({ searxngUrl: "http://file.local" }));
  const decoy = configHome(t, JSON.stringify({ searxngUrl: "http://decoy.local" }));

  await withProcessEnv({ XDG_CONFIG_HOME: decoy }, async () => {
    const urls: string[] = [];
    await runSearch(["q", "--provider", "searxng"], recordingSearxngFetch(urls), { XDG_CONFIG_HOME: real });
    assert.equal(new URL(urls[0]).host, "file.local");
  });
});
