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

const isHighSurrogate = (unit: number): boolean => unit >= 0xd800 && unit <= 0xdbff;
const isLowSurrogate = (unit: number): boolean => unit >= 0xdc00 && unit <= 0xdfff;

/**
 * Cuts `text` to `limit` UTF-16 code units. A cut that would land between the two
 * halves of a surrogate pair (an emoji, say) backs up one unit, so the result
 * never ends in half a character; it can then be one unit shorter than `limit`,
 * and empty when the pair is the first character and the limit is 1.
 * `totalChars` is the length in the same units.
 */
export function truncate(text: string, limit: number): Truncated {
  const totalChars = text.length;
  if (totalChars <= limit) {
    return { text, truncated: false, totalChars };
  }
  const splitsPair = limit > 0 && isHighSurrogate(text.charCodeAt(limit - 1)) && isLowSurrogate(text.charCodeAt(limit));
  return { text: text.slice(0, splitsPair ? limit - 1 : limit), truncated: true, totalChars };
}
