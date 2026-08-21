import { SerpAxiError } from "./errors.ts";
import type { OrganicResult, SearchParams, SearchResponse } from "./serper.ts";

export const BRIGHT_DATA_DEFAULT_ZONE = "serp_api1";
export const BRIGHT_DATA_DEFAULT_DATASET_ID = "gd_m6gjtfmeh43we6cqc";
const REQUEST_URL = "https://api.brightdata.com/request";

interface BrightDataEnvelope {
  status_code: number;
  body: string;
}

interface BrightDataOrganicResult {
  link: string;
  title: string;
  description?: string;
  rank: number;
}

interface BrightDataParsedBody {
  organic?: BrightDataOrganicResult[];
}

export type BrightDataRecord = Record<string, unknown>;

function isBrightDataRecord(value: unknown): value is BrightDataRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const MAX_ERROR_DETAIL = 200;

function boundedDetail(message: string): string {
  return message.length > MAX_ERROR_DETAIL ? `${message.slice(0, MAX_ERROR_DETAIL)}...` : message;
}

function buildGoogleSearchUrl(params: SearchParams): string {
  const url = new URL("https://www.google.com/search");
  url.searchParams.set("q", params.q);
  url.searchParams.set("gl", params.gl);
  url.searchParams.set("hl", params.hl);
  url.searchParams.set("num", String(params.num));
  return url.toString();
}

function toOrganicResults(results: BrightDataOrganicResult[]): OrganicResult[] {
  return results.map((r) => ({
    position: r.rank,
    title: r.title,
    link: r.link,
    snippet: r.description ?? "",
  }));
}

export async function searchBrightData(
  apiKey: string,
  params: SearchParams,
  fetchImpl: typeof fetch = fetch,
  zone: string = BRIGHT_DATA_DEFAULT_ZONE,
): Promise<SearchResponse> {
  let response: Response;
  try {
    response = await fetchImpl(REQUEST_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        zone,
        url: buildGoogleSearchUrl(params),
        format: "json",
        data_format: "parsed",
      }),
    });
  } catch (cause) {
    throw new SerpAxiError(
      `network error calling Bright Data: ${boundedDetail((cause as Error).message)}`,
      "runtime",
      "check network connectivity and retry",
    );
  }

  if (!response.ok) {
    // Bright Data's own auth/validation errors are plain text, not JSON
    // (verified live: 401 "Invalid token", 400 'zone "..." not found').
    const text = boundedDetail(await response.text().catch(() => ""));
    if (response.status === 401) {
      throw new SerpAxiError(
        "Bright Data rejected the API key (401)",
        "runtime",
        "check that BRIGHTDATA_API_KEY is set to a valid key",
      );
    }
    if (response.status === 429) {
      throw new SerpAxiError("Bright Data rate-limited this request (429)", "runtime", "wait and retry later");
    }
    if (response.status === 404) {
      throw new SerpAxiError(
        "Bright Data could not find the requested zone or endpoint (404)",
        "runtime",
        "check that BRIGHTDATA_ZONE (or --zone) names an existing zone",
      );
    }
    if (response.status === 400) {
      throw new SerpAxiError(
        `Bright Data rejected the request as invalid (400): ${text || "no details"}`,
        "runtime",
        "check that BRIGHTDATA_ZONE (or --zone) names an existing zone",
      );
    }
    if (response.status >= 500) {
      throw new SerpAxiError(`Bright Data had an upstream failure (${response.status})`, "runtime", "retry later");
    }
    throw new SerpAxiError(
      `Bright Data returned an unexpected status ${response.status}: ${text || "no details"}`,
      "runtime",
      "this is not a status serp-axi maps explicitly; report it if it persists",
    );
  }

  let envelope: BrightDataEnvelope;
  try {
    envelope = (await response.json()) as BrightDataEnvelope;
  } catch {
    throw new SerpAxiError(
      "Bright Data returned a non-JSON response (200)",
      "runtime",
      "this may be a transient upstream issue; retry",
    );
  }

  if (envelope.status_code === 429) {
    throw new SerpAxiError(
      "Google (via Bright Data) rate-limited this request (429)",
      "runtime",
      "wait and retry later",
    );
  }
  if (envelope.status_code >= 500) {
    throw new SerpAxiError(
      `Google (via Bright Data) had an upstream failure (${envelope.status_code})`,
      "runtime",
      "retry later",
    );
  }
  if (envelope.status_code !== 200) {
    throw new SerpAxiError(
      `Google (via Bright Data) returned an unexpected status ${envelope.status_code}`,
      "runtime",
      "this may be a transient block; retry, or check the query for anything that looks automated",
    );
  }

  let parsedBody: BrightDataParsedBody;
  try {
    parsedBody = JSON.parse(envelope.body) as BrightDataParsedBody;
  } catch {
    throw new SerpAxiError(
      "Bright Data's parsed body was not valid JSON",
      "runtime",
      "this may be a transient upstream issue; retry",
    );
  }

  return { organic: toOrganicResults(parsedBody.organic ?? []) };
}

function parseBrightDataErrorDetail(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as { message?: unknown };
    if (typeof parsed.message === "string") return parsed.message;
  } catch {
    // Bright Data commonly returns plain-text errors.
  }
  return raw;
}

/** Scrape one or more public URLs through Bright Data's synchronous dataset API. */
export async function scrapeBrightData(
  apiKey: string,
  datasetId: string,
  urls: string[],
  characterLimit: number,
  fetchImpl: typeof fetch = fetch,
): Promise<BrightDataRecord[]> {
  const endpoint =
    `https://api.brightdata.com/datasets/v3/scrape?dataset_id=${encodeURIComponent(datasetId)}` +
    "&notify=false&include_errors=true";

  let response: Response;
  try {
    response = await fetchImpl(endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        input: urls.map((url) => ({ url })),
        limit_per_input: characterLimit,
      }),
    });
  } catch (cause) {
    throw new SerpAxiError(
      `network error calling Bright Data: ${boundedDetail((cause as Error).message)}`,
      "runtime",
      "check network connectivity and retry",
    );
  }

  if (!response.ok) {
    const rawDetail = await response.text().catch(() => "");
    const detail = boundedDetail(parseBrightDataErrorDetail(rawDetail));
    if (response.status === 401 || response.status === 403) {
      throw new SerpAxiError(
        `Bright Data rejected the API key (${response.status})${detail ? `: ${detail}` : ""}`,
        "runtime",
        "check that BRIGHTDATA_API_KEY is set to a valid key",
      );
    }
    if (response.status === 429) {
      throw new SerpAxiError("Bright Data rate-limited this request (429)", "runtime", "wait and retry later");
    }
    if (response.status === 404) {
      throw new SerpAxiError(
        `Bright Data could not find dataset "${datasetId}" (404)`,
        "runtime",
        "verify --dataset-id / BRIGHTDATA_DATASET_ID is correct",
      );
    }
    if (response.status >= 500) {
      throw new SerpAxiError(`Bright Data had an upstream failure (${response.status})`, "runtime", "retry later");
    }
    throw new SerpAxiError(
      `Bright Data returned an unexpected status ${response.status}: ${detail || "no details"}`,
      "runtime",
      "this is not a status serp-axi maps explicitly; report it if it persists",
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new SerpAxiError(
      "Bright Data returned a non-JSON response (200)",
      "runtime",
      "this may be a transient upstream issue; retry",
    );
  }

  if (!Array.isArray(body)) {
    throw new SerpAxiError(
      "Bright Data returned an unexpected response shape (expected an array of records)",
      "runtime",
      "this may indicate an upstream API change; report it if it persists",
    );
  }
  if (!body.every(isBrightDataRecord)) {
    throw new SerpAxiError(
      "Bright Data returned an invalid record shape (expected objects)",
      "runtime",
      "this may indicate an upstream API change; report it if it persists",
    );
  }
  return body;
}
