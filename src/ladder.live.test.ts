import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { fetchViaLadder, resolveLadderBin, resolveLadderAxes } from "./ladder.ts";

// Live rung-1 fetch, never in CI: it needs the ladder-cli venv and a real
// network path, so the plan requires it by hand rather than in a suite. Opt in
// with SERP_AXI_LIVE_LADDER=1 after `cd ladder-cli && uv sync`.
const bin = resolveLadderBin({});
const skip = process.env.SERP_AXI_LIVE_LADDER !== "1" || !existsSync(bin);

test("ladder-cli answers a rung-1 URL end to end", { skip }, async () => {
  const response = await fetchViaLadder("https://en.wikipedia.org/wiki/Web_scraping", { bin }, resolveLadderAxes({}));
  assert.equal(response.verdict, "ok");
  assert.equal(response.rungReached, 1);
  assert.ok(response.text.length > 800, `expected real prose, got ${response.text.length} chars`);
  assert.ok(response.title.length > 0);
});

test("a thin page is refused with a reason rather than returned as an empty ok", { skip }, async () => {
  const response = await fetchViaLadder("https://example.com/", { bin }, resolveLadderAxes({}));
  assert.equal(response.verdict, "blocked");
  assert.match(response.warning ?? "", /under rung-1 floor/);
});
