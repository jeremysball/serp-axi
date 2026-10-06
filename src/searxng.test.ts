import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import http from "node:http";
import type { AddressInfo } from "node:net";
import type { Duplex } from "node:stream";
import { fileURLToPath } from "node:url";
import { test, type TestContext } from "node:test";
import { runSearch } from "./commands/search.ts";
import { runCli } from "./cli.ts";
import { createAppOptions } from "./app.ts";
import { SerpAxiError } from "./errors.ts";
import { decode } from "@toon-format/toon";

const KAGI_FIXTURE = readFileSync(
  fileURLToPath(new URL("./fixtures/kagi-html-search.html", import.meta.url)),
  "utf8",
);

const SEARXNG_ENVS = ["SERP_AXI_SEARXNG_URL", "SERP_AXI_SEARXNG_ENGINES", "SERP_AXI_SEARCH_TIMEOUT_MS"] as const;
const PAID_ENVS = ["SERPER_API_KEY", "BRIGHTDATA_API_KEY", "KAGI_SESSION_TOKEN"] as const;

async function withEnvs<T>(entries: Array<[string, string | undefined]>, fn: () => Promise<T>): Promise<T> {
  const originals = entries.map(([n]) => [n, process.env[n]] as const);
  for (const [n, v] of entries) {
    if (v === undefined) delete process.env[n];
    else process.env[n] = v;
  }
  try {
    return await fn();
  } finally {
    for (const [n, v] of originals) {
      if (v === undefined) delete process.env[n];
      else process.env[n] = v;
    }
  }
}

async function isolated(t: TestContext, fn: (home: string, configDir: string) => Promise<void>): Promise<void> {
  const home = mkdtempSync(path.join(tmpdir(), "serp-axi-xdg-"));
  const configDir = path.join(home, "serp-axi");
  mkdirSync(configDir, { recursive: true });
  t.after(() => rmSync(home, { recursive: true, force: true }));
  await withEnvs(
    [
      ...SEARXNG_ENVS.map((n) => [n, undefined] as [string, string | undefined]),
      ...PAID_ENVS.map((n) => [n, undefined] as [string, string | undefined]),
      ["XDG_CONFIG_HOME", home],
    ],
    () => fn(home, configDir),
  );
}

function writeConfig(configDir: string, config: unknown): string {
  const file = path.join(configDir, "config.json");
  writeFileSync(file, typeof config === "string" ? config : JSON.stringify(config));
  return file;
}

interface CapturedCall {
  url: string;
  hasSignal: boolean;
}

function searxngFetch(payload: unknown, captured: CapturedCall[]): typeof fetch {
  return (async (url: unknown, init?: RequestInit) => {
    captured.push({ url: String(url), hasSignal: init?.signal instanceof AbortSignal });
    if (typeof payload === "string" || payload instanceof Response) {
      return typeof payload === "string" ? new Response(payload, { status: 200 }) : payload;
    }
    return new Response(JSON.stringify(payload), { status: 200 });
  }) as typeof fetch;
}

async function capture(fn: () => Promise<Record<string, unknown>>): Promise<{
  output?: Record<string, unknown>;
  error?: unknown;
}> {
  try {
    return { output: await fn() };
  } catch (error) {
    return { error };
  }
}

function startServer(t: TestContext, handler: http.RequestListener): Promise<{ port: number; sockets: Set<Duplex> }> {
  const sockets = new Set<Duplex>();
  const server = http.createServer(handler);
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  t.after(() => {
    for (const socket of sockets) socket.destroy();
    server.close();
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      resolve({ port: (server.address() as AddressInfo).port, sockets });
    });
  });
}

function appOptions() {
  return createAppOptions(new URL("./bin/serp-axi.ts", import.meta.url).href);
}

test("runSearch rejects searxng-only flags with the default provider", async (t) => {
  await isolated(t, async () => {
    let called = 0;
    const fetchImpl = (async () => {
      called++;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    const { error } = await capture(() => runSearch(["q", "--searxng-url", "http://127.0.0.1:8888"], fetchImpl));
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /--searxng-url is only supported with --provider searxng/);
    assert.equal(called, 0);
  });
});

test("runSearch rejects --zone with --provider searxng before network", async (t) => {
  await isolated(t, async () => {
    let called = 0;
    const fetchImpl = (async () => {
      called++;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--zone", "z"], fetchImpl),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /--zone is not supported with --provider searxng/);
    assert.equal(called, 0);
  });
});

test("runSearch rejects --fields with --provider searxng", async (t) => {
  await isolated(t, async () => {
    let called = 0;
    const fetchImpl = (async () => {
      called++;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--fields", "date"], fetchImpl),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /--fields is not supported with --provider searxng/);
    assert.equal(called, 0);
  });
});

test("runSearch searxng returns normalized results with provider/status/engines", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      {
        results: [
          { url: "https://a.example/x", title: "A", content: "snippet a", engines: ["bing", "mojeek"] },
          { url: "https://b.example/y", title: "B", content: "snippet b", engine: "brave" },
        ],
      },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["hello", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.provider, "searxng");
    assert.equal(output?.status, "ok");
    assert.equal(output?.count, 2);
    const rows = output?.results as Array<Record<string, unknown>>;
    assert.equal(rows[0].position, 1);
    assert.equal(rows[0].title, "A");
    assert.equal(rows[0].link, "https://a.example/x");
    assert.equal(rows[0].snippet, "snippet a");
    assert.deepEqual(rows[0].engines, ["bing", "mojeek"]);
    assert.deepEqual(rows[1].engines, ["brave"]);
    const engines = output?.engines as Array<Record<string, unknown>>;
    assert.deepEqual(engines[0], { name: "bing", status: "ok", resultCount: 1 });
    assert.deepEqual(engines[1], { name: "mojeek", status: "ok", resultCount: 1 });
    assert.deepEqual(engines[2], { name: "brave", status: "ok", resultCount: 1 });
    assert.equal(captured.length, 1);
    assert.equal(captured[0].hasSignal, true);
  });
});

test("runSearch sends q, format=json, language=lang-region, engines; no num", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    const { error } = await capture(() =>
      runSearch(
        ["hello world", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9", "--engines", "bing,mojeek"],
        fetchImpl,
      ),
    );
    assert.equal(error, undefined);
    assert.equal(captured.length, 1);
    const url = new URL(captured[0].url);
    assert.equal(url.pathname, "/search");
    assert.equal(url.searchParams.get("q"), "hello world");
    assert.equal(url.searchParams.get("format"), "json");
    assert.equal(url.searchParams.get("language"), "en-US");
    assert.equal(url.searchParams.get("engines"), "bing,mojeek");
    assert.equal(url.searchParams.get("num"), null);
  });
});

test("runSearch dedupes by URL minus fragment, unions engines, caps after dedup", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      {
        results: [
          { url: "https://a.example/x#one", title: "First", content: "content one", engines: ["bing"] },
          { url: "https://a.example/x#two", title: "Second", content: "content two", engines: ["mojeek"] },
          { url: "https://b.example/y", title: "Other", content: "other", engines: ["brave"] },
        ],
      },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9", "--num", "2"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.count, 2);
    const rows = output?.results as Array<Record<string, unknown>>;
    assert.equal(rows[0].title, "First");
    assert.equal(rows[0].snippet, "content one");
    assert.deepEqual(rows[0].engines, ["bing", "mojeek"]);
    assert.equal(rows[0].position, 1);
    assert.equal(rows[1].position, 2);
  });
});

test("runSearch reports partial when results exist and an engine failed", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      {
        results: [{ url: "https://a.example/x", title: "A", engines: ["bing"] }],
        unresponsive_engines: [["brave", "connection reset by peer"]],
      },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.status, "partial");
    assert.equal(output?.count, 1);
    assert.match(output?.warning as string, /1 engine/);
    const engines = output?.engines as Array<Record<string, unknown>>;
    const brave = engines.find((e) => e.name === "brave") as Record<string, unknown>;
    assert.equal(brave.status, "error");
    assert.match(brave.reason as string, /connection reset/);
  });
});

test("runSearch attributes a failed engine truthfully even when rows name it", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      {
        results: [{ url: "https://a.example/x", title: "A", content: "s", engines: ["bing"] }],
        unresponsive_engines: [["bing", "captcha wall"]],
      },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.status, "partial");
    assert.equal(output?.count, 1);
    const engines = output?.engines as Array<Record<string, unknown>>;
    const bing = engines.find((e) => e.name === "bing") as Record<string, unknown>;
    assert.equal(bing.status, "blocked");
    assert.equal(bing.resultCount, 1);
    assert.match(bing.reason as string, /captcha wall/);
  });
});

test("runSearch treats 2xx with rows and unresponsive engines containing captcha/blocked as partial with blocked rows", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      {
        results: [],
        unresponsive_engines: [["bing", "captcha challenge"]],
      },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(output, undefined);
    assert.ok(error instanceof SerpAxiError);
    const details = (error as unknown as { details?: { status?: string; count?: number } }).details;
    assert.equal(details?.status, "blocked");
    assert.equal(details?.count, 0);
    assert.match(error.message, /no results/);
    assert.match(error.message, /failed/);
    assert.doesNotMatch(error.message, /only blocked engines/);
  });
});

test("runSearch reports a successful zero only when there are no failures", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    const { output, error } = await capture(() =>
      runSearch(["nothing", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.status, "ok");
    assert.equal(output?.count, 0);
    assert.match(output?.results as string, /0 results found for query "nothing"/);
  });
});

test("runSearch maps unresponsive non-blocked failures and no rows to unavailable", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch(
      { results: [], unresponsive_engines: [["mojeek", "connection reset"]] },
      captured,
    );
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(output, undefined);
    assert.ok(error instanceof SerpAxiError);
    assert.match(error.message, /no results/);
    assert.match(error.message, /failed/);
    const details = (error as unknown as { details?: { status?: string } }).details;
    assert.equal(details?.status, "unavailable");
  });
});

test("runSearch maps searxng HTTP 403/429 to typed blocked output", async (t) => {
  await isolated(t, async () => {
    for (const status of [403, 429]) {
      const fetchImpl = (async () => new Response("Forbidden", { status })) as typeof fetch;
      const { output, error } = await capture(() =>
        runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
      );
      assert.equal(output, undefined);
      const details = (error as unknown as { details?: { status?: string; count?: number } }).details;
      assert.equal(details?.status, "blocked");
      assert.equal(details?.count, 0);
    }
  });
});

test("runSearch maps 401 without leaking details", async (t) => {
  await isolated(t, async () => {
    const fetchImpl = (async () => new Response("unauthorized", { status: 401 })) as typeof fetch;
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "runtime");
    assert.match(error.message, /401/);
  });
});

test("runSearch maps searxng HTTP 500, malformed JSON and an HTML challenge body to runtime errors", async (t) => {
  await isolated(t, async () => {
    const html = (async () =>
      new Response("<html><body>challenge</body></html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      })) as typeof fetch;
    for (const [name, impl, pattern] of [
      ["500", (async () => new Response("boom", { status: 500 })) as typeof fetch, /upstream failure/],
      ["bad json", (async () => new Response("not json", { status: 200 })) as typeof fetch, /non-JSON/],
      ["html", html, /HTML/],
    ] as Array<[string, typeof fetch, RegExp]>) {
      const { error } = await capture(() =>
        runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], impl),
      );
      assert.ok(error instanceof SerpAxiError, name);
      assert.equal(error.kind, "runtime", name);
      assert.match(error.message, pattern, name);
    }
  });
});

test("runSearch rejects malformed upstream bodies with runtime errors", async (t) => {
  await isolated(t, async () => {
    const cases: Array<[string, unknown, RegExp]> = [
      ["missing results", { engines: [] }, /missing results array|malformed response/],
      ["results not array", { results: {} }, /malformed response/],
      ["row not object", { results: ["x"] }, /not an object/],
      ["row missing fields", { results: [{ url: "https://a" }] }, /missing a string url or title/],
      ["row bad url", { results: [{ url: "notaurl", title: "T" }] }, /invalid url/],
      ["row bad scheme", { results: [{ url: "ftp://a", title: "T" }] }, /non-http/],
      ["row bad content", { results: [{ url: "https://a", title: "T", content: 3 }] }, /non-string content/],
      ["row bad engines", { results: [{ url: "https://a", title: "T", engines: "bing" }] }, /invalid engines array/],
      ["row empty engine name", { results: [{ url: "https://a", title: "T", engine: "  " }] }, /empty|invalid engine/],
      ["bad unresponsive", { results: [], unresponsive_engines: {} }, /bad unresponsive_engines/],
      ["bad unresponsive entry", { results: [], unresponsive_engines: [["bing"]] }, /bad unresponsive_engines entry/],
      ["empty unresponsive name", { results: [], unresponsive_engines: [["", "x"]] }, /empty|blank|invalid/],
    ];
    for (const [name, body, pattern] of cases) {
      const captured: CapturedCall[] = [];
      const fetchImpl = searxngFetch(body, captured);
      const { error } = await capture(() =>
        runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
      );
      assert.ok(error instanceof SerpAxiError, name);
      assert.equal(error.kind, "runtime", name);
      assert.match(error.message, pattern, name);
    }
  });
});

test("runSearch wraps a network rejection as a runtime error", async (t) => {
  await isolated(t, async () => {
    const fetchImpl = (async () => {
      throw new Error("ECONNREFUSED");
    }) as typeof fetch;
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.match(error.message, /network error/);
  });
});

test("runSearch truncates a long snippet at the snippet limit", async (t) => {
  await isolated(t, async () => {
    const long = "x".repeat(250);
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [{ url: "https://a", title: "T", content: long, engine: "bing" }] }, captured);
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    const rows = output?.results as Array<Record<string, unknown>>;
    assert.equal((rows[0].snippet as string).length, 200);
    assert.ok((rows[0].snippet as string).endsWith("..."));
  });
});

test("runSearch needs no paid provider key for searxng", async (t) => {
  await isolated(t, async () => {
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    const { output, error } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9"], fetchImpl),
    );
    assert.equal(error, undefined);
    assert.equal(output?.provider, "searxng");
    assert.equal(captured.length, 1);
  });
});

test("runSearch config precedence: flag over env over config over default", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: "http://config.local", searxngEngines: ["cfg-engine"], searchTimeoutMs: 12345 });
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
    assert.equal(error, undefined);
    const url = new URL(captured[0].url);
    assert.equal(url.host, "config.local");
    assert.equal(url.searchParams.get("engines"), "cfg-engine");

    captured.length = 0;
    await withEnvs([["SERP_AXI_SEARXNG_ENGINES", "env-a,env-b"]], async () => {
      const { error: e2 } = await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
      assert.equal(e2, undefined);
      const url2 = new URL(captured[0].url);
      assert.equal(url2.host, "config.local");
      assert.equal(url2.searchParams.get("engines"), "env-a,env-b");
    });

    captured.length = 0;
    const { error: e3 } = await capture(() =>
      runSearch(["q", "--provider", "searxng", "--searxng-url", "http://flag.local", "--engines", "flag-e"], fetchImpl),
    );
    assert.equal(e3, undefined);
    const url3 = new URL(captured[0].url);
    assert.equal(url3.host, "flag.local");
    assert.equal(url3.searchParams.get("engines"), "flag-e");
  });
});

test("env beats config for all three searxng values", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: "http://config.local", searxngEngines: ["cfg-engine"], searchTimeoutMs: 50 });
    const seen: string[] = [];
    const { port } = await startServer(t, (req, res) => {
      seen.push(req.url ?? "");
      setTimeout(() => {
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify({ results: [] }));
      }, 150);
    });
    await withEnvs(
      [
        ["SERP_AXI_SEARXNG_URL", `http://127.0.0.1:${port}`],
        ["SERP_AXI_SEARXNG_ENGINES", "env-e"],
        ["SERP_AXI_SEARCH_TIMEOUT_MS", "60000"],
      ],
      async () => {
        const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetch));
        assert.equal(error, undefined);
      },
    );
    assert.equal(seen.length, 1);
    const seenUrl = new URL(seen[0], `http://127.0.0.1:${port}`);
    assert.equal(seenUrl.searchParams.get("engines"), "env-e");
  });
});

test("flag beats env for all three searxng values", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: "http://config.local", searxngEngines: ["cfg-engine"], searchTimeoutMs: 60000 });
    const seen: string[] = [];
    const { port } = await startServer(t, (req, res) => {
      seen.push(req.url ?? "");
      setTimeout(() => {
        res.end(JSON.stringify({ results: [] }));
      }, 150);
    });
    await withEnvs(
      [
        ["SERP_AXI_SEARXNG_URL", "http://env.local"],
        ["SERP_AXI_SEARXNG_ENGINES", "env-e"],
        ["SERP_AXI_SEARCH_TIMEOUT_MS", "60000"],
      ],
      async () => {
        const { error } = await capture(() =>
          runSearch(
            [
              "q", "--provider", "searxng",
              "--searxng-url", `http://127.0.0.1:${port}`,
              "--engines", "flag-e",
              "--search-timeout-ms", "50",
            ],
            fetch,
          ),
        );
        assert.ok(error instanceof SerpAxiError);
        assert.match(error.message, /timed out after 50 ms/);
      },
    );
    assert.equal(seen.length, 1);
    const seenUrl = new URL(seen[0], `http://127.0.0.1:${port}`);
    assert.equal(seenUrl.searchParams.get("engines"), "flag-e");
  });
});

test("config timeout wins when env and flag are absent", async (t) => {
  await isolated(t, async (_home, configDir) => {
    const { port } = await startServer(t, (_req, res) => {
      setTimeout(() => res.end(JSON.stringify({ results: [] })), 150);
    });
    writeConfig(configDir, { searxngUrl: `http://127.0.0.1:${port}`, searchTimeoutMs: 50 });
    const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetch));
    assert.ok(error instanceof SerpAxiError);
    assert.match(error.message, /timed out after 50 ms/);
  });
});

test("runSearch honors XDG_CONFIG_HOME for the config file location", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: "http://config-home.local" });
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
    assert.equal(captured.length, 1);
    assert.equal(new URL(captured[0].url).host, "config-home.local");
  });
});

test("runSearch rejects malformed config JSON with an actionable usage error", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, "{not json");
    let called = 0;
    const fetchImpl = (async () => {
      called++;
      return new Response("{}");
    }) as typeof fetch;
    const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /config/);
    assert.equal(called, 0);
  });
});

test("runSearch rejects invalid selected values with usage errors", async (t) => {
  await isolated(t, async () => {
    const cases: Array<Array<string>> = [
      ["q", "--provider", "searxng", "--searxng-url", "http://user:pw@127.0.0.1:9"],
      ["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9/?a=1"],
      ["q", "--provider", "searxng", "--searxng-url", "ftp://127.0.0.1:9"],
      ["q", "--provider", "searxng", "--searxng-url", ""],
      ["q", "--provider", "searxng", "--search-timeout-ms", "0"],
      ["q", "--provider", "searxng", "--search-timeout-ms", "abc"],
      ["q", "--provider", "searxng", "--search-timeout-ms", "-5"],
      ["q", "--provider", "searxng", "--search-timeout-ms", "2147483648"],
      ["q", "--provider", "searxng", "--engines", "bing,,mojeek"],
      ["q", "--provider", "searxng", "--engines", ""],
    ];
    for (const args of cases) {
      let called = 0;
      const fetchImpl = (async () => {
        called++;
        return new Response("{}");
      }) as typeof fetch;
      const { error } = await capture(() => runSearch(args, fetchImpl));
      assert.ok(error instanceof SerpAxiError, args.join(" "));
      assert.equal(error.kind, "usage", args.join(" "));
      assert.match(error.message, /searxng-url|timeout|engines/i, args.join(" "));
      assert.equal(called, 0, args.join(" "));
    }
  });
});

test("runSearch rejects an over-range timeout with a clear message and no timer call", async (t) => {
  await isolated(t, async () => {
    let called = 0;
    const fetchImpl = (async () => {
      called++;
      return new Response("{}");
    }) as typeof fetch;
    const { error } = await capture(() =>
      runSearch(
        ["q", "--provider", "searxng", "--searxng-url", "http://127.0.0.1:9", "--search-timeout-ms", "2147483648"],
        fetchImpl,
      ),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /2147483647/);
    assert.equal(called, 0);
  });
});

test("config type violations are rejected per field without masking others", async (t) => {
  await isolated(t, async (_home, configDir) => {
    const good = { searxngUrl: "http://127.0.0.1:9", searxngEngines: ["bing"], searchTimeoutMs: 30000 };
    const badUrl = { ...good, searxngUrl: 123 };
    const badEngines = { ...good, searxngEngines: "bing" };
    const badEnginesItems = { ...good, searxngEngines: ["bing", ""] };
    const badTimeout = { ...good, searchTimeoutMs: "30000" };
    const badTimeoutRange = { ...good, searchTimeoutMs: 2147483648 };
    const cases: Array<[unknown, RegExp]> = [
      [badUrl, /searxngUrl/i],
      [badEngines, /searxngEngines/i],
      [badEnginesItems, /searxngEngines/i],
      [badTimeout, /searchTimeoutMs/i],
      [badTimeoutRange, /searchTimeoutMs|2147483647/i],
    ];
    for (const [config, pattern] of cases) {
      writeConfig(configDir, config);
      let called = 0;
      const fetchImpl = (async () => {
        called++;
        return new Response("{}");
      }) as typeof fetch;
      const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
      assert.ok(error instanceof SerpAxiError, JSON.stringify(config));
      assert.equal(error.kind, "usage", JSON.stringify(config));
      assert.match(error.message, pattern, JSON.stringify(config));
      assert.equal(called, 0, JSON.stringify(config));
    }
  });
});

test("array-valued endpoint is rejected, not String-coerced", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: ["http://127.0.0.1:8888"] });
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng"], (async () => new Response("{}")) as typeof fetch),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /searxngUrl/i);
  });
});

test("higher-precedence valid values override lower invalid ones", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: 123, searchTimeoutMs: -3, searxngEngines: "bing" });
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    const { error } = await capture(() =>
      runSearch(
        [
          "q", "--provider", "searxng",
          "--searxng-url", "http://127.0.0.1:9",
          "--search-timeout-ms", "30000",
          "--engines", "bing",
        ],
        fetchImpl,
      ),
    );
    assert.equal(error, undefined);
    assert.equal(new URL(captured[0].url).host, "127.0.0.1:9");
  });
});

test("env valid values override lower invalid config values", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngUrl: 123, searchTimeoutMs: -3, searxngEngines: "bing" });
    const captured: CapturedCall[] = [];
    const fetchImpl = searxngFetch({ results: [] }, captured);
    await withEnvs(
      [
        ["SERP_AXI_SEARXNG_URL", "http://env.local"],
        ["SERP_AXI_SEARCH_TIMEOUT_MS", "30000"],
        ["SERP_AXI_SEARXNG_ENGINES", "env-e"],
      ],
      async () => {
        const { error } = await capture(() => runSearch(["q", "--provider", "searxng"], fetchImpl));
        assert.equal(error, undefined);
      },
    );
    assert.equal(new URL(captured[0].url).host, "env.local");
  });
});

test("runSearch preserves kagi dispatch and defaults", async (t) => {
  await isolated(t, async () => {
    await withEnvs([["KAGI_SESSION_TOKEN", "tok"]], async () => {
      const fetchImpl = (async () => new Response(KAGI_FIXTURE, { status: 200 })) as typeof fetch;
      const { output, error } = await capture(() => runSearch(["rust async runtime", "--provider", "kagi"], fetchImpl));
      assert.equal(error, undefined);
      assert.equal(output?.count, 10);
      const rows = output?.results as Array<Record<string, unknown>>;
      assert.equal(rows[2].title, "Tokio - An asynchronous Rust runtime");
    });
  });
});

test("integration: real local HTTP server sees the search path and parameters", async (t) => {
  await isolated(t, async () => {
    const seen: string[] = [];
    const { port } = await startServer(t, (req, res) => {
      seen.push(req.url ?? "");
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ results: [{ url: "https://x.example/", title: "T", content: "c", engines: ["bing"] }] }));
    });
    const { output, error } = await capture(() =>
      runSearch(
        [
          "typescript satisfies operator",
          "--provider", "searxng",
          "--searxng-url", `http://127.0.0.1:${port}/base`,
          "--engines", "bing,mojeek",
          "--lang", "en",
          "--region", "us",
        ],
        fetch,
      ),
    );
    assert.equal(error, undefined);
    assert.equal(output?.status, "ok");
    assert.equal(output?.count, 1);
    assert.equal(seen.length, 1);
    const seenUrl = new URL(seen[0], `http://127.0.0.1:${port}`);
    assert.equal(seenUrl.pathname, "/base/search");
    assert.equal(seenUrl.searchParams.get("q"), "typescript satisfies operator");
    assert.equal(seenUrl.searchParams.get("format"), "json");
    assert.equal(seenUrl.searchParams.get("language"), "en-US");
    assert.equal(seenUrl.searchParams.get("engines"), "bing,mojeek");
    assert.equal(seenUrl.searchParams.get("num"), null);
  });
});

test("runCli returns exit 1 with structured blocked details, not '0 results found'", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, (_req, res) => {
      res.writeHead(403);
      res.end("Forbidden");
    });
    const options = appOptions();
    const stdout = {
      output: "",
      write(chunk: string) {
        this.output += chunk;
        return true;
      },
    };
    const code = await runCli(
      ["search", "q", "--provider", "searxng", "--searxng-url", `http://127.0.0.1:${port}`],
      { ...options, stdout },
    );
    assert.equal(code, 1);
    const decoded = decode(stdout.output) as Record<string, unknown>;
    assert.equal(decoded.status, "blocked");
    assert.equal(decoded.count, 0);
    assert.equal(decoded.provider, "searxng");
    assert.ok(typeof decoded.error === "string" && decoded.error.length > 0);
    assert.ok(typeof decoded.help === "string" && decoded.help.length > 0);
    assert.ok(typeof decoded.results !== "string" || !decoded.results.includes("0 results found"));
  });
});

test("runCli succeeds with count and status for a healthy local SearXNG", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, (_req, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ results: [{ url: "https://x.example/", title: "T", content: "c" }] }));
    });
    const options = appOptions();
    const stdout = {
      output: "",
      write(chunk: string) {
        this.output += chunk;
        return true;
      },
    };
    const code = await runCli(
      ["search", "q", "--provider", "searxng", "--searxng-url", `http://127.0.0.1:${port}`],
      { ...options, stdout },
    );
    assert.equal(code, 0);
    const decoded = decode(stdout.output) as Record<string, unknown>;
    assert.equal(decoded.provider, "searxng");
    assert.equal(decoded.status, "ok");
    assert.equal(decoded.count, 1);
  });
});

test("runCli preserves engine details and blocked status for unresponsive engines", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, (_req, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ results: [], unresponsive_engines: [["bing", "captcha"]] }));
    });
    const options = appOptions();
    const stdout = {
      output: "",
      write(chunk: string) {
        this.output += chunk;
        return true;
      },
    };
    const code = await runCli(
      ["search", "q", "--provider", "searxng", "--searxng-url", `http://127.0.0.1:${port}`],
      { ...options, stdout },
    );
    assert.equal(code, 1);
    const decoded = decode(stdout.output) as Record<string, unknown>;
    assert.equal(decoded.status, "blocked");
    assert.equal(decoded.count, 0);
    assert.equal(decoded.provider, "searxng");
    const engines = decoded.engines as Array<Record<string, unknown>>;
    assert.equal(engines[0].name, "bing");
    assert.equal(engines[0].status, "blocked");
    assert.match(engines[0].reason as string, /captcha/);
  });
});

test("--search-timeout-ms bounds a slow upstream via AbortSignal.timeout", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, () => {});
    const { error } = await capture(() =>
      runSearch(
        ["q", "--provider", "searxng", "--searxng-url", `http://127.0.0.1:${port}`, "--search-timeout-ms", "50"],
        fetch,
      ),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.match(error.message, /timed out/i);
  });
});

test("a body that stalls after headers surfaces a structured timed-out error via the CLI", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, (_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.write('{"results":[{"url":');
    });
    const options = appOptions();
    const stdout = {
      output: "",
      write(chunk: string) {
        this.output += chunk;
        return true;
      },
    };
    const code = await runCli(
      [
        "search", "q", "--provider", "searxng",
        "--searxng-url", `http://127.0.0.1:${port}`,
        "--search-timeout-ms", "50",
      ],
      { ...options, stdout },
    );
    assert.equal(code, 1);
    const decoded = decode(stdout.output) as Record<string, unknown>;
    assert.match(decoded.error as string, /timed out after 50 ms/);
    assert.ok(typeof decoded.help === "string" && decoded.help.length > 0);
    assert.equal(decoded.status, undefined);
  });
});

test("a mid-body socket drop surfaces a safe network error via the CLI", async (t) => {
  await isolated(t, async () => {
    const { port } = await startServer(t, (_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.write('{"results":[');
      res.socket?.destroy();
    });
    const options = appOptions();
    const stdout = {
      output: "",
      write(chunk: string) {
        this.output += chunk;
        return true;
      },
    };
    const code = await runCli(
      ["search", "q", "--provider", "searxng", "--searxng-url", `http://127.0.0.1:${port}`],
      { ...options, stdout },
    );
    assert.equal(code, 1);
    const decoded = decode(stdout.output) as Record<string, unknown>;
    assert.match(decoded.error as string, /network error reading SearXNG response|network error/);
    assert.doesNotMatch(decoded.error as string, /__|DOMException|terminated|undefined/);
  });
});

test("config searxngEngines must be a JSON array", async (t) => {
  await isolated(t, async (_home, configDir) => {
    writeConfig(configDir, { searxngEngines: "bing,mojeek" });
    const { error } = await capture(() =>
      runSearch(["q", "--provider", "searxng"], (async () => new Response("{}")) as typeof fetch),
    );
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, /searxngEngines/);
    assert.match(error.message, /array/);
  });
});
