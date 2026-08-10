import { parseFlags, type CliCommand, type FlagSpec } from "../cli.ts";
import { SerperAxiError } from "../errors.ts";
import { truncate, type AxiOutput } from "../output.ts";
import { scrapeSerper } from "../serper.ts";

const SCRAPE_FLAGS: FlagSpec = {
  full: "boolean",
};

const DEFAULT_LIMIT = 1200;
const FULL_LIMIT = 50000;

const SCRAPE_HELP = `serper-axi scrape <url> [--full]

Fetch and extract readable text from a web page via Serper.

Flags:
  --full   Return up to 50,000 characters instead of the default 1,200.

Examples:
  serper-axi scrape https://example.com/article
  serper-axi scrape https://example.com/article --full`;

const PRIVATE_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);

function validateUrl(raw: string): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SerperAxiError(`"${raw}" is not a valid URL`, "usage", "example: serper-axi scrape https://example.com/article");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SerperAxiError(
      `scrape only accepts http/https URLs, got "${url.protocol}"`,
      "usage",
      "example: serper-axi scrape https://example.com/article",
    );
  }
  const hostname = url.hostname.toLowerCase();
  if (
    PRIVATE_HOSTS.has(hostname) ||
    hostname.startsWith("10.") ||
    hostname.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname)
  ) {
    throw new SerperAxiError(
      `"${hostname}" is a loopback or private-range host`,
      "usage",
      "scrape only accepts publicly reachable URLs",
    );
  }
  return url;
}

export async function runScrape(args: string[], fetchImpl: typeof fetch = fetch): Promise<AxiOutput> {
  const { positionals, flags } = parseFlags(args, SCRAPE_FLAGS, "scrape");

  const raw = positionals[0];
  if (!raw) {
    throw new SerperAxiError("scrape requires a URL", "usage", "example: serper-axi scrape https://example.com/article");
  }
  const url = validateUrl(raw);

  const apiKey = process.env.SERPER_API_KEY;
  if (!apiKey) {
    throw new SerperAxiError("SERPER_API_KEY is not set", "runtime", "export SERPER_API_KEY=<your key> and re-run");
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
      : `Run \`serper-axi scrape ${url.toString()} --full\` to see up to ${FULL_LIMIT} characters (${info.totalChars} total)`;
  }
  return output;
}

export const scrapeCommand: CliCommand = {
  name: "scrape",
  help: SCRAPE_HELP,
  run: (args) => runScrape(args),
};
