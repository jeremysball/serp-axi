import { spawn, type ChildProcess } from "node:child_process";

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
  return {
    verdict: body.verdict,
    rungReached: typeof body.rungReached === "number" ? body.rungReached : 0,
    title: typeof body.title === "string" ? body.title : "",
    text: typeof body.text === "string" ? body.text : "",
    engines: Array.isArray(body.engines) ? body.engines.filter((e): e is string => typeof e === "string") : [],
    elapsedMs: typeof body.elapsedMs === "number" ? body.elapsedMs : 0,
    warning: typeof body.warning === "string" ? body.warning : null,
  };
}

interface Pending {
  url: string;
  resolve: (response: LadderResponse) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
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

  async fetch(url: string): Promise<LadderResponse> {
    if (this.closed) {
      throw new SerpAxiLadderError("ladder client is closed");
    }
    this.ensureSpawned();
    return new Promise<LadderResponse>((resolve, reject) => {
      const timeoutMs = this.options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
      const pending: Pending = { url, resolve, reject, timer: undefined as unknown as NodeJS.Timeout };
      pending.timer = setTimeout(() => {
        this.dropPending(pending, new SerpAxiLadderError(`ladder-cli timed out after ${timeoutMs} ms for ${url}`));
      }, timeoutMs);
      this.queue.push(pending);
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
      this.armIdleTimer();
      void this.dispatch();
    }
  }

  private async dispatch(): Promise<void> {
    try {
      await this.ready;
    } catch (error) {
      this.failAll(error instanceof Error ? error : new SerpAxiLadderError(String(error)));
      return;
    }
    if (this.closed || this.inFlight !== null) return;
    const pending = this.queue.shift();
    if (!pending) return;
    this.inFlight = pending;
    this.clearIdleTimer();
    try {
      this.child?.stdin?.write(`${JSON.stringify({ url: pending.url })}\n`);
    } catch (error) {
      this.inFlight = null;
      clearTimeout(pending.timer);
      pending.reject(error instanceof Error ? error : new SerpAxiLadderError(String(error)));
      this.armIdleTimer();
      void this.dispatch();
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
        this.didExit = true;
        resolve(code);
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
        if (this.closed) this.child = null;
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

export async function fetchViaLadder(url: string, options: LadderClientOptions): Promise<LadderResponse> {
  const client = new LadderClient(options);
  try {
    return await client.fetch(url);
  } finally {
    await client.close();
  }
}
