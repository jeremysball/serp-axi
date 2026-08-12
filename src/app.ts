import os from "node:os";
import { fileURLToPath } from "node:url";
import type { RunCliOptions } from "./cli.ts";
import { searchCommand } from "./commands/search.ts";
import { scrapeCommand } from "./commands/scrape.ts";
import { updateCommand } from "./commands/update.ts";

export const VERSION = "0.1.0";

export function createAppOptions(
  execUrl: string,
  overrides: { homeDir?: string } = {},
): Omit<RunCliOptions, "stdout"> {
  return {
    description:
      "THIS IS GOOGLE. Runs real Google Search via Serper (google.serper.dev) — " +
      "live search results (title/link/snippet) and page-scrape text extraction.",
    version: VERSION,
    execPath: fileURLToPath(execUrl),
    homeDir: overrides.homeDir ?? os.homedir(),
    commands: [searchCommand, scrapeCommand, updateCommand],
  };
}
