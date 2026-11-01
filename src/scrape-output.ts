import { SerpAxiError } from "./errors.ts";
import { truncate, type AxiOutput } from "./output.ts";
import type { StoredConfig } from "./config.ts";

export const DEFAULT_LIMIT = 1200;
export const FULL_LIMIT = 50000;
export const INCLUDE_MARKUP_ENV = "SERP_AXI_INCLUDE_MARKUP";

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
  full: boolean;
  includeMarkup: boolean;
  /** The command that produced the record, without `--full` or `--include-markup`. */
  rerun: string;
  scope: TruncationScope;
}

// A field is raw markup when its name ends in "html" (page_html, description_html)
// or its value is a whole HTML document. Both signals are deliberately narrow:
// html2text is plain text, and a prose field that mentions `<div>` is content.
// Tags are never regex-stripped out of a field that stays, because ladder-cli
// decodes entities after stripping tags, so a page about HTML reaches us with a
// literal `<div>` in its text (ladder-cli/ladder_cli/rungs/http.py extract_html).
const MARKUP_FIELD_NAME = /html$/i;
const HTML_DOCUMENT = /^\s*(?:<!doctype\s+html\b|<html[\s>])/i;

function isMarkupField(key: string, value: unknown): boolean {
  return typeof value === "string" && (MARKUP_FIELD_NAME.test(key) || HTML_DOCUMENT.test(value));
}

function inScope(scope: TruncationScope, key: string): boolean {
  return scope.kind === "field" ? key === scope.key : !scope.except.has(key);
}

function markerFor(scope: TruncationScope, key: string): string {
  return scope.kind === "field" ? "truncatedFrom" : `${key}TruncatedFrom`;
}

/**
 * The one place a scraped record becomes output, whichever provider produced
 * it: raw-markup fields are omitted (and named, so nothing vanishes silently),
 * then the character limit is applied to what is left, then the hints are built.
 * Stripping comes first so the limit is spent on content, not on a page's HTML.
 */
export function shapeScrapeRecord(record: AxiOutput, options: ShapeOptions): AxiOutput {
  const limit = options.full ? FULL_LIMIT : DEFAULT_LIMIT;
  const out: AxiOutput = {};
  const omitted: string[] = [];

  // A provider with one declared content field has nothing else to show: omitting
  // it would turn "this page came back as HTML" into an empty result.
  const payload = options.scope.kind === "field" ? options.scope.key : undefined;

  for (const [key, value] of Object.entries(record)) {
    if (!options.includeMarkup && key !== payload && isMarkupField(key, value)) {
      omitted.push(key);
      continue;
    }
    out[key] = value;
  }
  for (const key of omitted) {
    delete out[`${key}TruncatedFrom`];
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
    const rerun = `${options.rerun}${options.includeMarkup ? " --include-markup" : ""} --full`;
    const total = cutTotals.length === 1 ? ` (${cutTotals[0]} total)` : "";
    hints.push(
      options.full
        ? `content is capped at ${FULL_LIMIT} characters even with --full`
        : `Run \`${rerun}\` to see up to ${FULL_LIMIT} characters${total}`,
    );
  }
  if (omitted.length > 0) {
    out.markupOmitted = omitted;
    hints.push(`Run \`${options.rerun} --include-markup\` to keep the omitted markup`);
  }
  if (hints.length > 0) {
    out.help = hints.join(" ");
  }
  return out;
}

export interface IncludeMarkupSources {
  flag?: boolean;
  env?: string;
  config?: StoredConfig;
}

function describe(value: unknown): string {
  return `${typeof value} ${JSON.stringify(value)}`;
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

  const raw = sources.config?.includeMarkup;
  if (raw === undefined) return false;
  if (typeof raw !== "boolean") {
    throw new SerpAxiError(
      `includeMarkup must be a JSON boolean, got ${describe(raw)}`,
      "usage",
      'example: "includeMarkup": true',
    );
  }
  return raw;
}
