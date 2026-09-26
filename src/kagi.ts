import { SerpAxiError } from "./errors.ts";
import type { OrganicResult, SearchParams, SearchResponse } from "./serper.ts";

// Kagi's default /search endpoint streams results to the browser over SSE, so
// its static HTML carries no organic results at all. /html/search is the
// non-JavaScript endpoint and renders the full SERP server-side.
const SEARCH_URL = "https://kagi.com/html/search";

const MAX_ERROR_DETAIL = 200;

function boundedDetail(message: string): string {
  return message.length > MAX_ERROR_DETAIL ? `${message.slice(0, MAX_ERROR_DETAIL)}...` : message;
}

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  "#39": "'",
  "#x27": "'",
};

function decodeEntities(text: string): string {
  return text.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, name: string) => {
    const known = ENTITIES[name.toLowerCase()];
    if (known !== undefined) return known;
    if (name.startsWith("#x") || name.startsWith("#X")) {
      const code = Number.parseInt(name.slice(2), 16);
      return Number.isNaN(code) ? match : String.fromCodePoint(code);
    }
    if (name.startsWith("#")) {
      const code = Number.parseInt(name.slice(1), 10);
      return Number.isNaN(code) ? match : String.fromCodePoint(code);
    }
    return match;
  });
}

// Kagi renders a "Summarize" action inside the description itself. It is a UI
// control, not part of the result text, so drop the whole anchor rather than
// letting its label survive tag-stripping and land at the end of the snippet.
const SUMMARIZE_LINK = /<a\b[^>]*class="[^"]*\bsummarize-link\b[^"]*"[^>]*>[\s\S]*?<\/a>/g;

function toText(html: string): string {
  const withoutControls = html.replace(SUMMARIZE_LINK, "");
  return decodeEntities(withoutControls.replace(/<[^>]*>/g, "")).replace(/\s+/g, " ").trim();
}

/**
 * Pull out the contents of the first div whose class list contains `__sri-desc`,
 * counting nested `<div>`s so a snippet containing markup isn't truncated at the
 * first `</div>`. The class is matched as a token, not a prefix: Kagi writes it
 * as `class="_0_DESC __sri-desc"`, with `__sri-desc` in second position.
 */
function extractDescription(block: string): string | null {
  const open = /<div class="[^"]*\b__sri-desc\b[^"]*"[^>]*>/.exec(block);
  if (open === null) return null;

  let index = open.index + open[0].length;
  const start = index;
  let depth = 1;
  const tag = /<(\/?)div\b[^>]*>/g;
  tag.lastIndex = index;

  for (let match = tag.exec(block); match !== null; match = tag.exec(block)) {
    depth += match[1] === "/" ? -1 : 1;
    if (depth === 0) return block.slice(start, match.index);
    index = tag.lastIndex;
  }

  // Unbalanced markup: take what's there rather than dropping the snippet.
  return block.slice(start, index);
}

/**
 * Each organic result is a `_0_SRI` block. The title and link live on the
 * anchor's `title`/`href` attributes, and the snippet in a `__sri-desc` div.
 * Some blocks (Kagi's own widgets, and results it renders without a summary)
 * carry no description; those get an empty snippet rather than being dropped,
 * matching how the other providers treat a missing description.
 */
export function parseKagiHtml(html: string): OrganicResult[] {
  const results: OrganicResult[] = [];
  const blocks = html.split('<div class="_0_SRI').slice(1);

  for (const block of blocks) {
    const link = /class="__sri_title_link[^"]*"[^>]*title="([^"]*)"[^>]*href="([^"]*)"/.exec(block);
    if (link === null) continue;

    const title = decodeEntities(link[1] ?? "").trim();
    const href = decodeEntities(link[2] ?? "").trim();
    if (title.length === 0 || !href.startsWith("http")) continue;

    const desc = extractDescription(block);
    results.push({
      position: results.length + 1,
      title,
      link: href,
      snippet: desc === null ? "" : toText(desc),
    });
  }

  return results;
}

/**
 * Search Kagi using a subscription session token.
 *
 * `params.gl` and `params.hl` are ignored: /html/search takes its region and
 * language from the account's own settings, not from the query string.
 */
export async function searchKagi(
  token: string,
  params: SearchParams,
  fetchImpl: typeof fetch = fetch,
): Promise<SearchResponse> {
  const url = new URL(SEARCH_URL);
  url.searchParams.set("q", params.q);

  let response: Response;
  try {
    response = await fetchImpl(url.toString(), {
      headers: {
        Cookie: `kagi_session=${token}`,
        // Kagi serves a challenge page to clients without a browser-shaped UA.
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) serp-axi",
      },
    });
  } catch (cause) {
    throw new SerpAxiError(
      `network error calling Kagi: ${boundedDetail((cause as Error).message)}`,
      "runtime",
      "check network connectivity and retry",
    );
  }

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new SerpAxiError(
        `Kagi rejected the session token (${response.status})`,
        "runtime",
        "the token may have expired; get a fresh one from kagi.com/settings?p=user_details",
      );
    }
    if (response.status === 429) {
      throw new SerpAxiError("Kagi rate-limited this request (429)", "runtime", "wait and retry later");
    }
    if (response.status >= 500) {
      throw new SerpAxiError(`Kagi had an upstream failure (${response.status})`, "runtime", "retry later");
    }
    const text = boundedDetail(await response.text().catch(() => ""));
    throw new SerpAxiError(
      `Kagi returned an unexpected status ${response.status}: ${text || "no details"}`,
      "runtime",
      "this is not a status serp-axi maps explicitly; report it if it persists",
    );
  }

  const html = await response.text();
  const organic = parseKagiHtml(html);

  // An expired token still returns 200, with a sign-in page instead of results.
  if (organic.length === 0) {
    throw new SerpAxiError(
      "Kagi returned no results",
      "runtime",
      "if this repeats for ordinary queries the session token has likely expired; " +
        "get a fresh one from kagi.com/settings?p=user_details",
    );
  }

  return { organic: organic.slice(0, params.num) };
}
