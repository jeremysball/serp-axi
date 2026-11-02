import { SerpAxiError, describeValue } from "./errors.ts";

/**
 * Where a setting's value came from. Every tunable has up to three homes, checked
 * flag first, then environment variable, then config file key.
 */
export type OptionSource = "flag" | "env" | "config";

/** What one setting is called in each of its homes. An error names the home the bad value came from. */
export interface SettingNames {
  flag: string;
  env: string;
  config: string;
}

export interface PickedOption<T> {
  value: T;
  source: OptionSource;
}

/**
 * One sample value written the way each home writes it: a flag and a
 * `NAME=value` env var take the text as is, a config key takes JSON. Pass
 * `json` only when the JSON spelling differs from the text, as a list does.
 */
export function settingExamples(names: SettingNames, text: string, json: string = text): SettingNames {
  return { flag: `${names.flag} ${text}`, env: `${names.env}=${text}`, config: `"${names.config}": ${json}` };
}

/**
 * Flag > env > config. Returns the winning value and which home it came from, or
 * undefined when none of them spoke. Only `undefined` counts as unset: an empty
 * string, `null` and `0` are values, so the validator sees them and says why they
 * are wrong. A caller that wants `null` to mean unset must test for it first.
 */
export function pickOption<T>(flag: T | undefined, env: T | undefined, config: T | undefined): PickedOption<T> | undefined {
  if (flag !== undefined) return { value: flag, source: "flag" };
  if (env !== undefined) return { value: env, source: "env" };
  if (config !== undefined) return { value: config, source: "config" };
  return undefined;
}

/** How an integer setting is written and what to call it when the value is wrong. */
export interface IntegerSettingShape {
  names: SettingNames;
  /** One example per home, shown in the error's help line. */
  examples: SettingNames;
  /** What a flag or env value must be, as the error says it: "an integer number of milliseconds". */
  textShape: string;
  /** What a config value must be, as the error says it: "a JSON number of milliseconds". */
  configShape: string;
}

/**
 * Reads one integer setting from the home it came from. A flag or env value
 * arrives as text and must be all digits; a config value must already be a JSON
 * integer. Either way the error names the home the bad value came from, so the
 * reader fixes the right place.
 *
 * This checks the type only. A config integer may be negative here, and a long
 * run of digits comes back as the number it rounds to, so the caller applies its
 * own range and says what the range is.
 */
export function parseIntegerSetting(raw: unknown, source: OptionSource, shape: IntegerSettingShape): number {
  const field = shape.names[source];
  if (source === "config") {
    if (typeof raw !== "number" || !Number.isInteger(raw)) {
      throw new SerpAxiError(`${field} must be ${shape.configShape}, got ${describeValue(raw)}`, "usage", `example: ${shape.examples.config}`);
    }
    return raw;
  }
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) {
    throw new SerpAxiError(`${field} must be ${shape.textShape}, got ${describeValue(raw)}`, "usage", `example: ${shape.examples[source]}`);
  }
  return Number(raw);
}
