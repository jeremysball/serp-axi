import { SerpAxiError } from "./errors.ts";

export interface SearchParams {
  q: string;
  gl: string;
  hl: string;
  num: number;
}

export interface OrganicResult {
  position: number;
  title: string;
  link: string;
  snippet: string;
  date?: string;
  sitelinks?: unknown;
}

export interface SearchResponse {
  organic: OrganicResult[];
}

export interface ScrapeResponse {
  text: string;
  metadata: { title?: string; [key: string]: unknown };
}

interface SerperErrorBody {
  message?: string;
  statusCode?: number;
}

const MAX_ERROR_DETAIL = 200;

function boundedDetail(message: string): string {
  return message.length > MAX_ERROR_DETAIL ? `${message.slice(0, MAX_ERROR_DETAIL)}...` : message;
}

async function serperRequest(url: string, apiKey: string, body: unknown, fetchImpl: typeof fetch): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: {
        "X-API-KEY": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new SerpAxiError(
      `network error calling Serper: ${boundedDetail((cause as Error).message)}`,
      "runtime",
      "check network connectivity and retry",
    );
  }

  if (response.ok) {
    try {
      return await response.json();
    } catch {
      throw new SerpAxiError(
        `Serper returned a non-JSON response (${response.status})`,
        "runtime",
        "this may be a transient upstream issue; retry",
      );
    }
  }

  let parsed: SerperErrorBody = {};
  try {
    parsed = (await response.json()) as SerperErrorBody;
  } catch {
    // body wasn't JSON; fall through with an empty parsed body
  }

  if (response.status === 403) {
    throw new SerpAxiError(
      "Serper rejected the API key (403)",
      "runtime",
      "check that SERPER_API_KEY is set to a valid key",
    );
  }
  if (response.status === 429) {
    throw new SerpAxiError("Serper rate-limited this request (429)", "runtime", "wait and retry later");
  }
  if (response.status === 404) {
    throw new SerpAxiError(
      "Serper could not find the requested page (404)",
      "runtime",
      "verify the URL is correct and reachable",
    );
  }
  if (response.status >= 500) {
    throw new SerpAxiError(`Serper had an upstream failure (${response.status})`, "runtime", "retry later");
  }

  throw new SerpAxiError(
    `Serper returned an unexpected status ${response.status}: ${parsed.message ?? "no details"}`,
    "runtime",
    "this is not a status serp-axi maps explicitly; report it if it persists",
  );
}

export async function searchSerper(
  apiKey: string,
  params: SearchParams,
  fetchImpl: typeof fetch = fetch,
): Promise<SearchResponse> {
  const body = await serperRequest(
    "https://google.serper.dev/search",
    apiKey,
    { q: params.q, gl: params.gl, hl: params.hl, num: params.num },
    fetchImpl,
  );
  return body as SearchResponse;
}

export async function scrapeSerper(
  apiKey: string,
  url: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ScrapeResponse> {
  const body = await serperRequest("https://scrape.serper.dev", apiKey, { url }, fetchImpl);
  return body as ScrapeResponse;
}
