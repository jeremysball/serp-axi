import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { LadderClient, SerpAxiLadderError } from "./ladder.ts";

const STUB = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "ladder-stub.mjs",
);

function client(mode: string, extra: Record<string, unknown> = {}) {
  return new LadderClient({ bin: process.execPath, args: [STUB, "--mode", mode], ...extra });
}

test("spawns once and reuses the child across sequential fetches", async () => {
  const ladder = client("ok");
  try {
    const first = await ladder.fetch("https://a.example/x");
    const second = await ladder.fetch("https://b.example/y");
    assert.equal(first.verdict, "ok");
    assert.equal(first.text, "body for https://a.example/x");
    assert.equal(second.text, "body for https://b.example/y");
    assert.equal(ladder.spawnCount, 1);
  } finally {
    await ladder.close();
  }
});

test("queues concurrent fetches behind one in-flight request", async () => {
  const ladder = client("ok");
  try {
    const [first, second] = await Promise.all([
      ladder.fetch("https://a.example/x"),
      ladder.fetch("https://b.example/y"),
    ]);
    assert.equal(first.text, "body for https://a.example/x");
    assert.equal(second.text, "body for https://b.example/y");
    assert.equal(ladder.spawnCount, 1);
  } finally {
    await ladder.close();
  }
});

test("returns blocked and dead verdicts distinctly, never as empty-ok", async () => {
  const blocked = client("blocked");
  try {
    const res = await blocked.fetch("https://c.example/z");
    assert.equal(res.verdict, "blocked");
    assert.equal(res.rungReached, 4);
  } finally {
    await blocked.close();
  }
  const dead = client("dead");
  try {
    const res = await dead.fetch("https://d.example/z");
    assert.equal(res.verdict, "dead");
  } finally {
    await dead.close();
  }
});

test("a child that exits before ready fails with its stderr tail", async () => {
  const ladder = client("die-before-ready");
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /exited before ready/);
      assert.match(error.message, /boom-startup/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

test("a malformed response line fails instead of resolving", async () => {
  const ladder = client("malformed");
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /malformed response/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

test("a timed-out request fails while the queued request still resolves", async () => {
  const ladder = client("slow", { timeoutMs: 200 });
  try {
    const [slow, queued] = await Promise.allSettled([
      ladder.fetch("https://slow.example/x"),
      ladder.fetch("https://fast.example/y"),
    ]);
    assert.equal(slow.status, "rejected");
    assert.match(String((slow as PromiseRejectedResult).reason), /timed out/);
    assert.equal(queued.status, "fulfilled");
    assert.equal((queued as PromiseFulfilledResult<{ text: string }>).value.text, "body for https://fast.example/y");
    assert.equal(ladder.spawnCount, 2);
  } finally {
    await ladder.close();
  }
});

test("a mid-request exit fails in-flight and queued requests fast, then respawns", async () => {
  const ladder = client("die-mid", { timeoutMs: 10000 });
  try {
    const start = Date.now();
    const [first, second] = await Promise.allSettled([
      ladder.fetch("https://a.example/x"),
      ladder.fetch("https://b.example/y"),
    ]);
    assert.ok(Date.now() - start < 5000);
    assert.equal(first.status, "rejected");
    assert.equal(second.status, "rejected");
    assert.match(String((first as PromiseRejectedResult).reason), /exited/);
  } finally {
    await ladder.close();
  }
});

test("missing binary names the binary", async () => {
  const ladder = new LadderClient({ bin: "/nonexistent/ladder-cli" });
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /\/nonexistent\/ladder-cli/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

test("idle teardown exits the child after quiet", async () => {
  const ladder = client("ok", { idleMs: 50 });
  const res = await ladder.fetch("https://a.example/x");
  assert.equal(res.verdict, "ok");
  await ladder.waitForExit(2000);
  assert.equal(ladder.exited, true);
});
