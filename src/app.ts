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
//
// A static `import pkg from "../package.json" with { type: "json" }` would
// read this same way, but it isn't catchable: a missing or corrupt
// package.json would throw at module-load time and take down the whole CLI
// (including commands that never touch VERSION) instead of just degrading
// `--version`. readFileSync + a try/catch keeps that failure local.
const packageJsonPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "package.json");

function readVersion(): string {
  try {
    const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8")) as { version: string };
    return packageJson.version;
  } catch {
    return "0.0.0-unknown";
  }
}

export const VERSION = readVersion();

export function createAppOptions(
  execUrl: string,
  overrides: { homeDir?: string } = {},
): Omit<RunCliOptions, "stdout"> {
  return {
    description:
      "THIS IS GOOGLE. Runs real Google Search via Serper (google.serper.dev) or " +
      "Bright Data (api.brightdata.com) — live search results (title/link/snippet) " +
      "— plus page-scrape text extraction via Serper or Bright Data.",
    version: VERSION,
    execPath: fileURLToPath(execUrl),
    homeDir: overrides.homeDir ?? os.homedir(),
    commands: [searchCommand, scrapeCommand, updateCommand],
  };
}
