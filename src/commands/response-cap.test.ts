import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { MAX_RESPONSE_BYTES_ENV } from "../body.ts";
import { SerpAxiError } from "../errors.ts";
import { kagiSearchHtml } from "../fixtures.ts";
import { runScrape } from "./scrape.ts";
import { runSearch } from "./search.ts";

/**
 * The byte cap on provider responses, driven through the two commands: where it
 * is read from, what wins, what fails before the network, and which runs ignore
 * which home. What the cap does to a body is in `body.test.ts` and
 * `body.socket.test.ts`.
 */

const BODY_BYTES = 5000;
const SMALL_CAP = "1000";
const BIG_CAP = "100000";

interface Served {
  fetchImpl: typeof fetch;
  calls: { count: number };
}

// A provider stub that serves `text` as the body and counts its calls.
function serving(text: string, headers: Record<string, string> = {}): Served {
  const calls = { count: 0 };
  const fetchImpl = (async () => {
    calls.count += 1;
    return new Response(text, { status: 200, headers });
  }) as typeof fetch;
  return { fetchImpl, calls };
}

const PAD = "p".repeat(BODY_BYTES);
const SERPER_SEARCH = JSON.stringify({ organic: [], pad: PAD });
const SERPER_SCRAPE = JSON.stringify({ text: PAD, metadata: {} });
const BRIGHT_DATA_SEARCH = JSON.stringify({ status_code: 200, body: JSON.stringify({ organic: [], pad: PAD }) });
const BRIGHT_DATA_SCRAPE = JSON.stringify({ url: "https://example.com", markdown: PAD });
const SEARXNG_SEARCH = JSON.stringify({ results: [], pad: PAD });
// The recorded page, 53 KB: over SMALL_CAP, under BIG_CAP, and a page Kagi parsing accepts.
const KAGI_SEARCH = kagiSearchHtml();

const KEYS: NodeJS.ProcessEnv = {
  SERPER_API_KEY: "k",
  BRIGHTDATA_API_KEY: "k",
  KAGI_SESSION_TOKEN: "k",
};

function capError(pattern: RegExp) {
  return (error: unknown) => {
    assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
    assert.equal(error.kind, "runtime");
    assert.match(error.message, pattern);
    return true;
  };
}

function usageError(pattern: RegExp) {
  return (error: unknown) => {
    assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
    assert.equal(error.kind, "usage");
    assert.match(error.message, pattern);
    return true;
  };
}

type Run = (extraArgs: string[], env: NodeJS.ProcessEnv, config: Record<string, unknown>) => Promise<unknown>;

interface Case {
  name: string;
  body: string;
  run: (served: Served) => Run;
  /** Whether this run opens the config file, and so honors the `maxResponseBytes` key. */
  readsConfig: boolean;
}

const SCRAPE_URL = "https://example.com/page";

const CASES: Case[] = [
  {
    name: "scrape (Serper)",
    body: SERPER_SCRAPE,
    readsConfig: true,
    run: (s) => (args, env, config) => runScrape([SCRAPE_URL, ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
  {
    name: "scrape (Bright Data)",
    body: BRIGHT_DATA_SCRAPE,
    readsConfig: true,
    run: (s) => (args, env, config) =>
      runScrape([SCRAPE_URL, "--provider", "brightdata", ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
  {
    name: "search (SearXNG)",
    body: SEARXNG_SEARCH,
    readsConfig: true,
    run: (s) => (args, env, config) =>
      runSearch(["q", "--provider", "searxng", ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
  {
    name: "search (Serper)",
    body: SERPER_SEARCH,
    readsConfig: false,
    run: (s) => (args, env, config) =>
      runSearch(["q", "--provider", "serper", ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
  {
    name: "search (Bright Data)",
    body: BRIGHT_DATA_SEARCH,
    readsConfig: false,
    run: (s) => (args, env, config) =>
      runSearch(["q", "--provider", "brightdata", ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
  {
    name: "search (Kagi)",
    body: KAGI_SEARCH,
    readsConfig: false,
    run: (s) => (args, env, config) =>
      runSearch(["q", "--provider", "kagi", ...args], s.fetchImpl, { ...KEYS, ...env }, config),
  },
];

for (const { name, body, run } of CASES) {
  test(`${name} stops at the cap given by --max-response-bytes`, async () => {
    const served = serving(body);
    await assert.rejects(
      () => run(served)(["--max-response-bytes", SMALL_CAP], {}, {}),
      capError(new RegExp(`${SMALL_CAP} bytes`)),
    );
    assert.equal(served.calls.count, 1);
  });

  test(`${name} stops at the cap given by ${MAX_RESPONSE_BYTES_ENV}`, async () => {
    const served = serving(body);
    await assert.rejects(
      () => run(served)([], { [MAX_RESPONSE_BYTES_ENV]: SMALL_CAP }, {}),
      capError(new RegExp(`${SMALL_CAP} bytes`)),
    );
  });

  test(`${name} lets a body through when the cap is above it`, async () => {
    // The default cap, 64 MiB, is far above a 5 KB body: nothing set means nothing refused.
    const served = serving(body);
    await run(served)([], {}, {});
    await run(served)(["--max-response-bytes", BIG_CAP], {}, {});
  });

  test(`${name} takes the flag over the env var`, async () => {
    const served = serving(body);
    await run(served)(["--max-response-bytes", BIG_CAP], { [MAX_RESPONSE_BYTES_ENV]: SMALL_CAP }, {});
    await assert.rejects(
      () => run(served)(["--max-response-bytes", SMALL_CAP], { [MAX_RESPONSE_BYTES_ENV]: BIG_CAP }, {}),
      capError(new RegExp(`${SMALL_CAP} bytes`)),
    );
  });

  test(`${name} checks the byte cap before it calls the network`, async () => {
    const served = serving(body);
    await assert.rejects(() => run(served)(["--max-response-bytes", "abc"], {}, {}), usageError(/--max-response-bytes/));
    await assert.rejects(() => run(served)(["--max-response-bytes", "0"], {}, {}), usageError(/--max-response-bytes/));
    await assert.rejects(
      () => run(served)([], { [MAX_RESPONSE_BYTES_ENV]: "lots" }, {}),
      usageError(/SERP_AXI_MAX_RESPONSE_BYTES/),
    );
    assert.equal(served.calls.count, 0);
  });

  test(`${name} does not check an env var that the flag overrides`, async () => {
    const served = serving(body);
    await run(served)(["--max-response-bytes", BIG_CAP], { [MAX_RESPONSE_BYTES_ENV]: "lots" }, {});
  });
}

for (const { name, body, run, readsConfig } of CASES) {
  if (readsConfig) {
    test(`${name} reads the maxResponseBytes config key, under the flag and the env var`, async () => {
      const served = serving(body);
      await assert.rejects(
        () => run(served)([], {}, { maxResponseBytes: Number(SMALL_CAP) }),
        capError(new RegExp(`${SMALL_CAP} bytes`)),
      );
      await run(served)(["--max-response-bytes", BIG_CAP], {}, { maxResponseBytes: Number(SMALL_CAP) });
      await run(served)([], { [MAX_RESPONSE_BYTES_ENV]: BIG_CAP }, { maxResponseBytes: Number(SMALL_CAP) });
    });

    test(`${name} names the config key when its value is wrong`, async () => {
      const served = serving(body);
      await assert.rejects(() => run(served)([], {}, { maxResponseBytes: "lots" }), usageError(/maxResponseBytes/));
      assert.equal(served.calls.count, 0);
    });
  } else {
    // Documented in docs/things-that-look-like-bugs.md. These searches never open the
    // config file, so the key has no effect there and a bad value does not fail the run.
    test(`${name} ignores the maxResponseBytes config key, as it ignores the whole config file`, async () => {
      const served = serving(body);
      await run(served)([], {}, { maxResponseBytes: Number(SMALL_CAP) });
      await run(served)([], {}, { maxResponseBytes: "lots" });
    });
  }
}

test("scrape checks the byte cap before it opens the config file", async () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "serp-axi-cap-config-"));
  try {
    mkdirSync(path.join(dir, "serp-axi"));
    writeFileSync(path.join(dir, "serp-axi", "config.json"), "{ not json");
    const served = serving(SERPER_SCRAPE);
    await assert.rejects(
      () =>
        runScrape([SCRAPE_URL, "--max-response-bytes", "abc"], served.fetchImpl, {
          ...KEYS,
          XDG_CONFIG_HOME: dir,
        }),
      usageError(/--max-response-bytes/),
    );
    assert.equal(served.calls.count, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("scrape refuses --max-response-bytes with --ladder, which never uses serp-axi's own requests", async () => {
  const served = serving(SERPER_SCRAPE);
  await assert.rejects(
    () => runScrape([SCRAPE_URL, "--ladder", "--max-response-bytes", SMALL_CAP], served.fetchImpl, KEYS, {}),
    usageError(/--max-response-bytes does not apply with --ladder/),
  );
  assert.equal(served.calls.count, 0);
});

test("scrape lets the env var and config key stand when --ladder is used", async () => {
  // The env var and config key are standing settings for every run, as the other
  // caps' are, so only the flag is a conflict. This run fails later, on the missing
  // ladder binary, which is the proof it got past the cap check.
  const served = serving(SERPER_SCRAPE);
  await assert.rejects(
    () =>
      runScrape(
        [SCRAPE_URL, "--ladder"],
        served.fetchImpl,
        { ...KEYS, [MAX_RESPONSE_BYTES_ENV]: SMALL_CAP, SERP_AXI_LADDER_BIN: "/nonexistent/ladder-cli" },
        { maxResponseBytes: Number(SMALL_CAP) },
      ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.doesNotMatch(error.message, /max-response-bytes|maxResponseBytes|SERP_AXI_MAX_RESPONSE_BYTES/);
      return true;
    },
  );
});

test("scrape does not validate a byte cap it will not use under --ladder", async () => {
  // A malformed standing setting would stop a ladder run for nothing: the ladder makes
  // its own requests. The run fails on the missing binary instead, and says so.
  const served = serving(SERPER_SCRAPE);
  await assert.rejects(
    () =>
      runScrape(
        [SCRAPE_URL, "--ladder"],
        served.fetchImpl,
        { ...KEYS, [MAX_RESPONSE_BYTES_ENV]: "lots", SERP_AXI_LADDER_BIN: "/nonexistent/ladder-cli" },
        { maxResponseBytes: "also lots" },
      ),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.doesNotMatch(error.message, /max-response-bytes|maxResponseBytes|SERP_AXI_MAX_RESPONSE_BYTES/);
      return true;
    },
  );
});

test("a Serper, Bright Data or Kagi search with the cap flag still never opens the config file", async () => {
  // The config key is read for scrape and SearXNG search only (docs/things-that-look-like-bugs.md),
  // so setting the flag must not be what makes these searches open a file they never needed.
  const dir = mkdtempSync(path.join(os.tmpdir(), "serp-axi-cap-config-"));
  try {
    mkdirSync(path.join(dir, "serp-axi"));
    writeFileSync(path.join(dir, "serp-axi", "config.json"), "{ not json");
    const env = { ...KEYS, XDG_CONFIG_HOME: dir, [MAX_RESPONSE_BYTES_ENV]: BIG_CAP };
    const searches: Array<[string, string]> = [
      ["serper", SERPER_SEARCH],
      ["brightdata", BRIGHT_DATA_SEARCH],
      ["kagi", KAGI_SEARCH],
    ];
    for (const [provider, body] of searches) {
      const served = serving(body);
      await runSearch(["q", "--provider", provider, "--max-response-bytes", BIG_CAP], served.fetchImpl, env);
      await runSearch(["q", "--provider", provider], served.fetchImpl, env);
    }
    // The control: SearXNG does read it, so the same broken file stops that run.
    await assert.rejects(
      () => runSearch(["q", "--provider", "searxng", "--max-response-bytes", BIG_CAP], serving(SEARXNG_SEARCH).fetchImpl, env),
      usageError(/not valid JSON/),
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
