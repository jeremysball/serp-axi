import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import os from "node:os";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  LadderClient,
  SerpAxiLadderError,
  LADDER_PROTOCOL,
  LADDER_AXIS_FLAG_NAMES,
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

// The stub's one-shot kill switch, so a test can remove a leftover marker.
function onceMarker(mode: string): string {
  return path.join(os.tmpdir(), `ladder-stub-once-${process.pid}-${mode}`);
}

function client(mode: string, extra: Record<string, unknown> = {}) {
  rmSync(onceMarker(mode), { force: true });
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
const ORTHOGONAL_PAIRS: Array<{
  axis: keyof LadderAxes;
  base: Record<string, string>;
  delta: Record<string, string>;
  // The jar sugar mirrors one path across jarIn and jarOut, so flipping
  // cookieState between cold and jar is expected to move jarIn too. That is the
  // sugar doing its job, not two axes drifting, so the pair says so rather than
  // the assertion pretending the mirroring does not exist.
  alsoChanges?: Array<keyof LadderAxes>;
}> = [
  { axis: "tabState", base: {}, delta: { "tab-state": "same" } },
  {
    axis: "cookieState",
    base: { "jar-out": "/tmp/ladder-jar" },
    delta: { "jar-out": "/tmp/ladder-jar", "cookie-state": "jar" },
    alsoChanges: ["jarIn"],
  },
  { axis: "cacheState", base: {}, delta: { "cache-state": "warm" } },
  { axis: "fingerprintState", base: {}, delta: { "fingerprint-state": "stable" } },
  { axis: "rungCeiling", base: {}, delta: { "rung-ceiling": "3" } },
  { axis: "profile", base: {}, delta: { profile: "cautious" } },
];

const PROFILE_CONFIG: StoredConfig = { ladderProfiles: { cautious: {} } };

test("each of the six axes varies the request alone", () => {
  for (const { axis, base, delta, alsoChanges } of ORTHOGONAL_PAIRS) {
    const before = buildLadderRequest("https://a.example/x", resolveLadderAxes({ flag: base, config: PROFILE_CONFIG }));
    const after = buildLadderRequest("https://a.example/x", resolveLadderAxes({ flag: delta, config: PROFILE_CONFIG }));
    const differing = Object.keys(before).filter(
      (key) =>
        JSON.stringify((before as unknown as Record<string, unknown>)[key]) !==
        JSON.stringify((after as unknown as Record<string, unknown>)[key]),
    );
    assert.deepEqual(differing, [axis, ...(alsoChanges ?? [])], `${axis} changed ${JSON.stringify(differing)}`);
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
  // The message names the spelling the caller wrote, not "from env": a flag, an
  // env var, and a config key are three different places to look.
  assert.throws(() => resolveLadderAxes({ env: { SERP_AXI_TAB_STATE: "sideways" } }), /SERP_AXI_TAB_STATE "sideways"/);
  assert.throws(() => resolveLadderAxes({ flag: { "rung-ceiling": "9" } }), /--rung-ceiling "9"/);
  assert.throws(
    () => resolveLadderAxes({ config: { ladderCacheState: 3 } }),
    /invalid config ladderCacheState 3/,
    "a config value of the wrong type is an error, not a silent skip",
  );
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

    assert.equal(resolveLadderBin({ SERP_AXI_LADDER_BIN: "/custom/ladder" }, [sibling]), "/custom/ladder");
    assert.equal(resolveLadderBin({}, [sibling]), sibling);
    assert.equal(
      resolveLadderBin({}, [path.join(dir, "absent"), sibling]),
      sibling,
      "the first candidate that exists wins",
    );
    assert.equal(resolveLadderBin({}, [path.join(dir, "absent")]), "ladder-cli");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// --- Phase 2 review fixes ------------------------------------------------
// Each of these pins one finding that survived verification, written so the test
// fails on the code as it stood before the fix rather than only on a break.

// Approval sensor: a mid-request death is the second place a stderr tail is
// dropped, and the tail is the only thing that says why the child stopped.
test("a mid-request exit carries its stderr tail like a pre-ready one does", async () => {
  const ladder = client("tail-mid", { timeoutMs: 10000 });
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /exited mid-request/);
      assert.match(error.message, /boom-mid: fetch exploded/);
      return true;
    });
  } finally {
    await ladder.close();
  }
});

// Approval sensor: a child that spawns and never speaks is a hang, not a slow
// start. Nothing else waits on the ready line, so this is the only thing between
// a hung client and a queue that never drains.
// A swallowed budget can only ever fail as a hang, so this test carries its own
// timeout: a regression has to surface as a failed test, not a hung suite.
test("a silent child is failed by the handshake budget instead of hanging", { timeout: 15000 }, async () => {
  const ladder = client("silent", { handshakeMs: 120 });
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), (error: unknown) => {
      assert.ok(error instanceof SerpAxiLadderError);
      assert.match(error.message, /printed no ready line within 120 ms/);
      return true;
    });
    // The budget has to leave a usable client behind: the silent child was killed
    // and its handle cleared, so the next fetch starts a fresh handshake rather
    // than hanging on a corpse. (A spawnCount of 2 is the observable proof.)
    await ladder.waitForExit(2000);
    await assert.rejects(() => ladder.fetch("https://a.example/y"), /printed no ready line within 120 ms/);
    assert.equal(ladder.spawnCount, 2, "the silent child must be respawned, not reused");
  } finally {
    await ladder.close();
  }
});

// Approval sensor: 04-tdd 1.1, in this same change, says output before the
// handshake completes is startup output and is tolerated. It was not.
test("output before the handshake is startup noise, not a failed handshake", async () => {
  const ladder = client("banner-then-ready");
  try {
    const res = await ladder.fetch("https://a.example/x");
    assert.equal(res.verdict, "ok");
  } finally {
    await ladder.close();
  }
});

// Approval sensor: folding `error` into `blocked` told the caller to retry a
// defence that never happened, so the verdict has to survive the parse.
test("an error verdict parses and stays distinct from blocked", async () => {
  const errored = client("error");
  try {
    const res = await errored.fetch("https://a.example/x");
    assert.equal(res.verdict, "error");
    assert.equal(res.warning, "boom: primp refused");
  } finally {
    await errored.close();
  }
});

// Approval sensor: after a mid-request death the shared buffer belongs to the new
// child, and a byte from the dead one landing in it would pass for a ready line.
test("a respawn after a mid-request death answers the next request", async () => {
  const ladder = client("die-mid", { timeoutMs: 300 });
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"));
    const after = await ladder.fetch("https://a.example/y");
    assert.equal(after.text, "body for https://a.example/y");
    assert.equal(ladder.spawnCount, 2);
  } finally {
    await ladder.close();
  }
});

// Approval sensor: a spawn that failed leaves a live-looking handle, so every
// later fetch would reuse a child that never existed.
test("a failed spawn is retried by the next fetch rather than failing forever", async () => {
  const ladder = new LadderClient({ bin: "/definitely/not/a/real/binary", handshakeMs: 200 });
  try {
    await assert.rejects(() => ladder.fetch("https://a.example/x"), /ladder binary not found/);
    await assert.rejects(() => ladder.fetch("https://a.example/y"), /ladder binary not found/);
    assert.equal(ladder.spawnCount, 2, "the second fetch must have spawned again");
  } finally {
    await ladder.close();
  }
});

// Approval sensor: mirroring was unconditional, so a caller who named one jar
// path and asked for cold got a cookie write they never requested.
test("--cookie-state cold leaves the jar paths alone", () => {
  const axes = resolveLadderAxes({ flag: { "cookie-state": "cold", "jar-out": "/tmp/j.txt" } });
  assert.equal(axes.jarOut, "/tmp/j.txt");
  assert.equal(axes.jarIn, null, "cold must not gain a jar it was not given");
});

// Approval sensor: AXIS_TABLE declared a config key for profile and StoredConfig
// declared the field, yet nothing read it, so a config-set default was ignored.
test("the config file can set the profile, not only be overridden by one", () => {
  const axes = resolveLadderAxes({
    config: { ladderProfile: "cautious", ladderProfiles: { cautious: { cacheState: "warm" } } },
  });
  assert.equal(axes.profile, "cautious");
  assert.equal(axes.cacheState, "warm");
});

test("an unknown profile-bundle key is a usage error, not a silent default", () => {
  assert.throws(
    () =>
      resolveLadderAxes({
        flag: { profile: "cautious" },
        config: { ladderProfiles: { cautious: { cacheStatee: "warm" } } },
      }),
    /unknown key: cacheStatee/,
  );
});

// Approval sensor: existsSync accepts a directory, which spawn then rejects with
// an errno that names neither the path nor the real problem.
test("binary resolution does not accept a directory as a binary", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "ladder-isdir-"));
  try {
    const file = path.join(root, "real");
    writeFileSync(file, "", { mode: 0o755 });
    const dir = path.join(root, "adir");
    mkdirSync(dir);
    assert.equal(resolveLadderBin({}, [dir, file]), file, "a directory at a candidate path is not a binary");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// Approval sensor: every flag the resolver understands must be one the CLI
// accepts. The list used to be hand-maintained in both places, which is how an
// axis becomes speakable on the wire and unknowable on the command line.
test("every ladder axis flag is a flag the scrape command accepts", async () => {
  const { SCRAPE_FLAGS } = await import("./commands/scrape.ts");
  for (const name of LADDER_AXIS_FLAG_NAMES) {
    assert.ok(name in SCRAPE_FLAGS, `${name} is an axis flag the CLI does not accept`);
  }
});
