import os from "node:os";
import { isIP } from "node:net";
import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerpAxiError } from "../errors.ts";
import type { AxiOutput } from "../output.ts";
import { scrapeBrightData, BRIGHT_DATA_DEFAULT_DATASET_ID, type BrightDataRecord } from "../brightdata.ts";
import { scrapeSerper } from "../serper.ts";
import { fetchViaLadder, LADDER_AXIS_FLAG_NAMES, resolveLadderAxes, resolveLadderBin } from "../ladder.ts";
import type { StoredConfig } from "../config.ts";
import { loadStoredConfig } from "../config.ts";
import {
  DEFAULT_LIMIT,
  FULL_LIMIT,
  INCLUDE_MARKUP_ENV,
  resolveIncludeMarkup,
  shapeScrapeRecord,
} from "../scrape-output.ts";

export const SCRAPE_FLAGS: FlagSpec = {
  full: "boolean",
  "include-markup": "boolean",
  provider: "string",
  "dataset-id": "string",
  ladder: "boolean",
  "tab-state": "string",
  "cookie-state": "string",
  "cache-state": "string",
  "fingerprint-state": "string",
  "rung-ceiling": "string",
  profile: "string",
  "jar-in": "string",
  "jar-out": "string",
  "http-jar-in": "string",
  "http-jar-out": "string",
};

// The six axes and the jar paths are ladder-only. Rejecting them elsewhere
// keeps a typo like `--tab-state` from being parsed and then silently ignored.
// Imported rather than re-listed: the axis table owns the names, so an axis
// cannot be addable to the wire without becoming addable to the CLI.
const LADDER_AXIS_FLAGS = LADDER_AXIS_FLAG_NAMES;

const PROVIDERS = ["serper", "brightdata"] as const;
type Provider = (typeof PROVIDERS)[number];

// Bright Data's record shape depends on the dataset, so every string field is
// limited except the url, which has to stay usable as a link.
const NON_TRUNCATED_RECORD_FIELDS: ReadonlySet<string> = new Set(["url"]);

function nonEmpty(value: string | undefined): string | undefined {
  return value !== undefined && value.length > 0 ? value : undefined;
}

function preferredUrlString(raw: string, normalized: URL): string {
  const normalizedStr = normalized.toString();
  if (raw === normalizedStr) return normalizedStr;
  if (raw + "/" === normalizedStr) return raw;
  return normalizedStr;
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

const SCRAPE_HELP = `serp-axi scrape <url> [--full] [--include-markup]
serp-axi scrape <url> [<url2> ...] --provider brightdata [--full] [--include-markup] [--dataset-id <id>]
serp-axi scrape <url> [--full] [--include-markup] --ladder

Fetch and extract readable text from one or more web pages.

Raw markup is left out by default. A field that holds raw HTML (its name ends in
"html", or its value is a whole HTML document) is omitted from the result and
named in markupOmitted. Markdown and plain-text fields are kept as they are.

Providers:
  serper (default)   Serper's own scrape endpoint. Exactly one URL, synchronous.
  brightdata          Bright Data's dataset scrape API. One or more URLs, synchronous,
                      batched in a single request. Requires BRIGHTDATA_API_KEY.
  ladder (--ladder)   Resident ladder CLI: free, no API key. Exactly one URL.
                      Binary from SERP_AXI_LADDER_BIN, a ladder-cli inside or
                      beside this package, or PATH.

Flags:
  --full                Return up to 50,000 characters per page instead of the default 1,200.
  --include-markup      Keep raw-HTML fields instead of omitting them. Serper and --ladder
                         return no such fields, so it changes nothing there.
                         Also: SERP_AXI_INCLUDE_MARKUP=1|0, or "includeMarkup": true in the
                         config file. Precedence: flag > env > config > off.
  --provider <name>      serper (default) or brightdata. Not valid with --ladder.
  --ladder               Scrape through the resident ladder CLI instead of a paid provider.
  --dataset-id <id>     Bright Data dataset to scrape against.
                         Default: ${BRIGHT_DATA_DEFAULT_DATASET_ID} (or $BRIGHTDATA_DATASET_ID).
                         Only valid with --provider brightdata.

Ladder axes (only with --ladder; flag > env > profile > config > default):
  --tab-state <state>          fresh (default) or same; reserved; not yet applied
  --cookie-state <state>       cold (default) or jar; jar needs a path (see below)
  --cache-state <state>        cold (default) or warm; reserved; not yet applied
  --fingerprint-state <state>  rotate (default) or stable; reserved; not yet applied
  --rung-ceiling <1-5>         Highest rung allowed. Default 5; currently stops at rung 4.
  --profile <name>             Named bundle of axes from ladderProfiles in the config file.
  --jar-in <path>              Filtered browser JSON cookie jar to load.
  --jar-out <path>             Filtered browser JSON cookie jar to save.
                         --cookie-state jar mirrors whichever of these you pass to both.
                         Browser jar paths reach zendriver (rungs 3-4) only, never HTTP or Camoufox.
  --http-jar-in <path>         Full-session Netscape cookie jar for HTTP rung 1 only.
  --http-jar-out <path>        Save HTTP-session cookies; never mirrored or converted.

Rungs 1-4 fetch pages. Rung 5 is deferred and is not attempted; audio helpers are unwired.

Examples:
  serp-axi scrape https://example.com/article
  serp-axi scrape https://example.com/article --full
  serp-axi scrape https://example.com https://example.com/1 --provider brightdata
  serp-axi scrape https://example.com/article --ladder
  serp-axi scrape https://example.com/article --ladder --cookie-state jar --jar-out ~/clearance.cookies.json`;

const IPV4_BLOCKED_RANGES: Array<[number, number]> = [
  [0x00000000, 0x00ffffff],
  [0x0a000000, 0x0affffff],
  [0x64400000, 0x647fffff],
  [0x7f000000, 0x7fffffff],
  [0xa9fe0000, 0xa9feffff],
  [0xac100000, 0xac1fffff],
  [0xc0000000, 0xc00000ff],
  [0xc0000200, 0xc00002ff],
  [0xc0a80000, 0xc0a8ffff],
  [0xc6120000, 0xc633ffff],
  [0xc6336400, 0xc63364ff],
  [0xcb007100, 0xcb0071ff],
];

function ipv4ToInt(address: string): number | undefined {
  const parts = address.split(".");
  if (parts.length !== 4) return undefined;
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return undefined;
    const byte = Number(part);
    if (byte > 255) return undefined;
    value = (value << 8) | byte;
  }
  return value >>> 0;
}

function ipv4InRanges(address: string): boolean {
  const value = ipv4ToInt(address);
  if (value === undefined) return false;
  return IPV4_BLOCKED_RANGES.some(([start, end]) => value >= start && value <= end);
}

function ipv4FromMappedIpv6(hostname: string): string | undefined {
  const match = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i.exec(hostname);
  if (!match) return undefined;
  const bytes = [match[1], match[2]].map((hex) => Number.parseInt(hex, 16));
  if (bytes.some((byte) => Number.isNaN(byte) || byte > 0xffff)) return undefined;
  return [bytes[0] >> 8, bytes[0] & 0xff, bytes[1] >> 8, bytes[1] & 0xff].join(".");
}

function blockedHost(hostname: string): boolean {
  const family = isIP(hostname);
  if (family === 0) return false;
  if (family === 4) return ipv4InRanges(hostname);
  if (hostname === "::1") return true;
  const mapped = ipv4FromMappedIpv6(hostname);
  if (mapped !== undefined) return ipv4InRanges(mapped);
  const firstSegment = /^[0-9a-f]{1,4}/i.exec(hostname)?.[0] ?? "";
  const firstGroup = Number.parseInt(firstSegment, 16);
  if (Number.isNaN(firstGroup)) return false;
  if (firstGroup >= 0xfc00 && firstGroup <= 0xfdff) return true;
  if (firstGroup >= 0xfe80 && firstGroup <= 0xfebf) return true;
  return false;
}

function validateUrl(raw: string): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SerpAxiError(`"${raw}" is not a valid URL`, "usage", "example: serp-axi scrape https://example.com/article");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SerpAxiError(
      `scrape only accepts http/https URLs, got "${url.protocol}"`,
      "usage",
      "example: serp-axi scrape https://example.com/article",
    );
  }
  const hostname = url.hostname.toLowerCase();
  const bareHost = hostname.startsWith("[") && hostname.endsWith("]") ? hostname.slice(1, -1) : hostname;
  if (hostname === "localhost" || blockedHost(bareHost)) {
    throw new SerpAxiError(
      `"${hostname}" is a loopback or private-range host`,
      "usage",
      "scrape only accepts publicly reachable URLs",
    );
  }
  return url;
}

function parseProvider(raw: string | boolean | undefined): Provider {
  if (raw === undefined) return "serper";
  if (typeof raw !== "string" || !PROVIDERS.includes(raw as Provider)) {
    throw new SerpAxiError(
      `--provider must be one of ${PROVIDERS.join(", ")}, got "${String(raw)}"`,
      "usage",
      "example: --provider brightdata",
    );
  }
  return raw as Provider;
}

function shapeBrightDataRecord(record: BrightDataRecord, full: boolean, includeMarkup: boolean): AxiOutput {
  const url = shellQuote(typeof record.url === "string" ? record.url : "<url>");
  return shapeScrapeRecord(record, {
    full,
    includeMarkup,
    rerun: `serp-axi scrape ${url} --provider brightdata`,
    scope: { kind: "every-string", except: NON_TRUNCATED_RECORD_FIELDS },
  });
}

async function runBrightDataScrape(
  positionals: string[],
  flags: Record<string, string | boolean>,
  fetchImpl: typeof fetch,
  env: NodeJS.ProcessEnv,
  includeMarkup: boolean,
): Promise<AxiOutput> {
  if (positionals.length === 0) {
    throw new SerpAxiError(
      "scrape requires at least one URL",
      "usage",
      "example: serp-axi scrape https://example.com --provider brightdata",
    );
  }
  const urls = positionals.map((raw) => preferredUrlString(raw, validateUrl(raw)));

  const apiKey = env.BRIGHTDATA_API_KEY;
  if (!apiKey) {
    throw new SerpAxiError(
      "BRIGHTDATA_API_KEY is not set",
      "runtime",
      "export BRIGHTDATA_API_KEY=<your key> and re-run",
    );
  }
  const datasetId =
    nonEmpty(flags["dataset-id"] as string | undefined) ??
    nonEmpty(env.BRIGHTDATA_DATASET_ID) ??
    BRIGHT_DATA_DEFAULT_DATASET_ID;

  const full = Boolean(flags.full);
  const records = await scrapeBrightData(apiKey, datasetId, urls, full ? FULL_LIMIT : DEFAULT_LIMIT, fetchImpl);

  return {
    provider: "brightdata",
    datasetId,
    results: records.map((record) => shapeBrightDataRecord(record, full, includeMarkup)),
  };
}

// The config file is read only when neither the flag nor the env var settles
// the answer, so a run governed entirely by flags or env does not depend on the
// file being readable.
function resolveMarkupSetting(
  flags: Record<string, string | boolean>,
  env: NodeJS.ProcessEnv,
  config: StoredConfig | undefined,
): boolean {
  const flag = flags["include-markup"] === true;
  const fromEnv = nonEmpty(env[INCLUDE_MARKUP_ENV]);
  const settled = flag || fromEnv !== undefined;
  return resolveIncludeMarkup({
    flag,
    env: fromEnv,
    config: settled ? undefined : (config ?? loadStoredConfig(os.homedir(), env)),
  });
}

// `env` and `config` are injectable so a test can drive every setting without
// touching process.env or the machine's real config file. `config` left unset
// means "read the config file if a setting needs it".
export async function runScrape(
  args: string[],
  fetchImpl: typeof fetch = fetch,
  env: NodeJS.ProcessEnv = process.env,
  config?: StoredConfig,
): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SCRAPE_FLAGS, "scrape");
  const includeMarkup = resolveMarkupSetting(flags, env, config);

  if (flags.ladder) {
    return runLadderScrape(positionals, flags, env, config, includeMarkup);
  }

  for (const axis of LADDER_AXIS_FLAGS) {
    if (flags[axis] !== undefined) {
      throw new SerpAxiError(
        `--${axis} only applies with --ladder`,
        "usage",
        "add --ladder, or drop the axis flag",
      );
    }
  }

  const provider = parseProvider(flags.provider);

  if (provider === "brightdata") {
    return runBrightDataScrape(positionals, flags, fetchImpl, env, includeMarkup);
  }

  if (flags["dataset-id"] !== undefined) {
    throw new SerpAxiError(
      "--dataset-id only applies with --provider brightdata",
      "usage",
      "example: serp-axi scrape <url> --provider brightdata --dataset-id <id>",
    );
  }

  const raw = positionals[0];
  if (!raw) {
    throw new SerpAxiError("scrape requires a URL", "usage", "example: serp-axi scrape https://example.com/article");
  }
  if (positionals.length > 1) {
    const extras = positionals.slice(1).map((p) => `"${p}"`).join(", ");
    throw new SerpAxiError(
      `unexpected argument${positionals.length > 2 ? "s" : ""} ${extras} for \`scrape\``,
      "usage",
      "usage: serp-axi scrape <url> [--full] (pass multiple URLs with --provider brightdata)",
    );
  }
  const url = validateUrl(raw);

  const apiKey = env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerpAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  const response = await scrapeSerper(apiKey, url.toString(), fetchImpl);

  const record: AxiOutput = { url: url.toString() };
  if (response.metadata.title) {
    record.title = response.metadata.title;
  }
  record.text = response.text;
  return shapeScrapeRecord(record, {
    full: Boolean(flags.full),
    includeMarkup,
    rerun: `serp-axi scrape ${shellQuote(url.toString())}`,
    scope: { kind: "field", key: "text" },
  });
}

async function runLadderScrape(
  positionals: string[],
  flags: Record<string, string | boolean>,
  env: NodeJS.ProcessEnv = process.env,
  // Injectable rather than read at the call site: a ladder scrape governed
  // entirely by flags should not depend on the machine's config file being
  // readable, and a test should not have to fake a home directory to reach one.
  config: StoredConfig = loadStoredConfig(os.homedir()),
  includeMarkup = false,
): Promise<AxiOutput> {
  if (flags.provider !== undefined) {
    throw new SerpAxiError(
      "--provider does not apply with --ladder",
      "usage",
      "drop --provider, or drop --ladder",
    );
  }
  if (flags["dataset-id"] !== undefined) {
    throw new SerpAxiError(
      "--dataset-id only applies with --provider brightdata",
      "usage",
      "example: serp-axi scrape <url> --provider brightdata --dataset-id <id>",
    );
  }
  const raw = positionals[0];
  if (!raw) {
    throw new SerpAxiError("scrape requires a URL", "usage", "example: serp-axi scrape https://example.com/article --ladder");
  }
  if (positionals.length > 1) {
    throw new SerpAxiError(
      "--ladder scrapes exactly one URL per invocation",
      "usage",
      "run once per URL; batching lands in a later phase",
    );
  }
  const url = validateUrl(raw);
  const bin = resolveLadderBin(env);
  const axes = resolveLadderAxes({ flag: flags, env, config });
  let response;
  try {
    response = await fetchViaLadder(url.toString(), { bin }, axes);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new SerpAxiError(`ladder scrape failed: ${message}`, "runtime", "check that the ladder CLI is installed (SERP_AXI_LADDER_BIN)");
  }
  if (response.verdict !== "ok") {
    // `error` is not `blocked`: one says the page defended itself, the other
    // says the climb never got to judge a page at all. Reporting the second as
    // the first tells the caller to retry a defence that never happened.
    const note = response.warning ? ` (${response.warning})` : "";
    throw new SerpAxiError(
      `"${url.toString()}" could not be fetched (ladder verdict: ${response.verdict}, rung ${response.rungReached})${note}`,
      "runtime",
      response.verdict === "blocked"
        ? "the page is defended; retry later or solve it interactively"
        : response.verdict === "error"
          ? `the ladder could not fetch the page: ${response.warning ?? "see the runtime error"}`
          : "the page appears dead; check the URL",
      { verdict: response.verdict, rungReached: response.rungReached },
    );
  }

  const record: AxiOutput = {
    url: url.toString(),
    verdict: response.verdict,
    rungReached: response.rungReached,
    links: response.links,
  };
  if (response.title) {
    record.title = response.title;
  }
  record.text = response.text;
  const output = shapeScrapeRecord(record, {
    full: Boolean(flags.full),
    includeMarkup,
    rerun: `serp-axi scrape ${shellQuote(url.toString())} --ladder`,
    scope: { kind: "field", key: "text" },
  });
  // The child's own note about how the page arrived (site api, rung used,
  // anything it thought worth saying). It was parsed, validated, and then
  // dropped by this branch, which made the field a write-only part of the
  // protocol.
  if (response.warning) {
    output.warning = response.warning;
  }
  return output;
}

export const scrapeCommand: CliCommand = {
  name: "scrape",
  help: SCRAPE_HELP,
  run: (args) => runScrape(args),
};
