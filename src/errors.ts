export type SerpAxiErrorKind = "usage" | "runtime";

export class SerpAxiError extends Error {
  readonly kind: SerpAxiErrorKind;
  readonly help: string;
  readonly details?: Record<string, unknown>;

  constructor(message: string, kind: SerpAxiErrorKind, help: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "SerpAxiError";
    this.kind = kind;
    this.help = help;
    this.details = details;
  }
}

export function exitCodeForError(error: unknown): number {
  if (error instanceof SerpAxiError) {
    return error.kind === "usage" ? 2 : 1;
  }
  return 1;
}

const MAX_ERROR_DETAIL = 200;

/** Clamp an upstream error body so it stays readable in a one-line error. */
export function boundedDetail(message: string): string {
  return message.length > MAX_ERROR_DETAIL ? `${message.slice(0, MAX_ERROR_DETAIL)}...` : message;
}
