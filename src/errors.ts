export type SerpAxiErrorKind = "usage" | "runtime";

export class SerpAxiError extends Error {
  readonly kind: SerpAxiErrorKind;
  readonly help: string;

  constructor(message: string, kind: SerpAxiErrorKind, help: string) {
    super(message);
    this.name = "SerpAxiError";
    this.kind = kind;
    this.help = help;
  }
}

export function exitCodeForError(error: unknown): number {
  if (error instanceof SerpAxiError) {
    return error.kind === "usage" ? 2 : 1;
  }
  return 1;
}
