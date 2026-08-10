#!/usr/bin/env node
// src/bin/serper-axi.ts
import { runCli } from "../cli.ts";
import { createAppOptions } from "../app.ts";

const exitCode = await runCli(process.argv.slice(2), {
  ...createAppOptions(import.meta.url),
  stdout: process.stdout,
});

process.exit(exitCode);
