// Test double for ladder-cli: speaks the NDJSON contract.
// Usage: node ladder-stub.mjs --mode ok|blocked|dead|malformed|die-before-ready|die-mid|slow|empty-ok|bad-protocol|echo-request|banner-then-ready|silent|error|tail-mid
import readline from "node:readline";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const modeIndex = process.argv.indexOf("--mode");
const mode = process.env.LADDER_STUB_MODE ?? (modeIndex >= 0 ? process.argv[modeIndex + 1] : undefined) ?? "ok";

// A kill switch that fires once per parent, so a test can watch the client die
// once and then answer a later request on the respawned child. Keyed by the
// parent's pid: two spawns from one client share it, a different client does not.
const ONCE_MARKER = path.join(os.tmpdir(), `ladder-stub-once-${process.ppid}-${mode}`);

if (mode === "die-before-ready") {
  process.stderr.write("boom-startup: config missing\n");
  process.exit(1);
}

// A child that spawns and never says hello. Nothing is printed at all, so the
// only thing standing between it and a permanent hang is the handshake budget.
if (mode === "silent") {
  setTimeout(() => {}, 1 << 30);
} else {
  // §1.1: anything before the handshake completes is startup output and is
  // skipped rather than fatal. This mode prints exactly that before the ready
  // line so the parent's tolerance is exercised instead of assumed.
  if (mode === "banner-then-ready") {
    process.stdout.write("LADDER_STUB_DEBUG: loading profile\n\n");
  }

  // A mismatched protocol must fail at the handshake, so this mode announces a
  // protocol the parent does not speak before any request is read.
  process.stdout.write(JSON.stringify({ ready: true, protocol: mode === "bad-protocol" ? 2 : 1 }) + "\n");
}

// A silent child never reaches the read loop, so it cannot be woken by stdin
// either: the parent's only route out is its own budget.
const input = readline.createInterface({ input: process.stdin });

function bodyFor(url) {
  if (mode === "slow" && url.includes("slow.example")) {
    return new Promise((resolve) => setTimeout(() => resolve(`body for ${url}`), 2000));
  }
  return Promise.resolve(`body for ${url}`);
}

input.on("line", async (line) => {
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    return;
  }
  const url = request.url ?? "";
  if ((mode === "die-mid" || mode === "tail-mid") && !existsSync(ONCE_MARKER)) {
    mkdirSync(path.dirname(ONCE_MARKER), { recursive: true });
    writeFileSync(ONCE_MARKER, "");
    // A mid-request death has to carry its stderr tail, the same as a pre-ready
    // one: without it the caller learns that the child stopped and nothing
    // about why.
    if (mode === "tail-mid") process.stderr.write("boom-mid: fetch exploded\n");
    setTimeout(() => process.exit(1), 20);
    return;
  }
  if (mode === "malformed") {
    process.stdout.write("not json at all\n");
    return;
  }
  if (mode === "blocked") {
    process.stdout.write(
      JSON.stringify({ verdict: "blocked", rungReached: 4, title: "", text: "", engines: [], elapsedMs: 1, warning: null }) + "\n",
    );
    return;
  }
  if (mode === "dead") {
    process.stdout.write(
      JSON.stringify({ verdict: "dead", rungReached: 1, title: "", text: "", engines: [], elapsedMs: 1, warning: null }) + "\n",
    );
    return;
  }
  // §1.3: an ok verdict with no text is a schema violation, not a small
  // success. This mode reproduces exactly that shape.
  if (mode === "empty-ok") {
    process.stdout.write(
      JSON.stringify({ verdict: "ok", rungReached: 1, title: "", text: "", engines: [], elapsedMs: 1, warning: null }) + "\n",
    );
    return;
  }
  // A climb that ran out of rungs because a rung malfunctioned is its own
  // verdict, not "blocked": the caller has to answer differently.
  if (mode === "error") {
    process.stdout.write(
      JSON.stringify({ verdict: "error", rungReached: 1, title: "", text: "", engines: [], elapsedMs: 1, warning: "boom: primp refused" }) + "\n",
    );
    return;
  }
  // Echo the request back as the page text so a test can assert what the
  // parent actually put on the wire, not just what it resolved locally.
  if (mode === "echo-request") {
    process.stdout.write(
      JSON.stringify({ verdict: "ok", rungReached: 1, title: "T", text: JSON.stringify(request), engines: [], elapsedMs: 1, warning: null }) + "\n",
    );
    return;
  }
  const text = await bodyFor(url);
  process.stdout.write(
    JSON.stringify({ verdict: "ok", rungReached: 1, title: "T", text, engines: [], elapsedMs: 1, warning: null }) + "\n",
  );
});
