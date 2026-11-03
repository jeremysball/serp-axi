import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * The recorded provider responses under `src/fixtures/`, loaded once here so no
 * test names the directory, decodes the file, or splits its lines for itself.
 * Test-only: nothing outside a `*.test.ts` file imports it, as with `live.ts`.
 *
 * Every loader reads when it is called, not when the module loads, and a missing
 * file throws the filesystem's own error. A test never runs against an empty
 * fixture because a path moved.
 */

const FIXTURE_DIR = new URL("./fixtures/", import.meta.url);

export function readFixture(name: string): string {
  return readFileSync(fileURLToPath(new URL(name, FIXTURE_DIR)), "utf8");
}

/** Kagi's HTML search page, recorded from a real session. */
export function kagiSearchHtml(): string {
  return readFixture("kagi-html-search.html");
}

/** Bright Data's dataset scrape reply as recorded: one JSON record per line. */
export function brightDataScrapeNdjson(): string {
  return readFixture("brightdata-scrape.ndjson");
}

/** The first record of the Bright Data scrape fixture, parsed. */
export function brightDataScrapeRecord(): Record<string, unknown> {
  const [first] = brightDataScrapeNdjson()
    .split("\n")
    .filter((line) => line.trim().length > 0);
  if (first === undefined) throw new Error("fixtures/brightdata-scrape.ndjson has no records");
  return JSON.parse(first) as Record<string, unknown>;
}
