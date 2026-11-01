import { SerpAxiError, describeValue } from "./errors.ts";
import { truncate, type AxiOutput } from "./output.ts";
import type { StoredConfig } from "./config.ts";

export const DEFAULT_LIMIT = 1200;
export const FULL_LIMIT = 50000;
export const INCLUDE_MARKUP_ENV = "SERP_AXI_INCLUDE_MARKUP";

/** The character limit for one run. Every cut a scrape makes, locally or upstream, takes it from here. */
export function limitFor(full: boolean): number {
  return full ? FULL_LIMIT : DEFAULT_LIMIT;
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
  full: boolean;
  includeMarkup: boolean;
  /**
   * The command that produced the record, without `--full`. It carries every flag
   * that changes what the record holds (`--include-markup` for a provider it
   * matters to), so a hint reruns the same thing rather than a neighbour of it.
   */
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
  const limit = limitFor(options.full);
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
    hints.push(
      options.full
        ? `content is capped at ${FULL_LIMIT} characters even with --full`
        : `Run \`${options.rerun} --full\` to see up to ${FULL_LIMIT} characters${total}`,
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
