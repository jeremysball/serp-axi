import { SerpAxiError, boundedDetail } from "./errors.ts";
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

function sourceField(source: string, flagName: string, envName: string, configName: string): string {
  if (source === "flag") return flagName;
  if (source === "env") return envName;
  return configName;
}

function validateEndpoint(raw: unknown, source: string): string {
  const field = sourceField(source, "--searxng-url", "SERP_AXI_SEARXNG_URL", "searxngUrl");
  if (typeof raw !== "string" || raw.length === 0) {
    throw new SerpAxiError(`${field} must be a non-empty URL string, got ${describe(raw)}`, "usage", "example: --searxng-url http://127.0.0.1:8888");
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SerpAxiError(`${field} is not a valid URL: "${raw}"`, "usage", "example: --searxng-url http://127.0.0.1:8888");
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

function describe(value: unknown): string {
  if (Array.isArray(value)) return "an array";
  if (value === null) return "null";
  return `${typeof value} ${JSON.stringify(value)}`;
}

function validateEngines(raw: unknown, source: string): string[] {
  const field = sourceField(source, "--engines", "SERP_AXI_SEARXNG_ENGINES", "searxngEngines");
  let items: string[];
  if (source === "config") {
    if (!Array.isArray(raw)) {
      throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describe(raw)}`, "usage", 'example: "searxngEngines": ["bing", "mojeek"]');
    }
    items = raw.map((entry) => {
      if (typeof entry !== "string") {
        throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describe(raw)}`, "usage", 'example: "searxngEngines": ["bing", "mojeek"]');
      }
      return entry.trim();
    });
  } else {
    if (typeof raw !== "string") {
      throw new SerpAxiError(`${field} must be a comma-separated engine list, got ${describe(raw)}`, "usage", "example: --engines bing,mojeek");
    }
    items = raw.split(",").map((name) => name.trim());
  }
  if (items.length === 0 || items.some((name) => name.length === 0)) {
    throw new SerpAxiError(`${field} must be a JSON array of non-empty engine names, got ${describe(raw)}`, "usage", "example: --engines bing,mojeek");
  }
  return [...new Set(items)];
}

function validateTimeout(raw: unknown, source: string): number {
  const field = sourceField(source, "--search-timeout-ms", "SERP_AXI_SEARCH_TIMEOUT_MS", "searchTimeoutMs");
  let value: number;
  if (source === "config") {
    if (typeof raw !== "number" || !Number.isInteger(raw)) {
      throw new SerpAxiError(`${field} must be a JSON number of milliseconds, got ${describe(raw)}`, "usage", 'example: "searchTimeoutMs": 30000');
    }
    value = raw;
  } else {
    if (typeof raw !== "string" || !/^\d+$/.test(raw)) {
      throw new SerpAxiError(`${field} must be an integer number of milliseconds, got ${describe(raw)}`, "usage", "example: --search-timeout-ms 30000");
    }
    value = Number(raw);
  }
  if (!Number.isFinite(value) || value <= 0 || value > MAX_TIMEOUT_MS) {
    throw new SerpAxiError(`${field} must be between 1 and ${MAX_TIMEOUT_MS} milliseconds, got "${String(raw)}"`, "usage", "example: --search-timeout-ms 30000");
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
  const urlRaw = sources.flagUrl !== undefined ? sources.flagUrl : sources.envUrl !== undefined ? sources.envUrl : sources.config.searxngUrl;
  const url = urlRaw === undefined ? SEARXNG_DEFAULT_URL : validateEndpoint(urlRaw, sources.flagUrl !== undefined ? "flag" : sources.envUrl !== undefined ? "env" : "config");

  const enginesRaw = sources.flagEngines !== undefined ? sources.flagEngines : sources.envEngines !== undefined ? sources.envEngines : sources.config.searxngEngines;
  let engines: string[] | undefined;
  if (enginesRaw !== undefined) {
    engines = validateEngines(enginesRaw, sources.flagEngines !== undefined ? "flag" : sources.envEngines !== undefined ? "env" : "config");
  }

  const timeoutRaw = sources.flagTimeoutMs !== undefined ? sources.flagTimeoutMs : sources.envTimeoutMs !== undefined ? sources.envTimeoutMs : sources.config.searchTimeoutMs;
  const timeoutMs = timeoutRaw === undefined ? SEARXNG_DEFAULT_TIMEOUT_MS : validateTimeout(timeoutRaw, sources.flagTimeoutMs !== undefined ? "flag" : sources.envTimeoutMs !== undefined ? "env" : "config");

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
    text = await response.text();
  } catch (cause) {
    const err = cause as Error;
    if (err.name === "TimeoutError" || err.name === "AbortError") {
      throw new SerpAxiError(`SearXNG request timed out after ${options.timeoutMs} ms`, "runtime", "raise --search-timeout-ms, or retry");
    }
    throw new SerpAxiError(`network error reading SearXNG response: ${boundedDetail(err.message)}`, "runtime", "the server interrupted the transfer; retry");
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
