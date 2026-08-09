import { test } from "node:test";
import assert from "node:assert/strict";
import { decode } from "@toon-format/toon";
import { parseFlags, runCli, type CliCommand, type RunCliOptions } from "./cli.ts";
import { SerperAxiError } from "./errors.ts";

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
