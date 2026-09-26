import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerpAxiError } from "../errors.ts";
import { truncate, type AxiOutput } from "../output.ts";
import { searchSerper, type SearchParams, type SearchResponse } from "../serper.ts";
import { searchBrightData, BRIGHT_DATA_DEFAULT_ZONE } from "../brightdata.ts";
import { searchKagi } from "../kagi.ts";

const SEARCH_FLAGS: FlagSpec = {
  region: "string",
  lang: "string",
  num: "string",
  fields: "string",
  provider: "string",
  zone: "string",
};

const ALLOWED_EXTRA_FIELDS = ["date", "sitelinks"];
const PROVIDERS = ["serper", "brightdata", "kagi"] as const;
type Provider = (typeof PROVIDERS)[number];
const SNIPPET_LIMIT = 200;

const SEARCH_HELP = `serp-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>] [--provider <name>] [--zone <name>]

Run a search query via Serper, Bright Data, or Kagi.

Flags:
  --region <cc>      Two-letter region code (maps to gl). Default: us
  --lang <code>       Language code (maps to hl). Default: en
  --num <n>            Number of results, 1-100. Default: 10
  --fields <a,b,c>      Extra fields to include beyond the default schema.
                          Accepted: date, sitelinks. Serper only.
  --provider <name>     Which backend to query: serper, brightdata, or kagi. Default: serper
  --zone <name>          Bright Data zone to use. Only applies with --provider brightdata.
                          Default: "${BRIGHT_DATA_DEFAULT_ZONE}", or the BRIGHTDATA_ZONE env var.

Requires SERPER_API_KEY (serper), BRIGHTDATA_API_KEY (brightdata), or
KAGI_SESSION_TOKEN (kagi) in the environment for whichever provider is
selected. Bright Data's zone defaults to "${BRIGHT_DATA_DEFAULT_ZONE}";
override with --zone or the BRIGHTDATA_ZONE env var (--zone wins if both
are set).

Kagi searches your own subscription through its session token. It takes
region and language from your Kagi account settings, so --region and --lang
are accepted but have no effect there.

Examples:
  serp-axi search "site:example.com pricing"
  serp-axi search "climate policy" --region uk --lang en --num 20
  serp-axi search "conference talks" --fields date,sitelinks
  serp-axi search "climate policy" --provider brightdata
  serp-axi search "climate policy" --provider brightdata --zone my_zone
  serp-axi search "climate policy" --provider kagi`;

function parseNum(raw: string | undefined): number {
  if (raw === undefined) return 10;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 100) {
    throw new SerpAxiError(`--num must be an integer in 1..100, got "${raw}"`, "usage", "example: --num 20");
  }
  return value;
}

function parseRegionOrLang(raw: string | undefined, flagName: string, fallback: string): string {
  const value = raw ?? fallback;
  if (!/^[a-z]+$/.test(value)) {
    throw new SerpAxiError(
      `--${flagName} must be non-empty lowercase ASCII, got "${value}"`,
      "usage",
      `example: --${flagName} ${fallback}`,
    );
  }
  return value;
}

function parseFields(raw: string | undefined): string[] {
  if (raw === undefined) return [];
  const fields = raw
    .split(",")
    .map((f) => f.trim())
    .filter((f) => f.length > 0);
  for (const field of fields) {
    if (!ALLOWED_EXTRA_FIELDS.includes(field)) {
      throw new SerpAxiError(
        `unknown field "${field}" for --fields`,
        "usage",
        `accepted fields: ${ALLOWED_EXTRA_FIELDS.join(", ")}`,
      );
    }
  }
  return fields;
}

function parseProvider(raw: string | undefined): Provider {
  const value = raw ?? "serper";
  if (!PROVIDERS.includes(value as Provider)) {
    throw new SerpAxiError(
      `unknown --provider "${value}"`,
      "usage",
      `valid providers: ${PROVIDERS.join(", ")}`,
    );
  }
  return value as Provider;
}

async function runProviderSearch(
  provider: Provider,
  params: SearchParams,
  fetchImpl: typeof fetch,
  zoneFlag: string | undefined,
): Promise<SearchResponse> {
  if (provider === "serper") {
    const apiKey = process.env.SERPER_API_KEY;
    if (!apiKey) {
      throw new SerpAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
    }
    return searchSerper(apiKey, params, fetchImpl);
  }
  if (provider === "brightdata") {
    const apiKey = process.env.BRIGHTDATA_API_KEY;
    if (!apiKey) {
      throw new SerpAxiError(
        "BRIGHTDATA_API_KEY is not set",
        "runtime",
        "export BRIGHTDATA_API_KEY=<your key> and re-run",
      );
    }
    const zone = zoneFlag || process.env.BRIGHTDATA_ZONE || BRIGHT_DATA_DEFAULT_ZONE;
    return searchBrightData(apiKey, params, fetchImpl, zone);
  }
  const token = process.env.KAGI_SESSION_TOKEN;
  if (!token) {
    throw new SerpAxiError(
      "KAGI_SESSION_TOKEN is not set",
      "runtime",
      "export KAGI_SESSION_TOKEN=<your token> and re-run; " +
        "get the token from kagi.com/settings?p=user_details",
    );
  }
  return searchKagi(token, params, fetchImpl);
}

export async function runSearch(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SEARCH_FLAGS, "search");

  const query = positionals.join(" ").trim();
  if (query.length === 0) {
    throw new SerpAxiError("search requires a query", "usage", 'example: serp-axi search "<query>"');
  }

  const num = parseNum(flags.num as string | undefined);
  const region = parseRegionOrLang(flags.region as string | undefined, "region", "us");
  const lang = parseRegionOrLang(flags.lang as string | undefined, "lang", "en");
  const provider = parseProvider(flags.provider as string | undefined);
  const extraFields = parseFields(flags.fields as string | undefined);
  if (provider !== "serper" && flags.fields !== undefined) {
    throw new SerpAxiError(
      `--fields is not supported with --provider ${provider}`,
      "usage",
      "drop --fields, or use --provider serper",
    );
  }

  const params: SearchParams = { q: query, gl: region, hl: lang, num };
  const response = await runProviderSearch(provider, params, fetchImpl, flags.zone as string | undefined);

  const results = response.organic.map((r) => {
    const snippetInfo = truncate(r.snippet, SNIPPET_LIMIT - 3);
    const row: Record<string, unknown> = {
      position: r.position,
      title: r.title,
      link: r.link,
      snippet: snippetInfo.truncated ? `${snippetInfo.text}...` : snippetInfo.text,
    };
    for (const field of extraFields) {
      row[field] = (r as unknown as Record<string, unknown>)[field];
    }
    return row;
  });

  if (results.length === 0) {
    return {
      count: 0,
      results: `0 results found for query "${query}"`,
      help: "try a different query, or broaden --region/--lang",
    };
  }

  return {
    count: results.length,
    results,
    help: 'Run `serp-axi scrape "<link>"` to read a result in full',
  };
}

export const searchCommand: CliCommand = {
  name: "search",
  help: SEARCH_HELP,
  run: (args) => runSearch(args),
};
