import {
  DEFAULT_MAX_RESPONSE_BYTES,
  MAX_RESPONSE_BYTES_CONFIG_KEY,
  MAX_RESPONSE_BYTES_ENV,
  MAX_RESPONSE_BYTES_FLAG,
} from "./body.ts";
import type { StoredConfig } from "./config.ts";
import {
  requestIntegerSetting,
  resolveIntegerSetting,
  settingExamples,
  type IntegerSettingShape,
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
  examples: settingExamples(NAMES, String(DEFAULT_MAX_RESPONSE_BYTES)),
  textShape: "a whole number of bytes",
  configShape: "a JSON integer number of bytes",
};

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
  return requestIntegerSetting(flag, env, SHAPE);
}

/**
 * Fills the cap the flag and env var left open: the config key, then the default.
 * A search that never opens the config file passes none, and gets the default;
 * why is in docs/things-that-look-like-bugs.md.
 */
export function resolveMaxResponseBytes(request: number | undefined, config: StoredConfig | undefined): number {
  return resolveIntegerSetting(request, config?.maxResponseBytes, SHAPE, DEFAULT_MAX_RESPONSE_BYTES);
}
