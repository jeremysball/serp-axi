### Task 5: CLI dispatcher and flag parser

**Files:**
- Create: `src/cli.ts`
- Test: `src/cli.test.ts`

**Interfaces:**
- Consumes: `SerperAxiError`, `exitCodeForError` from `./errors.js`; `encodeOutput`, `collapseHomeDirectory`, `AxiOutput` from
  `./output.js`.
- Produces: `FlagType = "string" | "boolean"`; `FlagSpec = Record<string, FlagType>`; `ParsedFlags { positionals: string[]; flags:
  Record<string, string | boolean>; helpRequested: boolean }`; `parseFlags(args: string[], spec: FlagSpec, commandName: string):
  ParsedFlags` (throws `SerperAxiError` with `kind: "usage"` on an unknown flag or a missing value); `CliCommand { name: string; help:
  string; run: (args: string[]) => Promise<AxiOutput | string> | AxiOutput | string }`; `RunCliOptions { description: string; version:
  string; execPath: string; homeDir: string; commands: CliCommand[]; stdout: { write: (chunk: string) => unknown } }`; `runCli(argv:
  string[], options: RunCliOptions): Promise<number>`.

- [ ] **Step 1: Write the failing tests**

```typescript
// src/cli.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { decode } from "@toon-format/toon";
import { parseFlags, runCli, type CliCommand, type RunCliOptions } from "./cli.js";
import { SerperAxiError } from "./errors.js";

function fakeStdout() {
  let buffer = "";
  return {
    write: (chunk: string) => {
      buffer += chunk;
      return true;
    },
    get output() {
      return buffer;
    },
  };
}

function baseOptions(commands: CliCommand[]): Omit<RunCliOptions, "stdout"> {
  return {
    description: "test tool",
    version: "0.0.1",
    execPath: "/home/user/.local/bin/serper-axi",
    homeDir: "/home/user",
    commands,
  };
}

test("parseFlags collects positionals and string flags", () => {
  const parsed = parseFlags(["query words", "--region", "uk"], { region: "string" }, "search");
  assert.deepEqual(parsed.positionals, ["query words"]);
  assert.equal(parsed.flags.region, "uk");
  assert.equal(parsed.helpRequested, false);
});

test("parseFlags rejects an unknown flag with a usage error", () => {
  assert.throws(
    () => parseFlags(["--stat", "closed"], { state: "string" }, "list"),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /unknown flag --stat/);
      assert.match(error.help, /--state/);
      return true;
    },
  );
});

test("parseFlags rejects a value-flag with a missing value", () => {
  assert.throws(
    () => parseFlags(["--region"], { region: "string" }, "search"),
    (error: unknown) => {
      assert.ok(error instanceof SerperAxiError);
      assert.equal(error.kind, "usage");
      return true;
    },
  );
});

test("runCli with no args renders the home view", async () => {
  const stdout = fakeStdout();
  const code = await runCli([], { ...baseOptions([]), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.bin, "~/.local/bin/serper-axi");
  assert.equal(decoded.description, "test tool");
});

test("runCli rejects an unknown command with exit 2", async () => {
  const stdout = fakeStdout();
  const code = await runCli(["bogus"], { ...baseOptions([]), stdout });
  assert.equal(code, 2);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.match(decoded.error as string, /unknown command `bogus`/);
});

test("runCli dispatches to a matching command and renders its output", async () => {
  const command: CliCommand = {
    name: "echo",
    help: "echo help text",
    run: (args) => ({ heard: args.join(" ") }),
  };
  const stdout = fakeStdout();
  const code = await runCli(["echo", "hi", "there"], { ...baseOptions([command]), stdout });
  assert.equal(code, 0);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.heard, "hi there");
});

test("runCli surfaces a SerperAxiError as a structured error with the right exit code", async () => {
  const command: CliCommand = {
    name: "boom",
    help: "boom help text",
    run: () => {
      throw new SerperAxiError("something is unset", "runtime", "set the thing");
    },
  };
  const stdout = fakeStdout();
  const code = await runCli(["boom"], { ...baseOptions([command]), stdout });
  assert.equal(code, 1);
  const decoded = decode(stdout.output) as Record<string, unknown>;
  assert.equal(decoded.error, "something is unset");
  assert.equal(decoded.help, "set the thing");
});

test("runCli prints a command's help text on --help without dispatching", async () => {
  let ran = false;
  const command: CliCommand = {
    name: "echo",
    help: "echo help text",
    run: () => {
      ran = true;
      return {};
    },
  };
  const stdout = fakeStdout();
  const code = await runCli(["echo", "--help"], { ...baseOptions([command]), stdout });
  assert.equal(code, 0);
  assert.equal(ran, false);
  assert.match(stdout.output, /echo help text/);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/cli.test.ts`
Expected: FAIL — `Cannot find module './cli.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/cli.ts
import { SerperAxiError, exitCodeForError } from "./errors.js";
import { encodeOutput, collapseHomeDirectory, type AxiOutput } from "./output.js";

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
      if (!(name in spec)) {
        throw new SerperAxiError(
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
        throw new SerperAxiError(`--${name} requires a value`, "usage", `example: --${name} <value>`);
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
    help: options.commands.map((c) => `Run \`serper-axi ${c.name} --help\` for details`),
  };
}

function renderTopLevelHelp(options: RunCliOptions): string {
  const lines = [
    options.description,
    "",
    "Commands:",
    ...options.commands.map((c) => `  ${c.name}`),
    "",
    "Run `serper-axi <command> --help` for a command's flags.",
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
    const message = error instanceof SerperAxiError ? error.message : (error as Error).message;
    const help = error instanceof SerperAxiError ? error.help : undefined;
    const output: AxiOutput = { error: message };
    if (help) output.help = help;
    options.stdout.write(encodeOutput(output));
    return exitCodeForError(error);
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/cli.test.ts`
Expected: PASS, 8/8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/cli.ts src/cli.test.ts
git commit -m "feat: add CLI dispatcher, flag parser, home view, and help rendering"
```

---

