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
 * An empty string is unset. Only env vars use this: a flag typed with an empty
 * value is a mistake the caller should see, while `SERP_AXI_FOO=` in a shell
 * profile means the variable is not configured.
 */
export function nonEmpty(value: string | undefined): string | undefined {
  return value !== undefined && value.length > 0 ? value : undefined;
}

/** One place a setting may come from: the value it holds, if any, and a label for where that is. */
export interface Layer<T, S> {
  value: T | undefined;
  source: S;
}

/**
 * The first layer that holds a value, with its source, or undefined when none
 * does. Only `undefined` counts as unset: an empty string, `null` and `0` are
 * values, so a validator sees them and says why they are wrong. A caller that
 * wants `null` to mean unset must turn it into `undefined` before the layer
 * is built.
 */
export function firstDefined<T, S>(layers: readonly Layer<T, S>[]): { value: T; source: S } | undefined {
  for (const layer of layers) {
    if (layer.value !== undefined) return { value: layer.value, source: layer.source };
  }
  return undefined;
}

/** Flag > env > config. Returns the winning value and which home it came from, or undefined when none of them spoke. */
export function pickOption<T>(flag: T | undefined, env: T | undefined, config: T | undefined): PickedOption<T> | undefined {
  return firstDefined<T, OptionSource>([
    { value: flag, source: "flag" },
    { value: env, source: "env" },
    { value: config, source: "config" },
  ]);
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

/**
 * Reads one integer setting and applies the range every such setting shares: a
 * whole number from 1 to `max`. `parseIntegerSetting` checks the type and names
 * the home; this adds the range and says what it is, so each cap does not spell
 * the same sentence again.
 */
export function validateIntegerSetting(
  raw: unknown,
  source: OptionSource,
  shape: IntegerSettingShape,
  max: number = Number.MAX_SAFE_INTEGER,
): number {
  const value = parseIntegerSetting(raw, source, shape);
  if (!Number.isSafeInteger(value) || value < 1 || value > max) {
    throw new SerpAxiError(
      `${shape.names[source]} must be ${shape.textShape} from 1 to ${max}, got ${String(raw)}`,
      "usage",
      `example: ${shape.examples[source]}`,
    );
  }
  return value;
}

/**
 * The request phase of an integer setting: flag > env, checked before any config
 * file is opened. Only the source that wins is checked, so a bad env var does
 * not fail a run that passes the flag. An empty env var is unset; an empty flag
 * value is an error because it was typed on purpose.
 */
export function requestIntegerSetting(
  flag: string | undefined,
  env: string | undefined,
  shape: IntegerSettingShape,
  max: number = Number.MAX_SAFE_INTEGER,
): number | undefined {
  const picked = pickOption(flag, nonEmpty(env), undefined);
  return picked === undefined ? undefined : validateIntegerSetting(picked.value, picked.source, shape, max);
}

/**
 * The config phase of an integer setting: the request wins, then the config
 * key, then the built-in default. Null and absent both mean "not set", as they
 * do for the ladder's config keys; a value the request overrides is not read,
 * so a bad key does not fail a run that already said what it wants.
 */
export function resolveIntegerSetting(
  request: number | undefined,
  configValue: unknown,
  shape: IntegerSettingShape,
  fallback: number,
  max: number = Number.MAX_SAFE_INTEGER,
): number {
  if (request !== undefined) return request;
  if (configValue === undefined || configValue === null) return fallback;
  return validateIntegerSetting(configValue, "config", shape, max);
}
