import { BodyReadError, DEFAULT_MAX_RESPONSE_BYTES, readBodyText } from "./body.ts";
import { SerpAxiError, boundedDetail, describeValue } from "./errors.ts";
import {
  parseIntegerSetting,
  pickOption,
  settingExamples,
  type IntegerSettingShape,
  type OptionSource,
  type SettingNames,
} from "./option-sources.ts";
import type { OrganicResult, SearchParams } from "./serper.ts";

export const SEARXNG_DEFAULT_URL = "http://127.0.0.1:8888";
export const SEARXNG_DEFAULT_TIMEOUT_MS = 30_000;

export interface SearxngOptions {
  url: string;
  engines?: string[];
  timeoutMs: number;
}

export type SearxngStatus = "ok" | "partial" | "blocked" | "unavailable";

export interface EngineStatus {
  name: string;
  status: "ok" | "blocked" | "error";
  resultCount: number;
  reason?: string;
}

const BLOCKED_REASON = /captcha|blocked|access denied|forbidden|403|429|rate limit|too many requests|suspended/i;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const MAX_TIMEOUT_MS = 2_147_483_647;

const URL_NAMES: SettingNames = { flag: "--searxng-url", env: "SERP_AXI_SEARXNG_URL", config: "searxngUrl" };
const URL_EXAMPLES = settingExamples(URL_NAMES, SEARXNG_DEFAULT_URL, `"${SEARXNG_DEFAULT_URL}"`);
const ENGINES_NAMES: SettingNames = { flag: "--engines", env: "SERP_AXI_SEARXNG_ENGINES", config: "searxngEngines" };
const ENGINES_EXAMPLES = settingExamples(ENGINES_NAMES, "bing,mojeek", '["bing", "mojeek"]');
const TIMEOUT_NAMES: SettingNames = { flag: "--search-timeout-ms", env: "SERP_AXI_SEARCH_TIMEOUT_MS", config: "searchTimeoutMs" };
const TIMEOUT_SHAPE: IntegerSettingShape = {
  names: TIMEOUT_NAMES,
  examples: settingExamples(TIMEOUT_NAMES, "30000"),
  textShape: "an integer number of milliseconds",
  configShape: "a JSON number of milliseconds",
};

function validateEndpoint(raw: unknown, source: OptionSource): string {
  const field = URL_NAMES[source];
  if (typeof raw !== "string" || raw.length === 0) {
    throw new SerpAxiError(`${field} must be a non-empty URL string, got ${describeValue(raw)}`, "usage", `example: ${URL_EXAMPLES[source]}`);
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SerpAxiError(`${field} is not a valid URL: "${raw}"`, "usage", `example: ${URL_EXAMPLES[source]}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SerpAxiError(`${field} must use http or https, got "${url.protocol}"`, "usage", "example: http://127.0.0.1:8888");
  }
  if (url.username !== "" || url.password !== "") {
    throw new SerpAxiError(`${field} must not contain credentials`, "usage", "pass the endpoint directly, without user:password@");
  }
  if (url.search !== "" || url.hash !== "") {
    throw new SerpAxiError(`${field} must not contain a query or fragment`, "usage", "example: http://127.0.0.1:8888");
  }
  return url.toString();
}

function validateEngines(raw: unknown, source: OptionSource): string[] {
  const field = ENGINES_NAMES[source];
  let items: string[];
  if (source === "config") {
    if (!Array.isArray(raw)) {
      throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describeValue(raw)}`, "usage", `example: ${ENGINES_EXAMPLES[source]}`);
    }
    items = raw.map((entry) => {
      if (typeof entry !== "string") {
        throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describeValue(raw)}`, "usage", `example: ${ENGINES_EXAMPLES[source]}`);
      }
      return entry.trim();
    });
  } else {
    if (typeof raw !== "string") {
      throw new SerpAxiError(`${field} must be a comma-separated engine list, got ${describeValue(raw)}`, "usage", `example: ${ENGINES_EXAMPLES[source]}`);
    }
    items = raw.split(",").map((name) => name.trim());
  }
  if (items.length === 0 || items.some((name) => name.length === 0)) {
    if (source === "config") {
      throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describeValue(raw)}`, "usage", `example: ${ENGINES_EXAMPLES[source]}`);
    }
    throw new SerpAxiError(`${field} must be a comma-separated list of non-empty engine names, got ${describeValue(raw)}`, "usage", `example: ${ENGINES_EXAMPLES[source]}`);
  }
  return [...new Set(items)];
}

function validateTimeout(raw: unknown, source: OptionSource): number {
  const value = parseIntegerSetting(raw, source, TIMEOUT_SHAPE);
  if (!Number.isFinite(value) || value <= 0 || value > MAX_TIMEOUT_MS) {
    throw new SerpAxiError(
      `${TIMEOUT_NAMES[source]} must be between 1 and ${MAX_TIMEOUT_MS} milliseconds, got "${String(raw)}"`,
      "usage",
      `example: ${TIMEOUT_SHAPE.examples[source]}`,
    );
  }
  return value;
}

export interface SearxngOptionSources {
  flagUrl?: string;
  flagEngines?: string;
  flagTimeoutMs?: string;
  envUrl?: string;
  envEngines?: string;
  envTimeoutMs?: string;
  config: { searxngUrl?: unknown; searxngEngines?: unknown; searchTimeoutMs?: unknown };
}

export function resolveSearxngOptions(sources: SearxngOptionSources): SearxngOptions {
  const urlPick = pickOption<unknown>(sources.flagUrl, sources.envUrl, sources.config.searxngUrl);
  const url = urlPick === undefined ? SEARXNG_DEFAULT_URL : validateEndpoint(urlPick.value, urlPick.source);

  const enginesPick = pickOption<unknown>(sources.flagEngines, sources.envEngines, sources.config.searxngEngines);
  const engines = enginesPick === undefined ? undefined : validateEngines(enginesPick.value, enginesPick.source);

  const timeoutPick = pickOption<unknown>(sources.flagTimeoutMs, sources.envTimeoutMs, sources.config.searchTimeoutMs);
  const timeoutMs = timeoutPick === undefined ? SEARXNG_DEFAULT_TIMEOUT_MS : validateTimeout(timeoutPick.value, timeoutPick.source);

  return { url, engines, timeoutMs };
}

interface RawSearchResult {
  url: string;
  title: string;
  content: string;
  engines: string[];
}

function validateUpstreamRow(value: unknown, index: number): RawSearchResult {
  if (!isPlainObject(value)) {
    throw new SerpAxiError(`SearXNG result ${index} is not an object`, "runtime", "this may be an upstream API change; report it if it persists");
  }
  const { url, title, content, engines, engine } = value as Record<string, unknown>;
  if (typeof url !== "string" || typeof title !== "string") {
    throw new SerpAxiError(`SearXNG result ${index} is missing a string url or title`, "runtime", "this may be an upstream API change; report it if it persists");
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new SerpAxiError(`SearXNG result ${index} has an invalid url`, "runtime", "this may be an upstream API change");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new SerpAxiError(`SearXNG result ${index} has a non-http(s) url`, "runtime", "this may be an upstream API change");
  }
  if (content !== undefined && typeof content !== "string") {
    throw new SerpAxiError(`SearXNG result ${index} has a non-string content`, "runtime", "this may be an upstream API change");
  }
  let rowEngines: string[] = [];
  if (engines !== undefined) {
    if (!Array.isArray(engines) || engines.some((e) => typeof e !== "string")) {
      throw new SerpAxiError(`SearXNG result ${index} has an invalid engines array`, "runtime", "this may be an upstream API change");
    }
    rowEngines = (engines as string[]).map((name) => name.trim());
    if (rowEngines.length === 0 || rowEngines.some((name) => name.length === 0)) {
      throw new SerpAxiError(`SearXNG result ${index} has an empty engine name`, "runtime", "this may be an upstream API change");
    }
  } else if (engine !== undefined) {
    if (typeof engine !== "string" || engine.trim().length === 0) {
      throw new SerpAxiError(`SearXNG result ${index} has an invalid engine`, "runtime", "this may be an upstream API change");
    }
    rowEngines = [engine.trim()];
  }
  return { url, title, content: content ?? "", engines: [...new Set(rowEngines)] };
}

function validateUpstreamBody(body: unknown): { results: RawSearchResult[]; unresponsiveEngines: Array<{ name: string; reason: string }> } {
  if (!isPlainObject(body) || !Array.isArray(body.results)) {
    throw new SerpAxiError("SearXNG returned a malformed response (missing results array)", "runtime", "this may be an upstream API change; report it if it persists");
  }
  const results = body.results.map((row, i) => validateUpstreamRow(row, i));
  const unresponsive: Array<{ name: string; reason: string }> = [];
  if (body.unresponsive_engines !== undefined) {
    if (!Array.isArray(body.unresponsive_engines)) {
      throw new SerpAxiError("SearXNG returned a malformed response (bad unresponsive_engines)", "runtime", "this may be an upstream API change");
    }
    for (const pair of body.unresponsive_engines) {
      if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string" || typeof pair[1] !== "string") {
        throw new SerpAxiError("SearXNG returned a malformed response (bad unresponsive_engines entry)", "runtime", "this may be an upstream API change");
      }
      if (pair[0].trim().length === 0 || pair[1].trim().length === 0) {
        throw new SerpAxiError("SearXNG returned a malformed response (empty unresponsive_engines name or reason)", "runtime", "this may be an upstream API change");
      }
      unresponsive.push({ name: pair[0].trim(), reason: pair[1] });
    }
  }
  return { results, unresponsiveEngines: unresponsive };
}

function normalizeUrl(raw: string): string {
  const url = new URL(raw);
  url.hash = "";
  return url.toString();
}

function dedupeRows(rows: RawSearchResult[]): Array<{ url: string; title: string; content: string; engines: string[] }> {
  const byUrl = new Map<string, { url: string; title: string; content: string; engines: string[] }>();
  for (const row of rows) {
    const key = normalizeUrl(row.url);
    const existing = byUrl.get(key);
    if (existing === undefined) {
      byUrl.set(key, { url: key, title: row.title, content: row.content, engines: [...new Set(row.engines)] });
    } else {
      const seen = new Set(existing.engines);
      for (const engine of row.engines) {
        if (!seen.has(engine)) {
          existing.engines.push(engine);
          seen.add(engine);
        }
      }
    }
  }
  return [...byUrl.values()];
}

function classify(reason: string): "blocked" | "error" {
  return BLOCKED_REASON.test(reason) ? "blocked" : "error";
}

export function buildEngineStatuses(
  rows: Array<{ engines: string[] }>,
  unresponsive: Array<{ name: string; reason: string }>,
  requested: string[] | undefined,
): EngineStatus[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    for (const engine of row.engines) {
      counts.set(engine, (counts.get(engine) ?? 0) + 1);
    }
  }
  const failures = new Map<string, { status: "blocked" | "error"; reason: string }>();
  for (const failure of unresponsive) {
    failures.set(failure.name, { status: classify(failure.reason), reason: failure.reason });
  }
  const names: string[] = [];
  const seen = new Set<string>();
  const push = (name: string) => {
    if (!seen.has(name)) {
      seen.add(name);
      names.push(name);
    }
  };
  for (const row of rows) for (const e of row.engines) push(e);
  for (const name of failures.keys()) push(name);
  for (const name of requested ?? []) push(name);
  return names.map((name) => {
    const failure = failures.get(name);
    if (failure !== undefined) {
      return { name, status: failure.status, resultCount: counts.get(name) ?? 0, reason: boundedDetail(failure.reason) };
    }
    return { name, status: "ok", resultCount: counts.get(name) ?? 0 };
  });
}

export function deriveStatus(
  rowCount: number,
  failures: Array<{ status: "blocked" | "error" }>,
): SearxngStatus {
  if (rowCount > 0 && failures.length > 0) return "partial";
  if (rowCount > 0) return "ok";
  if (failures.some((f) => f.status === "blocked")) return "blocked";
  if (failures.length > 0) return "unavailable";
  return "ok";
}

export type SearxngOutcome =
  | { status: "ok" | "partial"; organic: OrganicResult[]; engines: EngineStatus[] }
  | { status: "blocked" | "unavailable"; organic: []; engines: EngineStatus[] };

export interface SearxngSearchResponse {
  provider: "searxng";
  status: "ok" | "partial";
  organic: OrganicResult[];
  engines: EngineStatus[];
}

export function normalizeSearxngBody(body: unknown, num: number, requested: string[] | undefined): SearxngOutcome {
  const { results, unresponsiveEngines } = validateUpstreamBody(body);
  const deduped = dedupeRows(results);
  const failures = unresponsiveEngines.map((f) => ({ ...f, status: classify(f.reason) }));
  const status = deriveStatus(deduped.length, failures);
  const engines = buildEngineStatuses(deduped, unresponsiveEngines, requested);
  if (status === "blocked" || status === "unavailable") {
    return { status, organic: [], engines };
  }
  const capped = deduped.slice(0, num).map((row, index) => ({
    position: index + 1,
    title: row.title,
    link: row.url,
    snippet: row.content,
    engines: row.engines,
  }));
  return { status, organic: capped, engines };
}

function searchUrl(endpoint: string, params: SearchParams, engines: string[] | undefined, language: string): string {
  const base = endpoint.endsWith("/") ? endpoint : `${endpoint}/`;
  const url = new URL(`${base}search`);
  url.searchParams.set("q", params.q);
  url.searchParams.set("format", "json");
  url.searchParams.set("language", language);
  if (engines !== undefined) url.searchParams.set("engines", engines.join(","));
  return url.toString();
}

function blockedDetails(engines: EngineStatus[]): Record<string, unknown> {
  return { provider: "searxng", status: "blocked", count: 0, engines };
}

export async function searchSearxng(
  options: SearxngOptions,
  params: SearchParams,
  fetchImpl: typeof fetch = fetch,
  maxResponseBytes: number = DEFAULT_MAX_RESPONSE_BYTES,
): Promise<SearxngSearchResponse> {
  const language = `${params.hl}-${params.gl.toUpperCase()}`;
  const url = searchUrl(options.url, params, options.engines, language);

  let response: Response;
  try {
    response = await fetchImpl(url, { signal: AbortSignal.timeout(options.timeoutMs) });
  } catch (cause) {
    const err = cause as Error;
    if (err.name === "TimeoutError" || err.name === "AbortError") {
      throw new SerpAxiError(`SearXNG request timed out after ${options.timeoutMs} ms`, "runtime", "raise --search-timeout-ms, or retry");
    }
    throw new SerpAxiError(`network error calling SearXNG: ${boundedDetail(err.message)}`, "runtime", "check that the SearXNG endpoint is reachable (default http://127.0.0.1:8888)");
  }

  if (response.status === 403 || response.status === 429) {
    throw new SerpAxiError(
      `SearXNG blocked this request (${response.status})`,
      "runtime",
      "retry later, use fewer engines, or configure a different SearXNG instance",
      blockedDetails([]),
    );
  }
  if (response.status === 401) {
    throw new SerpAxiError("SearXNG rejected the request (401)", "runtime", "check the SearXNG endpoint configuration");
  }
  if (response.status >= 500) {
    throw new SerpAxiError(`SearXNG had an upstream failure (${response.status})`, "runtime", "retry later");
  }
  if (!response.ok) {
    throw new SerpAxiError(`SearXNG returned an unexpected status ${response.status}`, "runtime", "report it if it persists");
  }

  const contentType = response.headers.get("content-type") ?? "";
  let text: string;
  try {
    text = await readBodyText(response, { maxBytes: maxResponseBytes, source: "SearXNG" });
  } catch (cause) {
    // The cap error and a dropped transfer already say what happened. Only a
    // timeout is reworded, because only this call knows the budget it ran on.
    if (cause instanceof BodyReadError && cause.timedOut) {
      throw new SerpAxiError(`SearXNG request timed out after ${options.timeoutMs} ms`, "runtime", "raise --search-timeout-ms, or retry");
    }
    throw cause;
  }
  if (contentType.includes("text/html") || text.trimStart().startsWith("<")) {
    throw new SerpAxiError("SearXNG returned an HTML page instead of JSON (possible challenge or login page)", "runtime", "check the endpoint configuration; a formatting/challenge gate may be in front of it");
  }

  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    throw new SerpAxiError("SearXNG returned a non-JSON response (200)", "runtime", "this may be a transient upstream issue; retry");
  }

  const outcome = normalizeSearxngBody(body, params.num, options.engines);

  if (outcome.status === "blocked") {
    const count = outcome.engines.filter((e) => e.status === "blocked").length;
    throw new SerpAxiError(
      `SearXNG returned no results, and ${count} engine${count === 1 ? "" : "s"} failed (blocked). Results may be incomplete.`,
      "runtime",
      "retry later, use fewer engines, or point --searxng-url at a different instance",
      { provider: "searxng", status: "blocked", count: 0, engines: outcome.engines },
    );
  }
  if (outcome.status === "unavailable") {
    const count = outcome.engines.filter((e) => e.status === "error").length;
    throw new SerpAxiError(
      `SearXNG returned no results, and ${count} engine${count === 1 ? "" : "s"} failed. Results may be incomplete.`,
      "runtime",
      "check that the SearXNG server is running and its engines are configured",
      { provider: "searxng", status: "unavailable", count: 0, engines: outcome.engines },
    );
  }

  return { provider: "searxng", status: outcome.status, organic: outcome.organic, engines: outcome.engines };
}
