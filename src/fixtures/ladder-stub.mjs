// Test double for ladder-cli: speaks the Phase 1 NDJSON contract.
// Usage: node ladder-stub.mjs --mode ok|blocked|dead|malformed|die-before-ready|slow
import readline from "node:readline";

const modeIndex = process.argv.indexOf("--mode");
const mode = process.env.LADDER_STUB_MODE ?? (modeIndex >= 0 ? process.argv[modeIndex + 1] : undefined) ?? "ok";

if (mode === "die-before-ready") {
  process.stderr.write("boom-startup: config missing\n");
  process.exit(1);
}

process.stdout.write(JSON.stringify({ ready: true, protocol: 1 }) + "\n");

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
  if (mode === "die-mid") {
    setTimeout(() => process.exit(1), 50);
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
  const text = await bodyFor(url);
  process.stdout.write(
    JSON.stringify({ verdict: "ok", rungReached: 1, title: "T", text, engines: [], elapsedMs: 1, warning: null }) + "\n",
  );
});
