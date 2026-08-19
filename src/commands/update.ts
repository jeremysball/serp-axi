import { parseFlags, type CliCommand } from "../cli.ts";
import { SerpAxiError } from "../errors.ts";
import type { AxiOutput } from "../output.ts";

const UPDATE_HELP = `serp-axi update

Report the local install's upgrade path. serp-axi does not check the npm
registry itself; this just prints the command to pull the latest version.

Examples:
  serp-axi update`;

export function runUpdate(args: string[]): AxiOutput {
  const { positionals } = parseFlags(args, {}, "update");
  if (positionals.length > 0) {
    const extras = positionals.map((p) => `"${p}"`).join(", ");
    throw new SerpAxiError(
      `unexpected argument${positionals.length > 1 ? "s" : ""} ${extras} for \`update\``,
      "usage",
      "usage: serp-axi update",
    );
  }
  return {
    status: "no live version check; run the upgrade command below",
    upgrade: "npm install -g serp-axi@latest",
  };
}

export const updateCommand: CliCommand = {
  name: "update",
  help: UPDATE_HELP,
  run: (args) => runUpdate(args),
};
