import { spawn, type ChildProcess } from "node:child_process";
import { statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { StoredConfig } from "./config.ts";
import { boundedDetail, SerpAxiError } from "./errors.ts";

export type LadderVerdict = "ok" | "dead" | "blocked" | "error";

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
  /**
   * How long the child gets to print its ready line. A child that spawns but
   * never says hello is a hang, not a slow start, so it must fail on a budget
   * rather than holding every later fetch open.
   */
  handshakeMs?: number;
}

export class SerpAxiLadderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SerpAxiLadderError";
  }
}

// Two budgets, deliberately nested rather than competing. The handshake budget
// covers one thing: the child printing its ready line, which is a few hundred
// milliseconds of interpreter start. The request budget covers a rung, whose
// ceiling is DEFAULT_RUNG_TIMEOUT_MS plus interpreter and transport overhead.
// Nothing reads a timeout out of the environment: a knob that only one side
// knows about cannot be reasoned about from the other, and the values below
// are the ones both halves were measured against.
const DEFAULT_TIMEOUT_MS = 120000;
const DEFAULT_HANDSHAKE_MS = 30000;
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
// the three spellings. The config leg is the same shape as the other two, which
// is what makes `ladderProfile` in StoredConfig mean something.
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

/**
 * Every flag the ladder understands, derived from the same table as the env and
 * config names. Commands use this rather than keeping their own list, so an
 * axis cannot exist on the wire while being unknown to the CLI.
 */
export const LADDER_AXIS_FLAG_NAMES: readonly string[] = Object.values(AXIS_TABLE).map((entry) => entry.flag);

const AXIS_ENUMS: Record<string, readonly string[]> = {
  tabState: ["fresh", "same"],
  cookieState: ["cold", "jar"],
  cacheState: ["cold", "warm"],
  fingerprintState: ["rotate", "stable"],
};

const VALUE_KEYS = ["tabState", "cookieState", "cacheState", "fingerprintState", "rungCeiling"] as const;
const JAR_KEYS = ["jarIn", "jarOut"] as const;

// Axis and config validation is a usage error: the caller can fix it by
// changing a flag, so it must reach the CLI as a SerpAxiError with a help
// line rather than as a runtime failure. Child and protocol problems stay
// SerpAxiLadderError and are wrapped as runtime errors by the command.
function usageError(message: string, help: string): SerpAxiError {
  return new SerpAxiError(message, "usage", help);
}

// Named, so an error says which spelling the caller wrote. searxng.ts does the
// same for its endpoint; a flag, an env var, and a config key are three
// different places to look, and "from env" tells the caller none of them.
interface AxisSource {
  kind: "flag" | "env" | "config" | "profile";
  field: string;
}

function sourceLabel(source: AxisSource): string {
  if (source.kind === "flag") return `--${source.field}`;
  if (source.kind === "env") return source.field;
  if (source.kind === "profile") return `profile ${source.field}`;
  return `config ${source.field}`;
}

function readRaw(sources: LadderAxisSources, key: AxisKey): { value: string | undefined; source: AxisSource | null } {
  const entry = AXIS_TABLE[key];
  const flagValue = sources.flag?.[entry.flag];
  if (flagValue !== undefined && flagValue !== true && flagValue !== false) {
    return { value: String(flagValue), source: { kind: "flag", field: entry.flag } };
  }
  const envValue = sources.env?.[entry.env];
  if (envValue !== undefined && envValue.length > 0) {
    return { value: envValue, source: { kind: "env", field: entry.env } };
  }
  return { value: undefined, source: null };
}

/**
 * Read one lower-precedence layer of an axis. A value that is present but not a
 * string is an error, not a skip: a config that says `"ladderRungCeiling": 2`
 * would otherwise silently run rung 1 to 5, which is the opposite of what it
 * asks for and indistinguishable from a missing key. Null and absent both mean
 * "not set", because that is what they mean in JSON.
 */
function readMember(value: unknown, source: AxisSource): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") {
    throw usageError(
      `invalid ${sourceLabel(source)} ${JSON.stringify(value)}`,
      `${source.field} must be a string, or remove the key to fall back to the default`,
    );
  }
  return value;
}

function bundleMember(
  bundle: Record<string, unknown>,
  key: AxisKey,
  profile: string | null,
): { value: string | undefined; source: AxisSource } {
  const source: AxisSource = { kind: "profile", field: `"${profile}" ${key}` };
  return { value: key in bundle ? readMember(bundle[key], source) : undefined, source };
}

function readConfig(sources: LadderAxisSources, key: AxisKey): { value: string | undefined; source: AxisSource } {
  const field = AXIS_TABLE[key].config;
  const config = sources.config as Record<string, unknown> | undefined;
  return { value: readMember(config?.[field], { kind: "config", field }), source: { kind: "config", field } };
}

function enumValue(key: AxisKey, raw: string, source: AxisSource): string {
  const allowed = AXIS_ENUMS[key];
  if (allowed && !allowed.includes(raw)) {
    throw usageError(`invalid ${sourceLabel(source)} "${raw}"`, `must be one of ${allowed.join(", ")}`);
  }
  return raw;
}

function ceilingValue(raw: string, source: AxisSource): LadderRungCeiling {
  if (!/^[1-5]$/.test(raw)) {
    throw usageError(`invalid ${sourceLabel(source)} "${raw}"`, "must be an integer from 1 to 5");
  }
  return Number(raw) as LadderRungCeiling;
}

function profileBundle(sources: LadderAxisSources, profile: string): Record<string, unknown> {
  const profiles = sources.config?.ladderProfiles;
  if (profiles !== undefined && !isRecord(profiles)) {
    throw usageError("config ladderProfiles must be an object", "fix the config file");
  }
  const named = isRecord(profiles) ? profiles[profile] : undefined;
  if (named === undefined) {
    throw usageError(
      `unknown ladder profile "${profile}"`,
      "define it under ladderProfiles in the config file, or drop --profile",
    );
  }
  if (!isRecord(named)) {
    throw usageError(`ladder profile "${profile}" must be an object`, "map axis names to values in the config file");
  }
  // An unknown key in a bundle is a typo that would otherwise be read as
  // "leaves this axis at its default", which looks exactly like it worked.
  const unknown = Object.keys(named).filter((key) => !(key in AXIS_TABLE));
  if (unknown.length > 0) {
    throw usageError(
      `ladder profile "${profile}" sets unknown ${unknown.length === 1 ? "key" : "keys"}: ${unknown.join(", ")}`,
      `valid keys: ${Object.keys(AXIS_TABLE).join(", ")}`,
    );
  }
  return named;
}

/**
 * Resolve the six axes plus jar paths. Precedence, highest first: a flag, an
 * env var, the config file, a bundle named by `profile`, then the default. The
 * profile bundle sits below its own config file so a bundle is a named preset
 * rather than an override the user cannot see past.
 */
export function resolveLadderAxes(sources: LadderAxisSources = {}): LadderAxes {
  const flagOrEnvProfile = readRaw(sources, "profile");
  const configProfile = readConfig(sources, "profile");
  const profile = flagOrEnvProfile.value ?? configProfile.value ?? null;

  const bundle = profile === null ? {} : profileBundle(sources, profile);
  const axes: LadderAxes = { ...LADDER_AXIS_DEFAULTS, profile };

  // Flag, then the selected profile bundle, then the config file. Each layer
  // names where it came from, so an error points at the spelling the caller
  // actually wrote rather than saying "from env" and covering three places.
  const axisLayer = (key: AxisKey): { raw: string | undefined; source: AxisSource | null } => {
    const layers = [readRaw(sources, key), bundleMember(bundle, key, profile), readConfig(sources, key)];
    for (const layer of layers) {
      if (layer.value !== undefined) return { raw: layer.value, source: layer.source };
    }
    return { raw: undefined, source: null };
  };

  for (const key of VALUE_KEYS) {
    const { raw, source } = axisLayer(key);
    if (raw === undefined || source === null) continue;
    axes[key] = (key === "rungCeiling" ? ceilingValue(raw, source) : enumValue(key, raw, source)) as never;
  }

  for (const key of JAR_KEYS) {
    const { raw } = axisLayer(key);
    axes[key] = raw === undefined || raw.length === 0 ? null : raw;
  }

  // Sugar, not a new field: `--cookie-state jar` names "persist this jar both
  // ways" without a caller spelling out jar-in and jar-out separately. It never
  // invents a path, because a wrong path silently loses the clearance it exists
  // to keep, so it mirrors whichever path it was given and otherwise refuses.
  // Mirroring is scoped to the sugar it belongs to: a caller who asked for
  // `--cookie-state cold` and named one jar path expects a read, not a write.
  if (axes.cookieState === "jar") {
    if (axes.jarIn === null && axes.jarOut === null) {
      throw usageError(
        "--cookie-state jar needs a jar path",
        "pass --jar-out <path> (or --jar-in), which the sugar mirrors both ways",
      );
    }
    if (axes.jarIn === null) axes.jarIn = axes.jarOut;
    if (axes.jarOut === null) axes.jarOut = axes.jarIn;
  }

  return axes;
}

export function buildLadderRequest(url: string, axes: LadderAxes): LadderRequest {
  return { protocol: LADDER_PROTOCOL, url, ...axes };
}

/**
 * SERP_AXI_LADDER_BIN always wins so dev and sandboxes can point anywhere.
 * Otherwise the first candidate that is a regular file wins, and PATH is the
 * fallback. Existence is checked as a *file* rather than with existsSync: a
 * directory at a candidate path would otherwise be handed straight to spawn,
 * which fails with an errno that names neither the path nor the real problem.
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
    if (isRegularFile(candidate)) return candidate;
  }
  return "ladder-cli";
}

function isRegularFile(candidate: string): boolean {
  try {
    return statSync(candidate).isFile();
  } catch {
    return false;
  }
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
  return value === "ok" || value === "dead" || value === "blocked" || value === "error";
}

function parseResponse(line: string): LadderResponse {
  let body: unknown;
  try {
    body = JSON.parse(line);
  } catch {
    throw new SerpAxiLadderError(`ladder-cli returned a malformed response line: ${boundedDetail(line)}`);
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
      `ladder-cli returned verdict "ok" with empty text: schema violation, not a success (line: ${boundedDetail(line)})`,
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
  private handshakeTimer: NodeJS.Timeout | null = null;
  private buffer = "";
  private stderrTail = "";
  private queue: Pending[] = [];
  private inFlight: Pending | null = null;
  private idleTimer: NodeJS.Timeout | null = null;
  private closed = false;
  private exitPromise: Promise<number | null> | null = null;
  private didExit = false;
  private spawns = 0;
  // The current child's listeners, kept so resetChild and close can detach
  // them. A listener that outlives its child writes into `this.buffer`, which
  // is shared across children: a byte that arrives after the kill would land in
  // the *next* child's buffer and could pass for its ready line.
  private stdoutListener: ((chunk: Buffer) => void) | null = null;
  private stderrListener: ((chunk: Buffer) => void) | null = null;
  private stdinListener: ((error: Error) => void) | null = null;

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
    this.detachStreams(child);
    this.clearHandshakeTimer();
    this.buffer = "";
    this.stderrTail = "";
    this.ready = null;
    this.readySettled = false;
    this.didExit = false;
    if (child && child.exitCode === null) {
      child.kill();
    }
  }

  /**
   * Drop a child's stream listeners. Belt and braces: the listeners also test
   * `chunk owner === this.child` before touching shared state, so a byte in
   * flight when the kill lands is discarded twice over rather than being read
   * as the next child's handshake.
   */
  private detachStreams(child: ChildProcess | null): void {
    if (!child) return;
    if (this.stdoutListener) child.stdout?.off("data", this.stdoutListener);
    if (this.stderrListener) child.stderr?.off("data", this.stderrListener);
    if (this.stdinListener) child.stdin?.off("error", this.stdinListener);
    this.stdoutListener = null;
    this.stderrListener = null;
    this.stdinListener = null;
  }

  private clearHandshakeTimer(): void {
    if (this.handshakeTimer) {
      clearTimeout(this.handshakeTimer);
      this.handshakeTimer = null;
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
    this.clearHandshakeTimer();
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
        const tail = this.stderrTail.trim().split("\n").slice(-5).join("\n");
        if (!this.readySettled) {
          this.settleReady(
            new SerpAxiLadderError(
              `ladder-cli exited before ready (code ${code ?? "null"})${tail ? `: ${tail}` : ""}`,
            ),
          );
        } else if (this.inFlight) {
          const current = this.inFlight;
          this.inFlight = null;
          clearTimeout(current.timer);
          current.reject(
            new SerpAxiLadderError(`ladder-cli exited mid-request (code ${code ?? "null"})${tail ? `: ${tail}` : ""}`),
          );
        }
        if (this.closed) {
          this.child = null;
        } else {
          // Unexpected exit: queued requests must not hang on a dead child,
          // and later fetches must respawn instead of writing dead stdin.
          this.failAll(
            new SerpAxiLadderError(`ladder-cli exited unexpectedly (code ${code ?? "null"})${tail ? `: ${tail}` : ""}`),
          );
          this.resetChild();
        }
      });
    });

    child.on("error", (error: NodeJS.ErrnoException) => {
      const message =
        error.code === "ENOENT"
          ? `ladder binary not found: ${this.options.bin}`
          : `ladder-cli failed to spawn: ${error.message}`;
      this.clearHandshakeTimer();
      this.settleReady(new SerpAxiLadderError(message));
      // A spawn that failed leaves a live-looking handle, so without this the
      // client would hand every later fetch a child that never existed and fail
      // them on the first attempt's error forever. Clearing it lets the next
      // fetch try again, which is what a caller who just installed the binary
      // expects.
      if (this.child === child) this.resetChild();
    });

    // Writing to a child that just died raises EPIPE asynchronously. With no
    // listener that becomes an unhandled 'error' event on the stream and takes
    // the process down, so it has to be claimed here and turned into a
    // rejection rather than a crash.
    const onStdinError = (error: Error) => {
      if (child !== this.child) return;
      this.settleReady(new SerpAxiLadderError(`ladder-cli stdin failed: ${boundedDetail(error.message)}`));
      this.failAll(new SerpAxiLadderError(`ladder-cli stdin failed: ${boundedDetail(error.message)}`));
    };
    child.stdin?.on("error", onStdinError);
    this.stdinListener = onStdinError;

    const onStderr = (chunk: Buffer) => {
      if (child !== this.child) return;
      this.stderrTail += chunk.toString();
      if (this.stderrTail.length > 2000) this.stderrTail = this.stderrTail.slice(-2000);
    };
    child.stderr?.on("data", onStderr);
    this.stderrListener = onStderr;

    const onStdout = (chunk: Buffer) => {
      if (child !== this.child) return;
      this.buffer += chunk.toString();
      this.drainLines();
    };
    child.stdout?.on("data", onStdout);
    this.stdoutListener = onStdout;

    this.armHandshakeTimer();
  }

  /**
   * Budget the handshake. A child that spawns and then stays silent is a hang:
   * nothing else in the ladder is waiting on it, so `await this.ready` in
   * dispatch would never settle and every fetch, present and future, would sit
   * in the queue forever on a client that looks healthy.
   */
  private armHandshakeTimer(): void {
    this.clearHandshakeTimer();
    const handshakeMs = this.options.handshakeMs ?? DEFAULT_HANDSHAKE_MS;
    this.handshakeTimer = setTimeout(() => {
      if (this.readySettled) return;
      const tail = this.stderrTail.trim().split("\n").slice(-5).join("\n");
      this.detachStreams(this.child);
      this.child?.kill();
      this.settleReady(
        new SerpAxiLadderError(
          `ladder-cli printed no ready line within ${handshakeMs} ms${tail ? `: ${tail}` : ""}`,
        ),
      );
    }, handshakeMs);
    this.handshakeTimer.unref?.();
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
        // Only a ready-shaped line is judged. Anything else before the handshake
        // completes is startup output (a venv banner, a deprecation warning, a
        // blank line) and is skipped rather than treated as corruption, per
        // 04-tdd 1.1. Nothing is at risk in waiting, because the handshake
        // timer is the only thing standing between a silent child and a hang.
        if (isRecord(hello) && hello.ready === true) {
          if (hello.protocol !== LADDER_PROTOCOL) {
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
    this.clearHandshakeTimer();
    this.failAll(new SerpAxiLadderError("ladder client is closed"));
    const child = this.child;
    this.child = null;
    this.detachStreams(child);
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

/**
 * One client, one fetch, then closed. The axes are required rather than
 * defaulted: a default of `resolveLadderAxes({})` reads no environment and no
 * config, so a caller that omitted them would silently send an all-defaults
 * request while believing they had configured the ladder. There is exactly one
 * shipped caller and it always resolves them.
 */
export async function fetchViaLadder(
  url: string,
  options: LadderClientOptions,
  axes: LadderAxes,
): Promise<LadderResponse> {
  const client = new LadderClient(options);
  try {
    return await client.fetch(url, axes);
  } finally {
    await client.close();
  }
}
