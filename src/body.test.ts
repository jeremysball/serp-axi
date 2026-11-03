import test from "node:test";
import assert from "node:assert/strict";
import { ERROR_BODY_MAX_BYTES, readBodyText, readErrorBody } from "./body.ts";
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

test("readBodyText still bounds a body that outgrows its declared content-length", async () => {
  const chunks = Array.from({ length: 50 }, () => bytes("abcdef"));
  const tracked = trackedResponse(chunks, { "content-length": "5" });
  await assert.rejects(() => readBodyText(tracked.response, LIMIT), SerpAxiError);
  assert.ok(tracked.pulls() < 10);
});

test("readBodyText lets a stream failure through instead of returning what it had", async () => {
  const boom = new Error("socket hung up");
  const tracked = trackedResponse([bytes("abc")], {}, boom);
  await assert.rejects(() => readBodyText(tracked.response, LIMIT), (error: unknown) => error === boom);
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

test("readErrorBody says the body could not be read instead of returning nothing", async () => {
  const tracked = trackedResponse([bytes("part")], {}, new Error("socket hung up"));

  const text = await readErrorBody(tracked.response);

  assert.match(text, /could not be read/);
  assert.match(text, /socket hung up/);
});
