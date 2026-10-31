export function liveSkip(optIn: string, credential: string | boolean | undefined): boolean {
  return process.env[optIn] !== "1" || !credential;
}
