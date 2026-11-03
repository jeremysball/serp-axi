import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { gzipSync } from "node:zlib";
import type { AddressInfo } from "node:net";
import { readBodyText } from "./body.ts";
import { SerpAxiError } from "./errors.ts";
import { searchSerper, scrapeSerper, type SearchParams } from "./serper.ts";
import { searchKagi } from "./kagi.ts";
import { searchSearxng } from "./searxng.ts";
import { searchBrightData, scrapeBrightData } from "./brightdata.ts";

/**
 * These tests use a real socket, not a stand-in Response: the belief is that a
 * server which never stops sending cannot make a provider call buffer without
 * bound, and a fake stream would only show that the fake was bounded.
 *
 * The server writes 16 KiB at a time, as fast as the client reads, and stops on
 * its own at HARD_STOP so a reader with no bound fails an assertion instead of
 * eating the machine's memory.
 */
const CAP = 4096;
const CHUNK = 16 * 1024;
const HARD_STOP = 64 * 1024 * 1024;
// Far more than a bounded reader can have pulled through the socket buffers,
// far less than the whole body: tells "hung up early" from "read it all".
const EARLY = 32 * 1024 * 1024;

interface EndlessServer {
  url: string;
  written: () => number;
  closedEarly: () => boolean;
  stop: () => Promise<void>;
}

async function endlessServer(status: number, contentType: string): Promise<EndlessServer> {
  let written = 0;
  let closedEarly = false;
  const server = http.createServer((req, res) => {
    req.resume();
    res.writeHead(status, { "content-type": contentType });
    const chunk = Buffer.alloc(CHUNK, 0x61);
    let hungUp = false;
    res.on("close", () => {
      if (written < HARD_STOP) closedEarly = true;
      hungUp = true;
    });
    const pump = (): void => {
      while (!hungUp) {
        if (written >= HARD_STOP) {
          res.end();
          return;
        }
        written += chunk.length;
        if (!res.write(chunk)) {
          res.once("drain", pump);
          return;
        }
      }
    };
    pump();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/`,
    written: () => written,
    closedEarly: () => closedEarly,
    stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

// Sends every request to the local server, whatever URL the provider built.
function fetchTo(url: string): typeof fetch {
  return ((_input: unknown, init?: RequestInit) => fetch(url, init)) as typeof fetch;
}

const PARAMS: SearchParams = { q: "x", gl: "us", hl: "en", num: 3 };

type Call = (fetchImpl: typeof fetch, cap: number) => Promise<unknown>;

// Every call that reads a success body. A new provider call that reads one
// belongs in this table; the ast-grep rule is what notices when it is missing.
const SUCCESS_READS: Array<[string, string, Call]> = [
  ["Serper search", "application/json", (f, cap) => searchSerper("key", PARAMS, f, cap)],
  ["Serper scrape", "application/json", (f, cap) => scrapeSerper("key", "https://example.com", f, cap)],
  ["Kagi search", "text/html", (f, cap) => searchKagi("token", PARAMS, f, cap)],
  [
    "SearXNG search",
    "application/json",
    (f, cap) => searchSearxng({ url: "http://searx.invalid", engines: undefined, timeoutMs: 20_000 }, PARAMS, f, cap),
  ],
  ["Bright Data search", "application/json", (f, cap) => searchBrightData("key", PARAMS, f, "zone", cap)],
  [
    "Bright Data scrape",
    "application/jsonl",
    (f, cap) => scrapeBrightData("key", "gd_dataset", ["https://example.com"], f, cap),
  ],
];

// Every call that reads an error body to explain a status it does not map.
const ERROR_READS: Array<[string, Call]> = [
  ["Serper search", (f, cap) => searchSerper("key", PARAMS, f, cap)],
  ["Kagi search", (f, cap) => searchKagi("token", PARAMS, f, cap)],
  ["Bright Data search", (f, cap) => searchBrightData("key", PARAMS, f, "zone", cap)],
  ["Bright Data scrape", (f, cap) => scrapeBrightData("key", "gd_dataset", ["https://example.com"], f, cap)],
];

for (const [name, contentType, call] of SUCCESS_READS) {
  test(`${name} stops reading a body that never ends, and says which cap it hit`, { timeout: 30_000 }, async () => {
    const server = await endlessServer(200, contentType);
    try {
      await assert.rejects(
        () => call(fetchTo(server.url), CAP),
        (error: unknown) => {
          assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
          assert.equal(error.kind, "runtime");
          assert.match(error.message, new RegExp(`${CAP} bytes`));
          assert.match(error.help ?? "", /--max-response-bytes/);
          return true;
        },
      );
      assert.ok(server.written() < EARLY, `the server wrote ${server.written()} bytes before the client let go`);
      await new Promise((resolve) => setTimeout(resolve, 100));
      assert.ok(server.closedEarly(), "the client closed the connection instead of draining it");
    } finally {
      await server.stop();
    }
  });
}

for (const [name, call] of ERROR_READS) {
  test(`${name} reports an unmapped status without draining the error body`, { timeout: 30_000 }, async () => {
    const server = await endlessServer(418, "text/plain");
    try {
      await assert.rejects(
        () => call(fetchTo(server.url), CAP),
        (error: unknown) => {
          assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
          assert.match(error.message, /418/);
          return true;
        },
      );
      assert.ok(server.written() < EARLY, `the server wrote ${server.written()} bytes before the client let go`);
    } finally {
      await server.stop();
    }
  });
}

test("the byte cap counts decoded bytes, so a small gzip body that expands past it is refused", async () => {
  // 4 MiB of one letter gzips to a few KiB: far under the cap on the wire, far over it once decoded.
  const plain = Buffer.alloc(4 * 1024 * 1024, 0x61);
  const packed = gzipSync(plain);
  const cap = 64 * 1024;
  assert.ok(packed.length < cap, `the compressed body must be under the cap to prove anything; it is ${packed.length}`);

  const server = http.createServer((req, res) => {
    req.resume();
    res.writeHead(200, { "content-type": "text/plain", "content-encoding": "gzip", "content-length": packed.length });
    res.end(packed);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
  try {
    await assert.rejects(
      async () => readBodyText(await fetch(url), { maxBytes: cap, source: "Gzip test" }),
      (error: unknown) => {
        assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
        assert.match(error.message, new RegExp(`larger than the ${cap} bytes`));
        return true;
      },
    );
    // Control: the same body under a cap above its decoded size reads whole, so the
    // refusal above came from the decoded count and not from a dislike of gzip.
    const whole = await readBodyText(await fetch(url), { maxBytes: plain.length, source: "Gzip test" });
    assert.equal(whole.length, plain.length);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
