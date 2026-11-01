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
  FULL_MAX_CHARS_ENV,
  INCLUDE_MARKUP_ENV,
  MAX_CHARS_ENV,
  limitFor,
  requestCharLimits,
  resolveCharLimits,
  resolveIncludeMarkup,
  shapeScrapeRecord,
  type CharLimitRequest,
  type CharLimits,
} from "../scrape-output.ts";

export const SCRAPE_FLAGS: FlagSpec = {
  full: "boolean",
  "max-chars": "string",
  "full-max-chars": "string",
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

const SCRAPE_HELP = `serp-axi scrape <url> [--full [--full-max-chars <n>] | --max-chars <n>] [--include-markup]
serp-axi scrape <url> [<url2> ...] --provider brightdata [--full [--full-max-chars <n>] | --max-chars <n>] [--include-markup] [--dataset-id <id>]
serp-axi scrape <url> [--full [--full-max-chars <n>] | --max-chars <n>] [--include-markup] --ladder

Fetch and extract readable text from one or more web pages.

Raw markup is left out by default. A field that holds raw HTML (its name ends in
"html", or its value is a whole HTML document) is omitted from the result and
named in markupOmitted. Markdown and plain-text fields are kept as they are. A
record whose only text is an HTML document keeps it, cut to the character limit.

Providers:
  serper (default)   Serper's own scrape endpoint. Exactly one URL, synchronous.
  brightdata          Bright Data's dataset scrape API. One or more URLs, synchronous,
                      batched in a single request. Requires BRIGHTDATA_API_KEY.
  ladder (--ladder)   Resident ladder CLI: free, no API key. Exactly one URL.
                      Binary from SERP_AXI_LADDER_BIN, a ladder-cli inside or
                      beside this package, or PATH.

Flags:
  --full                Return up to 50,000 characters per page instead of the default 1,200.
  --max-chars <n>       Cap each page at n characters instead of the default 1,200.
                         Not valid with --full, which has its own cap.
                         Also: ${MAX_CHARS_ENV}=<n>, or "maxChars": <n> in the config file.
  --full-max-chars <n>  Change the 50,000-character cap that --full uses. Only valid with --full.
                         Also: ${FULL_MAX_CHARS_ENV}=<n>, or "fullMaxChars": <n> in the config file.
                         Each cap: flag > env > config > built-in default. Both are whole
                         numbers of at least 1, and a bad env or config value fails the run
                         whether or not --full is given.
  --include-markup      Keep raw-HTML fields instead of omitting them. The character limit
                         still applies to what is kept; add --full to raise it. Serper and
                         --ladder return no raw-HTML field of their own, so the flag matters
                         there only when the title is itself a whole HTML document.
                         Also: ${INCLUDE_MARKUP_ENV}=1|0, or "includeMarkup": true in the
                         config file (read for Bright Data only).
                         Precedence: flag > env > config > off.
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
  serp-axi scrape https://example.com/article --max-chars 4000
  serp-axi scrape https://example.com/article --full --full-max-chars 100000
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

// The command a hint tells the reader to run. It carries the flags that changed
// what this record holds, so the rerun is the same request with a bigger limit
// rather than a neighbouring one. Env and config settings are not repeated: they
// apply to the rerun on their own.
function withMarkupFlag(rerun: string, includeMarkup: boolean): string {
  return includeMarkup ? `${rerun} --include-markup` : rerun;
}

function shapeBrightDataRecord(
  record: BrightDataRecord,
  full: boolean,
  limits: CharLimits,
  includeMarkup: boolean,
  datasetFlag: string,
): AxiOutput {
  const url = shellQuote(typeof record.url === "string" ? record.url : "<url>");
  return shapeScrapeRecord(record, {
    full,
    limits,
    includeMarkup,
    rerun: withMarkupFlag(`serp-axi scrape ${url} --provider brightdata${datasetFlag}`, includeMarkup),
    scope: { kind: "every-string", except: NON_TRUNCATED_RECORD_FIELDS },
  });
}

// Serper and the ladder each return one body of text; the record's other strings
// (a title, the ladder's warning) ride along outside the limit's scope.
function shapeTextRecord(
  record: AxiOutput,
  full: boolean,
  limits: CharLimits,
  includeMarkup: boolean,
  rerun: string,
): AxiOutput {
  return shapeScrapeRecord(record, {
    full,
    limits,
    includeMarkup,
    rerun: withMarkupFlag(rerun, includeMarkup),
    scope: { kind: "field", key: "text" },
  });
}

async function runBrightDataScrape(
  positionals: string[],
  flags: Record<string, string | boolean>,
  fetchImpl: typeof fetch,
  env: NodeJS.ProcessEnv,
  config: StoredConfig | undefined,
  requestedMarkup: boolean | undefined,
  charRequest: CharLimitRequest,
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
  // The config file is read here, after the input checks, so a bad URL or a
  // missing key is reported as that rather than as a problem with a file the run
  // never needed. Every scrape reads it for the character limits; Bright Data is
  // also the one provider that reads it for `includeMarkup`, because its records
  // are the ones that carry raw-HTML fields of their own.
  const stored = config ?? loadStoredConfig(os.homedir(), env);
  const includeMarkup = requestedMarkup ?? resolveIncludeMarkup({ config: stored });
  const limits = resolveCharLimits(charRequest, stored);

  const datasetFlagValue = nonEmpty(flags["dataset-id"] as string | undefined);
  const datasetId = datasetFlagValue ?? nonEmpty(env.BRIGHTDATA_DATASET_ID) ?? BRIGHT_DATA_DEFAULT_DATASET_ID;
  const datasetFlag = datasetFlagValue === undefined ? "" : ` --dataset-id ${shellQuote(datasetFlagValue)}`;

  const full = Boolean(flags.full);
  const records = await scrapeBrightData(apiKey, datasetId, urls, limitFor(full, limits), fetchImpl);

  return {
    provider: "brightdata",
    datasetId,
    results: records.map((record) => shapeBrightDataRecord(record, full, limits, includeMarkup, datasetFlag)),
  };
}

// What the flags and env vars say about the two character caps; the config file
// fills the rest later. A malformed value, or `--max-chars` with `--full`, fails
// here, before any network call.
function charLimitRequest(flags: Record<string, string | boolean>, env: NodeJS.ProcessEnv): CharLimitRequest {
  return requestCharLimits({
    full: Boolean(flags.full),
    flagMaxChars: flags["max-chars"] as string | undefined,
    flagFullMaxChars: flags["full-max-chars"] as string | undefined,
    envMaxChars: nonEmpty(env[MAX_CHARS_ENV]),
    envFullMaxChars: nonEmpty(env[FULL_MAX_CHARS_ENV]),
  });
}

// What the flag or the env var says about markup, or undefined when neither
// speaks. A malformed env value fails here, before any network call. The config
// file is not read here: see runBrightDataScrape.
function markupFromFlagOrEnv(flags: Record<string, string | boolean>, env: NodeJS.ProcessEnv): boolean | undefined {
  const flag = flags["include-markup"] === true;
  const fromEnv = nonEmpty(env[INCLUDE_MARKUP_ENV]);
  if (!flag && fromEnv === undefined) return undefined;
  return resolveIncludeMarkup({ flag, env: fromEnv });
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
  const requestedMarkup = markupFromFlagOrEnv(flags, env);
  const charRequest = charLimitRequest(flags, env);

  if (flags.ladder) {
    return runLadderScrape(positionals, flags, env, config, requestedMarkup ?? false, charRequest);
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
    return runBrightDataScrape(positionals, flags, fetchImpl, env, config, requestedMarkup, charRequest);
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
      "usage: serp-axi scrape <url> [--full [--full-max-chars <n>] | --max-chars <n>] [--include-markup] (pass multiple URLs with --provider brightdata)",
    );
  }
  const url = validateUrl(raw);

  const apiKey = env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerpAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  // After the URL and key checks, for the reason given in runBrightDataScrape.
  const limits = resolveCharLimits(charRequest, config ?? loadStoredConfig(os.homedir(), env));

  const response = await scrapeSerper(apiKey, url.toString(), fetchImpl);

  const record: AxiOutput = { url: url.toString() };
  if (response.metadata.title) {
    record.title = response.metadata.title;
  }
  record.text = response.text;
  return shapeTextRecord(
    record,
    Boolean(flags.full),
    limits,
    requestedMarkup ?? false,
    `serp-axi scrape ${shellQuote(url.toString())}`,
  );
}

async function runLadderScrape(
  positionals: string[],
  flags: Record<string, string | boolean>,
  env: NodeJS.ProcessEnv,
  // Injectable so a test does not need a home directory. Left unset, the file is
  // read from the same env the rest of the run uses, and only after the URL and
  // the binary check out.
  config: StoredConfig | undefined,
  includeMarkup: boolean,
  charRequest: CharLimitRequest,
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
  const stored = config ?? loadStoredConfig(os.homedir(), env);
  const axes = resolveLadderAxes({ flag: flags, env, config: stored });
  const limits = resolveCharLimits(charRequest, stored);
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
  const axisFlags = LADDER_AXIS_FLAGS.flatMap((name) => {
    const value = flags[name];
    return typeof value === "string" ? [` --${name} ${shellQuote(value)}`] : [];
  }).join("");
  const output = shapeTextRecord(
    record,
    Boolean(flags.full),
    limits,
    includeMarkup,
    `serp-axi scrape ${shellQuote(url.toString())} --ladder${axisFlags}`,
  );
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
