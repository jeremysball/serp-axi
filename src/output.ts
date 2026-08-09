import { encode } from "@toon-format/toon";

export type AxiOutput = Record<string, unknown>;

export function encodeOutput(output: AxiOutput): string {
  const text = encode(output);
  return text.endsWith("\n") ? text : `${text}\n`;
}

export function collapseHomeDirectory(path: string, homeDir: string): string {
  if (homeDir.length > 0 && path.startsWith(homeDir)) {
    return `~${path.slice(homeDir.length)}`;
  }
  return path;
}

export interface Truncated {
  text: string;
  truncated: boolean;
  totalChars: number;
}

export function truncate(text: string, limit: number): Truncated {
  const totalChars = text.length;
  if (totalChars <= limit) {
    return { text, truncated: false, totalChars };
  }
  return { text: text.slice(0, limit), truncated: true, totalChars };
}
