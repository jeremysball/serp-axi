import type { CliCommand } from "../cli.ts";
import type { AxiOutput } from "../output.ts";

const UPDATE_HELP = `serper-axi update

Report the local install's upgrade path. serper-axi is not published to the
npm registry, so there is no version to check remotely.

Examples:
  serper-axi update`;

export function runUpdate(): AxiOutput {
  return {
    status: "local install; no registry to check",
    upgrade: "git pull && npm run build && npm install -g .",
  };
}

export const updateCommand: CliCommand = {
  name: "update",
  help: UPDATE_HELP,
  run: () => runUpdate(),
};
