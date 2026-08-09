export type SerperAxiErrorKind = "usage" | "runtime";

export class SerperAxiError extends Error {
  readonly kind: SerperAxiErrorKind;
  readonly help: string;

  constructor(message: string, kind: SerperAxiErrorKind, help: string) {
    super(message);
    this.name = "SerperAxiError";
    this.kind = kind;
    this.help = help;
  }
}

export function exitCodeForError(error: unknown): number {
  if (error instanceof SerperAxiError) {
    return error.kind === "usage" ? 2 : 1;
  }
  return 1;
}
