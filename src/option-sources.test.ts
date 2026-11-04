import assert from "node:assert/strict";
import test from "node:test";
import { usageError } from "./error-assertions.ts";
import { SerpAxiError } from "./errors.ts";
import { firstDefined, parseIntegerSetting, pickOption, settingExamples, type IntegerSettingShape } from "./option-sources.ts";

const shape: IntegerSettingShape = {
  names: { flag: "--wait-ms", env: "SERP_AXI_WAIT_MS", config: "waitMs" },
  examples: { flag: "--wait-ms 500", env: "SERP_AXI_WAIT_MS=500", config: '"waitMs": 500' },
  textShape: "an integer number of milliseconds",
  configShape: "a JSON number of milliseconds",
};

test("pickOption returns the flag first, then env, then config, and says which", () => {
  assert.deepEqual(pickOption("f", "e", "c"), { value: "f", source: "flag" });
  assert.deepEqual(pickOption(undefined, "e", "c"), { value: "e", source: "env" });
  assert.deepEqual(pickOption(undefined, undefined, "c"), { value: "c", source: "config" });
});

test("pickOption returns undefined when no source speaks", () => {
  assert.equal(pickOption(undefined, undefined, undefined), undefined);
});

test("pickOption counts only undefined as unset, so an empty string, null or 0 still wins", () => {
  assert.deepEqual(pickOption("", "e", "c"), { value: "", source: "flag" });
  assert.deepEqual(pickOption(undefined, "", "c"), { value: "", source: "env" });
  assert.deepEqual(pickOption<unknown>(undefined, undefined, null), { value: null, source: "config" });
  assert.deepEqual(pickOption<unknown>(undefined, undefined, 0), { value: 0, source: "config" });
});

test("firstDefined returns the first layer that has a value, with the source it carries", () => {
  assert.deepEqual(
    firstDefined([
      { value: undefined, source: "profile" },
      { value: 7, source: "config" },
      { value: 9, source: "default" },
    ]),
    { value: 7, source: "config" },
  );
});

test("firstDefined returns undefined when no layer has a value, or there are none", () => {
  assert.equal(firstDefined([{ value: undefined, source: "a" }]), undefined);
  assert.equal(firstDefined<number, string>([]), undefined);
});

test("firstDefined counts only undefined as unset, so null, an empty string and 0 still win", () => {
  assert.deepEqual(firstDefined<unknown, string>([{ value: null, source: "a" }, { value: 1, source: "b" }]), { value: null, source: "a" });
  assert.deepEqual(firstDefined<unknown, string>([{ value: "", source: "a" }]), { value: "", source: "a" });
  assert.deepEqual(firstDefined<unknown, string>([{ value: 0, source: "a" }]), { value: 0, source: "a" });
});

test("settingExamples spells one sample value in each home's own syntax", () => {
  assert.deepEqual(settingExamples(shape.names, "500"), {
    flag: "--wait-ms 500",
    env: "SERP_AXI_WAIT_MS=500",
    config: '"waitMs": 500',
  });
  // A config value is JSON, so it can differ from the text a flag or env var takes.
  assert.deepEqual(settingExamples({ flag: "--tags", env: "SERP_AXI_TAGS", config: "tags" }, "a,b", '["a", "b"]'), {
    flag: "--tags a,b",
    env: "SERP_AXI_TAGS=a,b",
    config: '"tags": ["a", "b"]',
  });
});

test("parseIntegerSetting reads all-digit text from a flag or env value", () => {
  assert.equal(parseIntegerSetting("500", "flag", shape), 500);
  assert.equal(parseIntegerSetting("0", "env", shape), 0);
  assert.equal(parseIntegerSetting("007", "flag", shape), 7);
});

test("parseIntegerSetting does not range-check, so a huge text value comes back as the number it is", () => {
  assert.equal(parseIntegerSetting("99999999999999999999", "flag", shape), 1e20);
});

test("parseIntegerSetting rejects text that is not all digits, naming the flag and the text shape", () => {
  for (const bad of ["", "1.5", "-1", "+1", " 1", "1 ", "1e3", "0x10", "abc"]) {
    assert.throws(
      () => parseIntegerSetting(bad, "flag", shape),
      usageError(/^--wait-ms must be an integer number of milliseconds, got string /),
      JSON.stringify(bad),
    );
  }
});

test("parseIntegerSetting names the env var, not the flag, when the bad value came from env", () => {
  assert.throws(
    () => parseIntegerSetting("abc", "env", shape),
    usageError(/^SERP_AXI_WAIT_MS must be an integer number of milliseconds, got string "abc"$/),
  );
});

test("parseIntegerSetting rejects a non-string flag or env value", () => {
  assert.throws(() => parseIntegerSetting(500, "env", shape), usageError(/^SERP_AXI_WAIT_MS must be an integer number of milliseconds, got number 500$/));
  assert.throws(() => parseIntegerSetting(undefined, "flag", shape), usageError(/^--wait-ms must be an integer number of milliseconds, got /));
});

test("parseIntegerSetting takes a config value only if it is a JSON integer", () => {
  assert.equal(parseIntegerSetting(500, "config", shape), 500);
  assert.equal(parseIntegerSetting(0, "config", shape), 0);
  assert.equal(parseIntegerSetting(-3, "config", shape), -3);
});

test("parseIntegerSetting rejects a config string, float, null, array and boolean, naming the config key", () => {
  for (const bad of ["500", 1.5, null, [500], true]) {
    assert.throws(
      () => parseIntegerSetting(bad, "config", shape),
      usageError(/^waitMs must be a JSON number of milliseconds, got /),
      JSON.stringify(bad),
    );
  }
});

test("parseIntegerSetting puts the example for the source the value came from in the help line", () => {
  const helpFor = (raw: unknown, source: "flag" | "env" | "config"): string => {
    try {
      parseIntegerSetting(raw, source, shape);
    } catch (error) {
      assert.ok(error instanceof SerpAxiError);
      return error.help;
    }
    throw new Error("expected parseIntegerSetting to throw");
  };
  assert.equal(helpFor("abc", "flag"), "example: --wait-ms 500");
  assert.equal(helpFor("abc", "env"), "example: SERP_AXI_WAIT_MS=500");
  assert.equal(helpFor("abc", "config"), 'example: "waitMs": 500');
});
