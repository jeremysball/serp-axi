import { parseFlags, type CliCommand } from "../cli.ts";
import { SerperAxiError } from "../errors.ts";
import type { AxiOutput } from "../output.ts";

const UPDATE_HELP = `serper-axi update

Report the local install's upgrade path. serper-axi is not published to the
npm registry, so there is no version to check remotely.

Examples:
  serper-axi update`;

export function runUpdate(args: string[]): AxiOutput {
  const { positionals } = parseFlags(args, {}, "update");
  if (positionals.length > 0) {
    const extras = positionals.map((p) => `"${p}"`).join(", ");
    throw new SerperAxiError(
      `unexpected argument${positionals.length > 1 ? "s" : ""} ${extras} for \`update\``,
      "usage",
      "usage: serper-axi update",
    );
  }
  return {
    status: "local install; no registry to check",
    upgrade: "git pull && npm run build && npm install -g .",
  };
}

export const updateCommand: CliCommand = {
  name: "update",
  help: UPDATE_HELP,
  run: (args) => runUpdate(args),
};
