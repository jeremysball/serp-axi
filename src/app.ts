import os from "node:os";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { RunCliOptions } from "./cli.ts";
import { searchCommand } from "./commands/search.ts";
import { scrapeCommand } from "./commands/scrape.ts";
import { updateCommand } from "./commands/update.ts";

// Read from package.json at runtime rather than hardcoding, so release-please's
// version bumps (which only touch package.json) don't silently drift from what
// `serp-axi --version` reports. This file lives one directory below the repo
// root both as src/app.ts and as the compiled dist/app.js, so the relative
// path to package.json is the same either way.
const packageJsonPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8")) as { version: string };
export const VERSION = packageJson.version;

export function createAppOptions(
  execUrl: string,
  overrides: { homeDir?: string } = {},
): Omit<RunCliOptions, "stdout"> {
  return {
    description:
      "THIS IS GOOGLE. Runs real Google Search via Serper (google.serper.dev) or " +
      "Bright Data (api.brightdata.com) — live search results (title/link/snippet) " +
      "— plus page-scrape text extraction via Serper.",
    version: VERSION,
    execPath: fileURLToPath(execUrl),
    homeDir: overrides.homeDir ?? os.homedir(),
    commands: [searchCommand, scrapeCommand, updateCommand],
  };
}
