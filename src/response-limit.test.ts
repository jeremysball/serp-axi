import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_MAX_RESPONSE_BYTES } from "./body.ts";
import { SerpAxiError } from "./errors.ts";
import { requestMaxResponseBytes, resolveMaxResponseBytes } from "./response-limit.ts";

function usageError(pattern: RegExp) {
  return (error: unknown) => {
    assert.ok(error instanceof SerpAxiError, `expected a SerpAxiError, got ${String(error)}`);
    assert.equal(error.kind, "usage");
    assert.match(error.message, pattern);
    return true;
  };
}

test("requestMaxResponseBytes takes the flag over the env var", () => {
  assert.equal(requestMaxResponseBytes("2048", "4096"), 2048);
});

test("requestMaxResponseBytes falls back to the env var, then to nothing", () => {
  assert.equal(requestMaxResponseBytes(undefined, "4096"), 4096);
  assert.equal(requestMaxResponseBytes(undefined, undefined), undefined);
});

test("requestMaxResponseBytes treats an empty env var as unset, as the other caps do", () => {
  assert.equal(requestMaxResponseBytes(undefined, ""), undefined);
  assert.equal(requestMaxResponseBytes("512", ""), 512);
});

test("requestMaxResponseBytes refuses an empty flag value, which was typed on purpose", () => {
  assert.throws(() => requestMaxResponseBytes("", undefined), usageError(/--max-response-bytes/));
});

test("requestMaxResponseBytes names the flag when the flag is wrong", () => {
  for (const bad of ["0", "abc", "1.5", "-3", "1e6", " 10", "9007199254740992"]) {
    assert.throws(() => requestMaxResponseBytes(bad, undefined), usageError(/--max-response-bytes/), `flag ${bad}`);
  }
});

test("requestMaxResponseBytes names the env var when the env var is wrong", () => {
  for (const bad of ["0", "abc", "1.5", "-3", "9007199254740992"]) {
    assert.throws(
      () => requestMaxResponseBytes(undefined, bad),
      usageError(/SERP_AXI_MAX_RESPONSE_BYTES/),
      `env ${bad}`,
    );
  }
});

test("requestMaxResponseBytes does not check an env var the flag overrides", () => {
  assert.equal(requestMaxResponseBytes("512", "abc"), 512);
});

test("requestMaxResponseBytes says what a good value looks like", () => {
  assert.throws(
    () => requestMaxResponseBytes("abc", undefined),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, /a whole number of bytes/);
      assert.match(error.help ?? "", /--max-response-bytes/);
      return true;
    },
  );
});

test("resolveMaxResponseBytes puts the flag or env value ahead of the config key", () => {
  assert.equal(resolveMaxResponseBytes(100, { maxResponseBytes: 200 }), 100);
});

test("resolveMaxResponseBytes uses the config key when the flag and env var are silent", () => {
  assert.equal(resolveMaxResponseBytes(undefined, { maxResponseBytes: 200 }), 200);
});

test("resolveMaxResponseBytes treats a null or missing config key as unset", () => {
  assert.equal(resolveMaxResponseBytes(undefined, { maxResponseBytes: null }), DEFAULT_MAX_RESPONSE_BYTES);
  assert.equal(resolveMaxResponseBytes(undefined, {}), DEFAULT_MAX_RESPONSE_BYTES);
});

test("resolveMaxResponseBytes falls back to the default when no config is given", () => {
  // The search providers that never open the config file pass none.
  assert.equal(resolveMaxResponseBytes(undefined, undefined), DEFAULT_MAX_RESPONSE_BYTES);
  assert.equal(resolveMaxResponseBytes(300, undefined), 300);
});

test("resolveMaxResponseBytes names the config key when the config value is wrong", () => {
  for (const bad of ["100", 0, -5, 1.5, true, [100], {}]) {
    assert.throws(
      () => resolveMaxResponseBytes(undefined, { maxResponseBytes: bad }),
      usageError(/maxResponseBytes/),
      `config ${JSON.stringify(bad)}`,
    );
  }
});

test("resolveMaxResponseBytes does not read a config value that a flag or env var overrides", () => {
  assert.equal(resolveMaxResponseBytes(100, { maxResponseBytes: "junk" }), 100);
});

test("the default cap is 64 MiB", () => {
  // A judgment call, written down so changing it is a decision. The reasoning is
  // in the doc comment on DEFAULT_MAX_RESPONSE_BYTES.
  assert.equal(DEFAULT_MAX_RESPONSE_BYTES, 64 * 1024 * 1024);
});
