import { SerpAxiError, describeValue } from "./errors.ts";
import { truncate, type AxiOutput } from "./output.ts";
import type { StoredConfig } from "./config.ts";

export const DEFAULT_MAX_CHARS = 1200;
export const DEFAULT_FULL_MAX_CHARS = 50000;
export const INCLUDE_MARKUP_ENV = "SERP_AXI_INCLUDE_MARKUP";
export const MAX_CHARS_ENV = "SERP_AXI_MAX_CHARS";
export const FULL_MAX_CHARS_ENV = "SERP_AXI_FULL_MAX_CHARS";

/** The two caps a scrape can run under. `--full` picks `fullMaxChars`; every other run uses `maxChars`. */
export interface CharLimits {
  maxChars: number;
  fullMaxChars: number;
}

/** The character limit for one run. Every cut a scrape makes, locally or upstream, takes it from here. */
export function limitFor(full: boolean, limits: CharLimits): number {
  return full ? limits.fullMaxChars : limits.maxChars;
}

/**
 * Which string fields of a record the character limit applies to, and so how a
 * cut is reported. `field` is a provider with one content field (the marker is
 * the bare `truncatedFrom`); `every-string` is a provider whose record shape is
 * not ours to know (the marker is `<key>TruncatedFrom`, one per cut field).
 */
export type TruncationScope =
  | { kind: "field"; key: string }
  | { kind: "every-string"; except: ReadonlySet<string> };

export interface ShapeOptions {
  /** Whether `--full` was given: it picks which cap applies and how a hint is worded. */
  full: boolean;
  /**
   * Both caps. The hint names the `--full` cap even on a run that is not `--full`.
   * On a `--full` run `maxChars` is never read, so it holds the built-in default.
   */
  limits: CharLimits;
  includeMarkup: boolean;
  /**
   * The command that produced the record, without `--full` and without the cap
   * flags. It carries every flag that changes what the record holds
   * (`--include-markup` for a provider it matters to), so a hint reruns the same
   * thing rather than a neighbour of it.
   */
  rerun: string;
  /**
   * The cap flags this run was given, as text to append to `rerun` (`" --max-chars
   * 500"`, `" --full --full-max-chars 7000"`, or `""`). The `--include-markup`
   * hint appends it so the markup comes back under the cap the reader chose. The
   * `--full` hint does not: that rerun sets its own cap, and `--max-chars` is
   * refused alongside `--full`.
   */
  capFlags: string;
  scope: TruncationScope;
}

// A field is raw markup when its name ends in "html" (page_html, description_html)
// or its value is a whole HTML document. Both signals are deliberately narrow:
// html2text is plain text, and a prose field that mentions `<div>` is content.
// Tags are never regex-stripped out of a field that stays, because ladder-cli
// decodes entities after stripping tags, so a page about HTML reaches us with a
// literal `<div>` in its text (ladder-cli/ladder_cli/rungs/http.py extract_html).
const MARKUP_FIELD_NAME = /html$/i;
const DOCUMENT_START = /^(?:<!doctype\s+html\b|<html[\s>])/i;
// Long enough for `<!doctype html` plus whitespace, short enough that the match never copies a page.
const DOCUMENT_START_WINDOW = 64;

function skipSpace(value: string, from: number): number {
  let index = from;
  while (index < value.length && /\s/.test(value[index])) index += 1;
  return index;
}

/**
 * True when the value opens as an HTML document: a doctype or an `<html>` tag,
 * after any whitespace, comments, and XML prologs a saved page starts with. The
 * prefix is skipped by a scan, not by one regex that repeats a lazy comment
 * match: that form doubles its time with every added comment (3 ms at 18
 * comments, 53 ms at 22), and the linear-time test pins the difference.
 */
function isHtmlDocument(value: string): boolean {
  let index = skipSpace(value, 0);
  while (value.startsWith("<!--", index) || value.startsWith("<?", index)) {
    const comment = value.startsWith("<!--", index);
    const close = value.indexOf(comment ? "-->" : "?>", index + 2);
    if (close < 0) return false;
    index = skipSpace(value, close + (comment ? 3 : 2));
  }
  return DOCUMENT_START.test(value.slice(index, index + DOCUMENT_START_WINDOW));
}

function isMarkupField(key: string, value: unknown): value is string {
  return typeof value === "string" && (MARKUP_FIELD_NAME.test(key) || isHtmlDocument(value));
}

function inScope(scope: TruncationScope, key: string): boolean {
  return scope.kind === "field" ? key === scope.key : !scope.except.has(key);
}

/** The name an upstream or local cut is recorded under: `page_html` becomes `page_htmlTruncatedFrom`. */
function truncationMarker(key: string): string {
  return `${key}TruncatedFrom`;
}

function markerFor(scope: TruncationScope, key: string): string {
  return scope.kind === "field" ? "truncatedFrom" : truncationMarker(key);
}

/**
 * The one place a scraped record becomes output, whichever provider produced
 * it: raw-markup fields are omitted (and named, so nothing vanishes silently),
 * then the character limit is applied to what is left, then the hints are built.
 * Stripping comes first so the limit is spent on content, not on a page's HTML.
 */
export function shapeScrapeRecord(record: AxiOutput, options: ShapeOptions): AxiOutput {
  const limit = limitFor(options.full, options.limits);
  const out: AxiOutput = {};
  const omitted: string[] = [];

  // When every text field the limit applies to is markup, omitting them would turn
  // "this page came back as HTML" into an empty result, so those fields stay (and
  // are cut to the limit). Markup outside that scope stays omitted: nothing
  // would bound it.
  const onlyMarkupToShow = Object.entries(record).every(
    ([key, value]) => typeof value !== "string" || !inScope(options.scope, key) || isMarkupField(key, value),
  );

  for (const [key, value] of Object.entries(record)) {
    const kept = options.includeMarkup || (onlyMarkupToShow && inScope(options.scope, key));
    if (!kept && isMarkupField(key, value)) {
      omitted.push(key);
      continue;
    }
    out[key] = value;
  }
  for (const key of omitted) {
    delete out[truncationMarker(key)];
  }

  const cutTotals: number[] = [];
  for (const [key, value] of Object.entries(out)) {
    if (typeof value !== "string" || !inScope(options.scope, key)) continue;
    const info = truncate(value, limit);
    out[key] = info.text;
    if (!info.truncated) continue;
    cutTotals.push(info.totalChars);
    const marker = markerFor(options.scope, key);
    if (!Object.hasOwn(record, marker)) {
      out[marker] = info.totalChars;
    }
  }

  const hints: string[] = [];
  if (cutTotals.length > 0) {
    const total = cutTotals.length === 1 ? ` (${cutTotals[0]} total)` : "";
    // `--full` only helps when its cap is higher than the one that just cut the
    // content. A run whose own cap already meets or beats it would be told to rerun
    // for the same or fewer characters.
    if (options.full) {
      hints.push(`content is capped at ${limit} characters even with --full`);
    } else if (options.limits.fullMaxChars > limit) {
      hints.push(`Run \`${options.rerun} --full\` to see up to ${options.limits.fullMaxChars} characters${total}`);
    } else {
      hints.push(`content is capped at ${limit} characters${total}`);
    }
  }
  if (omitted.length > 0) {
    out.markupOmitted = omitted;
    hints.push(`Run \`${options.rerun}${options.capFlags} --include-markup\` to keep the omitted markup`);
  }
  if (hints.length > 0) {
    out.help = hints.join(" ");
  }
  return out;
}

interface CharLimitNames {
  flag: string;
  env: string;
  config: string;
}

const MAX_CHARS_NAMES: CharLimitNames = { flag: "--max-chars", env: MAX_CHARS_ENV, config: "maxChars" };
const FULL_MAX_CHARS_NAMES: CharLimitNames = {
  flag: "--full-max-chars",
  env: FULL_MAX_CHARS_ENV,
  config: "fullMaxChars",
};

/**
 * One cap, from one source. Flag and env values arrive as strings and must be
 * all digits; a config value must already be a JSON integer. Either way the
 * error names the setting the bad value came from, so the reader fixes the right
 * place. The only upper bound is the largest integer a number holds exactly.
 */
function validateCharLimit(raw: unknown, source: "flag" | "env" | "config", names: CharLimitNames): number {
  const field = names[source];
  const example = source === "flag" ? `${field} 5000` : source === "env" ? `${field}=5000` : `"${field}": 5000`;
  let value: number;
  if (source === "config") {
    if (typeof raw !== "number" || !Number.isInteger(raw)) {
      throw new SerpAxiError(
        `${field} must be a JSON integer number of characters, got ${describeValue(raw)}`,
        "usage",
        `example: ${example}`,
      );
    }
    value = raw;
  } else {
    if (typeof raw !== "string" || !/^\d+$/.test(raw)) {
      throw new SerpAxiError(
        `${field} must be a whole number of characters, got ${describeValue(raw)}`,
        "usage",
        `example: ${example}`,
      );
    }
    value = Number(raw);
  }
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new SerpAxiError(
      `${field} must be a whole number of characters from 1 to ${Number.MAX_SAFE_INTEGER}, got ${String(raw)}`,
      "usage",
      `example: ${example}`,
    );
  }
  return value;
}

export interface CharLimitSources {
  /** Whether `--full` was given. Decides which of the two flags may appear. */
  full: boolean;
  flagMaxChars?: string;
  flagFullMaxChars?: string;
  envMaxChars?: string;
  envFullMaxChars?: string;
}

/** The caps the flags and env vars set. A cap neither speaks for is left for the config file. */
export interface CharLimitRequest {
  /** Whether `--full` was given, so `maxChars` is not wanted from any source. */
  full: boolean;
  maxChars?: number;
  fullMaxChars?: number;
  /** The cap flags as typed, ready to append to a rerun command. See `ShapeOptions.capFlags`. */
  capFlags: string;
}

/**
 * Flag > env, for each cap on its own, before any config file is opened. Only the
 * source that wins is checked: a bad `SERP_AXI_MAX_CHARS` does not fail a run that
 * passes `--max-chars`.
 *
 * The cap a run uses is always resolved, and so is the `--full` cap on a run that
 * is not `--full`, because its hint names that number. The normal cap is the one
 * thing a `--full` run never reads, so a bad `SERP_AXI_MAX_CHARS` does not fail
 * it: that is what lets the `--full` rerun a hint suggests work after a
 * `--max-chars` flag got past the bad value.
 *
 * Two flags are refused for the run they cannot affect, as `--dataset-id` is
 * without `--provider brightdata`: `--max-chars` with `--full` (the run uses the
 * `--full` cap, so the flag would be dropped), and `--full-max-chars` without
 * `--full` (the run would never use it). The env vars and config keys for the cap
 * a run does not use are not conflicts, so one setting works for both kinds of run.
 */
export function requestCharLimits(sources: CharLimitSources): CharLimitRequest {
  if (sources.full && sources.flagMaxChars !== undefined) {
    throw new SerpAxiError(
      "--max-chars cannot be combined with --full",
      "usage",
      "--full has its own cap: drop --full, or set it with --full-max-chars <n>",
    );
  }
  if (!sources.full && sources.flagFullMaxChars !== undefined) {
    throw new SerpAxiError(
      "--full-max-chars only applies with --full",
      "usage",
      "add --full, or use --max-chars <n> to change the default cap",
    );
  }
  const pick = (flag: string | undefined, env: string | undefined, names: CharLimitNames): number | undefined => {
    if (flag !== undefined) return validateCharLimit(flag, "flag", names);
    if (env !== undefined) return validateCharLimit(env, "env", names);
    return undefined;
  };
  const maxChars = sources.full ? undefined : pick(sources.flagMaxChars, sources.envMaxChars, MAX_CHARS_NAMES);
  const fullMaxChars = pick(sources.flagFullMaxChars, sources.envFullMaxChars, FULL_MAX_CHARS_NAMES);
  // Built after the picks, so a flag value that reaches the rerun text has passed
  // validation and is all digits: nothing in it needs shell quoting.
  let capFlags = "";
  if (sources.full) {
    capFlags = sources.flagFullMaxChars === undefined ? " --full" : ` --full ${FULL_MAX_CHARS_NAMES.flag} ${sources.flagFullMaxChars}`;
  } else if (sources.flagMaxChars !== undefined) {
    capFlags = ` ${MAX_CHARS_NAMES.flag} ${sources.flagMaxChars}`;
  }
  return { full: sources.full, maxChars, fullMaxChars, capFlags };
}

function charLimitFromConfig(raw: unknown, names: CharLimitNames): number | undefined {
  // Null and absent both mean "not set", as they do for the other config keys.
  if (raw === undefined || raw === null) return undefined;
  return validateCharLimit(raw, "config", names);
}

/**
 * Fills each cap the flags and env left open: `maxChars` / `fullMaxChars` in the
 * config, then the built-in default. On a `--full` run `maxChars` is not wanted,
 * so the config key is not read and the default stands in.
 */
export function resolveCharLimits(request: CharLimitRequest, config: StoredConfig): CharLimits {
  const maxChars = request.full
    ? DEFAULT_MAX_CHARS
    : (request.maxChars ?? charLimitFromConfig(config.maxChars, MAX_CHARS_NAMES) ?? DEFAULT_MAX_CHARS);
  return {
    maxChars,
    fullMaxChars:
      request.fullMaxChars ?? charLimitFromConfig(config.fullMaxChars, FULL_MAX_CHARS_NAMES) ?? DEFAULT_FULL_MAX_CHARS,
  };
}

export interface IncludeMarkupSources {
  flag?: boolean;
  env?: string;
  config?: StoredConfig;
}

/** Flag > SERP_AXI_INCLUDE_MARKUP > config `includeMarkup` > off. */
export function resolveIncludeMarkup(sources: IncludeMarkupSources): boolean {
  if (sources.flag === true) return true;

  if (sources.env !== undefined && sources.env !== "") {
    const normalized = sources.env.toLowerCase();
    if (normalized === "1" || normalized === "true") return true;
    if (normalized === "0" || normalized === "false") return false;
    throw new SerpAxiError(
      `${INCLUDE_MARKUP_ENV} must be 1, 0, true, or false, got "${sources.env}"`,
      "usage",
      `example: ${INCLUDE_MARKUP_ENV}=1`,
    );
  }

  // Null and absent both mean "not set", as they do for the ladder's config keys.
  const raw = sources.config?.includeMarkup;
  if (raw === undefined || raw === null) return false;
  if (typeof raw !== "boolean") {
    throw new SerpAxiError(
      `includeMarkup must be a JSON boolean, got ${describeValue(raw)}`,
      "usage",
      'example: "includeMarkup": true',
    );
  }
  return raw;
}
