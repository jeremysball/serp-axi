import { readFileSync } from "node:fs";
import path from "node:path";
import { SerpAxiError } from "./errors.ts";

export interface StoredConfig {
  searxngUrl?: unknown;
  searxngEngines?: unknown;
  searchTimeoutMs?: unknown;
}

export function configFilePath(homeDir: string, env: NodeJS.ProcessEnv = process.env): string {
  const base = env.XDG_CONFIG_HOME && env.XDG_CONFIG_HOME.length > 0 ? env.XDG_CONFIG_HOME : path.join(homeDir, ".config");
  return path.join(base, "serp-axi", "config.json");
}

export function loadStoredConfig(homeDir: string, env: NodeJS.ProcessEnv = process.env): StoredConfig {
  const file = configFilePath(homeDir, env);
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw new SerpAxiError(
      `config file ${file} is not readable`,
      "usage",
      "fix its permissions, or remove it to fall back to defaults",
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new SerpAxiError(
      `config file ${file} is not valid JSON`,
      "usage",
      "fix the JSON, or remove the file to use defaults",
    );
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new SerpAxiError(
      `config file ${file} must contain a JSON object`,
      "usage",
      "fix the file, or remove it to use defaults",
    );
  }
  return parsed as StoredConfig;
}
