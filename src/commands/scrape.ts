import { isIP } from "node:net";
import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerpAxiError } from "../errors.ts";
import { truncate, type AxiOutput } from "../output.ts";
import { scrapeBrightData, BRIGHT_DATA_DEFAULT_DATASET_ID, type BrightDataRecord } from "../brightdata.ts";
import { scrapeSerper } from "../serper.ts";

const SCRAPE_FLAGS: FlagSpec = {
  full: "boolean",
  provider: "string",
  "dataset-id": "string",
};

const DEFAULT_LIMIT = 1200;
const FULL_LIMIT = 50000;
const PROVIDERS = ["serper", "brightdata"] as const;
type Provider = (typeof PROVIDERS)[number];

const NON_TRUNCATED_RECORD_FIELDS = new Set(["url"]);

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

const SCRAPE_HELP = `serp-axi scrape <url> [--full]
serp-axi scrape <url> [<url2> ...] --provider brightdata [--full] [--dataset-id <id>]

Fetch and extract readable text from one or more web pages.

Providers:
  serper (default)   Serper's own scrape endpoint. Exactly one URL, synchronous.
  brightdata          Bright Data's dataset scrape API. One or more URLs, synchronous,
                      batched in a single request. Requires BRIGHTDATA_API_KEY.

Flags:
  --full                Return up to 50,000 characters per page instead of the default 1,200.
  --provider <name>      serper (default) or brightdata.
  --dataset-id <id>     Bright Data dataset to scrape against.
                         Default: ${BRIGHT_DATA_DEFAULT_DATASET_ID} (or $BRIGHTDATA_DATASET_ID).
                         Only valid with --provider brightdata.

Examples:
  serp-axi scrape https://example.com/article
  serp-axi scrape https://example.com/article --full
  serp-axi scrape https://example.com https://example.com/1 --provider brightdata`;

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

function summarizeRecord(record: BrightDataRecord, limit: number, full: boolean): AxiOutput {
  const out: AxiOutput = { ...record };
  for (const [key, value] of Object.entries(record)) {
    if (typeof value !== "string") continue;
    if (NON_TRUNCATED_RECORD_FIELDS.has(key)) continue;
    const info = truncate(value, limit);
    out[key] = info.text;
    const marker = `${key}TruncatedFrom`;
    if (info.truncated) {
      if (!Object.hasOwn(record, marker)) {
        out[marker] = info.totalChars;
      }
      const url = shellQuote(typeof record.url === "string" ? record.url : "<url>");
      out.help = full
        ? `content is capped at ${FULL_LIMIT} characters even with --full`
        : `Run \`serp-axi scrape ${url} --provider brightdata --full\` to see up to ${FULL_LIMIT} characters`;
    }
  }
  return out;
}

async function runBrightDataScrape(
  positionals: string[],
  flags: Record<string, string | boolean>,
  fetchImpl: typeof fetch,
): Promise<AxiOutput> {
  if (positionals.length === 0) {
    throw new SerpAxiError(
      "scrape requires at least one URL",
      "usage",
      "example: serp-axi scrape https://example.com --provider brightdata",
    );
  }
  const urls = positionals.map((raw) => preferredUrlString(raw, validateUrl(raw)));

  const apiKey = process.env.BRIGHTDATA_API_KEY;
  if (!apiKey) {
    throw new SerpAxiError(
      "BRIGHTDATA_API_KEY is not set",
      "runtime",
      "export BRIGHTDATA_API_KEY=<your key> and re-run",
    );
  }
  const datasetId =
    nonEmpty(flags["dataset-id"] as string | undefined) ??
    nonEmpty(process.env.BRIGHTDATA_DATASET_ID) ??
    BRIGHT_DATA_DEFAULT_DATASET_ID;

  const limit = flags.full ? FULL_LIMIT : DEFAULT_LIMIT;
  const records = await scrapeBrightData(apiKey, datasetId, urls, limit, fetchImpl);

  return {
    provider: "brightdata",
    datasetId,
    results: records.map((record) => summarizeRecord(record, limit, Boolean(flags.full))),
  };
}

export async function runScrape(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SCRAPE_FLAGS, "scrape");
  const provider = parseProvider(flags.provider);

  if (provider === "brightdata") {
    return runBrightDataScrape(positionals, flags, fetchImpl);
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

  const apiKey = process.env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerpAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
  }

  const response = await scrapeSerper(apiKey, url.toString(), fetchImpl);
  const limit = flags.full ? FULL_LIMIT : DEFAULT_LIMIT;
  const info = truncate(response.text, limit);

  const output: AxiOutput = { url: url.toString() };
  if (response.metadata.title) {
    output.title = response.metadata.title;
  }
  output.text = info.text;
  if (info.truncated) {
    output.truncatedFrom = info.totalChars;
    output.help = flags.full
      ? `content is capped at ${FULL_LIMIT} characters even with --full`
      : `Run \`serp-axi scrape ${url.toString()} --full\` to see up to ${FULL_LIMIT} characters (${info.totalChars} total)`;
  }
  return output;
}

export const scrapeCommand: CliCommand = {
  name: "scrape",
  help: SCRAPE_HELP,
  run: (args) => runScrape(args),
};
