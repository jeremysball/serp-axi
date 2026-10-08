import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import os from "node:os";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  LadderClient,
  SerpAxiLadderError,
  LADDER_PROTOCOL,
  buildLadderRequest,
  resolveLadderAxes,
  resolveLadderBin,
  type LadderAxes,
} from "./ladder.ts";
import type { StoredConfig } from "./config.ts";

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

// Approval sensor 1: a stale installed ladder-cli must fail at the handshake
// with both protocol numbers named, not misparse the requests after it.
test("a protocol mismatch fails at the handshake and names both sides", async () => {
  const ladder = client("bad-protocol");
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /protocol mismatch/);
      assert.match(error.message, /speaks protocol 1/);
      assert.match(error.message, /reported protocol 2/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

// Approval sensor 2: §1.3 says an ok verdict with no text is a schema
// violation, never a small success.
test("verdict ok with empty text is a schema violation, not a success", async () => {
  const ladder = client("empty-ok");
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /verdict "ok" with empty text/);
      assert.match(error.message, /schema violation/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

test("the request on the wire carries protocol plus all nine fields", async () => {
  const ladder = client("echo-request");
  try {
    const res = await ladder.fetch("https://a.example/x", resolveLadderAxes({}));
    const sent = JSON.parse(res.text) as Record<string, unknown>;
    assert.deepEqual(
      Object.keys(sent).sort(),
      [
        "cacheState",
        "cookieState",
        "fingerprintState",
        "jarIn",
        "jarOut",
        "profile",
        "protocol",
        "rungCeiling",
        "tabState",
        "url",
      ],
    );
    assert.equal(sent.protocol, LADDER_PROTOCOL);
    assert.equal(sent.tabState, "fresh");
    assert.equal(sent.cookieState, "cold");
    assert.equal(sent.cacheState, "cold");
    assert.equal(sent.fingerprintState, "rotate");
    assert.equal(sent.rungCeiling, 5);
    assert.equal(sent.profile, null);
    assert.equal(sent.jarIn, null);
    assert.equal(sent.jarOut, null);
  } finally {
    await ladder.close();
  }
});

// §1.7 axis-orthogonality sensor: each knob varies while the other five hold
// defaults, asserting only its own field changes the request. The cookie-state
// pair carries a jar path in both halves, because a path the sugar needs is
// held constant rather than being the axis under test.
const ORTHOGONAL_PAIRS: Array<{ axis: keyof LadderAxes; base: Record<string, string>; delta: Record<string, string> }> = [
  { axis: "tabState", base: {}, delta: { "tab-state": "same" } },
  {
    axis: "cookieState",
    base: { "jar-out": "/tmp/ladder-jar" },
    delta: { "jar-out": "/tmp/ladder-jar", "cookie-state": "jar" },
  },
  { axis: "cacheState", base: {}, delta: { "cache-state": "warm" } },
  { axis: "fingerprintState", base: {}, delta: { "fingerprint-state": "stable" } },
  { axis: "rungCeiling", base: {}, delta: { "rung-ceiling": "3" } },
  { axis: "profile", base: {}, delta: { profile: "cautious" } },
];

const PROFILE_CONFIG: StoredConfig = { ladderProfiles: { cautious: {} } };

test("each of the six axes varies the request alone", () => {
  for (const { axis, base, delta } of ORTHOGONAL_PAIRS) {
    const before = buildLadderRequest("https://a.example/x", resolveLadderAxes({ flag: base, config: PROFILE_CONFIG }));
    const after = buildLadderRequest("https://a.example/x", resolveLadderAxes({ flag: delta, config: PROFILE_CONFIG }));
    const differing = Object.keys(before).filter(
      (key) =>
        JSON.stringify((before as unknown as Record<string, unknown>)[key]) !==
        JSON.stringify((after as unknown as Record<string, unknown>)[key]),
    );
    assert.deepEqual(differing, [axis], `${axis} changed ${JSON.stringify(differing)}`);
  }
});

test("resolution precedence is flag, then env, then profile, then config, then default", () => {
  assert.equal(
    resolveLadderAxes({
      flag: { "tab-state": "same" },
      env: { SERP_AXI_TAB_STATE: "fresh" },
      config: { ladderTabState: "fresh" },
    }).tabState,
    "same",
    "flag must beat env",
  );
  assert.equal(
    resolveLadderAxes({ env: { SERP_AXI_TAB_STATE: "same" }, config: { ladderTabState: "fresh" } }).tabState,
    "same",
    "env must beat config",
  );
  assert.equal(
    resolveLadderAxes({ config: { ladderTabState: "same" } }).tabState,
    "same",
    "config must beat the default",
  );
  assert.equal(resolveLadderAxes({}).tabState, "fresh", "the documented default must stand");
});

test("a profile bundle expands into exactly its named axes", () => {
  const axes = resolveLadderAxes({
    flag: { profile: "cautious" },
    config: { ladderProfiles: { cautious: { cacheState: "warm", rungCeiling: "2" } } },
  });
  assert.equal(axes.profile, "cautious");
  assert.equal(axes.cacheState, "warm");
  assert.equal(axes.rungCeiling, 2);
  assert.equal(axes.tabState, "fresh");
  assert.equal(axes.cookieState, "cold");
});

test("an invalid axis value names the axis, the value, and its source", () => {
  assert.throws(() => resolveLadderAxes({ env: { SERP_AXI_TAB_STATE: "sideways" } }), /tab-state "sideways" from env/);
  assert.throws(() => resolveLadderAxes({ flag: { "rung-ceiling": "9" } }), /rung-ceiling "9" from flag/);
});

test("an unknown profile is a usage error that names the config file", () => {
  assert.throws(
    () => resolveLadderAxes({ flag: { profile: "nope" }, config: { ladderProfiles: {} } }),
    /unknown ladder profile "nope"/,
  );
});

test("--cookie-state jar refuses to invent a path and mirrors a given one", () => {
  assert.throws(() => resolveLadderAxes({ flag: { "cookie-state": "jar" } }), /needs a jar path/);
  const axes = resolveLadderAxes({ flag: { "cookie-state": "jar", "jar-out": "/tmp/j.txt" } });
  assert.equal(axes.jarIn, "/tmp/j.txt");
  assert.equal(axes.jarOut, "/tmp/j.txt");
});

// Approval sensor 3: env beats sibling beats PATH, and an absent sibling never
// hides a working PATH entry.
test("binary resolution prefers env, then an existing sibling, then PATH", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "ladder-bin-"));
  try {
    const sibling = path.join(dir, "ladder-cli");
    writeFileSync(sibling, "", { mode: 0o755 });

    assert.equal(resolveLadderBin({ SERP_AXI_LADDER_BIN: "/custom/ladder" }, sibling), "/custom/ladder");
    assert.equal(resolveLadderBin({}, sibling), sibling);
    assert.equal(resolveLadderBin({}, path.join(dir, "absent")), "ladder-cli");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
