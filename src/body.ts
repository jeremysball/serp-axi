import { SerpAxiError, boundedDetail } from "./errors.ts";

/**
 * The only module in `src/` that reads a response body. Everything else goes
 * through `readBodyText` or `readErrorBody`, and `.ast-grep/rules/` fails the
 * build on a body read anywhere else. The belief behind that rule: no network
 * response is read into memory without a byte bound.
 *
 * The bound is on decoded bytes. `fetch` undoes gzip and brotli before the body
 * stream hands anything over, so a small compressed bomb counts at its expanded
 * size here, which is the size that costs memory.
 */

/**
 * The largest response any provider call reads, in bytes, unless the flag, env
 * var or config key says otherwise. Search replies are well under a megabyte; the
 * room is for Bright Data scrapes, whose records carry the page's raw HTML next to
 * its text, several pages to a response.
 */
export const DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024;

/** The three homes of the cap. `response-limit.ts` parses them; the overflow error names them. */
export const MAX_RESPONSE_BYTES_FLAG = "--max-response-bytes";
export const MAX_RESPONSE_BYTES_ENV = "SERP_AXI_MAX_RESPONSE_BYTES";
export const MAX_RESPONSE_BYTES_CONFIG_KEY = "maxResponseBytes";

/** How much of an error response is kept to explain the failure. */
export const ERROR_BODY_MAX_BYTES = 64 * 1024;

export interface BodyLimit {
  maxBytes: number;
  /** What the response came from, as the error names it: "Bright Data", "Serper". */
  source: string;
}

function overflow(limit: BodyLimit, how: string): SerpAxiError {
  return new SerpAxiError(
    `${limit.source} response is larger than the ${limit.maxBytes} bytes serp-axi will read (${how})`,
    "runtime",
    `raise the cap with ${MAX_RESPONSE_BYTES_FLAG} <n>, ${MAX_RESPONSE_BYTES_ENV}=<n>, or "${MAX_RESPONSE_BYTES_CONFIG_KEY}": <n> in the config file; ` +
      "a body that is cut off cannot be parsed, so serp-axi stops instead of using part of it",
  );
}

/**
 * The body stream failed partway: a reset connection, an abort, a timeout that
 * fired while the body was still arriving. It is a `SerpAxiError`, so a provider
 * that does not look at it still reports a one-line runtime error instead of a
 * raw `TypeError: terminated`. `timedOut` is true when the stream raised a
 * `TimeoutError` or `AbortError`, so a caller that owns a timeout budget can say
 * "timed out after N ms" in its own words; `cause` keeps the stream's own error.
 */
export class BodyReadError extends SerpAxiError {
  readonly timedOut: boolean;
  override readonly cause: unknown;

  constructor(limit: BodyLimit, cause: unknown) {
    const name = cause instanceof Error ? cause.name : "";
    const message = cause instanceof Error ? cause.message : String(cause);
    super(
      `network error reading ${limit.source} response: ${boundedDetail(message)}`,
      "runtime",
      "the server interrupted the transfer; retry",
    );
    this.name = "BodyReadError";
    this.timedOut = name === "TimeoutError" || name === "AbortError";
    this.cause = cause;
  }
}

/**
 * Reads a whole response body as UTF-8, or throws a `SerpAxiError` naming the cap
 * when the body is bigger than `limit.maxBytes`. There is no partial result: a
 * cut-off JSON document does not parse, and a cut-off page would look complete.
 *
 * A declared `content-length` over the cap is refused before a byte is read. The
 * header is only a hint, so the read counts bytes either way and hangs up the
 * moment the count passes the cap.
 *
 * A stream failure (a reset connection, an abort) throws a `BodyReadError`, which
 * carries the stream's own error as `cause` and says whether it was a timeout.
 * What was read before the failure is dropped: half a document is not a result.
 */
export async function readBodyText(response: Response, limit: BodyLimit): Promise<string> {
  const declared = Number(response.headers.get("content-length"));
  const body = response.body;
  if (Number.isFinite(declared) && declared > limit.maxBytes) {
    await body?.cancel().catch(ignoreCancelFailure);
    throw overflow(limit, `the server declared ${declared}`);
  }
  if (body === null) return "";

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parts: string[] = [];
  let total = 0;
  for (;;) {
    let chunk: Awaited<ReturnType<typeof reader.read>>;
    try {
      chunk = await reader.read();
    } catch (cause) {
      throw new BodyReadError(limit, cause);
    }
    const { done, value } = chunk;
    if (done) break;
    total += value.byteLength;
    if (total > limit.maxBytes) {
      await reader.cancel().catch(ignoreCancelFailure);
      throw overflow(limit, "the body kept going");
    }
    parts.push(decoder.decode(value, { stream: true }));
  }
  parts.push(decoder.decode());
  return parts.join("");
}

/**
 * The start of an error response, for the line that explains a failed request.
 * Keeps at most `maxBytes` and hangs up on the rest; a long error page is cut,
 * not refused, because the status code already says what went wrong.
 *
 * It never throws. When the body cannot be read it returns a sentence saying so
 * and why, so the message that carries it does not read as "the server said
 * nothing".
 */
export async function readErrorBody(response: Response, maxBytes: number = ERROR_BODY_MAX_BYTES): Promise<string> {
  const body = response.body;
  if (body === null) return "";
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let text = "";
  let kept = 0;
  try {
    while (kept < maxBytes) {
      const { done, value } = await reader.read();
      if (done) break;
      const room = maxBytes - kept;
      const slice = value.byteLength > room ? value.subarray(0, room) : value;
      kept += slice.byteLength;
      text += decoder.decode(slice, { stream: true });
    }
    text += decoder.decode();
    await reader.cancel().catch(ignoreCancelFailure);
    return text;
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause);
    return `(the response body could not be read: ${reason})`;
  }
}

// Hanging up on a body is best effort. The caller is already reporting why it
// stopped, and a cancel that fails changes nothing about that report.
function ignoreCancelFailure(): void {}
