import {
  DEFAULT_MAX_RESPONSE_BYTES,
  MAX_RESPONSE_BYTES_CONFIG_KEY,
  MAX_RESPONSE_BYTES_ENV,
  MAX_RESPONSE_BYTES_FLAG,
} from "./body.ts";
import type { StoredConfig } from "./config.ts";
import { SerpAxiError } from "./errors.ts";
import {
  parseIntegerSetting,
  pickOption,
  settingExamples,
  type IntegerSettingShape,
  type OptionSource,
  type SettingNames,
} from "./option-sources.ts";

/**
 * The byte cap on a provider response, from its three homes: `--max-response-bytes`,
 * `SERP_AXI_MAX_RESPONSE_BYTES`, and the `maxResponseBytes` config key, in that
 * order, then the built-in default. What the cap guards is in `body.ts`.
 */

const NAMES: SettingNames = {
  flag: MAX_RESPONSE_BYTES_FLAG,
  env: MAX_RESPONSE_BYTES_ENV,
  config: MAX_RESPONSE_BYTES_CONFIG_KEY,
};

const SHAPE: IntegerSettingShape = {
  names: NAMES,
  examples: settingExamples(NAMES, "67108864"),
  textShape: "a whole number of bytes",
  configShape: "a JSON integer number of bytes",
};

function validate(raw: unknown, source: OptionSource): number {
  const value = parseIntegerSetting(raw, source, SHAPE);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new SerpAxiError(
      `${NAMES[source]} must be a whole number of bytes from 1 to ${Number.MAX_SAFE_INTEGER}, got ${String(raw)}`,
      "usage",
      `example: ${SHAPE.examples[source]}`,
    );
  }
  return value;
}

/**
 * Flag > env, checked before any network call and before any config file is
 * opened. Only the source that wins is checked, so a bad env var does not fail a
 * run that passes the flag. Returns `undefined` when neither speaks, which leaves
 * the config key and the default.
 *
 * An empty env var is unset, so `SERP_AXI_MAX_RESPONSE_BYTES=` in a shell profile
 * does not stop every run. An empty flag value is an error: it was typed here.
 */
export function requestMaxResponseBytes(flag: string | undefined, env: string | undefined): number | undefined {
  const picked = pickOption(flag, env === "" ? undefined : env, undefined);
  return picked === undefined ? undefined : validate(picked.value, picked.source);
}

/**
 * Fills the cap the flag and env var left open: the config key, then the default.
 * A search that never opens the config file passes none, and gets the default;
 * why is in docs/things-that-look-like-bugs.md.
 */
export function resolveMaxResponseBytes(request: number | undefined, config: StoredConfig | undefined): number {
  if (request !== undefined) return request;
  const fromConfig = config?.maxResponseBytes;
  // Null and absent both mean "not set", as they do for maxChars.
  if (fromConfig === undefined || fromConfig === null) return DEFAULT_MAX_RESPONSE_BYTES;
  return validate(fromConfig, "config");
}
