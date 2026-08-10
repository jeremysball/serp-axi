import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerperAxiError } from "../errors.ts";
import { truncate, type AxiOutput } from "../output.ts";
import { searchSerper, type SearchParams } from "../serper.ts";

const SEARCH_FLAGS: FlagSpec = {
  region: "string",
  lang: "string",
  num: "string",
  fields: "string",
};

const ALLOWED_EXTRA_FIELDS = ["date", "sitelinks"];
const SNIPPET_LIMIT = 200;

const SEARCH_HELP = `serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>]

Run a Serper (Google Search API) query.

Flags:
  --region <cc>      Two-letter region code (maps to Serper's gl). Default: us
  --lang <code>       Language code (maps to Serper's hl). Default: en
  --num <n>            Number of results, 1-100. Default: 10
  --fields <a,b,c>      Extra fields to include beyond the default schema.
                          Accepted: date, sitelinks

Examples:
  serper-axi search "site:example.com pricing"
  serper-axi search "climate policy" --region uk --lang en --num 20
  serper-axi search "conference talks" --fields date,sitelinks`;

function parseNum(raw: string | undefined): number {
  if (raw === undefined) return 10;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 100) {
    throw new SerperAxiError(`--num must be an integer in 1..100, got "${raw}"`, "usage", "example: --num 20");
  }
  return value;
}

function parseRegionOrLang(raw: string | undefined, flagName: string, fallback: string): string {
  const value = raw ?? fallback;
  if (!/^[a-z]+$/.test(value)) {
    throw new SerperAxiError(
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
      throw new SerperAxiError(
        `unknown field "${field}" for --fields`,
        "usage",
        `accepted fields: ${ALLOWED_EXTRA_FIELDS.join(", ")}`,
      );
    }
  }
  return fields;
}

export async function runSearch(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SEARCH_FLAGS, "search");

  const query = positionals.join(" ").trim();
  if (query.length === 0) {
    throw new SerperAxiError("search requires a query", "usage", 'example: serper-axi search "<query>"');
  }

  const num = parseNum(flags.num as string | undefined);
  const region = parseRegionOrLang(flags.region as string | undefined, "region", "us");
  const lang = parseRegionOrLang(flags.lang as string | undefined, "lang", "en");
  const extraFields = parseFields(flags.fields as string | undefined);

  const apiKey = process.env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerperAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  const params: SearchParams = { q: query, gl: region, hl: lang, num };
  const response = await searchSerper(apiKey, params, fetchImpl);

  const results = response.organic.map((r) => {
    const snippetInfo = truncate(r.snippet, SNIPPET_LIMIT);
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
    help: 'Run `serper-axi scrape "<link>"` to read a result in full',
  };
}

export const searchCommand: CliCommand = {
  name: "search",
  help: SEARCH_HELP,
  run: (args) => runSearch(args),
};
