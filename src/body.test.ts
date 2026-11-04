import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BodyReadError, DEFAULT_MAX_RESPONSE_BYTES, ERROR_BODY_MAX_BYTES, readBodyText, readErrorBody } from "./body.ts";
import { searchCommand } from "./commands/search.ts";
import { scrapeCommand } from "./commands/scrape.ts";
import { SerpAxiError } from "./errors.ts";

const LIMIT = { maxBytes: 10, source: "Example" };

interface Tracked {
  response: Response;
  pulls: () => number;
  cancelled: () => boolean;
}

// A response whose body hands out `chunks` one pull at a time, so a test can see
// how much of the body a reader asked for and whether it hung up on the rest.
function trackedResponse(chunks: Uint8Array[], headers: Record<string, string> = {}, failAfter?: Error): Tracked {
  let pulled = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (pulled < chunks.length) {
        controller.enqueue(chunks[pulled]);
        pulled += 1;
      } else if (failAfter !== undefined) {
        controller.error(failAfter);
      } else {
        controller.close();
      }
    },
    cancel() {
      cancelled = true;
    },
  });
  return { response: new Response(body, { headers }), pulls: () => pulled, cancelled: () => cancelled };
}

const bytes = (text: string): Uint8Array => new TextEncoder().encode(text);

test("readBodyText returns a body that fits under the cap", async () => {
  const { response } = trackedResponse([bytes("hello"), bytes(" you")]);
  assert.equal(await readBodyText(response, LIMIT), "hello you");
});

test("readBodyText accepts a body of exactly the cap and refuses one byte more", async () => {
  const exact = trackedResponse([bytes("0123456789")]);
  assert.equal(await readBodyText(exact.response, LIMIT), "0123456789");

  const over = trackedResponse([bytes("0123456789A")]);
  await assert.rejects(() => readBodyText(over.response, LIMIT), SerpAxiError);
});

test("readBodyText decodes a character that is split across two chunks", async () => {
  const encoded = bytes("é");
  const { response } = trackedResponse([encoded.slice(0, 1), encoded.slice(1)]);
  assert.equal(await readBodyText(response, LIMIT), "é");
});

test("readBodyText counts bytes, not characters", async () => {
  // Five characters, ten bytes: fits. Six characters, twelve bytes: does not.
  const fits = trackedResponse([bytes("ééééé")]);
  assert.equal(await readBodyText(fits.response, LIMIT), "ééééé");
  const over = trackedResponse([bytes("éééééé")]);
  await assert.rejects(() => readBodyText(over.response, LIMIT), SerpAxiError);
});

test("readBodyText stops reading and hangs up when the body outgrows the cap", async () => {
  const chunks = Array.from({ length: 50 }, () => bytes("abcdef"));
  const tracked = trackedResponse(chunks);

  await assert.rejects(
    () => readBodyText(tracked.response, LIMIT),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "runtime");
      // The message names the response, the cap, and where the cap is set.
      assert.match(error.message, /Example/);
      assert.match(error.message, /10 bytes/);
      assert.match(error.help ?? "", /--max-response-bytes/);
      assert.match(error.help ?? "", /SERP_AXI_MAX_RESPONSE_BYTES/);
      assert.match(error.help ?? "", /maxResponseBytes/);
      return true;
    },
  );
  assert.ok(tracked.cancelled(), "the reader cancelled the stream");
  assert.ok(tracked.pulls() < 10, `read ${tracked.pulls()} of 50 chunks; it should stop a little past the cap`);
});

test("readBodyText refuses a declared content-length over the cap without reading", async () => {
  const tracked = trackedResponse([bytes("abc")], { "content-length": "1000" });
  await assert.rejects(() => readBodyText(tracked.response, LIMIT), SerpAxiError);
  assert.equal(tracked.pulls(), 0);
});

test("readBodyText does not compare a compressed content-length with the decoded cap", async () => {
  // content-length on an encoded response counts encoded bytes. For incompressible
  // data that is larger than the decoded body the cap is about.
  const encoded = trackedResponse([bytes("0123456789")], {
    "content-encoding": "gzip",
    "content-length": "1000",
  });
  assert.equal(await readBodyText(encoded.response, LIMIT), "0123456789");
  assert.ok(encoded.pulls() > 0, "the encoded body was read, so the no-read assertion below is about the header");

  // Control: the same declared length on a plain response is still refused before reading.
  const plain = trackedResponse([bytes("abc")], { "content-length": "1000" });
  await assert.rejects(() => readBodyText(plain.response, LIMIT), SerpAxiError);
  assert.equal(plain.pulls(), 0);
});

test("readBodyText still bounds a body that outgrows its declared content-length", async () => {
  const chunks = Array.from({ length: 50 }, () => bytes("abcdef"));
  const tracked = trackedResponse(chunks, { "content-length": "5" });
  await assert.rejects(() => readBodyText(tracked.response, LIMIT), SerpAxiError);
  assert.ok(tracked.pulls() < 10);
});

test("readBodyText turns a stream failure into a typed error instead of returning what it had", async () => {
  const boom = new Error("socket hung up");
  const tracked = trackedResponse([bytes("abc")], {}, boom);
  await assert.rejects(
    () => readBodyText(tracked.response, LIMIT),
    (error: unknown) => {
      assert.ok(error instanceof BodyReadError);
      // A SerpAxiError, so a provider that never looks at it still exits with a
      // one-line runtime error and not a stack trace.
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "runtime");
      assert.equal(error.message, "network error reading Example response: socket hung up");
      assert.equal(error.cause, boom);
      assert.equal(error.timedOut, false);
      return true;
    },
  );
});

test("readBodyText flags a stream that died of a timeout or an abort", async () => {
  for (const name of ["TimeoutError", "AbortError"]) {
    const timeout = new Error("The operation was aborted due to timeout");
    timeout.name = name;
    const tracked = trackedResponse([bytes("abc")], {}, timeout);
    await assert.rejects(
      () => readBodyText(tracked.response, LIMIT),
      (error: unknown) => error instanceof BodyReadError && error.timedOut && error.cause === timeout,
      name,
    );
  }
});

test("readBodyText gives a cap overflow and a stream failure different errors", async () => {
  // The positive half of the pair above: an overflow is a plain SerpAxiError, so a
  // caller that treats every BodyReadError as a dropped transfer is not told that
  // an oversized body was one.
  const over = trackedResponse([bytes("0123456789A")]);
  await assert.rejects(
    () => readBodyText(over.response, LIMIT),
    (error: unknown) => error instanceof SerpAxiError && !(error instanceof BodyReadError),
  );
});

test("readBodyText keeps a long stream-failure message to one bounded line", async () => {
  const tracked = trackedResponse([bytes("abc")], {}, new Error("x".repeat(5000)));
  await assert.rejects(
    () => readBodyText(tracked.response, LIMIT),
    (error: unknown) => error instanceof BodyReadError && error.message.length < 300,
  );
});

test("readBodyText returns an empty string for a response with no body", async () => {
  assert.equal(await readBodyText(new Response(null, { status: 204 }), LIMIT), "");
});

test("readErrorBody returns a short body whole", async () => {
  assert.equal(await readErrorBody(new Response('{"message":"bad zone"}', { status: 400 })), '{"message":"bad zone"}');
});

test("readErrorBody keeps a prefix of a huge body and hangs up on the rest", async () => {
  const chunk = new Uint8Array(ERROR_BODY_MAX_BYTES / 4).fill(0x61);
  const tracked = trackedResponse(Array.from({ length: 200 }, () => chunk));

  const text = await readErrorBody(tracked.response);

  assert.equal(text.length, ERROR_BODY_MAX_BYTES);
  assert.ok(tracked.cancelled());
  assert.ok(tracked.pulls() < 10, `read ${tracked.pulls()} of 200 chunks`);
});

test("readErrorBody decodes a character split across two chunks", async () => {
  const encoded = bytes("é");
  const { response } = trackedResponse([encoded.slice(0, 1), encoded.slice(1)]);
  assert.equal(await readErrorBody(response), "é");
});

test("readErrorBody says the body could not be read instead of throwing", async () => {
  const tracked = trackedResponse([bytes("part")], {}, new Error("socket hung up"));

  const text = await readErrorBody(tracked.response);

  assert.match(text, /could not be read/);
  assert.match(text, /socket hung up/);
});

test("readErrorBody reports a locked body as unreadable instead of throwing its TypeError", async () => {
  const response = new Response("part", { status: 500 });
  const lock = response.body!.getReader();
  try {
    const text = await readErrorBody(response);
    assert.match(text, /could not be read/);
    assert.match(text, /locked/i);
  } finally {
    lock.releaseLock();
  }
});

test("the overflow help says which runs read the config key", async () => {
  const over = trackedResponse([bytes("0123456789A")]);
  await assert.rejects(
    () => readBodyText(over.response, LIMIT),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      // A Serper search never opens the config file, so the advice must not send
      // its reader to a key that cannot affect the run.
      assert.match(error.help ?? "", /read by scrape and search --provider searxng/);
      return true;
    },
  );
});

test("the default cap is written once, and help and docs restate it from DEFAULT_MAX_RESPONSE_BYTES", () => {
  const bytes = String(DEFAULT_MAX_RESPONSE_BYTES);
  const mib = String(DEFAULT_MAX_RESPONSE_BYTES / (1024 * 1024));

  // Both commands build their help from the constant, so a change reaches them.
  for (const command of [searchCommand, scrapeCommand]) {
    assert.match(command.help, new RegExp(`Default: ${bytes}\\s*\\(${mib} MiB\\)`), command.name);
  }
  // No command or error example keeps a typed-in copy beside the constant.
  for (const file of ["commands/search.ts", "commands/scrape.ts", "response-limit.ts"]) {
    const source = readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
    assert.doesNotMatch(
      source,
      new RegExp(`\\b${bytes}\\b|\\b${mib} MiB\\b`),
      `${file} restates the default cap instead of deriving it`,
    );
  }

  // Prose cannot interpolate, so each hand-written copy stays pinned to the constant.
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  const doc = readFileSync(new URL("../docs/things-that-look-like-bugs.md", import.meta.url), "utf8");
  assert.match(readme, new RegExp(`\\| \`--max-response-bytes <n>\` \\| \`${bytes}\` \\|`), "search flag table");
  assert.match(readme, new RegExp(`\\| Response size \\|.*\\| ${bytes} \\(${mib} MiB\\) \\|`), "response size table");
  assert.match(readme, new RegExp(`default ${bytes} `), "environment variable table");
  assert.match(doc, new RegExp(`\`DEFAULT_MAX_RESPONSE_BYTES\`, ${mib} MiB`), "Bright Data cap entry");
  assert.match(doc, new RegExp(`\\(default ${mib} MiB\\)`), "over-cap entry");
});
