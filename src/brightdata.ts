import { SerpAxiError } from "./errors.ts";
import type { OrganicResult, SearchParams, SearchResponse } from "./serper.ts";

export const BRIGHT_DATA_DEFAULT_ZONE = "serp_api1";
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
