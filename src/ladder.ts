import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { StoredConfig } from "./config.ts";
import { SerpAxiError } from "./errors.ts";

export type LadderVerdict = "ok" | "dead" | "blocked";

export interface LadderResponse {
  verdict: LadderVerdict;
  rungReached: number;
  title: string;
  text: string;
  engines: string[];
  elapsedMs: number;
  warning: string | null;
}

export const LADDER_PROTOCOL = 1;

export type LadderTabState = "fresh" | "same";
export type LadderCookieState = "cold" | "jar";
export type LadderCacheState = "cold" | "warm";
export type LadderFingerprintState = "rotate" | "stable";
export type LadderRungCeiling = 1 | 2 | 3 | 4 | 5;

export interface LadderAxes {
  tabState: LadderTabState;
  cookieState: LadderCookieState;
  cacheState: LadderCacheState;
  fingerprintState: LadderFingerprintState;
  rungCeiling: LadderRungCeiling;
  profile: string | null;
  jarIn: string | null;
  jarOut: string | null;
}

export interface LadderRequest extends LadderAxes {
  protocol: typeof LADDER_PROTOCOL;
  url: string;
}

export interface LadderAxisSources {
  flag?: Record<string, string | boolean>;
  env?: NodeJS.ProcessEnv;
  config?: StoredConfig;
}

export interface LadderClientOptions {
  bin: string;
  args?: string[];
  timeoutMs?: number;
  idleMs?: number;
}

export class SerpAxiLadderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SerpAxiLadderError";
  }
}

const DEFAULT_TIMEOUT_MS = 120000;
const DEFAULT_IDLE_MS = 30000;

const LADDER_AXIS_DEFAULTS: LadderAxes = {
  tabState: "fresh",
  cookieState: "cold",
  cacheState: "cold",
  fingerprintState: "rotate",
  rungCeiling: 5,
  profile: null,
  jarIn: null,
  jarOut: null,
};

// Each axis reads flag, then env, then config, then its default. The flag and
// env names are derived from one table so a new axis cannot drift apart across
// the three spellings.
const AXIS_TABLE = {
  tabState: { flag: "tab-state", env: "SERP_AXI_TAB_STATE", config: "ladderTabState" },
  cookieState: { flag: "cookie-state", env: "SERP_AXI_COOKIE_STATE", config: "ladderCookieState" },
  cacheState: { flag: "cache-state", env: "SERP_AXI_CACHE_STATE", config: "ladderCacheState" },
  fingerprintState: { flag: "fingerprint-state", env: "SERP_AXI_FINGERPRINT_STATE", config: "ladderFingerprintState" },
  rungCeiling: { flag: "rung-ceiling", env: "SERP_AXI_RUNG_CEILING", config: "ladderRungCeiling" },
  profile: { flag: "profile", env: "SERP_AXI_PROFILE", config: "ladderProfile" },
  jarIn: { flag: "jar-in", env: "SERP_AXI_JAR_IN", config: "ladderJarIn" },
  jarOut: { flag: "jar-out", env: "SERP_AXI_JAR_OUT", config: "ladderJarOut" },
} as const;

type AxisKey = keyof typeof AXIS_TABLE;

const AXIS_ENUMS: Record<string, readonly string[]> = {
  tabState: ["fresh", "same"],
  cookieState: ["cold", "jar"],
  cacheState: ["cold", "warm"],
  fingerprintState: ["rotate", "stable"],
};

// Axis and config validation is a usage error: the caller can fix it by
// changing a flag, so it must reach the CLI as a SerpAxiError with a help
// line rather than as a runtime failure. Child and protocol problems stay
// SerpAxiLadderError and are wrapped as runtime errors by the command.
function usageError(message: string, help: string): SerpAxiError {
  return new SerpAxiError(message, "usage", help);
}

function readRaw(sources: LadderAxisSources, key: AxisKey): { value: string | undefined; origin: "flag" | "env" | null } {
  const entry = AXIS_TABLE[key];
  const flagValue = sources.flag?.[entry.flag];
  if (flagValue !== undefined && flagValue !== true && flagValue !== false) {
    return { value: String(flagValue), origin: "flag" };
  }
  const envValue = sources.env?.[entry.env];
  if (envValue !== undefined && envValue.length > 0) {
    return { value: envValue, origin: "env" };
  }
  return { value: undefined, origin: null };
}

function enumValue(key: AxisKey, raw: string, origin: string): string {
  const allowed = AXIS_ENUMS[key];
  if (allowed && !allowed.includes(raw)) {
    throw usageError(`invalid ${AXIS_TABLE[key].flag} "${raw}" from ${origin}`, `must be one of ${allowed.join(", ")}`);
  }
  return raw;
}

function ceilingValue(raw: string, origin: string): LadderRungCeiling {
  if (!/^[1-5]$/.test(raw)) {
    throw usageError(`invalid ${AXIS_TABLE.rungCeiling.flag} "${raw}" from ${origin}`, "must be an integer from 1 to 5");
  }
  return Number(raw) as LadderRungCeiling;
}

/**
 * Resolve the six axes plus jar paths, honoring flag > env > profile > config >
 * default. Profiles live in the config file as bundles of axis overrides, so the
 * request schema never grows a seventh axis.
 */
export function resolveLadderAxes(sources: LadderAxisSources = {}): LadderAxes {
  const profileRead = readRaw(sources, "profile");
  const profile = profileRead.value ?? null;

  let bundle: Record<string, unknown> = {};
  if (profile !== null) {
    const profiles = sources.config?.ladderProfiles;
    if (profiles !== undefined && (typeof profiles !== "object" || profiles === null)) {
      throw usageError("config ladderProfiles must be an object", "fix the config file");
    }
    const named = (profiles as Record<string, unknown> | undefined)?.[profile];
    if (named === undefined) {
      throw usageError(
        `unknown ladder profile "${profile}"`,
        "define it under ladderProfiles in the config file, or drop --profile",
      );
    }
    if (typeof named !== "object" || named === null || Array.isArray(named)) {
      throw usageError(`ladder profile "${profile}" must be an object`, "map axis names to values in the config file");
    }
    bundle = named as Record<string, unknown>;
  }

  const axes: LadderAxes = { ...LADDER_AXIS_DEFAULTS, profile };

  for (const key of ["tabState", "cookieState", "cacheState", "fingerprintState", "rungCeiling"] as const) {
    const { value, origin } = readRaw(sources, key);
    const bundled = bundle[key];
    const fromConfig = sources.config?.[AXIS_TABLE[key].config];
    const raw =
      value ??
      (typeof bundled === "string" ? bundled : undefined) ??
      (typeof fromConfig === "string" ? fromConfig : undefined);
    if (raw === undefined) continue;
    const source = origin ?? (typeof bundled === "string" ? `profile "${profile}"` : "config");
    axes[key] = (key === "rungCeiling" ? ceilingValue(raw, source) : enumValue(key, raw, source)) as never;
  }

  for (const key of ["jarIn", "jarOut"] as const) {
    const { value } = readRaw(sources, key);
    const bundled = bundle[key];
    const fromConfig = sources.config?.[AXIS_TABLE[key].config];
    const raw =
      value ??
      (typeof bundled === "string" ? bundled : undefined) ??
      (typeof fromConfig === "string" ? fromConfig : undefined);
    axes[key] = raw === undefined || raw.length === 0 ? null : raw;
  }

  // Sugar, not a new field: `--cookie-state jar` names "persist this jar both
  // ways" without a caller spelling out jar-in and jar-out separately. It never
  // invents a path, because a wrong path silently loses the clearance it exists
  // to keep, so it mirrors whichever path it was given and otherwise refuses.
  if (axes.cookieState === "jar" && axes.jarIn === null && axes.jarOut === null) {
    throw usageError(
      "--cookie-state jar needs a jar path",
      "pass --jar-out <path> (or --jar-in), which the sugar mirrors both ways",
    );
  }
  if (axes.jarIn === null) axes.jarIn = axes.jarOut;
  if (axes.jarOut === null) axes.jarOut = axes.jarIn;

  return axes;
}

export function buildLadderRequest(url: string, axes: LadderAxes): LadderRequest {
  return { protocol: LADDER_PROTOCOL, url, ...axes };
}

/**
 * SERP_AXI_LADDER_BIN always wins so dev and sandboxes can point anywhere.
 * Otherwise the first candidate that actually exists wins, and PATH is the
 * fallback. Candidates are checked for existence rather than assumed, so an
 * absent ladder-cli never hides a working PATH entry.
 *
 * `candidates` is a parameter so the precedence legs are testable without
 * rearranging the filesystem the tests run on.
 */
export function resolveLadderBin(
  env: NodeJS.ProcessEnv = process.env,
  candidates: string[] | null = defaultLadderBinCandidates(),
): string {
  const explicit = env.SERP_AXI_LADDER_BIN;
  if (explicit !== undefined && explicit.length > 0) return explicit;
  for (const candidate of candidates ?? []) {
    if (existsSync(candidate)) return candidate;
  }
  return "ladder-cli";
}

function defaultLadderBinCandidates(): string[] {
  try {
    const here = path.dirname(fileURLToPath(import.meta.url));
    // src/ in dev, dist/ when installed; both sit directly inside the package.
    const packageRoot = path.resolve(here, "..");
    return [
      // The repo checkout keeps the Python tree inside the package, and a
      // published package can too if ladder-cli ships with it.
      path.join(packageRoot, "ladder-cli", "ladder-cli"),
      // Otherwise a ladder-cli installed beside this package.
      path.resolve(packageRoot, "..", "ladder-cli"),
    ];
  } catch {
    return [];
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isVerdict(value: unknown): value is LadderVerdict {
  return value === "ok" || value === "dead" || value === "blocked";
}

function parseResponse(line: string): LadderResponse {
  let body: unknown;
  try {
    body = JSON.parse(line);
  } catch {
    throw new SerpAxiLadderError(`ladder-cli returned a malformed response line: ${line.slice(0, 120)}`);
  }
  if (!isRecord(body) || !isVerdict(body.verdict)) {
    throw new SerpAxiLadderError(`ladder-cli returned a malformed response line: ${line.slice(0, 120)}`);
  }
  const text = typeof body.text === "string" ? body.text : "";
  // An ok verdict with no text is not a small success, it is a schema
  // violation: accepting it would let a rung that silently failed report
  // success. Reporting it as an error is what keeps `blocked` vs `dead` vs
  // empty honest, per the verdict-honesty guide.
  if (body.verdict === "ok" && text.trim().length === 0) {
    throw new SerpAxiLadderError(
      `ladder-cli returned verdict "ok" with empty text: schema violation, not a success (line: ${line.slice(0, 120)})`,
    );
  }
  return {
    verdict: body.verdict,
    rungReached: typeof body.rungReached === "number" ? body.rungReached : 0,
    title: typeof body.title === "string" ? body.title : "",
    text,
    engines: Array.isArray(body.engines) ? body.engines.filter((e): e is string => typeof e === "string") : [],
    elapsedMs: typeof body.elapsedMs === "number" ? body.elapsedMs : 0,
    warning: typeof body.warning === "string" ? body.warning : null,
  };
}

interface Pending {
  request: LadderRequest;
  resolve: (response: LadderResponse) => void;
  reject: (error: Error) => void;
  timer?: NodeJS.Timeout;
}

export class LadderClient {
  private child: ChildProcess | null = null;
  private ready: Promise<void> | null = null;
  private readyResolve: () => void = () => {};
  private readyReject: (error: Error) => void = () => {};
  private readySettled = false;
  private buffer = "";
  private stderrTail = "";
  private queue: Pending[] = [];
  private inFlight: Pending | null = null;
  private idleTimer: NodeJS.Timeout | null = null;
  private closed = false;
  private exitPromise: Promise<number | null> | null = null;
  private didExit = false;
  private spawns = 0;

  private readonly options: LadderClientOptions;

  constructor(options: LadderClientOptions) {
    this.options = options;
  }

  get spawnCount(): number {
    return this.spawns;
  }

  get exited(): boolean {
    return this.didExit;
  }

  async fetch(url: string, axes?: LadderAxes): Promise<LadderResponse> {
    if (this.closed) {
      throw new SerpAxiLadderError("ladder client is closed");
    }
    const request = buildLadderRequest(url, axes ?? resolveLadderAxes({}));
    this.ensureSpawned();
    return new Promise<LadderResponse>((resolve, reject) => {
      // No timer here: the timeout covers the upstream call and arms at
      // dispatch, so queued requests never burn budget while waiting.
      this.queue.push({ request, resolve, reject });
      void this.dispatch();
    });
  }

  private dropPending(pending: Pending, error: Error): void {
    clearTimeout(pending.timer);
    const index = this.queue.indexOf(pending);
    if (index >= 0) {
      this.queue.splice(index, 1);
      pending.reject(error);
      return;
    }
    if (this.inFlight === pending) {
      this.inFlight = null;
      pending.reject(error);
      // Fence the abandoned request: a late reply must never resolve a
      // different request, and responses carry no id, so reset the child.
      this.resetChild();
      this.armIdleTimer();
      void this.dispatch();
    }
  }

  private async dispatch(): Promise<void> {
    if (this.closed) return;
    this.ensureSpawned();
    try {
      await this.ready;
    } catch (error) {
      this.failAll(error instanceof Error ? error : new SerpAxiLadderError(String(error)));
      return;
    }
    if (this.closed || this.inFlight !== null || !this.child?.stdin) return;
    const pending = this.queue.shift();
    if (!pending) return;
    this.inFlight = pending;
    this.clearIdleTimer();
    const timeoutMs = this.options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    pending.timer = setTimeout(() => {
      this.dropPending(
        pending,
        new SerpAxiLadderError(`ladder-cli timed out after ${timeoutMs} ms for ${pending.request.url}`),
      );
    }, timeoutMs);
    try {
      this.child?.stdin?.write(`${JSON.stringify(pending.request)}\n`);
    } catch (error) {
      this.inFlight = null;
      clearTimeout(pending.timer);
      pending.reject(error instanceof Error ? error : new SerpAxiLadderError(String(error)));
      this.armIdleTimer();
      void this.dispatch();
    }
  }

  private resetChild(): void {
    const child = this.child;
    this.child = null;
    this.buffer = "";
    this.stderrTail = "";
    this.ready = null;
    this.readySettled = false;
    this.didExit = false;
    if (child && child.exitCode === null) {
      child.kill();
    }
  }

  private failAll(error: Error): void {
    for (const pending of this.queue.splice(0)) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    if (this.inFlight) {
      const current = this.inFlight;
      this.inFlight = null;
      clearTimeout(current.timer);
      current.reject(error);
    }
  }

  private settleReady(error?: Error): void {
    if (this.readySettled) return;
    this.readySettled = true;
    if (error) {
      this.readyReject(error);
      this.failAll(error);
    } else {
      this.readyResolve();
    }
  }

  private ensureSpawned(): void {
    if (this.child) return;
    this.spawns += 1;
    const child = spawn(this.options.bin, this.options.args ?? [], { stdio: ["pipe", "pipe", "pipe"] });
    this.child = child;
    this.ready = new Promise<void>((resolve, reject) => {
      this.readyResolve = resolve;
      this.readyReject = reject;
    });

    this.exitPromise = new Promise<number | null>((resolve) => {
      child.on("exit", (code) => {
        resolve(code);
        if (child !== this.child) {
          // Stale: killed by resetChild, or by close() which already nulled
          // the handle. Only close() cares about the exit flag.
          if (this.closed) this.didExit = true;
          return;
        }
        this.didExit = true;
        if (!this.readySettled) {
          const tail = this.stderrTail.trim().split("\n").slice(-5).join("\n");
          this.settleReady(
            new SerpAxiLadderError(
              `ladder-cli exited before ready (code ${code ?? "null"})${tail ? `: ${tail}` : ""}`,
            ),
          );
        } else if (this.inFlight) {
          const current = this.inFlight;
          this.inFlight = null;
          clearTimeout(current.timer);
          current.reject(new SerpAxiLadderError(`ladder-cli exited mid-request (code ${code ?? "null"})`));
        }
        if (this.closed) {
          this.child = null;
        } else {
          // Unexpected exit: queued requests must not hang on a dead child,
          // and later fetches must respawn instead of writing dead stdin.
          this.failAll(new SerpAxiLadderError(`ladder-cli exited unexpectedly (code ${code ?? "null"})`));
          this.resetChild();
        }
      });
    });

    child.on("error", (error: NodeJS.ErrnoException) => {
      const message =
        error.code === "ENOENT"
          ? `ladder binary not found: ${this.options.bin}`
          : `ladder-cli failed to spawn: ${error.message}`;
      this.settleReady(new SerpAxiLadderError(message));
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      this.stderrTail += chunk.toString();
      if (this.stderrTail.length > 2000) this.stderrTail = this.stderrTail.slice(-2000);
    });

    child.stdout?.on("data", (chunk: Buffer) => {
      this.buffer += chunk.toString();
      this.drainLines();
    });
  }

  private drainLines(): void {
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      if (!this.readySettled) {
        let hello: unknown;
        try {
          hello = JSON.parse(line);
        } catch {
          hello = null;
        }
        if (!isRecord(hello) || hello.ready !== true) {
          this.settleReady(new SerpAxiLadderError(`ladder-cli sent an invalid ready line: ${line.slice(0, 120)}`));
        } else if (hello.protocol !== LADDER_PROTOCOL) {
          // Fail at the handshake, not at the first garbled request: a stale
          // installed ladder-cli must name both protocol numbers instead of
          // silently misparsing everything after this point.
          this.settleReady(
            new SerpAxiLadderError(
              `ladder-cli protocol mismatch: serp-axi speaks protocol ${LADDER_PROTOCOL}, ` +
                `ladder-cli reported protocol ${JSON.stringify(hello.protocol ?? null)} on its ready line`,
            ),
          );
        } else {
          this.settleReady();
        }
      } else if (line.length > 0) {
        const current = this.inFlight;
        this.inFlight = null;
        if (current) {
          clearTimeout(current.timer);
          try {
            current.resolve(parseResponse(line));
          } catch (error) {
            current.reject(error instanceof Error ? error : new SerpAxiLadderError(String(error)));
          }
        }
        this.armIdleTimer();
        void this.dispatch();
      }
      newline = this.buffer.indexOf("\n");
    }
  }

  private clearIdleTimer(): void {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  private armIdleTimer(): void {
    this.clearIdleTimer();
    if (this.closed || this.queue.length > 0 || this.inFlight !== null) return;
    const idleMs = this.options.idleMs ?? DEFAULT_IDLE_MS;
    this.idleTimer = setTimeout(() => {
      void this.close();
    }, idleMs);
    this.idleTimer.unref?.();
  }

  async close(): Promise<void> {
    this.closed = true;
    this.clearIdleTimer();
    this.failAll(new SerpAxiLadderError("ladder client is closed"));
    const child = this.child;
    this.child = null;
    if (child && child.exitCode === null) {
      child.kill();
    }
  }

  async waitForExit(timeoutMs: number): Promise<void> {
    const exit = this.exitPromise;
    if (!exit) return;
    await Promise.race([
      exit,
      new Promise((_resolve, reject) =>
        setTimeout(() => reject(new Error("timed out waiting for exit")), timeoutMs),
      ),
    ]);
  }
}

export async function fetchViaLadder(
  url: string,
  options: LadderClientOptions,
  axes: LadderAxes = resolveLadderAxes({}),
): Promise<LadderResponse> {
  const client = new LadderClient(options);
  try {
    return await client.fetch(url, axes);
  } finally {
    await client.close();
  }
}
