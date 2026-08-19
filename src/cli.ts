import { SerpAxiError, exitCodeForError } from "./errors.ts";
import { encodeOutput, collapseHomeDirectory, type AxiOutput } from "./output.ts";

export type FlagType = "string" | "boolean";
export type FlagSpec = Record<string, FlagType>;

export interface ParsedFlags {
  positionals: string[];
  flags: Record<string, string | boolean>;
  helpRequested: boolean;
}

export function parseFlags(args: string[], spec: FlagSpec, commandName: string): ParsedFlags {
  const positionals: string[] = [];
  const flags: Record<string, string | boolean> = {};
  let helpRequested = false;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") {
      helpRequested = true;
      continue;
    }
    if (arg.startsWith("--")) {
      const name = arg.slice(2);
      if (!Object.hasOwn(spec, name)) {
        throw new SerpAxiError(
          `unknown flag --${name} for \`${commandName}\``,
          "usage",
          `valid flags for \`${commandName}\`: ${Object.keys(spec)
            .map((f) => `--${f}`)
            .join(", ")} (--help always allowed)`,
        );
      }
      if (spec[name] === "boolean") {
        flags[name] = true;
        continue;
      }
      const value = args[i + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new SerpAxiError(`--${name} requires a value`, "usage", `example: --${name} <value>`);
      }
      flags[name] = value;
      i++;
      continue;
    }
    positionals.push(arg);
  }

  return { positionals, flags, helpRequested };
}

export interface CliCommand {
  name: string;
  help: string;
  run: (args: string[]) => Promise<AxiOutput | string> | AxiOutput | string;
}

export interface RunCliOptions {
  description: string;
  version: string;
  execPath: string;
  homeDir: string;
  commands: CliCommand[];
  stdout: { write: (chunk: string) => unknown };
}

function homeHeader(options: RunCliOptions): AxiOutput {
  return {
    bin: collapseHomeDirectory(options.execPath, options.homeDir),
    description: options.description,
  };
}

function renderHome(options: RunCliOptions): AxiOutput {
  return {
    ...homeHeader(options),
    commands: options.commands.map((c) => c.name),
    help: options.commands.map((c) => `Run \`serp-axi ${c.name} --help\` for details`),
  };
}

function renderTopLevelHelp(options: RunCliOptions): string {
  const lines = [
    options.description,
    "",
    "Commands:",
    ...options.commands.map((c) => `  ${c.name}`),
    "",
    "Run `serp-axi <command> --help` for a command's flags.",
  ];
  return `${lines.join("\n")}\n`;
}

export async function runCli(argv: string[], options: RunCliOptions): Promise<number> {
  if (argv.length === 0) {
    options.stdout.write(encodeOutput(renderHome(options)));
    return 0;
  }

  if (argv[0] === "--help" || argv[0] === "-h") {
    options.stdout.write(renderTopLevelHelp(options));
    return 0;
  }

  if (argv[0] === "--version" || argv[0] === "-v") {
    options.stdout.write(`${options.version}\n`);
    return 0;
  }

  const [commandName, ...rest] = argv;
  const command = options.commands.find((c) => c.name === commandName);

  if (!command) {
    const output: AxiOutput = {
      error: `unknown command \`${commandName}\``,
      help: `valid commands: ${options.commands.map((c) => c.name).join(", ")}`,
    };
    options.stdout.write(encodeOutput(output));
    return 2;
  }

  if (rest.includes("--help") || rest.includes("-h")) {
    options.stdout.write(command.help.endsWith("\n") ? command.help : `${command.help}\n`);
    return 0;
  }

  try {
    const result = await command.run(rest);
    options.stdout.write(typeof result === "string" ? result : encodeOutput(result));
    return 0;
  } catch (error) {
    if (error instanceof SerpAxiError) {
      const output: AxiOutput = { error: error.message };
      if (error.help) output.help = error.help;
      options.stdout.write(encodeOutput(output));
      return exitCodeForError(error);
    }
    const detail = error instanceof Error ? error.message : String(error);
    process.stderr.write(`unexpected error: ${detail}\n`);
    options.stdout.write(encodeOutput({ error: "unexpected error", help: "see stderr for details" }));
    return exitCodeForError(error);
  }
}
