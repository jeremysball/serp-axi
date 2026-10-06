import os from "node:os";
import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerpAxiError } from "../errors.ts";
import { truncate, type AxiOutput } from "../output.ts";
import type { SearchParams } from "../serper.ts";
import { BRIGHT_DATA_DEFAULT_ZONE } from "../brightdata.ts";
import { searchStrategies, PROVIDERS, type Provider } from "../providers.ts";
import { loadStoredConfig } from "../config.ts";
import { resolveSearxngOptions, type EngineStatus } from "../searxng.ts";

const SEARCH_FLAGS: FlagSpec = {
  region: "string",
  lang: "string",
  num: "string",
  fields: "string",
  provider: "string",
  zone: "string",
  "searxng-url": "string",
  engines: "string",
  "search-timeout-ms": "string",
};

const ALLOWED_EXTRA_FIELDS = ["date", "sitelinks"];
const SNIPPET_LIMIT = 200;

const SEARCH_HELP = `serp-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>] [--provider <name>] [--zone <name>]
                              [--searxng-url <url>] [--engines <a,b>] [--search-timeout-ms <ms>]

Run a search query via Serper, Bright Data, Kagi, or SearXNG.

Flags:
  --region <cc>      Lowercase region code. Default: us
  --lang <code>       Language code. Default: en
  --num <n>            Number of results, 1-100. Default: 10
  --fields <a,b,c>      Extra fields to include beyond the default schema.
                           Accepted: date, sitelinks. Serper only.
  --provider <name>     Which backend to query: serper, brightdata, kagi, or searxng. Default: serper
  --zone <name>          Bright Data zone to use. Only applies with --provider brightdata.
                           Default: "${BRIGHT_DATA_DEFAULT_ZONE}", or the BRIGHTDATA_ZONE env var.
  --searxng-url <url>   Base URL of a SearXNG server. Only applies with --provider searxng.
                           Default: http://127.0.0.1:8888 (env SERP_AXI_SEARXNG_URL,
                           config searxngUrl; --searxng-url wins).
  --engines <a,b>       Comma-separated engine names to query. Only applies with --provider searxng.
                           Default: the server's configured engines (env SERP_AXI_SEARXNG_ENGINES,
                           config searxngEngines).
  --search-timeout-ms <ms>  Request timeout in milliseconds. Only applies with --provider searxng.
                           Default: 30000 (env SERP_AXI_SEARCH_TIMEOUT_MS, config searchTimeoutMs).

Paid providers require SERPER_API_KEY (serper), BRIGHTDATA_API_KEY (brightdata), or
KAGI_SESSION_TOKEN (kagi) in the environment for whichever provider is
selected. Bright Data's zone defaults to "${BRIGHT_DATA_DEFAULT_ZONE}";
override with --zone or the BRIGHTDATA_ZONE env var (--zone wins if both
are set).

The searxng provider needs no API key: it queries a SearXNG instance
directly. Loopback targets are allowed. Configuration precedence for its
endpoint, engines, and timeout is flag > SERP_AXI_SEARXNG_URL /
SERP_AXI_SEARXNG_ENGINES / SERP_AXI_SEARCH_TIMEOUT_MS > config file
(searxngUrl / searxngEngines / searchTimeoutMs) > built-in defaults.
The config file lives at $XDG_CONFIG_HOME/serp-axi/config.json or
~/.config/serp-axi/config.json.

Kagi searches your own subscription through its session token. It takes
region and language from your Kagi account settings, so --region and --lang
are accepted but have no effect there.

Examples:
  serp-axi search "site:example.com pricing"
  serp-axi search "climate policy" --region uk --lang en --num 20
  serp-axi search "conference talks" --fields date,sitelinks
  serp-axi search "climate policy" --provider brightdata
  serp-axi search "climate policy" --provider brightdata --zone my_zone
  serp-axi search "climate policy" --provider kagi
  serp-axi search "climate policy" --provider searxng
  serp-axi search "climate policy" --provider searxng --searxng-url http://127.0.0.1:8888 --engines bing,mojeek`;

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

function failedEngineCount(engines: EngineStatus[]): number {
  return engines.filter((e) => e.status !== "ok").length;
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

  const searxngOnlyFlags = ["searxng-url", "engines", "search-timeout-ms"] as const;
  if (provider !== "searxng") {
    for (const name of searxngOnlyFlags) {
      if (flags[name] !== undefined) {
        throw new SerpAxiError(
          `--${name} is only supported with --provider searxng`,
          "usage",
          "drop the flag, or use --provider searxng",
        );
      }
    }
  } else {
    if (flags.zone !== undefined) {
      throw new SerpAxiError("--zone is not supported with --provider searxng", "usage", "drop --zone");
    }
  }

  const params: SearchParams = { q: query, gl: region, hl: lang, num };

  let searxng;
  if (provider === "searxng") {
    const stored = loadStoredConfig(os.homedir());
    searxng = resolveSearxngOptions({
      flagUrl: flags["searxng-url"] as string | undefined,
      flagEngines: flags.engines as string | undefined,
      flagTimeoutMs: flags["search-timeout-ms"] as string | undefined,
      envUrl: process.env.SERP_AXI_SEARXNG_URL,
      envEngines: process.env.SERP_AXI_SEARXNG_ENGINES,
      envTimeoutMs: process.env.SERP_AXI_SEARCH_TIMEOUT_MS,
      config: stored,
    });
  }

  const response = await searchStrategies[provider].run({
    params,
    fetchImpl,
    zone: flags.zone as string | undefined,
    searxng,
  });

  if ("provider" in response && response.provider === "searxng") {
    const searxngResponse = response;
    const results = searxngResponse.organic.map((r) => {
      const snippetInfo = truncate(r.snippet, SNIPPET_LIMIT - 3);
      const row: Record<string, unknown> = {
        position: r.position,
        title: r.title,
        link: r.link,
        snippet: snippetInfo.truncated ? `${snippetInfo.text}...` : snippetInfo.text,
        engines: r.engines ?? [],
      };
      return row;
    });

    const failed = failedEngineCount(searxngResponse.engines);
    const base: AxiOutput = {
      provider: "searxng",
      status: searxngResponse.status,
      count: searxngResponse.organic.length,
      engines: searxngResponse.engines,
    };

    if (searxngResponse.status === "partial") {
      return {
        ...base,
        results,
        warning: `${failed} engine${failed === 1 ? "" : "s"} failed; results may be incomplete`,
        help: "retry later, adjust --engines, or check the SearXNG server logs",
      };
    }

    if (results.length === 0) {
      return {
        ...base,
        results: `0 results found for query "${query}"`,
        help: "try a different query, or broaden --region/--lang",
      };
    }

    return {
      ...base,
      results,
      help: 'Run `serp-axi scrape "<link>"` to read a result in full',
    };
  }

  const legacyRows = response.organic.map((r) => {
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

  if (legacyRows.length === 0) {
    return {
      count: 0,
      results: `0 results found for query "${query}"`,
      help: "try a different query, or broaden --region/--lang",
    };
  }

  return {
    count: legacyRows.length,
    results: legacyRows,
    help: 'Run `serp-axi scrape "<link>"` to read a result in full',
  };
}

export const searchCommand: CliCommand = {
  name: "search",
  help: SEARCH_HELP,
  run: (args) => runSearch(args),
};
